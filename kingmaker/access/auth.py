"""Accounts and sessions.

Passwords are not stored: PBKDF2-HMAC-SHA256 is, with a different salt for
each, and at login the same computation is redone and the results compared.
All with the standard library, no extra dependency.

The iteration count is stored next to every password: it can be raised later
without invalidating existing accounts, which update themselves at the first
successful login.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import logging
import secrets
import time
import uuid
from dataclasses import dataclass

from nicegui import app

from kingmaker import config
from kingmaker.access import permissions
from kingmaker.locale.i18n import t

log = logging.getLogger(__name__)

ALGORITHM = "sha256"
ITERATIONS = 600_000        # OWASP recommendation for PBKDF2-HMAC-SHA256
SALT_BYTES = 16

# A minimum of braking on rapid-fire attempts. Not a defence against a real
# attack, but it makes trying passwords one after another pointless.
MAX_ATTEMPTS = 5
WAIT_AFTER_ATTEMPTS = 30.0
# By address, as well as by name: whoever changed name at every attempt found
# the brake always reset.
MAX_ATTEMPTS_PER_IP = 20
# A username is an identifier, not free text: no spaces, no markup, so it ends
# up in a label or in a log without a second thought.
VALID_USERNAME = re.compile(r"[A-Za-z0-9._-]{2,32}")
_attempts: dict[str, tuple[int, float]] = {}


@dataclass(frozen=True)
class User:
    id: str
    username: str
    role: str
    active: bool
    must_change_pw: bool
    language: str | None = None
    units: str | None = None
    can_host: bool = False

    @property
    def role_name(self) -> str:
        return permissions.role_name(self.role)

    def can(self, action: str) -> bool:
        return permissions.can(self, action)


def _from_row(row: dict) -> User:
    return User(
        id=row["id"],
        username=row["username"],
        role=row["role"],
        active=bool(row["active"]),
        must_change_pw=bool(row["must_change_pw"]),
        language=row.get("language") if hasattr(row, "get") else None,
        units=row.get("units") if hasattr(row, "get") else None,
        can_host=bool(row.get("can_host")) if hasattr(row, "get") else False,
    )


# ---------------------------------------------------------------- password
def blend(password: str, salt_: str, iterations: int = ITERATIONS) -> str:
    """The password's digest, in hexadecimal."""
    raw_one = hashlib.pbkdf2_hmac(
        ALGORITHM, password.encode("utf-8"), bytes.fromhex(salt_), iterations)
    return raw_one.hex()


def new_salt() -> str:
    return secrets.token_bytes(SALT_BYTES).hex()


def random_password(words: int = 4) -> str:
    """Readable initial password: four short groups separated by dashes."""
    alphabet = "abcdefghijkmnopqrstuvwxyz23456789"   # no l/1 and o/0
    return "-".join("".join(secrets.choice(alphabet) for _ in range(4))
                    for _ in range(words))


