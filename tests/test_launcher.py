# -*- coding: utf-8 -*-
"""The launcher without its window: settings, versions, the lines the server
prints, the ports, the lock, the command line, the frozen defaults, the
administrator reset.

Runs on the test scene like the rest of the suite. The one thing it changes
in the scene — the administrator's password — is put back at the end.
"""
import os
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from kingmaker import cli, config  # noqa: E402
from kingmaker.launcher import core  # noqa: E402

results = []
folder = Path(tempfile.mkdtemp(prefix="km-launcher-"))

# 1. versions
results.append(("version tuple", core.version_tuple("v1.10.2") == (1, 10, 2)))
results.append(("version tuple of junk", core.version_tuple("latest") == ()))
results.append(("1.10 is newer than 1.9", core.is_newer("1.10.0", "1.9.9")))
results.append(("same version is not newer", not core.is_newer("1.1.0", "1.1.0")))
results.append(("junk is never newer", not core.is_newer("", "1.0.0")))

# 2. settings round-trip, and a broken file falls back to the defaults
path = folder / "launcher.json"
saved = core.Settings(mode="online", port=8123, language="it", token="abc", open_browser=False,
                      firewall_shown=True, check_updates=False)
saved.save(path)
loaded = core.Settings.load(path)
results.append(("settings round-trip", loaded == saved))
results.append(("the update check is on unless switched off",
                core.Settings().check_updates and not loaded.check_updates))
path.write_text('{"mode": "sideways", "port": "eighty", "unknown": 1}', encoding="utf-8")
loaded = core.Settings.load(path)
results.append(("unknown mode falls back", loaded.mode == "local"))
results.append(("bad port falls back", loaded.port == config.PORT))
path.write_text("{ not json", encoding="utf-8")
results.append(("unreadable file gives defaults", core.Settings.load(path) == core.Settings()))
cloudy = core.Settings(cloud={"app_key": "k", "refresh_token": "r", "table": "T", "role": "gm",
                              "username": "dm"}, token="AIR")
cloudy.save(path)
back = core.Settings.load(path)
results.append(("the cloud credential round-trips", back.cloud_ready and back.cloud["table"] == "T"))
results.append(("a launcher without a credential is not cloud-ready", not core.Settings().cloud_ready))
host_id, host_name = back.identity()
results.append(("the identity is made once and named after the account",
                len(host_id) == 12 and host_name.startswith("dm@") and back.identity() == (host_id, host_name)))
env_cloud = core.server_environment(cloudy, "shh")
handout = __import__("json").loads(env_cloud[core.CREDENTIAL_VARIABLE])
results.append(("the hand-out carries the cloud and the table's token",
                handout["refresh_token"] == "r" and handout["token"] == "AIR" and handout["table"] == "T"))
results.append(("no hand-out without a credential",
                core.CREDENTIAL_VARIABLE not in core.server_environment(core.Settings(), "shh")))

# 3. the lines the server prints
results.append(("ready line", core.parse_line("KM ready http://127.0.0.1:8080") == ("ready", "http://127.0.0.1:8080")))
results.append(("lan line", core.parse_line("KM lan http://192.168.1.7:8080\n") == ("lan", "http://192.168.1.7:8080")))
results.append(("password line", core.parse_line("KM admin-password abcd-efgh") == ("admin-password", "abcd-efgh")))
results.append(("NiceGUI's on air line",
                core.parse_line("NiceGUI is on air at https://europe.on-air.io/marco/device-0")
                == ("air", "https://europe.on-air.io/marco/device-0/")))
results.append(("a log line is not an event", core.parse_line("INFO: Uvicorn running on ...") is None))
results.append(("an unknown KM kind is log", core.parse_line("KM whatever x") is None))

# 4. a release as GitHub describes it
release = core.parse_release({"tag_name": "v1.2.0", "html_url": "https://example/rel",
                              "assets": [{"name": "Kingmaker-Kingdom-Manager-1.2.0-Setup.exe",
                                          "browser_download_url": "https://example/setup", "size": 5},
                                         {"name": "Kingmaker-Kingdom-Manager-1.2.0-linux-x86_64.tar.gz",
                                          "browser_download_url": "https://example/tar", "size": 6}]})
