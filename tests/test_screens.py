# -*- coding: utf-8 -*-
"""Every launcher window on small screens: nothing out of reach.

The set-up wizards once asked for more height than a laptop has, and their
buttons went below the bottom of the screen, where nothing could press them.
Here every window of the launcher — the main one in its tallest state, the
settings, the versions, the password, the connection, every step of both
wizards — is opened on work areas from a small laptop's to a desktop's, in
both languages, and each button, field and box must be either in view or
brought into view by scrolling, and the window must sit inside the area.

Needs a display: without one (a server, a container) it says so and passes.
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ["KINGMAKER_DATA_DIR"] = tempfile.mkdtemp(prefix="km-screens-")

import tkinter as tk  # noqa: E402
from tkinter import ttk  # noqa: E402

from kingmaker.launcher import core, screen, sync, window, wizard  # noqa: E402
from kingmaker.locale import i18n  # noqa: E402

results = []
# (width, height) of the work area: 1366 × 768 at 125 %, 1920 × 1080 at
# 150 %, a desktop at 125 % — each less its taskbar.
AREAS = [(1024, 560), (1280, 680), (1536, 816)]
INTERACTIVE = {"TButton", "TCheckbutton", "TRadiobutton", "TEntry", "TCombobox", "TSpinbox",
               "Listbox", "Text"}


def shown(widget, top) -> bool:
    """Laid out, and every container up to the window laid out too."""
    while widget is not top:
        if not widget.winfo_manager():
            return False
        widget = widget.master
    return True


def controls(top) -> list:
    found, stack = [], [top]
    while stack:
        widget = stack.pop()
        if widget.winfo_class() in INTERACTIVE and shown(widget, top):
            found.append(widget)
        stack.extend(widget.winfo_children())
    return found


def unreachable(top) -> list[str]:
    """The controls of `top` that cannot be brought into view."""
    top.update()
    lost = []
    for widget in controls(top):
        holder = screen._holder(widget)
        if holder is not None:
            holder.see(widget)
            top.update()
        y = widget.winfo_rooty() - top.winfo_rooty()
        x = widget.winfo_rootx() - top.winfo_rootx()
        inside = (0 <= y and y + widget.winfo_height() <= top.winfo_height()
                  and 0 <= x and x + min(widget.winfo_width(), 40) <= top.winfo_width())
        if holder is not None:
            view = holder.canvas.winfo_rooty()
            inside = inside and view <= widget.winfo_rooty() \
                and widget.winfo_rooty() + widget.winfo_height() <= view + holder.canvas.winfo_height()
        if not inside:
            text = ""
            try:
                text = widget.cget("text")
            except tk.TclError:
                pass
            lost.append(f"{widget.winfo_class()} {text!r}".strip())
    return lost


def outside(top, area) -> bool:
    """True when the window, frame included, runs past the work area."""
    top.update()
    extra_w, extra_h = screen.decor(top)
    return (top.winfo_x() < 0 or top.winfo_y() < 0
            or top.winfo_x() + top.winfo_width() + extra_w > area[0]
            or top.winfo_y() + top.winfo_height() + extra_h > area[1])


def check(label, top, area) -> None:
    lost = unreachable(top)
    results.append((f"{label}: every control in reach{'' if not lost else ' — lost: ' + ', '.join(lost)}",
                    not lost))
    results.append((f"{label}: inside the work area", not outside(top, area)))


def tallest_launcher(root, lang) -> window.Launcher:
    """The main window with everything it can show at once."""
    settings = core.Settings(mode="online", language=lang)
    settings.cloud = {"app_key": "k", "refresh_token": "r", "account_id": "a", "account_name": "Marco",
                      "app_name": "x", "table": "Tavolo", "role": "admin", "username": "admin"}
    app = window.Launcher(root, settings)
    app.other = sync.HostRecord(host_id="abc", host_name="Someone-PC", epoch=3, seq=4,
                                since="2026-09-27T10:00:00Z", address="https://on-air.nicegui.io/x")
    app.other.held = lambda: True
    app.refresh_cloud()
    app.show_release(core.Release(version="9.9.9", page="https://example.org"))
    app.links = {"local": "http://127.0.0.1:8080", "lan": "http://192.168.1.10:8080",
                 "air": "https://on-air.nicegui.io/device-0/abcdef"}
    app.rebuild_links()
    app.set_status(i18n.t("launcher.status.port_moved", wanted=8080, port=8081), "busy")
    app.show_log.set(True)
    app.toggle_log()
    return app


try:
    probe = tk.Tk()
    probe.destroy()
    display = True
except tk.TclError:
    display = False

if not display:
    results.append(("no display here: the windows are not measured", True))
else:
    real_work_area = screen.work_area
    for width, height in AREAS:
        area = (width, height)
        screen.work_area = lambda _win, w=width, h=height: (0, 0, w, h)
        for lang in ("en", "it"):
            i18n.language_resolver = lambda lang=lang: lang
            tag = f"{width}×{height} {lang}"
            root = tk.Tk()
            try:
                app = tallest_launcher(root, lang)
                screen.present(root)
                check(f"{tag} main window", root, area)

                app.open_settings()
                check(f"{tag} settings", app.settings_window, area)
                app.settings_window.destroy()

                # The host's window: paired with someone hosting, and not
                # paired yet, when Start waits for the pairing.
                host = core.Settings(mode="online", language=lang, role="host",
                                     cloud=dict(app.settings.cloud, role="host"))
                for paired in (True, False):
                    host_root = tk.Tk()
                    try:
                        if not paired:
                            host.cloud = {}
                        guest = window.Launcher(host_root, host)
                        guest.other = app.other
                        guest.refresh_cloud()
                        guest.show_log.set(True)
                        guest.toggle_log()
                        screen.present(host_root)
                        label = f"{tag} host window ({'paired' if paired else 'not paired'})"
                        check(label, host_root, area)
                        results.append((f"{label}: nothing of the administrator's",
                                        not hasattr(guest, "where") and guest.load_button is None))
                        results.append((f"{label}: Start {'ready' if paired else 'waits for the pairing'}",
                                        str(guest.start_button.cget("state")) == ("normal" if paired
                                                                                    else "disabled")))
                        if paired:
                            guest.open_settings()
                            check(f"{tag} host settings", guest.settings_window, area)
                            guest.settings_window.destroy()
                    finally:
                        for pending in host_root.tk.call("after", "info"):
                            host_root.after_cancel(pending)
                        host_root.destroy()

                # The administrator without a table: no Table box on this
                # computer only, where nobody else reaches the game.
                alone_root = tk.Tk()
                try:
                    alone = window.Launcher(alone_root, core.Settings(mode="local", language=lang, role="admin"))
                    boxes = []
                    for mode in ("local", "lan", "online", "local"):
                        alone.mode_var.set(mode)
                        alone.mode_changed()
                        boxes.append(bool(alone.cloud.winfo_manager()))
                    results.append((f"{tag} the Table box only on the network or online",
                                    boxes == [False, True, True, False]))
                finally:
                    alone_root.update()
                    for pending in alone_root.tk.call("after", "info"):
                        alone_root.after_cancel(pending)
                    alone_root.destroy()

                # The administrator with a table, on this computer only: the
                # box stays, but nobody else reaches the game for a pairing
                # code, so a line says why instead of the pairing buttons;
                # the keys and Forget stay. The address rows of the last run
                # follow the place chosen while the game is stopped.
                local_root = tk.Tk()
                try:
                    mine = window.Launcher(local_root, core.Settings(mode="local", language=lang,
                                                                     check_updates=False,
                                                                     cloud=dict(app.settings.cloud)))
                    for pending in local_root.tk.call("after", "info"):
                        local_root.after_cancel(pending)   # no watch of who hosts: no network here
                    mine.links = {"local": "http://127.0.0.1:8080", "lan": "http://192.168.1.10:8080",
                                  "air": "https://on-air.nicegui.io/device-0/abcdef"}

                    def box_texts() -> set[str]:
                        found, stack = set(), [mine.cloud_row]
                        while stack:
                            widget = stack.pop()
                            try:
                                found.add(str(widget.cget("text")))
                            except tk.TclError:
                                pass
                            stack.extend(widget.winfo_children())
                        return found

                    def rows() -> list[str]:
                        return [str(row.winfo_children()[0].cget("text"))
                                for row in mine.links_frame.winfo_children()]

                    pairing = {i18n.t("launcher.cloud.pair_launcher"), i18n.t("launcher.cloud.launchers")}
                    keys = {i18n.t("launcher.cloud.rotate"), i18n.t("launcher.cloud.cut_off"),
                            i18n.t("launcher.cloud.forget")}
                    note = i18n.t("launcher.cloud.pair_local")
                    seen = {}
                    for mode in ("local", "lan", "online", "local"):
                        mine.mode_var.set(mode)
                        mine.mode_changed()
                        seen.setdefault(mode, []).append((bool(mine.cloud.winfo_manager()), box_texts(), rows()))
                    shown_box, texts, links = seen["local"][-1]
                    results.append((f"{tag} on this computer only, a table keeps its box", shown_box))
                    results.append((f"{tag} on this computer only, no pairing buttons", not pairing & texts))
                    results.append((f"{tag} on this computer only, a line says why", note in texts))
                    results.append((f"{tag} on this computer only, the keys and Forget stay", keys <= texts))
                    results.append((f"{tag} the box went back to this computer only with the radio",
                                    seen["local"][0][1] == texts))
                    for mode in ("lan", "online"):
                        _shown, texts_there, _links = seen[mode][0]
                        results.append((f"{tag} {mode}: the pairing buttons, and no line",
                                        pairing | keys <= texts_there and note not in texts_there))
                    link = {kind: i18n.t(f"launcher.link.{kind}") for kind in ("local", "lan", "air")}
                    results.append((f"{tag} stopped, on this computer only: one address row",
                                    links == [link["local"]]))
                    results.append((f"{tag} stopped, on the network: no Online row",
                                    seen["lan"][0][2] == [link["local"], link["lan"]]))
                    results.append((f"{tag} stopped, online: every row of the last run",
                                    seen["online"][0][2] == [link["local"], link["lan"], link["air"]]))

                    # Hosting on this computer only, the cloud keeping the
                    # copies: still no code to make.
                    mine.record = sync.HostRecord(host_id="me", host_name="This-PC", epoch=4, seq=1,
                                                  since="2026-10-10T10:00:00Z")
                    mine.refresh_cloud()
                    texts = box_texts()
                    results.append((f"{tag} hosting on this computer only: a line, no pairing button",
                                    note in texts and i18n.t("launcher.cloud.pair_launcher") not in texts))
                    told = []
                    real_showinfo = window.messagebox.showinfo
                    window.messagebox.showinfo = lambda _title, text, **_k: told.append(text)
                    try:
                        mine.make_pairing_code()
                    finally:
                        window.messagebox.showinfo = real_showinfo
                    results.append((f"{tag} no pairing code on this computer only, and it says why",
                                    told == [i18n.t("launcher.cloud.pair_needs_network")]))
                    mine.record = None

                    # The seat found on another PC. A launcher that never held
                    # it is told and left whole (Start asks); one that held it
                    # steps down: access cancelled, the table forgotten.
                    mine.settings.identity()
                    other = sync.TableRecord(format=2, name="T", admin_id="h2", admin_name="Other-PC",
                                             admin_key="f" * 64, admin_since="2026-10-10T10:00:00Z")
                    revoked = []
                    mine.cloud_client = lambda: type("Client", (), {"revoke": lambda _s: revoked.append(1)})()
                    told = []
                    window.messagebox.showinfo = lambda _title, text, **_k: told.append(text)
                    try:
                        mine.settings.cloud["seated"] = False
                        mine.table = other
                        untouched = not mine.check_seat(other)
                        mine.refresh_cloud()
                        elsewhere = i18n.t("launcher.cloud.seat_elsewhere", name="Other-PC", date="2026-10-10")
                        results.append((f"{tag} another seat, never held here: nothing lost, the box says Start asks",
                                        untouched and mine.settings.cloud_ready and not revoked and not told
                                        and elsewhere in box_texts()))
                        mine.settings.cloud["seated"] = True
                        deposed = mine.check_seat(other)
                        results.append((f"{tag} another seat, held here before: stepped down, access cancelled",
                                        deposed and not mine.settings.cloud and revoked == [1]
                                        and told == [i18n.t("launcher.cloud.seat_taken", name="Other-PC",
                                                            date="2026-10-10")]))
                    finally:
                        window.messagebox.showinfo = real_showinfo
                        mine.table = None
                finally:
                    for pending in local_root.tk.call("after", "info"):
                        local_root.after_cancel(pending)
                    local_root.update()             # Tk's own idle work, before the window goes
                    for pending in local_root.tk.call("after", "info"):
                        local_root.after_cancel(pending)
                    local_root.destroy()

                before = set(root.winfo_children())
                app.open_versions()
                versions = next(w for w in root.winfo_children()
                                if w not in before and isinstance(w, tk.Toplevel))
                check(f"{tag} versions", versions, area)
                versions.destroy()

                before = set(root.winfo_children())
                app.show_password("admin", "abcd-efgh-ijkl-mnop")
                dialog = next(w for w in root.winfo_children()
                              if w not in before and isinstance(w, tk.Toplevel))
                check(f"{tag} password", dialog, area)
                dialog.destroy()

                connect = wizard.PairDialog(root, app.settings, lambda: None)
                connect.failed(i18n.t("launcher.pair.unreachable",
                                      error="<urlopen error [WinError 10061] the machine refused it>"))
                check(f"{tag} pair", connect.win, area)
                connect.win.destroy()

                for cls, steps in ((wizard.SetupWizard, wizard.STEPS), (wizard.AirWizard, wizard.AIR_STEPS)):
                    guide = cls(root, app.settings, lambda: None)
                    if cls is wizard.AirWizard:
                        guide.entered = "renew"          # the renewal step's extra button
                    lost, out, pictures = [], [], 0
                    for i, name in enumerate(steps[:-1]):
                        guide.step = i
                        guide.show()
                        if name == "code":
                            guide.feedback.config(text=i18n.t("launcher.wizard.authorise.failed",
                                                              error="HTTP Error 400: Bad Request"))
                        lost += [f"{name}: {w}" for w in unreachable(guide.win)]
                        if outside(guide.win, area):
                            out.append(name)
                        pictures += guide.image is not None
                    results.append((f"{tag} {cls.__name__}: every control of every step in reach"
                                    f"{'' if not lost else ' — lost: ' + ', '.join(lost)}", not lost))
                    results.append((f"{tag} {cls.__name__}: every step inside the work area"
                                    f"{'' if not out else ' — out: ' + ', '.join(out)}", not out))
                    results.append((f"{tag} {cls.__name__}: the pictures are still there, shrunk",
                                    pictures >= len(steps) - 2))
                    if cls is wizard.SetupWizard:
                        # The road for an app made before: its own page, then
                        # the key, as `use_existing` takes it (without the
                        # browser it opens).
                        guide.step = 0
                        guide.existing = True
                        guide.repage_cloud()
                        guide.go_to("cloud/existing")
                        lost = unreachable(guide.win)
                        results.append((f"{tag} SetupWizard, an existing app: its page in reach, with "
                                        f"its picture{'' if not lost else ' — lost: ' + ', '.join(lost)}",
                                        not lost and not outside(guide.win, area) and guide.image is not None))
                        guide.go_next()
                        results.append((f"{tag} SetupWizard, an existing app: Next checks the permissions",
                                        guide.page == "cloud/permissions" and guide.existing))
                        guide.go_back()
                        guide.go_back()
                        guide.go_next()
                        results.append((f"{tag} SetupWizard, back to a new app: Next goes to the permissions",
                                        guide.page == "cloud/permissions" and not guide.existing))
                    guide.win.destroy()

                # The welcome, along its longest road (the administrator,
                # online, both guides) and the host's: every page it can
                # show, with the Dropbox code page's failure text on.
                for who, longest in (("admin", True), ("host", False)):
                    # A fresh launcher: the one the welcome is for. (The
                    # tallest launcher's settings hold a table, and a table
                    # already set up skips the address and the others.)
                    welcome = wizard.WelcomeWizard(root, core.Settings(), lambda: None)
                    welcome.who.set(who)
                    welcome.mode.set("online")
                    welcome.air_way.set("guide")
                    welcome.cloud_way.set("cloud")
                    welcome.pages = welcome.plan()
                    lost, out = [], []
                    for i, name in enumerate(welcome.pages):
                        welcome.step = i
                        welcome.show()
                        if name == "cloud/code":
                            welcome.feedback.config(text=i18n.t("launcher.wizard.authorise.failed",
                                                                error="HTTP Error 400: Bad Request"))
                        if name == "welcome/pair":
                            welcome.feedback.config(text=i18n.t("launcher.pair.refused"))
                        lost += [f"{name}: {w}" for w in unreachable(welcome.win)]
                        if outside(welcome.win, area):
                            out.append(name)
                    results.append((f"{tag} welcome ({who}): the road has the pages it should",
                                    ("air/token" in welcome.pages and "cloud/code" in welcome.pages) == longest
                                    and ("welcome/pair" in welcome.pages) != longest))
                    results.append((f"{tag} welcome ({who}): every control of every page in reach"
                                    f"{'' if not lost else ' — lost: ' + ', '.join(lost)}", not lost))
                    results.append((f"{tag} welcome ({who}): every page inside the work area"
                                    f"{'' if not out else ' — out: ' + ', '.join(out)}", not out))
                    welcome.win.destroy()
            finally:
                # The launcher's own timers (the poll, the watch of who
                # hosts) would fire into a destroyed window otherwise.
                for pending in root.tk.call("after", "info"):
                    root.after_cancel(pending)
                root.destroy()
    screen.work_area = real_work_area

for name, ok in results:
    print(f" {'ok' if ok else 'NO'}  {name}")
print(f"{sum(1 for _n, ok in results if ok)}/{len(results)} passed")
