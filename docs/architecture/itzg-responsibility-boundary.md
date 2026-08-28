# Wishicraft / itzg 責務境界・採用方針

*Control Plane / Host Runtime / Minecraft Runtime の3層モデル
2026-08-22 改訂*

- **文書状態:** Canonical
- **適用時点:** Phase 1正式完了後のtarget architecture
- **履歴の扱い:** Phase 1のrunbook、決定、実装はas-built記録として維持する

本書は、Wishicraft が itzg/docker-minecraft-server を採用する際の責務境界と、Phase 1 完了後の移行方針を定義する。従来の「Wishicraft 対 itzg」という二分法ではなく、Control Plane、Host Runtime、Minecraft Runtime の3層に分け、機能追加・保守・移行時の判断基準を明確にする。Phase 1 の実装履歴は as-built として維持し、Phase 2 以降で Minecraft Runtime を段階的に itzg へ移行する。

## 1. 方針の要約

- Wishicraft は Control Plane として、ユーザー操作、認可、状態遷移、AWS リソース、コスト・運用ポリシーを担当する。

- EC2 上には Host Runtime 層を設け、Docker/Compose、EBS mount、Linux 権限、secret 注入、コンテナライフサイクルを担当する。

- Minecraft Runtime は itzg に委譲し、Minecraft 固有の取得・設定・互換性・起動・停止・Mod/Plugin 等を原則として独自実装しない。

- Wishicraft は desired state を保持し、それを itzg が受け取れる入力へ mapping し、いつ適用するかを orchestration する。itzg は与えられた入力を Minecraft 固有形式へ反映して実行する。

- 既存実装との重複があっても sunk cost を理由に残さない。成熟した itzg の責務に該当するものは、新経路で代替確認後に段階的に退役させる。

- 同じ設定値について複数の source of truth を持たず、Wishicraft と itzg が同じ Minecraft ファイルを双方から直接編集する二重管理を避ける。

## 2. 3層アーキテクチャ

```text
[ Control Plane: Wishicraft ]
Discord / API / Authorization / Step Functions / DynamoDB
EC2 start-stop / IAM / SSM / backup policy / desired state
desired state -> itzg input mapping / apply orchestration
                    |
                    v
[ Host Runtime ]
AL2023 / EBS mount / systemd / Docker / Compose
secret injection / bind mount / container lifecycle / host-local command path / logs
                    |
                    v
[ Minecraft Runtime: itzg ]
Java / Minecraft distribution / server.properties / RCON
whitelist / ops / Paper-Fabric-Forge / Mods / Plugins / Modpacks
Minecraft process / graceful shutdown
                    |
                    v
                 Minecraft
```

## 3. Control Plane - Wishicraft の責務

| **領域**         | **責務**                                                                                             |
|------------------|------------------------------------------------------------------------------------------------------|
| 操作受付・認可   | Discord 等から start/stop/reset/設定変更を受け、誰が何を実行できるか判断する。                       |
| 状態遷移         | 起動中・停止中・実行中などの状態、排他、失敗時の扱いを管理する。                                     |
| AWS リソース     | EC2、EBS、IAM、SSM、Security Group、DNS 等を管理する。                                               |
| 運用ポリシー     | いつ起動・停止・バックアップ・復元するかを決める。                                                   |
| コスト制御       | 無人状態等を根拠に EC2 停止まで含む自動停止を行う。                                                  |
| desired state    | Minecraft version、server type、許可プレイヤー、難易度等の論理的な希望状態を保持する。               |
| mapping / apply  | desired state を itzg の environment・file・command 等へ変換し、起動時反映か稼働中反映かを判断する。 |
| Secret lifecycle | RCON password 等を AWS 側で安全に保存し、取得権限・配布方法を管理する。                              |
| EULA gate        | EULA 同意を人間の承認事項として扱い、承認済みである場合だけ runtime へ同意状態を渡す。               |

## 4. Host Runtime の責務

- Docker Engine / Docker Compose の導入と version 固定。

- data EBS の初期化・XFS mount・/srv/minecraft 等のホスト側永続領域の準備。

- EBS mount 完了前に Minecraft container を起動させない mount guard。

- /srv/minecraft と container /data の bind mount。

- UID/GID、ファイル所有権、Linux permissions の管理。

- AWS から取得した secret を、必要最小限の形で container へ注入する処理。

- systemd 等による Compose/container の起動順序・停止順序・再起動方針。

