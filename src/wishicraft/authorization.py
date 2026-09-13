"""Shared Guild role policy for signed Discord commands and Web OAuth membership."""


def role_authorized(
    roles: object, *, player_role_id: str, admin_role_id: str, admin_only: bool = False
) -> bool:
    if not isinstance(roles, list) or not all(isinstance(role, str) for role in roles):
        return False
    allowed = {admin_role_id} if admin_only else {player_role_id, admin_role_id}
    return bool(allowed.intersection(roles))
