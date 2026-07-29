# 10. Codex Working Agreement

- **文書状態:** Canonical
- **最終更新:** 2026-07-23

## 1. 目的

Codexが推測で設計を変えたり、広すぎる変更を一度に行ったり、未確認の動作を完了扱いにしたりすることを防ぐ。

この文書は、Codexへ実装作業を依頼するときの恒常ルールである。

## 2. 作業開始前に読む文書

Codexは作業開始時に最低限次を読む。

Phase 0最初のrepository bootstrapだけはREADMEが未作成であるため、文書群を直接正本として開始してよい。README作成後は以後必ず読む。

1. `README.md`
2. `docs/09_decisions_and_backlog.md`
3. `docs/12_initial_configuration.md`
4. `config/project.yaml`
5. 対象stageの`config/stages/<stage>.yaml`
6. `config/secrets.example.yaml`
7. 対象機能に対応する要件
8. `docs/04_domain_and_state_model.md`
9. `docs/05_data_and_interface_contracts.md`
10. `docs/06_delivery_plan.md`の現在Phase

セキュリティ、AWS、運用へ関係する場合は`docs/07_operations_security_and_cost.md`も読む。

## 3. 正本と推測

- 設計、要件、契約、Decisionは文書群を正本とする。
- project共通値とstage別の具体値は`config/project.yaml`と`config/stages/<stage>.yaml`を正本とする。
- Parameter Store StringやLambda environmentの公開値を、YAMLと独立した手動設定の正本にしない。
- secretの実値ではなく保存先のParameter名は`config/secrets.example.yaml`を参照する。
- 会話、古いIssue、コメント、過去コードが正本と矛盾する場合、文書と設定を優先する。
- 文書と設定が互いに矛盾する場合、暗黙に選択せず作業前に報告する。
- `null`、`TO_BE_CONFIRMED`、文書にないARN、ID、secret、instance typeを推測しない。
- 不足が実装を妨げない軽微事項なら、安全なplaceholderまたは設定項目として切り出す。
- 設計判断が必要なら、コードへ埋め込まずDecision候補として提示する。

## 4. 1回の作業範囲

1回の依頼では、原則1つの明確な機能または契約だけを変更する。

適切な例:

- SystemState modelとunit test
- lock acquisition repository
- `probe_game.py`
- EC2 state取得adapter
- Start workflowのVerifyAdmission〜SetDesiredRunning
- Discord署名検証

広すぎる例:

- AWS全体を構築
- Phase全体を一括実装
- start、stop、backup、Discordを同時実装
- MOD対応を全loaderへ一括実装

作業が大きい場合、先に分割案を提示する。

## 5. 変更前の報告

コードを変更する前に、短く次を示す。

- 今回の目的
- 対応する要件ID
- 変更予定ファイル
- 新規作成ファイル
- 変更しない範囲
- 重要な前提

既存コードを読まずにファイルや構成を推測しない。

## 6. 実装ルール

### 一般

- domain logicとAWS SDK呼び出しを分離する。
- AWS、Discord、SSMをadapter/repository経由にする。
- functionを小さく保つ。
- stageごとに初期stackを1つとし、constructで責務を分離する。不要なstack分割を先行しない。
- secretを引数、ログ、exceptionへ露出しない。
- UTC時刻を使う。
- enumとerror codeを中央管理する。
- path操作にはresolverとallowlistを使う。

### Python

- 型注釈を付ける。
- dataclass/Pydantic等の採用は既存方針へ合わせる。
- broad `except Exception`で原因を隠さない。境界層では記録・変換してよい。
- mutable defaultを使わない。
- AWS SDK responseをdomain modelへ変換する。
- コメントは、コードから分からない理由や安全条件に限定する。

### Lambda

- 長時間sleep/poll loopを行わない。
- 冪等性を考慮する。
- timeoutを明示する。
- structured logにoperation IDを含める。
- 再試行可能errorと非再試行errorを区別する。
- Lambda environmentへsecret値を直接埋め込まない。

### Step Functions

- EC2、SSM、DynamoDB、Route 53の単純API操作はAWS SDK統合を優先する。
- Lambdaはdomain logicや複雑な変換が必要な処理へ限定する。
- Retry、Catch、Timeoutを明示する。
- AWS一時障害、domain conflict、timeoutを分ける。
- payloadへ巨大ログを蓄積しない。
- Wait/poll中にLockを期限より十分短い間隔で延長する。
- 副作用直前にLock所有権を確認し、喪失後は新しい副作用を実行しない。
- cleanup/release lockとCurrent Operation解除が所有者条件付きで実行されるようにする。
- failure pathでも実状態を再観測する。
- Desired State更新後のfailure cleanupでDesiredを暗黙に元へ戻さない。
- Discord progress metadataがないoperationではmessage作成・更新をskipできるようにする。

### DynamoDB

