# -*- coding: utf-8 -*-
"""City rules (2.3.0 D): costs, upgrades, repair, failed construction, Demolish,
borders and walls, an Edifice once per settlement.

Sections 1-6 work on a kingdom built in memory; section 7 builds, repairs and
retries in a simulated window of the real app, with the die fixed.
"""
import asyncio
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ["NICEGUI_USER_SIMULATION"] = "true"

import httpx  # noqa: E402
from nicegui import core, ui  # noqa: E402
from nicegui.testing.general import prepare_simulation  # noqa: E402
from nicegui.testing.user import User  # noqa: E402

prepare_simulation()
from kingmaker import main, rules  # noqa: E402,F401
from kingmaker.access import auth  # noqa: E402
from kingmaker.state import STATE, new_kingdom  # noqa: E402
from kingmaker.ui.tabs import city  # noqa: E402

results = []
saved_kingdom, saved_check, saved_roll = STATE.k, rules.roll_check, rules.roll
B = rules.BY_ID["structure"]


def build(sett, *structures, block=4):
    """These structures, one lot each (a two-lot one takes two), in one block."""
    grid = sett["grids"][0]
    for b, block_ in enumerate(grid):
        grid[b] = [{"structure": None, "gid": None} for _ in block_]
    i = 0
    for n, sid in enumerate(structures):
        for _ in range(B[sid]["lots"]):
            grid[block][i] = {"structure": sid, "gid": f"g{n}"}
            i += 1


def fixed(grade):
    rules.roll_check = lambda mod, dc, detail=None, worsens_by=0: rules.Result(
        10, mod, 10 + mod, dc, grade, detail or [])


STATE.k = new_kingdom()
k = STATE.k
try:
    for role in k["roles"].values():
        role["name"] = "Leader"
    town = city.new_settlement("Riverhold", (3, 3))
    port = city.new_settlement("Saltmere", (8, 8))
    k["settlements"] += [town, port]
    k["capital"] = town["id"]

    # --- 1. costs and upgrades ---------------------------------------------------
    k["commodities"].update(lumber=5, stone=1)
    bridge = city.cost_of(B["bridge"])
    results.append(("«Lumber or Stone»: paid in the one the kingdom has more of",
                    bridge["lumber"] == 1 and bridge["stone"] == 0 and bridge["rp"] == 6))
    half = city.cost_of(B["watchtower"], half=True)
    results.append(("half a cost rounds up", half["rp"] == 6 and half["lumber"] == 2))
    diff = city.upgrade_cost(B["houses"], B["mansion"])
    results.append(("an upgrade pays the difference", diff["rp"] == 7 and diff["lumber"] == 5
                    and diff["luxuries"] == 6))
    cheaper = city.upgrade_cost(B["academy"], B["military_academy"])
    results.append(("never below 0", min(cheaper.values()) == 0 and cheaper["ore"] == 6))
    build(town, "herbalist", "houses", "houses", "houses")
    block_ = town["grids"][0][4]
    results.append(("an upgrade needing a second lot is refused in a full block",
                    city.upgrade_room(block_, 0, "g0", B["hospital"]) is None))
    build(town, "herbalist")
    block_ = town["grids"][0][4]
    results.append(("and allowed with a free lot beside", city.upgrade_room(block_, 0, "g0", B["hospital"]) == [0, 1]))

    # --- 2. repair -------------------------------------------------------------------
    detail = dict(STATE.check_detail("industry", "build_structure", "herbalist", settlement=town["id"],
                                     extra=[("Repairing", 2, "item")]))
    results.append(("Repair's +2 item in the breakdown", detail.get("Repairing") == 2))
    build(town, "town_hall")
    block_ = town["grids"][0][4]
    city.rubble_gid(block_, "g0")
    results.append(("a critical failure while repairing: the whole structure to Rubble",
                    [l["structure"] for l in block_[:2]] == ["rubble", "rubble"]
                    and block_[0]["gid"] == block_[1]["gid"]))

    # --- 3. a failed construction's free retry ----------------------------------------
    lot = {"structure": None, "gid": None, "failed": {"structure": "granary", "turn": k["turn"]}}
    results.append(("retried the same turn: free", city.build_cost(B["granary"], town, lot)[0] == {"rp": 0}))
    k["turn"] += 1
    results.append(("retried next turn: still free", city.retry_free(lot, B["granary"])))
    results.append(("another structure there: full price",
                    city.build_cost(B["inn"], town, lot)[0]["rp"] == B["inn"]["cost"]["rp"]))
    k["turn"] += 1
    results.append(("two turns later it pays", city.build_cost(B["granary"], town, lot)[0]["rp"] == 12))

    # --- 4. Demolish ---------------------------------------------------------------------
    for grade, expect in (("critical_success", [None, None]), ("success", [None, "town_hall"]),
                          ("failure", ["rubble", "town_hall"])):
        build(town, "town_hall")
        block_ = town["grids"][0][4]
        city.demolish_result(block_, 0, grade)
        results.append((f"Demolish {grade} on a two-lot structure",
                        [l["structure"] for l in block_[:2]] == expect))
    build(town, "town_hall")
    block_ = town["grids"][0][4]
    city.demolish_result(block_, 0, "success")
    results.append(("a structure being demolished stops working", "town_hall" not in STATE.structures_of(town)))

    # --- 5. borders ----------------------------------------------------------------------
    town["borders"] = {s: "land" for s in city.SIDES}
    port["borders"] = {s: "water" for s in city.SIDES}
    port["kind"] = "town"                  # a village's influence is its own hex anyway
    trade = dict(STATE.check_detail("trade"))
    results.append(("a settlement without a land border: -1 item to Trade",
                    any(v == -1 for n, v in trade.items() if "land border" in n)))
    results.append(("an island: Influence 0", STATE.influence_of(port) == {(8, 8)}))
    port["border_bridges"] = {"east": True}
    trade = dict(STATE.check_detail("trade"))
    results.append(("a bridge over a water border: no Trade penalty",
                    not any("land border" in n for n in trade)))
    for x in range(7, 10):
        for y in range(7, 10):
            STATE.hex(x, y)["status"] = "claimed"
    results.append(("and the island's influence comes back", len(STATE.influence_of(port)) > 1))
    town["border_walls"] = {}
    build(town, "wooden_wall")
    town["borders"] = {s: "walls" for s in city.SIDES}
    results.append(("four walled borders are land borders: no Trade penalty, no island",
                    not STATE.no_land_border(town) and not STATE.water_only(town)))
    town["borders"] = {s: "water" for s in city.SIDES}
    results.append(("four water borders: the penalty", STATE.no_land_border(town)))
    town["borders"] = {s: "land" for s in city.SIDES}
    town["border_walls"] = {"north": "wooden"}
    results.append(("a stone wall upgraded from a wooden one goes on the wooden wall's border",
                    city.side_options(town, B["stone_wall"], upgraded_from="wooden_wall") == ["north"]))
    results.append(("built anew, it may go on any border",
                    city.side_options(town, B["stone_wall"]) == list(city.SIDES)))
    town["border_walls"] = {}
    results.append(("a wooden wall may go on any border", len(city.wall_sides(town, B["wooden_wall"])) == 4))
    town["border_walls"] = {"north": "wooden"}
    results.append(("but not twice on one", "north" not in city.wall_sides(town, B["wooden_wall"])))
    results.append(("a stone wall may replace it there", "north" in city.wall_sides(town, B["stone_wall"])))
    build(town, "wooden_wall", "wooden_wall")
    results.append(("a second wooden wall is not the first of its kind (no -1 Unrest)",
                    STATE.structures_of(town).get("wooden_wall") == 2))

    # --- 6. an Edifice counts once ----------------------------------------------------------
    # The Edifice trait (id "building": the ids read crossed) is on the big
    # works; the Mint's item bonus to Collect Taxes (or any Edifice's) counts once.
    edifice = B["keep"]                    # +1 item to Deploy Army, two lots
    town["kind"] = "city"                  # room for +2, so stacking would show
    build(town, "keep")
    one = STATE.item_bonus("deploy_army", settlement=town["id"])
    build(town, "keep", "keep")
    two = STATE.item_bonus("deploy_army", settlement=town["id"])
    results.append((f"two of an Edifice ({edifice['id']}) give its item bonus once", one and two and one[1] == two[1]))
    results.append(("and the dialog says it is built already", city.edifice_built(town, edifice)))
    build(town, "granary", "granary")
    results.append(("a Granary is no Edifice: two still raise Food storage twice",
                    not city.edifice_built(town, B["inn"]) and STATE.storage("food") == STATE.size_entry()["storage"] + 2
                    + STATE.k["storage_extra"].get("food", 0)))
