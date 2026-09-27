# D-114 resumed dev release — stage A deployed, stage B held

**Partial completion. Daily BACKUP remains provisioned but disabled.**
Stage A succeeded; stage B's ChangeSet failed the existing safety gate **before the formal
START/STOP pair**. No runtime proof or automatic acquisition is claimed.
[Structured commits, changes, identities and read-back](daily_backup_dev_stage_a_2026-09-27.json).
The [previous validation failure](daily_backup_dev_preflight_2026-09-26.md) remains historical evidence.

## Exact repository and assembly inputs

PR #2 reviewed HEAD `c22f408d3d950310b8fa5dbc15f3f8d5c1da6393` and base
`9f8bdf054077cce933b30f8af0498b184e0df2f0` matched the request. All five checks passed;
GitHub reported no separately configured required checks. Draft was removed and the PR was
normally merged, with exact-head matching and no protection bypass.

| Input | Commit | Tree |
|---|---|---|
| Reviewed PR #2 | `c22f408d3d950310b8fa5dbc15f3f8d5c1da6393` | `78d9cf21d23a0c342ff4fc4771f96326d99f0fb9` |
| PR #2 test merge | `fe15d6da2d1a498958a598c7dd3806f9f7a3ad46` | same |
| Actual merge / stage A source | `f17f5c9bc8f907b62803708ca0d689aff89a119a` | same |
| Stage B enabled-only configuration | `9f862bfe3856d3ec8d20b029a687361e1839c171` | `f3955856b80344fcbbb3e5b35bfc54a9ca93cec1` |
| PR #4 test merge | `fbd22020c5e943bc6e01e586913043bd839e3bfe` | same stage B tree |
| PR #4 actual merge / stage B source | `4576098a6aca172b045c509e150293d694348da3` | same stage B tree |

