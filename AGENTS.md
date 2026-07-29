# Wishicraft Codex Instructions

作業前に必ず以下を読むこと。

- `docs/10_codex_working_agreement.md`
- `docs/09_decisions_and_backlog.md`
- `docs/12_initial_configuration.md`
- `docs/06_delivery_plan.md`の現在Phase
- `config/project.yaml`
- 対象stageの設定ファイル
- 対象機能に関係する要件・契約文書

変更前に、目的・対応要件・変更予定ファイル・対象外を報告すること。

`null`、ID、ARN、secret、AWS設定を推測しない。
秘密値をコード、Git、ログへ保存しない。
一度にPhase全体を実装せず、1つの明確な作業単位に分ける。
テスト・lint・型検査・CDK synthの結果を報告する。
実行していない確認を成功扱いしない。
devを基本とし、prod deployや破壊的操作を勝手に行わない。