- 条件付き書き込みを使う。
- 競合Operation受付はTransactWriteItemsを使い、Idempotency、Operation、Lock、Current Operationを原子的に設定する。
- 同じidempotency keyの再送では既存operationを返し、新しいoperationを作らない。
- STATUS OperationはLockとCurrent Operationを使用しない。
- SystemState全体をPutItemで置換せず、Desired、Current Operation、Observed/Health、Last Errorを部分更新する。
- version/observed_atで古い更新を防ぐ。
- TTLを即時削除として扱わない。
- scan前提の設計を安易に追加しない。
- nullと0、unknownとstoppedを区別する。

### EC2スクリプト

- data volumeの期待mountを確認し、未mount時にMinecraft、backup、resetを実行しない。
- 任意shell commandを受け取らない。
- 任意pathを受け取らない。
- stdoutはJSON契約を守る。
- 同一operation ID再実行を考慮する。
- data volume mountを破壊的処理前に確認する。
- normal stopでsave失敗時に強制停止しない。

### Discord

- 署名検証を最初に行う。
- 長時間処理はDeferred Responseを返す。
- 受付後はBot Tokenで通常の公開進捗メッセージを作成し、message IDをOperationへ保存する。
- Interaction TokenをDynamoDB、Step Functions input、通常ログへ保存しない。
- internal error detailを公開しない。
- 権限不足と入力エラーは本人限定。
- Discord API失敗とMinecraft operation失敗を別に記録する。

### 管理CLIとworkflow開始

- Phase 5、6のCLI確認でも、Operation admission serviceを経由する。
- State Machineを直接開始してIdempotency、Operation、Lock、Current Operationを迂回しない。
- integration test用request IDを明示し、再実行時の既存operation取得を確認する。


## 7. テストルール

### Unit test

最低限、変更したdomain logicとerror pathを追加する。

重要対象:

- state derivation
- READY判定
- health判定
- lock condition
- idempotency
- timeout/error変換
- path/ID validation
- Discord authorization

### Integration test

AWSやEC2へ接続する作業では、実行手順と期待結果を示す。

- 実際に実行していない場合は「未実行」と明記する。
- console上の目視確認だけを自動test成功と表現しない。
- dev環境で確認してからprodへ進む。

### Regression

bug修正時は、可能な限り再現testを先に追加する。

## 8. 破壊的変更

次をCodex単独判断で実行しない。

- prod deploy
- EBS削除・detach
- S3 bucket削除
- DynamoDB table replacement
- EC2 terminate
- Route 53 Hosted Zoneまたはdomain削除
- Game/world削除
- backup lifecycle短縮
- IAM権限の大幅拡大
- Security Groupの公開範囲拡大
- secret表示・rotation
- force stop

コードやCDKへ変更を加える場合も、`cdk diff`で想定される影響を説明する。

## 9. Documentation更新

次を変更した場合、対応文書を同一作業で更新する。

| 変更 | 更新文書 |
|---|---|
| scope/priority | 01, 06, 09 |
| requirement | 02 |
| AWS構成 | 03, 09 |
| state/error/timeout | 04, 05 |
| schema/API/script | 05 |
| phase/acceptance | 06 |
| security/backup/cost | 07 |
| user flow | 08 |
| design decision | 09 |
| Codexルール | 10 |
| external service constraint | 11 |
| setting/naming/secret placement | 12, config |

文書とコードの不一致を「後で直す」として作業完了にしない。

## 10. 作業後の報告形式

作業完了時は次を示す。

1. 変更概要
2. 変更ファイル
3. 重要な実装判断
4. test結果
5. 実行していない確認
6. deploy/operation手順
7. 残課題
8. 更新した文書

大量のコード全文をチャットへ貼らず、必要なdiffや重要箇所を示す。

## 11. エラー時の姿勢

- 成功していない処理を成功と報告しない。
- AWS credential不足、外部接続不可、未デプロイ等を明示する。
- 失敗の原因が不明なら、確認できた層までを分けて報告する。
- 状態不明を推測で補完しない。
- ワールドやAWS resourceへ危険がある場合、安全側で停止する。

## 12. 禁止事項

- 文書を読まずに全面実装する。
- 旧設計を復活させる。
- 常駐コントローラーEC2を追加する。
- NAT Gatewayを暗黙に追加する。
- Elastic IPをDecision log更新なしに追加する。
- Minecraftホワイトリストを無効のまま公開ポートを運用する。
- DynamoDB値だけでREADY/STOPPEDを決める。
- TTL削除を待ってロックを解放する。
- Lambdaで数分間pollし続ける。
- user inputをshellへ連結する。
- RCON/SSHをinternet公開する。
- secretをコードやログへ書く。
- backup未検証でreset/delete/upgradeを実装する。
- WebSocketを管理Web初版の必須とする。

## 13. Codex依頼テンプレート

```markdown
## 目的

## 対象Phase

## 対応要件

## 今回の作業範囲

## 作業対象外

## 参照必須文書

## 完了条件

## 実行してよいコマンド

## 実行してはいけない操作
```
