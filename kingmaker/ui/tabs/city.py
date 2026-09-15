"""Urban Grid: building settlements, city-builder style."""
from __future__ import annotations

import uuid

from nicegui import ui

from kingmaker.access import permissions
from kingmaker import rules
from kingmaker.state import STATE
from kingmaker.ui import icons, theme
from kingmaker.ui.tabs import turn
from kingmaker.locale.i18n import t, tn

# Adjacencies inside a 2x2 block:  0 1
#                                  2 3
LOT_NEIGHBOURS = {0: {1, 2}, 1: {0, 3}, 2: {0, 3}, 3: {1, 2}}

# Adjacencies between blocks in the 3x3 grid
def adjacent_blocks(idx: int) -> set[int]:
    r, c = divmod(idx, 3)
    out = set()
    for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        nr, nc = r + dr, c + dc
        if 0 <= nr < 3 and 0 <= nc < 3:
            out.add(nr * 3 + nc)
    return out


def empty_grid() -> list[list[dict]]:
    return [[{"structure": None, "gid": None} for _ in range(4)] for _ in range(9)]


def new_settlement(name: str, hexpos: tuple[int, int] | None = None) -> dict:
    return {
        "id": uuid.uuid4().hex[:8],
        "name": name,
        "kind": "village",
        "hex": list(hexpos) if hexpos else None,
        "grids": [empty_grid()],
        "active_blocks": [4],
        "borders": {"north": "land", "south": "land", "east": "land", "west": "land"},
        "capital": False,
        "consumption_extra": 0,
        "water_only": False,
        "has_bridge": False,
        "note": "",
    }


# --------------------------------------------------------------------------
def _free_contiguous_lots(block_: list[dict], departure: int, n: int) -> list[int] | None:
    """Finds n contiguous free lots in the block, including `start`."""
    if block_[departure]["structure"]:
        return None
    if n == 1:
        return [departure]
    chosen = [departure]
    frontier = set(LOT_NEIGHBOURS[departure])
    while len(chosen) < n:
        cand = [i for i in sorted(frontier)
                if i not in chosen and not block_[i]["structure"]]
        if not cand:
            return None
        chosen.append(cand[0])
        frontier |= LOT_NEIGHBOURS[cand[0]]
    return chosen if len(chosen) == n else None


def _can_expand(sett: dict) -> tuple[bool, str]:
    kind = sett["kind"]
    lvl = STATE.level
    grid = sett["grids"][0]
    active_ones = sett["active_blocks"]

    if STATE.overcrowded(sett):
        return False, t("city.settlement_overcrowded_more_residential")
    if kind == "village":
        if lvl < 3:
            return False, t("city.3rd_level_kingdom_needed")
        if any(not l["structure"] for l in grid[active_ones[0]]):
            return False, t("city.village_must_first_fill")
        return True, t("city.expand_into_town_adds")
    if kind == "town":
        if len(active_ones) < 4:
            return True, t("city.add_another_block_town")
        if lvl < 9:
            return False, t("city.9th_level_kingdom_needed")
        if any(sum(1 for l in grid[i] if l["structure"]) < 2 for i in active_ones):
            return False, t("city.least_two_lots_built")
        return True, t("city.expand_into_city_unlocks")
    if kind == "city":
        if lvl < 15:
            return False, t("city.15th_level_kingdom_needed")
        if any(sum(1 for l in grid[i] if l["structure"]) < 2 for i in range(9)):
            return False, t("city.least_two_lots_built_2")
        return True, t("city.expand_into_metropolis_adds")
    return True, t("city.add_another_urban_grid")


