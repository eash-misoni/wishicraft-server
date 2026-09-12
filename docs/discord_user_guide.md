# DiscordでのMinecraft操作

対象はdevの操作チャンネルです。ここは利用案内で、権限・保存・復旧契約の正本は末尾の参照先です。
Aは`game-vanilla-main`、B（Wishicraft Vanilla B）は`game-vanilla-secondary`です。同時に遊べるGameは一つです。

## 使えるコマンド

PlayerまたはAdmin roleが必要です。Adminも操作チャンネルを使います。

| コマンド／例 | 誰が使えるか | 状態・引数・処理 |
|---|---|---|
| `/mc status` | Player / Admin | 状態を改めて観測します。選択Game、観測Game、進行中操作を確認します。停止中も使用できます |
| `/mc start game:game-vanilla-main` | Player / Admin | 停止中に指定Gameを起動します。`game`省略は選択中Game。稼働中の別Gameを止めて切り替える操作ではありません |
| `/mc stop` | Player / Admin | 現在対象を保存・正常停止し、EC2を停止、接続先を取り下げます。SWITCH/RESETとは違い、0人条件の操作ではないため同席者に知らせてください |
| `/mc backup` | Admin | 共有Data EBS全体（A/B、保持worldを含む）をSnapshotで保護します。**正常停止中（STOPPED/HEALTHY）専用**です。稼働中は受け付けられても実行条件で失敗するため、先に通常STOPの完了を確認してください。作成・完了・復旧情報の検証を待ちます |
| `/mc switch game:game-vanilla-secondary confirm:true` | Admin | 稼働中のGameを保存・正常停止し、指定Gameへ切り替えます。`game`と`confirm:true`は必須。観測0人が必要。EC2は維持しますがMinecraftの保存・終了・起動時間は残ります |
| `/mc reset game:game-vanilla-secondary confirm:true seed:fixed` | Player / Admin | Bの新worldへやり直します。三引数すべて必須。選択中・稼働中・観測0人のBだけ。Aや停止中は非対応。`seed:new`も選べます |

STATUS以外は他の所有操作が進行している場合などに受け付けられないことがあります。
拒否された時に連打せず、まず状態を確認してください。人数不明は0人とは扱いません。
SWITCH/RESETの最後の0人確認直後に誰かが接続するraceは残ります。無切断保証や全員の合意確認ではありません。

## Resetで変わるもの・残るもの

`fixed`は具体値 **seed 0**、`new`はその操作に固定される新seedです。同一操作の再開で抽選し直しません。
新しい操作を送ることは、同一操作の再開とは別です。

地形・dimension・playerの所持品/位置/進捗・world内gamerule/scoreboardは新しくなります。
停止したBの`server.properties`（seedを除く）、whitelist、存在するops/ban設定を引き継ぎます。
Aの設定やworldをコピーしません。world内gamerule等を次worldの初期値に自動引継ぎする機能はありません。

currentに加え、直近3個のmanaged旧worldを保持し、それ以前は成功後の限定自動整理対象です。
最初の既存B領域は別枠の自動削除対象外anchorです。容量条件を満たさなければ旧worldを削って無理に続けません。

同じEBSの旧world保持と外部BACKUPは別の保護です。通常Resetは毎回の外部BACKUPを待たず、**EBS喪失時は最後の外部BACKUP以降を失い得ます**。
過去worldの復元は管理者の別作業で、Discord Restoreコマンドはありません。旧world整理とSnapshot削除も別です。Snapshotの実削除は公開していません。

## 受付・経過・失敗の見方

本人だけに見える受付応答と、操作チャンネルの公開進捗は別です。
公開進捗は一操作につき一メッセージを編集します。通知失敗はMinecraft操作失敗と同じ意味ではありません。

**表示改善案（D-099 Proposed、未deploy）:** 操作・Game・実行者、最新状態、記録された主要経過を数行表示します。
経過の「processing entered」はその処理への到達であり、保存や起動の成功証明ではありません。
`Completed`、`Failed`、`Cancelled`は別の結果です。`Cancelled`もあらゆる副作用を取り消したという意味ではありません。
名前・経過が古い記録にない場合は「not recorded」と表示し、後から推測で埋めません。

応答が途切れた、失敗と出た、公開通知が来ない場合は、まず`/mc status`で確認してください。
特にReset/切替/Backupの結果不明時は、同じコマンドを送り直して新しい操作で補わず、管理者にチャンネルのメッセージと状況を伝えてください。
配送failureを直すためにbackend操作をやり直す必要はありません。

## 正本との対応

- 公開schema: [基本command](../config/discord/commands.v1.json)、[二Game拡張](../src/wishicraft/two_game_admin.py)、[Reset拡張](../src/wishicraft/reset_commands.py)。このガイドはcommand登録を変更しません。
- 認可・引数: [署名済みInteraction parser](../src/wishicraft/discord_interactions.py)、[Data/interface §19](05_data_and_interface_contracts.md#19-discord-operation-metadata)。
- 切替と共有保護: [D-097](reviews/two_game_switch.md)。Resetの範囲・保持・損失境界: [D-098](reviews/game_scoped_reset.md)、[B宣言](../config/reset-dev.json)。
- BACKUPの停止中専用条件: [BackupObservation](../src/wishicraft/backup.py)。
- 新表示の契約案・承認計画: [D-099](reviews/discord_progress.md)。

whitelist管理、Web、汎用Restore、死亡自動検知等は、この利用可能コマンド一覧には含みません。
