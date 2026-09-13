# D-102 Web Foundation — production approval package

状態: **Accepted / Conditional GO、production適用前**。2026-09-13。
承認基準1636f18。token取得後のgrant validationをrevokeのfinally内へ移し、WebSessionsだけDESTROYへ限定是正する。full validation/CI成功・live diffが承認範囲内なら追加gateなくreleaseする。
基準HEADはD-101 `89fb8ec`。Web Foundationだけを扱い、current sequenceを維持する。

## 推奨構成と比較

**既存dev AWS account/regionを候補とする専用HTTP API + Web Lambda + Auth Lambda + 短期session table**を推奨する。
小さいguideの生成物はLambda assetに同梱し、同一originで配信する。最初は生成されたexecute-api HTTPS URLを使用する案。
既存dev AWS/ap-northeast-1、専用Web stack、生成HTTPS URL、月$3増分目安をユーザー承認済み。custom domain/DNS/ACMと既存Budget変更は対象外。

| 案 | component / state接続 | secret / trust / 開発とrollback | 判断 |
|---|---|---|---|
| AWS CDN型 | S3 + CloudFront + HTTP API + 2 Lambda + session table | OAC、cache behavior、private経路のcache無効化、asset deployを追加。IAM roleでCP GetItem。CDKで再現、CDN invalidationが必要 | 配信規模には適するが初版では部品が多い |
| **AWS小規模型（推奨）** | HTTP API + 2 Lambda + session table。4既存CP table GetItem | Standard SecureString 2参照、既存IAM trust内。同梱assetで一つのWeb stackをrollback。ローカルPython/JS、既存CDK | 少数利用に十分。CDNは初版不要、cold start・静的requestも課金される |
| Workers Static Assets + Worker auth + AWS read API | static配信は効率的。AWS側API/Lambdaは残る | CF secret/session保存、AWS側が信頼する署名鍵/検証・失効とcross-cloud障害点が増える。長期AWS access keyは置かない。WranglerとCDKの二系統 | 無料配信の利点より新しい認証境界が重い |
| WorkersでAWSへ直接アクセス | GetItemだけでもAWS credential/trustが必要 | 長期access keyまたは新規短期credential brokerが必要 | 第一候補から除外 |
| Lambda Function URL | HTTP APIを省ける | 無認証URLへの公開、route単位throttlingや将来API接続の運用を別途検討 | HTTP APIの小さい従量費より明示的route/throttle境界を優先 |

