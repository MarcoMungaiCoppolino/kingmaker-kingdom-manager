"""Kingdom Turn: phases, guided steps and rollable activities."""
from __future__ import annotations

from nicegui import ui

from kingmaker.access import permissions
from kingmaker import rules
from kingmaker.travel import daily
from kingmaker.state import STATE
from kingmaker.ui import hexmap, theme
from kingmaker.ui.tabs import sheet
from kingmaker.locale.i18n import t

REFERENCES = {
    "map": ("map", "turn.this_activity_performed_from"),
    "city": ("location_city", "turn.this_activity_performed_from_2"),
}


# --------------------------------------------------------------------------
def _activity_dc(act: dict) -> tuple[int, str]:
    cd = act["dc"]
    if cd["kind"] == "control":
        return STATE.control_dc + cd.get("mod", 0), (
            t("turn.control_dc", control_dc=STATE.control_dc)
            + (f" {cd['mod']:+d}" if cd.get("mod") else "")
            + (f" — {cd['note']}" if cd.get("note") else ""))
    if cd["kind"] == "fixed":
        return cd["valore"], t("turn.fixed_dc", dc=cd["valore"])
    if cd["kind"] == "none_":
        return 0, cd.get("note") or t("turn.no_check")
    return STATE.control_dc, cd.get("note") or t("turn.dc_gm")


def outcomes_block(act: dict) -> None:
    """Lists the four degrees of success of the activity, as in the Manual."""
    for grade in ("critical_success", "success", "failure", "critical_failure"):
        text = act["outcomes"].get(grade)
        if text:
            ui.html(f'<div style="font-size:.82rem"><b class="{theme.GRADE_CLASSES[grade]}">'
                    f'{rules.grade_label(grade)}:</b> {text}</div>')


def _effect_rows(entries: list[dict], skill: str | None = None) -> list[dict]:
    """Draws the entries as tickable, editable rows; returns their state.
    `skill`, the one the check used, is the first choice where an effect
    asks for a skill (Focused Attention)."""
    rows: list[dict] = []
    for v in entries:
        if v["t"] == "note":
            ui.html(f'<div style="font-size:.78rem;color:var(--km-muted);'
                    f'border-left:2px solid var(--km-line);padding-left:8px">{v["text"]}</div>')
            continue
        value, explain = ((v["v"], "") if v["t"] == "mod"
                          else rules.signed_value(v.get("q", "0")))
        active = bool(v.get("auto", True))
        # «Lose 1 Fame; if you have none, gain 1d4 Unrest instead»: which of
        # the two applies depends on the points in hand now.
        if v.get("only_if") in ("fame", "no_fame"):
            active = (STATE.k["fame_points"] > 0) == (v["only_if"] == "fame")
        row = {"entry": v, "active": active, "valore": value, "target": None, "base": value}
        with ui.row().classes("items-center gap-2 w-full no-wrap"):
            ui.checkbox(value=row["active"],
                        on_change=lambda e, r=row: r.update(active=e.value)).props("dense")
            ui.label(rules.entry_label(v, value)).style("font-size:.82rem;flex:1;min-width:0")
            if v["t"] not in ("mod", "milestone", "focus"):
                row["field"] = ui.number(value=value, format="%d",
                                         on_change=lambda e, r=row: r.update(valore=int(e.value or 0))) \
                    .props("outlined dense").classes("w-20")
            tgt = rules.entry_target(v)
            if tgt:
                listing = {"ruin": rules.RUINS, "skill": rules.SKILLS}.get(tgt, rules.COMMODITIES)
                ids = [x["id"] for x in listing]
                row["target"] = skill if tgt == "skill" and skill in ids else ids[0]
                ui.select({x["id"]: x["name"] for x in listing}, value=row["target"],
                          on_change=lambda e, r=row: r.update(target=e.value)) \
                    .props("outlined dense").classes("w-32")
        if explain or v.get("text"):
            ui.html(f'<div style="font-size:.7rem;color:var(--km-gold-dim);margin:-4px 0 2px 34px">'
                    f'{" · ".join(x for x in (explain, v.get("text")) if x)}</div>')
        rows.append(row)
    return rows


def _per_count(entries: list[dict], rows_of) -> None:
    """«1 per trade agreement», «2 per point spent», «1 RP per hex»: a count
    that multiplies those rows. `rows_of()` gives the rows, drawn after it."""
    per = next((v["per"] for v in entries if v.get("per")), None)
    if not per:
        return

    def recount(n) -> None:
        n = max(0, int(n or 0))
        for row in rows_of():
            if row["entry"].get("per") and "field" in row:
                row["valore"] = row["base"] * n
                row["field"].value = row["valore"]

    ui.number(t(f"turn.per_{per}"), value=1, min=0, format="%d",
              on_change=lambda e: recount(e.value)).props("outlined dense").classes("w-48")


# Which figures an effect kind touches (`State.apply_effect`); a kind not
# listed — a modifier, or a kind added later — redraws everything.
_EFFECT_FIELDS = {
    "unrest": ("unrest",), "ruin": ("ruins",), "ruin_choice": ("ruins",),
    "rp": ("rp",), "rp_next": (), "xp": ("xp",), "fame": ("fame_points",), "fame_next": ("fame_points",), "milestone": ("xp",),
    "commodity": ("commodities",), "commodity_choice": ("commodities",),
    "resource_die": ("rp", "bonus_dice"), "bonus_dice": ("bonus_dice",),
}



@theme.requires(permissions.EDIT_KINGDOM)
def _apply_rows(rows: list[dict], title: str) -> list[str]:
    active = [r for r in rows if r["active"]]
    dice: list[dict] = []
    done_ones = [d for r in active
             for d in [STATE.apply_effect(r["entry"], r["valore"], r["target"], dice)] if d]
    if done_ones:
        STATE.record(f"{title}: " + "; ".join(done_ones), "activities")
        fields = [_EFFECT_FIELDS.get(r["entry"]["t"]) for r in active]
        if any(f is None for f in fields):
            theme.save_and_refresh()
        else:
            theme.save_and_refresh_panels(
                theme.stat_panels(*(x for f in fields for x in f), extra=("turn.journal",)))
    # Resource Dice rolled by an effect or a cost: on screen for the table.
    for roll in dice:
        key = "theme.effect_dice_spent" if roll["spent"] else "theme.effect_dice_gained"
        theme.show_dice(lambda: t("theme.resource_dice"), roll["rolls"], roll["faces"],
                        lambda key=key, roll=roll: t(key, tot=roll["total"], what=title))
    return done_ones


def _reference_dialog(act: dict) -> None:
    icon, text = REFERENCES[act["reference"]]
    text = t(text)
    with theme.dialog() as dlg, ui.card().classes("km-panel").style("max-width:520px"):
        theme.title(act["name"], 2)
        with ui.row().classes("items-start gap-3 no-wrap"):
            ui.icon(icon).style("color:var(--km-gold);font-size:1.6rem")
            ui.label(text).style("font-size:.85rem;white-space:normal")
        ui.button(t("turn.got"), on_click=dlg.close).props("flat color=amber")
    dlg.open()


