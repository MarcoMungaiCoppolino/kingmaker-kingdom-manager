"""The leaders' rules that the Turn tab asks about: the week of downtime each
month, and New Leadership's Loyalty check.

Every leader owes 7 days of downtime a month, not necessarily consecutive.
The app never knows how a PC spent their days, so it asks: a tick per leader
in the Upkeep phase, NPCs ticked by default (the wiki assumes they stay at
court unless the PCs take them away), with a hint from the journeys of the
month. A leader who did not spend the week gives up a Leadership activity
this turn, or takes the vacancy penalty until next turn, as the table chooses.
"""
from __future__ import annotations

from nicegui import ui

from kingmaker import rules
from kingmaker import turn_memory as memory
from kingmaker.access import permissions
from kingmaker.locale.i18n import t
from kingmaker.rules import almanac
from kingmaker.state import STATE
from kingmaker.travel import daily
from kingmaker.ui import theme

_PANELS = ("turn.steps", "turn.panel", "turn.journal", "sheet.ruoli", "sheet.abilita",
           "sheet.identita", "main.header")


# ------------------------------------------------------------- downtime
def downtime() -> dict:
    """This turn's downtime record (a fresh one when the turn moved on)."""
    dt = STATE.k["downtime"]
    if dt.get("turn") != STATE.k["turn"]:
        dt.clear()
        dt.update(turn=STATE.k["turn"], ticks={}, choices={})
    dt.setdefault("ticks", {})
    dt.setdefault("choices", {})
    return dt


def held_roles() -> list[str]:
    return [rid for rid, data in STATE.k["roles"].items() if data.get("name") or data.get("character_id")]


def ticked(rid: str) -> bool:
    """Whether that leader spent the week of downtime: NPCs by default."""
    dt = STATE.k["downtime"]
    ticks = (dt.get("ticks") or {}) if dt.get("turn") == STATE.k["turn"] else {}
    if rid in ticks:
        return bool(ticks[rid])
    return not STATE.k["roles"][rid].get("pc")


def month_span() -> tuple[int, int]:
    """The current month as absolute days of the clock: (first, length)."""
    k = STATE.k
    today = daily.current_date(k)
    days = int((k.get("clock") or {}).get("days", 0))
    length = today.calendar.days_in_month(today.year, today.month)
    return days - (today.day - 1), length


def travel_days(character_id: str | None) -> int:
    """Days this character is on the road in the current month, from the
    journeys the clock ran or is running: a hint, not what the PC really did.

    A journey moved at once (completed with no `turn_resolved`: the clock
    never ran through it) counts nothing, and a day covered by two journeys
    counts once: Marco's table, full of test moves, showed every PC away the
    whole month."""
    if not character_id:
        return 0
    first, length = month_span()
    last = first + length
    away: set[int] = set()
    for status in ("in_progress", "completed"):
        for v in STATE.archive.list_journeys(STATE.campaign, status):
            if character_id not in (v.get("characters") or ()) or v.get("departure_day") is None:
                continue
            if status == "completed" and v.get("turn_resolved") is None:
                continue
            start = int(v["departure_day"])
            end = start + int(v.get("days") or 0)
            away.update(range(max(start, first), min(end, last)))
    return len(away)


@theme.requires(permissions.EDIT_KINGDOM)
def set_tick(rid: str, value: bool) -> None:
    if rid not in STATE.k["roles"]:
        return
    dt = downtime()
    dt["ticks"][rid] = bool(value)
    if value:
        _set_choice(rid, None)
    STATE.record(t("leaders.journal_tick" if value else "leaders.journal_untick",
                   role=STATE.role_label(rid)), "kingdom")
    theme.save_and_refresh_panels(_PANELS)


@theme.requires(permissions.EDIT_KINGDOM)
def set_choice(rid: str, choice: str | None) -> None:
    if rid not in STATE.k["roles"] or choice not in (None, "give_up", "penalty"):
        return
    _set_choice(rid, choice)
    if choice:
        STATE.record(t(f"leaders.journal_{choice}", role=STATE.role_label(rid)), "kingdom")
    theme.save_and_refresh_panels(_PANELS)


def _set_choice(rid: str, choice: str | None) -> None:
    """The choice of an unticked leader; the vacancy penalty lasts until next turn."""
    dt = downtime()
    mem = memory.memory(STATE.k)
    mem["penalties"] = [p for p in mem["penalties"]
                        if not (p.get("kind") == "vacancy" and p.get("role") == rid
                                and p.get("since_turn") == STATE.k["turn"] and p.get("downtime"))]
    if choice is None:
        dt["choices"].pop(rid, None)
        return
    dt["choices"][rid] = choice
    if choice == "penalty":
        mem["penalties"].append({"role": rid, "subject": None, "value": 0, "kind": "vacancy",
                                 "scope": "leader", "reason": t("leaders.downtime_reason"),
                                 "until_turn": STATE.k["turn"], "clears_on": "next_turn",
                                 "phase": None, "since_turn": STATE.k["turn"], "downtime": True})


