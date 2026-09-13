# D-103 Web URL Stabilization — production review

状態: **Accepted・production Completed（2026-09-13）**。
D-102 read-only release Completed、基準HEAD `b51935d`を継承。D-101順序2のWeb write操作には着手しない。

## canonical URLと実preflight

移行後の正本は **https://web.wishicraft.net**。public guide、Game/command、manage、status、authを同originへ統合する。
移行前のgenerated endpointはD-102の稼働先で、切替後はrollback/read-back用default endpointとしてのみ扱う。

2026-09-13 read-only AWS preflight:

- canonical caller account `385526546525` / `ap-northeast-1`一致。
- 既存public hosted zone `wishicraft.net.`、`Z077818024BJUAUBFMTKV`。新zoneを作らない。
- 既存recordはNS/SOAの2件。`web.wishicraft.net`、その配下、`*.wishicraft.net`の衝突なし。
- public NSはzoneの4 nameserverと一致。既存API Gateway custom domainなし、WishicraftのACM certificateなし。
- `AWSServiceRoleForAPIGateway`は既存。custom domainのためのservice-linked role新設は現在不要。
- Minecraft DNS名はstageの`route53.record_name`を維持し、今回のAlias/validation対象に含めない。

## IaCと段階

すべて専用`WishicraftWebStack-dev`の中で管理する。新しいstack・CloudFront・S3・Cloudflareは追加しない。
`config/web-dev.json`の`domain_name`がdomain名の宣言。CLI context `web_domain_phase`は移行段階だけで、別domainやrole policyを入力しない。

| phase | 追加resource / origin |
|---|---|
| `certificate` | 非exportable ACM public certificate 1件。DNS validationと同一accountの既存zone IDを明示。旧originのまま。 |
| `domain` | Regional DomainName、root API mapping、A Alias各1件。証明書はそのまま。OAuthは旧originのまま。 |
| `canonical`（通常default） | resource追加なし。両Lambdaへ固定canonical origin、AuthのOAuth originを新domainへ切替。 |
| `legacy` | 初回baseline比較test専用。証明書作成後の通常rollbackには使わない。 |

証明書は`ap-northeast-1`、FQDNは`web.wishicraft.net`だけ、wildcard/SAN追加なし、`CertificateExport=DISABLED`。
CloudFormation native DNS validationが同zoneへ実CNAMEを作る。CNAME名・値とcertificate ARNは発行後のread-backで確定し、推測しない。
証明書はRetain。validation CNAMEは自動renewalのため保持し、rollbackで削除しない。WebSessions=Delete、既存durable tableのRetainは不変。
DomainNameは`REGIONAL` / `TLS_1_2`、mapping keyなし（root）、既存APIの`$default` stage。A AliasのtargetはDomainNameのregional attributesを参照し、EvaluateTargetHealth=false。
新しいLambda role IAMは0。Web/AuthのCP GetItem・session・exact secret pathの権限はD-102と同じ。
CloudFormation実行roleがACM/Route53/API Gatewayを操作する。service-linked roleは既存のものをサービスが使用する。

## なぜcertificateだけを先にdeployするか

同account・public Route53 zone・DNS validationの条件をpreflightで確かめ、CloudFormationが自動validationできる構成にする。
証明書だけを先に作り、`ISSUED`をread-backするまでdomain追加もOAuth変更も進めない。custom provider Lambdaや長期credentialは作らない。
最初のdeployは非同期processとして監視し、1分以内の間隔でCloudFormation eventsとACM statusを観測する。
15分でISSUEDにならなければ進行停止し、CNAME/委任/CAA/ACM FailureReasonをread-onlyで診断する。結果不明のままretry・delete・新certificate要求をしない。
待機時間を成功扱いせず、CloudFormationがまだ進行中ならその状態を報告する。既存API/旧OAuthはその間稼働を維持する。

## origin / cookie / OAuthの境界

