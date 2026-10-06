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
                     rev=str(meta.get("rev", "")))
        modified = meta.get("server_modified")
        record.age = max(0.0, now - _parse_time(modified)) if modified else 0.0
        return record

    def body(self) -> bytes:
        return json.dumps({"host_id": self.host_id, "host_name": self.host_name,
                           "epoch": self.epoch, "seq": self.seq, "since": self.since,
                           "released": self.released, "address": self.address,
                           "app_version": self.app_version,
                           "beat": self.beat, "seen": self.seen},
                          indent=2).encode("utf-8")

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
    every host agrees on."""
    meta = client.upload(".clock", b"", mode="overwrite")
    return _parse_time(meta["server_modified"])


def read_record(client) -> HostRecord | None:
    meta = client.metadata(HOST_FILE)
    if meta is None:
        return None
    data, meta = client.download(HOST_FILE)
    return HostRecord.parse(data, meta, server_now(client))


def claim(client, host_id: str, host_name: str, force: bool = False,
          attempts: int = 3) -> HostRecord:
    """Become the host, or raise `Held`. `force` takes the game from a
    living host (the administrator's button); a stale or released record is
    taken freely; our own record (a crash and a restart) is kept."""
    for _attempt in range(attempts):
        current = read_record(client)
        mine = HostRecord(host_id=host_id, host_name=host_name,
                          since=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
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


# ------------------------------------------------------------------ the table
TABLE_FILE = "table.json"
TABLE_FORMAT = 1


@dataclass
class TableRecord:
    """`table.json`: what the table is, which version it plays on, and the
    On Air token every host reads at Start instead of keeping a copy.

    Any member of the folder can write it — Dropbox gives no finer right —
    so the launcher's manners (only the administrator changes the version
    and the token) are a convention, not a wall; the docs say so."""
    format: int = TABLE_FORMAT
    table_id: str = ""            # who we are: random, made once with the file
    name: str = ""
    app_version: str = ""         # the version every host must run to host
    air_token: str = ""           # "" until the administrator's launcher writes it
    air_address: str = ""         # the fixed address the token gives, once seen
    air_generation: int = 0       # rises at every new token
    access_generation: int = 1    # rises at every rotation of the cloud access
    set_by: str = ""
    set_at: str = ""
    rev: str = ""                 # Dropbox's, for the compare-and-swap

    @classmethod
    def parse(cls, data: bytes, meta: dict) -> "TableRecord":
        try:
            raw = json.loads(data.decode("utf-8"))
        except ValueError:
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        return cls(format=int(raw.get("format") or TABLE_FORMAT), table_id=str(raw.get("table_id", "")),
                   name=str(raw.get("name", "")), app_version=str(raw.get("app_version", "")),
                   air_token=str(raw.get("air_token", "")), air_address=str(raw.get("air_address", "")),
                   air_generation=int(raw.get("air_generation") or 0),
                   access_generation=int(raw.get("access_generation") or 1),
                   set_by=str(raw.get("set_by", "")), set_at=str(raw.get("set_at", "")),
                   rev=str(meta.get("rev", "")))

    def body(self) -> bytes:
        return json.dumps({"format": self.format, "table_id": self.table_id, "name": self.name,
                           "app_version": self.app_version, "air_token": self.air_token,
                           "air_address": self.air_address, "air_generation": self.air_generation,
                           "access_generation": self.access_generation,
                           "set_by": self.set_by, "set_at": self.set_at},
                          indent=2).encode("utf-8")

    def mismatch(self, mine: str = __version__) -> bool:
        """Whether a launcher of version `mine` may not host: the match is
        exact, because the same save format has carried different rules."""
        return bool(self.app_version) and self.app_version != mine


def read_table(client) -> TableRecord | None:
    meta = client.metadata(TABLE_FILE)
    if meta is None:
        return None
    data, meta = client.download(TABLE_FILE)
    return TableRecord.parse(data, meta)


def write_table(client, table: TableRecord, by: str = "") -> TableRecord:
    """Writes the table file with a compare-and-swap on its rev (`add`
    when it has none yet); a conflict reads it again and writes once more,
    keeping what the caller set."""
    mine = table.body()
    for attempt in range(2):
        if by:
            table.set_by = by
        table.set_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
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
                 by: str = "") -> tuple[TableRecord, bool]:
    """The table file, created by the first launcher of 1.3.0 or newer that
    finds none: its own version pins the table, its local token (if the
    caller passes one) goes in. `(table, created)`."""
    table = read_table(client)
    if table is not None:
        return table, False
    table = TableRecord(table_id=uuid.uuid4().hex[:12], name=name, app_version=version,
                        air_token=token, air_generation=1 if token else 0)
    return write_table(client, table, by=by), True


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


def newest_usable(client, into: Path, log: Callable[[str], None] = lambda _t: None,
                  record: HostRecord | None = None) -> Path | None:
    """Downloads copies newest first, recent then daily, and returns the
    first one that passes the checks, or None.

    A corrupt copy is skipped for the next one. A copy from a **newer** app
    stops the search with `NewerCopy`: falling back to an older copy there
    would roll the game back to before the newer host played, and nobody
    would know. A recent copy whose epoch is above the record's cannot have
    been written by any host the record ever named (epochs come from the
    record alone), so it is skipped and said in the log.
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


class Hoster:
    """While we host: the heartbeat, the snapshots, the retention — in a
    thread, reporting through `on_event(kind, text)`; `on_taken_over()` when
    the record is no longer ours."""

    def __init__(self, client, record: HostRecord, server: LocalServer, assets_dir: Path,
                 on_event: Callable[[str, str], None], on_taken_over: Callable[[], None],
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.client = client
        self.record = record
        self.server = server
        self.assets_dir = Path(assets_dir)
        self.on_event = on_event
        self.on_taken_over = on_taken_over
        self.clock = clock
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
        if final and not self.state.taken_over:
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
        """One round: heartbeat when due, snapshot when the game changed."""
        now = self.clock()
        try:
            if now - self.state.last_heartbeat >= HEARTBEAT_EVERY:
                heartbeat(self.client, self.record)
                self.state.last_heartbeat = now
            self.upload_once()
        except DropboxError as error:
            if error.conflict:
                self.state.taken_over = True
                self._stop.set()
                self.on_event("taken", "")
                self.on_taken_over()
                return
            self.state.errors.append(error.summary)
            self.on_event("error", error.summary)
        except Exception as error:
            self.state.errors.append(str(error))
            self.on_event("error", str(error))

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
