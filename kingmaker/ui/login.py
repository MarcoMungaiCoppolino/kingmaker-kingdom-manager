"""Login pages, user bar and account management."""
from __future__ import annotations

from nicegui import app, run, ui
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import RedirectResponse

from kingmaker.access import auth, pairing, permissions
from kingmaker import config
from kingmaker.locale import i18n, units
from kingmaker.locale.i18n import t
from kingmaker.state import STATE
from kingmaker.ui import theme

# Paths reachable without having logged in. Besides the login page, the
# NiceGUI static files and the websocket channel are needed, otherwise the
# login page would arrive without style and without javascript.
# `/_launcher/shutdown` answers only the launcher that started the server,
# with its secret (`main.launcher_route`): nobody else gets past a 404.
OPEN_PAGES = {"/login", "/favicon.ico", "/_launcher/shutdown", "/_launcher/status",
              "/_launcher/snapshot", "/_launcher/synced", "/_launcher/whoami",
              "/_launcher/pairing", "/_launcher/pair", "/_launcher/credential"}
# `/_km/fonts/` holds the typefaces the app serves itself (`theme.FONTS_ROUTE`):
# the login page wears them too, before anyone has signed in.
OPEN_PREFIXES = ("/_nicegui/", "/_nicegui_ws", "/_km/fonts/")


def _is_free(path: str, prefix: str = "") -> bool:
    """Whether that path may be seen without having logged in.

    The prefix must be stripped before looking. Under On Air the address that
    arrives is `/name/device-0/login`, which is not `/login`: the login page
    did not count as open, was redirected to itself, and whoever arrived for
    the first time found «redirected you too many times». Whoever had already
    logged in did not notice — with the session in their pocket they never go
    through that redirect.
    """
    if prefix and path.startswith(prefix):
        path = path[len(prefix):] or "/"
    return path in OPEN_PAGES or path.startswith(OPEN_PREFIXES)


# The On Air prefix on the redirect is **not** added by us. NiceGUI has its
# own `RedirectWithPrefixMiddleware` that adds `X-Forwarded-Prefix` to every
# `Location` starting with «/», and ours ran inside that one: the result was
# the prefix written twice — `/name/device-0/name/device-0/login` — an
# address that does not exist. The browser followed it, was redirected again,
# and after a few rounds gave up with «redirected you too many times».
#
# Whoever had already logged in never saw it, and that is why it stayed
# hidden: with the session in their pocket that redirect does not fire. Only
# whoever arrived for the first time found it, which is exactly the person
# who cannot work around it.


class AccessMiddleware(BaseHTTPMiddleware):
    """Bars everything that is not a page protected by hand.

    The real check is inside the pages, but alone it would not suffice: the
    `/assets` folder is a static mount, not a page, and without this filter
    anyone who guessed a file name would have downloaded it from the public
    On Air address.
    """

    async def dispatch(self, request, call_next):
        # The relay delivers the path already without the prefix (it passes it
        # separately, in `X-Forwarded-Prefix`), but behind a reverse proxy
        # mounted under a path the `root_path` stays attached: it is stripped
        # before looking.
        prefix = theme.request_prefix(request)
        if (not _is_free(request.url.path, prefix)
                and auth.id_in_session() is None):
            return RedirectResponse("/login")
        return await call_next(request)


# ---------------------------------------------------------------------------
def _accept_language(request_) -> str | None:
    """What the browser asks for, from the `Accept-Language` header."""
    try:
        return request_.headers.get("accept-language") if request_ else None
    except AttributeError:
        return None


def _session_language() -> str | None:
    """The language chosen on this browser before logging in."""
    try:
        return app.storage.user.get("lang")
    except (RuntimeError, AttributeError):
        return None


def language_for(user: auth.User | None, request_) -> str:
    """The language a page must be drawn in: the person's choice, then the
    choice made on the login page, then the browser's, then the server's."""
    preferred = user.language if user is not None else None
    return i18n.resolve(preferred or _session_language(), _accept_language(request_),
                        config.LANG)


