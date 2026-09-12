# D-098 対応Game限定Reset（Accepted、限定release Completed）

2026-09-12ユーザーGOで設計採用。同日、production適用・二回の隔離復旧・条件付き一般公開を完了。実証範囲は[closeout](../runbooks/game_scoped_reset_migration.md#production-closeout)を参照する。
D-095/096/097のAccepted・Completedを維持する。本書は現在の契約、runbookは手順・履歴、production evidenceは実測の正本である。

## 採用した利用方法

`/mc reset game:<対応Game> confirm:true seed:fixed|new` の一操作だけを公開する。
初版は、選択中かつ稼働中の対応Gameのみ。停止中、別Game稼働中、人数positive/unknownは副作用前に拒否する。
EC2を維持し、既存の保存・正常停止・exact container removal・起動を一つのOperation/leaseでつなぐ。
Gameの削除・再登録、worldファイルの選択削除、通常STOP/STARTの再Admissionはしない。

| 利用者判断 | 採用内容と負担・限界 |
|---|---|
| 有効化 | 管理者がGitの明示allowlistを承認し、CP/hostへ同じ宣言を配布。日常操作から変更できない。`config/reset-dev.json`にB限定の承認値を固定。A非対応、production反映は別途検証する |
| 日常の実行 | 既存PlayerまたはAdmin role。遊ぶ人が管理者待ちせず使える。ただし新worldへ移り旧worldは保持policyに従うことを明示確認 |
| 同席player | 最終観測0人、hostの停止直前RCONも0人。unknown/positiveは拒否。全員投票や死亡検知は追加しない。最後の確認後に接続するraceが残り、無切断保証ではない |
| 外部保護 | 毎回のSnapshotを待たず、旧領域を同じEBSへ保持。EBS喪失時は最後の外部BACKUP以降の進捗を失い得る。移行直前とrelease検証用BACKUPは別目的で計画する |
| 保持 | 直近3個のmanaged旧領域＋currentを保持し、それ以前を成功後に自動整理する。最初の既存`server`は永久anchorとして自動削除対象外。過去の例「2」は採用しない |
| 容量 | 準備前にfree ≥ max(4 GiB, 現保存領域のファイル総量×2)を要求する。これは将来のworld成長を予約する保証ではない。不足時は旧worldを削って続行しない |
| seed | `fixed`はGame宣言のsigned 64-bit seed、`new`はUUID由来Operation IDのSHA-256から決定するsigned 64-bit値。再試行で再抽選しない。承認されたBの固定seedは具体値0 |

既存のadmin-only SWITCHは他Gameを止める権限として維持する。Resetの有効化と日常実行を同じadmin-onlyにする案は、Hardcoreの反復操作を管理者へ集中させるため初版の推奨にしない。
全員接続中でもconfirmだけで止める案は手軽だが、他playerへの影響が大きいため採らない。

## 最小の正本と責務

| 情報 | 正本／意味 |
|---|---|
| 選択Game | 既存SystemState.desired_game_id。ResetではGameを変えない |
| 次に起動する保存対象 | Games.world.current_id。欠損は既存`games/<Game>/server`。追加後は`games/<Game>/worlds/<作成元Operation ID>/server` |
| 実行対象 | 既存runtime_targetのinstance/Game/data_source/config_digest/run_id。world identityはdata_sourceに一意に含まれ、別の重複fieldを増やさない |
| 一回のReset | Operation.reset_planにsource/target/seed/policyをcreate-only固定。同じGame、同じinstance/config、別run/pathを検証 |
| 実稼働 | 既存root-owned receipt、実container/StartedAt/bind、probe。Game一致だけでworld一致とはしない |
| 所有・整理の証拠 | EBS上のroot-owned `worlds/<ID>.owner.json`。作成plan、初期fileのhash、phaseを持つ。Minecraft UIDから書換不能。選択pointerではない |

新table、world管理サービス、Package/Preset/Template、汎用baseline、汎用cleanup workflowは作らない。
Reset workflowはD-097と同じ既存STOP/START graphを組み合わせ、準備・参照CAS・cleanupだけを追加する。
専用Lambdaは増やさず、Stop taskの限定責務として扱う。Game選択をcached Lambda Runtimeに残さず、毎呼出しOperationを読む。

現在worldは「選択した対象」であり、「最後に正常稼働した対象」ではない。
source停止とdestination準備の成功後、起動前にGames.world.current_idを条件付き更新する。
起動失敗時は新しい選択先と実runtimeなし／途中状態を表示し、HEALTHYを装わない。
通常STARTはこの同じ保存領域を新runで使う。旧runtimeが残る場合は先に対象を観測し、正常STOP可能か判断する。
旧領域への復帰を自動rollbackしない。未終了host命令を無視した参照書換えは認めない。

## 新しくするデータ／保持する設定

新領域は地形、各dimension、player inventory・位置・進捗、world内gamerule、scoreboardを一切コピーしない。
Minecraft 26.2の`world/players/data`を含む旧`server`全体はそのまま残す。古い`playerdata`想定による選択削除はしない。

保存・正常停止済みsourceから、`server.properties`、`whitelist.json`、存在する`ops.json`、`banned-players.json`、`banned-ips.json`だけを引き継ぐ。
`level-seed`のみ固定planの値へ変える。`level-name=world`以外やescaped key等の未対応設定は拒否する。
whitelistを共通設定へ逆同期せず、停止時点のGame内変更を次の領域へ保持する。ゲーム稼働中の外部編集は今回追加しない。
jar、logs、cache、usercache、RCON一時mountpointはコピーしない。固定imageが再準備する。
secret実値をOperation、所有記録、Git、ログへ入れない。Snapshotの暗号化された実データと復旧metadataは別である。

次worldに必要な設定は、この引継ぎ対象のserver設定と、宣言seedで明示する。world内gameruleやPlugin権限は引継がずVanilla初期値となる。
今回、任意shell・初期化hookやgamerule baseline管理を追加しない。

## 失敗・再開・整理

| 中断地点 | 残るもの／確認・対応 |
|---|---|
| 対象固定前 | sourceのみ。非対応・別Game・人数不明等では保存/停止/参照変更なし |
| sourceのsave/stop失敗 | source、既存receipt/stop proofを保持。destinationへ進まない。通常STOPの対象確認を緩めない |
| 新領域準備中 | root-owned preparing記録を先にfsyncし、同じIDへ設定を準備。既存fileはhash一致だけ再利用。未知file・symlink・内容差では止まる |
| 準備後・参照CAS前 | sourceが選択対象。新領域はpreparedとして残る。同一planとSSM結果から続行する |
| CAS応答喪失 | Gamesをconsistent read。exact新IDなら確定済み。旧/別値なら推測せず停止 |
| 新起動中／応答喪失 | 新領域、固定run、receipt、実containerを観測。initialized領域のlevel.dat欠損を新規生成として扱わない。未終了命令を別runへ置き換えない |
| READY後cleanup失敗 | 稼働成功を取り消さずcleanup_pendingを結果へ記録。旧データを保持し、次の成功Resetの整理で再評価。無関係な領域を手動で削らせない |
| cleanup中断 | deletingを記録してからexact managed serverだけ削除し、親directory fsync後deletedを記録。応答喪失後は同じ所有記録と実在を再照合。owner記録は削除しない |

cleanupは全ancestor chainの所有を検査して候補を固定し、current、直近保持対象、protected、preparing/未知領域、legacy anchorを削除しない。
名前検索の結果やmtime順では認定しない。symlink/hardlink/別mount/special fileは拒否する。fdベースの安全なrmtreeがある環境だけを使用する。
ホスト排他とglobal leaseは準備・正常停止・cleanupまで維持し、その後にOperationを確定・Lockを解放する。
通常のファイルcleanup失敗は通知可能なpendingにする。SSM送信・結果が不明ならOperation/leaseを保持し、成功済みとして解放しない。

新SSM作成はOperation内のdispatch予約＋SDK総試行数1。予約だけ残る場合は自動再送しない。
予約保存後・送信前にprocessが落ちた場合は、未送信と送信結果不明を区別できないため自動再開できない。この例外はデータ保持して止める範囲であり、全失敗点の自動回復を保証しない。
これはexactly-once一般基盤ではなく、作成結果不明を止める小さな境界である。再開時は同じOperation/SSMの結果を観測する。
通常START/STOPで収束できないreceipt/未終了命令は、既存のstale Operation recovery条件を含めoperator観測が必要となる。
foreground準備の確定非zero終了は既存owned failureへ終端化し、選択した旧worldを通常STARTで再開できる。timeout/cancel/結果不明はこの確定失敗へ含めない。
失敗した準備領域は通常成功のancestor chain外なら保持する。失敗証跡や未知領域の自動掃除はしない。

## BACKUPと復旧の差分

D-097のSnapshot単位・tags schema v2・共有newest 7・dry-run-only RETENTIONを変えない。
復旧JSONは既存Games.world全体に任意のcurrent_idを含め、data_sourceとの一致を検証する。
旧JSON/旧digestを書換えず、current_id欠損なら旧固定pathとして読む。
current以外の領域・owner record・deleting/deletedの状態はSnapshot内のEBSに含まれる。
これによりOperation監査がなくても、選択参照はprovenance、所有と実データはSnapshotから再構築できる。

同じEBS上の旧worldはEBS喪失からの保護ではない。またlive directory削除後も過去Snapshot内にデータが残り得る。
Snapshot保持とworld directory保持は別の寿命であり、今回DeleteSnapshot能力は追加しない。
今回のshared v2復旧点では、A単独抽出とB非干渉、さらにB新currentのowner chain付き抽出・保存再起動を隔離copyで実証した。本番への上書き復元、任意の将来構成、削除済みworldの復元まで実証したわけではない。[実行証跡](../evidence/2026-09-12-reset-production.json)を参照する。

## 現行文書との差分

既存`world.generation`はlegacy記録として残し、Reset回数や現在worldのidentityへ流用しない。新しい選択の正本は`current_id`だけである。
RESET-001の連番generation増加、RESET-002と旧domain/deliveryの毎回最終BACKUP・Reset後停止は、D-098で置換した。旧記録は当時の仕様として保持する。
Reset以外のwhitelist、Web、異なるruntime、Phase 9全体は対象外。
実装・テスト結果は[準備証跡](../evidence/2026-09-12-reset-preparation.json)に集約し、ここをproduction完了証跡にはしない。


## 文書の責務と確認結果

READMEは適用済み機能の入口、要件はRESET-001/002の置換、architecture/domain/dataは新しい選択参照・実観測・復旧情報へのAccepted参照を持つ。契約詳細は本書へ集約し重複定義しない。
Delivery Planは一利用機能の完了と復旧条件を示し、operations/human flowは削除単位・有効化と日常操作の違いを参照する。DecisionsはD-098 Acceptedと限定release完了を区別して記録し、initial configurationはGitのB限定宣言を参照する。
AGENTS.mdとCodex working agreementは既にローカル実装の委任・一括production承認・Wiki triggerを満たすため変更しない。D-095/096/097 runbook/evidenceは実行履歴として保持し、未実行Resetの成功証跡を追記しない。Phase8 reviewは次期具体案への参照だけ追加する。
Reset以外のwhitelist再設計、Web、異なるspec/runtime、旧Snapshot削除、Resetの自動死亡検知等は引き続き未採用である。
