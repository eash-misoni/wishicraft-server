# BACKUP safety / isolated restore approval plan

**Execution authorized by user GO, 2026-09-11. Results are recorded in the closeout section.**
Phase 8 remains Completed and Phase 9 remains unstarted. Proposed redesign choices are
[kept separately](../reviews/phase8_redesign_followup.md). This plan does not accept them.

## Execution closeout — 2026-09-11 UTC

**Completed: scoped BACKUP deploy/read-back and isolated recovery of the existing world.**
The only newly Accepted design decision is D-095's restore-test ordering. Other redesign
choices remain Proposed. [Sanitized execution evidence](../evidence/2026-09-11-backup-safety-isolated-restore.json)
contains exact resource IDs, CommandIds, reply evidence and limitations.

Control Plane's final update/read-back completed by 04:55 UTC. All 128 physical resources
were accounted for, 11 Lambdas were Active/Successful, BACKUP definition matched the
resolved synthesis, and ConditionCheckItem remained limited to wc-dev-locks. No replacement,
deletion, new resource or additional permission was introduced into the Control Plane.
BACKUP CodeSha256: `Stgyhf06ngccS+auBfXSfpI8M2oM12Xupc+6fF0naCg=`.
No new BACKUP, Snapshot, forced replay or redrive was executed. Installed boto3/botocore
1.43.91 SDK boundaries were tested locally; the managed Lambda SDK version is unmeasured.

