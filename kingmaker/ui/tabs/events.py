"""The kingdom's ongoing events: named by the GM, checked in the Event phase.

The wiki keeps no table of kingdom events (the GM has the book), so the app
does not roll them: it tracks them. A random event the Event phase brings,
or a story event the GM adds, becomes an entry of `k["events"]` with its
level modifier and what it is (continuous, harmful, dangerous, the leader
it calls for, the settlement it strikes). Its check offers what helps
resolve it (a Watchtower, Quick Recovery, the leader's bonus, Hire
Adventurers' +2), and its outcome is built by the GM from the book as rows
the table applies, like every other effect.
"""
from __future__ import annotations

import uuid

from nicegui import ui

from kingmaker import rules
from kingmaker.access import permissions
from kingmaker.locale.i18n import t
from kingmaker.state import STATE
from kingmaker.ui import theme

# The panels an event's change reaches: the Event phase's list, the figures
# its XP moves, and the Turn column, whose Hire Adventurers card is dimmed
# while no event is ongoing.
_PANELS = ("turn.steps", "turn.panel", "turn.journal", "turn.adjustments", "sheet.identita",
           "main.header")

# The effect kinds the GM may add to an event's outcome.
OUTCOME_KINDS = ("unrest", "ruin_choice", "rp", "resource_die", "commodity_choice", "xp", "fame",
                 "bonus_dice")


def _kind_label(kind: str) -> str:
    return t(f"events.kind_{kind}")


# ------------------------------------------------------------- the entries
def new_entry(name: str, *, kind: str = "random", modifier: int = 0, continuous: bool = False,
              harmful: bool = False, dangerous: bool = False, leader: str | None = None,
              leader_bonus: int = 0, settlement: str | None = None, hexes: str = "", note: str = "",
              xp: int = 0, source: str = "gm") -> dict:
    """A new ongoing event in the kingdom, `xp` awarded with it (30 for a
    random event, 30 or more for a story event), once. No window needed:
    `_create` is the button's."""
    ev = {"id": uuid.uuid4().hex[:8], "name": name.strip(), "kind": kind, "modifier": int(modifier),
          "continuous": bool(continuous), "harmful": bool(harmful), "dangerous": bool(dangerous),
          "leader": leader or None, "leader_bonus": int(leader_bonus or 0),
          "settlement": settlement or None, "hexes": hexes, "started_turn": STATE.k["turn"],
          "ended_turn": None, "hire_failed": False, "hire_locked": False, "hire_bonus": None,
          "xp_awarded": False, "note": note, "source": source}
    STATE.k["events"].append(ev)
    if xp > 0:
        STATE.k["xp"] += xp
        ev["xp_awarded"] = True
    STATE.record(t("events.journal_started", name=ev["name"], xp=max(0, xp)), "event")
    return ev


@theme.requires(permissions.EDIT_KINGDOM)
def _create(name: str, **fields) -> dict:
    ev = new_entry(name, **fields)
    theme.save_and_refresh_panels(_PANELS)
    return ev


@theme.requires(permissions.EDIT_KINGDOM)
def _update(ev: dict, **fields) -> None:
    ev.update(fields)
    STATE.record(t("events.journal_edited", name=ev["name"]), "event")
    theme.save_and_refresh_panels(_PANELS)


@theme.requires(permissions.EDIT_KINGDOM)
def _end(ev: dict) -> None:
    ev["ended_turn"] = STATE.k["turn"]
    STATE.record(t("events.journal_ended", name=ev["name"]), "event")
    theme.save_and_refresh_panels(_PANELS)


@theme.requires(permissions.EDIT_KINGDOM)
def _reopen(ev: dict) -> None:
    ev["ended_turn"] = None
    STATE.record(t("events.journal_reopened", name=ev["name"]), "event")
    theme.save_and_refresh_panels(_PANELS)


# ------------------------------------------------------------- the dialog
def _role_options() -> dict:
    return {"": t("events.no_leader"), **{rid: STATE.role_label(rid) for rid in STATE.k["roles"]}}