@theme.requires(permissions.EDIT_KINGDOM)
def run_activity(act: dict) -> None:
    """Generic dialog to attempt a Kingdom activity."""
    if act.get("reference"):
        _reference_dialog(act)
        return

    default_dc, dc_note = _activity_dc(act)
    options = [a for a in act["skills"] if a != "*"]
    if act["skills"] == ["*"]:
        options = [a["id"] for a in rules.SKILLS]
    # Quell Unrest: never with the skill used for it last turn.
    last = STATE.k["feat_turns"].get("quell_skill") or {}
    banned = last.get("skill") if act["id"] == "quell_unrest" and last.get("turn") == STATE.k["turn"] - 1 else None
    if banned in options and len(options) > 1:
        options.remove(banned)
    # Practical Magic: Magic in place of Engineering.
    if "practical_magic" in STATE.k["feats"] and "engineering" in options and "magic" not in options:
        options.append("magic")
    block = STATE.activities_block(act)

    with theme.dialog() as dlg, ui.card().classes("km-panel") \
            .style("min-width:600px;max-width:760px;max-height:85vh;overflow-y:auto"):
        theme.title(act["name"], 1)
        with ui.row().classes("gap-2 flex-wrap"):
            for trait in act["traits"]:
                ui.html(f'<span class="km-chip" style="font-size:.7rem">{trait}</span>')
        ui.markdown(act["description"]).style("font-size:.88rem")
        if act.get("skills_note"):
            ui.markdown(t("turn.text", skills_note=act['skills_note'])).style("font-size:.82rem;color:var(--km-muted)")
        if any(act["outcomes"].get(g) for g in rules.GRADES):
            theme.sep()
            with ui.column().classes("gap-1 w-full"):
                outcomes_block(act)

        theme.sep()
        if block:
            ui.html(f'<div class="km-chip km-fc" style="white-space:normal">{block}</div>')
        if not options:
            ui.label(dc_note).style("color:var(--km-muted)")
            ui.button(t("common.close"), on_click=dlg.close).props("flat color=amber")
            dlg.open()
            return

        ready = {"requirements": not act["requirements"]}
        if act["requirements"]:
            ui.checkbox(t("turn.requirements_met"),
                        on_change=lambda e: (ready.update(requirements=e.value), buttons.refresh())) \
                .props("dense")
            ui.html(f'<div style="font-size:.78rem;color:var(--km-muted);margin-left:34px;'
                    f'white-space:normal">{act["requirements"]}</div>')

        cost_rows: list[dict] = []
        cost_data = act.get("cost_data")
        if act["id"] == "hire_adventurers" and "practical_magic" in STATE.k["feats"]:
            cost_data = [{"t": "rp", "q": "-1", "auto": True,
                          "text": rules.BY_ID["feat"]["practical_magic"]["name"]}]
        if cost_data:
            theme.title(t("turn.cost"), 3)
            _per_count(cost_data, lambda: cost_rows)
            cost_rows = _effect_rows(cost_data)
        elif act["cost"]:
            ui.html(t("turn.div_style_font_size", cost=act["cost"]))

        theme.sep()
        choice = {"skills": options[0], "dc": default_dc, "settlement": None}
        with ui.row().classes("items-center gap-3 flex-wrap"):
            ui.select({a: rules.BY_ID["skills"][a]["name"] for a in options},
                      value=options[0], label=t("turn.skill"),
                      on_change=lambda e: (choice.update(skills=e.value), mod_row.refresh())) \
                .props("outlined dense").classes("w-52")
            ui.number(t("turn.dc"), value=default_dc, format="%d",
                      on_change=lambda e: choice.update(dc=int(e.value or 0))) \
                .props("outlined dense").classes("w-28")
            ui.label(dc_note).style("font-size:.78rem;color:var(--km-muted)")
        if banned:
            ui.label(t("turn.quell_same_skill", skill=rules.BY_ID["skills"][banned]["name"])) \
                .style("font-size:.78rem;color:var(--km-muted)")
        # The capital's structures help everywhere; another settlement's only
        # where it has influence. When one of them would help this activity,
        # the table says where the activity is attempted.
        places = STATE.bonus_settlements(act["id"])
        if places:
            ui.select({"": t("turn.anywhere_in_kingdom"), **{s["id"]: s["name"] for s in places}},
                      value="", label=t("turn.attempted_in"),
                      on_change=lambda e: (choice.update(settlement=e.value or None), mod_row.refresh())) \
                .props("outlined dense").classes("w-64")

        @ui.refreshable
        def mod_row() -> None:
            aid = choice["skills"]
            detail = STATE.check_detail(aid, act["id"], settlement=choice["settlement"])
            mod = sum(v for _n, v in detail)
            with ui.row().classes("items-center gap-2 flex-wrap"):
                ui.html(f'<span class="km-mod">{mod:+d}</span>')
                for name, val in detail:
                    ui.html(f'<span class="km-chip" style="font-size:.7rem">{theme.esc(name)} {val:+d}</span>')
            if "buttons" in drawn:
                buttons.refresh()

        drawn: set[str] = set()

        def roll(assurance: bool = False) -> None:
            dlg.close()
            spent = _apply_rows(cost_rows, t("turn.cost_2", name=act['name']))
            if spent:
                theme.notify(t("turn.cost_paid") + "; ".join(spent), "info")
            STATE.mark_activity(act["id"])
            check = dict(choice)
            if act["id"] == "quell_unrest":
                STATE.k["feat_turns"]["quell_skill"] = {"turn": STATE.k["turn"], "skill": check["skills"]}

            def attempt(fair: bool = True) -> rules.Result:
                return sheet.roll_skill(check["skills"], check["dc"], act["name"], show=False,
                                        activity=act["id"], settlement=check["settlement"], fair=fair)

            if assurance:
                # Kingdom Assurance: no die, so nothing to reroll.
                res = STATE.assurance_result(check["skills"], check["dc"])
                STATE.record(t("sheet.vs_dc", label=f'{act["name"]} · {rules.BY_ID["skills"][check["skills"]]["name"]}',
                               label2=res.label, total=res.total, cd=check["dc"]), "check")
                theme.save_and_refresh_panels(("turn.journal", "sheet.identita"))
                theme.refresh_panels(("turn.uses",))
                _outcome_dialog(act, res, None, skill=check["skills"])
                return
            res = attempt()
            theme.refresh_panels(("turn.uses",))
            _outcome_dialog(act, res, attempt, skill=check["skills"])

        @ui.refreshable
        def buttons() -> None:
            blocked = "disable" if block or not ready["requirements"] else ""
            with ui.row().classes("gap-2 items-center"):
                ui.button(t("turn.roll_check"), on_click=lambda: roll()) \
                    .props(f'color=amber {blocked}')
                if STATE.assurance_available(choice["skills"]):
                    prof = STATE.k["proficiencies"].get(choice["skills"], "untrained")
                    value = 10 + rules.proficiency_bonus(STATE.level, prof)
                    ui.button(t("turn.assurance", name=rules.BY_ID["feat"]["kingdom_assurance"]["name"],
                                value=value), on_click=lambda: roll(assurance=True)) \
                        .props(f'outline color=amber {blocked}')
                ui.button(t("common.close"), on_click=dlg.close).props("flat")
                if not ready["requirements"]:
                    ui.label(t("turn.confirm_requirements_able_roll")) \
                        .style("font-size:.75rem;color:var(--km-muted)")

        mod_row()
        buttons()
        drawn.add("buttons")
    dlg.open()


