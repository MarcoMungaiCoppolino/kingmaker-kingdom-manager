# -*- coding: utf-8 -*-
"""What carries across Kingdom turns (2.3.0 B): repeat DCs, streaks, lock-outs,
the treasury's debt, pending flat checks, the record, the turn number.

Sections 1-7 work on a kingdom built in memory; section 8 rolls a pending
check and corrects the turn number in a simulated window of the real app.
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
from kingmaker import turn_memory as memory  # noqa: E402
from kingmaker.access import auth  # noqa: E402
from kingmaker.state import STATE, new_kingdom  # noqa: E402
from kingmaker.storage import migrations  # noqa: E402
from kingmaker.ui.tabs import events, turn  # noqa: E402

results = []
saved_kingdom, saved_check, saved_roll = STATE.k, rules.roll_check, rules.roll
act = rules.BY_ID["activities"]


def dc(act_id, **kw):
    return STATE.activity_dc(act_id, **kw)[0]


def next_turn():
    """What `turn.advance_turn` does to the turn's counts and memory."""
    STATE.k["turn"] += 1
    STATE.k["turn_activities"] = {}
    STATE.k["turn_leaders"] = {}
    STATE.k["turn_civic"] = {}
    STATE.new_turn_memory()


STATE.k = new_kingdom()
k = STATE.k
try:
    for role in k["roles"].values():
        role["name"] = "Leader"

    # --- 1. the new keys reach an older save -------------------------------
    old = new_kingdom()
    for key in ("events", "partners", "turn_memory", "turn_leaders", "turn_civic",
                "downtime", "favored_land", "rp_no_xp"):
        old.pop(key)
    loaded = migrations.normalize(old, new_kingdom)
    results.append(("a save without the 2.3.0 keys gets every default",
                    loaded["events"] == [] and loaded["partners"] == [] and loaded["rp_no_xp"] == 0
                    and loaded["turn_memory"]["pending"] == [] and loaded["downtime"] == {}))
    old = new_kingdom()
    del old["turn_memory"]["pending"]
    loaded = migrations.normalize(old, new_kingdom)
    results.append(("a turn_memory lacking a list gets it", loaded["turn_memory"]["pending"] == []))

    # --- 2. repeat DCs -------------------------------------------------------
    k["turn"] = 5
    plain = dc("rest_and_relax")
    STATE.mark_activity("rest_and_relax")
    next_turn()
    breakdown = STATE.activity_dc("rest_and_relax")[1]
    results.append(("Rest and Relax the turn after: DC +4", dc("rest_and_relax") == plain + 4))
    results.append(("and the breakdown names it", ("attempted last turn", 4) in breakdown))
    next_turn()
    results.append(("a turn skipped: no increase", dc("rest_and_relax") == plain))

    # --- 3. the streak --------------------------------------------------------
    k["turn"] = 10
    base = dc("clandestine_business")
    seen = []
    for _ in range(3):
        seen.append(dc("clandestine_business") - base)
        STATE.mark_activity("clandestine_business")
        next_turn()
    results.append(("Clandestine Business three turns running: +0, +2, +4", seen == [0, 2, 4]))
    next_turn()                         # one turn without
    results.append(("one turn skipped after: +3", dc("clandestine_business") - base == 3))
    k["turn"] += 5
    results.append(("five turns without: back to +0", dc("clandestine_business") - base == 0))

    # --- 4. lock-outs ------------------------------------------------------------
    k["turn"] = 20
    k["proficiencies"]["arts"] = "trained"     # Repair Reputation asks for a trained skill
    rr = act["repair_reputation"]
    lock_row = rr["effects"]["failure"][0]
    STATE.apply_effect(lock_row, 0, "crime", None, {"act": "repair_reputation", "subject": "crime"})
    results.append(("a Repair Reputation failure on Crime locks Crime this turn",
                    STATE.activities_block(rr, subject="crime") != ""))
    results.append(("and not Decay", STATE.activities_block(rr, subject="decay") == ""))
    next_turn()
    results.append(("and Crime next turn too", STATE.activities_block(rr, subject="crime") != ""))
    next_turn()
    results.append(("free again the turn after", STATE.activities_block(rr, subject="crime") == ""))
    STATE.apply_effect(rr["effects"]["critical_failure"][1], 0, None, None, {"act": "repair_reputation"})
    results.append(("a critical failure locks every Ruin",
                    all(STATE.activities_block(rr, subject=r) for r in ("crime", "decay", "strife", "corruption"))))
    results.append(("and the card (no Ruin chosen) is dimmed by it", STATE.activities_block(rr) != ""))
    results.append(("only a lock-out: the GM may override it", STATE.lockout_only(rr, "crime")))
    k["turn_activities"] = {"focused_attention": 99}
    lead = act["rest_and_relax"]
    results.append(("a step limit is not a lock-out", not STATE.lockout_only(lead)))
    k["turn_activities"] = {}
    for _ in range(3):
        next_turn()
    results.append(("for the three turns after it", STATE.activities_block(rr, subject="crime") != ""))
    next_turn()
    results.append(("and gone the turn after those",
                    STATE.activities_block(rr, subject="crime") == ""
                    and not k["turn_memory"]["lockouts"]))

    # --- 5. Tap Treasury's debt --------------------------------------------------
    tap = act["tap_treasury"]
    debt_row = next(r for r in tap["effects"]["success"] if r["t"] == "debt")
    STATE.apply_effect(debt_row, 0, None, None, {"act": "tap_treasury"})
    results.append(("Tap Treasury's success: the treasury is owed", STATE.debt("tap_treasury") is not None))
    results.append(("and the next Tap Treasury is worsened by two", STATE.worsens_by("tap_treasury") == 2))
    repay = next(r for r in act["capital_investment"]["effects"]["success"] if r["t"] == "repay")
    results.append(("Capital Investment offers to repay it only while owed",
                    repay.get("only_if") == "debt:tap_treasury"))
    STATE.apply_effect(repay, 0, None, None, {"act": "capital_investment"})
    results.append(("repaid: no debt, no worsening",
                    STATE.debt("tap_treasury") is None and STATE.worsens_by("tap_treasury") == 0))

    # --- 6. pending flat checks -----------------------------------------------------
    k["turn"] = 30
    ab = act["abandon_hex"]
    STATE.apply_effect(ab["effects"]["failure"][1], 0, None, None, {"act": "abandon_hex", "hex": (4, 4)})
    due = STATE.due_checks()
    results.append(("an Abandon Hex failure: a DC 6 check due this turn's Event phase",
                    len(due) == 1 and due[0]["due_turn"] == 30 and due[0]["dc"] == 6
                    and due[0]["then"] == "squatters"))
    irr = act["irrigation"]
    row = irr["effects"]["critical_failure"][1]
    for pos in ((1, 1), (2, 2), (3, 3)):
        STATE.apply_effect(row, 0, None, None, {"act": "irrigation", "hex": pos})
    first = next(e for e in k["turn_memory"]["pending"] if e["source"] == "irrigation")
    results.append(("Irrigation's DC 4, +1 for each other hex with that failure",
                    first["dc"] + events.pending_extra(first) == 6))
    removed = STATE.clear_pending("irrigation", (2, 2))
    results.append(("a later Irrigation success on a hex takes its check back",
                    removed == 1 and events.pending_extra(first) == 1))

    # --- 7. the record --------------------------------------------------------------
    k["turn"] = 40
    STATE.apply_effect(rr["effects"]["critical_failure"][1], 0, None, None, {"act": "repair_reputation"})
    for _ in range(4):
        STATE.mark_activity("rest_and_relax")
        next_turn()
    turns = {r["turn"] for r in k["turn_memory"]["record"]}
    results.append(("the record keeps three turns", turns == {k["turn"] - 2, k["turn"] - 1}))
    STATE.apply_effect(rr["effects"]["critical_failure"][1], 0, None, None, {"act": "repair_reputation"})
    for _ in range(3):
        STATE.mark_activity("rest_and_relax")
        next_turn()
    results.append(("a lock-out outlives the record's trim",
                    STATE.activities_block(rr, subject="crime") != ""
                    and not any(r["act"] == "repair_reputation" for r in k["turn_memory"]["record"])))
