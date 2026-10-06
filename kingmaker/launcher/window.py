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
import secrets
import sys
import tempfile
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

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
    root = tk.Tk()
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
        Launcher(root, settings)
        screen.present(root)
        root.mainloop()
    finally:
        lock.release()


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

        root.title(core.APP_NAME)
        root.minsize(560, 420)
        self.set_icon(root)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.mode_var = tk.StringVar(value=settings.mode)
        self.token_var = tk.StringVar(value=settings.token)
        self.show_token = tk.BooleanVar(value=False)
        self.show_log = tk.BooleanVar(value=False)
        self.body: ttk.Frame | None = None
        self.build()
        root.after(100, self.poll)
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
        if self.body is not None:
            self.body.destroy()
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

        self.where = where = ttk.LabelFrame(body, text=t("launcher.where"))
        where.pack(fill="x", **PAD)
        for mode in core.MODES:
            ttk.Radiobutton(where, text=t(f"launcher.mode.{mode}"), value=mode,
                            variable=self.mode_var, command=self.mode_changed
                            ).pack(anchor="w", padx=8, pady=2)
        self.mode_hint = ttk.Label(where, foreground=COLOURS["quiet"], wraplength=500)
        self.mode_hint.pack(anchor="w", padx=8, pady=(2, 6))

        self.air = ttk.LabelFrame(body, text=t("launcher.air.title"))
        ttk.Label(self.air, text=t("launcher.air.steps"), wraplength=500, justify="left"
                  ).pack(anchor="w", padx=8, pady=(4, 4))
        # The two ways to the token, next to the step that asks for them:
        # the wizard with its pictures, or the site for who knows the way.
        ways = ttk.Frame(self.air)
        ways.pack(anchor="w", padx=8, pady=(0, 6))
        self.air_button = ttk.Button(ways, text=t("launcher.air.setup"), command=self.open_air)
        self.air_button.pack(side="left")
        ttk.Button(ways, text=t("launcher.air.get"),
                   command=lambda: webbrowser.open(core.ON_AIR_PAGE)).pack(side="left", padx=8)
        # The way to a new token has a door of its own: whoever lost theirs
        # cannot reach that step by walking the guide, because the step
        # before it asks for the token they no longer have.
        self.air_renew = ttk.Button(ways, text=t("launcher.air.renew"),
                                    command=self.open_air_renew)
        self.air_renew.pack(side="left")
        self.token_row = row = ttk.Frame(self.air)
        row.pack(fill="x", padx=8, pady=2)
        self.token_entry = ttk.Entry(row, textvariable=self.token_var, show="•")
        self.token_entry.pack(side="left", fill="x", expand=True)
        ttk.Checkbutton(row, text=t("launcher.air.show"), variable=self.show_token,
                        command=self.toggle_token).pack(side="left", padx=6)
        # With the cloud the token is not here but in the table's folder:
        # this line stands where the field would be.
        self.air_from_table = ttk.Label(self.air, text=t("launcher.air.from_table"),
                                        foreground=COLOURS["quiet"], wraplength=500, justify="left")
        self.air_note = ttk.Label(self.air, text=t("launcher.air.note"), foreground=COLOURS["quiet"],
                                  wraplength=500, justify="left")
        self.air_note.pack(anchor="w", padx=8, pady=(4, 6))
        self.refresh_air()

        self.cloud = ttk.LabelFrame(body, text=t("launcher.cloud.title"))
        self.cloud.pack(fill="x", **PAD)
        self.cloud_label = ttk.Label(self.cloud, wraplength=500, justify="left")
        self.cloud_label.pack(anchor="w", padx=8, pady=(4, 4))
        self.cloud_row = ttk.Frame(self.cloud)
        self.cloud_row.pack(fill="x", padx=8, pady=(0, 6))
        self.refresh_cloud()

        actions = ttk.Frame(body)
        actions.pack(fill="x", **PAD)
        self.start_button = ttk.Button(actions, text=t("launcher.start"), command=self.toggle)
        self.start_button.pack(side="left")
        self.browser_button = ttk.Button(actions, text=t("launcher.open_browser"),
                                         command=self.open_browser, state="disabled")
        self.browser_button.pack(side="left", padx=8)
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

    def refresh_air(self) -> None:
        """The token field, or the line that says the token lives in the
        table's folder; and the renewal door for whoever may use it."""
        with_cloud = self.settings.cloud_ready
        admin = self.settings.cloud.get("role") == "admin"
        if with_cloud:
            self.token_row.pack_forget()
            self.air_from_table.pack(anchor="w", padx=8, pady=2, before=self.air_note)
        else:
            self.air_from_table.pack_forget()
            self.token_row.pack(fill="x", padx=8, pady=2, before=self.air_note)
        if with_cloud and not admin:
            self.air_renew.pack_forget()
        else:
            self.air_renew.pack(side="left")

    def mode_changed(self) -> None:
        mode = self.mode_var.get()
        self.mode_hint.config(text=t(f"launcher.mode.{mode}_hint"))
        if mode == "online":
            self.air.pack(fill="x", after=self.mode_hint.master, **PAD)
        else:
            self.air.pack_forget()

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

    def set_status(self, text: str, kind: str = "quiet") -> None:
        self.status.config(text=text, foreground=COLOURS.get(kind, COLOURS["quiet"]))

    # --------------------------------------------------------------- links
    def rebuild_links(self) -> None:
        for child in self.links_frame.winfo_children():
            child.destroy()
        for kind, url in self.links.items():
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

    def start(self, force: bool = False) -> None:
        if self.server.running or self.cloud_busy:
            return
        self.gather()
        if self.settings.mode == "lan" and sys.platform == "win32" and not self.settings.firewall_shown:
            messagebox.showinfo(t("launcher.firewall.title"), t("launcher.firewall.text"))
            self.settings.firewall_shown = True
            self.settings.save()
        if self.settings.cloud_ready:
            self.claim_then_start(force)
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
        for child in self.cloud_row.winfo_children():
            child.destroy()
        cloud = self.settings.cloud
        if not self.settings.cloud_ready:
            if self.settings.vault_error and cloud.get("app_key"):
                # The secrets were protected by another Windows user or on
                # another PC (a copied game folder): the rest of the cloud
                # settings are here, the access is not. Connect again.
                self.cloud_label.config(text=t("launcher.cloud.vault_error", table=cloud.get("table", "")),
                                        foreground=COLOURS["bad"])
            else:
                self.cloud_label.config(text=t("launcher.cloud.not_set_up"), foreground=COLOURS["quiet"])
            ttk.Button(self.cloud_row, text=t("launcher.cloud.set_up"), command=self.open_wizard
                       ).pack(side="left")
            ttk.Button(self.cloud_row, text=t("launcher.cloud.connect"), command=self.open_connect
                       ).pack(side="left", padx=8)
            self.refresh_air()
            return
        who = cloud.get("username") or cloud.get("account_name") or ""
        if self.record is not None:
            text = t("launcher.cloud.you_host", table=cloud.get("table", ""), epoch=self.record.epoch)
            colour = COLOURS["ok"]
        elif self.offline and self.server.running:
            text = t("launcher.cloud.offline", table=cloud.get("table", ""))
            colour = COLOURS["bad"]
        elif self.other is not None and self.other.held():
            text = self.hosted_text(self.other)
            colour = COLOURS["busy"]
        else:
            text = t("launcher.cloud.ready", table=cloud.get("table", ""), who=who,
                     role=cloud.get("role", ""), account=cloud.get("account_name", ""))
            colour = COLOURS["quiet"]
        self.cloud_label.config(text=text, foreground=colour)
        self.refresh_air()
        if self.record is None:
            ttk.Button(self.cloud_row, text=t("launcher.cloud.check"), command=self.check_host
                       ).pack(side="left")
        if self.other is not None and self.other.held() and self.record is None:
            if self.other.address:
                ttk.Button(self.cloud_row, text=t("launcher.cloud.join"),
                           command=lambda: webbrowser.open(self.other.address)).pack(side="left", padx=8)
            if cloud.get("role") == "admin":
                ttk.Button(self.cloud_row, text=t("launcher.cloud.take_over"), command=self.take_over
                           ).pack(side="left", padx=8)
        ttk.Button(self.cloud_row, text=t("launcher.cloud.forget"), command=self.forget_cloud
                   ).pack(side="right")

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

    def check_host(self) -> None:
        """Who holds the record right now, without claiming it; and what
        the table's file says."""
        if self.cloud_busy:
            return
        self.cloud_busy = True
        self.set_status(t("launcher.cloud.checking"), "busy")

        def work() -> None:
            try:
                client = self.cloud_client()
                record = sync.read_record(client)
                table = sync.read_table(client)
            except dropbox.DropboxError as error:
                err = error
                self.post(lambda: self.cloud_failed(err))
                return
            self.post(lambda: self.checked(record, table))

        threading.Thread(target=work, daemon=True).start()

    def checked(self, record: sync.HostRecord | None, table: sync.TableRecord | None = None) -> None:
        self.cloud_busy = False
        self.table = table
        self.other = record if record is not None and record.held() else None
        if self.other is None:
            self.set_status(t("launcher.cloud.nobody"), "quiet")
            if table is not None and table.air_token and table.air_address and not self.server.running:
                threading.Thread(target=self.probe_idle, args=(table.air_address,), daemon=True).start()
        else:
            self.set_status(self.hosted_text(self.other), "busy")
        self.refresh_cloud()

    def probe_idle(self, address: str) -> None:
        """Nobody hosts, says the record: does anything of ours answer at
        the table's address all the same? Then somebody else holds the
        token, and the table should know."""
        data, _why = core.probe_address(address, secrets.token_hex(8))
        if data is not None and not self.server.running:
            self.post(lambda: self.idle_alarm(address))

    def idle_alarm(self, address: str) -> None:
        text = t("launcher.cloud.address_idle", address=address)
        self.append_log(f"cloud: {text}")
        self.set_status(text, "bad")
        messagebox.showwarning(t("launcher.cloud.address_other_title"), text)

    def cloud_failed(self, error: Exception) -> None:
        self.cloud_busy = False
        self.append_log(f"cloud: {error}")
        self.set_status(t("launcher.cloud.unreachable", error=error), "bad")
        self.refresh_cloud()

    def claim_then_start(self, force: bool = False) -> None:
        """The claim, the pull and only then the server — in a thread, the
        window told at each step."""
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
                table = self.settle_table(client, host_name)
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
                record = sync.claim(client, host_id, host_name, force=force)
                say(t("launcher.cloud.pulling"))
                try:
                    pulled = sync.newest_usable(client, core.game_folder() / "cloud",
                                                log=cloud_log, record=record)
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
        """The table's file, read or created, and the token put where it
        belongs. The administrator's local token goes into the file (a
        renewal made while the cloud was away arrives this way); a GM's
        local copy fills an empty file, and is forgotten once the file has
        one. Called from the claim thread."""
        admin = self.settings.cloud.get("role") == "admin"
        local = self.settings.token.strip()
        name = self.settings.cloud.get("table") or "Kingmaker"
        table, created = sync.ensure_table(client, name, token=local, by=host_name)
        if created:
            self.post(lambda: self.append_log(t("launcher.log.table_created", version=table.app_version)))
        elif local and ((admin and local != table.air_token) or not table.air_token):
            table.air_token = local
            table.air_generation += 1
            sync.write_table(client, table, by=host_name)
        if local and table.air_token:
            self.post(self.token_moved)
        if table.air_generation:
            self.post(lambda: self.append_log(
                t("launcher.log.token_generation", generation=table.air_generation)))
        if table.name:
            self.settings.cloud["table"] = table.name
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
        win = tk.Toplevel(self.root)
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
        self.set_status(self.hosted_text(record), "busy")
        self.refresh_cloud()

    def claim_failed(self, error: Exception) -> None:
        self.cloud_busy = False
        self.start_button.config(state="normal")
        self.append_log(f"cloud: {error}")
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
        if not messagebox.askyesno(t("launcher.cloud.take_over"), t("launcher.cloud.take_over_confirm")):
            return
        self.start(force=True)

    def begin_hosting(self) -> None:
        """The server is up: keep the record alive and upload the game."""
        if self.record is None or self.hoster is None and self.server.port is None:
            return
        if self.hoster is not None:
            return
        local = sync.LocalServer(self.server.port or 0, self.server.secret)
        self.hoster = sync.Hoster(self.cloud_client(), self.record, local, config.ASSETS_DIR,
                                  on_event=lambda kind, text: self.events.put(("cloud", (kind, text))),
                                  on_taken_over=lambda: self.events.put(("taken", None)))
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

    def open_air(self) -> None:
        wizard.AirWizard(self.root, self.settings, on_done=self.air_ready)

    def open_air_renew(self) -> None:
        wizard.AirWizard(self.root, self.settings, on_done=self.air_ready, start="renew")

    def air_ready(self) -> None:
        self.token_var.set(self.settings.token)
        if (self.settings.cloud_ready and self.settings.cloud.get("role") == "admin"
                and self.settings.token.strip()):
            threading.Thread(target=self.publish_token, daemon=True).start()

    def publish_token(self) -> None:
        """The administrator's new token into the table's folder, so every
        host reads it at its next Start. When the cloud is away the token
        stays here and the next Start carries it (`settle_table`)."""
        _host_id, host_name = self.settings.identity()
        token = self.settings.token.strip()
        try:
            client = self.cloud_client()
            table, _created = sync.ensure_table(client, self.settings.cloud.get("table") or "Kingmaker",
                                                token=token, by=host_name)
            if table.air_token != token:
                table.air_token = token
                table.air_generation += 1
                sync.write_table(client, table, by=host_name)
        except Exception as error:          # unreachable, refused: kept locally for now
            err = error
            self.post(lambda: self.append_log(f"cloud: {err}"))
            return
        self.table = table
        self.post(self.token_moved)

    def open_connect(self) -> None:
        wizard.ConnectDialog(self.root, self.settings, on_done=self.cloud_connected, post=self.post)

    def cloud_connected(self) -> None:
        self.token_var.set(self.settings.token)
        self.refresh_cloud()
        self.check_host()

    def forget_cloud(self) -> None:
        if self.record is not None or self.server.running:
            messagebox.showinfo(t("launcher.cloud.title"), t("launcher.load_save.stop_first"))
            return
        if not messagebox.askyesno(t("launcher.cloud.forget"), t("launcher.cloud.forget_confirm")):
            return
        if self.settings.cloud.get("role") == "admin" and messagebox.askyesno(
                t("launcher.cloud.forget"), t("launcher.cloud.revoke_confirm")):
            try:
                self.cloud_client().revoke()
            except Exception as error:
                self.append_log(t("launcher.log.cloud_revoke_failed", error=error))
        self.settings.cloud = {}
        self.other = None
        self.settings.save()
        self.refresh_cloud()

    def reflect_running(self) -> None:
        running = self.server.running
        self.start_button.config(text=t("launcher.stop") if running else t("launcher.start"),
                                 state="normal")
        if not running:
            self.browser_button.config(state="disabled")
            self.set_status(t("launcher.status.stopped"), "quiet")
        for widget in self.mode_widgets():
            widget.config(state="disabled" if running else "normal")
        self.load_button.config(state="disabled" if running else "normal")

    def mode_widgets(self) -> list:
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

    def verify_address(self, address: str, secret: str) -> None:
        """Asks the public address who answers there, three times over half
        a minute (the relay takes a moment to route a new device): this
        server, proven by its own secret, or another program."""
        why = ""
        for attempt in range(3):
            nonce = secrets.token_hex(8)
            data, why = core.probe_address(address, nonce)
            if data is not None:
                ok = data.get("proof") == core.whoami_proof(secret, nonce)
                self.post(lambda: self.address_checked(ok, address))
                return
            if attempt < 2:
                time.sleep(10)
        reason = why
        self.post(lambda: self.append_log("cloud: " + t("launcher.cloud.address_unverified", error=reason)))

    def address_checked(self, ok: bool, address: str) -> None:
        if not self.server.running:
            return
        if ok:
            self.append_log("cloud: " + t("launcher.cloud.address_ok"))
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
        dialog = tk.Toplevel(self.root)
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
            self.post(lambda: self.run_update(target))

        threading.Thread(target=work, daemon=True).start()

    def open_versions(self) -> None:
        """Every release on GitHub, to install any of them — the newest, or
        an older one when a new one misbehaves."""
        win = tk.Toplevel(self.root)
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
        win = tk.Toplevel(self.root)
        win.withdraw()                      # shown by screen.present, sized and placed
        self.settings_window = win
        win.title(t("launcher.settings"))
        win.transient(self.root)
        close = ttk.Button(win, text=t("launcher.settings.close"))
        close.pack(side="bottom", pady=(4, 12))
        scroller = screen.Scrolled(win)
        scroller.pack(padx=16, pady=12, fill="both", expand=True)
        grid = scroller.inner

        ttk.Label(grid, text=t("launcher.settings.port")).grid(row=0, column=0, sticky="w", pady=4)
        port_var = tk.StringVar(value=str(self.settings.port))
        ttk.Spinbox(grid, from_=1024, to=65535, textvariable=port_var, width=8
                    ).grid(row=0, column=1, sticky="w", padx=8)

        ttk.Label(grid, text=t("launcher.settings.language")).grid(row=1, column=0, sticky="w", pady=4)
        names = [i18n.NAMES[code] for code in i18n.LANGUAGES]
        lang_var = tk.StringVar(value=i18n.NAMES.get(self.settings.language, names[0]))
        ttk.Combobox(grid, values=names, textvariable=lang_var, state="readonly", width=12
                     ).grid(row=1, column=1, sticky="w", padx=8)

        browser_var = tk.BooleanVar(value=self.settings.open_browser)
        ttk.Checkbutton(grid, text=t("launcher.settings.browser"), variable=browser_var
                        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=4)
        updates_var = tk.BooleanVar(value=self.settings.check_updates)
        ttk.Checkbutton(grid, text=t("launcher.settings.updates"), variable=updates_var
                        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=4)

        ttk.Label(grid, text=t("launcher.folder_label", folder=core.game_folder()),
                  wraplength=380, foreground=COLOURS["quiet"]).grid(row=4, column=0, columnspan=2,
                                                                    sticky="w", pady=(8, 2))
        ttk.Button(grid, text=t("launcher.settings.folder"),
                   command=lambda: core.open_folder(core.game_folder())
                   ).grid(row=5, column=0, columnspan=2, sticky="w", pady=2)
        ttk.Button(grid, text=t("launcher.settings.reset"), command=self.reset_password
                   ).grid(row=6, column=0, columnspan=2, sticky="w", pady=2)
        ttk.Button(grid, text=t("launcher.versions.button"), command=self.open_versions
                   ).grid(row=7, column=0, columnspan=2, sticky="w", pady=(10, 2))

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
        self.root.destroy()


def bundle_manifest(path) -> dict:
    from kingmaker.storage import bundle
    return bundle.manifest(path)
