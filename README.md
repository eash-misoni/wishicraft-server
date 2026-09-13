# wishicraft-server

Existing Operations via Webはproduction Completedです（D-104、2026-09-13）。[管理画面](https://web.wishicraft.net/manage/)から既存5操作を共有Admissionへ接続し、Web START A→SWITCH B→A→STOPの成功、CSRF・15分失効・logout・重複防止・terminal追跡を確認しました。[契約](docs/reviews/existing_operations_web.md)と[release証跡・rollback](docs/runbooks/existing_operations_web.md)を参照してください。最終状態はSTOPPED/HEALTHY。Minimal Game Creationは[D-105 repository実装](docs/reviews/minimal_game_creation.md)を準備中で、[production write前の承認gate](docs/runbooks/minimal_game_creation.md)を維持しています。

D-103 Web URL Stabilizationはproduction Completedです。canonical URLは[public guide](https://web.wishicraft.net/)と[管理画面](https://web.wishicraft.net/manage/)。DNS/TLS、新domainの実OAuth/status・15分失効・logout、旧redirect削除後の再loginを確認しました。[release証跡・rollback](docs/runbooks/web_custom_domain.md)を参照してください。生成execute-api URLは運用上のunderlying endpointです。

Web Foundation（D-102 Accepted）を既存dev AWSへproduction適用しました。[設計・費用・承認対象](docs/reviews/web_foundation.md)、[ローカル表示とrelease計画](docs/runbooks/web_foundation.md)を参照してください。public guideはログイン不要で一般公開可（FQDN/招待URL除外）。実Discord OAuth・read-only status・15分失効・logoutを確認し、read-only releaseをCompletedとしました。実証範囲・残る観測項目はrunbookを参照してください。

```sh
tools/dev-env run -- uv run python -m web.local --scenario players
```

localhost上でguide → 管理 → fake login → read-only statusを確認できます。実Discord認証・実運用状態ではありません。

静的な参加・コマンド案内Webをrepository実装しました。説明の正本は利用案内から辿るページ別Markdown、local build/previewと公開計画は [D-100 Web準備レビュー](docs/reviews/user_guide_web.md) を参照してください。canonical Web URLで公開済みです。public guideの閲覧はログイン不要で一般公開可です。

利用者向けの現行コマンド・権限・Resetの注意点は[Discord利用案内](docs/discord_user_guide.md)を参照してください。進捗表示改善D-099はAccepted・production適用済みです。実STATUS一回で実行者・到達記録・公開配送を確認しました。

> Reset release（2026-09-12）: [D-098のB限定Reset](docs/reviews/game_scoped_reset.md)はAccepted・限定release Completed。fixed/new、通常再起動、二回の隔離復旧を確認し、両受付を元UNSETへ復元した。本番旧world削除は0件、実Discord RESET Interactionは未実施。実証範囲は[production証跡](docs/evidence/2026-09-12-reset-production.json)を参照。Phase 9全体の完了ではない。


Wishicraft（ゐしクラくん）のMinecraft制御面を構築するリポジトリです。

## 現在地点

今後は[D-101のCurrent roadmap](docs/06_delivery_plan.md#current-roadmap)に従い、Web Foundation → Existing Operations via Web → Minimal Game Creation → Whitelist Management → 需要に応じたRuntime / Version / MOD Extensionへ進みます。read-only statusとwrite operationsは別release sliceです。旧Phase 9〜16はprevious planとして残し、連番消化や一般化を必須依存にしません。

RETENTION実削除、Restore UI、chat、高度なPackage/Preset/Template管理等は条件・需要で開始するindependent trackです。D-100の承認済み本文・構成はWeb Foundationのpublic領域で公開済みです。public guideはログイン不要で一般公開可です。既存dev AWSでのread-only releaseを適用済みです。custom domainは今回対象外です。


現在の通常実行契約は[Data/Interface §0](docs/05_data_and_interface_contracts.md#0-production適用済みruntime契約d-096)を参照してください。runbookは移行手順・証跡を所有します。現在は[D-097 二Game切替・共有BACKUP](docs/reviews/two_game_switch.md)の設計と限定移行計画がAcceptedです。production適用・A→B→Aと共有BACKUP/RETENTION検証は2026-09-12 Completedで、[実行証跡](docs/evidence/2026-09-12-two-game-production.json)へ別途記録します。Phase 9全体の採用ではありません。

D-097の二Game切替sliceは2026-09-12にCompleted。A→B→Aは同一EC2 boot、両受付UNSET、最終A/STOPPED/HEALTHY、42 alarm OK、Snapshot計7件（v1 normal 5・anchor 1・shared v2 normal 1）を確認しました。RETENTIONはdry-run-only、実multi-Game単独復元とPhase 9全体は未完了です。[今回のcloseout](docs/runbooks/two_game_switch_migration.md#production-closeout2026-09-12)を参照してください。

Phase 0〜8は完了しています。停止中Data EBSのBACKUP、durable provenance、retention dry-run、Runtime heartbeat、warning付き無人自動停止、監視・コスト整備をdevで検証済みです。Phase 7ではDiscord signed Interaction Endpointとdev Guild限定`/mc status|start|stop`を既存Control Planeへ接続し、real DiscordからSTOPPED STATUS、START→READY、RUNNING STATUS、public Minecraft protocol、STOP、final STOPPED STATUSまでdev E2Eを完了しました。

Phase 8.3は2026-09-10 UTCにControl Plane限定deployと通常START/STOP監視E2Eを完了しました。D-094 Accepted、READY後15分以上のfreshness維持、正しいData EBS使用率1.4389%、停止後SSM/容量値発行なし、41 alarm OK、最終STOPPED/HEALTHYを確認済みです。初期欠測による5件の実メール通知と自然復帰も[監視runbook](docs/runbooks/phase8_monitoring.md)へ記録しています。旧Phase 9全体は未完了です。RETENTION実削除はD-097 shared-volume v2の保持群と復旧条件に基づく独立gateで、Snapshot総数だけでは開始しません。Restore UIは必要時の管理Web拡張です。D-095の独立sliceとして、2026-09-11にBACKUP安全性deployと既存Snapshotの隔離復元・保存・再起動・抽出・cleanupを完了しました。[実証範囲と限界](docs/runbooks/backup_safety_isolated_restore.md#execution-closeout--2026-09-11-utc)を参照してください。この独立復元slice時点では新BACKUP経路の実AWS E2Eは未実施でした。

D-096の既存Game対象付きruntime移行は2026-09-11にCompleted。限定canonical STOPで前の失敗状態を復旧し、host/Control Plane修正後の通常START/STOP二巡、既存world保持、停止container限定削除、新run heartbeatを実証しました。最終STOPPED/HEALTHY、両受付UNSET、41 alarm OK、元EBSと5 Snapshot/provenance保持を確認済みです。[closeout](docs/runbooks/targeted_runtime_migration.md#production-closeout--limited-stop--forward-migration)を参照してください。Phase 9全体は未着手、その他再設計はProposedです。

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
- Node.js 22とrepository lock済みCDK CLI

最初に実行環境とtoolの実path/versionを確認します。checkはinstall、login、shell設定変更を行いません。Dockerとlocal shellcheckはoptionalとして状態を表示します。

```sh
tools/dev-env check
```

`uv`が通常PATH外にある場合も、正規entrypointはPython user base等の確認済みinstallationを動的に発見し、repository-local `.uv-cache/`と`.jsii-cache/`を使います。`run`が構成したPATHはCDK local bundlingの子processにも継承されます。machine固有の絶対pathをrepositoryへ固定しません。

macOSではvenv等でPython versionが変わった場合も、既存の`~/Library/Python/*/bin/uv`を発見します。通常のdiscoveryで見つからず、このfallbackに複数installationがある場合は`WISHICRAFT_UV_BIN`で使用対象を明示します。

```sh
tools/dev-env run uv sync --frozen --all-groups
tools/dev-env run npm ci
tools/setup-dev-tools bundling-cache
tools/dev-env run uv run pytest
tools/dev-env run uv run ruff check .
tools/dev-env run uv run ruff format --check .
tools/dev-env run uv run mypy src infrastructure tests
tools/dev-env run npx --no-install cdk synth MinecraftStack-dev --context stage=dev --context phase=1 --context deployment=phase1
tools/dev-env run npx --no-install cdk synth MinecraftTargetStack-dev --context stage=dev --context deployment=target
tools/dev-env run npx --no-install cdk synth WishicraftControlPlaneStack-dev --context stage=dev --context phase=8 --context deployment=control-plane
```

GitHub CLIが未導入の場合だけ、`tools/setup-dev-tools gh`で公式GitHub CLI 2.100.0のOS/architecture対応archiveを公開SHA-256 checksumで検証し、user-local領域へ導入します。既存installationは変更せず、同versionの再実行ではdownloadしません。導入後の認証・repository/account確認は別操作です。

`tools/setup-dev-tools bundling-cache`はhash-lock済みLambda依存のLinux wheelをrepository-local uv cacheへ準備する明示的setupです。初回だけnetworkを必要とし、再実行とlocal bundlingは同じcacheを再利用します。wheel取得失敗、`uv`未検出、bundling code failureを別々に報告し、Docker fallbackで隠しません。

```sh
tools/dev-env auth-check
```

認証がなければ`gh auth login`を人間が実行します。token表示用commandは使わず、git credential helperも変更しません。AWS CLIのinstallationとAWS sessionも別物です。production操作前は`wishicraft-dev` profileのSTS caller Account IDをdev stage設定と照合し、不一致や期限切れをIAM変更で補いません。

Dockerはdeveloper validationの必須条件ではありません。`tools/dev-env check`は「CLIなし」「CLIあり/daemon接続不可」「CLIとdaemon利用可能」を区別し、contextやdaemon設定を変更しません。固定itzg imageを使うsynthetic ownership integrationだけはDocker/Buildxを必要とし、通常のpytest/lint/type/synthとは分離されています。

prod synthとdeployは初期リリース直前まで行いません。通常のrepository validationはAWS credentialやsecretを使用しません。

## CI

GitHub ActionsはPython 3.12、lock済みCDK CLIでpytest、Ruff、mypy、dev向けCDK synthを実行します。AWS credential、secret、prod deployは使用しません。

Phase 2 target hostは`deployment=target`で独立assemblyとしてsynthし、deploy時も`MinecraftTargetStack-dev`を必ず明示する。通常のPhase 1 assemblyと`--all` deployは使用しない。

## Phase 2a Host Runtime static artifacts

`config/stages/dev.yaml`の`host_runtime`は、AL2023 release/kernel/公式AMI identity、Compose checksum、itzg release image digest、Minecraft 26.2、initial memory/timeoutを固定する。`wishicraft.host_runtime.render_boot_time_artifacts`は、実機preflightで観測したnumeric UID/GIDを受け取り、secretを含まないcanonicalな`compose.yaml`、`runtime.env`、manifest、render digestを新しい専用output rootへ生成する。

Phase 2aのrepository validationはDocker Engineを必要としない。Phase 2b-1ではGitHub-hosted Linux x86_64 runnerの既設Dockerだけを使い、固定digest imageを`SETUP_ONLY=true`で実行するsynthetic ownership integration testを追加した。local開発環境へDockerをinstallせず、実world、実`server.properties`、secret、AWSを使用しない。
