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


def _effect_rows(entries: list[dict]) -> list[dict]:
    """Draws the entries as tickable, editable rows; returns their state."""
    rows: list[dict] = []
    for v in entries:
        if v["t"] == "note":
            ui.html(f'<div style="font-size:.78rem;color:var(--km-muted);'
                    f'border-left:2px solid var(--km-line);padding-left:8px">{v["text"]}</div>')
            continue
        value, explain = ((v["v"], "") if v["t"] == "mod"
                          else rules.signed_value(v.get("q", "0")))
        row = {"entry": v, "active": bool(v.get("auto", True)),
                "valore": value, "target": None}
        with ui.row().classes("items-center gap-2 w-full no-wrap"):
            ui.checkbox(value=row["active"],
                        on_change=lambda e, r=row: r.update(active=e.value)).props("dense")
            ui.label(rules.entry_label(v, value)).style("font-size:.82rem;flex:1;min-width:0")
            if v["t"] != "mod":
                ui.number(value=value, format="%d",
                          on_change=lambda e, r=row: r.update(value=int(e.value or 0))) \
                    .props("outlined dense").classes("w-20")
            tgt = rules.entry_target(v)
            if tgt:
                listing = rules.RUINS if tgt == "ruin" else rules.COMMODITIES
                row["target"] = listing[0]["id"]
                ui.select({x["id"]: x["name"] for x in listing}, value=row["target"],
                          on_change=lambda e, r=row: r.update(target=e.value)) \
                    .props("outlined dense").classes("w-32")
        if explain or v.get("text"):
            ui.html(f'<div style="font-size:.7rem;color:var(--km-gold-dim);margin:-4px 0 2px 34px">'
                    f'{" · ".join(x for x in (explain, v.get("text")) if x)}</div>')
        rows.append(row)
    return rows


@theme.requires(permissions.EDIT_KINGDOM)
def _apply_rows(rows: list[dict], title: str) -> list[str]:
    done_ones = [d for r in rows if r["active"]
             for d in [STATE.apply_effect(r["entry"], r["valore"], r["target"])] if d]
    if done_ones:
        STATE.record(f"{title}: " + "; ".join(done_ones), "activities")
    theme.save_and_refresh()
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
        if act.get("cost_data"):
            theme.title(t("turn.cost"), 3)
            cost_rows = _effect_rows(act["cost_data"])
        elif act["cost"]:
            ui.html(t("turn.div_style_font_size", cost=act["cost"]))

        theme.sep()
        choice = {"skills": options[0], "dc": default_dc}
        with ui.row().classes("items-center gap-3 flex-wrap"):
            ui.select({a: rules.BY_ID["skills"][a]["name"] for a in options},
                      value=options[0], label=t("turn.skill"),
                      on_change=lambda e: (choice.update(skills=e.value), mod_row.refresh())) \
                .props("outlined dense").classes("w-52")
            ui.number(t("turn.dc"), value=default_dc, format="%d",
                      on_change=lambda e: choice.update(cd=int(e.value or 0))) \
                .props("outlined dense").classes("w-28")
            ui.label(dc_note).style("font-size:.78rem;color:var(--km-muted)")

        @ui.refreshable
        def mod_row() -> None:
            aid = choice["skills"]
            detail = STATE.skill_detail(aid)
            mod = sum(v for _n, v in detail)
            with ui.row().classes("items-center gap-2 flex-wrap"):
                ui.html(f'<span class="km-mod">{mod:+d}</span>')
                for name, val in detail:
                    ui.html(f'<span class="km-chip" style="font-size:.7rem">{theme.esc(name)} {val:+d}</span>')

        mod_row()

        def roll() -> None:
            dlg.close()
            spent = _apply_rows(cost_rows, t("turn.cost_2", name=act['name']))
            if spent:
                theme.notify(t("turn.cost_paid") + "; ".join(spent), "info")
            STATE.mark_activity(act["id"])
            res = sheet.roll_skill(choice["skills"], choice["dc"], act["name"], show=False)
            _outcome_dialog(act, res)

        @ui.refreshable
        def buttons() -> None:
            with ui.row().classes("gap-2 items-center"):
                ui.button(t("turn.roll_check"), on_click=roll) \
                    .props(f'color=amber {"disable" if block or not ready["requirements"] else ""}')
                ui.button(t("common.close"), on_click=dlg.close).props("flat")
                if not ready["requirements"]:
                    ui.label(t("turn.confirm_requirements_able_roll")) \
                        .style("font-size:.75rem;color:var(--km-muted)")

        buttons()
    dlg.open()