- Control Plane から Minecraft command を実行するための host-local command path。RCON 等の管理 port は host/network へ公開しない。

- container logs、Docker 自体の health、ディスク容量等、Minecraft より下位のホスト監視。

- 外部公開 port の制御。原則として Minecraft 接続 port のみを publish する。

## 5. Minecraft Runtime - itzg の責務

- Java runtime と Minecraft/Java の互換性。

- Minecraft server distribution の取得・準備・起動。

- Vanilla、Paper、Fabric、Forge 等の server type 差異。

- server.properties の生成・反映。

- whitelist / ops 等の Minecraft 固有形式への反映。

- RCON および Minecraft command 実行の runtime 部分。

- JVM オプションの Minecraft 向け設定。

- Mods、Plugins、Modpacks、および対応配布プラットフォームとの統合。

- Minecraft process の監視と graceful shutdown。

- Minecraft 固有ファイルの生成・更新・version 差異への追従。

## 6. 境界の基本原則: Desired State / Mapping / Realization

Wishicraft は「何を実現したいか」を表現し、その希望状態を itzg が受け取れる入力へ変換する。itzg は、その入力を Minecraft が理解できる設定・ファイル・コマンドへ反映して実現する。Wishicraft は Minecraft の内部形式を可能な限り知らないが、itzg の公開設定インターフェースとの mapping は Wishicraft 側の責務とする。

| **要求**               | **Wishicraft が扱うもの** | **境界での mapping / apply**                        | **itzg が扱うもの**             |
|------------------------|---------------------------|-----------------------------------------------------|---------------------------------|
| Alice を参加可能にする | 許可プレイヤー = Alice    | whitelist 設定または稼働中 command へ変換           | whitelist の Minecraft 固有反映 |
| 難易度を Hard にする   | difficulty = hard         | itzg の設定入力へ変換し、必要な反映タイミングを判断 | server.properties 等への反映    |
| Fabric で動かす        | server type = Fabric      | TYPE 等の起動時入力へ変換                           | Fabric の取得・セットアップ     |
| Minecraft を停止する   | 停止を実行すべきか判断    | Host Runtime へ停止要求                             | Minecraft process の正常終了    |

## 7. Apply Strategy: 起動時設定と稼働中操作

desired state は、変更内容によって反映方法が異なる。Wishicraft は設定値そのものだけでなく、どの apply strategy を使うかを管理する。

| **区分**                | **代表例**                                                                   | **原則**                                                                           |
|-------------------------|------------------------------------------------------------------------------|------------------------------------------------------------------------------------|
| 起動時 / 再起動時に収束 | Minecraft version、TYPE、Mod/Plugin 構成、JVM 設定、起動時 server properties | Compose/environment/file 等の itzg 入力として反映し、必要に応じて restart を伴う。 |
| 稼働中にも即時反映      | whitelist、op、say、save、運用 command                                       | host-local command path から itzg/runtime の command 実行機構を利用する。          |
| 変更不可 / 承認が必要   | EULA 同意、破壊的 reset、restore 対象選択                                    | Control Plane の policy / human gate を通過した場合だけ実行する。                  |

- 「設定を保存した」ことと「running server へ反映済み」であることを同一視しない。必要なら desired / applied の状態を区別する。

- restart が必要な変更は、Wishicraft が明示的に状態遷移として扱う。itzg 側の自動更新や暗黙 restart に依存しない。

## 8. 例外的に Wishicraft 側へ残すべき Minecraft 関連判断

「Minecraft に関係する」という理由だけで全てを itzg へ渡すわけではない。システム全体のポリシー、ユーザー向け意味、AWS 側の安全性を持つ判断は Wishicraft に残す。

- 自動停止: プレイヤー不在等の情報は利用しても、EC2 停止まで含む状態遷移の判断は Wishicraft が行う。itzg の単純な autostop だけに委ねない。

- バックアップ: Minecraft を整合した状態にする具体的方法は Minecraft-aware なツールへ委譲できるが、取得時刻、世代数、保存先、restore 対象の選択は Wishicraft の運用ポリシーとする。

- whitelist: 誰を許可するかという desired state や操作権限は Wishicraft。whitelist.json 等への具体的反映は itzg/runtime。

- RCON secret: password の保管・取得権限は AWS/Wishicraft。Minecraft 側 RCON 設定への反映と利用は itzg/runtime。

- EULA: 同意の事実を誰が承認したかという gate は Wishicraft/operator。itzg は承認済み入力を受けて Minecraft を起動するだけとする。