canonical段階ではAPI Gatewayの`requestContext.domainName`を固定originと照合する。Host/X-Forwarded-Hostやqueryからoriginを組み立てない。
旧default hostのpublic GET・manage・loginは308で新originの同pathへ誘導し、queryを転送しない。
旧hostのAPI・callback・logoutやGET以外は421で拒否し、secret/session/CPへ到達しない。callback code/stateを新hostへ転送しない。
default endpoint自体は無効化しないが、そこでprivate response/sessionを発行しない。CORSは追加しない。
API Gatewayが信頼するdomain情報を入口にし、次sliceのwriteではさらにexact OriginとCSRF検査を追加する。default endpoint disableは必要性を確認する後続hardening候補で、今回のsecurity成立条件ではない。

Cookieは従来の`__Host-`、Secure/HttpOnly/SameSite=Lax/Path=/、Domain属性なし。
session 15分、state 5分、HMAC・server expiry・logout DeleteItem・一回state消費・bounded revoke・User-Agent・NoRedirectを維持。
canonical originをsession/state fingerprintへ追加するので、旧originのrecordを新domainへ持ち込んでも拒否。cutover時は再loginが必要。secret rotationは不要。
local harnessはloopback fake authのまま。production handlerにlocalhost/fake authの許可を追加しない。
public/internal links、polling `/api/status`、logout formはroot-relativeなので新host内で完結する。承認済み本文/UI/13ページを再設計しない。

`domain`段階で新hostから本格loginしない。state cookieは新host、まだ旧callbackという組合せはfail closedになるため、ここではpublic/manage/API未認証境界だけを確認する。

## release順序

1. finalized HEAD/CI、canonical caller/account/region、Web record衝突なしを再確認。下記phaseごとに新temporary rootへsynthし、`cdk diff --change-set=false`でWebだけをreviewする。
2. `web_domain_phase=certificate`をWeb stackだけdeploy。ACM request / validation CNAME / ISSUED / stack completionをread-back。
3. `web_domain_phase=domain`をdeploy。DomainName AVAILABLE、TLS policy、mapping、Alias、Route53 INSYNC、HTTPS public13ページ、manage login、API401を確認。TLS1.2接続と証明書host検証を行う。
4. **人間操作:** Discord ApplicationのOAuth2 Redirectsへ `https://web.wishicraft.net/auth/callback` を完全一致追加・保存。旧redirectは削除しない。Client Secretのresetは不要、必要なら停止。
5. `web_domain_phase=canonical`をdeploy。WebOrigin/OAuthRedirectUri、両Lambda environment・実IAM、旧hostのpublic redirect/private421をread-back。
6. **人間E2E:** 新originからreal Discord login、status、15分失効、再login、logoutとAPI401。CP保存record・logs・no-store/CSP・cookie属性を安全な証跡で確認。Operationを作らず、Minecraftを起動しない。
7. **人間操作:** 新origin E2E成功後だけ、旧generated callback URIをDiscordから削除。新redirectを残したことを確認し、もう一度new loginを検証。
8. docs/evidence/CI/Wiki/clean closeout。以後のpublic links・表示URL・write設計は新originだけを正本とする。

```sh
# 毎回新しいtemporary rootを使う。以下はsynth例で、deploy許可ではない。
WEB_DOMAIN_ROOT=$(mktemp -d)
tools/dev-env run -- npx --no-install cdk synth WishicraftWebStack-dev \
  -c stage=dev -c phase=8 -c deployment=web -c web_domain_phase=certificate \
  --output "$WEB_DOMAIN_ROOT/assembly"
# approval後: 同assembly / canonical profileで、WishicraftWebStack-devだけdeployする。
```

## rollback

新OAuthが失敗し旧redirectをまだ残している間は、同HEADの`domain`段階へWebだけ戻す。旧generated originへOAuthを戻し、custom domain/certificate/Aliasは維持する。
旧redirect削除後は人間が旧exact URIを再登録してから戻す。新origin sessionは旧originへ移植しない。旧recordは元の15分期限を超えて復活しない。
DNS/TLS問題時も既存CP/Target/Frozen・Minecraft DNS・secretをrepairしない。証明書CNAMEを消してやり直さない。
result-unknown deploy、ownership/identity不一致、不要なwildcard/zone新設/費用拡大、default endpoint停止必須のsecurity問題は停止条件。

## 費用と公式根拠（2026-09-13確認）

