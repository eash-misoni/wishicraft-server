# D-099 Discordの実行者・主要経過表示（Accepted、限定release Completed）

2026-09-12。D-098限定release Completedを基準にした小さい利用者向け改善。ユーザーGOにより設計Accepted。production適用・実Discord STATUS一回の限定検証は完了。
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

CANCELLED例はrenderer fixtureであり、scheduled Operationの新しい公開配送先を追加したものではない。

## 適用計画（2026-09-12ユーザーGOで限定承認）

1. 承認時HEAD/CI/callerとControl Planeの実diffを再照合。START/STOP等の実操作・進行中message workerがない窓を使い、Command Lambdaの元concurrencyを記録して0にしdrainする。Admissionは元設定のまま。concurrency 0だけでdrain完了とは判定しない。一般受付への短い影響を伴う。
2. `WishicraftControlPlaneStack-dev`だけ、現行`two_games=true/reset=true`でdeploy。想定は既存Lambda code assetsのみ。host、IAM、workflow、環境変数、Game/data、Discord command bodyは変更しない。追加resource/権限差分が出たら停止。
3. code hash、Lambda更新状態、stack安定、両concurrencyをread-back。Command/Admissionの新旧入力の混在を閉じた窓で解消した後、Commandを記録した元設定（現在UNSET）へ戻す。Admission設定は変更しない。
4. dev操作チャンネルの人間から `/mc status` 一回。signed actor → ACK → Admission → saved record → public message一件 → delivery完了を確認する。停止のままの観測を用い、STATUS/Reconcileによる正規の観測更新だけを伴う。recordにない履歴を出していないこと、名前の表示とmention無効、既存状態表示を確認する。
5. 複数revisionの長時間進捗・各終端の網羅はrepository fixtureで確認する。本番長時間操作は次の自然な利用時に観測し、表示のためのSTART/STOP/RESET/BACKUPを追加しない。STATUSだけで全実操作のprogress E2E実証とはしない。
6. error/duplicate/stale terminal表示ならbackendを再送せず、同じOperation/message/revisionを観測。必要ならCommandを閉じて原因を調べる。data/result/履歴のraw repairはしない。元D-098実装を保つbaselineへのcode復帰は、同じdrainとdiff確認後の選択肢であり、今回の準備で実行しない。optional metadataは残してよく、過去D-098以前へdowngradeしない。

最終期待値は選択A/STOPPED/HEALTHY、受付元設定、DNS/Lock/未終了操作なし。STATUS由来の観測timestamp更新は正常。Snapshot/world/host変更0、Discord command登録0。追加恒久resourceやprofile API費用なし。既存Operationが最大10 timestamp属性（数百byte）増えるため、DynamoDB書込み/Stream payloadが課金単位を跨ぐ可能性はある。利用回数未固定なので月額を断定しない。Budget変更なし。

## 検証と文書責務

保存serializer → SDK Decimal round-trip →実loader →renderer →delivery/HTTP payloadをfixtureで確認。署名済みmember → ACK → Admission parser、旧NULL/属性なし、全公開種別・terminal分類、bounded milestones、既存revision/CAS/retryの回帰を含む。準備時はAWS/Discord実送信未実施。releaseでは下記STATUS一回を実証した。

利用案内は[一か所](../discord_user_guide.md)へ集約。README/human flowは入口、Data/interfaceは本契約への参照、Delivery Plan/Decisionは限定releaseの位置づけを記録する。認可/runtime/state/security/AGENTS/working agreementは契約変更がないため変更しない。D-095〜098 runbook/evidenceは履歴として不変。whitelist/Web/Reset拡張/Phase 9全体は対象外。

## 準備結果

[証跡](../evidence/2026-09-12-discord-progress-preparation.json): 1068 tests、Ruff、mypy、5構成synth成功。実production templateとの比較は11 LambdaのCodeと対応するasset metadataだけ。IAM/environment/workflow/Host/command schema・永続resource差分なし。read-only preflightはstack UPDATE_COMPLETE、両受付UNSET、43 alarms OK。EC2内部やworldの再検証は今回行わず、D-098実証を再実行していない。

文字数とmentionの外部仕様は[Discord公式Message API](https://docs.discord.com/developers/resources/message#create-message)のcontent上限・allowed_mentionsを参照。UTF-16換算2000以内は今回の保守的なローカル検査であり、Discordへの実送信結果とは分ける。

実装commit `d25d00ecb91cd815f7f4eeb6ff2d53eb0900f19d` の[CI 34698073795](https://github.com/eash-misoni/wishicraft-server/actions/runs/34698073795)はquality・既存実Docker integrationとも成功。後続はBACKUP停止中専用の案内・guide assertionと検証記録だけで、deploy asset差分を増やさない。当時予定した実Discord STATUS一回の結果は下記へ記録する。

## Production release承認

基準HEAD `9e217cdec7bb166de0271bffcaaac82d6e31d8d1` に対し、Command受付停止/drain、11 Lambda code限定deploy、元設定復元、人間の実STATUS一回、closeoutを承認。Admission設定・他の業務操作・登録・Host変更は対象外。表示由来の継続障害時だけ、同じdrain/diff確認とoptional属性互換性を条件に直前D-098 codeへの限定復帰を許可。設計Acceptedと適用完了は分ける。

## Production closeout（2026-09-12 UTC）

実適用HEAD `3df2b611b776fa64ff17233c061040eab1384df0`、CI `34699287419` 成功。実productionとの差分は11 Lambda Codeとasset metadataのみ。stack UPDATE_COMPLETE、全Lambda Active/Successful、配布zip内の全Python sourceと適用HEADを照合し、handler/runtime/role/environment等の不変を確認した。Host/Game/world/Snapshot、IAM/workflow、Discord登録は変更していない。

Commandは14:30:17 UTCに0、150秒のtimeout horizonと呼出しログ・Operation/Lockからdrain確認。Admissionは終始UNSET。適用後の停止・整合確認を経て14:38:15 UTCにCommandをUNSETへ復元した。

実Discord STATUS `op-5c7f82a9-987e-4b2b-b425-565affef83d3` は14:39:32.815870受付、`progress_reconciling_at=14:39:36.249977Z`、14:39:38.288229成功。Idempotencyの対応と新Operation一件を確認した。署名・認可済み経路から保存した実行者名は人間の表示報告と一致。ACK-before-Admissionは適用コードと実ACKを根拠とし、wire timingを採取した意味ではない。

公開message `1548342334507327489` をGETし、実recordを実loader/rendererへ通した投影と全文一致した。393 UTF-16単位、mention 0、delivery attempt 1、DELIVERED、source/delivered revisionはともに2。履歴は受付と実在するRECONCILING到達だけで、到達と完了を分けている。STATUSは非Lock操作のまま。

[production evidence](../evidence/2026-09-12-discord-progress-production.json)に最終read-backを集約する。全10種類の到達書込み、長時間操作の複数回編集、失敗/CANCELLED、特殊文字等は保存形式→loader→renderer→delivery境界testsの実証であり、今回の実AWS E2Eではない。追加業務操作、過去record backfill、過去message一括編集、手動配送replayは0。利用案内はrepository内のみで、Webやhelp commandを追加していない。