@theme.requires(permissions.EDIT_KINGDOM)
def _expand(sett: dict) -> None:
    ok, msg = _can_expand(sett)
    if not ok:
        theme.notify(msg, "warning")
        return
    kind = sett["kind"]
    if kind == "village":
        neighbours = adjacent_blocks(sett["active_blocks"][0]) - set(sett["active_blocks"])
        sett["active_blocks"].append(sorted(neighbours)[0])
        sett["kind"] = "town"
        STATE.award_milestone("first_town")
        STATE.record(t("city.has_become_town", name=sett['name']), "settlement")
    elif kind == "town" and len(sett["active_blocks"]) < 4:
        neighbours: set[int] = set()
        for i in sett["active_blocks"]:
            neighbours |= adjacent_blocks(i)
        neighbours -= set(sett["active_blocks"])
        sett["active_blocks"].append(sorted(neighbours)[0])
        STATE.record(t("city.block_added", name=sett['name']), "settlement")
    elif kind == "town":
        sett["active_blocks"] = list(range(9))
        sett["kind"] = "city"
        STATE.award_milestone("first_city")
        STATE.record(t("city.has_become_city", name=sett['name']), "settlement")
    elif kind == "city":
        sett["kind"] = "metropolis"
        sett["grids"].append(empty_grid())
        STATE.award_milestone("first_metropolis")
        STATE.record(t("city.has_become_metropolis", name=sett['name']), "settlement")
    else:
        sett["grids"].append(empty_grid())
    theme.save_and_refresh()


# --------------------------------------------------------------------------
def _construction_dialog(sett: dict, gi: int, bi: int, li: int, refresh) -> None:
    """Choice of the structure to build in a lot."""
    block_ = sett["grids"][gi][bi]
    lot = block_[li]

    if lot["structure"]:
        _occupied_lot_dialog(sett, gi, bi, li, refresh)
        return

    filter_ = {"text": "", "buildable_only": False}

    with theme.dialog("maximized") as dlg, ui.card().classes("km-panel").style("padding:16px"):
        with ui.row().classes("w-full items-center justify-between"):
            theme.title(t("city.build_structure", name=sett['name']), 1)
            ui.button(icon="close", on_click=dlg.close).props("flat round color=amber")
        with ui.row().classes("items-center gap-3"):
            ui.input(t("city.search"), on_change=lambda e: (filter_.update(text=e.value), items.refresh())) \
                .props("outlined dense clearable").classes("w-64")
            ui.checkbox(t("city.only_those_i_can"), value=False,
                        on_change=lambda e: (filter_.update(buildable_only=e.value), items.refresh()))
            ui.label(f"{t('turn.rp')} {STATE.k['rp']} · " + " · ".join(
                f"{rules.BY_ID['commodity'][p]['name']} {STATE.k['commodities'][p]}"
                for p in ("food", "lumber", "luxuries", "ore", "stone"))) \
                .style("color:var(--km-muted)")

        @ui.refreshable
        def items() -> None:
            free_items = sum(1 for l in block_ if not l["structure"])
            with ui.column().classes("w-full km-scroll gap-1"):
                for st in rules.all_structures():
                    if filter_["text"] and filter_["text"].lower() not in st["name"].lower():
                        continue
                    if st["lots"] > free_items:
                        continue
                    if not _free_contiguous_lots(block_, li, st["lots"]):
                        continue
                    level_ok = st["level"] <= STATE.level
                    payable = level_ok and _can_pay(st)
                    if filter_["buildable_only"] and not payable:
                        continue
                    _structure_row(st, sett, gi, bi, li, payable, dlg, refresh)

        items()
    dlg.open()


def _can_pay(st: dict) -> bool:
    c = st["cost"]
    if STATE.k["rp"] < c["rp"]:
        return False
    for p in ("food", "lumber", "luxuries", "ore", "stone"):
        if STATE.k["commodities"][p] < c[p]:
            return False
    return True