非exportable ACM public certificateは無料。[ACM pricing](https://aws.amazon.com/certificate-manager/pricing/)。exportable有料certificateは要求しない。
API Gatewayは既存HTTP APIのrequest/data transfer課金を維持。Regional custom domain/API mappingによる追加固定課金項目は公式料金表にない。[API Gateway pricing](https://aws.amazon.com/api-gateway/pricing/)。
既存zoneを再利用するのでhosted zone固定費増加なし。API GatewayへのAlias queryは無料。validation CNAME等の通常DNS queryは標準料金対象（最初の10億queryは$0.40/100万）。[Route53 pricing](https://aws.amazon.com/route53/pricing/)、[Alias料金](https://aws.amazon.com/route53/faqs/)。
したがって通常の小規模利用で増分固定費は$0、validation照会は微小な従量分。既存Web月$3計画目安を重大に増やす構成ではなく、無料trialには依存しない。traffic増加や攻撃時のhard capではない。Budget変更なし。

仕様: [HTTP custom domain/TLS](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-custom-domain-names.html)、[same-regionとservice-linked role](https://docs.aws.amazon.com/apigateway/latest/developerguide/apigateway-regional-api-custom-domain-create.html)、[CloudFormation native DNS validation](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-certificatemanager-certificate.html)。

## Validation / production gate

focused testsは旧Web Foundationとcanonical handler/各migration synthを含む61件成功。最初の追加test1件はJavaScriptのquote形式を取り違えたfixture assertionで失敗し修正した。型検査の初回union narrowing/optional result errorsも修正済み。full validation/CI/live diffはこのsliceのhandoffで確定する。
以下のrepository検証はproduction承認前の記録。実適用結果は末尾に記録する。

full初回は1157 passed / 3 failed。既存migrationがstage YAML全文をpredecessor前提として固定していたため、Web domain設定を専用configへ分離した。既存stage YAML/migration契約は変更せず、新rootで再検証する。

最終repository検証: full **1,160 passed（54.00秒）**、focused 61件、Ruff lint/format（243 files）、mypy（182 source）成功。
3段階のsynthと`--change-set=false`のlive diff成功。差分は下記4 resourceの追加と、既存Web/Auth Lambda code（canonical段階ではorigin environmentも）のみ。既存resource削除0、Lambda IAM差分0、CP/Target/Frozen変更0。

| phase | 固定template SHA-256 |
|---|---|
| certificate | `8c3b823cd5797a644c5456c92bb16c45686a2ee2c76c726eb1ff13f336d6566d` |
| domain | `edac9f4155381262344e0860138696d4b750e5e7edd272b2425e3f4d35d9e3d4` |
| canonical | `2339facf788777585edf975cd17fbb7c4abdea8c8cd69f23c69b37a9985839f0` |

追加logical resources: `WebCertificate`、`WebDomain`、`WebMapping`、`WebAlias`。CNAMEはnative certificate DNS validationが管理するため、別の推測値RecordSetを作らない。
local evidence: `wishicraft-web-domain-validation-v2-a9kct92n`、`wishicraft-web-domain-synth-v2-clzdn8j_`、`wishicraft-web-domain-live-review-nap33y0z`。
CIはfinalized commitのpush後に確認し、handoffでrun/HEADを報告する。承認前handoffではproduction writeを行わず停止した。その後、同HEAD・live diffに対する明示GOを受領した。


## Production release evidence（2026-09-13、Completed）

承認・deploy基準HEAD: `954839813e7b33f72e3af3788e3ff5d1297b67e0`、CI `34746215304` success。
固定assemblyを順に適用し、各live templateの完全一致を確認した。Web stackだけをdeployし、CP/Target/Frozen・Minecraft DNS・secret・Budgetを変更していない。

- certificate: 17:02:19 JST UPDATE_COMPLETE。ACM `ISSUED`、SANはexact domainだけ、export DISABLED。
- domain: 17:03:58 JST UPDATE_COMPLETE。REGIONAL / AVAILABLE / TLS_1_2、root mappingとA Alias一致。HTTPS接続のTLSv1.2・hostname検証成功。
- canonical: 新redirect追加・旧redirect維持・secret不変を人間が確認後、17:10:43 JST UPDATE_COMPLETE。両Lambda canonical originとAuth redirect、新WebOrigin output一致。
- certificate ARN: `arn:aws:acm:ap-northeast-1:385526546525:certificate/1852ab6e-32e7-424e-a366-25113b8e8647`。
- validation CNAME: `_d896e56e5f62302d70151cbd8a02081b.web.wishicraft.net.` → `_fc5827cad5525ffbc95e02d2200e3e2d.wzccmgtwzk.acm-validations.aws.`。renewalのため保持。
- public 13ページ・16 assetsはdeploy assetとbytes一致。新manageは未認証login表示、新APIは401。
- 旧host public/Game/command/manage/loginは308、queryを落としてcanonical同pathへ転送。API/callback/logoutは421、cookie/Locationなし。X-Forwarded-Hostで迂回できない。
- OAuth開始のredirectは新exact URI、scopeはidentify + guilds.members.read。state cookieのSecure/HttpOnly/SameSite=Lax/Path=/・Domainなし・300秒を実測。invalid stateは403。
- 人間による新domainの実Discord OAuth・status表示・15分失効を確認。既存identityはPlayer/Admin両role。再login・logout後manage login表示/API authentication_required、旧redirect削除・削除後new loginも人間が確認した。
- 実Web/Auth inline + managed IAMは承認template一致。最初の検証器は既存AWSLambdaBasicExecutionRoleを「なし」と誤って想定し失敗したため、templateとの比較へ修正して新versionで成功。production IAM変更なし。
- 08:15:54 UTCの保存state projectionはSTOPPED / stopped / not-running、heartbeat staleかつexpected=false、players not_expected/count=null、current operationなし。連続GetItemの3 record完全一致。これは保存state readの比較であり、ブラウザsessionを使った全期間snapshotの証明ではない。CP mutation不能のIAM・handler testsと併せて評価する。
- 同時点の直近25分logs 261件は全てLambda platform events。raw message・cookie・tokenは証跡へ保存しない。
- WebSessions Delete、certificate Retainのread-back一致。

local evidence roots: `wishicraft-web-certificate-deploy-3tgs_o41`、`wishicraft-web-domain-deploy-cdr945c2`、`wishicraft-web-custom-basic-e2e-bwazo4tz`、`wishicraft-web-canonical-deploy-x6gh5zms`、`wishicraft-web-canonical-basic-e2e-r365_0d6`、`wishicraft-web-canonical-readonly-evidence-v2-ds3_j25p`。

closeout full validation初回は1104 passed / 9 failed / 47 errors。sandboxのPyPI DNS制限によるCDK dependency bundling失敗を確認。実装成功として扱わず、依存取得可能な環境の新rootで全件再実行し、1,160 passed（58.70秒）、Ruff lint/format 243 files、mypy 182 source全成功。証跡 `wishicraft-web-domain-release-validation-v2-sez384_0`。


最終確認では旧callbackへ架空code/stateでアクセスし421拒否・転送/Set-Cookieなしを確認した。証跡 `wishicraft-web-domain-final-readback-5glhpbjh`。同時に新public 200/API 401、ACM ISSUED、domain AVAILABLE、TLSv1.2、既存zoneの4 recordとAlias一致、stack UPDATE_COMPLETEを再確認した。実code/tokenを再利用しない。Portal旧redirect削除自体は人間確認を根拠とし、新redirectだけでの実login成功と組み合わせる。

実ブラウザでのsession cookie値は収集しない。host-only等のsession cookie生成contractは既存実装・境界testと失効/logoutの実E2E、state cookieは実HTTP属性で確認した。Player-only/Admin-only、role不足identity、署名改ざん・state replay・origin fingerprintの詳細はsynthetic testsを根拠とする。RUNNING/transitionは次回正規Operation時のread-only観測に残し、Minecraft起動やOperation作成は今回0件。

費用・rollbackは上記のとおり。旧redirect削除済みなので、旧originへrollbackする場合は先に人間が旧exact callbackを再登録する。ACM CNAMEは維持する。次sliceのwriteはcanonical originでのCSRF/Origin検査と既存Admission接続を設計するが、本sliceでは実装していない。
