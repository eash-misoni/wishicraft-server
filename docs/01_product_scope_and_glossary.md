# 01. Product Scope and Glossary

- **文書状態:** Canonical
- **最終更新:** 2026-08-22

## 1. プロジェクト目的

プロジェクトの利用者向け名称は`Wishicraft`、Discord Botの表示名は`ゐしクラくん`とする。初期の固定接続先候補は`mc.wishicraft.net`とし、ドメイン取得前は設定上の予定値として扱う。

AWS上でMinecraftサーバーを必要なときだけ起動し、少人数の利用者がDiscordから安全かつ簡単に操作できる仕組みを作る。

主目的は次のとおりである。

1. Minecraft用EC2の常時起動費用を避ける。
2. 起動、停止、状態確認をDiscordから行えるようにする。
3. 保存漏れ、二重起動、停止漏れ、状態ずれを減らす。
4. 将来、複数ゲーム、MOD、Paper、旧バージョンへ拡張できる土台を作る。
5. 人間がAWSコンソールやシェルを日常的に操作しなくても運用できるようにする。

## 2. 対象利用者

### 一般利用者

- 登録済みゲームを起動する。
- 現在状態を確認する。
- 遊び終わったゲームを停止する。
- ゲーム一覧や接続情報を見る。

### Discord管理者

- 一般利用者の操作に加えて、ゲーム作成、バックアップ、reset、OP管理等を行う。
- 利用者向けエラーと内部エラーを切り分ける。

### システム管理者

- AWSリソース、IAM、ネットワーク、デプロイ、障害対応を管理する。
- SSM Session Managerを使用してMinecraft EC2を調査する。

### サーバーパッケージ作成者

- バニラ、旧バージョン、Paper、MOD構成を検証し、不変パッケージとして登録する。

## 3. システムの基本制約

- 利用人数は少人数とする。
- Minecraft EC2は必要時だけ起動する。
- 保存可能なゲームは複数とする。
- 同時に起動できるゲームは1つだけとする。
- 全ゲームで共通の固定FQDNを使用する。EC2の動的パブリックIPv4が変わっても、Minecraftクライアント側の登録アドレスを変更しない。
- 日常操作はDiscord中心とする。
- 詳細確認用Webページは後期フェーズで追加する。
- サーバー基盤は新規実装し、旧コードや旧AWS構成との互換性を要件としない。
- 公開設定はGit管理YAMLを正本とし、秘密値はParameter Store SecureStringへ保存する。

## 4. 初回実用版の範囲

初回実用版は、制御経路を端から端まで完成させることを優先し、機能を次に限定する。

### 含める

- 新規バニラゲーム1個
- Minecraft用EC2 1台
- Route 53の固定FQDNによる共通接続先
- EC2起動時のDNS Aレコード更新と停止時の削除
- 固定メンバーを手動登録したMinecraftホワイトリスト
- SSMによるEC2管理
- EC2内部の起動、停止、probeスクリプト
- 実測`status`
- Step Functionsによる安全な起動
- Step Functionsによる安全な停止
- DynamoDBによる状態、操作履歴、ロック管理
- Discord `/mc status`
- Discord `/mc start`
- Discord `/mc stop`
- 排他制御
- 操作履歴
- 最低限の監視とコスト通知
- Phase 8の検証済みbackup完成までの手動EBS snapshot runbook

### 含めない

- `/mc create`
- 複数ゲーム選択
- ゲームごとのEC2タイプ変更
- MOD、Paper、旧Minecraftバージョン
- `/mc reset`
- `/mc op`
- チャット連携
- 管理Webページ
- WebSocket
- 自動upgrade
- restoreの利用者向けUI
- 完全削除

## 5. 機能拡張の方向

初回実用版の後、次の順で広げる。

1. バックアップと無人自動停止
2. package、preset、template、gameの一般化
3. 複数ゲームと`/mc create`
4. reset
5. 旧バニラ、Paper、MOD
6. 管理Webページ
7. DiscordからのOP、ホワイトリスト管理
8. チャット連携
9. restore、upgrade、archive、delete

