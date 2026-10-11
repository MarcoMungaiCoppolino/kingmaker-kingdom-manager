"""The guides of the launcher: one window of numbered pages each.

`Wizard` is the frame they share: the window, Back / Next / Cancel, a page
that scrolls when the screen is short. The pages come in three groups,
each with its texts under its own prefix and its pictures in `guide/`:

- `air/…` (`AirPages`): the On Air token that gives the table a fixed
  address — the site, the login, GitHub, the device, the token pasted back.
- `cloud/…` (`DropboxPages`): the administrator's Dropbox, once — an
  account, an app in the App Console (App folder, five permissions), the
  App key, the authorisation with PKCE and the code pasted back.
- `welcome/…`: the questions of the first run.

`AirWizard` and `SetupWizard` are one group each, opened from the main
window. `WelcomeWizard` is the first run: who you are at the table, where
you play, and then only the pages the answers call for, the two guides
among them. `PairDialog` is the new host's side on its own, and `PairForm`
its three fields, which the welcome shows too: the table's address, the
pairing code the administrator made in the game, a name for this PC,
exchanged for the credential over `POST /_launcher/pair`; no password is
asked, and what arrives is kept only once it opened the table's folder.
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
from kingmaker.locale import i18n
from kingmaker.locale.i18n import t

APP_CONSOLE = "https://www.dropbox.com/developers/apps/create"
# The apps already made with the account: for whoever made the table's app
# before (on another PC, say) and only has to connect to it again.
APP_LIST = "https://www.dropbox.com/developers/apps"
DROPBOX_HOME = "https://www.dropbox.com/register"
# Two authorisations: the administrator's own key, then a second key "for
# the hosts", the one pairing hands out. Changing the keys replaces the
# hosts' one alone (`start="hosts_authorise"`); a lost own access is
# authorised again from `start="authorise"`, and the hosts' key follows.
STEPS = ("account", "create", "permissions", "key", "authorise", "code",
         "hosts_authorise", "hosts_code", "done")
# The same road for an app made before: picked from the list instead of
# made. The permissions page stays: an app made and left before that step
# would otherwise fail at the first upload, with its key accepted.
EXISTING_STEPS = ("account", "create", "existing", "permissions", "key", "authorise", "code",
                  "hosts_authorise", "hosts_code", "done")
AIR_STEPS = ("site", "login", "github", "add", "token", "renew", "done")
# The welcome's own pages; which of them show, and which guide pages come
# between them, depends on the answers (`WelcomeWizard.plan`).
WELCOME_STEPS = ("who", "where", "address", "others", "pair", "done")
COLOURS = {"quiet": "#555555", "bad": "#b71c1c", "ok": "#2e7d32",
           "warn": "#c8a24a", "warn_text": "#7a5200"}
# The sizes a picture may shrink to, largest first: Tk scales only by whole
# ratios. Below a quarter a screenshot is unreadable, and is left out.
FRACTIONS = ((4, 5), (3, 4), (2, 3), (3, 5), (1, 2), (2, 5), (1, 3), (1, 4))
PAGE_PAD = 14
WRAP = 600


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


def page_text(page: str, what: str, **params) -> str:
    """The text `what` ("title", "text", …) of a page, from the group's
    prefix. Spelt out per group so the i18n check sees each prefix."""
    group, name = page.split("/", 1)
    if group == "air":
        return t(f"launcher.air.wizard.{name}.{what}", **params)
    if group == "cloud":
        return t(f"launcher.wizard.{name}.{what}", **params)
    return t(f"launcher.welcome.{name}.{what}", **params)


def page_picture(page: str) -> Path | None:
    group, name = page.split("/", 1)
    if group == "air":
        return guide_folder() / "air" / f"{name}.png"
    if group == "cloud":
        # The hosts' authorisation shows the same two screens again.
        return guide_folder() / f"{name.removeprefix('hosts_')}.png"
    return None


def choice(parent: ttk.Frame, text: str, hint: str, variable: tk.StringVar, value: str,
           command: Callable[[], None] | None = None) -> ttk.Radiobutton:
    """One answer of a page: the radio button, and under it, in grey, what
    choosing it means."""
    button = ttk.Radiobutton(parent, text=text, value=value, variable=variable, command=command)
    button.pack(anchor="w", pady=(6, 0))
    ttk.Label(parent, text=hint, wraplength=WRAP - 24, justify="left", foreground=COLOURS["quiet"]
              ).pack(anchor="w", padx=(22, 0))
    return button


class Wizard:
    """One window of numbered pages with Back, Next and Cancel: the frame
    the guides share. A subclass lists its `pages` ("group/name"), draws
    each in `render`, and says in `leaving` whether Next may go on from a
    page, after doing what the page asked (a check, a save, a request)."""

    title_key = "launcher.wizard.title"
    cancel_key = "common.cancel"

    def __init__(self, root: tk.Tk, settings: core.Settings, on_done: Callable[[], None],
                 post: Callable[[Callable[[], None]], None] | None = None,
                 pages: tuple[str, ...] | list[str] = (), start: int = 0) -> None:
        self.root = root
        self.settings = settings
        self.on_done = on_done
        self.post = post or (lambda fn: root.after(0, fn))
        self.pages = list(pages)
        self.step = start
        self.image: tk.PhotoImage | None = None

        self.win = tk.Toplevel(root, class_=core.WM_CLASS)
        self.win.withdraw()                 # shown by screen.present, sized and placed
        self.win.title(t(self.title_key))
        if root.winfo_ismapped():
            # Over the window. Not at the first run, where the welcome comes
            # alone: a window kept over a hidden one is hidden with it.
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
        self.cancel_button = ttk.Button(nav, text=t(self.cancel_key), command=self.cancel)
        self.cancel_button.pack(side="right", padx=8)
        self.win.protocol("WM_DELETE_WINDOW", self.cancel)
        self.show()
        screen.present(self.win, grab=True)

    @property
    def page(self) -> str:
        return self.pages[self.step]

    @property
    def last(self) -> bool:
        return self.step >= len(self.pages) - 1

    def numbering(self) -> tuple[int, int] | None:
        """(this page's number, how many), put before the title as "Step n
        of total"; None for a window whose pages are not counted."""
        return self.step + 1, len(self.pages)

    def show(self) -> None:
        for child in self.body.winfo_children():
            child.destroy()
        page = self.page
        title = page_text(page, "title")
        counted = self.numbering()
        if counted is not None:
            title = t("launcher.wizard.step", n=counted[0], total=counted[1], title=title)
        # The words of the frame follow the language, which the welcome's
        # first page can change.
        self.win.title(t(self.title_key))
        self.back.config(text=t("common.back"))
        self.cancel_button.config(text=t(self.cancel_key))
        self.cancel_button.pack_forget()
        if self.skippable(page):
            self.cancel_button.pack(side="right", padx=8)
        header = ttk.Frame(self.body)
        header.pack(fill="x")
        ttk.Label(header, text=title, font=("TkDefaultFont", 12, "bold")).pack(side="left")
        self.header_extra(header)
        ttk.Label(self.body, text=page_text(page, "text"), wraplength=WRAP, justify="left"
                  ).pack(anchor="w", pady=(6, 8))
        row = ttk.Frame(self.body)
        row.pack(fill="x")
        self.render(page, row)
        self.back.config(state="normal" if 0 < self.step and not self.last else "disabled")
        self.next.config(text=self.next_text(page), state="normal")
        path = page_picture(page)
        self.image = picture(self.win, self.body, path, before=row) if path is not None else None
        self.scroller.to_top()

    def render(self, page: str, row: ttk.Frame) -> None:
        """The controls of a page, into `row` (and `self.body` below it)."""

    def header_extra(self, header: ttk.Frame) -> None:
        """Whatever belongs on the title's line, to the right of it."""

    def skippable(self, page: str) -> bool:
        """Whether the Cancel (or Skip) button is offered on this page."""
        return True

    def next_text(self, page: str) -> str:
        return t("launcher.wizard.finish") if self.last else t("common.next")

    def leaving(self, page: str) -> bool:
        """Whether Next may leave this page now. False holds the page: the
        page said why, or is waiting for an answer and will move on itself."""
        return True

    def go_back(self) -> None:
        if self.step > 0:
            self.step -= 1
            self.show()

    def go_next(self) -> None:
        if not self.leaving(self.page):
            return
        if self.last:
            self.finish()
            return
        self.step += 1
        self.show()

    def go_to(self, page: str) -> None:
        self.step = self.pages.index(page)
        self.show()

    def finish(self) -> None:
        self.win.destroy()
        self.on_done()

    def cancel(self) -> None:
        self.win.destroy()


class AirPages:
    """The On Air pages: what the relay does, the login the site asks for,
    GitHub, the device, and the token copied back. Nothing is asked of the
    network here — the token is only written down, and whether it works is
    answered by the first Start. Needs `token` (the field), `settings`,
    `entered` (the page the window was opened at)."""

    token: tk.StringVar
    settings: core.Settings
    entered: str
    pages: list[str]

    def render_air(self, name: str, row: ttk.Frame) -> None:
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
            # on is the field, which is the page before and not after.
            ttk.Button(row, text=t("launcher.air.wizard.renew.button"),
                       command=lambda: self.go_to("air/token")).pack(side="left")
        elif name == "done":
            # Only what is true: arriving here from the renewal page, nobody
            # has necessarily written a token down.
            if self.settings.token.strip():
                ttk.Label(row, text=t("launcher.air.wizard.done.saved"),
                          foreground=COLOURS["ok"]).pack(side="left")

    def leaving_air(self, name: str, win: tk.Toplevel) -> bool:
        if name == "token":
            if not self.token.get().strip():
                messagebox.showinfo(t("launcher.air.wizard.title"),
                                    t("launcher.air.wizard.token.missing"), parent=win)
                return False
            self.settings.token = self.token.get().strip()
            self.settings.save()
        return True



class DropboxPages:
    """The Dropbox pages, and the exchange of the code for the credential
    at the end of them. Needs `app_key`, `table`, `code` (the fields),
    `verifier`, `settings`, `post`, `next`, `body`, `result`."""

    app_key: tk.StringVar
    table: tk.StringVar
    code: tk.StringVar
    verifier: str
    settings: core.Settings
    post: Callable[[Callable[[], None]], None]
    next: ttk.Button
    body: ttk.Frame
    pages: list[str]
    step: int
    result: dict | None
    page: str
    go_to: Callable[[str], None]

    def init_cloud(self, settings: core.Settings) -> None:
        # Whether the app is one made before, picked from the list: the
        # road then has "existing" where it had "permissions".
        self.existing = False
        self.verifier = dropbox.new_verifier()
        self.app_key = tk.StringVar(value=settings.cloud.get("app_key", ""))
        self.table = tk.StringVar(value=settings.cloud.get("table", ""))
        self.code = tk.StringVar()
        self.result = None

    def render_cloud(self, name: str, row: ttk.Frame) -> None:
        if name == "account":
            ttk.Button(row, text=t("launcher.wizard.account.button"),
                       command=lambda: webbrowser.open(DROPBOX_HOME)).pack(side="left")
        elif name == "create":
            ttk.Button(row, text=t("launcher.wizard.create.button"),
                       command=lambda: webbrowser.open(APP_CONSOLE)).pack(side="left")
            ttk.Button(row, text=t("launcher.wizard.create.existing"), command=self.use_existing
                       ).pack(side="right")
        elif name == "existing":
            ttk.Button(row, text=t("launcher.wizard.existing.button"),
                       command=lambda: webbrowser.open(APP_LIST)).pack(side="left")
        elif name == "key":
            ttk.Label(row, text=t("launcher.wizard.key.label")).pack(side="left")
            ttk.Entry(row, textvariable=self.app_key, width=28).pack(side="left", padx=8)
            row2 = ttk.Frame(self.body)
            row2.pack(fill="x", pady=(8, 0))
            ttk.Label(row2, text=t("launcher.wizard.key.table")).pack(side="left")
            ttk.Entry(row2, textvariable=self.table, width=28).pack(side="left", padx=8)
            # Nobody should wonder whether the name must match something:
            # it is a label, and nothing else.
            ttk.Label(self.body, text=t("launcher.wizard.key.table_hint"), wraplength=WRAP,
                      justify="left", foreground=COLOURS["quiet"]).pack(anchor="w", pady=(4, 0))
        elif name in ("authorise", "hosts_authorise"):
            ttk.Button(row, text=t("launcher.wizard.authorise.button"), command=self.open_authorise
                       ).pack(side="left")
        elif name in ("code", "hosts_code"):
            ttk.Label(row, text=t("launcher.wizard.authorise.label")).pack(side="left")
            ttk.Entry(row, textvariable=self.code, width=48).pack(side="left", padx=8)
            self.feedback = ttk.Label(self.body, text="", wraplength=WRAP, foreground=COLOURS["quiet"])
            self.feedback.pack(anchor="w", pady=(8, 0))
        elif name == "done":
            account = self.result.get("account_name", "") if self.result else ""
            ttk.Label(row, text=t("launcher.wizard.done.account", account=account),
                      foreground=COLOURS["ok"]).pack(side="left")

    def cloud_steps(self) -> tuple[str, ...]:
        return EXISTING_STEPS if self.existing else STEPS

    def cloud_pages(self) -> list[str]:
        """The window's pages for the road chosen (`existing` or not)."""
        raise NotImplementedError

    def repage_cloud(self) -> None:
        current = self.page
        self.pages = self.cloud_pages()
        self.step = self.pages.index(current)

    def use_existing(self) -> None:
        """The app was made before: its list opens in the browser, and the
        window goes to the page that says which one to click."""
        webbrowser.open(APP_LIST)
        self.existing = True
        self.repage_cloud()
        self.go_to("cloud/existing")

    def leaving_cloud(self, name: str, win: tk.Toplevel) -> bool:
        if name == "create" and self.existing:
            # Back from the list, and on with Next: a new app after all.
            self.existing = False
            self.repage_cloud()
        if name == "key" and not self.app_key.get().strip():
            messagebox.showinfo(t("launcher.wizard.title"), t("launcher.wizard.key.missing"), parent=win)
            return False
        if name in ("code", "hosts_code"):
            self.connect(for_hosts=name == "hosts_code")
            return False                    # `connected` moves on when Dropbox answered
        if name in ("authorise", "hosts_authorise"):
            # A fresh code verifier for each authorisation: Dropbox ties the
            # code it shows to the one the page was opened with.
            self.code.set("")
        return True

    def open_authorise(self) -> None:
        webbrowser.open(dropbox.authorize_url(self.app_key.get().strip(), self.verifier))

    def connect(self, for_hosts: bool = False) -> None:
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
                self.post(lambda: self.connected(credential, for_hosts))
            except (dropbox.DropboxError, KeyError, OSError) as error:
                err = error
                self.post(lambda: self.failed(err))

        threading.Thread(target=work, daemon=True).start()

    def failed(self, error: Exception) -> None:
        self.next.config(state="normal")
        self.feedback.config(text=t("launcher.wizard.authorise.failed", error=error), foreground=COLOURS["bad"])

    def connected(self, credential: dropbox.Credential, for_hosts: bool = False) -> None:
        """The first authorisation is the administrator's own access: the
        cloud settings are made from it (the table's name, the seat's role),
        keeping the hosts' key if one is there already. The second is the
        hosts' key alone, kept next to it. Each goes to the vault at save."""
        if for_hosts:
            self.settings.cloud["hosts_refresh_token"] = credential.refresh_token
        else:
            self.result = credential.to_dict()
            kept_hosts = self.settings.cloud.get("hosts_refresh_token", "")
            self.settings.cloud = {**credential.to_dict(), "table": self.table.get().strip() or "Kingmaker",
                                   "role": "admin", "table_id": self.settings.cloud.get("table_id", ""),
                                   # The seat is Start's to create or take: until then a look
                                   # finding another key on it leaves this launcher alone.
                                   "seated": False}
            if kept_hosts:
                self.settings.cloud["hosts_refresh_token"] = kept_hosts
            self.settings.host_name = ""
            self.settings.identity()
            # The administrator trusts its own key for the table file.
            self.settings.cloud["admin_key"] = self.settings.sign_key
        self.settings.save()
        self.next.config(state="normal")
        self.verifier = dropbox.new_verifier()  # the next authorisation starts afresh
        self.code.set("")
        # The hosts' key follows the administrator's; then the group's own
        # last page when there is one, else whatever the window has next.
        if not for_hosts and "cloud/hosts_authorise" in self.pages:
            self.go_to("cloud/hosts_authorise")
            return
        self.step = self.pages.index("cloud/done") if "cloud/done" in self.pages else self.step + 1
        self.show()



class SetupWizard(DropboxPages, Wizard):
    """The administrator's Dropbox, once; or, opened at "authorise", the
    rotation of the cloud access, which needs only a fresh authorisation
    with the app key already known."""

    title_key = "launcher.wizard.title"

    def __init__(self, root: tk.Tk, settings: core.Settings, on_done: Callable[[], None],
                 post: Callable[[Callable[[], None]], None] | None = None,
                 start: str = STEPS[0]) -> None:
        self.init_cloud(settings)
        super().__init__(root, settings, on_done, post=post,
                         pages=[f"cloud/{name}" for name in STEPS], start=STEPS.index(start))

    def render(self, page: str, row: ttk.Frame) -> None:
        self.render_cloud(page.split("/", 1)[1], row)

    def cloud_pages(self) -> list[str]:
        return [f"cloud/{name}" for name in self.cloud_steps()]

    def next_text(self, page: str) -> str:
        if page in ("cloud/code", "cloud/hosts_code"):
            return t("launcher.wizard.connect")
        return super().next_text(page)

    def leaving(self, page: str) -> bool:
        return self.leaving_cloud(page.split("/", 1)[1], self.win)


class AirWizard(AirPages, Wizard):
    """The On Air token, step by step; or, opened at "renew", the page that
    tells how to make another when the one in use is lost: whoever lost it
    cannot reach that page by walking from the beginning, because the page
    before it asks for the token they have not got."""

    title_key = "launcher.air.wizard.title"

    def __init__(self, root: tk.Tk, settings: core.Settings, on_done: Callable[[], None],
                 start: str = AIR_STEPS[0]) -> None:
        self.entered = start
        self.token = tk.StringVar(value=settings.token)
        super().__init__(root, settings, on_done,
                         pages=[f"air/{name}" for name in AIR_STEPS], start=AIR_STEPS.index(start))

    def render(self, page: str, row: ttk.Frame) -> None:
        self.render_air(page.split("/", 1)[1], row)

    def next_text(self, page: str) -> str:
        if page == "air/token":
            return t("common.save")
        return super().next_text(page)

    def leaving(self, page: str) -> bool:
        return self.leaving_air(page.split("/", 1)[1], self.win)


class PairForm:
    """The three fields of pairing and the exchange behind them: the
    table's address, the code, a name for this PC → the credential, kept
    only once it opened the table's folder. Shown by `PairDialog` and by the
    welcome; the caller owns the button that starts it."""

    def __init__(self, parent: ttk.Frame, settings: core.Settings,
                 post: Callable[[Callable[[], None]], None], wrap: int = 460) -> None:
        self.settings = settings
        self.post = post
        grid = ttk.Frame(parent)
        grid.pack(fill="x")
        self.address = tk.StringVar(value=settings.cloud.get("address", ""))
        self.code = tk.StringVar()
        self.name = tk.StringVar(value=settings.identity()[1])
        for i, (label, var) in enumerate((
                (t("launcher.pair.address"), self.address),
                (t("launcher.pair.code"), self.code),
                (t("launcher.pair.name"), self.name))):
            ttk.Label(grid, text=label).grid(row=i, column=0, sticky="w", pady=3)
            ttk.Entry(grid, textvariable=var, width=44).grid(row=i, column=1, sticky="w", padx=8)
        self.feedback = ttk.Label(parent, text="", wraplength=wrap, foreground=COLOURS["quiet"])
        self.feedback.pack(anchor="w", pady=(8, 0))

    def start(self, on_ok: Callable[[str], None], on_fail: Callable[[], None]) -> bool:
        """Asks the host; False at once when a field is empty. `on_ok` gets
        the address once the credential is kept, `on_fail` after the
        feedback said what went wrong; both on the Tk thread."""
        address, code, name = self.address.get().strip(), self.code.get().strip(), self.name.get().strip()
        if not address or not code or not name:
            self.feedback.config(text=t("launcher.pair.missing"), foreground=COLOURS["bad"])
            return False
        self.feedback.config(text=t("launcher.pair.working"), foreground=COLOURS["quiet"])

        def fail(text: str) -> None:
            self.feedback.config(text=text, foreground=COLOURS["bad"])
            on_fail()

        host_id, _name = self.settings.identity()
        key = self.settings.sign_key

        def work() -> None:
            try:
                answer = core.pair(address, code, name, host_id=host_id, key=key)
            except LookupError:
                self.post(lambda: fail(t("launcher.pair.refused")))
                return
            except Exception as error:      # unreachable, or an answer we cannot read
                text = t("launcher.pair.unreachable", error=error)
                self.post(lambda: fail(text))
                return
            try:
                # Kept only once it opened the table's folder, and the table
                # there is the one the host named.
                core.adopt_pairing(self.settings, answer, host_name=name)
            except LookupError:
                self.post(lambda: fail(t("launcher.pair.mismatch")))
                return
            except Exception as error:      # the cloud did not answer the check
                text = t("launcher.pair.unreachable", error=error)
                self.post(lambda: fail(text))
                return
            self.settings.cloud["address"] = address
            self.settings.save()
            self.post(lambda: on_ok(address))

        threading.Thread(target=work, daemon=True).start()
        return True


class PairDialog:
    """The new host, from the main window: the pairing form and its button."""

    def __init__(self, root: tk.Tk, settings: core.Settings, on_done: Callable[[], None],
                 post: Callable[[Callable[[], None]], None] | None = None) -> None:
        self.root = root
        self.settings = settings
        self.on_done = on_done
        self.post = post or (lambda fn: root.after(0, fn))
        self.win = tk.Toplevel(root, class_=core.WM_CLASS)
        self.win.withdraw()                 # shown by screen.present, sized and placed
        self.win.title(t("launcher.pair.title"))
        self.win.transient(root)
        nav = ttk.Frame(self.win)
        nav.pack(side="bottom", fill="x", padx=16, pady=(0, 12))
        scroller = screen.Scrolled(self.win)
        scroller.pack(padx=16, pady=12, fill="both", expand=True)
        frame = scroller.inner
        ttk.Label(frame, text=t("launcher.pair.text"), wraplength=460, justify="left"
                  ).pack(anchor="w", pady=(0, 8))
        self.form = PairForm(frame, settings, self.post)
        self.feedback = self.form.feedback
        self.button = ttk.Button(nav, text=t("launcher.pair.button"), command=self.connect)
        self.button.pack(side="right")
        ttk.Button(nav, text=t("common.cancel"), command=self.win.destroy).pack(side="right", padx=8)
        screen.present(self.win, grab=True)

    def connect(self) -> None:
        if self.form.start(self.done, lambda: self.button.config(state="normal")):
            self.button.config(state="disabled")

    def failed(self, text: str) -> None:
        self.button.config(state="normal")
        self.feedback.config(text=text, foreground=COLOURS["bad"])

    def done(self, address: str) -> None:
        self.win.destroy()
        self.on_done()


class WelcomeWizard(AirPages, DropboxPages, Wizard):
    """The first run. Who you are at the table decides everything after:
    the administrator says where the game is played, whether the table gets
    a fixed address (the On Air pages, a token they have, or later) and
    whether anyone else may host (the Dropbox pages, or just them); a host
    pairs with the table, whose address says where it is played. The last
    page says what was set and what to press first, and where to change it.
    Skipping it marks the welcome as seen all the same. Closing its window
    closes the launcher: before the first answer the welcome asks again at
    the next start, after it the answers so far are kept, as with Skip."""

    title_key = "launcher.welcome.title"
    cancel_key = "launcher.welcome.skip"

    def __init__(self, root: tk.Tk, settings: core.Settings, on_done: Callable[[], None],
                 post: Callable[[Callable[[], None]], None] | None = None,
                 on_quit: Callable[[], None] | None = None) -> None:
        self.settings = settings                 # `plan` reads it before the frame is built
        # Closing the window closes the launcher (`close`), Skip goes on to
        # the main window (`cancel`).
        self.on_quit = on_quit or on_done
        self.chosen = False
        self.entered = "site"
        self.token = tk.StringVar(value=settings.token)
        self.init_cloud(settings)
        self.who = tk.StringVar(value="host" if settings.host else "admin")
        self.mode = tk.StringVar(value=settings.mode)
        self.air_way = tk.StringVar(value="have" if settings.token.strip() else "guide")
        self.cloud_way = tk.StringVar(value="alone")
        self.form: PairForm | None = None
        self.paired_to = ""
        super().__init__(root, settings, on_done, post=post, pages=self.plan())
        self.win.protocol("WM_DELETE_WINDOW", self.close)

    # -------------------------------------------------------------- pages
    def plan(self) -> list[str]:
        """The pages the answers so far call for, from the first to the
        summary. Recomputed whenever an answer changes; the page we are on
        keeps its place, so Back and Next still mean what they did."""
        pages = ["welcome/who"]
        if self.who.get() == "host":
            pages.append("welcome/pair")
        else:
            pages.append("welcome/where")
            # A table already set up keeps its address and its folder: the
            # welcome run again from the Settings asks neither.
            if self.mode.get() == "online" and not self.settings.cloud_ready:
                pages.append("welcome/address")
                if self.air_way.get() == "guide":
                    pages += [f"air/{name}" for name in AIR_STEPS[:AIR_STEPS.index("token") + 1]]
            if self.mode.get() in ("lan", "online") and not self.settings.cloud_ready:
                pages.append("welcome/others")
                if self.cloud_way.get() == "cloud":
                    pages += [f"cloud/{name}" for name in self.cloud_steps()[:-1]]
        pages.append("welcome/done")
        return pages

    def replan(self) -> None:
        current = self.page
        self.pages = self.plan()
        if current in self.pages:
            self.step = self.pages.index(current)
        self.show()

    def numbering(self) -> None:
        # No "Step n of total" here: every answer (who you are, where you
        # play, a guide or not, a new Dropbox app or one made before) changes
        # how many pages follow, and a count that changes under the reader's
        # eyes is worse than none. The guides opened alone keep theirs.
        return None

    def cloud_pages(self) -> list[str]:
        return self.plan()

    def header_extra(self, header: ttk.Frame) -> None:
        # The language, on every page's title line: whoever reads no English
        # must be able to read the rest, and must not have to go back for
        # it. The choice is the launcher's, saved at once.
        names = [i18n.NAMES[code] for code in i18n.LANGUAGES]
        shown = self.settings.language or i18n.current()
        self.language = tk.StringVar(value=i18n.NAMES.get(shown, names[0]))
        box = ttk.Combobox(header, values=names, textvariable=self.language, state="readonly", width=10)
        box.pack(side="right")
        box.bind("<<ComboboxSelected>>", lambda _e: self.language_chosen())

    def skippable(self, page: str) -> bool:
        # Who you are is not skipped: it decides the rest. The summary has
        # Finish. Anything in between may wait for another day.
        return page != "welcome/who" and not self.last

    def language_chosen(self) -> None:
        chosen = next((code for code in i18n.LANGUAGES if i18n.NAMES[code] == self.language.get()),
                      self.settings.language)
        if chosen == self.settings.language:
            return
        self.settings.language = chosen
        self.settings.save()
        self.show()                         # the same page, in the chosen language

    def render(self, page: str, row: ttk.Frame) -> None:
        group, name = page.split("/", 1)
        if group == "air":
            self.render_air(name, row)
        elif group == "cloud":
            self.render_cloud(name, row)
        elif name == "who":
            choice(row, t("launcher.welcome.who.admin"), t("launcher.welcome.who.admin_hint"),
                   self.who, "admin", self.replan)
            choice(row, t("launcher.welcome.who.host"), t("launcher.welcome.who.host_hint"),
                   self.who, "host", self.replan)
            # A word of caution, framed and headed, so it reads as advice
            # and not as one more thing to do.
            note = tk.Frame(self.body, highlightbackground=COLOURS["warn"], highlightthickness=1, bd=0)
            note.pack(fill="x", pady=(16, 0))
            ttk.Label(note, text=t("launcher.welcome.who.note_title"), foreground=COLOURS["warn_text"],
                      font=("TkDefaultFont", 9, "bold")).pack(anchor="w", padx=10, pady=(6, 0))
            ttk.Label(note, text=t("launcher.welcome.who.note"), wraplength=WRAP - 24, justify="left"
                      ).pack(anchor="w", padx=10, pady=(2, 8))
        elif name == "where":
            for mode in core.MODES:
                choice(row, t(f"launcher.mode.{mode}"), t(f"launcher.mode.{mode}_hint"),
                       self.mode, mode, self.replan)
        elif name == "address":
            choice(row, t("launcher.welcome.address.guide"), t("launcher.welcome.address.guide_hint"),
                   self.air_way, "guide", self.replan)
            choice(row, t("launcher.welcome.address.have"), t("launcher.welcome.address.have_hint"),
                   self.air_way, "have", self.replan)
            field = ttk.Frame(row)
            field.pack(fill="x", padx=(22, 0), pady=(4, 0))
            ttk.Label(field, text=t("launcher.air.field")).pack(side="left")
            ttk.Entry(field, textvariable=self.token, width=48, show="•").pack(side="left", padx=8)
            choice(row, t("launcher.welcome.address.later"), t("launcher.welcome.address.later_hint"),
                   self.air_way, "later", self.replan)
        elif name == "others":
            choice(row, t("launcher.welcome.others.alone"), t("launcher.welcome.others.alone_hint"),
                   self.cloud_way, "alone", self.replan)
            choice(row, t("launcher.welcome.others.cloud"), t("launcher.welcome.others.cloud_hint"),
                   self.cloud_way, "cloud", self.replan)
        elif name == "pair":
            self.form = PairForm(row, self.settings, self.post, wrap=WRAP)
            self.feedback = self.form.feedback
        elif name == "done":
            ttk.Label(row, text=self.summary(), wraplength=WRAP, justify="left").pack(anchor="w")
            # Where to undo it all: the one place that says so, read by
            # everyone who comes this far, and nothing more in the window.
            ttk.Label(row, text=t("launcher.welcome.done.change", settings=t("launcher.settings"),
                                  reset=t("launcher.settings.reset_setup")),
                      wraplength=WRAP, justify="left", foreground=COLOURS["quiet"]
                      ).pack(anchor="w", pady=(12, 0))

    def summary(self) -> str:
        """What was set, line by line, and the first thing to press."""
        settings = self.settings
        lines = []
        if self.who.get() == "host":
            lines.append(t("launcher.welcome.done.paired", table=settings.cloud.get("table", "")))
            lines.append(t("launcher.welcome.done.mode", mode=t(f"launcher.mode.{settings.mode}")))
            lines.append(t("launcher.welcome.done.start_host"))
            return "\n".join(lines)
        mode = self.mode.get()
        lines.append(t("launcher.welcome.done.mode", mode=t(f"launcher.mode.{mode}")))
        if mode == "online":
            if settings.cloud_ready:
                lines.append(t("launcher.welcome.done.address_table"))
            elif settings.token.strip() and self.air_way.get() != "later":
                lines.append(t("launcher.welcome.done.address_fixed"))
            else:
                lines.append(t("launcher.welcome.done.address_random"))
        if mode in ("lan", "online"):
            if settings.cloud_ready:
                lines.append(t("launcher.welcome.done.table", table=settings.cloud.get("table", ""),
                               account=settings.cloud.get("account_name", "")))
            else:
                lines.append(t("launcher.welcome.done.alone"))
        lines.append(t("launcher.welcome.done.start_admin"))
        return "\n".join(lines)

    def next_text(self, page: str) -> str:
        if page == "welcome/pair":
            return t("launcher.pair.button")
        if page in ("cloud/code", "cloud/hosts_code"):
            return t("launcher.wizard.connect")
        if page == "air/token":
            return t("common.save")
        return super().next_text(page)

    def leaving(self, page: str) -> bool:
        group, name = page.split("/", 1)
        if group == "air":
            return self.leaving_air(name, self.win)
        if group == "cloud":
            return self.leaving_cloud(name, self.win)
        if name == "who":
            # Kept at once: a Skip further on still leaves the launcher
            # knowing which main window is its own.
            self.settings.role = self.who.get()
            self.settings.save()
            self.chosen = True
        if name == "address" and self.air_way.get() == "have":
            return self.leaving_air("token", self.win)
        if name == "pair":
            assert self.form is not None
            if self.form.start(self.paired, lambda: self.next.config(state="normal")):
                self.next.config(state="disabled")
            return False
        if name == "done":
            self.settings.mode = self.mode.get()
        return True

    def paired(self, address: str) -> None:
        # The address says where the table is played: through the relay, or
        # on the network. The host does not choose.
        self.settings.mode = core.mode_for_address(address)
        self.settings.save()
        self.step += 1
        self.show()

    def finish(self) -> None:
        self.settings.welcomed = core.WELCOME_REVISION
        self.settings.save()
        super().finish()

    def cancel(self) -> None:
        # Skip: not asked again, the role's window shows, and Reset the
        # setup brings the welcome back. (Not offered before the role.)
        if not self.chosen:
            self.close()
            return
        self.settings.welcomed = core.WELCOME_REVISION
        self.settings.save()
        self.win.destroy()
        self.on_done()

    def close(self) -> None:
        # The window's own close button closes the launcher. Before the role
        # was given (Next on the first page) nothing was decided, and the
        # welcome asks again at the next start; after it, the answers so far
        # are kept as with Skip, and the next start opens the main window.
        if self.chosen:
            self.settings.welcomed = core.WELCOME_REVISION
            self.settings.save()
        self.win.destroy()
        self.on_quit()
