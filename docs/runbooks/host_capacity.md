# D-107 Host capacity: guarded CloudFormation resize

**Accepted repository contract, 2026-09-14. Production policy installation and resize are deferred.**
The main branch keeps dev `t3a.medium`. This document does not authorize production writes.

## Capacity and ownership

`host_runtime.target_host.instance_type` remains the only deployment selector. The supported
values are `t3a.medium` (Light, 4 GiB), `m8a.large` (Standard, 8 GiB), `r8a.large` (Memory,
16 GiB), and `m8a.xlarge` (Heavy, 16 GiB). Names are explanatory labels, not configuration keys.
All Games share the deployed host. There is no Game profile, automatic resize, new host/resource,
application CloudFormation call, or runtime ModifyInstanceAttribute permission.

`StageConfig.target_instance_type` validates the allowlist; the Target stack explicitly renders
`AWS::EC2::Instance.InstanceType`. Null, unsupported values and profile labels fail closed.
Phase 1 `compute.instance_type` is frozen history. prod placeholders are not resolved.
The generic commit changes neither deployed nor requested capacity. A future release commit
changes only the dev Target type to `m8a.large`; review that commit and its CI before deployment.

Memory remains Xms 1G / Xmx 2G / container 2816MiB for all four types. itzg receives INIT_MEMORY
and MAX_MEMORY, and Compose supplies mem_limit. Increasing EC2 RAM alone does not increase heap.
A later memory slice must account for manifest hashes, CP/host config_digest, stopped receipts,
and D-105 creation.config_digest (including registered but unmaterialized Games), and recovery
metadata. Do not weaken digest checks or edit old records as a shortcut. A possible future
Standard starting point is heap 5 GiB / container 6 GiB, leaving 2 GiB outside the container and
1 GiB for non-heap memory inside it; this is not selected, validated, or deployed tuning.
Java 25/image/runtime version and modpack support remain unchanged.

## Exact preview and compatibility evidence

[Full preview evidence](../evidence/host_capacity_preview_2026-09-14.json) records a deleted,
unexecuted ChangeSet against the actual Target stack, baseline b59c672. Semantic JSON comparison
of the live and synthesized candidate templates found exactly one change:
`Resources.TargetInstance.Properties.InstanceType: t3a.medium -> m8a.large`.
No ImageId, AZ, SubnetId, KeyName, NetworkInterfaces, LaunchTemplate, CpuOptions, root mapping,
IAM, logical ID, attachment declaration, retention policy, or other property changes exist.

| Resource | ChangeSource | CausingEntity | Evaluation | Target.Attribute / Name | RequiresRecreation |
|---|---|---|---|---|---|
| TargetInstance | DirectModification | absent | Static | Properties / InstanceType | Conditionally |
| TargetDataVolumeAttachment | DirectModification | absent | Dynamic | Properties / InstanceId | Always |
| TargetDataVolumeAttachment | ResourceReference | TargetInstance | Dynamic | Properties / InstanceId | Always |

Both ResourceChange.Replacement values are Conditional. Attachment InstanceId is known after
apply because it references the changed resource; the template reference itself is unchanged.
Conditional is neither proof that replacement will happen nor proof that it will not.

Read-only EC2 observations: EBS-backed x86_64 HVM AL2023 6.18 AMI, ENA enabled, current boot UEFI
(AMI uefi-preferred), one ordinary ENI, default tenancy, no placement group, hibernation false,
enclave false. Both encrypted gp3 volumes are attached in ap-northeast-1a. Both families use
Nitro/NVMe and support EBS, x86_64/HVM and UEFI; the candidate supports the existing ENI/volume
counts. All four types are offered in that AZ. No availability reservation is implied.
Current CPU options are 1 core / 2 threads; m8a.large defaults to 2 cores / 1 thread and does
not support 2 threads/core. No CpuOptions property is introduced (it can require replacement).
Verify the resulting CPU options after any approved update; API observations alone do not
prove the provider's CPU-option transition behavior. Existing EbsOptimized=false is observed;
the candidates advertise default EBS optimization. Do not add an unrelated property change.

The AMI is available, Amazon-owned, x86_64/HVM, ENA-capable, and supports the host's boot mode.
These satisfy the API-visible conditions, not an end-to-end launch guarantee. Guest ENA/NVMe
driver versions, actual capacity, service quotas and runtime boot were not exercised. A stopped
host cannot provide fresh guest inspection without separately approved maintenance access.
The console's candidate selector and successful in-place resize are not reproduced by this review.

## Permanent policy and its boundary

Canonical policy files are `config/stack-policies/target.json` and
`config/stack-policies/data-volume-dev.json`. They are operator deployment inputs, not CDK
resources or automatically installed stack metadata. Main/CI/synth does not install them.

