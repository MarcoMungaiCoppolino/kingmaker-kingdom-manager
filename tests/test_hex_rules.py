# -*- coding: utf-8 -*-
"""Map and hex rules (2.3.0 E): claim effects, work sites, roads over a river,
Irrigation, Ruins and Structure features, losing and abandoning hexes,
secondary territories.

Sections 1-7 work on a kingdom built in memory (a river's banks go to the
test scene's archive and are taken back); section 8 draws the Turn column
in a simulated window of the real app.
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
from kingmaker.access import auth, view  # noqa: E402
from kingmaker.state import STATE, new_kingdom  # noqa: E402
from kingmaker.ui.hexmap import hex_panel  # noqa: E402
from kingmaker.ui.tabs import city, turn  # noqa: E402

results = []
saved_kingdom, saved_check, saved_roll = STATE.k, rules.roll_check, rules.roll


def claim(*cells):
    for c, r in cells:
        STATE.hex(c, r)["status"] = "claimed"


# --- 0. a player receives the irrigation (on the scene's own kingdom) -------------
player = next(u for u in STATE.archive.list_users() if u["username"] == "player")
sight = view.MapView(auth._from_row(player), STATE)
seen = next(((c, r) for (c, r) in sorted(STATE.archive.visible_to_party(STATE.campaign))
             if STATE.existing_hex(c, r)), None)
if seen:
    STATE.existing_hex(*seen)["irrigated"] = "lake"
    results.append(("«irrigated» is a public field: a player's hex carries it",
                    "irrigated" in view.PUBLIC_FIELDS and (sight.hex_for(*seen) or {}).get("irrigated") == "lake"))
    STATE.existing_hex(*seen).pop("irrigated", None)
else:
    # The scene always shows the party some hexes: none means an earlier
    # test left it empty, and this check must not pass by being skipped.
    results.append(("«irrigated» is a public field: the scene shows the party no hex", False))

STATE.k = new_kingdom()
k = STATE.k
try:
    for role in k["roles"].values():
        role["name"] = "Leader"
    town = city.new_settlement("Riverhold", (5, 5))
    k["settlements"].append(town)
    k["capital"] = town["id"]
    STATE.hex(5, 5)["settlement"] = town["id"]
    claim((5, 5), (5, 6), (6, 5))

    # --- 1. a Landmark's and a Refuge's claim effects --------------------------------
    rules.roll = lambda n, faces: (3, [3])
    k["unrest"] = 5
    for row in rules.BY_ID["feature"]["landmark"]["claim_effects"]:
        value = row["v"] if row["t"] == "mod" else rules.signed_value(row["q"])[0]
        STATE.apply_effect(row, value, None, None, {"hex": (5, 6)})
    names = [m["name"] for m in STATE.active_modifiers(ability="culture")] + \
            [m["name"] for m in STATE.active_modifiers(ability="economy")]
    results.append(("a Landmark: -1d4 Unrest, +2 to Culture and Economy until next turn",
                    k["unrest"] == 2 and len(names) == 2
                    and all(m["expiry"] == k["turn"] + 1 for m in k["modifiers"])))
    k["ruins"]["crime"]["points"] = 3
    for row in rules.BY_ID["feature"]["refuge"]["claim_effects"]:
        value = row["v"] if row["t"] == "mod" else rules.signed_value(row["q"])[0]
        STATE.apply_effect(row, value, "crime", None, {"hex": (5, 6)})
    results.append(("a Refuge: a Ruin -1, +2 to Loyalty and Stability",
                    k["ruins"]["crime"]["points"] == 2 and STATE.active_modifiers(ability="loyalty")
                    and STATE.active_modifiers(ability="stability")))
    rules.roll = saved_roll
    k["modifiers"] = []

    # --- 2. work sites -------------------------------------------------------------
    h = STATE.hex(5, 6)
    h["terrains"] = ["plains"]
    results.append(("a lumber camp is refused on plains", not hex_panel.site_terrain_ok(h, "lumber")))
    h["terrains"] = ["forest"]
    results.append(("and allowed in a forest", hex_panel.site_terrain_ok(h, "lumber")))
    h["terrains"] = ["hills"]
    results.append(("a mine in hills", hex_panel.site_terrain_ok(h, "ore")))
    site = {"commodity": "ore", "doubled": False, "rich_until_turn": k["turn"] + 1}
    yields = [turn.site_yield(site)]
    k["turn"] += 1
    yields.append(turn.site_yield(site))
    k["turn"] += 1
    yields.append(turn.site_yield(site))
    results.append(("a critical success doubles the yield this turn and next, not after", yields == [2, 2, 1]))

    # --- 3. roads over a river --------------------------------------------------------
    road = STATE.hex(6, 5)
    road["terrains"] = ["plains"]
    STATE.archive.set_banks(STATE.campaign, (6, 5), [[[0, 0]], [[1, 1]]])
    try:
        cost, river = hex_panel.roads_cost(road)
        results.append(("a river across the hex doubles Build Roads", river and cost == 2 * hex_panel._cost(road)))
        road["features"].append({"kind": "bridge", "name": ""})
        cost, river = hex_panel.roads_cost(road)
        results.append(("not with a Bridge already there", not river and cost == hex_panel._cost(road)))
    finally:
        STATE.archive.set_banks(STATE.campaign, (6, 5), [])
    # Build Roads' critical success: a second, adjacent hex, claimed, without
    # roads and no less hospitable (its terrain costs no more to build on).
    from kingmaker.geometry import hexgrid
    far = STATE.hex(25, 20)            # away from the hexes the sections below use
    far.update(status="claimed", terrains=["plains"], roads=True)
    near = list(hexgrid.neighbours(25, 20, STATE.orientation))
    easy, steep, paved, wild = (STATE.hex(*pos) for pos in near[:4])
    for h_ in (easy, steep, paved):
        h_["status"] = "claimed"
    easy.update(terrains=["plains"], roads=False)
    steep.update(terrains=["forest"], roads=False)
    paved.update(terrains=["plains"], roads=True)
    wild.update(status="cleared", terrains=["plains"], roads=False)
    partners = [(p["col"], p["row"]) for p in hex_panel.road_partners(far)]
    results.append(("the second hex of Build Roads: claimed, no roads, as hospitable, nothing else",
                    partners == [(easy["col"], easy["row"])]))

    # --- 4. Irrigation -------------------------------------------------------------------
    irr = rules.BY_ID["activities"]["irrigation"]
    pending_row = irr["effects"]["critical_failure"][1]
    STATE.apply_effect(pending_row, 0, None, None, {"act": "irrigation", "hex": (5, 6)})
    results.append(("a critical failure leaves a Plague check on that hex",
                    any(e["source"] == "irrigation" for e in k["turn_memory"]["pending"])))
    hex_panel.irrigate(STATE.hex(5, 6), "river")
    results.append(("a later success irrigates the hex and takes the check back",
                    STATE.hex(5, 6)["irrigated"] == "river" and not k["turn_memory"]["pending"]))

    # --- 5. Ruins and Structure features -----------------------------------------------------
    inn = rules.BY_ID["structure"]["inn"]
    STATE.hex(5, 5)["features"].append({"kind": "ruins_feature", "name": inn["name"], "structure": "inn"})
    cost, why = city.build_cost(inn, town, {"structure": None, "gid": None})
    results.append(("Ruins of an Inn on the hex: the Inn costs half", why == "city.ruins_half"
                    and cost["rp"] == (inn["cost"]["rp"] + 1) // 2))
    STATE.hex(5, 5)["features"][-1]["used"] = True
    results.append(("once", city.build_cost(inn, town, {"structure": None, "gid": None})[1] == ""))
    founded = city.new_settlement("Newstead", (6, 5))
    STATE.hex(6, 5)["features"].append({"kind": "structure", "name": "Shrine", "structure": "shrine"})
    hex_panel.place_structure_features(STATE.hex(6, 5), founded)
    results.append(("a Structure feature stands, free, in a settlement founded there",
                    "shrine" in STATE.structures_of(founded)))

    # --- 6. losing and abandoning a hex -----------------------------------------------------------
    second = city.new_settlement("Hillfort", (5, 6))
    k["settlements"].append(second)
    STATE.hex(5, 6)["settlement"] = second["id"]
    STATE.hex(5, 6)["farmland"] = True
    size = STATE.size_
    rows = hex_panel.abandon_rows("failure", [(5, 6)])
    unrest = next(r for r in rows if r["t"] == "unrest")
    results.append(("Abandon Hex's Unrest doubles with a settlement on the hex", unrest["q"] == "4"))
    results.append(("and its rows unclaim the hexes", rows[-1]["t"] == "unclaim"))
    left = STATE.unclaim_hex(5, 5)
    free = next(f for f in STATE.hex(5, 5)["features"] if f["kind"] == "freehold")
    results.append(("an unclaimed hex: its settlement becomes a freehold that remembers it",
                    left is town and free["settlement_data"]["id"] == town["id"]
                    and town not in k["settlements"]))
    results.append(("the capital moves to another settlement", k["capital"] == second["id"]))
    results.append(("and Size drops by one", STATE.size_ == size - 1))

    # --- 7. secondary territories ------------------------------------------------------------------
    k["capital"] = second["id"]
    claim((5, 6), (6, 6), (9, 9))
    secondary = STATE.secondary_hexes()
    results.append(("a claimed hex reached only across unclaimed ground is secondary",
                    (9, 9) in secondary and (6, 6) not in secondary))
    detail = dict(STATE.check_detail("trade", "establish_work_site", hex_=(9, 9)))
    results.append(("-4 to a check there", detail.get("Secondary territory") == -4))
    k["capital"] = None
    results.append(("no capital: no secondary territory", STATE.secondary_hexes() == set()))
finally:
    STATE.k = saved_kingdom
    rules.roll_check = saved_check
    rules.roll = saved_roll


# --- 8. in a window: the kingdom at 0 hexes -----------------------------------------------
accounts = {u["username"]: u for u in STATE.archive.list_users()}
auth.id_in_session = lambda: accounts["admin"]["id"]
ui.run(storage_secret="simulated secret", reload=False, show=False)


def texts(element) -> str:
    out = str(getattr(element, "text", "") or "") + str(getattr(element, "content", "") or "")
    for slot in element.slots.values():
        for child in slot.children:
            out += texts(child)
    return out


async def window_run() -> None:
    async with core.app.router.lifespan_context(core.app):
        user = User(httpx.AsyncClient(transport=httpx.ASGITransport(core.app), base_url="http://test"))
        await user.open("/")
        saved = STATE.k
        try:
            STATE.k = new_kingdom()
            STATE.k["created"] = True
            with user.client:
                with ui.element("div") as box:
                    turn._turn_column()
            results.append(("a kingdom at 0 hexes is told to refound", "holds no hex" in texts(box)))
            STATE.k["hexes"]["1,1"] = {"col": 1, "row": 1, "status": "claimed"}
            with user.client:
                with ui.element("div") as box:
                    turn._turn_column()
            results.append(("and not with a hex", "holds no hex" not in texts(box)))
        finally:
            STATE.k = saved
            user.client.delete()


asyncio.run(window_run())

for name, ok in results:
    print(f" {'ok' if ok else 'NO'}  {name}")
print(f"{sum(1 for _n, ok in results if ok)}/{len(results)} passed")
