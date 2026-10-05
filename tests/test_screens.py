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
                 "online": "https://on-air.nicegui.io/device-0/abcdef"}
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

                connect = wizard.ConnectDialog(root, app.settings, lambda: None)
                connect.failed(i18n.t("launcher.connect.unreachable",
                                      error="<urlopen error [WinError 10061] the machine refused it>"))
                check(f"{tag} connect", connect.win, area)
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
                    guide.win.destroy()
            finally:
                root.destroy()
    screen.work_area = real_work_area

for name, ok in results:
    print(f" {'ok' if ok else 'NO'}  {name}")
print(f"{sum(1 for _n, ok in results if ok)}/{len(results)} passed")