Target policy allows Update:* generally and explicitly denies Update:Replace and Update:Delete
on TargetInstance and TargetDataVolumeAttachment. Update:Modify remains allowed on both, including
reference reevaluation without physical replacement. A deny of all attachment updates would
unnecessarily block that reevaluation. Deny takes precedence over Allow. Under the AWS documented
action semantics, physical replacement requires Update:Replace and must be rejected, even if
in-place execution cannot succeed. Conditional may conservatively be rejected too: accept a
failed update, never relax the deny to force success. This behavior is specification-backed;
no real denied replacement or guarded resize has been executed in this slice.

Root EBS belongs to the instance's root block mapping; preventing instance replacement, preserving
that mapping byte-for-byte and prohibiting direct volume actions protects it during this resize.
It is still DeleteOnTermination=true; this is not a root backup or termination protection feature.

Data EBS `vol-03ac9f534326c345c` is owned by frozen MinecraftStack-dev logical resource
`MinecraftDataVolume30BACD41`, not by the Target stack. The second policy denies Replace/Delete
only for that resource in its owning stack, leaving unrelated updates alone. Apply it only after
reconfirming that exact ownership. Its existing DeletionPolicy and UpdateReplacePolicy Retain
remain defense in depth, not permission to replace. Target-only resize never updates the frozen
stack's template or the data volume. Data attachment retains its existing Retain attributes,
volume ID/device and instance reference. No detach, delete, replacement volume or whole-volume
restore is an acceptable recovery shortcut.

Stack policies govern stack updates only. They do not deny direct EC2/EBS APIs, deleting a whole
stack, or an administrator changing/overriding the policy. Keep the existing approval/IAM boundary;
no application IAM changes are introduced. Never use a temporary override or permit Replace in
this release. Capture an existing policy before setting one; if it differs, stop for review rather
than overwrite unknown protections. Future unrelated Target deployments must also read back the
canonical policy. Renamed protected logical IDs require a policy review before deployment.

## Production release preflight (separate approval required)

1. Finalized release HEAD/CI, tool availability and canonical wishicraft-dev caller Account ID
   must match config. Use a new evidence root, exact Target stack and explicit region/profile.
   Inventory current stack policy, template, parameters, stack status, physical resource IDs,
   root/Data volume IDs, sizes, encryption, devices, attachment flags and recovery evidence.
2. Drain admission using the existing maintenance procedure; capture and restore the exact prior
   concurrency settings. No active workflow/current Operation, no Lock (including stale leases),
   no SSM command/session activity, and all normal/delivery/DLQ queues empty, including in-flight
   or delayed messages. Wait for in-flight requests before assuming that admission is closed.
3. Require Desired STOPPED, EC2 stopped and consistent fresh Observed, DNS absent, successful
   graceful save/stop evidence with an exact stopped receipt and removed Minecraft container.
   Verify retained Data EBS identity/attachment and recent healthy backup/provenance with expected
   shared-volume membership. Do not infer a saved world from EC2 stopped alone. If save/backup
   evidence is insufficient, stop and obtain separately approved normal STOP/BACKUP work first.
4. Confirm canonical installed systemd/Compose/boot configuration from approved host evidence:
   targeted service has Restart=no, no Install/WantedBy/RequiredBy, no external enable symlink or
   boot caller; Compose restart is no; legacy minecraft.service is absent/disabled/masked and has
   no enable dependency; no container remains; /run runtime-run.env is volatile. Target CDK has
   no UserData that starts Minecraft. Docker boot alone cannot start an absent container. A
   timer starts only read-only heartbeat production. No application auto-START is introduced.
   Repository assertions establish the intended configuration, not arbitrary live drift. Missing
   or conflicting live evidence blocks resize; do not start the host merely to bypass this gate.
5. Repeat API compatibility/offering/quota checks for the candidate, and confirm no competing
   operator/deployment. Approve CF stop/start/restart explicitly: a stopped starting condition
   does not guarantee CloudFormation keeps EC2 stopped throughout the update.

## Policy installation, preview and execution

Only after explicit production approval (NOT performed by this repository slice):

```sh
tools/dev-env run -- aws cloudformation set-stack-policy --profile wishicraft-dev --region ap-northeast-1 --stack-name MinecraftTargetStack-dev --stack-policy-body file://config/stack-policies/target.json
tools/dev-env run -- aws cloudformation set-stack-policy --profile wishicraft-dev --region ap-northeast-1 --stack-name MinecraftStack-dev --stack-policy-body file://config/stack-policies/data-volume-dev.json
```

Read both back with GetStackPolicy and compare parsed JSON to their canonical files. Preserve
existing stronger policies by review, not by silently replacing them. These are permanent guards;
do not remove them after resize or on failure. No update of the frozen stack template is needed.

Use a reviewed release commit containing the explicit stage type change. Synth only Target to a
new directory; `cdk diff --method=template` compares it with live without making a ChangeSet.
Create an UPDATE ChangeSet using the exact synthesized template, existing parameter values and
required IAM capability. Do not use --all or deploy CP/Web/Frozen. After CREATE_COMPLETE, capture
GetTemplate for the stack and for that exact ChangeSet, plus every DescribeChangeSet page with
IncludePropertyValues. Compare the submitted ChangeSet template with the reviewed synth artifact.
Only InstanceType may differ semantically; any other diff stops the release.

