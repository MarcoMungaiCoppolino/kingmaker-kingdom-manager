# -*- coding: utf-8 -*-
"""The kingdom's ongoing events (2.3.0 A): their DC, what helps resolve them, Hire
Adventurers' marks, the cemetery's row, the new-event dialog.

Sections 1-3 work on a kingdom built in memory; section 4 runs the Event
phase in a simulated window of the real app, on the test scene, with the die
fixed.
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
from nicegui.testing.user_interaction import UserInteraction  # noqa: E402

prepare_simulation()
from kingmaker import main, rules  # noqa: E402,F401
from kingmaker.access import auth  # noqa: E402
from kingmaker.state import STATE, new_kingdom  # noqa: E402
from kingmaker.ui.tabs import events, turn  # noqa: E402
from kingmaker.ui.tabs.city import new_settlement  # noqa: E402

results = []
saved_kingdom, saved_check, saved_roll = STATE.k, rules.roll_check, rules.roll


def build(sett, *structures):
    """These structures, one lot each, filling the grid's blocks in order."""
    grid = sett["grids"][0]
    for b, block_ in enumerate(grid):
        grid[b] = [{"structure": None} for _ in block_]
    lots = [(b, i) for b, block_ in enumerate(grid) for i in range(len(block_))]
    for n, sid in enumerate(structures):
        b, i = lots[n]
        grid[b][i] = {"structure": sid, "gid": f"g{n}"}


def names(detail):
    return dict(detail)


STATE.k = new_kingdom()
k = STATE.k
try:
    for role in k["roles"].values():
        role["name"] = "Leader"
    town = new_settlement("Riverhold", (3, 3))
    other = new_settlement("Oakbrook", (8, 8))
    k["settlements"] += [town, other]
    k["capital"] = town["id"]

    # --- 1. the DC and what helps ------------------------------------------
    ev = events.new_entry("Bandits", modifier=2, settlement=town["id"])
    results.append(("an event's DC is the Control DC + its modifier", STATE.event_dc(ev) == STATE.control_dc + 2))
    build(town, "watchtower")
    watch = rules.BY_ID["structure"]["watchtower"]["name"]
    results.append(("a Watchtower in its settlement: +1 item",
                    any(v == 1 and kind == "item" and watch in n for n, v, kind in events.check_extras(ev))))
    ev["settlement"] = other["id"]
    results.append(("and nothing for an event elsewhere", events.check_extras(ev) == []))
    k["feats"] = ["quick_recovery"]
    qr = rules.BY_ID["feat"]["quick_recovery"]["name"]
    plain = names(STATE.check_detail("trade", event=events.check_event_kind(ev)))
    ev.update(continuous=True, harmful=True)
    helped = names(STATE.check_detail("trade", event=events.check_event_kind(ev)))
    results.append(("Quick Recovery: +4 only for a continuous harmful event",
                    not any(qr in n for n in plain) and helped.get(f"{qr} (status)") == 4))
    k["feats"] = []
    ev.update(leader="ruler", leader_bonus=2)
    results.append(("the leader's bonus when the role is held",
                    any(v == 2 for _n, v, _k in events.check_extras(ev))))
    k["roles"]["ruler"]["absent"] = True
    results.append(("and none when the role is vacant", events.check_extras(ev) == []))
    k["roles"]["ruler"]["absent"] = False
    ev.update(leader=None, leader_bonus=0)
    hire = rules.BY_ID["activities"]["hire_adventurers"]
    STATE.apply_effect(hire["effects"]["success"][0], 0, ev["id"], None, {"event": ev["id"]})
    results.append(("Hire Adventurers' success: +2 at the next check",
                    any(n == hire["name"] and v == 2 for n, v, _k in events.check_extras(ev))))
    ev["hire_bonus"] = None            # what the check does when it rolls
    results.append(("and used up by that check", events.check_extras(ev) == []))

    # --- 2. Hire Adventurers' marks ------------------------------------------
    second = events.new_entry("Monster", modifier=0)
    STATE.apply_effect(hire["effects"]["failure"][0], 0, second["id"], None, {"event": second["id"]})
    cost = turn.activity_cost(hire, second["id"])
    results.append(("a failure: the next attempt on it costs 2 Resource Dice",
                    second["hire_failed"] and cost[0]["q"] == "-2"))
    results.append(("on another event it still costs 1", turn.activity_cost(hire, ev["id"])[0]["q"] == "-1"))
    STATE.apply_effect(hire["effects"]["critical_failure"][0], 0, second["id"], None, {"event": second["id"]})
    results.append(("a critical failure locks the event out of Hire Adventurers",
                    second["hire_locked"] and second["id"] not in turn._subject_options(hire)))
    STATE.apply_effect(hire["effects"]["critical_success"][0], 0, ev["id"], None, {"event": ev["id"]})
    results.append(("a critical success ends the event",
                    ev["ended_turn"] == k["turn"] and ev not in STATE.ongoing_events()))
    results.append(("with no event left to hire for, the activity is refused",
                    STATE.activities_block(hire) == STATE.activities_block(hire) != ""
                    and not turn._subject_options(hire)))

    # --- 3. the cemetery's row ------------------------------------------------
    third = events.new_entry("Plague", dangerous=True, settlement=town["id"])
    build(town, "cemetery", "cemetery")
    row = events.cemetery_row(third)
    results.append(("2 Cemeteries: -2 Unrest offered", row is not None and row["q"] == "-2"))
    build(town, *["cemetery"] * 6)
    results.append(("6 Cemeteries: -4, the cap", events.cemetery_row(third)["q"] == "-4"))
    build(town)
    results.append(("none: no row", events.cemetery_row(third) is None))
    third["dangerous"] = False
    build(town, "cemetery")
    results.append(("not dangerous: no row", events.cemetery_row(third) is None))
