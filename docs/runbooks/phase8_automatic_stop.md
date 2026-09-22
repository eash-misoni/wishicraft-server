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

## Immutable Game authority for the final direct observation — 2026-09-22

The dev `vps-survival` SCHEDULE STOP
`op-f033bdd6-b435-49b1-b159-d25d8e314047` cancelled at 06:58:58 UTC with
`DIRECT_PLAYER_OBSERVATION_NOT_ZERO`. Existing SSM observations at 06:58:52 and
06:58:59 both showed Paper 26.1.2, READY and zero players. The saved latter response
fails the old expected-26.2 parser with `protocol version comparison is inconsistent`,
but passes at authoritative 26.1.2 with player_count=0. The deployed Stop task ZIP
matched the inspected source. This was a separate defect from Discord completion
supersession; cancellation occurred before Desired/Minecraft/EC2/DNS mutation.

### Authority path comparison

| Path | Expected package/version authority |
| --- | --- |
| START READY | Workflow ReconcileReady invokes shared Reconcile; `GamePackageAuthority.expected_version` validates observed receipt/Game/instance, consistent-read immutable registration, package digest/definition and fixed catalog. START still compares the complete observed target with its Operation. |
| Scheduled Reconcile | Same Reconcile factory and Game authority; selected Game/world checks remain separate. |
| Heartbeat | Fixed host probe verifies running receipt, Game/package and actual runtime through `game_package.observed`; producer requires matching Game/run/process and preserves unknown versus zero. No CP global-version parsing is added here. |
| Automatic-stop evaluator | Reads selected registered Game policy, SystemState and trusted fresh heartbeat; it does not parse host protocol/version. Warning/idle/intent contract is unchanged. |
| STOP final direct observation before fix | Handler rebuilt `AwsStatusFactory` after Operation binding without `expected_version`; `TargetStatusObserver._version` consequently selected `legacy_package()` (Vanilla 26.2), even for a valid Paper/NeoForge Game. |
| STOP final direct observation after fix | Same existing `GamePackageAuthority.expected_version` callback as Reconcile, enabled by the existing GAME_PACKAGES flag; raw RUNTIME_GAMES contains only the legacy compatibility IDs. The running receipt determines the Game to validate, while the gate requires the observed Game to match the STOP-bound Game and its intent/run/process. |

Only the STOP factory wiring changes. No new resolver, package pin, Game schema,
IAM permission, host artifact or State Machine logic is introduced. Legacy
pre-package deployments retain the explicit canonical Vanilla fallback. In package
mode, missing/corrupt/mismatched authority remains unknown; it never falls back.
Loader/build/artifact checks remain in the existing integrity-checked host probe.

`_automatic_gate_reason` is unchanged: READY, matching Game and exactly zero direct
players are required after lease, Reconcile, heartbeat, warning/idle, instance and
volume checks. Run/process matching is still required. The existing reason
`DIRECT_PLAYER_OBSERVATION_NOT_ZERO` remains an umbrella for non-ready, unknown,
wrong Game and nonzero count, not proof that someone connected. Unknown cannot be
converted to zero. Splitting this reason taxonomy is deferred; metric and alarm
names/thresholds are unchanged. Invalid Operation binding retains its existing
fail-closed failure path before the final observation; invalid observed authority
inside the gate cancels normally.

### Regression and release boundary

Tests use the real STOP handler, Operation binding, shared package authority and
host-response parser with synthetic DynamoDB/EC2/SSM boundaries. Every case must
reach the direct probe. Paper 26.1.2, legacy Vanilla 26.2 and NeoForge 1.21.1 zero
pass. Positive/unknown counts, returned Game/observed Game/package definition or
digest mismatch, missing registration, runtime digest mismatch, wrong version,
transport failure and run/process mismatch cancel. The same Paper handler test
against the prior adapter reproduces the original false cancellation.

The user authorized a combined dev release with the already qualified Discord
supersession commit `b54dae4`. Its earlier Message-only ChangeSet was correctly
held and deleted; this new authorization explicitly permits the existing Case D
semantic-no-op guard. Review all candidate changes and actual ChangeSet entries;
stop on IAM expansion, new resource, workflow semantic difference, Game migration
or unrelated properties. Preserve every existing Game/package/world/generation.

Apply the existing stopped release guard. If the current Game is running, confirm
fresh zero players before a formal normal STOP; never stop occupied/unknown runtime
for this validation. Close and restore the exact prior ingress concurrency settings
around the stopped release. After CI and reviewed release, formally START the same
Game and observe a fresh natural empty period, warning delivery, full 30-minute idle
and 5-minute warning interval, final direct observation and scheduled STOP.
Do not rewrite the cancelled intent, fabricate heartbeat/player data, shorten timers
or replay its idempotency key. A user joining takes priority and starts the normal
continuity rules. Production execution/results are recorded separately below.

Repository qualification: 1,611 tests passed, including 56 focused authority/STOP
boundary tests; Ruff lint/format, mypy (227 source files) and full-feature dev
Control Plane synth passed. The old adapter fails the new Paper handler regression
with the original false-cancellation reason. Synthetic fixture validation initially
stopped at a missing VolumeId; the fixture was corrected and every case now asserts
that it actually reached the direct probe. No production predicate was relaxed.
Production/CI results remain separate from this local qualification.
