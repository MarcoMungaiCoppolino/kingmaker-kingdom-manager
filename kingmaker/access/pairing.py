"""The pairing code: how a launcher joins the table without a password.

The administrator, logged into the game, makes a code from the accounts
dialog and tells it to the person whose launcher is joining; that launcher
sends the code and a name for its PC to `POST /_launcher/pair` at the
table's address, and receives the cloud credential. No password ever
enters a launcher: the only thing a program at a hijacked address could
collect is a code that dies at its first use, its third wrong try, or ten
minutes, whichever comes first.

One code at a time per server, kept here as its SHA-256; a new one
replaces the old. The code is eight letters and digits from the alphabet
`auth.random_password` uses (no l/1, o/0), shown as `abcd-efgh`: about
forty bits, which with three tries online is plenty.
"""
from __future__ import annotations

import hashlib
import hmac
import time

from kingmaker.access import auth

LIFETIME = 600.0
ATTEMPTS = 3
clock = time.monotonic                  # replaced by the tests
_active: dict | None = None


def normalize(code: str) -> str:
    return code.strip().lower().replace("-", "").replace(" ", "")


def _digest(code: str) -> str:
    return hashlib.sha256(normalize(code).encode("ascii", "ignore")).hexdigest()


def new_code(made_by: str = "") -> str:
    """A fresh code, replacing any other; `made_by` is for the journal."""
    global _active
    code = auth.random_password(words=2)
    _active = {"hash": _digest(code), "expires": clock() + LIFETIME, "attempts": 0,
               "made_by": made_by}
    return code


def active() -> dict | None:
    """The live pairing, or None once it expired."""
    global _active
    if _active is not None and clock() > _active["expires"]:
        _active = None
    return _active


def check(code: str) -> bool:
    """True once, for the right code while it lives. A wrong try counts,
    and the third one kills the code."""
    global _active
    current = active()
    if current is None:
        return False
    if hmac.compare_digest(_digest(code), current["hash"]):
        _active = None
        return True
    current["attempts"] += 1
    if current["attempts"] >= ATTEMPTS:
        _active = None
    return False


def forget() -> None:
    global _active
    _active = None
