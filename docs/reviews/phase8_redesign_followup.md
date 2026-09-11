# Phase 8後の再設計レビューと限定補足

- 状態: **Proposed / review record**。Accepted Decisionではない。
- 基準: `751bcdbfaed2312cb3e09825e8643426cdc7acfa`、Phase 8 Completed / Phase 9未着手。
- 今回の実装許可: 既存BACKUP契約の限定修正、boundary tests、隔離復元準備、文書、commit/CI。
- 未許可: AWS write、復元試験実行、Gameモデル・SWITCH/RESET・retention・whitelistの仕様確定と実装。
- 本書は前回レビューと追加フィードバックの統合保存先。元の会話や外部メモリを正本にしない。

## 維持する結論

目的は少人数・同時1Game・Discord中心という[既存scope](../01_product_scope_and_glossary.md)を、
実データ保護と途中失敗の回復を含め、小さな総負担で実現すること。
現在の制御面（認可、Admission、Operation、idempotency、Lock、Desired/Observed、正常保存停止）を
活かす。tableを統合しても整合条件や権限の責務は消えず、既存移行リスクが先に増えるため今は維持する。
START/STOP/BACKUPの権限・成功条件を巨大workflowへ統合しない。一方、1回のSWITCHの内部で
別START/STOPをadmitし直してLockを取り直す設計も避ける。

Package/Preset/Templateの独立管理は先行せず、不変runtime構成参照とGame作成設定から始める。
同一スペックに収まるGame間は同一EC2でruntimeを切り替える案が有力。実runtime停止・起動時間は残り、
目標時間は未確定。大きなinstance常用、予備EC2、proxy、同時複数runtime、汎用hooks、
multi-tenant、自動upgrade、chat bridgeは現在の必須要素ではない。

案内WebはEC2外の静的情報と時刻付き状態読取でよい。操作を追加するなら既存Admissionへ接続し、
Discord/Webから制御状態を直接書き換えない。Web管理機能一式は案内ページの前提にしない。

独立Data EBS、mount/volume identity、itzgへのMinecraft処理委譲を維持する。
復元UIは後回しにできるが、実データ移行・Reset前の復元試験は必要。
現在のSnapshot completedは取得成功であり、Minecraftとして復元できた証拠ではない。

## Fast Reset: 旧world整理の結論を変更

| 比較 | 利用・開発・障害時の負担 | 判断 |
|---|---|---|
| 上限到達で毎回手動cleanup | 実装は少ないが連続やり直しを止め、日常判断を管理者へ移す | 通常経路には推奨しない |
| Reset成功後の小さな自動cleanup | 所有・保護・容量条件は必要だが、正常時の手作業を除ける | 推奨候補 |
| 即時旧world削除／固定2領域の交互上書き | 容量は予測しやすいが、曖昧な完了・復帰先を壊しやすい | 不採用 |

別workflowや新サービスは前提にしない。Reset terminal確定後に同じ実行の後処理として呼ぶか、
次操作前の短い保守処理として呼べる。失敗しても成功済みResetをFAILEDへ戻さず、cleanup pendingを示す。
後処理中の次操作との競合は同じ排他で防ぐ。Reset結果の確定と所有権解放の順序は実装時に契約化する。

削除候補は、作成元OperationとGame/world identityを証明でき、currentでもpendingでもなく、
復帰に必要な保護参照も持たない旧領域だけ。現在の参照、進行中操作、保護参照を削除直前に再検証する。
対象ID固定でquarantineへ移してから内容削除する方法なら、途中失敗は同じ対象の残りだけを再処理できる。
symlink、未知path、所有不明は除外。空き容量不足を新worldの途中失敗で検出する設計にはせず、
準備前に余裕を確認し、安全な候補がなければ停止する。保持数・容量余裕・保護期間は未承認で「2」に固定しない。
quarantineは別backupではなく同じEBSの一部であり、EBS喪失への保証を増やさない。

### 認可

