---
title: /mc backup
summary: 共有Data EBS全体を外部Snapshotとして保護します。
roles: Admin
conditions: 正常停止中（STOPPED/HEALTHY）専用。
warning: 稼働中は先に通常STOPを完了してください。自動でSTOPする操作ではありません。
---

## 基本構文と使用例

正常停止と正常性を確認してから実行します。稼働中は受付されても実行条件で失敗するため、先に [stop](stop.md) の完了を待ってください。

{{examples}}

## 引数

{{arguments}}

## 保護する範囲と完了

共有Data EBS全体が保護単位です。A/Bのworld、保持している旧world、Gameのserver設定などをSnapshotへ含めます。一つのGameだけを指定する引数はありません。
Snapshotの作成・完了・復旧情報の検証を待ちます。受付や作成開始だけでBACKUP成功と判断しないでください。

**取得成功と復元実行は別です。** このcommandは現在のworldを書き戻す操作ではありません。Game単独復元は隔離した復元copyから対象Gameを取り出す管理者の別作業で、共有EBS全体の巻き戻しとは区別します。

## Reset・STOPとの違い

[reset](reset.md) の旧world保持は同じEBS内に残す仕組みで、EBS喪失から守る外部BACKUPではありません。
毎回のSTOP/RESETが外部BACKUPを更新するわけではなく、通常Resetも毎回の外部BACKUPを待ちません。

Discord Restoreコマンドはありません。旧world整理とSnapshot保持・削除も別です。Snapshotの実削除は公開していません。

## 拒否・失敗・結果不明

停止条件、正常性、他の進行中操作などを確認します。結果不明時はSnapshotが作られている可能性があるため、新しいBACKUPで補わないでください。
[status](status.md)と元のメッセージを確認し、管理者へ相談します。通知失敗だけを理由にbackend操作をやり直しません。[困ったとき](../help.md)も参照してください。

## 関連ページ

[A詳細](../games/a.md) / [B詳細](../games/b.md) / [stop](stop.md) / [reset](reset.md)
