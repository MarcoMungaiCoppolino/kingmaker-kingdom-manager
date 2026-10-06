"""What the launcher does, without the window.

The server is a child process — the same executable with `--serve`, or
`launch.py --serve` from source — and the launcher reads its output: the
`KM <kind> <value>` lines printed by `main.announce`, plus the one line
NiceGUI itself prints with the On Air address. Everything else the child
prints goes to the log pane.
"""
from __future__ import annotations

import json
import os
import re
import platform
import secrets
import socket
import subprocess
import sys
import threading
import urllib.error
import urllib.request
import uuid
import webbrowser
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from kingmaker import __version__, config

APP_NAME = "Kingmaker Kingdom Manager"
REPOSITORY = "MarcoMungaiCoppolino/kingmaker-kingdom-manager"
RELEASES_PAGE = f"https://github.com/{REPOSITORY}/releases/latest"
RELEASES_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
RELEASES_LIST_API = f"https://api.github.com/repos/{REPOSITORY}/releases?per_page=30"
ON_AIR_PAGE = "https://on-air.nicegui.io/login"
TOKEN_VARIABLE = "KINGMAKER_ON_AIR_TOKEN"
ANONYMOUS_VARIABLE = "KINGMAKER_ON_AIR_ANONYMOUS"
SECRET_VARIABLE = "KINGMAKER_LAUNCHER_SECRET"
CREDENTIAL_VARIABLE = "KINGMAKER_SYNC_CREDENTIAL"

MODES = ("local", "lan", "online")
SETTINGS_FILE = "launcher.json"
LOCK_FILE = "launcher.lock"
# How long a graceful stop may take before the child is killed.
STOP_PATIENCE = 8.0
# Ports tried after the chosen one when it is busy.
PORT_ATTEMPTS = 20

KM_LINE = re.compile(r"^KM (ready|lan|admin-password) (\S.*)$")
AIR_LINE = re.compile(r"NiceGUI is on air at (https?://\S+)")


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def game_folder() -> Path:
    """Where the save, the images and the launcher's own settings live."""
    return config.DATA_DIR


def icon_file(kind: str = "ico") -> Path | None:
    """The window's icon: `kingmaker.ico` (Windows) or `kingmaker.png`,
    bundled under `_internal/icon/` when frozen, in `packaging/icon/` from
    source. None when missing: the window then keeps Tk's own."""
    if is_frozen():
        folder = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent / "_internal")) / "icon"
    else:
        folder = config.ROOT_DIR / "packaging" / "icon"
    path = folder / f"kingmaker.{kind}"
    return path if path.is_file() else None


# ----------------------------------------------------------------- settings
@dataclass
class Settings:
    mode: str = "local"
    port: int = config.PORT
    language: str = ""            # "" = not chosen yet: guess from the system
    token: str = ""
    open_browser: bool = True
    firewall_shown: bool = False
    # Whether the launcher asks GitHub for a newer release at start. The
    # only thing the request carries is this machine's address and the app's
    # version, but it is a request nobody typed: hence the switch.
    check_updates: bool = True
    # The cloud: the Dropbox credential (app_key, refresh_token, account_id,
    # account_name, app_name), the table's name, and who we are to it
    # (username, role). Empty until the administrator set it up here or
    # this launcher connected to a table. In clear, like the token.
    cloud: dict = field(default_factory=dict)
    # This launcher's identity in `host.json`: a random id made once, and a
    # name the others read ("Marco's PC").
    host_id: str = ""
    host_name: str = ""

    @property
    def cloud_ready(self) -> bool:
        return bool(self.cloud.get("app_key") and self.cloud.get("refresh_token"))

    def credential(self):
        from kingmaker.launcher.dropbox import Credential
        return Credential.from_dict(self.cloud)

    def identity(self) -> tuple[str, str]:
        """(host_id, host_name), made up the first time."""
        if not self.host_id:
            self.host_id = uuid.uuid4().hex[:12]
        if not self.host_name:
            who = self.cloud.get("username") or os.environ.get("USERNAME") or os.environ.get("USER") or ""
            self.host_name = f"{who}@{platform.node()}" if who else platform.node()
        return self.host_id, self.host_name

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = path or game_folder() / SETTINGS_FILE
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        known = {f: raw[f] for f in cls.__dataclass_fields__ if f in raw}
        if not isinstance(known.get("cloud", {}), dict):
            known["cloud"] = {}
        settings = cls(**known)
        if settings.mode not in MODES:
            settings.mode = "local"
        if not isinstance(settings.port, int) or not 1 <= settings.port <= 65535:
            settings.port = config.PORT
        return settings

    def save(self, path: Path | None = None) -> None:
        path = path or game_folder() / SETTINGS_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        # Written whole into a sibling and moved over: a crash half-way must
        # not leave an empty file where the credential was. On POSIX the
        # file is the owner's alone; Windows keeps it in the user's profile.
        part = path.with_name(path.name + ".tmp")
        part.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        try:
            os.chmod(part, 0o600)
        except OSError:
            pass
        os.replace(part, path)


