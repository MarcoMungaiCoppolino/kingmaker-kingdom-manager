"""Visual theme and shared widgets."""
from __future__ import annotations

import asyncio
import base64
import functools
import html
import json
import logging
import time
from contextlib import contextmanager
from pathlib import Path

from nicegui import app, background_tasks, context, helpers, ui
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

# The three typefaces are served by the app itself, from `static/fonts/`:
# nothing in a player's page is fetched from anyone but the host. They used
# to come from Google Fonts, which meant every player's browser handed its
# address to Google on every page — a request nobody at the table had
# chosen, and a breach of the GDPR for the host under European case law.
# The files are the subsetted woff2 Google serves (latin and latin-ext:
# Italian and English need nothing more), under the SIL Open Font License,
# whose texts sit next to them. The addresses are relative on purpose: every
# page of the app lives at the root of its prefix (`/`, `/login`), so
# `_km/fonts/…` resolves under the On Air prefix as well as at home, with
# no `with_prefix` needed in a stylesheet written before any window exists.
STATIC_DIR = Path(__file__).parent / "static"
FONTS_ROUTE = "/_km/fonts"
app.add_static_files(FONTS_ROUTE, str(STATIC_DIR / "fonts"))

LATIN = ("U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, "
         "U+0308, U+0329, U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, "
         "U+FEFF, U+FFFD")
LATIN_EXT = ("U+0100-02BA, U+02BD-02C5, U+02C7-02CC, U+02CE-02D7, U+02DD-02FF, U+0304, "
             "U+0308, U+0329, U+1D00-1DBF, U+1E00-1E9F, U+1EF2-1EFF, U+2020, U+20A0-20AB, "
             "U+20AD-20C0, U+2113, U+2C60-2C7F, U+A720-A7FF")


def _font_faces() -> str:
    faces = []
    for family, weights, stem in (("Cinzel", "500 700", "cinzel"),
                                  ("IBM Plex Sans", "400 600", "ibm-plex-sans"),
                                  ("Press Start 2P", "400", "press-start-2p")):
        for subset, ranges in (("latin", LATIN), ("latin-ext", LATIN_EXT)):
            faces.append(
                f"@font-face {{ font-family: '{family}'; font-style: normal; "
                f"font-weight: {weights}; font-display: swap; "
                f"src: url('_km/fonts/{stem}-{subset}.woff2') format('woff2'); "
                f"unicode-range: {ranges}; }}")
    return "\n".join(faces)