def _settlement_options() -> dict:
    return {"": t("events.no_settlement"), **{s["id"]: s["name"] for s in STATE.k["settlements"]}}


def new_event_dialog(kind: str = "random", name: str = "", source: str = "gm", hex_=None,
                     entry: dict | None = None) -> None:
    """Names an event (or edits `entry`). A new one offers its XP: 30 for a
    random event, 30 or more for a story event, typed by the GM."""
    ev = entry or {}
    form = {"name": ev.get("name", name), "kind": ev.get("kind", kind),
            "modifier": ev.get("modifier", 0), "continuous": ev.get("continuous", False),
            "harmful": ev.get("harmful", False), "dangerous": ev.get("dangerous", False),
            "leader": ev.get("leader") or "", "leader_bonus": ev.get("leader_bonus", 0),
            "settlement": ev.get("settlement") or "",
            "hexes": ev.get("hexes", f"{hex_[0]},{hex_[1]}" if hex_ else ""),
            "note": ev.get("note", ""), "xp_on": entry is None, "xp": 30}
    with theme.dialog() as dlg, ui.card().classes("km-panel") \
            .style("min-width:520px;max-width:680px;max-height:85vh;overflow-y:auto"):
        theme.title(t("events.edit_title") if entry else t("events.new_title"), 2)
        ui.input(t("events.name"), value=form["name"],
                 on_change=lambda e: form.update(name=e.value or "")) \
            .props("outlined dense autofocus").classes("w-full")
        with ui.row().classes("items-center gap-3 flex-wrap"):
            ui.select({"random": t("events.kind_random"), "story": t("events.kind_story")},
                      value=form["kind"], label=t("events.kind"),
                      on_change=lambda e: (form.update(kind=e.value), xp_row.refresh())) \
                .props("outlined dense").classes("w-40")
            ui.number(t("events.modifier"), value=form["modifier"], format="%d",
                      on_change=lambda e: form.update(modifier=int(e.value or 0))) \
                .props("outlined dense").classes("w-36")
        with ui.row().classes("items-center gap-3 flex-wrap"):
            for key in ("continuous", "harmful", "dangerous"):
                ui.checkbox(t(f"events.{key}"), value=form[key],
                            on_change=lambda e, key=key: form.update({key: e.value})).props("dense")
        with ui.row().classes("items-center gap-3 flex-wrap"):
            ui.select(_role_options(), value=form["leader"], label=t("events.leader"),
                      on_change=lambda e: form.update(leader=e.value or "")) \
                .props("outlined dense").classes("w-64")
            ui.number(t("events.leader_bonus"), value=form["leader_bonus"], format="%d",
                      on_change=lambda e: form.update(leader_bonus=int(e.value or 0))) \
                .props("outlined dense").classes("w-36")
        ui.label(t("events.leader_bonus_hint")).style("font-size:.75rem;color:var(--km-muted)")
        with ui.row().classes("items-center gap-3 flex-wrap"):
            ui.select(_settlement_options(), value=form["settlement"], label=t("events.settlement"),
                      on_change=lambda e: form.update(settlement=e.value or "")) \
                .props("outlined dense").classes("w-56")
            ui.input(t("events.hexes"), value=form["hexes"],
                     on_change=lambda e: form.update(hexes=e.value or "")) \
                .props("outlined dense").classes("w-48")
        ui.textarea(t("events.note"), value=form["note"],
                    on_change=lambda e: form.update(note=e.value or "")) \
            .props("outlined dense autogrow").classes("w-full")

        @ui.refreshable
        def xp_row() -> None:
            if entry is not None:
                return
            story = form["kind"] == "story"
            form["xp"] = max(30, form["xp"]) if story else form["xp"]
            with ui.row().classes("items-center gap-3"):
                ui.checkbox(t("events.xp_row"), value=form["xp_on"],
                            on_change=lambda e: form.update(xp_on=e.value)).props("dense")
                ui.number(t("turn.xp"), value=form["xp"], min=30 if story else 0, format="%d",
                          on_change=lambda e: form.update(xp=int(e.value or 0))) \
                    .props("outlined dense").classes("w-28")
            ui.label(t("events.xp_hint_story") if story else t("events.xp_hint_random")) \
                .style("font-size:.75rem;color:var(--km-muted)")

        xp_row()

        def save() -> None:
            if not form["name"].strip():
                theme.notify(t("events.name_needed"), "warning")
                return
            dlg.close()
            fields = dict(kind=form["kind"], modifier=form["modifier"], continuous=form["continuous"],
                          harmful=form["harmful"], dangerous=form["dangerous"],
                          leader=form["leader"] or None, leader_bonus=form["leader_bonus"],
                          settlement=form["settlement"] or None, hexes=form["hexes"], note=form["note"])
            if entry is not None:
                _update(entry, name=form["name"].strip(), **fields)
                return
            xp = form["xp"] if form["xp_on"] else 0
            if form["kind"] == "story" and xp:
                xp = max(30, xp)
            _create(form["name"], xp=xp, source=source, **fields)

        with ui.row().classes("justify-end w-full gap-2"):
            ui.button(t("common.cancel"), on_click=dlg.close).props("flat")
            ui.button(t("common.save"), on_click=save).props("color=amber")
    dlg.open()


