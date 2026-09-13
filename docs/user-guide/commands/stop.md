---
title: /mc stop
summary: 現在対象を保存・正常停止し、MinecraftとEC2を停止します。
roles: Player / Admin
conditions: 他の所有操作との競合がないこと。0人条件の操作ではありません。
warning: 接続中の参加者にも影響します。実行前に同席者へ知らせてください。
---

## 基本構文と使用例

{{examples}}

## 引数

{{arguments}}

## 実行中と完了後

現在対象の保存を確認してMinecraftを正常終了し、EC2を停止して接続先を取り下げます。保存に失敗したときに強制停止するcommandではありません。
worldは保存領域に残ります。選択Gameも維持されるため、次の [start](start.md) で続けられます。

SWITCHはEC2を維持して別Gameへ移りますが、STOPはEC2停止まで行います。別Gameの起動は含みません。
STOP完了は外部BACKUP更新を意味しません。外部保護が必要なら正常停止の完了を確認し、管理者が [backup](backup.md) を実行します。

## 拒否・失敗・結果不明

保存・終了・EC2停止の途中で失敗した場合、一部の処理だけが済んでいる可能性があります。応答が途切れた時も停止完了と決めつけません。
新しいSTOPを再送する前に [status](status.md) を確認し、結果が不明なら管理者へ相談してください。[困ったとき](../help.md)を参照します。

## 関連ページ

[switch](switch.md) / [backup](backup.md)

## 現在の対応Game

{{supported-games}}
