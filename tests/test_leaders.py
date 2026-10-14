# -*- coding: utf-8 -*-
"""Leaders and activity limits (2.3.0 C): who acts, two or three Leadership
activities each, one Civic activity per settlement, the week of downtime,
New Leadership's penalty, Favored Land.

Sections 1-6 work on a kingdom built in memory (the journeys of section 3 go
to the test scene's archive); section 7 rolls a Loyalty check in a simulated
window of the real app.
"""
import asyncio
import os
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ["NICEGUI_USER_SIMULATION"] = "true"

import httpx  # noqa: E402
from nicegui import core, ui  # noqa: E402
from nicegui.testing.general import prepare_simulation  # noqa: E402
from nicegui.testing.user import User  # noqa: E402

prepare_simulation()
from kingmaker import main, rules  # noqa: E402,F401
from kingmaker import turn_memory as memory  # noqa: E402
from kingmaker.access import auth  # noqa: E402
from kingmaker.rules import almanac  # noqa: E402
from kingmaker.state import STATE, new_kingdom  # noqa: E402
from kingmaker.ui.hexmap import hex_panel  # noqa: E402
from kingmaker.ui.tabs import leaders  # noqa: E402
from kingmaker.ui.tabs.city import new_settlement  # noqa: E402

results = []
saved_kingdom, saved_check, saved_roll = STATE.k, rules.roll_check, rules.roll
act = rules.BY_ID["activities"]


def build(sett, *structures):
    grid = sett["grids"][0]
    for b, block_ in enumerate(grid):
        grid[b] = [{"structure": None} for _ in block_]
    for n, sid in enumerate(structures):
        grid[0][n] = {"structure": sid, "gid": f"g{n}"}


def names(detail):
    return dict(detail)


