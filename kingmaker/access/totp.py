"""Time-based one-time codes (RFC 6238 over RFC 4226): the second factor
of an account. A secret of twenty random bytes, shown once as base32 and
as an `otpauth://` link for the authenticator app; six digits every thirty
seconds; a code is accepted from the step before to the step after, for
clocks that drift. Standard library only."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
import urllib.parse

STEP = 30
DIGITS = 6
WINDOW = 1                  # steps either side that still pass
SECRET_BYTES = 20
RECOVERY_CODES = 8


def new_secret() -> bytes:
    return secrets.token_bytes(SECRET_BYTES)


def encode_secret(secret: bytes) -> str:
    """The secret as the authenticator apps want it typed: base32, no
    padding, in groups of four."""
    text = base64.b32encode(secret).decode("ascii").rstrip("=")
    return " ".join(text[i:i + 4] for i in range(0, len(text), 4))


def decode_secret(text: str) -> bytes:
    cleaned = "".join(text.split()).upper()
    cleaned += "=" * (-len(cleaned) % 8)
    return base64.b32decode(cleaned)


def otpauth_url(secret: bytes, account: str, issuer: str = "Kingmaker") -> str:
    """The link an authenticator app scans or opens."""
    label = urllib.parse.quote(f"{issuer}:{account}")
    query = urllib.parse.urlencode({"secret": "".join(encode_secret(secret).split()),
                                    "issuer": issuer, "algorithm": "SHA1",
                                    "digits": DIGITS, "period": STEP})
    return f"otpauth://totp/{label}?{query}"


def code_at(secret: bytes, counter: int, digits: int = DIGITS) -> str:
    """HOTP: the code for one counter value."""
    mac = hmac.new(secret, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    number = struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(number % (10 ** digits)).zfill(digits)


def code_now(secret: bytes, now: float | None = None, digits: int = DIGITS) -> str:
    when = time.time() if now is None else now
    return code_at(secret, int(when) // STEP, digits)


def matches(secret: bytes, code: str, now: float | None = None, window: int = WINDOW) -> bool:
    """Whether `code` is the current one, or one of its neighbours within
    `window` steps: True also for the step just gone, so a code typed at
    the last second still passes."""
    typed = "".join(code.split())
    if not typed.isdigit() or len(typed) != DIGITS:
        return False
    when = time.time() if now is None else now
    counter = int(when) // STEP
    return any(hmac.compare_digest(code_at(secret, counter + delta), typed)
               for delta in range(-window, window + 1))


def new_recovery_codes(how_many: int = RECOVERY_CODES) -> list[str]:
    """Eight codes of ten letters and digits, shown once, each good for one
    login without the phone."""
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    return ["".join(secrets.choice(alphabet) for _ in range(10)) for _ in range(how_many)]


def hash_recovery(code: str) -> str:
    """What is kept of a recovery code: its hash, so a stolen save does not
    give the codes away."""
    return hashlib.sha256("".join(code.split()).lower().encode("ascii")).hexdigest()
