# wishicraft-server

Wishicraft（ゐしクラくん）のMinecraft制御面を構築するリポジトリです。

## Phase 0

Phase 0では、Python、AWS CDK、設定検証、テスト、CIだけを整備します。AWSリソース、Discord接続、Minecraftのインストールはまだ行いません。

`config/project.yaml`、`config/stages/<stage>.yaml`、`config/secrets.example.yaml`がGit管理された設定の正本です。秘密値は含めず、`secrets.example.yaml`にはParameter Store SecureStringのParameter名だけを置きます。

`null`は未確定値であり、コードは補完しません。Phase 0ではdevの空CDK stackはenvironment-agnosticにsynthでき、AWS Account IDやAWS profileを必要としません。AWS Account IDとprofileの解決方式は、最初のdev deploy前に決定します。

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
npx --no-install cdk synth --context stage=dev
```

prod synthとdeployは初期リリース直前まで行いません。deploy、secret登録、AWS profileの指定はこのPhase 0の手順に含めません。

## CI

GitHub ActionsはPython 3.12、lock済みCDK CLIでpytest、Ruff、mypy、dev向けCDK synthを実行します。AWS credential、secret、prod deployは使用しません。