def _outcome_dialog(act: dict, res: rules.Result, reroll=None, rerolled: bool = False,
                    share: bool = True, skill: str | None = None) -> None:
    """Outcome of the activity with the proposed effects, to confirm before applying.

    The effects wait for the table, so the reroll for 1 Fame/Infamy point
    sits here: `reroll()` rolls the check again, and the new outcome replaces
    this one (`theme.can_reroll`: once per check)."""
    text = act["outcomes"].get(res.grade, "")
    entries = (act.get("effects") or {}).get(res.grade, [])

    def name() -> str:
        title_ = rules.BY_ID["activities"][act["id"]]["name"]
        return t("theme.rerolled", title=title_) if rerolled else title_

    # The others see the roll and its outcome, read-only and in their own
    # language; the effects to apply stay with whoever rolled.
    if share:
        theme.share_roll(res, name,
                         lambda: rules.BY_ID["activities"][act["id"]]["outcomes"].get(res.grade, ""))

    @theme.requires(permissions.EDIT_KINGDOM)
    def again() -> None:
        dlg.close()
        if not STATE.spend_fame():
            # Spent meanwhile from another window: the same roll, back on
            # screen without the reroll — and not sent to the others again.
            theme.notify(t("theme.fame_none_left", fame=STATE.fame_name), "warning")
            _outcome_dialog(act, res, None, rerolled, share=False, skill=skill)
            return
        theme.record_reroll(lambda: rules.BY_ID["activities"][act["id"]]["name"], res)
        new = reroll()
        theme.save_and_refresh_panels(theme.stat_panels("fame_points", extra=("turn.journal",)))
        _outcome_dialog(act, new, reroll, rerolled=True, skill=skill)

    # Free and Fair: a failed New Leadership or Pledge of Fealty with a
    # Loyalty skill may be rerolled for 2 RP, without the feat's +2. A
    # fortune effect too, so never on top of a reroll for Fame.
    fair = (reroll is not None and not rerolled and "free_and_fair" in STATE.k["feats"]
            and act["id"] in ("new_leadership", "pledge_of_fealty")
            and skill and rules.BY_ID["skills"][skill]["ability"] == "loyalty"
            and res.grade in ("failure", "critical_failure"))

    @theme.requires(permissions.EDIT_KINGDOM)
    def fair_again() -> None:
        dlg.close()
        if STATE.k["rp"] < 2:
            theme.notify(t("turn.free_and_fair_no_rp"), "warning")
            _outcome_dialog(act, res, None, rerolled=True, share=False, skill=skill)
            return
        STATE.spend_rp(2)
        STATE.record(t("turn.free_and_fair_journal", name=act["name"], grade=res.label, total=res.total),
                     "check")
        new = reroll(fair=False)
        theme.save_and_refresh_panels(theme.stat_panels("rp", extra=("turn.journal",)))
        _outcome_dialog(act, new, reroll, rerolled=True, skill=skill)

    def reroll_button() -> None:
        if reroll is not None and theme.can_reroll(res, rerolled):
            ui.button(theme.reroll_label(), on_click=again).props("outline color=amber")
        if fair:
            ui.button(t("turn.free_and_fair_reroll", name=rules.BY_ID["feat"]["free_and_fair"]["name"]),
                      on_click=fair_again).props(f'outline color=amber {"" if STATE.k["rp"] >= 2 else "disable"}')

    with theme.dialog() as dlg, ui.card().classes("km-panel") \
            .style("min-width:520px;max-width:680px;max-height:85vh;overflow-y:auto"):
        theme.title(name(), 2)
        theme.result_block(res)
        if text:
            theme.sep()
            ui.html(f'<div style="font-size:.86rem;white-space:normal">{theme.esc(text)}</div>')
        theme.sep()
        if not entries:
            ui.label(t("turn.no_automatic_effect_adjust")) \
                .style("color:var(--km-muted);font-size:.82rem")
            quick_adjustments(compact=True)
            with ui.row().classes("gap-2 flex-wrap"):
                ui.button(t("turn.done"), on_click=dlg.close).props("color=amber")
                reroll_button()
            dlg.open()
            return

        theme.title(t("turn.effects_apply"), 3)
        ui.label(t("turn.untick_what_does_not")) \
            .style("color:var(--km-muted);font-size:.75rem")
        rows: list[dict] = []
        _per_count(entries, lambda: rows)
        rows = _effect_rows(entries, skill)

        def apply() -> None:
            dlg.close()
            done_ones = _apply_rows(rows, f"{act['name']} ({rules.grade_label(res.grade)})")
            theme.notify(t("turn.applied", list="; ".join(done_ones)) if done_ones else t("turn.no_effect_applied"),
                           "positive" if done_ones else "info")

        with ui.row().classes("gap-2 flex-wrap"):
            ui.button(t("turn.apply_effects"), on_click=apply).props("color=amber")
            ui.button(t("turn.skip"), on_click=dlg.close).props("flat")
            reroll_button()
    dlg.open()


# --------------------------------------------------------------------------
@theme.requires(permissions.EDIT_KINGDOM)
def _adjust_field(field: str, delta: int) -> None:
    k = STATE.k
    if field == "unrest":
        STATE.modify_unrest(delta)     # Anarchy reached: Fame may stave it off
    elif field == "fame_points":
        k[field] = max(0, min(STATE.max_fame, k[field] + delta))
    else:
        k[field] = max(0, k[field] + delta)
    theme.save_and_refresh_panels(theme.stat_panels(field))


@theme.requires(permissions.EDIT_KINGDOM)
def _adjust_ruin(rid: str, delta: int) -> None:
    STATE.modify_ruin(rid, delta)
    # Crossing the threshold writes in the journal.
    theme.save_and_refresh_panels(theme.stat_panels("ruins", extra=("turn.journal",)))


@theme.requires(permissions.EDIT_KINGDOM)
def _adjust_commodity(char_id: str, delta: int) -> None:
    k = STATE.k
    if delta > 0:
        STATE.add_commodity(char_id, delta)
    else:
        k["commodities"][char_id] = max(0, k["commodities"][char_id] + delta)
    theme.save_and_refresh_panels(theme.stat_panels("commodities"))


_ADJUSTABLE = ("unrest", "rp", "xp", "fame_points")


def _adjust(key) -> None:
    """A click in the adjustments block: `field|delta`, or `turn|dialog`.

    The key comes from the browser, so it is read like any other input:
    a field not in the short list, a ruin or a commodity the kingdom does not
    have, a delta that is not a number — nothing happens.
    """
    field, _sep, what = str(key).partition("|")
    if field == "turn" and what == "dialog":
        _turn_dialog()
        return
    try:
        delta = int(what)
    except ValueError:
        return
    if field == "turn":
        _move_turn(delta)
    elif field.startswith("ruin.") and field[5:] in STATE.k["ruins"]:
        _adjust_ruin(field[5:], delta)
    elif field.startswith("com.") and field[4:] in STATE.k["commodities"]:
        _adjust_commodity(field[4:], delta)
    elif field in _ADJUSTABLE:
        _adjust_field(field, delta)