def _structure_row(st: dict, sett: dict, gi: int, bi: int, li: int,
                    payable: bool, dlg, refresh) -> None:
    with ui.card().classes("km-panel w-full").style("padding:8px 12px"):
        with ui.row().classes("items-center gap-3 w-full no-wrap"):
            ui.html(f'<div style="font-size:1.5rem">{icons.icon(st["id"])}</div>')
            with ui.column().classes("gap-0").style("flex:1"):
                with ui.row().classes("items-center gap-2 flex-wrap"):
                    ui.html(f'<b class="km-title">{theme.esc(st["name"])}</b>')
                    ui.html(f'<span class="km-chip" style="font-size:.7rem">{t("common.level_short", level=st["level"])}</span>')
                    ui.html(f'<span class="km-chip" style="font-size:.7rem">{tn("city.lots", st["lots"])}</span>')
                    for trait in st["traits"]:
                        stretch_name = rules.BY_ID["structure_trait"].get(trait, {}).get("name", trait)
                        ui.html(f'<span class="km-chip" style="font-size:.65rem;color:'
                                f'{icons.TRAIT_COLORS.get(trait, "var(--km-muted)")}">{theme.esc(stretch_name)}</span>')
                if st["description"]:
                    ui.label(st["description"]).style("font-size:.8rem;color:var(--km-muted)")
                row = []
                if st["cost_raw"]:
                    row.append(t("city.cost", cost_raw=st['cost_raw']))
                if st["construction"]:
                    row.append(t("city.construction", raw=st['construction']['raw']))
                if st["item_bonus"]:
                    row.append(t("city.item_bonus", item_bonus=st['item_bonus']))
                if st["ruin"]:
                    row.append(t("city.ruin", ruin=st['ruin']))
                if row:
                    ui.label(" · ".join(row)).style("font-size:.78rem;color:var(--km-gold-dim)")
                if st["effects"]:
                    ui.label(t("city.effects", effects=st['effects'])).style("font-size:.78rem;color:var(--km-muted)")
            with ui.column().classes("gap-1"):
                ui.button(t("city.build"), on_click=lambda: _build(st, sett, gi, bi, li, dlg, refresh,
                                                                    with_check=True)) \
                    .props(f'dense color=amber {"" if payable else "disable"}')
                ui.button(t("city.place_without_check"), on_click=lambda: _build(st, sett, gi, bi, li, dlg,
                                                                             refresh, with_check=False)) \
                    .props("dense flat color=grey").tooltip(
                        t("city.pre_existing_structures_cleared"))


@theme.requires(permissions.EDIT_KINGDOM)
def _build(st: dict, sett: dict, gi: int, bi: int, li: int, dlg, refresh, with_check: bool) -> None:
    block_ = sett["grids"][gi][bi]
    lots = _free_contiguous_lots(block_, li, st["lots"])
    if not lots:
        theme.notify(t("city.there_are_not_enough"), "negative")
        return

    def square() -> None:
        gid = uuid.uuid4().hex[:6]
        for idx in lots:
            block_[idx] = {"structure": st["id"], "gid": gid}
        if st["id"] == "bridge":
            sett["has_bridge"] = True
        STATE.record(t("city.built", name=sett['name'], name2=st['name']), "settlement",
                       st["effects"] or st["item_bonus"])
        theme.save_and_refresh()
        refresh()
        dlg.close()
        _effects_dialog(st, refresh)

    if not with_check:
        square()
        theme.notify(t("city.placed_without_check", name=st['name']))
        return

    # Pays the cost
    c = st["cost"]
    if not _can_pay(st):
        theme.notify(t("city.not_enough_resources"), "negative")
        return
    STATE.spend_rp(c["rp"])
    for p in ("food", "lumber", "luxuries", "ore", "stone"):
        STATE.k["commodities"][p] -= c[p]

    constr = st["construction"]
    if not constr:
        square()
        return

    # Picks automatically the skill option with the best modifier among the valid ones
    valid_ones = []
    for opt in constr["options"]:
        aid = opt["skill"]
        if aid not in rules.BY_ID["skills"]:
            continue
        owned = STATE.k["proficiencies"].get(aid, "untrained")
        ok = rules.meets_proficiency(owned, opt["proficiency"])
        valid_ones.append((aid, ok, STATE.skill_mod(aid)))
    usable = [v for v in valid_ones if v[1]] or valid_ones
    if not usable:
        square()
        return
    aid = max(usable, key=lambda v: v[2])[0]

    res = rules.roll_check(STATE.skill_mod(aid), constr["dc"], STATE.skill_detail(aid))
    STATE.mark_activity("build_structure")
    act = rules.BY_ID["activities"]["build_structure"]
    outcome = act["outcomes"][res.grade]

    if res.grade in ("success", "critical_success"):
        square()
        if res.grade == "critical_success":
            for p in ("food", "lumber", "luxuries", "ore", "stone"):
                STATE.k["commodities"][p] += c[p] // 2
            STATE.fame_on_critical(res)
    elif res.grade == "critical_failure":
        gid = uuid.uuid4().hex[:6]
        for idx in lots:
            block_[idx] = {"structure": "rubble", "gid": gid}
        STATE.record(t("city.failed_lots_are_reduced", name=sett['name'], name2=st['name']),
                       "settlement")
        theme.save_and_refresh()
        refresh()
        dlg.close()
    else:
        STATE.record(t("city.construction_failed_you_can", name=sett['name'], name2=st['name']), "settlement")
        theme.save_and_refresh()
        refresh()
        dlg.close()

    theme.show_result(res, t("city.build_structure", name=st['name']), outcome)