# ------------------------------------------------------------- the list
def _chips(ev: dict) -> str:
    out = [_kind_label(ev.get("kind", "random"))]
    if ev.get("modifier"):
        out.append(f"{int(ev['modifier']):+d}")
    for key in ("continuous", "harmful", "dangerous"):
        if ev.get(key):
            out.append(t(f"events.{key}"))
    if ev.get("leader"):
        out.append(rules.BY_ID["role"][ev["leader"]]["name"])
    sett = STATE.settlement(ev.get("settlement") or "")
    if sett:
        out.append(sett["name"])
    return "".join(f'<span class="km-chip" style="font-size:.66rem">{theme.esc(x)}</span>' for x in out)


def ongoing_list() -> None:
    """The ongoing events, each with its check; those ended this turn below."""
    ongoing = STATE.ongoing_events()
    ended = [e for e in STATE.k["events"] if e.get("ended_turn") == STATE.k["turn"]]
    if not ongoing and not ended:
        ui.label(t("events.none")).style("font-size:.8rem;color:var(--km-muted)")
    for ev in ongoing:
        with ui.row().classes("items-center gap-2 w-full flex-wrap"):
            ui.label(ev["name"]).classes("km-title").style("font-size:.9rem")
            ui.html(f'<span style="display:inline-flex;gap:4px;flex-wrap:wrap">{_chips(ev)}</span>')
            ui.element("div").style("flex:1")
            ui.button(t("events.check"), on_click=lambda _e=None, x=ev: check_dialog(x)) \
                .props("dense color=amber")
            ui.button(t("events.edit"), on_click=lambda _e=None, x=ev: new_event_dialog(entry=x)) \
                .props("dense flat color=amber")
            ui.button(t("events.ended"), on_click=lambda _e=None, x=ev: _end(x)) \
                .props("dense flat color=grey")
    for ev in ended:
        with ui.row().classes("items-center gap-2 w-full").style("opacity:.6"):
            ui.label(t("events.ended_this_turn", name=ev["name"])).style("font-size:.8rem")
            ui.button(t("events.reopen"), on_click=lambda _e=None, x=ev: _reopen(x)) \
                .props("dense flat size=sm color=grey")


# ------------------------------------------------------------- the check
def check_extras(ev: dict) -> list[tuple[str, int, str]]:
    """What helps resolve the event, as typed bonuses for the check: a
    Watchtower in its settlement, the leader's bonus when the role is held,
    Hire Adventurers' +2 when earned."""
    out = []
    sett = STATE.settlement(ev.get("settlement") or "")
    if sett and "watchtower" in STATE.structures_of(sett):
        out.append((t("events.watchtower_chip", name=rules.BY_ID["structure"]["watchtower"]["name"],
                      settlement=sett["name"]), 1, "item"))
    if ev.get("leader") and ev.get("leader_bonus") and not STATE.role_vacant(ev["leader"]):
        out.append((t("events.leader_bonus_chip", role=rules.BY_ID["role"][ev["leader"]]["name"]),
                    int(ev["leader_bonus"]), "circumstance"))
    if ev.get("hire_bonus") is not None:
        out.append((rules.BY_ID["activities"]["hire_adventurers"]["name"], 2, "circumstance"))
    return out