@ui.refreshable
def quick_adjustments(compact: bool = False) -> None:
    """The figures with a minus and a plus each, as one element.

    Seventeen rows of four elements and two buttons were four hundred
    elements per window, redone at every change of a figure. The block is
    now a single piece of markup; the browser reports which control was
    clicked (`data-km`) and `_adjust` does the rest.
    """
    k = STATE.k
    rows = []

    def row(key: str, label: str, value, extra: str = "", step: int = 1,
            dialog: bool = False) -> None:
        number = (f'<b class="km-adj-num km-adj-link" data-km="{key}|dialog">{theme.esc(value)}</b>'
                  if dialog else f'<b class="km-adj-num">{theme.esc(value)}</b>')
        rows.append(
            f'<div class="km-adj-row"><div class="km-adj-name"><div class="n">{theme.esc(label)}</div>'
            f'<div class="x">{theme.esc(extra)}</div></div><div class="km-adj-ctl">'
            f'<i class="material-icons km-adj-btn" data-km="{key}|{-step}">remove</i>{number}'
            f'<i class="material-icons km-adj-btn plus" data-km="{key}|{step}">add</i></div></div>')

    row("turn", t("turn.kingdom_turn"), k["turn"], t("turn.click_number_type"), dialog=True)
    row("unrest", t("turn.unrest"), k["unrest"], f'{rules.unrest_penalty(k["unrest"])} status')
    row("rp", t("turn.rp"), k["rp"])
    row("xp", t("turn.xp"), k["xp"], "±10", step=10)
    row("fame_points", t("turn.fame_infamy"), k["fame_points"], f'max {STATE.max_fame}')
    for r in rules.RUINS:
        rd = k["ruins"][r["id"]]
        row(f'ruin.{r["id"]}', r["name"], f'{rd["points"]}/{rd["threshold"]}',
            t("turn.penalty_short", n=rd["penalty"]) if rd["penalty"] else "")
    for c in rules.COMMODITIES:
        row(f'com.{c["id"]}', f'{c["icon"]} {c["name"]}', k["commodities"][c["id"]],
            f'max {STATE.storage(c["id"])}')
    ui.html("".join(rows)).classes("km-adj w-full" + ("" if compact else " km-panel")) \
        .on("click", lambda e: _adjust(e.args), js_handler=theme.PICK)


# --------------------------------------------------------------------------
def _simple_check(cd: int, title, on_success="", on_failure="") -> None:
    """A flat check: a d20 against `cd`, on screen for everybody. The texts
    may be functions, so each window reads them in its own language."""
    tot, rolls = rules.roll(1, 20)
    ok = tot >= cd
    STATE.record(t("turn.d20_vs_dc", title=theme._text(title), tot=tot, cd=cd, v=rules.grade_label('success' if ok else 'failure')), "check")
    theme.save_and_refresh()
    theme.show_dice(title, rolls, 20, on_success if ok else on_failure, dc=cd)


# --------------------------------------------------------------------------
def overcrowded_chip(over: list[dict]) -> str:
    """The chip of the overcrowded settlements, with their Residential lots
    out of the built blocks, in the window's language. The names are typed
    by the players and go into HTML: escaped."""
    details = ", ".join(
        t("turn.residential_of_built", name=theme.esc(i["name"]),
          residential=lot["residential_count"], built=lot["built_blocks"])
        for i in over for lot in [STATE.lot_detail(i)])
    return f'<div class="km-chip km-fc">{t("turn.overcrowded", details=details)}</div>'


def _upkeep_step(step: dict) -> None:
    k = STATE.k
    if step["id"] == "unrest":
        with ui.row().classes("gap-2 flex-wrap"):
            over = STATE.overcrowded_settlements()
            n_over = len(over)
            ui.button(t("turn.apply_from_overcrowded_settlements", n_over=n_over),
                      on_click=lambda: _add_unrest(n_over)) \
                .props(f'dense outline color=amber {"" if n_over else "disable"}')
            if over:
                ui.html(overcrowded_chip(over))
            if k["unrest"] >= 10:
                ui.button(t("turn.unrest_10_roll_1d10"),
                          on_click=_ruin_from_unrest).props("dense color=red")
                ui.button(t("turn.flat_check_dc_11"),
                          on_click=lambda: _simple_check(
                              11, lambda: t("turn.loss_hex"),
                              lambda: t("turn.kingdom_loses_no_hex"),
                              lambda: t("turn.kingdom_loses_hex_pcs"))).props("dense outline color=red")
            if STATE.in_anarchy:
                ui.html(t("turn.div_class_km_chip"))

    elif step["id"] == "resources":
        with ui.row().classes("gap-2 flex-wrap items-center"):
            ui.button(t("turn.roll_d_resource_dice", resource_dice_count=STATE.resource_dice_count, resource_die=STATE.resource_die),
                      on_click=_roll_resources).props("dense color=amber")
            ui.button(t("turn.collect_from_work_sites"), on_click=_collect_sites).props("dense outline color=amber")
            ui.label(t("turn.current_rp", rp=k['rp'])).style("color:var(--km-muted)")

    elif step["id"] == "consumption":
        cons = STATE.consumption()
        with ui.row().classes("gap-2 flex-wrap items-center"):
            ui.label(t("turn.turn_consumption_settlements_armies", total=cons["total"], settlements=cons["settlements"], armies=cons["armies"], farms=cons["farms"], events=cons["events"])
                     + (" · " + t("common.farmland_outside", n=cons["farms_outside"]) if cons["farms_outside"] else "")) \
                .style("color:var(--km-muted)")
            due = _consumption_due()
            if cons["total"] > 0:
                ui.html(f'<span class="km-chip {"km-s" if not due else "km-f"}">'
                        f'{theme.esc(t("turn.consumption_due", due=due) if due else t("turn.consumption_settled"))}</span>')
            ui.button(t("turn.pay_food"), on_click=lambda: _pay_consumption("food")).props("dense color=amber")
            ui.button(t("turn.pay_5_rp_per"), on_click=lambda: _pay_consumption("rp")).props("dense outline color=amber")
            ui.button(t("turn.increase_unrest_1d4"), on_click=lambda: _pay_consumption("unrest")) \
                .props("dense outline color=red")

    elif step["id"] == "roles":
        ui.label(t("turn.assign_change_leaders_from")).style("color:var(--km-muted)")
        absent = [rules.BY_ID["role"][rid]["name"] for rid in k["roles"] if STATE.role_vacant(rid)]
        if absent:
            ui.html(t("turn.div_class_km_chip_2", join=", ".join(absent)))
        if STATE.role_vacant("ruler"):
            # The Ruler's vacancy: 1d4 Unrest at the start of every turn.
            ui.button(t("turn.ruler_vacant_unrest"), on_click=_ruler_vacancy) \
                .props(f'dense outline color=red {"disable" if STATE.feat_used("ruler_vacancy") else ""}')


@theme.requires(permissions.EDIT_KINGDOM)
def _ruler_vacancy() -> None:
    if STATE.feat_used("ruler_vacancy") or not STATE.role_vacant("ruler"):
        return
    STATE.use_feat("ruler_vacancy")         # once a turn, like the rule
    tot, rolls = rules.roll(1, 4)
    STATE.modify_unrest(tot, t("turn.ruler_vacant"))
    theme.save_and_refresh()
    theme.show_dice(lambda: t("turn.ruler_vacant"), rolls, 4,
                    lambda: t("turn.ruler_vacant_outcome", tot=tot))


