from infrastructure.retention_iam import delete_snapshot_policy


def test_future_delete_policy_is_accountless_tag_scoped_and_not_attached() -> None:
    policy = delete_snapshot_policy(
        partition="aws",
        region="ap-northeast-1",
        project="wishicraft",
        stage="dev",
        game_id="game-vanilla-main",
        volume_id="vol-data",
    )
    assert policy["Action"] == "ec2:DeleteSnapshot"
    assert policy["Resource"] == "arn:aws:ec2:ap-northeast-1::snapshot/*"
    condition = policy["Condition"]["StringEquals"]  # type: ignore[index]
    assert condition == {
        "aws:ResourceTag/Project": "wishicraft",
        "aws:ResourceTag/Stage": "dev",
        "aws:ResourceTag/WishicraftCategory": "backup",
        "aws:ResourceTag/WishicraftGameId": "game-vanilla-main",
        "aws:ResourceTag/WishicraftSourceVolumeId": "vol-data",
        "aws:ResourceTag/WishicraftSchemaVersion": "1",
        "aws:ResourceTag/WishicraftProtected": "false",
        "ec2:Region": "ap-northeast-1",
    }
    assert "ec2:Owner" not in condition
    assert "ec2:ParentVolume" not in condition
    assert all(
        forbidden not in str(policy)
        for forbidden in (
            "CreateSnapshot",
            "DeleteVolume",
            "AttachVolume",
            "DetachVolume",
            "StartInstances",
            "StopInstances",
            "RestoreSnapshot",
        )
    )
