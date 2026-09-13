# Web Foundation release / rollback runbook

D-102 Accepted。2026-09-13ユーザーConditional GO（基準1636f18）。revoke境界・WebSessionsだけDESTROYへ是正後、full validation/CI成功とlive diff条件に基づき、下記read-only releaseを追加確認なしで進める。実適用完了とは区別する。
設計・schema・費用・trust boundaryは[review](../reviews/web_foundation.md)。

## ローカル表示

```sh
tools/dev-env check
tools/dev-env run -- uv run python -m web.local --scenario stopped
# http://127.0.0.1:8765/ → 管理 → Discordでログイン（LOCAL MOCK）
# --scenario running|players|stale|unknown|transition
```

loopbackだけbind。毎回新しいtemporary root、fake session/keyはprocess memory、実credential不要。
本番bundleに`web/local.py`/MemoryStore/FakeOAuthを含めない。production環境変数でfakeを有効にする入口なし。
実ブラウザ検証: `tools/dev-env run -- node web/foundation-browser.mjs --chrome`。
CIは同scriptをbundled Chromiumで実行。画像/result.jsonを各invocationのtemporary rootへ保存する。

## 承認済みの一括release計画

1. hosting account=既存dev AWS/ap-northeast-1、専用HTTP API/Lambda、生成HTTPS URL、増分月$3目安は承認済み。
   新account/projectの作成は不要という案。Minecraft Target、既存Control Plane、Discord command設定はdeploy対象外。
2. operatorがcanonical `wishicraft-dev` sessionへlogin。STS Account/Regionをstage YAMLと照合。
   mismatch/期限切れは停止。IAM追加で迂回しない。
3. finalized commitをcheckoutし、local checks/CI成功、専用Web assemblyを新temporary rootにsynthする。
   `tools/dev-env run -- npx --no-install cdk synth WishicraftWebStack-dev --context stage=dev --context phase=8 --context deployment=web --output "$WEB_RELEASE_ROOT/assembly"`
   `$WEB_RELEASE_ROOT`は毎回mktempで作る。既存assemblyを上書きしない。
4. `cdk diff --change-set=false`（同context/profile/output）で新Web stackだけをreview。
   existing CP/Target/Frozen resource置換、未知IAM/secret/DNS/SG差分は停止。
   session table DeletionPolicy/UpdateReplacePolicy=Delete、CP GetItem only、secret path 2件、実handler environmentとの一致を照合する。
5. 人間がDiscord Developer Portalで既存stage ApplicationのOAuth client secretを安全なoperator経路から確認する。
   値をチャット/引数/env/logに入れず、SecureString `/wishicraft/dev/secret/discord-oauth-client-secret`へ非echo入力で登録。
   cryptographic random 32 bytes以上のsigning secretも `/wishicraft/dev/secret/web-session-signing-key`へ同様に登録。
   存在済みなら勝手にoverwrite/rotateせずmetadataと所有者確認。Codexへ値を渡さない。
6. 承認済みWeb stackだけdeploy（`--all`禁止）。**この時点でpublic guideが公開される**。
   Authはredirect未登録の間fail closed。公開とOAuth登録を不可分に見せない。
7. output `OAuthRedirectUri`をPortalへ完全一致登録。URL/secretを手入力の第二role policyにしない。
   今回はDNS/TLS/ACM変更なし。custom domainは安定後の別slice。
8. 下記E2E後、人間がrole/session 15分失効境界を確認してrelease closeout。

承認済み: 専用Web stack deploy、exact secret 2件の初回登録（overwrite禁止）、generated URLのOAuth登録、read-only E2E。Portal操作とsecret入力は人間が行う。禁止: custom domain/DNS/ACM、既存CP/Target/Frozen変更、Minecraft起動、Guild/role変更、bot token変更・複製、Web write操作。

## production E2E計画

- 未loginで13 publicページ・Game/commandリンク・コピー、manage login、API401。FQDN/招待/状態非露出。
- 正しいGuildのPlayer/AdminでOAuth、同一status view。role不足/非member/他userは403、sessionなし。
- wrong/missing/replayed state、callback拒否、Discord拒否/429、expired/tampered cookie、logout POST/Origin mismatch。
- Secure/HttpOnly/SameSite/Path、Cache-Control/CSP/referrer、callback query/tokenがlogs/HTML/APIへ残らないこと。
- 保存済みSTOPPED projectionとheartbeat時刻、Operation件数/Desired/heartbeatがページviewで変更されないこと。
- 実host起動をE2Eへ暗黙追加しない。RUNNING/transitionのproduction確認は次の承認済み通常Operation時にread-only観測。
- 実role剥奪のためにGuildを書き換えない。既存の権限別test accountを人間が指定する。
- API failure時はUIに旧人数なし、重複pollなし、background休止、logout後API401、session expiry後再login。
- 費用/HTTP throttlingを確認。認証障害とMinecraft障害を混同しない。

## rollback / 停止条件

既存Minecraft操作・Data EBS・Control Plane recordには戻し操作をしない。
Web更新時は直前成功commitの同Web stackへ戻す。assetとhandlerは同stack releaseで揃える。
初回release障害なら公開を止めるためWeb API/Lambdaだけを無効化する承認済みoperator手順を選び、
session tableはDESTROY、logはRetain。初回に「以前のWeb stack」があるとは扱わない。
secret漏洩/認可不整合なら公開停止、signing key rotationでsession/state全失効、OAuth grant revokeを人間経路で行う。
結果不明deployはstack events/read-only statusを確認し、再作成/削除を推測実行しない。