def guess_language() -> str:
    """The system's language, if it is one we speak."""
    import locale
    from kingmaker.locale import i18n
    try:
        code = locale.getlocale()[0] or ""
    except ValueError:
        code = ""
    if not code and sys.platform == "win32":
        try:
            import ctypes
            code = locale.windows_locale.get(ctypes.windll.kernel32.GetUserDefaultUILanguage(), "")
        except (AttributeError, OSError):
            code = ""
    return i18n.normalize(code.replace("_", "-")) or i18n.DEFAULT


# ----------------------------------------------------------------- versions
def version_tuple(text: str) -> tuple[int, ...]:
    """`"v1.10.2"` → `(1, 10, 2)`; anything unreadable → `()`."""
    text = str(text or "").strip().lstrip("vV")
    parts = []
    for piece in text.split("."):
        digits = re.match(r"\d+", piece)
        if not digits:
            break
        parts.append(int(digits.group()))
    return tuple(parts)


def is_newer(candidate: str, current: str = __version__) -> bool:
    new, old = version_tuple(candidate), version_tuple(current)
    return bool(new) and new > old


@dataclass
class Release:
    version: str
    page: str
    assets: list[dict] = field(default_factory=list)
    published: str = ""            # "2026-09-16", from GitHub
    prerelease: bool = False

    def installer(self) -> dict | None:
        """The file for this platform: the Windows setup, or the Linux tarball."""
        wanted = "-Setup.exe" if sys.platform == "win32" else "-linux-x86_64.tar.gz"
        for asset in self.assets:
            if str(asset.get("name", "")).endswith(wanted):
                return asset
        return None