## 9. Command Path / RCON の境界

RCON 等の管理 port を host や Internet へ publish しないことを前提とし、Control Plane から Minecraft command を実行する経路は Host Runtime 内に閉じる。具体方式は Phase 2 で固定するが、責務境界は次の通りとする。

```text
Control Plane
    -> SSM 等の管理経路
    -> EC2 Host Runtime
    -> container-local command execution
    -> itzg / RCON
    -> Minecraft
```

- RCON password を application log、shell history、Git、DynamoDB の平文値として残さない。

- command path の認可は Control Plane、secret の安全な受け渡しは Host Runtime、Minecraft command の具体的実行は itzg/runtime の責務とする。

## 10. Source of Truth と設定の所有権

同じ設定値を Git と DynamoDB 等の複数箇所で独立に管理しない。設定種別ごとに唯一の source of truth を定め、他の層はそこから生成・同期される派生物として扱う。

| **設定種別**                     | **原則の正本**                    | **例**                                                                                                   |
|----------------------------------|-----------------------------------|----------------------------------------------------------------------------------------------------------|
| デプロイ / 基盤固定値            | Git                               | itzg image tag/digest、Docker/Compose version、CDK、schema、固定 policy、環境ごとの immutable default    |
| 運用中に変更される desired state | DynamoDB 等の Control Plane store | whitelist、難易度、運用設定、Discord から変更可能な値                                                    |
| Secret                           | AWS の secret store               | RCON password 等。Git/DynamoDB へ平文で複製しない。                                                      |
| Minecraft 実ファイル             | data EBS 上の runtime data        | world、server.properties、whitelist.json 等。Control Plane の正本ではなく realization の結果として扱う。 |

- Git 管理する値と runtime desired state の境界は schema 上でも明示し、同じキーが両方に存在する設計を避ける。

- Minecraft 実ファイルを Wishicraft と itzg が双方から直接編集しない。必要な変更は desired state または itzg の公開入力経路を通す。

## 11. 既存実装の再分類

| **既存実装**                        | **新しい層**           | **方針**   | **理由**                                            |
|-------------------------------------|------------------------|------------|-----------------------------------------------------|
| VPC / subnet / IGW / Security Group | Control Plane          | 維持       | AWS 基盤                                            |
| EC2 IAM Role / SSM                  | Control Plane          | 維持       | 安全な管理経路                                      |
| 独立 data EBS / Retain              | Control Plane + Host   | 維持       | 永続データ基盤                                      |
| XFS / UUID mount / mount guard      | Host Runtime           | 維持・強化 | container 起動前の永続領域保証                      |
| Corretto 25 host installer          | Minecraft Runtime 相当 | 退役       | Java は itzg image へ委譲                           |
| server.jar URL/SHA-1 downloader     | Minecraft Runtime 相当 | 退役       | distribution 取得を itzg へ委譲                     |
| Minecraft systemd service           | Host Runtime へ再設計  | 置換       | Minecraft 直接起動ではなく Compose/container を制御 |
| RCON 用独自 nftables                | Host/Minecraft 境界    | 原則退役   | RCON port を publish しない設計へ                   |
| whitelist artifact 独自配置・修復   | Minecraft Runtime 相当 | 退役       | Minecraft 固有反映を itzg/runtime へ委譲            |
| Discord whitelist 操作              | Control Plane          | 維持       | 認可と desired state 管理                           |
| Step Functions / DynamoDB           | Control Plane          | 維持       | 状態遷移・排他・desired state                       |

## 12. 今後の機能の判定ルール

| **質問**                                                 | **原則の担当**           |
|----------------------------------------------------------|--------------------------|
| AWS の resource・料金・永続性に関係するか                | Control Plane            |
| ユーザー権限・状態遷移・サービス固有ルールか             | Control Plane            |
| desired state の正本・mapping・apply timing に関係するか | Control Plane            |
| EC2/Linux/Docker/EBS を安全に接続する処理か              | Host Runtime             |
| secret を host/container へ安全に受け渡す処理か          | Host Runtime             |
| Minecraft の version 差異や内部形式を知る必要があるか    | Minecraft Runtime / itzg |
| Java/Paper/Fabric/Forge/Mod/Plugin 互換性か              | Minecraft Runtime / itzg |
| 「いつ・誰が・なぜ実行するか」という policy か           | Control Plane            |
| 「Minecraft へどう反映するか」という mechanism か        | Minecraft Runtime / itzg |

## 13. itzg 採用時の固定・安全性ポリシー

