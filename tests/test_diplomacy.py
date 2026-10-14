# -*- coding: utf-8 -*-
"""Diplomacy, trade agreements and war (2.3.0 F): partners, relations, the
envoy's bonus, agreements, foreign aid's RP, Pledge of Fealty, war.

Sections 1-5 work on a kingdom built in memory; section 6 draws the Upkeep
Unrest step at war in a simulated window of the real app.
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
from kingmaker.ui import theme  # noqa: E402
from kingmaker.ui.tabs import diplomacy, turn  # noqa: E402
from kingmaker.ui.tabs.city import new_settlement  # noqa: E402

results = []
saved_kingdom, saved_check, saved_roll = STATE.k, rules.roll_check, rules.roll
act = rules.BY_ID["activities"]


def rows_of(act_id, grade):
    return [r for r in act[act_id]["effects"][grade] if r["t"] != "note"]


def apply(act_id, grade, target=None, **context):
    for row in rows_of(act_id, grade):
        value = row["v"] if row["t"] == "mod" else rules.signed_value(row.get("q", "0"))[0]
        STATE.apply_effect(row, value, target, None, dict(context, act=act_id))


def next_turn():
    STATE.k["turn"] += 1
    STATE.new_turn_memory()


STATE.k = new_kingdom()
k = STATE.k
try:
    for role in k["roles"].values():
        role["name"] = "Leader"

    # --- 1. a partner, relations, the envoy's bonus ---------------------------------
    elves = diplomacy.new_partner("Elves of the Narlmarches", 18)
    trolls = diplomacy.new_partner("Trolls", 22)
    dc = STATE.activity_dc("send_diplomatic_envoy", subject=elves["id"])[0]
    results.append(("the envoy's DC is the partner's Negotiation DC", dc == 18))
    apply("send_diplomatic_envoy", "critical_success", elves["id"], subject=elves["id"])
    rel = STATE.relation(elves["id"])
    results.append(("a critical success: relations established", rel and rel["status"] == "relations"))
    results.append(("and the milestone, once", k["milestones"].count("first_diplomatic_relation") == 1))
    apply("send_diplomatic_envoy", "success", elves["id"], subject=elves["id"])
    results.append(("a second success awards no second milestone",
                    k["milestones"].count("first_diplomatic_relation") == 1))
    next_turn()
    name = act["send_diplomatic_envoy"]["name"]
    with_elves = dict(STATE.check_detail("statecraft", "send_diplomatic_envoy", subject=elves["id"]))
    with_trolls = dict(STATE.check_detail("statecraft", "send_diplomatic_envoy", subject=trolls["id"]))
    results.append(("its +2 reaches a check with those elves next turn", with_elves.get(name) == 2))
    results.append(("not one with another partner", name not in with_trolls))
    next_turn()
    with_elves = dict(STATE.check_detail("statecraft", "send_diplomatic_envoy", subject=elves["id"]))
    results.append(("and expires after", name not in with_elves))

    # --- 2. an envoy to a partner at war --------------------------------------------
    STATE.apply_effect({"t": "relation", "status": "war"}, 0, trolls["id"], None, {"subject": trolls["id"]})
    extra = turn.activity_extra("send_diplomatic_envoy", trolls["id"])
    results.append(("an envoy to the enemy: -4 circumstance and one degree worse",
                    extra and extra[0][1] == -4 and STATE.worsens_by("send_diplomatic_envoy", trolls["id"]) == 1))
    results.append(("not to a friend", not turn.activity_extra("send_diplomatic_envoy", elves["id"])))

    # --- 3. trade agreements ------------------------------------------------------------
    k["level"] = 1
    dc, parts = STATE.activity_dc("establish_trade_agreement", subject=elves["id"])
    results.append(("the agreement's DC: the higher of the Negotiation and Control DCs",
                    dc == max(18, STATE.control_dc)))
    apply("establish_trade_agreement", "success", elves["id"], subject=elves["id"])
    results.append(("a success: the agreement", [a["partner"] for a in STATE.active_agreements()] == [elves["id"]]))
    results.append(("+1 to Trade Commodities with diplomatic relations",
                    dict(STATE.check_detail("trade", "trade_commodities")).get("Diplomatic relations") == 1))
    rel = STATE.relation(elves["id"])
    status, rel["status"] = rel["status"], "ended"
    results.append(("not once the relations are ended, agreement or not",
                    "Diplomatic relations" not in dict(STATE.check_detail("trade", "trade_commodities"))))
    rel["status"] = status
    paid = {r["t"] for r in rows_of("establish_trade_agreement", "failure")}
    results.append(("a failure, once its Resource Dice are paid, offers the agreement too",
                    {"resource_die", "agreement", "milestone"} <= paid))
    STATE.apply_effect({"t": "agreement", "what": "ended"}, 0, elves["id"], None, {"subject": elves["id"]})
    results.append(("ended: no agreement", not STATE.active_agreements()))

    # --- 4. foreign aid's RP ---------------------------------------------------------------
    k["rp"], k["rp_no_xp"] = 0, 0
    aid = next(r for r in act["request_foreign_aid"]["effects"]["critical_success"] if r["t"] == "resource_die")
    STATE.apply_effect(aid, 2, None, None, {"act": "request_foreign_aid"})
    gained = k["rp"]
    k["rp"] += 5                                    # RP of the turn's own
    results.append(("foreign aid's RP does not become XP, the rest does",
                    gained > 0 and k["rp_no_xp"] == gained and turn.convertible_rp() == 5))
    STATE.roll_resource_dice()
    results.append(("the next Resource Dice start afresh", k["rp_no_xp"] == 0))

    # --- 5. Pledge of Fealty -----------------------------------------------------------------
    capital = new_settlement("Riverhold", (5, 5))
    k["settlements"].append(capital)
    k["capital"] = capital["id"]
    STATE.hex(5, 5).update(status="claimed", settlement=capital["id"])
    lost = new_settlement("Hillfort", (5, 6))
    lost["grids"][0][4][0] = {"structure": "inn", "gid": "x1"}
    STATE.hex(5, 6)["features"].append({"kind": "freehold", "name": "Hillfort", "settlement_data": lost})
    STATE.hex(9, 9)["features"].append({"kind": "freehold", "name": "Far Hamlet"})
    claim = next(r for r in act["pledge_of_fealty"]["effects"]["critical_success"] if r["t"] == "claim")
    STATE.apply_effect(claim, 0, None, None, {"act": "pledge_of_fealty", "hex": (5, 6)})
    back = STATE.settlement(lost["id"])
    results.append(("a freehold that was the kingdom's comes back with its grid",
                    back is not None and back["grids"][0][4][0]["structure"] == "inn"
                    and STATE.hex(5, 6)["status"] == "claimed"))
    STATE.apply_effect(claim, 0, None, None, {"act": "pledge_of_fealty", "hex": (9, 9)})
    far = next(s for s in k["settlements"] if s["name"] == "Far Hamlet")
    results.append(("one never the kingdom's comes with an empty grid",
                    not any(lot["structure"] for block_ in far["grids"][0] for lot in block_)))
    results.append(("away from the kingdom it is a secondary territory", (9, 9) in STATE.secondary_hexes()))
finally:
    STATE.k = saved_kingdom
    rules.roll_check = saved_check
    rules.roll = saved_roll


# --- 6. in a window: the Upkeep at war -------------------------------------------------------
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
            orcs = diplomacy.new_partner("Orcs", 20)
            step = next(s for s in rules.TURN_PHASES[0]["steps"] if s["id"] == "unrest")
            with user.client:
                with ui.element("div") as box:
                    turn._upkeep_step(step)
            results.append(("at peace: no war buttons", "at war" not in texts(box)))
            STATE.k["diplomatic_relations"].append({"partner": orcs["id"], "since_turn": 0, "status": "war",
                                                    "abstract_war": True, "bonus": 0, "note": ""})
            with user.client:
                with ui.element("div") as box:
                    turn._upkeep_step(step)
            shown = texts(box)
            results.append(("at war: +1 Unrest, and the war without armies' rows",
                            "+1 Unrest: at war" in shown and "War without armies" in shown))
        finally:
            STATE.k = saved
        # A partner is a document write: once on disk, the revision the
        # launcher's /_launcher/status reports (`archive.rev`) has risen. On
        # the scene's own kingdom, never on the throwaway one above: writing
        # that to disk once emptied the scene for every test after this one.
        before = STATE.archive.rev
        try:
            with user.client:
                diplomacy._add_partner("Lizardfolk", 17)
            theme.write_to_disk()
            results.append(("a partner added raises the revision the launcher reads",
                            STATE.archive.rev > before
                            and any(p["name"] == "Lizardfolk" for p in STATE.k["partners"])))
        finally:
            STATE.k["partners"] = [p for p in STATE.k["partners"] if p["name"] != "Lizardfolk"]
            theme.mark_dirty()
            theme.write_to_disk()
            user.client.delete()


asyncio.run(window_run())

for name, ok in results:
    print(f" {'ok' if ok else 'NO'}  {name}")
print(f"{sum(1 for _n, ok in results if ok)}/{len(results)} passed")