Cloudflareは新規static/full-stackにはPagesよりWorkersを推奨している。
D-100のPages Direct Uploadは**historical candidate**で、現推奨ではない。
[Cloudflare公式推奨](https://developers.cloudflare.com/workers/best-practices/workers-best-practices/)、
[Static Assets](https://developers.cloudflare.com/workers/static-assets/)、
[Workers料金](https://developers.cloudflare.com/workers/platform/pricing/)を2026-09-13確認。

## Trust boundary / URL

```text
Browser ─ HTTPS ─ dedicated HTTP API
  /, /games/..., /commands/..., /join/, /help/ → Web Lambda static allowlist (public)
  /manage/ (+ /manage/index.html) → session認証 → HTML shell
  /api/status → session認証 → CP保存値の小さい投影
  /auth/login|callback|logout → Auth Lambda → Discord OAuth + session table
Web Lambda → GetItem only → SystemState / RuntimeHeartbeats / Games / Operations
Auth Lambda → Get/Put/Delete only → WebSessions (Control Plane tableへの権限なし)
```

public guideは**ログイン不要で一般公開可、接続先FQDN・招待URLは掲載しない**というユーザー判断を採用済み。
本文/13ページ/build allowlistはD-100のまま。統合bundleだけ共通navへ「管理」を足す。
privateな状態、人数、履歴、実行者、AWS/Discord ID、secret、production証跡をpublic bundleへ混ぜない。
command例の既承認公開Game選択文字列はD-100の公開allowlistを維持する。DB内部identityの自動公開ではない。
新Gameの公開掲載は明示登録が必要。Web statusは選択/観測されたGameをIDでGetItemし、2 Game固定ではない。

候補URLは初版 `https://<generated-api-id>.execute-api.ap-northeast-1.amazonaws.com`。
custom domainは `web-dev.wishicraft.net`（dev候補）、実用名は `play.wishicraft.net` / `www.wishicraft.net`。
Minecraft DNSを流用しない。今回のCDKにはdomain/ACM/Route53 resourceを含めない。
採用時は同region ACM証明書 + Regional API custom domain + API mapping + DNSを後続reviewする。
Origin/callbackを変更する際は固定登録URI・Lambda設定・既存sessionを一括更新する。
[HTTP API custom domain公式](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-custom-domain-names.html)。

## OAuth / authorization / session

- Discord Authorization Code Grant、scopeは`identify guilds.members.read`だけ。
- `/users/@me`と、**stage canonical Guildだけ**の`/users/@me/guilds/{guild_id}/member`をuser tokenで読む。
  同user identity、member存在、membership screening完了、player/admin roleのいずれかが必要。
  Discord loginだけでは許可しない。Guild一覧・email・connections・bot scopeは要求しない。
- Discord署名commandとWebで`authorization.role_authorized`を共有。IDは同じstage設定からCDK配布。
  Web専用手入力role policyはない。Player/Adminへ同一投影。channel条件はHTTP画面には適用しない。
- stateは暗号学的random 256 bit。署名済み`__Host-`cookieと一致を必須とし、5分期限。
  server側DynamoDB `DeleteItem ReturnValues=ALL_OLD`で一回だけ消費してからcode交換する。replayは拒否。
- redirect URIはdeploy outputのorigin + `/auth/callback`をauthorize/token交換とも使用。
  request Host、returnTo、任意redirectを採用しない。upstream redirect自体も追従しない。
- callback取得token/refresh tokenは保存しない。non-empty access token取得後はgrant validation/identity/member/認可の成否によらずbounded revokeを一回試みる。tokenなしはrevokeしない。validation/revoke失敗時はsessionを発行しない。
  外部呼出しはbounded timeout、raw upstream errorは表示/logしない。
- sessionは256 bit opaque handle + HMAC-SHA256署名。`Secure; HttpOnly; SameSite=Lax; Path=/`、Domainなし、15分固定期限。
  DynamoDB consistent GetItemで毎回期限/policy fingerprint確認。TTL削除を失効判定に使わない。
  current sessionの再login時は旧handleを削除。logoutはsame-origin POST、server record削除後cookie削除。
  役割剥奪/Guild脱退の反映は最大15分。継続refreshはなく再OAuthが必要。policy設定変更はfingerprintで即拒否。
  signing key rotationは次requestから全session/state無効（secret cacheなし）。
- session tableはuser ID/role一覧/tokenを保存しない。次write sliceではactor attribution、CSRF token、操作毎の再認可を追加する。
  opaque server sessionなので拡張可能だが、read-only承認をwriteへ拡張しない。
- API/HTML/auth errorは`no-store`、CSP、nosniff、frame拒否。callbackは`no-referrer`、manageだけ`same-origin`でlogout Originを保持。
  API CORSなし。API Gateway access logを作らず、Lambdaはevent/query/header/body/secretをlogしない。

公式契約: [OAuth2](https://docs.discord.com/developers/topics/oauth2)、
[Current User Guild Member](https://docs.discord.com/developers/resources/user#get-current-user-guild-member)。
既存bot tokenを新Lambdaへ複製する案はscope削減以上にsecret権限境界を増やすため採らない。

## Read projection schema（schema_version: 1）

`GET /api/status`。sessionなし401、auth基盤失敗503、部分read失敗は200/quality=partial。
CPの正本をrepairせず、STATUS Operation、Reconcile invoke、SSM、heartbeat/Desired/Game/Operation writeは0。

| field | 型 / 意味 |
|---|---|
| generated_at / poll_after_seconds | UTC取得時刻 / 60。観測時刻ではない |
| quality / issues | complete・partial / 固定の安全な欠測code一覧。raw errorなし |
| desired_state | canonical Desired enum、判定不能unknown |
| selected_game / observed_game | `{name: string|null, state: known|unknown}`。Games display_nameだけ、内部IDなし |
| observed_state / runtime_state | 保存済みhost/HostRuntime enum。現在と断定せず観測鮮度と併記 |
| health / last_observed_health | 鮮度・欠測・遷移でUNKNOWNへ縮退する表示 / 最終観測時のcanonical Health（再判定しない） |
| discrepancy / game_mismatch | boolean|null。raw discrepancy/resource detailは返さない |
| observation | `{at: UTC|null, freshness: fresh|stale|unknown}`。stageの10分閾値 |
| heartbeat | `{at, freshness, expected: boolean|null, identity_matches: boolean}`。5分閾値、未来時刻unknown |
| protocol | ready・not-ready・unknown・not_expected |
| players | `{state: known|unknown|not_expected, count: integer|null, at: UTC|null}`。known時だけcount |
| current_operation | null、またはtype/status、safe主要progress、updated_at/freshness、terminal、固定milestonesのlabel/at |
| operation_pending | current参照あり。読取失敗で「操作なし」に変換しない |

読取はSystemState→heartbeat→選択/観測Game（最大2件）→current Operation（最大1件）→SystemState再確認。
通常4〜7 GetItem（session readは別）。全てConsistentRead、Scan/Query/GSI/履歴列挙なし。
SystemStateが途中で変わればpartial/人数unknown。これはtransaction snapshotではなく保存済み観測のviewである。

| 状況 | 表示 |
|---|---|
| fresh STOPPED + old heartbeat | 人数・protocolはnot_expected。古い人数を使わない。heartbeat自身の時刻/staleは残す |
| fresh RUNNING | run/process/instance/Gameの一致とheartbeat鮮度、protocol readyを確認してcount採用。0は0人 |
| START/STOP/SWITCH/RESET途中 | Desiredと観測・Operationを分離。人数unknown、health UNKNOWN |
| Reconcile遅延/未来時刻 | 観測stale/unknown、人数unknown、health UNKNOWN |
| heartbeat stale / protocol unknown | 人数unknown。healthyへ補完しない |
| Game不一致 | selectedとobservedの名前を別表示、不一致あり。選択値から実Gameを推測しない |
| terminal Operationのcurrent残存 | terminalであることとcurrent参照の更新待ちを表示。repairしない |
| current解除済み | Operationなし。履歴から最新terminalを検索しない |
| optional Game/heartbeat/read failure | partialと欠測を明示。全ページ500を避ける。基礎情報なしならunknown |
| browser API failure | 過去カードを消し、現在不明。重複requestはin-flight一件、background polling停止、再表示でrefresh |

実行者名・raw error・run ID・instance/volume/snapshot/lease/SSM/Discord IDは今回のprojectionに含めない。

## Infrastructure / IAM diff

独立`WishicraftWebStack-dev`。既存Control Plane/Target/Frozen stackはdeploy対象にしない。共有role helperを含むsource asset hashは既存Control Planeのsynthでも変わるが、既存stackのdeployは今回の計画に含めない。
新規: HTTP API 1、default stage、3 routes/integrations、Lambda 2、IAM roles/policies、14日log groups 2、
session table 1（on-demand/encrypted/TTL/DESTROY）、Lambda Errors alarms 2。既存secret名参照2（secret作成なし）。
CDK asset bucketは既存bootstrapを利用する。Web公開用S3 bucket/CloudFront/NAT/VPC/Route53/ACMなし。

Web role: CPの4 tableへGetItemだけ。SystemState/heartbeatはLeadingKeys=canonical system。
session tableへGetItemだけ。signing Parameter一件GetParameter。
Auth role: session table Get/Put/Delete、signing/OAuth ParameterだけGetParameter。CP read/write権限なし。
AWS managed SecureString keyを前提とし、custom KMS keyを推測追加しない。
Lambda invocation権限は専用APIからのみ。OAuth client secretをWeb read Lambdaへ渡さない。
HTTP API default throttle 5 req/sec、burst 10。予約concurrency・常時課金resourceは追加しない。
エラー応答はアプリ境界で縮退するためLambda Errorsだけでauth/read failureを網羅しない。
release E2Eでエラーpath確認し、実運用metrics/SNS通知拡張は費用と必要性で追加する。

## 費用（増分USD、税/為替/既存Minecraft費を除く）

前提例: 10人が毎日30分、1分poll → 9,000 status/月。static/auth合わせて約20,000 HTTP request/月、
Lambda 256MiB平均200ms（OAuth時は長め）、status/session合計約7万GetItem/月、1 record <=4KiBを仮置き。
HTTP API約$0.02〜0.03、Lambda request+compute約$0.02、Dynamo read/write/storageは数cent規模、
少量転送/log込みで**月$0.10〜1程度の計画見積、承認候補上限$3/月の増分目安**。
実record size/アクセスで変動。上限は課金のhard capではない。未使用の既存無料枠を仮定しなくても小さい構成を選ぶ。

HTTP API料金はregion/volume依存、Lambdaは$0.20/百万request + GB秒課金、Standard Parameter Storeは標準throughputで追加料金なし。
[API Gateway料金](https://aws.amazon.com/api-gateway/pricing/)、[Lambda料金](https://aws.amazon.com/lambda/pricing/)、
[DynamoDB料金](https://aws.amazon.com/dynamodb/pricing/)、[Parameter Store料金](https://aws.amazon.com/systems-manager/pricing/)。
既存accountのfree tier/credits残量は未確認で、無料を保証しない。
Workers static assetsは無料・無制限request、dynamic Freeは10万request/日・CPU上限あり、Paidは最低$5/月。
AWS側API費とsession/trustの追加実装は残る。[Workers料金](https://developers.cloudflare.com/workers/platform/pricing/)。
CloudFrontはFree/$15/$200等のflat-rate planもあるが、配信を無料とするためだけにcomponentを追加しない。
[CloudFront料金](https://aws.amazon.com/cloudfront/pricing/)。custom domain登録料・DNS費は今回見積外、選択後に確定する。

## Local / validation / release

[release runbook](../runbooks/web_foundation.md)を参照。ローカルfixtureは実認証の保証ではない。
実OAuth/production E2E、live stack diff、AWS preflightの適用状況はrunbookへ記録する。条件成立後に承認済みrelease順序で実行し、secret非echo入力とPortal登録だけ人間へ依頼する。
repository test・実ブラウザ・CI結果は同runbookのcloseoutへ記載する。

WebSessionsは15分の認証補助記録で業務/監査正本ではない。stack削除/置換でDeleteし、再作成後は全員再loginとする。TTLはcleanup専用。Backup provenance等のdurable tableとlogのRetainは変更しない。