@theme.requires(permissions.EDIT_KINGDOM)
def _add_unrest(n: int) -> None:
    STATE.modify_unrest(n)
    STATE.record(t("turn.unrest_from_overcrowded_settlements", n=n), "unrest")
    theme.save_and_refresh()
    quick_adjustments.refresh()
    sheet.identity_block.refresh()


@theme.requires(permissions.EDIT_KINGDOM)
def _ruin_from_unrest() -> None:
    tot, rolls = rules.roll(1, 10)
    STATE.record(t("turn.unrest_10_ruin_points", tot=tot), "ruin")
    theme.save_and_refresh()
    theme.show_dice(lambda: t("turn.unrest_ruin_title"), rolls, 10,
                    lambda: t("turn.1d10_ruin_points_distribute", tot=tot))


@theme.requires(permissions.EDIT_KINGDOM)
def _roll_resources() -> None:
    n, faces, tot, rolls = STATE.roll_resource_dice()
    STATE.record(t("turn.resource_dice_d", n=n, faces=faces, tot=tot), "resources", str(rolls))
    theme.save_and_refresh()
    sheet.resources_block.refresh()
    quick_adjustments.refresh()
    theme.show_dice(lambda: t("theme.resource_dice"), rolls, faces,
                    lambda: t("theme.resource_dice_outcome", tot=tot))


@theme.requires(permissions.EDIT_KINGDOM)
def _collect_sites() -> None:
    gains: dict[str, int] = {}
    lost_ones: dict[str, int] = {}
    for h in STATE.claimed_hexes():
        sl = h.get("work_site")
        if not sl:
            continue
        q = 2 if sl.get("doubled") else 1
        p = STATE.add_commodity(sl["commodity"], q)
        gains[sl["commodity"]] = gains.get(sl["commodity"], 0) + q
        if p:
            lost_ones[sl["commodity"]] = lost_ones.get(sl["commodity"], 0) + p
    if not gains:
        theme.notify(t("turn.no_active_work_site"), "info")
        return
    text = ", ".join(f'{rules.BY_ID["commodity"][p]["name"]} +{n}' for p, n in gains.items())
    if lost_ones:
        text += t("turn.lost_full_storage") + ", ".join(
            f'{rules.BY_ID["commodity"][p]["name"]} {n}' for p, n in lost_ones.items()) + ")"
    STATE.record(t("turn.collected_from_work_sites") + text, "resources")
    theme.save_and_refresh()
    sheet.resources_block.refresh()
    quick_adjustments.refresh()
    theme.notify(text)


def _consumption_due() -> int:
    """The Consumption still to pay this turn: the turn's total, less the
    Food already paid toward it; 0 once it is settled (in full, in RP for the
    rest, or with the 1d4 Unrest of not paying)."""
    k = STATE.k
    paid = k["consumption_paid"] if k["consumption_paid"].get("turn") == k["turn"] else {}
    if paid.get("settled"):
        return 0
    return max(0, STATE.consumption()["total"] - paid.get("food", 0))


def _consumption_paid(food: int = 0, settled: bool = False) -> None:
    k = STATE.k
    if k["consumption_paid"].get("turn") != k["turn"]:
        k["consumption_paid"] = {"turn": k["turn"], "food": 0, "settled": False}
    k["consumption_paid"]["food"] += food
    k["consumption_paid"]["settled"] = k["consumption_paid"]["settled"] or settled


@theme.requires(permissions.EDIT_KINGDOM)
def _pay_consumption(mode: str) -> None:
    """Pays the turn's Consumption. Food first, as much as there is; what
    stays unpaid costs 5 RP per point, or else 1d4 Unrest."""
    k = STATE.k
    if STATE.consumption()["total"] <= 0:
        theme.notify(t("turn.consumption_0_nothing_pay"), "info")
        return
    due = _consumption_due()
    if not due:
        theme.notify(t("turn.consumption_settled"), "info")
        return
    if mode == "food":
        paid = min(due, k["commodities"]["food"])
        if not paid:
            theme.notify(t("turn.not_enough_food_pay", food=0, cons=due), "warning")
            return
        k["commodities"]["food"] -= paid
        _consumption_paid(food=paid, settled=paid == due)
        STATE.record(t("turn.paid_consumption_food", cons=paid), "consumption")
        if paid < due:
            theme.notify(t("turn.not_enough_food_pay", food=paid, cons=due), "warning")
    elif mode == "rp":
        cost = due * 5
        if k["rp"] < cost:
            theme.notify(t("turn.consumption_rp_short", cost=cost, rp=k["rp"]), "warning")
            return
        STATE.spend_rp(cost)
        _consumption_paid(settled=True)
        STATE.record(t("turn.paid_consumption_rp", cost=cost), "consumption")
    else:
        _consumption_paid(settled=True)
        tot, rolls = rules.roll(1, 4)
        STATE.modify_unrest(tot)
        STATE.record(t("turn.consumption_not_paid_unrest", tot=tot), "consumption")
    theme.save_and_refresh()
    sheet.resources_block.refresh()
    sheet.identity_block.refresh()
    quick_adjustments.refresh()
    if mode not in ("food", "rp"):
        # The 1d4 used to go only into the journal: not even whoever rolled saw it.
        theme.show_dice(lambda: t("turn.unpaid_consumption_title"), rolls, 4,
                        lambda: t("turn.consumption_not_paid_unrest", tot=tot))


# --------------------------------------------------------------------------
def _event_step(step: dict) -> None:
    k = STATE.k
    if step["id"] == "control":
        with ui.row().classes("gap-2 items-center flex-wrap"):
            ui.button(t("turn.check_random_event_dc", event_dc=k['event_dc']),
                      on_click=_check_event).props("dense color=amber")
            ui.label(t("turn.current_dc_back_16", event_dc=k['event_dc'])).style("color:var(--km-muted);font-size:.8rem")
    elif step["id"] == "xp":
        with ui.row().classes("gap-2 items-center flex-wrap"):
            ui.button(t("turn.convert_unspent_rp_into"), on_click=_convert_rp) \
                .props("dense color=amber")
            ui.button(t("turn.30_xp_random_event"), on_click=lambda: _xp(30)).props("dense outline color=amber")
            ui.label(t("turn.total_xp", xp=k['xp'])).style("color:var(--km-muted)")
    elif step["id"] == "level":
        ready = k["xp"] >= 1000 and k["level"] < k["party_level"]
        ui.button(t("turn.raise_kingdom_level_1000"), on_click=_level_up) \
            .props(f'dense color=amber {"" if ready else "disable"}')
        pending = _pending_advancements()
        if pending:
            ui.button(t("turn.advancement_pending", n=len(pending)), on_click=_advancement_dialog) \
                .props("dense outline color=amber")
        if k["xp"] >= 1000 and k["level"] >= k["party_level"]:
            ui.label(t("turn.kingdom_has_xp_but")) \
                .style("color:var(--km-muted)")
    elif step["id"] == "resolution":
        ui.label(t("turn.resolve_events_here_use", control_dc=STATE.control_dc)) \
            .style("color:var(--km-muted)")
        ui.button(t("turn.close_turn"), on_click=_new_turn).props("dense color=amber")


