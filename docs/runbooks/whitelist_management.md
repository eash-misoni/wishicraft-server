# Whitelist Management production gate

**Preparation only: no production write authorized or performed for D-106.**
[D-106](../reviews/whitelist_management.md) owns the policy contract.

## Migration and approval boundary

The current EC2 is stopped. Fresh A/B whitelist contents, owner/mode and file digests cannot be
obtained through AWS read-only APIs. Do not start EC2 or send SSM for this preparation. A single
release approval must explicitly include the bounded maintenance capture below. Config defaults
and prior tree digests do not prove current effective membership.

The candidate mapping is Common=intersection of all existing materialized Game memberships,
Game-specific=each membership minus Common. This preserves each current Game's access and grants
the intersection to future Games. That future-Game meaning is a release approval decision, not a
property proved by set arithmetic. If the observed files/history do not support it, stop before
policy migration and report only counts/digests and the ambiguity. Do not reveal member values in
chat, public documentation, CI or tracked evidence.

`wishicraft.whitelist_migration.plan` is offline-only. It validates strict UUID/name entries,
rejects duplicate UUIDs or conflicting names, builds bounded policies and proves exact per-Game
effective equality (count and canonical digest). It does not read AWS, write tables or touch worlds.
Preserve exact original file bytes as private evidence as well as normalized membership digests.

## Reviewed release sequence (requires GO)

1. Recheck canonical wishicraft-dev STS Account against config/stages/dev.yaml, Tokyo region,
   Game records, SystemState, selected/observed Game, world/generation/path, EBS, DNS, locks,
   workflows, SSM, queues, alarms, Snapshots and durable provenance. Capture current templates,
   Lambda configurations/concurrency and exact host predecessor hashes/receipt from D-105 evidence.
2. Enter bounded maintenance using the existing Admission/Web/Discord draining procedure. Verify
   no active lifecycle work, Lock, SSM or players. Maintenance is not Minecraft startup permission.
3. Start only existing Target EC2 for inspection. Verify mount UUID/device/Data EBS, no Minecraft
   container/listener/runtime job, and exact stopped receipt. Read canonical A/B current paths from
   Game records; capture whitelist files privately with exact owner/mode/hash and full Game tree
   digest. Unexpected runtime or Game identity/path/generation changes stop the release.
4. Run offline migration planner on these exact files. Require complete A/B effective equality,
   no unsupported identity/duplicate/ambiguity, and counts within bounds. Recheck the source bytes
   and Game records before any policy write. New dynamic Games are not expected; stop if registry
   differs from the approved inventory. Never infer membership from config defaults.
5. Generate the three-file host bundle with `whitelist_migration.host_bundle(repository, new_root,
   verified_stopped_receipt)`. It reproduces the D-105 contract and wrapper predecessor from
   e75f825 and checks them against tracked production evidence. Review destinations/hashes/modes.
   Inactive-only installer updates contract and wrapper and adds whitelist_policy.py. It must match
   exact predecessor bytes/hash/owner/mode and receipt. No Compose/runtime.env/manifest, Game file,
   world or generation changes occur at installation. Unknown result stops, with no blind retry.
6. Read back all three host artifacts, receipt and unchanged Game tree. Stop EC2 without starting
   Minecraft. Confirm stopped and DNS absent. No Snapshot or Game is created.
7. Install the new schema-compatible CP assembly with game_creation=true, whitelist_management=true,
   two_games=true, reset=true, keeping maintenance closed. No workflow definition change or new IAM
   is expected. Atomically insert Common and per-Game policy records with attribute_not_exists for
   every policy item, no Lock, and exact current Game world/version conditions. Read back and prove
   identical effective counts/digests; result unknown requires read-back, never raw cleanup.
8. Deploy Web assembly with game_creation=true, whitelist_management=true. Recheck wiring, artifact
   digests and scopes, then restore captured concurrency. Runtime remains STOPPED/HEALTHY.
9. Run safe E2E below and capture final unchanged A/B metadata/world/path, snapshots/provenance,
   system state, no Lock/workflow/SSM, empty queues, normal alarms and absent DNS.

The policy transaction in step 7 must be generated from the captured private plan, never copied
from chat. This gate authorizes no mutation now. Live diff uses `--change-set=false`; synth/diff
does not create or execute a CloudFormation changeset. No Target IAM/resource deployment is needed:
its existing Games:GetItem already reads dedicated policy records.

## Safe production E2E

Read public guide regression and authenticated Common/Game UI. Admin write visibility and Player
rejection use current roles; never change Discord roles. Verify CSRF/foreign Origin/old execute-api
and unauthenticated rejection with guaranteed negative input. Do not add a fake player, remove a
real player, create a Game or start Minecraft for tests.

Use the Admin UI's **現在の設定を再保存** to submit a no-op with current policy revision. Verify
terminal Operation, same request retry/read-back and identical membership/revision. Compare A/B
effective policy with the migration proofs. Positive running projection is observed at the next
normal authorized START; local/CI Docker evidence is labeled separately from production evidence.
D-105 positive CREATE/materialization remains deferred.

## Rollback and cost

Before any real membership change, exact predecessor host/CP/Web can be restored under the same
inactive/receipt guard. Keep inserted policy records as dormant private records; no raw delete,
Data EBS replacement, A/B metadata mutation or Snapshot deletion is required. Original runtime
files were never changed by migration or no-op E2E, so effective access remains the predecessor's.
Do not roll back to file-authoritative behavior after policy edits without a separately reviewed
access-preserving export of every effective Game policy. Prefer disabling new whitelist writes
with maintenance concurrency, retaining policy/recovery support and forward fixing. Dynamic Game
registration also preserves D-105's prohibition on A/B-only rollback.

No new persistent resource or always-running compute is added. Costs are existing Lambda/DynamoDB
on-demand requests and small policy/provenance storage. Name lookup is one bounded external HTTPS
request per unrecorded add. Maintenance EC2 use is bounded; no runtime polling/daemon is introduced.

## Validation evidence

Preparation evidence, final CI and live diff are recorded at the production gate. Local Docker CLI
is unavailable; actual pinned-image integration runs on the existing disposable Linux CI runner.
AWS/SSM/systemd/mount transports there are synthetic, while Minecraft, files, RCON and Docker are
real. Do not report a queued or failed CI run as passed or preparation as production Completed.