def units_for(user: auth.User | None) -> str:
    """Metres or feet for this window: the person's choice, else what the
    language suggests (feet with the English books, metres with the Italian)."""
    preferred = user.units if user is not None else None
    return units.resolve(preferred or app.storage.user.get("units"), theme.language())


def units_button(user: auth.User | None) -> None:
    """The m/ft toggle next to the language: shows the unit it switches to."""
    target = units.other()

    def switch() -> None:
        app.storage.user["units"] = target
        if user is not None:
            STATE.archive.update_user(user.id, units=target)
        ui.navigate.reload()

    ui.button(target, on_click=switch).props("flat dense size=sm") \
        .tooltip(t("units.switch_tooltip",
                   unit=t("units.feet") if target == "ft" else t("units.metres")))


def language_button(user: auth.User | None) -> None:
    """The IT/EN toggle: shows the language it switches to, and reloads."""
    target = i18n.other()

    def switch() -> None:
        app.storage.user["lang"] = target
        if user is not None:
            STATE.archive.update_user(user.id, language=target)
        ui.navigate.reload()

    ui.button(target.upper(), on_click=switch).props("flat dense size=sm") \
        .tooltip(t("language.switch_tooltip", language=i18n.NAMES[target]))


@ui.page("/login")
async def login_page() -> None:
    theme.apply_theme()
    theme.set_language(language_for(None, getattr(ui.context.client, "request", None)))
    ui.page_title(t("app.login_title"))

    if auth.id_in_session():
        ui.navigate.to("/")
        return

    with ui.column().classes("w-full items-center").style("padding-top:8vh"):
        with ui.card().classes("km-panel").style("min-width:340px;max-width:400px"):
            with ui.row().classes("w-full items-center no-wrap"):
                ui.html(f'<div class="km-title" style="font-size:1.6rem;display:flex;align-items:center;'
                        f'gap:8px;white-space:nowrap">{theme.crest(34, margin="0")}<span>Kingmaker</span></div>')
                ui.element("div").style("flex:1")
                language_button(None)
            ui.label(t("login.kingdom_belongs_whoever_governs")) \
                .style("color:var(--km-muted);font-size:.85rem")
            theme.sep()

            name_field = ui.input(t("login.username")).props("outlined dense autofocus") \
                .classes("w-full")
            pw_field = ui.input(t("login.password"), password=True, password_toggle_button=True) \
                .props("outlined dense").classes("w-full")
            # The second step, for an account with a second factor: shown
            # once the password passed, in place of the two fields above.
            code_prompt = ui.label(t("login.code_prompt")).style("color:var(--km-muted);font-size:.8rem")
            code_field = ui.input(t("login.code")).props("outlined dense inputmode=numeric").classes("w-full")
            code_prompt.set_visibility(False)
            code_field.set_visibility(False)
            warning = ui.label("").style("color:var(--km-red);font-size:.8rem;min-height:1.2em")
            pending: dict = {"user": None}

            def finish(user: auth.User) -> None:
                auth.log_in(user)
                # The first login adopts the language chosen on this page.
                if user.language is None:
                    STATE.archive.update_user(user.id, language=theme.language())
                ui.navigate.to("/")

            async def enters() -> None:
                if pending["user"] is not None:
                    # The password passed already: the one-time code now.
                    user = pending["user"]
                    code = (code_field.value or "").strip()
                    wait = auth.remaining_wait(user.username)
                    if wait > 0:
                        warning.set_text(t("login.too_many_attempts_try", wait=wait))
                        return
                    if not code or not auth.second_factor_ok(STATE.archive, user.id, code):
                        warning.set_text(t("login.invalid_code"))
                        code_field.set_value("")
                        return
                    finish(user)
                    return
                name = (name_field.value or "").strip()
                pw = pw_field.value or ""
                if not name or not pw:
                    warning.set_text(t("login.username_password_are_required"))
                    return
                ip = auth.client_ip(ui.context.client)
                wait = auth.remaining_wait(name, ip)
                if wait > 0:
                    key = ("login.everyone_waits" if auth.global_wait() >= wait
                           else "login.too_many_attempts_try")
                    warning.set_text(t(key, wait=wait))
                    return

                button.props("loading")
                # Computing the password takes half a second of processor: if
                # we did it here it would block the other players too.
                user = await run.io_bound(auth.verify, STATE.archive, name, pw, ip)
                button.props(remove="loading")

                if user is None:
                    # Same message for a non-existent user and a wrong
                    # password: the message must not reveal which names exist.
                    warning.set_text(t("login.invalid_username_password"))
                    pw_field.set_value("")
                    return
                if user.second_factor:
                    pending["user"] = user
                    warning.set_text("")
                    name_field.set_visibility(False)
                    pw_field.set_visibility(False)
                    code_prompt.set_visibility(True)
                    code_field.set_visibility(True)
                    code_field.run_method("focus")
                    button.set_text(t("login.confirm"))
                    return
                finish(user)

            name_field.on("keydown.enter", enters)
            pw_field.on("keydown.enter", enters)
            code_field.on("keydown.enter", enters)
            button = ui.button(t("login.sign"), on_click=enters).props("color=amber").classes("w-full")


