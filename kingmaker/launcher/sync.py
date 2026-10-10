"""The game in the cloud: who hosts, and the copies the next host loads.

The folder (Dropbox's app folder, but any `Client`-shaped object works):

    host.json                       who hosts: host_id, host_name, epoch, seq, since, released,
                                    beat, seen, address, app_version
    recent/save-e<epoch>-s<seq>.zip the last five database snapshots, written while playing
    daily/save-<YYYY-MM-DD>.zip     the first snapshot of each UTC day, thirty kept
    assets/<sha256>.<ext>           the images, uploaded once each

One host at a time: `claim` takes `host.json` with a compare-and-swap on
its `rev`, and a record younger than `HEARTBEAT_STALE` seconds belongs to a
living host. Time is the server's (`server_modified`), never a PC clock.
`(epoch, seq)` orders the copies: epoch rises at every take-over, seq at
every upload. The copies are not trusted blindly: a copy from a newer app
stops the pull instead of being skipped for an older one, a copy whose
epoch no record ever had is ignored, and an image arrives only under a
path inside the assets folder, with the bytes its name promises, and only
if it is an image. Nothing here knows tkinter or the server: the window
drives `claim`, `pull`, `Hoster` and `release`, and the server's snapshot
route supplies the bytes.
"""
from __future__ import annotations

import calendar
import hashlib
import json
import os
import re
import threading
import time
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from kingmaker import __version__
from kingmaker.access import ed25519
from kingmaker.launcher.dropbox import DropboxError
from kingmaker.locale.i18n import t
from kingmaker.media import images, imgsize
from kingmaker.storage import bundle
from kingmaker.storage.archive import Archive

HOST_FILE = "host.json"
RECENT, DAILY, ASSETS = "recent", "daily", "assets"
KEEP_RECENT, KEEP_DAILY = 5, 30
HEARTBEAT_EVERY = 60.0
HEARTBEAT_STALE = 180.0
UPLOAD_EVERY = 180.0
STATUS_EVERY = 30.0
SNAPSHOT_NAME = re.compile(r"^save-e(\d+)-s(\d+)\.zip$")
DAILY_NAME = re.compile(r"^save-(\d{4}-\d{2}-\d{2})\.zip$")


def _parse_time(text: str) -> float:
    """Dropbox's `2026-09-16T10:20:30Z` → seconds since the epoch (UTC, so
    no daylight-saving surprise)."""
    return calendar.timegm(time.strptime(text[:19], "%Y-%m-%dT%H:%M:%S"))


