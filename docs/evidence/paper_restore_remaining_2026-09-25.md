# Paper retained-world comparison continuation

2026-09-25 UTC. **PASSED: this limited continuation completed, with safe final state.**
This continues the [earlier PARTIAL proof](paper_restore_dev_2026-09-25.md),
without repeating BACKUP, RESTORE request, prepare, commit or rollback.
See the [runbook](../runbooks/paper_restore_dev.md).

## Identity and execution

Baseline `a11e0f9ba3a2342a70fe86811f1849514dee7fa5` matched HEAD/origin/main.
Fixed execution commit: `fe116d870bf015672f9bbb44f00ce8c8fe4a1205`, generated
from clean detached `/private/tmp/wishicraft-paper-remaining-fe116d8`.
The primary checkout retains its unrelated README, delivery/backlog, Terralith
runbook and untracked Terralith evidence changes. They are absent from execution.

Dev account 385526546525 / ap-northeast-1 / wishicraft-dev / wishicraft-main,
EC2 `i-04fc0629dc4ea466e`, Data EBS `vol-03ac9f534326c345c`, canonical ownership
and caller were checked. vps-survival Game
`game-bfd8409b3f8a4d1b591231c3490d9b646f546294ca11837cad74616ed33eaf21`
selects its initial `server`, generation 1 / counter 2 / current_id absent.
RESTORE `op-a09fec85b92d5620351ef556b7d47d4dff6f6d62e0042fc0a3f0e5c28b519f42`
remains ROLLED_BACK, journal revision 18, cleanup DELETED. Desired revision 75
is consistent with the earlier restored START/STOP; revision 73 was not required.

Source `snap-0aac363f3ce09e05a` and protection `snap-0e5941ab3b8e0e6ff` remain
completed/encrypted, with formal provenance and matching package/creation/world.
The old temporary volume is NotFound, and its operation-owned volume set is empty.
There is no new BACKUP, RESTORE, temporary EBS or source mount in this continuation.

Before maintenance: STOPPED/HEALTHY, EC2 stopped, no Current Operation/Lock,
running workflow, active SSM, DNS or unfinished maintenance; three queues empty;
51 alarms OK. Existing alarm configuration, host IAM, Game records and RESTORE
journals matched the saved previous final state. Both existing ingress concurrency
settings were recorded as UNSET and temporarily set to zero. Admission, Observer
and Reconcile remain active.

## Retained baseline and private evidence

First ordinary maintenance `paper-compare-20260925-fe116d8` began 14:41:52 UTC,
expires 16:41:52 UTC (7200 seconds). Normal suppression was observed before
EC2-only startup at 14:48:47. Canonical fresh idle-host checks and the content
reader confirmed managed Minecraft/container absence, expected mount, no source
restore mount and unchanged installed helpers. No helper was distributed.

The current original server equals the prior formal `previous_tree` and
`source_tree`: 1670 files, 3680766267 bytes,
`9258f8ff8f2a773c318635df4248c690faf1e90bf0145060126cf683766005d8`.
Its world equals prior source/copy: 1541 files, 3515790017 bytes,
`133e616c3bcf4482fe7df5851adab7970d81ecca549789c45973078ffe4ae7a3`.
The retained restored world equals the prior post-STOP tree: 1541 files,
3515790036 bytes,
`1e02ace2a3e4f15ec8925632220f9a666c0c53f6f7a5d0a50eb9fa018f4c5bf9`.

Both 33-file Minecraft metadata groups reproduce the saved aggregate and filename
hashes from individual entries. This establishes the original as this run's
pre-start comparator. It does not recover individual hashes from an aggregate,
or establish that other snapshots equal their current worlds.

The bounded reader captured relative names, sizes, SHA-256, complete file-only
aggregates and stability checks. Three matching private transport parts reassembled
into a complete typed metadata/level snapshot with verified length/hash. Exact
integer strings and NBT types are preserved; arrays remain opaque typed hashes.
Raw player data, coordinates, inventories and server.properties are not published.
The original has not been started since this baseline was captured.

Whole-world comparison found 12 changed files, 1529 unchanged, no additions or
deletions. Formal content and protection readers also confirm the other four
Games and retained Vanilla B trees equal prior evidence. Current policy hashes,
initial IMPORT owner, restored owner/validated receipt, package/creation and
selected Paper configuration/content checks match. This does not require the
two entire server trees (which contain runtime caches) to equal each other.