@ui.page("/logout")
def logout_page() -> None:
    auth.log_out()
    ui.navigate.to("/login")


# ---------------------------------------------------------------------------
def user_bar(user: auth.User) -> None:
    """Who you are and how to leave, at the end of the header."""
    # What this window recorded when its page was built: a redraw caused by
    # another player's click would otherwise read that player's session.
    behind = auth.impersonator(STATE.archive, theme.window_state().get("real_id"))
    with ui.row().classes("items-center gap-2 no-wrap"):
        if behind is not None:
            # An invisible disguise is another matter: here it shows, and the
            # way to take it off sits next to the caption.
            ui.html(t("login.span_class_km_chip", esc=theme.esc(user.username)))
            ui.button(t("login.back", username=behind.username), icon="undo",
                      on_click=_back_to_self) \
                .props("flat dense size=sm color=amber")
        ui.html(f'<span class="km-chip" style="font-size:.7rem">'
                f'{theme.esc(user.username)} · {theme.esc(user.role_name)}</span>')
        language_button(user)
        units_button(user)
        if user.can(permissions.MANAGE_USERS):
            ui.button(icon="manage_accounts", on_click=lambda: users_dialog(user)) \
                .props("flat dense round size=sm").tooltip(t("login.player_accounts"))
        ui.button(icon="key", on_click=lambda: change_password_dialog(user)) \
            .props("flat dense round size=sm").tooltip(t("login.change_password"))
        ui.button(icon="verified_user", on_click=lambda: second_factor_dialog(user)) \
            .props("flat dense round size=sm").tooltip(t("login.second_factor"))
        ui.button(icon="logout", on_click=lambda: ui.navigate.to("/logout")) \
            .props("flat dense round size=sm").tooltip(t("login.sign_out"))