def canonical(data: dict) -> bytes:
    """One spelling of a dictionary, the bytes every signature is over:
    sorted keys, no spaces, ASCII only."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _signed(public_hex: str, body: dict, signature_hex: str) -> bool:
    try:
        return bool(public_hex) and ed25519.verify(bytes.fromhex(public_hex), canonical(body),
                                                   bytes.fromhex(signature_hex))
    except ValueError:
        return False


def _now_text() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass
class HostRecord:
    host_id: str = ""
    host_name: str = ""
    epoch: int = 0
    seq: int = 0
    since: str = ""
    released: bool = False
    address: str = ""             # where the players find the game while this host runs
    app_version: str = __version__
    # The heartbeat counts. Every rewrite of the record must change its
    # bytes: a Dropbox that keeps identical content as the same revision
    # would leave `server_modified` where it was, and a host with nothing
    # new to say would look dead after HEARTBEAT_STALE seconds. `seen` is
    # the server's time of the previous write, for whoever reads the record
    # by eye; the staleness test never looks at it.
    beat: int = 0
    seen: str = ""
    rev: str = ""                 # Dropbox's, for the compare-and-swap
    age: float = 0.0              # seconds since the server last saw it written
    # A hand-over asked of this host: {"to_id", "to_name", "asked_at"},
    # written into the record by the one who asks (`request_handover`).
    # The holder's next look at the record uploads a last copy and
    # releases; a holder that never looks is taken by force after a wait.
    handover: dict | None = None
    # The holder's launcher key and its signature over who it is, when it
    # took the game and where the game is (`signing_body`): the fields a
    # thief with the folder's key would want to write. The ones that move
    # with every heartbeat are outside it, so the taker's hand-over request
    # and the holder's own beats leave it valid.
    key: str = ""
    signature: str = ""

    @classmethod
    def parse(cls, data: bytes, meta: dict, now: float) -> "HostRecord":
        try:
            raw = json.loads(data.decode("utf-8"))
        except ValueError:
            raw = {}
        record = cls(host_id=str(raw.get("host_id", "")), host_name=str(raw.get("host_name", "")),
                     epoch=int(raw.get("epoch") or 0), seq=int(raw.get("seq") or 0),
                     since=str(raw.get("since", "")), released=bool(raw.get("released")),
                     address=str(raw.get("address", "")),
                     app_version=str(raw.get("app_version", "")),
                     beat=int(raw.get("beat") or 0), seen=str(raw.get("seen", "")),
                     rev=str(meta.get("rev", "")),
                     key=str(raw.get("key", "")), signature=str(raw.get("signature", "")))
        modified = meta.get("server_modified")
        record.age = max(0.0, now - _parse_time(modified)) if modified else 0.0
        asked = raw.get("handover")
        record.handover = asked if isinstance(asked, dict) and asked else None
        return record

    def body(self) -> bytes:
        fields = {"host_id": self.host_id, "host_name": self.host_name,
                  "epoch": self.epoch, "seq": self.seq, "since": self.since,
                  "released": self.released, "address": self.address,
                  "app_version": self.app_version,
                  "beat": self.beat, "seen": self.seen}
        if self.handover:
            fields["handover"] = self.handover
        if self.key:
            fields["key"] = self.key
            fields["signature"] = self.signature
        return json.dumps(fields, indent=2).encode("utf-8")

    def signing_body(self) -> dict:
        return {"host_id": self.host_id, "host_name": self.host_name, "epoch": self.epoch,
                "since": self.since, "address": self.address, "app_version": self.app_version,
                "key": self.key}

    def sign(self, seed: bytes, key: str) -> None:
        self.key = key
        self.signature = ed25519.sign(seed, canonical(self.signing_body())).hex()

    def verified(self) -> bool:
        """Signed by the key it names. Whether that key is one of the
        table's is the reader's question (`known_launchers`)."""
        return _signed(self.key, self.signing_body(), self.signature)

    def held(self) -> bool:
        """A living host holds it: not released, written recently."""
        return bool(self.host_id) and not self.released and self.age < HEARTBEAT_STALE


class Held(Exception):
    """Somebody else hosts right now."""

    def __init__(self, record: HostRecord) -> None:
        super().__init__(f"hosted by {record.host_name or record.host_id}")
        self.record = record


def server_now(client) -> float:
    """The server's clock, read from a file we just wrote: the only clock
    every host agrees on. The bytes change at every write: Dropbox keeps an
    upload of identical content as the same revision, `server_modified`
    included, and an empty file rewritten forever had frozen this clock at
    the first cloud start — every record since looked zero seconds old."""
    # The PC's time alone is not enough: two writes can fall within its
    # resolution and come out identical; a few random bytes never do.
    stamp = f"{time.time()!r} {os.urandom(4).hex()}".encode("ascii")
    meta = client.upload(".clock", stamp, mode="overwrite")
    return _parse_time(meta["server_modified"])


def download_if_there(client, path: str) -> tuple[bytes, dict] | None:
    """The file and its metadata, or None when there is no such file. One
    call: the download carries the `rev` and `server_modified` of exactly
    the bytes it returns, so asking first whether the file exists only cost
    a second call (and could be told one revision while downloading the
    next)."""
    try:
        return client.download(path)
    except DropboxError as error:
        if error.not_found:
            return None
        raise


def read_record(client) -> HostRecord | None:
    found = download_if_there(client, HOST_FILE)
    if found is None:
        return None
    data, meta = found
    # The answer's own Date header says what time the server thinks it is:
    # no write to read the clock off, so an idle launcher asking every
    # minute uploads nothing. The clock file stays for an answer without it.
    now = meta.get("_server_time")
    return HostRecord.parse(data, meta, float(now) if now else server_now(client))


def claim(client, host_id: str, host_name: str, force: bool = False,
          attempts: int = 3, seed: bytes | None = None, key: str = "") -> HostRecord:
    """Become the host, or raise `Held`. `force` takes the game from a
    living host (the administrator's button); a stale or released record is
    taken freely; our own record (a crash and a restart) is kept. With a
    `seed` and `key` the record is signed (`HostRecord.sign`)."""
    for _attempt in range(attempts):
        current = read_record(client)
        mine = HostRecord(host_id=host_id, host_name=host_name, since=_now_text())
        if current is None:
            mine.epoch = 1
            mode, rev = "add", None
        else:
            if current.held() and current.host_id != host_id and not force:
                raise Held(current)
            mine.epoch = current.epoch + (0 if current.host_id == host_id and current.held()
                                          else 1)
            mine.seq = current.seq
            if current.host_id == host_id:
                mine.address = current.address
            mode, rev = "update", current.rev
        if seed is not None and key:
            mine.sign(seed, key)
        try:
            meta = client.upload(HOST_FILE, mine.body(), mode=mode, rev=rev)
        except DropboxError as error:
            if error.conflict:
                continue                 # somebody wrote first: look again
            raise
        mine.rev = str(meta.get("rev", ""))
        return mine
    raise Held(read_record(client) or HostRecord())


def heartbeat(client, record: HostRecord) -> HostRecord:
    """Rewrite our record; a conflict means we were taken over. The beat
    rises first, so the bytes differ from the last write (see `HostRecord`)."""
    record.beat += 1
    meta = client.upload(HOST_FILE, record.body(), mode="update", rev=record.rev)
    record.rev = str(meta.get("rev", ""))
    record.seen = str(meta.get("server_modified", ""))
    return record


def release(client, record: HostRecord, attempts: int = 3, pause: float = 2.0) -> bool:
    """On Stop: the next host need not wait for the record to go stale. A
    Dropbox that does not answer is asked again a couple of times; False
    when it never did, or when the record is no longer ours (the next host
    then waits for it to go stale, as before)."""
    record.released = True
    for attempt in range(attempts):
        try:
            heartbeat(client, record)
            return True
        except DropboxError as error:
            if error.conflict or attempt == attempts - 1:
                return False
            time.sleep(pause)
    return False


def request_handover(client, to_id: str, to_name: str, attempts: int = 3) -> HostRecord | None:
    """Asks the living host for the game: their record gets `handover`
    (who asks, since when), which their next look at it reads (`Hoster.look`).
    None when nobody holds the record, or we do: the claim is free then.
    Otherwise the record as written, for `wait_for_release`."""
    for _attempt in range(attempts):
        current = read_record(client)
        if current is None or not current.held() or current.host_id == to_id:
            return None
        current.handover = {"to_id": to_id, "to_name": to_name,
                            "asked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        try:
            meta = client.upload(HOST_FILE, current.body(), mode="update", rev=current.rev)
        except DropboxError as error:
            if error.conflict:
                continue                 # the holder wrote meanwhile: ask on the new rev
            raise
        current.rev = str(meta.get("rev", ""))
        return current
    raise DropboxError(409, "host.json: conflict while asking for the hand-over")


def wait_for_release(client, holder_id: str, timeout: float = 120.0, every: float = 10.0,
                     progress: Callable[[float], None] | None = None,
                     sleep: Callable[[float], None] = time.sleep,
                     clock: Callable[[], float] = time.monotonic) -> bool:
    """Waits for the host asked to let go: True once their record is
    released, stale, gone or someone else's (the claim is free), False when
    `timeout` seconds passed with them still on it. `progress(seconds)` is
    called at every look, for a line that says how long."""
    started = clock()
    while True:
        current = read_record(client)
        if current is None or current.host_id != holder_id or not current.held():
            return True
        waited = clock() - started
        if progress is not None:
            progress(waited)
        if waited >= timeout:
            return False
        sleep(min(every, max(0.0, timeout - waited)))


# ------------------------------------------------------------------ the table
TABLE_FILE = "table.json"
TABLE_FORMAT = 2


@dataclass
class TableRecord:
    """`table.json`: what the table is, which version it plays on, the On
    Air token every host reads at Start instead of keeping a copy, and —
    format 2 — who the administrator is: their launcher's id, name and
    public key, the launchers struck off, and the administrator's
    signature over all of it.

    Any member of the folder can write the file — Dropbox gives no finer
    right — but only the administrator's launcher can sign it: a rewritten
    file fails `verified` on every launcher and is refused."""
    format: int = TABLE_FORMAT
    table_id: str = ""            # who we are: random, made once with the file
    name: str = ""
    app_version: str = ""         # the version every host must run to host
    air_token: str = ""           # "" until the administrator's launcher writes it
    air_address: str = ""         # the fixed address the token gives, once seen
    air_generation: int = 0       # rises at every new token
    access_generation: int = 1    # rises at every change of the hosts' key
    # The seat: the administrator's launcher. `signed_since` is the first
    # epoch whose copies must be signed (the ones before came from 1.x).
    admin_id: str = ""
    admin_name: str = ""
    admin_key: str = ""
    admin_since: str = ""
    revoked: list[str] = field(default_factory=list)
    signed_since: int = 0
    set_by: str = ""
    set_at: str = ""
    signature: str = ""
    rev: str = ""                 # Dropbox's, for the compare-and-swap

    @classmethod
    def parse(cls, data: bytes, meta: dict) -> "TableRecord":
        try:
            raw = json.loads(data.decode("utf-8"))
        except ValueError:
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        admin = raw.get("admin") if isinstance(raw.get("admin"), dict) else {}
        revoked = raw.get("revoked") if isinstance(raw.get("revoked"), list) else []
        return cls(format=int(raw.get("format") or 1), table_id=str(raw.get("table_id", "")),
                   name=str(raw.get("name", "")), app_version=str(raw.get("app_version", "")),
                   air_token=str(raw.get("air_token", "")), air_address=str(raw.get("air_address", "")),
                   air_generation=int(raw.get("air_generation") or 0),
                   access_generation=int(raw.get("access_generation") or 1),
                   admin_id=str(admin.get("host_id", "")), admin_name=str(admin.get("name", "")),
                   admin_key=str(admin.get("key", "")), admin_since=str(admin.get("since", "")),
                   revoked=[str(r) for r in revoked], signed_since=int(raw.get("signed_since") or 0),
                   set_by=str(raw.get("set_by", "")), set_at=str(raw.get("set_at", "")),
                   signature=str(raw.get("signature", "")), rev=str(meta.get("rev", "")))

    def signing_body(self) -> dict:
        """Everything but the signature: what the administrator signs."""
        body = {"format": self.format, "table_id": self.table_id, "name": self.name,
                "app_version": self.app_version, "air_token": self.air_token,
                "air_address": self.air_address, "air_generation": self.air_generation,
                "access_generation": self.access_generation,
                "set_by": self.set_by, "set_at": self.set_at}
        if self.format >= 2:
            body["admin"] = {"host_id": self.admin_id, "name": self.admin_name,
                             "key": self.admin_key, "since": self.admin_since}
            body["revoked"] = list(self.revoked)
            body["signed_since"] = self.signed_since
        return body

    def body(self) -> bytes:
        fields = self.signing_body()
        if self.format >= 2:
            fields["signature"] = self.signature
        return json.dumps(fields, indent=2).encode("utf-8")

    def sign(self, seed: bytes) -> None:
        self.signature = ed25519.sign(seed, canonical(self.signing_body())).hex()

    def verified(self) -> bool:
        """A format-2 file signed by the administrator's key it names."""
        return self.format >= 2 and _signed(self.admin_key, self.signing_body(), self.signature)

    def trusted_by(self, admin_key: str) -> bool:
        """What a host asks: signed, and by the administrator this launcher
        learned at pairing. Another key is another seat."""
        return bool(admin_key) and self.admin_key == admin_key and self.verified()

    def mismatch(self, mine: str = __version__) -> bool:
        """Whether a launcher of version `mine` may not host: the match is
        exact, because the same save format has carried different rules."""
        return bool(self.app_version) and self.app_version != mine


def read_table(client) -> TableRecord | None:
    found = download_if_there(client, TABLE_FILE)
    if found is None:
        return None
    data, meta = found
    return TableRecord.parse(data, meta)


def write_table(client, table: TableRecord, by: str = "", seed: bytes | None = None) -> TableRecord:
    """Writes the table file with a compare-and-swap on its rev (`add`
    when it has none yet); a conflict reads it again and writes once more,
    keeping what the caller set. The administrator passes its `seed`: a
    format-2 file is signed over its final fields just before each write."""
    for attempt in range(2):
        if by:
            table.set_by = by
        table.set_at = _now_text()
        if seed is not None and table.format >= 2:
            table.sign(seed)
        mode, rev = ("update", table.rev) if table.rev else ("add", None)
        try:
            meta = client.upload(TABLE_FILE, table.body(), mode=mode, rev=rev)
        except DropboxError as error:
            if not error.conflict or attempt:
                raise
            current = read_table(client)
            table.rev = current.rev if current is not None else ""
            continue
        table.rev = str(meta.get("rev", ""))
        return table
    raise DropboxError(409, "table.json: conflict twice")


def ensure_table(client, name: str, version: str = __version__, token: str = "",
                 by: str = "", admin: tuple[str, str, str] | None = None,
                 seed: bytes | None = None) -> tuple[TableRecord, bool]:
    """The table file, created by the administrator's launcher when it
    finds none: its own version pins the table, its local token (if the
    caller passes one) goes in, and `admin` (host_id, name, key) with the
    `seed` takes the seat and signs. `(table, created)`."""
    table = read_table(client)
    if table is not None:
        return table, False
    table = TableRecord(table_id=uuid.uuid4().hex[:12], name=name, app_version=version,
                        air_token=token, air_generation=1 if token else 0, signed_since=1)
    if admin is not None:
        table.admin_id, table.admin_name, table.admin_key = admin
        table.admin_since = _now_text()
    return write_table(client, table, by=by, seed=seed), True


def take_seat(table: TableRecord, host_id: str, name: str, key: str, epoch: int) -> TableRecord:
    """The administrator's seat for this launcher: on a table from 1.x
    (format 1) the upgrade, on a format-2 table the move from another PC.
    Copies from before `epoch` stay accepted unsigned. The caller writes
    the file with its seed."""
    if table.format < 2:
        table.format = TABLE_FORMAT
        table.signed_since = epoch
    table.admin_id, table.admin_name, table.admin_key = host_id, name, key
    table.admin_since = _now_text()
    return table


# ------------------------------------------------------------- the launchers
LAUNCHERS_FILE = "launchers.json"
LAUNCHERS_FORMAT = 1
CHAIN_DEPTH = 12


def admission_body(entry: dict) -> dict:
    return {"host_id": str(entry.get("host_id", "")), "name": str(entry.get("name", "")),
            "key": str(entry.get("key", "")), "since": str(entry.get("since", "")),
            "admitted_by": str(entry.get("admitted_by", ""))}


def make_admission(seed: bytes, admitted_by: str, host_id: str, name: str, key: str) -> dict:
    """What the hosting game signs at `POST /_launcher/pair`, with the
    hosting launcher's seed: the newcomer's id, name and key, vouched for
    by a launcher the table already knows."""
    entry = {"host_id": host_id, "name": name[:80], "key": key, "since": _now_text(),
             "admitted_by": admitted_by}
    entry["signature"] = ed25519.sign(seed, canonical(admission_body(entry))).hex()
    return entry


def read_launchers(client) -> tuple[list[dict], str]:
    """The entries as written, and the file's rev ("" when absent)."""
    found = download_if_there(client, LAUNCHERS_FILE)
    if found is None:
        return [], ""
    data, meta = found
    try:
        raw = json.loads(data.decode("utf-8"))
    except ValueError:
        raw = {}
    entries = raw.get("entries") if isinstance(raw, dict) and isinstance(raw.get("entries"), list) else []
    return [e for e in entries if isinstance(e, dict)], str(meta.get("rev", ""))


def add_launcher(client, entry: dict, attempts: int = 3) -> None:
    """Appends an admission with a compare-and-swap; an entry for the same
    launcher id replaces the old one (a re-pairing after a change of keys)."""
    for _attempt in range(attempts):
        entries, rev = read_launchers(client)
        entries = [e for e in entries if e.get("host_id") != entry.get("host_id")] + [entry]
        body = json.dumps({"format": LAUNCHERS_FORMAT, "entries": entries}, indent=2).encode("utf-8")
        try:
            client.upload(LAUNCHERS_FILE, body, mode="update" if rev else "add", rev=rev or None)
            return
        except DropboxError as error:
            if not error.conflict:
                raise
    raise DropboxError(409, "launchers.json: conflict while adding a launcher")


def known_launchers(table: TableRecord, entries: list[dict]) -> dict[str, str]:
    """`{host_id: key}` of every launcher the table vouches for: the
    administrator, and each entry whose admission was signed by the
    administrator or by a launcher vouched for in turn, none of them
    struck off. A valid table file is the root; without one, nobody."""
    known: dict[str, str] = {}
    if not table.verified() or not table.admin_id:
        return known
    revoked = set(table.revoked)
    if table.admin_id not in revoked:
        known[table.admin_id] = table.admin_key
    by_id = {str(e.get("host_id", "")): e for e in entries}
    cache: dict[str, str | None] = {}

    def key_of(host_id: str, depth: int) -> str | None:
        # A launcher struck off vouches for nobody any more: the ones it
        # let in fall with it, unless the administrator admits them again
        # under its own signature (`window.strike_off` offers to).
        if host_id in known:
            return known[host_id]
        if host_id in cache:
            return cache[host_id]
        cache[host_id] = None                       # a loop ends here
        entry = by_id.get(host_id)
        if entry is None or host_id in revoked or depth > CHAIN_DEPTH:
            return None
        voucher = key_of(str(entry.get("admitted_by", "")), depth + 1)
        if voucher and _signed(voucher, admission_body(entry), str(entry.get("signature", ""))):
            cache[host_id] = str(entry.get("key", ""))
        return cache[host_id]

    for host_id in by_id:
        found = key_of(host_id, 0)
        if found:
            known[host_id] = found
    return known


# --------------------------------------------------------------------- copies
def _snapshots(client, folder: str, pattern: re.Pattern) -> list[dict]:
    """Newest first."""
    found = []
    for entry in client.list_folder(folder):
        match = pattern.match(str(entry.get("name", "")))
        if entry.get(".tag") == "file" and match:
            key = tuple(int(g) if g.isdigit() else g for g in match.groups())
            found.append({"name": entry["name"], "path": f"{folder}/{entry['name']}",
                          "key": key, "server_modified": entry.get("server_modified", "")})
    found.sort(key=lambda e: e["key"], reverse=True)
    return found


class NewerCopy(Exception):
    """The newest copy in the cloud was written by a newer app than this
    one: nothing older may be loaded in its place."""

    def __init__(self, name: str, version: int, mine: int, app: str) -> None:
        super().__init__(f"{name}: schema {version} is newer than this app's {mine}")
        self.name, self.version, self.mine, self.app = name, version, mine, app


SIGNATURE_MEMBER = "signature.json"


def sign_snapshot(data: bytes, seed: bytes, host_id: str, key: str) -> bytes:
    """The snapshot with a `signature.json` member added: the launcher's
    id and key, and its signature over the hashes of the manifest and the
    database. Made by the launcher, not the game: the seed never leaves
    the launcher's vault."""
    import io
    import zipfile
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        hashes = {"manifest": hashlib.sha256(zf.read(bundle.MANIFEST)).hexdigest(),
                  "db": hashlib.sha256(zf.read(bundle.DB_NAME)).hexdigest()}
    stamp = {"host_id": host_id, "key": key,
             "signature": ed25519.sign(seed, canonical(hashes)).hex()}
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            if item.filename != SIGNATURE_MEMBER:
                dst.writestr(item, src.read(item.filename))
        dst.writestr(SIGNATURE_MEMBER, json.dumps(stamp, indent=2))
    return out.getvalue()


def snapshot_signer(path: Path) -> tuple[str, str] | None:
    """`(host_id, key)` of the launcher whose signature the copy carries
    and verifies, or None for an unsigned or tampered copy."""
    import zipfile
    try:
        with zipfile.ZipFile(path) as zf:
            if SIGNATURE_MEMBER not in zf.namelist():
                return None
            stamp = json.loads(zf.read(SIGNATURE_MEMBER).decode("utf-8"))
            hashes = {"manifest": hashlib.sha256(zf.read(bundle.MANIFEST)).hexdigest(),
                      "db": hashlib.sha256(zf.read(bundle.DB_NAME)).hexdigest()}
    except (zipfile.BadZipFile, KeyError, ValueError, OSError):
        return None
    if not isinstance(stamp, dict):
        return None
    host_id, key, signature = (str(stamp.get("host_id", "")), str(stamp.get("key", "")),
                               str(stamp.get("signature", "")))
    if not _signed(key, hashes, signature):
        return None
    return host_id, key


def newest_usable(client, into: Path, log: Callable[[str], None] = lambda _t: None,
                  record: HostRecord | None = None, trusted: dict[str, str] | None = None,
                  signed_since: int = 0) -> Path | None:
    """Downloads copies newest first, recent then daily, and returns the
    first one that passes the checks, or None.

    A corrupt copy is skipped for the next one. A copy from a **newer** app
    stops the search with `NewerCopy`: falling back to an older copy there
    would roll the game back to before the newer host played, and nobody
    would know. A recent copy whose epoch is above the record's cannot have
    been written by any host the record ever named (epochs come from the
    record alone), so it is skipped and said in the log. With `trusted`
    (`known_launchers`), a copy at an epoch from `signed_since` on must
    carry the signature of one of them, or it is skipped and said.
    """
    into.mkdir(parents=True, exist_ok=True)
    for folder, pattern in ((RECENT, SNAPSHOT_NAME), (DAILY, DAILY_NAME)):
        for entry in _snapshots(client, folder, pattern):
            if folder == RECENT and record is not None and entry["key"][0] > record.epoch:
                log(t("launcher.log.skipping_epoch", name=entry["name"], epoch=record.epoch))
                continue
            target = into / entry["name"]
            try:
                data, _meta = client.download(entry["path"])
                target.write_bytes(data)
                bundle.inspect(target)
                if not bundle.integrity_ok(target):
                    raise ValueError("integrity")
                if trusted is not None:
                    epoch = int(bundle.manifest(target).get("epoch") or entry["key"][0] or 0)
                    if epoch >= signed_since:
                        signer = snapshot_signer(target)
                        if signer is None or trusted.get(signer[0]) != signer[1]:
                            raise ValueError("signature")
            except ValueError as error:
                target.unlink(missing_ok=True)
                if error.args and error.args[0] == Archive.INSPECT_ERRORS["newer"]:
                    params = error.args[1] if len(error.args) > 1 and isinstance(error.args[1], dict) else {}
                    raise NewerCopy(entry["name"], int(params.get("version") or 0),
                                    int(params.get("mine") or 0), str(params.get("app") or ""))
                log(t("launcher.log.skipping", name=entry['name'], error=error))
                continue
            except (DropboxError, OSError) as error:
                log(t("launcher.log.skipping", name=entry['name'], error=error))
                target.unlink(missing_ok=True)
                continue
            return target
    return None


def marks_of(path: Path) -> tuple[int, int]:
    data = bundle.manifest(path)
    return int(data.get("epoch") or 0), int(data.get("seq") or 0)


def pull_assets(client, assets_dir: Path, wanted: dict[str, str],
                log: Callable[[str], None] = lambda _t: None) -> int:
    """Brings the images a snapshot refers to; returns how many arrived.

    The manifest was written by another host and is not trusted on its
    word: a path that leaves the assets folder, a file whose bytes are not
    the hash it is named after, or bytes that are not an image are refused
    and said in the log — the same three refusals `bundle.restore` and the
    uploads make.
    """
    have = bundle.asset_hashes(assets_dir)
    remote = {str(e.get("name", "")).split(".")[0]: e for e in client.list_folder(ASSETS)}
    fetched = 0
    for relative, digest in wanted.items():
        if have.get(relative) == digest:
            continue
        safe = bundle.safe_asset(f"{bundle.ASSETS}/{relative}")
        if safe is None or safe.suffix.lower() not in images.EXTENSIONS:
            log(t("launcher.log.image_refused", path=relative,
                  reason=t("launcher.log.image_reason.path")))
            continue
        entry = remote.get(digest)
        if entry is None:
            log(t("launcher.log.image_missing", path=relative))
            continue
        data, _meta = client.download(f"{ASSETS}/{entry['name']}")
        if hashlib.sha256(data).hexdigest() != digest:
            log(t("launcher.log.image_refused", path=relative,
                  reason=t("launcher.log.image_reason.hash")))
            continue
        target = Path(assets_dir) / safe
        target.parent.mkdir(parents=True, exist_ok=True)
        part = target.with_name(target.name + ".part")
        part.write_bytes(data)
        if imgsize.sizes(part) is None:
            part.unlink(missing_ok=True)
            log(t("launcher.log.image_refused", path=relative,
                  reason=t("launcher.log.image_reason.kind")))
            continue
        os.replace(part, target)
        fetched += 1
    return fetched


def push_assets(client, assets_dir: Path, hashes: dict[str, str] | None = None,
                known: set[str] | None = None) -> set[str]:
    """Uploads the images whose hash the cloud does not have; returns the
    hashes known afterwards (pass it back next time to skip the listing)."""
    hashes = hashes if hashes is not None else bundle.asset_hashes(assets_dir)
    if known is None:
        known = {str(e.get("name", "")).split(".")[0] for e in client.list_folder(ASSETS)}
    for relative, digest in hashes.items():
        if digest in known:
            continue
        suffix = Path(relative).suffix.lower() or ".bin"
        client.upload(f"{ASSETS}/{digest}{suffix}", (Path(assets_dir) / relative).read_bytes(),
                      mode="overwrite")
        known.add(digest)
    return known


def prune(client, folder: str, pattern: re.Pattern, keep: int) -> int:
    entries = _snapshots(client, folder, pattern)
    for entry in entries[keep:]:
        client.delete(entry["path"])
    return max(0, len(entries) - keep)


def upload_snapshot(client, data: bytes, epoch: int, seq: int, today: str | None = None) -> dict:
    """One snapshot to `recent/`, to `daily/` too if the day has none yet,
    then the retention. Returns what was done."""
    name = f"save-e{epoch}-s{seq}.zip"
    client.upload(f"{RECENT}/{name}", data, mode="overwrite")
    done = {"recent": name, "daily": None, "pruned": 0}
    today = today or time.strftime("%Y-%m-%d", time.gmtime())
    if not any(e["key"][0] == today for e in _snapshots(client, DAILY, DAILY_NAME)):
        daily = f"save-{today}.zip"
        client.upload(f"{DAILY}/{daily}", data, mode="overwrite")
        done["daily"] = daily
        done["pruned"] += prune(client, DAILY, DAILY_NAME, KEEP_DAILY)
    done["pruned"] += prune(client, RECENT, SNAPSHOT_NAME, KEEP_RECENT)
    return done


# --------------------------------------------------------------- the server
class LocalServer:
    """The running server's launcher routes, from the launcher's side."""

    def __init__(self, port: int, secret: str) -> None:
        self.port = port
        self.secret = secret

    def _request(self, path: str, method: str = "GET", body: bytes | None = None,
                 timeout: float = 60.0) -> tuple[bytes, dict]:
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method,
                                         data=body, headers={"X-Launcher-Secret": self.secret})
        with urllib.request.urlopen(request, timeout=timeout) as answer:
            return answer.read(), dict(answer.headers)

    def status(self) -> dict:
        data, _h = self._request("/_launcher/status")
        return json.loads(data.decode("utf-8"))

    def snapshot(self, epoch: int, seq: int) -> bytes:
        data, _h = self._request(f"/_launcher/snapshot?epoch={epoch}&seq={seq}", method="POST",
                                 body=b"")
        return data

    def synced(self, epoch: int, seq: int) -> None:
        self._request("/_launcher/synced", method="POST",
                      body=json.dumps({"epoch": epoch, "seq": seq}).encode("utf-8"))

    def pairing(self) -> dict:
        """A fresh pairing code from the running game: `{"code", "expires_in"}`."""
        data, _h = self._request("/_launcher/pairing", method="POST", body=b"")
        return json.loads(data.decode("utf-8"))