results.append(("release version without the v", release is not None and release.version == "1.2.0"))
wanted = "Setup.exe" if sys.platform == "win32" else "tar.gz"
results.append(("the installer for this platform",
                release is not None and release.installer() is not None
                and release.installer()["name"].endswith(wanted)))
results.append(("a release without a version is None", core.parse_release({"tag_name": "nightly"}) is None))
listed = [core.parse_release(d) for d in ({"tag_name": "v1.1.0", "published_at": "2026-09-16T10:00:00Z"},
                                          {"tag_name": "v1.10.0", "published_at": "2026-12-01T10:00:00Z"},
                                          {"tag_name": "v1.2.0", "published_at": "2026-10-01T10:00:00Z", "prerelease": True})]
listed.sort(key=lambda r: core.version_tuple(r.version), reverse=True)
results.append(("releases sort by version, not by text, and carry their date",
                [r.version for r in listed] == ["1.10.0", "1.2.0", "1.1.0"] and listed[0].published == "2026-12-01"
                and listed[1].prerelease))

# 5. ports: the chosen one when free, the next when busy
with socket.socket() as blocker:
    blocker.bind(("0.0.0.0", 0))
    blocker.listen(1)
    busy = blocker.getsockname()[1]
    results.append(("a listening port is in use", core.port_in_use(busy)))
    results.append(("the next free port is offered", core.free_port(busy) not in (None, busy)))
results.append(("a free port is kept", core.free_port(busy) == busy))

# 6. one launcher per game folder
first = core.SingleInstance(folder / "launcher.lock")
second = core.SingleInstance(folder / "launcher.lock")
results.append(("the lock is taken", first.acquire()))
results.append(("a second launcher is refused", not second.acquire()))
first.release()
results.append(("released, it can be taken again", second.acquire()))
second.release()

# 7. the child's command line and environment
settings = core.Settings(mode="lan", token="secret-token")
command = core.server_command(settings, 8090)
results.append(("from source the child runs launch.py --serve",
                command[0] == sys.executable and command[1].endswith("launch.py")
                and "--serve" in command and "--lan" in command and "--no-browser" in command
                and command[command.index("--port") + 1] == "8090"))
results.append(("the token stays out of the command line",
                "secret-token" not in " ".join(command)))
env = core.server_environment(settings, "shh")
results.append(("no token in the environment unless online", core.TOKEN_VARIABLE not in env
                or env[core.TOKEN_VARIABLE] != "secret-token"))
settings.mode = "online"
env = core.server_environment(settings, "shh")
results.append(("online, the token and the secret travel in the environment",
                env.get(core.TOKEN_VARIABLE) == "secret-token" and env.get(core.SECRET_VARIABLE) == "shh"
                and "--online" in core.server_command(settings, 8090)))

import gzip  # noqa: E402


class _Answer:
    def __init__(self, data, encoding=""):
        self.data, self.headers = data, {"Content-Encoding": encoding}

    def read(self):
        return self.data


results.append(("a plain answer is read as is", core.read_body(_Answer(b'{"a":1}')) == b'{"a":1}'))
results.append(("a gzipped answer is unpacked, header or not",
                core.read_body(_Answer(gzip.compress(b'{"a":1}'), "gzip")) == b'{"a":1}'
                and core.read_body(_Answer(gzip.compress(b'{"a":1}'))) == b'{"a":1}'))

# 8. the command line routes to the window or to the server
calls = []
from kingmaker.launcher import window  # noqa: E402
run_before, serve_before = window.run, cli.serve
window.run = lambda: calls.append("window")
cli.serve = lambda args: calls.append(("serve", args.port, args.lan, args.online))
try:
    cli.main([], frozen=True)
    cli.main(["--serve", "--port", "8099", "--lan"], frozen=True)
    cli.main([], frozen=False)
    cli.main(["--launcher"], frozen=False)
    cli.main(["--online", "TOK"], frozen=False)
finally:
    window.run, cli.serve = run_before, serve_before
