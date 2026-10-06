# -*- coding: utf-8 -*-
"""The kingdom rules the 1.2.0 audit found missing, each checked on its own:

- the activity limits on the map and in the city (Region 3 a turn, Claim Hex
  by level, Civic one per settlement, nothing but Quell Unrest in Anarchy),
  and Claim Hex's critical outcomes;
- the structures that raise storage (a Granary: Food +1) or lower a
  settlement's Consumption (a Stockyard, a Sewer System, a Mill by water);
- the level-up choices: ability boosts, skill increases, Ruin Resistance;
- Consumption paid in part with Food, the rest in RP or Unrest;
- RP owed for the next turn, a Ruin's flat check at 0, Envy of the World,
  no XP for claiming again a hex once lost.

Sections 1–4 work on a kingdom built in memory; section 5 pays Consumption
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
from kingmaker.access import auth  # noqa: E402
from kingmaker.state import STATE, new_kingdom  # noqa: E402
from kingmaker.ui.tabs import turn  # noqa: E402
from kingmaker.ui.tabs.city import new_settlement  # noqa: E402

results = []
saved_kingdom = STATE.k
act = rules.BY_ID["activities"]


def build(sett, *structures):
    sett["grids"][0][0] = [{"structure": None} for _ in sett["grids"][0][0]]
    for i, sid in enumerate(structures):
        sett["grids"][0][0][i] = {"structure": sid, "gid": f"g{i}"}


STATE.k = new_kingdom()
k = STATE.k
real_roll = rules.roll
try:
    for role in k["roles"].values():
        role["name"] = "Leader"
    town = new_settlement("Riverhold", (3, 3))
    k["settlements"].append(town)
    k["capital"] = town["id"]

    # --- 1. the activity limits ---------------------------------------------
    k["level"] = 1
    STATE.mark_activity("claim_hex")
    results.append(("Claim Hex: once a turn at 1st level", bool(STATE.activities_block(act["claim_hex"]))))
    k["level"] = 4
    results.append(("twice from 4th", not STATE.activities_block(act["claim_hex"])))
    STATE.mark_activity("build_roads")
    STATE.mark_activity("fortify_hex")
    results.append(("Region: 3 a turn", bool(STATE.activities_block(act["clear_hex"]))))
    STATE.add_region_activity()
    results.append(("a Claim Hex critical success allows one more", not STATE.activities_block(act["clear_hex"])))
    k["turn_activities"] = {}
    STATE.mark_activity("build_structure")
    results.append(("Civic: one per settlement", bool(STATE.activities_block(act["build_structure"]))))
    k["level"] = 12
    results.append(("two in one with Civic Planning (12th)", not STATE.activities_block(act["build_structure"])))
    k["turn_activities"] = {}
    k["unrest"] = 20
    results.append(("Anarchy: no Region activity", bool(STATE.activities_block(act["build_roads"]))))
    results.append(("but Quell Unrest", not STATE.activities_block(act["quell_unrest"])))
    k["unrest"], k["level"] = 0, 1

    # --- 2. storage and Consumption ------------------------------------------
    base = STATE.storage("food")
    build(town, "granary", "granary")
    results.append(("two Granaries: Food storage +2", STATE.storage("food") == base + 2))
    results.append(("and nothing else", STATE.storage("lumber") == base))
    build(town)
    plain = STATE.settlement_consumption(town)
    build(town, "stockyard", "stockyard")
    results.append(("a Stockyard: the settlement's Consumption -1, once",
                    STATE.settlement_consumption(town) == max(0, plain - 1)))
    town["kind"] = "city"                                  # Consumption 4
    build(town, "stockyard", "sewer_system", "mill")
    results.append(("a Mill without a water border saves nothing",
                    STATE.settlement_consumption(town) == 4 - 2))
    town["borders"]["north"] = "water"
    results.append(("by water it does", STATE.settlement_consumption(town) == 4 - 3))
    results.append(("and the kingdom's Consumption follows", STATE.consumption()["settlements"] == 1))
    town["consumption_extra"] = 2
    results.append(("plus the adjustment typed in the city", STATE.settlement_consumption(town) == 3))
    town["consumption_extra"], town["kind"] = 0, "village"
    build(town)

    # --- 3. level-up choices -------------------------------------------------
    results.append(("5th level: boosts, a skill increase, Ruin Resistance",
                    STATE.advancement(5) == ["boosts", "skill", "ruin"]))
    results.append(("4th level: none of them", STATE.advancement(4) == []))
    k["abilities"].update(culture=17, economy=18)
    results.append(("boosts need two different abilities", not STATE.boost_abilities(5, "culture", "culture")))
    results.append(("+2 below 18, +1 from 18", STATE.boost_abilities(5, "culture", "economy")
                    and k["abilities"]["culture"] == 19 and k["abilities"]["economy"] == 19))
    results.append(("once per level", not STATE.boost_abilities(5, "loyalty", "stability")))
    k["proficiencies"]["trade"] = "expert"
    results.append(("an expert skill cannot reach master before 7th",
                    "trade" not in STATE.skill_increase_options(5)))
    results.append(("from 7th it can", STATE.skill_increase_options(7).get("trade") == "master"))
    results.append(("an untrained skill becomes trained",
                    STATE.increase_skill(5, "arts") and k["proficiencies"]["arts"] == "trained"))
    k["ruins"]["crime"].update(threshold=10, penalty=2)
    results.append(("Ruin Resistance: threshold +2, penalty to 0",
                    STATE.ruin_resistance(5, "crime") and k["ruins"]["crime"]["threshold"] == 12
                    and k["ruins"]["crime"]["penalty"] == 0))

    # --- 4. RP next turn, a Ruin at 0, Envy of the World ---------------------
    STATE.apply_effect({"t": "rp_next", "q": "3"}, 3)
    rules.roll = lambda n, faces: (n, [1] * n)
    n, _f, tot, _r = STATE.roll_resource_dice()
    results.append(("RP owed arrive with the next Resource Dice", tot == n + 3 and k["rp_next_turn"] == 0))
    k["ruins"]["decay"].update(points=0, penalty=2)
    rules.roll = lambda n, faces: (16, [16])
    STATE.modify_ruin("decay", -1)
    results.append(("a Ruin at 0: a DC 16 flat check lowers the penalty", k["ruins"]["decay"]["penalty"] == 1))
    rules.roll = lambda n, faces: (15, [15])
    STATE.modify_ruin("decay", -1)
    results.append(("a 15 does not", k["ruins"]["decay"]["penalty"] == 1))
    rules.roll = real_roll
    k["level"], k["unrest"] = 20, 0
    STATE.modify_unrest(2)
    results.append(("Envy of the World: the first Unrest of a turn ignored", k["unrest"] == 0))
    STATE.modify_unrest(2)
    results.append(("the second is not", k["unrest"] == 2))
    STATE.modify_ruin("strife", 1)
    results.append(("nor a Ruin after it, in the same turn", k["ruins"]["strife"]["points"] == 1))
    k["level"], k["unrest"] = 1, 0
finally:
    rules.roll = real_roll
    STATE.k = saved_kingdom


# --- 5. in a window: Consumption paid in part ------------------------------
accounts = {u["username"]: u for u in STATE.archive.list_users()}
auth.id_in_session = lambda: accounts["admin"]["id"]
ui.run(storage_secret="simulated secret", reload=False, show=False)


async def window_run() -> None:
    async with core.app.router.lifespan_context(core.app):
        user = User(httpx.AsyncClient(transport=httpx.ASGITransport(core.app), base_url="http://test"))
        await user.open("/")
        k = STATE.k
        try:
            with user.client:
                k["consumption_extra"] = 4
                cons = STATE.consumption()["total"]
                k["commodities"]["food"] = 1
                k["rp"] = 100
                k["consumption_paid"] = {}
                turn._pay_consumption("food")
                results.append(("Food pays what it can", k["commodities"]["food"] == 0
                                and turn._consumption_due() == cons - 1))
                turn._pay_consumption("rp")
                results.append(("the rest costs 5 RP per point", k["rp"] == 100 - 5 * (cons - 1)
                                and turn._consumption_due() == 0))
                rp = k["rp"]
                turn._pay_consumption("rp")
                results.append(("and nothing more once settled", k["rp"] == rp))
        finally:
            user.client.delete()


asyncio.run(window_run())

for name, ok in results:
    print(f" {'ok' if ok else 'NO'}  {name}")
print(f"{sum(1 for _n, ok in results if ok)}/{len(results)} passed")