@theme.requires(permissions.EDIT_KINGDOM)
def _set_field(where: dict, key, value) -> None:
    """A settlement field: the setter for the panel's inputs."""
    where[key] = value


# --------------------------------------------------------------------------
def _refresh_stats() -> None:
    theme.save_and_refresh()
    turn.quick_adjustments.refresh()


@theme.requires(permissions.EDIT_KINGDOM)
def _apply_unrest(entry: dict, structure_name: str, dlg) -> None:
    value, detail = rules.quantity_value(entry["quantity"])
    real = STATE.modify_unrest(entry["sign"] * value, structure_name)
    _refresh_stats()
    theme.notify(t("city.unrest", real=real, detail=detail))
    dlg.close()


@theme.requires(permissions.EDIT_KINGDOM)
def _apply_ruin(entry: dict, rid: str, structure_name: str, dlg) -> None:
    value, detail = rules.quantity_value(entry["quantity"])
    STATE.modify_ruin(rid, entry["sign"] * value, structure_name)
    _refresh_stats()
    theme.notify(t("city.text", name=rules.BY_ID["ruin"][rid]["name"], v=entry["sign"] * value, detail=detail))
    dlg.close()


def _effects_dialog(st: dict, refresh=None) -> None:
    """Proposes the changes to Unrest and Ruin described by the structure.

    They do not apply on their own: almost all of them count «the first time in
    a Kingdom Turn» or depend on conditions the table decides.
    """
    entries = rules.structure_effects(st)
    if not entries:
        return
    with theme.dialog() as dlg, ui.card().classes("km-panel").style("min-width:460px;max-width:620px"):
        with ui.row().classes("items-center gap-2"):
            ui.html(f'<div style="font-size:1.6rem">{icons.icon(st["id"])}</div>')
            theme.title(t("city.effects_kingdom", name=st["name"]), 2)
        ui.label(t("city.apply_only_those_that")) \
            .style("font-size:.8rem;color:var(--km-muted)")
        theme.sep()
        for entry in entries:
            with ui.column().classes("gap-1 w-full"):
                ui.label(entry["text"]).style("font-size:.82rem;color:var(--km-gold-dim)")
                sign = "−" if entry["sign"] < 0 else "+"
                with ui.row().classes("gap-2 flex-wrap items-center"):
                    if entry["kind"] == "unrest":
                        ui.button(t("city.unrest_2", sign=sign, quantity=entry["quantity"]),
                                  on_click=lambda v=entry: _apply_unrest(v, st["name"], dlg)) \
                            .props("dense color=amber")
                    elif entry["kind"] == "ruin":
                        ruin_name = rules.BY_ID["ruin"][entry["ruin"]]["name"]
                        ui.button(t("city.text_2", ruin_name=ruin_name, sign=sign, quantity=entry["quantity"]),
                                  on_click=lambda v=entry: _apply_ruin(v, v["ruin"], st["name"], dlg)) \
                            .props(f'dense color={"red" if entry["sign"] > 0 else "amber"}')
                    else:
                        ui.label(t("city.ruin_your_choice")).style("font-size:.8rem")
                        for r in rules.RUINS:
                            ui.button(t("city.text_3", name=r["name"], sign=sign, quantity=entry["quantity"]),
                                      on_click=lambda v=entry, rid=r["id"]:
                                      _apply_ruin(v, rid, st["name"], dlg)) \
                                .props(f'dense outline color={"red" if entry["sign"] > 0 else "amber"}')
        theme.sep()
        ui.button(t("common.close"), on_click=lambda: (dlg.close(), refresh() if refresh else None)) \
            .props("flat color=amber")
    dlg.open()


