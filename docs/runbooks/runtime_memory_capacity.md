# Shared runtime memory capacity (D-108)

Repository implementation and production migration completed on 2026-09-14. This is one D-101 demand-driven slice,
before the first modded Game. Requirements: SYS-002/006/007, START-001/002; preserve D-096/097/098/105/106.
The production deployment uses stage **dev**, account/region from its canonical configuration.
The prod YAML remains an unresolved placeholder. No new persistent resource, IAM, Game profile,
loader, mod, Game creation, world copy, or lifecycle/state-machine change is included.

## Configuration and budget

Reuse `config/stages/dev.yaml:host_runtime.memory`, a host-wide deploy-time setting:

| Setting | Previous | Deployed |
|---|---|---|
| jvm_initial → INIT_MEMORY → Xms | 1G | 1G |
| jvm_maximum → MAX_MEMORY → Xmx | 2G | 4G |
| container_limit → Compose mem_limit | 2816MiB | 6144MiB |
| host | m8a.large, nominal 8192MiB | unchanged |

The candidate reserves 2048MiB inside the container above the heap and 2048MiB nominally outside
the container. The former covers JVM native allocations, metaspace, code cache, thread stacks,
direct buffers, GC structures, helper processes, charged filesystem cache and startup peaks.
These compete for the same allowance; it is not a reservation for each category. The latter
covers the OS/kernel, Docker/containerd, SSM, monitoring and other host processes. Guest MemTotal
is lower than nominal EC2 RAM; record both guest-total-minus-limit and idle MemAvailable before
release. Require at least 1536MiB guest-total-minus-limit and at least 512MiB idle
MemAvailable-minus-limit; otherwise stop and lower the candidate in Git and repeat validation.
Do not count swap as physical RAM or as a required safety dependency.

4G is preferred to 5G because the additional heap would consume much of the native/peak margin.
Xms remains 1G to avoid unnecessary initial commitment. This is a conservative initial budget,
not proof that an arbitrary modpack cannot exhaust memory. Workload evidence belongs to the
later concrete modded runtime slice. Do not disable the OOM killer, add auto-tuning, or change
the image, Java version or GC flags as part of this release.

The locked image remains itzg `2026.7.2-java25` at the existing sha256, Vanilla 26.2. Wishicraft
sets neither Aikar/MeowIce flags nor JVM_OPTS/JVM_XX_OPTS. The pinned entry script defaults the
optional flag sets off and maps independent INIT_MEMORY/MAX_MEMORY to JVM heap arguments.
Verify image-default environment and Java version without launching a production Minecraft
container; the isolated CI test checks real JVM arguments.

`runtime_memory.validate_memory` accepts explicit positive integer M/G JVM values and
MiB/GiB/M/G container values; no percentage, fractional, null, boolean or shell text. It enforces
512MiB <= Xms <= Xmx, Xmx >= 1GiB, container-minus-heap >= max(768MiB, 25% of heap), and nominal
host reserve >= 1GiB on the legacy 4GiB host or >= 2GiB on larger supported hosts. Known nominal
sizes are t3a.medium=4GiB, m8a.large=8GiB, r8a.large=m8a.xlarge=16GiB. Rendering and Target synth
both validate: a type-only downsize cannot leave an unsafe memory budget. Old valid 1G/2G/2816MiB
configuration renders byte-identically; Phase 1 compute.java_xmx=3G and frozen Phase 5/6 artifacts
are historical and remain unchanged.

## Integrity and durable records

`host_runtime.render_boot_time_artifacts` generates Compose and runtime.env. Their complete
SHA-256 values are in canonical manifest JSON, whose SHA-256 is the runtime config_digest.
Memory stays inside these hashes. No digest exemptions or compatibility allowlists are added.
CDK distributes that digest to START/STOP tasks, Admission CREATE defaults and recovery defaults.
The host's `/etc/wishicraft/runtime-contract.json` must agree. operation-v2 validates
Operation/lease/instance/Game/data_source/run, then exact manifest and both artifact hashes.
The same execution path serves START, SWITCH and RESET; Reconcile does not mutate runtime config.

| Record / artifact | Treatment |
|---|---|
| Compose, runtime.env, manifest, host contract | Update exactly four root-owned files while inactive |
| START/STOP CP environment, CREATE/recovery defaults | Redeploy the existing complete CP context |
| Existing A/B Game records and Whitelist policy | No writes; compare full private before/after inventory |
| Historical Operation runtime_target, switch_source, reset_plan | Preserve old digest and historical result |
| RESET world owner plan source/target on Data EBS | Preserve historical digest/plan; initialized/ancestry checks identify the Game and path |
| Stopped execution receipt on root EBS | Preserve exact bytes/hash, run, saved/removal-ready proof |
| Historical heartbeat / AutoStopIntent | Preserve; next normal run starts a new identity/continuity |
| SystemState observed execution | Reconcile refreshes observations; no fabricated receipt/target |
| Snapshots and durable backup recovery/provenance | Preserve original digest/description/owner chain |
| D-105 creation.config_digest and initial-owner plan | Immutable for this slice; never rewrite |