CSS = _font_faces() + """

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
/* an activity card: one element, the whole of it a button */
.km-activity:hover { border-color: var(--km-gold); }
/* the quick adjustments: one element, every control a data-km attribute */
.km-adj { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  column-gap: 16px; row-gap: 2px; padding: 8px; }
.km-adj-row { display: grid; grid-template-columns: 1fr auto; align-items: center;
  column-gap: 4px; min-width: 0; }
.km-adj-name { min-width: 0; overflow: hidden; }
.km-adj-name .n { font-size: .82rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.km-adj-name .x { font-size: .68rem; color: var(--km-muted); min-height: 1.05em;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.km-adj-ctl { display: flex; align-items: center; }
.km-adj-btn { font-size: 18px; padding: 5px; border-radius: 50%; cursor: pointer;
  color: #9e9e9e; user-select: none; }
.km-adj-btn.plus { color: #ffc107; }
.km-adj-btn:hover { background: rgba(255, 255, 255, .08); }
.km-adj-num { min-width: 38px; text-align: center; display: inline-block; color: var(--km-gold); }
.km-adj-link { cursor: pointer; text-decoration: underline dotted; }
/* the blocks of the sheet drawn as one element: native controls in the theme's clothes */
.km-select, .km-input { background: var(--km-panel-2); color: inherit; border: 1px solid var(--km-line);
  border-radius: 6px; padding: 4px 6px; font: inherit; font-size: .82rem; }
.km-select:focus, .km-input:focus { outline: none; border-color: var(--km-gold-dim); }
.km-icon-btn { font-size: 20px; padding: 4px; border-radius: 50%; cursor: pointer; color: #9e9e9e;
  user-select: none; }
.km-icon-btn.amber { color: #ffc107; }
.km-icon-btn:hover { background: rgba(255, 255, 255, .08); }
.km-icons { display: flex; align-items: center; }
/* As many columns as the panel has room for: two in a wide column, one in a
   narrow one (a smaller screen, a narrow window) — no breakpoint needed. */
.km-skills { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 6px; }
.km-check { display: inline-flex; align-items: center; gap: 2px; cursor: pointer; font-size: .82rem;
  user-select: none; }
.km-check i { font-size: 20px; color: #9e9e9e; }
.km-check.on i { color: #ffc107; }
.km-role { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding: 4px 0;
  border-bottom: 1px solid var(--km-line); }
.km-role:last-child { border-bottom: none; }
.km-feat-level { font-family: 'Cinzel', serif; font-size: .8rem; letter-spacing: .08em; color: var(--km-gold-dim);
  text-transform: uppercase; margin: 8px 0 2px; border-bottom: 1px solid var(--km-line); }
.km-feat { display: flex; align-items: flex-start; gap: 6px; padding: 3px 0; cursor: pointer; }
.km-feat:hover { background: rgba(255, 255, 255, .04); }
.km-feat i { font-size: 20px; color: #9e9e9e; flex: none; margin-top: 1px; }
.km-feat.on i { color: #ffc107; }
.km-feat .s { font-size: .8rem; color: var(--km-muted); }

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
/* the map in two layers: the ground (fills, fog, water, icons) in a box of its
   own under the image's SVG, which keeps the live things — markers, journeys,
   the ruler's arrow — and stays the one the scripts draw into */
.km-drag .km-ground-box { position: absolute; left: 0; top: 0; width: 100%; height: 100%;
  z-index: 1; pointer-events: none; }
.km-drag svg:not(.km-ground) { z-index: 2; }

/* A crossed-out icon, to say «this is off now». The stroke is drawn by the
   stylesheet instead of looking for a second icon in the set: so it works for
   any symbol and stays the same colour. */
.km-strike { position: relative; }
.km-strike::after { content: ''; position: absolute; left: -1px; right: -1px;
  top: calc(50% - 1px); height: 2px; border-radius: 1px; background: currentColor;
  transform: rotate(-45deg); box-shadow: 0 0 0 1px rgba(0,0,0,.55); }

/* A card lays its children out at their own width, not at the card's: a row
   sized by its texts came out wider than its panel in Italian (the activity
   cards of the turn). Nothing inside a panel is wider than the panel. */
.km-panel > * { max-width: 100%; }

/* Smaller screens and narrow windows. Only the stylesheet changes — no
   element more, nothing that runs on a resize, no second layout to draw and
   send: the browser lays the same page out otherwise. `.km-split` is a tab's
   row of side-by-side columns (the sheet, the turn, the city, the map): below
   900 px the columns stack at full width instead of running off the screen,
   or of squeezing one of them to a strip nobody can read. */
@media (max-width: 900px) {
  .km-split { flex-wrap: wrap !important; }
  .km-split > * { flex: 1 1 100% !important; width: 100% !important;
    min-width: 0 !important; max-width: none !important; }
}
/* A very narrow window: the dialogs fit it instead of keeping a fixed
   minimum wider than it. The text keeps its size. */
@media (max-width: 600px) {
  .q-dialog .q-card { min-width: 0 !important; max-width: calc(100vw - 24px) !important; }
}
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


# A block drawn as one element reports its clicks itself: the browser finds
# the nearest ancestor with a `data-km` attribute and sends its key — and,
# for a control with a value, the value too. The server reads the key like
# any other input from outside.
PICK = "(e) => { const t = e.target.closest('[data-km]'); if (t) emit(t.dataset.km); }"
PICK_VALUE = ("(e) => { const t = e.target.closest('[data-km]'); "
              "if (t) emit([t.dataset.km, t.value]); }")


def key_value(args) -> tuple[str, str]:
    """The `[key, value]` pair a `PICK_VALUE` event carries, as two strings;
    anything else is `("", "")`."""
    if isinstance(args, (list, tuple)) and len(args) == 2:
        return str(args[0]), str(args[1])
    return "", ""


def stat_box(value, label: str, tooltip: str = "") -> None:
    """One element: the header draws eight of them in every window at every
    change, and the box, its text and its tooltip were three."""
    title = f' title="{esc(tooltip)}"' if tooltip else ""
    ui.html(f'<div class="km-stat"{title}><div class="v">{esc(value)}</div>'
            f'<div class="l">{esc(label)}</div></div>')


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
    # What a feat did to the result after the die (Pull Together, Focused
    # Attention): said, so the degree shown is not a mystery.
    for note in getattr(res, "notes", ()):
        ui.label(note).style("font-size:.8rem;color:var(--km-gold-dim);white-space:normal")


def _text(value) -> str:
    return value() if callable(value) else (value or "")


def show_result(res: rules.Result, check_title, outcome_text="",
                where: tuple[int, int] | None = None) -> None:
    """Dialog with the outcome of a check, Roll20 style — here, and read-only
    in every other open window (`share_roll`).

    `check_title` and `outcome_text` are strings, or functions returning one:
    a function is called again in each window, so that everybody reads the
    roll in the language of their own window. `where` is the hex the roll is
    about, for the windows that may not see it."""
    _result_dialog(res, _text(check_title), _text(outcome_text))
    share_roll(res, check_title, outcome_text, where)


def _result_dialog(res: rules.Result, check_title: str, outcome_text: str,
                   roller: str = "") -> None:
    with dialog() as dlg, ui.card().classes("km-panel").style("min-width:420px;max-width:560px"):
        if roller:
            ui.label(t("theme.rolled_by", name=roller)) \
                .style("font-size:.8rem;color:var(--km-muted)")
        title(check_title, 2)
        result_block(res)
        if outcome_text:
            sep()
            ui.markdown(outcome_text).style("font-size:.9rem")
        ui.button(t("common.close"), on_click=dlg.close).props("flat color=amber")
    dlg.open()


def can_reroll(res: rules.Result, rerolled: bool = False) -> bool:
    """Whether the roller may spend 1 Fame/Infamy point to reroll this check:
    a point in hand, a check not rerolled already (the reroll is a fortune
    effect: one per check), and a result worth rerolling."""
    return (not rerolled and STATE.k["fame_points"] > 0
            and res.grade != "critical_success")


def reroll_label() -> str:
    return t("theme.fame_reroll", fame=STATE.fame_name, n=STATE.k["fame_points"])


def record_reroll(check_title, res: rules.Result) -> None:
    """The point spent, in the journal: which check, and what was given up."""
    STATE.record(t("theme.fame_reroll_journal", fame=STATE.fame_name,
                   title=_text(check_title), grade=res.label, total=res.total), "check")


def show_check(res: rules.Result, check_title, outcome=None, *, apply=None,
               reroll=None, where: tuple[int, int] | None = None) -> None:
    """A Kingdom skill check on screen, with the reroll the rules allow for
    1 Fame/Infamy point.

    `outcome(res)` gives the outcome text of a result; it runs again in each
    window, for that window's language. `apply(res)` does to the kingdom what
    the result does, once, with the result that is kept. `reroll()` rolls
    the check again and returns the new result.

    While the reroll is possible (`can_reroll`) the result waits, on screen,
    until whoever rolled keeps it or spends the point; the second result is
    the one that stands, rerolled or not. Otherwise it applies at once."""
    outcome = outcome or (lambda _res: "")
    if reroll is None or not can_reroll(res):
        if apply:
            apply(res)
        show_result(res, check_title, lambda: outcome(res), where)
        return
    # The others see the first roll now, and the second when it comes.
    share_roll(res, check_title, lambda: outcome(res), where)
    save_and_refresh_panels(stat_panels("rp", "fame_points", extra=("turn.journal", "turn.uses", "sheet.abilita")))
    with dialog("persistent") as dlg, ui.card().classes("km-panel").style("min-width:420px;max-width:560px"):
        title(_text(check_title), 2)
        result_block(res)
        text = outcome(res)
        if text:
            sep()
            ui.markdown(text).style("font-size:.9rem")
        sep()
        ui.label(t("theme.fame_reroll_note", fame=STATE.fame_name, n=STATE.k["fame_points"])) \
            .style("font-size:.8rem;color:var(--km-muted);white-space:normal")

        # Answered once: by a button, or by the window going away (below).
        answered = {"done": False}

        def first() -> bool:
            if answered["done"]:
                return False
            answered["done"] = True
            return True

        @requires(permissions.EDIT_KINGDOM)
        def keep() -> None:
            dlg.close()
            if first() and apply:
                grade = res.grade
                apply(res)
                # What applying it rolled or changed (the d6 of founding a
                # settlement, a founding not paid for) was not on the
                # screen just closed: the result again, with it.
                if res.grade != grade or outcome(res) != text:
                    show_result(res, check_title, lambda: outcome(res), where)

        @requires(permissions.EDIT_KINGDOM)
        def again() -> None:
            dlg.close()
            if not first():
                return
            if not STATE.spend_fame():
                # Spent meanwhile, from another window: the first result stands.
                notify(t("theme.fame_none_left", fame=STATE.fame_name), "warning")
                if apply:
                    apply(res)
                return
            record_reroll(check_title, res)
            new = reroll()
            if apply:
                apply(new)
            save_and_refresh_panels(stat_panels("fame_points", extra=("turn.journal",)))
            show_result(new, lambda: t("theme.rerolled", title=_text(check_title)),
                        lambda: outcome(new), where)

        with ui.row().classes("gap-2 flex-wrap"):
            ui.button(t("theme.keep_result"), on_click=keep).props("color=amber")
            ui.button(reroll_label(), on_click=again).props("outline color=amber")

    def gone() -> None:
        """The window closed with the result still waiting: its cost is
        paid and the activity counted, so the first result stands rather
        than none. The window's own panels may fail to redraw: the kingdom
        has changed by then, and is saved. While this runs the window is
        marked closing, so no offer is shown where nobody would see it."""
        cid = context.client.id
        _CLOSING.add(cid)
        try:
            if first() and apply:
                try:
                    apply(res)
                except Exception:
                    log.warning("a kept result could not redraw its closed window", exc_info=True)
                    mark_dirty()
        finally:
            _CLOSING.discard(cid)

    context.client.on_delete(gone)
    dlg.open()


# Windows whose delete handlers are running (`show_check`'s `gone`): no
# dialog there, and the offers stay queued for the next change from a live one.
_CLOSING: set[str] = set()


def _offer_feats() -> None:
    """The choices a kingdom feat gives right after something happened:
    Crush Dissent when Unrest rises, Liquidate Resources when an outcome
    leaves the kingdom without the RP to pay. Asked, like the Fame ones, in
    the window of whoever caused it (`State.take_feat_offers`)."""
    if not STATE.feat_offers:
        return
    try:
        if context.client.id in _CLOSING:
            return
    except RuntimeError:
        return
    offers = STATE.take_feat_offers()
    if not offers:
        return
    with dialog() as dlg, ui.card().classes("km-panel").style("min-width:380px;max-width:560px"):
        for offer in offers:
            name = rules.BY_ID["feat"][offer["kind"]]["name"]
            title(name, 2)
            if offer["kind"] == "crush_dissent":
                ui.label(t("theme.crush_dissent_offer", n=offer["unrest"], dc=STATE.control_dc)) \
                    .style("font-size:.88rem;white-space:normal")
                ui.button(t("theme.crush_dissent_roll"),
                          on_click=lambda o=offer: _crush(o, dlg)).props("color=amber")
            else:
                ui.label(t("theme.liquidate_offer")).style("font-size:.88rem;white-space:normal")
                ui.button(t("theme.liquidate_button"), on_click=lambda: _liquidate(dlg)).props("color=amber")
            sep()
        ui.button(t("theme.feat_offer_decline"), on_click=dlg.close).props("flat")
    dlg.open()


def _crush(offer: dict, dlg) -> None:
    """Crush Dissent: a basic Warfare check. Success cancels the Unrest just
    gained, a critical failure doubles it. (The permission is checked here:
    `requires` is defined further down the module.)"""
    dlg.close()
    if not permissions.can(user(), permissions.EDIT_KINGDOM) or STATE.feat_used("crush_dissent"):
        return
    STATE.use_feat("crush_dissent")
    n = offer["unrest"]
    res = STATE.kingdom_check("warfare", STATE.control_dc)
    name = rules.BY_ID["feat"]["crush_dissent"]["name"]
    if res.grade in ("success", "critical_success"):
        STATE.modify_unrest(-n, name)
    elif res.grade == "critical_failure":
        STATE.modify_unrest(n, name)
    STATE.record(t("sheet.vs_dc", label=name, label2=res.label, total=res.total, cd=res.cd), "check")
    save_and_refresh()
    key = {"success": "theme.crush_dissent_won", "critical_success": "theme.crush_dissent_won",
           "critical_failure": "theme.crush_dissent_doubled"}.get(res.grade, "theme.crush_dissent_lost")
    show_result(res, lambda: rules.BY_ID["feat"]["crush_dissent"]["name"], lambda: t(key, n=n))


def _liquidate(dlg) -> None:
    dlg.close()
    if permissions.can(user(), permissions.EDIT_KINGDOM) and STATE.liquidate():
        save_and_refresh()
        notify(t("state.liquidated"))


def _offer_fame() -> None:
    """Anarchy, or a Ruin penalty, that Fame/Infamy can still stave off
    (`State.take_fame_offers`): asked in the window of whoever caused it.
    From a background timer there is no window to ask in: the offer waits
    for the next change made from one, if it still stands then."""
    if not STATE.fame_offers:
        return
    try:
        if context.client.id in _CLOSING:
            return
    except RuntimeError:
        return
    offers = STATE.take_fame_offers()
    if not offers:
        return
    k = STATE.k
    fame, n = STATE.fame_name, k["fame_points"]
    with dialog() as dlg, ui.card().classes("km-panel").style("min-width:380px;max-width:560px"):
        title(t("theme.fame_stave_title", fame=fame), 2)
        ui.label(t("theme.fame_stave_rule", fame=fame, n=n)) \
            .style("font-size:.82rem;color:var(--km-muted);white-space:normal")

        @requires(permissions.EDIT_KINGDOM)
        def stave(offer: dict) -> None:
            dlg.close()
            if STATE.stave_off(offer):
                save_and_refresh()
                notify(t("theme.fame_staved", fame=fame))
            else:
                notify(t("theme.fame_stave_gone"), "warning")

        for offer in offers:
            sep()
            if offer["kind"] == "unrest":
                text = t("theme.fame_stave_anarchy", unrest=k["unrest"],
                         limit=STATE.anarchy_threshold - 1)
            else:
                r = k["ruins"][offer["ruin"]]
                text = t("theme.fame_stave_ruin", name=rules.BY_ID["ruin"][offer["ruin"]]["name"],
                         penalty=r["penalty"], before=offer["penalty"], points=r["threshold"])
            ui.label(text).style("font-size:.88rem;white-space:normal")
            ui.button(t("theme.fame_stave_button", fame=fame, n=n),
                      on_click=lambda o=offer: stave(o)).props("color=amber")
        sep()
        ui.button(t("theme.fame_stave_decline"), on_click=dlg.close).props("flat")
    dlg.open()


def share_roll(res: rules.Result, check_title, outcome_text="",
               where: tuple[int, int] | None = None) -> None:
    """The roll, read-only, in every other open window: the GM sees what the
    players roll, and the players see each other's — the screen of whoever
    rolled, with only Close, and their account's name above it."""
    _broadcast(lambda roller: _result_dialog(res, _text(check_title), _text(outcome_text),
                                             roller=roller), where)