## 6. 用語

### ゲーム `Game`

利用者が実際に作成、起動して遊ぶ保存単位。

ゲームには次が固定される。

- ワールドデータ
- Minecraftバージョン
- サーバー種別
- サーバーパッケージとバージョン
- Javaランタイム
- ランタイムクラス
- Javaメモリ
- 自動停止時間
- 作成元テンプレート

表示名が変更されても内部`game_id`は変えない。

### サーバーパッケージ `Package`

Minecraftサーバーを再現可能に実行するための不変構成。

例:

- Minecraft server jar
- Paperビルド
- MODローダー
- MOD、プラグイン
- config、defaultconfigs
- 対応Java
- 起動方法
- backup/reset対象
- 能力宣言

同じ`package_version`を上書きしない。

### 作成プリセット `Preset`

ワールド生成時に利用者が選べる設定群。

例:

- サバイバル
- ハードコア
- クリエイティブ
- Seed
- 難易度
- ワールドタイプ
- 構造物生成

### テンプレート `Template`

Package、Preset、推奨ランタイム設定を組み合わせた、ゲーム作成方法。

テンプレートを更新しても既存ゲームへ自動反映しない。

### ランタイムクラス `Runtime Class`

具体的なEC2インスタンスタイプとJavaメモリをまとめた許可済み設定。

例:

- `small`
- `medium`
- `large`
- `heavy`

初回実用版では1クラスに固定する。

### Materialize

GameのメタデータとPackageから、EC2上に実行可能なゲームディレクトリを作成する処理。

`/mc create`の実装後も、作成時にはメタデータだけを保存し、初回start時にmaterializeする方針を基本とする。

### Operation

start、stop、backup、create、reset等の1回の操作記録。

操作には一意な`operation_id`を付け、実行者、対象、進行段階、結果、エラーを記録する。

### Desired State

システムが目標とする状態。

例:

- `STOPPED`
- 特定ゲームを`RUNNING`にしたい

### Observed State

AWS API、SSM、systemd、Minecraft応答等から観測した実状態。

保存値だけを実状態とみなさない。

### Reconcile

Desired State、保存済みObserved State、現在の実測結果の差を確認し、観測値を更新する処理。

初期版では、状態不一致を見つけても無条件に自動修復せず、正確な観測と通知を優先する。

### Control Plane / Host Runtime / Minecraft Runtime

- Control PlaneはWishicraftのユーザー操作、認可、状態遷移、AWS resource、desired state、運用policy、mapping/apply orchestrationを指す。
- Host RuntimeはEC2上のAL2023、EBS mount、Docker/Compose、systemd、secret injection、container lifecycle、host-local command pathを指す。
- Minecraft Runtimeはitzg/docker-minecraft-serverへ委譲するJava、distribution、Minecraft固有設定・形式・command・processを指す。

Phase 1の直接Java/systemd実装は完了済みas-builtとして維持し、この用語はPhase 2以降のtarget architectureへ適用する。

### Generation

同一Game内のワールド世代番号。

reset時に同じ`game_id`を維持したまま世代を増やす。


### 固定接続先 `Connection Endpoint`

Minecraftクライアントへ一度登録して使い続ける固定FQDN。

初回構成ではElastic IPを常時保持せず、EC2起動時に割り当てられた動的パブリックIPv4へRoute 53のAレコードを更新する。停止完了後はAレコードを削除し、古いIPを指し続けないようにする。

利用者向けにオンラインと表示するには、MinecraftのREADY条件に加えて、固定FQDNが現在のEC2パブリックIPv4を指していることを確認する。

### READY

EC2がrunningであるだけではなく、次を確認できた状態。

- SSM到達可能
- 対象ゲームのMinecraftサービスが起動
- Minecraft管理プロトコルへ応答
- 実アクティブゲームIDが要求対象と一致
- 固定FQDNが現在のEC2パブリックIPv4を指す
- Route 53変更が`INSYNC`

### UNKNOWN

確認不能な状態。

確認不能を`STOPPED`や正常状態へ変換しない。
