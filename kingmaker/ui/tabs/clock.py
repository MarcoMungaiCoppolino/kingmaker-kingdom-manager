"""The campaign clock: the days that pass, and who makes them pass.

Time flows on the server, not in the browsers: a single timer for everyone, so
two windows never count different days. Players only watch it; starting and
stopping it is the Game Master's.

When the month ends the clock stops by itself and the Kingdom Turn advances:
the rules say turns «occur at the end of each month of game time», and stopping
there is exactly when the table needs the Kingdom Activities. It resumes when
the GM says so.
"""
from __future__ import annotations

import logging
import time

from nicegui import app, ui

from kingmaker.travel import daily
from kingmaker.access import permissions
from kingmaker.rules import almanac
from kingmaker.state import STATE
from kingmaker.ui import theme
from kingmaker.ui.tabs import turn
from kingmaker.locale.i18n import t, tn

log = logging.getLogger(__name__)

# How many real seconds a game day lasts. Short names: they sit on a button,
# and the exact figure is in the tooltip.
SPEED = (("clock.speed.slow", 12.0), ("clock.speed.normal", 6.0), ("clock.speed.fast", 3.0),
         ("clock.speed.fastest", 1.0))

_accumulation = 0.0
_last = time.monotonic()

# Panels to redraw when a day passes: the bar, the map (the markers moved)
# and the tabs that show positions and journeys.
_AFTER_A_DAY = ("clock.bar", "hexmap.map", "hexmap.travel",
                   "hexmap.party", "party.characters", "turn.journeys",
                   "turn.panel", "turn.journal")


def _block() -> dict:
    return STATE.k.setdefault("clock", {})


def data() -> almanac.Data:
    return daily.current_date(STATE.k)


def in_progress() -> bool:
    return bool(_block().get("in_progress"))


def seconds_per_day() -> float:
    return float(_block().get("seconds_per_day", 6.0))


# --------------------------------------------------------------------- commands
@theme.requires(permissions.CONTROL_CLOCK)
def start() -> None:
    global _accumulation, _last
    _accumulation = 0.0
    _last = time.monotonic()
    _block()["in_progress"] = True
    _propagate()


@theme.requires(permissions.CONTROL_CLOCK)
def stop() -> None:
    _block()["in_progress"] = False
    _propagate()


@theme.requires(permissions.CONTROL_CLOCK)
def set_speed(seconds: float) -> None:
    _block()["seconds_per_day"] = float(seconds)
    _propagate()


def _propagate() -> None:
    theme.save_and_refresh()


# ---------------------------------------------------------------- ticking
def _flows() -> None:
    """Called twice a second: converts real time into game days."""
    global _accumulation, _last
    now = time.monotonic()
    elapsed, _last = now - _last, now
    if not in_progress():
        return
    # An absurd interval (the computer went to sleep, the server stood still)
    # must not make months pass in one go.
    _accumulation += min(elapsed, 5.0)

    step = max(0.2, seconds_per_day())
    changed = stopped = False
    while _accumulation >= step:
        _accumulation -= step
        # The day passes anyway, even when it is that very day that stops the
        # clock: the date changed and the button is no longer the one it was.
        # Marking it after the check left the bar on the previous day, saying
        # «1 day to the Kingdom Turn» with the clock still looking on, until
        # someone touched it.
        changed = True
        if not _a_day_passes():
            stopped = True
            break
    if not changed:
        return
    if stopped:
        # End of the month (or an error): the turn changed, and with it the
        # header, the kingdom sheet and the available activities. The full
        # redraw applies, the same the manual turn button does.
        theme.save_and_refresh()
    else:
        theme.mark_dirty()
        theme.refresh_panels(_AFTER_A_DAY)


def _a_day_passes() -> bool:
    """Lets a day pass. Returns False if the clock stopped."""
    try:
        report = daily.advance_one_day(STATE)
    except Exception:
        # An error here would stop the timer forever and the game with it:
        # better stop the clock, say so in the journal and let it restart.
        log.exception("error while a day passed: clock stopped")
        _block()["in_progress"] = False
        STATE.record(t("clock.clock_stopped_error_check"), "turn")
        return False

    for names, where in report.advanced:
        STATE.record(t("clock.travelling_now", names=names, where=where[0], where2=where[1]), "map")
    for names, where in report.arrived:
        STATE.record(t("clock.arrived", names=names, where=where[0], where2=where[1]), "map")

    if report.month_end:
        # End of the month: the turn advances and the clock stops, so the table
        # has time to play its Kingdom Activities.
        _block()["in_progress"] = False
        _block()["turn_started_at"] = int(_block().get("days", 0))
        turn.advance_turn(t("clock.end_month_closed_itself", month_name=report.data.month_name))
        return False
    return True


