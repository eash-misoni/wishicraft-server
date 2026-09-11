# Two-Game SWITCH / BACKUP contract

**Status: Proposed — repository implementation in progress; no production writes authorized.**

Baseline: `bb78deacc4daf1ad195887f337b3d4fa6a53c30f`. D-096 remains Completed.
This proposal does not accept the rest of Phase 9, RESET, whitelist synchronization,
Package/Preset/Template management, or different runtime classes.

## Scope and ownership

Two declaratively allowlisted Games share one pinned runtime configuration, one EC2,
and one Data EBS. A stays at its existing path. B uses a distinct Game-derived path.
Paths and commands are not supplied by Discord callers. Games records describe the
registered Games; the Git catalog limits what the host can execute. Distribution of
that catalog is configuration deployment, not synchronization of an active pointer.

`SystemState.desired_game_id` is the selected Game. STOP retains it. A legacy unset
selection resolves to A until the first successful desired update. Actual Game/run
comes from the validated container/receipt, never from the selection. `runtime_id`
continues to name the host runtime slot; `run_id` names one execution.

START can name a Game while stopped. SWITCH freezes source and destination together
in the owning Operation before saving A. The destination run uses that Operation ID;
the source keeps its existing run. One lease owns both halves. Existing normal host
STOP (save, graceful exit, exact container removal) and START are reused. The SWITCH
state graph contains no EC2 start/stop task and no intermediate Operation completion.

A stays selected during its save/stop. Once A is confirmed stopped, the START half
selects B and requests RUNNING. A save failure retains A and its receipt. B start
failure retains both data directories and selects B; unknown/failed runtime is not
HEALTHY. There is no automatic rollback or generation of a replacement world.

Duplicate requests resolve through existing idempotency. An ambiguous host result
requires exact Operation/lease/SSM/receipt/container read-back. No replacement run is
created to conceal an unresolved one. A later ordinary START may resume the selected
unresolved run only under D-096 target validation. Returning to A first requires B
to be confirmed normally stopped. Terminal execution replay is not a recovery API.

## User policy proposed for approval

`/mc start game:<A|B>` retains current START authorization, but cannot stop a running
different Game. `/mc switch game:<A|B> confirm:true` requires Admin authorization.
SWITCH rejects positive or unknown player counts, with a second check at the host
before saving/stopping. This is a last-observed-empty policy: a connection can race
that check. It is not a promise of an atomic player admission fence. Broader player
permission or guaranteed advance notice needs a separate explicit policy decision.

## Backup proposal

New backups protect the shared physical volume and carry a frozen recovery description
in the existing durable provenance. No separate manifest service or archive subsystem.
The description identifies both registered Games, Game-derived paths, runtime image
and configuration revision. Failure to freeze that information must prevent creation;
post-create uncertainty protects the existing Snapshot and reservation until read-back.

Retention remains dry-run-only. New shared-volume normal backups form their own newest
seven group. Old per-Game schema records and migration anchors are preserved separately;
they are not rewritten, counted as new shared records, or silently made deletion eligible.
Restoring A alone means extracting A from an isolated restored copy and validating it,
not replacing the shared EBS and rolling back B. Snapshot-time configuration evidence
must be distinguished from configuration reconstructed later.

## Production gate

No BACKUP, Game registration, host directory creation, SSM, command registration,
deploy, IAM, START/STOP/SWITCH, Snapshot/provenance update, or retention execution has
been authorized by this request. The final migration plan must identify fresh protection,
exact deployed predecessors, admission drain, B materialization, compatible host/CP
cutover, A→B→A measurements, failure checkpoints, and final STOPPED/HEALTHY.

Repository tests, Docker CI, deployment difference review, and the concrete runbook
remain work in progress. This document is not execution evidence or a readiness claim.