def show_dice(check_title, rolls: list[int], faces: int, outcome_text="",
              dc: int | None = None, verdict=None,
              where: tuple[int, int] | None = None) -> None:
    """Plain dice — the Resource Dice, the d20 of a random event, the 1d4 of
    Unrest — on screen here and, read-only, in every other open window.

    `dc` adds «vs DC» and Success or Failure on the total, for a flat check;
    `verdict` replaces that line with a text of its own (the event check says
    whether an event happens, not «Success»). Texts may be functions, as in
    `show_result`, so each window reads them in its own language."""
    _dice_dialog(_text(check_title), rolls, faces, _text(outcome_text), dc, _text(verdict))
    _broadcast(lambda roller: _dice_dialog(_text(check_title), rolls, faces, _text(outcome_text),
                                           dc, _text(verdict), roller=roller), where)


def _dice_dialog(check_title: str, rolls: list[int], faces: int, outcome_text: str,
                 dc: int | None, verdict: str, roller: str = "") -> None:
    total = sum(rolls)
    with dialog() as dlg, ui.card().classes("km-panel").style("min-width:360px;max-width:560px"):
        if roller:
            ui.label(t("theme.rolled_by", name=roller)) \
                .style("font-size:.8rem;color:var(--km-muted)")
        title(check_title, 2)
        with ui.row().classes("items-center gap-3"):
            ui.html(f'<div class="km-pixel" style="font-size:1.6rem;color:var(--km-gold)">{total}</div>')
            ui.label(t("theme.dice_rolled", dice=f"{len(rolls)}d{faces}",
                       rolls=" + ".join(map(str, rolls)))).classes("text-lg")
            if dc is not None:
                ui.label(t("theme.vs_dc", cd=dc)).style("color:var(--km-muted)")
        if verdict:
            ui.html(verdict)
        elif dc is not None:
            grade = "success" if total >= dc else "failure"
            ui.html(f'<div class="{GRADE_CLASSES[grade]}" style="font-family:Cinzel;font-size:1.2rem">'
                    f'{rules.grade_label(grade)}</div>')
        if outcome_text:
            sep()
            ui.markdown(outcome_text).style("font-size:.9rem")
        ui.button(t("common.close"), on_click=dlg.close).props("flat color=amber")
    dlg.open()