app.timer(0.5, _flows)


@app.on_startup
def _stopped_at_start() -> None:
    """A server that restarts must not resume grinding days on its own.

    If the app closed with the clock running, on restart we find it stopped:
    letting days pass while nobody was watching is not what whoever started it
    wanted.
    """
    if _block().get("in_progress"):
        _block()["in_progress"] = False
        theme.mark_dirty()


# ------------------------------------------------------------------ interface
@ui.refreshable
def bar() -> None:
    """Date, days left to the Kingdom Turn and the clock controls."""
    user = theme.user()
    today = data()
    missing = almanac.days_left_in_month(today)
    commands = permissions.can(user, permissions.CONTROL_CLOCK)

    with ui.row().classes("items-center gap-2 no-wrap") \
            .style("background:var(--km-panel-2);border:1px solid var(--km-line);"
                   "border-radius:10px;padding:3px 8px"):
        with ui.column().classes("gap-0").style("min-width:132px"):
            ui.html(f'<div class="km-title" style="font-size:.86rem;line-height:1.1">'
                    f'{theme.esc(str(today))}</div>')
            ui.html(f'<div style="font-size:.6rem;color:var(--km-muted);'
                    f'text-transform:uppercase;letter-spacing:.08em">'
                    f'{theme.esc(_subtitle(today, missing))}</div>')

        if commands:
            is_on = in_progress()
            ui.button(icon="pause" if is_on else "play_arrow",
                      on_click=stop if is_on else start) \
                .props(f'dense round size=sm {"color=amber" if is_on else "flat"}') \
                .tooltip(t("clock.stop_passing_time") if is_on
                         else t("clock.let_time_pass_journeys"))
            current_one = seconds_per_day()
            for key, seconds in SPEED:
                name = t(key)
                choice = abs(current_one - seconds) < 0.01
                ui.button(name[0], on_click=lambda _=None, s=seconds: set_speed(s)) \
                    .props(f'dense round size=sm {"color=amber" if choice else "flat"}') \
                    .tooltip(t("clock.one_game_day_every", name=name, seconds=seconds))
            ui.button(icon="today", on_click=_date_dialog) \
                .props("dense round size=sm flat").tooltip(t("clock.set_campaign_date"))
        elif in_progress():
            ui.html(t("clock.span_class_km_chip"))


def _subtitle(today: almanac.Data, missing: int) -> str:
    if missing <= 0:
        return t("clock.end_month_kingdom_turn")
    return tn("clock.days_to_turn", missing)


def _date_dialog() -> None:
    """Moves the date by hand: to line the app up with the real campaign."""
    if not permissions.can(theme.user(), permissions.CONTROL_CLOCK):
        theme.notify(t("clock.only_game_master_governs"), "negative")
        return
    block = _block()
    today = data()
    with theme.dialog() as dlg, ui.card().classes("km-panel").style("min-width:380px"):
        theme.title(t("clock.campaign_date"), 2)
        ui.label(t("clock.absalom_reckoning_calendar_kingdom")).style("color:var(--km-muted);font-size:.8rem")
        with ui.row().classes("gap-2 items-center flex-wrap"):
            day = ui.number(t("clock.day"), value=today.day, min=1, max=31, step=1) \
                .props("outlined dense").classes("w-24")
            month = ui.select({i: m["name"] for i, m in enumerate(almanac.MONTHS)},
                             label=t("clock.month"), value=today.month) \
                .props("outlined dense options-dense").classes("w-40")
            year = ui.number(t("clock.year_ar"), value=today.year, step=1) \
                .props("outlined dense").classes("w-32")

        def save() -> None:
            new_one = almanac.Data(int(year.value or today.year), int(month.value or 0),
                               max(1, int(day.value or 1)))
            max_ = almanac.days_in_month(new_one.year, new_one.month)
            new_one = almanac.Data(new_one.year, new_one.month, min(new_one.day, max_))
            # We keep the start fixed and move the counter: this way the start
            # date stays the campaign's real one.
            start_ = almanac.from_dict(block.get("start"))
            block["days"] = max(0, almanac.days_between(start_, new_one))
            if almanac.days_between(start_, new_one) < 0:
                # A date before the start: move the start, not the counter.
                block["start"] = almanac.to_dict(new_one)
                block["days"] = 0
            STATE.record(t("clock.campaign_date_set", new_one=new_one), "turn")
            dlg.close()
            _propagate()

        with ui.row().classes("justify-end w-full"):
            ui.button(t("common.cancel"), on_click=dlg.close).props("flat")
            ui.button(t("common.save"), on_click=save).props("color=amber")
    dlg.open()


theme.register_refresh("clock.bar", bar)