def _occupied_lot_dialog(sett: dict, gi: int, bi: int, li: int, refresh) -> None:
    block_ = sett["grids"][gi][bi]
    lot = block_[li]
    st = rules.BY_ID["structure"].get(lot["structure"])
    lot_name = st["name"] if st else str(lot["structure"])

    with theme.dialog() as dlg, ui.card().classes("km-panel").style("min-width:420px"):
        with ui.row().classes("items-center gap-3"):
            ui.html(f'<div style="font-size:2rem">{icons.icon(lot["structure"])}</div>')
            theme.title(lot_name, 2)
        if st:
            ui.label(st["description"]).style("color:var(--km-muted)")
            for label, value in ((t("city.cost_2"), st["cost_raw"]),
                                      (t("main.construction"), st["construction"]["raw"] if st["construction"] else ""),
                                      (t("city.item_bonus_2"), st["item_bonus"]),
                                      (t("city.ruin_label"), st["ruin"]),
                                      (t("city.effects_label"), st["effects"])):
                if value:
                    ui.markdown(t("city.text_4", label=label, value=value)).style("font-size:.85rem")
            if st["upgrade_to"]:
                names = [rules.BY_ID["structure"][x]["name"] for x in st["upgrade_to"]
                        if x in rules.BY_ID["structure"]]
                ui.markdown(t("city.upgrades", join=', '.join(names))).style("font-size:.85rem")
        theme.sep()

        @theme.requires(permissions.EDIT_KINGDOM)
        def demolish() -> None:
            gid = lot["gid"]
            for idx, l in enumerate(block_):
                if l["gid"] == gid:
                    block_[idx] = {"structure": None, "gid": None}
            STATE.record(t("city.removed", name=sett['name'], lot_name=lot_name), "settlement")
            theme.save_and_refresh()
            refresh()
            dlg.close()

        @theme.requires(permissions.EDIT_KINGDOM)
        def to_rubble() -> None:
            gid = lot["gid"]
            new = uuid.uuid4().hex[:6]
            for idx, l in enumerate(block_):
                if l["gid"] == gid:
                    block_[idx] = {"structure": "rubble", "gid": new}
            theme.save_and_refresh()
            refresh()
            dlg.close()

        with ui.row():
            ui.button(t("city.empty_lot"), on_click=demolish).props("flat color=red")
            if lot["structure"] != "rubble":
                ui.button(t("city.reduce_rubble"), on_click=to_rubble).props("flat color=orange")
            if st and rules.structure_effects(st):
                ui.button(t("city.apply_effects_kingdom"),
                          on_click=lambda: (dlg.close(), _effects_dialog(st, refresh))) \
                    .props("flat color=amber")
            ui.button(t("common.close"), on_click=dlg.close).props("flat color=amber")
    dlg.open()


# --------------------------------------------------------------------------
@theme.requires(permissions.EDIT_KINGDOM)
def _make_capital(sett: dict, refresh) -> None:
    for i in STATE.k["settlements"]:
        i["capital"] = i["id"] == sett["id"]
    STATE.k["capital"] = sett["id"]
    STATE.record(t("city.new_capital_kingdom", name=sett['name']), "settlement")
    theme.save_and_refresh()
    refresh.refresh()
    theme.notify(t("city.now_capital", name=sett["name"]))