def second_factor_dialog(user: auth.User) -> None:
    """The one-time code after the password: switched on with a secret the
    authenticator app takes, confirmed with a code it shows, the eight
    recovery codes shown once; switched off with a code."""
    from kingmaker.access import totp
    row = STATE.archive.user_by_id(user.id)
    enabled = bool(row and row["totp_secret"])
    with theme.dialog() as dlg, ui.card().classes("km-panel").style("min-width:360px;max-width:460px"):
        theme.title(t("login.second_factor"), 2)
        if enabled:
            ui.label(t("login.sf.on_text", n=auth.recovery_codes_left(STATE.archive, user.id))) \
                .style("color:var(--km-muted);font-size:.82rem;white-space:normal")
            code_field = ui.input(t("login.sf.disable_code")).props("outlined dense inputmode=numeric") \
                .classes("w-full")
            warning = ui.label("").style("color:var(--km-red);font-size:.8rem;min-height:1.2em")

            def disable() -> None:
                if not auth.second_factor_ok(STATE.archive, user.id, (code_field.value or "").strip()):
                    warning.set_text(t("login.sf.wrong"))
                    return
                auth.disable_second_factor(STATE.archive, user.id, by=user.username)
                STATE.record(t("login.sf.disabled_journal", username=user.username), "account")
                theme.mark_dirty()
                dlg.close()
                theme.notify(t("login.sf.disabled"), "positive")

            with ui.row().classes("gap-2"):
                ui.button(t("login.sf.disable"), on_click=disable).props("color=red")
                ui.button(t("common.cancel"), on_click=dlg.close).props("flat")
        else:
            secret = totp.new_secret()
            ui.label(t("login.sf.off_text")).style("color:var(--km-muted);font-size:.82rem;white-space:normal")
            ui.label(t("login.sf.secret_label")).style("font-size:.78rem;margin-top:6px")
            ui.html(f'<div class="km-pixel" style="font-size:1rem;color:var(--km-gold);user-select:all;'
                    f'padding:4px 0">{theme.esc(totp.encode_secret(secret))}</div>')
            ui.label(t("login.sf.link_label")).style("font-size:.78rem;margin-top:6px")
            ui.html(f'<div style="font-size:.7rem;word-break:break-all;user-select:all;color:var(--km-muted)">'
                    f'{theme.esc(totp.otpauth_url(secret, user.username))}</div>')
            code_field = ui.input(t("login.sf.code_label")).props("outlined dense inputmode=numeric") \
                .classes("w-full")
            warning = ui.label("").style("color:var(--km-red);font-size:.8rem;min-height:1.2em")

            def enable() -> None:
                if not totp.matches(secret, (code_field.value or "").strip()):
                    warning.set_text(t("login.sf.wrong"))
                    return
                codes = totp.new_recovery_codes()
                auth.enable_second_factor(STATE.archive, user.id, secret, codes)
                STATE.record(t("login.sf.enabled_journal", username=user.username), "account")
                theme.mark_dirty()
                dlg.close()
                with theme.dialog() as shown, ui.card().classes("km-panel").style("min-width:340px"):
                    theme.title(t("login.second_factor"), 2)
                    ui.label(t("login.sf.enabled")).style("color:var(--km-muted);font-size:.82rem;white-space:normal")
                    ui.html('<div class="km-pixel" style="font-size:.95rem;color:var(--km-gold);user-select:all;'
                            'line-height:1.7;padding:6px 0">' + "<br>".join(theme.esc(c) for c in codes) + "</div>")
                    ui.button(t("login.done"), on_click=shown.close).props("color=amber")
                shown.open()

            with ui.row().classes("gap-2"):
                ui.button(t("login.sf.enable"), on_click=enable).props("color=amber")
                ui.button(t("common.cancel"), on_click=dlg.close).props("flat")
    dlg.open()


def _clear_second_factor(row: dict) -> None:
    """The administrator clears another account's second factor: for the
    day the phone is lost with the recovery codes. Written in the journal."""
    with theme.dialog() as dlg, ui.card().classes("km-panel"):
        ui.label(t("login.sf.clear_confirm", username=row["username"])).style("white-space:normal")

        def confirm() -> None:
            me = auth.current_user(STATE.archive)
            auth.disable_second_factor(STATE.archive, row["id"], by=me.username if me else None)
            STATE.record(t("login.sf.cleared_journal", username=row["username"],
                           by=me.username if me else "?"), "account")
            theme.mark_dirty()
            dlg.close()
            theme.notify(t("login.sf.cleared", username=row["username"]), "positive")
            users_panel.refresh()

        with ui.row().classes("gap-2"):
            ui.button(t("login.sf.clear"), on_click=confirm).props("color=red")
            ui.button(t("common.cancel"), on_click=dlg.close).props("flat")
    dlg.open()