## Changed files and review boundary

Of the 33 Minecraft metadata files, **7 changed and 26 were identical**:

| Relative path below wishinkaiwai | Typed change |
| --- | --- |
| dimensions/minecraft/overworld/data/minecraft/raids.dat | INT data.tick: 30367734 → 30378346 |
| dimensions/minecraft/the_nether/data/minecraft/raids.dat | Same INT tick change |
| dimensions/minecraft/the_end/data/minecraft/raids.dat | Same INT tick change |
| dimensions/minecraft/overworld/data/minecraft/weather.dat | INT rain_time: 11827 → 1212; thunder_time: 143371 → 132756 |
| dimensions/minecraft/overworld/data/minecraft/world_clocks.dat | Both saved LONG total_ticks increased 10615 |
| dimensions/minecraft/the_nether/data/minecraft/world_clocks.dat | Both saved LONG total_ticks increased 10615 |
| dimensions/minecraft/the_end/data/minecraft/world_clocks.dat | Both saved LONG total_ticks increased 10615 |

These files differ in compressed bytes, expanded bytes and the listed typed
values; they are not classified as compression-only differences. All other typed
fields in those files match. The exact Minecraft 26.1.2 official server artifact
and Paper commit `39a1aa5c7fa9742accf82c247a0ea18014788b5f` support ordinary
clock advancement, positive weather-timer decrement and independently saved raid
tick advancement. Raids marks itself dirty periodically; its delta is not claimed
to be an exact reconstruction of every world tick or save instant.

Separately, `level.dat` and `level.dat_old` differ only in LONG Time (+10615) and
LONG LastPlayed. The version's writer sets LastPlayed from epoch milliseconds
at save. Other typed level fields match. Level Time is not used to explain away
changes in the 33-file metadata group.

