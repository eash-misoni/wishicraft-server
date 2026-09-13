# D-100 静的利用案内Webと公開準備

> D-102 release追記: 2026-09-13 Conditional GOにより既存dev AWS・generated HTTPS URLでの初回read-only公開を承認・適用済み。custom domainは対象外。限定是正/CI/live diff条件と適用状況は[Web runbook](../runbooks/web_foundation.md)を参照。


> 2026-09-13 Web Foundation追記: public guideはログイン不要で一般公開可、FQDN/招待URL除外をユーザー承認済み。以下のPages案・閲覧範囲未決はhistorical candidate/当時の記録。現推奨は[D-102 AWS小規模Web](web_foundation.md)。本文・13ページ・ローカル構成承認を維持し、hosting/URL/費用/実公開は未承認。

**状態:** 内容・ローカル構成は承認済み、公開条件は未決。D-100全体の完了やhosting採用の承認ではない。
2026-09-13のユーザーレビュー承認により、公開候補のページ・生成処理を `81f181d90412fe6d440d9866f0106a7b0ef77c8a` に固定する。追加のUI再設計・文章拡充・ページ構成変更は行わず、新たに判明した不具合だけ必要最小限で対応する。
同HEADのCI run `34737820030` は承認記録時点でQueued、成功未確認だった。最新の承認記録HEAD `39bae168813892edc6556b502ca8d7687e9135c2` のCI run `34738758175` はsuccess（2026-09-13確認）。以下の実装・ローカル検証記録を保持し、公開候補と承認記録だけを更新した文書HEADを区別する。
Web公開・hosting project作成・DNS/TLS/Access変更・自動公開の有効化・AWS/Discord/Hostへのproduction操作は未実施・未承認。閲覧者・認証・最終URL・費用上限も未決。
基準HEADは前回準備完了 `940aa0337433ec7ca268c3a5d95f656d7091bc44`。originと一致・cleanを確認して継続した。
D-099 Completed / release COMPLETED / PRODUCTION_VERIFIEDを維持し、完了E2Eは再実行しない。
前回の追加委任はGame中心の参加導線・公開Game一覧からの生成・検証。既存の外観とページ別URLを維持し、Game中心のローカル再確認を経て上記の内容承認に至った。

## Current roadmapとの関係（D-101）

内容・ローカル構成を承認済み公開候補として維持し、Web Foundationのpublic部分へつながる独立完成物とする。実公開はWeb全体のhosting / URL / Discord OAuth / authorizationと合わせて配信構成を決めるのを第一候補とする。以下のCloudflare推奨はD-100準備時の候補で、採用決定ではない。内容承認をhostingや管理Webの承認へ拡張しない。