- itzg image は浮動する latest 任せにせず、明示的な release tag を基本とし、必要に応じて digest まで固定する。

- Minecraft VERSION / TYPE 等のうちデプロイ固定値は Git、運用中に変更する値は Control Plane store とし、同じ値を二重管理しない。

- 自動更新は原則無効とし、更新は明示的な変更として dev 検証後に反映する。

- RCON 等の管理 port は host へ publish しない。

- container layer を永続データの正本にしない。Minecraft データは data EBS 上へ保持する。

- Docker daemon への権限は最小化し、一般ユーザーを安易に docker group へ追加しない。

- Wishicraft と itzg が同じ Minecraft ファイルを双方から直接編集する二重管理を避ける。

- secret は必要なプロセスへ必要な時間だけ渡し、log・environment dump・shell history 等からの露出を防ぐ。

## 14. Lifecycle Owner と再起動ポリシー

systemd、Docker/Compose、itzg、Minecraft の複数層が独立に restart を判断すると、Control Plane の停止要求と競合する可能性がある。各層の owner を明示し、上位の状態遷移を下位の自動 restart が打ち消さない構成にする。

| **対象**                     | **owner / 原則**                                                                        |
|------------------------------|-----------------------------------------------------------------------------------------|
| EC2 の起動・停止             | Control Plane。コスト・状態遷移を含む最終判断を持つ。                                   |
| Host Runtime の起動順序      | systemd 等。EBS mount 完了後に Docker/Compose を開始する。                              |
| container lifecycle          | Host Runtime で一元化。restart policy は Control Plane の停止意図と競合しない値にする。 |
| Minecraft process の正常終了 | itzg/runtime。十分な stop timeout を確保し、強制 kill を通常経路にしない。              |

## 15. 移行方針

1.  Phase 1 は正式完了として履歴を維持し、過去の実装を「なかったこと」にするための rewrite は行わない。

2.  現行 AWS 基盤と data EBS を維持したまま、dev に Host Runtime（Docker/Compose）を導入する。

3.  EBS mount guard の後段で itzg container が起動する構成を作る。

4.  最小構成で Minecraft の起動、接続、command、正常停止、再起動後の world 永続性を確認する。

5.  Wishicraft の desired state を itzg の設定インターフェースへ mapping する境界を作り、起動時設定と稼働中操作を分離する。

6.  RCON/command path を host-local に閉じたまま、Control Plane から安全に操作できることを確認する。

7.  新経路で代替できた独自 Minecraft runtime 実装を一つずつ退役させる。退役前に dev で機能同等性と回帰条件を確認する。

8.  既存テストを、Control Plane/Host Runtime として残す保証と、itzg へ委譲したため不要になる保証に分類して再設計する。

9.  Mod/Plugin 等の追加機能は、独自実装前に itzg の標準機能で実現可能かを確認する。

## 16. 現時点の未確定事項

AL2023 release/kernel/AMI、itzg image tag/digest、Docker/Compose、UID/GID 993、ownership migration、Host Runtime lifecycle owner/restart no、停止timeout、最小memory/OOM/graceful stopはD-060〜D-068で固定またはProvisional化し、dev実機で検証した。Phase 3ではread-only observation、active game、Reconcile、current SystemStateを完成した。残る設計事項は次のとおりである。

- Phase 4で運用中desired stateのwrite-side CAS/versionとOperation/Lock ownershipを確定する。

- Control Plane -> Host Runtime -> itzg への具体的 command path と secret injection 方法。

- whitelist 等について、起動時同期と稼働中即時反映をどう使い分けるか。

- バックアップ runtime として何を採用するか、および S3/EBS snapshot 等との役割分担。

## 17. 最終的な位置づけ

**Wishicraft は Minecraft runtime の再実装ではなく、Minecraft server infrastructure の control plane である。**

成熟した itzg を Minecraft Runtime として利用し、その上に AWS のオンデマンド計算資源、永続ストレージ、権限、状態遷移、Discord 操作、自動停止、バックアップ等を組み合わせる。Wishicraft は desired state、policy、orchestration、AWS との境界に集中し、Minecraft 固有の互換性・配布・設定処理を再発明しない。Host Runtime は両者を安全に接続する薄い実行基盤とする。

## 参考

- https://github.com/itzg/docker-minecraft-server

- https://docker-minecraft-server.readthedocs.io/

- https://github.com/itzg/docker-mc-backup

- https://docs.docker.com/engine/
