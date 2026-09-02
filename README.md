# wishicraft-server

Wishicraft（ゐしクラくん）のMinecraft制御面を構築するリポジトリです。

## 現在地点

Phase 0〜7は完了しています。Phase 8Aでは停止中のpersistent Data EBSだけを対象とするBACKUP Operationをrepository-onlyで実装・検証済みです。Phase 7ではDiscord signed Interaction Endpointとdev Guild限定`/mc status|start|stop`を既存Control Planeへ接続し、real DiscordからSTOPPED STATUS、START→READY、RUNNING STATUS、public Minecraft protocol、STOP、final STOPPED STATUSまでdev E2Eを完了しました。D-032のread-only observer、24 alarms、confirmed SNS Email通知、月額Budgetも実deploy・検証済みです。

devは次の3層architectureです。

```text
Wishicraft Control Plane
  -> AL2023 Host Runtime（systemd / Docker / Compose）
  -> pinned itzg Minecraft Runtime
```

Frozen Phase 1 stack、独立Target stack、独立Control Plane stackを分離しています。dev Control PlaneのReconcile/SystemStateに加え、Phase 4 tablesとAdmission Lambdaもdeploy・integration済みです。Phase 1のhost Java、直接`minecraft.service`、Xmx 3G等はas-built履歴であり、現在のTarget runtime契約ではありません。

設計・契約の正本は[Architecture](docs/03_architecture.md)、[Domain model](docs/04_domain_and_state_model.md)、[Data/interface contracts](docs/05_data_and_interface_contracts.md)、[Delivery plan](docs/06_delivery_plan.md)、[Decisions/backlog](docs/09_decisions_and_backlog.md)です。itzgとの責務境界は[itzg responsibility boundary](docs/architecture/itzg-responsibility-boundary.md)を参照してください。

## 設定の正本

`config/project.yaml`、`config/stages/<stage>.yaml`、`config/secrets.example.yaml`がGit管理された設定の正本です。秘密値は含めず、`secrets.example.yaml`にはParameter Store SecureStringのParameter名だけを置きます。

`null`は未確定値であり、コードは補完しません。手動AWS操作は、runbookで定めたIAM Identity Center profileとSTS Account ID照合方針に従います。

prod設定はplaceholderとして読み込めますが、未確定の必須値がある間はprod向けsynth/deployをvalidationで停止します。

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
npx --no-install cdk synth WishicraftControlPlaneStack-dev --context stage=dev --context phase=7 --context deployment=control-plane
```

prod synthとdeployは初期リリース直前まで行いません。通常のrepository validationはAWS credentialやsecretを使用しません。

## CI

GitHub ActionsはPython 3.12、lock済みCDK CLIでpytest、Ruff、mypy、dev向けCDK synthを実行します。AWS credential、secret、prod deployは使用しません。

Phase 2 target hostは`deployment=target`で独立assemblyとしてsynthし、deploy時も`MinecraftTargetStack-dev`を必ず明示する。通常のPhase 1 assemblyと`--all` deployは使用しない。

## Phase 2a Host Runtime static artifacts

`config/stages/dev.yaml`の`host_runtime`は、AL2023 release/kernel/公式AMI identity、Compose checksum、itzg release image digest、Minecraft 26.2、initial memory/timeoutを固定する。`wishicraft.host_runtime.render_boot_time_artifacts`は、実機preflightで観測したnumeric UID/GIDを受け取り、secretを含まないcanonicalな`compose.yaml`、`runtime.env`、manifest、render digestを新しい専用output rootへ生成する。

Phase 2aのrepository validationはDocker Engineを必要としない。Phase 2b-1ではGitHub-hosted Linux x86_64 runnerの既設Dockerだけを使い、固定digest imageを`SETUP_ONLY=true`で実行するsynthetic ownership integration testを追加した。local開発環境へDockerをinstallせず、実world、実`server.properties`、secret、AWSを使用しない。