authenticated read-only statusとwrite operationsは別release slice。WebからGameを作成してもguideへ自動掲載せず、説明/client要件を揃えた明示的公開登録を維持する。順序と承認境界は[Current roadmap](../06_delivery_plan.md#current-roadmap)を参照。

## 動くページとローカルレビュー

`web/build.py`が既存Python環境でMarkdownをHTMLへ変換する。追加は開発依存のmarkdown-it-pyとブラウザ検証用Playwrightだけ。
SPA、CMS、documentation framework、backend、database、外部font・画像・解析・埋込みはない。
生成物は13ページの`index.html`と`404.html`、`guide.css`、`guide.js`、`_headers`の計17ファイル。
宣伝的なキャッチコピーとheroを削除。無彩色背景・白い本文面・低彩度の差し色・細い境界線を基本とし、一覧とボタンだけ浅い影を付ける。
共通ナビゲーション、現在位置、親一覧へ戻るリンクと詳細のページ内目次を用意。スマートフォンでは一覧と引数表を縦に並べる。
コピーはClipboard API＋失敗時の手動選択案内。表示の折返しやfenced code末尾改行をクリップボードへ含めない。
JavaScript無効でも本文・リンク・例は読める。現在状態の表示やAPI通信はなく、`/mc status`を案内する。

| ページ | 公開用相対URL |
|---|---|
| ホーム | `/` |
| 共通の準備（補助） | `/join/` |
| Game一覧・A・B | `/games/`・`/games/a/`・`/games/b/` |
| コマンド一覧 | `/commands/` |
| status・start・stop | `/commands/status/`・`/commands/start/`・`/commands/stop/` |
| switch・backup・reset | `/commands/switch/`・`/commands/backup/`・`/commands/reset/` |
| 困ったとき | `/help/` |

各URLは独立HTMLで、直接アクセスとreloadが可能。公開domainは埋め込まず、通常の相対リンクを使う。

```sh
tools/dev-env check
tools/dev-env run -- uv sync --frozen --all-groups
tools/dev-env run -- npm ci
GUIDE_ROOT=$(mktemp -d)
tools/dev-env run -- uv run python -m web.build --output "$GUIDE_ROOT/site"
tools/dev-env run -- uv run python -m http.server 8765 --bind 127.0.0.1 --directory "$GUIDE_ROOT/site"
```

ブラウザで`http://127.0.0.1:8765/`を開く。repository rootを配信しない。
新しいbuildは別のtemporary rootを作る。既存出力への上書き・混在はbuildが拒否する。
表示確認は別terminalで次を実行できる。localは確認済みChromeがあれば`--chrome`を末尾へ付け、CIはlock済みPlaywright Chromiumを使う。

```sh
tools/dev-env run -- npx --no-install playwright --version
tools/dev-env run -- node web/browser-check.mjs "$GUIDE_ROOT/site" --chrome
```

毎回新しいtemporary rootへJSONとmobile/narrow/desktopのPNGを保存する。初回harnessのskip linkクリック失敗も旧rootへ保持し、成功結果へ書換えない。

## 正本と更新

| 項目 | 正本・更新方法 |
|---|---|
| 説明・操作例・権限表示・注意 | `docs/user-guide/`のページ原稿、Game紹介原稿、共通原稿が各説明の編集元。旧`docs/discord_user_guide.md`は入口と正本参照を保持。HTMLへ再入力しない |
| Game ID/名称・runtime版・Reset数値 | project/dev stage、two-game/reset宣言、既存のpure `two_game_admin.declaration`から必要fieldだけ投影 |
| 引数の型・必須性・候補 | 基本schema＋既存D-097/D-098のcommand拡張をそのまま使用 |
| 権限・例の整合 | testsが各例を合成Interactionとして現行`parse_and_authorize`へ渡し、Player/Admin/roleなし・別Guild/channel/applicationを検査。実Discord通信なし |
| 現行の意味 | D-097/098/099、BackupObservation。古い管理者限定Reset表や毎回Snapshot/Reset後停止案を復活させない |
| 管理手順・実証 | 既存runbook/evidenceをrepositoryに保持し、Webへ出さない |

原稿のfrontmatterとMarkdownを編集する。`{{examples}}`・`{{arguments}}`はschema、`{{supported-games}}`は公開Gameのcapabilityとpolicyから生成する。Game詳細は`games/_page.md`の共通構成へ紹介原稿・参加要件・操作例を展開する。
`--update-guide`による旧Markdown生成ブロック更新は廃止。buildとfocused testsを実行し、設定/schema変更では本文の意味もレビューする。未知token・commandページ不足を拒否する。未知runtime種別ではedition/client説明の見直しを要求し、勝手に対応を拡張しない。
Game登録の宣言関数はローカル純粋処理だけを使用し、register/mainやAWS clientは呼ばない。宣言内のwhitelist等を一括serializeしない。
新しい機械値と説明の意味の一致は生成だけで保証できないため、schema変更時も人間の内容レビューを残す。

## Game中心の導線と公開登録

ホームではGame一覧を最初の入口にする。一覧から対象Gameを選ぶと、edition/version・clientのloader/MODパック・準備、申請、status、対象指定START/管理者SWITCH、接続の順で確認できる。
共通接続先なので、何かのGameがREADYではなく参加したいGameの選択/観測と稼働を確認する。共通申請と個別接続案内は`shared/access.md`・`shared/connection.md`をGame詳細と`/join/`で再利用する。FQDN・招待URLは出力しない。

公開Gameを追加するWeb側の編集は`web/games.yaml`のID/slug/clientと`docs/user-guide/games/<slug>.md`の紹介・注意。共通テンプレート、navigation、route/出力allowlistのコードへGame別分岐を追加しない。
名称・正式引数・edition/version/server・Reset capability/policyは`web/canonical.py`が既存正本から解決し、`web/build.py`はIDをkeyに公開登録と結合する。件数・配列位置・共通version・単一Reset policyへ依存しない。
現行canonical adapterは既存のinitial/secondary宣言とdefault Vanilla runtimeを投影する。backendの2Game制約は維持する。将来backendの正本形式が変わる場合、そのadapterの対応は別途必要だが、公開rendererのGame別分岐は不要。

client metadataは`confirmed_none`（追加MOD不要と確認済み）、`required`（必要構成を明示）、`unknown`（未確認）を区別し、loader・packの名称/版または不要/未確認の明示、準備文を必須にする。欠落はGame IDとfieldを示してbuild失敗、明示的な未確認は参加前の管理者確認として表示する。空欄や未知runtimeを標準clientへ補完しない。
一般command説明は対象Gameという表現へ整理し、現在の対応Game・使用例・具体的fixed seed/保持/容量を生成する。現行のReset非対応/対応、fixed seed 0、直近3個、元の保護anchorを維持する。共有BACKUPと同時稼働一つは共通契約でありGame metadataで変更できない。

テスト専用の3件目は異なるversionとloader/pack、Reset非対応を与え、追加生成、相互リンク、順序変更、必須情報欠落、未知client、slug/文字列挿入、未登録Gameの除外を検証する。fixtureはtemporary rootだけに展開し、実build・runtime・command登録へ追加しない。多runtime本番実行の証明ではない。

## 旧内容の移動と追加説明

| 旧章 | 新しい編集元・配置 |
|---|---|
| 参加の準備 | 版/clientは各Game詳細へ移動。`join.md`は共通申請・role・操作チャンネルの補足 |
| Game詳細 | `games.md`と`games/a.md`・`games/b.md`：比較は一覧、版・操作例・対応操作は詳細 |
| コマンド例と独立した引数章 | `commands.md`の短い比較と`commands/*.md`の各構文・引数・使用例へ分割 |
| Resetで変わるもの・残るもの | `commands/reset.md`へ統合。B詳細・一覧は変更範囲の短い注意から誘導 |
| 応答不明時の案内 | `help.md`と各commandの失敗時案内。新しい要求で埋め合わせない境界を維持 |

statusは選択/観測/処理中/到達記録を区別し、現行rendererに正確な観測時刻が表示されない点も明記。
startは省略時・同じGame起動済み・別Game稼働中、stopは保存からEC2停止と他参加者への影響を補足。
switchはsource/target・起動待ち・直前接続race・途中失敗時の選択を説明。
backupは共有EBS保護と復元別作業、resetはseed・変更範囲・保持・容量・cleanup・損失境界を集約した。
現行schema/parser/認可とD-097〜099・runtime/reset policyに照合し、command/backend/Game設定は変更していない。

## 公開候補と非公開境界

**公開候補:** このbuildの参加条件、Java版/version/Vanilla、A/Bの利用者向け名称とコマンド選択用Game ID、権限区分、構文・例、安全条件、Reset/保持/BACKUPの違い、失敗時の行動。
Game IDはコマンド入力に必要な明示allowlist対象であり、AWS/Discord resource IDの公開とは分ける。
現在のdev向けであることを明示し、prod対応や現時点の稼働状況を示さない。

**除外:** repository全文、runbook、production evidence、config原本、AWS account/resource ID、内部path/receipt/実Operation/lease、Discord内部ID/参加者一覧、whitelist/ops/ban実データ、個人名・実行履歴、token/secret/credential/環境変数。
接続先FQDNと招待URLは参加には必要でも公開可否が未決なので一切出力しない。管理者からの個別案内とする。
接続先を載せる場合はこのpublic範囲の変更と除外検査の明示見直しを別の公開承認へ含める。設定から自動注入する隠しswitchは作らない。

Markdown内のraw HTMLは無効、文字列はMarkdown/HTML境界でescape。リンクはallowlist内の原稿ページと存在するページ内anchorだけ許可し、画像は追加承認済みassetがない限り拒否する。
copy処理はDOMのtextContentを使い、innerHTMLやevalへ渡さない。CSPは外部通信とinline実行を禁止。
allowlist出力と禁止値検査は人間の公開レビューを補助するもので、任意の機密文章を自動分類する保証ではない。

**未決:** 誰でも閲覧か指定参加者だけか、認証方式、hosting account/所有者、最終URL、検索index、接続先/招待の将来掲載、公開後の承認不要更新範囲。
管理者情報はrepository/既存の非公開経路に残す。今回それをWebへ置くためのOAuthは導入しない。
将来のライブ状態確認・管理WebはWEB-001〜003 / Phase 13の後続判断として維持する。

## Hosting比較と推奨（2026-09-13公式資料確認）

全案ともMinecraft EC2の起動やDNS出現に依存しない。

| 候補 | 既存環境・更新 | 費用・独自domain | 閲覧制限と負担 |
|---|---|---|---|
| **Cloudflare Pages / Direct Upload（推奨）** | 新account/serviceは必要。レビュー済み17ファイルを手動upload。Git連携不要 | Functionsなしの静的requestは無料・無制限。候補`wishicraft-guide.pages.dev`、独自subdomainも可能 | Accessを別設定できるが全入口の保護確認が必要。previewだけの認証を本番保護と誤認しない |
| GitHub Pages | 既存GitHubを再利用、手動workflowへの承認gateは別途設計 | 公開repoはFreeで利用可能。独自domain対応 | private repoでもサイト非公開とは限らない。private公開はEnterprise Cloud組織等の制約があり、少人数の閲覧制限目的には重い |
| S3 private origin＋CloudFront | 既存AWS/CDKの知識・運用を再利用。専用bucket/distribution/OACが必要 | CloudFrontは月額$0 Freeのflat-rate枠も提供。S3 request/storageや対象plan条件を別途見積り | OACはorigin保護で、閲覧者認証ではない。限定公開には署名URL等の運用が増える。IAM・証明書・DNS変更範囲が大きい |

根拠: [Pages静的配信料金](https://developers.cloudflare.com/pages/functions/pricing/)、[Direct Upload](https://developers.cloudflare.com/pages/get-started/direct-upload/)、[独自domain](https://developers.cloudflare.com/pages/configuration/custom-domains/)、[Pages preview保護の範囲](https://developers.cloudflare.com/pages/configuration/preview-deployments/)、[GitHub Pages提供条件](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages)、[GitHub private公開条件](https://docs.github.com/en/enterprise-cloud@latest/pages/getting-started-with-github-pages/changing-the-visibility-of-your-github-pages-site)、[CloudFront料金](https://aws.amazon.com/cloudfront/pricing/)、[flat-rate仕様](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/flat-rate-pricing-plan.html)。

推奨理由は、静的配信費と更新手順を小さくし、既存Minecraft AWS権限・DNS lifecycleから分離できること。service採用と認証なし公開の決定は別であり、まだ採用確定しない。
Functions/Workers/KV/analyticsは追加しない。静的配信の見込増分は**月額$0**。domain登録更新費は別、既存Route 53の費用も残る。Accessが必要なら対象人数・契約と料金を承認前に再確認し、$0と断定しない。
Cloudflareのaccountと利用権限・既存契約は未確認。追加の有料planを選ぶ権限は委任されていない。

## URL・権限・必要resource

第一候補は`https://wishicraft-guide.pages.dev/`（空き未確認）。独自URL候補は`https://guide.wishicraft.net/`。
未確定のURLをHTMLへ埋め込まず、相対asset/page/anchorでrootとsubpathの両方に対応する。
独自subdomainは既存Route 53にWeb用CNAMEを一件追加する案。Pages側custom domain登録を先に行い、発行された正しいtargetを確認する。
zone/apexのnameserver移管はしない。既存Minecraftレコード・TTL・起動時UPSERT/停止時DELETEの対象を触らない。
subdomainだけならCloudflareへzone全体を移す必要はない。[公式domain手順](https://developers.cloudflare.com/pages/configuration/custom-domains/)

初回に必要な権限は選んだCloudflare accountのPages project作成・upload・deployment管理。CLI化する場合だけ対象accountのCloudflare Pages Edit tokenを安全に発行し、Git/log/引数へ残さない。今回はdashboard手動uploadが最小で、tokenやGitHub secretは不要。
独自domainを選ぶ場合だけ、対象Route 53 zoneのWebレコード限定変更とCloudflare側domain/TLS設定を追加承認する。既存AWS role/IAMを拡張しない。
限定閲覧を選ぶ場合はAccess application/policy、許可者、認証provider、費用と所有者を具体化する。非公開の案内本文を置く前に、無害な空ページで認証を検証する。
Pagesのpreview保護は本番pages.dev/custom domainを保護しない。production、branch alias、deployment固有URL、custom domainの全入口で未認証拒否/許可者成功を検証するまで案内をuploadしない。

## 初回公開・更新・差戻し（すべて未実行）

1. 一括承認でhosting account、閲覧者/認証、URL、公開する内容、費用上限、作成resourceと差戻し操作を確定する。
2. 承認したcommitを新しいrootでbuildし、tests/CIと実表示を確認。17ファイル名・size/SHA-256をローカル記録し、upload対象をレビューする。
3. 承認されたPages Direct Upload projectを作成。Git連携・自動deploy・deploy hookを設定しない。限定閲覧の場合は先に空ページと全入口のAccessを検証する。
4. dashboardから**siteディレクトリの17ファイルだけ**をupload。repository、temporary root全体、PNG、JSON検証結果を選ばない。初回upload自体がインターネット公開なので、この手順は現在実行禁止。
5. 実deployment URL、HTML/CSS/JS、HTTPS、CSP/Cache-Control/拒否応答、スマートフォン表示、コピー、未認証/認証時の境界を確認する。`_headers`は配信headerとして扱われるか実URLで検証する。
6. 独自domain承認がある場合だけ、Pagesのdomain登録と発行確認後にWeb CNAMEを追加しTLS/DNSを確認する。Minecraft DNSとの分離を差分で照合する。
7. 次回はページ別Markdown編集→build時に機械項目生成→tests/新build/表示→commit/CI→承認済み範囲で手動upload。前deployment IDとartifact hashを非公開のrelease記録へ残す。現在は通常pushで公開されない。

誤記はPagesのDeploymentsから前の成功production deploymentへRollbackし、同じURLで旧内容を確認する。preview deploymentはrollback対象にできない。[公式差戻し](https://developers.cloudflare.com/pages/configuration/rollbacks/)
初回で前deploymentがない場合は、事前レビューした「案内を準備中です」の無害な静的ページへ差し替える。
誤った内容が古いdeployment URLにも残る点に注意し、漏えい時は配信停止/Access遮断、該当deploymentの削除とcache確認を承認範囲に含める。単なるRollbackでは第三者の保存copyを取り消せない。
repositoryの修正は前進commitで行い、D-099やGame/worldを過去状態に戻さない。Web撤去時もMinecraftレコードやresourceを削除しない。

## 検証結果と未実証範囲

### 今回のGame中心導線

ローカル1099 tests、focused 32 tests、Ruff/format、mypy 170 files、dev5構成synthが成功。初期実装のGame record参照field誤りと、adapter分離時のexport不足を修正して再検証した。
仮3件目はversion 99.7、明示loader/pack、Reset非対応のWeb専用入力。canonical順と公開登録順の変更、欠落field、unknown、重複/不正slug、文字列挿入、未公開Game/fixture混入を検査した。backend多runtime対応の実証ではない。
Chrome 153.0.8010.36、320×740・390×844・1440×1000で全13ページの遷移・直接URL/reload・深いURLのCSS/JS・anchor・Tab/focus・15コピー箇所・overflowを検証。ホーム、共通準備、Game一覧、A/B詳細、各command詳細の実表示を目視した。JavaScript無効・clipboard拒否・root/subpathも確認。外部request/browser errorは0。
最終buildを新rootで再生成し、17ファイル・70,572 bytesのbyte一致を確認。[今回の証跡](../evidence/2026-09-13-user-guide-web-game-centered.json)に結果とartifact/PNG hashを記録。schema/認可と実コピー用例の合成parser検査はローカルtestであり、実Discord・Minecraft参加の検証ではない。
CSS/JavaScript、backend、Game/runtime設定、command schema/認可、infra、CI workflowを変更していない。接続先/招待URLと内部情報は引き続き除外。通常pushで公開されない。

### 前回（940aa03）の複数ページ化検証履歴

今回のローカル検証は1080 tests、focused 13 tests、Ruff/format、mypy 169 files、devの5構成synthが成功。
初回pytestとcontrol-plane系3 synthはsandboxのPyPI DNS制限で失敗し、新rootで依存取得可能な環境から再検証した。初回mypyのtest内Path/string変数衝突は修正後に成功。旧ログは上書きしない。
Chrome 153.0.8010.36で全13ページ×390×844 / 320×740 / 1440×1000の39組合せを検査。全ページの直接アクセス/reload、全リンク遷移、親一覧/相互リンク、ページ内anchor、深いURLのCSS/JS、見出し順、skip linkとTab/focus、合計15コピー箇所/各viewport、横overflowなしを確認した。
ホーム・Game一覧・B詳細・コマンド一覧・reset詳細の実画面も目視。Resetの警告・折返し・引数表・コピーを確認した。root配置と`/guide/`配下のリンク、JavaScript無効時、clipboard拒否時も検証した。外部request/browser errorは0、画像は未使用。
再buildはbyte一致、allowlist17ファイル・65,967 bytes。機密値除外、raw HTML/設定名/metadataのescape、未登録原稿除外、schema/parser/role照合はpytestによる静的/合成入力検査。実Discord操作の証明ではない。
[今回の準備証跡](../evidence/2026-09-13-user-guide-web-design.json)に出力とPNG hashを記録した。PNG本体・ログは専用temporary rootに保持し、公開buildへ入れない。
local Docker/shellcheckは未導入。既存CIのsynthetic Docker integrationとshellcheckはcommit後にGitHub runで確認する。

前回単一ページの1079 tests、5ファイル、Chrome8コピー等の実績は[初回準備証跡](../evidence/2026-09-13-user-guide-web-preparation.json)に履歴として保持し、今回の結果へ読み替えない。

CIにはbuild/browser検証のみ追加し、公開workflow、Pages write権限、OIDC、hosting secretは設定しない。
backend/Discord/Hostのsource・infra・設定は変更対象外。通常の既存CI Docker integrationはsyntheticでありproduction E2Eではない。
実Minecraft参加、実機スマートフォン、Safari/Firefox、screen reader、hosted HTTPS/Access/DNS/TLS/cache/rollbackは今回未実証。

## 公開承認の具体的な範囲

公開の別承認に必要なのは、(a) Cloudflare Pages採用と実account/所有者、(b)全員閲覧か許可者限定か・認証方式、(c)内容承認済み17ファイルをその閲覧範囲へ公開する可否と除外方針、(d)pages.dev候補またはWeb専用subdomain、(e)費用上限、(f)初回project/upload/必要なAccess、任意のWeb DNS/TLS、公開検証、Webだけの差戻し・緊急遮断。
独自domainを承認しなければAWS/DNS変更は不要。Discord送信・command登録、production deploy/IAM、Lambda invoke/Reconcile/SSM、START/STOP、Game/world/Snapshot/provenanceはこの公開承認にも含めない。

**READY FOR USER GUIDE WEB / GAME-CENTERED LOCAL REVIEW** は修正版のローカルデザインレビュー準備完了を示す。Web公開済み、D-100のhosting採用済み、production変更済みという意味ではない。

### CI初回の環境選択修正

CI 34734192540のWeb jobはsystem Pythonを選び`wishicraft` importで失敗した。build/preview/生成更新の実行例をcanonical entrypoint内の`uv run python`へ統一した。backend/package設定は変更せず、失敗runを保持して次commitのCIで再検証する。
