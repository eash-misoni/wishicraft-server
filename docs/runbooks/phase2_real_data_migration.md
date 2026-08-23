# Phase 2b real-data migration runbook

## Scope and fixed identities

This runbook moves the existing dev data EBS from the stopped Phase 1 host to the
independent stopped Phase 2 target host. It does not update either CloudFormation
stack. The migration script fixes and validates these identities before touching the
filesystem:

- source EC2: `i-021eaa7f33ddaf0a6`
- target EC2: `i-04fc0629dc4ea466e`
- data EBS: `vol-03ac9f534326c345c`
- AZ: `ap-northeast-1a`
- filesystem: XFS, UUID `420cea6d-0520-4436-bb5a-db1191f1e63b`
- game directory: `/srv/minecraft/games/game-vanilla-main/server`
- ownership transition: only `server.properties`, `0:993 / 0640` to
  `993:993 / 0640`

The script has no filesystem creation or repair path, no force-detach path, and no
recursive ownership operation. It validates the target instance through IMDS, maps
the EBS volume by NVMe serial, rejects partitions and additional signatures, and
mounts only the fixed UUID.

AL2023 util-linux 2.37.4 uses `--output TYPE` for signature output; short `-o`
means an erase offset and is forbidden by the reviewed artifact.
Filesystem classification uses file tests rather than GNU `stat %F` wording because
AL2023 reports an empty regular file as `regular empty file`.

## Ordered execution gate

1. Validate the repository, commit/push it, and require successful CI.
2. Confirm account/region, both EC2 instances stopped, the volume attached to the
   Phase 1 instance, both instances in the fixed AZ, and target SG ingress empty.
3. Create and tag one rollback snapshot, then wait for `completed`.
4. Reconfirm Phase 1 stopped; normally detach without force and wait for `available`.
5. Attach at `/dev/sdf` to the target and confirm `DeleteOnTermination=false`.
6. Start only the target and wait for SSM Online. Confirm Phase 1 remains stopped.
7. Run `--raw-preflight` before mount, then install the reviewed artifact and run
   `--mount-existing`, `--filesystem-preflight`, and `--world-record`.
8. Record non-content metadata and run `--properties-migrate`. The command changes
   exactly one inode and proves mode, inode, size, type, and SHA-256 are unchanged.
9. Install the canonical portless Host Runtime artifacts. Reconfirm the Phase 1
   interlock and pinned image, then explicitly start the Host Runtime.
10. Require READY, health, existing-world evidence, data-EBS bind evidence, no OOM or
    restart, and safe `enable-rcon=false` metadata verification.
11. Stop through the Host Runtime systemd unit, require a normal container exit and
    no remaining listener, then repeat start/READY/persistence/stop once.
12. Stop the target normally and leave the data EBS attached. Leave Phase 1 stopped,
    the rollback snapshot retained, target ingress empty, and both stacks untouched.

## Failure boundary

Before the first real-world container start, rollback may restore the single-file
owner and normally reattach the volume to stopped Phase 1. After the first start,
Minecraft has written real data: stop the container and target, preserve the current
attachment and snapshot, and require human review before any rollback. Never expose
secret properties in command output.

## Known CloudFormation state

Manual detach/attach intentionally creates temporary drift for the Phase 1
`VolumeAttachment`. Do not reconcile, import, or deploy either stack during this
migration. IaC attachment ownership is a separate follow-up phase.
