"""The pairing code: how a launcher joins the table without a password.

The administrator's launcher makes a code while it hosts (`POST
/_launcher/pairing`, with the Dropbox key it authorised for that one host)
and the person tells it to whoever is joining; their launcher sends the
code and a name for its PC to `POST /_launcher/pair` at the table's
address, and receives the cloud credential with that key. No password ever
enters a launcher: the only thing a program at a hijacked address could
collect is a code that dies at its first use, its third wrong try, or ten
minutes, whichever comes first. Since 2.2.0 the game's accounts dialog
makes no codes: letting a launcher in is the administrator's act alone.

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


def new_code(made_by: str = "", handout: dict | None = None) -> str:
    """A fresh code, replacing any other; `made_by` is for the journal, and
    `handout` is what the code hands out when it is spent (the key made for
    this one host), kept here and nowhere else until then."""
    global _active
    code = auth.random_password(words=2)
    _active = {"hash": _digest(code), "expires": clock() + LIFETIME, "attempts": 0,
               "made_by": made_by, "handout": dict(handout or {})}
    return code


def active() -> dict | None:
    """The live pairing, or None once it expired."""
    global _active
    if _active is not None and clock() > _active["expires"]:
        _active = None
    return _active


def take(code: str) -> dict | None:
    """The code's hand-out, once, for the right code while it lives; None
    for a wrong one, which counts, the third killing the code."""
    global _active
    current = active()
    if current is None:
        return None
    if hmac.compare_digest(_digest(code), current["hash"]):
        _active = None
        return dict(current.get("handout") or {})
    current["attempts"] += 1
    if current["attempts"] >= ATTEMPTS:
        _active = None
    return None


def check(code: str) -> bool:
    """True once, for the right code while it lives (`take` without the
    hand-out)."""
    return take(code) is not None


def forget() -> None:
    global _active
    _active = None
