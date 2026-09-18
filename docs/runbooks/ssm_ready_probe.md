# SSM READY probe execution boundary

Scope: D-109 observation transport fix and the existing create-survival prepared
world's first successful formal START/READY/materialization/STOP. Production
qualification below is separate from repository qualification. No new CREATE,
world regeneration, package/version change, timeout extension or relaxed READY.

## Root cause and minimal correction

Control Plane previously transported the exact packaged probe through
`printf ... | base64 --decode | python3 -`. The probe imports the Game package
observer from the repository when available, otherwise the installed adjacent
`game_package.py`. Direct installed helper execution supplies its script directory;
stdin execution supplies the shell working directory instead. Repository-import
unit/Docker tests did not cover that shell boundary.

Read-only production maintenance on 2026-09-18 measured root (uid 0), cwd `/usr/bin`,
`/usr/bin/python3`, Python 3.9.25, unset PYTHONPATH/PYTHONHOME. sys.path was the empty
entry (cwd), `/usr/lib64/python39.zip`, `/usr/lib64/python3.9`, its `lib-dynload`,
`/usr/lib64/python3.9/site-packages`, `/usr/lib/python3.9/site-packages`.
Installed game_package.py is root:root 0644 in `/usr/local/libexec/wishicraft`.
There was no installed wishicraft Python distribution supplying that module.

The transport now retains exactly the same probe bytes and runs its stdin from
`/usr/local/libexec/wishicraft`, with `python3 -E -s -B -`: ignore inherited Python
environment overrides and user site, avoid bytecode writes, and use the same
adjacent module location as installed host helpers. Missing directory stops the
shell; missing module or failed observation never establishes READY. This is a
fixed deployment path, not user input or a production-only exception.

READY predicates, parser, package validation, expected run/Game/data source,
health/protocol checks and workflow deadlines are unchanged. No host file changes
or migration are required. Common digest remains
`64bbfff50b03dd0411ca496ada7060d93d015ecd81aab02ca14963dcb9f8073c`; package digest remains
`720deb9f4a32515af87c7f620cf9d2667cabbc7e9b793db109cb011b71122f0b`.
Minecraft 1.21.1 / NeoForge 21.1.219 / Create 6.0.10 / Farmer's Delight 1.3.4 stay pinned.

## Regression boundaries

- A subprocess `/bin/sh` test uses the generated pipeline/interpreter flags from an
  unrelated cwd with hostile PYTHONPATH. Only fixture path/payload are replaced;
  it imports the real installed-style module, verifies the pinned catalog and
  rejects missing module/directory. The production payload remains byte-identical.
- Real NeoForge Docker executes the unmodified generated command and probe bytes
  in canonical absolute runtime layout. Real package files, Docker and Minecraft
  protocol are observed; disposable CI substitutes systemd and lacks production
  IMDS/retained mount, so this alone does not claim full EC2 READY.
- Wrong package/loader/version/hash/Game/generation path/run and malformed probe
  responses remain rejected. Health/RCON alone do not substitute for READY.
- Recovery fixture leaves initialized ownership, UNMATERIALIZED DB, saved world,
  terminal old receipt and no container. New host START uses another container/run,
  retains world inode and verified cache bytes/mtime, and observes the expected
  package via the exact stdin command before fixture materialization completion.
  The production Control Plane's existing READY-gated commit remains authoritative.

## Production gates and status

Beginning preflight 2026-09-18 11:36:49 UTC: stopped, 45 alarms OK, queues empty,
no Lock/workflow/SSM/session/DNS, nine snapshots and sixteen provenance records.
Canonical caller matched configured account. All seven Game/registry/policy records
and 79 historical Operations matched the previous closeout.
Read-only maintenance SSM `f5420519-64f9-4144-bd8b-9ca7056ad278` confirmed complete
Game tree, A/B tree, world inode, initialized ownership, stopped receipt, finalized
recovery sidecar, cache/projection and all installed artifact hashes/metadata equal
to the previous terminal closeout. No container/Java/listener existed. Minecraft
was not started; maintenance EC2 normal stop was requested after inspection.

