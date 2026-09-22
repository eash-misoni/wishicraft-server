# Discord progress completion supersession

## Incident and root cause

The 2026-09-22 Discord START `op-b6129025-0175-4020-97af-c4e93922b4cb`
succeeded at 06:12:53 UTC. Its Message Lambda invocation
`05a12961-1f7c-4a00-b1ae-001a9e6e2963` failed at 06:08:47.445 UTC in
`mark_delivered` / `_finish` / DynamoDB UpdateItem after a successful edit.
The same invocation retried at 06:08:47.657 and completed. Delivery eventually
reached revision 5 DELIVERED on the same message; the Errors alarm recovered at
06:14:32. This was a projection-record race, not a Minecraft failure.

Read-only DynamoDB Stream evidence showed revision 1 claimed PENDING, followed
by authoritative progress 2 while delivery_source_revision was still 1 under the
original owner. The previous no-op classifier required delivery_source_revision
already equal to current progress. It therefore rejected this normal gap before
the newer stream consumer claims. A previously qualified ordering where the new
consumer has already completed did not cover it.

## Completion conflict contract

The conditional write remains unchanged. Only ConditionalCheckFailedException
triggers consistent read-back. A successful API completion is superseded when:

- Operation ID/type, channel, deterministic delivery ID and returned message ID match;
  the loaded Operation key is also verified.
- The attempted record is the matching PENDING claim and authoritative progress
  is strictly newer than the attempted revision.
- If delivery still belongs to the attempted revision, it is PENDING under that
  same attempt, with unchanged delivered revision and outcome-unknown flag.
- Otherwise the newer delivery has a nonempty different attempt and a revision
  greater than attempted but no greater than authoritative progress. DELIVERED
  requires its matching delivered revision and a known outcome; other recognized
  delivery states cannot claim a delivered revision at or beyond their own revision.

The loser returns without any additional write, Discord API call or retry enqueue.
The existing stream/retry path owns the newer delivery. No schema or queue changes.
Same-revision conflicts, even terminal duplicates, now fail closed as explicitly
requested; this replaces the old same-revision completion no-op. Earlier
pre-delivery duplicate/stale-event filtering is unchanged. Unknown identity,
owner/state mismatch, older progress, non-conditional database errors and failed
read-back propagate. Actual Discord API failures still record FAILED or
RETRYABLE_FAILED through the existing contract; their completion conflicts are
not reclassified as successful API completion.

One Operation still has one public message, edited for progress. No change to
Minecraft lifecycle, revision writers, message format/history, State Machines,
Game/runtime, IAM, alarm definitions or thresholds.

## Verification

The regression uses the real handler/service/store with a stateful conditional
DynamoDB fixture and an edit-success interleaving. It claims revision 1, accepts
its edit, advances progress to 2 without a new delivery claim, then rejects the
revision-1 completion CAS. The invocation succeeds without modifying the snapshot
of revision 2. A normal next stream event delivers the final revision on the same
message. Running that regression against the previous adapter fails with the
original ConditionalFailure; the corrected implementation passes.

Negative cases cover same revision (including delivered), regressed progress,
Operation/type/channel/message/delivery identity mismatch, wrong or missing owner,
missing/out-of-range delivery revision, invalid state/receipt and genuine API
failure/retry. Newer delivery may legitimately lag an even newer progress revision.
Local qualification passed: 130 focused tests, all 1,593 repository tests, Ruff lint/format, mypy (226 source files), and the full-feature dev Control Plane synth. The initial sandbox-only full-suite/synth attempts failed fetching pinned bundling dependencies due to network isolation; the network-enabled reruns passed. Local Docker/shellcheck are unavailable and remain CI checks. Release/CI results follow after execution.

## Dev release boundary

The user permits an existing Lambda code-only update after ChangeSet review.
Only the Message Lambda needs changed behavior. A reviewed template may retain
all deployed resources/properties and replace only that function's Code with the
exact canonical CDK-synthesized asset. Compare all other fields byte-for-byte or
structurally, including IAM, workflow definitions, alarms, mappings and queues.
Do not execute if the actual ChangeSet includes unrelated resource/IAM/workflow
changes. Do not induce a real START/STOP or artificial Discord error to test this
race in production. Deterministic concurrency verification is local; real-traffic
absence of Errors is an observation, not proof the race was exercised.

Release status: pending validation and ChangeSet review.