GameのReset対応と実行者の許可は別軸。admin-onlyを当然としない。
推奨候補は、管理者がGame単位にResetを有効化し、そのGameで遊ぶ承認済みplayer roleへ許可する方式。
操作確認は対象Game/現在worldを固定し、有効期限・再送identity・競合拒否を持たせる。
死亡判定の自動化、全員投票、複雑な所有者制度は先行しない。最後の確認時に他playerがいる場合の扱い
（警告付き同意または拒否）は価値判断。SWITCHも「start権限なら無条件で他Gameを止めてよい」にはしない。
普通のGameはReset無効を既定にできるが、具体的認可は未確定。今回は実装しない。

## Whitelist: Game内変更の保持を諦めない

前案は「Globalへの逆同期」と「Game内変更の保持」を近く扱いすぎていた。
共通とGame固有を別の編集責任にすれば、双方向同期なしでも後者は可能。

| 案 | 意味・同時編集 | 判断 |
|---|---|---|
| 共通リストを起動ごとに強制反映 | 一つの正本だがGame内変更を失う | 希望に合わない |
| 差分検出ごとに管理者が採否判断 | 変更は保護できるが日常負担が大きい | 例外回復用に限定 |
| 共通は初期値、Gameごとに完全な実リスト | 動的な合成や逆同期不要。共通変更は既存Gameへ暗黙適用しない | 最小案として推奨 |

推奨案の共通リストは「新Game/新worldへ渡す初期値」。Game稼働中の実whitelistはruntimeの正本とする。
ゲーム内commandはそのGameの実リストを変更し、Globalへ戻さない。外部編集も稼働中は同じruntime command
へ送り、DynamoDBにもう一つ独立したdesiredリストを作らない。標準commandを使い、ファイルを競合編集しない。
同じ人への相反する変更はruntimeが処理した順、外部UIは適用後再読込で表示する。全リストの置換は
稼働中に提供せず、追加/削除へ限定する。

EC2停止中の外部編集は初版では予約せず、「次回起動後に編集」と表示する。これにより停止中queueと
ゲーム内変更のマージを不要にする。共通変更を既存Gameへ一括伝播する機能も初版には作らない。
必要なGameへ「共通リストへ置換」を明示実行するなら、対象runtime停止または編集を排除できる保守時だけ。
Resetの初期whitelistは停止時のGame固有リストを引き継ぐ案が自然だが、これはgamerule/Plugin権限の
無条件引継ぎとは別契約。Game外から停止中編集やGlobalの即時伝播が必須なら、この単純案では不足する。
この編集体験そのものはユーザー判断として残す。

## Backupと復旧metadata: 保存機能を増やす前に単位を固定

共有EBS＋全体Snapshotは引き続き有力だが未確定。1Game/1EBSなら復元単位は揃うが、volume/attachment/
容量/移行負担が増える。Game archiveなら対象別retentionは明快だが整合取得・転送・復元経路が増える。
いずれも単なるtable/service数では選ばない。

Aだけ戻す場合、Snapshotから隔離volumeを作り、Aの必要データ一式を新しい領域へ抽出・検証し、
Aの参照だけを切り替える。live共有EBS全体を古いvolumeへ置き換えてはいけない。
Bの領域・参照は保持し、抽出前後にBの変更がないことを検証する。A/B間に共有書込データがあるPackageは
独立復元を保証できないので、共有領域の扱いが決まるまで対応扱いにしない。
今回のsingle-Game試験はAの抽出とsynthetic B sentinelまで。実multi-Gameの非干渉保証は後続試験。

### 復旧情報の比較

- **既存Backups provenanceへの不変な復旧情報追加**を第一候補とする。Game定義、world参照、runtime構成の
  不変参照/必要値を、そのSnapshotの証跡として保持する。実行時の第二の正本にせず、復元時だけ使う。
- 外部manifestは、DynamoDBの項目上限・artifactサイズ・制御store喪失時の独立保護が必要と判明した場合の候補。
  外部objectとDBのcommit点、孤児object、retentionという負担が増えるので、初めから必須にしない。