The inspected production registry contains only A/B and their three Whitelist policies; there
are no D-105 registered Games. A/B are authorized by the existing legacy catalog and have no
creation digest to migrate. A fresh START ignores an old **stopped** execution target and freezes
the new deployed digest in a new Operation; active/partial old runs are not eligible. Historical
Operations must not be replayed against the new host.

The limited planner requires a complete consistent Games inventory with exactly A/B plus the
known policies, ACTIVE/MATERIALIZED A/B, no creation field and no dynamic registry item. Unknown,
partial or D-105 inventory stops before deployment. D-105's creation digest is also part of its
immutable initial-owner plan, including failed materialization. Updating the DynamoDB digest alone
would break that contract. **This release does not implement migration of registered D-105 Games.**
Future CREATE uses the new exact digest; positive CREATE remains deferred. A future runtime/image
change after such registration needs a reviewed, provenance-preserving compatibility migration.
This limit avoids inventing a new migration framework or weakening current integrity checks.

## Offline plan and release sequence

Use new private temporary roots for every invocation/version; never modify earlier evidence.
`runtime_memory_migration.prepare` reproduces the predecessor stage from `03cde07`, checks that
only memory changes, and reproduces all four prior artifact hashes from D-098/D-106 production
evidence. It reuses the existing D-106 contract reconstruction and D-096 inactive-only installer.
Transport verifies the approved complete bundle digest before execution. The bundle does not
contain Game file paths as destinations and does not perform DynamoDB writes.

1. Complete repository tests/lint/type, all canonical synth contexts and pushed release CI,
   including isolated real Docker memory verification. Review Target and CP template differences.
   Target/Frozen/Web resources, workflows, IAM, instance type and block mappings must not change;
   CP changes are existing Lambda code assets and runtime-related environment values only.
2. Verify canonical wishicraft-dev STS Account ID, Tokyo region, exact Target instance and retained
   volumes, both permanent stack policies, all prior artifact/receipt evidence, and no competing
   operator. Read all inventory pages. Require Desired/Observed/EC2 STOPPED, HEALTHY, no active
   workflow/current Operation/Lock, no active SSM command/session, all three queues empty including
   in-flight/delayed, DNS absent, Data EBS healthy, backup/provenance valid and all alarms OK.
3. Capture exact Admission/Discord/Web reserved concurrency; set all three to zero using the
   established maintenance procedure. Drain and repeat the entire safety inventory. CREATE has
   no runtime Lock, so Lock absence alone does not protect registry membership.
4. Use the existing inspection-only maintenance EC2 boot. Check no Minecraft container/process/
   listener, inactive static canonical unit with Restart=no/no boot dependency, same stopped
   receipt, mount UUID/source/volume, exact artifact hashes and complete Game tree fingerprint.
   Record guest MemTotal/MemAvailable, swap, aggregate/per-service RSS, Docker accounting and
   pinned image Java/default flags. No normal START or synthetic Game on the production host.
5. Generate the reviewed four-file plan from that exact receipt and complete registry inventory:

   ```sh
   tools/dev-env run -- uv run python -m wishicraft.runtime_memory_migration --receipt "$MEMORY_ROOT/receipt.json" --inventory "$MEMORY_ROOT/games.json" --output "$MEMORY_ROOT/bundle"
   ```

   Confirm the candidate passes guest memory margins, receipt and registry are unchanged, and
   all plan hashes/owners/modes match. Deliver only the fixed bundle to the existing maintenance
   directory and run the same inactive-only installer under its existing host flock. It verifies
   IMDS instance, data preflight, no container/listener, unit inactivity, exact stopped receipt,
   all predecessors and source hashes before replacement. No wrapper/unit update is needed.
6. Read back all four files and hash chain, run Compose config validation with explicit stopped
   receipt Game/run/data inputs, and verify the same data tree/receipt. Stop the maintenance EC2
   normally after proving no Minecraft process/container. Preserve all old artifacts.
7. Deploy only WishicraftControlPlaneStack-dev with phase=8, two_games=true, reset=true,
   game_creation=true, whitelist_management=true and exact reviewed assembly. Keep admission
   closed. Read back every deployed digest/default and ensure stack UPDATE_COMPLETE; do not
   replace resources or relax stack policies. No Web/Target/Frozen deploy is required.
