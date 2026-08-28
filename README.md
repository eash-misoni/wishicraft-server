# wishicraft-server

Wishicraft（ゐしクラくん）のMinecraft制御面を構築するリポジトリです。

## Phase 0

Phase 0で、Python、AWS CDK、設定検証、テスト、CIを整備しました。AWSリソース、Discord接続、Minecraftのインストールはまだ行いません。

`config/project.yaml`、`config/stages/<stage>.yaml`、`config/secrets.example.yaml`がGit管理された設定の正本です。秘密値は含めず、`secrets.example.yaml`にはParameter Store SecureStringのParameter名だけを置きます。

`null`は未確定値であり、コードは補完しません。Phase 0のdev空CDK stackはenvironment-agnosticにsynthでき、AWS Account IDやAWS profileを必要としません。Phase 1以降の手動AWS操作は、runbookで定めたIAM Identity Center profileとSTS Account ID照合方針に従います。

prod設定はplaceholderとして読み込めますが、Phase 0でprod向けsynthを行うと、現在の`null`値をパス付きで列挙して失敗します。この一時的な安全ゲートは、すべての`null`を将来永続的に必須とするものではありません。Phase 1開始前にstage・処理・Phaseごとの必須値を定義します。

## 開発環境

- Python 3.12
- [uv](https://docs.astral.sh/uv/)

```sh
uv sync --all-groups
npm ci
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src infrastructure tests
npx --no-install cdk synth MinecraftStack-dev --context stage=dev --context phase=1 --context deployment=phase1
npx --no-install cdk synth MinecraftTargetStack-dev --context stage=dev --context deployment=target
npx --no-install cdk synth WishicraftControlPlaneStack-dev --context stage=dev --context phase=3 --context deployment=control-plane
```

prod synthとdeployは初期リリース直前まで行いません。deploy、secret登録、AWS profileの指定はこのPhase 0の手順に含めません。

## CI

GitHub ActionsはPython 3.12、lock済みCDK CLIでpytest、Ruff、mypy、dev向けCDK synthを実行します。AWS credential、secret、prod deployは使用しません。

Phase 2 target hostは`deployment=target`で独立assemblyとしてsynthし、deploy時も`MinecraftTargetStack-dev`を必ず明示する。通常のPhase 1 assemblyと`--all` deployは使用しない。

## Phase 2a Host Runtime static artifacts

`config/stages/dev.yaml`の`host_runtime`は、AL2023 release/kernel/公式AMI identity、Compose checksum、itzg release image digest、Minecraft 26.2、initial memory/timeoutを固定する。`wishicraft.host_runtime.render_boot_time_artifacts`は、実機preflightで観測したnumeric UID/GIDを受け取り、secretを含まないcanonicalな`compose.yaml`、`runtime.env`、manifest、render digestを新しい専用output rootへ生成する。

Phase 2aのrepository validationはDocker Engineを必要としない。Phase 2b-1ではGitHub-hosted Linux x86_64 runnerの既設Dockerだけを使い、固定digest imageを`SETUP_ONLY=true`で実行するsynthetic ownership integration testを追加した。local開発環境へDockerをinstallせず、実world、実`server.properties`、secret、AWSを使用しない。
