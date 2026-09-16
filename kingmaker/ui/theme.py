"""Visual theme and shared widgets."""
from __future__ import annotations

import base64
import functools
import html
import logging
import time
from contextlib import contextmanager
from pathlib import Path

from nicegui import app, context, ui
from nicegui.client import Client
from nicegui.slot import Slot

from kingmaker.access import auth, permissions
from kingmaker.locale import i18n, units
from kingmaker import rules
from kingmaker.state import STATE
from kingmaker.locale.i18n import t

log = logging.getLogger(__name__)


@contextmanager
def dialog(props: str = ""):
    """Creates a dialog attached to the root of the page.

    Dialogs created inside a `@ui.refreshable` panel would be destroyed by the
    next refresh of that panel, so we anchor them to the client's content.
    """
    with context.client.content:
        dlg = ui.dialog()
    if props:
        dlg.props(props)
    with dlg:
        yield dlg

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@500;700&family=IBM+Plex+Sans:wght@400;500;600&family=Press+Start+2P&display=swap');

:root {
  --km-bg:      #14110d;
  --km-panel:   #1f1a14;
  --km-panel-2: #2a231a;
  --km-line:    #4a3d2c;
  --km-gold:    #d7b263;
  --km-gold-dim:#8d7440;
  --km-green:   #6f9a4e;
  --km-red:     #b84a3a;
  --km-blue:    #5b8fb0;
  --km-text:    #e9e0cf;
  --km-muted:   #a2957c;
}

body, .nicegui-content { background: var(--km-bg); color: var(--km-text);
  font-family: 'IBM Plex Sans', system-ui, sans-serif; }

.km-title { font-family: 'Cinzel', serif; letter-spacing: .04em; color: var(--km-gold); }
.km-pixel { font-family: 'Press Start 2P', monospace; }

