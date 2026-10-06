"""The whole game in one file: a zip with the database, the kingdom as JSON
and the images.

    kingmaker-<date>.zip
      manifest.json      what it is: app version, schema, kingdom, date
      kingmaker.db       the database, a consistent copy (Archive.backup_to)
      kingdom.json       the kingdom document, readable by a human
      assets/…           the map image, portraits, tokens, thumbnails

`inspect` and `restore` also take a bare `.db` (a backup of the database, or
the file itself carried from another PC): then there are no images to bring.
Nothing here knows about the interface: the Save tab, the creation page and
the launcher all call these three functions.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tempfile
import time
import zipfile
from pathlib import Path

from kingmaker import __version__

DB_NAME = "kingmaker.db"
JSON_NAME = "kingdom.json"
MANIFEST = "manifest.json"
ASSETS = "assets"
# What an archive may unpack to, all members together: a zip that says
# otherwise is not a save.
MAX_UNPACKED = 4 * 1024 ** 3


def is_zip(path: Path) -> bool:
    with open(path, "rb") as f:
        return f.read(4) == b"PK\x03\x04"


def write(archive, kingdom_json: str, assets_dir: Path, target: Path) -> Path:
    """Writes the bundle to `target` and returns it."""
    from kingmaker.storage.archive import SCHEMA_VERSION
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    assets_dir = Path(assets_dir)
    with tempfile.TemporaryDirectory(prefix="km-bundle-") as tmp:
        db_copy = archive.backup_to(Path(tmp) / DB_NAME)
        info = archive.inspect(db_copy)
        manifest = {"app": "Kingmaker Kingdom Manager", "version": __version__,
                    "schema": SCHEMA_VERSION, "kingdom": info["kingdom"],
                    "users": info["users"], "written": time.strftime("%Y-%m-%dT%H:%M:%S")}
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2))
            zf.write(db_copy, DB_NAME)
            zf.writestr(JSON_NAME, kingdom_json)
            if assets_dir.is_dir():
                for file in sorted(assets_dir.rglob("*")):
                    if file.is_file() and file.name != "README.md":
                        zf.write(file, f"{ASSETS}/{file.relative_to(assets_dir).as_posix()}")
    return target


def asset_hashes(assets_dir: Path) -> dict[str, str]:
    """`{relative path: sha256}` of every image under the assets folder,
    thumbnails and README excluded: what a copy of the game refers to."""
    assets_dir = Path(assets_dir)
    found: dict[str, str] = {}
    if not assets_dir.is_dir():
        return found
    for file in sorted(assets_dir.rglob("*")):
        if not file.is_file() or file.name == "README.md":
            continue
        relative = file.relative_to(assets_dir)
        if "thumbnails" in relative.parts:
            continue
        found[relative.as_posix()] = hashlib.sha256(file.read_bytes()).hexdigest()
    return found


def write_snapshot(archive, assets_dir: Path, target: Path, marks: dict | None = None) -> Path:
    """The database alone, for the cloud: `kingmaker.db` and a manifest
    that lists the images by hash instead of carrying them. `marks` are
    extra manifest fields (epoch, seq)."""
    from kingmaker.storage.archive import SCHEMA_VERSION
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="km-snapshot-") as tmp:
        db_copy = archive.backup_to(Path(tmp) / DB_NAME)
        info = archive.inspect(db_copy)
        manifest = {"app": "Kingmaker Kingdom Manager", "version": __version__,
                    "schema": SCHEMA_VERSION, "kingdom": info["kingdom"],
                    "users": info["users"], "written": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "assets": asset_hashes(assets_dir), **(marks or {})}
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2))
            zf.write(db_copy, DB_NAME)
    return target


def manifest(path: Path) -> dict:
    """The manifest of a bundle or snapshot ({} for a bare database)."""
    path = Path(path)
    if not is_zip(path):
        return {}
    with _open_zip(path) as zf:
        if MANIFEST not in zf.namelist():
            return {}
        try:
            return json.loads(zf.read(MANIFEST).decode("utf-8"))
        except ValueError:
            return {}


def integrity_ok(path: Path) -> bool:
    """`PRAGMA integrity_check` on the database inside (or on the bare
    file): a copy that fails here is skipped, never loaded."""
    path = Path(path)
    with tempfile.TemporaryDirectory(prefix="km-check-") as tmp:
        db = path
        if is_zip(path):
            db = Path(tmp) / DB_NAME
            with _open_zip(path) as zf, zf.open(DB_NAME) as src, open(db, "wb") as dst:
                shutil.copyfileobj(src, dst)
        try:
            conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
            try:
                row = conn.execute("PRAGMA integrity_check").fetchone()
            finally:
                conn.close()
        except sqlite3.Error:
            return False
    return bool(row) and row[0] == "ok"


def safe_asset(name: str) -> Path | None:
    """The path inside the assets folder a member unpacks to, or None for a
    member that is not an asset or tries to climb out. The cloud pull asks
    the same question of every path a snapshot's manifest names."""
    if not name.startswith(ASSETS + "/") or name.endswith("/"):
        return None
    relative = Path(name[len(ASSETS) + 1:])
    if relative.is_absolute() or not relative.parts or any(p in ("..", "") for p in relative.parts):
        return None
    return relative


def _open_zip(path: Path) -> zipfile.ZipFile:
    from kingmaker.storage.archive import Archive
    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        raise ValueError(Archive.INSPECT_ERRORS["sqlite"], {})
    names = zf.namelist()
    if DB_NAME not in names:
        zf.close()
        raise ValueError(Archive.INSPECT_ERRORS["tables"], {})
    if sum(i.file_size for i in zf.infolist()) > MAX_UNPACKED:
        zf.close()
        raise ValueError(Archive.INSPECT_ERRORS["sqlite"], {})
    return zf


def inspect(path: Path) -> dict:
    """What the file holds: `kind` ("zip" or "db"), `version`, `users`,
    `kingdom`, `assets` (files). Raises ValueError with a catalog key and
    its params when it is neither a bundle nor a save."""
    from kingmaker.storage.archive import Archive
    path = Path(path)
    if not is_zip(path):
        info = Archive.inspect(path)
        return {"kind": "db", "assets": 0, **info}
    with _open_zip(path) as zf, tempfile.TemporaryDirectory(prefix="km-inspect-") as tmp:
        db = Path(tmp) / DB_NAME
        with zf.open(DB_NAME) as src, open(db, "wb") as dst:
            shutil.copyfileobj(src, dst)
        info = Archive.inspect(db)
        assets = sum(1 for n in zf.namelist() if safe_asset(n) is not None)
    return {"kind": "zip", "assets": assets, **info}


def restore(archive, assets_dir: Path, path: Path) -> Path:
    """Replaces the game with the file: the database through
    `Archive.restore_from` (the previous one kept next to itself), the
    images unpacked over `assets_dir`. Returns the copy kept."""
    path = Path(path)
    if not is_zip(path):
        return archive.restore_from(path)
    assets_dir = Path(assets_dir)
    with _open_zip(path) as zf, tempfile.TemporaryDirectory(prefix="km-restore-") as tmp:
        db = Path(tmp) / DB_NAME
        with zf.open(DB_NAME) as src, open(db, "wb") as dst:
            shutil.copyfileobj(src, dst)
        kept = archive.restore_from(db)
        for name in zf.namelist():
            relative = safe_asset(name)
            if relative is None:
                continue
            target = assets_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(name) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
    return kept
