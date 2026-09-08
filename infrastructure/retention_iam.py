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