def check_event_kind(ev: dict) -> str | None:
    """The kind of event a feat may help with: Quick Recovery's «ongoing»."""
    return "ongoing" if ev.get("continuous") and ev.get("harmful") else None


@theme.requires(permissions.EDIT_KINGDOM)
def roll_event(ev: dict, skill: str, dc: int, reroll: bool = False) -> rules.Result:
    """The event's check, with what helps it; Hire Adventurers' +2 is used up
    by the first roll (a reroll for Fame is the same check again)."""
    from kingmaker.ui.tabs import sheet

    extras = check_extras(ev)
    if reroll and ev.get("hire_spent") == STATE.k["turn"]:
        extras.append((rules.BY_ID["activities"]["hire_adventurers"]["name"], 2, "circumstance"))
    res = sheet.roll_skill(skill, dc, ev["name"], show=False, event=check_event_kind(ev),
                           extra=extras, category="event")
    if ev.get("hire_bonus") is not None:
        ev["hire_bonus"] = None              # used up by this roll
        ev["hire_spent"] = STATE.k["turn"]
    return res


@theme.requires(permissions.EDIT_KINGDOM)
def check_dialog(ev: dict) -> None:
    """The event's check: a skill, the DC (Control DC + modifier), and what helps."""
    skills = {s["id"]: s["name"] for s in rules.SKILLS}
    choice = {"skill": next(iter(skills)), "dc": STATE.event_dc(ev)}
    extras = check_extras(ev)
    kind = check_event_kind(ev)
    with theme.dialog() as dlg, ui.card().classes("km-panel").style("min-width:480px;max-width:620px"):
        theme.title(ev["name"], 2)
        with ui.row().classes("items-center gap-3 flex-wrap"):
            ui.select(skills, value=choice["skill"], label=t("turn.skill"),
                      on_change=lambda e: (choice.update(skill=e.value), mod_row.refresh())) \
                .props("outlined dense").classes("w-52")
            ui.number(t("turn.dc"), value=choice["dc"], format="%d",
                      on_change=lambda e: choice.update(dc=int(e.value or 0))) \
                .props("outlined dense").classes("w-28")
            ui.label(t("events.dc_breakdown", control_dc=STATE.control_dc,
                       modifier=f"{int(ev.get('modifier') or 0):+d}")) \
                .style("font-size:.78rem;color:var(--km-muted)")

        @ui.refreshable
        def mod_row() -> None:
            detail = STATE.check_detail(choice["skill"], event=kind, extra=extras)
            with ui.row().classes("items-center gap-2 flex-wrap"):
                ui.html(f'<span class="km-mod">{sum(v for _n, v in detail):+d}</span>')
                for n, v in detail:
                    ui.html(f'<span class="km-chip" style="font-size:.7rem">{theme.esc(n)} {v:+d}</span>')

        mod_row()

        def roll() -> None:
            dlg.close()
            check = dict(choice)
            res = roll_event(ev, check["skill"], check["dc"])
            outcome_dialog(ev, res, lambda: roll_event(ev, check["skill"], check["dc"], reroll=True))

        with ui.row().classes("gap-2"):
            ui.button(t("turn.roll_check"), on_click=roll).props("color=amber")
            ui.button(t("common.close"), on_click=dlg.close).props("flat")
    dlg.open()


def cemetery_row(ev: dict) -> dict | None:
    """A dangerous event in a settlement: -1 Unrest per Cemetery there, up to 4."""
    sett = STATE.settlement(ev.get("settlement") or "")
    if not (ev.get("dangerous") and sett):
        return None
    n = STATE.structures_of(sett).get("cemetery", 0)
    if not n:
        return None
    return {"t": "unrest", "q": f"-{min(4, n)}", "auto": False,
            "text": t("events.cemetery_row", settlement=sett["name"])}