## 次slice

Existing Operations via Web: START/STOP/SWITCH/BACKUP/RESETを既存Admissionへ接続。
operation毎のcanonical認可、actor attribution、CSRF、confirmation/idempotencyと非同期進捗を追加。
履歴一覧/接続情報/操作buttonは今回追加しない。Game Creation/Whitelist等はD-101順序を維持。

## repository validation closeout

- 全体pytest: 1,128 passed（54.67秒）。最終revoke空body互換修正はWeb境界29件で追加確認。
- Ruff lint / format、mypy（179 source files）成功。
- Web stackと現行Control Plane（二Game + RESET）のlocal synth成功。新規Web resource/IAMはreviewの一覧どおり。
- public guide実Chrome: 13ページ×3 viewport、links/copy/keyboard/再読込/build allowlist回帰成功。証跡root `wishicraft-web-browser-x44M9E`。
- 実Chrome: 6状態のguide→fake OAuth→session→JSON→UI→logout、mobile/desktop、duplicate/read failure成功。
  証跡root: `/var/folders/8l/yptb5b71055c5cqxbzn5qw300000gn/T/wishicraft-foundation-browser-B86aqo`。
- 全体初回の9 failures/47 setup errorsは既存Discord bundleのPyPI DNS/network制限。正規bundling-cache準備後に再検証。
  test追加途中のimport不足、Dynamo list decode、Chrome logout Origin問題は修正して新規rootで再検証済み。
- 実OAuth・AWS deploy・live diff・production E2Eは未実行。Docker CLIはlocal未導入、実Docker回帰はCIで確認する。
- CI runはpush後、final handoffでcommitとともに報告する。

## 人間端末でのsecret初回登録

CI/live diff/caller照合後だけ、repository rootで次を実行する。

```sh
tools/dev-env run -- uv run python -m web.register_secrets
```

stage正本Application IDのDeveloper Portal → OAuth2のClient Secretを、上の非echo promptへ直接入力する。
chat、shell引数、環境変数、履歴、ファイルに値を置かない。非TTYは拒否、既存Parameterは値を読まず保持する。
signing keyはprocess内で48 random bytesから生成して直接SecureStringへ登録し、表示しない。
PutParameterはOverwrite=false、SDK自動retryなし。結果不明なら再実行せずmetadata調査で停止する。
既存client secretをPortalで取得できずReset Secret/Regenerateが必要なら、それは人間操作として明示し、Codexは実行しない。Bot TokenのResetは行わない。

## 今回の適用checkpoint

- revoke境界とWebSessionsのみDESTROYの限定是正を実装。focused 45件、full 1,144件成功（51.24秒）。Ruff lint/format、mypy 181 source、Web synth成功。
- DeletionPolicy/UpdateReplacePolicyはWebSessions=Delete、log=Retainをsynthで固定。既存durable tableの保持回帰もfull testで成功。
- 初回full検証の3 failures/47 setup errorsはPyPI DNS制限による既存Discord bundling失敗。正規bundling-cache準備後、新rootでfull再検証成功。
- validation root: `wishicraft-web-release-tests-v2-ma8ok70o`、synth root: `wishicraft-web-release-synth-j66r084h`（local temporary directory）。
- 限定是正commit `cacb772`、CI run `34742615971`は全job成功。
- canonical caller/account/regionとdeployed Discord Application/Guild/role設定の一致を確認。secret 2件は人間端末からSecureString Version 1で初回登録済み（値は読まずmetadata確認）。
- `WishicraftWebStack-dev`初回deployはCREATE_COMPLETE。実template/IAM/Lambda environment/routes/throttle/TTLはreview済みassemblyと一致。WebSessionsはDelete/Delete。
- public 13ページ、未認証manage login/API401、invalid callback、canonical cookie tamper、no-store/CSP、公開allowlistをproduction HTTPで確認。
- deploy evidence: `wishicraft-web-deploy-46ouvzd5`、read-back: `wishicraft-web-readback-mupniy14`、public: `wishicraft-web-public-e2e-89pv6vij`、cookie: `wishicraft-web-cookie-e2e-v2-qfj5x12u`（いずれもlocal temporary root）。最初のpublic検証のcookieはunknown nameだったため、正規cookie名の改ざんを別rootで追加検証。
- 人間がexact redirectを登録した後、real OAuthでgeneric拒否を報告。release E2Eは未完了。
- HTTP adapterがPython既定User-Agentを使用していた。秘密値なしの同じDiscord `/users/@me` GETで既定UA=403、公式形式UA=401を再現。全OAuth requestへ[公式形式User-Agent](https://docs.discord.com/developers/reference#user-agent)を明示する限定修正。権限・scope・state・revoke・timeout・NoRedirectを維持。実ログイン失敗の原因確定は修正deploy後の再試行で行う。
- User-Agent修正: focused 45件、full 1,144件（52.15秒）、Ruff lint/format、mypy 181 source、Web synth成功。full初回は既存Discord bundleのPyPI DNS制限で5 failures/47 errors、正規cache準備後に新root `wishicraft-web-oauth-ua-validation-v2-1ulxnr8p`で成功。template比較の初回harnessはCDK asset metadata pathの正規化漏れで失敗し、別root `wishicraft-web-ua-template-compare-v2-srq3_45n`でLambda Code/asset metadata以外の差分なしを確認した。