def _broadcast(draw, where: tuple[int, int] | None = None) -> None:
    """`draw(roller)` in every other open window, inside it — so that `t()`
    and the rules tables answer in that window's language.

    A roll about a hex (`where`) skips the windows whose account cannot see
    that hex: the GM working under the fog does not tell the players where.
    A window that fails to draw it does not stop the others, nor the roll."""
    from kingmaker.access.view import MapView
    roller = getattr(user(), "username", "") or "?"
    for cid, data in other_windows():
        viewer = data.get("user")
        client = Client.instances.get(cid)
        if client is None or not isinstance(viewer, auth.User):
            continue          # a closed window, or one still on the login page
        if where is not None and not MapView(viewer, STATE).can_see(*where):
            continue
        try:
            with client:
                draw(roller)
        except Exception:
            log.warning("roll not shown in window %s", cid, exc_info=True)


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


def register_refresh(name: str, refreshable, depends=None) -> None:
    """A panel on the bus, under a name that says which tab it belongs to.

    `depends`, when given, is a function returning what the panel reads —
    the figures, the lists, nothing else — as something `json` can write.
    The bus keeps, for every copy, the fingerprint of the last rebuild, and
    a copy whose fingerprint has not moved is not rebuilt. The language and
    the account of the window are always part of it. A dependency left out
    is a stale panel: `tests/test_windows.py` compares every copy in front
    with a fresh render after random changes, so it does not stay left out.
    """
    _REFRESH.setdefault(_window(), {})[name] = refreshable
    _route_through_bus(refreshable)
    if depends is not None:
        _DEPENDS[id(refreshable)] = depends