def latest_release(timeout: float = 5.0) -> Release | None:
    """The latest release on GitHub, or None when there is no network, no
    release, or the API is not in the mood: the launcher must work offline."""
    request = urllib.request.Request(RELEASES_API, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"{APP_NAME.replace(' ', '-')}/{__version__}",
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as answer:
            data = json.loads(answer.read().decode("utf-8"))
    except Exception:
        return None
    return parse_release(data)


def parse_release(data: dict) -> Release | None:
    tag = str(data.get("tag_name") or "")
    if not version_tuple(tag):
        return None
    assets = [{"name": a.get("name", ""), "url": a.get("browser_download_url", ""),
               "size": int(a.get("size") or 0)}
              for a in data.get("assets") or []]
    return Release(version=tag.lstrip("vV"), page=str(data.get("html_url") or RELEASES_PAGE),
                   assets=assets, published=str(data.get("published_at") or "")[:10],
                   prerelease=bool(data.get("prerelease")))


def list_releases(timeout: float = 8.0) -> list[Release]:
    """Every release on GitHub, newest first — for choosing a version, an
    older one included. [] when offline."""
    request = urllib.request.Request(RELEASES_LIST_API, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"{APP_NAME.replace(' ', '-')}/{__version__}",
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as answer:
            data = json.loads(read_body(answer).decode("utf-8"))
    except Exception:
        return []
    found = [parse_release(item) for item in data if isinstance(item, dict) and not item.get("draft")]
    releases = [r for r in found if r is not None]
    releases.sort(key=lambda r: version_tuple(r.version), reverse=True)
    return releases


def release_for(releases: list[Release], version: str) -> Release | None:
    """The release of exactly that version among those listed, or None."""
    wanted = version_tuple(version)
    for release in releases:
        if wanted and version_tuple(release.version) == wanted:
            return release
    return None


def find_release(version: str) -> Release | None:
    """The release of that version on GitHub, or None when offline or when
    there is none: the way to the installer the table's version asks for."""
    return release_for(list_releases(), version)


def download(url: str, target: Path, progress: Callable[[int, int], None] | None = None,
             timeout: float = 30.0) -> Path:
    """Downloads `url` to `target`, calling `progress(done, total)` on the way."""
    request = urllib.request.Request(url, headers={"User-Agent": f"{APP_NAME}/{__version__}"})
    target.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(request, timeout=timeout) as answer, open(target, "wb") as out:
        total = int(answer.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = answer.read(1 << 16)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    return target


def run_installer(path: Path) -> None:
    """Hands the downloaded installer to the system; the caller quits."""
    if sys.platform == "win32":
        os.startfile(str(path))          # type: ignore[attr-defined]
    else:
        webbrowser.open(str(path.parent))


# -------------------------------------------------------------------- ports
def port_in_use(port: int) -> bool:
    """True when nothing can listen on `port` right now.

    Both the wildcard and the loopback are tried: on Windows a bind on all
    addresses succeeds even while another program holds `127.0.0.1` alone
    (an editor's port forward, an old server), and the real server, which
    binds the loopback, would then fail where the check said it was free.
    """
    for host in ("0.0.0.0", "127.0.0.1"):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind((host, port))
            except OSError:
                return True
    return False


def free_port(preferred: int, attempts: int = PORT_ATTEMPTS) -> int | None:
    """`preferred` if it is free, else the first free one after it."""
    for port in range(preferred, preferred + attempts + 1):
        if 1 <= port <= 65535 and not port_in_use(port):
            return port
    return None


# ------------------------------------------------------------------ the child
def server_command(settings: Settings, port: int) -> list[str]:
    """The child's command line: the same program, `--serve`."""
    if is_frozen():
        command = [sys.executable, "--serve"]
    else:
        command = [sys.executable, str(config.ROOT_DIR / "launch.py"), "--serve"]
    command += ["--port", str(port), "--no-browser"]
    if settings.mode == "lan":
        command.append("--lan")
    elif settings.mode == "online":
        command.append("--online")
    return command


def server_environment(settings: Settings, secret: str = "", cloud: bool = True,
                       token: str | None = None) -> dict[str, str]:
    """The child's environment: the token and the shutdown secret travel
    here, not on the command line, where every process list would show
    them.

    `token` is the table's, read from the cloud folder for this one start
    (None: the launcher's own, for whoever plays online without the cloud).
    `cloud=False` is hosting without the cloud, after it did not answer:
    no token, because the table's fixed address must not point at a copy
    the cloud knows nothing about, and no credential to hand out from a
    server nobody is told of."""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    chosen = (settings.token if token is None else token).strip()
    if settings.mode == "online" and chosen and cloud:
        env[TOKEN_VARIABLE] = chosen
    if not cloud:
        # Leaving the token out is not enough: the server also reads it from
        # the user's environment and, on Windows, from the registry.
        env.pop(TOKEN_VARIABLE, None)
        env[ANONYMOUS_VARIABLE] = "1"
    if secret:
        env[SECRET_VARIABLE] = secret
    if cloud and settings.cloud_ready:
        # What another host's launcher receives from the credential route:
        # the cloud, the table's token and name. Never the database's business.
        handout = {**{k: settings.cloud.get(k, "") for k in
                      ("app_key", "refresh_token", "account_id", "account_name", "app_name")},
                   "table": settings.cloud.get("table", ""), "token": settings.token.strip()}
        env[CREDENTIAL_VARIABLE] = json.dumps(handout)
    return env


PASSWORD_LINE = re.compile(r"(password:\s*)(\S+)", re.IGNORECASE)


def mask_secrets(line: str) -> str:
    """A line the server printed, with whatever follows `password:` hidden.
    The first-start block says the password in words, and the log pane —
    which people paste into bug reports — must not keep it."""
    return PASSWORD_LINE.sub(r"\1********", line)


def parse_line(line: str) -> tuple[str, str] | None:
    """`("ready", url)`, `("lan", url)`, `("admin-password", pw)`, `("air", url)`
    or None for a line that is just log."""
    line = line.strip()
    found = KM_LINE.match(line)
    if found:
        return found.group(1), found.group(2).strip()
    found = AIR_LINE.search(line)
    if found:
        return "air", found.group(1).rstrip("/") + "/"
    return None


class Server:
    """The child process and its output.

    `on_line(text)` is called from the reader thread for every line the
    child prints; `on_exit(code)` once, when it ends. The window puts both
    on a queue and reads it from the Tk loop.
    """

    def __init__(self, on_line: Callable[[str], None], on_exit: Callable[[int], None]) -> None:
        self.on_line = on_line
        self.on_exit = on_exit
        self.process: subprocess.Popen | None = None
        self._reader: threading.Thread | None = None
        self.port: int | None = None
        self.secret = ""

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self, settings: Settings, port: int, cloud: bool = True, token: str | None = None) -> None:
        if self.running:
            return
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        self.port = port
        self.secret = secrets.token_urlsafe(24)
        self.process = subprocess.Popen(
            server_command(settings, port),
            env=server_environment(settings, self.secret, cloud=cloud, token=token),
            cwd=str(config.ROOT_DIR), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            creationflags=flags)
        self._reader = threading.Thread(target=self._read, args=(self.process,), daemon=True)
        self._reader.start()

    def _read(self, process: subprocess.Popen) -> None:
        assert process.stdout is not None
        for line in process.stdout:
            self.on_line(line.rstrip("\r\n"))
        code = process.wait()
        self.on_exit(code)

    def ask_shutdown(self, timeout: float = 3.0) -> bool:
        """The polite request: `POST /_launcher/shutdown` with this start's
        secret. False when the server is not answering (not up yet, or
        already gone)."""
        if not self.port or not self.secret:
            return False
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/_launcher/shutdown", method="POST",
            headers={"X-Launcher-Secret": self.secret})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as answer:
                return answer.status == 204
        except Exception:
            return False

    def stop(self, patience: float = STOP_PATIENCE) -> None:
        """Asks first, so the app writes its last save on shutdown; a child
        that does not answer, or does not leave in time, is killed."""
        process = self.process
        if process is None or process.poll() is not None:
            return
        asked = self.ask_shutdown()
        try:
            if not asked:
                process.terminate()
            process.wait(timeout=patience)
        except (subprocess.TimeoutExpired, OSError):
            process.kill()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass


# ------------------------------------------------------------ one at a time
class SingleInstance:
    """A lock file, so a second launcher on the same game says so and quits
    instead of starting a second server on the same database."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or game_folder() / LOCK_FILE
        self._handle = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            handle = open(self.path, "a+")
        except OSError:
            return False
        try:
            if sys.platform == "win32":
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self._handle = handle
        return True

    def release(self) -> None:
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            if sys.platform == "win32":
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        handle.close()


# ------------------------------------------------------------------ the game
def writable(folder: Path) -> bool:
    """Can we create files here? The installed app must live in a folder the
    user owns; `Program Files` is not one."""
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / ".write-probe"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
    except OSError:
        return False
    return True


def open_folder(folder: Path) -> None:
    if sys.platform == "win32":
        os.startfile(str(folder))        # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(folder)])
    else:
        subprocess.Popen(["xdg-open", str(folder)])


def inspect_save(path: Path) -> dict:
    """What a save holds — a zip from the Save tab or a bare database:
    `{"kind", "version", "users", "kingdom", "assets"}`. Raises ValueError
    with a catalog key and its params when it is neither."""
    from kingmaker.storage import bundle
    return bundle.inspect(Path(path))


def load_save(path: Path, assets_dir: Path | None = None) -> Path:
    """Replaces the game with a save — the zip the table downloaded on the
    old PC, or its database. The server must be stopped. The current save,
    if any, is kept next to itself as `kingmaker.db.before-restore-<date>.bak`,
    the images of a zip are unpacked over the assets folder, and the file
    given is copied, never moved. Returns the copy kept."""
    from kingmaker.storage import bundle
    from kingmaker.storage.archive import Archive
    archive = Archive(config.DB_FILE)
    try:
        return bundle.restore(archive, assets_dir or config.ASSETS_DIR, Path(path))
    finally:
        archive.close()


@dataclass
class LocalState:
    """What the local database says of the cloud: the copy it last matched
    (`epoch`, `seq`), the document revision it had at that moment
    (`synced_krev`, None for a file synced before 1.3.0 recorded it), the
    revision it has now, and the day it was hosted without the cloud, if
    it was ("" otherwise)."""
    epoch: int = 0
    seq: int = 0
    synced_krev: int | None = None
    current_krev: int = 0
    forked_at: str = ""

    @property
    def marks(self) -> tuple[int, int]:
        return self.epoch, self.seq

    @property
    def diverged(self) -> bool:
        """Whether the game changed here since it last matched the cloud.
        Not knowable for a file synced before the revision was recorded:
        then the cloud wins, as it always did."""
        return self.synced_krev is not None and self.current_krev != self.synced_krev


FORK_MARK = "forked_at"


def local_state(db_file: Path | None = None, campaign: str | None = None) -> LocalState:
    """Reads `LocalState` from the database; the server must be stopped."""
    from kingmaker.storage.archive import Archive
    archive = Archive(db_file or config.DB_FILE)
    try:
        raw = archive.read_meta("sync_marks")
        current = archive.document_rev(campaign or config.DEFAULT_CAMPAIGN)
        forked = archive.read_meta(FORK_MARK) or ""
    finally:
        archive.close()
    try:
        data = json.loads(raw) if raw else {}
    except ValueError:
        data = {}
    synced = data.get("krev")
    return LocalState(epoch=int(data.get("epoch") or 0), seq=int(data.get("seq") or 0),
                      synced_krev=int(synced) if synced is not None else None,
                      current_krev=current, forked_at=str(forked))


def mark_fork(when: str = "", db_file: Path | None = None) -> None:
    """Writes the day the game was hosted without the cloud into the
    database (`""` clears it); the server must be stopped. The next cloud
    start shows it when it asks which copy is the game."""
    from kingmaker.storage.archive import Archive
    archive = Archive(db_file or config.DB_FILE)
    try:
        archive.write_meta(FORK_MARK, when)
    finally:
        archive.close()


def read_body(answer) -> bytes:
    """The bytes of an HTTP answer, gunzipped when a relay compressed them
    (the On Air relay does, whatever the request asked for)."""
    data = answer.read()
    if (answer.headers.get("Content-Encoding") or "").lower() == "gzip" or data[:2] == b"\x1f\x8b":
        import gzip
        data = gzip.decompress(data)
    return data


def whoami_proof(secret: str, nonce: str) -> str:
    """What the server started with `secret` answers to `whoami?nonce=`:
    an HMAC nobody else can produce, of a nonce the caller chose."""
    import hashlib
    import hmac
    return hmac.new(secret.encode("utf-8"), nonce.encode("ascii"), hashlib.sha256).hexdigest()


def is_random_air_address(url: str) -> bool:
    """Whether the relay handed out an anonymous device instead of the
    token's: the address then has `/devices/` in it, as `cli.py` says."""
    return "/devices/" in (url or "")


def probe_address(address: str, nonce: str, timeout: float = 10.0) -> tuple[dict | None, str]:
    """Asks whatever answers at `address` who it is: `(the JSON of
    /_launcher/whoami, "")`, or `(None, why)` when nothing of ours answers.
    Through the public address, so the answer says who holds it."""
    address = address.strip().rstrip("/")
    if not address.startswith(("http://", "https://")):
        address = "https://" + address
    request = urllib.request.Request(f"{address}/_launcher/whoami?nonce={nonce}",
                                     headers={"Accept-Encoding": "identity",
                                              "User-Agent": f"{APP_NAME}/{__version__}"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as answer:
            data = json.loads(read_body(answer).decode("utf-8"))
    except urllib.error.HTTPError as error:
        return None, str(error.code)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as error:
        return None, str(error)
    if not isinstance(data, dict) or not isinstance(data.get("proof"), str):
        return None, "no proof in the answer"
    return data, ""


def fetch_credential(address: str, username: str, password: str, timeout: float = 20.0) -> dict:
    """Asks a running host for the cloud credential: `POST /_launcher/credential`
    at the table's address. Returns `{"credential", "role", "username", "kingdom"}`;
    raises LookupError when refused (wrong password, or not allowed to host),
    OSError when the address does not answer."""
    address = address.strip().rstrip("/")
    if not address.startswith(("http://", "https://")):
        address = "https://" + address
    body = json.dumps({"username": username.strip(), "password": password}).encode("utf-8")
    request = urllib.request.Request(f"{address}/_launcher/credential", data=body, method="POST",
                                     headers={"Content-Type": "application/json",
                                              "Accept-Encoding": "identity",
                                              "User-Agent": f"{APP_NAME}/{__version__}"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as answer:
            data = json.loads(read_body(answer).decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise LookupError(str(error.code))
    except (urllib.error.URLError, TimeoutError, ValueError) as error:
        raise OSError(str(error))
    if not isinstance(data, dict) or not isinstance(data.get("credential"), dict):
        raise LookupError("no credential in the answer")
    return data


def adopt_credential(settings: Settings, answer: dict) -> None:
    """Keeps what a host handed out: the cloud, the table's token, our role."""
    credential = answer["credential"]
    settings.cloud = {k: str(credential.get(k, "")) for k in
                      ("app_key", "refresh_token", "account_id", "account_name", "app_name")}
    settings.cloud["table"] = str(credential.get("table") or answer.get("kingdom") or "")
    settings.cloud["role"] = str(answer.get("role", ""))
    settings.cloud["username"] = str(answer.get("username", ""))
    if credential.get("token"):
        settings.token = str(credential["token"])
    settings.host_name = ""          # renamed after the account we now know
    settings.identity()


def reset_admin_password() -> tuple[str, str]:
    """A new password for the administrator, shown once like the first one.

    For the day the launcher missed the first-start dialog, or the password
    was simply lost: whoever can run the launcher owns the folder with the
    database, so nothing is protected from them anyway. The server must be
    stopped: the file is opened directly.
    """
    from kingmaker.access import auth, permissions
    from kingmaker.storage.archive import Archive
    archive = Archive(config.DB_FILE)
    try:
        users = [u for u in archive.list_users()
                 if u.get("role") == permissions.ADMIN and int(u.get("active") or 0)]
        if not users:
            password = auth.ensure_admin(archive)
            if password is None:
                raise LookupError("no active administrator")
            return "admin", password
        users.sort(key=lambda u: (u.get("username") != "admin", u.get("username") or ""))
        chosen = users[0]
        password = auth.random_password()
        auth.change_password(archive, chosen["id"], password)
        archive.update_user(chosen["id"], must_change_pw=1)
        return str(chosen["username"]), password
    finally:
        archive.close()