- EBS内manifestだけでは、停止中のControl Plane設定変更を含められず、Snapshotとの対応も検証が必要。

将来の取得時は全変更経路が同じ排他契約を守り、停止・保存済みデータと適用構成を照合してから
復旧情報を固定しSnapshotを取得する。未適用desiredはappliedと分け、どちらを復元するか明示する。
復旧情報の保存に失敗したSnapshotは「復旧セット完成」と表示せず、証跡と実Snapshotを残して同一対象を照合する。
Snapshot completedのみでprovenanceを捏造しない。新Snapshotを作り直して失敗を隠さない。

provenanceを非TTLで残すだけではDynamoDB自体の喪失を守れない。その保証が必要ならPITR/export等を別に比較する。
今回の既存Snapshot復元試験には、将来のmanifestを要求しない。[実行準備runbook](../runbooks/backup_safety_isolated_restore.md)参照。

## World参照: 意味を固定する案を維持

Proposed: current worldは「通常STARTが選ぶ永続対象」と定義し、「最後に正常起動した対象」と混同しない。
準備中候補はOperationに保持し、準備完了後のCASでcurrentを一度切り替える。READY前の変更であるため、
起動失敗ならcurrentは新worldのまま、Operation FAILED/Observed not-readyを表示する。
通常STARTは同じ新worldを再試行し、次のworldを生成しない。新seedもOperationで一度固定する。
旧world復帰は対象を指定した別操作で、新worldを保持してからcurrentを戻す。暗黙rollbackは行わない。

比較: 「最後に成功したworldをcurrent」とする案なら起動失敗でcurrentは旧worldだが、実runtimeが候補を
使っている期間にpending参照が別途必要になり、通常STARTが旧worldを動かす事故を防ぐ分岐が増える。
起動前のデータ準備検証と起動成功を分け、選択対象の定義を保つ前案を推奨する。
現行のgeneration最後確定契約とは異なるため、Accepted化も実装も今回は行わない。

## 依存関係と優先順位

```text
BACKUP安全性 + 隔離復元確認
                  |
対象Game/world/runtime起動identity + 古い命令排除 + 正常停止 + 再開契約
                  |                              |
         同一GameのReset                    複数GameのSWITCH
  新領域準備/初期設定/旧world整理       Game選択/構成解決/資源適合性
```

SWITCH完成はResetの必須前提ではない。Hardcoreが直近の利用目的なら同一Game Resetを先行できる。
二つのGameを頻繁に行き来するならSWITCH先行。共通基盤を同時に全面実装することはしない。

## Decision / delivery planの差分案（未適用）

2026-09-11のGOにより、既存Snapshotの隔離復元確認を実データ移行・Resetより前に置く順序だけはD-095でAcceptedとなった。以下の他の再設計案・retention gate案はProposedのまま。

- D-017の手動復元前提を具体化。D-048/D-090/BAK-004の「Restore試験はPhase 16」との関係を整理する。
- Phase 8のCompletedと過去証跡は維持。Phase 9開始前の独立準備sliceとして既存Snapshotの隔離復元確認を置く。
- Phase 16にはRestore UI/汎用workflowを残す。Phase 11の復元試験前提は維持。
- Snapshot実削除gateにも復元確認を必要とする案を提示するが、D-091の採否・retention実装は変更しない。
- Phase 9のPackage/Preset/Template一括一般化を、採択後に対象identityと実際のGame構成へ縮小する。

## 開発・承認

CDK→実handler環境、DynamoDB wire形式→domain、Operation→delivery loader、SDK transport、host identityを
少数のboundary testで検証する。長時間production E2Eは変更した保証に対応する場合だけ再実施する。
通常のローカル修正はslice内で委任し、外部writeは差分・停止点・rollbackをまとめて一回レビューする。
今回のrepo修正は[BACKUP契約補足](../05_data_and_interface_contracts.md#backup-create-reservation)とrunbookへ限定し、
本書のProposed内容の承認を含まない。
