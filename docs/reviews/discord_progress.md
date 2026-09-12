# D-099 Discordの実行者・主要経過表示（Proposed）

2026-09-12。D-098限定release Completedを基準にした小さい利用者向け改善。設計・repository準備のみで、production未適用。
DIS-004/006/009、OPR-002を具体化する。D-081/086/087/089のnonce/CAS/revision、ACK-before-Admission、認可を維持する。

## 契約差分と根拠

- 署名・認可済みguild memberのuser IDと、nick → global_name → usernameの最初の名前を受付時に固定する。既存`requested_by.discord_user_id/display_name`を使い、公開は名前だけ。ID、role、tokenは公開しない。profile API・同期・新tableなし。
- Admissionの`discord`入力にoptional `user_id/display_name`を追加。旧3属性入力も受理する。名前がある場合はuser ID必須。名前なしを推測しない。operator/CLIはOperator、SCHEDULEはScheduled execution、Discord名前欠損は明示的縮退。
- 公開先は既存Discord由来Operationだけ。operator/scheduleのための新しいchannel routingを作らない。rendererはこれらのsourceも区別できるが、実配送経路を追加したという意味ではない。
- `OperationRepository.update_step`が既存revision更新と同じconditional writeで`progress_<step lowercase>_at`を`if_not_exists`保存する。許可stepは[固定10項目](../../src/wishicraft/progress_display.py)。最初の到達時刻を残し、再試行回数に比例して増えない。入れ子map作成の追加writeや旧record一括migrationは不要。
- 表示は既存requested_at＋実在する到達記録から直近4件。stream intermediateが省略されても保存された記録だけを読む。到達は完了を意味しない。正確な時刻や全step UIは表示しない。同時刻記録の厳密な実行順を保証しない。
- source/destinationは既存`switch_source.game_id`と`target_game_id`、Reset seed方針は既存`reset_seed_mode`。固定前のsourceはnot recorded。world/run/内部AWS情報は出さない。成功・失敗・timeout・CANCELLEDを分け、失敗を一律「failed safely」と呼ばない。
- 旧recordは欠損/NULLに対応。過去の経過・実行者を補完しない。malformed値を別対象として解釈せず配送errorにする。history属性はdisplay evidenceで、runtime/recoveryの正本にしない。
- 名前/自由文は長さ制限、制御文字除去、Markdown/mention escape。create/editとも既存`allowed_mentions.parse=[]`。メッセージはUTF-16換算2000以内を検証する。
- deliveryのexpected stale completion CAS判定を変更しない。別message/ownershipの競合はerrorのまま。配送失敗でbackendの再実行やresult変更を行わない。

## 表示例

以下はfixtureの記録に基づく例。実行者名は例示。各ブロックは一つの編集対象メッセージ。

```text
Minecraft START: Completed
Requested by: Haru (Discord)
Game: game-vanilla-main
Recorded progress (phase entry, not proof of completion):
• Request accepted
• Minecraft start processing entered
Online and ready.
```

```text
Minecraft SWITCH: In progress
Requested by: Haru (Discord)
Game: game-vanilla-main → game-vanilla-secondary
Recorded progress (phase entry, not proof of completion):
• Request accepted
• Save and graceful stop processing entered
• Minecraft start processing entered
Latest recorded phase: Minecraft start processing entered
```

```text
Minecraft RESET: Failed — completion not confirmed
Requested by: Haru (Discord)
Game: game-vanilla-secondary
Seed policy: new, fixed for this operation
Recorded progress (phase entry, not proof of completion):
• Request accepted
• Save and graceful stop processing entered
Check /mc status before retrying; contact an admin if the result is unclear.
```

```text
Minecraft STOP: Cancelled — not completed
Requested by: Scheduled execution
Game: game-vanilla-main
Recorded progress (phase entry, not proof of completion):
• Request accepted
Check /mc status before retrying; contact an admin if the result is unclear.
```

