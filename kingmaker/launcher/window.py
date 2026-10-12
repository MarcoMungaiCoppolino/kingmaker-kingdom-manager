"""The launcher window: tkinter, standard library only, in the two languages
of the app.

One window. Where do you play (this computer, the network, online), the On
Air token when online, Start and Stop, the links to copy, the status and a
log pane; the first-start password in a dialog; the settings in a second
window. Everything the server says arrives on a queue from the reader
thread and is read from the Tk loop, which is the only one allowed to touch
the widgets.
"""
from __future__ import annotations

import dataclasses
import queue
import sys
import tempfile
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Callable

from kingmaker import __version__, config
from kingmaker.launcher import core, dropbox, screen, sync, wizard
from kingmaker.locale import i18n
from kingmaker.locale.i18n import t

PAD = {"padx": 12, "pady": 4}
COLOURS = {"ok": "#2e7d32", "busy": "#8a6d00", "bad": "#b71c1c", "quiet": "#555555"}


def run() -> None:
    """Opens the window; returns when it is closed."""
    settings = core.Settings.load()
    if not settings.language:
        settings.language = core.guess_language()
    i18n.language_resolver = lambda: settings.language
    root = tk.Tk(baseName="kingmaker", className=core.WM_CLASS)
    root.withdraw()
    if not core.writable(core.game_folder()):
        messagebox.showerror(core.APP_NAME, t("launcher.not_writable", folder=core.game_folder()))
        root.destroy()
        return
    lock = core.SingleInstance()
    if not lock.acquire():
        messagebox.showinfo(core.APP_NAME, t("launcher.already_running"))
        root.destroy()
        return
    try:
        app = Launcher(root, settings)
        if settings.welcome_due:
            # Alone on screen: who you are at the table, where you play, the
            # rest only as the answers call for. The window comes after it,
            # finished or skipped, already showing what was answered.
            root.after(0, app.open_welcome)
        else:
            screen.present(root)
        root.mainloop()
    finally:
        lock.release()


# How often the window asks the cloud, by itself, who is hosting: while this
# launcher does not host, so that "Hosted by" and "Nobody is hosting" stay true
# without a button to press. A few small calls to Dropbox each time (the record,
# the table's file, and the clock it is judged by), so every minute as a rule,
# and every 15 seconds while someone else hosts: that is when somebody is
# waiting for them to stop, to start the game here.
WATCH_EVERY_MS = 60_000
# A key authorised for a pairing that nobody spent: cancelled after the
# code's life (ten minutes) and a margin (2.2.0).
PENDING_KEY_LIFE_S = 900
WATCH_HOSTED_MS = 15_000
# While someone else hosts, the quick checks ask only who holds the game; the
# table's file (its name, address and token, which rarely change) is read
# again once this many seconds have passed. Start always reads it afresh.
TABLE_EVERY_S = 60.0
# How long the administrator waits for the current host to hand the game
# over before being asked whether to take it by force: the holder looks at
# the record every STATUS_EVERY seconds, then uploads its last copy.
HANDOVER_WAIT_S = 120.0


class SeatChanged(Exception):
    """The table file is signed by another seat than this launcher's
    (a host), or the administrator declined to take a seat another PC
    holds. `who` and `since` name the seat on the file."""

    def __init__(self, who: str, since: str) -> None:
        super().__init__(f"the seat is {who}'s since {since}")
        self.who, self.since = who, since


class TableRefused(Exception):
    """The table's file cannot be acted on: it names a seat without that
    seat's signature (rewritten by hand), or it names this launcher
    without its signature and the person declined to sign it. The text
    says which, for the log and the window."""


