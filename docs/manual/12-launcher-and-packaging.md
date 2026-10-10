# 12. The launcher and the installers

The app stays a web app in the browser. The **launcher** is the window that starts and stops
the server for whoever has no terminal; the **installers** are the same program frozen with
Python inside, so nothing has to be installed first. Nothing in this chapter is needed to run
from source: `python launch.py` is unchanged, and `packaging/` is imported by nothing in
`kingmaker/`.

![The launcher](img/screenshots/launcher.jpg)

## One program, two modes

The installed executable — `Kingmaker Kingdom Manager.exe` on Windows,
`kingmaker-kingdom-manager` on Linux — is `packaging/frozen_entry.py` frozen by PyInstaller.
It calls `kingmaker.cli.main(frozen=True)`:

- **no arguments** → the launcher window (`kingmaker.launcher.window.run`);
- **`--serve [--lan] [--port N] [--online [TOKEN]] [--no-browser]`** → the server, exactly
  what `python launch.py` does.

`cli.py` is the one parser for both: `launch.py` is now four lines that call `cli.main()`, where
the server is the default and `--launcher` opens the window from source (that is how the window
is developed and tested without freezing).

## The launcher (`kingmaker/launcher/`)

`core.py` is everything that can be tested without a screen; `window.py` is the tkinter around
it (standard library, no dependency, bilingual through the `launcher.*` keys of the catalogs).
Nothing in the package imports `kingmaker.state` or the interface: the launcher is a separate
process from the game, and can touch the save only through the server it starts — with one
exception, the administrator reset below.

**The child process.** `core.Server.start` runs `[sys.executable, "--serve", ...]` when frozen,
`[sys.executable, "launch.py", "--serve", ...]` from source (`core.server_command`), with
`--no-browser` — the launcher opens the browser itself, when the server says it is ready — and
reads its stdout from a thread. The token and the shutdown secret travel in the environment
(`core.server_environment`), never on the command line.