8. Reconcile after EC2 STOPPED; require fresh STOPPED/HEALTHY, unchanged Games/Whitelist/backup/
   provenance/volume identities, no DNS/Lock/current/workflow/SSM and empty queues. Observe alarm
   recovery naturally, without suppressing maintenance alarms. Restore exact prior concurrency
   only after all stages agree, and capture final inventory. Normal Minecraft START is deferred.

The user's request authorizes production continuation only while this is an established,
non-destructive inactive migration. Unexpected data, dynamic registrations, new resources,
replacement, relaxed integrity, unresolved mutation outcome or difficult rollback stops release.
Repository completion and production execution are recorded separately below.

## Retry, retention and rollback

The installer classifies each file by exact old/new hash and metadata. New canonical files are
left untouched, including mtime; old files are backed up then atomically replaced and fsynced.
Unknown/missing predecessor, wrong owner/mode, changed receipt or container presence fails closed.
After an interrupted four-file update, keep all admission closed, observe actual files/outcome,
and resume the **same** bundle against the same stopped receipt. Never create a new receipt or
rewrite the remaining files by hand. Read-back is mandatory after an ambiguous SSM result.

Host and CP updates are not one transaction. Mixed digests are intentionally incompatible and
must never be exposed to new admissions. If CP deployment rolls back, the host does not
automatically revert: finish the matching CP deployment or execute a reviewed inverse file plan
while still inactive. Before any new START/CREATE, an inverse plan can swap exact known new hashes
back to the preserved predecessor bytes with the same installer and a separate backup namespace;
restore the predecessor CP assembly, then verify both sides and Reconcile. No Game/world rollback
is needed. Do not run the old D-096 initial installer against an existing receipt.

After any new run, preserve its historical target and normally stop it first; after a D-105
CREATE, this limited reverse plan is not sufficient. Prefer forward fixing. Never rewrite
historical provenance to make a rollback pass. Retain old manifest/Compose/env/contract, release
assemblies and migration evidence while any retained Operation, receipt or Snapshot/provenance
references them. Since provenance has no TTL, no automatic deletion deadline is introduced.

## Production closeout — 2026-09-14

