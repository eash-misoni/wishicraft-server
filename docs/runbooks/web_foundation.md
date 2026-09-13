# Web Foundation release / rollback runbook

D-102 Proposed。通常repository作業とproduction承認を分離する。
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

## 承認対象となる一括release計画（まだ実行禁止）

1. 人間がhosting account=既存dev AWS、service=専用HTTP API/Lambda、生成HTTPS URL、費用目安を承認する。
   新account/projectの作成は不要という案。Minecraft Target、既存Control Plane、Discord command設定はdeploy対象外。
2. operatorがcanonical `wishicraft-dev` sessionへlogin。STS Account/Regionをstage YAMLと照合。
   mismatch/期限切れは停止。IAM追加で迂回しない。
3. finalized commitをcheckoutし、local checks/CI成功、専用Web assemblyを新temporary rootにsynthする。
   `tools/dev-env run -- npx --no-install cdk synth WishicraftWebStack-dev --context stage=dev --context phase=8 --context deployment=web --output "$WEB_RELEASE_ROOT/assembly"`
   `$WEB_RELEASE_ROOT`は毎回mktempで作る。既存assemblyを上書きしない。
4. `cdk diff --change-set=false`（同context/profile/output）で新Web stackだけをreview。
   existing CP/Target/Frozen resource置換、未知IAM/secret/DNS/SG差分は停止。
   session table Retain、CP GetItem only、secret path 2件、実handler environmentとの一致を照合する。
5. 人間がDiscord Developer Portalで既存stage ApplicationのOAuth client secretを安全なoperator経路から確認する。
   値をチャット/引数/env/logに入れず、SecureString `/wishicraft/dev/secret/discord-oauth-client-secret`へ非echo入力で登録。
   cryptographic random 32 bytes以上のsigning secretも `/wishicraft/dev/secret/web-session-signing-key`へ同様に登録。
   存在済みなら勝手にoverwrite/rotateせずmetadataと所有者確認。Codexへ値を渡さない。
6. 承認済みWeb stackだけdeploy（`--all`禁止）。**この時点でpublic guideが公開される**。
   Authはredirect未登録の間fail closed。公開とOAuth登録を不可分に見せない。
7. output `OAuthRedirectUri`をPortalへ完全一致登録。URL/secretを手入力の第二role policyにしない。
   選択案ではDNS/TLS変更なし。custom domainを選ぶ場合は追加diff/費用を具体化してから同承認範囲へ含める。
8. 下記E2E後、人間がrole/session 15分失効境界を確認してrelease closeout。

まだ実行しない操作: AWS resource作成/deploy、secret取得/保存、Portal変更、URL登録、DNS/TLS、
Lambda直接invoke・productionテスト、Discord/Guild変更。repository commit/push/CIは許可済み。

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
残すsession table/logはRetain。初回に「以前のWeb stack」があるとは扱わない。
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