def _position_block(sett: dict, refresh) -> None:
    """Which hex the settlement stands on, and how to change it."""
    with ui.row().classes("items-center gap-2 flex-wrap"):
        if sett.get("hex"):
            ui.html(t("city.span_class_km_chip", hex=sett["hex"][0], hex2=sett["hex"][1]))
        else:
            ui.html(t("city.span_class_km_chip_2"))
        col = ui.number(t("city.col"), value=sett["hex"][0] if sett.get("hex") else None, format="%d") \
            .props("outlined dense").classes("w-20")
        row = ui.number(t("city.row"), value=sett["hex"][1] if sett.get("hex") else None, format="%d") \
            .props("outlined dense").classes("w-20")

        def link() -> None:
            if col.value is None or row.value is None:
                theme.notify(t("city.column_row_are_required"), "negative")
                return
            error = STATE.link_settlement(sett["id"], int(col.value), int(row.value))
            if error:
                theme.notify(error, "negative")
                return
            theme.save_and_refresh()
            refresh.refresh()
            theme.notify(t("city.linked_hex", name=sett["name"], int=int(col.value), int2=int(row.value)))

        ui.button(t("city.link"), on_click=link).props("dense color=amber") \
            .tooltip(t("city.links_this_settlement_given"))


def _confirm_city_removal(sett: dict, refresh) -> None:
    """Removes a settlement from the City tab.

    For those without a hex (founded from the form below with no coordinates):
    they cannot be reached from the map.
    """
    counts = STATE.lot_detail(sett)
    with theme.dialog() as dlg, ui.card().classes("km-panel").style("min-width:420px"):
        theme.title(t("city.remove_settlement"), 2)
        ui.label(t("city.will_deleted_its_whole", name=sett["name"], occupied=counts["occupied"])) \
            .style("color:var(--km-muted)")
        if sett["capital"] and len(STATE.k["settlements"]) > 1:
            ui.html(t("city.div_class_km_chip"))

        @theme.requires(permissions.EDIT_KINGDOM)
        def delete() -> None:
            name = sett["name"]
            STATE.remove_settlement(sett["id"])
            theme.save_and_refresh()
            dlg.close()
            refresh.refresh()
            theme.notify(t("city.settlement_removed", name=name))

        with ui.row():
            ui.button(t("common.delete"), on_click=delete).props("color=red")
            ui.button(t("common.cancel"), on_click=dlg.close).props("flat")
    dlg.open()


def _overcrowding_block(sett: dict, counts: dict) -> None:
    """Counter of Residential lots: one is needed for every built block."""
    needed = counts["built_blocks"]
    residential_count = counts["residential_count"]
    missing_items = counts["missing"]
    color = "var(--km-red)" if missing_items else "var(--km-green)"
    with ui.column().classes("gap-1 w-full"):
        with ui.row().classes("items-center gap-2 flex-wrap"):
            ui.html(t("city.span_class_km_chip_3", color=color, residential_count=residential_count, needed=needed))
            ui.html(f'<span class="km-chip">{t("city.blocks_built")} <b>{needed}</b></span>')
            ui.html(t("city.span_class_km_chip_4", free=counts["free"]))
        if missing_items:
            ui.html(t("city.div_class_km_chip_2", missing_items=missing_items, v=t("city.residential_lot") if missing_items == 1 else t("city.residential_lots")))
        else:
            ui.label(t("city.no_overcrowding_there_residential")) \
                .style("font-size:.75rem;color:var(--km-muted)")


def _kingdom_stats_block() -> None:
    """The kingdom statistics here too, so you need not change page while building."""
    with ui.card().classes("km-panel w-full"):
        theme.title(t("city.kingdom_statistics"), 3)
        over = STATE.overcrowded_settlements()
        if over:
            ui.html(t("city.div_class_km_chip_3", len=len(over), v=t("city.overcrowded_settlement") if len(over) == 1 else t("city.overcrowded_settlements"), len2=len(over), join=", ".join(i["name"] for i in over)))
        cons = STATE.consumption()
        ui.html(t("city.span_class_km_chip_5", total=cons["total"], settlements=cons["settlements"], armies=cons["armies"], farms=cons["farms"], events=cons["events"]))
        turn.quick_adjustments(compact=True)