def downtime_block() -> None:
    """The Upkeep roles step: one row per held role, the tick, the hint, the choice."""
    roles = held_roles()
    if not roles:
        return
    days = almanac.LEADER_REST_DAYS
    # The rule in two lines: the week and the tick, then what a PC who
    # skipped it chooses, the NPC assumption and what the days beside a PC are.
    ui.label(t("leaders.downtime_title", days=days)) \
        .style("font-size:.8rem;color:var(--km-gold-dim);white-space:normal;line-height:1.3")
    ui.label(t("leaders.downtime_rule", days=days)) \
        .style("font-size:.72rem;color:var(--km-muted);white-space:normal;line-height:1.3")
    dt = STATE.k["downtime"] if STATE.k["downtime"].get("turn") == STATE.k["turn"] else {}
    choices = dt.get("choices") or {}
    first, length = month_span()
    # A grid of three columns (the tick, the days, the choice), every row the
    # same height, so the rows line up instead of each one wrapping on its
    # own; a row keeps its three cells even when a column has nothing to say.
    # On a narrow panel the theme's rule folds it to two, the choice under
    # the tick and the days.
    with ui.element("div").classes("km-downtime-box"), ui.element("div").classes("km-downtime"):
        for rid in roles:
            data = STATE.k["roles"][rid]
            on = ticked(rid)
            ui.checkbox(STATE.role_label(rid), value=on,
                        on_change=lambda e, r=rid: set_tick(r, e.value)).props("dense")
            if data.get("pc"):
                away = travel_days(data.get("character_id"))
                free = length - away
                colour = "--km-red" if free < days else "--km-muted"
                ui.label(t("leaders.downtime_hint", away=away, free=free, length=length)) \
                    .style(f"font-size:.72rem;color:var({colour});white-space:nowrap")
            else:
                ui.element("div")
            if not on:
                # Two round buttons with short labels; the role's own vacancy
                # penalty, as the rules give it, appears on hovering the
                # vacancy option (the `label` slot of Quasar's option group).
                penalty = rules.BY_ID["role"][rid]["absence_penalty"]
                radio = ui.radio({"give_up": t("leaders.give_up"), "penalty": t("leaders.penalty")},
                                 value=choices.get(rid),
                                 on_change=lambda e, r=rid: set_choice(r, e.value)) \
                    .props("inline dense").classes("km-dt-choice")
                # NiceGUI numbers the options: in the slot the vacancy is 1.
                radio.add_slot("label", (
                    '<span :class="props.value === 1 ? \'km-dt-penalty\' : \'\'">{{ props.label }}'
                    '<q-tooltip v-if="props.value === 1" anchor="top middle" self="bottom middle">'
                    + theme.esc(t("leaders.vacancy_note", penalty=penalty)) + "</q-tooltip></span>"))
            else:
                ui.element("div").classes("km-dt-choice")


# ------------------------------------------------------------- New Leadership
def loyalty_skills() -> dict:
    return {s["id"]: s["name"] for s in rules.SKILLS if s["ability"] == "loyalty"}


def pending_loyalty() -> None:
    """The leaders who took office after a failed New Leadership: their -1
    lasts until a Loyalty check wins the people over."""
    waiting = [p for p in memory.memory(STATE.k)["penalties"]
               if p.get("clears_on") == "loyalty_check" and memory.penalty_active(STATE.k, p)]
    if not waiting:
        return
    ui.label(t("leaders.loyalty_title")).style("font-size:.8rem;color:var(--km-gold-dim)")
    skills = loyalty_skills()
    for entry in waiting:
        box = {"skill": next(iter(skills))}
        with ui.row().classes("items-center gap-2 w-full flex-wrap"):
            ui.label(STATE.role_label(entry["role"])).style("font-size:.85rem")
            ui.select(skills, value=box["skill"], label=t("turn.skill"),
                      on_change=lambda e, b=box: b.update(skill=e.value)) \
                .props("outlined dense").classes("w-44")
            ui.button(t("leaders.loyalty_roll", dc=STATE.control_dc),
                      on_click=lambda _e=None, x=entry, b=box: roll_loyalty(x, b["skill"])) \
                .props("dense color=amber")


@theme.requires(permissions.EDIT_KINGDOM)
def roll_loyalty(entry: dict, skill: str) -> str | None:
    """The Loyalty check of a leader taking office under a cloud: a success
    lifts the -1, a critical failure costs the role (proposed as rows), a
    failure leaves it for next turn. Returns the grade."""
    from kingmaker.ui.tabs import sheet, turn

    mem = memory.memory(STATE.k)
    if entry not in mem["penalties"] or skill not in rules.BY_ID["skills"]:
        return None
    res = sheet.roll_skill(skill, STATE.control_dc, t("leaders.loyalty_check", role=STATE.role_label(entry["role"])),
                           show=False, leader=entry["role"])
    if res.grade in ("success", "critical_success"):
        mem["penalties"].remove(entry)
        STATE.record(t("leaders.loyalty_won", role=STATE.role_label(entry["role"])), "kingdom")
    theme.save_and_refresh_panels(_PANELS)
    theme.show_result(res, lambda: t("leaders.loyalty_check", role=STATE.role_label(entry["role"])))
    if res.grade == "critical_failure":
        turn.propose_rows(lambda: t("leaders.loyalty_check", role=STATE.role_label(entry["role"])),
                          [{"t": "unrest", "q": "1", "auto": True},
                           {"t": "note", "text": t("turn.loyalty_cf_note")}],
                          context={"act": "new_leadership"})
    return res.grade