# ------------------------------------------------------------------ accounts
def create_user(archive, username: str, password: str,
                role: str = permissions.PLAYER,
                must_change_pw: bool = False) -> User:
    username = username.strip()
    if not username:
        raise ValueError(t("auth.username_cannot_empty"))
    if not VALID_USERNAME.fullmatch(username):
        raise ValueError(t("auth.username_2_32_letters"))
    if len(password) < 8:
        raise ValueError(t("auth.password_must_least_8"))
    if role not in permissions.HIERARCHY:
        raise ValueError(t("auth.unknown_role", role=role))
    if archive.user_by_name(username):
        raise ValueError(t("auth.user_already_exists", username=username))

    salt_ = new_salt()
    data = {
        "id": uuid.uuid4().hex[:12],
        "username": username,
        "pw_hash": blend(password, salt_),
        "salt": salt_,
        "iterations": ITERATIONS,
        "role": role,
        "active": 1,
        "must_change_pw": 1 if must_change_pw else 0,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    archive.create_user(data)
    log.info("created user %r with role %s", username, role)
    return _from_row(data)


def change_password(archive, user_id: str, password: str, from_=None) -> None:
    """New password for `user_id`. `by` is who asks: the user themself, or an
    administrator; whoever wears someone else's clothes cannot change it."""
    if len(password) < 8:
        raise ValueError(t("auth.password_must_least_8"))
    if from_ is not None:
        who = from_ if isinstance(from_, User) else _from_row(archive.user_by_id(str(from_)) or {}) \
            if archive.user_by_id(str(from_)) else None
        if who is None or (who.id != user_id and not permissions.can(who, permissions.MANAGE_USERS)):
            raise ValueError(t("auth.you_cannot_change_password"))
        if is_impersonating() and real_id() != user_id:
            raise ValueError(t("auth.while_somebody_else_s"))
    salt_ = new_salt()
    archive.update_user(user_id, salt=salt_, pw_hash=blend(password, salt_),
                             iterations=ITERATIONS, must_change_pw=0)
    log.info("password changed for user %s (by %s)", user_id,
             getattr(from_, "id", from_))


def client_ip(client) -> str | None:
    """The address to count attempts with, or None if it is not reliable.

    Behind a reverse proxy (KINGMAKER_TRUST_PROXY) the first hop of
    X-Forwarded-For counts; under On Air everyone arrives from the relay with
    the same address, and counting them together would mean that twenty wrong
    attempts by anyone shut the door on the whole table: there the per-address
    brake is off and the per-name one remains.
    """
    request_ = getattr(client, "request", None)
    if config.TRUST_PROXY and request_ is not None:
        forwarded = request_.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip() or None
    if config.ON_AIR:
        return None
    return getattr(client, "ip", None) or None


def _ip_key(ip: str | None) -> str | None:
    ip = (ip or "").strip()
    return f"ip:{ip}" if ip else None


def remaining_wait(username: str, ip: str | None = None) -> float:
    """Seconds to wait before retrying, by name or by address."""
    wait = _wait_for(username.strip().lower(), MAX_ATTEMPTS)
    ip_key = _ip_key(ip)
    if ip_key:
        wait = max(wait, _wait_for(ip_key, MAX_ATTEMPTS_PER_IP))
    return wait


def _wait_for(key: str, max_: int) -> float:
    """Seconds left before one may retry, 0 if one already may."""
    how_many, last = _attempts.get(key, (0, 0.0))
    if how_many < max_:
        return 0.0
    return max(0.0, WAIT_AFTER_ATTEMPTS - (time.monotonic() - last))


def verify(archive, username: str, password: str,
             ip: str | None = None) -> User | None:
    """The user if the credentials are right, otherwise None.

    Beware: this function keeps the processor busy for half a second. Call it
    outside the event loop, or it blocks every other player.
    """
    key = username.strip().lower()
    ip_key = _ip_key(ip)
    if remaining_wait(username, ip) > 0:
        return None

    row = archive.user_by_name(username)
    if row is None:
        # We compute a digest anyway: if a non-existent user answered at once
        # and an existing one after half a second, the timing would reveal
        # which usernames exist.
        blend(password, new_salt())
        _mark_failure(key)
        if ip_key and _wait_for(key, MAX_ATTEMPTS) == 0:
            _mark_failure(ip_key)
        return None

    is_expected = row["pw_hash"]
    obtained = blend(password, row["salt"], int(row["iterations"]))
    if not hmac.compare_digest(is_expected, obtained):
        _mark_failure(key)
        # The per-address brake counts only while the per-name one has not
        # tripped yet: so an attacker hammering a single name does not shut the
        # door on someone with the right password for another account.
        if ip_key and _wait_for(key, MAX_ATTEMPTS) == 0:
            _mark_failure(ip_key)
        return None
    if not row["active"]:
        return None

    _attempts.pop(key, None)
    if ip_key:
        _attempts.pop(ip_key, None)
    archive.update_user(row["id"], last_login=time.strftime("%Y-%m-%dT%H:%M:%S"))
    # If meanwhile we raised the iterations, we take the chance now that we
    # have the clear password at hand.
    if int(row["iterations"]) < ITERATIONS:
        salt_ = new_salt()
        archive.update_user(row["id"], salt=salt_, pw_hash=blend(password, salt_),
                                 iterations=ITERATIONS)
        log.info("password iterations updated for %r", row["username"])
    return _from_row(row)


def _mark_failure(key: str) -> None:
    now = time.monotonic()
    # Old entries go away: before, the dictionary grew by one name at every
    # wrong attempt and never emptied.
    for old_one in [k for k, (_n, last) in _attempts.items()
                    if now - last > 10 * WAIT_AFTER_ATTEMPTS]:
        _attempts.pop(old_one, None)
    how_many, _ = _attempts.get(key, (0, 0.0))
    _attempts[key] = (how_many + 1, now)


# ------------------------------------------------------------------ session
SESSION_KEY = "user_id"
# Who really logged in, while wearing someone else's clothes.
REAL_KEY = "real_user"


def log_in(user: User) -> None:
    app.storage.user[SESSION_KEY] = user.id
    app.storage.user.pop(REAL_KEY, None)


def log_out() -> None:
    app.storage.user.pop(SESSION_KEY, None)
    app.storage.user.pop(REAL_KEY, None)


def id_in_session() -> str | None:
    try:
        return app.storage.user.get(SESSION_KEY)
    except RuntimeError:
        # Outside a request (timer, startup) the session does not exist.
        return None


# ------------------------------------------------------------ impersonation
#
# The administrator can look at the app through the eyes of another account
# without knowing its password. It is not an extra power: whoever administers
# has the database file, and from there can already rewrite a password. It is
# just the honest way to do it — without changing someone's password and
# locking them out of their account to find out why something does not work
# for them.
#
# Two fences, and they are what makes the matter acceptable: the permission is
# checked on the *real* user, not the worn one, so wearing a player's clothes
# is not a ladder to climb; and while it lasts it shows, written in the header
# and recorded in the kingdom journal.
def real_id() -> str | None:
    """Who really logged in, when wearing another account."""
    try:
        return app.storage.user.get(REAL_KEY)
    except RuntimeError:
        return None


def is_impersonating() -> bool:
    return bool(real_id())


def impersonator(archive) -> User | None:
    """The administrator behind the clothes, or None if there is no disguise."""
    real = real_id()
    if not real:
        return None
    row = archive.user_by_id(real)
    return _from_row(row) if row is not None else None


def wear(archive, user_id: str) -> User | None:
    """Steps into another account's clothes. None if it cannot be done.

    The permission is checked on who really logged in: a session already in
    disguise does not open another starting from scratch.
    """
    real_id_ = real_id() or id_in_session()
    real_row = archive.user_by_id(real_id_) if real_id_ else None
    if real_row is None or not real_row["active"]:
        return None
    if not permissions.can(_from_row(real_row), permissions.MANAGE_USERS):
        return None
    row = archive.user_by_id(user_id)
    if row is None or not row["active"] or row["id"] == real_id_:
        return None
    app.storage.user[REAL_KEY] = real_id_
    app.storage.user[SESSION_KEY] = row["id"]
    return _from_row(row)


def back_to_self(archive) -> User | None:
    """Takes the clothes off and returns to one's own account."""
    real = real_id()
    if not real:
        return None
    row = archive.user_by_id(real)
    app.storage.user.pop(REAL_KEY, None)
    if row is None or not row["active"]:
        log_out()
        return None
    app.storage.user[SESSION_KEY] = row["id"]
    return _from_row(row)


def current_user(archive) -> User | None:
    """Who is looking at this page, or None if not logged in."""
    user_id = id_in_session()
    if not user_id:
        return None
    row = archive.user_by_id(user_id)
    if row is None or not row["active"]:
        # Account deleted or deactivated while it was connected.
        log_out()
        return None
    return _from_row(row)


# -------------------------------------------------------------- first start
def ensure_admin(archive, username: str = "admin") -> str | None:
    """On first start creates the administrator and returns the generated password.

    If an account already exists it does nothing and returns None. The password
    is never written to disk: it appears once, in the console.
    """
    if archive.count_users() > 0:
        return None
    password = random_password()
    create_user(archive, username, password,
                role=permissions.ADMIN, must_change_pw=True)
    return password
