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
import shutil
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ["KINGMAKER_DATA_DIR"] = tempfile.mkdtemp(prefix="km-screens-")

import tkinter as tk  # noqa: E402
from tkinter import ttk  # noqa: E402

from kingmaker.access import ed25519  # noqa: E402
from kingmaker.launcher import core, screen, sync, window, wizard  # noqa: E402

# No window of this test may ask GitHub for updates: every Settings below says
# check_updates=False, and this stub catches the one that forgets. The suite
# once ran both laptops dry of the API's hourly quota, and the installed
# launcher showed no update.
asked_github: list = []
core.latest_release = lambda *_a, **_k: asked_github.append(1)     # type: ignore[assignment]
core.check_latest = lambda *_a, **_k: (asked_github.append(1), (None, True))[1]  # type: ignore[assignment]
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
    settings = core.Settings(mode="online", language=lang, check_updates=False)
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

                # GitHub out of reach: the muted line and «Check now» under
                # the version; gone once GitHub answers (2.3.0).
                if area == AREAS[0] and lang == "en":
                    app.after_check(None, False)
                    root.update()
                    failed = (app.check_line.winfo_manager() == "pack"
                              and "Could not check for updates" in app.check_label.cget("text"))
                    app.after_check(None, True)
                    root.update()
                    results.append(("could not check for updates: the line and Check now show, "
                                    "and go once GitHub answers", failed and app.check_line.winfo_manager() == ""))

                app.open_settings()
                check(f"{tag} settings", app.settings_window, area)
                app.settings_window.destroy()

                # The host's window: paired with someone hosting, and not
                # paired yet, when Start waits for the pairing.
                host = core.Settings(mode="online", language=lang, role="host", check_updates=False,
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
                            host_root.tk.call("after", "cancel", pending)
                        host_root.destroy()

                # The administrator without a table: no Table box on this
                # computer only, where nobody else reaches the game.
                alone_root = tk.Tk()
                try:
                    alone = window.Launcher(alone_root, core.Settings(mode="local", language=lang, role="admin",
                                                                      check_updates=False))
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
                        alone_root.tk.call("after", "cancel", pending)
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
                        local_root.tk.call("after", "cancel", pending)   # no watch of who hosts: no network here
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
                    keys = {i18n.t("launcher.cloud.forget")}
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
                    results.append((f"{tag} on this computer only, Forget stays", keys <= texts))
                    results.append((f"{tag} nothing of 'when someone leaves' in the box any more (2.2.0)",
                                    i18n.t("launcher.cloud.cut_off") not in texts))
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
                    # The game's "KM paired" line gives the waiting key to the newcomer at once.
                    mine.settings.pending_key = {"token": "rt-new", "since": "2026-10-12T12:00:00Z"}
                    mine.settings.save = lambda *_a, **_k: None
                    mine.handle_line("KM paired h-new New-PC")
                    results.append((f"{tag} the key waiting for a code goes under the newcomer's id when "
                                    "the game says the code was spent (2.2.0)",
                                    mine.settings.host_keys.get("h-new") == "rt-new"
                                    and mine.settings.pending_key == {}))
                    # Stop's last upload runs off the window's thread (2.2.0): the
                    # window answers meanwhile, and finishes once the hoster is done.
                    class SlowHoster:
                        def __init__(self) -> None:
                            self.calls: list[bool] = []
                            self.release = threading.Event()

                        def stop(self, final: bool = True) -> None:
                            self.release.wait(5)
                            self.calls.append(final)

                    slow = SlowHoster()
                    mine.hoster = slow
                    mine.record = sync.HostRecord(host_id="me", host_name="This-PC", epoch=4, seq=1)
                    mine.stop()
                    answering = (mine.stop_thread is not None and mine.stop_thread.is_alive()
                                 and slow.calls == [] and mine.hoster is None and mine.record is None
                                 and mine.working_bar.winfo_manager() == "pack")
                    mine.handle_cloud("uploaded", "save-e1-s1.zip")     # the last copy's report
                    answering = (answering and mine.working_bar.winfo_manager() == "pack"
                                 and mine.status.cget("text") == i18n.t("launcher.status.stopping"))
                    slow.release.set()
                    mine.stop_thread.join(5)
                    mine.poll()
                    results.append((f"{tag} Stop uploads the last copy in a thread, the window answering, "
                                    "and finishes when it is done",
                                    answering and slow.calls == [True] and mine.stop_thread is None
                                    and mine.working_bar.winfo_manager() == ""))
                    # The working bar follows the busy statuses (2.2.0).
                    mine.set_status(i18n.t("launcher.cloud.claiming"), "busy")
                    shown_busy = mine.working_bar.winfo_manager() == "pack"
                    mine.set_status(i18n.t("launcher.cloud.upload_failed", error="x"), "busy", working=False)
                    hidden_failed = mine.working_bar.winfo_manager() == ""
                    mine.set_status(i18n.t("launcher.cloud.pulling"), "busy")
                    mine.set_status(i18n.t("launcher.status.stopped"), "quiet")
                    hidden_done = mine.working_bar.winfo_manager() == ""
                    results.append((f"{tag} the working bar shows while the launcher works and goes when it is done",
                                    shown_busy and hidden_failed and hidden_done))
                    mine.record = None

                    # The seat found on another PC. A launcher that never held
                    # it is told and left whole (Start asks); one that held it
                    # is asked once, with the other launcher's key, and steps
                    # down only on a yes; a file naming another seat without
                    # that seat's signature moves nothing (2.2.0).
                    mine.settings.identity()
                    seed_other = ed25519.new_seed()
                    key_other = ed25519.public_key(seed_other).hex()
                    other = sync.TableRecord(format=2, name="T", admin_id="h2", admin_name="Other-PC",
                                             admin_key=key_other, admin_since="2026-10-10T10:00:00Z")
                    other.sign(seed_other)
                    forged = sync.TableRecord(format=2, name="T", admin_id="h3", admin_name="Forger",
                                              admin_key="f" * 64, admin_since="2026-10-10T11:00:00Z")
                    revoked = []
                    mine.cloud_client = lambda: type("Client", (), {"revoke": lambda _s: revoked.append(1)})()
                    told, asked = [], []
                    answer = {"yes": False}
                    window.messagebox.showinfo = lambda _title, text, **_k: told.append(text)
                    real_askyesno = window.messagebox.askyesno
                    window.messagebox.askyesno = lambda _title, text, **_k: (asked.append(text), answer["yes"])[1]
                    try:
                        mine.settings.cloud["seated"] = False
                        mine.table = other
                        untouched = not mine.check_seat(other)
                        mine.refresh_cloud()
                        elsewhere = i18n.t("launcher.cloud.seat_elsewhere", name="Other-PC", date="2026-10-10")
                        own_key = i18n.t("launcher.launchers.own", name=mine.settings.identity()[1],
                                         fingerprint=sync.fingerprint(mine.settings.sign_key))
                        results.append((f"{tag} another seat, never held here: nothing lost, the box says Start asks",
                                        untouched and mine.settings.cloud_ready and not revoked and not told
                                        and elsewhere in box_texts()))
                        results.append((f"{tag} the box does not carry the launcher's key (it is under Hosts of the table)",
                                        own_key not in box_texts()))
                        mine.table = forged
                        mine.settings.cloud["seated"] = True
                        quiet = not mine.check_seat(forged)
                        mine.refresh_cloud()
                        tampered = i18n.t("launcher.cloud.table_tampered", name="Forger", date="2026-10-10",
                                          fingerprint=sync.fingerprint("f" * 64))
                        results.append((f"{tag} a file naming another seat without its signature: nothing given up, said",
                                        quiet and not revoked and not asked and mine.settings.cloud.get("seated")
                                        and tampered in box_texts() and elsewhere not in box_texts()))
                        # The seat ours, a host the table vouches for still hosting:
                        # the box offers the hand-over, not the force for a stranger.
                        seed_old, seed_mine = ed25519.new_seed(), mine.settings.seed()
                        key_old = ed25519.public_key(seed_old).hex()
                        ours = sync.TableRecord(format=2, name="T", admin_id=mine.settings.host_id,
                                                admin_name="This-PC", admin_key=mine.settings.sign_key,
                                                admin_since="2026-10-11T03:00:00Z", signed_since=1,
                                                seats=[{"host_id": "h-old", "name": "Old-PC",
                                                        "since": "2026-10-01T00:00:00Z",
                                                        "until": "2026-10-11T03:00:00Z"}])
                        ours.sign(seed_mine)
                        entries = [sync.make_admission(seed_mine, mine.settings.host_id, "h-old", "Old-PC", key_old)]
                        old_address = "https://on-air.nicegui.io/old/device-0/"
                        old_record = sync.HostRecord(host_id="h-old", host_name="Old-PC", epoch=3, seq=1,
                                                     since="2026-10-11T03:05:00Z", address=old_address)
                        old_record.sign(seed_old, key_old)
                        mine.settings.cloud["seated"] = True
                        mine.table, mine.entries = ours, entries
                        mine.known = sync.known_launchers(ours, entries)
                        mine.other = old_record
                        mine.refresh_cloud()
                        texts = box_texts()
                        results.append((f"{tag} a vouched-for host still hosting: hand-over offered, no force",
                                        mine.holder_known(old_record) and i18n.t("launcher.cloud.take_over") in texts
                                        and i18n.t("launcher.cloud.take_force") not in texts))
                        # The Hosts window (2.2.0): this launcher, the hosts with their
                        # keys, the seats before, the way out for a lost PC.
                        tops_before = set(local_root.winfo_children())
                        mine.open_launchers()
                        hosts_win = next(w for w in local_root.winfo_children()
                                         if w not in tops_before and isinstance(w, tk.Toplevel))
                        hosts_texts, walk = set(), [hosts_win]
                        while walk:
                            widget = walk.pop()
                            try:
                                hosts_texts.add(str(widget.cget("text")))
                            except tk.TclError:
                                pass
                            walk.extend(widget.winfo_children())
                        hosts_win.destroy()
                        sections = ("launcher.launchers.section.this", "launcher.launchers.section.hosts",
                                    "launcher.launchers.section.former", "launcher.launchers.section.lost")
                        results.append((f"{tag} the Hosts window has its four sections and the lost-PC button",
                                        all(i18n.t(k) in hosts_texts for k in sections)
                                        and i18n.t("launcher.cloud.cut_off") in hosts_texts
                                        and i18n.t("launcher.launchers.former_none") not in hosts_texts
                                        and any("Old-PC" in s for s in hosts_texts)))
                        held = i18n.t("launcher.launchers.held_seat", until="2026-10-11")
                        results.append((f"{tag} a host that held the seat before is marked so on its row, "
                                        "and listed among the former seats",
                                        any(held in s and "Old-PC" in s for s in hosts_texts)
                                        and any(s.startswith("Old-PC,") for s in hosts_texts)))
                        # Hosting: the control room stays reachable (2.2.0).
                        mine.mode_var.set("online")
                        mine.other = None
                        mine.record = sync.HostRecord(host_id=mine.settings.host_id, host_name="This-PC",
                                                      epoch=5, seq=1, since="2026-10-12T10:00:00Z")
                        mine.refresh_cloud()
                        hosting_texts = box_texts()
                        results.append((f"{tag} the control room and the pairing stay reachable while hosting",
                                        i18n.t("launcher.cloud.launchers") in hosting_texts
                                        and i18n.t("launcher.cloud.pair_launcher") in hosting_texts))
                        mine.record = None
                        mine.other = old_record
                        mine.mode_var.set("local")
                        mine.refresh_cloud()
                        results.append((f"{tag} Join shows the web address it opens",
                                        i18n.t("launcher.cloud.join") in texts
                                        and i18n.t("launcher.cloud.row.join", host="Old-PC", address=old_address) in texts))
                        old_record.address = chr(92) * 2 + "evil" + chr(92) + "share" + chr(92) + "run.exe"
                        old_record.sign(seed_old, key_old)
                        mine.refresh_cloud()
                        texts = box_texts()
                        results.append((f"{tag} an address that is not a web address gets no Join, and a line says so",
                                        i18n.t("launcher.cloud.join") not in texts
                                        and i18n.t("launcher.cloud.address_not_web", host="Old-PC") in texts))
                        mine.other = None
                        mine.known, mine.entries = {}, []
                        # Held here before, the file signed by the new seat: asked.
                        mine.table = other
                        mine.settings.cloud["seated"] = True
                        mine.seat_asked = ""
                        answer["yes"] = False
                        kept = mine.check_seat(other)
                        ask_text = i18n.t("launcher.cloud.seat_taken_ask", name="Other-PC", date="2026-10-10",
                                          fingerprint=sync.fingerprint(key_other))
                        results.append((f"{tag} another seat, held here before: asked with the key; no keeps the seat here",
                                        kept and asked == [ask_text] and not revoked and mine.settings.cloud_ready
                                        and not mine.settings.cloud.get("seated") and elsewhere in box_texts()))
                        results.append((f"{tag} and the same key is not asked about twice",
                                        not mine.check_seat(other) and len(asked) == 1))
                        mine.settings.cloud["seated"] = True
                        mine.seat_asked = ""
                        answer["yes"] = True
                        deposed = mine.check_seat(other)
                        results.append((f"{tag} yes steps down: access cancelled, the table forgotten, no popup",
                                        deposed and not mine.settings.cloud and revoked == [1] and told == []))
                        mine.refresh_cloud()
                        left = mine.settings.left_table
                        results.append((f"{tag} and the box keeps saying so, with the way back, until the "
                                        "launcher joins a table again (2.2.0)",
                                        left.get("name") == "Other-PC" and left.get("date") == "2026-10-10"
                                        and mine.cloud_label.cget("text") == i18n.t(
                                            "launcher.cloud.left_table", table=left.get("table", ""),
                                            name="Other-PC", date="2026-10-10")))
                        results.append((f"{tag} stepped down: Take the seat back and Forget, no set-up, and the "
                                        "Start row and the address box are gone (2.2.0)",
                                        mine.stepped_down()
                                        and i18n.t("launcher.cloud.take_seat_back") in box_texts()
                                        and i18n.t("launcher.cloud.left_forget") in box_texts()
                                        and i18n.t("launcher.cloud.set_up") not in box_texts()
                                        and mine.actions.winfo_manager() == "" and mine.air.winfo_manager() == ""
                                        and mine.cloud.winfo_manager() == "pack"))
                        # Online, where the address box would be: the box stays
                        # and anchors above the status line (the Start row is out).
                        mine.mode_var.set("online")
                        mine.mode_changed()
                        results.append((f"{tag} stepped down online: the box shown, the address box and the "
                                        "Start row out",
                                        mine.cloud.winfo_manager() == "pack" and mine.air.winfo_manager() == ""
                                        and mine.actions.winfo_manager() == ""))
                        mine.mode_var.set("local")
                        mine.mode_changed()
                        mine.settings.left_table = {}
                        mine.refresh_cloud()
                        results.append((f"{tag} forgotten: an ordinary launcher again, the Start row back",
                                        not mine.stepped_down() and mine.actions.winfo_manager() == "pack"
                                        and i18n.t("launcher.cloud.set_up") in box_texts()))
                    finally:
                        window.messagebox.showinfo = real_showinfo
                        window.messagebox.askyesno = real_askyesno
                        mine.table = None
                finally:
                    for pending in local_root.tk.call("after", "info"):
                        local_root.tk.call("after", "cancel", pending)
                    local_root.update()             # Tk's own idle work, before the window goes
                    for pending in local_root.tk.call("after", "info"):
                        local_root.tk.call("after", "cancel", pending)
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
                        results.append((f"{tag} SetupWizard, an existing app: Next asks for its key, no permissions page (2.2.0)",
                                        guide.page == "cloud/key" and guide.existing
                                        and "permissions" not in wizard.EXISTING_STEPS))
                        guide.go_back()
                        guide.go_back()
                        guide.go_next()
                        results.append((f"{tag} SetupWizard, back to a new app: Next goes to the permissions",
                                        guide.page == "cloud/permissions" and not guide.existing))
                    guide.win.destroy()

                # The seat back (2.2.0): its own short road, from the app list,
                # or from the authorisation when the app's key is known.
                bare = core.Settings(mode="online", language=lang, check_updates=False)
                guide = wizard.SetupWizard(root, bare, lambda: None, seat_back=True)
                short_road = [p.split("/", 1)[1] for p in guide.pages]
                first = guide.page
                real_open = wizard.webbrowser.open
                wizard.webbrowser.open = lambda _url: None
                try:
                    guide.connect_existing()
                finally:
                    wizard.webbrowser.open = real_open
                results.append((f"{tag} Take the seat back: a first page that says so, its button opens the "
                                "list and goes to it; then the key, the authorisation, the code, done",
                                tuple(short_road) == wizard.SEAT_BACK_STEPS and first == "cloud/seat_back"
                                and guide.page == "cloud/existing" and guide.existing))
                guide.go_next()
                results.append((f"{tag} and Next from the list asks for the key", guide.page == "cloud/key"))
                guide.win.destroy()
                guide = wizard.SetupWizard(root, app.settings, lambda: None, seat_back=True)
                first = guide.page
                guide.go_next()
                results.append((f"{tag} Take the seat back with the key known: the page says so, Next is the "
                                "authorisation, four pages",
                                first == "cloud/seat_known" and guide.page == "cloud/authorise"
                                and tuple(p.split("/", 1)[1] for p in guide.pages) == wizard.SEAT_KNOWN_STEPS))
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
                    root.tk.call("after", "cancel", pending)
                root.destroy()
    screen.work_area = real_work_area

results.append(("no launcher window asked GitHub for updates", not asked_github))
shutil.rmtree(os.environ["KINGMAKER_DATA_DIR"], ignore_errors=True)
for name, ok in results:
    print(f" {'ok' if ok else 'NO'}  {name}")
print(f"{sum(1 for _n, ok in results if ok)}/{len(results)} passed")