finally:
    STATE.k = saved_kingdom
    rules.roll_check = saved_check
    rules.roll = saved_roll


# --- 7. in a window: a repair, a failed build and its free retry ------------------------
accounts = {u["username"]: u for u in STATE.archive.list_users()}
auth.id_in_session = lambda: accounts["admin"]["id"]
ui.run(storage_secret="simulated secret", reload=False, show=False)


class Dialog:
    def close(self):
        pass


async def window_run() -> None:
    async with core.app.router.lifespan_context(core.app):
        user = User(httpx.AsyncClient(transport=httpx.ASGITransport(core.app), base_url="http://test"))
        await user.open("/")
        k = STATE.k
        try:
            sett = k["settlements"][0]
            grid = sett["grids"][0]
            bi = sett["active_blocks"][0]
            grid[bi] = [{"structure": "inn", "gid": "r1", "damaged": True},
                        {"structure": None, "gid": None}, {"structure": None, "gid": None},
                        {"structure": None, "gid": None}]
            k["rp"], k["turn_civic"], k["turn_activities"] = 100, {}, {}
            k["commodities"].update(lumber=20, stone=20, luxuries=20, ore=20)
            k["fame_points"] = 0               # no reroll offer: the result applies at once
            fixed("success")
            half = city.cost_of(B["inn"], sett, half=True)
            with user.client:
                city._build(B["inn"], sett, 0, bi, 0, Dialog(), lambda: None, True, cost=half,
                            replace_gid="r1", bonus=[("Repairing", 2, "item")], repairing=True)
            results.append(("a repair's success mends the structure",
                            not grid[bi][0].get("damaged") and grid[bi][0]["structure"] == "inn"))
            results.append(("at half the cost", k["rp"] == 100 - half["rp"]))
            k["turn_civic"], k["turn_activities"] = {}, {}
            fixed("failure")
            with user.client:
                city._build(B["granary"], sett, 0, bi, 1, Dialog(), lambda: None, True)
            results.append(("a failed build marks the lot", (grid[bi][1].get("failed") or {}).get("structure") == "granary"))
            k["turn_civic"], k["turn_activities"] = {}, {}
            rp = k["rp"]
            fixed("success")
            with user.client:
                city._build(B["granary"], sett, 0, bi, 1, Dialog(), lambda: None, True)
            results.append(("its retry pays nothing and builds", k["rp"] == rp and grid[bi][1]["structure"] == "granary"))
        finally:
            rules.roll_check = saved_check
            user.client.delete()


asyncio.run(window_run())

for name, ok in results:
    print(f" {'ok' if ok else 'NO'}  {name}")
print(f"{sum(1 for _n, ok in results if ok)}/{len(results)} passed")