def outcome_dialog(ev: dict, res: rules.Result, reroll=None, rerolled: bool = False) -> None:
    """The event's result and the rows the GM builds from the book's outcome."""
    from kingmaker.ui.tabs import turn

    grade = rules.grade_label(res.grade)
    theme.share_roll(res, lambda: ev["name"])
    entries: list[dict] = []
    cem = cemetery_row(ev)
    if cem:
        entries.append(cem)
    state = {"ends": False, "kind": OUTCOME_KINDS[0], "q": "1"}
    holder = {"rows": []}

    @theme.requires(permissions.EDIT_KINGDOM)
    def again() -> None:
        dlg.close()
        if not STATE.spend_fame():
            theme.notify(t("theme.fame_none_left", fame=STATE.fame_name), "warning")
            outcome_dialog(ev, res, None, rerolled)
            return
        theme.record_reroll(lambda: ev["name"], res)
        new = reroll()
        theme.save_and_refresh_panels(theme.stat_panels("fame_points", extra=("turn.journal",)))
        outcome_dialog(ev, new, reroll, rerolled=True)

    with theme.dialog() as dlg, ui.card().classes("km-panel") \
            .style("min-width:520px;max-width:680px;max-height:85vh;overflow-y:auto"):
        theme.title(t("theme.rerolled", title=ev["name"]) if rerolled else ev["name"], 2)
        theme.result_block(res)
        theme.sep()
        ui.label(t("events.outcome_hint")).style("font-size:.8rem;color:var(--km-muted);white-space:normal")
        with ui.row().classes("items-center gap-2 flex-wrap"):
            ui.select({k_: t(f"events.row_{k_}") for k_ in OUTCOME_KINDS}, value=state["kind"],
                      label=t("events.row_kind"), on_change=lambda e: state.update(kind=e.value)) \
                .props("outlined dense").classes("w-48")
            ui.input(t("events.row_quantity"), value=state["q"],
                     on_change=lambda e: state.update(q=e.value or "")) \
                .props("outlined dense").classes("w-28")

            def add() -> None:
                q = (state["q"] or "").strip()
                if not rules.signed_value(q)[1] and not q.lstrip("+-").isdigit():
                    theme.notify(t("events.row_bad_quantity"), "warning")
                    return
                entries.append({"t": state["kind"], "q": q, "auto": True})
                rows_block.refresh()

            ui.button(t("events.row_add"), on_click=add).props("dense outline color=amber")

        @ui.refreshable
        def rows_block() -> None:
            holder["rows"] = turn._effect_rows(entries, context={"event": ev["id"]}) if entries else []

        rows_block()
        ui.checkbox(t("events.ends"), value=False, on_change=lambda e: state.update(ends=e.value)) \
            .props("dense")

        @theme.requires(permissions.EDIT_KINGDOM)
        def apply() -> None:
            dlg.close()
            done = turn._apply_rows(holder["rows"], f"{ev['name']} ({grade})", {"event": ev["id"]},
                                    category="event")
            if state["ends"]:
                _end(ev)
            elif not done:
                theme.save_and_refresh_panels(_PANELS)
            theme.notify(t("turn.applied", list="; ".join(done)) if done else t("turn.no_effect_applied"),
                         "positive" if done else "info")

        with ui.row().classes("gap-2 flex-wrap"):
            ui.button(t("turn.apply_effects"), on_click=apply).props("color=amber")
            ui.button(t("turn.skip"), on_click=dlg.close).props("flat")
            if reroll is not None and theme.can_reroll(res, rerolled):
                ui.button(theme.reroll_label(), on_click=again).props("outline color=amber")
    dlg.open()


