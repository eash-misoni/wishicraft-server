# D-103 Web URL Stabilization — production review

状態: **repository implementation / Proposed、最初のproduction write前**。
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

## 承認後のrelease順序（現在は未実行）

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
production ACM request、DNS変更、domain作成、OAuth変更はまだ0件。最初のproduction write前にこのrelease planを一度reviewする。

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
CIはfinalized commitのpush後に確認し、handoffでrun/HEADを報告する。**production writeは未実行のまま停止する。**