@theme.requires(permissions.EDIT_KINGDOM)
def _check_event() -> None:
    k = STATE.k
    tot, rolls = rules.roll(1, 20)
    dc = k["event_dc"]
    ok = tot >= dc
    if ok:
        k["event_dc"] = 16
        STATE.record(t("turn.random_kingdom_event_d20", tot=tot), "event")
    else:
        k["event_dc"] = max(1, k["event_dc"] - 5)
        STATE.record(t("turn.no_event_d20_next", tot=tot, event_dc=k['event_dc']), "event")
    theme.save_and_refresh()
    # The whole table waits on this one: everybody sees whether an event comes.
    next_dc = k["event_dc"]
    theme.show_dice(lambda: t("turn.check_random_events"), rolls, 20,
                    (lambda: t("turn.gm_rolls_events_table")) if ok
                    else (lambda: t("turn.next_turn_s_dc", event_dc=next_dc)),
                    dc=dc,
                    verdict=lambda: t("turn.div_class_km_s") if ok else t("turn.div_class_km_f"))


@theme.requires(permissions.EDIT_KINGDOM)
def _xp(n: int) -> None:
    STATE.k["xp"] += n
    STATE.record(t("turn.kingdom_xp", n=n), "xp")
    theme.save_and_refresh()
    sheet.identity_block.refresh()
    quick_adjustments.refresh()


@theme.requires(permissions.EDIT_KINGDOM)
def _convert_rp() -> None:
    k = STATE.k
    gain = min(120, k["rp"])
    k["xp"] += gain
    STATE.record(t("turn.unspent_rp_converted_into", gain=gain), "xp")
    k["rp"] = 0
    theme.save_and_refresh()
    sheet.identity_block.refresh()
    sheet.resources_block.refresh()
    quick_adjustments.refresh()
    theme.notify(t("turn.xp_from_unspent_rp", gain=gain))


@theme.requires(permissions.EDIT_KINGDOM)
def _level_up() -> None:
    k = STATE.k
    if k["xp"] < 1000 or k["level"] >= k["party_level"]:
        return
    k["xp"] -= 1000
    k["level"] += 1
    capabilities = rules.level_entry(k["level"])["capabilities"]
    STATE.record(t("turn.kingdom_rises_level", level=k['level'], join=', '.join(capabilities)), "kingdom")
    theme.save_and_refresh()
    sheet.identity_block.refresh()
    sheet.skills_block.refresh()
    sheet.feats_block.refresh()
    theme.notify(t("turn.level_new_capabilities", level=k['level'], join=', '.join(capabilities)))
    if _pending_advancements():
        _advancement_dialog()


def _pending_advancements() -> list[tuple[int, str]]:
    """The level-up choices not made yet, (level, what), up to the kingdom's
    level: ability boosts, a skill increase, Ruin Resistance."""
    return [(lv, what) for lv in range(2, STATE.level + 1) for what in STATE.advancement(lv)
            if not STATE.advancement_done(lv, what)]


def _advancement_dialog() -> None:
    """The level-up choices, each applied once: the ability boosts (two
    different abilities), the skill increase, the Ruin Resistance."""
    pending = _pending_advancements()
    abilities = {a["id"]: a["name"] for a in rules.ABILITIES}
    ruins = {r["id"]: r["name"] for r in rules.RUINS}
    with theme.dialog() as dlg, ui.card().classes("km-panel").style("min-width:420px;max-width:600px"):
        theme.title(t("turn.advancement_title"), 2)
        if not pending:
            ui.label(t("turn.advancement_none")).style("color:var(--km-muted)")
        for level, what in pending:
            theme.sep()
            ui.label(t(f"turn.advancement_{what}", level=level)).classes("km-title")
            with ui.row().classes("items-center gap-2 flex-wrap"):
                if what == "boosts":
                    first = ui.select(abilities, value=None, label=t("turn.advancement_first")) \
                        .props("outlined dense").classes("w-40")
                    second = ui.select(abilities, value=None, label=t("turn.advancement_second")) \
                        .props("outlined dense").classes("w-40")
                    ui.button(t("turn.advancement_apply"), on_click=lambda lv=level, a=first, b=second: _advance(
                        dlg, STATE.boost_abilities(lv, a.value, b.value))).props("dense color=amber")
                elif what == "skill":
                    options = {sid: f'{rules.BY_ID["skills"][sid]["name"]} → {rules.BY_ID["proficiency"][rank]["name"]}'
                               for sid, rank in STATE.skill_increase_options(level).items()}
                    skill = ui.select(options, value=None, label=t("turn.skill")) \
                        .props("outlined dense").classes("w-64")
                    ui.button(t("turn.advancement_apply"), on_click=lambda lv=level, x=skill: _advance(
                        dlg, STATE.increase_skill(lv, x.value))).props("dense color=amber")
                else:
                    ruin = ui.select(ruins, value=None, label=t("turn.advancement_ruin_pick")) \
                        .props("outlined dense").classes("w-48")
                    ui.button(t("turn.advancement_apply"), on_click=lambda lv=level, x=ruin: _advance(
                        dlg, STATE.ruin_resistance(lv, x.value))).props("dense color=amber")
        if STATE.level % 2 == 0:
            ui.label(t("turn.advancement_feat")).style("font-size:.8rem;color:var(--km-muted)")
        ui.button(t("common.close"), on_click=dlg.close).props("flat")
    dlg.open()


@theme.requires(permissions.EDIT_KINGDOM)
def _advance(dlg, done: bool) -> None:
    if not done:
        theme.notify(t("turn.advancement_invalid"), "warning")
        return
    STATE.record(t("turn.advancement_done"), "kingdom")
    theme.save_and_refresh()
    dlg.close()
    if _pending_advancements():
        _advancement_dialog()


# --------------------------------------------------------------------------
# Correcting the turn number. «New turn» only knows how to go forward, and
# rightly so: it is the gesture of the game. But after a test, or after
# pressing the button once too often, one must be able to go back without
# putting one's hands in the save.
@theme.requires(permissions.EDIT_KINGDOM)
def _set_turn(new: int, reason: str = "") -> None:
    """Writes the turn number. Corrects the counter, does not rewind the game.

    We touch nothing else on purpose: RP spent, activities attempted and Fame
    stay as they are. Moving the number back is a bookkeeping correction, not
    an undo of what happened at the table, and what needs fixing is fixed
    with the other quick adjustments.
    """
    k = STATE.k
    before = int(k["turn"])
    new = max(0, int(new))
    if new == before:
        return
    k["turn"] = new
    # Temporary modifiers expire at a given turn: going back they would become
    # valid again, and forward they would vanish silently. We say so.
    returned = [m["name"] for m in k["modifiers"]
               if m.get("expiry") is not None and before > m["expiry"] >= new]
    STATE.record(t("turn.kingdom_turn_corrected_from", before=before, new=new), "turn", reason)
    theme.save_and_refresh()
    _turn_column.refresh()
    quick_adjustments.refresh()
    sheet.identity_block.refresh()
    if returned:
        theme.notify(t("turn.temporary_modifiers_become_valid")
                       + ", ".join(sorted(set(returned))), "warning")


@theme.requires(permissions.EDIT_KINGDOM)
def _move_turn(delta: int) -> None:
    _set_turn(STATE.k["turn"] + delta)


