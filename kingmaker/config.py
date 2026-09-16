"""App configuration: paths and network, with today's values as defaults.

One place where the environment is read. It exists for the day the app runs on
a hosting service instead of this PC: there the data does not live next to the
code, and the path comes from an environment variable. As long as you play
locally nothing changes, because the defaults are exactly the current folders.
"""
from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path


def _root() -> Path:
    """The folder the game lives next to.

    From source it is the repository (the parent of this package), so `saves/`
    and `assets/` sit beside `launch.py`. In the installed app (frozen with
    PyInstaller, `sys.frozen` set) the package lives inside the bundle's
    `_internal/`, which every update replaces: the game goes next to the
    executable instead, so the installed folder has the same shape as the
    repository.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


ROOT_DIR = _root()


def _folder(variable: str, default_one: Path) -> Path:
    """A folder taken from the environment, created if missing."""
    choice = os.environ.get(variable, "").strip()
    path = Path(choice).expanduser() if choice else default_one
    path.mkdir(parents=True, exist_ok=True)
    return path


def _whole(variable: str, default_: int) -> int:
    raw = os.environ.get(variable, "").strip()
    if not raw:
        return default_
    try:
        return int(raw)
    except ValueError:
        return default_


# Game data: the database and, while it is still needed, the old JSON save.
DATA_DIR = _folder("KINGMAKER_DATA_DIR", ROOT_DIR / "saves")

# Map images, served under /assets.
ASSETS_DIR = _folder("KINGMAKER_ASSETS_DIR", ROOT_DIR / "assets")

DB_FILE = DATA_DIR / "kingmaker.db"

# The save of the previous version: imported once from here, and still
# exportable from the Manual.
SAVE_JSON = DATA_DIR / "regno.json"

# A single campaign for now. The field already exists in the database because
# the day the app is hosted elsewhere several will share one server.
DEFAULT_CAMPAIGN = "principale"

HOST = os.environ.get("KINGMAKER_HOST", "").strip() or "127.0.0.1"
PORT = _whole("KINGMAKER_PORT", 8080)

# The interface language for whoever has not chosen one and whose browser
# asks for nothing supported: "en" or "it".
LANG = os.environ.get("KINGMAKER_LANG", "").strip().lower() or "en"


def _real(variable: str) -> bool:
    return os.environ.get(variable, "").strip().lower() in ("1", "true", "si", "yes", "on")


# Behind a reverse proxy with TLS: the session cookie travels only over HTTPS
# and the client address is read from X-Forwarded-For (only if you say so:
# trusting that header without a proxy in front means letting anyone dictate
# their own address).
HTTPS = _real("KINGMAKER_HTTPS")
TRUST_PROXY = _real("KINGMAKER_TRUST_PROXY")
# Set at startup when the game goes through the On Air relay: from there
# everyone arrives with the same address.
ON_AIR = False

SECRET_FILE = DATA_DIR / ".storage_secret"


def storage_secret() -> str:
    """The key that signs the session cookies.

    Whoever knows it can forge an administrator cookie, so it cannot live in the
    code. If you do not pass it with KINGMAKER_STORAGE_SECRET, on first start we
    generate a random one and keep it in `saves/.storage_secret`, which is
    already outside version control. Deleting that file does no harm: it only
    sends everyone back to the login screen.
    """
    from_environment = os.environ.get("KINGMAKER_STORAGE_SECRET", "").strip()
    if from_environment:
        return from_environment
    if SECRET_FILE.exists():
        saved = SECRET_FILE.read_text(encoding="utf-8").strip()
        if saved:
            return saved
    new_one = secrets.token_urlsafe(48)
    SECRET_FILE.write_text(new_one, encoding="utf-8")
    try:
        SECRET_FILE.chmod(0o600)
    except OSError:
        # POSIX permissions do not apply on Windows: the data folder is inside
        # the user's profile anyway.
        pass
    return new_one