# ------------------------------------------------------------- the pending checks
def pending_extra(entry: dict) -> int:
    """Irrigation's flat check: +1 for every other open critical failure."""
    if not entry.get("dc_per_hex"):
        return 0
    pending = STATE.k["turn_memory"]["pending"]
    return sum(1 for e in pending if e is not entry and e.get("dc_per_hex")
               and e.get("source") == entry.get("source"))


def _source_name(entry: dict) -> str:
    act = rules.BY_ID["activities"].get(entry.get("source") or "")
    return act["name"] if act else (entry.get("source") or "")


@theme.requires(permissions.EDIT_KINGDOM)
def roll_pending(entry: dict, dc: int | None = None) -> bool | None:
    """Rolls a pending flat check (None: the event comes without a roll).
    The entry counts down and falls due again next turn while checks are
    left; a failure (or no roll at all) names the event it forces. Returns
    whether the check succeeded."""
    pending = STATE.k["turn_memory"]["pending"]
    if entry not in pending:
        return None
    event_name = rules.forced_event_name(entry.get("then"))
    hex_ = entry.get("hex")
    where = f" ({hex_[0]},{hex_[1]})" if hex_ else ""
    ok = None
    if entry.get("dc") is None:
        STATE.record(t("events.pending_auto_journal", event=event_name, source=_source_name(entry),
                       where=where), "event")
    else:
        dc = int(dc if dc is not None else entry["dc"] + pending_extra(entry))
        tot, rolls = rules.roll(1, 20)
        ok = tot >= dc
        STATE.record(t("events.pending_journal", source=_source_name(entry), event=event_name,
                       roll=tot, dc=dc, where=where,
                       grade=rules.grade_label("success" if ok else "failure")), "event")
        theme.show_dice(lambda: t("events.pending_title", event=rules.forced_event_name(entry.get("then"))),
                        rolls, 20,
                        (lambda: t("events.pending_safe")) if ok
                        else (lambda: t("events.pending_comes", event=rules.forced_event_name(entry.get("then")))),
                        dc=dc)
    remaining = entry.get("remaining")
    if remaining is not None:
        remaining -= 1
        entry["remaining"] = remaining
    if remaining is not None and remaining <= 0:
        pending.remove(entry)
    else:
        entry["due_turn"] = STATE.k["turn"] + 1
    theme.save_and_refresh_panels(_PANELS)
    if not ok:
        new_event_dialog(kind="random", name=event_name, source="pending",
                         hex_=tuple(hex_) if hex_ else None)
    return ok


def pending_block() -> None:
    """The flat checks the activities left for this Event phase."""
    from kingmaker.locale.i18n import tn

    due = STATE.due_checks()
    if not due:
        return
    ui.label(tn("turn.pending_due", len(due))).style("font-size:.8rem;color:var(--km-gold-dim)")
    for entry in due:
        hex_ = entry.get("hex")
        with ui.row().classes("items-center gap-2 w-full flex-wrap"):
            ui.label(_source_name(entry)).classes("km-title").style("font-size:.88rem")
            if hex_:
                ui.html(f'<span class="km-chip" style="font-size:.66rem">{hex_[0]},{hex_[1]}</span>')
            ui.label(rules.forced_event_name(entry.get("then"))).style("font-size:.8rem;color:var(--km-muted)")
            ui.element("div").style("flex:1")
            if entry.get("dc") is None:
                ui.button(t("events.pending_create"), on_click=lambda _e=None, x=entry: roll_pending(x)) \
                    .props("dense color=red")
                continue
            extra = pending_extra(entry)
            box = {"dc": entry["dc"] + extra}
            ui.number(t("turn.dc"), value=box["dc"], format="%d",
                      on_change=lambda e, b=box: b.update(dc=int(e.value or 0))) \
                .props("outlined dense").classes("w-24")
            if extra:
                ui.label(t("events.pending_extra", dc=entry["dc"], n=extra)) \
                    .style("font-size:.72rem;color:var(--km-muted)")
            ui.button(t("events.pending_roll"), on_click=lambda _e=None, x=entry, b=box: roll_pending(x, b["dc"])) \
                .props("dense color=amber")