def _turn_dialog() -> None:
    """Typing the number directly, to jump there from afar."""
    with theme.dialog() as dlg, ui.card().classes("km-panel").style("min-width:360px"):
        theme.title(t("turn.kingdom_turn_number"), 2)
        ui.label(t("turn.only_counter_changes_does")) \
            .style("color:var(--km-muted);font-size:.8rem")
        field = ui.number(t("turn.turn"), value=STATE.k["turn"], min=0, step=1, format="%d") \
            .props("outlined dense autofocus").classes("w-32")

        def save() -> None:
            _set_turn(int(field.value or 0), t("turn.corrected_by_hand"))
            dlg.close()

        with ui.row().classes("justify-end w-full"):
            ui.button(t("common.cancel"), on_click=dlg.close).props("flat")
            ui.button(t("common.save"), on_click=save).props("color=amber")
    dlg.open()


def advance_turn(reason: str = "") -> None:
    """Brings the kingdom to the next turn, without touching the interface.

    Kept separate from the button because the clock calls it too, when the
    month ends: from a background timer there is no window to send a
    notification to, and trying would be an error. For the same reason it
    checks no permission: a timer has no account, and the check refused it
    in silence, so the month ended and the turn stayed where it was. The
    button's handler, `_new_turn`, checks it.
    """
    k = STATE.k
    k["turn"] += 1
    # Unspent points are lost; +1 at the start of the turn, plus those owed
    # from the last one (a Masterpiece's critical success).
    k["fame_points"] = min(STATE.max_fame, 1 + k["fame_next_turn"])
    k["fame_next_turn"] = 0
    STATE.new_turn_feats()
    k["rp_spent_turn"] = 0
    k["turn_activities"] = {}
    STATE.clean_modifiers()
    STATE.record(t("turn.start_kingdom_turn", turn=k['turn']), "turn", reason)


@theme.requires(permissions.EDIT_KINGDOM)
def _new_turn() -> None:
    advance_turn()
    theme.save_and_refresh()
    theme.notify(t("turn.kingdom_turn_started_1", turn=STATE.k['turn'], v=t("turn.fame") if STATE.k["reputation"] == "fame" else t("turn.infamy")))
    _turn_column.refresh()
    sheet.identity_block.refresh()


# --------------------------------------------------------------------------
def _activity_card(act: dict) -> None:
    """One element per card, clickable as a whole.

    A card, a row, a column of labels, a button and a tooltip were eight
    elements, forty-nine times per window at every redraw of the column. The
    card is now a single block of markup with the dice drawn in it, and a
    click anywhere on it does what the button did; the requirements are the
    browser's own tooltip.
    """
    cd, note = _activity_dc(act)
    reference_ = act.get("reference")
    block = "" if reference_ else STATE.activities_block(act)
    icon = REFERENCES[reference_][0] if reference_ else "casino"
    skill = ", ".join(rules.BY_ID["skills"][a]["name"] for a in act["skills"] if a != "*")         or t("turn.any_skill")
    lines = [f'<b class="km-title">{theme.esc(act["name"])}</b>',
             f'<div style="font-size:.72rem;color:var(--km-muted)">{theme.esc(skill)}</div>',
             f'<div style="font-size:.7rem;color:var(--km-gold-dim)">{theme.esc(note)}</div>']
    if act["cost"]:
        lines.append('<div style="font-size:.7rem;color:var(--km-muted);white-space:nowrap;'
                     'overflow:hidden;text-overflow:ellipsis">'
                     f'{theme.esc(t("turn.cost_3", cost=act["cost"]))}</div>')
    if block:
        lines.append(f'<div class="km-fc" style="font-size:.7rem;white-space:normal">{block}</div>')
    title = f' title="{theme.esc(act["requirements"])}"' if act["requirements"] else ""
    ui.html(f'<div{title} style="display:flex;align-items:center;gap:8px;width:100%">'
            f'<div style="flex:1;min-width:0">{"".join(lines)}</div>'
            f'<i class="material-icons" style="color:#ffc107;font-size:22px;flex:none">{icon}</i></div>')         .classes("km-panel km-activity")         .style("padding:8px 12px;min-width:260px;flex:1;cursor:pointer" + (";opacity:.55" if block else ""))         .on("click", lambda _e=None, a=act: run_activity(a))


# --------------------------------------------------------------------------
@ui.refreshable
def _step_body(phase_id: str, step_id: str) -> None:
    """The live part of an upkeep or event step — the figures it reads, the
    buttons it offers — as a panel of its own: a change of a figure redoes
    the steps, not the column of activity cards around them."""
    phase = next(f for f in rules.TURN_PHASES if f["id"] == phase_id)
    step = next(s for s in phase["steps"] if s["id"] == step_id)
    if phase_id == "upkeep":
        _upkeep_step(step)
    else:
        _event_step(step)


@ui.refreshable
def _uses_chip(phase_id: str, step_id: str) -> None:
    """How many times a step was used this turn: a panel of its own, so an
    activity marks its use without redoing the whole column."""
    max_ = STATE.step_limit(phase_id, step_id)
    if max_ is None:
        return
    used_ones = STATE.step_uses(phase_id, step_id)
    exhausted = used_ones >= max_
    ui.html(t("turn.span_class_km_chip", v="km-fc" if exhausted else "", used_ones=used_ones, max=max_))


def turn_panel() -> None:
    """The tab: the turn column on the left, adjustments and journal on the
    right. Three panels, not one inside another: redoing the column does not
    rebuild the journal, nor the other way round."""
    with ui.row().classes("w-full items-start gap-4 no-wrap km-split"):
        with ui.column().classes("gap-3").style("flex:1;min-width:0"):
            _turn_column()
        with ui.column().classes("gap-3").style("width:400px;min-width:340px"):
            with ui.card().classes("km-panel w-full"):
                theme.title(t("turn.quick_adjustments"), 2)
                quick_adjustments()
            with ui.card().classes("km-panel w-full km-scroll"):
                theme.title(t("turn.log"), 2)
                _journal()


