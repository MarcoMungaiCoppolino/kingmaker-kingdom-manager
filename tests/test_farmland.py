# -*- coding: utf-8 -*-
"""Farmland and Consumption, by the book: a Farmland hex reduces Consumption
only inside a settlement's influence, Establish Farmland requires a hex in it,
and a critical success adds a second, adjacent Farmland hex.

The influence is the settlement's type: a village's is its own hex, a town's
reaches the adjacent ones, and unclaimed hexes are never in it. A table had a
Farmland hex next to its village and read «farmland 0»: the count was right,
and what was missing was saying why — `farms_outside`.

Sections 1–5 work on a kingdom built in memory; section 6 runs the activity
in a simulated window of the real app (NiceGUI's user simulation, no
browser), on the test scene, with the die fixed on a critical success.
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
from kingmaker.geometry import hexgrid  # noqa: E402
from kingmaker.state import STATE, new_kingdom  # noqa: E402
from kingmaker.ui.hexmap import hex_panel  # noqa: E402
from kingmaker.ui.tabs.city import new_settlement  # noqa: E402

results = []
saved_kingdom = STATE.k
STATE.k = new_kingdom()
VILLAGE = (5, 5)
ring = hexgrid.neighbours(*VILLAGE, STATE.orientation)


def hex_(pos, status="claimed", terrains=("plains",), farmland=False):
    h = STATE.hex(*pos)
    h.update(status=status, terrains=list(terrains), farmland=farmland)
    return h


try:
    village = new_settlement("Novadomus", VILLAGE)
    STATE.k["settlements"].append(village)
    hex_(VILLAGE)["settlement"] = village["id"]
    for pos in ring:
        hex_(pos)

    # --- 1. a village influences its own hex only --------------------------
    results.append(("a village's influence is its own hex", STATE.influenced_hexes() == {VILLAGE}))
    results.append(("so the hex next to it is not in influence", not STATE.in_influence(*ring[0])))

    # --- 2. Farmland next to a village: on the map, not in the Consumption --
    hex_(ring[0], farmland=True)
    cons = STATE.consumption()
    results.append(("a village's Consumption is 1", cons["settlements"] == 1 and cons["total"] == 1))
    results.append(("Farmland out of influence does not count", cons["farms"] == 0))
    results.append(("and it is reported as outside", cons["farms_outside"] == 1))

    # --- 3. the village grows into a town: the same field now counts -------
    village["kind"] = "town"
    cons = STATE.consumption()
    results.append(("a town influences the adjacent hexes",
                    STATE.influenced_hexes() == {VILLAGE, *ring}))
    results.append(("the Farmland next to a town counts",
                    cons["farms"] == 1 and cons["farms_outside"] == 0))
    results.append(("and reduces the town's Consumption of 2 to 1", cons["total"] == 1))

    # --- 4. unclaimed hexes are never in influence ---------------------------
    hex_(ring[1], status="reconnoitered", farmland=True)
    cons = STATE.consumption()
    results.append(("an unclaimed hex is out of influence", not STATE.in_influence(*ring[1])))
    results.append(("Farmland on an unclaimed hex is not the kingdom's",
                    cons["farms"] == 1 and cons["farms_outside"] == 0))
    hex_(ring[1], status="claimed", farmland=False)

    # --- 5. the second hex of a critical success -----------------------------
    # From ring[2]: its neighbours include the village and two hexes of the
    # ring; the rest lie outside the town's influence.
    start = ring[2]
    hex_(start, farmland=True)
    around = set(hexgrid.neighbours(*start, STATE.orientation))
    partners = {(h["col"], h["row"]) for h in STATE.farmland_partners(*start, hills=False)}
    expected = {p for p in around if p in set(ring) and p not in (ring[0],)}
    results.append(("partners are adjacent, claimed and in influence",
                    partners and partners <= around and partners <= set(ring)))
    results.append(("never the settlement's own hex", VILLAGE not in partners))
    results.append(("never a hex that is Farmland already",
                    ring[0] not in partners and partners == expected - {ring[0]}))
    for pos in around - {VILLAGE}:
        if pos not in set(ring):
            hex_(pos)               # claimed, but beyond the town's reach
    results.append(("never a claimed hex outside influence",
                    {(h["col"], h["row"]) for h in STATE.farmland_partners(*start, hills=False)} == partners))

    some = sorted(partners)[0]
    hex_(some, terrains=("forest",))
    results.append(("a forest hex is never a partner",
                    some not in {(h["col"], h["row"]) for h in STATE.farmland_partners(*start, hills=True)}))
    hex_(some, terrains=("hills",))
    results.append(("hills only when the attempt was in hills",
                    some not in {(h["col"], h["row"]) for h in STATE.farmland_partners(*start, hills=False)}
                    and some in {(h["col"], h["row"]) for h in STATE.farmland_partners(*start, hills=True)}))
    hex_(some, terrains=())
    results.append(("a hex with no terrain set is left to the table",
                    some in {(h["col"], h["row"]) for h in STATE.farmland_partners(*start, hills=False)}))

    # --- 5b. the ground: the predominant terrain, the first listed ----------
    ground = lambda *terrains: STATE.farmland_ground({"terrains": list(terrains)})  # noqa: E731
    results.append(("plains and hills qualify", ground("plains") == "plains" and ground("hills") == "hills"))
    results.append(("forest, swamp, mountains do not",
                    ground("forest") is None and ground("swamp") is None and ground("mountains") is None))
    results.append(("mostly plains with some hills is plains", ground("plains", "hills") == "plains"))
    results.append(("mostly forest with some plains does not qualify", ground("forest", "plains") is None))
    results.append(("no terrain set counts as plains", ground() == "plains"))
finally:
    STATE.k = saved_kingdom


# --- 6. the activity in a window: requirement, critical success, the choice --
accounts = {u["username"]: u for u in STATE.archive.list_users()}
auth.id_in_session = lambda: accounts["admin"]["id"]
ui.run(storage_secret="simulated secret", reload=False, show=False)


class Map:
    """The map panel the activity redraws: here, nothing to draw."""
    def refresh(self):
        pass

    def soon(self):
        pass


async def window_run() -> None:
    async with core.app.router.lifespan_context(core.app):
        user = User(httpx.AsyncClient(transport=httpx.ASGITransport(core.app), base_url="http://test"))
        await user.open("/")
        real_roll = hex_panel.rules.roll_check
        try:
            with user.client:
                capital = STATE.settlement(STATE.k["capital"])
                town = tuple(capital["hex"][:2])
                around = hexgrid.neighbours(*town, STATE.orientation)
                for pos in around:
                    hex_(pos)
                far = next(p for p in hexgrid.neighbours(*around[0], STATE.orientation)
                           if p != town and p not in around)
                hex_(far)
                # Every roll a critical success, so that the outcome is known.
                hex_panel.rules.roll_check = lambda *_a, **_k: rules.Result(
                    20, 0, 40, STATE.control_dc, "critical_success", [])

                # A village: nothing next to it is in influence, the activity refuses.
                capital["kind"] = "village"
                rp_before = STATE.k["rp"]
                hex_panel._farmland(STATE.hex(*around[0]), Map())
                results.append(("out of influence the activity does nothing",
                                not STATE.hex(*around[0])["farmland"] and STATE.k["rp"] == rp_before))

                # A town: the hex next to it qualifies, and so do its neighbours.
                capital["kind"] = "town"
                first = STATE.hex(*around[0])
                expected = {(h["col"], h["row"]) for h in STATE.farmland_partners(*around[0], hills=False)}
                hex_panel._farmland(first, Map())
            results.append(("the critical success makes the first hex Farmland", first["farmland"]))
            await user.should_see("Critical success: a second Farmland")
            user.find("Establish here").click()
            await asyncio.sleep(0.1)
            chosen = [p for p in expected if STATE.hex(*p)["farmland"]]
            results.append(("the chosen neighbour becomes the second Farmland",
                            len(expected) > 0 and len(chosen) == 1))
            results.append(("and nothing outside influence was touched", not STATE.hex(*far)["farmland"]))
            cons = STATE.consumption()
            results.append(("both now reduce the Consumption", cons["farms"] == 2 and cons["farms_outside"] == 0))

            # The ground: refused in a forest, charged by the predominant terrain.
            with user.client:
                dcs = []

                def failing(_modifier, dc, *_a, **_k):
                    dcs.append(dc)
                    return rules.Result(1, 0, 1, dc, "failure", [])
                hex_panel.rules.roll_check = failing
                spare = [p for p in around if not STATE.hex(*p)["farmland"]]

                def attempt(pos, terrains):
                    """(RP spent, DC rolled against or None)"""
                    hex_(pos, terrains=terrains)
                    STATE.k["rp"] = 10
                    dcs.clear()
                    hex_panel._farmland(STATE.hex(*pos), Map())
                    return 10 - STATE.k["rp"], (dcs[0] if dcs else None)

                base = STATE.control_dc
                results.append(("in a forest the activity does nothing, no roll",
                                attempt(spare[0], ("forest",)) == (0, None)))
                results.append(("mostly plains: 1 RP, the Control DC",
                                attempt(spare[0], ("plains", "hills")) == (1, base)))
                results.append(("mostly hills: 2 RP, the Control DC + 5",
                                attempt(spare[0], ("hills", "plains")) == (2, base + 5)))
        finally:
            hex_panel.rules.roll_check = real_roll
            # Closed before the end, so its outbox loop stops on its own:
            # see `close_all` in test_windows.py, which hung without it.
            user.client.delete()


asyncio.run(window_run())

for name, ok in results:
    print(f" {'ok' if ok else 'NO'}  {name}")
print(f"{sum(1 for _n, ok in results if ok)}/{len(results)} passed")
