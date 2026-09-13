---
title: /mc reset
summary: Resetが有効なGameのworldとプレイヤー状態を新しくし、同じGameでやり直します。
roles: Player / Admin
conditions: 対象Gameが選択中・稼働中・観測0人であること。明示確認とseed指定が必要。
warning: 地形・所持品・位置・進捗などが新しくなります。毎回の外部BACKUPは待たず、EBS喪失時は最後の外部BACKUP以降を失い得ます。
---

## 対象と実行条件

現在の対応Gameは下記に示します。対象が非対応・停止中・別Game稼働中の場合は実行できません。PlayerまたはAdmin roleと指定の操作チャンネルが必要です。
人数不明は0人ではありません。`confirm:true`があっても人数条件を省けず、直前確認後の接続raceが残ります。無切断保証や全員の合意確認ではありません。

## 現在の対応Gameと具体的policy

{{supported-games}}

上記の対応Gameの元の既存領域（anchor）は別枠の自動削除対象外として保護されています。各GameのReset非対応も[Game一覧](../games.md)で確認できます。

## 基本構文と使用例

新しくなる範囲と上の損失境界を確認してから使用してください。`game`・`confirm`・`seed`の三引数すべてが必須です。

{{examples}}

## 引数とseed

{{arguments}}

`fixed`は対象Gameのpolicyに設定された固定seed、`new`はその操作に固定される新seedです。同一操作の再開で抽選し直しません。
`seed`を省略してfixedにする動作はありません。新しい操作を送ることは、同一操作の再開とは別です。

## 新しくなるもの・残るもの

地形・dimension・playerの所持品/位置/進捗・world内gamerule/scoreboardは新しくなります。
停止した対象Gameの`server.properties`（seedを除く）、whitelist、存在するops/ban設定を引き継ぎます。他Gameの設定やworldは使用しません。
world内gamerule等を次worldの初期値に自動引継ぎする機能はありません。

## 実行中と完了後

対象Gameを保存・正常停止し、新しい保存領域を準備して参照を確定した後、同じEC2上で起動します。EC2の維持はMinecraftの起動待ちが不要という意味ではありません。
正常完了後は新しいworldで遊びます。通常のSTOP/STARTではこの同じ保存領域を使用し、再Resetにはなりません。

## 旧worldの保持と容量

currentに加え、対象Gameのpolicyで定める個数のmanaged旧worldを保持し、それ以前は成功後の限定自動整理対象です。
既存領域の保護anchorはmanaged旧worldの保持数と別枠です。未知の領域や処理途中の領域を一般的に掃除するものではありません。

準備前に、空き容量が **対象Gameのpolicyの最低空き容量と、現在の保存領域のファイル総量×2の大きい方以上** 必要です。
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

[backup](backup.md) / [switch](switch.md) / [start](start.md) / [stop](stop.md)