@ui.refreshable
def _turn_column() -> None:
    k = STATE.k
    with ui.card().classes("km-panel w-full"):
        with ui.row().classes("items-center gap-3 flex-wrap"):
            theme.title(t("turn.kingdom_turn_2", turn=k['turn']), 1)
            ui.element("div").style("flex:1")
            ui.button(t("turn.new_turn"), on_click=_new_turn).props("dense color=amber")
            # The button above only knows how to go forward: if you
            # pressed it once too often, it is corrected from here.
            ui.button(icon="edit", on_click=_turn_dialog)                         .props("dense flat round size=sm color=grey")                         .tooltip(t("turn.correct_turn_number"))
        ui.label(t("turn.start_every_turn_you", v=t("turn.fame") if k["reputation"] == "fame" else t("turn.infamy"))) \
            .style("font-size:.8rem;color:var(--km-muted)")

    journeys_in_progress()

    for phase in rules.TURN_PHASES:
        with ui.expansion(phase["name"], value=(phase["id"] in ("upkeep", "activity"))) \
                .classes("km-panel w-full"):
            for step in phase["steps"]:
                with ui.card().classes("km-panel w-full").style("padding:10px 14px"):
                    ui.html(f'<b class="km-title">{theme.esc(step["name"])}</b>')
                    ui.label(step["desc"]).style("font-size:.82rem;color:var(--km-muted)")
                    if phase["id"] in ("upkeep", "event"):
                        _step_body(phase["id"], step["id"])

                    atts = rules.activities_for_step(phase["id"], step["id"])
                    if atts:
                        max_ = STATE.step_limit(phase["id"], step["id"])
                        if max_ is not None:
                            _uses_chip(phase["id"], step["id"])
                        if phase["id"] == "activity" and step["id"] == "leadership":
                            ui.label(t("turn.every_pc_leader_may", max_leadership_activities=STATE.max_leadership_activities())) \
                                .style("font-size:.78rem;color:var(--km-gold-dim)")
                        if phase["id"] == "activity" and step["id"] == "region":
                            ui.label(t("turn.claim_hex_max_times", claims_per_turn=STATE.claims_per_turn())) \
                                .style("font-size:.78rem;color:var(--km-gold-dim)")
                        if phase["id"] == "activity" and step["id"] == "civic":
                            ui.label(t("turn.build_structure_performed_from")) \
                                .style("font-size:.78rem;color:var(--km-gold-dim)")
                        # The whole width of the step's panel, said out loud: the
                        # card around it lays its children out at their own
                        # width, and this row took the width of its texts —
                        # one card per line in English, wider than the panel
                        # in Italian, with the cards running out of it.
                        with ui.element("div").style(
                                "display:flex;flex-wrap:wrap;gap:8px;margin-top:6px;"
                                "width:100%;min-width:0"):
                            for act in atts:
                                _activity_card(act)


@ui.refreshable
def _journal() -> None:
    """The last eighty lines, as one block of markup.

    A row, a chip and a column per line made seven hundred elements, rebuilt
    in every window at every roll; nothing in a line is clickable, so the
    whole list is one element now.
    """
    rows = []
    for entry in STATE.journal(80):
        detail = (f'<div style="font-size:.7rem;color:var(--km-muted)">{theme.esc(entry["detail"])}</div>'
                  if entry.get("detail") else "")
        rows.append('<div style="display:flex;align-items:flex-start;gap:8px;margin-bottom:6px">'
                    f'<span style="color:var(--km-muted);font-size:.7rem;min-width:56px;flex:none">'
                    f'T{int(entry["turn"])} {theme.esc(str(entry["logged_at"])[-5:])}</span>'
                    f'<div style="min-width:0"><div style="font-size:.8rem">{theme.esc(entry["text"])}</div>'
                    f'{detail}</div></div>')
    ui.html("".join(rows)).classes("w-full")


# --------------------------------------------------------------------------
@ui.refreshable
def journeys_in_progress() -> None:
    """The journeys queued from the Map tab, waiting to be resolved.

    They remain proposals until someone confirms them: resolving a journey
    moves the markers, and it is the players who say when it really happened.
    """
    journeys = STATE.archive.list_journeys(STATE.campaign, "in_progress")
    if not journeys:
        return
    characters = {p["id"]: p for p in STATE.characters()}

    with ui.card().classes("km-panel w-full"):
        theme.title(t("turn.journeys_under_way", len=len(journeys)), 3)
        ui.label(t("turn.planned_map_resolve_them")) \
            .style("font-size:.78rem;color:var(--km-muted)")
        for v in journeys:
            names = ", ".join(characters[i]["name"] for i in v["characters"]
                             if i in characters) or "—"
            with ui.row().classes("items-center gap-2 w-full no-wrap flex-wrap"):
                ui.html(f'<span class="km-chip" style="font-size:.66rem">'
                        f'{theme.esc(v["departure"])} → {theme.esc(v["arrival"])}</span>')
                ui.label(names).style("font-size:.8rem;flex:1;min-width:120px")
                ui.html(t("turn.span_class_km_chip_2", activity_cost=v["activity_cost"], days=v["days"], v=t("turn.forced_march_suffix") if v["forced_march"] else ""))
                ui.label(t("turn.since_turn", turn_created=v["turn_created"])) \
                    .style("font-size:.7rem;color:var(--km-muted)")
                ui.button(t("turn.resolve"), on_click=lambda _=None, x=v: _resolve_journey(x)) \
                    .props("dense flat size=sm color=amber") \
                    .tooltip(t("turn.moves_markers_arrival_hex"))
                ui.button(icon="close", on_click=lambda _=None, x=v: _cancel_journey(x)) \
                    .props("dense flat round size=sm color=grey") \
                    .tooltip(t("turn.cancels_journey_nobody_moves"))


def _travellers(v: dict) -> list[dict]:
    outside = []
    for char_id in v["characters"]:
        char = STATE.archive.character(char_id)
        if char is not None:
            outside.append(char)
    return outside


def _can_resolve(v: dict) -> bool:
    return hexmap._can_move(theme.user(), _travellers(v))


@theme.requires(permissions.EDIT_KINGDOM)
def _resolve_journey(v: dict) -> None:
    if not _can_resolve(v):
        theme.notify(t("turn.you_can_only_resolve"),
                       "negative")
        return
    col, row = (int(n) for n in v["arrival"].split(","))
    # The saved path says where one enters the last hex from, and there,
    # where a river cuts it, decides which bank the party stops on.
    course = v.get("path") or []
    coming_from = tuple(course[-2]) if len(course) > 1 else None
    # And if the journey had aimed at **a piece** of that hex, one stops
    # there: the point was chosen when the journey left, and crossing the
    # river on arrival was already in the count of days.
    hexmap.move_characters(list(v["characters"]), (col, row), coming_from,
                            stable_id=v.get("stable_id"),
                            where=daily.final_spot(v))
    STATE.archive.update_journey(v["id"], status="completed",
                                    turn_resolved=STATE.k["turn"])
    names = ", ".join(p["name"] for p in _travellers(v)) or t("turn.party")
    STATE.record(t("turn.journey_completed_days", names=names, arrival=v['arrival'], days=v['days']), "map")
    theme.save_and_refresh()
    journeys_in_progress.refresh()
    theme.refresh_panels(("hexmap.map", "hexmap.travel", "turn.journeys",
                             "party.characters"))


@theme.requires(permissions.EDIT_KINGDOM)
def _cancel_journey(v: dict) -> None:
    if not _can_resolve(v):
        theme.notify(t("turn.you_can_only_cancel"),
                       "negative")
        return
    STATE.archive.update_journey(v["id"], status="cancelled",
                                    turn_resolved=STATE.k["turn"])
    STATE.record(t("turn.journey_cancelled", arrival=v['arrival']), "map")
    theme.save_and_refresh()
    journeys_in_progress.refresh()
    theme.refresh_panels(("turn.journeys",))


# --------------------------------------------------------------------------
theme.register_refresh("turn.journeys", journeys_in_progress)
theme.register_refresh("turn.panel", _turn_column)
theme.register_refresh("turn.uses", _uses_chip)
theme.register_refresh("turn.steps", _step_body)
theme.register_refresh("turn.adjustments", quick_adjustments, depends=lambda: [
    [STATE.k[f] for f in ("turn", "unrest", "rp", "xp", "fame_points")],
    STATE.max_fame, STATE.k["ruins"], STATE.k["commodities"],
    {c["id"]: STATE.storage(c["id"]) for c in rules.COMMODITIES}])
theme.register_refresh("turn.journal", _journal)
