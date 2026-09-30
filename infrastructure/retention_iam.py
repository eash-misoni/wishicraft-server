"""Unattached IAM contract for the future RETENTION delete-only task role."""

from __future__ import annotations


def delete_snapshot_policy(
    *, partition: str, region: str, project: str, stage: str, game_id: str, volume_id: str
) -> dict[str, object]:
    """Return the offline-reviewed second boundary; application proof remains primary."""
    return {
        "Effect": "Allow",
        "Action": "ec2:DeleteSnapshot",
        "Resource": f"arn:{partition}:ec2:{region}::snapshot/*",
        "Condition": {
            "StringEquals": {
                "aws:ResourceTag/Project": project,
                "aws:ResourceTag/Stage": stage,
                "aws:ResourceTag/WishicraftCategory": "backup",
                "aws:ResourceTag/WishicraftGameId": game_id,
                "aws:ResourceTag/WishicraftSourceVolumeId": volume_id,
                "aws:ResourceTag/WishicraftSchemaVersion": "1",
                "aws:ResourceTag/WishicraftProtected": "false",
                "ec2:Region": region,
            }
        },
    }


# ec2:Owner and ec2:ParentVolume are intentionally absent until their DeleteSnapshot
# request-context value forms are demonstrated by simulation/DryRun at the release gate.


def shared_delete_policy(
    *,
    partition: str,
    region: str,
    account: str,
    project: str,
    stage: str,
    volume_id: str,
    snapshot_id: str = "*",
) -> dict[str, object]:
    """Future shared-v2 policy; canonical FF never attaches this statement.

    SAR: snapshot ARN has an empty account segment; ParentVolume is ARN, Owner is
    account ID. Exact target can further narrow the separately approved qualification.
    """
    return {
        "Effect": "Allow",
        "Action": "ec2:DeleteSnapshot",
        "Resource": f"arn:{partition}:ec2:{region}::snapshot/{snapshot_id}",
        "Condition": {
            "StringEquals": {
                "ec2:Owner": account,
                "ec2:Region": region,
                "aws:ResourceTag/Project": project,
                "aws:ResourceTag/Stage": stage,
                "aws:ResourceTag/WishicraftCategory": "backup",
                "aws:ResourceTag/WishicraftSchemaVersion": "2",
                "aws:ResourceTag/WishicraftBackupScope": "shared-volume",
                "aws:ResourceTag/WishicraftProtected": "false",
                "aws:ResourceTag/WishicraftSourceVolumeId": volume_id,
            },
            "ArnEquals": {
                "ec2:ParentVolume": f"arn:{partition}:ec2:{region}:{account}:volume/{volume_id}"
            },
        },
    }