finally:
    STATE.k = saved_kingdom
    rules.roll_check = saved_check
    rules.roll = saved_roll


# --- 4. in a window: a random event comes, and is named ------------------------
accounts = {u["username"]: u for u in STATE.archive.list_users()}
auth.id_in_session = lambda: accounts["admin"]["id"]
ui.run(storage_secret="simulated secret", reload=False, show=False)


async def window_run() -> None:
    async with core.app.router.lifespan_context(core.app):
        user = User(httpx.AsyncClient(transport=httpx.ASGITransport(core.app), base_url="http://test"))
        await user.open("/")
        k = STATE.k
        try:
            STATE.check_milestones()          # the scene's own milestones, awarded first
            before_xp, before_n = k["xp"], len(k["events"])
            k["event_dc"] = 16
            rules.roll = lambda n, faces: (20, [20]) if faces == 20 else saved_roll(n, faces)
            with user.client:
                turn._check_event()
            rules.roll = saved_roll
            await user.should_see("A new kingdom event")
            # The dialog's own field and button: the newest of their kind
            # (a simulated click takes the oldest element with that text).
            elements = list(user.client.elements.values())
            field = max((e for e in elements if isinstance(e, ui.input)
                         and e.props.get("label") == "Name (from the book)"), key=lambda e: e.id)
            field.value = "Squatters on the river"
            save = max((e for e in elements if isinstance(e, ui.button) and e.text == "Save"),
                       key=lambda e: e.id)
            UserInteraction(user, {save}, None).click()
            await asyncio.sleep(0.1)
            found = [e for e in k["events"] if e["name"] == "Squatters on the river"]
            results.append(("a random event on a 20 opens the dialog, and saving lists it",
                            len(k["events"]) == before_n + 1 and found and found[0] in STATE.ongoing_events()))
            results.append(("with its 30 XP, once", k["xp"] == before_xp + 30 and found[0]["xp_awarded"]))
        finally:
            rules.roll = saved_roll
            user.client.delete()


asyncio.run(window_run())

for name, ok in results:
    print(f" {'ok' if ok else 'NO'}  {name}")
print(f"{sum(1 for _n, ok in results if ok)}/{len(results)} passed")
