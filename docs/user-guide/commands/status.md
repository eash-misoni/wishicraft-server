---
title: /mc status
summary: サーバーの状態を改めて観測して確認します。
roles: Player / Admin
conditions: 停止中も使用できます。
warning: ''
---

## 基本構文と使用例

{{examples}}

## 引数

{{arguments}}

## 結果の読み方

**Selected Game（選択Game）** は起動・切替で選んだ対象です。停止しても選択は残ります。
**Observed Game（観測Game）** は実際のruntimeから確認できた対象です。選択と観測が同じとは限らず、切替中や起動失敗時は異なる場合があります。

`Current Operation` は進行中の所有操作を示します。処理中の表示は完了を意味しません。
`unknown` は確認できない状態です。`none` や記録の欠損だけで「停止した」「正常」と判断しないでください。

STATUSは最新の観測を要求します。ただし現在のDiscord表示には**正確な観測時刻は表示されません**。メッセージの送信時刻や経過の到達記録を、実測時刻の代わりに扱わないでください。古い通知だけを現在状態の根拠にせず、必要な時点でSTATUSを使います。

## 到達記録と完了

公開進捗の「processing entered」は処理への到達で、保存や起動の成功証明ではありません。受付、処理中、Completed / Failed / Cancelledを区別します。

応答がない、unknownが続く、選択と観測の意味が分からない場合は、[困ったとき](../help.md)に従って管理者へ状況を伝えます。確認できない状態を別のSTART/RESETで補わないでください。

## 関連ページ

[Game一覧](../games.md) / [start](start.md) / [stop](stop.md) / [switch](switch.md)
