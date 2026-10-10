"""Who may do what.

One place where it is decided, instead of `if user.role == ...` scattered over
five thousand lines of interface. Panels ask `can(user, ACTION)` and draw
themselves accordingly; the functions that write ask again, because hiding a
button is not a defence.
"""
from __future__ import annotations
from kingmaker.locale.i18n import t

# The roles, from the most to the least powerful. Each one may do everything
# the following ones may.
ADMIN = "admin"
GM = "gm"
PLAYER = "player"
SPECTATOR = "spectator"

HIERARCHY = (ADMIN, GM, PLAYER, SPECTATOR)


def role_name(role: str) -> str:
    """The role as shown to people, in the viewer's language."""
    return t(f"permissions.role.{role}") if role in HIERARCHY else role


def role_description(role: str) -> str:
    """What the role may do, in one line."""
    return t(f"permissions.role_description.{role}") if role in HIERARCHY else ""

# ---------------------------------------------------------------------------
# The actions, with the minimum role needed to perform them.
EDIT_KINGDOM = "edit_kingdom"
UPLOAD_IMAGE = "upload_image"
SEE_SECRETS = "see_secrets"
MANAGE_CHARACTERS = "manage_characters"
OWN_CHARACTER = "own_character"
MANAGE_STABLE = "manage_stable"
PLAN_TRAVEL = "plan_travel"
CONTROL_CLOCK = "control_clock"
MANAGE_USERS = "manage_users"
EXPORT_SAVE = "export_save"
RESET_KINGDOM = "reset_kingdom"
MIN_ROLE = {
    EDIT_KINGDOM: PLAYER,
    UPLOAD_IMAGE: GM,
    SEE_SECRETS: GM,
    # Who plays whom is decided by the table, not by a single player.
    MANAGE_CHARACTERS: GM,
    # One's own sheet, instead, is kept by each player: portrait, marker, Speed.
    # The check on *which* character is done by `can_on_character`.
    OWN_CHARACTER: PLAYER,
    # The stable belongs to the kingdom: whoever plays the kingdom manages it.
    MANAGE_STABLE: PLAYER,
    PLAN_TRAVEL: PLAYER,
    # The clock belongs to the GM: they decide when time flows and when it
    # stops to play out a scene.
    CONTROL_CLOCK: GM,
    MANAGE_USERS: ADMIN,
    # The save holds the whole campaign, GM notes included: not something a
    # player should be able to walk away with.
    EXPORT_SAVE: ADMIN,
    RESET_KINGDOM: ADMIN,
}
# Who may host is no longer a flag on an account: a launcher joins the table
# with a pairing code the administrator makes (MANAGE_USERS), and holds the
# cloud credential from then on. `users.can_host` stays in the schema, unread.


def level(role: str) -> int:
    """Position in the hierarchy: lower means more power."""
    try:
        return HIERARCHY.index(role)
    except ValueError:
        # A role we do not know must not become an extra permission.
        return len(HIERARCHY)


def at_least(user, required_role: str) -> bool:
    """True if the user has that role or a higher one."""
    if user is None or not getattr(user, "active", False):
        return False
    return level(user.role) <= level(required_role)


def can(user, action: str) -> bool:
    """True if the user may perform the action."""
    required = MIN_ROLE.get(action)
    if required is None:
        # An action never declared: better to deny it and notice, than to grant
        # it by oversight.
        raise KeyError(f"unknown action: {action!r}")
    return at_least(user, required)


def can_on_character(user, character) -> bool:
    """True if the user may edit *that* character.

    The GM governs them all; a player only those linked to their account. A
    character with no linked account stays the GM's: if having none were
    enough, anyone could adopt it.
    """
    if user is None or character is None:
        return False
    if can(user, MANAGE_CHARACTERS):
        return True
    if not can(user, OWN_CHARACTER):
        return False
    owner = character.get("user_id") if isinstance(character, dict)         else getattr(character, "user_id", None)
    return bool(owner) and owner == user.id


class NotAllowed(PermissionError):
    """The user lacks the permission for the requested action."""


def require(user, action: str) -> None:
    """Like `can`, but raises `NotAllowed`: for the functions that write."""
    if not can(user, action):
        raise NotAllowed(action)

