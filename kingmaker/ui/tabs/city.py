"""Urban Grid: building settlements, city-builder style."""
from __future__ import annotations

import uuid

from nicegui import ui

from kingmaker.access import permissions
from kingmaker import rules
from kingmaker.settlements import empty_grid, new_settlement  # noqa: F401  (re-exported)
from kingmaker.state import EDIFICE, STATE
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
                    cost, why = build_cost(st, sett, lot)
                    payable = level_ok and _can_pay(st, sett, cost)
                    if filter_["buildable_only"] and not payable:
                        continue
                    _structure_row(st, sett, gi, bi, li, payable, dlg, refresh, cost, why)

        items()
    dlg.open()


def _commodity_cost(st: dict) -> dict[str, int]:
    """The commodities building `st` takes. A cost of «1 Lumber or 1 Stone»
    (`cost_either`, the Bridge, the Watchtower) is paid in one of them: the
    one the kingdom can pay with and has more of; neither, when it has
    enough of none — then the cost asks for the first, and is refused."""
    c = st["cost"]
    cost = {p: c[p] for p in ("food", "lumber", "luxuries", "ore", "stone")}
    either = st.get("cost_either") or ()
    if either:
        stock = STATE.k["commodities"]
        payable = [p for p in either if stock[p] >= c[p]]
        chosen = max(payable, key=lambda p: stock[p]) if payable else either[0]
        for p in either:
            if p != chosen:
                cost[p] = 0
    return cost