Stage A actual-merge [normal](https://github.com/eash-misoni/wishicraft-server/actions/runs/36290464564),
[NeoForge](https://github.com/eash-misoni/wishicraft-server/actions/runs/36290464552),
[Paper](https://github.com/eash-misoni/wishicraft-server/actions/runs/36290464570) CI succeeded.
Stage B candidate [normal](https://github.com/eash-misoni/wishicraft-server/actions/runs/36290568101),
[NeoForge](https://github.com/eash-misoni/wishicraft-server/actions/runs/36290568143),
[Paper](https://github.com/eash-misoni/wishicraft-server/actions/runs/36290568118) CI succeeded.
Its canonical true/true full suite also passed locally: **1961 tests**, 121.89 seconds.
Quality CI includes lint, format, typing and all historical/current CLI synth configurations.

Both assemblies were generated from committed canonical settings in separate worktrees with full
shared/RESET/CREATE/Whitelist/package contexts and **no daily_backup_validation override**.
Stage B was resynthesized from its actual merge; its template matched the candidate byte-for-byte.
Temporary tool links were removed; the stage A/B source worktrees are clean. The primary checkout's
unrelated Terralith documentation/evidence differences remain untouched.

- Stage A template SHA-256: `d5a59b7774887415720c49bcef578b247f43ec04b3600eebd7fcaffb3c552a63`.
- Stage B template SHA-256: `3e06496b97d694a90018f4000d172778d6c0a5da910ca7aba2162ca1a9c3b8bb`.
- Shared Lambda asset: `0ffe413b74738bd4a102eb4d72f892d29c5da1941c4d5b191b088f8705816a1e`.
- Bundled Discord Lambda asset: `fa87978b04eb784c5b6b4cbc57c3995dde73af8833e981e023d0175a59218549`.
- A→B source templates differ only in the nine expected enablement paths across eight resources.
  Lambda assets, IAM and State Machine Properties are identical between A/B.

The private evidence root is `/private/tmp/wishicraft-d114-resume-20260927.CluERA`.
It contains per-file immutable assembly hashes, original/property-evaluated ChangeSet pages,
ZIP/source comparisons, operation-free baseline/read-back and safe-closeout records.
Live Lambda configuration environment equality was checked in memory; those API maps and value
hashes were not saved or printed. A collector omission initially retained resolved public template
environment maps inside CloudFormation BeforeContext/AfterContext (24 stage-A and 4 stage-B
contexts). These maps were removed from the saved evidence during closeout, retaining variable
names and only the explicitly reviewed daily flags; property-change Details remain intact. No
secret-bearing environment map or environment-value hash was retained. Canonical source templates
and their required assembly hashes remain separate from live environment evidence.

## Fresh baseline and stage A

Initial SSO expiration stopped the first caller check. The user renewed wishicraft-dev; the new
baseline completed at **2026-09-27 03:09:56 UTC**, with the canonical account/region confirmed.
Selected vps-survival was the original world, generation 1 / counter 2, same immutable Paper
package. STOPPED/HEALTHY and actual EC2 stopped; no Current Operation/Lock, running workflow,
active SSM/session, DNS or unfinished maintenance. Three queues were empty, **51 alarms OK**,
13 snapshots, unchanged Games/creation/access/RESTORE journals. backup_protection was absent;
old snapshots were not treated as evidence of current protection.

Live template comparison allowed exactly 15 additions, 11 existing Lambda Code updates, and
PROTECTION_VOLUME_ID additions to Admission/StopTask/BackupTask. Existing IAM, SNS/KMS, alarms,
Game/runtime settings and State Machine Properties stayed unchanged. All eleven deployed ZIPs
(two distinct archives) matched actual deployed source `e233e9f`, rather than assuming repository
base `29c3231` had been deployed. The reviewed candidate also contains the already-committed
RESTORE comparison/reader files added before D-114; their source delta was recorded. They are
operator payload files, not a new helper installation or invocation in this release.

Stage A ChangeSet:

`arn:aws:cloudformation:ap-northeast-1:385526546525:changeSet/d114-stage-a-f17f5c9-20260927/78fc6b12-15fe-4dd4-9c31-b1c4086d846c`

The five allowlisted State Machine Definition entries passed Case D: Replacement=False,
Definition-only/Never, identical raw Properties/resolved and canonical ASL/Role/configuration,
and **raw ResourceAttribute dependencies naming the actually updated existing Lambda ARNs**.
Referenced identities were independently read back. Retention was not a final workflow change.
All pages and property values were saved; no previous exception was reused.

Only Discord Command and the Web handler concurrency were temporarily set to zero, preserving
Admin Admission, Auth, Observer, Reconcile and idle STOP. After a fresh stopped/idle/empty guard,
that same ChangeSet was executed once. The stack reached **UPDATE_COMPLETE at 03:22:59.308 UTC**.

Read-back verified all Lambda CodeSha256/handler/environment against published assets/template,
all inline IAM policies and role trust, six workflow identities/definitions/configurations,
existing SNS/KMS and 51 alarm configuration/action/suppression. New daily Lambda environments
were disabled, rule DISABLED, all five new alarm actions disabled. No snapshot was created.
Missing evaluator execution and still-absent protection were expected at this disabled stage;
formal START/STOP had not yet been performed.

## Stage B: the exact stop boundary

PR #4's enabled-only setting and its assembly/ChangeSet were prepared before START to avoid
lengthy preparation after normal STOP. Merging that configuration was not AWS enablement.

Stage B ChangeSet:

`arn:aws:cloudformation:ap-northeast-1:385526546525:changeSet/d114-stage-b-4576098-20260927/abab1d8e-de95-420c-8071-a26bbd20aefe`

Expected final changes were only the eight daily resources (nine property paths). The
property-evaluated result instead listed **13 modifications**, including unexpected Definition
updates for BackupStateMachine, ResetWorkflow, StartStateMachine, StopStateMachine and
SwitchWorkflow. Each was DirectModification/Static, Replacement=False, Definition/Never.
The non-property-evaluated response contained **no State Machine change entries** and therefore
no updated dependency evidence for these five changes. **Case D condition 3 fails.**

Equal A/B source Properties and already verified live ASL do not waive that condition. Opaque
truncated signatures were retained without reverse engineering or treating them as proof of
an actual semantic change. This is a ChangeSet authorization failure, not a claim that the
workflow body or daily BACKUP runtime failed. No guard relaxation, template editing, new body
fix, IAM expansion, alternate deployment or repeated ChangeSet attempt was used.

**Stage B was never executed. START/STOP were never submitted.** There is no new automatic
Operation, snapshot/provenance or PROTECTED evaluation to qualify. The prepared but unexecuted
stage B ChangeSet was deleted during safe closeout, after preserving its complete evidence.

## Safe closeout and unqualified work

At **03:31:23 UTC**, the canonical original Game/world/package and all Game records were unchanged.
STOPPED/HEALTHY, EC2 stopped, no Current Operation/Lock/running workflow/active SSM/session/DNS,
three empty queues, ended maintenance. All **56 alarms were OK**; the new five actions remained
disabled and existing 51 actions/maintenance suppression were unchanged. Thirteen pre-existing
snapshots and both provenance records were preserved exactly, as were RESTORE journals.
Both daily log groups had no invocation events. Release-window alarm history contained ten
configuration/state entries, no ALARM transition and no notification action. New alarm
initialization is consistent with disabled actions and missing-data settings; this is not a
positive notification-delivery test. No fake metric or alarm-state manipulation occurred.

Both restricted handlers were restored to their original **UNSET** concurrency; Admin Admission
remained UNSET throughout. No pending executable ChangeSet remained. AWS still exactly matches
stage A: provision=true/enabled=false. No emergency DisableRule or AWS rollback was necessary.
The closeout commit restores the repository's dev enabled=false setting through a normal PR,
so main also describes that safe disabled state. This is **not successful automatic-BACKUP
operation**; it is a deployed preparation with an unresolved enablement gate.

The stopped plan remains disabled deployment → one formal START/STOP → enable → one scheduled
BACKUP → at least two natural PROTECTED evaluations. Resumption requires review of the precise
stage-B ChangeSet gate; old exceptions are not authorization. No additional feature or lifecycle
redesign is proposed by this closeout.

Unperformed: dirty boundary tracking under real START/STOP, safe normal-STOP proof for this
attempt, periodic BACKUP/complete snapshot/shared recovery/provenance, duplicate suppression,
live DescribeExecution response-loss IAM, retry/failure/TTL/races, 30-minute/24-hour/heartbeat
failure notification delivery, idle STOP, snapshot mount/world-content/RESTORE verification.
The repository tests retain their narrower meaning. No snapshot was created or deleted;
retention is still independently dry-run-only. Costs were not measured. Existing historical
snapshots are preserved, but this attempt established no new external recovery point.
