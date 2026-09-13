---
title: 困ったとき
summary: 受付・進捗・完了を区別し、結果を確かめてから次の行動を判断します。
roles: ''
conditions: ''
warning: ''
---

## 応答がない・失敗と表示された

1. 元のメッセージを確認し、Discordで `/mc status` を実行してください。
2. 選択Game、観測Game、進行中の操作と状態を確認します。人数不明やunknownを0人・停止・正常に読み替えません。
3. 結果が不明なら、新しい要求で埋め合わせず、管理者へチャンネルのメッセージと状況を伝えます。特にReset・切替・BACKUPの送り直しを避けてください。

通知失敗とMinecraft操作失敗は別です。公開通知が来ないことだけでは、処理が行われていないとは断定できません。配送failureを直すためにbackend操作をやり直す必要はありません。

## 受付・経過・完了の違い

本人だけに見える受付応答と、操作チャンネルの公開進捗は別です。公開進捗は一操作につき一メッセージを編集します。
操作・Game・実行者、最新状態、記録された主要経過を数行表示します。

経過の「processing entered」はその処理への到達であり、保存や起動の成功証明ではありません。
`Completed`、`Failed`、`Cancelled`は別の結果です。`Cancelled`もあらゆる副作用を取り消したという意味ではありません。
名前・経過が古い記録にない場合は「not recorded」と表示し、後から推測で埋めません。

## 拒否された場合

Discordの指定チャンネルと必要role、Gameの選択、実行条件を各command詳細で確認します。管理者も操作チャンネルを使います。
条件を満たさない要求を連打しないでください。進行中の別操作がある場合は、その結果を確認します。

## 状況に応じた参照先

[状態の読み方](commands/status.md) / [起動](commands/start.md) / [停止](commands/stop.md) / [切替](commands/switch.md) / [BACKUP](commands/backup.md) / [Reset](commands/reset.md)

接続できない場合は [共通の準備](join.md) と [Game一覧](games.md) も確認してください。復旧用のDiscord commandは実装されていません。過去worldやSnapshotの復元は管理者の別作業です。