The local checker requires the known stack/instance IDs from that release's independent inventory:

```sh
tools/dev-env run -- uv run python -m wishicraft.host_capacity_review --live "$CAPACITY_ROOT/live-template.json" --candidate "$CAPACITY_ROOT/candidate-template.json" --change-set "$CAPACITY_ROOT/change-set.json" --policy "$CAPACITY_ROOT/target-policy.json" --stack-id "$CAPACITY_STACK_ID" --instance-id "$CAPACITY_INSTANCE_ID"
```

Template inputs are decoded TemplateBody JSON objects; policy is the GetStackPolicy response.
ChangeSet must be a complete single response (NextToken is rejected); this resize should fit one
page. Do not discard pages to pass the checker. The checker permits only the documented two-resource
Conditional shape, fails for explicit replacement/extra triggers and requires the canonical policy.
It is an offline artifact check, not an execution command, approval, live safety probe or IAM simulator.

Read both policies back again immediately before executing the exact reviewed ChangeSet ARN and
repeat the preflight state/identity checks. ExecuteChangeSet has no temporary overriding policy
parameter. Keep admission closed and exclude concurrent deployment/policy writers through the
whole operation; file validation is not a distributed lock. If policy changed, stop. Execute only
under the permanent deny policy; normal rollback stays enabled. Observe saved stack events and
physical IDs until terminal state. If any replacement is needed, accept failure. Never override
the policy, use Retain to permit replacement, skip protected resources during rollback, or call
ModifyInstanceAttribute directly. Unknown outcome requires read-back of this execution, not a new
update. A failed/rollback-failed update is not a successful resize; preserve guards and data for
review. Policy installation/guarded execution require operator CloudFormation privileges only.

## Closeout and recovery

After UPDATE_COMPLETE, verify Instance ID, root/Data volume IDs, attachment physical identity,
volume properties, boot mode/CPU options and actual target instance type. Confirm template and
live InstanceType agree, no unexpected drift, and both policies remain canonical.
If CloudFormation left EC2 running, confirm Minecraft stayed stopped: no process/container/listener,
canonical inactive unit and same stopped receipt. Use the existing maintenance EC2 stop path only
under the resize approval, with the exact instance ID and stopped-runtime evidence. Do not invoke
START or fabricate a run/receipt; never force-stop an unexpectedly active Minecraft process.
If a process unexpectedly started, stop the resize closeout and use the normal graceful STOP
recovery under separate approval rather than cutting off writes.

Run the canonical Reconcile after EC2 is stopped (no raw state repair). Require Desired/Actual/
Observed STOPPED and HEALTHY, DNS absent, no active workflow/current Operation/Lock/SSM, all queues
empty, unchanged Games/world references/backup provenance, normal alarms after full evaluation
periods, and unchanged retained data identity. Preserve expected transient running alarms; do not
suppress them by editing thresholds. Restore the captured admission settings only after convergence.
Keep the permanent policies. Any rollback is an explicit reviewed IaC update with the same deny
policy and idle preflight, never an out-of-band resize. Root/data losses are not acceptable rollback.

## Validation and references

2026-09-14 local validation: 1,305 tests passed, Ruff lint/format and strict mypy passed;
all eight CI synth contexts succeeded. Generic Target live template diff is zero. Local Docker
CLI and shellcheck are unavailable; their existing Linux CI checks remain the integration gate.
The actual no-policy GetStackPolicy response was rejected by the offline checker as intended.
The positive policy fixture is synthetic and is not evidence of production policy installation.
The first full test run rejected a comment-only stage edit through the existing predecessor-byte
guard; removing that comment restored byte-identical stage config without weakening migration.
The CLI argument typing was corrected before the successful full rerun. Dependency wheels were
prepared through the canonical bundling-cache setup; final local gates used UV_OFFLINE=1.

Generic support has no synthesized Target resource difference at the retained t3a.medium setting.
Tests cover all supported types, invalid/null values, artifact/digest stability, exact template-only
change, canonical policy, missing/weakened policy, extra replacement triggers, resource identities,
ChangeSet freshness shape and no automatic canonical systemd start. Existing integration/CI covers
host lifecycle; there is no live reboot or replacement-denial integration in this slice.

- [AWS stack policy actions, explicit Deny and dependent resource updates](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/protect-stack-resources.html)
- [AWS InstanceType conditional update behavior](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-ec2-instance.html)
- [ExecuteChangeSet API parameters](https://docs.aws.amazon.com/AWSCloudFormation/latest/APIReference/API_ExecuteChangeSet.html)
- [CPU option compatibility rules](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/instance-cpu-options-rules.html)
- [itzg JVM inputs](https://docker-minecraft-server.readthedocs.io/en/latest/configuration/jvm-options/)
