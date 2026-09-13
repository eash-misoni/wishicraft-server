"""Shared Guild role policy for signed Discord commands and Web OAuth membership."""


def role_authorized(
    roles: object, *, player_role_id: str, admin_role_id: str, admin_only: bool = False
) -> bool:
    if not isinstance(roles, list) or not all(isinstance(role, str) for role in roles):
        return False
    allowed = {admin_role_id} if admin_only else {player_role_id, admin_role_id}
    return bool(allowed.intersection(roles))


def operation_authorized(
    operation: str, roles: object, *, player_role_id: str, admin_role_id: str
) -> bool:
    """Canonical daily-operation policy, independent of the ingress channel."""
    return operation in {
        "STATUS",
        "START",
        "STOP",
        "SWITCH",
        "BACKUP",
        "RESET",
    } and role_authorized(
        roles,
        player_role_id=player_role_id,
        admin_role_id=admin_role_id,
        admin_only=operation in {"BACKUP", "SWITCH"},
    )