# --------------------------------------------------------------------------
def city_panel() -> None:
    ui_state = {"sel": STATE.k["capital"], "grid": 0}

    @ui.refreshable
    def content_() -> None:
        k = STATE.k
        if not k["settlements"]:
            with ui.card().classes("km-panel w-full"):
                ui.label(t("city.no_settlement_found_one")) \
                    .style("color:var(--km-muted)")
                _new_form(content_)
            return

        ids = [i["id"] for i in k["settlements"]]
        if ui_state["sel"] not in ids:
            ui_state["sel"] = ids[0]
        sett = STATE.settlement(ui_state["sel"])
        kind = rules.BY_ID["settlement"][sett["kind"]]

        with ui.row().classes("w-full items-start gap-4 no-wrap"):
            # ---------------------------------------------------- left column
            with ui.column().classes("gap-3").style("min-width:340px;max-width:380px"):
                with ui.card().classes("km-panel w-full"):
                    ui.select({i["id"]: (i["name"] + (" ★" if i["capital"] else "")
                                         + ("" if i.get("hex") else t("city.off_map")))
                               for i in k["settlements"]},
                              value=ui_state["sel"],
                              on_change=lambda e: (ui_state.update(sel=e.value, grid=0), content_.refresh())) \
                        .props("outlined dense").classes("w-full")
                    _position_block(sett, content_)
                    with ui.row().classes("gap-1 items-center"):
                        if not sett["capital"]:
                            ui.button(t("city.make_capital"), on_click=lambda: _make_capital(sett, content_)) \
                                .props("dense flat color=amber")
                        ui.button(t("city.remove_settlement_2"),
                                  on_click=lambda: _confirm_city_removal(sett, content_)) \
                            .props("dense flat color=red")
                    counts = STATE.lot_detail(sett)
                    with ui.row().classes("gap-2 flex-wrap items-center"):
                        theme.stat_box(kind["name"], t("city.type"))
                        theme.stat_box(STATE.settlement_level(sett), t("city.level"),
                                       t("city.equal_blocks_least_one"))
                        theme.stat_box(kind["consumption"] + sett.get("consumption_extra", 0), t("city.consumption"))
                        theme.stat_box(f'+{kind["item_bonus_max"]}', t("city.max_item_bonus"))
                        theme.stat_box(kind["influence"], t("city.influence"))
                    _overcrowding_block(sett, counts)
                    ui.label(t("city.approximate_population", population=kind["population"])) \
                        .style("font-size:.78rem;color:var(--km-muted)")

                    ok, msg = _can_expand(sett)
                    ui.button(("Espandi" if ok else t("city.expansion_blocked")),
                              on_click=lambda: _expand(sett) or content_.refresh()) \
                        .props(f'dense color={"amber" if ok else "grey"} {"" if ok else "disable"}') \
                        .classes("w-full")
                    ui.label(msg).style("font-size:.75rem;color:var(--km-muted)")

                with ui.card().classes("km-panel w-full"):
                    theme.title(t("city.grid_borders"), 3)
                    for side in ("north", "south", "east", "west"):
                        ui.select({"land": t("city.land_border"), "water": t("city.water_border"),
                                   "walls": t("city.walled_border")},
                                  label=side.capitalize(), value=sett["borders"][side],
                                  on_change=lambda e, l=side: (_set_field(sett["borders"], l, e.value),
                                                               theme.save_and_refresh())) \
                            .props("outlined dense").classes("w-full")
                    ui.label(t("city.settlement_without_land_borders")) \
                        .style("font-size:.72rem;color:var(--km-muted)")

                with ui.card().classes("km-panel w-full"):
                    theme.title(t("city.structures_built"), 3)
                    tally = STATE.structures_of(sett)
                    if not tally:
                        ui.label(t("city.none")).style("color:var(--km-muted)")
                    for sid, n in sorted(tally.items()):
                        st = rules.BY_ID["structure"].get(sid)
                        name = st["name"] if st else sid
                        with ui.row().classes("items-center gap-2 w-full no-wrap"):
                            ui.label(icons.icon(sid))
                            ui.label(t("city.text_5", name=name, v=f' ×{n}' if n > 1 else '')).style("flex:1")
                            if st and "residential" in st["traits"]:
                                ui.html('<span class="km-chip" style="font-size:.65rem;'
                                        'color:var(--km-green)">' + t("city.residential") + '</span>')
                            if st and st["item_bonus"]:
                                ui.html(f'<span class="km-chip" style="font-size:.65rem">'
                                        f'{st["item_bonus"]}</span>')

                _kingdom_stats_block()
                _new_form(content_)

            # ---------------------------------------------------- right column
            with ui.column().classes("gap-2").style("flex:1"):
                with ui.row().classes("items-center gap-3"):
                    theme.title(t("city.urban_grid", name=sett["name"]), 1)
                    if len(sett["grids"]) > 1:
                        ui.select({i: t("city.grid", v=i + 1) for i in range(len(sett["grids"]))},
                                  value=ui_state["grid"],
                                  on_change=lambda e: (ui_state.update(grid=e.value), content_.refresh())) \
                            .props("outlined dense").classes("w-40")
                _draw_grid(sett, ui_state["grid"], content_.refresh)
                ui.label(t("city.every_urban_grid_has")) \
                    .style("font-size:.78rem;color:var(--km-muted)")

    content_()
    theme.register_refresh("city.content", content_)


