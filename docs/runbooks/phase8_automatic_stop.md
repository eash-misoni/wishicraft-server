# Phase 8 Automatic STOP operator runbook

## Scope

通常のautomatic STOPはD-093のEvaluator、shared Admission、既存STOP workflowへ委ねる。このrunbookは、pre-commit workflow failure後にOperation/owned Lock/Current Operationだけが残った場合の調査とcanonical stale recoveryを扱う。EC2、Minecraft、DNS、heartbeat、Game、Data EBS、Snapshotをrepairする手順ではない。

## Normal evidence

- warningは同一Game/boot/empty_sinceに一logical deliveryである。
- STOPは`RequestSource=SCHEDULE`、Operation type `STOP`である。
- `AutomaticStopFinalGate`の後にだけ`SetDesiredStopped`へ進む。
- final gateの安全な拒否はCANCELLEDであり、Desired/Minecraft/EC2/DNSを変更しない。
- FAILED/CANCELLED後は同一empty periodでwarning、intent、STOP Operationを増殖させない。

## Stale failed Operation recovery

raw DynamoDB write、Lock単独削除、Current Operation単独削除、deadline変更は禁止する。

1. exact Operation IDを固定する。
2. OperationがSTOP/SCHEDULE/PENDINGで、対応するStandard executionがFAILEDであることを確認する。
3. execution historyから`AutomaticStopFinalGate`へ到達し、`SetDesiredStopped`へ到達していないことを確認する。
4. global Lock owner、lease identity、Current Operationが同じOperationであり、対応AutoStopIntentが同じGame/boot/empty_sinceであることを確認する。
5. Operation deadlineが自然に経過するまで待つ。deadline、clock、leaseを変更しない。
6. fresh Reconcileで期待するDesired/Actual/Observed、HEALTHY、discrepancy/observation errorなし、canonical Target/Data EBS attachmentを確認する。pre-commit failureではruntimeがRUNNINGのままでよい。
7. operator entrypointをexact Operation IDで一度だけ実行する。

```console
.venv/bin/python -m wishicraft.operation_recovery_operator \
  --stage dev \
  --profile <canonical-deploy-profile> \
  --operation-id <exact-operation-id> \
  --execute
```

8. outcome不明時はblind retryせずconsistent readする。Operation FAILED、owned Lockなし、Current Operationなしの三点が完全一致した場合だけ成功へ収束したと判断する。
9. Desired、EC2、Minecraft、DNS、heartbeat、Game、Data EBSが変更されていないことを確認する。
10. 複数Evaluator cycleで同empty periodのwarning、intent、STOP Operation、executionが増えていないことを確認する。

positive proof、fresh Reconcile、deadline、ownership、atomic outcomeのいずれかを確認できない場合は停止する。新empty periodはplayer positive/unknown等で旧continuityが切れ、その後trusted zeroが観測されてから始まる。旧warningや旧idempotency identityを再利用しない。

## 2026-09-10 dev evidence

最初のSCHEDULE STOPはStop taskの`GAME_ID`環境不足によりfinal gateでFAILEDしたがcommit pointへ到達せず、runtime mutationは0だった。上記operatorが既存`OperationRepository.recover_stale()`を使い、historical Operation FAILED、Lock/Current Operation解放へ収束した。次のperiodはDynamoDB integer fieldが`Decimal`で復元されるtyped-boundary不整合によりpre-commit CANCELLEDとなった。finite integral Decimalだけを受理する修正後の新empty periodで、warning実deliveryから5分以上、idle 30分以上を待ち、fresh Reconcileと独立player-zero probeを通過してautomatic STOPがSUCCEEDEDした。