class Launcher:
    def __init__(self, root: tk.Tk, settings: core.Settings) -> None:
        self.root = root
        self.settings = settings
        self.events: queue.Queue = queue.Queue()
        self.server = core.Server(on_line=lambda text: self.events.put(("line", text)),
                                  on_exit=lambda code: self.events.put(("exit", code)))
        self.links: dict[str, str] = {}
        self.port_in_use: int | None = None
        self.release: core.Release | None = None
        self.log_lines: list[str] = []
        self.settings_window: tk.Toplevel | None = None
        # The cloud: the record we hold while hosting, the thread that keeps
        # it alive and uploads, and the record of whoever else hosts.
        self.record: sync.HostRecord | None = None
        self.hoster: sync.Hoster | None = None
        self.other: sync.HostRecord | None = None
        self.cloud_busy = False
        # Stop's last upload, in its thread (`stop`): the window is told
        # when it is done (`stopped`), and closing waits for it.
        self.stop_thread: threading.Thread | None = None
        # Whether this process has held the record once: a living record
        # with our own identity is then a crash and a restart, otherwise it
        # may be a copied game folder on another PC, and we ask.
        self.hosted_before = False
        # Hosting without the cloud, after it did not answer: no token, no
        # uploads, and the next cloud start asks what to do with the fork.
        self.offline = False
        # The table's file as last read, and the token it gave for this
        # start: read at every Start, handed to the server, never saved here.
        self.table: sync.TableRecord | None = None
        self.token_for_start: str | None = None
        # The administrator rotated the cloud access and ours is cancelled
        # (Dropbox said `invalid_grant`): pair again.
        self.access_lost = False
        self.token_refused_said = False
        # The quiet check of who is hosting (`watch_host`): its own flag, not
        # `cloud_busy`, so that it never makes a Start wait or go unheard.
        # The line under Start follows it only while it already speaks of
        # who hosts; an outage is logged once, not every minute; a stranger
        # at the table's address is shown once per address.
        self.watching = False
        self.table_read_at = 0.0
        self.status_about_host = False
        self.watch_error = ""
        self.alarmed: str | None = None
        self.shown_key: tuple | None = None
        self.watch_id: str = ""
        # The launchers the table vouches for (`sync.known_launchers`), read
        # with the table's file: who may hold the record and sign copies.
        self.known: dict[str, str] = {}
        self.entries: list[dict] = []
        # A host whose table file is signed by another seat than the one it
        # paired with: the administrator's launcher changed. Pair again.
        self.seat_changed = False
        # The key found on a seat this administrator's launcher never held:
        # said once in the log (the Table box keeps saying it), Start asks.
        self.seat_elsewhere_said = ""
        # The key found on the seat this launcher held: asked about once
        # (step down, or keep the seat and let Start take it back).
        self.seat_asked = ""
        # A file naming another seat without that seat's signature: said
        # once per such file, nothing done about it.
        self.tampered_said = ""
        # An earlier file of this seat's written back: said once per file.
        self.stale_said = ""
        # A seat just taken from another PC: `(old admin id, the launchers
        # the old seat vouched for)`, until the copies are listed and the
        # hosts admitted again under this seat (`inherit`).
        self.inherit_from: tuple[str, dict[str, str]] | None = None

        root.title(core.APP_NAME)
        root.minsize(560, 420)
        self.set_icon(root)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.mode_var = tk.StringVar(value=settings.mode)
        self.token_var = tk.StringVar(value=settings.token)
        self.show_token = tk.BooleanVar(value=False)
        self.show_log = tk.BooleanVar(value=False)
        self.body: ttk.Frame | None = None
        # The address box's first line follows the field: "fixed" as soon as
        # a token is pasted, without a Start in between.
        self.token_var.trace_add("write", lambda *_: self.body is not None and self.refresh_air())
        self.build()
        root.after(100, self.poll)
        self.watch_id = root.after(1500, self.watch_host)
        if settings.check_updates:
            threading.Thread(target=self.check_updates, daemon=True).start()

    def set_icon(self, root: tk.Tk) -> None:
        """The crest in the title bar and the taskbar, for every window of
        this root (`default=` covers the dialogs too)."""
        try:
            if sys.platform == "win32":
                ico = core.icon_file("ico")
                if ico is not None:
                    root.iconbitmap(default=str(ico))
                    return
            png = core.icon_file("png")
            if png is not None:
                self.icon_image = tk.PhotoImage(file=str(png))
                root.iconphoto(True, self.icon_image)
        except tk.TclError:
            pass                       # Tk's feather, then; nothing else changes

    def post(self, fn) -> None:
        """Runs `fn` on the Tk thread at the next poll: the only safe way in
        from the threads that talk to the network."""
        self.events.put(("call", fn))

    # ------------------------------------------------------------ building
    def build(self) -> None:
        """The window of who this launcher is at the table. The administrator
        gets everything: where you play, the address, the table and what to
        do with it. A host gets the table and Start: where the game is played
        came with the table's address, and nothing else is theirs to set."""
        if self.body is not None:
            self.body.destroy()
        self.start_button = None
        self.actions = None
        self.built_language = self.settings.language
        admin = not self.settings.host
        self.body = ttk.Frame(self.root)
        self.body.pack(fill="both", expand=True)
        # The log first and at the bottom, where the room a taller window
        # gives goes to it; the rest above scrolls when the screen is short
        # of height, as a laptop's is (`screen`), so Start stays reachable.
        foot = ttk.Frame(self.body)
        foot.pack(side="bottom", fill="both", expand=True)
        scroller = screen.Scrolled(self.body)
        scroller.pack(side="top", fill="both")
        body = scroller.inner

        self.head = head = ttk.Frame(body)
        head.pack(fill="x", **PAD)
        ttk.Label(head, text=core.APP_NAME, font=("TkDefaultFont", 15, "bold")).pack(side="left")
        ttk.Label(head, text=t("launcher.version", version=__version__),
                  foreground=COLOURS["quiet"]).pack(side="left", padx=8, pady=6)
        ttk.Button(head, text=t("launcher.settings"), command=self.open_settings).pack(side="right")

        self.update_bar = ttk.Frame(body)
        self.update_label = ttk.Label(self.update_bar, foreground=COLOURS["busy"])
        self.update_label.pack(side="left")
        self.update_button = ttk.Button(self.update_bar, command=self.download_update)
        self.update_button.pack(side="left", padx=8)
        self.show_release()

        if admin:
            self.build_admin(body)

        self.cloud = ttk.LabelFrame(body, text=t("launcher.cloud.title"))
        self.cloud.pack(fill="x", **PAD)
        self.cloud_label = ttk.Label(self.cloud, wraplength=500, justify="left")
        self.cloud_label.pack(anchor="w", padx=8, pady=(4, 4))
        self.cloud_row = ttk.Frame(self.cloud)
        self.cloud_row.pack(fill="x", padx=8, pady=(0, 6))
        self.refresh_cloud()

        self.actions = actions = ttk.Frame(body)
        actions.pack(fill="x", **PAD)
        self.start_button = ttk.Button(actions, text=t("launcher.start"), command=self.toggle)
        self.start_button.pack(side="left")
        self.browser_button = ttk.Button(actions, text=t("launcher.open_browser"),
                                         command=self.open_browser, state="disabled")
        self.browser_button.pack(side="left", padx=8)
        # Loading another game is the administrator's: a host's copy is the
        # table's, and the next start would carry it to everyone.
        self.load_button = None
        if admin:
            self.load_button = ttk.Button(actions, text=t("launcher.load_save"), command=self.load_save)
            self.load_button.pack(side="right")

        self.status_row = status_row = ttk.Frame(body)
        status_row.pack(fill="x", **PAD)
        self.status = ttk.Label(status_row, wraplength=440, foreground=COLOURS["quiet"])
        self.status.pack(side="left", anchor="w")
        # Shown, moving, while the launcher works on the cloud (a status in
        # the busy colour): a seat take reads every copy in the folder, and
        # a window that says nothing for a minute looks crashed.
        self.working_bar = ttk.Progressbar(status_row, mode="indeterminate", length=120)

        self.links_frame = ttk.Frame(body)
        self.links_frame.pack(fill="x", padx=12)

        ttk.Checkbutton(foot, text=t("launcher.log.show"), variable=self.show_log,
                        command=self.toggle_log).pack(anchor="w", padx=12, pady=(6, 0))
        self.log = ScrolledText(foot, height=9, state="disabled", wrap="word",
                                font=("TkFixedFont", 9))
        self.refill_log()

        self.mode_changed()
        self.reflect_running()
        self.rebuild_links()
        self.toggle_log()

    def build_admin(self, body: ttk.Frame) -> None:
        """Where you play and the table's address: the administrator's."""
        self.where = where = ttk.LabelFrame(body, text=t("launcher.where"))
        where.pack(fill="x", **PAD)
        for mode in core.MODES:
            ttk.Radiobutton(where, text=t(f"launcher.mode.{mode}"), value=mode,
                            variable=self.mode_var, command=self.mode_changed
                            ).pack(anchor="w", padx=8, pady=2)
        self.mode_hint = ttk.Label(where, foreground=COLOURS["quiet"], wraplength=500)
        self.mode_hint.pack(anchor="w", padx=8, pady=(2, 6))

        self.air = ttk.LabelFrame(body, text=t("launcher.air.title"))
        # Two faces. Without a table in the cloud: one line that says whether
        # the address is fixed, the guide for who has no token, the field for
        # who has one. With a table: one line, because the token lives in the
        # table's folder, and — for the administrator — the door to a new
        # one. `refresh_air` shows one face or the other. The welcome already
        # said what a token is for: the box does not say it again.
        self.air_full = ttk.Frame(self.air)
        self.air_status = ttk.Label(self.air_full, wraplength=500, justify="left")
        self.air_status.pack(anchor="w", padx=8, pady=(4, 2))
        self.air_button = self.row(self.air_full, t("launcher.air.setup"), self.open_air,
                                   t("launcher.air.row.setup"))
        self.token_row = row = ttk.Frame(self.air_full)
        row.pack(fill="x", padx=8, pady=(6, 6))
        ttk.Label(row, text=t("launcher.air.field")).pack(side="left", padx=(0, 8))
        self.token_entry = ttk.Entry(row, textvariable=self.token_var, show="•")
        self.token_entry.pack(side="left", fill="x", expand=True)
        ttk.Checkbutton(row, text=t("launcher.air.show"), variable=self.show_token,
                        command=self.toggle_token).pack(side="left", padx=6)
        # The new token's door opens the guide straight at the renewal step,
        # because the step before it asks for the token being replaced.
        self.air_cloud = ttk.Frame(self.air)
        self.air_from_table = ttk.Label(self.air_cloud, text=t("launcher.air.from_table"),
                                        wraplength=500, justify="left")
        self.air_from_table.pack(anchor="w", padx=8, pady=(6, 4))
        self.air_renew = self.row(self.air_cloud, t("launcher.air.renew"), self.open_air_new,
                                  t("launcher.air.row.renew"))
        self.refresh_air()

    def refresh_air(self) -> None:
        """The On Air box's face: the ways to a token, the field and the note
        for whoever plays online without the cloud; one line with the cloud.
        A host's window has no such box."""
        if self.settings.host:
            return
        self.air_full.pack_forget()
        self.air_cloud.pack_forget()
        if self.settings.cloud_ready:
            self.air_cloud.pack(fill="x")
            renew_row = self.air_renew.master
            renew_row.pack_forget()
            if self.settings.cloud.get("role") == "admin":
                renew_row.pack(fill="x", padx=8, pady=(2, 6))
        else:
            fixed = bool(self.token_var.get().strip())
            self.air_status.config(text=t("launcher.air.status.fixed" if fixed else "launcher.air.status.none"),
                                   foreground=COLOURS["ok"] if fixed else COLOURS["quiet"])
            self.air_full.pack(fill="x")

    def mode_changed(self) -> None:
        if self.settings.host:
            return
        mode = self.mode_var.get()
        self.mode_hint.config(text=t(f"launcher.mode.{mode}_hint"))
        if mode == "online":
            self.air.pack(fill="x", after=self.mode_hint.master, **PAD)
        else:
            self.air.pack_forget()
        # The Table box's pairing group and the address rows follow the place
        # chosen; `refresh_cloud` also places the box.
        self.refresh_cloud()
        self.rebuild_links()

    def stepped_down(self) -> bool:
        """An administrator's launcher that stepped down from a table and
        has not joined one since (`Settings.left_table`)."""
        left = self.settings.left_table
        return (not self.settings.host and not self.settings.cloud_ready
                and isinstance(left, dict) and bool(left.get("name")))

    def stepped_down_view(self, on: bool) -> None:
        """Stepped down, the window keeps the box and little else: the Start
        row (Start, the browser, the save file) and the address box go, so
        nothing on it leads to a game apart from the table. Off, both come
        back where they were."""
        if self.actions is None or self.settings.host:
            return
        if on:
            self.actions.pack_forget()
            self.air.pack_forget()
        else:
            if not self.actions.winfo_manager():
                self.actions.pack(fill="x", before=self.status_row, **PAD)
            if self.mode_var.get() == "online" and not self.air.winfo_manager():
                self.air.pack(fill="x", after=self.mode_hint.master, **PAD)

    def take_seat_back(self) -> None:
        """From a launcher that stepped down: the Dropbox guide on its short
        road (the app list, the key, the authorisation, the code), at the
        authorisation when the app's key is still known, and Start then
        asks whether to take the seat. The account and the app exist: no
        page for either."""
        left = self.settings.left_table
        app_key = str(left.get("app_key", ""))
        self.settings.cloud = {"app_key": app_key, "table": str(left.get("table", ""))} if app_key else {}
        wizard.SetupWizard(self.root, self.settings, on_done=self.refresh_cloud, post=self.post, seat_back=True)

    def forget_left(self) -> None:
        """The way out for a PC that goes its own way: the step-down is
        forgotten, the window is an ordinary launcher's again."""
        left = self.settings.left_table
        if not messagebox.askyesno(t("launcher.cloud.left_forget"),
                                   t("launcher.cloud.left_forget_confirm", table=left.get("table", ""))):
            return
        self.settings.left_table = {}
        self.settings.cloud = {}
        self.settings.save()
        self.refresh_cloud()

    def local_only(self) -> bool:
        """"On this computer only": the game answers at 127.0.0.1, where no
        other PC's launcher reaches it, so there is no pairing from here."""
        return self.mode_var.get() == "local"

    def place_table_box(self) -> None:
        """The Table box, but not on this computer only: nobody else reaches
        the game there, so there is nobody to let host. A table already made
        keeps its box, whatever the mode, for what is done with it."""
        if self.actions is None:
            return                          # still being built: `mode_changed` comes after
        cloud = self.settings.cloud
        alone = (not self.settings.host and self.mode_var.get() == "local"
                 and not self.settings.cloud_ready and not cloud.get("app_key")
                 and not self.stepped_down())
        if alone:
            self.cloud.pack_forget()
        else:
            # Above the Start row; above the status line while that row is
            # unpacked (the stepped-down view), since Tk anchors only on a
            # packed widget.
            anchor = self.actions if self.actions.winfo_manager() else self.status_row
            self.cloud.pack(fill="x", before=anchor, **PAD)

    def toggle_token(self) -> None:
        self.token_entry.config(show="" if self.show_token.get() else "•")

    def toggle_log(self) -> None:
        if self.show_log.get():
            self.log.pack(fill="both", expand=True, padx=12, pady=(2, 12))
        else:
            self.log.pack_forget()

    def refill_log(self) -> None:
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.insert("end", "\n".join(self.log_lines[-400:]))
        self.log.config(state="disabled")
        self.log.see("end")

    def append_log(self, text: str) -> None:
        self.log_lines.append(text)
        if len(self.log_lines) > 2000:
            del self.log_lines[:1000]
        self.log.config(state="normal")
        self.log.insert("end", text + "\n")
        self.log.config(state="disabled")
        self.log.see("end")

    def set_status(self, text: str, kind: str = "quiet", about_host: bool = False,
                   working: bool | None = None) -> None:
        """`working` shows the moving bar beside the text; by default a
        status in the busy colour is work under way, the others are not."""
        self.status.config(text=text, foreground=COLOURS.get(kind, COLOURS["quiet"]))
        self.status_about_host = about_host
        if working is None:
            working = kind == "busy"
        if working and not self.working_bar.winfo_manager():
            self.working_bar.pack(side="right", padx=(8, 0))
            self.working_bar.start(15)
        elif not working and self.working_bar.winfo_manager():
            self.working_bar.stop()
            self.working_bar.pack_forget()

    # --------------------------------------------------------------- links
    def rebuild_links(self) -> None:
        """The address rows: the running game's, or, while it is stopped,
        the last run's that the place now chosen still gives."""
        for child in self.links_frame.winfo_children():
            child.destroy()
        links = self.links if self.server.running else core.links_for_mode(self.links, self.mode_var.get())
        # An emptied frame keeps its last size in Tk: without rows it leaves
        # the window, or the room its rows took stays blank under Start.
        if not links:
            self.links_frame.pack_forget()
        elif not self.links_frame.winfo_manager():
            self.links_frame.pack(fill="x", padx=12, after=self.status_row)
        for kind, url in links.items():
            row = ttk.Frame(self.links_frame)
            row.pack(fill="x", pady=2)
            ttk.Label(row, text=t(f"launcher.link.{kind}"), width=16).pack(side="left")
            entry = ttk.Entry(row, state="readonly")
            # A StringVar that nothing holds is collected, and the entry goes
            # blank: the variable hangs on the widget.
            entry.var = tk.StringVar(value=url)      # type: ignore[attr-defined]
            entry.config(textvariable=entry.var)      # type: ignore[attr-defined]
            entry.pack(side="left", fill="x", expand=True)
            ttk.Button(row, text=t("launcher.copy"), width=8,
                       command=lambda u=url: self.copy(u)).pack(side="left", padx=(6, 0))

    def copy(self, text: str) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.set_status(t("launcher.copied"), "ok")

    # ------------------------------------------------------- start and stop
    def toggle(self) -> None:
        if self.server.running:
            self.stop()
        else:
            self.start()

    def gather(self) -> None:
        self.settings.mode = self.mode_var.get()
        self.settings.token = self.token_var.get().strip()
        self.settings.save()

    def start(self, force: bool = False, handover: bool = False) -> None:
        if self.server.running or self.cloud_busy:
            return
        self.gather()
        if self.settings.mode == "lan" and sys.platform == "win32" and not self.settings.firewall_shown:
            messagebox.showinfo(t("launcher.firewall.title"), t("launcher.firewall.text"))
            self.settings.firewall_shown = True
            self.settings.save()
        if self.settings.cloud_ready:
            self.claim_then_start(force, handover)
            return
        self.start_server()

    def start_server(self) -> None:
        port = core.free_port(self.settings.port)
        if port is None:
            self.set_status(t("launcher.status.no_port", port=self.settings.port), "bad")
            return
        self.links = {}
        self.rebuild_links()
        self.port_in_use = port
        if port != self.settings.port:
            self.set_status(t("launcher.status.port_moved", wanted=self.settings.port, port=port), "busy",
                            working=False)
        else:
            self.set_status(t("launcher.status.starting"), "busy")
        self.append_log("$ " + " ".join(core.server_command(self.settings, port)))
        self.token_refused_said = False
        if self.offline:
            self.append_log(t("launcher.log.offline"))
        try:
            self.server.start(self.settings, port, cloud=not self.offline, token=self.token_for_start)
        except OSError as error:
            self.set_status(str(error), "bad")
            self.drop_record()
            return
        self.reflect_running()

    def stop(self, wait: bool = False) -> None:
        """Stop: the last copy up and the record released (the hoster's
        stop), then the server down. The upload runs in a thread and the
        window is told when it is done (`stopped`): it can take a while,
        and a window that does not answer meanwhile looks crashed. `wait`
        (closing) does it here, so the process does not leave before the
        copy is up."""
        self.set_status(t("launcher.status.stopping"), "busy")
        self.start_button.config(state="disabled")
        self.root.update_idletasks()
        hoster, self.hoster = self.hoster, None
        self.record = None
        if hoster is not None:
            self.set_status(t("launcher.cloud.final_upload"), "busy")
            self.root.update_idletasks()
        if wait:
            if hoster is not None:
                hoster.stop(final=True)
            self.stopped()
            return

        def work() -> None:
            # The last copy, then the server's own shutdown, which writes
            # the game's last save and takes a few seconds too.
            try:
                if hoster is not None:
                    hoster.stop(final=True)
                    self.post(lambda: self.set_status(t("launcher.status.stopping"), "busy"))
                self.server.stop()
            finally:
                self.post(self.stopped)

        self.stop_thread = threading.Thread(target=work, daemon=True)
        self.stop_thread.start()

    def stopped(self) -> None:
        """The last copy up and the server gone (or asked to go here, when
        closing): the window is a stopped one."""
        self.stop_thread = None
        self.server.stop()
        self.offline = False
        self.token_for_start = None
        self.reflect_running()
        self.refresh_cloud()

    # ---------------------------------------------------------------- cloud
    def refresh_cloud(self) -> None:
        """The Cloud box: one line that says where things stand, then the
        things to do here in groups, from every evening to the day someone
        leaves, each button with its use written next to it — the box must
        read as a story, not as a row of buttons."""
        for child in self.cloud_row.winfo_children():
            child.destroy()
        cloud = self.settings.cloud
        admin = cloud.get("role") == "admin"
        self.stepped_down_view(self.stepped_down())
        if self.stepped_down():
            # Stepped down from a table: one thing to do here, the seat
            # back, and a way out for a PC that goes its own way. Nothing
            # that starts a game apart from the table.
            left = self.settings.left_table
            self.cloud_label.config(text=t("launcher.cloud.left_table", table=left.get("table", ""),
                                           name=left.get("name", ""), date=str(left.get("date", ""))[:10]),
                                    foreground=COLOURS["bad"])
            self.action(t("launcher.cloud.take_seat_back"), self.take_seat_back,
                        t("launcher.cloud.row.take_seat_back"))
            self.action(t("launcher.cloud.left_forget"), self.forget_left, t("launcher.cloud.row.left_forget"))
            self.place_table_box()
            return
        if not self.settings.cloud_ready:
            if self.settings.vault_error and cloud.get("app_key"):
                # The secrets were protected by another Windows user or on
                # another PC (a copied game folder): the rest of the cloud
                # settings are here, the access is not. Pair again.
                self.cloud_label.config(text=t("launcher.cloud.vault_error", table=cloud.get("table", "")),
                                        foreground=COLOURS["bad"])
            elif self.settings.host:
                self.cloud_label.config(text=t("launcher.cloud.not_paired"), foreground=COLOURS["quiet"])
            else:
                self.cloud_label.config(text=t("launcher.cloud.not_set_up"), foreground=COLOURS["quiet"])
            # Each its own door: the administrator lets others host, a host
            # pairs with the table someone else set up.
            if self.settings.host:
                self.action(t("launcher.cloud.pair"), self.open_pair, t("launcher.cloud.row.pair"))
            else:
                self.action(t("launcher.cloud.set_up"), self.open_wizard, t("launcher.cloud.row.set_up"))
            self.refresh_air()
            self.gate_start()
            self.place_table_box()
            return
        who = self.settings.identity()[1]
        role = cloud.get("role", "")
        role_name = t(f"launcher.cloud.role.{role}") if role in ("admin", "host") else role
        if self.access_lost and admin:
            # Dropbox refuses the administrator's own access: the app was
            # disconnected on dropbox.com (a lost PC cut off), or the keys
            # were changed from another seat. Authorise again, then every
            # host pairs again.
            self.cloud_label.config(text=t("launcher.cloud.access_lost_admin"), foreground=COLOURS["bad"])
            self.action(t("launcher.cloud.reauthorise"), self.reauthorise, t("launcher.cloud.row.reauthorise"))
            self.group(t("launcher.cloud.group.this_pc"))
            self.action(t("launcher.cloud.forget"), self.forget_cloud, t("launcher.cloud.row.forget"))
            self.refresh_air()
            return
        if self.access_lost or self.seat_changed:
            # The administrator changed the keys, or another PC took the
            # seat: this launcher's access is cancelled either way.
            if self.seat_changed and self.table is not None:
                text = t("launcher.cloud.seat_changed", name=self.table.admin_name or self.table.admin_id,
                         date=self.table.admin_since[:10])
            else:
                text = t("launcher.cloud.rotated_out")
            self.cloud_label.config(text=text, foreground=COLOURS["bad"])
            self.action(t("launcher.cloud.pair"), self.open_pair, t("launcher.cloud.row.pair_again"))
            self.group(t("launcher.cloud.group.this_pc"))
            self.action(t("launcher.cloud.forget"), self.forget_cloud, t("launcher.cloud.row.forget"))
            self.refresh_air()
            return
        if self.record is not None:
            self.cloud_label.config(text=t("launcher.cloud.you_host", table=cloud.get("table", ""),
                                           epoch=self.record.epoch), foreground=COLOURS["ok"])
            if admin:
                self.group(t("launcher.cloud.group.host"))
                if self.local_only():
                    self.note(t("launcher.cloud.pair_local"))
                else:
                    self.action(t("launcher.cloud.pair_launcher"), self.make_pairing_code,
                                t("launcher.cloud.row.pair_launcher"))
                    self.action(t("launcher.cloud.launchers"), self.open_launchers,
                                t("launcher.cloud.row.launchers"))
        elif self.offline and self.server.running:
            self.cloud_label.config(text=t("launcher.cloud.offline", table=cloud.get("table", "")),
                                    foreground=COLOURS["bad"])
        elif self.other is not None and self.other.held():
            host = self.other.host_name or self.other.host_id
            self.group(t("launcher.cloud.group.now"))
            if self.holder_known(self.other):
                self.cloud_label.config(text=self.hosted_text(self.other), foreground=COLOURS["busy"])
                if self.other.address:
                    # Only a web address is opened: the record is another
                    # launcher's, and the shell would run anything else.
                    address = core.web_address(self.other.address)
                    if address:
                        self.action(t("launcher.cloud.join"), lambda: webbrowser.open(address),
                                    t("launcher.cloud.row.join", host=host, address=address))
                    else:
                        self.note(t("launcher.cloud.address_not_web", host=host))
                if admin:
                    self.action(t("launcher.cloud.take_over"), self.take_over,
                                t("launcher.cloud.row.take_over", host=host))
            else:
                # A record the table does not vouch for: a key thief, or a
                # launcher struck off. No link to follow; the administrator
                # takes the record back by force, nothing is asked of it.
                self.cloud_label.config(text=t("launcher.cloud.hosted_unknown", host=host,
                                               since=self.other.since[:16].replace("T", " ")),
                                        foreground=COLOURS["bad"])
                if admin:
                    self.action(t("launcher.cloud.take_force"), lambda: self.start(force=True),
                                t("launcher.cloud.row.take_force"))
        else:
            key = "launcher.cloud.ready_admin" if admin else "launcher.cloud.ready"
            self.cloud_label.config(text=t(key, table=cloud.get("table", ""), who=who, role=role_name,
                                           account=cloud.get("account_name", "")), foreground=COLOURS["quiet"])
            if admin:
                if self.seat_elsewhere():
                    # Connected to the table's app on this PC, the seat still
                    # another PC's: Start asks whether to take it here.
                    self.note(self.seat_elsewhere_text(self.table))
                elif self.table_tampered():
                    self.note(self.tampered_text(self.table))
                # On this computer only nobody else reaches the game for a
                # code: no pairing, and no hosts to look after. The keys stay,
                # since the copies still go to the table from here.
                self.group(t("launcher.cloud.group.host"))
                if self.local_only():
                    self.note(t("launcher.cloud.pair_local"))
                else:
                    self.action(t("launcher.cloud.pair_launcher"), self.make_pairing_code,
                                t("launcher.cloud.row.pair_launcher"))
                    self.action(t("launcher.cloud.launchers"), self.open_launchers,
                                t("launcher.cloud.row.launchers"))
            self.group(t("launcher.cloud.group.this_pc"))
            self.action(t("launcher.cloud.forget"), self.forget_cloud, t("launcher.cloud.row.forget"))
        self.refresh_air()
        self.gate_start()
        self.place_table_box()

    def gate_start(self) -> None:
        """A host not paired with a table has nothing to start: Start waits
        for the pairing, and the line under it says so."""
        if self.start_button is None or self.server.running or self.cloud_busy:
            return
        if self.settings.host and not self.settings.cloud_ready:
            self.start_button.config(state="disabled")
            self.set_status(t("launcher.status.pair_first"), "quiet")
        else:
            self.start_button.config(state="normal")
            if self.status.cget("text") == t("launcher.status.pair_first"):
                self.set_status(t("launcher.status.stopped"), "quiet")   # paired just now

    def row(self, parent, text: str, command, explanation: str, width: int = 24) -> ttk.Button:
        """One row of a box: the button, and next to it what it is for and
        when, in a sentence. The buttons share a width, so the sentences
        line up."""
        line = ttk.Frame(parent)
        line.pack(fill="x", padx=8, pady=2)
        button = ttk.Button(line, text=text, command=command, width=width)
        button.pack(side="left", anchor="n")
        ttk.Label(line, text=explanation, wraplength=340, justify="left",
                  foreground=COLOURS["quiet"]).pack(side="left", padx=8, anchor="w")
        return button

    def action(self, text: str, command, explanation: str) -> None:
        self.row(self.cloud_row, text, command, explanation)

    def group(self, title: str) -> None:
        """A small heading over a few rows of the Cloud box: when they are
        for. The order of the groups is the order of how often."""
        ttk.Label(self.cloud_row, text=title, font=("TkDefaultFont", 9, "bold")
                  ).pack(anchor="w", padx=8, pady=(8, 1))

    def note(self, text: str) -> None:
        """A muted line in a group of the Cloud box, where a button would be
        if it made sense here: why it does not."""
        ttk.Label(self.cloud_row, text=text, wraplength=480, justify="left",
                  foreground=COLOURS["quiet"]).pack(anchor="w", padx=8, pady=2)

    def warn(self, text: str) -> None:
        """The same line in the colour of bad news: something the person
        should read before the buttons."""
        ttk.Label(self.cloud_row, text=text, wraplength=480, justify="left",
                  foreground=COLOURS["bad"]).pack(anchor="w", padx=8, pady=2)

    def open_air_new(self) -> None:
        """A new On Air token for the table — the whole guide for a first
        token, or straight at the renewal step when there is one to replace."""
        known = bool(self.settings.token.strip() or (self.table is not None and self.table.air_token))
        wizard.AirWizard(self.root, self.settings, on_done=self.air_ready,
                         start="renew" if known else wizard.AIR_STEPS[0])

    def cloud_client(self) -> dropbox.Client:
        credential = self.settings.credential()
        assert credential is not None
        return dropbox.Client(credential)

    def hosted_text(self, record: sync.HostRecord) -> str:
        """"Hosted by X (version) since…" — with a word for a host whose
        launcher predates the table's version and cannot know it."""
        since = record.since.replace("T", " ").rstrip("Z")
        host = record.host_name or record.host_id
        version = record.app_version or "?"
        known = core.version_tuple(version)
        if known and known < (1, 3, 0):
            return t("launcher.cloud.hosted_by_old", host=host, version=version, since=since)
        return t("launcher.cloud.hosted_by", host=host, version=version, since=since)

    def watch_host(self) -> None:
        """Who is hosting, asked by the window itself: soon after it opens,
        then every minute (every 15 seconds while someone else hosts),
        while this launcher does not host and nothing else is talking to the
        cloud. Start still asks again before it takes the game, so the delay
        here costs nothing but the wait to see it."""
        try:
            # Not while the welcome has the window hidden; a minimised
            # window still asks, so what it shows is true when it comes back.
            if (self.settings.cloud_ready and not self.access_lost and not self.server.running
                    and self.record is None and not self.cloud_busy and not self.watching
                    and self.root.state() != "withdrawn"):
                self.check_host(quiet=True)
            self.watch_id = self.root.after(WATCH_HOSTED_MS if self.other is not None else WATCH_EVERY_MS,
                                            self.watch_host)
        except tk.TclError:
            pass                            # the window is gone

    def check_host(self, quiet: bool = False) -> None:
        """Who holds the record right now, without claiming it; and what
        the table's file says. Quiet, it is `watch_host`'s: no "Asking"
        line, and it never holds Start back."""
        if self.cloud_busy or (quiet and self.watching):
            return
        if quiet:
            self.watching = True
        else:
            self.cloud_busy = True
            self.set_status(t("launcher.cloud.checking"), "busy")
        # Only the quick checks while someone else hosts may keep the table's
        # file read less than TABLE_EVERY_S ago: what they show needs only who
        # hosts. With nobody hosting it is read every time, for `probe_idle`.
        fresh = (not quiet or self.other is None or self.table is None
                 or time.monotonic() - self.table_read_at >= TABLE_EVERY_S)
        kept, kept_entries = self.table, self.entries

        def work() -> None:
            try:
                client = self.cloud_client()
                record = sync.read_record(client)
                table = sync.read_table(client) if fresh else kept
                entries = sync.read_launchers(client)[0] if fresh else kept_entries
            except Exception as error:
                # Any failure, not only Dropbox's own: an outage during the
                # token's refresh comes as a bare URLError, and a check that
                # dies here would leave Start, or the minute's check, waiting.
                err = error
                self.post(lambda: self.cloud_failed(err, quiet))
                return
            self.post(lambda: self.checked(record, table, quiet, fresh, entries))

        threading.Thread(target=work, daemon=True).start()

    def checked(self, record: sync.HostRecord | None, table: sync.TableRecord | None = None,
                quiet: bool = False, fresh: bool = True, entries: list[dict] | None = None) -> None:
        if quiet:
            self.watching = False
            self.watch_error = ""
            if self.cloud_busy or self.server.running or self.record is not None:
                return                      # a Start came meanwhile: its answer wins
        else:
            self.cloud_busy = False
        self.table = table
        if fresh:
            self.table_read_at = time.monotonic()
            self.entries = entries or []
            believed = self.believed_table(table)
            self.known = sync.known_launchers(believed, self.entries) if believed is not None else {}
            self.settle_pending_key()
            if self.check_seat(table):
                return                      # the seat moved: the box says so
        self.other = record if record is not None and record.held() else None
        speak = not quiet or self.status_about_host
        if self.other is None:
            if speak:
                self.set_status(t("launcher.cloud.nobody"), "quiet", about_host=True)
            if (table is not None and table.air_token and core.web_address(table.air_address)
                    and not self.server.running):
                threading.Thread(target=self.probe_idle, args=(table.air_address,), daemon=True).start()
        else:
            self.alarmed = None
            # "Press Start: this computer hosts the game" is not true while
            # someone else does: that line goes too.
            if speak or self.status.cget("text") == t("launcher.status.stopped"):
                # The Table box says who hosts, and since when: the line under
                # Start does not say it again. Kept as about the host, so it
                # says "nobody" once they stop.
                self.set_status("", "quiet", about_host=True)
        # The box is rebuilt only when what it would say changed: the
        # minute's check must not pull the buttons from under the pointer,
        # nor flicker every 15 seconds while someone else hosts.
        shown = self.box_key()
        if not quiet or shown != self.shown_key:
            self.shown_key = shown
            self.refresh_cloud()

    def box_key(self) -> tuple:
        """What the Table box reads from: who hosts and from where, the
        table's file, and whether the keys still open."""
        other = self.other
        table = self.table
        return ((other.host_id, other.host_name, other.epoch, other.since, other.address, other.app_version,
                 self.holder_known(other))
                if other is not None else None,
                (table.name, table.app_version, table.air_address, table.admin_key, tuple(table.revoked))
                if table is not None else None,
                self.access_lost, self.seat_changed, self.settings.cloud_ready)

    def holder_known(self, record: sync.HostRecord) -> bool:
        """Whether the record was written by a launcher the table vouches
        for: signed by its key, and that key listed. A table from before
        the signatures vouches for nobody and refuses nobody."""
        if self.table is None or self.table.format < 2:
            return True
        return record.verified() and self.known.get(record.host_id) == record.key

    def check_seat(self, table: sync.TableRecord | None) -> bool:
        """What the table file says about the seat, at every read. The
        administrator finding another key on a seat it held is asked,
        once per key: step down (its own Dropbox access revoked and
        forgotten, the window says who took the seat and when), or keep
        the seat here and let Start ask whether to take it back. Nothing
        is given up on the file's word alone: a file naming another seat
        without that seat's signature was rewritten by hand, and is only
        said. One that never held the seat (`cloud.seated` false:
        connected to the table's app on a new PC, Start not pressed yet)
        is only told, and Start asks. A host whose file is no longer
        signed by the administrator it paired with pairs again. True
        when the box was redrawn for either."""
        if table is None or table.format < 2:
            return False
        cloud = self.settings.cloud
        if cloud.get("role") == "admin":
            if table.admin_key and table.admin_key != self.settings.sign_key and not self.server.running \
                    and self.record is None:
                if not table.verified():
                    if self.tampered_said != table.admin_key + table.signature:
                        self.tampered_said = table.admin_key + table.signature
                        self.append_log("cloud: " + self.tampered_text(table))
                    return False
                if cloud.get("seated"):
                    if self.seat_asked == table.admin_key:
                        return False
                    self.seat_asked = table.admin_key
                    if messagebox.askyesno(t("launcher.cloud.seat_title"), self.seat_taken_ask_text(table),
                                           default="no"):
                        self.seat_lost(table)
                        return True
                    # Kept: still the administrator here, and the next
                    # Start asks whether to take the seat back.
                    cloud["seated"] = False
                    self.settings.save()
                    self.append_log("cloud: " + t("launcher.cloud.seat_kept",
                                                  name=table.admin_name or table.admin_id,
                                                  date=table.admin_since[:10]))
                    self.refresh_cloud()
                    return True
                if self.seat_elsewhere_said != table.admin_key:
                    self.seat_elsewhere_said = table.admin_key
                    self.append_log("cloud: " + self.seat_elsewhere_text(table))
            return False
        remembered = int(cloud.get("table_serial") or 0)
        trusted = table.trusted_by(cloud.get("admin_key", "")) and table.serial >= remembered
        if trusted and table.serial > remembered:
            cloud["table_serial"] = table.serial
            self.settings.save()
        if trusted == (not self.seat_changed):
            return False
        self.seat_changed = not trusted
        if self.seat_changed:
            who = table.admin_name or table.admin_id
            self.append_log("cloud: " + t("launcher.cloud.seat_changed", name=who, date=table.admin_since[:10]))
        self.refresh_cloud()
        return True

    def seat_elsewhere(self) -> bool:
        """Another PC holds the administrator's seat, the file signed by
        it, and this launcher does not: nothing is lost here, and the
        next Start asks."""
        table, cloud = self.table, self.settings.cloud
        return (cloud.get("role") == "admin" and not cloud.get("seated") and table is not None
                and table.format >= 2 and bool(table.admin_key)
                and table.admin_key != self.settings.sign_key and table.verified())

    def seat_elsewhere_text(self, table: sync.TableRecord) -> str:
        return t("launcher.cloud.seat_elsewhere", name=table.admin_name or table.admin_id,
                 date=table.admin_since[:10])

    def seat_taken_ask_text(self, table: sync.TableRecord) -> str:
        return t("launcher.cloud.seat_taken_ask", name=table.admin_name or table.admin_id,
                 date=table.admin_since[:10], fingerprint=sync.fingerprint(table.admin_key))

    def table_tampered(self) -> bool:
        """A table file naming another seat without that seat's signature:
        rewritten by whoever holds the folder's key."""
        table = self.table
        return (self.settings.cloud.get("role") == "admin" and table is not None and table.format >= 2
                and bool(table.admin_key) and table.admin_key != self.settings.sign_key
                and not table.verified())

    def tampered_text(self, table: sync.TableRecord) -> str:
        return t("launcher.cloud.table_tampered", name=table.admin_name or table.admin_id,
                 date=table.admin_since[:10], fingerprint=sync.fingerprint(table.admin_key))

    def restore_table(self, table: sync.TableRecord) -> bool:
        """The table's signed fields back from the record of what this
        launcher last signed (`cloud.table_body`, kept by `sign_table`):
        for a file that names this seat without its signature, rewritten
        by hand or by a launcher from before 2.2.0. False without a record
        of this seat; the caller then asks, or stops."""
        body = self.settings.cloud.get("table_body")
        if not isinstance(body, dict) or not body:
            return False
        admin = body.get("admin") if isinstance(body.get("admin"), dict) else {}
        if str(admin.get("key", "")) != self.settings.sign_key:
            return False
        table.format = max(int(body.get("format") or sync.TABLE_FORMAT), sync.TABLE_FORMAT)
        for name in ("table_id", "name", "app_version", "air_address"):
            setattr(table, name, str(body.get(name, "")))
        table.air_token = str(self.settings.cloud.get("table_air_token", ""))
        for name in ("air_generation", "access_generation", "signed_since"):
            setattr(table, name, int(body.get(name) or 0))
        table.admin_id, table.admin_name = str(admin.get("host_id", "")), str(admin.get("name", ""))
        table.admin_key, table.admin_since = self.settings.sign_key, str(admin.get("since", ""))
        table.revoked = [str(r) for r in (body.get("revoked") or [])]
        table.serial = int(body.get("serial") or 0)
        return True

    def stale_table(self, table: sync.TableRecord) -> bool:
        """A file signed by this launcher, but earlier than what it last
        signed: written back by whoever holds the folder's key, to undo a
        strike-off, a token or the keys' generation. It verifies; only the
        serial says it is old."""
        body = self.settings.cloud.get("table_body")
        return (isinstance(body, dict) and bool(body) and table.format >= 2
                and table.admin_key == self.settings.sign_key and table.verified()
                and table.serial < int(body.get("serial") or 0))

    def believed_table(self, table: sync.TableRecord | None) -> sync.TableRecord | None:
        """The table the box and the known launchers go by: the file, or,
        for an administrator reading an earlier file of its own written
        back (`stale_table`), the record of what it last signed, said
        once; the next Start rewrites the file from it. A verified own
        file read before any record exists starts the record: the look
        comes before Start, and the first file read is the one believed."""
        if table is None or self.settings.cloud.get("role") != "admin":
            return table
        if table.format >= 2 and table.admin_key == self.settings.sign_key and table.verified():
            if not self.settings.cloud.get("table_body"):
                self.remember_table(table)
                self.settings.save()
            elif self.stale_table(table):
                if self.stale_said != table.signature:
                    self.stale_said = table.signature
                    self.append_log("cloud: " + t("launcher.cloud.table_stale_seen"))
                believed = dataclasses.replace(table)
                self.restore_table(believed)
                return believed
        return table

    def sign_table(self, client, table: sync.TableRecord, host_name: str, seed: bytes | None) -> sync.TableRecord:
        """Every write of the table by the administrator: signed, and what
        was signed kept in the settings, so a file that comes back without
        the signature can be rebuilt from here (`restore_table`)."""
        table = sync.write_table(client, table, by=host_name, seed=seed)
        if seed is not None and table.format >= 2:
            self.remember_table(table)
            self.post(self.settings.save)
        return table

    def remember_table(self, table: sync.TableRecord) -> None:
        """What the file says under this launcher's signature, in the
        settings: the token apart, which is a secret and goes to the vault
        with the other secrets of `cloud` (`Settings.SECRET_FIELDS`)."""
        body = table.signing_body()
        self.settings.cloud["table_air_token"] = str(body.pop("air_token", ""))
        self.settings.cloud["table_body"] = body

    def own_table(self, client, table: sync.TableRecord | None = None) -> sync.TableRecord:
        """The table's file for an administrator's write (the token, the
        keys, a strike-off): read, and when it names this seat without
        its signature, rebuilt from this launcher's record. A file naming
        another seat, or this one without a record to rebuild from, is
        `TableRefused`: those writes are Start's to sort out, which asks."""
        if table is None:
            table = sync.read_table(client)
        if table is None:
            raise TableRefused(t("launcher.cloud.table_missing"))
        if table.format >= 2 and not table.verified():
            if table.admin_key != self.settings.sign_key:
                raise TableRefused(self.tampered_text(table))
            if not self.restore_table(table):
                raise TableRefused(t("launcher.cloud.table_unsigned_refused"))
            self.post(lambda: self.append_log("cloud: " + t("launcher.cloud.table_restored")))
        elif self.stale_table(table):
            self.restore_table(table)
            self.post(lambda: self.append_log("cloud: " + t("launcher.cloud.table_stale")))
            table = self.sign_table(client, table, self.settings.identity()[1], self.settings.seed())
        return table

    def inherit(self, client, table: sync.TableRecord, host_name: str, seed: bytes | None,
                final: bool = False) -> sync.TableRecord:
        """After a seat taken from another PC (`inherit_from`): the copies in
        the folder signed by a launcher the old seat vouched for go on this
        seat's list (`TableRecord.inherited`), and the hosts the old seat
        vouched for are admitted again under this one; the old launcher
        itself is not, so what it uploads from now on is nobody's. Called at
        the seat, and once more after the claim (`final`), for the last copy
        a hand-over brings; a crash in between leaves the next Start to do
        it, since the file then names this seat with no list."""
        if self.inherit_from is None:
            return table
        old_admin, before = self.inherit_from
        host_id = self.settings.host_id
        admitted = 0
        if seed is not None:
            self.post(lambda: self.set_status(t("launcher.cloud.readmitting"), "busy"))
            entries = sync.read_launchers(client)[0]
            by_id = {str(e.get("host_id", "")): e for e in entries}
            for other, key in before.items():
                if other in (old_admin, host_id) or other in table.revoked:
                    continue
                entry = by_id.get(other)
                if entry is None or entry.get("admitted_by") == host_id:
                    continue
                sync.add_launcher(client, sync.make_admission(seed, host_id, other, str(entry.get("name", "")), key))
                admitted += 1
        # The copies listed already (by the old seat, or by this one at the
        # seat) are not read again: after the claim only the new ones are.
        found = sync.inherit_copies(client, before, into=core.game_folder() / "cloud",
                                    log=lambda m: self.events.put(("line", f"cloud: {m}")),
                                    skip=set(table.inherited),
                                    progress=lambda done, total, name: self.post(
                                        lambda: self.set_status(t("launcher.cloud.inheriting", done=done,
                                                                  total=total, name=name), "busy")))
        new = {name: hashes for name, hashes in found.items() if table.inherited.get(name) != hashes}
        if new:
            table.inherited.update(new)
            table = self.sign_table(client, table, host_name, seed)
        if new or admitted:
            self.post(lambda: self.append_log("cloud: " + t("launcher.cloud.inherited", copies=len(new),
                                                             hosts=admitted)))
        if final:
            self.inherit_from = None
        return table

    def seat_lost(self, table: sync.TableRecord) -> None:
        who, date = table.admin_name or table.admin_id, table.admin_since[:10]
        try:
            self.cloud_client().revoke()    # our own access, not the hosts'
        except Exception as error:
            self.append_log(t("launcher.log.cloud_revoke_failed", error=error))
        self.settings.left_table = {"table": table.name or str(self.settings.cloud.get("table", "")),
                                    "name": who, "date": date,
                                    "app_key": str(self.settings.cloud.get("app_key", ""))}
        self.settings.cloud = {}
        self.settings.token = ""
        self.settings.save()
        self.other = None
        self.table = None
        self.known = {}
        self.entries = []
        # Said once, in the box (`left_table`), until this launcher joins a
        # table again; the log keeps the line. No popup, no status line.
        self.append_log("cloud: " + t("launcher.cloud.seat_taken", name=who, date=date))
        self.set_status(t("launcher.status.stopped"), "quiet")
        self.refresh_cloud()

    def probe_idle(self, address: str) -> None:
        """Nobody hosts, says the record: does anything answer at the
        table's address all the same? The relay serves a 404 when no program
        is connected, so an answer means somebody else holds the token, and
        the table should know."""
        if core.address_state(address, "") != "none" and not self.server.running:
            self.post(lambda: self.idle_alarm(address))

    def idle_alarm(self, address: str) -> None:
        if self.alarmed == address:
            return                          # said already; the minute's check must not nag
        self.alarmed = address
        text = t("launcher.cloud.address_idle", address=address)
        self.append_log(f"cloud: {text}")
        self.set_status(text, "bad")
        messagebox.showwarning(t("launcher.cloud.address_other_title"), text)

    def cloud_failed(self, error: Exception, quiet: bool = False) -> None:
        if quiet:
            # The minute's check: a lost access is a state and is shown; an
            # outage goes to the log once, and Start will say it if it lasts.
            self.watching = False
            if self.note_lost_access(error):
                return
            if str(error) != self.watch_error:
                self.watch_error = str(error)
                self.append_log(f"cloud: {error}")
            return
        self.cloud_busy = False
        self.append_log(f"cloud: {error}")
        if self.note_lost_access(error):
            return
        self.set_status(t("launcher.cloud.unreachable", error=error), "bad")
        self.refresh_cloud()

    def note_lost_access(self, error: Exception) -> bool:
        """Dropbox refusing our refresh token (`invalid_grant`) means the
        administrator rotated the cloud access: not an outage, a state."""
        detail = getattr(error, "error", None) or {}
        refused = (isinstance(detail, dict) and detail.get("error") == "invalid_grant") \
            or "invalid_grant" in str(error)
        if not refused:
            return False
        self.access_lost = True
        admin = self.settings.cloud.get("role") == "admin"
        self.set_status(t("launcher.cloud.access_lost_admin" if admin else "launcher.cloud.rotated_out"), "bad")
        self.refresh_cloud()
        return True

    def claim_then_start(self, force: bool = False, handover: bool = False) -> None:
        """The claim, the pull and only then the server — in a thread, the
        window told at each step. `handover`: the current host is asked for
        the game first, and the claim waits for their last copy."""
        self.cloud_busy = True
        self.start_button.config(state="disabled")
        self.set_status(t("launcher.cloud.claiming"), "busy")
        host_id, host_name = self.settings.identity()
        self.settings.save()
        assets_dir = config.ASSETS_DIR

        def say(text: str) -> None:
            self.post(lambda: self.set_status(text, "busy"))

        def cloud_log(m: str) -> None:
            self.events.put(("line", f"cloud: {m}"))

        def work() -> None:
            try:
                client = self.cloud_client()
                current = sync.read_record(client)
                if (current is not None and current.held() and current.host_id == host_id
                        and not self.hosted_before and not force):
                    # Our own identity, alive, and this process never held
                    # it: a crash and a restart, or a copied game folder on
                    # another PC. Only the person knows which.
                    age = int(current.age)
                    if not self.ask(lambda: messagebox.askyesno(
                            t("launcher.cloud.title"), t("launcher.cloud.same_identity", age=age))):
                        self.post(self.cancelled)
                        return
                # The table's file: the version every host must run, and
                # the token for this start. Nothing is claimed on a
                # mismatch: the way on is to install, or (the
                # administrator) to move the table.
                try:
                    table = self.settle_table(client, host_name)
                except SeatChanged as changed:
                    moved = changed
                    self.post(lambda: self.seat_refused(moved))
                    return
                except TableRefused as refused:
                    why = refused
                    self.post(lambda: self.table_refused(why))
                    return
                # The seat held, the table's id: kept now, not at the next save.
                self.post(self.settings.save)
                entries = sync.read_launchers(client)[0]
                known = sync.known_launchers(table, entries)
                self.post(lambda: self.learn_launchers(entries, known))
                move = False
                if table.mismatch():
                    decision = self.ask(lambda: self.version_dialog(table))
                    if decision == "install":
                        wanted = table.app_version
                        self.post(lambda: self.install_version(wanted))
                        return
                    if decision != "move":
                        self.post(self.cancelled)
                        return
                    move = True
                token = table.air_token or self.settings.token.strip()
                # `take`, not `force`: an assignment to the outer name here
                # would make it local to this thread's function from its
                # first line, and the read above would fail.
                take = force
                if handover:
                    decided = self.hand_over_wait(client, host_id, host_name, say)
                    if decided is None:
                        self.post(self.cancelled)
                        return
                    take = decided
                record = sync.claim(client, host_id, host_name, force=take,
                                    seed=self.settings.seed(), key=self.settings.sign_key)
                if self.inherit_from is not None:
                    # The seat was just taken: the copies in the folder now,
                    # the last one of a hand-over included, go on the list.
                    table = self.inherit(client, table, host_name, self.settings.seed(), final=True)
                    entries = sync.read_launchers(client)[0]
                    known = sync.known_launchers(table, entries)
                    self.post(lambda: self.learn_launchers(entries, known))
                    self.table = table
                say(t("launcher.cloud.pulling"))
                try:
                    pulled = sync.newest_usable(client, core.game_folder() / "cloud",
                                                log=cloud_log, record=record,
                                                trusted=known if table.format >= 2 else None,
                                                inherited=table.inherited if table.format >= 2 else None)
                except sync.NewerCopy as newer:
                    sync.release(client, record)
                    found = newer
                    self.post(lambda: self.claim_failed_newer(found))
                    return
                loaded = None
                local = core.local_state()
                if pulled is not None:
                    marks = sync.marks_of(pulled)
                    keep_mine = False
                    if marks > local.marks:
                        if local.diverged:
                            # Both sides moved on: the cloud since we last
                            # matched it, this file since then too. Asked,
                            # never decided here.
                            name, when = pulled.name, local.forked_at
                            choice = self.ask(lambda: self.fork_dialog(name, when))
                            if choice == "cancel":
                                sync.release(client, record)
                                self.post(self.cancelled)
                                return
                            keep_mine = choice == "mine"
                        if not keep_mine:
                            say(t("launcher.cloud.loading", name=pulled.name))
                            core.load_save(pulled)
                            loaded = pulled.name
                    wanted = bundle_manifest(pulled).get("assets") or {}
                    if wanted:
                        sync.pull_assets(client, assets_dir, wanted, log=cloud_log)
                    record.seq = max(record.seq, marks[1] if marks[0] == record.epoch - 1 else record.seq)
                if local.forked_at:
                    core.mark_fork("")           # the fork is settled either way
                if move:
                    # Only now, with the newest copy read: a move down that
                    # could not read it stopped above, the table untouched.
                    # Signed, as every write of the administrator's: the
                    # write changes `set_at`, which the signature covers.
                    table.app_version = __version__
                    self.sign_table(client, table, host_name, self.settings.seed())
                    self.post(lambda: self.append_log(
                        "cloud: " + t("launcher.cloud.version.moved", version=__version__)))
                self.post(lambda: self.claimed(record, loaded, token))
            except sync.Held as held:
                other = held.record
                self.post(lambda: self.refused(other))
            except dropbox.DropboxError as error:
                err = error
                self.post(lambda: self.claim_failed(err))
            except Exception as error:      # a bad copy, a full disk: shown, never a crash
                err = error
                self.post(lambda: self.claim_failed(err))

        threading.Thread(target=work, daemon=True).start()

    def settle_table(self, client, host_name: str) -> sync.TableRecord:
        """The table's file, read or created, the seat settled, and the
        token put where it belongs. Called from the claim thread.

        The administrator: creates the file with its seat, upgrades a file
        from 1.x (format 1) to a signed one, or, finding another seat on
        it, asks whether to take it (the other PC steps down at its next
        look; every host pairs again) and raises `SeatChanged` on no. Its
        local token goes into the file (a renewal made while the cloud was
        away arrives this way).
        A host: the file must be signed by the administrator it paired
        with, else `SeatChanged`; hosts write nothing here any more."""
        cloud = self.settings.cloud
        admin = cloud.get("role") == "admin"
        local = self.settings.token.strip()
        name = cloud.get("table") or "Kingmaker"
        host_id, _name = self.settings.identity()
        seed, key = self.settings.seed(), self.settings.sign_key
        if admin:
            table, created = sync.ensure_table(client, name, token=local, by=host_name,
                                               admin=(host_id, host_name, key), seed=seed)
            changed = False
            if created:
                self.post(lambda: self.append_log(t("launcher.log.table_created", version=table.app_version)))
            elif table.format < 2:
                # A table from 1.x: the seat is ours. Its copies from before
                # the signatures are not loaded again: the first Start here
                # uploads a signed one.
                current = sync.read_record(client)
                sync.take_seat(table, host_id, host_name, key, (current.epoch if current else 0) + 1)
                changed = True
                self.post(lambda: self.append_log(t("launcher.log.table_upgraded")))
            elif not table.verified():
                # The file does not carry the signature of the seat it
                # names. Another seat's: rewritten by hand, nothing is taken
                # from it. Ours: rebuilt from what this launcher last signed,
                # or, without such a record (a launcher from before 2.2.0
                # wrote it, which left the signature behind), signed as it is
                # on the person's word.
                if table.admin_key != key:
                    raise TableRefused(self.tampered_text(table))
                if self.restore_table(table):
                    self.post(lambda: self.append_log("cloud: " + t("launcher.cloud.table_restored")))
                elif not self.ask(lambda: messagebox.askyesno(
                        t("launcher.cloud.seat_title"),
                        t("launcher.cloud.table_unsigned_ours", struck=len(table.revoked),
                          generation=table.air_generation), default="no")):
                    raise TableRefused(t("launcher.cloud.table_unsigned_refused"))
                changed = True
            elif self.stale_table(table):
                # An earlier file of ours written back: the record wins,
                # and the file is written again from it.
                self.restore_table(table)
                self.post(lambda: self.append_log("cloud: " + t("launcher.cloud.table_stale")))
                changed = True
            elif table.admin_key != key:
                # Another PC's seat, the file signed by it: asked, with that
                # launcher's key to compare with what it shows. Yes takes the
                # seat; the copies the old seat vouched for are listed as the
                # table's and its hosts admitted again (`inherit`), the old
                # launcher itself vouched for no more.
                who, since = table.admin_name or table.admin_id, table.admin_since[:10]
                shown = sync.fingerprint(table.admin_key)
                if not self.ask(lambda: messagebox.askyesno(
                        t("launcher.cloud.seat_title"),
                        t("launcher.cloud.seat_take_confirm", name=who, date=since, fingerprint=shown),
                        default="no")):
                    raise SeatChanged(who, since)
                entries = sync.read_launchers(client)[0]
                self.inherit_from = (table.admin_id, sync.known_launchers(table, entries))
                sync.take_seat(table, host_id, host_name, key, table.signed_since or 1)
                changed = True
                self.post(lambda: self.append_log(t("launcher.cloud.seat_taken_here", name=who)))
            if local and local != table.air_token:
                table.air_token = local
                table.air_generation += 1
                changed = True
            if changed:
                table = self.sign_table(client, table, host_name, seed)
            elif table.format >= 2 and not self.settings.cloud.get("table_body"):
                # Signed by us and nothing to write: the record of it starts
                # here, for the day the file comes back without the signature.
                self.remember_table(table)
            if self.inherit_from is not None:
                table = self.inherit(client, table, host_name, seed)
            if local and table.air_token:
                self.post(self.token_moved)
            cloud["admin_key"] = key
            # Created, upgraded, taken, or ours already: from here the look
            # finding another key on the seat means it was taken from us.
            cloud["seated"] = True
        else:
            table = sync.read_table(client)
            if table is None:
                raise SeatChanged("", "")
            remembered = int(cloud.get("table_serial") or 0)
            if not table.trusted_by(cloud.get("admin_key", "")) or table.serial < remembered:
                raise SeatChanged(table.admin_name or table.admin_id, table.admin_since[:10])
            if table.serial > remembered:
                cloud["table_serial"] = table.serial
        if table.air_generation:
            self.post(lambda: self.append_log(
                t("launcher.log.token_generation", generation=table.air_generation)))
        if table.name:
            cloud["table"] = table.name
        # The server hands the table's id out with the credential at pairing,
        # and the joining launcher checks it against the folder.
        cloud["table_id"] = table.table_id
        self.table = table
        return table

    def token_moved(self) -> None:
        """The token is in the table's folder now: forgotten here, said once."""
        self.settings.token = ""
        self.token_var.set("")
        self.settings.save()
        self.append_log("cloud: " + t("launcher.cloud.token_moved"))
        self.refresh_air()

    def ask(self, fn):
        """Runs `fn` on the Tk thread and waits for what it returns: a
        question asked by a thread that may not touch the widgets. Never
        to be called from the Tk thread itself, which would wait for its
        own answer."""
        done = threading.Event()
        answer: list = []

        def run() -> None:
            try:
                answer.append(fn())
            finally:
                done.set()

        self.post(run)
        done.wait()
        return answer[0] if answer else None

    def choose(self, title: str, text: str, options: list[tuple[str, str]]) -> str:
        """A question with its answers as buttons, one under the other, on
        the Tk thread: the value of the one pressed, or the last option's
        when the window is closed instead."""
        win = tk.Toplevel(self.root, class_=core.WM_CLASS)
        win.withdraw()                      # shown by screen.present, sized and placed
        win.title(title)
        win.transient(self.root)
        answer = [options[-1][1]]

        def pick(what: str) -> None:
            answer[0] = what
            win.destroy()

        ttk.Label(win, text=text, wraplength=460, justify="left").pack(padx=16, pady=(14, 10))
        for label, what in options:
            ttk.Button(win, text=label, command=lambda w=what: pick(w)).pack(fill="x", padx=16, pady=3)
        ttk.Frame(win, height=10).pack()
        win.protocol("WM_DELETE_WINDOW", lambda: pick(options[-1][1]))
        screen.present(win, grab=True)
        self.root.wait_window(win)
        return answer[0]

    def fork_dialog(self, name: str, forked_at: str) -> str:
        """Which copy is the game: the cloud's, newer, or this PC's, played
        on since. Answers "cloud", "mine" or "cancel"."""
        when = t("launcher.cloud.fork.when", date=forked_at) if forked_at else ""
        return self.choose(t("launcher.cloud.fork.title"),
                           t("launcher.cloud.fork.text", name=name, when=when),
                           [(t("launcher.cloud.fork.keep_cloud"), "cloud"),
                            (t("launcher.cloud.fork.keep_mine"), "mine"),
                            (t("launcher.cloud.fork.cancel"), "cancel")])

    def version_dialog(self, table: sync.TableRecord) -> str:
        """The table plays on another version: "install" it, or (the
        administrator) "move" the table to this one, or "cancel"."""
        admin = self.settings.cloud.get("role") == "admin"
        mine, theirs = __version__, table.app_version
        title = t("launcher.cloud.version.title")
        install = (t("launcher.cloud.version.install", version=theirs), "install")
        move = (t("launcher.cloud.version.move", mine=mine), "move")
        cancel = (t("common.cancel"), "cancel")
        if admin and core.is_newer(mine, theirs):
            return self.choose(title, t("launcher.cloud.version.move_text", table=theirs, mine=mine),
                               [move, install, cancel])
        if admin:
            return self.choose(title, t("launcher.cloud.version.move_down_text", table=theirs, mine=mine),
                               [install, move, cancel])
        return self.choose(title, t("launcher.cloud.version.mismatch", table=theirs, mine=mine),
                           [install, cancel])

    def install_version(self, version: str) -> None:
        """The table's version, from GitHub, over this copy: nothing was
        claimed, the game folder is kept."""
        self.cloud_busy = False
        self.record = None
        self.start_button.config(state="normal")
        self.set_status(t("launcher.cloud.version.status", table=version, mine=__version__), "bad")
        self.refresh_cloud()

        def work() -> None:
            release = core.find_release(version)
            self.post(lambda: self.install_found(version, release))

        threading.Thread(target=work, daemon=True).start()

    def install_found(self, version: str, release: core.Release | None) -> None:
        if release is None:
            messagebox.showinfo(t("launcher.cloud.version.title"),
                                t("launcher.cloud.version.no_release", version=version))
            return
        self.download_update(release)

    def cancelled(self) -> None:
        """The person said no at one of the questions: nothing was taken."""
        self.cloud_busy = False
        self.record = None
        self.start_button.config(state="normal")
        self.set_status(t("launcher.cloud.cancelled"), "quiet")
        self.refresh_cloud()

    def claim_failed_newer(self, newer: sync.NewerCopy) -> None:
        """The cloud's newest copy comes from a newer app: nothing was
        loaded, the record was released, and the way on is to install it."""
        self.cloud_busy = False
        self.record = None
        self.start_button.config(state="normal")
        self.append_log(f"cloud: {newer}")
        self.set_status(t("launcher.cloud.newer_copy_status", app=newer.app or "?"), "bad")
        self.refresh_cloud()
        if messagebox.askyesno(t("launcher.cloud.title"), t(
                "launcher.cloud.newer_copy", app=newer.app or "?", version=newer.version,
                mine=newer.mine, name=newer.name)):
            self.open_versions()

    def claimed(self, record: sync.HostRecord, loaded: str | None, token: str | None = None) -> None:
        self.cloud_busy = False
        self.hosted_before = True
        self.offline = False
        self.token_for_start = token
        self.record = record
        self.other = None
        if loaded:
            self.append_log(t("launcher.log.cloud_loaded", what=loaded))
        self.refresh_cloud()
        self.start_server()

    def refused(self, record: sync.HostRecord) -> None:
        self.cloud_busy = False
        self.other = record
        self.start_button.config(state="normal")
        self.set_status("", "quiet", about_host=True)   # the Table box says who hosts
        self.refresh_cloud()

    def claim_failed(self, error: Exception) -> None:
        self.cloud_busy = False
        self.start_button.config(state="normal")
        self.append_log(f"cloud: {error}")
        if self.note_lost_access(error):
            return
        if messagebox.askyesno(t("launcher.cloud.title"), t("launcher.cloud.host_without", error=error)):
            self.record = None
            self.offline = True
            self.token_for_start = None
            try:
                core.mark_fork(time.strftime("%Y-%m-%d"))
            except Exception as marking:     # a database that cannot be opened: the server will say
                self.append_log(f"cloud: {marking}")
            self.start_server()
        else:
            self.set_status(t("launcher.cloud.unreachable", error=error), "bad")

    def take_over(self) -> None:
        """The administrator asks the current host for the game: they
        upload their last copy and stop, and the game starts here with it.
        Only when they do not answer is it taken by force, and only after
        asking again (`hand_over_wait`)."""
        host = (self.other.host_name or self.other.host_id) if self.other is not None else ""
        if not messagebox.askyesno(t("launcher.cloud.take_over"),
                                   t("launcher.cloud.take_over_confirm", host=host)):
            return
        self.start(handover=True)

    def hand_over_wait(self, client, host_id: str, host_name: str, say) -> bool | None:
        """On the worker thread: asks the holder, waits for their last copy,
        and when they do not answer asks the person what to do. False: the
        record is free, claim it; True: take it by force; None: cancelled."""
        asked = sync.request_handover(client, host_id, host_name)
        if asked is None:
            return False                    # nobody holds it, or we do: the claim is free
        holder = asked.host_name or asked.host_id
        self.events.put(("line", "cloud: " + t("launcher.cloud.handover_asked", host=holder)))
        while True:
            if sync.wait_for_release(client, asked.host_id, timeout=HANDOVER_WAIT_S,
                                     progress=lambda waited: say(t("launcher.cloud.handover_waiting",
                                                                   host=holder, seconds=int(waited)))):
                return False
            choice = self.ask(lambda: self.choose(
                t("launcher.cloud.handover_title"), t("launcher.cloud.handover_timeout", host=holder),
                [("take", t("launcher.cloud.handover_take")), ("wait", t("launcher.cloud.handover_wait")),
                 ("cancel", t("common.cancel"))]))
            if choice == "take":
                return True
            if choice != "wait":
                return None

    def begin_hosting(self) -> None:
        """The server is up: keep the record alive and upload the game."""
        if self.record is None or self.hoster is None and self.server.port is None:
            return
        if self.hoster is not None:
            return
        local = sync.LocalServer(self.server.port or 0, self.server.secret)
        self.hoster = sync.Hoster(self.cloud_client(), self.record, local, config.ASSETS_DIR,
                                  on_event=lambda kind, text: self.events.put(("cloud", (kind, text))),
                                  on_taken_over=lambda: self.events.put(("taken", None)),
                                  on_handed=lambda name: self.events.put(("handed", name)),
                                  seed=self.settings.seed(), key=self.settings.sign_key)
        self.hoster.start()

    def handle_cloud(self, kind: str, text: str) -> None:
        if kind == "uploaded":
            self.append_log(t("launcher.log.cloud_uploaded", what=text))
            if self.stop_thread is not None:
                # The last copy of a Stop: the record's release and the
                # server's shutdown still follow, so the bar stays.
                self.set_status(t("launcher.status.stopping"), "busy")
            else:
                self.set_status(t("launcher.cloud.uploaded", name=text), "ok")
        elif kind == "error":
            self.append_log(f"cloud: {text}")
            self.set_status(t("launcher.cloud.upload_failed", error=text), "busy", working=False)

    def handle_taken(self) -> None:
        """The administrator took the game: stop without a final upload."""
        self.hoster = None
        self.record = None
        self.server.stop()
        self.reflect_running()
        self.set_status(t("launcher.cloud.taken"), "bad")
        messagebox.showinfo(t("launcher.cloud.title"), t("launcher.cloud.taken"))
        self.check_host()

    def handle_handed(self, name: str) -> None:
        """We handed the game over: the hoster uploaded the last copy and
        released the record already; the server stops now, nothing lost."""
        self.hoster = None
        self.record = None
        self.server.stop()
        self.reflect_running()
        text = t("launcher.cloud.handed", name=name)
        self.append_log(f"cloud: {text}")
        self.set_status(text, "ok")
        messagebox.showinfo(t("launcher.cloud.title"), text)
        self.check_host()

    def drop_record(self) -> None:
        if self.record is not None:
            try:
                sync.release(self.cloud_client(), self.record)
            except Exception:
                pass
            self.record = None
            self.refresh_cloud()

    def open_wizard(self) -> None:
        wizard.SetupWizard(self.root, self.settings, on_done=self.refresh_cloud, post=self.post)

    def open_welcome(self) -> None:
        """The first run's questions: at the first start, and after a reset
        of the setup. Not while the game runs: the answers change where it is
        played."""
        if self.server.running:
            messagebox.showinfo(core.APP_NAME, t("launcher.load_save.stop_first"))
            return
        wizard.WelcomeWizard(self.root, self.settings, on_done=self.welcomed, post=self.post,
                             on_quit=self.on_close)

    def welcomed(self) -> None:
        """Everything the welcome may have set, reflected: the mode, the
        token, the table, and the boxes that depend on them."""
        self.mode_var.set(self.settings.mode)
        self.token_var.set(self.settings.token)
        self.access_lost = False
        self.build()                        # the role, or the language, may be another
        self.mode_changed()
        self.refresh_cloud()
        if self.settings.cloud_ready:
            if self.settings.cloud.get("role") == "admin" and self.settings.token.strip():
                threading.Thread(target=self.publish_token, daemon=True).start()
            self.check_host()
        if not self.root.winfo_ismapped():
            screen.present(self.root)       # the first run, or a reset: the welcome came alone

    def reset_setup(self, then: Callable[[], None] | None = None) -> None:
        """For who chose wrong at the first run, or must start again: the
        welcome's answers forgotten, after saying what goes, and the welcome
        alone on screen again. The game and its saves are not touched.
        `then` runs once the person said yes, before the window hides: the
        Settings window closing and saving its fields, not before."""
        if self.server.running or self.record is not None:
            messagebox.showinfo(core.APP_NAME, t("launcher.load_save.stop_first"))
            return
        key = "launcher.reset_setup.confirm_host" if self.settings.host else "launcher.reset_setup.confirm_admin"
        if not messagebox.askyesno(t("launcher.reset_setup.title"), t(key), icon="warning", default="no"):
            return
        # The administrator's keys would otherwise stay valid on every host
        # with nobody left to change them: the same question as Forget.
        if (not self.settings.host and self.settings.cloud_ready and not self.access_lost
                and messagebox.askyesno(t("launcher.reset_setup.title"), t("launcher.cloud.revoke_confirm"))):
            try:
                self.cloud_client().revoke()
            except Exception as error:
                self.append_log(t("launcher.log.cloud_revoke_failed", error=error))
        if then is not None:
            then()
        self.settings.reset_setup()
        self.settings.save()
        self.other = None
        self.table = None
        self.access_lost = False
        self.hosted_before = False
        self.token_for_start = None
        self.token_refused_said = False
        self.alarmed = None
        self.watch_error = ""
        self.table_read_at = 0.0
        self.shown_key = None
        self.mode_var.set(self.settings.mode)
        self.token_var.set(self.settings.token)
        self.root.withdraw()
        self.open_welcome()

    def open_air(self) -> None:
        wizard.AirWizard(self.root, self.settings, on_done=self.air_ready)

    def air_ready(self) -> None:
        self.token_var.set(self.settings.token)
        if (self.settings.cloud_ready and self.settings.cloud.get("role") == "admin"
                and self.settings.token.strip()):
            threading.Thread(target=self.publish_token, daemon=True).start()

    def publish_token(self) -> None:
        """The administrator's new token into the table's folder, so every
        host reads it at its next Start. When the cloud is away the token
        stays here and the next Start carries it (`settle_table`)."""
        host_id, host_name = self.settings.identity()
        token = self.settings.token.strip()
        seed, key = self.settings.seed(), self.settings.sign_key
        try:
            client = self.cloud_client()
            table, _created = sync.ensure_table(client, self.settings.cloud.get("table") or "Kingmaker",
                                                token=token, by=host_name, admin=(host_id, host_name, key),
                                                seed=seed)
            if table.format >= 2 and table.admin_key != key:
                return                      # another seat: the next Start asks about it
            table = self.own_table(client, table)
            if table.air_token != token or table.format < 2:
                if table.format < 2:
                    current = sync.read_record(client)
                    sync.take_seat(table, host_id, host_name, key, (current.epoch if current else 0) + 1)
                table.air_token = token
                table.air_generation += 1
                self.sign_table(client, table, host_name, seed)
        except Exception as error:          # unreachable, refused: kept locally for now
            err = error
            self.post(lambda: self.append_log(f"cloud: {err}"))
            return
        self.settings.cloud["seated"] = True   # created now, upgraded, or ours before
        self.table = table
        self.post(self.token_moved)

    def make_pairing_code(self) -> None:
        """Letting one launcher in (2.2.0): the guided window authorises a
        Dropbox key for that host alone, asks the running game for a code
        that hands it out, and shows the code with the table's address for
        the person to pass on. Not on this computer only: the other
        launcher could not reach the game to use it."""
        if self.local_only():
            messagebox.showinfo(t("launcher.cloud.pair_launcher"), t("launcher.cloud.pair_needs_network"))
            return
        if not (self.server.running and self.record is not None and not self.offline):
            messagebox.showinfo(t("launcher.cloud.pair_launcher"), t("launcher.cloud.pair_needs_hosting"))
            return
        address = self.links.get("air") or self.links.get("lan") or self.links.get("local") or ""
        wizard.PairWizard(self.root, self.settings, server=sync.LocalServer(self.server.port or 0, self.server.secret),
                          address=address, on_done=self.pairing_made, post=self.post)

    def pairing_made(self) -> None:
        """The code is out with its key: the next looks watch for the
        newcomer's admission, to put the key under its name (`settle_pending_key`)."""
        self.append_log("cloud: " + t("launcher.launchers.code_made"))
        self.refresh_cloud()

    def open_pair(self) -> None:
        wizard.PairDialog(self.root, self.settings, on_done=self.paired, post=self.post)

    def paired(self) -> None:
        address = str(self.settings.cloud.get("address", ""))
        if self.settings.host and address:
            # The address says where the table is played: a host's window
            # has no choice of its own.
            self.settings.mode = core.mode_for_address(address)
            self.settings.save()
            self.mode_var.set(self.settings.mode)
        self.access_lost = False
        self.token_var.set(self.settings.token)
        self.refresh_cloud()
        self.check_host()

    def reauthorise(self) -> None:
        """The administrator's own access refused by Dropbox (a lost PC cut
        off, the app disconnected): its key anew, after which every key
        handed out before is dead and every host pairs again (`reauthorised`)."""
        if self.record is not None or self.server.running:
            messagebox.showinfo(t("launcher.cloud.title"), t("launcher.load_save.stop_first"))
            return
        before = str(self.settings.cloud.get("refresh_token", ""))
        wizard.SetupWizard(self.root, self.settings, on_done=lambda: self.reauthorised(before),
                           post=self.post, start="authorise")

    def reauthorised(self, before: str) -> None:
        new = str(self.settings.cloud.get("refresh_token", ""))
        if not new or new == before:
            return                          # the wizard was cancelled: nothing changed
        host_id, host_name = self.settings.identity()
        seed, key = self.settings.seed(), self.settings.sign_key
        self.access_lost = False

        def work() -> None:
            try:
                client = self.cloud_client()
                table = sync.read_table(client)
                if table is not None:
                    if table.format >= 2 and table.admin_key != key and not table.verified():
                        # Another seat on the file without its signature:
                        # not taken on the file's word. Start asks about it.
                        raise TableRefused(self.tampered_text(table))
                    if table.format >= 2 and table.admin_key == key:
                        table = self.own_table(client, table)
                    if table.format < 2 or table.admin_key != key:
                        if table.format >= 2:
                            # Another PC's seat, signed by it: asked, as at
                            # Start, with its key to compare; yes admits it.
                            who, since = table.admin_name or table.admin_id, table.admin_since[:10]
                            shown = sync.fingerprint(table.admin_key)
                            if not self.ask(lambda: messagebox.askyesno(
                                    t("launcher.cloud.seat_title"),
                                    t("launcher.cloud.seat_take_confirm", name=who, date=since,
                                      fingerprint=shown), default="no")):
                                raise TableRefused(self.seat_elsewhere_text(table))
                            entries = sync.read_launchers(client)[0]
                            self.inherit_from = (table.admin_id, sync.known_launchers(table, entries))
                        current = sync.read_record(client)
                        sync.take_seat(table, host_id, host_name, key, (current.epoch if current else 0) + 1)
                    table.access_generation += 1
                    table = self.sign_table(client, table, host_name, seed)
                    if self.inherit_from is not None:
                        table = self.inherit(client, table, host_name, seed, final=True)
                    self.settings.cloud["seated"] = True
                # Every key handed out under the old access died with it.
                self.settings.host_keys = {}
                self.settings.pending_key = {}
                self.settings.cloud.pop("hosts_refresh_token", None)
            except Exception as error:
                err = error
                self.post(lambda: self.append_log(t("launcher.cloud.rotate_failed", error=err)))
                self.post(lambda: messagebox.showwarning(
                    t("launcher.cloud.reauthorise"), t("launcher.cloud.rotate_failed", error=err)))
                return
            self.post(self.settings.save)
            self.post(lambda: self.append_log("cloud: " + t("launcher.cloud.rotated")))
            self.post(lambda: messagebox.showinfo(t("launcher.cloud.reauthorise"), t("launcher.cloud.rotated")))

        self.refresh_cloud()
        threading.Thread(target=work, daemon=True).start()

    def forget_cloud(self) -> None:
        if self.record is not None or self.server.running:
            messagebox.showinfo(t("launcher.cloud.title"), t("launcher.load_save.stop_first"))
            return
        if not messagebox.askyesno(t("launcher.cloud.forget"), t("launcher.cloud.forget_confirm")):
            return
        if (self.settings.cloud.get("role") == "admin" and not self.access_lost and messagebox.askyesno(
                t("launcher.cloud.forget"), t("launcher.cloud.revoke_confirm"))):
            self.revoke_both()
        self.settings.cloud = {}
        self.settings.left_table = {}
        self.other = None
        self.table = None
        self.known = {}
        self.entries = []
        self.access_lost = False
        self.seat_changed = False
        self.settings.save()
        self.refresh_cloud()

    def revoke_both(self) -> None:
        """The administrator's own Dropbox access and the hosts' key, each
        cancelled by a client built on it (Dropbox revokes the caller only)."""
        cloud = self.settings.cloud
        app_key = str(cloud.get("app_key", ""))
        for token in (cloud.get("hosts_refresh_token", ""), cloud.get("refresh_token", "")):
            if not token:
                continue
            try:
                dropbox.Client(dropbox.Credential(app_key=app_key, refresh_token=str(token))).revoke()
            except Exception as error:
                self.append_log(t("launcher.log.cloud_revoke_failed", error=error))

    def learn_launchers(self, entries: list[dict], known: dict[str, str]) -> None:
        self.entries = entries
        self.known = known
        self.settle_pending_key()

    def settle_pending_key(self) -> None:
        """The key authorised for a pairing under way (`Settings.pending_key`)
        goes under the newcomer's id once its admission, made by this
        launcher since the key was, is in the list. A key nobody took within
        the code's life and a margin is cancelled: the code is dead, and a
        key nobody holds is one key too many."""
        pending = self.settings.pending_key
        if not pending or not isinstance(pending, dict):
            return
        mine = self.settings.host_id
        since = str(pending.get("since", ""))
        newcomers = [e for e in self.entries
                     if str(e.get("admitted_by", "")) == mine and str(e.get("host_id", "")) in self.known
                     and str(e.get("host_id", "")) not in self.settings.host_keys
                     and str(e.get("since", "")) >= since]
        if newcomers:
            newest = max(newcomers, key=lambda e: str(e.get("since", "")))
            host_id = str(newest.get("host_id", ""))
            self.settings.host_keys[host_id] = str(pending.get("token", ""))
            self.settings.pending_key = {}
            self.settings.save()
            self.append_log("cloud: " + t("launcher.launchers.key_given", name=newest.get("name") or host_id))
            return
        try:
            age = time.time() - sync._parse_time(since)
        except (ValueError, TypeError):
            age = PENDING_KEY_LIFE_S + 1
        if age > PENDING_KEY_LIFE_S:
            token = str(pending.get("token", ""))
            app_key = str(self.settings.cloud.get("app_key", ""))
            self.settings.pending_key = {}
            self.settings.save()
            self.append_log("cloud: " + t("launcher.launchers.key_unused"))
            if token and app_key:
                threading.Thread(target=lambda: self.revoke_quietly(app_key, token), daemon=True).start()

    def key_taken(self, host_id: str, name: str) -> None:
        """The game says a launcher spent the pairing code (`KM paired`):
        the key waiting for it goes under that id now. The list's look
        (`settle_pending_key`) would do the same, but it only comes after
        Stop, and the pairing happens while hosting."""
        pending = self.settings.pending_key
        if not host_id or not pending or not isinstance(pending, dict):
            return
        self.settings.host_keys[host_id] = str(pending.get("token", ""))
        self.settings.pending_key = {}
        self.settings.save()
        self.append_log("cloud: " + t("launcher.launchers.key_given", name=name or host_id))

    def revoke_quietly(self, app_key: str, token: str) -> None:
        try:
            dropbox.Client(dropbox.Credential(app_key=app_key, refresh_token=token)).revoke()
        except Exception as error:
            err = error
            self.post(lambda: self.append_log(f"cloud: {err}"))

    def seat_refused(self, changed: "SeatChanged") -> None:
        """Start stopped at the table file: the administrator declined the
        seat another PC holds, or a host found the file signed by another
        seat than the one it paired with."""
        self.cloud_busy = False
        self.start_button.config(state="normal")
        if self.settings.cloud.get("role") == "admin":
            self.set_status(t("launcher.cloud.cancelled"), "quiet")
            return
        self.seat_changed = True
        self.table = None
        self.refresh_cloud()

    def table_refused(self, refused: "TableRefused") -> None:
        """Start stopped at the table file: rewritten by hand, or this
        seat's without its signature and not signed on request."""
        self.cloud_busy = False
        self.start_button.config(state="normal")
        self.set_status(t("launcher.cloud.cancelled"), "quiet")
        self.append_log(f"cloud: {refused}")
        messagebox.showwarning(t("launcher.cloud.seat_title"), str(refused))
        self.refresh_cloud()

    def open_launchers(self) -> None:
        """The control room of the table (2.2.0): this launcher and its seat,
        the hosts the table vouches for (each with the key it holds and a
        button to strike it off, which cancels that key alone), the seats
        before this one, and the way out for a lost PC."""
        if self.table is None or self.table.format < 2:
            messagebox.showinfo(t("launcher.launchers.title"), t("launcher.launchers.none"))
            return
        win = tk.Toplevel(self.root, class_=core.WM_CLASS)
        win.withdraw()
        win.title(t("launcher.launchers.title"))
        win.transient(self.root)
        ttk.Button(win, text=t("launcher.settings.close"), command=win.destroy
                   ).pack(side="bottom", pady=(8, 12))
        scroller = screen.Scrolled(win)
        scroller.pack(fill="both", expand=True, padx=16, pady=12)
        body = scroller.inner
        quiet = COLOURS["quiet"]

        def section(title: str, first: bool = False) -> None:
            ttk.Label(body, text=title, font=("TkDefaultFont", 10, "bold")
                      ).pack(anchor="w", pady=(0 if first else 12, 4))

        def line(text: str, colour: str | None = None, pady=(0, 2)) -> None:
            ttk.Label(body, text=text, wraplength=480, justify="left",
                      **({"foreground": colour} if colour else {})).pack(anchor="w", pady=pady)

        # This launcher: its name and key, and the seat.
        section(t("launcher.launchers.section.this"), first=True)
        line(t("launcher.launchers.own", name=self.settings.identity()[1],
               fingerprint=sync.fingerprint(self.settings.sign_key)))
        line(t("launcher.launchers.seat_since", date=self.table.admin_since[:10]), quiet)

        # The hosts, each with the key it holds.
        section(t("launcher.launchers.section.hosts"))
        line(t("launcher.launchers.text"), quiet, pady=(0, 6))
        names = {self.table.admin_id: self.table.admin_name}
        names.update({str(e.get("host_id", "")): str(e.get("name", "")) for e in self.entries})
        listed = [e for e in self.entries if str(e.get("host_id", "")) in self.known]
        if not listed:
            line(t("launcher.launchers.none"), quiet)
        shared_key = bool(self.settings.cloud.get("hosts_refresh_token"))
        on_shared = 0
        # The table knows no roles among the hosts: a launcher is on the seat
        # or let in. One let in after holding the seat is marked so.
        seat_until = {str(s.get("host_id", "")): str(s.get("until", ""))[:10] for s in self.table.seats}
        for entry in listed:
            host_id = str(entry.get("host_id", ""))
            if host_id in self.settings.host_keys:
                kind = "key_own"
            elif shared_key:
                kind, on_shared = "key_shared", on_shared + 1
            else:
                kind = "key_unknown"
            text = (t("launcher.launchers.entry", name=entry.get("name") or host_id,
                      since=str(entry.get("since", ""))[:10],
                      by=names.get(str(entry.get("admitted_by", "")), entry.get("admitted_by", "")))
                    + " · " + t(f"launcher.launchers.{kind}"))
            if host_id in seat_until:
                text += " · " + t("launcher.launchers.held_seat", until=seat_until[host_id])
            row = ttk.Frame(body)
            row.pack(fill="x", pady=3)
            ttk.Label(row, text=text, wraplength=360, justify="left").pack(side="left")
            ttk.Button(row, text=t("launcher.launchers.strike"),
                       command=lambda h=host_id, w=win: self.strike_off(h, w)).pack(side="right")
        if shared_key:
            line(t("launcher.launchers.shared_left", n=on_shared), quiet, pady=(8, 2))
            ttk.Button(body, text=t("launcher.launchers.retire"),
                       command=lambda w=win: self.retire_shared_key(w)).pack(anchor="w")

        # The seats before this one.
        section(t("launcher.launchers.section.former"))
        if not self.table.seats:
            line(t("launcher.launchers.former_none"), quiet)
        for seat in self.table.seats:
            line(t("launcher.launchers.former_entry", name=seat.get("name") or seat.get("host_id") or "?",
                   since=str(seat.get("since", ""))[:10], until=str(seat.get("until", ""))[:10]))
        line(t("launcher.launchers.former_note"), quiet, pady=(4, 0))

        # A lost PC.
        section(t("launcher.launchers.section.lost"))
        line(t("launcher.cloud.row.cut_off"), quiet, pady=(0, 6))
        ttk.Button(body, text=t("launcher.cloud.cut_off"), command=self.cut_off).pack(anchor="w")
        screen.present(win)

    def retire_shared_key(self, win: tk.Toplevel) -> None:
        """The shared hosts' key of 2.0.0, cancelled for good once every host
        has a key of its own: whoever still held it pairs again."""
        if not messagebox.askyesno(t("launcher.launchers.retire"), t("launcher.launchers.retire_confirm"),
                                   default="no"):
            return
        old = str(self.settings.cloud.get("hosts_refresh_token", ""))
        app_key = str(self.settings.cloud.get("app_key", ""))
        host_name = self.settings.identity()[1]
        seed = self.settings.seed()

        def work() -> None:
            try:
                if old:
                    dropbox.Client(dropbox.Credential(app_key=app_key, refresh_token=old)).revoke()
                client = self.cloud_client()
                table = self.own_table(client)
                table.access_generation += 1
                self.sign_table(client, table, host_name, seed)
            except Exception as error:
                err = error
                self.post(lambda: self.append_log(t("launcher.cloud.rotate_failed", error=err)))
                return
            self.settings.cloud.pop("hosts_refresh_token", None)
            self.post(self.settings.save)
            self.post(lambda: self.append_log("cloud: " + t("launcher.launchers.retired")))
            self.post(lambda: win.winfo_exists() and win.destroy())
            self.post(self.refresh_cloud)

        threading.Thread(target=work, daemon=True).start()

    def strike_off(self, host_id: str, win: tk.Toplevel) -> None:
        """Also while hosting: the running game holds no Dropbox key (2.2.0),
        and the table file is the administrator's to write at any time."""
        name = next((str(e.get("name", "")) for e in self.entries if e.get("host_id") == host_id), host_id)
        if not messagebox.askyesno(t("launcher.launchers.title"), t("launcher.launchers.strike_confirm", name=name)):
            return
        admin_id, host_name = self.settings.identity()
        seed = self.settings.seed()
        app_key = str(self.settings.cloud.get("app_key", ""))

        def work() -> None:
            try:
                client = self.cloud_client()
                table = self.own_table(client)
                if host_id not in table.revoked:
                    table.revoked.append(host_id)
                table = self.sign_table(client, table, host_name, seed)
                # Its own key dies with it (2.2.0): a host on the shared key
                # of 2.0.0 keeps that one until the key is retired.
                token = self.settings.host_keys.pop(host_id, "")
                if token:
                    self.post(self.settings.save)
                    try:
                        dropbox.Client(dropbox.Credential(app_key=app_key, refresh_token=token)).revoke()
                    except Exception as error:
                        err = error
                        self.post(lambda: self.append_log(f"cloud: {err}"))
                entries = sync.read_launchers(client)[0]
                # The hosts the struck-off launcher had let in would fall
                # with it: the administrator vouches for them anew, under
                # its own signature. Each stays in the list to strike off
                # on its own if need be.
                if seed is not None:
                    for child in entries:
                        if child.get("admitted_by") == host_id and child.get("host_id") not in table.revoked:
                            sync.add_launcher(client, sync.make_admission(
                                seed, admin_id, str(child.get("host_id", "")), str(child.get("name", "")),
                                str(child.get("key", ""))))
                    entries = sync.read_launchers(client)[0]
            except Exception as error:
                err = error
                self.post(lambda: self.append_log(f"cloud: {err}"))
                return
            self.post(lambda: self.struck(table, entries, name, win))

        threading.Thread(target=work, daemon=True).start()

    def struck(self, table: sync.TableRecord, entries: list[dict], name: str, win: tk.Toplevel) -> None:
        self.table = table
        self.entries = entries
        self.known = sync.known_launchers(table, entries)
        text = t("launcher.launchers.struck", name=name)
        self.append_log(f"cloud: {text}")
        self.refresh_cloud()
        if win.winfo_exists():
            win.destroy()
        messagebox.showinfo(t("launcher.launchers.title"), text)

    def cut_off(self) -> None:
        """A lost or stolen PC with the keys on it: the only thing that
        cancels its copy is disconnecting the app on dropbox.com, which
        cancels every key. The page opens; when Dropbox then refuses this
        launcher's access, the box offers to authorise again."""
        app_name = self.settings.cloud.get("app_name") or "Kingmaker Kingdom Manager"
        if messagebox.askyesno(t("launcher.cloud.cut_off"), t("launcher.cloud.cut_off_text", app=app_name)):
            webbrowser.open(core.DROPBOX_APPS_PAGE)

    def reflect_running(self) -> None:
        running = self.server.running
        self.start_button.config(text=t("launcher.stop") if running else t("launcher.start"),
                                 state="normal")
        if not running:
            self.browser_button.config(state="disabled")
            self.set_status(t("launcher.status.stopped"), "quiet")
        for widget in self.mode_widgets():
            widget.config(state="disabled" if running else "normal")
        if self.load_button is not None:
            self.load_button.config(state="disabled" if running else "normal")
        self.gate_start()

    def mode_widgets(self) -> list:
        if self.settings.host:
            return []
        found = [w for w in self.where.winfo_children() if isinstance(w, ttk.Radiobutton)]
        found.append(self.token_entry)
        found.append(self.air_button)
        found.append(self.air_renew)
        return found

    def open_browser(self) -> None:
        url = self.links.get("local")
        if url:
            webbrowser.open(url)

    # -------------------------------------------------------- what it says
    def poll(self) -> None:
        try:
            while True:
                kind, value = self.events.get_nowait()
                try:
                    self.dispatch(kind, value)
                except tk.TclError:
                    # An answer for a window closed before it came — the
                    # Versions list, say, shut while GitHub was still
                    # thinking: there is nobody to show it to. The loop
                    # must go on either way, or the launcher goes deaf.
                    pass
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def dispatch(self, kind: str, value) -> None:
        if kind == "line":
            self.handle_line(value)
        elif kind == "call":
            value()
        elif kind == "cloud":
            self.handle_cloud(*value)
        elif kind == "taken":
            self.handle_taken()
        elif kind == "handed":
            self.handle_handed(value)
        else:
            self.handle_exit(value)

    def handle_line(self, text: str) -> None:
        parsed = core.parse_line(text)
        if parsed and parsed[0] == "admin-password":
            self.append_log("KM admin-password ********")
            self.show_password("admin", parsed[1])
            return
        self.append_log(core.mask_secrets(text))
        if not parsed:
            return
        kind, value = parsed
        if kind == "ready":
            self.links["local"] = value
            self.rebuild_links()
            self.browser_button.config(state="normal")
            self.set_status(t("launcher.status.ready", url=value), "ok")
            if self.settings.open_browser:
                webbrowser.open(value)
            if self.record is not None:
                self.begin_hosting()
        elif kind == "paired":
            host_id, _space, name = value.partition(" ")
            self.key_taken(host_id, name)
        elif kind == "lan":
            self.links.setdefault("lan", value)
            self.rebuild_links()
            if self.record is not None and not self.record.address:
                self.record.address = value
        elif kind == "air":
            self.links["air"] = value
            self.rebuild_links()
            if self.record is not None:
                self.record.address = value      # the next heartbeat tells the others
            if (core.is_random_air_address(value) and self.table is not None
                    and self.table.air_token and not self.offline):
                # The relay gave an anonymous device: the table's token
                # was refused, and the fixed address leads nowhere.
                self.set_status(t("launcher.cloud.token_refused"), "bad")
                self.append_log("cloud: " + t("launcher.cloud.token_refused"))
            elif self.record is not None:
                threading.Thread(target=self.verify_address, args=(value, self.server.secret),
                                 daemon=True).start()
        elif kind == "air-refused":
            # The relay says it every five seconds; the table hears it once
            # per start. The game is not online at all in this state.
            if not self.token_refused_said:
                self.token_refused_said = True
                self.set_status(t("launcher.cloud.token_refused"), "bad")

    # The relay gives the address to the newest program that connects with
    # the token and tells the one before nothing (seen on the real relay,
    # 2026-10-06): a check at start alone would miss a hijack an hour later.
    RECHECK_EVERY_MS = 5 * 60 * 1000

    def verify_address(self, address: str, secret: str, first: bool = True) -> None:
        """Asks the public address who answers there, three times over half
        a minute (the relay takes a moment to route a new device): this
        server, proven by its own secret, another program, or nothing."""
        state = "none"
        for attempt in range(3):
            state = core.address_state(address, secret)
            if state != "none":
                break
            if attempt < 2:
                time.sleep(10)
        found = state
        self.post(lambda: self.address_checked(found, address, first))

    def address_checked(self, state: str, address: str, first: bool = True) -> None:
        if not self.server.running:
            return
        if state == "ours" or state == "none":
            if state == "none":
                self.append_log("cloud: " + t("launcher.cloud.address_unverified", error="404"))
            elif first:
                self.append_log("cloud: " + t("launcher.cloud.address_ok"))
            # Again in five minutes, for as long as we host.
            secret = self.server.secret
            self.root.after(self.RECHECK_EVERY_MS, lambda: self.server.running and threading.Thread(
                target=self.verify_address, args=(address, secret, False), daemon=True).start())
        if state == "ours":
            if (self.table is not None and self.table.air_address != address
                    and self.settings.cloud.get("role") == "admin"
                    and (self.table.format < 2 or self.table.admin_key == self.settings.sign_key)):
                # The administrator's to write, signed: the write changes
                # `set_at`, which the signature covers, and a host's write
                # would leave the file unsigned for everyone.
                self.table.air_address = address
                table, host_name = self.table, self.settings.identity()[1]
                seed = self.settings.seed()

                def remember() -> None:
                    try:
                        self.sign_table(self.cloud_client(), table, host_name, seed)
                    except Exception as error:
                        err = error
                        self.post(lambda: self.append_log(f"cloud: {err}"))

                threading.Thread(target=remember, daemon=True).start()
            return
        if state == "none":
            return
        text = t("launcher.cloud.address_other")
        self.append_log("cloud: " + text)
        self.set_status(text, "bad")
        messagebox.showwarning(t("launcher.cloud.address_other_title"), text)

    def handle_exit(self, code: int) -> None:
        if self.hoster is not None:
            hoster, self.hoster = self.hoster, None
            threading.Thread(target=lambda: hoster.stop(final=False), daemon=True).start()
        if self.record is not None:
            threading.Thread(target=self.drop_record, daemon=True).start()
        self.offline = False
        self.links = {}                  # the addresses were this server's
        self.rebuild_links()
        self.reflect_running()
        if code not in (0, None) and self.port_in_use is not None:
            self.set_status(t("launcher.status.died", code=code), "bad")
            self.show_log.set(True)
            self.toggle_log()
        self.port_in_use = None

    def show_password(self, username: str, password: str, reset: bool = False) -> None:
        dialog = tk.Toplevel(self.root, class_=core.WM_CLASS)
        dialog.withdraw()                   # shown by screen.present, sized and placed
        dialog.title(t("launcher.password.title"))
        dialog.transient(self.root)
        ttk.Button(dialog, text=t("launcher.password.ok"), command=dialog.destroy
                   ).pack(side="bottom", pady=(12, 14))
        scroller = screen.Scrolled(dialog)
        scroller.pack(fill="both", expand=True)
        key = "launcher.password.reset_text" if reset else "launcher.password.text"
        ttk.Label(scroller.inner, text=t(key, username=username), wraplength=420, justify="left"
                  ).pack(padx=16, pady=(14, 8))
        row = ttk.Frame(scroller.inner)
        row.pack(fill="x", padx=16)
        entry = ttk.Entry(row, state="readonly", font=("TkFixedFont", 12), justify="center")
        entry.var = tk.StringVar(value=password)     # type: ignore[attr-defined]
        entry.config(textvariable=entry.var)          # type: ignore[attr-defined]
        entry.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text=t("launcher.copy"), command=lambda: self.copy(password)
                   ).pack(side="left", padx=(8, 0))
        dialog.bind("<Return>", lambda _e: dialog.destroy())
        screen.present(dialog, grab=True)

    # ------------------------------------------------------------- updates
    def check_updates(self) -> None:
        release = core.latest_release()
        if release is not None and core.is_newer(release.version):
            self.post(lambda: self.show_release(release))

    def show_release(self, release: core.Release | None = None) -> None:
        if release is not None:
            self.release = release
        if self.release is None:
            self.update_bar.pack_forget()
            return
        self.update_label.config(text=t("launcher.update_available", version=self.release.version))
        has_file = self.release.installer() is not None and sys.platform == "win32"
        self.update_button.config(text=t("launcher.update_download") if has_file
                                  else t("launcher.update_open_page"))
        self.update_bar.pack(fill="x", padx=12, pady=(0, 4), after=self.head)

    def download_update(self, release: core.Release | None = None) -> None:
        release = release or self.release
        if release is None:
            return
        asset = release.installer()
        if asset is None or sys.platform != "win32":
            webbrowser.open(release.page)
            return
        if self.server.running:
            if not messagebox.askyesno(core.APP_NAME, t("launcher.close.running")):
                return
            self.stop()
        if not core.is_newer(release.version) and release.version != __version__:
            if not messagebox.askyesno(t("launcher.versions.title"),
                                       t("launcher.versions.downgrade", version=release.version)):
                return
        if not messagebox.askyesno(t("launcher.update_ready_title"), t("launcher.update_run")):
            return
        self.release = release
        self.show_release()
        self.update_button.config(state="disabled")
        target = Path(tempfile.gettempdir()) / asset["name"]

        def progress(done: int, total: int) -> None:
            percent = int(done * 100 / total) if total else 0
            self.post(lambda: self.update_label.config(
                text=t("launcher.update_downloading", percent=percent)))

        def work() -> None:
            try:
                core.download(asset["url"], target, progress)
            except Exception as error:      # network, disk: shown, not raised
                err = error
                self.post(lambda: self.update_failed(err))
                return
            # Not run before it is known to be the owner's: the hash in a
            # list the owner signed. A release from before the signatures
            # is run only after asking.
            try:
                verdict = core.verify_download(target, release)
            except Exception as error:
                err = error
                self.post(lambda: self.update_rejected(target, err))
                return
            if verdict == "unsigned" and not self.ask(lambda: messagebox.askyesno(
                    t("launcher.update_ready_title"), t("launcher.update.unsigned_confirm",
                                                        version=release.version), default="no")):
                try:
                    target.unlink(missing_ok=True)      # not run, not kept either
                except OSError:
                    pass
                self.post(lambda: self.update_failed(ValueError(t("launcher.update.unsigned_kept"))))
                return
            self.post(lambda: self.run_update(target))

        threading.Thread(target=work, daemon=True).start()

    def update_rejected(self, target: Path, error: Exception) -> None:
        """A downloaded installer that is not the owner's: deleted, said."""
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
        text = t("launcher.update.bad_signature", error=error)
        self.append_log(f"update: {text}")
        self.update_button.config(state="normal")
        self.update_label.config(text=t("launcher.update.refused"))
        messagebox.showerror(t("launcher.update_ready_title"), text)

    def open_versions(self) -> None:
        """Every release on GitHub, to install any of them — the newest, or
        an older one when a new one misbehaves."""
        win = tk.Toplevel(self.root, class_=core.WM_CLASS)
        win.withdraw()                      # shown by screen.present, sized and placed
        win.title(t("launcher.versions.title"))
        win.transient(self.root)
        # The buttons and the status first and at the bottom: on a short
        # screen the list gives up its lines, and it scrolls.
        row = ttk.Frame(win)
        row.pack(side="bottom", fill="x", padx=14, pady=(0, 12))
        status = ttk.Label(win, text=t("launcher.versions.loading"), foreground=COLOURS["quiet"])
        status.pack(side="bottom", anchor="w", padx=14, pady=4)
        ttk.Label(win, text=t("launcher.versions.text"), wraplength=460, justify="left"
                  ).pack(anchor="w", padx=14, pady=(12, 6))
        listed = ttk.Frame(win)
        listed.pack(fill="both", expand=True, padx=14)
        box = tk.Listbox(listed, height=10, width=64, activestyle="none")
        bar = ttk.Scrollbar(listed, orient="vertical", command=box.yview)
        box.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        box.pack(side="left", fill="both", expand=True)
        install = ttk.Button(row, text=t("launcher.versions.install"), state="disabled")
        install.pack(side="right")
        ttk.Button(row, text=t("launcher.settings.close"), command=win.destroy).pack(side="right", padx=8)
        releases: list[core.Release] = []

        def fill(found: list[core.Release]) -> None:
            if not box.winfo_exists():      # closed before GitHub answered
                return
            releases[:] = found
            box.delete(0, "end")
            for release in found:
                marks = []
                if release.version == __version__:
                    marks.append(t("launcher.versions.current"))
                if found and release is found[0]:
                    marks.append(t("launcher.versions.latest"))
                if release.installer() is None:
                    marks.append(t("launcher.versions.no_installer"))
                elif not release.signed:
                    marks.append(t("launcher.versions.unsigned"))
                line = f"{release.version}    {release.published}    {' · '.join(marks)}"
                box.insert("end", line)
            if not found:
                status.config(text=t("launcher.versions.none"))
            else:
                status.config(text="")
                install.config(state="normal")

        def chosen() -> None:
            picked = box.curselection()
            if not picked:
                return
            release = releases[picked[0]]
            win.destroy()
            if release.installer() is None or sys.platform != "win32":
                webbrowser.open(release.page)
                return
            self.download_update(release)

        install.config(command=chosen)
        screen.present(win)
        threading.Thread(target=lambda: self.post(lambda: fill(core.list_releases())),
                         daemon=True).start()

    def update_failed(self, error: Exception) -> None:
        self.update_label.config(text=t("launcher.update_failed", error=error))
        self.update_button.config(state="normal")

    def run_update(self, path: Path) -> None:
        core.run_installer(path)
        self.on_close(force=True)

    # ---------------------------------------------------------- a save file
    def load_save(self) -> None:
        """The game of another PC, or a backup: looked at, confirmed, loaded."""
        if self.server.running:
            messagebox.showinfo(core.APP_NAME, t("launcher.load_save.stop_first"))
            return
        chosen = filedialog.askopenfilename(
            title=t("launcher.load_save"),
            filetypes=[(t("launcher.load_save.filter"), "*.zip *.db *.bak *.sqlite"), ("*", "*.*")])
        if not chosen:
            return
        path = Path(chosen)
        try:
            info = core.inspect_save(path)
        except ValueError as error:
            key, params = (error.args + ({},))[:2]
            messagebox.showerror(t("launcher.error.title"),
                                 t("launcher.load_save.failed", error=t(key, **params)))
            return
        except Exception as error:
            messagebox.showerror(t("launcher.error.title"), t("launcher.load_save.failed", error=error))
            return
        if not messagebox.askyesno(t("launcher.load_save"), t(
                "launcher.load_save.confirm", name=path.name, kingdom=info["kingdom"] or "?",
                users=info["users"], version=info["version"], images=info["assets"])):
            return
        try:
            kept = core.load_save(path)
        except Exception as error:
            messagebox.showerror(t("launcher.error.title"), t("launcher.load_save.failed", error=error))
            return
        self.append_log(t("launcher.log.save_loaded", path=path, kept=kept.name))
        messagebox.showinfo(core.APP_NAME, t("launcher.load_save.done", kingdom=info["kingdom"] or "?"))

    # ------------------------------------------------------------ settings
    def open_settings(self) -> None:
        if self.settings_window is not None and self.settings_window.winfo_exists():
            self.settings_window.lift()
            return
        win = tk.Toplevel(self.root, class_=core.WM_CLASS)
        win.withdraw()                      # shown by screen.present, sized and placed
        self.settings_window = win
        win.title(t("launcher.settings"))
        win.transient(self.root)
        close = ttk.Button(win, text=t("launcher.settings.close"))
        close.pack(side="bottom", pady=(4, 12))
        scroller = screen.Scrolled(win)
        scroller.pack(padx=12, pady=8, fill="both", expand=True)
        body = scroller.inner
        # Laid out like the main window's Table box: small headings, and
        # under them each button with what it is for written next to it.
        # The buttons share the width of the longest, so the sentences line
        # up in either language.
        admin = not self.settings.host
        labels = [t("launcher.versions.button"), t("launcher.settings.folder"),
                  t("launcher.settings.reset_setup")] + ([t("launcher.settings.reset")] if admin else [])
        width = max(len(text) for text in labels) + 2

        def heading(text: str, first: bool = False) -> None:
            ttk.Label(body, text=text, font=("TkDefaultFont", 9, "bold")
                      ).pack(anchor="w", padx=8, pady=(0 if first else 14, 2))

        heading(t("launcher.settings.group.launcher"), first=True)
        fields = ttk.Frame(body)
        fields.pack(fill="x", padx=8)
        ttk.Label(fields, text=t("launcher.settings.port")).grid(row=0, column=0, sticky="w", pady=3)
        port_var = tk.StringVar(value=str(self.settings.port))
        ttk.Spinbox(fields, from_=1024, to=65535, textvariable=port_var, width=8
                    ).grid(row=0, column=1, sticky="w", padx=8)
        ttk.Label(fields, text=t("launcher.settings.port_hint"), foreground=COLOURS["quiet"],
                  wraplength=320, justify="left").grid(row=0, column=2, sticky="w")
        ttk.Label(fields, text=t("launcher.settings.language")).grid(row=1, column=0, sticky="w", pady=3)
        names = [i18n.NAMES[code] for code in i18n.LANGUAGES]
        lang_var = tk.StringVar(value=i18n.NAMES.get(self.settings.language, names[0]))
        ttk.Combobox(fields, values=names, textvariable=lang_var, state="readonly", width=12
                     ).grid(row=1, column=1, columnspan=2, sticky="w", padx=8)
        browser_var = tk.BooleanVar(value=self.settings.open_browser)
        ttk.Checkbutton(body, text=t("launcher.settings.browser"), variable=browser_var
                        ).pack(anchor="w", padx=8, pady=(6, 2))
        updates_var = tk.BooleanVar(value=self.settings.check_updates)
        ttk.Checkbutton(body, text=t("launcher.settings.updates"), variable=updates_var
                        ).pack(anchor="w", padx=8, pady=(2, 6))
        self.row(body, t("launcher.versions.button"), self.open_versions,
                 t("launcher.settings.row.versions"), width=width)

        heading(t("launcher.settings.group.game"))
        ttk.Label(body, text=t("launcher.folder_label", folder=core.game_folder()), wraplength=560,
                  justify="left", foreground=COLOURS["quiet"]).pack(anchor="w", padx=8, pady=(0, 4))
        self.row(body, t("launcher.settings.folder"), lambda: core.open_folder(core.game_folder()),
                 t("launcher.settings.row.folder"), width=width)
        # The game's own administrator password is the administrator's: a
        # host's copy of the game is the table's, carried to everyone.
        if admin:
            self.row(body, t("launcher.settings.reset"), self.reset_password,
                     t("launcher.settings.row.reset"), width=width)

        heading(t("launcher.settings.group.start_over"))
        self.row(body, t("launcher.settings.reset_setup"), lambda: self.reset_setup(then=apply),
                 t("launcher.settings.row.reset_setup"), width=width)

        def apply() -> None:
            try:
                port = int(port_var.get())
            except ValueError:
                port = self.settings.port
            self.settings.port = port if 1 <= port <= 65535 else self.settings.port
            self.settings.open_browser = browser_var.get()
            was_checking = self.settings.check_updates
            self.settings.check_updates = updates_var.get()
            if self.settings.check_updates and not was_checking and self.release is None:
                # Switched on just now: the check skipped at start runs once.
                threading.Thread(target=self.check_updates, daemon=True).start()
            chosen = next((code for code in i18n.LANGUAGES if i18n.NAMES[code] == lang_var.get()),
                          self.settings.language)
            changed = chosen != self.settings.language
            self.settings.language = chosen
            self.gather()
            win.destroy()
            if changed:
                self.build()

        close.config(command=apply)
        win.protocol("WM_DELETE_WINDOW", apply)
        screen.present(win)

    def reset_password(self) -> None:
        if self.server.running:
            messagebox.showinfo(core.APP_NAME, t("launcher.settings.reset_stop_first"))
            return
        if not messagebox.askyesno(t("launcher.settings.reset"), t("launcher.settings.reset_confirm")):
            return
        try:
            username, password = core.reset_admin_password()
        except Exception as error:
            messagebox.showerror(t("launcher.error.title"),
                                 t("launcher.settings.reset_failed", error=error))
            return
        self.show_password(username, password, reset=True)

    # --------------------------------------------------------------- close
    def on_close(self, force: bool = False) -> None:
        if self.stop_thread is not None:
            # A Stop under way: its last copy first, the thread would die
            # with the process otherwise.
            self.stop_thread.join()
            self.stop_thread = None
        if self.server.running:
            if not force and not messagebox.askyesno(core.APP_NAME, t("launcher.close.running")):
                return
            self.stop(wait=True)
        self.drop_record()
        self.gather()
        try:
            self.root.after_cancel(self.watch_id)
        except tk.TclError:
            pass
        self.root.destroy()


def bundle_manifest(path) -> dict:
    from kingmaker.storage import bundle
    return bundle.manifest(path)
