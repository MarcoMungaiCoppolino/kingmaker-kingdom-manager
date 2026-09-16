"""The two dialogs that connect a launcher to the cloud.

`SetupWizard` walks the administrator through Dropbox once: an account,
an app in the App Console (App folder, five permissions), the App key,
the authorisation with PKCE and the code pasted back. Each step has a
picture from `guide/` when one is there. `ConnectDialog` is the other
host's side: the table's address, a username and a password, exchanged
for the credential over `POST /_launcher/credential`; the password is
typed once and never kept.
"""
from __future__ import annotations

import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable

from kingmaker.launcher import core, dropbox
from kingmaker.locale.i18n import t

APP_CONSOLE = "https://www.dropbox.com/developers/apps/create"
DROPBOX_HOME = "https://www.dropbox.com/register"
STEPS = ("account", "create", "permissions", "key", "authorise", "code", "done")
COLOURS = {"quiet": "#555555", "bad": "#b71c1c", "ok": "#2e7d32"}


def guide_folder() -> Path:
    if core.is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent / "_internal")) / "guide"
    return Path(__file__).resolve().parent / "guide"


class SetupWizard:
    def __init__(self, root: tk.Tk, settings: core.Settings, on_done: Callable[[], None],
                 post: Callable[[Callable[[], None]], None] | None = None) -> None:
        self.root = root
        self.settings = settings
        self.on_done = on_done
        self.post = post or (lambda fn: root.after(0, fn))
        self.step = 0
        self.verifier = dropbox.new_verifier()
        self.app_key = tk.StringVar(value=settings.cloud.get("app_key", ""))
        self.table = tk.StringVar(value=settings.cloud.get("table", ""))
        self.code = tk.StringVar()
        self.image: tk.PhotoImage | None = None
        self.result: dict | None = None

        self.win = tk.Toplevel(root)
        self.win.title(t("launcher.wizard.title"))
        self.win.transient(root)
        self.win.grab_set()
        self.win.minsize(640, 420)
        self.body = ttk.Frame(self.win)
        self.body.pack(fill="both", expand=True, padx=14, pady=(12, 6))
        nav = ttk.Frame(self.win)
        nav.pack(fill="x", padx=14, pady=(0, 12))
        self.back = ttk.Button(nav, text=t("common.back"), command=self.go_back)
        self.back.pack(side="left")
        self.next = ttk.Button(nav, text=t("common.next"), command=self.go_next)
        self.next.pack(side="right")
        ttk.Button(nav, text=t("common.cancel"), command=self.win.destroy).pack(side="right", padx=8)
        self.show()

    # ------------------------------------------------------------- steps
    def show(self) -> None:
        for child in self.body.winfo_children():
            child.destroy()
        name = STEPS[self.step]
        ttk.Label(self.body, text=t(f"launcher.wizard.{name}.title", n=self.step + 1, total=len(STEPS)),
                  font=("TkDefaultFont", 12, "bold")).pack(anchor="w")
        ttk.Label(self.body, text=t(f"launcher.wizard.{name}.text"), wraplength=600, justify="left"
                  ).pack(anchor="w", pady=(6, 8))
        picture = guide_folder() / f"{name}.png"
        if picture.is_file():
            try:
                self.image = tk.PhotoImage(file=str(picture))
                ttk.Label(self.body, image=self.image).pack(anchor="w", pady=(0, 8))
            except tk.TclError:
                self.image = None
        row = ttk.Frame(self.body)
        row.pack(fill="x")
        if name == "account":
            ttk.Button(row, text=t("launcher.wizard.account.button"),
                       command=lambda: webbrowser.open(DROPBOX_HOME)).pack(side="left")
        elif name == "create":
            ttk.Button(row, text=t("launcher.wizard.create.button"),
                       command=lambda: webbrowser.open(APP_CONSOLE)).pack(side="left")
        elif name == "key":
            ttk.Label(row, text=t("launcher.wizard.key.label")).pack(side="left")
            ttk.Entry(row, textvariable=self.app_key, width=28).pack(side="left", padx=8)
            row2 = ttk.Frame(self.body)
            row2.pack(fill="x", pady=(8, 0))
            ttk.Label(row2, text=t("launcher.wizard.key.table")).pack(side="left")
            ttk.Entry(row2, textvariable=self.table, width=28).pack(side="left", padx=8)
        elif name == "authorise":
            ttk.Button(row, text=t("launcher.wizard.authorise.button"), command=self.open_authorise
                       ).pack(side="left")
        elif name == "code":
            ttk.Label(row, text=t("launcher.wizard.authorise.label")).pack(side="left")
            ttk.Entry(row, textvariable=self.code, width=48).pack(side="left", padx=8)
            self.feedback = ttk.Label(self.body, text="", wraplength=600, foreground=COLOURS["quiet"])
            self.feedback.pack(anchor="w", pady=(8, 0))
        elif name == "done":
            account = self.result.get("account_name", "") if self.result else ""
            ttk.Label(row, text=t("launcher.wizard.done.account", account=account),
                      foreground=COLOURS["ok"]).pack(side="left")
        self.back.config(state="normal" if 0 < self.step < len(STEPS) - 1 else "disabled")
        self.next.config(text=t("launcher.wizard.finish") if name == "done"
                         else t("launcher.wizard.connect") if name == "code" else t("common.next"))

    def go_back(self) -> None:
        if self.step > 0:
            self.step -= 1
            self.show()

    def go_next(self) -> None:
        name = STEPS[self.step]
        if name == "key" and not self.app_key.get().strip():
            messagebox.showinfo(t("launcher.wizard.title"), t("launcher.wizard.key.missing"), parent=self.win)
            return
        if name == "code":
            self.connect()
            return
        if name == "done":
            self.win.destroy()
            self.on_done()
            return
        self.step += 1
        self.show()

    # --------------------------------------------------------- authorise
    def open_authorise(self) -> None:
        webbrowser.open(dropbox.authorize_url(self.app_key.get().strip(), self.verifier))

    def connect(self) -> None:
        code = self.code.get().strip()
        if not code:
            self.feedback.config(text=t("launcher.wizard.authorise.missing"), foreground=COLOURS["bad"])
            return
        self.next.config(state="disabled")
        self.feedback.config(text=t("launcher.wizard.authorise.working"), foreground=COLOURS["quiet"])
        app_key = self.app_key.get().strip()

        def work() -> None:
            try:
                answer = dropbox.exchange_code(app_key, self.verifier, code)
                credential = dropbox.Credential(app_key=app_key, refresh_token=str(answer["refresh_token"]),
                                                account_id=str(answer.get("account_id", "")))
                # The code is spent now: whatever the name lookup does, the
                # credential is kept.
                try:
                    account = dropbox.Client(credential).account()
                    credential.account_name = str((account.get("name") or {}).get("display_name")
                                                  or account.get("email") or "")
                except dropbox.DropboxError:
                    credential.account_name = ""
                self.post(lambda: self.connected(credential))
            except (dropbox.DropboxError, KeyError, OSError) as error:
                err = error
                self.post(lambda: self.failed(err))

        threading.Thread(target=work, daemon=True).start()

    def failed(self, error: Exception) -> None:
        self.next.config(state="normal")
        self.feedback.config(text=t("launcher.wizard.authorise.failed", error=error), foreground=COLOURS["bad"])

    def connected(self, credential: dropbox.Credential) -> None:
        self.result = credential.to_dict()
        self.settings.cloud = {**credential.to_dict(), "table": self.table.get().strip() or "Kingmaker",
                               "role": "admin", "username": self.settings.cloud.get("username", "")}
        self.settings.host_name = ""
        self.settings.identity()
        self.settings.save()
        self.next.config(state="normal")
        self.step = len(STEPS) - 1
        self.show()