@theme.requires(permissions.EDIT_KINGDOM)
def _new_form(refresh) -> None:
    with ui.card().classes("km-panel w-full"):
        theme.title(t("city.new_settlement"), 3)
        name = ui.input(t("city.name")).props("outlined dense").classes("w-full")
        with ui.row():
            col = ui.number(t("city.column"), format="%d").props("outlined dense").classes("w-28")
            row = ui.number(t("city.row"), format="%d").props("outlined dense").classes("w-28")

        def create() -> None:
            if not name.value:
                theme.notify(t("city.name_required"), "negative")
                return
            pos = (int(col.value), int(row.value)) if col.value is not None and row.value is not None else None
            sett = new_settlement(name.value, pos)
            if not STATE.k["settlements"]:
                sett["capital"] = True
                STATE.k["capital"] = sett["id"]
            STATE.k["settlements"].append(sett)
            if pos:
                STATE.hex(*pos)["settlement"] = sett["id"]
            STATE.award_milestone("first_village")
            STATE.record(t("city.founded_settlement", name=sett['name']), "settlement")
            theme.save_and_refresh()
            refresh.refresh() if hasattr(refresh, "refresh") else refresh()

        ui.button(t("city.found_village"), on_click=create).props("dense color=amber")


def _draw_grid(sett: dict, gi: int, refresh) -> None:
    grid = sett["grids"][gi]
    active_ones = sett["active_blocks"] if (gi == 0 and sett["kind"] != "metropolis") else list(range(9))
    if sett["kind"] == "metropolis":
        active_ones = list(range(9))

    with ui.element("div").style(
            "display:grid;grid-template-columns:repeat(3,1fr);gap:8px;"
            "max-width:640px;padding:10px;background:#120f0b;border:1px solid var(--km-line);"
            "border-radius:10px"):
        for bi in range(9):
            is_unlocked = bi in active_ones
            with ui.element("div").classes("km-block" + ("" if is_unlocked else " locked")):
                for li in range(4):
                    lot = grid[bi][li]
                    sid = lot["structure"]
                    cls = "km-lot"
                    if sid == "rubble":
                        cls += " rubble"
                    elif sid:
                        cls += " full"
                    el = ui.element("div").classes(cls)
                    with el:
                        if sid:
                            st = rules.BY_ID["structure"].get(sid, {})
                            name = st.get("name", sid)
                            ui.html(f'<div style="font-size:1.2rem;line-height:1">{icons.icon(sid)}</div>'
                                    f'<div>{theme.esc(name)}</div>')
                            if st.get("item_bonus") or st.get("effects"):
                                ui.tooltip(st.get("item_bonus") or st.get("effects"))
                        else:
                            ui.html('<span style="color:#4a3d2c;font-size:1.1rem">+</span>')
                    if is_unlocked:
                        el.on("click", lambda _e, b=bi, l=li: _construction_dialog(sett, gi, b, l, refresh))