Release requires both CIs, stopped healthy preflight and a live diff limited to
Control Plane Lambda code. Any IAM/resource/state-machine/Target/Data/unrelated Web
change stops release. Re-read retained disk identities immediately before formal
START. Use a new admitted request and verify its retry returns the same Operation.
Only successful READY may commit MATERIALIZED, generation 1 and the same world path.
Then use normal STOP, canonical save proof and container cleanup, and verify final
STOPPED/HEALTHY, 45 OK, no active work or DNS, unchanged A/B and backup provenance.
Only after all gates pass may the three ingress functions return to their prior
settings. Another production bug stops this slice after safe containment.

**Production code deployment and new START are not yet performed at this checkpoint.**

Repository checkpoint: 1,443 full tests passed with dependency network access, plus
2 later READY-gated commit regressions passed. Lint/format/type and production
context synth passed. Initial sandbox-only tests/synth failed on PyPI DNS during
hash-locked bundling, not application assertions. Local Docker CLI is unavailable;
real Docker qualification is required in CI. Synth versus current live template
shows only Code changes to the eleven existing Control Plane Lambdas sharing the
bundle, with no new resources or IAM/state-machine/configuration changes.


## Release blocked before deployment — second observation defect

The import correction is insufficient for end-to-end READY. Review of the next
Control Plane boundary found `probe._parse_protocol` independently checking
`version_match` against global `EXPECTED_MINECRAFT_VERSION = "26.2"`. The host's
integrity-checked NeoForge package correctly reports Minecraft 1.21.1 and true,
but the parser rejects this as `protocol version comparison is inconsistent`.
`status.py` calls this parser without a Game-specific expected version input.

A local reproduction uses the existing complete running probe fixture, changes
reported_version to 1.21.1 and protocol_version to 767, preserves ready=true and
version_match=true, then calls parse_host_runtime_probe with its exact instance.
It raises ProbeContractError with the above message. Read-only retrieval of the
currently deployed Reconcile S3 code asset confirmed probe.py is byte-identical
to the repository parser, including the fixed 26.2 predicate. This is a separate
pre-existing production defect, discovered before another production START.

The current Docker fixture verifies real host package/protocol observation but
cannot certify Control Plane acceptance: CI lacks production IMDS/mount context.
The previously separate host/protocol and parser tests covered different expected
versions. Green transport/Docker tests must not override this release blocker.

**No production code deploy, host migration, new START or materialization commit
was performed.** Keep all three ingress functions closed. Existing initialized
world, stopped old receipt and absent container remain intact. Do not change this
parser within the import-only slice or trust host-supplied version_match blindly.
The next separately scoped correction must supply the Control Plane parser with
an independently validated expected version from the bound Game/package identity,
preserve wrong-version/Game/run/generation rejection, and test the full transported
response through Status/Reconcile before retrying formal START.

Final production observation **2026-09-18 11:51:00 UTC**: STOPPED/HEALTHY,
EC2 stopped, 45 alarms OK, no Current Operation/Lock/workflow/SSM/session/DNS,
three queues empty. Seven Game/registry/policy records, all 79 Operations,
16 provenance rows, nine snapshot metadata entries, volume metadata and four
CloudFormation templates matched beginning baseline. The maintenance-only
DesiredStoppedEc2Running alarm recovered naturally; no alarm suppression occurred.
Ingress remains closed. There are no new START/STOP Operation IDs for this slice.


## Repository qualification complete; production remains blocked

Fix commit `f95fb02328961a99b8ddb2319f72918877e95603` passed
[standard CI 35341251311](https://github.com/eash-misoni/wishicraft-server/actions/runs/35341251311)
and [NeoForge Docker CI 35341251322](https://github.com/eash-misoni/wishicraft-server/actions/runs/35341251322).
The final suite has 1,445 tests; lint, format, type, synth, Web and real Docker
lifecycle checks passed. At 11:50:40 UTC Docker recorded
`INITIALIZED_PREPARED_WORLD_REUSED_NEW_RUN_READY`; the unmodified stdin command
observed create-survival and Vanilla in six checkpoints, followed by
`HOST_NEOFORGE_START_SWITCH_RESET_WHITELIST_PASSED` at 11:53:01 UTC.
These qualify the import correction and host reuse, not the blocked production
parser/READY/materialization boundary. No new production capacity sample or normal
START/STOP proof exists in this slice. Whitelist remains 0/0/0; client access is
not ready and ingress was not restored.
