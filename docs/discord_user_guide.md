# Wishicraft 利用ガイド

利用者向け説明の編集元は下のページ別Markdownです。Webは同じ原稿と現行設定/schemaから生成します。
生成方法と公開前の境界は [Web準備レビュー](reviews/user_guide_web.md) を参照してください。Web公開は未承認です。

- [共通の準備](user-guide/join.md)
- [Game一覧](user-guide/games.md)：[A](user-guide/games/a.md) / [B](user-guide/games/b.md)
- [コマンド一覧](user-guide/commands.md)：[/mc status](user-guide/commands/status.md) / [/mc start](user-guide/commands/start.md) / [/mc stop](user-guide/commands/stop.md) / [/mc switch](user-guide/commands/switch.md) / [/mc backup](user-guide/commands/backup.md) / [/mc reset](user-guide/commands/reset.md)
- [困ったとき](user-guide/help.md)

原稿の `{{…}}` はGame/runtime/policy/schemaからbuild時に置換します。具体値は設定正本を参照し、原稿やHTMLへ重複入力しません。

## 正本との対応

- 公開schema: [基本command](../config/discord/commands.v1.json)、[二Game拡張](../src/wishicraft/two_game_admin.py)、[Reset拡張](../src/wishicraft/reset_commands.py)。このガイドはcommand登録を変更しません。
- 認可・引数: [署名済みInteraction parser](../src/wishicraft/discord_interactions.py)、[Data/interface §19](05_data_and_interface_contracts.md#19-discord-operation-metadata)。
- 切替と共有保護: [D-097](reviews/two_game_switch.md)。Resetの範囲・保持・損失境界: [D-098](reviews/game_scoped_reset.md)、[B宣言](../config/reset-dev.json)。
- BACKUPの停止中専用条件: [BackupObservation](../src/wishicraft/backup.py)。
- 新表示の契約・適用記録: [D-099](reviews/discord_progress.md)。

whitelist管理、Web、汎用Restore、死亡自動検知等は、この利用可能コマンド一覧には含みません。

参加する場合はGame一覧から対象を選んでください。各Game詳細は共通構成と申請原稿を再利用して生成し、必要なclientと参加手順を一ページにまとめます。編集方法は[Webレビュー](reviews/user_guide_web.md)を参照してください。