_DEPENDS: dict[int, object] = {}     # id(ref) → function of the panel's inputs


def _route_through_bus(ref) -> None:
    """A registered panel's own `refresh()` takes the bus too.

    The panels call `.refresh()` on each other all over the tabs — a level
    change redraws the skills block, a role change the roles — and every such
    call rebuilt the panel in *all* the windows at once, whatever tab they
    were on, and again when the bus itself got to it. From here on the call
    is an entry in the queue like any other: the windows on the tab are
    rebuilt once, the others owe a redraw. A call with arguments keeps
    NiceGUI's own behaviour, and so does anything that is not a refreshable
    (the map's `_Refresher`).
    """
    if not hasattr(ref, "targets") or getattr(ref, "_km_bus", False):
        return
    original = ref.refresh

    def refresh(*args, **kwargs):
        if args or kwargs:
            return original(*args, **kwargs)
        for cid, name in _registrations(ref):
            _refresh(cid, {name: ref}, [name])
        return None
    ref.refresh = refresh
    ref._km_bus = True


def _registrations(ref) -> list[tuple[str, str]]:
    """Under which windows and names a panel is registered."""
    return [(cid, name) for cid, panels in _REFRESH.items()
            for name, candidate in panels.items() if candidate is ref]


def _live_windows() -> list[tuple[str, dict]]:
    """Forgets the closed windows: their panels no longer exist."""
    for cid in [c for c in _REFRESH if c != _GLOBAL and c not in Client.instances]:
        _REFRESH.pop(cid, None)
        _WINDOWS.pop(cid, None)
        _DIRTY.pop(cid, None)
    return list(_REFRESH.items())


# Which tab every registered panel belongs to. Redrawing the map (on a large
# grid tens of KB of SVG) in the window of someone looking at the kingdom
# sheet instead is wasted work, and in play it shows.
_TABS = {"hexmap": "map", "sheet": "kingdom", "turn": "turn",
         "city": "city", "party": "party", "gm_screen": "gm", "transport": "transport"}
_DIRTY: dict[str, set[str]] = {}


def _tab_of(panel_name: str) -> str | None:
    """The tab a panel belongs to; None for the header and the clock, which
    are in front whatever the tab."""
    return _TABS.get(panel_name.split(".")[0])


