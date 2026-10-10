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


class HostsKeyNeeded(Exception):
    """An administrator's launcher without a key for the hosts yet."""


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

        self.status = ttk.Label(body, wraplength=520, foreground=COLOURS["quiet"])
        self.status.pack(anchor="w", **PAD)

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
                 and not self.settings.cloud_ready and not cloud.get("app_key"))
        if alone:
            self.cloud.pack_forget()
        else:
            self.cloud.pack(fill="x", before=self.actions, **PAD)

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

    def set_status(self, text: str, kind: str = "quiet", about_host: bool = False) -> None:
        self.status.config(text=text, foreground=COLOURS.get(kind, COLOURS["quiet"]))
        self.status_about_host = about_host

    # --------------------------------------------------------------- links
    def rebuild_links(self) -> None:
        """The address rows: the running game's, or, while it is stopped,
        the last run's that the place now chosen still gives."""
        for child in self.links_frame.winfo_children():
            child.destroy()
        links = self.links if self.server.running else core.links_for_mode(self.links, self.mode_var.get())
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
            self.set_status(t("launcher.status.port_moved", wanted=self.settings.port, port=port), "busy")
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

    def stop(self) -> None:
        self.set_status(t("launcher.status.stopping"), "busy")
        self.start_button.config(state="disabled")
        self.root.update_idletasks()
        if self.hoster is not None:
            hoster, self.hoster = self.hoster, None
            self.set_status(t("launcher.cloud.final_upload"), "busy")
            self.root.update_idletasks()
            hoster.stop(final=True)
            self.record = None
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
        elif self.offline and self.server.running:
            self.cloud_label.config(text=t("launcher.cloud.offline", table=cloud.get("table", "")),
                                    foreground=COLOURS["bad"])
        elif self.other is not None and self.other.held():
            host = self.other.host_name or self.other.host_id
            self.group(t("launcher.cloud.group.now"))
            if self.holder_known(self.other):
                self.cloud_label.config(text=self.hosted_text(self.other), foreground=COLOURS["busy"])
                if self.other.address:
                    address = self.other.address
                    self.action(t("launcher.cloud.join"), lambda: webbrowser.open(address),
                                t("launcher.cloud.row.join", host=host))
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
                self.group(t("launcher.cloud.group.leaving"))
                self.action(t("launcher.cloud.rotate"), self.rotate_access,
                            t("launcher.cloud.row.rotate"))
                self.action(t("launcher.cloud.cut_off"), self.cut_off, t("launcher.cloud.row.cut_off"))
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
            self.known = sync.known_launchers(table, self.entries) if table is not None else {}
            if self.check_seat(table):
                return                      # the seat moved: the box says so
        self.other = record if record is not None and record.held() else None
        speak = not quiet or self.status_about_host
        if self.other is None:
            if speak:
                self.set_status(t("launcher.cloud.nobody"), "quiet", about_host=True)
            if table is not None and table.air_token and table.air_address and not self.server.running:
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
        administrator finding another key on it has lost the seat to a
        newer PC: its own Dropbox access is revoked and forgotten, the
        window says who took it and when. A host whose file is no longer
        signed by the administrator it paired with pairs again. True when
        the box was redrawn for either."""
        if table is None or table.format < 2:
            return False
        cloud = self.settings.cloud
        if cloud.get("role") == "admin":
            if table.admin_key and table.admin_key != self.settings.sign_key and not self.server.running \
                    and self.record is None:
                self.seat_lost(table)
                return True
            return False
        trusted = table.trusted_by(cloud.get("admin_key", ""))
        if trusted == (not self.seat_changed):
            return False
        self.seat_changed = not trusted
        if self.seat_changed:
            who = table.admin_name or table.admin_id
            self.append_log("cloud: " + t("launcher.cloud.seat_changed", name=who, date=table.admin_since[:10]))
        self.refresh_cloud()
        return True

    def seat_lost(self, table: sync.TableRecord) -> None:
        who, date = table.admin_name or table.admin_id, table.admin_since[:10]
        try:
            self.cloud_client().revoke()    # our own access, not the hosts'
        except Exception as error:
            self.append_log(t("launcher.log.cloud_revoke_failed", error=error))
        self.settings.cloud = {}
        self.settings.token = ""
        self.settings.save()
        self.other = None
        self.table = None
        self.known = {}
        self.entries = []
        text = t("launcher.cloud.seat_taken", name=who, date=date)
        self.append_log(f"cloud: {text}")
        self.set_status(text, "bad")
        self.refresh_cloud()
        messagebox.showinfo(t("launcher.cloud.seat_title"), text)

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
                except HostsKeyNeeded:
                    self.post(self.need_hosts_key)
                    return
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
                say(t("launcher.cloud.pulling"))
                try:
                    pulled = sync.newest_usable(client, core.game_folder() / "cloud",
                                                log=cloud_log, record=record,
                                                trusted=known if table.format >= 2 else None,
                                                signed_since=table.signed_since)
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
                    table.app_version = __version__
                    sync.write_table(client, table, by=host_name)
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
        away arrives this way). Without a hosts' key yet, `HostsKeyNeeded`.
        A host: the file must be signed by the administrator it paired
        with, else `SeatChanged`; hosts write nothing here any more."""
        cloud = self.settings.cloud
        admin = cloud.get("role") == "admin"
        local = self.settings.token.strip()
        name = cloud.get("table") or "Kingmaker"
        host_id, _name = self.settings.identity()
        seed, key = self.settings.seed(), self.settings.sign_key
        if admin:
            if not cloud.get("hosts_refresh_token"):
                raise HostsKeyNeeded()
            table, created = sync.ensure_table(client, name, token=local, by=host_name,
                                               admin=(host_id, host_name, key), seed=seed)
            changed = False
            if created:
                self.post(lambda: self.append_log(t("launcher.log.table_created", version=table.app_version)))
            elif table.format < 2:
                # A table from 1.x: the seat is ours, the copies before this
                # epoch stay accepted unsigned.
                current = sync.read_record(client)
                sync.take_seat(table, host_id, host_name, key, (current.epoch if current else 0) + 1)
                changed = True
                self.post(lambda: self.append_log(t("launcher.log.table_upgraded")))
            elif table.admin_key != key:
                who, since = table.admin_name or table.admin_id, table.admin_since[:10]
                if not self.ask(lambda: messagebox.askyesno(
                        t("launcher.cloud.seat_title"),
                        t("launcher.cloud.seat_take_confirm", name=who, date=since))):
                    raise SeatChanged(who, since)
                sync.take_seat(table, host_id, host_name, key, table.signed_since or 1)
                changed = True
                self.post(lambda: self.append_log(t("launcher.cloud.seat_taken_here", name=who)))
            if local and local != table.air_token:
                table.air_token = local
                table.air_generation += 1
                changed = True
            if changed:
                table = sync.write_table(client, table, by=host_name, seed=seed)
            if local and table.air_token:
                self.post(self.token_moved)
            cloud["admin_key"] = key
        else:
            table = sync.read_table(client)
            if table is None:
                raise SeatChanged("", "")
            if not table.trusted_by(cloud.get("admin_key", "")):
                raise SeatChanged(table.admin_name or table.admin_id, table.admin_since[:10])
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
            self.set_status(t("launcher.cloud.uploaded", name=text), "ok")
        elif kind == "error":
            self.append_log(f"cloud: {text}")
            self.set_status(t("launcher.cloud.upload_failed", error=text), "busy")

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
            if table.air_token != token or table.format < 2:
                if table.format < 2:
                    current = sync.read_record(client)
                    sync.take_seat(table, host_id, host_name, key, (current.epoch if current else 0) + 1)
                table.air_token = token
                table.air_generation += 1
                sync.write_table(client, table, by=host_name, seed=seed)
        except Exception as error:          # unreachable, refused: kept locally for now
            err = error
            self.post(lambda: self.append_log(f"cloud: {err}"))
            return
        self.table = table
        self.post(self.token_moved)

    def make_pairing_code(self) -> None:
        """A pairing code from the running game, for the launcher of the next
        host — the same code the game's accounts dialog makes, from here.
        Not on this computer only: the other launcher could not reach the
        game to use it."""
        if self.local_only():
            messagebox.showinfo(t("launcher.cloud.pair_launcher"), t("launcher.cloud.pair_needs_network"))
            return
        if not (self.server.running and self.record is not None and not self.offline):
            messagebox.showinfo(t("launcher.cloud.pair_launcher"), t("launcher.cloud.pair_needs_hosting"))
            return
        local = sync.LocalServer(self.server.port or 0, self.server.secret)

        def work() -> None:
            try:
                answer = local.pairing()
            except Exception as error:
                err = error
                self.post(lambda: messagebox.showerror(t("launcher.error.title"), str(err)))
                return
            code = str(answer.get("code", ""))
            self.post(lambda: self.show_pairing_code(code))

        threading.Thread(target=work, daemon=True).start()

    def show_pairing_code(self, code: str) -> None:
        """The code, large, with the address the other launcher must type."""
        address = self.links.get("air") or self.links.get("lan") or self.links.get("local") or ""
        dialog = tk.Toplevel(self.root, class_=core.WM_CLASS)
        dialog.withdraw()                   # shown by screen.present, sized and placed
        dialog.title(t("launcher.cloud.pair_code_title"))
        dialog.transient(self.root)
        ttk.Button(dialog, text=t("launcher.password.ok"), command=dialog.destroy
                   ).pack(side="bottom", pady=(12, 14))
        scroller = screen.Scrolled(dialog)
        scroller.pack(fill="both", expand=True)
        ttk.Label(scroller.inner, text=t("launcher.cloud.pair_code_text"),
                  wraplength=420, justify="left").pack(anchor="w", padx=16, pady=(14, 8))

        # Each in a field with its Copy, named as the other person's pairing
        # form names it: they paste both, nobody types a web address by hand.
        grid = ttk.Frame(scroller.inner)
        grid.pack(fill="x", padx=16)
        grid.columnconfigure(1, weight=1)

        def copyable(line: int, label: str, value: str, **options) -> None:
            ttk.Label(grid, text=label).grid(row=line, column=0, sticky="w", padx=(0, 8), pady=3)
            entry = ttk.Entry(grid, state="readonly", **options)
            entry.var = tk.StringVar(value=value)     # type: ignore[attr-defined]
            entry.config(textvariable=entry.var)      # type: ignore[attr-defined]
            entry.grid(row=line, column=1, sticky="ew", pady=3)
            ttk.Button(grid, text=t("launcher.copy"), command=lambda: self.copy(value)
                       ).grid(row=line, column=2, padx=(8, 0), pady=3)

        # Wide enough to read the whole address before sending it.
        copyable(0, t("launcher.pair.address"), address, width=min(max(len(address) + 2, 20), 64))
        copyable(1, t("launcher.pair.code"), code, font=("TkFixedFont", 12), justify="center")
        ttk.Label(scroller.inner, text=t("launcher.cloud.pair_code_note"), foreground=COLOURS["quiet"],
                  wraplength=420, justify="left").pack(anchor="w", padx=16, pady=(8, 4))
        dialog.bind("<Return>", lambda _e: dialog.destroy())
        screen.present(dialog, grab=True)

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

    def rotate_access(self) -> None:
        """Change the keys: a fresh hosts' key, the old one cancelled on
        every PC that holds a copy. The administrator's own never moves.
        For the day someone left the table or a PC was lost; every other
        host pairs again afterwards."""
        if self.record is not None or self.server.running:
            messagebox.showinfo(t("launcher.cloud.title"), t("launcher.load_save.stop_first"))
            return
        if not messagebox.askyesno(t("launcher.cloud.rotate"), t("launcher.cloud.rotate_confirm")):
            return
        old = str(self.settings.cloud.get("hosts_refresh_token", ""))
        wizard.SetupWizard(self.root, self.settings, on_done=lambda: self.rotated(old),
                           post=self.post, start="hosts_authorise")

    def reauthorise(self) -> None:
        """The administrator's own access refused by Dropbox: both keys
        anew, then every host pairs again (`rotated`)."""
        if self.record is not None or self.server.running:
            messagebox.showinfo(t("launcher.cloud.title"), t("launcher.load_save.stop_first"))
            return
        old = str(self.settings.cloud.get("hosts_refresh_token", ""))
        wizard.SetupWizard(self.root, self.settings, on_done=lambda: self.rotated(old, lost=True),
                           post=self.post, start="authorise")

    def rotated(self, old: str, lost: bool = False) -> None:
        new = str(self.settings.cloud.get("hosts_refresh_token", ""))
        if not new or new == old:
            return                          # the wizard was cancelled: nothing changed
        app_key = str(self.settings.cloud.get("app_key", ""))
        host_id, host_name = self.settings.identity()
        seed, key = self.settings.seed(), self.settings.sign_key
        self.access_lost = False

        def work() -> None:
            try:
                if old and not lost:
                    dropbox.Client(dropbox.Credential(app_key=app_key, refresh_token=old)).revoke()
                client = self.cloud_client()
                table = sync.read_table(client)
                if table is not None:
                    if table.format < 2 or table.admin_key != key:
                        current = sync.read_record(client)
                        sync.take_seat(table, host_id, host_name, key, (current.epoch if current else 0) + 1)
                    table.access_generation += 1
                    sync.write_table(client, table, by=host_name, seed=seed)
            except Exception as error:
                err = error
                self.post(lambda: self.append_log(t("launcher.cloud.rotate_failed", error=err)))
                self.post(lambda: messagebox.showwarning(
                    t("launcher.cloud.rotate"), t("launcher.cloud.rotate_failed", error=err)))
                return
            self.post(lambda: self.append_log("cloud: " + t("launcher.cloud.rotated")))
            self.post(lambda: messagebox.showinfo(t("launcher.cloud.rotate"), t("launcher.cloud.rotated")))

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

    def need_hosts_key(self) -> None:
        """An administrator from before the two keys: the hosts need a key
        of their own before the table can be hosted at this version."""
        self.cloud_busy = False
        self.start_button.config(state="normal")
        self.set_status(t("launcher.cloud.cancelled"), "quiet")
        messagebox.showinfo(t("launcher.cloud.title"), t("launcher.cloud.hosts_key_needed"))
        old = str(self.settings.cloud.get("hosts_refresh_token", ""))
        wizard.SetupWizard(self.root, self.settings, on_done=lambda: self.rotated(old, lost=True),
                           post=self.post, start="hosts_authorise")

    def open_launchers(self) -> None:
        """The launchers the table vouches for, each with who let it in and
        since when, and a button to strike it off: its copies are refused
        from then on and the record it holds is nobody's. The hosts' key it
        still holds is changed with *Change the keys…*."""
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
        ttk.Label(body, text=t("launcher.launchers.text"), wraplength=480, justify="left"
                  ).pack(anchor="w", pady=(0, 8))
        names = {self.table.admin_id: self.table.admin_name}
        names.update({str(e.get("host_id", "")): str(e.get("name", "")) for e in self.entries})
        listed = [e for e in self.entries if str(e.get("host_id", "")) in self.known]
        if not listed:
            ttk.Label(body, text=t("launcher.launchers.none"), foreground=COLOURS["quiet"]).pack(anchor="w")
        for entry in listed:
            host_id = str(entry.get("host_id", ""))
            line = ttk.Frame(body)
            line.pack(fill="x", pady=3)
            ttk.Label(line, text=t("launcher.launchers.entry", name=entry.get("name") or host_id,
                                   since=str(entry.get("since", ""))[:10],
                                   by=names.get(str(entry.get("admitted_by", "")), entry.get("admitted_by", ""))),
                      wraplength=360, justify="left").pack(side="left")
            ttk.Button(line, text=t("launcher.launchers.strike"),
                       command=lambda h=host_id, w=win: self.strike_off(h, w)).pack(side="right")
        screen.present(win)

    def strike_off(self, host_id: str, win: tk.Toplevel) -> None:
        if self.record is not None or self.server.running:
            messagebox.showinfo(t("launcher.cloud.title"), t("launcher.load_save.stop_first"))
            return
        name = next((str(e.get("name", "")) for e in self.entries if e.get("host_id") == host_id), host_id)
        if not messagebox.askyesno(t("launcher.launchers.title"), t("launcher.launchers.strike_confirm", name=name)):
            return
        admin_id, host_name = self.settings.identity()
        seed = self.settings.seed()

        def work() -> None:
            try:
                client = self.cloud_client()
                table = sync.read_table(client)
                if table is None:
                    return
                if host_id not in table.revoked:
                    table.revoked.append(host_id)
                table = sync.write_table(client, table, by=host_name, seed=seed)
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
            if self.table is not None and self.table.air_address != address:
                self.table.air_address = address
                table, host_name = self.table, self.settings.identity()[1]

                def remember() -> None:
                    try:
                        sync.write_table(self.cloud_client(), table, by=host_name)
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
        if self.server.running:
            if not force and not messagebox.askyesno(core.APP_NAME, t("launcher.close.running")):
                return
            self.stop()
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
