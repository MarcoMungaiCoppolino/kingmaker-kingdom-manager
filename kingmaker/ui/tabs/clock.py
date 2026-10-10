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


def _calendar_line(calendar: almanac.Calendar) -> str:
    """What the calendar means for the turn, under the dialog's title."""
    if calendar.preset == almanac.PRESET:
        return t("clock.absalom_reckoning_calendar_kingdom")
    low, high = calendar.shortest_month(), calendar.longest_month()
    if low == high:
        return t("clock.calendar_turn_fixed", name=calendar.name, days=low)
    return t("clock.calendar_turn_length", name=calendar.name, low=low, high=high)


def _year_label(calendar: almanac.Calendar) -> str:
    era = calendar.era_label()
    return t("clock.year_era", era=era) if era else t("clock.year")


def _date_dialog() -> None:
    """Moves the date by hand: to line the app up with the real campaign."""
    if not permissions.can(theme.user(), permissions.CONTROL_CLOCK):
        theme.notify(t("clock.only_game_master_governs"), "negative")
        return
    block = _block()
    calendar = almanac.calendar_of(STATE.k)
    today = data()
    with theme.dialog() as dlg, ui.card().classes("km-panel").style("min-width:380px"):
        theme.title(t("clock.campaign_date"), 2)
        ui.label(_calendar_line(calendar)).style("color:var(--km-muted);font-size:.8rem")
        with ui.row().classes("gap-2 items-center flex-wrap"):
            day = ui.number(t("clock.day"), value=today.day, min=1,
                            max=calendar.days_in_month(today.year, today.month), step=1) \
                .props("outlined dense").classes("w-24")
            month = ui.select({i: m.name for i, m in enumerate(calendar.months)},
                             label=t("clock.month"), value=today.month) \
                .props("outlined dense options-dense").classes("w-40")
            year = ui.number(_year_label(calendar), value=today.year, step=1) \
                .props("outlined dense").classes("w-32")

        def follow_month() -> None:
            # The day's maximum is the chosen month's, leap days included.
            day.max = calendar.days_in_month(int(year.value or today.year), int(month.value or 0))
            day.update()

        month.on_value_change(lambda _e: follow_month())
        year.on_value_change(lambda _e: follow_month())

        def save() -> None:
            new_one = calendar.date(int(year.value or today.year), int(month.value or 0),
                                    max(1, int(day.value or 1)))
            # We keep the start fixed and move the counter: this way the start
            # date stays the campaign's real one.
            start_ = almanac.from_dict(block.get("start"), calendar)
            block["days"] = max(0, almanac.days_between(start_, new_one))
            if almanac.days_between(start_, new_one) < 0:
                # A date before the start: move the start, not the counter.
                block["start"] = almanac.to_dict(new_one)
                block["days"] = 0
            STATE.record(t("clock.campaign_date_set", new_one=new_one), "turn")
            dlg.close()
            _propagate()

        def other_calendar() -> None:
            dlg.close()
            _calendar_dialog()

        with ui.row().classes("justify-between items-center w-full"):
            ui.button(t("calendar.open"), icon="calendar_month", on_click=other_calendar).props("flat")
            with ui.row().classes("gap-2"):
                ui.button(t("common.cancel"), on_click=dlg.close).props("flat")
                ui.button(t("common.save"), on_click=save).props("color=amber")
    dlg.open()


# ------------------------------------------------------------ the calendar
def _draft_of(calendar: almanac.Calendar) -> dict:
    """The editable form of a calendar. Golarion's months are the starting
    point of a table's own calendar: renaming is quicker than typing twelve."""
    source = calendar if calendar.preset is None else almanac.GOLARION
    leap = source.leap
    return {
        "kind": "golarion" if calendar.preset == almanac.PRESET else "custom",
        "name": calendar.name if calendar.preset is None else "",
        "era": calendar.era if calendar.preset is None else "",
        "months": [{"name": m.name, "days": m.days} for m in source.months],
        "leap_on": leap is not None,
        "leap_every": leap.every if leap else 4,
        "leap_anchor": leap.anchor_year if leap else almanac.DEFAULT_YEAR,
        "leap_month": leap.month if leap else 0,
        "leap_days": leap.days if leap else 1,
    }