## 適用計画（全write未承認）

1. 承認時HEAD/CI/callerとControl Planeの実diffを再照合。START/STOP等の実操作・進行中message workerがない窓を使い、Command Lambdaの元concurrencyを記録して0にしdrainする。Admissionは元設定のまま。concurrency 0だけでdrain完了とは判定しない。一般受付への短い影響を伴う。
2. `WishicraftControlPlaneStack-dev`だけ、現行`two_games=true/reset=true`でdeploy。想定は既存Lambda code assetsのみ。host、IAM、workflow、環境変数、Game/data、Discord command bodyは変更しない。追加resource/権限差分が出たら停止。
3. code hash、Lambda更新状態、stack安定、両concurrencyをread-back。Command/Admissionの新旧入力の混在を閉じた窓で解消した後、Commandを記録した元設定（現在UNSET）へ戻す。Admission設定は変更しない。
4. dev操作チャンネルの人間から `/mc status` 一回。signed actor → ACK → Admission → saved record → public message一件 → delivery完了を確認する。停止のままの観測を用い、STATUS/Reconcileによる正規の観測更新だけを伴う。recordにない履歴を出していないこと、名前の表示とmention無効、既存状態表示を確認する。
5. 複数revisionの長時間進捗・各終端の網羅はrepository fixtureで確認する。本番長時間操作は次の自然な利用時に観測し、表示のためのSTART/STOP/RESET/BACKUPを追加しない。STATUSだけで全実操作のprogress E2E実証とはしない。
6. error/duplicate/stale terminal表示ならbackendを再送せず、同じOperation/message/revisionを観測。必要ならCommandを閉じて原因を調べる。data/result/履歴のraw repairはしない。元D-098実装を保つbaselineへのcode復帰は、同じdrainとdiff確認後の選択肢であり、今回の準備で実行しない。optional metadataは残してよく、過去D-098以前へdowngradeしない。

最終期待値は選択A/STOPPED/HEALTHY、受付元設定、DNS/Lock/未終了操作なし。STATUS由来の観測timestamp更新は正常。Snapshot/world/host変更0、Discord command登録0。追加恒久resourceやprofile API費用なし。既存Operationが最大10 timestamp属性（数百byte）増えるため、DynamoDB書込み/Stream payloadが課金単位を跨ぐ可能性はある。利用回数未固定なので月額を断定しない。Budget変更なし。

## 検証と文書責務

保存serializer → SDK Decimal round-trip →実loader →renderer →delivery/HTTP payloadをfixtureで確認。署名済みmember → ACK → Admission parser、旧NULL/属性なし、全公開種別・terminal分類、bounded milestones、既存revision/CAS/retryの回帰を含む。AWS/Discord実APIへの新表示の送信は未実施。

利用案内は[一か所](../discord_user_guide.md)へ集約。README/human flowは入口、Data/interfaceは本Proposed差分への参照、Delivery Plan/Decisionは未適用の位置づけを記録する。認可/runtime/state/security/AGENTS/working agreementは契約変更がないため変更しない。D-095〜098 runbook/evidenceは履歴として不変。whitelist/Web/Reset拡張/Phase 9全体は対象外。

## 準備結果

[証跡](../evidence/2026-09-12-discord-progress-preparation.json): 1068 tests、Ruff、mypy、5構成synth成功。実production templateとの比較は11 LambdaのCodeと対応するasset metadataだけ。IAM/environment/workflow/Host/command schema・永続resource差分なし。read-only preflightはstack UPDATE_COMPLETE、両受付UNSET、43 alarms OK。EC2内部やworldの再検証は今回行わず、D-098実証を再実行していない。

文字数とmentionの外部仕様は[Discord公式Message API](https://docs.discord.com/developers/resources/message#create-message)のcontent上限・allowed_mentionsを参照。UTF-16換算2000以内は今回の保守的なローカル検査であり、Discordへの実送信結果とは分ける。