def change_password_dialog(user: auth.User, mandatory: bool = False) -> None:
    # Whoever wears someone else's clothes does not change their password: it
    # is chosen by the real owner of the account. The administrator generates
    # a new one from the Accounts panel, and it is recorded.
    if auth.is_impersonating():
        theme.notify(t("login.while_somebody_else_s"), "negative")
        return
    with theme.dialog() as dlg, ui.card().classes("km-panel").style("min-width:340px"):
        theme.title(t("login.change_password"), 2)
        if mandatory:
            ui.label(t("login.this_password_generated_startup")) \
                .style("color:var(--km-gold);font-size:.82rem")
        current_one = ui.input(t("login.current_password"), password=True, password_toggle_button=True) \
            .props("outlined dense").classes("w-full")
        before = ui.input(t("login.new_password"), password=True, password_toggle_button=True) \
            .props("outlined dense").classes("w-full")
        second_one = ui.input(t("login.repeat"), password=True) \
            .props("outlined dense").classes("w-full")
        warning = ui.label("").style("color:var(--km-red);font-size:.8rem;min-height:1.2em")

        async def save() -> None:
            if before.value != second_one.value:
                warning.set_text(t("login.two_passwords_do_not"))
                return
            # The current password is always asked, even at the first login:
            # whoever finds an open session must not be able to make it theirs.
            verified = await run.io_bound(auth.verify, STATE.archive,
                                            user.username, current_one.value or "")
            if verified is None:
                warning.set_text(t("login.current_password_not_right"))
                return
            try:
                auth.change_password(STATE.archive, user.id, before.value or "", from_=user)
            except ValueError as error:
                warning.set_text(str(error))
                return
            STATE.record(t("login.changed_their_password", username=user.username), "account")
            theme.mark_dirty()
            dlg.close()
            theme.notify(t("login.password_updated"))

        with ui.row().classes("justify-end w-full"):
            if not mandatory:
                ui.button(t("common.cancel"), on_click=dlg.close).props("flat")
            ui.button(t("common.save"), on_click=save).props("color=amber")
    dlg.open()


# ---------------------------------------------------------------------------
def users_dialog(user: auth.User) -> None:
    """Accounts are managed from here, next to one's own name.

    They used to be inside the Manual, which is the reference section: nobody
    would go looking for them there.
    """
    if not user.can(permissions.MANAGE_USERS):
        theme.notify(t("login.you_do_not_have"), "negative")
        return
    with theme.dialog() as dlg, ui.card().classes("km-panel") \
            .style("min-width:min(760px, 94vw);max-width:94vw"):
        users_panel(user)
        with ui.row().classes("justify-end w-full"):
            ui.button(t("common.close"), on_click=dlg.close).props("flat")
    dlg.open()