def _outcome_dialog(act: dict, res: rules.Result) -> None:
    """Outcome of the activity with the proposed effects, to confirm before applying."""
    text = act["outcomes"].get(res.grade, "")
    entries = (act.get("effects") or {}).get(res.grade, [])
    with theme.dialog() as dlg, ui.card().classes("km-panel") \
            .style("min-width:520px;max-width:680px;max-height:85vh;overflow-y:auto"):
        theme.title(act["name"], 2)
        theme.result_block(res)
        if text:
            theme.sep()
            ui.html(f'<div style="font-size:.86rem;white-space:normal">{theme.esc(text)}</div>')
        theme.sep()
        if not entries:
            ui.label(t("turn.no_automatic_effect_adjust")) \
                .style("color:var(--km-muted);font-size:.82rem")
            quick_adjustments(compact=True)
            ui.button(t("turn.done"), on_click=dlg.close).props("color=amber")
            dlg.open()
            return

        theme.title(t("turn.effects_apply"), 3)
        ui.label(t("turn.untick_what_does_not")) \
            .style("color:var(--km-muted);font-size:.75rem")
        rows = _effect_rows(entries)

        def apply() -> None:
            dlg.close()
            done_ones = _apply_rows(rows, f"{act['name']} ({rules.grade_label(res.grade)})")
            theme.notify(t("turn.applied", list="; ".join(done_ones)) if done_ones else t("turn.no_effect_applied"),
                           "positive" if done_ones else "info")

        with ui.row().classes("gap-2"):
            ui.button(t("turn.apply_effects"), on_click=apply).props("color=amber")
            ui.button(t("turn.skip"), on_click=dlg.close).props("flat")
    dlg.open()


