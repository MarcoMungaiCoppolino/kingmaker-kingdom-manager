"""Ed25519 signatures (RFC 8032), in plain Python on the standard library.

Every launcher of a table signs what it writes to the folder with a key
pair of its own, and the owner signs each release with another: a thief
with the folder's key, or with the GitHub account, can read and write but
cannot forge. A dependency for a hundred lines of arithmetic was not worth
its weight in the installers; this is the reference construction, checked
against the RFC's test vectors in `tests/test_ed25519.py`. Signing takes a
few milliseconds, which is nothing next to the upload it signs.

    seed = new_seed()                 # 32 random bytes, the private key
    public = public_key(seed)         # 32 bytes
    signature = sign(seed, message)   # 64 bytes
    verify(public, message, signature)
"""
from __future__ import annotations

import hashlib
import secrets

P = 2 ** 255 - 19
Q = 2 ** 252 + 27742317777372353535851937790883648493
SEED_BYTES, KEY_BYTES, SIGNATURE_BYTES = 32, 32, 64


def _inv(x: int) -> int:
    return pow(x, P - 2, P)


D = (-121665 * _inv(121666)) % P
I = pow(2, (P - 1) // 4, P)


def _sha512(*parts: bytes) -> bytes:
    h = hashlib.sha512()
    for part in parts:
        h.update(part)
    return h.digest()


def _x_recover(y: int) -> int | None:
    """The even x of the point with this y, or None when there is none."""
    xx = (y * y - 1) * _inv(D * y * y + 1) % P
    x = pow(xx, (P + 3) // 8, P)
    if (x * x - xx) % P != 0:
        x = x * I % P
    if (x * x - xx) % P != 0:
        return None
    if x % 2 != 0:
        x = P - x
    return x


# Points in extended coordinates (X, Y, Z, T) with x = X/Z, y = Y/Z, T = XY/Z.
_Point = tuple[int, int, int, int]
_NEUTRAL: _Point = (0, 1, 1, 0)


def _add(a: _Point, b: _Point) -> _Point:
    x1, y1, z1, t1 = a
    x2, y2, z2, t2 = b
    aa = (y1 - x1) * (y2 - x2) % P
    bb = (y1 + x1) * (y2 + x2) % P
    cc = t1 * 2 * D * t2 % P
    dd = z1 * 2 * z2 % P
    e, f, g, h = bb - aa, dd - cc, dd + cc, bb + aa
    return (e * f % P, g * h % P, f * g % P, e * h % P)


def _double(a: _Point) -> _Point:
    x1, y1, z1, _t1 = a
    aa = x1 * x1 % P
    bb = y1 * y1 % P
    cc = 2 * z1 * z1 % P
    dd = -aa % P
    e = ((x1 + y1) * (x1 + y1) - aa - bb) % P
    g = dd + bb
    f = g - cc
    h = dd - bb
    return (e * f % P, g * h % P, f * g % P, e * h % P)


def _mul(point: _Point, scalar: int) -> _Point:
    result = _NEUTRAL
    while scalar > 0:
        if scalar & 1:
            result = _add(result, point)
        point = _double(point)
        scalar >>= 1
    return result


def _encode(point: _Point) -> bytes:
    x, y, z, _t = point
    zi = _inv(z)
    x, y = x * zi % P, y * zi % P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _decode(data: bytes) -> _Point | None:
    if len(data) != 32:
        return None
    y = int.from_bytes(data, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    if y >= P:
        return None
    x = _x_recover(y)
    if x is None:
        return None
    if (x & 1) != sign:
        x = P - x
    point = (x, y, 1, x * y % P)
    if (-x * x + y * y - 1 - D * x * x * y * y) % P != 0:
        return None
    return point


_BY = 4 * _inv(5) % P
_BX = _x_recover(_BY)
assert _BX is not None
B: _Point = (_BX, _BY, 1, _BX * _BY % P)


def _expand(seed: bytes) -> tuple[int, bytes]:
    if len(seed) != SEED_BYTES:
        raise ValueError("an Ed25519 seed is 32 bytes")
    h = _sha512(seed)
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def new_seed() -> bytes:
    return secrets.token_bytes(SEED_BYTES)


def public_key(seed: bytes) -> bytes:
    a, _prefix = _expand(seed)
    return _encode(_mul(B, a))


def sign(seed: bytes, message: bytes) -> bytes:
    a, prefix = _expand(seed)
    public = _encode(_mul(B, a))
    r = int.from_bytes(_sha512(prefix, message), "little") % Q
    big_r = _encode(_mul(B, r))
    h = int.from_bytes(_sha512(big_r, public, message), "little") % Q
    s = (r + h * a) % Q
    return big_r + s.to_bytes(32, "little")


def verify(public: bytes, message: bytes, signature: bytes) -> bool:
    """True for a signature made with the seed behind `public`; False for
    anything else, including malformed input, and never an exception."""
    try:
        if len(signature) != SIGNATURE_BYTES or len(public) != KEY_BYTES:
            return False
        point_a = _decode(public)
        point_r = _decode(signature[:32])
        if point_a is None or point_r is None:
            return False
        s = int.from_bytes(signature[32:], "little")
        if s >= Q:
            return False
        h = int.from_bytes(_sha512(signature[:32], public, message), "little") % Q
        left = _mul(B, s)
        right = _add(point_r, _mul(point_a, h))
        return _encode(left) == _encode(right)
    except Exception:
        return False