The first deployment failed because an unreachable `SetVerificationFailure` remained.
AWS rejected the definition and CloudFormation completed automatic rollback at 04:26 UTC.
No new creation reservations or running workflows existed, and the predecessor template
and source evidence were confirmed unchanged. Removing that unused state reproduced a
failing-to-passing reachability test; AWS ValidateStateMachineDefinition then returned OK.
Further review found missing Catch ResultPath in observation/create failure paths. These
now preserve Operation/lease input at `$.workflow_error`; a focused boundary assertion
covers every failure-recording Catch. The final additional deployment changed only those
three Catch fields. See [AWS's Catch input preservation semantics](https://docs.aws.amazon.com/step-functions/latest/dg/input-output-resultpath.html#input-output-resultpath-catch).

Separate temporary stack `wc-isolated-restore-20260911-b2022225` was created at 04:33 UTC.
Its host `i-05a5af5b227c09cf5`, copy `vol-0a993749ea7b8dca0`, root
`vol-0b7d545c029253037`, SG `sg-08b23bc28234adc64`, dedicated role/profile and attachment
were checked against creation receipts. The exact source was `snap-0989e090822d69d1e`.
No original attachment, role, agent, DNS or public gameplay endpoint was reused.

| Checkpoint | Evidence |
|---|---|
| Initial read-only mount, 04:37 | Exact NVMe volume/XFS UUID; ro,norecovery; 39 world files, 12 region files |
| World/player | NBT Version 26.2 / DataVersion 4903; required UUID file under `world/players/data/`; initial world inventory checksum recorded |
| Fixed runtime, 04:42 | AL2023/Docker NEVRA/Compose checksum matched; pinned itzg digest matched; no restored scripts/units/symlinks executed |
| Initial protocol, 04:45 | Minecraft 26.2, protocol 776, online 0; correct bind, loopback port, no OOM/restart |
| Save/normal stop, 04:46 | Score `proof=20260911` in `wc_restore`; explicit Saved the game reply; container exit 0, no listener |
| Restart/save/normal stop, 04:48 | Same container/copy; score read back as 20260911; Saved the game reply; second exit 0 |
| Extraction, 04:49 | Entire Game copied to test-root staging; world contents/UID/GID/mode matched; synthetic sibling B unchanged |
| Unmount, 04:53 | No process using copy, normal unmount, no mount remained; no force or lazy operation |
| Cleanup, 04:57–04:58 | Host normally stopped, exact stack DELETE_COMPLETE; retained root/copy available/unattached/receipt-matched before deletion |

At 04:58 UTC both temporary volumes, SG, role/profile and ENI were confirmed absent;
host was terminated. No running/stopped test host or diagnostic volume remains. Stack
history, local evidence and normal CDK deployment assets remain; they are not orphaned
test compute/storage. The trial stayed well below four hours. Rough compute/IPv4/EBS
baseline for the observed lifetime is about USD 0.02, excluding transfer/tax; this is
an estimate, not an observed billing line. No Budget change was made.

Final production check at 04:58 UTC: original Target STOPPED/HEALTHY, original Data EBS
identity/attachment unchanged, existing four Snapshots/provenance and Game unchanged,
Desired revision 15, DNS absent, no Lock/current/unfinished Operation, 41 alarms OK.
Resolver matched only the original Target. Captured CloudTrail showed no original
Target/Data EBS write, and all ten SSM commands targeted the test host. Normal scheduled
Observed updates continued. The original filesystem was not mounted or rehashed.

Two observation-tool issues were corrected without AWS repair: resource-list pagination
initially returned only nine Lambdas, and an in-memory datetime vs saved-JSON comparison
falsely reported a Snapshot mismatch. Full pagination and normalized representations
confirmed the actual data unchanged. Failed evidence versions remain preserved.

This proves recovery of the existing single-Game world files from the September 8 recovery
point, fixed-runtime launch, write/save/normal-stop/restart persistence, and directory
extraction. It does not recover later progress, prove a full Snapshot-time configuration
manifest, exercise player login/deserialization or human buildings/inventory inspection,
or prove future real multi-Game independence. Human connection was optional and omitted.
Restore UI/general workflow remain deferred. Repository validation: 875 tests, Ruff,
format and mypy passed after the final ASL correction; full CI/HEAD are in final handoff.

Raw evidence roots: `/private/tmp/wishicraft-restore-go-v1.c7kp4o93` (initial failed deploy),
`/private/tmp/wishicraft-restore-asl-v2.a8jr7h69` (restore/cleanup),
`/private/tmp/wishicraft-backup-catch-v3._y3zha93` (final BACKUP definition/read-back).

## Scope and evidence

The user approved the scoped BACKUP deploy, isolated test and successful-test cleanup.
This is not approval for the separate Proposed redesign choices. No automatic credential
search, SSO login, IAM escalation, production SSM or BACKUP is part of preparation.

2026-09-11 03:27:28 UTC read-only preflight, profile `wishicraft-dev`, caller account
`385526546525` matched `config/stages/dev.yaml`. Evidence:
`/private/tmp/wishicraft-backup-restore-preflight-v2.7p9yardo/evidence.json`.
The first script version was rejected before execution because it would persist the full
Lambda Environment. v2 omits that field; no secret values were requested or saved.

| Item | Exact identity / observed result |
|---|---|
| First-choice source | `snap-0989e090822d69d1e`, completed, encrypted, 30 GiB, standard |
| Source start time | `2026-09-08T13:06:56.332000Z` |
| Source Operation | `op-de3dd5bb-87c8-48ad-b9af-4631ec483f8d`, BACKUP/SUCCEEDED |
| Source volume | `vol-03ac9f534326c345c`, remains attached to original Target |
| Game | `game-vanilla-main` |
| Provenance | SNAPSHOT and OPERATION uniqueness pair, exact metadata/fingerprint verified |
| Other backups | `snap-0762ec7637f489d5b`, `snap-079c0aa0c06935d8f`, completed |
| Protected migration history | `snap-0b1d9536e9c476c0f`, completed; never use for cleanup |
| Original Target | `i-04fc0629dc4ea466e`, stopped |
| Control state | STOPPED/HEALTHY, desired revision 15, no Lock/current Operation |

No new Snapshot is required to prove restoration of the first-choice existing backup.
A successful restore establishes a recovery point at September 8, not recovery of all
September 9–11 changes. A new BACKUP for a deployed safety-path smoke test is a separate,
optional write and is **not included in the initial approval request**.

### Reconstructable information and limits

Source tags + immutable provenance + successful Operation bind the backup to its
volume/Game/time. They do NOT capture the complete Game definition or runtime inputs.
Current Games contains package/runtime/generation metadata; do not call that a
Snapshot-time manifest. Historical repository commit
`40651ba8b211676c1a5a1b5864f225b077debbc4` predates the Snapshot by about five minutes.
`phase6-compose.yaml` and `phase6-runtime.env` last changed in
`c5bd12b506b0a51afb5525f244e2b077e6a40055` and describe the pinned Vanilla 26.2/Java25
runtime documented in Phase 6/8 production evidence. Current `host_runtime` values are
consistent with that reconstruction; this is historical evidence plus reconstruction,
not proof that every applied setting at Snapshot time was exported.

The restored copy must be inspected for actual world, version/configuration and player
data before launch. Missing/drifted data is a stop condition, not permission to generate
a replacement world. Rebuild infrastructure from Git, recover secrets through their own
approved procedure in a real disaster, and never restore old Operations/Locks/heartbeat
as live control state. This test needs no production secret retrieval.

### Repeat the read-only gate

Use canonical entrypoints. Record `git rev-parse HEAD`, `dev-env check`, successful CI,
then `aws sts get-caller-identity --profile wishicraft-dev --region ap-northeast-1` and
compare Account with stage configuration. A new session expiry goes back to the user.

Read exact source with `ec2 describe-snapshots --snapshot-ids snap-0989e090822d69d1e --owner-ids self`;
read `SNAPSHOT#snap-0989e090822d69d1e` and `OPERATION#op-de3dd5bb-87c8-48ad-b9af-4631ec483f8d`
from `wc-dev-backups` with consistent GetItem, and the related `wc-dev-operations` record
with only operation_id/type/status/requested_at/result/execution ARN projected.
Do not use the backfill tool: it writes. Collect these as `snapshots`, `provenance`,
`operations` arrays (AWS DynamoDB AttributeValue format for the latter two).

Also read exact original volume/Target/SG, DNS record, Game, SystemState, Lock, backup
Lambda configuration (allowlisted metadata only), current stack template, source AMI,
subnet/AZ/VPC and role policies. Check source KMS key accessibility. Do not log full
Lambda Environment, get secrets, invoke Reconcile or send SSM. Use complete pagination
for any inventory; exact-ID reads do not need a global inventory. Freeze captured
JSON into a fresh private temporary root, with timestamp and command exit status.

Offline verification uses existing production provenance/Operation decoders:

```sh
./tools/dev-env run -- python -m wishicraft.isolated_restore \
  --evidence /path/to/new-preflight/evidence.json \
  --snapshot-id snap-0989e090822d69d1e \
  --output-root /path/to/new-preflight/approval
```

`output-root` must not exist. The tool makes no AWS calls and emits `source.json` and
`isolated-stack.json`; inspect/hash both. The source validator rejects missing/duplicate
records, non-successful Operations, source/owner/tag/fingerprint mismatch. v2 approval
artifacts were generated locally after correcting table separation in the offline loader;
no AWS data was repaired. Re-observe before execution; do not merely reuse stale JSON.

## BACKUP safety contract and release

Four distinct boundaries:

1. **SDK internal retry:** creation uses its own EC2 client with
   `Config(retries={"mode":"standard", "total_max_attempts":1})`.
   This means one total attempt INCLUDING the initial request. Config `max_attempts=1`
   would allow one retry and is not equivalent. The read client is unchanged.
2. **Repeated handler/task:** a transaction checks current Lock owner/lease/expiry and
   reserves `backup_create_intent` on the existing RUNNING BACKUP Operation, with Game,
   lease, deadline and attribute-not-exists conditions. Only a newly acknowledged
   reservation may call EC2. Repeated handler, redrive, concurrent duplicate or lost
   reservation response never grants a second create. No new table/lifecycle is added.
3. **Creation outcome unknown:** explicit EC2 rejections are separated from transport,
   service/internal, malformed response and persistence ambiguity. The reserved tags
   remain even when no Snapshot ID returns. A valid returned ID is additionally saved
   as `backup_snapshot_id` before returning to Step Functions. A crash between reserve
   and send may therefore create zero snapshots and require manual resolution.
4. **Provenance commit:** Snapshot verification precedes the existing atomic transaction
   containing provenance pair + successful Operation + ownership cleanup. On a lost
   transaction response, exact read-back can establish success. Replayed completion
   also accepts a matching already-SUCCEEDED Operation. A rejected transaction does
   not delete the Snapshot. Partial/conflicting evidence never becomes success.

Local SDK version tested: boto3/botocore **1.43.91** from `uv.lock`.
The deployed Lambda uses AWS-managed Python 3.12 SDK, not the dev lock. Its exact SDK
version cannot be inferred from Runtime=`python3.12`; no Lambda was invoked to obtain it.
The explicit Config option is documented by AWS and verified through the installed SDK
HTTP transport, rather than merely counting a mock adapter call. No production duplicate
was observed in preflight; guarantee gaps do not establish historical duplication.

Guarantee: at most one create attempt through the new path per retained Operation
reservation. NOT exactly-once; not a guarantee against a different request ID, manual
AWS calls, overwritten/deleted Operation records, old deployed handlers, arbitrary raw
Lambda invocation, or AWS-side behavior. Do not apply this guarantee retroactively.
Quiesce old executions before deploying. Existing Operation retention is unchanged.

### Unknown-result operator procedure

- Keep original Operation/request identity. No new BACKUP, task redrive, reservation
  clearing, retag, deletion or provenance fabrication to make an error disappear.
- Read Operation reserved tags, optional snapshot ID, execution input/history/output,
  and EC2 Snapshot evidence. Match owner, source volume, exact 9 tags, description and
  completion state. Paginate any tag search completely. Search by operation ID and
  source as evidence, not timestamp proximity.
- Zero matches: unresolved (eventual visibility or no send are both possible). Re-observe
  over a bounded operator window and keep unresolved if still absent. Absence alone
  never authorizes recreation. More than one match/conflicting metadata: anomaly;
  retain all and stop. Exactly one fully matching completed Snapshot: creation is
  established, but successful provenance completion is a separate check.
- If terminal transaction succeeded, require both provenance records plus exact
  SUCCEEDED Operation result; no rewrite. If not committed, leave Snapshot outside
  verified retention eligibility. A still-owned live execution can complete its known
  Snapshot; a terminal FAILED or expired ownership needs a reviewed targeted recovery.
  The current backfill tool requires a prior SUCCEEDED Operation, so it is NOT an
  automatic repair for this case. A general failed-Operation adoption lifecycle remains
  Proposed and is not implemented in this slice.
- State Machine total timeout/lost cleanup can leave Lock/current Operation. Inspect
  execution and in-flight work before any recovery; expiry is not takeover permission.
- Failure recording may conservatively say outcome unknown even if no write occurred.
  A State Machine failure after a committed transaction must not override the committed
  Operation/provenance. Report both facts if read-back cannot converge during invocation.

### Deployment plan (write approval required)

Deploy only `WishicraftControlPlaneStack-dev`, phase=8, after confirming no active BACKUP
or old execution that could cross the deployment. Review credential-backed template diff
without ChangeSet first. Shared source assets can update other Lambda code hashes even
though only BACKUP behavior changed. Expect one BACKUP State Machine definition change,
shared code asset changes, and `dynamodb:ConditionCheckItem` on the **Locks table only**
for BACKUP task. No new table, Target/volume replacement, delete permission, secret read,
Discord schema, DNS or retention change. Halt on any additional unexpected resource impact.

```sh
./tools/dev-env run -- npx --no-install cdk diff WishicraftControlPlaneStack-dev \
  --context stage=dev --context phase=8 --context deployment=control-plane \
  --method=template --profile wishicraft-dev
# FIRST WRITE: only after combined approval
./tools/dev-env run -- npx --no-install cdk deploy WishicraftControlPlaneStack-dev \
  --context stage=dev --context phase=8 --context deployment=control-plane \
  --profile wishicraft-dev
```

Read back deployed asset/definition/IAM, UpdateComplete, physical IDs and alarms. A no-op
or synthetic invocation does not demonstrate real CreateSnapshot behavior. Existing
source restoration is independent of a new BACKUP. If real producer E2E is desired,
request a separately identified one-Snapshot smoke-test addition, not implicit scope.
Rollback code/template to the captured predecessor only before new reservation-bearing
Operations have started. Once new records exist, keep markers; do not downgrade to a
handler that ignores them. Stop new BACKUP requests operationally and prefer forward
repair; do not change production command settings without approval.

## Isolated environment

Use a **new temporary host**, not original Target. Existing Target has production role,
heartbeat timer and resolver identity; sharing it would require changing more production
state and guarding against automatic controllers. The fresh host uses the stage's fixed
AL2023 x86_64 AMI, `t3a.medium`, root gp3 16 GiB, one new 30 GiB volume from source Snapshot,
and existing VPC/subnet in ap-northeast-1a. No original attachment changes.

The generated standalone CloudFormation template has 6 resources: SG, role, instance
profile, host, restored volume, attachment. It is not part of normal CDK deployment.
No bootstrap UserData, production units, agents or configuration are installed implicitly.
All mutations inside the test host are subsequent explicit operator actions.

- Tags are Project=`wishicraft-restore-test`, Stage=`restore-test`, Purpose=`isolated-restore`.
  Production resolver requires all three different canonical production values.
- New SG: inbound NONE, outbound TCP 443 only. Public dynamic IPv4 enables SSM and fixed
  package/image HTTPS downloads without NAT. No public gameplay/DNS endpoint.
- Host role: only SSM registration and ssmmessages control/data channels; explicit deny
  DynamoDB, EC2 APIs, Route53, secrets, Lambda, Step Functions, GetParameter*. No production
  role/profile reuse. The role cannot send heartbeat/SystemState or lifecycle mutations.
- Fresh root boots standard SSM only. Mount data explicitly; never execute restored
  scripts/units. Run only fixed Vanilla image, not any restored shell, plugin or agent.
- Container publishes gameplay to **127.0.0.1:25565 only**. RCON disabled; no production
  password/config injected. No Discord token or callback endpoint. IMDSv2 hop limit 1.
- HTTPS egress permits SSM, AL2023 repository, GitHub/GHCR, Mojang distribution/authentication.
  It is not a domain allowlist. Identity/IAM and executing only reviewed Vanilla inputs
  are the isolation boundary, not a claim that all outbound connections are impossible.

The root is retained on termination and restored volume has Retain on deletion/replacement.
Interrupted/failed stack creation must not erase the only diagnostic copy.

## Ordered execution and restartable checkpoints

Use one new private invocation root, record approved HEAD, template SHA256, exact source,
caller/account/region, start time, expected resource count, and a JSONL action ledger.
Append actual API request IDs and returned resource IDs; never infer success from a command
being sent. Creation receipt and CloudFormation StackId are authoritative, not name/tag.

1. **PRECHECK**: repeat source and production baseline checks above. Validate AMI availability,
   VPC/subnet/AZ route, source encryption/KMS, IAM permissions and the offline template.
   Ensure no concurrent human activity that makes preservation comparison ambiguous.
2. **CREATE**: after approval, `cloudformation create-stack --stack-name <unique-test-name>
   --template-body file://<reviewed-isolated-stack.json> --capabilities CAPABILITY_IAM
   --on-failure DO_NOTHING --client-request-token <fixed-invocation-token>` with canonical
   profile/region. Capture StackId; use that exact ID thereafter. This is a new test stack,
   never an update/import of an existing stack. Do not auto-retry creating a differently
   named stack after transport loss: resolve the same stack/client token and stack events.
3. **INVENTORY**: `describe-stack-events`, `list-stack-resources`, `describe-stacks` by exact
   StackId. Record actual Host/Copy/SG/Role/Profile and root EBS ID, ENI ID, attachment.
   Read back Source SnapshotId, Copy != original volume, AZ, encryption, DeleteOnTermination,
   instance AMI/type/role/tags/SG. A partial stack keeps its identity and ledger; do not
   create a second host as a repair. Conflicts stop for review.
4. **HOST ACCESS**: SSM `start-session` or fixed `send-command` to the exact test Host only.
   Wait SSM Online. On host first confirm IMDS instance/account/region matches ledger.
   Copy reviewed files through operator/SSM payload; do not give host access to production
   code/config buckets. Read only identity-safe output; never dump env or server.properties.
5. **MOUNT**: identify restored Copy by exact NVMe serial (`ebsnvme-id`/`lsblk`), not device
   ordering. Require XFS, UUID `420cea6d-0520-4436-bb5a-db1191f1e63b`, no unknown partition
   signature. Original EBS is not attached. Initially `mount -t xfs -o ro,norecovery <verified-device>
   /mnt/wc-restore` after creating the test mountpoint. Never format, repair or change UUID.
   Bind identity must be checked before each later write. Dirty-log/mount failure stops;
   do not silently run repair. A new isolated copy can be separately approved if needed.
6. **DATA INVENTORY**: require regular nonempty `games/game-vanilla-main/server/world/level.dat`,
   existing `.mca` recursively (26.2 dimension layout), expected player's UUID `.dat`/related
   data in the actual version layout, and required configuration. Record world-only file
   inventory/checksums and numeric ownership. Do not hash or print secret-bearing config.
   Compare expected player UUID with project configuration (normalize hyphens); absence
   is a recorded failure requiring explanation, not automatic creation. Do not start with
   an empty world. Do not copy root agents or original host environment.
7. **RUNTIME PREPARE**: unmount and remount ONLY the verified clone read-write. Use the
   existing `infrastructure/host_runtime/docker_compose_install.sh` on fresh test root with
   stage AL2023/Compose/checksum values, known Docker NEVRA
   `docker-25.0.16-1.amzn2023.0.3.x86_64` and a test-local package record path. It rejects
   version drift; do not upgrade locks to get past it. Start Docker explicitly. Pull the
   exact stage image digest. Install NO production Host Runtime unit or heartbeat.
8. **START COPY**: run one fixed container named `wc-isolated-restore`, restart=no,
   memory=2816MiB, UID/GID=993, SKIP_CHOWN_DATA=true, INIT_MEMORY=1G/MAX_MEMORY=2G,
   TYPE=VANILLA, VERSION=26.2, EULA=TRUE (existing accepted Vanilla use), ENABLE_RCON=false,
   CREATE_CONSOLE_IN_PIPE=true, ONLINE_MODE=true, ENABLE_WHITELIST=true, STOP_DURATION=120.
   Bind ONLY `/mnt/wc-restore/games/game-vanilla-main/server` to `/data` and publish
   `127.0.0.1:25565:25565/tcp`. Use the digest from `config/stages/dev.yaml.host_runtime.image`.
   The copy's RCON setting changes intentionally for isolation; this is not byte-exact
   configuration restoration. Verify the fixed image provides `mc-send-to-console`
   before sending commands. No arbitrary downloaded entrypoint or automatic updates.
9. **VERIFY / MUTATE COPY**: require correct bind/image/version, runtime protocol READY,
   no OOM/restart, existing-world load and known player data. Via container-local
   `mc-send-to-console` as UID 993, add a test-only scoreboard objective `wc_restore`, set
   player `proof` to an invocation-specific integer, then `scoreboard players get proof
   wc_restore`. Record exact successful replies; API submission alone is insufficient.
   Send `save-all flush`, require save confirmation, send `stop`, wait for exit 0 and
   no container/process/listener. Never force-kill to turn a failed save into success.
10. **RESTART**: start that same stopped container and verify READY, same world/bind/image,
    then read back the exact scoreboard value. Compare required player-data presence,
    and repeat confirmed save + graceful stop. This establishes test changes persisted.
    A host reboot adds useful root/runtime rebuilding coverage but is not mandatory for
    this first data-restore test and must not bootstrap production agents.
11. **EXTRACTION**: while clone/runtime stopped, copy the whole Game server directory into
    a fresh test-root staging directory only if enough space exists. Verify world-only
    inventory/checksums match, preserve metadata, reject unexpected links. A sibling
    synthetic B sentinel before/after proves the extraction command does not overwrite
    adjacent paths; it does NOT prove a future multi-Game schema or shared Plugin data.
    Do not stage this test on the original EBS.
12. **PRESERVATION / CLOSEOUT**: compare original Target stopped, original EBS ID/attachment,
    Snapshot/provenance exact content, desired revision/Game selection/DNS/Lock before/after.
    Scheduled Observed timestamps and monitoring can advance normally; do not rewrite
    them for byte equality. CloudTrail/SSM target evidence must show no write or command
    to original resources. Without reading original filesystem, this is isolation and
    control-plane preservation evidence, not a fresh checksum of the original world.

Human content verification can use SSM port forwarding to the test Host's localhost:25565,
then a Minecraft 26.2 client on localhost:<local-port>; no FQDN/SG mutation. The local
`session-manager-plugin` was not found during preparation. Its human installation on the
chosen client is a client prerequisite if visual inspection is requested; do not silently
install it or open public gameplay as a fallback. SSM browser shell is sufficient for the
protocol/data/save/restart checks above. If actual buildings/inventory must be confirmed,
record that human step as pending until completed, not automatically passed.

## Failure, resumption and cleanup

Checkpoint ledger states are PRECHECK/CREATED/IDENTIFIED/MOUNTED/INVENTORIED/READY/SAVED/
RESTART_VERIFIED/PRESERVATION_VERIFIED/CLEANED, with timestamps and exact IDs. A recorded
step is evidence to revalidate, not authorization to skip observing its prerequisites.
After interruption, inspect exact stack/resource/container/mount identities and scoreboard
result. Never blindly rerun world mutation or initial provisioning over partial state.

On any source drift, unknown ownership, unexpected extra volume/role/ingress, wrong mount,
missing world/player data, save failure or production state change: stop the test progression.
Preserve source and clone. If runtime is live, try graceful stop; if impossible, do not
force-stop/terminate it under the normal cleanup permission. Escalate with its live state.
After confirmed graceful stop the test EC2 may be stopped to bound cost while the copy
and evidence remain. Mark incomplete, not restored.

Cleanup on successful closeout (and normal stopped test host) is included in requested
approval. Confirm Minecraft save and graceful exit, stopped container, and no process using
the copy. Unmount the restored volume normally and prove no mount remains before stopping
the test Host or deleting its stack. An unmount failure must not become lazy unmount,
force detach or force-kill. Save ledger/resource inventory and outcomes first. Verify exact StackId and all
physical IDs still match; `delete-stack --stack-name <exact-StackId>` removes only that
stack's host/attachment/SG/role/profile. The clone and root are retained. Before deletion,
record root EBS identity from the exact test Host; missing root receipt blocks volume cleanup.
After stack deletion completes, independently describe each retained volume by ID and
require available/no attachments plus identity matching its creation receipt. Delete only
those two exact IDs with `delete-volume --volume-id <recorded-ID>`, never tag/name batch delete.
A timeout is resolved by describing the same ID; no unrelated resource is selected.

On failed restore retain the clone and evidence for diagnosis; root may also contain needed
logs and stays until those are exported. Safe host STOP can bound costs. Do not delete a
failed diagnostic copy merely because a time limit passed. A reviewed cleanup decision can
then delete the exact recorded resources. Existing backups, source EBS, Frozen/Target,
VPC/subnet, production SG/role, provenance and Budget are never cleanup targets.

## Cost and permissions

Official AWS Price List GetProducts read on 2026-09-11 (Tokyo, Linux, Shared, OnDemand):
`t3a.medium` **USD 0.049/hour**, gp3 **USD 0.096/GB-month**.
Evidence: `/private/tmp/wishicraft-restore-pricing-v1.w172_2f4/prices.json` (SKU/effectiveDate retained).
Public IPv4 is USD 0.005/hour per [AWS VPC pricing](https://aws.amazon.com/vpc/pricing/).
Assume one host, 16+30 GiB storage, 730h/month, four hours:
`4*(0.049+0.005) + 46*0.096*4/730 = USD 0.2402` baseline.
24h running: about USD 1.44; forgotten running month: about USD 43.84 plus transfer/logging.
Stopped host with root+copy retained: USD 4.416/month, or clone-only USD 2.88/month.
CPU credits are Standard (no Unlimited surcharge; workload can throttle). Download ingress
is generally free; allow extra for HTTPS egress/client transfer/logs and taxes. Four-hour
working estimate is under USD 1 with modest traffic, not a spending cap. Review at four
hours; if incomplete gracefully stop and retain evidence. Never change existing Budget.

Operator requires CloudFormation create/describe/delete for only the test stack; IAM
create/delete role/profile and inline policy plus PassRole for the new test role; EC2
RunInstances/CreateVolume/AttachVolume/Describe/SG creation and exact test Stop/Terminate/
Detach/DeleteVolume for execution/cleanup; encrypted-volume KMS use as required by source
key policy; SSM StartSession/SendCommand/GetCommandInvocation for the exact test Host.
No original resource mutation or production secret access is required. Creation-time new
IDs cannot be guessed; record them from receipts and constrain subsequent commands to them.
The operator's existing SSO role is broad; this plan narrows its authorized actions rather
than claiming that a new restricted operator IAM role has been deployed.

BACKUP deployment separately needs existing CDK deployment permissions and adds only the
Locks-table ConditionCheckItem permission to BACKUP task. The isolated host role has no
access to production DynamoDB or Snapshot lifecycle. No new persistent service is required.

## Approval boundary

Requested combined write scope: the reviewed Control Plane BACKUP safety deploy/read-back,
new isolated stack creation, test-host-only installation/mount/container/data commands,
optional localhost SSM tunnel, graceful test stop, and exact successful-test cleanup above.
The existing Snapshot is immutable input. No new BACKUP/Snapshot, source attach/detach,
production START/STOP/Reconcile/SSM, DNS/Discord/retention change or Game model adoption.

First write is the approved deploy (or isolated create-stack if explicitly ordered first).
A new source failure, unexpected diff, stale old execution, lost exact resource identity,
unsafe cleanup or broadened IAM requirement stops before dependent mutation.

## Preparation validation (2026-09-11; no AWS write)

- Full local validation: **875 tests passed**, Ruff check/format, mypy (132 source files),
  phase1/Target/phase8 Control Plane synth all passed. Evidence:
  `/private/tmp/wishicraft-backup-safety-validation-v4.jevtufiv/results.json` and sibling logs.
  Earlier v3 retains its PyPI network failures and formatting failure; neither was
  reclassified as success. v4 uses a fresh evidence root after the correction.
- Boundary coverage includes synthesized Lambda environment to actual Runtime construction,
  DynamoDB AttributeValue serialization/Decimal decoding, production handlers/repositories,
  actual boto3 HTTP retry transport, and DynamoDB SDK-generated per-call request tokens.
  Conditional transaction behavior is tested with a stateful fixture, **not live DynamoDB**.
  The new production BACKUP path and managed-runtime SDK version remain unmeasured.
- Read-only supplement at 03:43 UTC verified fixed AMI availability, subnet/AZ/VPC/routes,
  DNS and allowlisted retry configuration. Lambda has neither AWS_MAX_ATTEMPTS nor
  AWS_RETRY_MODE override. At 03:47 UTC complete Snapshot pagination returned four items
  in one page, and source KMS key metadata was Enabled/AWS-managed.
- Offline isolated template passed AWS ValidateTemplate with CAPABILITY_IAM; no stack or
  ChangeSet was created. Credential-backed CDK diff with `--method=template` succeeded:
  `/var/folders/8l/yptb5b71055c5cqxbzn5qw300000gn/T/wishicraft-backup-template-diff-v1.rwljfecx/diff.log`.
  Live-template comparison shows zero added/deleted resources and 13 changed resources:
  11 Lambda code assets, BACKUP State Machine definition, one BACKUP IAM policy.
  This is a template comparison, not an executed ChangeSet or deployment result.
- Local Docker and shellcheck are unavailable; repository CI supplies these checks.
  CI configuration contains quality/synth and synthetic host-runtime integration only;
  no AWS deploy is triggered by the authorized commit/push. Exact commit/CI result is
  recorded in the final handoff, without claiming deployment or restored-world success.

## Official references

- [Boto3 retry configuration](https://docs.aws.amazon.com/boto3/latest/guide/retries.html)
- [Step Functions redrive](https://docs.aws.amazon.com/step-functions/latest/dg/redrive-executions.html)
- [DynamoDB transaction IAM](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/transaction-apis-iam.html)
- [EBS Snapshot restore and file retrieval](https://docs.aws.amazon.com/ebs/latest/userguide/ebs-restoring-volume.html)
- [itzg console commands when RCON is disabled](https://docker-minecraft-server.readthedocs.io/en/latest/sending-commands/commands/)
- [EC2 official pricing](https://aws.amazon.com/ec2/pricing/on-demand/)
- [EBS official pricing](https://aws.amazon.com/ebs/pricing/)
