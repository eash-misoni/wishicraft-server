---
title: /mc reset
summary: Bのworldとプレイヤー状態を新しくし、同じGameでやり直します。
roles: Player / Admin
conditions: 選択中・稼働中・観測0人のBだけ。明示確認とseed指定が必要。
warning: 地形・所持品・位置・進捗などが新しくなります。毎回の外部BACKUPは待たず、EBS喪失時は最後の外部BACKUP以降を失い得ます。
---

## 対象と実行条件

Bのみ対応し、Aや停止中、別Game稼働中には対応しません。PlayerまたはAdmin roleと指定の操作チャンネルが必要です。
人数不明は0人ではありません。`confirm:true`があっても人数条件を省けず、直前確認後の接続raceが残ります。無切断保証や全員の合意確認ではありません。

## 基本構文と使用例

新しくなる範囲と上の損失境界を確認してから使用してください。`game`・`confirm`・`seed`の三引数すべてが必須です。

{{examples}}

## 引数とseed

{{arguments}}

`fixed`は具体値 **seed {{fixed-seed}}**、`new`はその操作に固定される新seedです。同一操作の再開で抽選し直しません。
`seed`を省略してfixedにする動作はありません。新しい操作を送ることは、同一操作の再開とは別です。

## 新しくなるもの・残るもの

地形・dimension・playerの所持品/位置/進捗・world内gamerule/scoreboardは新しくなります。
停止したBの`server.properties`（seedを除く）、whitelist、存在するops/ban設定を引き継ぎます。Aの設定やworldをコピーしません。
world内gamerule等を次worldの初期値に自動引継ぎする機能はありません。

## 実行中と完了後

Bを保存・正常停止し、新しい保存領域を準備して参照を確定した後、同じEC2上で起動します。EC2の維持はMinecraftの起動待ちが不要という意味ではありません。
正常完了後は新しいBで遊びます。通常のSTOP/STARTではこの同じ保存領域を使用し、再Resetにはなりません。

## 旧worldの保持と容量

currentに加え、直近{{retain-previous}}個のmanaged旧worldを保持し、それ以前は成功後の限定自動整理対象です。
最初の既存B領域は別枠の自動削除対象外anchorです。未知の領域や処理途中の領域を一般的に掃除するものではありません。

準備前に、空き容量が **{{minimum-free-gib}} GiBと現在の保存領域のファイル総量×2の大きい方以上** 必要です。
これは将来のworld成長を予約する保証ではありません。容量条件を満たさなければ、旧worldを削って無理に続けません。

同じEBSの旧world保持と外部BACKUPは別の保護です。通常Resetは毎回の外部BACKUPを待たず、**EBS喪失時は最後の外部BACKUP以降を失い得ます**。
過去worldの復元は管理者の別作業で、Discord Restoreコマンドはありません。
旧worldのcleanupとSnapshot保持は別の寿命です。旧worldが整理されても過去Snapshot内に残る場合があります。Snapshotの実削除は公開していません。

## 失敗・結果不明・整理待ち

新worldの選択は起動成功より前に確定します。起動失敗時に自動で旧worldへ戻す保証はありません。選択だけで正常稼働と判断しないでください。
起動後の旧world整理が失敗した場合、旧データを保持して整理待ちになることがあります。無関係な領域を自分で削除しないでください。

応答不明や失敗時は、まず [status](status.md) を確認します。同じコマンドを送り直して新しい操作で補わず、管理者へ元のメッセージと状況を伝えてください。
管理者は同じ操作の結果を確認して次の行動を判断します。[困ったとき](../help.md)を参照してください。

## 関連Game・コマンド

[B詳細](../games/b.md) / [A詳細（Reset非対応）](../games/a.md) / [backup](backup.md) / [switch](switch.md) / [start](start.md) / [stop](stop.md)