**What the server says.** `main.announce(kind, value)` prints `KM <kind> <value>` lines,
flushed, on stdout: `KM ready http://127.0.0.1:8080` from an `app.on_startup` hook,
`KM lan http://192.168.1.7:8080` per address when listening on `0.0.0.0` (`main.lan_addresses`,
from `ifaddr` like NiceGUI's own welcome line, without loopback and link-local),
`KM admin-password …` on the first start next to the human block. The On Air address is the one
line NiceGUI itself prints, `NiceGUI is on air at …`. `core.parse_line` turns them into events;
everything else is log. These lines are the contract between the two processes; the human
text around them is free to change.

**Stopping.** A signal cannot reach a child without a console, and the installed app has
none. So `main.launcher_route(secret)` registers `POST /_launcher/shutdown` when the
`KINGMAKER_LAUNCHER_SECRET` variable is set: the caller must be `127.0.0.1` and carry the
secret in `X-Launcher-Secret`, anything else is a 404, and the route does not exist at all
without the variable. It calls NiceGUI's `app.shutdown()`, so `theme._switch_off` writes the
last save. `core.Server.stop` asks, waits `STOP_PATIENCE` seconds, then kills. The path is in
`login.OPEN_PAGES` because the access middleware would otherwise redirect it to `/login`.
The other routes of the same family — status, snapshot, synced, whoami, pairing, pair — are
chapter 13.

**Ports.** Before starting, `core.free_port` binds the chosen port to see whether it is free
and takes the next one otherwise; the status line says so. A server that dies on its own is
reported with its exit code and the log pane opens.

**Small screens (`screen.py`).** A Tk window takes the size its content asks for, and Windows
lets it run past the bottom of the screen. The main window asks for about 850 px with the log
open and the wizards did too, while a 1366 × 768 laptop has about 720 once the taskbar is
counted (and 560 at 125 %). The lower part — the log, the links, the wizards' *Next* — went
where nothing could reach it. So every launcher window is built the same way: the content in
a `screen.Scrolled` (a canvas that is exactly as tall as its content and grows a scroll bar
only when the window is shorter); the buttons that close a dialog outside it, packed first at
the bottom so pack takes room from the content and never from them; and `screen.settle`,
which caps the window at the work area of its monitor (`MonitorFromWindow` on Windows, the
screen less a panel elsewhere) and moves it inside. A `Scrolled` calls `settle` whenever its
content changes size. A dialog is built withdrawn and shown by `screen.present`, because Tk's
first layout pass would otherwise map it wherever the system puts it. The main window keeps
the log below the scrolled part, where the room a taller window gives goes. The wizards'
pictures are shrunk first (`wizard.fit`, by whole ratios, down to a quarter) to the room
`screen.room` says is left, so scrolling there is a last resort. The wheel scrolls the
`Scrolled` under the pointer, except over widgets that scroll themselves, and Tab onto a
control out of view scrolls it into view. `tests/test_screens.py` opens every window in its
tallest state on work areas from 1024 × 560 to 1536 × 816, in both languages, and requires
every control to be in view or scrollable into view and the window to sit inside the area.

**One at a time.** `core.SingleInstance` locks `launcher.lock` in the game folder
(`msvcrt.locking` / `fcntl.flock`); a second launcher on the same folder says so and quits,
because two servers on one database is the one thing the README forbids.

**Settings.** `launcher.json` in the game folder (`core.Settings`): mode, port, language, On
Air token, whether to open the browser, whether the firewall notice was shown, the cloud
credential and this launcher's identity. Written whole through a `.tmp` sibling moved into
place, owner-only on POSIX. The two secrets — the refresh token inside `cloud`, and `token`,
which is only the launcher's own for whoever plays online **without** the cloud (with the
cloud the token is in the table's folder, `table.json`, chapter 13, read at every Start) —
are plain in memory and nowhere else: `Settings.save` moves them into `vault` (`launcher/vault.py`:
on Windows a DPAPI blob in the scope of the current user, through `ctypes`; elsewhere an
owner-only file under `~/.local/share/kingmaker-kingdom-manager/secrets/`, or `KINGMAKER_VAULT_DIR`,
which the suite points at the scene) and writes the file without them; `Settings.load` brings
them back, or records `vault_error` when the blob was made by another user or on another PC,
and the Table box asks to connect again. A file from before 1.4.0, with the secrets in clear,
is migrated by its first save. `tests/test_vault.py` covers both schemes.

**Updates.** `core.latest_release` asks the GitHub API for the latest release, in a thread, with
a five-second timeout and silence on failure; `core.is_newer` compares version tuples. On
Windows the launcher downloads the `-Setup.exe` asset to `%TEMP%` and starts it, then quits; on
Linux it opens the release page. *Settings → Versions on GitHub…* (`window.open_versions`,
`core.list_releases`: the releases API, drafts skipped, sorted by version tuple) installs any
release the same way, an older one after a warning.

**A save from elsewhere.** *Load a save file…* (`window.load_save`, server stopped) goes
through `core.inspect_save` — `bundle.inspect`, the same check as the Save tab's upload, for
the zip or a bare database — a confirmation with the kingdom's name, the accounts and the
images, then `core.load_save`, which opens the database and calls `bundle.restore`: the
previous file kept as `kingmaker.db.before-restore-<date>.bak`, the given one copied in, the
images unpacked over `assets/`. On the web side the same control is `main.save_upload`, shown
in the Save tab and on the creation page.

**The cloud.** The *Cloud* box, the claim before Start, the hoster thread and the two
dialogs are chapter 13; the window's part is `claim_then_start`, `begin_hosting`,
`handle_cloud`, `handle_taken` and `refresh_cloud`, all driven through `Launcher.post`.
On this computer only (`Launcher.local_only`) a table keeps its box, but `refresh_cloud` puts
a muted line where *Pair a launcher…* and *Hosts of the table…* would be and
`make_pairing_code` refuses, because the game answers at 127.0.0.1 where no other launcher
reaches it for the code; `mode_changed` redraws the box and the address rows, which while the
game is stopped list only what the chosen place gives (`core.links_for_mode`).

**The administrator reset.** `core.reset_admin_password` opens the database directly (server
stopped), gives the first active administrator a new random password with `must_change_pw`,
and returns it for the dialog. Whoever can run the launcher owns the folder with the database,
so nothing is protected from them anyway; this is the recovery for a lost first-start password.

## Where the game lives

`config._root()` decides: from source, the repository (the parent of the package); frozen,
the folder of the executable. Everything else — `saves/`, `assets/`, `.storage_secret`, the
NiceGUI sessions — follows, so the installed folder has the same shape as the repository, and
the environment variables still override. `tests/test_launcher.py` pins the source defaults.

## Building (`packaging/`)

```bash
python -m pip install -r packaging/requirements-build.txt    # PyInstaller and Pillow
python packaging/build.py                                    # folder, installer, smoke test
```

- `kingmaker.spec` — one folder (`dist/<name>/` with `_internal/`), windowed, the whole
  `nicegui` package as data (what `nicegui-pack` does), the app's `rules/data`, `locale/lang`
  and `ui/static` with their package layout kept, the licence files, the icon.
- `third_party.py` — writes `THIRD_PARTY_LICENSES.txt` into the built folder, so the
  installer and the tarball ship it next to the program: every distribution of the build
  environment (build tools excluded) with the licence files its wheel carries, read through
  `importlib.metadata`; PyInstaller's bootloader licence; Python's and Tcl/Tk's from the
  interpreter; the browser libraries and fonts NiceGUI serves from its `static/`, listed by
  hand with the MIT or Apache text; and the three typefaces with their OFL files from
  `ui/static/fonts/`. `python packaging/third_party.py` alone writes it at the repository
  root (ignored by git) for a source install.
- `build.py` — runs PyInstaller, then `third_party.py`, then the **smoke test**: starts the built program with
  `--serve` on a temporary game folder, waits for `KM ready`, fetches `/login`, asks it to
  stop through the shutdown route; a missing hidden import shows up here, not at a user's.
  Then Inno Setup on Windows (`kingmaker.iss`, found in its usual folders), or the tarball with
  `linux/kingmaker.desktop` and `linux/INSTALL.txt`. In CI it also refuses a tag that does not
  match `kingmaker.__version__`. The `.desktop` file's `StartupWMClass=Kingmaker` matches
  `core.WM_CLASS`, the class every launcher window is made with (`tk.Tk(className=...)`,
  `tk.Toplevel(class_=...)`): without it Linux sees Tk's own "Tk" and "Toplevel", and GNOME
  groups and labels the windows under those names.
- `kingmaker.iss` — per-user install, no administrator rights, the destination page shown with
  `%LOCALAPPDATA%\Programs\Kingmaker Kingdom Manager` as default; `[InstallDelete]` removes
  `_internal` before an update and never touches `saves\` or `assets\`; the uninstaller removes
  the installers the launcher downloaded to `%TEMP%` and asks
  whether to delete the game too. English and Italian.
- `icon/make_icon.py` — cuts `kingmaker.ico` (16 to 256 px, rounded corners) and
  `kingmaker.png` out of `icon/party.png`, the crest of the party that founded the kingdom at
  the author's table; the outputs are committed, so a build never needs Pillow for this.
- Pillow is bundled, so "read the water from the image" works in the installed app.

## The release workflow (`.github/workflows/release.yml`)

On a `v*` tag: a Windows runner and an Ubuntu 22.04 runner install, build and smoke-test, and
a third job attaches the two files to the release of that tag — created **as a draft** if it
does not exist, so the owner pastes the changelog section and publishes. "Run workflow" on the
Actions page builds without a tag, leaving the files in the run's artifacts. The Linux build is
made on 22.04 (glibc 2.35), so the tarball needs Ubuntu 22.04 or newer; GitHub no longer offers
older runners. `ci.yml` runs the suite and the checkers on every push.

The unsigned executable shows Windows SmartScreen's "Windows protected your PC" on a machine
that has never seen the file; the README explains the *More info → Run anyway* click. A
signing certificate would remove it and is a cost, not a code change.

**The owner's signature (2.0.0).** What the launcher checks is another signature, the owner's
own: after the draft is built, `packaging/sign_release.py sign <version>` downloads the two
installers with `gh`, writes `SHA256SUMS` (one `hash  name` line each) and `SHA256SUMS.sig`
(the Ed25519 signature of that file, hex, by the offline seed `new-key` made, whose public
half is `launcher/keys.py: RELEASE_KEYS`) and uploads both to the release. The key never
goes to GitHub: a compromised account can publish a release, not sign one. On the launcher's
side `core.verify_download` runs after the download and before `run_update`: the two files
are fetched, the signature checked under any shipped key, the installer's hash compared with
its line; a failure deletes the file and says so (`window.update_rejected`), and a release
without the two files is "unsigned": marked so in the versions window (`Release.signed`) and
run only after a confirmation. `tests/test_updates.py` covers every refusal.

## Testing

`tests/test_launcher.py` (in the suite): versions, the settings round-trip and its fallbacks,
the parsed lines, the release as GitHub describes it, the busy port, the lock, the child's
command line and environment, the routing of `cli.main` in both modes, the frozen root and the
pinned source defaults, the administrator reset (put back afterwards). The window is exercised
by hand: `KINGMAKER_DATA_DIR=<a copy> python launch.py --launcher`.