def _visible(panel_name: str, tab_: str | None) -> bool:
    panel_tab = _tab_of(panel_name)
    if panel_tab is None or tab_ is None:
        return True           # header, clock; or a window that has not chosen a tab yet
    return panel_tab == tab_


def _tab_of_target(target) -> str | None:
    """The tab a copy of a panel sits in: the name of the `ui.tab_panel`
    above it, or None when there is none above (the header, a dialog).

    A shared panel is not always drawn in its own tab — the quick adjustments
    sit in the City tab too, and in the outcome dialog — so the copy, not the
    panel's name, says whether somebody is looking at it.
    """
    element = getattr(target, "container", None)
    seen = 0
    while element is not None and seen < 10_000:
        if getattr(element, "tag", None) == "q-tab-panel":
            return getattr(element, "_props", {}).get("name")
        slot = getattr(element, "parent_slot", None)
        element = getattr(slot, "parent", None) if slot is not None else None
        seen += 1
    return None


def target_in_front(target, window_tab: str | None) -> bool:
    """Whether this copy is on the tab the window shows."""
    tab = _tab_of_target(target)
    return tab is None or window_tab is None or tab == window_tab


def _windows_on(ref) -> tuple[set[str], set[str]]:
    """Of the windows a shared panel is drawn in, those with a copy in front:
    `(watching, reached)`."""
    reached: set[str] = set()
    watching: set[str] = set()
    for target in _targets(ref) or []:
        cid = _window_of(target)
        if cid is None:
            continue
        reached.add(cid)
        if target_in_front(target, _WINDOWS.get(cid, {}).get("tab")):
            watching.add(cid)
    return watching, reached


# ------------------------------------------------------------- the targets
# A `@ui.refreshable` keeps a target for every window it was drawn in: the
# container element, the arguments, the instance. NiceGUI's `refresh()`
# rebuilds them all; here they are rebuilt one by one, so a shared panel is
# redone only in the windows that have it in front.
def _targets(ref) -> list | None:
    """The live targets of a refreshable, or None for something that only
    has a `refresh()` of its own (the map's `_Refresher`, a test stub)."""
    targets = getattr(ref, "targets", None)
    if targets is None:
        return None
    prune = getattr(ref, "prune", None)
    if callable(prune):
        prune()                       # replaces the list: read it again
        targets = getattr(ref, "targets", None) or []
    else:
        targets[:] = [b for b in targets
                      if getattr(b, "container", None) is not None
                      and not getattr(b.container, "is_deleted", False)]
    return list(targets)


def _window_of(target) -> str | None:
    try:
        return target.container.client.id
    except AttributeError:
        return None


def _drawn_inside(element, containers: set[int]) -> bool:
    """Whether the element sits under one of the containers listed."""
    seen = 0
    slot = getattr(element, "parent_slot", None)
    while slot is not None and seen < 10_000:
        parent = getattr(slot, "parent", None)
        if parent is None:
            return False
        if id(parent) in containers:
            return True
        slot = getattr(parent, "parent_slot", None)
        seen += 1
    return False


def _rebuild(ref, target) -> None:
    """One target redone in place: what NiceGUI's `refresh()` does for each
    of them, without the others."""
    target.container.clear()
    result = target.run(ref.func)
    if helpers.should_await(result):
        background_tasks.create(result, name=f"refresh {ref.func.__name__}")


def _redraw(ref) -> None:
    """Something with a `refresh()` of its own, redone whole."""
    try:
        ref.refresh()
    except Exception:
        # The normal case is that the panel is not instantiated on this window.
        # We do not raise it, but we do not lose it either: with logging at
        # DEBUG one sees what really failed.
        log.debug("panel refresh failed: %r", ref, exc_info=True)


# ---------------------------------------------------------------- the queue
# One action asks for the same panel several times — the actor's own window,
# then the round over every window, then a panel that calls another — and
# each request used to be a rebuild. They now land in a queue, flushed once
# the running handler is over: one rebuild per panel and window. The flush
# is a task of its own that does one window per turn of the event loop, the
# actor's first: the actor sees the result at once, everybody's clicks are
# served in between, and a request that arrives meanwhile goes to the next
# batch — a window not yet redone in this one is left to that batch, so it
# is rebuilt once, with the newest state. Without an event loop (the tests)
# the flush is immediate, at the end of the bus call.
_PENDING: dict[int, list] = {}      # id(ref) → [ref, windows or None for all]
_flush_due = False
_flush_task: asyncio.Task | None = None
_batch_depth = 0
_actor: str | None = None           # the window whose handler asked first


@contextmanager
def _batch():
    """One bus call is one batch: without an event loop (the tests) the
    queue is flushed at its end, not at every panel, so the nesting is seen."""
    global _batch_depth
    _batch_depth += 1
    try:
        yield
    finally:
        _batch_depth -= 1
        if _batch_depth == 0 and _PENDING and not _flush_due:
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                _flush_now()


def _queue(ref, windows: set[str] | None) -> None:
    global _actor
    if _actor is None:
        cid = _window()
        if cid != _GLOBAL:
            _actor = cid
    entry = _PENDING.get(id(ref))
    if entry is None:
        _PENDING[id(ref)] = [ref, None if windows is None else set(windows)]
    elif entry[1] is not None:
        entry[1] = None if windows is None else entry[1] | set(windows)
    _schedule_flush()


