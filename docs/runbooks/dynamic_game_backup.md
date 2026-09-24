# Dynamic Game BACKUP — IAM alignment

Repository fix for BAK-002/003/004 and D-105. Dev deployment and positive proof
are separate gates; no successful release is claimed by this design alone.

## Root cause and minimum contract

The deployed BackupTask accepts registry-backed Games and freezes shared-volume
recovery v2, but CreateSnapshot's request-tag policy still enumerated only legacy
A/B. The rejected create-terralith BACKUP is preserved in the
[historical pause](../evidence/game_restore_pause_2026-09-23.md).
D-113 Vanilla B RESTORE success did not repair this mismatch.

Only CREATE-enabled stacks add a `StringLike` Game-tag alternative: legacy exact
IDs or `game-` followed by 64 `?` characters. Each IAM `?` matches one character;
this is **not a regex, hexadecimal validation or registry lookup**. Missing/empty,
short and long IDs do not match. No current dynamic Game names/IDs are enumerated.
CREATE-disabled and single-Game configurations retain their exact prior policy.

The snapshot statement still requires exact Project, Stage, category `backup` and
protected `false`; its resource is the existing region-scoped, accountless EC2
snapshot ARN. A separate CreateSnapshot statement permits only the canonical Data
EBS's exact region/account/volume ARN. CreateTags remains conditional on
`ec2:CreateAction=CreateSnapshot`. No standalone retagging, DeleteSnapshot,
CopySnapshot, ModifySnapshotAttribute or CreateVolume permission is added.

Application authority remains mandatory: registry read on each invocation, exact
`game-[0-9a-f]{64}` registered identity, durable Operation target, ACTIVE Game schema,
package/creation identity and validated all-Game recovery data before creation.
A syntactically valid but unregistered ID can match IAM and is rejected by the
formal application path. Registry read errors are not legacy fallback; an absent
registry retains the pre-CREATE legacy contract. User tags are not accepted.
Registry additions therefore require neither another IAM list update nor deploy.

The snapshot is **the entire shared Data EBS**. Its Game tag identifies the selected
triggering Game, not an exclusive content boundary. Recovery metadata preserves all
registered Games, world references (including generation_counter), package/creation
and current access-policy evidence. Current authority is not replaced by that copy.

AWS references: [EC2 Service Authorization Reference](https://docs.aws.amazon.com/service-authorization/latest/reference/list_ec2.html)
lists both required CreateSnapshot resource types; [EBS policy examples](https://docs.aws.amazon.com/ebs/latest/userguide/security_iam_id-based-policy-examples.html)
show separate volume/snapshot permissions and creation-only tagging;
[EC2 tag-on-create](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/supported-iam-actions-tagging.html)
explains the additional CreateTags check. [IAM string operators](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_elements_condition_operators.html#Conditions_String)
define `?` as one-character wildcard. The application supplies stronger identity
validation than this deliberately limited IAM pattern.

## Validation and bounded release

Generated-policy tests cover legacy/single/CREATE-disabled and dynamic configurations,
exact source volume/region and all mandatory tag conditions, creation-only tagging
and unchanged EC2 actions. Real registry/freeze/create handler fixtures cover
create-survival, create-terralith, Paper IMPORT and another created Vanilla Game;
a subsequent registry addition uses the same process/configuration. Invalid registry,
unknown Game, broken record and package mismatch stop before snapshot create intent.
Existing admission/preflight, create-result-unknown, idempotency, provenance and
legacy recovery regressions remain required. These fixtures are not real AWS IAM proof.

1. Pin successful implementation CI and clean execution worktree. Save synthesized
   assembly/artifact hashes; preserve unrelated primary-checkout work.
2. Reconfirm canonical account/dev/region/EC2/Data EBS, STOPPED/HEALTHY, no work/Lock,
   SSM/session, DNS, queue messages or unfinished maintenance, and all 49 alarms OK.
3. Record/temporarily restrict existing ingress. Keep Observer/Reconcile and formal
   Admin Admission available. Create a new Control Plane ChangeSet and review all
   changes before executing that exact set. Prefer IAM-only if available. Shared
   asset Code changes require deployed-source review; dependency-only State Machine
   changes require every [Case D condition](ssm_ready_probe.md#case-d-release-guard--explicit-dependency-propagated-semantic-no-op)
   anew. Stop for other IAM, resource/replacement, workflow, configuration or stack changes.
4. Read back completed stack and real BackupTask policy/code. If vps-survival is not
   selected, use exactly one normal Admin START/READY/identity/STOP pair to select
   its existing world. No direct state edit, CREATE or other Game start.
5. Submit one normal Admin BACKUP with a fixed unique idempotency key and no explicit
   target_game_id. Wait for SUCCEEDED, completed/encrypted snapshot and matching
   Operation/snapshot provenance pair. Verify canonical source volume, selected Game
   tag and shared-volume recovery digest/full registry. Replay the successful same
   request and prove no new Operation/workflow/snapshot. Keep the valid snapshot.
6. Restore ingress, verify selected vps-survival STOPPED/HEALTHY and all original
   safety conditions. Preserve prior snapshots, D-113 journal and both Vanilla B worlds.

Result uncertainty requires read-back of intent, tags, workflow and provenance;
never blind CreateSnapshot retry or a fresh request. New core failures or broader IAM
requirements stop the slice; only already-authorized safe normal STOP/closeout apply.
Normal selection START/STOP saves are expected, not evidence of untouched world bytes.
No new host reader, snapshot mount/full-tree content proof, Paper RESTORE, automatic
BACKUP scheduling, retention deletion, host/package update or VPS operation is included.
