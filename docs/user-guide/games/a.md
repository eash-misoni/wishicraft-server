---
title: A · {{a-name}}
summary: A専用のworldを保存するGameです。現在Resetには対応していません。
roles: ''
conditions: ''
warning: ''
---

## 版とclient条件

- Minecraft Java Edition **{{version}}** / Vanilla（A・B共通）
- 同じ版の標準Java clientを使用します。追加MODパックの指定はありません。
- Bedrock EditionやMOD入りclientの互換性は未確認です。
- コマンドで選ぶ名前：`{{game-id}}`

A・Bの保存領域は独立しています。BのResetでAのworldを新しくすることはありません。
難易度・gamemode・Hardcoreは未確認です。[参加方法](../join.md)でwhitelistと接続先の受け取り方を確認してください。

## 起動・切替の例

停止中はPlayer / AdminがSTARTできます。別Gameが稼働中なら管理者のSWITCHが必要です。SWITCHは観測0人と明示確認が条件で、直前接続raceが残ります。

{{game-examples}}

## 対応する操作

[status](../commands/status.md)で選択Gameと観測Gameを確認します。[start](../commands/start.md)は起動、[stop](../commands/stop.md)は保存からEC2停止までの操作です。
稼働中のBからAへ移るときは [switch](../commands/switch.md) を使います。
正常停止中の [backup](../commands/backup.md) はAだけでなく共有Data EBS全体を保護します。

Aは [reset](../commands/reset.md) の対象外です。Bとの違いは [B詳細](b.md) を参照してください。
