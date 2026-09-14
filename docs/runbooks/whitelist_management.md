# Whitelist Management production gate

**Production release authorized against ade0d89, with empty-Common migration amendment; execution pending.**
[D-106](../reviews/whitelist_management.md) owns the policy contract.

## Migration and approval boundary

The current EC2 is stopped. Fresh A/B whitelist contents, owner/mode and file digests cannot be
obtained through AWS read-only APIs. Do not start EC2 or send SSM for this preparation. A single
release approval must explicitly include the bounded maintenance capture below. Config defaults
and prior tree digests do not prove current effective membership.

Initial Common is empty. Each existing Game-specific policy preserves that Game's complete current
effective membership. The earlier intersection candidate is superseded by explicit release approval:
being present in A and B does not establish permission for future Games. Common membership must be
set explicitly by an Admin after release. Require exact current effective membership preservation.
If observed files/history contain ambiguity, stop before policy migration and report only counts and
digests. Do not reveal member values in chat, public documentation, CI or tracked evidence.

`wishicraft.whitelist_migration.plan` is offline-only. It validates strict UUID/name entries,
rejects duplicate UUIDs or conflicting names, builds bounded policies and proves exact per-Game
effective equality (count and canonical digest). It does not read AWS, write tables or touch worlds.
Preserve exact original file bytes as private evidence as well as normalized membership digests.

## Approved release sequence

1. Recheck canonical wishicraft-dev STS Account against config/stages/dev.yaml, Tokyo region,
   Game records, SystemState, selected/observed Game, world/generation/path, EBS, DNS, locks,
   workflows, SSM, queues, alarms, Snapshots and durable provenance. Capture current templates,
   Lambda configurations/concurrency and exact host predecessor hashes/receipt from D-105 evidence.
2. Enter bounded maintenance using the existing Admission/Web/Discord draining procedure. Verify
   no active lifecycle work, Lock, SSM or players. Maintenance is not Minecraft startup permission.
3. Start only existing Target EC2 for inspection. Verify mount UUID/device/Data EBS, no Minecraft
   container/listener/runtime job, and exact stopped receipt. Read canonical A/B current paths from
   Game records; capture whitelist files privately with exact owner/mode/hash and full Game tree
   digest. Both server.properties and whitelist.json must be regular/single-link UID/GID 993,
   not group/world-writable, with online-mode/white-list/enforce-whitelist exactly true. Do not
   silently repair unexpected attributes. Unexpected runtime or Game identity/path/generation
   changes stop the release.
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
from chat. The user approved this bounded sequence with the empty-Common amendment. Live diff uses `--change-set=false`; synth/diff
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


Preparation inventory at 2026-09-13 23:56 UTC: STOPPED/HEALTHY, selected A, A/B exact metadata
hashes unchanged, no Lock/active workflow/SSM, 3 empty queues, 45 alarms OK, 9 Snapshots and
16 provenance items byte-equivalent under canonical inventory comparison to D-105 closeout.
Three old schema-1 recovery descriptions validate unchanged with the new reader. DNS is absent
and the original Data EBS remains attached to the original stopped instance. Host whitelist contents
remain unobserved until approved maintenance; no membership values are included in tracked evidence.

[Preparation evidence](../evidence/whitelist_management_preparation_2026-09-14.json) records the
review bundle hashes, exact live diff and validation scopes. New source code changes only existing
Lambda code plus the three feature environments; IAM, resources and workflow definitions compare
unchanged. First CI 34791083220 passed all jobs and 1,262 tests, including real pinned-image
Whitelist START/SWITCH/in-game add/remove/restart convergence. Follow-up CI 34791463982 stopped in
the additional RESET fixture's file identity check: its legacy fixture had not preseeded A/B's
canonical settings file attributes. The corrected fixture seeds UID/GID 993, mode 0640 before the
first boot and explicitly verifies those attributes after stopping. The pinned image's default
umask is 0002; this does not authorize relaxing the production file identity guard. Failed evidence
is retained. Finalized gate HEAD must pass the full CI, including corrected RESET generations;
the exact final run is reported in the handoff rather than predicting an uncompleted result.