Release `03d19f2f0793d47c6339360d105bd2367a5a8a70`,
[CI 34804883136](https://github.com/eash-misoni/wishicraft-server/actions/runs/34804883136),
completed all three jobs, including the real pinned-image memory/lifecycle tests. Java was
OpenJDK 25.0.3; actual JVM arguments were -Xms1G/-Xmx4G and Docker HostConfig.Memory was
6442450944 bytes. Both initial start and restart passed, with saved synthetic world retained.
The earlier CI attempt failed because `docker top -eo args` omitted PID; the corrected test uses
`-eo pid,args`. This was a verification-command defect, not a production JVM change.

Production guest measurements during Minecraft-free maintenance boot:

| Measurement | MiB |
|---|---:|
| Nominal EC2 RAM | 8192 |
| Guest MemTotal | 7757.97 |
| Idle MemAvailable | 7118.02 |
| Guest total minus container limit | 1613.97 |
| Idle available minus container limit | 974.02 |
| Summed process RSS | 422.94 |
| Container allowance above maximum heap | 2048 |

Both guest release gates passed. The actual guest host allowance is about 1.58GiB, not the
nominal 2GiB; approximately 0.95GiB remains above the container limit after the measured idle
host load. RSS includes inspection/SSM and may count shared pages more than once. Docker 25.0.16
uses cgroup v2, swap is zero, and the image had no optional JVM/memory flag overrides. These are
idle measurements, not modded peak-load evidence.

With Admission/Discord/Web concurrency held at zero, the reused inactive installer updated
exactly four files. Read-back verified the complete new hash chain and Compose configuration,
and the exact old receipt, canonical unit and 920-entry Game tree. The first postflight check
expected an integer but Compose returned the exact decimal string `"6442450944"`; its failed
evidence was retained. A new read-only diagnostic and v2 verification checked the observed
string type, decimal syntax and exact byte count, then repeated all original integrity/data
checks successfully. No artifact was reinstalled to fix this test representation issue.

EC2 was normally stopped before the CP-only deployment. The reviewed assembly deployed with
UPDATE_COMPLETE; all 11 Lambda code hashes, four runtime environment values and complete live
template were verified against it. Physical resource identities remained unchanged. Target,
Frozen Data and Web templates and update timestamps stayed unchanged, as did both permanent
stack policies. No normal Minecraft START, Game registration/materialization or snapshot action
was performed. Admission concurrency was restored exactly after the safety gate passed.

Maintenance generated the two existing alarms reported by the user. DesiredStoppedEc2Running
detects Desired STOPPED while maintenance EC2 is running; RuntimeObservationUnknown requires a
fresh current-boot runtime heartbeat while EC2 runs outside an owned lifecycle transition.
The maintenance boot did not start Minecraft. After normal EC2 stop and canonical Reconcile,
the alarms naturally returned OK at **04:31:53 UTC** and **04:31:59 UTC**, respectively
(13:31:53 / 13:31:59 JST). No alarm thresholds, actions or states were overridden.

Final inventory at **04:34:15 UTC** after admission restoration: Desired/EC2 STOPPED, HEALTHY,
45 alarms OK, all three queues empty, no current Operation/Lock/workflow/SSM command/session/DNS.
Instance `i-04fc0629dc4ea466e` remains m8a.large; root `vol-092c04a633ffc6010` and retained Data
`vol-03ac9f534326c345c` retain their attachments and ownership. Data EBS status is OK.
All 73 historical Operations compare equal; A/B records, generation/path/Game metadata,
three Whitelist policies, nine Snapshots and 16 provenance items compare equal. Historical
RESET owner plans and stopped receipt still refer to their original runtime. Full data-tree
fingerprint equality covers world, metadata and whitelist bytes.

[Sanitized production evidence](../evidence/runtime_memory_capacity_production_2026-09-14.json)
records exact hashes, measured margins, release and preservation proofs. Private raw inventory,
old/new bundles, inverse-plan preview, release assembly and failed/successful diagnostics remain
in separate temporary evidence roots. Keep durable copies with the retained provenance; temporary
directories are not a retention mechanism. Old artifact bytes are additionally backed up by the
installer on the host and remain reproducible from the pinned Git history. Rollback was planned
and the same installer's retry paths tested; production rollback was not executed.

## Evidence and remaining work

Initial read-only production inventory, 2026-09-14 03:52 UTC: m8a.large, STOPPED/HEALTHY,
no Lock/workflow/SSM/session/DNS, three empty queues, 45 alarms OK, 9 Snapshots and 16 provenance
items. A/B plus three policies; no dynamic registry. The completed migration is recorded above.
Local Docker CLI is unavailable. CI's pinned-image test checks inspect.HostConfig.Memory,
INIT_MEMORY/MAX_MEMORY and the actual JVM -Xms/-Xmx arguments, then normal save/STOP/restart
and retained synthetic world. AWS/SSM/systemd are substituted there; it is not production E2E.

The next modded slice still needs a concrete Minecraft/loader/Java combination, pinned loader/mod
artifacts, runtime compatibility/recovery design and real modded smoke/load evidence. Neither
NeoForge/Fabric/Create/Farmer's Delight nor positive CREATE/materialization is part of D-108.

## External basis

- [itzg independent heap inputs](https://docker-minecraft-server.readthedocs.io/en/latest/configuration/jvm-options/)
- [Pinned 2026.7.2 launch implementation](https://github.com/itzg/docker-minecraft-server/blob/2026.7.2/scripts/start-finalExec)
- [Docker memory constraints and OOM behavior](https://docs.docker.com/engine/containers/resource_constraints/)
- [Linux cgroup v2 memory accounting](https://docs.kernel.org/admin-guide/cgroup-v2.html)
- [AWS nominal instance memory](https://docs.aws.amazon.com/ec2/latest/instancetypes/gp.html)

Local validation (2026-09-14): 1,336 tests passed; Ruff lint/format and mypy (200 files) passed;
all eight canonical synth contexts passed. Full deployed Target template equality holds. The
current CP candidate differs only in 11 existing Lambda code assets and four runtime-related
environment values (START/STOP digest, CREATE defaults, backup recovery runtime). No IAM,
state-machine, resource, volume or network difference. Old digest is
`1c0b8a75989e4ac81130a7ab24df93c2a88793ed1509752e3a429c2f08f06c1e`; new digest is
`373dfb9c768b8d4b0b318793551212e0de5d5fe07b8ae4dc31791226e9ba5048`.

Earlier validation failures were preserved: restricted PyPI access prevented CDK dependency
bundling; the canonical bundling-cache preparation fixed that environment issue. Historical
Phase 5/6/Reset fixtures were corrected to load their original Git configuration, maintaining
exact old artifact checks. A subsequent /private/tmp fixture inherited macOS group 0 rather
than the user's group 20; the new default user-temporary-root run passed without weakening
owner checks. Four interruption points in the real installer converge on retry while keeping
canonical file mtimes, old backups, stopped receipt and synthetic world bytes unchanged.

First Docker CI `34804568267` failed after container memory/env inspect checks, at `docker top`
with an args-only ps format. The test now retains the PID column required for process identity
and preserves command stderr on failure. This is a test-harness correction; production code and
runtime digest are unchanged. The replacement CI must pass before maintenance begins.