The remaining three changes are
`dimensions/minecraft/{overworld,the_nether,the_end}/data/paper/level_overrides.dat`.
Their individual before/after sizes and hashes are captured, but their typed
contents were outside the initial fixed reader. The exact
[Paper implementation](https://github.com/PaperMC/Paper/blob/39a1aa5c7fa9742accf82c247a0ea18014788b5f/paper-server/src/main/java/io/papermc/paper/world/saveddata/PaperLevelOverrides.java)
can store game time as well as spawn, initialized state, game type and difficulty.
Consequently, filename or small size change alone cannot qualify these values.
The user separately authorized the fixed six-file reader. Its first invocation
returned Success/0 with stable fingerprints matching the whole-world comparison.
All three Paper files differ only in LONG `data.game_time`, 30367857 → 30378472;
spawn, initialization, game type and difficulty fields are unchanged. This matches
the exact Paper `setGameTime` dirty-save implementation. **The pre-start semantic
gate passed after this evidence was fixed.** The coverage gap was not a failed-output
retry and no data corruption was observed.

## Qualified supplementary approval

Separate commit `08455f6c43800d944a9f9e62b123c8d407e301a6` adds only a bounded
reader selection/tests/runbook text for those three files in each retained world.
Clean worktree `/private/tmp/wishicraft-paper-overrides-08455f6`; fixed payload
SHA-256 `5fc0937cc875313bbc51fc034a5d703981493ab12e23dbf58f69f2c23da325eb`.
The user separately approved exactly two invocations, before original START and
after its STOP, inside the two planned maintenances. First command
`03d1ae2d-c6af-4780-bbc2-bc17be0f9a0c` succeeded; its payload hash matched and
the fresh idle-host preflight had 4679 seconds of lease remaining. This separate
approval does not consume or expand the display-failure retry allowance.

Local full tests: 1839 passed; Ruff/format/mypy passed. Generated payloads passed
Python 3.9 and 3.12 JSON roundtrip checks. Exact proposal CI succeeded:
[CI](https://github.com/eash-misoni/wishicraft-server/actions/runs/36151680691),
[NeoForge](https://github.com/eash-misoni/wishicraft-server/actions/runs/36151680622),
[Paper](https://github.com/eash-misoni/wishicraft-server/actions/runs/36151680672).
Existing Paper CI remains IMPORT integration, not real RESTORE proof.

One planned metadata-part send was blocked by the pre-send active-SSM gate.
No SendCommand/attempt marker existed for that failed local invocation. After
terminal history and absence of a matching command were checked, its initial
send succeeded. The failed gate record remains; it is not a reader retransmission.
Every completed planned reader returned SSM Success / ResponseCode 0.

Final safe state is recorded below.
No full proof, client play, load, other build/plugin compatibility, NeoForge RESTORE,
disaster recovery or maintenance-notification-race fix is claimed.

## First maintenance notification observation

At 15:25:26 UTC the idle host began normal stop. Real EC2 stopped and normal
Reconcile returned STOPPED/HEALTHY with no discrepancies or DNS. The suppressor
returned OK at 15:26:46, before RuntimeObservationUnknown (15:26:49) and
DesiredActualDivergence (15:31:31). Both composite SNS actions succeeded at
15:26:46, and the user confirmed both emails. Formal end was 15:27:27, after
those actions. By 15:32 all 51 alarms were naturally OK before original START.

The state/metric/log/history sequence supports planned idle-host shutdown
convergence, independently of the retained-world hash proof. Monitoring was not
changed, no alarm state or metric was injected, and the suppression race remains
an independent backlog. The observation does not prove a permanent notification fix.

## Original-world normal lifecycle

Original START `op-cca5d0f4-bce2-4dcd-8968-dc3d25bf0628` and STOP
`op-0d5594ea-76a0-4ae8-8575-e2c1e3236e0d` both SUCCEEDED. Desired revision
advanced 75 → 76 → 77; generation 1 / counter 2 / current_id absent and
ROLLED_BACK journal revision 18 remained unchanged.

Fresh Reconcile and heartbeat at 15:39 confirmed READY/HEALTHY, the same
Game/run/process/boot and the original initial server path. The fixed live reader
`97d96e86-fa18-47fe-916a-e9e5c7425870` returned Success/0 at 15:40:24:
container /data binding is original, config digest and immutable image match the
previous Paper runtime, owners/receipts and current policy-file hashes match.
Dimension-specific region counts were Overworld 402 / Nether 33 / End 90 with
matching selected hashes. Player groups were observed, not hardcoded: data 27
files (12 .dat decoded for selected-field hashes), stats 14, advancements 14.
Group filename/content hashes, selected player-field hashes, datapacks, gamerule/
border/world-generation saved files and seven Paper configuration files match.
The retained restored server/world trees remain unchanged. No full-world byte
invariance is required while the original is ticking. Observed player count was
zero; no client play, exploration, load or intentional gameplay was performed.

Formal STOP SSM `9a65f0ea-999b-4854-97a0-3e03fd818db4` returned Success/0.
At 15:41:41 the workflow observed stopped receipt phase, no process/container or
Minecraft service, then completed EC2 stop and DNS deletion. STOPPED/HEALTHY and
DNS absence were read back at 15:43:05. Second ordinary maintenance
`paper-postsave-20260925-fe116d8` began 15:44:29 for 7200 seconds; normal
suppression was confirmed before EC2-only start at 15:47:57.

## Original normal-save comparison

The post-save fixed readers all returned Success/0. The additional Paper command
`55d9414b-0abe-4243-9069-e3914c8a478a` used the same approved payload hash;
its fresh idle preflight had 6275 seconds of lease remaining. Exactly two added
Paper invocations were used, with no display-failure retry.

The original world now has 1541 files, 3515790025 bytes and tree SHA-256
`aa48221f13d41fc42c9f1b6007759366f1f08e8cf00fccd34b855b7f98a492e7`.
The 33-file Minecraft metadata aggregate is
`b4cc4ce5a83b50114002f0ef6c8b900a8fe6681a7b43eaefcaed023a139c342f`;
filename/count identity is unchanged. These are observed post-save values,
not replacement acceptance criteria for the original pre-start baseline.

Per-file pair comparisons join through the unchanged retained restored tree;
metadata and level values also compare directly against the privately fixed
pre-start typed snapshot. No individual hash is inferred from an aggregate.
The same 12 files changed, 1529 did not, with no additions/deletions:

- Seven Minecraft metadata files: world clocks +8237 (LONG total_ticks), positive
  rain/thunder timers −8237 (INT), and independent raid ticks +8234 (INT).
- Three separate Paper override files: only LONG game_time, 30367857 → 30376094.
- level.dat and level.dat_old: only LONG Time (+8237) and LastPlayed save epochs.

All other typed fields, including Paper spawn/difficulty/type/initialized values,
match. These changes follow the same exact-version writers described above;
there is no blanket exclusion of time-like fields or compression-only assumption.
No unexplained loss or abnormal content change remains. The original's normal
lifecycle success and this post-save content qualification are separate passed
results. The original is not claimed byte-identical across its own normal save.

The retained restored server/world and private typed records are unchanged from
this continuation's start. Other four Game trees and retained Vanilla B trees,
current policy, owners/validated receipt, helpers, player groups, selected Paper
settings, datapacks and saved gamerule/border/world-generation files are protected.
Both existing snapshots were revalidated with formal provenance; old clone volume
remains NotFound and the RESTORE-owned temporary volume set is empty.

## Validation distinction

The base execution commit's CI also passed before AWS:
[CI](https://github.com/eash-misoni/wishicraft-server/actions/runs/36147498797),
[NeoForge](https://github.com/eash-misoni/wishicraft-server/actions/runs/36147498778),
[Paper](https://github.com/eash-misoni/wishicraft-server/actions/runs/36147498821).
Quality checks include full tests, Ruff/format/mypy and configured Control Plane
and independent Web synth. The supplementary commit's 1839-test run and separate
CI qualification preceded both additional reads. CI contains host/Paper/NeoForge
integration; it is distinct from the real limited Paper continuation documented here.

Initial local online bundling/tests were blocked by PyPI DNS resolution. Their
failed logs were retained; existing offline uv cache allowed the subsequent full
suite and configured synth to pass. No installation, IAM expansion or real deploy
was used to work around the environment. Reader output stayed within its existing
limits; no AWS reader failed and no display-failure retry was used. A successful
reader's initial Paper content-coverage gap required the separate explicit approval
recorded above; it was not silently normalized away.

## Final state and scope

At 16:09 UTC: original vps-survival selected; generation 1 / counter 2 /
current_id absent; target RESTORE remains ROLLED_BACK at revision 18. All RESTORE
journals equal the starting records, including the pre-existing unused PLANNED
journal; no new RESTORE execution or request was created. Package, creation,
policy, other Game records, host IAM and Data EBS attachment are unchanged.
Original and restored worlds and both snapshots remain retained; no source mount,
new clone or unwanted restore staging remains.

STOPPED/HEALTHY, EC2 stopped, second maintenance ENDED at 16:03:32; no Current
Operation/Lock, running workflow, active SSM command/session or DNS. All three
queues report Visible/NotVisible/Delayed zero. All 51 alarms naturally returned
OK with their configuration unchanged. Both ingress concurrency settings were
restored to their recorded UNSET values; all Lambda concurrency values match
baseline. No Observer/Reconcile or monitoring setting was disabled.

Second idle-host normal stop began 16:01:26. DesiredStoppedEc2Running recovered
16:06:25 and DesiredActualDivergence 16:06:31. Suppressor recovery at 16:06:46
preceded RuntimeObservationUnknown recovery at 16:06:49, producing one SNS action
success; the user confirmed that email. Thus this continuation had **three SNS
notifications and three user-confirmed email receipts** (first maintenance two,
second one). Data checks and actual stop observations passed independently. The
notification-ordering problem remains an independent backlog, not a solved feature.

There was exactly one original-world normal START/STOP pair and the two planned
ordinary maintenances. No new BACKUP/RESTORE, source remount, temporary EBS,
re-prepare/re-copy/commit/rollback, restored-world restart, other Game/VPS action,
IAM/helper/runtime/deploy, package/version/policy or monitoring change occurred.
Both retained worlds remain available; none was deleted or hand-edited.

The [machine-readable closeout](paper_restore_remaining_2026-09-25.json) records
execution commits, payload identities, command times, per-file/typed comparisons,
private-evidence checksums and final-state assertions. Full private records remain
in the dedicated task evidence root. The documentation closeout commit is separate
from execution commits; its CI qualification and final-HEAD Wiki handoff are
reported after commit. The earlier PARTIAL evidence remains historical and links
here. This proves only the specified Paper package's limited RESTORE continuation;
it does not complete the excluded runtime, plugin, failure, disaster recovery,
automated BACKUP or maintenance-monitoring scopes.
