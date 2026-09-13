---
title: B · {{b-name}}
summary: B専用のworldを保存し、条件を満たせばResetでやり直せるGameです。
roles: ''
conditions: ''
warning: ResetはBのworldとプレイヤー状態を新しくします。旧world保持は外部BACKUPの代わりにはなりません。
---

## 版とclient条件

- Minecraft Java Edition **{{version}}** / Vanilla（A・B共通）
- 同じ版の標準Java clientを使用します。追加MODパックの指定はありません。
- Bedrock EditionやMOD入りclientの互換性は未確認です。
- コマンドで選ぶ名前：`{{game-id}}`

BはAとは別の保存領域を使います。難易度・gamemode・Hardcoreの実設定は未確認です。
[参加方法](../join.md)でwhitelistと接続先の受け取り方を確認してください。

## 起動・切替の例

停止中のSTARTはPlayer / Adminが使用できます。Aが稼働中なら管理者のSWITCHを使い、観測0人と明示確認が必要です。直前接続raceが残るため、同席者にも確認してください。

{{game-examples}}

## Reset対応と注意

Bが選択中・稼働中・観測0人の場合だけ、Player / Adminが明示確認付きでResetできます。停止中やAの稼働中は実行できません。
worldとプレイヤーの所持品・位置・進捗が新しくなります。毎回の外部BACKUPは待たず、EBS喪失時に最後の外部BACKUP以降を失い得ます。

具体的な引数、seed、引き継ぐ設定、旧world保持・容量条件は [reset詳細](../commands/reset.md) を実行前に読んでください。

## 関連する操作

現在の対象は [status](../commands/status.md)、通常の起動は [start](../commands/start.md)、保存して終了する場合は [stop](../commands/stop.md) を使います。
[切替](../commands/switch.md)は別Gameへ移る操作です。[backup](../commands/backup.md)は正常停止中に共有Data EBS全体を保護します。
[A詳細](a.md) と [困ったとき](../help.md) も参照してください。