def _schedule_flush() -> None:
    global _flush_due
    if _flush_due:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        if _batch_depth == 0:
            _flush_now()
        return
    _flush_due = True
    loop.call_soon(_start_flush)


def _start_flush() -> None:
    global _flush_due, _flush_task
    _flush_due = False
    if _flush_task is not None and not _flush_task.done():
        return              # the running task takes the new batch after its own
    _flush_task = asyncio.ensure_future(_flush_async())


def _take_batch() -> tuple[list, str | None]:
    global _actor
    batch = list(_PENDING.values())
    _PENDING.clear()
    actor, _actor = _actor, None
    return batch, actor


def _plan(batch: list, actor: str | None) -> tuple[list, dict]:
    """The rebuilds of a batch grouped by window, in the order they ship:
    the actor's window, then those on the map — the cheapest, and where the
    shared things are watched — then the rest. Also the containers about to
    be rebuilt, kept alive so their identities hold for the nesting check."""
    rebuilt: dict[int, object] = {}
    by_window: dict[str | None, list] = {}
    base = _fingerprints(batch)
    for ref, windows in batch:
        targets = _targets(ref)
        if targets is None:
            by_window.setdefault(None, []).append((ref, None, None))
            continue
        for target in targets:
            cid = _window_of(target)
            if windows is not None and cid not in windows:
                continue
            stamp = None
            if id(ref) in base:
                stamp = base[id(ref)] + "|" + json.dumps(_window_bits(cid), default=str)
                if getattr(target, "_km_print", None) == stamp:
                    continue        # nothing it reads has moved: the copy stands
            rebuilt[id(target.container)] = target.container
            by_window.setdefault(cid, []).append((ref, target, stamp))

    def rank(cid):
        if cid is None:
            return 0
        if cid == actor:
            return 1
        return 2 if _WINDOWS.get(cid, {}).get("tab") == "map" else 3
    return [(cid, by_window[cid]) for cid in sorted(by_window, key=rank)], rebuilt


def _window_bits(cid: str | None) -> list:
    """What a copy also depends on: the window's language, units and account."""
    data = _WINDOWS.get(cid, {}) if cid else {}
    user_ = data.get("user")
    return [data.get("lang"), data.get("units"),
            getattr(user_, "id", None), getattr(user_, "role", None)]


def _fingerprints(batch: list) -> dict:
    """The inputs of every panel in the batch that declares them, computed
    once per panel; None for the others."""
    base = {}
    for ref, _windows in batch:
        fn = _DEPENDS.get(id(ref))
        if fn is None:
            continue
        try:
            base[id(ref)] = json.dumps(fn(), sort_keys=True, default=str)
        except Exception:
            log.debug("fingerprint failed: %r", ref, exc_info=True)
    return base


def _still_pending(ref, cid: str | None) -> bool:
    entry = _PENDING.get(id(ref))
    return entry is not None and (entry[1] is None or cid in entry[1])


def _run_window(jobs: list, rebuilt: dict) -> None:
    for ref, target, stamp in jobs:
        if target is None:
            _redraw(ref)
            continue
        if _still_pending(ref, _window_of(target)):
            continue        # asked again meanwhile: the next batch redoes it, newer
        if getattr(target.container, "is_deleted", False):
            continue
        if _drawn_inside(target.container, rebuilt):
            continue
        try:
            _rebuild(ref, target)
        except Exception:
            log.debug("panel refresh failed: %r", ref, exc_info=True)
            continue
        if stamp is not None:
            try:
                target._km_print = stamp
            except AttributeError:
                pass


def _flush_now() -> None:
    """Everything queued, rebuilt at once: the path without an event loop."""
    while _PENDING:
        batch, actor = _take_batch()
        groups, rebuilt = _plan(batch, actor)
        for _cid, jobs in groups:
            _run_window(jobs, rebuilt)


async def _flush_async() -> None:
    while _PENDING:
        batch, actor = _take_batch()
        try:
            groups, rebuilt = _plan(batch, actor)
        except Exception:
            log.exception("planning the redraws failed")
            continue
        for _cid, jobs in groups:
            _run_window(jobs, rebuilt)
            await asyncio.sleep(0)


def flush_redraws() -> None:
    """Redoes at once whatever is queued: for whoever needs the panels
    rebuilt before going on (the tests, a handler that reads them back)."""
    _flush_now()


def redraws_idle() -> bool:
    """Nothing queued and no rebuild under way: what a test waits for."""
    return (not _PENDING and not _flush_due
            and (_flush_task is None or _flush_task.done()))


def active_tab(name) -> None:
    """The window changed tab: catches up the panels left behind."""
    name = getattr(name, "name", name)
    cid = _window()
    _WINDOWS.setdefault(cid, {})["tab"] = name
    arrears = _DIRTY.get(cid)
    if not arrears:
        return
    with _batch():
        for panel_name in sorted(arrears):
            ref = _REFRESH.get(cid, {}).get(panel_name)
            if ref is not None:
                if _visible(panel_name, name):
                    arrears.discard(panel_name)
                    _queue(ref, None)
                continue
            # A shared panel left behind in this window only: redone here
            # alone, if one of its copies is on the tab now in front.
            ref = _REFRESH.get(_GLOBAL, {}).get(panel_name)
            if ref is None:
                arrears.discard(panel_name)
                continue
            if any(_window_of(b) == cid and target_in_front(b, name)
                   for b in _targets(ref) or []):
                arrears.discard(panel_name)
                _queue(ref, {cid})