def cost_of(st: dict, sett: dict | None = None, *, half: bool = False) -> dict[str, int]:
    """What building `st` costs: RP and the commodities (one of «Lumber or
    Stone»). `half`: Repair, or Ruins of that structure on the hex, half of
    each, rounded up."""
    cost = {"rp": st["cost"]["rp"], **_commodity_cost(st)}
    if half:
        cost = {p: (n + 1) // 2 for p, n in cost.items()}
    return cost


def cost_text(cost: dict[str, int]) -> str:
    """«3 RP · 2 Lumber», or «free»."""
    parts = [f'{cost["rp"]} {t("turn.rp")}'] if cost.get("rp") else []
    parts += [f'{n} {rules.BY_ID["commodity"][p]["name"]}' for p, n in cost.items() if p != "rp" and n]
    return " · ".join(parts) or t("city.free")


def _can_pay(st: dict, sett: dict | None = None, cost: dict | None = None) -> bool:
    cost = cost if cost is not None else cost_of(st, sett)
    if STATE.k["rp"] < cost.get("rp", 0):
        return False
    return all(STATE.k["commodities"][p] >= n for p, n in cost.items() if p != "rp")


def ruins_feature(sett: dict, st: dict) -> dict | None:
    """Ruins of this structure on the settlement's hex, not used yet: the
    structure costs half there, once."""
    h = STATE.existing_hex(*sett["hex"]) if sett.get("hex") else None
    for f in (h or {}).get("features", ()):
        if f.get("kind") == "ruins_feature" and f.get("structure") == st["id"] and not f.get("used"):
            return f
    return None


def retry_free(lot: dict, st: dict) -> bool:
    """A construction failed on this lot last turn or this one: trying the
    same structure again pays nothing."""
    failed = lot.get("failed") or {}
    return failed.get("structure") == st["id"] and STATE.k["turn"] - failed.get("turn", -99) <= 1


def build_cost(st: dict, sett: dict, lot: dict) -> tuple[dict[str, int], str]:
    """The cost of building `st` on `lot` now, and why it differs (a text key
    or ""): a free retry, Ruins on the hex, or the plain cost."""
    if retry_free(lot, st):
        return {"rp": 0}, "city.retry_free"
    if ruins_feature(sett, st):
        return cost_of(st, sett, half=True), "city.ruins_half"
    return cost_of(st, sett), ""


def edifice_built(sett: dict, st: dict) -> bool:
    """An Edifice already standing here: a second one adds nothing."""
    return EDIFICE in st.get("traits", ()) and st["id"] in STATE.structures_of(sett)


# Walls and bridges stand on a border of the grid.
WALLS = {"wooden_wall": "wooden", "stone_wall": "stone"}
SIDES = ("north", "south", "east", "west")


def wall_sides(sett: dict, st: dict) -> list[str]:
    """The borders a wall of this kind may go on: not one with the same wall,
    nor a wooden wall where a stone one stands (a stone one replaces wood)."""
    kind = WALLS[st["id"]]
    walls = sett.get("border_walls") or {}
    return [s for s in SIDES if walls.get(s) != kind and not (kind == "wooden" and walls.get(s) == "stone")]


def bridge_sides(sett: dict) -> list[str]:
    bridges = sett.get("border_bridges") or {}
    return [s for s in SIDES if (sett.get("borders") or {}).get(s) == "water" and not bridges.get(s)]


def gid_lots(block_: list[dict], gid) -> list[int]:
    return [i for i, l in enumerate(block_) if gid and l.get("gid") == gid]


def rubble_gid(block_: list[dict], gid) -> None:
    """Every lot of a structure to Rubble, as one rubble structure."""
    new = uuid.uuid4().hex[:6]
    for idx in gid_lots(block_, gid):
        block_[idx] = {"structure": "rubble", "gid": new}


def place_free(sett: dict, structure_id: str) -> bool:
    """A structure placed on the grid with no cost, no check and no Fame (a
    Structure feature on the hex of a new settlement): the first free
    contiguous lots of the unlocked blocks."""
    st = rules.BY_ID["structure"].get(structure_id)
    if not st:
        return False
    grid = sett["grids"][0]
    for bi in sett.get("active_blocks") or [4]:
        for li in range(4):
            lots = _free_contiguous_lots(grid[bi], li, st["lots"])
            if lots:
                gid = uuid.uuid4().hex[:6]
                for idx in lots:
                    grid[bi][idx] = {"structure": st["id"], "gid": gid}
                return True
    return False


def _structure_row(st: dict, sett: dict, gi: int, bi: int, li: int,
                    payable: bool, dlg, refresh, cost: dict | None = None, why: str = "") -> None:
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
                chips = []
                if why:
                    chips.append(t(why) + " · " + cost_text(cost or {}))
                if edifice_built(sett, st):
                    chips.append(t("city.edifice_built"))
                if chips:
                    ui.html(" ".join(f'<span class="km-chip" style="font-size:.7rem;color:var(--km-gold)">'
                                     f'{theme.esc(c)}</span>' for c in chips))
            with ui.column().classes("gap-1"):
                # The Civic step's limits: the button waits, and says why.
                blocked = STATE.activities_block(rules.BY_ID["activities"]["build_structure"],
                                                 settlement=sett["id"])
                ui.button(t("city.build"), on_click=lambda: _build(st, sett, gi, bi, li, dlg, refresh,
                                                                    with_check=True, cost=cost)) \
                    .props(f'dense color=amber {"" if payable and not blocked else "disable"}') \
                    .tooltip(blocked or "")
                ui.button(t("city.place_without_check"), on_click=lambda: _build(st, sett, gi, bi, li, dlg,
                                                                             refresh, with_check=False)) \
                    .props("dense flat color=grey").tooltip(
                        t("city.pre_existing_structures_cleared"))


@theme.requires(permissions.EDIT_KINGDOM)
def _build(st: dict, sett: dict, gi: int, bi: int, li: int, dlg, refresh, with_check: bool, *,
           cost: dict | None = None, replace_gid=None, bonus=(), repairing: bool = False) -> None:
    """Builds `st` on lot `li`: pays, rolls the Build Structure check, places it.
    `cost` replaces the plain cost (an upgrade's difference, a repair's half);
    `replace_gid` is the structure being upgraded or repaired, whose lots count
    as free; `bonus` typed bonuses for the check (Repair's +2 item);
    `repairing`: on a success the lots are mended, on a critical failure they
    fall to Rubble."""
    block_ = sett["grids"][gi][bi]
    if repairing:
        lots = gid_lots(block_, replace_gid)
    else:
        view = [{"structure": None, "gid": None} if replace_gid and l.get("gid") == replace_gid else l
                for l in block_]
        lots = _free_contiguous_lots(view, li, st["lots"])
    if not lots:
        theme.notify(t("city.there_are_not_enough"), "negative")
        return
    # A wall needs a border without one; a bridge a water border without one.
    if not repairing and st["id"] in WALLS and not wall_sides(sett, st):
        theme.notify(t("city.wall_no_side"), "warning")
        return
    if not repairing and st["id"] == "bridge" and not bridge_sides(sett):
        theme.notify(t("city.bridge_no_water"), "warning")
        return
    ruins = None if (repairing or replace_gid) else ruins_feature(sett, st)
    # The structure being upgraded (a wooden wall under a stone one keeps its border).
    old_lots = gid_lots(block_, replace_gid) if replace_gid and not repairing else []
    old_id = block_[old_lots[0]].get("structure") if old_lots else None

    def square(built: bool = True) -> None:
        if repairing:
            for idx in lots:
                block_[idx].pop("damaged", None)
            STATE.record(t("city.repaired", name=sett["name"], name2=st["name"]), "settlement")
            theme.save_and_refresh()
            refresh()
            dlg.close()
            return
        gid = uuid.uuid4().hex[:6]
        if replace_gid:
            for idx in gid_lots(block_, replace_gid):
                block_[idx] = {"structure": None, "gid": None}
        for idx in lots:
            block_[idx] = {"structure": st["id"], "gid": gid}
        if ruins is not None and built:
            ruins["used"] = True
        STATE.record(t("city.built", name=sett['name'], name2=st['name']), "settlement",
                       st["effects"] or st["item_bonus"])
        # A famous or infamous structure moves the kingdom's points when it
        # is built — not when one already standing is placed on the grid.
        fame = STATE.fame_from_structure(st["id"]) if built else 0
        if fame:
            STATE.record(t("city.fame_from_structure", name=st["name"], fame=STATE.fame_name,
                           delta=fame), "settlement")
        theme.save_and_refresh()
        refresh()
        dlg.close()
        if st["id"] in WALLS or st["id"] == "bridge":
            _border_side_dialog(st, sett, refresh, upgraded_from=old_id)
        else:
            _effects_dialog(st, refresh)

    if not with_check:
        square(built=False)
        theme.notify(t("city.placed_without_check", name=st['name']))
        return

    # The Civic step's limits: one activity per settlement (two in one of
    # them with Civic Planning), nothing but Quell Unrest in Anarchy.
    why = STATE.activities_block(rules.BY_ID["activities"]["build_structure"], settlement=sett["id"])
    if why:
        theme.notify(why, "warning")
        return

    # Pays the cost
    if cost is None:
        cost = build_cost(st, sett, block_[li])[0]
    if not _can_pay(st, sett, cost):
        theme.notify(t("city.not_enough_resources"), "negative")
        return
    STATE.spend_rp(cost.get("rp", 0))
    paid = {p: n for p, n in cost.items() if p != "rp"}
    for p, n in paid.items():
        STATE.k["commodities"][p] -= n

    constr = st["construction"]
    if not constr:
        STATE.mark_activity("build_structure", settlement=sett["id"])
        square()
        return

    # Picks automatically the skill option with the best modifier among the valid ones
    valid_ones = []
    options = list(constr["options"])
    # Practical Magic: Magic in place of Engineering, at the same rank.
    if "practical_magic" in STATE.k["feats"]:
        options += [dict(o, skill="magic") for o in constr["options"] if o["skill"] == "engineering"]
    for opt in options:
        aid = opt["skill"]
        if aid not in rules.BY_ID["skills"]:
            continue
        owned = STATE.k["proficiencies"].get(aid, "untrained")
        ok = rules.meets_proficiency(owned, opt["proficiency"])
        valid_ones.append((aid, ok, sum(v for _n, v in STATE.check_detail(
            aid, "build_structure", st["id"], settlement=sett["id"], extra=bonus))))
    usable = [v for v in valid_ones if v[1]] or valid_ones
    if not usable:
        STATE.mark_activity("build_structure", settlement=sett["id"])
        square()
        return
    aid = max(usable, key=lambda v: v[2])[0]
    dc = STATE.activity_dc("build_structure", base=constr["dc"])[0]

    # Built in this settlement: its structures help (a Construction Yard),
    # with the capital's; `State.kingdom_check` counts them.
    def roll() -> rules.Result:
        # The structure is the variant: Fortified Fiefs helps with some.
        res = STATE.kingdom_check(aid, dc, "build_structure", st["id"], settlement=sett["id"],
                                  extra=bonus)
        STATE.note_grade("build_structure", res.grade)
        return res

    def apply(res: rules.Result) -> None:
        if res.grade in ("success", "critical_success"):
            if res.grade == "critical_success":
                # Half of what was paid comes back — within the storage.
                for p, n in paid.items():
                    if n // 2:
                        STATE.add_commodity(p, n // 2)
            square()
            return
        if res.grade == "critical_failure":
            if repairing:
                rubble_gid(block_, replace_gid)
            else:
                gid = uuid.uuid4().hex[:6]
                for idx in lots:
                    block_[idx] = {"structure": "rubble", "gid": gid}
            STATE.record(t("city.failed_lots_are_reduced", name=sett['name'], name2=st['name']),
                           "settlement")
        else:
            # The next attempt of the same structure here, this turn or the
            # next, pays nothing.
            if not repairing:
                block_[li]["failed"] = {"structure": st["id"], "turn": STATE.k["turn"]}
            STATE.record(t("city.construction_failed_you_can", name=sett['name'], name2=st['name']), "settlement")
        theme.save_and_refresh()
        refresh()
        dlg.close()

    STATE.mark_activity("build_structure", settlement=sett["id"], skill=aid)
    # Functions, not strings: the other windows read the roll in their own
    # language, structure name and outcome included. The structure dialog
    # stays open under the result until the result is kept.
    theme.show_check(roll(), lambda: t("city.build_structure", name=rules.BY_ID["structure"][st["id"]]["name"]),
                     lambda res: rules.BY_ID["activities"]["build_structure"]["outcomes"][res.grade],
                     apply=apply, reroll=roll)


def side_options(sett: dict, st: dict, upgraded_from: str | None = None) -> list[str]:
    """The borders a new wall or bridge may go on. A stone wall upgraded from
    a wooden one takes the wooden wall's border: the box of the wooden wall is
    unchecked and the stone one checked in its place."""
    wall = WALLS.get(st["id"])
    sides = wall_sides(sett, st) if wall else bridge_sides(sett)
    if wall and upgraded_from in WALLS:
        walls = sett.get("border_walls") or {}
        old = [s for s in SIDES if walls.get(s) == WALLS[upgraded_from]]
        sides = old or sides
    return sides


def _border_side_dialog(st: dict, sett: dict, refresh, upgraded_from: str | None = None) -> None:
    """Which border the new wall stands on, or which water border the bridge
    spans. A wall's −1 Unrest is offered only for the first of its kind here.
    A stone wall upgraded from a wooden one takes the wooden wall's border
    («if you're upgrading from a wooden wall, uncheck that box»)."""
    wall = WALLS.get(st["id"])
    sides = side_options(sett, st, upgraded_from)
    with theme.dialog() as dlg, ui.card().classes("km-panel").style("min-width:360px"):
        theme.title(t("city.wall_side_title") if wall else t("city.bridge_side_title"), 2)
        side = ui.select({s: t(f"city.side.{s}") for s in sides}, value=sides[0] if sides else None) \
            .props("outlined dense").classes("w-48")

        def confirm() -> None:
            dlg.close()
            _set_border_piece(sett, st, side.value)
            first = STATE.structures_of(sett).get(st["id"], 0) == 1
            if wall and not first:
                theme.notify(t("city.wall_not_first"), "info")
            else:
                _effects_dialog(st, refresh)

        ui.button(t("common.save"), on_click=confirm).props("color=amber")
    dlg.open()


@theme.requires(permissions.EDIT_KINGDOM)
def _set_border_piece(sett: dict, st: dict, side: str | None) -> None:
    if side not in SIDES:
        return
    if st["id"] in WALLS:
        sett.setdefault("border_walls", {})[side] = WALLS[st["id"]]
    elif st["id"] == "bridge":
        sett.setdefault("border_bridges", {})[side] = True
        sett["has_bridge"] = True          # what a 2.2 app reads
    STATE.record(t("city.border_piece", name=sett["name"], structure=st["name"],
                   side=t(f"city.side.{side}")), "settlement")
    theme.save_and_refresh()


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
    delta = entry["sign"] * value
    # Lowered by building — an activity: Endure Anarchy may take 1 more.
    real = (STATE.activity_unrest(delta, structure_name) if delta < 0
            else STATE.modify_unrest(delta, structure_name))
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
    """A standing structure (or Rubble): what it is, then what can be done to
    it, in sections: upgrade, repair, demolish, and the corrections the table
    makes by hand."""
    block_ = sett["grids"][gi][bi]
    lot = block_[li]
    st = rules.BY_ID["structure"].get(lot["structure"])
    lot_name = st["name"] if st else str(lot["structure"])
    rubble = lot["structure"] == "rubble"

    with theme.dialog() as dlg, ui.card().classes("km-panel") \
            .style("min-width:460px;max-width:640px;max-height:85vh;overflow-y:auto;gap:6px"):
        with ui.row().classes("items-center gap-3 w-full"):
            ui.html(f'<div style="font-size:2rem">{icons.icon(lot["structure"])}</div>')
            theme.title(lot_name, 2)
            ui.element("div").style("flex:1")
            if lot.get("damaged"):
                ui.html(f'<span class="km-chip km-fc" style="font-size:.72rem">{theme.esc(t("city.damaged_chip"))}</span>')
            if lot.get("demolishing"):
                ui.html(f'<span class="km-chip" style="font-size:.72rem">{theme.esc(t("city.demolishing_chip"))}</span>')
        if st:
            ui.label(st["description"]).style("color:var(--km-muted)")
            for label, value in ((t("city.cost_2"), st["cost_raw"]),
                                 (t("main.construction"), st["construction"]["raw"] if st["construction"] else ""),
                                 (t("city.item_bonus_2"), st["item_bonus"]),
                                 (t("city.ruin_label"), st["ruin"]),
                                 (t("city.effects_label"), st["effects"])):
                if value:
                    ui.html(f'<div style="font-size:.85rem"><b>{theme.esc(label)}:</b> {theme.esc(value)}</div>')
            if st["upgrade_to"]:
                names = [rules.BY_ID["structure"][x]["name"] for x in st["upgrade_to"]
                         if x in rules.BY_ID["structure"]]
                ui.html(f'<div style="font-size:.85rem"><b>{theme.esc(t("city.upgrades_label"))}:</b> '
                        f'{theme.esc(", ".join(names))}</div>')

        @theme.requires(permissions.EDIT_KINGDOM)
        def empty() -> None:
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
            rubble_gid(block_, lot["gid"])
            theme.save_and_refresh()
            refresh()
            dlg.close()

        if st and not rubble:
            _lot_actions(sett, gi, bi, li, st, dlg, refresh)

        theme.sep()
        theme.title(t("city.lot_corrections"), 3)
        ui.label(t("city.lot_corrections_hint")).style("font-size:.75rem;color:var(--km-muted);white-space:normal")
        with ui.row().classes("gap-2 flex-wrap items-center w-full"):
            ui.button(t("city.empty_lot"), on_click=empty).props("dense flat color=red")
            if not rubble:
                ui.button(t("city.reduce_rubble"), on_click=to_rubble).props("dense flat color=orange")
            if st and rules.structure_effects(st):
                ui.button(t("city.apply_effects_kingdom"),
                          on_click=lambda: (dlg.close(), _effects_dialog(st, refresh))) \
                    .props("dense flat color=amber")
            ui.element("div").style("flex:1")
            ui.button(t("common.close"), on_click=dlg.close).props("flat color=amber")
    dlg.open()


def upgrade_cost(old: dict, new: dict) -> dict[str, int]:
    """An upgrade pays the new structure's cost minus the old one's, each
    resource on its own, never below 0."""
    a, b = old["cost"], new["cost"]
    return {p: max(0, b.get(p, 0) - a.get(p, 0)) for p in ("rp", "food", "lumber", "luxuries", "ore", "stone")}


def upgrade_room(block_: list[dict], li: int, gid, new: dict) -> list[int] | None:
    """The lots the upgrade would take, the old structure's counted free."""
    view = [{"structure": None, "gid": None} if l.get("gid") == gid else l for l in block_]
    return _free_contiguous_lots(view, li, new["lots"])


def _lot_actions(sett: dict, gi: int, bi: int, li: int, st: dict, dlg, refresh) -> None:
    """What can be done to a standing structure, in three sections: the
    upgrades it offers, its repair, and Demolish."""
    block_ = sett["grids"][gi][bi]
    lot = block_[li]
    damaged = bool(lot.get("damaged"))

    theme.sep()
    theme.title(t("city.lot_upgrade"), 3)
    upgrades = [rules.BY_ID["structure"][nid] for nid in st.get("upgrade_to") or ()
                if nid in rules.BY_ID["structure"]]
    if not upgrades:
        ui.label(t("city.lot_upgrade_none")).style("font-size:.8rem;color:var(--km-muted)")
    with ui.row().classes("gap-2 flex-wrap"):
        for new in upgrades:
            diff = upgrade_cost(st, new)
            room = upgrade_room(block_, li, lot["gid"], new)
            ok = room and new["level"] <= STATE.level and _can_pay(new, sett, diff)
            label = (t("city.upgrade_to", name=new["name"], cost=cost_text(diff)) if room
                     else t("city.upgrade_no_room", name=new["name"]))
            ui.button(label, on_click=lambda _e=None, n=new, d=diff: _build(
                n, sett, gi, bi, li, dlg, refresh, with_check=True, cost=d, replace_gid=lot["gid"])) \
                .props(f'dense outline color=amber {"" if ok else "disable"}')

    theme.sep()
    theme.title(t("city.lot_repair"), 3)
    ui.label(t("city.lot_repair_hint")).style("font-size:.75rem;color:var(--km-muted);white-space:normal")
    with ui.row().classes("gap-2 flex-wrap items-center"):
        if damaged:
            half = cost_of(st, sett, half=True)
            ui.button(t("city.repair_button", cost=cost_text(half)),
                      on_click=lambda: _build(st, sett, gi, bi, li, dlg, refresh, with_check=True,
                                              cost=half, replace_gid=lot["gid"],
                                              bonus=[(t("city.repair"), 2, "item")], repairing=True)) \
                .props(f'dense color=amber {"" if _can_pay(st, sett, half) else "disable"}')
        ui.button(t("city.mark_repaired") if damaged else t("city.mark_damaged"),
                  on_click=lambda: (_toggle_damaged(sett, block_, lot["gid"]), dlg.close(), refresh())) \
            .props("dense outline color=orange")

    theme.sep()
    theme.title(t("city.lot_demolish"), 3)
    ui.label(t("city.lot_demolish_hint")).style("font-size:.75rem;color:var(--km-muted);white-space:normal")
    why = STATE.activities_block(rules.BY_ID["activities"]["demolish"], settlement=sett["id"])
    ui.button(t("city.demolish_check"), on_click=lambda: _demolish(sett, gi, bi, li, dlg, refresh)) \
        .props(f'dense outline color=red {"disable" if why else ""}').tooltip(why or "")


@theme.requires(permissions.EDIT_KINGDOM)
def _toggle_damaged(sett: dict, block_: list[dict], gid) -> None:
    """A structure damaged by an event, or mended by hand: every lot of it."""
    lots = gid_lots(block_, gid)
    if not lots:
        return
    on = not block_[lots[0]].get("damaged")
    for idx in lots:
        if on:
            block_[idx]["damaged"] = True
        else:
            block_[idx].pop("damaged", None)
    st = rules.BY_ID["structure"].get(block_[lots[0]].get("structure") or "") or {}
    STATE.record(t("city.journal_damaged" if on else "city.journal_mended",
                   name=sett["name"], structure=st.get("name", "")), "settlement")
    theme.save_and_refresh()


@theme.requires(permissions.EDIT_KINGDOM)
def _demolish(sett: dict, gi: int, bi: int, li: int, dlg, refresh) -> None:
    """Demolish: a Civic activity, an Engineering check. A critical success
    clears the whole structure (a single lot salvages 1d6 Lumber, Stone or
    Ore), a success this lot, a failure leaves it Rubble; a critical failure
    adds 1 Unrest. A structure being demolished stops working."""
    act = rules.BY_ID["activities"]["demolish"]
    why = STATE.activities_block(act, settlement=sett["id"])
    if why:
        theme.notify(why, "warning")
        return
    block_ = sett["grids"][gi][bi]
    gid = block_[li].get("gid")
    single = len(gid_lots(block_, gid)) == 1
    skill = "magic" if ("practical_magic" in STATE.k["feats"]
                        and STATE.skill_mod("magic") > STATE.skill_mod("engineering")) else "engineering"
    dc = STATE.activity_dc("demolish")[0]
    STATE.mark_activity("demolish", settlement=sett["id"], skill=skill)
    dlg.close()

    def roll() -> rules.Result:
        res = STATE.kingdom_check(skill, dc, "demolish", settlement=sett["id"])
        STATE.note_grade("demolish", res.grade)
        return res

    def apply(res: rules.Result) -> None:
        demolish_result(block_, li, res.grade)
        STATE.record(t("city.demolish_journal", name=sett["name"], grade=rules.grade_label(res.grade)),
                     "settlement")
        theme.save_and_refresh()
        refresh()
        if res.grade == "critical_success" and single:
            turn.propose_rows(lambda: rules.BY_ID["activities"]["demolish"]["name"],
                              [{"t": "commodity_choice", "q": "1d6", "auto": True, "text": t("city.salvage")}],
                              context={"act": "demolish"})
        elif res.grade == "critical_failure":
            turn.propose_rows(lambda: rules.BY_ID["activities"]["demolish"]["name"],
                              [{"t": "unrest", "q": "1", "auto": True}], context={"act": "demolish"})

    theme.show_check(roll(), lambda: rules.BY_ID["activities"]["demolish"]["name"],
                     lambda res: rules.BY_ID["activities"]["demolish"]["outcomes"].get(res.grade, ""),
                     apply=apply, reroll=roll)


def demolish_result(block_: list[dict], li: int, grade: str) -> None:
    """What a Demolish check does to the lots: the whole structure cleared on
    a critical success; this lot cleared on a success, Rubble on a failure,
    the structure's other lots marked as being demolished (they stop working
    and wait for the next Demolish)."""
    gid = block_[li].get("gid")
    lots = gid_lots(block_, gid)
    if grade == "critical_success":
        for idx in lots:
            block_[idx] = {"structure": None, "gid": None}
        return
    for idx in lots:
        if idx != li:
            block_[idx]["demolishing"] = True
    if grade == "success":
        block_[li] = {"structure": None, "gid": None}
    else:
        block_[li] = {"structure": "rubble", "gid": uuid.uuid4().hex[:6]}


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

        @theme.requires(permissions.EDIT_KINGDOM)
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


def _border_lines(sett: dict) -> None:
    """The walls and bridges standing on the borders, and what the borders
    mean: an island (Influence 0), no land border (−1 Trade)."""
    walls = sett.get("border_walls") or {}
    bridges = sett.get("border_bridges") or {}
    for side in SIDES:
        bits = []
        if walls.get(side):
            bits.append(t(f"city.wall_{walls[side]}"))
        if bridges.get(side):
            bits.append(rules.BY_ID["structure"]["bridge"]["name"])
        if bits:
            ui.label(t("city.border_line", side=t(f"city.side.{side}"), what=", ".join(bits))) \
                .style("font-size:.75rem;color:var(--km-gold-dim)")
    chips = []
    if STATE.water_only(sett) and not STATE.has_bridge(sett):
        chips.append(t("city.island_chip"))
    if STATE.no_land_border(sett):
        chips.append(t("city.no_land_border_chip"))
    if chips:
        ui.html(" ".join(f'<span class="km-chip km-fc" style="font-size:.7rem">{theme.esc(c)}</span>'
                         for c in chips))


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

        with ui.row().classes("w-full items-start gap-4 no-wrap km-split"):
            # ------------------------------------- left: the settlement
            with ui.column().classes("gap-3").style("flex:1 1 0;min-width:340px"):
                with ui.card().classes("km-panel w-full"):
                    with ui.row().classes("items-center w-full no-wrap"):
                        theme.title(t("city.settlement_title"), 2)
                        ui.element("div").style("flex:1")
                        ui.button(t("city.new_button"), icon="add",
                                  on_click=lambda: _new_settlement_dialog(content_)) \
                            .props("dense outline color=amber")
                    ui.select({i["id"]: (i["name"] + (" ★" if i["capital"] else "")
                                         + ("" if i.get("hex") else t("city.off_map")))
                               for i in k["settlements"]},
                              value=ui_state["sel"],
                              on_change=lambda e: (ui_state.update(sel=e.value, grid=0), content_.refresh())) \
                        .props("outlined dense").classes("w-full")

                    # The card in sections, each with its title: where the
                    # settlement stands, its figures, its lots, what can be done.
                    theme.sep()
                    theme.title(t("city.section_position"), 3)
                    _position_block(sett, content_)

                    theme.sep()
                    theme.title(t("city.section_figures"), 3)
                    counts = STATE.lot_detail(sett)
                    with ui.row().classes("gap-2 flex-wrap items-center"):
                        theme.stat_box(kind["name"], t("city.type"))
                        theme.stat_box(STATE.settlement_level(sett), t("city.level"),
                                       t("city.equal_blocks_least_one"))
                        theme.stat_box(STATE.settlement_consumption(sett), t("city.consumption"),
                                       t("city.consumption_tip"))
                        theme.stat_box(f'+{kind["item_bonus_max"]}', t("city.max_item_bonus"))
                        theme.stat_box(kind["influence"], t("city.influence"))
                    # Consumption the structures do not explain (an event, a
                    # ruling): added by hand to this settlement's.
                    ui.number(t("city.consumption_adjust"), value=sett.get("consumption_extra", 0), format="%d",
                              on_change=lambda e: (_set_field(sett, "consumption_extra", int(e.value or 0)),
                                                   theme.save_and_refresh())) \
                        .props("outlined dense").classes("w-48")
                    ui.label(t("city.approximate_population", population=kind["population"])) \
                        .style("font-size:.78rem;color:var(--km-muted)")

                    theme.sep()
                    theme.title(t("city.section_lots"), 3)
                    _overcrowding_block(sett, counts)

                    theme.sep()
                    theme.title(t("city.section_actions"), 3)
                    ok, msg = _can_expand(sett)
                    ui.button((t("city.expand") if ok else t("city.expansion_blocked")),
                              on_click=lambda: _expand(sett) or content_.refresh()) \
                        .props(f'dense color={"amber" if ok else "grey"} {"" if ok else "disable"}') \
                        .classes("w-full")
                    ui.label(msg).style("font-size:.75rem;color:var(--km-muted)")
                    with ui.row().classes("gap-1 items-center w-full"):
                        if not sett["capital"]:
                            ui.button(t("city.make_capital"), on_click=lambda: _make_capital(sett, content_)) \
                                .props("dense flat color=amber")
                        ui.element("div").style("flex:1")
                        ui.button(t("city.remove_settlement_2"),
                                  on_click=lambda: _confirm_city_removal(sett, content_)) \
                            .props("dense flat color=red")



            # ------------------------------------- middle: the Urban Grid
            with ui.column().classes("gap-2").style("flex:2 1 0;min-width:0"):
                with ui.row().classes("items-center gap-3"):
                    theme.title(t("city.urban_grid", name=sett["name"]), 1)
                    if len(sett["grids"]) > 1:
                        ui.select({i: t("city.grid", v=i + 1) for i in range(len(sett["grids"]))},
                                  value=ui_state["grid"],
                                  on_change=lambda e: (ui_state.update(grid=e.value), content_.refresh())) \
                            .props("outlined dense").classes("w-40")
                # The grid is nine blocks of four lots: its borders and the structures
                # standing sit beside it, where the room was empty.
                with ui.row().classes("w-full gap-4 items-start flex-wrap"):
                    with ui.column().classes("gap-2").style("flex:0 0 auto;width:440px;max-width:100%"):
                        _draw_grid(sett, ui_state["grid"], content_.refresh)
                        ui.label(t("city.every_urban_grid_has")) \
                            .style("font-size:.78rem;color:var(--km-muted)")
                    with ui.column().classes("gap-3").style("flex:1 1 300px;min-width:0"):
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

                        with ui.card().classes("km-panel w-full"):
                            theme.title(t("city.grid_borders"), 3)
                            for side in ("north", "south", "east", "west"):
                                ui.select({"land": t("city.land_border"), "water": t("city.water_border"),
                                           "walls": t("city.walled_border")},
                                          label=t(f"city.side.{side}"), value=sett["borders"][side],
                                          on_change=lambda e, l=side: (_set_field(sett["borders"], l, e.value),
                                                                       theme.save_and_refresh())) \
                                    .props("outlined dense").classes("w-full")
                            ui.label(t("city.settlement_without_land_borders")) \
                                .style("font-size:.72rem;color:var(--km-muted)")
                            _border_lines(sett)

    content_()
    theme.register_refresh("city.content", content_)


@theme.requires(permissions.EDIT_KINGDOM)
def _new_settlement_fields(refresh, after=None) -> None:
    """The fields that found a settlement: a name, and where it stands."""
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
        if after:
            after()
        refresh.refresh() if hasattr(refresh, "refresh") else refresh()

    ui.button(t("city.found_village"), on_click=create).props("dense color=amber")


def _new_form(refresh) -> None:
    """The form on the page: only while the kingdom has no settlement at all."""
    with ui.card().classes("km-panel w-full"):
        theme.title(t("city.new_settlement"), 3)
        _new_settlement_fields(refresh)


def _new_settlement_dialog(refresh) -> None:
    """The same form in a window, from the «New…» button of the settlement's card."""
    with theme.dialog() as dlg, ui.card().classes("km-panel").style("min-width:380px"):
        theme.title(t("city.new_settlement"), 2)
        _new_settlement_fields(refresh, after=dlg.close)
        ui.button(t("common.cancel"), on_click=dlg.close).props("flat")
    dlg.open()


def _draw_grid(sett: dict, gi: int, refresh) -> None:
    grid = sett["grids"][gi]
    active_ones = sett["active_blocks"] if (gi == 0 and sett["kind"] != "metropolis") else list(range(9))
    if sett["kind"] == "metropolis":
        active_ones = list(range(9))

    with ui.element("div").style(
            "display:grid;grid-template-columns:repeat(3,1fr);gap:8px;"
            "width:100%;max-width:640px;padding:10px;background:#120f0b;border:1px solid var(--km-line);"
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
                    if lot.get("demolishing"):
                        el.style("opacity:.45;background:repeating-linear-gradient(45deg,#332a20,"
                                 "#332a20 4px,#241d15 4px,#241d15 8px)")
                    elif lot.get("damaged"):
                        el.style("border-color:var(--km-red);box-shadow:inset 0 0 0 1px var(--km-red)")
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