finally:
    STATE.k = saved_kingdom
    rules.roll_check = saved_check
    rules.roll = saved_roll


# --- 8. in a window: a pending check rolled, the turn number corrected --------------
accounts = {u["username"]: u for u in STATE.archive.list_users()}
auth.id_in_session = lambda: accounts["admin"]["id"]
ui.run(storage_secret="simulated secret", reload=False, show=False)


def notified(user: User, text: str) -> bool:
    return any(text in str(getattr(e, "message", "") or "") for e in user.client.elements.values()) \
        or any(text in str(getattr(e, "text", "") or "") + str(getattr(e, "content", "") or "")
               for e in user.client.elements.values())


async def window_run() -> None:
    async with core.app.router.lifespan_context(core.app):
        user = User(httpx.AsyncClient(transport=httpx.ASGITransport(core.app), base_url="http://test"))
        await user.open("/")
        k = STATE.k
        try:
            memory.memory(k)["pending"].append({"due_turn": k["turn"], "phase": "event", "dc": 6,
                                                "dc_per_hex": False, "source": "abandon_hex",
                                                "hex": [4, 4], "remaining": 1, "then": "squatters"})
            entry = k["turn_memory"]["pending"][-1]
            rules.roll = lambda n, faces: (2, [2]) if faces == 20 else saved_roll(n, faces)
            with user.client:
                events.roll_pending(entry)
            rules.roll = saved_roll
            await user.should_see("A new kingdom event")
            names = [e.value for e in user.client.elements.values()
                     if isinstance(e, ui.input) and e.props.get("label") == "Name (from the book)"]
            results.append(("a roll under the DC opens the named event, Squatters",
                            "Squatters" in names))
            results.append(("and the check, its count spent, is gone", entry not in k["turn_memory"]["pending"]))

            before = k["turn"]
            memory.memory(k)["lockouts"].append({"act": "supernatural_solution", "subject": None,
                                                 "until_turn": before + 1, "reason": "test"})
            with user.client:
                turn._set_turn(before + 5)
            await asyncio.sleep(0.05)
            results.append(("a corrected turn number says what it skips",
                            any("Supernatural Solution" in s for s in turn._turn_skips(before, before + 5))))
            with user.client:
                turn._set_turn(before)

            # The taxes flat check is not a kingdom activity: Endure Anarchy's
            # extra point off does not apply, the success takes exactly 1.
            k["feats"] = list(set(k["feats"]) | {"endure_anarchy"})
            k["unrest"] = 8
            k["feat_turns"].pop("taxes_flat", None)
            rules.roll = lambda n, faces: (15, [15]) if faces == 20 else saved_roll(n, faces)
            with user.client:
                turn._taxes_flat_check()
            rules.roll = saved_roll
            results.append(("the taxes flat check takes 1 Unrest, not Endure Anarchy's 2", k["unrest"] == 7))
            k["feats"].remove("endure_anarchy")
        finally:
            rules.roll = saved_roll
            user.client.delete()


asyncio.run(window_run())

for name, ok in results:
    print(f" {'ok' if ok else 'NO'}  {name}")
print(f"{sum(1 for _n, ok in results if ok)}/{len(results)} passed")