@ui.refreshable
def users_panel(user: auth.User) -> None:
    """Account management. Administrator only."""
    if not user.can(permissions.MANAGE_USERS):
        return

    with ui.card().classes("km-panel w-full"):
        theme.title(t("login.accounts"), 2)
        ui.label(t("login.every_player_has_their")) \
            .style("color:var(--km-muted);font-size:.8rem")

        for row in STATE.archive.list_users():
            with ui.row().classes("items-center gap-2 w-full no-wrap") \
                    .style("border-top:1px solid var(--km-line);padding-top:6px"):
                ui.html(f'<b class="km-title" style="min-width:130px">'
                        f'{theme.esc(row["username"])}</b>')
                ui.select({r: permissions.role_name(r) for r in permissions.HIERARCHY},
                          value=row["role"],
                          on_change=lambda e, i=row["id"]: _change_role(i, e.value)) \
                    .props("outlined dense options-dense").classes("w-40") \
                    .tooltip(permissions.role_description(row["role"]))
                ui.checkbox(t("login.active"), value=bool(row["active"]),
                            on_change=lambda e, i=row["id"]: _change_active(i, e.value))
                ui.label(t("login.last_login", v=row["last_login"] or t("login.never"))) \
                    .style("color:var(--km-muted);font-size:.72rem;flex:1")
                if row["id"] != user.id and row["active"]:
                    ui.button(icon="login",
                              on_click=lambda _, r=row: _enter_as(r)) \
                        .props("flat dense round size=sm") \
                        .tooltip(t("login.see_app_without_knowing", username=row['username']))
                ui.button(icon="password",
                          on_click=lambda _, r=row: _regenerate_password(r)) \
                    .props("flat dense round size=sm").tooltip(t("login.generate_new_password"))
                if row["totp_secret"]:
                    ui.button(icon="no_encryption",
                              on_click=lambda _, r=row: _clear_second_factor(r)) \
                        .props("flat dense round size=sm") \
                        .tooltip(t("login.clear_second_factor", username=row["username"]))
                if row["id"] != user.id:
                    ui.button(icon="delete",
                              on_click=lambda _, r=row: _confirm_deletion(r)) \
                        .props("flat dense round size=sm color=red").tooltip(t("login.delete_account"))

        theme.sep()
        with ui.row().classes("items-center gap-2 w-full no-wrap"):
            new_name = ui.input(t("login.new_user")).props("outlined dense").classes("w-44")
            new_role = ui.select({r: permissions.role_name(r) for r in permissions.HIERARCHY},
                                    value=permissions.PLAYER) \
                .props("outlined dense options-dense").classes("w-40")

            @theme.requires(permissions.MANAGE_USERS)
            def create() -> None:
                name = (new_name.value or "").strip()
                password = auth.random_password()
                try:
                    auth.create_user(STATE.archive, name, password,
                                     role=new_role.value, must_change_pw=True)
                except ValueError as error:
                    theme.notify(str(error), "negative")
                    return
                new_name.set_value("")
                users_panel.refresh()
                _show_password(name, password)

            ui.button(t("common.create"), on_click=create).props("dense color=amber")

        theme.sep()
        with ui.row().classes("items-center gap-2 w-full no-wrap"):
            ui.label(t("login.pair_intro")).style("color:var(--km-muted);font-size:.8rem;flex:1")
            ui.button(t("login.pair_launcher"), icon="link",
                      on_click=lambda: _pair_launcher(user)).props("dense color=amber")


@theme.requires(permissions.MANAGE_USERS)
def _pair_launcher(user: auth.User) -> None:
    """A pairing code for a launcher joining the table: made here, by the
    administrator, and told to the person; their launcher sends it to this
    server with no password. Ten minutes, one use."""
    code = pairing.new_code(user.username)
    STATE.record(t("login.pair_made", username=user.username), "account")
    theme.mark_dirty()
    with theme.dialog() as dlg, ui.card().classes("km-panel").style("min-width:340px"):
        theme.title(t("login.pair_title"), 2)
        ui.label(t("login.pair_text")).style("color:var(--km-muted);font-size:.82rem;white-space:normal")
        ui.html(f'<div class="km-pixel" style="font-size:1.3rem;color:var(--km-gold);'
                f'user-select:all;padding:8px 0">{theme.esc(code)}</div>')
        ui.label(t("login.pair_expires")).style("color:var(--km-muted);font-size:.78rem")
        ui.button(t("login.done"), on_click=dlg.close).props("color=amber")
    dlg.open()


def _enter_as(row: dict) -> None:
    """Wears another account's clothes and reloads the page.

    The reload is needed: tabs, permissions and filters are decided while the
    page is drawn, and redrawing a piece of it would leave around things seen
    with the previous eyes.
    """
    worn = auth.wear(STATE.archive, row["id"])
    if worn is None:
        theme.notify(t("login.this_account_cannot_entered"), "negative")
        return
    real = auth.impersonator(STATE.archive, auth.real_id())     # an event: the session is right
    who = real.username if real else "?"
    STATE.record(t("login.looking_app", who=who, username=worn.username), "info")
    theme.mark_dirty()
    ui.navigate.reload()