def _refresh(cid: str, panels: dict, names=None, exclude: str | None = None) -> None:
    """Queues the panels of one registration.

    A window's own panels: redone if the window has their tab in front,
    marked otherwise and redone when it comes back (`active_tab`). The shared
    heap (`_GLOBAL`): each copy is redone in the windows on its tab, and the
    other windows owe it. `exclude` is the window that just acted and has
    already seen the result.
    """
    tab_ = _WINDOWS.get(cid, {}).get("tab")
    with _batch():
        for name in (names if names is not None else list(panels)):
            ref = panels.get(name)
            if ref is None:
                continue
            if cid == _GLOBAL:
                watching, reached = _windows_on(ref)
                if exclude:
                    watching.discard(exclude)
                for other in reached - watching:
                    if other != exclude:
                        _DIRTY.setdefault(other, set()).add(name)
                _queue(ref, watching)
            elif _visible(name, tab_):
                _DIRTY.get(cid, set()).discard(name)
                _queue(ref, None)
            else:
                _DIRTY.setdefault(cid, set()).add(name)


def refresh_ui() -> None:
    """Redraws the foreground panels of every connected window."""
    global _refreshing
    if _refreshing:
        return
    _refreshing = True
    try:
        with _batch():
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
    tab_ = _WINDOWS.get(cid, {}).get("tab")
    with _batch():
        panels = _REFRESH.get(cid)
        if panels:
            _refresh(cid, panels, names)
        # The shared panels (registered at import: the header, the turn's
        # steps) have copies in this window too. They were skipped here, and
        # `save_light` sends them to every window but the actor's: whoever
        # ticked a Farmland read the old Consumption in the turn until a
        # reload. Redone here alone when a copy is in front, owed otherwise,
        # as `active_tab` does.
        shared = _REFRESH.get(_GLOBAL, {})
        for name in names:
            ref = shared.get(name)
            if ref is None:
                continue
            copies = [b for b in _targets(ref) or [] if _window_of(b) == cid]
            if any(target_in_front(b, tab_) for b in copies):
                _queue(ref, {cid})
            elif copies:
                _DIRTY.setdefault(cid, set()).add(name)


def refresh_panels(names, exclude: str | None = None) -> None:
    """Redraws only the panels listed, skipping the window that just acted
    (whoever is dragging a slider or typing must not be interrupted)."""
    with _batch():
        for cid, panels in _live_windows():
            if cid == exclude:
                continue
            _refresh(cid, panels, names, exclude=exclude)


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
    awarded = STATE.check_milestones()
    STATE.notify(save=False)
    mark_dirty()
    if awarded:          # a milestone's XP: the figures that show it, everywhere
        refresh_panels(stat_panels("xp", extra=("turn.journal",)))
    if propagate:
        _to_propagate.update(propagate)
        _author = _window()


def save_and_refresh() -> None:
    """Important change: every connected window sees it at once.

    Redraws *everything* that is in front of somebody: every panel, in every
    window that has its tab open; the other windows catch up when they get
    there. Still the most expensive call there is — the Turn column alone is
    hundreds of elements per window — so when one knows what changed,
    `save_and_refresh_panels` is better.
    """
    STATE.check_milestones()
    STATE.notify(save=False)
    mark_dirty()
    refresh_ui()
    _offer_fame()
    _offer_feats()


# The panels that show a kingdom figure, by figure: for the changes that
# touch numbers only — a quick adjustment, an activity's costs and effects —
# so they redraw the sheet and the turn's steps and leave the map alone.
# `tests/test_windows.py` compares every window against a fresh render after
# random changes: a panel missing here is a failed test, not a stale screen.
PANELS_BY_STAT = {
    "rp": ("sheet.risorse", "turn.steps", "city.content"),
    "unrest": ("sheet.identita", "sheet.abilita", "turn.steps", "turn.panel"),
    "xp": ("sheet.identita", "turn.steps"),
    "fame_points": ("sheet.identita",),
    "ruins": ("sheet.caratteristiche", "sheet.abilita"),
    "commodities": ("sheet.risorse", "turn.steps", "city.content"),
    "bonus_dice": ("sheet.risorse", "turn.steps"),
}
_STAT_ALWAYS = ("main.header", "turn.adjustments")


def stat_panels(*fields: str, extra=()) -> tuple:
    """The panels to redraw when these figures changed."""
    names = list(_STAT_ALWAYS) + list(extra)
    for field in fields:
        names.extend(PANELS_BY_STAT[field])
    return tuple(dict.fromkeys(names))


def save_and_refresh_panels(names) -> None:
    """Like `save_and_refresh`, but redraws only the panels listed.

    Same thing for the data — the change is recorded and reaches the disk the
    same way — and different only in how much interface is rebuilt. Listing
    the panels is a commitment: what changes and is not in the list stays
    behind until something else redraws it.
    """
    if STATE.check_milestones():
        names = (*names, *stat_panels("xp", extra=("turn.journal",)))
    STATE.notify(save=False)
    mark_dirty()
    refresh_panels(names)
    _offer_fame()
    _offer_feats()