# --------------------------------------------------------------------------
@ui.refreshable
def quick_adjustments(compact: bool = False) -> None:
    k = STATE.k

    @theme.requires(permissions.EDIT_KINGDOM)
    def d(field: str, delta: int) -> None:
        k[field] = max(0, k[field] + delta)
        theme.save_and_refresh()
        quick_adjustments.refresh()
        sheet.identity_block.refresh()
        sheet.resources_block.refresh()
        sheet.skills_block.refresh()

    @theme.requires(permissions.EDIT_KINGDOM)
    def ruin_(rid: str, delta: int) -> None:
        STATE.modify_ruin(rid, delta)
        theme.save_and_refresh()
        quick_adjustments.refresh()
        sheet.abilities_block.refresh()
        sheet.skills_block.refresh()

    @theme.requires(permissions.EDIT_KINGDOM)
    def com(char_id: str, delta: int) -> None:
        if delta > 0:
            STATE.add_commodity(char_id, delta)
        else:
            k["commodities"][char_id] = max(0, k["commodities"][char_id] + delta)
        theme.save_and_refresh()
        quick_adjustments.refresh()
        sheet.resources_block.refresh()

    def row(label: str, value, less, more, extra: str = "",
             on_click_=None) -> None:
        # Name on the left, controls on the right: if the column is narrow
        # the name shortens by itself instead of overrunning the next entry.
        with ui.element("div").style("display:grid;grid-template-columns:1fr auto;"
                                     "align-items:center;column-gap:4px;min-width:0"):
            with ui.element("div").style("min-width:0;overflow:hidden"):
                ui.html(f'<div style="font-size:.82rem;white-space:nowrap;overflow:hidden;'
                        f'text-overflow:ellipsis">{label}</div>'
                        f'<div style="font-size:.68rem;color:var(--km-muted);min-height:1.05em;'
                        f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{extra}</div>')
            with ui.row().classes("items-center gap-0 no-wrap"):
                ui.button(icon="remove", on_click=less).props("dense flat round size=sm color=grey")
                number = ui.html(
                    f'<b style="min-width:38px;text-align:center;display:inline-block;'
                    f'color:var(--km-gold)'
                    f'{";cursor:pointer;text-decoration:underline dotted" if on_click_ else ""}'
                    f'">{value}</b>')
                if on_click_ is not None:
                    number.on("click", on_click_)
                ui.button(icon="add", on_click=more).props("dense flat round size=sm color=amber")

    with ui.element("div").classes("w-full" if compact else "km-panel w-full") \
            .style("padding:8px;display:grid;"
                   "grid-template-columns:repeat(auto-fit,minmax(200px,1fr));"
                   "column-gap:16px;row-gap:2px"):
        row(t("turn.kingdom_turn"), k["turn"], lambda: _move_turn(-1),
             lambda: _move_turn(1), t("turn.click_number_type"),
             on_click_=_turn_dialog)
        row(t("turn.unrest"), k["unrest"], lambda: d("unrest", -1), lambda: d("unrest", 1),
             f'{rules.unrest_penalty(k["unrest"])} status')
        row(t("turn.rp"), k["rp"], lambda: d("rp", -1), lambda: d("rp", 1))
        row(t("turn.xp"), k["xp"], lambda: d("xp", -10), lambda: d("xp", 10), "±10")
        row(t("turn.fame_infamy"), k["fame_points"], lambda: d("fame_points", -1), lambda: d("fame_points", 1),
             f'max {STATE.max_fame}')
        for r in rules.RUINS:
            rd = k["ruins"][r["id"]]
            row(r["name"], f'{rd["points"]}/{rd["threshold"]}',
                 lambda rid=r["id"]: ruin_(rid, -1), lambda rid=r["id"]: ruin_(rid, 1),
                 t("turn.penalty_short", n=rd["penalty"]) if rd["penalty"] else "")
        for p in rules.COMMODITIES:
            row(f'{p["icon"]} {p["name"]}', k["commodities"][p["id"]],
                 lambda char_id=p["id"]: com(char_id, -1), lambda char_id=p["id"]: com(char_id, 1),
                 f'max {STATE.storage(p["id"])}')


# --------------------------------------------------------------------------
def _simple_check(cd: int, title: str, on_success: str = "", on_failure: str = "") -> None:
    tot, rolls = rules.roll(1, 20)
    ok = tot >= cd
    STATE.record(t("turn.d20_vs_dc", title=title, tot=tot, cd=cd, v=rules.grade_label('success' if ok else 'failure')), "check")
    theme.save_and_refresh()
    with theme.dialog() as dlg, ui.card().classes("km-panel"):
        theme.title(title, 2)
        ui.html(f'<div class="km-pixel" style="font-size:1.6rem;color:var(--km-gold)">{tot}</div>')
        ui.label(t("turn.flat_check_dc", cd=cd)).style("color:var(--km-muted)")
        ui.html(f'<div class="{"km-s" if ok else "km-f"}" style="font-family:Cinzel;font-size:1.2rem">'
                f'{rules.grade_label("success" if ok else "failure")}</div>')
        text = on_success if ok else on_failure
        if text:
            ui.markdown(text)
        ui.button(t("common.close"), on_click=dlg.close).props("flat color=amber")
    dlg.open()


# --------------------------------------------------------------------------
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
                details = ", ".join(
                    f'{i["name"]} (Residenziali {STATE.lot_detail(i)["residential_count"]}/'
                    f'{STATE.lot_detail(i)["built_blocks"]})' for i in over)
                ui.html(f'<div class="km-chip km-fc">Sovrappopolati: {details}</div>')
            if k["unrest"] >= 10:
                ui.button(t("turn.unrest_10_roll_1d10"),
                          on_click=_ruin_from_unrest).props("dense color=red")
                ui.button(t("turn.flat_check_dc_11"),
                          on_click=lambda: _simple_check(
                              11, t("turn.loss_hex"),
                              t("turn.kingdom_loses_no_hex"),
                              t("turn.kingdom_loses_hex_pcs"))).props("dense outline color=red")
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
            ui.label(t("turn.turn_consumption_settlements_armies", total=cons["total"], settlements=cons["settlements"], armies=cons["armies"], farms=cons["farms"], events=cons["events"])) \
                .style("color:var(--km-muted)")
            ui.button(t("turn.pay_food"), on_click=lambda: _pay_consumption("food")).props("dense color=amber")
            ui.button(t("turn.pay_5_rp_per"), on_click=lambda: _pay_consumption("rp")).props("dense outline color=amber")
            ui.button(t("turn.increase_unrest_1d4"), on_click=lambda: _pay_consumption("unrest")) \
                .props("dense outline color=red")

    elif step["id"] == "roles":
        ui.label(t("turn.assign_change_leaders_from")).style("color:var(--km-muted)")
        absent = [rules.BY_ID["role"][rid]["name"] for rid, dv in k["roles"].items()
                   if dv["absent"] or not dv["name"]]
        if absent:
            ui.html(t("turn.div_class_km_chip_2", join=", ".join(absent)))


@theme.requires(permissions.EDIT_KINGDOM)
def _add_unrest(n: int) -> None:
    STATE.k["unrest"] += n
    STATE.record(t("turn.unrest_from_overcrowded_settlements", n=n), "unrest")
    theme.save_and_refresh()
    quick_adjustments.refresh()
    sheet.identity_block.refresh()


@theme.requires(permissions.EDIT_KINGDOM)
def _ruin_from_unrest() -> None:
    tot, _ = rules.roll(1, 10)
    theme.notify(t("turn.1d10_ruin_points_distribute", tot=tot), "warning")
    STATE.record(t("turn.unrest_10_ruin_points", tot=tot), "ruin")
    theme.save_and_refresh()


@theme.requires(permissions.EDIT_KINGDOM)
def _roll_resources() -> None:
    n, faces = STATE.resource_dice_count, STATE.resource_die
    tot, rolls = rules.roll(n, faces)
    STATE.k["rp"] = tot
    STATE.k["rp_spent_turn"] = 0
    # Bonus/penalty dice count for a single turn: here they were just used.
    STATE.k["bonus_dice"] = 0
    STATE.record(t("turn.resource_dice_d", n=n, faces=faces, tot=tot), "resources", str(rolls))
    theme.save_and_refresh()
    sheet.resources_block.refresh()
    quick_adjustments.refresh()
    theme.notify(t("turn.d_rp", n=n, faces=faces, tot=tot, join=', '.join(map(str, rolls))))


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


@theme.requires(permissions.EDIT_KINGDOM)
def _pay_consumption(mode: str) -> None:
    cons = STATE.consumption()["total"]
    k = STATE.k
    if cons <= 0:
        theme.notify(t("turn.consumption_0_nothing_pay"), "info")
        return
    if mode == "food":
        if k["commodities"]["food"] < cons:
            theme.notify(t("turn.not_enough_food_pay", food=k['commodities']['food'], cons=cons), "warning")
            return
        k["commodities"]["food"] -= cons
        STATE.record(t("turn.paid_consumption_food", cons=cons), "consumption")
    elif mode == "rp":
        cost = cons * 5
        if not STATE.spend_rp(cost):
            theme.notify(t("turn.not_enough_rp_increase"), "warning")
        STATE.record(t("turn.paid_consumption_rp", cost=cost), "consumption")
    else:
        tot, _ = rules.roll(1, 4)
        k["unrest"] += tot
        STATE.record(t("turn.consumption_not_paid_unrest", tot=tot), "consumption")
    theme.save_and_refresh()
    sheet.resources_block.refresh()
    sheet.identity_block.refresh()
    quick_adjustments.refresh()


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
    tot, _ = rules.roll(1, 20)
    ok = tot >= k["event_dc"]
    if ok:
        k["event_dc"] = 16
        STATE.record(t("turn.random_kingdom_event_d20", tot=tot), "event")
    else:
        k["event_dc"] = max(1, k["event_dc"] - 5)
        STATE.record(t("turn.no_event_d20_next", tot=tot, event_dc=k['event_dc']), "event")
    theme.save_and_refresh()
    _simple_check_result(tot, ok)


def _simple_check_result(tot: int, ok: bool) -> None:
    with theme.dialog() as dlg, ui.card().classes("km-panel"):
        theme.title(t("turn.check_random_events"), 2)
        ui.html(f'<div class="km-pixel" style="font-size:1.6rem;color:var(--km-gold)">{tot}</div>')
        if ok:
            ui.html(t("turn.div_class_km_s"))
            ui.label(t("turn.gm_rolls_events_table")).style("color:var(--km-muted)")
        else:
            ui.html(t("turn.div_class_km_f"))
            ui.label(t("turn.next_turn_s_dc", event_dc=STATE.k["event_dc"])) \
                .style("color:var(--km-muted)")
        ui.button(t("common.close"), on_click=dlg.close).props("flat color=amber")
    dlg.open()


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
    turn_panel.refresh()
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


@theme.requires(permissions.EDIT_KINGDOM)
def advance_turn(reason: str = "") -> None:
    """Brings the kingdom to the next turn, without touching the interface.

    Kept separate from the button because the clock calls it too, when the
    month ends: from a background timer there is no window to send a
    notification to, and trying would be an error.
    """
    k = STATE.k
    k["turn"] += 1
    k["fame_points"] = min(STATE.max_fame, 1)   # unspent points are lost, +1 at the start of the turn
    k["rp_spent_turn"] = 0
    k["turn_activities"] = {}
    STATE.clean_modifiers()
    STATE.record(t("turn.start_kingdom_turn", turn=k['turn']), "turn", reason)


@theme.requires(permissions.EDIT_KINGDOM)
def _new_turn() -> None:
    advance_turn()
    theme.save_and_refresh()
    theme.notify(t("turn.kingdom_turn_started_1", turn=STATE.k['turn'], v=t("turn.fame") if STATE.k["reputation"] == "fame" else t("turn.infamy")))
    turn_panel.refresh()
    sheet.identity_block.refresh()


# --------------------------------------------------------------------------
def _activity_card(act: dict) -> None:
    cd, note = _activity_dc(act)
    reference_ = act.get("reference")
    block = "" if reference_ else STATE.activities_block(act)
    with ui.card().classes("km-panel").style("padding:8px 12px;min-width:260px;flex:1"
                                             + (";opacity:.55" if block else "")):
        with ui.row().classes("items-center gap-2 w-full no-wrap"):
            with ui.column().classes("gap-0").style("flex:1;min-width:0"):
                ui.html(f'<b class="km-title">{theme.esc(act["name"])}</b>')
                skill = ", ".join(rules.BY_ID["skills"][a]["name"] for a in act["skills"] if a != "*") \
                    or t("turn.any_skill")
                ui.label(skill).style("font-size:.72rem;color:var(--km-muted)")
                ui.label(note).style("font-size:.7rem;color:var(--km-gold-dim)")
                if act["cost"]:
                    ui.label(t("turn.cost_3", cost=act["cost"])).style(
                        "font-size:.7rem;color:var(--km-muted);white-space:nowrap;"
                        "overflow:hidden;text-overflow:ellipsis")
                if block:
                    ui.html(f'<div class="km-fc" style="font-size:.7rem;white-space:normal">{block}</div>')
            ui.button(icon=REFERENCES[reference_][0] if reference_ else "casino",
                      on_click=lambda a=act: run_activity(a)) \
                .props("dense flat round color=amber")
        if act["requirements"]:
            ui.tooltip(act["requirements"])


# --------------------------------------------------------------------------
@ui.refreshable
def turn_panel() -> None:
    k = STATE.k
    with ui.row().classes("w-full items-start gap-4 no-wrap"):
        with ui.column().classes("gap-3").style("flex:1;min-width:0"):
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
                            if phase["id"] == "upkeep":
                                _upkeep_step(step)
                            elif phase["id"] == "event":
                                _event_step(step)

                            atts = rules.activities_for_step(phase["id"], step["id"])
                            if atts:
                                max_ = STATE.step_limit(phase["id"], step["id"])
                                if max_ is not None:
                                    used_ones = STATE.step_uses(phase["id"], step["id"])
                                    exhausted = used_ones >= max_
                                    ui.html(t("turn.span_class_km_chip", v="km-fc" if exhausted else "", used_ones=used_ones, max=max_))
                                if phase["id"] == "activities" and step["id"] == "government":
                                    ui.label(t("turn.every_pc_leader_may", max_leadership_activities=STATE.max_leadership_activities())) \
                                        .style("font-size:.78rem;color:var(--km-gold-dim)")
                                if phase["id"] == "activities" and step["id"] == "region":
                                    ui.label(t("turn.claim_hex_max_times", claims_per_turn=STATE.claims_per_turn())) \
                                        .style("font-size:.78rem;color:var(--km-gold-dim)")
                                if phase["id"] == "activities" and step["id"] == "civic":
                                    ui.label(t("turn.build_structure_performed_from")) \
                                        .style("font-size:.78rem;color:var(--km-gold-dim)")
                                with ui.element("div").style(
                                        "display:flex;flex-wrap:wrap;gap:8px;margin-top:6px"):
                                    for act in atts:
                                        _activity_card(act)

        with ui.column().classes("gap-3").style("width:400px;min-width:340px"):
            with ui.card().classes("km-panel w-full"):
                theme.title(t("turn.quick_adjustments"), 2)
                quick_adjustments()
            with ui.card().classes("km-panel w-full km-scroll"):
                theme.title(t("turn.log"), 2)
                _journal()


@ui.refreshable
def _journal() -> None:
    for entry in STATE.journal(80):
        with ui.row().classes("items-start gap-2 no-wrap"):
            ui.html(f'<span style="color:var(--km-muted);font-size:.7rem;min-width:56px">'
                    f'T{int(entry["turn"])} {theme.esc(str(entry["logged_at"])[-5:])}</span>')
            with ui.column().classes("gap-0"):
                ui.label(entry["text"]).style("font-size:.8rem")
                if entry.get("detail"):
                    ui.label(entry["detail"]).style("font-size:.7rem;color:var(--km-muted)")


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
theme.register_refresh("turn.panel", turn_panel)
theme.register_refresh("turn.adjustments", quick_adjustments)
theme.register_refresh("turn.journal", _journal)