class ConnectDialog:
    """The other host: address, username, password → the credential."""

    def __init__(self, root: tk.Tk, settings: core.Settings, on_done: Callable[[], None],
                 post: Callable[[Callable[[], None]], None] | None = None) -> None:
        self.root = root
        self.settings = settings
        self.on_done = on_done
        self.post = post or (lambda fn: root.after(0, fn))
        self.win = tk.Toplevel(root)
        self.win.title(t("launcher.connect.title"))
        self.win.transient(root)
        self.win.grab_set()
        frame = ttk.Frame(self.win)
        frame.pack(padx=16, pady=12, fill="x")
        ttk.Label(frame, text=t("launcher.connect.text"), wraplength=460, justify="left"
                  ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        self.address = tk.StringVar(value=settings.cloud.get("address", ""))
        self.username = tk.StringVar(value=settings.cloud.get("username", ""))
        self.password = tk.StringVar()
        for i, (label, var, show) in enumerate((
                (t("launcher.connect.address"), self.address, ""),
                (t("launcher.connect.username"), self.username, ""),
                (t("launcher.connect.password"), self.password, "•"))):
            ttk.Label(frame, text=label).grid(row=i + 1, column=0, sticky="w", pady=3)
            ttk.Entry(frame, textvariable=var, width=44, show=show).grid(row=i + 1, column=1, sticky="w", padx=8)
        self.feedback = ttk.Label(frame, text="", wraplength=460, foreground=COLOURS["quiet"])
        self.feedback.grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 0))
        nav = ttk.Frame(self.win)
        nav.pack(fill="x", padx=16, pady=(0, 12))
        self.button = ttk.Button(nav, text=t("launcher.wizard.connect"), command=self.connect)
        self.button.pack(side="right")
        ttk.Button(nav, text=t("common.cancel"), command=self.win.destroy).pack(side="right", padx=8)

    def connect(self) -> None:
        address, username, password = self.address.get().strip(), self.username.get().strip(), self.password.get()
        if not address or not username or not password:
            self.feedback.config(text=t("launcher.connect.missing"), foreground=COLOURS["bad"])
            return
        self.button.config(state="disabled")
        self.feedback.config(text=t("launcher.connect.working"), foreground=COLOURS["quiet"])

        def work() -> None:
            try:
                answer = core.fetch_credential(address, username, password)
            except LookupError:
                self.post(lambda: self.failed(t("launcher.connect.refused")))
                return
            except Exception as error:      # unreachable, or an answer we cannot read
                text = t("launcher.connect.unreachable", error=error)
                self.post(lambda: self.failed(text))
                return
            self.post(lambda: self.done(answer, address))

        threading.Thread(target=work, daemon=True).start()

    def failed(self, text: str) -> None:
        self.button.config(state="normal")
        self.feedback.config(text=text, foreground=COLOURS["bad"])

    def done(self, answer: dict, address: str) -> None:
        core.adopt_credential(self.settings, answer)
        self.settings.cloud["address"] = address
        self.settings.save()
        self.win.destroy()
        self.on_done()