STATE.k = new_kingdom()
k = STATE.k
try:
    for rid, role in k["roles"].items():
        role["name"] = f"Leader {rid}"
    for p in ("statecraft", "trade", "arts", "folklore", "politics"):
        k["proficiencies"][p] = "trained"
    town = new_settlement("Riverhold", (3, 3))
    other = new_settlement("Oakbrook", (8, 8))
    k["settlements"] += [town, other]
    k["capital"] = town["id"]
    lead = [a for a in rules.ACTIVITIES if a["phase"] == "activity" and a["step"] == "leadership"
            and not a.get("requirements") and not a.get("min_proficiency") and not a.get("subject")
            and a["id"] not in ("recruit_army", "relocate_capital", "hire_adventurers")]
    a1, a2, a3 = lead[0], lead[1], lead[2]

    # --- 1. Leadership activities by leader -----------------------------------
    STATE.mark_activity(a1["id"], role="ruler")
    STATE.mark_activity(a2["id"], role="ruler")
    results.append(("two activities by the Ruler, the third refused",
                    STATE.activities_block(a3, leader="ruler") != ""))
    results.append(("another leader may still act", STATE.activities_block(a3, leader="treasurer") == ""))
    results.append(("the same leader cannot repeat an activity",
                    STATE.activities_block(a1, leader="ruler") != ""))
    results.append(("another leader can attempt it", STATE.activities_block(a1, leader="counselor") == ""))
    build(town, "castle")
    results.append(("a Castle in the capital: a third allowed", STATE.activities_block(a3, leader="ruler") == ""))
    leaders._set_choice("ruler", "give_up")
    results.append(("a leader giving up one for the missed downtime: back to two",
                    STATE.activities_block(a3, leader="ruler") != ""))
    leaders._set_choice("ruler", None)
    k["turn_activities"], k["turn_leaders"] = {}, {}
    build(town)

    # --- 2. one Civic activity per settlement ----------------------------------
    demolish = act["demolish"]
    STATE.mark_activity("demolish", settlement=town["id"])
    results.append(("a second Civic activity in the same settlement is refused",
                    STATE.activities_block(demolish, settlement=town["id"]) != ""))
    results.append(("another settlement may still act",
                    STATE.activities_block(demolish, settlement=other["id"]) == ""))
    k["level"] = 12
    results.append(("Civic Planning: not before every other settlement acted",
                    STATE.activities_block(demolish, settlement=town["id"]) != ""))
    STATE.mark_activity("demolish", settlement=other["id"])
    results.append(("then one settlement may attempt a second",
                    STATE.activities_block(demolish, settlement=town["id"]) == ""))
    STATE.mark_activity("demolish", settlement=town["id"])
    results.append(("and only one", STATE.activities_block(demolish, settlement=other["id"]) != ""))
    k["level"] = 1
    k["turn_activities"], k["turn_civic"] = {}, {}

    # --- 3. the week of downtime -----------------------------------------------
    char = STATE.archive.list_characters(STATE.campaign)[0]["id"]
    first, length = leaders.month_span()
    def journey(start: int, days: int, ran: bool = True) -> None:
        # A journey the clock ran has its resolved turn; one moved at once has not.
        jid = uuid.uuid4().hex
        STATE.archive.create_journey({
            "id": jid, "campaign_id": STATE.campaign, "characters": [char],
            "departure": "1,1", "arrival": "2,2", "path": [], "costs": [], "legs": [],
            "activity_cost": 1, "days": days, "activities_per_day": 1, "progress": 0,
            "departure_day": start, "forced_march": 0, "status": "completed", "turn_created": 0,
            "created_by": None, "created_at": "2026-10-13"})
        if ran:
            STATE.archive.update_journey(jid, turn_resolved=0)

    journey(first + 2, 5)
    journey(first - 40, 5)
    results.append(("the hint counts the journey inside the month, not the one before",
                    leaders.travel_days(char) == 5))
    journey(first + 10, 12, ran=False)
    results.append(("a journey moved at once, with no clock day behind it, counts nothing",
                    leaders.travel_days(char) == 5))
    journey(first + 4, 5)
    results.append(("two journeys over the same days count those days once",
                    leaders.travel_days(char) == 7))
    results.append(("an NPC leader is ticked by default, a PC not",
                    (k["roles"]["ruler"].update(pc=False) or leaders.ticked("ruler"))
                    and (k["roles"]["ruler"].update(pc=True) or not leaders.ticked("ruler"))))
    leaders._set_choice("warden", "penalty")
    results.append(("the vacancy penalty chosen: the Warden is vacant this turn", STATE.role_vacant("warden")))
    k["turn"] += 1
    STATE.new_turn_memory()
    results.append(("and no longer next turn", not STATE.role_vacant("warden")))

    # --- 4. the rest days -------------------------------------------------------
    results.append(("the week of downtime is 7 days, from the kingdom rules",
                    almanac.LEADER_REST_DAYS == 7 == rules.KINGDOM["leader_rest_days"]))

    # --- 5. New Leadership's failure --------------------------------------------
    nl = act["new_leadership"]
    STATE.apply_effect(nl["effects"]["failure"][0], 0, None, None,
                       {"act": "new_leadership", "subject": "treasurer"})
    activity_check = names(STATE.check_detail("trade", a1["id"], leader="treasurer"))
    upkeep_check = names(STATE.check_detail("trade", "new_leadership", leader="treasurer"))
    other_leader = names(STATE.check_detail("trade", a1["id"], leader="ruler"))
    results.append(("its -1 reaches an Activity-phase check by that leader",
                    activity_check.get(nl["name"]) == -1))
    results.append(("not an Upkeep check, nor another leader",
                    nl["name"] not in upkeep_check and nl["name"] not in other_leader))

    # --- 6. Favored Land ------------------------------------------------------------
    k["heartland"] = next(h["id"] for h in rules.HEARTLANDS if "forest" in h.get("terrains", ()))
    here, there = STATE.hex(5, 5), STATE.hex(6, 6)
    here["terrains"], there["terrains"] = ["forest"], ["forest"]
    results.append(("a heartland hex offers Favored Land", hex_panel.favored_available(here)))
    k["favored_land"].update(turn=k["turn"], hex=[5, 5], used=0, as_one=False)
    first_ = hex_panel.favored_extra("build_roads", here)
    second = hex_panel.favored_extra("clear_hex", here)
    third = hex_panel.favored_extra("build_roads", here)
    results.append(("-2 on both checks in the hex, none on a third",
                    first_ and first_[0][1] == -2 and second and not third))
    results.append(("none in another hex", hex_panel.favored_extra("build_roads", there) == []))
    k["favored_land"].update(turn=k["turn"], hex=[5, 5], used=0, as_one=True)
    k["region_bonus"] = {}
    hex_panel.favored_extra("build_roads", here)
    hex_panel.favored_extra("clear_hex", here)
    results.append(("counted as one: the Region slot comes back",
                    STATE.step_limit("activity", "region") == 4))
finally:
    STATE.k = saved_kingdom
    rules.roll_check = saved_check
    rules.roll = saved_roll


# --- 7. in a window: the Loyalty check lifts the penalty --------------------------
accounts = {u["username"]: u for u in STATE.archive.list_users()}
auth.id_in_session = lambda: accounts["admin"]["id"]
ui.run(storage_secret="simulated secret", reload=False, show=False)


async def window_run() -> None:
    async with core.app.router.lifespan_context(core.app):
        user = User(httpx.AsyncClient(transport=httpx.ASGITransport(core.app), base_url="http://test"))
        await user.open("/")
        k = STATE.k
        try:
            entry = {"role": "treasurer", "subject": None, "value": -1, "kind": "circumstance",
                     "scope": "leader", "reason": "New Leadership", "until_turn": None,
                     "clears_on": "loyalty_check", "phase": "activity", "since_turn": k["turn"]}
            memory.memory(k)["penalties"].append(entry)
            rules.roll_check = lambda mod, dc, detail=None, worsens_by=0: rules.Result(
                15, mod, 15 + mod, dc, "success", detail or [])
            with user.client:
                leaders.roll_loyalty(entry, "politics")
            results.append(("a Loyalty success lifts New Leadership's -1",
                            entry not in k["turn_memory"]["penalties"]))
        finally:
            rules.roll_check = saved_check
            user.client.delete()


asyncio.run(window_run())

for name, ok in results:
    print(f" {'ok' if ok else 'NO'}  {name}")
print(f"{sum(1 for _n, ok in results if ok)}/{len(results)} passed")