.km-panel { background: linear-gradient(180deg, var(--km-panel) 0%, #1a150f 100%);
  border: 1px solid var(--km-line); border-radius: 10px; }

.km-chip { background: var(--km-panel-2); border: 1px solid var(--km-line);
  border-radius: 8px; padding: 4px 10px;
  /* inline-block: as a <span> the box broke in half when it wrapped */
  display: inline-block; max-width: 100%; }

.km-stat { background: var(--km-panel-2); border: 1px solid var(--km-line);
  border-radius: 10px; padding: 6px 12px; min-width: 76px; text-align: center; }
.km-stat .v { font-family: 'Cinzel', serif; font-size: 1.35rem; color: var(--km-gold); line-height: 1.1; }
.km-stat .l { font-size: .62rem; text-transform: uppercase; letter-spacing: .09em; color: var(--km-muted); }

.km-skill { display: grid; grid-template-columns: 1fr auto auto auto; gap: 8px; align-items: center;
  background: var(--km-panel-2); border: 1px solid var(--km-line); border-radius: 8px; padding: 6px 10px; }
.km-skill:hover { border-color: var(--km-gold-dim); }

.km-mod { font-family: 'Cinzel', serif; font-size: 1.05rem; color: var(--km-gold); min-width: 34px; text-align: right; }

.km-sc  { color: #8fd46a; } .km-s { color: #cfe08a; }
.km-f   { color: #e3a86a; } .km-fc { color: #e0705d; }

.km-lot { aspect-ratio: 1; border: 1px solid var(--km-line); border-radius: 4px;
  background: #241d15; display: flex; align-items: center; justify-content: center;
  font-size: .58rem; text-align: center; cursor: pointer; padding: 2px; overflow: hidden;
  line-height: 1.1; transition: .12s; }
.km-lot:hover { border-color: var(--km-gold); background: #302617; }
.km-lot.full { background: linear-gradient(160deg,#3b3220,#2a2317); border-color: var(--km-gold-dim); color: var(--km-gold); }
.km-lot.rubble { background: repeating-linear-gradient(45deg,#332a20,#332a20 4px,#241d15 4px,#241d15 8px); }
.km-block { display: grid; grid-template-columns: 1fr 1fr; gap: 3px; padding: 5px;
  background: #191410; border: 1px solid var(--km-line); border-radius: 6px; }
.km-block.locked { opacity: .35; }

.q-tab { color: var(--km-muted); }
.q-tab--active { color: var(--km-gold); }
.q-field__native, .q-field__input { color: var(--km-text) !important; }
.q-item__label { color: var(--km-text); }
.km-scroll { max-height: 70vh; overflow-y: auto; }
/* The hand shows only while dragging: at rest the arrow is needed, or nobody
   thinks a hex can be clicked to edit it any more. */
.km-drag.km-running, .km-drag.km-running * { cursor: grabbing !important; }

/* A crossed-out icon, to say «this is off now». The stroke is drawn by the
   stylesheet instead of looking for a second icon in the set: so it works for
   any symbol and stays the same colour. */
.km-strike { position: relative; }
.km-strike::after { content: ''; position: absolute; left: -1px; right: -1px;
  top: calc(50% - 1px); height: 2px; border-radius: 1px; background: currentColor;
  transform: rotate(-45deg); box-shadow: 0 0 0 1px rgba(0,0,0,.55); }
"""

# Panning the map by holding the right (or middle) button, as on Roll20: with
# the wheel or the scrollbars, without a touchpad, it is a pain. All browser
# side: dragging must not go through the server at every pixel.
#
# Here also lives the memory of **where you were looking**. Switching tab,
# Quasar does not throw the map box away, it hides it: a hidden box is zero
# high and wide, and a zero-wide box has nothing to scroll, so the browser
# resets the scroll. Coming back to the Map you found yourself in the top-left
# corner, and whoever plays in the right half of the Stolen Lands had to make
# the trip again every time.


# The party's crest: the favicon (a file NiceGUI serves at /favicon.ico) and,
# small and inlined, the badge next to the kingdom's name — the same picture
# as the launcher's icon, so the app has one face everywhere.
CREST_FILE = Path(__file__).parent / "static" / "crest.png"
_CREST_SMALL = base64.b64encode((Path(__file__).parent / "static" / "crest-40.png").read_bytes()).decode("ascii")


def crest(size: int = 28, margin: str = "0 6px 0 0") -> str:
    """The crest as an inline `<img>`, ready for `ui.html`."""
    return (f'<img src="data:image/png;base64,{_CREST_SMALL}" width="{size}" height="{size}" '
            f'alt="" style="vertical-align:middle;border-radius:22%;margin:{margin}">')


SCROLL_JS = (Path(__file__).parent / "static" / "map_scroll.js").read_text(encoding="utf-8")
TRAVEL_JS = (Path(__file__).parent / "static" / "travel_drag.js").read_text(encoding="utf-8")
ERASER_JS = (Path(__file__).parent / "static" / "water_eraser.js").read_text(encoding="utf-8")
CURRENT_JS = (Path(__file__).parent / "static" / "water_current.js").read_text(encoding="utf-8")


def apply_theme() -> None:
    ui.add_head_html(f"<style>{CSS}</style>")
    ui.add_body_html(f"<script>{SCROLL_JS}</script>")
    ui.add_body_html(f"<script>{TRAVEL_JS}</script>")
    ui.add_body_html(f"<script>{ERASER_JS}</script>")
    ui.add_body_html(f"<script>{CURRENT_JS}</script>")
    ui.dark_mode().enable()


# --------------------------------------------------------------------------
def esc(text) -> str:
    """Text ready to go inside a `ui.html`.

    `ui.label` escapes by itself, `ui.html` does not: everything the user can
    type (kingdom, settlement and hex names) must pass through here, or an
    `<img src=x onerror=...>` typed in a field would end up running in every
    other player's browser.
    """
    return html.escape(str(text), quote=True)


def stat_box(value, label: str, tooltip: str = "") -> None:
    with ui.element("div").classes("km-stat"):
        ui.html(f'<div class="v">{esc(value)}</div><div class="l">{esc(label)}</div>')
        if tooltip:
            ui.tooltip(tooltip)


def title(text: str, level: int = 1) -> None:
    dim = {1: "1.5rem", 2: "1.15rem", 3: "1rem"}[level]
    ui.html(f'<div class="km-title" style="font-size:{dim};margin:2px 0 6px">{esc(text)}</div>')


def sep() -> None:
    ui.separator().style("background: var(--km-line); margin: 6px 0")


GRADE_CLASSES = {
    "critical_success": "km-sc",
    "success": "km-s",
    "failure": "km-f",
    "critical_failure": "km-fc",
}


def result_block(res: rules.Result) -> None:
    """Body of the roll: d20, modifier, degree of success and breakdown."""
    sign = "+" if res.modifier >= 0 else "−"
    with ui.row().classes("items-center gap-3"):
        ui.html(f'<div class="km-pixel" style="font-size:1.6rem;color:var(--km-gold)">{res.natural}</div>')
        ui.label(t("theme.d20", sign=sign, abs=abs(res.modifier), total=res.total)).classes("text-lg")
        ui.label(t("theme.vs_dc", cd=res.cd)).style("color:var(--km-muted)")
    ui.html(f'<div class="{GRADE_CLASSES[res.grade]}" style="font-family:Cinzel;font-size:1.4rem">'
            f'{res.label} <span style="font-size:.8rem;color:var(--km-muted)">'
            f'{t("theme.margin", margin=f"{res.margin:+d}")}</span></div>')
    if res.natural in (1, 20):
        ui.label(t("theme.natural_20_result_improved") if res.natural == 20
                 else t("theme.natural_1_result_worsened")).style("color:var(--km-muted)")
    if res.detail:
        with ui.row().classes("gap-2 flex-wrap"):
            for name, val in res.detail:
                ui.html(f'<span class="km-chip" style="font-size:.72rem">{esc(name)} {val:+d}</span>')


def show_result(res: rules.Result, check_title: str, outcome_text: str = "") -> None:
    """Dialog with the outcome of a check, Roll20 style."""
    with dialog() as dlg, ui.card().classes("km-panel").style("min-width:420px;max-width:560px"):
        title(check_title, 2)
        result_block(res)
        if outcome_text:
            sep()
            ui.markdown(outcome_text).style("font-size:.9rem")
        ui.button(t("common.close"), on_click=dlg.close).props("flat color=amber")
    dlg.open()


def notify(text: str, kind: str = "positive") -> None:
    ui.notify(text, type=kind, position="top-right")


# --------------------------------------------------------------------------
# The permission is checked again inside the function that writes, not only
# on the button: an event can be emitted from the browser console too, and a
# hidden button is not a defence.
def denied_message() -> str:
    return t("theme.you_do_not_have")


def requires(action: str):
    """Decorator: the function runs only if the actor has that permission."""
    def decorator(fn):
        @functools.wraps(fn)
        def inside(*a, **k):
            if not permissions.can(user(), action):
                try:
                    notify(denied_message(), "negative")
                except Exception:          # outside a window: nothing to say
                    pass
                return None
            return fn(*a, **k)
        return inside
    return decorator


def protected(action: str, fn):
    """`requires` for the lambdas written inline in the panels."""
    return requires(action)(fn)


# --------------------------------------------------------------------------
# The kingdom is one and everyone sees it; every connected window (you and
# your friends) has instead its own panels and its own choices in the menus.
_GLOBAL = "globale"          # panels registered at import: shared by all
_REFRESH: dict[str, dict[str, object]] = {}
_WINDOWS: dict[str, dict] = {}
_refreshing = False


def _window() -> str:
    """Identifier of the window that is acting."""
    stack = Slot.get_stack()
    if stack:
        try:
            return stack[-1].parent.client.id
        except (AttributeError, RuntimeError):
            pass
    # Only once the server is up: asking for the client earlier would make
    # NiceGUI believe it is a script with the interface in the global scope.
    if app.is_started:
        try:
            return context.client.id  # inside an event handler
        except (AttributeError, RuntimeError, KeyError):
            pass
    return _GLOBAL                   # import or background activity


def window_state() -> dict:
    """Private data of a window: it does not go into the kingdom save."""
    return _WINDOWS.setdefault(_window(), {})


def set_user(user) -> None:
    """Remembers who is looking at this window.

    Call it once, while the page is drawing: there a real HTTP request exists
    and `app.storage.user` answers correctly.
    """
    data = window_state()
    data["user"] = user
    data["user_rev"] = STATE.archive.rev


def set_language(lang: str) -> None:
    """Remembers which language this window reads in.

    Like the identity, it is a property of the window and not of the session:
    during a redraw `i18n.t()` must answer in the language of the window
    being redrawn, not in that of whoever acted.
    """
    window_state()["lang"] = i18n.resolve(lang)


def language() -> str:
    """The language of the window being drawn."""
    return i18n.current()


def set_units(unit: str) -> None:
    """Remembers whether this window reads distances in metres or feet."""
    window_state()["units"] = unit if unit in units.UNITS else None


i18n.language_resolver = lambda: _WINDOWS.get(_window(), {}).get("lang")
units.units_resolver = lambda: _WINDOWS.get(_window(), {}).get("units")


def request_prefix(request_) -> str:
    """Under which path the app is published, as seen by whoever is looking.

    The On Air relay says it in two ways — the `X-Forwarded-Prefix` header and
    the `root_path` of the ASGI scope — and under On Air the two say **the same
    thing**. Adding them up, which is what used to happen, wrote the prefix
    twice: the redirect to the login page landed on
    `/name/device-0/name/device-0/login`, an address that does not exist, and
    the browser went round in circles until it gave up.

    Here only one is kept. They stay added up only when they say different
    things and neither contains the other: that is the case of a reverse proxy
    in front of an app already mounted under a path, and there they really are
    two pieces of road.
    """
    if request_ is None:
        return ""
    try:
        header = (request_.headers.get("X-Forwarded-Prefix") or "")
        root = (request_.scope.get("root_path") or "")
    except AttributeError:
        return ""
    header, root = header.rstrip("/"), root.rstrip("/")
    if not header or not root:
        return header or root
    if header == root or root.endswith(header):
        return root
    if header.endswith(root):
        return header
    return header + root


def set_prefix(request_) -> None:
    """Remembers under which path this window sees the app.

    Publishing the game with NiceGUI On Air the app is not at the root of the
    domain: the address is `https://.../<name>/device-0/`, and the relay tells
    the app in the `X-Forwarded-Prefix` header.

    NiceGUI adds that piece to the addresses of *its* elements — `ui.image`,
    `ui.interactive_image` and company do it in the browser with
    `window.path_prefix`. But inside the map SVG we write the markers by hand,
    and nobody passes there: an `/assets/...` written by us pointed outside the
    app, and the marker never arrived. From here on we add it ourselves.
    """
    if request_ is None:
        return
    window_state()["prefix"] = request_prefix(request_)


def with_prefix(path: str) -> str:
    """An absolute address of ours, valid from outside the house too.

    To be used **only** for addresses that end up in markup written by us (the
    map SVG, a `ui.html`). Those going through a NiceGUI element must not be
    touched: it already adds the prefix itself, and adding it twice is worse
    than not adding it.
    """
    if not path.startswith("/"):
        return path
    return _WINDOWS.get(_window(), {}).get("prefix", "") + path


def user():
    """Who is looking at the window being drawn right now.

    `app.storage.user` cannot be asked during a redraw: when a player edits the
    kingdom, NiceGUI re-runs the panels of *all* windows while staying in the
    context of the one who acted, and every panel would find the wrong
    identity. The slot stack instead points to the right window, and that is
    what `_window()` relies on.
    """
    cid = _window()
    data = _WINDOWS.get(cid, {})
    u = data.get("user")
    # The identity is a snapshot taken when the page was drawn: if meanwhile
    # the administrator changed the role or switched the account off, the open
    # window must know. `archive.rev` rises at every write, and the row is
    # re-read only then: one SELECT per key, not per click.
    if isinstance(u, auth.User) and data.get("user_rev") != STATE.archive.rev:
        data["user_rev"] = STATE.archive.rev
        row = STATE.archive.user_by_id(u.id)
        if row is None or not row["active"]:
            data.pop("user", None)
            _kick_out(cid)
            return None
        updated = auth._from_row(row)
        if updated != u:
            data["user"] = u = updated
    return u


def _kick_out(cid: str) -> None:
    """Sends a window whose account is no longer valid back to the login screen."""
    client = Client.instances.get(cid)
    if client is None:
        return
    try:
        with client:
            ui.navigate.to("/logout")
    except Exception:
        log.debug("cannot send window %s out", cid, exc_info=True)


def current_window() -> str:
    """Who is acting, as a window identifier."""
    return _window()


def other_windows() -> list[tuple[str, dict]]:
    """The other connected windows, with their data: who looks and from which tab.

    For whoever must send something to *them* instead of to themself — the
    arrow of a journey while it is being dragged, for instance. It prunes the
    closed ones first, so nobody talks to windows that no longer exist.
    """
    myself = _window()
    _live_windows()
    return [(cid, data) for cid, data in _WINDOWS.items()
            if cid != myself and cid != _GLOBAL]


def register_refresh(name: str, refreshable) -> None:
    _REFRESH.setdefault(_window(), {})[name] = refreshable


def _live_windows() -> list[tuple[str, dict]]:
    """Forgets the closed windows: their panels no longer exist."""
    for cid in [c for c in _REFRESH if c != _GLOBAL and c not in Client.instances]:
        _REFRESH.pop(cid, None)
        _WINDOWS.pop(cid, None)
        _DIRTY.pop(cid, None)
    return list(_REFRESH.items())


def _drop_dead_targets(ref) -> None:
    """Removes from the panel the copies whose container no longer exists.

    A `@ui.refreshable` keeps a list of targets, one for every window it was
    drawn in, and does not clean it up by itself. While redraws were rare it
    went unnoticed; with the clock asking for one per game day, every closed
    window left a dead target behind — and NiceGUI notices and warns. Here we
    remove them before redrawing.
    """
    targets = getattr(ref, "targets", None)
    if targets is None:
        return
    alive = [b for b in targets
            if getattr(b, "container", None) is not None
            and not getattr(b.container, "is_deleted", False)]
    if len(alive) != len(targets):
        targets[:] = alive


def _redraw(ref) -> None:
    try:
        _drop_dead_targets(ref)
        ref.refresh()
    except Exception:
        # The normal case is that the panel is not instantiated on this window.
        # We do not raise it, but we do not lose it either: with logging at
        # DEBUG one sees what really failed.
        log.debug("panel refresh failed: %r", ref, exc_info=True)


# Which tab every registered panel belongs to. Redrawing the map (on a large
# grid tens of KB of SVG) in the window of someone looking at the kingdom
# sheet instead is wasted work, and in play it shows.
_TABS = {"hexmap": "map", "sheet": "kingdom", "turn": "turn",
         "city": "city", "party": "party", "gm_screen": "gm"}
_DIRTY: dict[str, set[str]] = {}


def _watched_tabs() -> set:
    """The tabs someone really has in front of them, in any window."""
    return {data.get("tab") for cid, data in _WINDOWS.items()
            if cid != _GLOBAL}


def _visible(panel_name: str, tab_: str | None,
              cid: str | None = None) -> bool:
    panel_tab = _TABS.get(panel_name.split(".")[0])
    if panel_tab is None:
        return True           # header, clock: always visible
    if cid == _GLOBAL:
        # Panels registered at import belong to no window: there is a single
        # shared copy, and redrawing it updates all windows at once. The right
        # question is therefore not «this window is on it» but «someone is on
        # it». Without this distinction they were always redrawn, the filter
        # never touched them, and they are the most expensive there are:
        # rebuilding the kingdom journal — eighty rows, four elements per row —
        # costs half a second, and it was paid even with the Map in front and
        # the Turn tab closed.
        watched = _watched_tabs()
        return None in watched or panel_tab in watched
    if tab_ is None:
        return True           # window that has not chosen a tab yet
    return panel_tab == tab_


def active_tab(name) -> None:
    """The window changed tab: catches up the panels left behind."""
    name = getattr(name, "name", name)
    cid = _window()
    _WINDOWS.setdefault(cid, {})["tab"] = name
    # The backlog of the shared heap too: they were left behind precisely
    # because nobody was looking at this tab, and now someone is.
    for key in (cid, _GLOBAL):
        arrears = _DIRTY.get(key)
        if not arrears:
            continue
        panels = _REFRESH.get(key, {})
        for panel_name in sorted(arrears):
            if _visible(panel_name, name):
                arrears.discard(panel_name)
                ref = panels.get(panel_name)
                if ref is not None:
                    _redraw(ref)


def _refresh(cid: str, panels: dict, names=None) -> None:
    """Redraws the panels of the tab in the foreground; the others stay marked
    and refresh when the window comes back to them."""
    tab_ = _WINDOWS.get(cid, {}).get("tab")
    for name in (names if names is not None else list(panels)):
        ref = panels.get(name)
        if ref is None:
            continue
        if _visible(name, tab_, cid):
            _DIRTY.get(cid, set()).discard(name)
            _redraw(ref)
        else:
            _DIRTY.setdefault(cid, set()).add(name)


def refresh_ui() -> None:
    """Redraws the foreground panels of every connected window."""
    global _refreshing
    if _refreshing:
        return
    _refreshing = True
    try:
        for cid, panels in _live_windows():
            _refresh(cid, panels)
    finally:
        _refreshing = False


def refresh_locals(names) -> None:
    """Redraws at once, only in the acting window, the panels listed.

    For frequent edits (a hex status, a work site): the actor sees the result
    instantly and the others receive it shortly after with `save_light`,
    without rebuilding panels nobody is looking at.
    """
    cid = _window()
    panels = _REFRESH.get(cid)
    if panels:
        _refresh(cid, panels, names)


def refresh_panels(names, exclude: str | None = None) -> None:
    """Redraws only the panels listed, skipping the window that just acted
    (whoever is dragging a slider or typing must not be interrupted)."""
    for cid, panels in _live_windows():
        if cid == exclude:
            continue
        _refresh(cid, panels, names)


# --------------------------------------------------------------------------
# Deferred saving to disk: writing the whole kingdom as JSON at every keystroke
# or every notch of a slider used to block the server.
_to_save = False
_last_save = 0.0
_to_propagate: set[str] = set()
_author: str | None = None


def mark_dirty() -> None:
    """Something changed: it is written to disk at the next tick, and the
    revision rises — it is the key by which the map knows to redo its layers
    and the ruler its field."""
    global _to_save
    _to_save = True
    STATE.k["_rev"] = STATE.k.get("_rev", 0) + 1


def write_to_disk() -> None:
    """Saves the kingdom if there are pending changes."""
    global _to_save, _last_save
    if _to_save:
        _to_save = False
        _last_save = time.monotonic()
        STATE.save()


def _maintenance() -> None:
    """Twice a second: shows the other players the continuous edits (sliders,
    names) and writes the save at most once every two seconds."""
    global _author
    if _to_propagate:
        names = set(_to_propagate)
        _to_propagate.clear()
        author_, _author = _author, None
        refresh_panels(names, exclude=author_)
    if _to_save and time.monotonic() - _last_save >= 2.0:
        write_to_disk()


def _switch_off() -> None:
    """Last save and clean closing of the database."""
    write_to_disk()
    STATE.archive.close()


app.timer(0.5, _maintenance)
app.on_shutdown(_switch_off)


def save_light(propagate: tuple[str, ...] = ()) -> None:
    """Records the change without rebuilding the interface of whoever is making it.

    The panels listed in `propagate` are refreshed in the *other* windows
    within half a second, so everyone sees the same map.
    """
    global _author
    STATE.notify(save=False)
    mark_dirty()
    if propagate:
        _to_propagate.update(propagate)
        _author = _window()


def save_and_refresh() -> None:
    """Important change: every connected window sees it at once.

    Redraws *everything*, and it is expensive: the panels registered at import
    (the Turn tab, the Kingdom blocks, the stable) sit in a single heap without
    a window, so the «foreground tab only» filter does not touch them and they
    are rebuilt even if nobody is looking. They are the heaviest there are.
    When one knows what changed, `save_and_refresh_panels` is better.
    """
    STATE.notify(save=False)
    mark_dirty()
    refresh_ui()


def save_and_refresh_panels(names) -> None:
    """Like `save_and_refresh`, but redraws only the panels listed.

    Same thing for the data — the change is recorded and reaches the disk the
    same way — and different only in how much interface is rebuilt. Listing
    the panels is a commitment: what changes and is not in the list stays
    behind until something else redraws it.
    """
    STATE.notify(save=False)
    mark_dirty()
    refresh_panels(names)