def _number(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _calendar_from(draft: dict) -> almanac.Calendar:
    if draft["kind"] == "golarion":
        return almanac.GOLARION
    leap = None
    if draft["leap_on"]:
        leap = almanac.Leap(_number(draft["leap_every"]), _number(draft["leap_anchor"]),
                            _number(draft["leap_month"], -1), _number(draft["leap_days"]))
    months = tuple(almanac.Month(str(m["name"] or "").strip()[:almanac.MAX_NAME], _number(m["days"]))
                   for m in draft["months"])
    return almanac.Calendar(name=str(draft["name"] or "").strip()[:almanac.MAX_NAME],
                            era=str(draft["era"] or "").strip()[:almanac.MAX_ERA],
                            months=months, leap=leap)


def _calendar_dialog() -> None:
    """The campaign's calendar: Golarion's, or one the table writes. The days
    already played stay the same days: only their names change."""
    if not permissions.can(theme.user(), permissions.CONTROL_CLOCK):
        theme.notify(t("clock.only_game_master_governs"), "negative")
        return
    if in_progress():
        theme.notify(t("calendar.stop_clock_first"), "warning")
        return
    current = almanac.calendar_of(STATE.k)
    today = data()
    draft = _draft_of(current)
    when = {"year": today.year, "month": today.month, "day": today.day}
    buttons: dict = {}

    def change(target: dict, key: str, value, redraw: bool = False) -> None:
        target[key] = value
        if redraw:
            body.refresh()
        else:
            checks.refresh()

    with theme.dialog() as dlg, ui.card().classes("km-panel").style("min-width:460px;max-width:640px"):
        theme.title(t("calendar.title"), 2)
        ui.label(t("calendar.intro", days=almanac.LEADER_REST_DAYS)) \
            .style("color:var(--km-muted);font-size:.8rem")

        @ui.refreshable
        def checks() -> None:
            candidate = _calendar_from(draft)
            problems = candidate.validate()
            for key, params in problems:
                ui.label(t(key, **params)).style("color:#d9534f;font-size:.8rem")
            if not problems:
                target = candidate.date(when["year"], when["month"], when["day"])
                ui.label(t("calendar.preview", date=str(target))).style("font-size:.85rem")
            if "save" in buttons:
                buttons["save"].set_enabled(not problems)

        @ui.refreshable
        def body() -> None:
            ui.radio({"golarion": t("calendar.golarion"), "custom": t("calendar.custom")},
                     value=draft["kind"], on_change=lambda e: change(draft, "kind", e.value, True)) \
                .props("dense")
            if draft["kind"] == "custom":
                _custom_fields(draft, change, body)
            theme.sep()
            theme.title(t("calendar.today"), 3)
            ui.label(t("calendar.today_note")).style("color:var(--km-muted);font-size:.8rem")
            candidate = _calendar_from(draft)
            with ui.row().classes("gap-2 items-center flex-wrap"):
                ui.number(t("clock.day"), value=when["day"], min=1, step=1, format="%d",
                          on_change=lambda e: change(when, "day", _number(e.value, 1))) \
                    .props("outlined dense").classes("w-24")
                ui.select({i: (m.name or str(i + 1)) for i, m in enumerate(candidate.months)},
                          label=t("clock.month"),
                          value=when["month"] if when["month"] < len(candidate.months) else None,
                          on_change=lambda e: change(when, "month", e.value if e.value is not None else 0)) \
                    .props("outlined dense options-dense").classes("w-40")
                # A plain "Year": the era is still being typed above, and the
                # preview line under the date shows it.
                ui.number(t("clock.year"), value=when["year"], step=1, format="%d",
                          on_change=lambda e: change(when, "year", _number(e.value))) \
                    .props("outlined dense").classes("w-32")
            checks()

        body()
        with ui.row().classes("justify-end w-full gap-2"):
            ui.button(t("common.cancel"), on_click=dlg.close).props("flat")
            buttons["save"] = ui.button(t("common.save"),
                                        on_click=lambda: _save_calendar(draft, when, dlg)).props("color=amber")
        checks.refresh()
    dlg.open()


def _custom_fields(draft: dict, change, body) -> None:
    """Name, era, months and leap rule of a table's own calendar."""
    with ui.row().classes("gap-2 w-full no-wrap"):
        ui.input(t("calendar.name"), value=draft["name"],
                 on_change=lambda e: change(draft, "name", e.value)) \
            .props(f"outlined dense maxlength={almanac.MAX_NAME}").classes("grow")
        ui.input(t("calendar.era"), value=draft["era"],
                 on_change=lambda e: change(draft, "era", e.value)) \
            .props(f"outlined dense maxlength={almanac.MAX_ERA}").classes("w-48")
    theme.title(t("calendar.months"), 3)
    for i, month in enumerate(draft["months"]):
        with ui.row().classes("gap-2 items-center w-full no-wrap"):
            ui.label(str(i + 1)).classes("w-6 text-right").style("color:var(--km-muted)")
            ui.input(t("calendar.month_name"), value=month["name"],
                     on_change=lambda e, m=month: change(m, "name", e.value)) \
                .props(f"outlined dense maxlength={almanac.MAX_NAME}").classes("grow")
            ui.number(t("calendar.month_days"), value=month["days"], min=1,
                      max=almanac.MAX_MONTH_DAYS, step=1, format="%d",
                      on_change=lambda e, m=month: change(m, "days", _number(e.value))) \
                .props("outlined dense").classes("w-24")

            def remove(i: int = i) -> None:
                draft["months"].pop(i)
                body.refresh()

            ui.button(icon="close", on_click=remove) \
                .props("flat dense round size=sm").tooltip(t("calendar.remove_month"))

    def add() -> None:
        draft["months"].append({"name": "", "days": 30})
        body.refresh()

    if len(draft["months"]) < almanac.MAX_MONTHS:
        ui.button(t("calendar.add_month"), icon="add", on_click=add).props("flat dense")
    ui.checkbox(t("calendar.leap"), value=draft["leap_on"],
                on_change=lambda e: change(draft, "leap_on", e.value, True))
    if draft["leap_on"]:
        with ui.row().classes("gap-2 items-center flex-wrap"):
            ui.number(t("calendar.leap_every"), value=draft["leap_every"], min=1, step=1, format="%d",
                      on_change=lambda e: change(draft, "leap_every", e.value)) \
                .props("outlined dense").classes("w-28")
            ui.number(t("calendar.leap_anchor"), value=draft["leap_anchor"], step=1, format="%d",
                      on_change=lambda e: change(draft, "leap_anchor", e.value)) \
                .props("outlined dense").classes("w-32")
            ui.select({i: (m["name"] or str(i + 1)) for i, m in enumerate(draft["months"])},
                      label=t("calendar.leap_month"),
                      value=draft["leap_month"] if 0 <= draft["leap_month"] < len(draft["months"]) else None,
                      on_change=lambda e: change(draft, "leap_month", e.value if e.value is not None else -1)) \
                .props("outlined dense options-dense").classes("w-40")
            ui.number(t("calendar.leap_days"), value=draft["leap_days"], min=1, step=1, format="%d",
                      on_change=lambda e: change(draft, "leap_days", e.value)) \
                .props("outlined dense").classes("w-28")


@theme.requires(permissions.CONTROL_CLOCK)
def _save_calendar(draft: dict, when: dict, dlg) -> None:
    calendar = _calendar_from(draft)
    if calendar.validate():
        return
    if in_progress():
        theme.notify(t("calendar.stop_clock_first"), "warning")
        return
    save_calendar(calendar, calendar.date(when["year"], when["month"], when["day"]))
    dlg.close()
    _propagate()


def save_calendar(calendar: almanac.Calendar, today: almanac.Data) -> None:
    """Makes `calendar` the campaign's, with `today` as the current date. The
    days already played stay the days they were: `days` does not move
    (journeys count from it), the start is re-expressed in the new calendar."""
    block = _block()
    days = int(block.get("days", 0))
    block["calendar"] = calendar.to_dict()
    block["start"] = almanac.to_dict(calendar.date_plus_days(today, -days))
    name = calendar.name if calendar.preset is None else t("calendar.golarion_short")
    STATE.record(t("calendar.changed", name=name, date=str(today)), "turn")


theme.register_refresh("clock.bar", bar)