# ---------------------------------------------------------------- the hoster
@dataclass
class HosterState:
    last_rev: int | None = None
    last_upload: float = 0.0
    last_heartbeat: float = 0.0
    uploads: int = 0
    known_assets: set[str] | None = None
    errors: list[str] = field(default_factory=list)
    taken_over: bool = False
    handed: bool = False


class Hoster:
    """While we host: the heartbeat, the snapshots, the retention — in a
    thread, reporting through `on_event(kind, text)`; `on_taken_over()` when
    the record is no longer ours, `on_handed(name)` once a hand-over asked
    of us is done (the last copy uploaded, the record released)."""

    def __init__(self, client, record: HostRecord, server: LocalServer, assets_dir: Path,
                 on_event: Callable[[str, str], None], on_taken_over: Callable[[], None],
                 clock: Callable[[], float] = time.monotonic,
                 on_handed: Callable[[str], None] | None = None,
                 seed: bytes | None = None, key: str = "") -> None:
        self.client = client
        self.record = record
        self.server = server
        self.assets_dir = Path(assets_dir)
        self.on_event = on_event
        self.on_taken_over = on_taken_over
        self.on_handed = on_handed or (lambda _name: None)
        self.clock = clock
        # The launcher's key pair: every copy uploaded carries its signature.
        self.seed = seed
        self.key = key
        self.state = HosterState()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self, final: bool = True) -> None:
        """Ends the loop; with `final`, a last snapshot and the release."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=STATUS_EVERY + 5)
        if final and not self.state.taken_over and not self.state.handed:
            try:
                self.upload_once(force=True)
            except Exception as error:      # the game is stopping anyway: log, never raise
                self.on_event("error", str(error))
            release(self.client, self.record)

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.tick()
            self._stop.wait(STATUS_EVERY)

    def tick(self) -> None:
        """One round: a look at the record (a hand-over asked of us, or the
        game taken), the heartbeat when due, a snapshot when the game
        changed."""
        now = self.clock()
        try:
            if self.look():
                return
            if now - self.state.last_heartbeat >= HEARTBEAT_EVERY:
                heartbeat(self.client, self.record)
                self.state.last_heartbeat = now
            self.upload_once()
        except DropboxError as error:
            if error.conflict:
                # Somebody wrote since our last write, between our look and
                # ours: a hand-over asked just now, or the game taken.
                try:
                    if self.look():
                        return
                except Exception:
                    pass
                self.taken()
                return
            self.state.errors.append(error.summary)
            self.on_event("error", error.summary)
        except Exception as error:
            self.state.errors.append(str(error))
            self.on_event("error", str(error))

    def look(self) -> bool:
        """The record as it is now (one download, no write). Taken by
        someone else: `taken`, True. A hand-over asked of us: `hand_over`,
        True. Still ours and quiet: False, with the rev followed, so that
        our next write lands on whatever was written meanwhile."""
        current = read_record(self.client)
        if (current is None or current.host_id != self.record.host_id
                or current.epoch != self.record.epoch):
            self.taken()
            return True
        self.record.rev = current.rev
        if current.handover and not current.released:
            self.hand_over(current.handover)
            return True
        return False

    def taken(self) -> None:
        self.state.taken_over = True
        self._stop.set()
        self.on_event("taken", "")
        self.on_taken_over()

    def hand_over(self, asked: dict) -> None:
        """What the one who asked waits for: the last copy up, the record
        released, and the window told to stop the server (nothing to upload
        at its Stop: `handed` says so)."""
        self.record.handover = asked
        name = str(asked.get("to_name") or asked.get("to_id") or "")
        try:
            self.upload_once(force=True)
        except DropboxError as error:
            if error.conflict:              # taken by force while we were at it
                self.taken()
                return
            self.on_event("error", error.summary)
        except Exception as error:
            self.on_event("error", str(error))
        release(self.client, self.record)
        self.state.handed = True
        self._stop.set()
        self.on_event("handed", name)
        self.on_handed(name)

    def upload_once(self, force: bool = False) -> bool:
        now = self.clock()
        status = self.server.status()
        rev = int(status.get("rev") or 0)
        changed = self.state.last_rev is None or rev != self.state.last_rev
        due = now - self.state.last_upload >= UPLOAD_EVERY
        if not force and not (changed and due):
            return False
        if not force and not changed:
            return False
        self.record.seq += 1
        data = self.server.snapshot(self.record.epoch, self.record.seq)
        if self.seed is not None and self.key:
            data = sign_snapshot(data, self.seed, self.record.host_id, self.key)
        hashes = bundle.asset_hashes(self.assets_dir)
        self.state.known_assets = push_assets(self.client, self.assets_dir, hashes,
                                              self.state.known_assets)
        done = upload_snapshot(self.client, data, self.record.epoch, self.record.seq)
        heartbeat(self.client, self.record)          # the seq travels in the record too
        self.state.last_heartbeat = now
        self.server.synced(self.record.epoch, self.record.seq)
        # Recording the marks is itself a write: read the revision again, or
        # every upload would look like a change and the next tick would upload
        # once more, forever.
        self.state.last_rev = int(self.server.status().get("rev") or rev)
        self.state.last_upload = now
        self.state.uploads += 1
        self.on_event("uploaded", done["recent"] + (f" + {done['daily']}" if done["daily"] else ""))
        return True
