# -*- coding: utf-8 -*-
"""Fame and Infamy points, spent the way the rules allow, and the item
bonuses of the structures, counted in the checks they help.

Spending: 1 point rerolls a Kingdom skill check, once, and the second result
stands; all the points stave off Anarchy (Unrest stops 1 below it) or a Ruin
penalty (the Ruin stops 1 below where it would rise). Gaining: a famous or
infamous structure moves the points when built, and a Masterpiece's critical
success owes a point at the start of the next turn.

Item bonuses: a settlement's structures help the activities in its
influence, the capital's everywhere; identical structures stack up to the
settlement's maximum, different ones do not. The Inn's +1 to Hire
Adventurers was only text, and never reached the roll.

Sections 1–4 work on a kingdom built in memory; section 5 runs the screens
in a simulated window of the real app, on the test scene, with the die fixed.
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
from kingmaker.ui.tabs import turn  # noqa: E402
from kingmaker.ui.tabs.city import new_settlement  # noqa: E402

results = []
saved_kingdom = STATE.k


def build(sett, *structures):
    """The settlement's first block holds these structures, one lot each,
    and nothing else."""
    clear(sett)
    block_ = sett["grids"][0][0]
    for i, sid in enumerate(structures):
        block_[i] = {"structure": sid, "gid": f"g{i}"}


def clear(sett):
    sett["grids"][0][0] = [{"structure": None} for _ in sett["grids"][0][0]]


def drop_closed(user: User) -> None:
    """Deletes the dialogs already closed: the simulated window keeps them,
    and a click on a label goes to the oldest element bearing it — a button
    of a screen the table has already left."""
    for e in list(user.client.elements.values()):
        if type(e).__name__ == "Dialog" and not e.value:
            e.delete()


def sees(user: User, text: str) -> bool:
    """Anywhere in the window, dialogs included: labels and buttons carry
    their text in `text`, titles and chips in their HTML `content`."""
    return any(text in str(getattr(e, "text", "") or "") + str(getattr(e, "content", "") or "")
               for e in user.client.elements.values())


def bonus(*args, **kwargs):
    found = STATE.item_bonus(*args, **kwargs)
    return found[1] if found else 0


STATE.k = new_kingdom()
try:
    k = STATE.k
    CAPITAL, FAR = (5, 5), (12, 12)
    for pos in (CAPITAL, FAR, *hexgrid.neighbours(*FAR, STATE.orientation)):
        STATE.hex(*pos).update(status="claimed")
    capital = new_settlement("Capitolium", CAPITAL)
    other = new_settlement("Farstead", FAR)
    k["settlements"] += [capital, other]
    k["capital"] = capital["id"]

    # --- 1. the structures' item bonus ------------------------------------
    build(capital, "inn")
    results.append(("the capital's Inn gives +1 to Hire Adventurers", bonus("hire_adventurers") == 1))
    detail = dict(STATE.check_detail("exploration", "hire_adventurers"))
    results.append(("and the bonus shows in the check's breakdown",
                    detail.get("Inn, Capitolium (item)") == 1))
    results.append(("not in a check for another activity", bonus("celebrate_holiday") == 0
                    and len(STATE.check_detail("exploration", "celebrate_holiday"))
                    == len(STATE.skill_detail("exploration"))))
    build(capital, "inn", "inn")
    results.append(("two Inns in a village: capped at its +1", bonus("hire_adventurers") == 1))
    capital["kind"] = "city"
    results.append(("two Inns in a city: +2, its maximum", bonus("hire_adventurers") == 2))
    build(capital, "inn", "inn", "inn")
    results.append(("three Inns in a city: still +2", bonus("hire_adventurers") == 2))
    build(capital, "inn", "tavern_popular")
    results.append(("an Inn and a Popular Tavern do not stack", bonus("hire_adventurers") == 1))
    build(capital, "library")
    results.append(("the Library helps Rest and Relax with Scholarship",
                    bonus("rest_and_relax", "scholarship") == 1))
    results.append(("and not with another skill", bonus("rest_and_relax", "trade") == 0))
    build(capital, "lumberyard")
    results.append(("the Lumberyard helps a lumber camp",
                    bonus("establish_work_site", "engineering", "lumber") == 1))
    results.append(("and not a mine", bonus("establish_work_site", "engineering", "ore") == 0))
    clear(capital)

    build(other, "inn")
    results.append(("another settlement's Inn: not anywhere in the kingdom", bonus("hire_adventurers") == 0))
    results.append(("but in that settlement", bonus("hire_adventurers", settlement=other["id"]) == 1))
    results.append(("and in a hex of its influence",
                    bonus("hire_adventurers", hex_=FAR) == 1))
    other["kind"] = "town"
    near = hexgrid.neighbours(*FAR, STATE.orientation)[0]
    results.append(("a town's influence reaches the next hex", bonus("hire_adventurers", hex_=near) == 1))
    results.append(("but not the capital's hex", bonus("hire_adventurers", hex_=CAPITAL) == 0))
    results.append(("it is offered as a place to attempt the activity",
                    [s["id"] for s in STATE.bonus_settlements("hire_adventurers")] == [other["id"]]))
    results.append(("the capital never is", STATE.bonus_settlements("celebrate_holiday") == []))
    clear(other)

    # --- 2. famous and infamous structures --------------------------------
    famous_only = next(s["id"] for s in rules.STRUCTURES
                       if "famous" in s["traits"] and "infamous" not in s["traits"])
    k["fame_points"] = 1
    results.append(("a famous kingdom builds a famous structure: +1",
                    STATE.fame_from_structure(famous_only) == 1 and k["fame_points"] == 2))
    infamous_only = next(s["id"] for s in rules.STRUCTURES
                         if "infamous" in s["traits"] and "famous" not in s["traits"])
    results.append(("an infamous one: -1", STATE.fame_from_structure(infamous_only) == -1
                    and k["fame_points"] == 1))
    both = next(s["id"] for s in rules.STRUCTURES
                if "infamous" in s["traits"] and "famous" in s["traits"])
    results.append(("one with both traits counts as the kingdom's", STATE.fame_from_structure(both) == 1))
    k["fame_points"] = STATE.max_fame
    results.append(("never above the maximum", STATE.fame_from_structure(famous_only) == 0))
    k["reputation"] = "infamy"
    results.append(("for an infamous kingdom the infamous one is +1",
                    STATE.fame_from_structure(infamous_only) == 0 and k["fame_points"] == STATE.max_fame))
    k["fame_points"] = 1
    results.append(("and the famous one -1", STATE.fame_from_structure(famous_only) == -1))
    results.append(("a structure with neither trait changes nothing", STATE.fame_from_structure("houses") == 0))
    k["reputation"] = "fame"

    # --- 3. staving off Anarchy and a Ruin penalty ------------------------
    STATE.fame_offers.clear()
    k["fame_points"], k["unrest"] = 2, 18
    STATE.modify_unrest(1)
    results.append(("Unrest below the threshold: nothing to stave off", STATE.fame_offers == []))
    STATE.modify_unrest(3)
    offers = STATE.take_fame_offers()
    results.append(("Unrest reaching Anarchy is offered", [o["kind"] for o in offers] == ["unrest"]))
    results.append(("once", STATE.take_fame_offers() == []))
    results.append(("all the points stave it off", STATE.stave_off(offers[0])
                    and k["unrest"] == STATE.anarchy_threshold - 1 and k["fame_points"] == 0))
    results.append(("and not twice", not STATE.stave_off(offers[0])))
    k["unrest"] = 19
    STATE.modify_unrest(1)
    results.append(("without points nothing is offered", STATE.fame_offers == [] and STATE.in_anarchy))

    k["fame_points"], k["unrest"] = 1, 0
    ruin_ = k["ruins"]["crime"]
    ruin_.update(points=9, penalty=0)
    STATE.modify_ruin("crime", 3)
    results.append(("the Ruin crossed its threshold", ruin_["penalty"] == 1 and ruin_["points"] == 2))
    offers = STATE.take_fame_offers()
    results.append(("and its penalty is offered", [(o["kind"], o["ruin"]) for o in offers] == [("ruin", "crime")]))
    results.append(("staved off: penalty as before, the Ruin 1 below the rise",
                    STATE.stave_off(offers[0]) and ruin_["penalty"] == 0
                    and ruin_["points"] == ruin_["threshold"] and k["fame_points"] == 0))
    k["fame_points"] = 1
    STATE.modify_ruin("crime", 1)
    stale = STATE.fame_offers[0]
    ruin_.update(penalty=0)            # somebody fixed it by hand meanwhile
    results.append(("an offer no longer standing is dropped",
                    STATE.take_fame_offers() == [] and not STATE.stave_off(stale)
                    and k["fame_points"] == 1))

    # --- 4. the reroll and the next-turn point, in the state ----------------
    k["fame_points"] = 1
    results.append(("one point to reroll", STATE.spend_fame() and k["fame_points"] == 0))
    results.append(("none left, no reroll", not STATE.spend_fame() and k["fame_points"] == 0))
    STATE.apply_effect({"t": "fame_next", "q": "1"}, 1)
    results.append(("a Masterpiece's point waits for the next turn",
                    k["fame_next_turn"] == 1 and k["fame_points"] == 0))

    # --- 4b. milestones, however the kingdom got there ----------------------
    k["milestones"], k["xp"] = [], 0
    STATE.hex(*FAR)["features"] = [{"kind": "landmark"}]      # marked after the claim
    other["kind"] = "city"                                     # set by hand, no Expand
    results.append(("the check awards what the kingdom already is", STATE.check_milestones()))
    results.append(("a Landmark on a claimed hex", "first_landmark" in k["milestones"]))
    results.append(("a city: the village, town and city milestones",
                    {"first_village", "first_town", "first_city"} <= set(k["milestones"])
                    and "first_metropolis" not in k["milestones"]))
    results.append(("not twice", not STATE.check_milestones()))
    entry = {"t": "milestone", "m": "first_trade_agreement", "q": "1"}
    xp = k["xp"]
    results.append(("an established Trade Agreement awards its milestone",
                    STATE.apply_effect(entry, 1) and k["xp"] == xp + 80))
    results.append(("once per campaign", STATE.apply_effect(entry, 1) == "" and k["xp"] == xp + 80))
    envoy = rules.BY_ID["activities"]["send_diplomatic_envoy"]["effects"]
    results.append(("Send Diplomatic Envoy's success carries the diplomatic milestone",
                    all(any(e.get("m") == "first_diplomatic_relation" for e in envoy[g])
                        for g in ("success", "critical_success"))))
finally:
    STATE.k = saved_kingdom


# --- 5. in a window: the reroll screen, the offer, the activity dialog -----
accounts = {u["username"]: u for u in STATE.archive.list_users()}
auth.id_in_session = lambda: accounts["admin"]["id"]
ui.run(storage_secret="simulated secret", reload=False, show=False)


class Map:
    def refresh(self):
        pass

    def soon(self):
        pass


def fixed(*grades):
    """roll_check answering these degrees of success, one per roll."""
    queue = list(grades)

    def roll(_modifier, dc, detail=None, *_a, **_k):
        grade = queue.pop(0)
        natural = {"critical_success": 20, "success": 15, "failure": 5, "critical_failure": 1}[grade]
        return rules.Result(natural, 0, natural, dc, grade, detail or [])
    return roll


async def window_run() -> None:
    async with core.app.router.lifespan_context(core.app):
        user = User(httpx.AsyncClient(transport=httpx.ASGITransport(core.app), base_url="http://test"))
        await user.open("/")
        real_roll = rules.roll_check
        k = STATE.k
        try:
            capital = STATE.settlement(k["capital"])
            town = tuple(capital["hex"][:2])
            road = STATE.hex(*town)
            road.update(status="claimed", roads=False)
            k["rp"] = 50

            # A failure with a point in hand: the result waits for the table.
            k["fame_points"], k["unrest"] = 1, 0
            with user.client:
                hex_panel.rules.roll_check = fixed("failure", "success")
                k["turn_activities"] = {}          # the Region limit: a fresh turn each time
                hex_panel._roads(road, Map())
            results.append(("the failure waits: nothing applied yet", not road.get("roads")))
            await user.should_see("Keep this result")
            drop_closed(user)
            user.find("Reroll for 1 Fame point (you have 1)").click()
            await asyncio.sleep(0.1)
            results.append(("the reroll's success is applied", road.get("roads") is True))
            results.append(("and it cost the point", k["fame_points"] == 0))
            results.append(("the second result is on screen, marked rerolled",
                            sees(user, "Build Roads (rerolled)")))
            results.append(("the journal says what was given up",
                            any("point spent to reroll Build Roads" in e["text"] for e in STATE.journal(20))))

            # Kept: the first result applies, the point stays.
            road["roads"] = False
            k["fame_points"] = 1
            with user.client:
                hex_panel.rules.roll_check = fixed("critical_failure")
                k["turn_activities"] = {}          # the Region limit: a fresh turn each time
                hex_panel._roads(road, Map())
            results.append(("a critical failure waits too", k["unrest"] == 0))
            drop_closed(user)
            user.find("Keep this result").click()
            await asyncio.sleep(0.1)
            results.append(("kept: its Unrest arrives, the point stays",
                            k["unrest"] == 1 and k["fame_points"] == 1 and not road.get("roads")))

            # No point, or a critical success: applied at once, as before.
            k["fame_points"] = 0
            with user.client:
                hex_panel.rules.roll_check = fixed("success")
                k["turn_activities"] = {}          # the Region limit: a fresh turn each time
                hex_panel._roads(road, Map())
            results.append(("without points the result applies at once", road.get("roads") is True))
            road["roads"] = False
            k["fame_points"] = 1
            with user.client:
                hex_panel.rules.roll_check = fixed("critical_success")
                k["turn_activities"] = {}          # the Region limit: a fresh turn each time
                hex_panel._roads(road, Map())
            results.append(("a critical success applies at once, and brings a point",
                            road.get("roads") is True and k["fame_points"] == 2))

            # The activity's outcome screen: the reroll replaces the outcome.
            act = rules.BY_ID["activities"]["hire_adventurers"]
            k["fame_points"] = 2
            with user.client:
                turn._outcome_dialog(act, fixed("failure")(0, 15),
                                     lambda: fixed("critical_success")(0, 15))
            drop_closed(user)
            user.find("Reroll for 1 Fame point (you have 2)").click()
            await asyncio.sleep(0.1)
            results.append(("the activity's new outcome is on screen", sees(user, "Hire Adventurers (rerolled)")))
            results.append(("the activity's reroll spent the point", k["fame_points"] == 1))

            # The Inn's bonus, in the activity dialog before rolling.
            build(capital, "inn")
            with user.client:
                turn.run_activity(act)
            await asyncio.sleep(0.1)
            results.append(("the Inn's +1 is in the Hire Adventurers dialog",
                            sees(user, f"Inn, {capital['name']} (item) +1")))
            clear(capital)

            # Unrest reaching Anarchy by hand: the offer, and the point spent.
            k["fame_points"], k["unrest"] = 2, STATE.anarchy_threshold - 1
            STATE.fame_offers.clear()
            with user.client:
                turn._adjust("unrest|1")
            await user.should_see("Spend the Fame points (2)")
            drop_closed(user)
            user.find("Spend the Fame points (2)").click()
            await asyncio.sleep(0.1)
            results.append(("Anarchy staved off from the screen",
                            k["unrest"] == STATE.anarchy_threshold - 1 and k["fame_points"] == 0))

            # Masterpiece, critical failure: which row is ticked depends on the points.
            entries = rules.BY_ID["activities"]["create_a_masterpiece"]["effects"]["critical_failure"]
            with user.client:
                with ui.dialog():
                    k["fame_points"] = 0
                    rows = turn._effect_rows(entries)
                    k["fame_points"] = 1
                    rows_with = turn._effect_rows(entries)
            results.append(("no points: the 1d4 Unrest is ticked, the Fame loss is not",
                            [r["active"] for r in rows] == [False, True]))
            results.append(("with a point: the loss is ticked, the Unrest is not",
                            [r["active"] for r in rows_with] == [True, False]))

            # The point owed by a Masterpiece arrives with the next turn —
            # from the clock too, a timer with no window and no account,
            # whose turn the permission check used to refuse in silence.
            k["fame_points"], k["fame_next_turn"] = 0, 1
            turn_before = k["turn"]
            turn.advance_turn()
            results.append(("the next turn starts with 1 + the owed point",
                            k["fame_points"] == 2 and k["fame_next_turn"] == 0))
            results.append(("and it starts outside any window, as from the clock",
                            k["turn"] == turn_before + 1))

            # The quick adjustment never takes Fame above its maximum.
            k["fame_points"] = STATE.max_fame
            with user.client:
                turn._adjust("fame_points|1")
            results.append(("+1 Fame at the maximum stays at the maximum", k["fame_points"] == STATE.max_fame))

            # Leadership activities used up: the card says why, not a KeyError.
            k["turn_activities"] = {}
            leadership = [a for a in rules.ACTIVITIES if a["step"] == "leadership" and not a.get("turn_limit")]
            for a in leadership[:STATE.step_limit("activity", "leadership")]:
                STATE.mark_activity(a["id"])
            try:
                why = STATE.activities_block(leadership[-1])
            except KeyError:
                why = None
            results.append(("Leadership used up: blocked with a reason", bool(why)))
            k["turn_activities"] = {}

            # Bonus and penalty dice: used up by the roll, from either button.
            k["bonus_dice"], k["penalty_dice"] = 2, 1
            n, _faces, _tot, _rolls = STATE.roll_resource_dice()
            results.append(("the Resource Dice use the bonus and penalty dice once",
                            n == STATE.level + 4 + 1 and k["bonus_dice"] == 0 and k["penalty_dice"] == 0))

            # A result left waiting when the window goes away: the first stands.
            road["roads"], k["unrest"], k["fame_points"] = False, 0, 1
            with user.client:
                hex_panel.rules.roll_check = fixed("critical_failure")
                k["turn_activities"] = {}          # the Region limit: a fresh turn each time
                hex_panel._roads(road, Map())
            results.append(("a result waits while the window is open", k["unrest"] == 0))
        finally:
            rules.roll_check = real_roll
            hex_panel.rules.roll_check = real_roll
            # Closed before the end, so its outbox loop stops on its own:
            # see `close_all` in test_windows.py, which hung without it.
            user.client.delete()
        results.append(("the window closed: the first result was applied", k["unrest"] == 1))


asyncio.run(window_run())

for name, ok in results:
    print(f" {'ok' if ok else 'NO'}  {name}")
print(f"{sum(1 for _n, ok in results if ok)}/{len(results)} passed")
