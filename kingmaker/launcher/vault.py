"""Secrets at rest: the cloud credential and the On Air token, protected
by the system instead of lying in clear in `launcher.json`.

Windows: DPAPI (`CryptProtectData`, through `ctypes`, no dependency), in
the scope of the current user: the blob can be read back only by the same
Windows user on the same PC, so a copied game folder carries nothing a
thief can use. Elsewhere: a file in the user's data home, outside the game
folder, readable by its owner alone (`~/.local/share/kingmaker-kingdom-manager/secrets/`,
or `$XDG_DATA_HOME`); `KINGMAKER_VAULT_DIR` moves it (the tests do). Neither
protects against a program running as the user: that is not what they are for.

    blob = protect(b"...")        {"scheme": "dpapi", "data": "<base64>"}
                                  {"scheme": "file", "id": "<hex>"}
    unprotect(blob) -> bytes      VaultError when it cannot (another user,
                                  another PC, a file that is gone)
    forget(blob)                  removes what `file` left behind
"""
from __future__ import annotations

import base64
import ctypes
import os
import secrets
import sys
from pathlib import Path

ENTROPY = b"kingmaker-kingdom-manager/launcher"
CRYPTPROTECT_UI_FORBIDDEN = 0x01
APP_FOLDER = "kingmaker-kingdom-manager"


class VaultError(Exception):
    """The secrets could not be read back: protected by another user or
    on another PC, or the file is gone."""


def default_scheme() -> str:
    return "dpapi" if sys.platform == "win32" else "file"


def secrets_dir() -> Path:
    chosen = os.environ.get("KINGMAKER_VAULT_DIR", "").strip()
    if chosen:
        return Path(chosen).expanduser()
    home = os.environ.get("XDG_DATA_HOME", "").strip()
    base = Path(home).expanduser() if home else Path.home() / ".local" / "share"
    return base / APP_FOLDER / "secrets"


def protect(data: bytes, scheme: str | None = None) -> dict:
    scheme = scheme or default_scheme()
    if scheme == "dpapi":
        return {"scheme": "dpapi", "data": base64.b64encode(_dpapi(data, ENTROPY, encrypt=True)).decode("ascii")}
    if scheme == "file":
        folder = secrets_dir()
        folder.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(folder, 0o700)
        except OSError:
            pass
        name = secrets.token_hex(8)
        target = folder / f"{name}.secret"
        part = folder / f"{name}.secret.tmp"
        part.write_bytes(data)
        try:
            os.chmod(part, 0o600)
        except OSError:
            pass
        os.replace(part, target)
        return {"scheme": "file", "id": name}
    raise VaultError(f"unknown scheme {scheme!r}")


def unprotect(blob: dict) -> bytes:
    scheme = str((blob or {}).get("scheme", ""))
    if scheme == "dpapi":
        try:
            raw = base64.b64decode(str(blob.get("data", "")))
        except (ValueError, TypeError) as error:
            raise VaultError(f"unreadable blob: {error}")
        return _dpapi(raw, ENTROPY, encrypt=False)
    if scheme == "file":
        name = str(blob.get("id", ""))
        if not name or any(c not in "0123456789abcdef" for c in name):
            raise VaultError("unreadable blob: no id")
        try:
            return (secrets_dir() / f"{name}.secret").read_bytes()
        except OSError as error:
            raise VaultError(f"the secrets file is gone: {error}")
    raise VaultError(f"unknown scheme {scheme!r}")


def forget(blob: dict) -> None:
    """Removes what `file` left behind; a DPAPI blob is just forgotten."""
    if (blob or {}).get("scheme") == "file":
        name = str(blob.get("id", ""))
        if name and all(c in "0123456789abcdef" for c in name):
            (secrets_dir() / f"{name}.secret").unlink(missing_ok=True)


# ------------------------------------------------------------------ DPAPI
class _Blob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi(data: bytes, entropy: bytes, encrypt: bool) -> bytes:
    if sys.platform != "win32":
        raise VaultError("DPAPI exists on Windows only")
    crypt32 = ctypes.windll.crypt32                  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32                # type: ignore[attr-defined]
    buffer_in = ctypes.create_string_buffer(data, len(data))
    buffer_entropy = ctypes.create_string_buffer(entropy, len(entropy))
    blob_in = _Blob(len(data), ctypes.cast(buffer_in, ctypes.POINTER(ctypes.c_char)))
    blob_entropy = _Blob(len(entropy), ctypes.cast(buffer_entropy, ctypes.POINTER(ctypes.c_char)))
    blob_out = _Blob()
    call = crypt32.CryptProtectData if encrypt else crypt32.CryptUnprotectData
    ok = call(ctypes.byref(blob_in), None, ctypes.byref(blob_entropy), None, None,
              CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out))
    if not ok:
        raise VaultError("Windows refused to %s the secrets (another user, or another PC)"
                         % ("protect" if encrypt else "unprotect"))
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)
