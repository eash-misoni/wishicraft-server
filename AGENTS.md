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

## 自律ローカル検証

- ローカルのtest-only harness、fixture、証跡は新しい専用temporary rootへ作成し、過去のrootと正式結果を上書きしない。
- fixture失敗は既存結果を補正せず、新しいversionで原因診断・修正・再検証する。
- production wrapper、payload、oracle、selection logicを変える必要が生じたら、根拠と影響を示して停止する。
- AWS、SSM、EC2、host、deploy、DNS、secret、破壊的操作、またはセキュリティ動作変更の直前では停止して明示承認を求める。
- 詳細な自律実行・証跡・停止境界は`docs/10_codex_working_agreement.md`を正本とする。

## 学習Wiki同期

- 完了したPhaseまたは明確な実装sliceの予定tracked変更がすべてcommitされた後、finalized HEADを根拠として最終handoff前に`$wishicraft-learning-wiki`を実行する。Phase途中や未commitの仕様変更には実行しない。
- 自動実行は`.local/learning-wiki/`が存在するprimary/local checkoutだけで行う。temporary worktree、Codex cloud、または出力先がない環境では別Wikiを作らず、skip理由を最終報告する。
- 同期失敗で完了済みPhaseやcommitを巻き戻さない。同期ではAWS、Discord、production、GitHub設定、実機を操作せず、学習Wiki生成物をcommitしない。