results.append(("frozen without arguments opens the window", calls[0] == "window"))
results.append(("frozen --serve starts the server with its flags", calls[1] == ("serve", 8099, True, None)))
results.append(("from source the server is the default", calls[2][0] == "serve"))
results.append(("--launcher opens the window from source", calls[3] == "window"))
results.append(("--online keeps its token", calls[4] == ("serve", config.PORT, False, "TOK")))

results.append(("the window icon is found from source",
                core.icon_file("ico") is not None and core.icon_file("png") is not None
                and core.icon_file("ico").parent == Path(ROOT) / "packaging" / "icon"))

# 9. where the game lives: next to the package from source, next to the
#    executable when frozen — and the source defaults are pinned
results.append(("from source the root is the repository",
                config._root() == Path(ROOT).resolve() and not getattr(sys, "frozen", False)))
sys.frozen = True
try:
    results.append(("frozen, the root is the executable's folder",
                    config._root() == Path(sys.executable).resolve().parent))
finally:
    del sys.frozen
clean = {k: v for k, v in os.environ.items() if not k.startswith("KINGMAKER_")}
clean["PYTHONPATH"] = ROOT
probe = subprocess.run([sys.executable, "-c",
                        "from kingmaker import config; print(config.DATA_DIR); print(config.ASSETS_DIR)"],
                       cwd=folder, env=clean, capture_output=True, text=True)
lines = probe.stdout.split()
# Compared as paths, not text: on Windows the same folder prints as "Desktop"
# or "DESKTOP" depending on how the shell was opened.
results.append(("without settings the game is in ./saves and ./assets of the repository",
                [Path(line).resolve() for line in lines]
                == [Path(ROOT).resolve() / "saves", Path(ROOT).resolve() / "assets"]))

# 10. the administrator reset: a new password that works, must be changed,
#     and the old one put back afterwards
from kingmaker.access import auth, permissions  # noqa: E402
from kingmaker.storage.archive import Archive  # noqa: E402
probe_archive = Archive(config.DB_FILE)
admins = [u for u in probe_archive.list_users() if u["role"] == permissions.ADMIN and u["active"]]
before = dict(admins[0]) if admins else None
probe_archive.close()
username, password = core.reset_admin_password()
check = Archive(config.DB_FILE)
try:
    row = check.user_by_name(username)
    results.append(("the reset names an administrator", row is not None and row["role"] == permissions.ADMIN))
    results.append(("the new password is accepted",
                    auth.verify(check, username, password) is not None))
    results.append(("and must be changed at the next login", row is not None and int(row["must_change_pw"]) == 1))
    if before is not None:
        check.update_user(before["id"], pw_hash=before["pw_hash"], salt=before["salt"],
                          iterations=before["iterations"], must_change_pw=before["must_change_pw"])
finally:
    check.close()

# 11. loading a save from the launcher: looked at, then copied in, the
#     previous one kept; the scene is the same game afterwards
import shutil  # noqa: E402
probe_archive = Archive(config.DB_FILE)
carried = probe_archive.backup_to(folder / "from-the-old-pc.db")
probe_archive.close()
info = core.inspect_save(carried)
results.append(("the carried save is recognised", info["version"] > 0 and info["users"] > 0))
try:
    core.inspect_save(path)          # the broken launcher.json from section 2
    results.append(("a file that is not a save is refused", False))
except ValueError as error:
    results.append(("a file that is not a save is refused", error.args[0] == "main.not_sqlite"))
kept = core.load_save(carried)
results.append(("the previous save is kept next to itself",
                kept.exists() and kept.name.startswith("kingmaker.db.before-restore-")))
check = Archive(config.DB_FILE)
try:
    results.append(("the loaded game is the carried one",
                    check.count_users() == info["users"] and carried.exists()))
finally:
    check.close()
kept.unlink(missing_ok=True)

shutil.rmtree(folder, ignore_errors=True)
for name, ok in results:
    print(f" {'ok' if ok else 'NO'}  {name}")
print(f"{sum(1 for _n, ok in results if ok)}/{len(results)} passed")