def _back_to_self() -> None:
    has_returned = auth.back_to_self(STATE.archive)
    if has_returned is None:
        ui.navigate.to("/login")
        return
    ui.navigate.reload()


def _last_admin(user_id: str) -> bool:
    """True if stripping this account of its powers would leave the kingdom with
    no active administrator: from there nobody could get back in."""
    row = STATE.archive.user_by_id(user_id)
    if row is None or row["role"] != permissions.ADMIN or not row["active"]:
        return False
    return STATE.archive.count_active_admins(excluded_one=user_id) == 0


@theme.requires(permissions.MANAGE_USERS)
def _change_role(user_id: str, role: str) -> None:
    who = theme.user()
    if who is not None and who.id == user_id:
        theme.notify(t("login.your_own_role_cannot"), "negative")
    elif role != permissions.ADMIN and _last_admin(user_id):
        theme.notify(t("login.this_last_active_administrator"), "negative")
    elif role in permissions.HIERARCHY:
        STATE.archive.update_user(user_id, role=role)
    users_panel.refresh()


@theme.requires(permissions.MANAGE_USERS)
def _change_active(user_id: str, active: bool) -> None:
    if not active and _last_admin(user_id):
        theme.notify(t("login.this_last_active_administrator"), "negative")
    else:
        STATE.archive.update_user(user_id, active=1 if active else 0)
    users_panel.refresh()


@theme.requires(permissions.MANAGE_USERS)
def _regenerate_password(row: dict) -> None:
    password = auth.random_password()
    auth.change_password(STATE.archive, row["id"], password, from_=theme.user())
    STATE.archive.update_user(row["id"], must_change_pw=1)
    who = theme.user()
    STATE.record(t("login.generated_new_password", v=who.username if who else '?', username=row['username']), "account")
    theme.mark_dirty()
    _show_password(row["username"], password)


def _show_password(username: str, password: str) -> None:
    """The password in the clear, once: it cannot be recovered later."""
    with theme.dialog() as dlg, ui.card().classes("km-panel").style("min-width:340px"):
        theme.title(t("login.initial_password"), 2)
        ui.label(t("login.hand_cannot_read_again", username=username)) \
            .style("color:var(--km-muted);font-size:.82rem")
        ui.html(f'<div class="km-pixel" style="font-size:1.3rem;color:var(--km-gold);'
                f'user-select:all;padding:8px 0">{theme.esc(password)}</div>')
        ui.button(t("login.done"), on_click=dlg.close).props("color=amber")
    dlg.open()


def _confirm_deletion(row: dict) -> None:
    with theme.dialog() as dlg, ui.card().classes("km-panel"):
        theme.title(t("login.delete_account_2"), 2)
        ui.label(t("login.will_no_longer_able", username=row["username"]))

        @theme.requires(permissions.MANAGE_USERS)
        def go() -> None:
            if _last_admin(row["id"]):
                theme.notify(t("login.this_last_active_administrator"),
                               "negative")
                return
            STATE.archive.delete_user(row["id"])
            dlg.close()
            users_panel.refresh()

        with ui.row():
            ui.button(t("common.delete"), on_click=go).props("color=red")
            ui.button(t("common.cancel"), on_click=dlg.close).props("flat")
    dlg.open()


def _abuse_noted(username: str, how_many: int) -> None:
    """A name's brake tripped: one line in the journal, where the GM and
    the administrator read, because the login page says nothing to them."""
    STATE.record(t("login.failed_attempts", username=username, count=how_many), "account")
    theme.mark_dirty()


auth.on_abuse = _abuse_noted
app.add_middleware(AccessMiddleware)
