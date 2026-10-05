"""The three dialogs that set a launcher up for playing with others.

`SetupWizard` walks the administrator through Dropbox once: an account,
an app in the App Console (App folder, five permissions), the App key,
the authorisation with PKCE and the code pasted back. `AirWizard` does
the same for the On Air token that gives the table a fixed address: the
site, the login, GitHub, the token pasted back. Each step of either has
a picture from `guide/` when one is there. `ConnectDialog` is the other
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

from kingmaker.launcher import core, dropbox, screen
from kingmaker.locale.i18n import t

APP_CONSOLE = "https://www.dropbox.com/developers/apps/create"
DROPBOX_HOME = "https://www.dropbox.com/register"
STEPS = ("account", "create", "permissions", "key", "authorise", "code", "done")
AIR_STEPS = ("site", "login", "github", "add", "token", "renew", "done")
COLOURS = {"quiet": "#555555", "bad": "#b71c1c", "ok": "#2e7d32"}
# The sizes a picture may shrink to, largest first: Tk scales only by whole
# ratios. Below a quarter a screenshot is unreadable, and is left out.
FRACTIONS = ((4, 5), (3, 4), (2, 3), (3, 5), (1, 2), (2, 5), (1, 3), (1, 4))
PAGE_PAD = 14


def guide_folder() -> Path:
    if core.is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent / "_internal")) / "guide"
    return Path(__file__).resolve().parent / "guide"


def picture(win: tk.Toplevel, parent: ttk.Frame, path: Path, before: tk.Widget) -> tk.PhotoImage | None:
    """The picture of a step, shown when the folder has one, above `before`.
    A missing or unreadable file leaves the text of the step to stand on its
    own; the caller keeps the returned image alive, or Tk throws it away.

    It is shrunk to the room the screen has left once the rest of the step
    is laid out: at full size, a laptop's screen put the buttons of the
    dialog below its bottom edge, where they could not be pressed. What
    still does not fit scrolls (`screen.Scrolled`)."""
    if not path.is_file():
        return None
    try:
        image = tk.PhotoImage(file=str(path))
    except tk.TclError:
        return None
    wider, taller = screen.room(win)
    image = fit(image, win.winfo_reqwidth() + wider - 2 * PAGE_PAD - screen.BAR, taller - 8)
    if image is not None:
        ttk.Label(parent, image=image).pack(anchor="w", pady=(0, 8), before=before)
    return image


def fit(image: tk.PhotoImage, width: int, height: int) -> tk.PhotoImage | None:
    """The image as it is when it fits in width × height, else the largest
    of FRACTIONS of it that does; None when not even the smallest does."""
    if image.width() <= width and image.height() <= height:
        return image
    for zoom, subsample in FRACTIONS:
        if image.width() * zoom // subsample <= width and image.height() * zoom // subsample <= height:
            smaller = tk.PhotoImage(master=image.tk)
            # One pass in Tk: zooming first and subsampling after would hold
            # an image three times the size in between.
            smaller.tk.call(smaller, "copy", image, "-zoom", zoom, zoom, "-subsample", subsample, subsample)
            return smaller
    return None


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
        self.win.withdraw()                 # shown by screen.present, sized and placed
        self.win.title(t("launcher.wizard.title"))
        self.win.transient(root)
        self.win.minsize(640, 420)
        # The buttons first and at the bottom: when the window is short of
        # room, pack takes it from the step and not from them.
        nav = ttk.Frame(self.win)
        nav.pack(side="bottom", fill="x", padx=14, pady=(0, 12))
        self.scroller = screen.Scrolled(self.win)
        self.scroller.pack(fill="both", expand=True, padx=PAGE_PAD, pady=(12, 6))
        self.body = self.scroller.inner
        self.back = ttk.Button(nav, text=t("common.back"), command=self.go_back)
        self.back.pack(side="left")
        self.next = ttk.Button(nav, text=t("common.next"), command=self.go_next)
        self.next.pack(side="right")
        ttk.Button(nav, text=t("common.cancel"), command=self.win.destroy).pack(side="right", padx=8)
        self.show()
        screen.present(self.win, grab=True)

    # ------------------------------------------------------------- steps
    def show(self) -> None:
        for child in self.body.winfo_children():
            child.destroy()
        name = STEPS[self.step]
        ttk.Label(self.body, text=t(f"launcher.wizard.{name}.title", n=self.step + 1, total=len(STEPS)),
                  font=("TkDefaultFont", 12, "bold")).pack(anchor="w")
        ttk.Label(self.body, text=t(f"launcher.wizard.{name}.text"), wraplength=600, justify="left"
                  ).pack(anchor="w", pady=(6, 8))
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
        self.image = picture(self.win, self.body, guide_folder() / f"{name}.png", before=row)
        self.scroller.to_top()

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


class AirWizard:
    """The On Air token, step by step: what the relay does, the login the
    site asks for, GitHub, and the token copied back into the launcher.
    Nothing is asked of the network here — the token is only written down,
    and whether it works is answered by the first Start."""

    def __init__(self, root: tk.Tk, settings: core.Settings, on_done: Callable[[], None],
                 start: str = AIR_STEPS[0]) -> None:
        self.settings = settings
        self.on_done = on_done
        # Opened at a step of its own when the launcher asks for one: whoever
        # has lost the token cannot reach the step that tells how to make
        # another by walking from the beginning, because the step before it
        # is the one that asks for the token they have not got.
        self.step = AIR_STEPS.index(start)
        self.entered = start
        self.token = tk.StringVar(value=settings.token)
        self.image: tk.PhotoImage | None = None

        self.win = tk.Toplevel(root)
        self.win.withdraw()                 # shown by screen.present, sized and placed
        self.win.title(t("launcher.air.wizard.title"))
        self.win.transient(root)
        self.win.minsize(640, 420)
        # The buttons first and at the bottom: when the window is short of
        # room, pack takes it from the step and not from them.
        nav = ttk.Frame(self.win)
        nav.pack(side="bottom", fill="x", padx=14, pady=(0, 12))
        self.scroller = screen.Scrolled(self.win)
        self.scroller.pack(fill="both", expand=True, padx=PAGE_PAD, pady=(12, 6))
        self.body = self.scroller.inner
        self.back = ttk.Button(nav, text=t("common.back"), command=self.go_back)
        self.back.pack(side="left")
        self.next = ttk.Button(nav, text=t("common.next"), command=self.go_next)
        self.next.pack(side="right")
        ttk.Button(nav, text=t("common.cancel"), command=self.win.destroy).pack(side="right", padx=8)
        self.show()
        screen.present(self.win, grab=True)

    def show(self) -> None:
        for child in self.body.winfo_children():
            child.destroy()
        name = AIR_STEPS[self.step]
        ttk.Label(self.body, text=t(f"launcher.air.wizard.{name}.title",
                                    n=self.step + 1, total=len(AIR_STEPS)),
                  font=("TkDefaultFont", 12, "bold")).pack(anchor="w")
        ttk.Label(self.body, text=t(f"launcher.air.wizard.{name}.text"), wraplength=600,
                  justify="left").pack(anchor="w", pady=(6, 8))
        row = ttk.Frame(self.body)
        row.pack(fill="x")
        if name == "site":
            ttk.Button(row, text=t("launcher.air.wizard.site.button"),
                       command=lambda: webbrowser.open(core.ON_AIR_PAGE)).pack(side="left")
        elif name == "token":
            ttk.Label(row, text=t("launcher.air.wizard.token.label")).pack(side="left")
            entry = ttk.Entry(row, textvariable=self.token, width=48)
            entry.pack(side="left", padx=8)
            entry.focus_set()
        elif name == "renew" and self.entered == "renew":
            # Opened here from the launcher, with a token to replace: the way
            # on is the field, which is the step before and not after.
            ttk.Button(row, text=t("launcher.air.wizard.renew.button"),
                       command=self.to_token).pack(side="left")
        elif name == "done":
            # Only what is true: arriving here from the renewal step, nobody
            # has necessarily written a token down.
            if self.settings.token.strip():
                ttk.Label(row, text=t("launcher.air.wizard.done.saved"),
                          foreground=COLOURS["ok"]).pack(side="left")
        self.back.config(state="normal" if 0 < self.step < len(AIR_STEPS) - 1 else "disabled")
        self.next.config(text=t("launcher.wizard.finish") if name == "done"
                         else t("common.save") if name == "token" else t("common.next"))
        self.image = picture(self.win, self.body, guide_folder() / "air" / f"{name}.png", before=row)
        self.scroller.to_top()

    def to_token(self) -> None:
        self.step = AIR_STEPS.index("token")
        self.show()

    def go_back(self) -> None:
        if self.step > 0:
            self.step -= 1
            self.show()

    def go_next(self) -> None:
        name = AIR_STEPS[self.step]
        if name == "token":
            if not self.token.get().strip():
                messagebox.showinfo(t("launcher.air.wizard.title"),
                                    t("launcher.air.wizard.token.missing"), parent=self.win)
                return
            self.settings.token = self.token.get().strip()
            self.settings.save()
        if name == "done":
            self.win.destroy()
            self.on_done()
            return
        self.step += 1
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
        self.win.withdraw()                 # shown by screen.present, sized and placed
        self.win.title(t("launcher.connect.title"))
        self.win.transient(root)
        nav = ttk.Frame(self.win)
        nav.pack(side="bottom", fill="x", padx=16, pady=(0, 12))
        scroller = screen.Scrolled(self.win)
        scroller.pack(padx=16, pady=12, fill="both", expand=True)
        frame = scroller.inner
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
        self.button = ttk.Button(nav, text=t("launcher.wizard.connect"), command=self.connect)
        self.button.pack(side="right")
        ttk.Button(nav, text=t("common.cancel"), command=self.win.destroy).pack(side="right", padx=8)
        screen.present(self.win, grab=True)

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
