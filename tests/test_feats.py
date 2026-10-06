# -*- coding: utf-8 -*-
"""The kingdom feats, each doing what its text says once taken, and the
vacancy penalties of the leadership roles, which Civil Service waives.

Until 1.1.7 only Endure Anarchy's threshold and Fortified Fiefs' bonus to
Fortify Hex were applied: every other feat was a tick on the sheet. Every
check now rolls through `State.kingdom_check`, which builds the modifier with
the PF2e stacking rules (`State.skill_detail`) and then lets the feats act on
the result; this file takes them one by one, on a kingdom built in memory.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from kingmaker import rules  # noqa: E402
from kingmaker.state import STATE, new_kingdom  # noqa: E402

results = []
saved_kingdom, saved_roll = STATE.k, rules.roll_check


def names(detail):
    return dict(detail)


def total(skill, activity=None, **kw):
    return sum(v for _n, v in STATE.check_detail(skill, activity, **kw))


def take(*feats):
    STATE.k["feats"] = list(feats)


def fixed(grade, natural=10):
    """The next roll_check answers this degree."""
    rules.roll_check = lambda mod, dc, detail=None, worsens_by=0: rules.Result(
        natural, mod, natural + mod, dc, grade, detail or [])


STATE.k = new_kingdom()
k = STATE.k
try:
    k["level"] = 5
    for rid, role in k["roles"].items():
        role.update(name=f"Leader {rid}", invested=False)
    feat = lambda fid: rules.BY_ID["feat"][fid]["name"]  # noqa: E731

    # --- vacancy penalties -------------------------------------------------
    base, arts = total("trade"), total("arts")
    k["roles"]["treasurer"]["absent"] = True
    results.append(("a vacant Treasurer: -1 to Economy checks", total("trade") == base - 1))
    results.append(("and not to others", total("arts") == arts))
    k["roles"]["ruler"]["name"] = ""
    results.append(("a vacant Ruler: another -1, stacking", total("trade") == base - 2))
    dc = STATE.control_dc
    k["roles"]["warden"]["absent"] = True
    results.append(("a vacant Warden: -4 to Region activities",
                    total("agriculture", "harvest_crops") == total("agriculture") - 4))
    k["roles"]["general"]["absent"] = True
    results.append(("a vacant General: -4 to Army activities",
                    total("warfare", "train_army") == total("warfare") - 4))
    take("civil_service")
    k["feat_choices"]["civil_service"] = "ruler"
    results.append(("Civil Service waives the chosen role's penalty",
                    total("trade") == base - 1 and STATE.control_dc == dc - 2))
    results.append(("and gives +2 status to New Leadership",
                    names(STATE.check_detail("statecraft", "new_leadership")).get(
                        f"{feat('civil_service')} (status)") == 2))
    for role in k["roles"].values():
        role.update(absent=False, name=role["name"] or "Leader")
    take()

    # --- stacking: one status bonus, one circumstance bonus -----------------
    k["roles"]["treasurer"]["invested"] = True       # Economy: +1 status
    take("insider_trading")
    detail = names(STATE.check_detail("engineering", "establish_work_site"))
    results.append(("Insider Trading: +1 status to Establish Work Site",
                    detail.get(f"{feat('insider_trading')} (status)") == 1))
    eco = names(STATE.check_detail("trade", "establish_trade_agreement"))
    results.append(("status bonuses do not stack: the leader's or the feat's, one",
                    sum(1 for n in eco if "(status)" in n.lower() or "status" in n.lower()) == 1))
    n_before = STATE.resource_dice_count
    take()
    results.append(("Insider Trading: 1 bonus Resource Die every turn",
                    n_before == STATE.resource_dice_count + 1))
    k["roles"]["treasurer"]["invested"] = False

    # --- Practical Magic ---------------------------------------------------
    take("practical_magic")
    with_feat = total("magic")
    results.append(("Practical Magic: +1 status to Magic",
                    names(STATE.skill_detail("magic")).get(f"{feat('practical_magic')} (status)") == 1))
    take()
    results.append(("and only while taken", total("magic") == with_feat - 1))

    # --- Inspiring Entertainment ------------------------------------------
    take("inspiring_entertainment")
    k["unrest"] = 0
    calm = total("arts")
    k["unrest"] = 1
    results.append(("Inspiring Entertainment: +2 status to Culture with Unrest",
                    names(STATE.skill_detail("arts")).get(f"{feat('inspiring_entertainment')} (status)") == 2))
    results.append(("which beats the Unrest penalty's -1 of the same type? no: both count",
                    total("arts") == calm + 2 - 1))
    k["unrest"] = 0
    take()

    # --- event feats --------------------------------------------------------
    take("quick_recovery", "fortified_fiefs", "crush_dissent")
    results.append(("Quick Recovery: +4 status to end an ongoing event",
                    total("defense", event="ongoing") == total("defense") + 4))
    results.append(("Fortified Fiefs: +1 status against events on the defenses",
                    total("defense", event="defenses") == total("defense") + 1))
    results.append(("Crush Dissent: +1 status against internal bickering",
                    total("defense", event="bickering") == total("defense") + 1))
    results.append(("Fortified Fiefs: +2 to build a Keep",
                    total("industry", "build_structure", variant="keep")
                    == total("industry", "build_structure", variant="houses") + 2))
    results.append(("and to Fortify Hex", total("defense", "fortify_hex") == total("defense") + 2))
    take()

    # --- Free and Fair -----------------------------------------------------
    take("free_and_fair")
    results.append(("Free and Fair: +2 circumstance to Loyalty New Leadership",
                    total("politics", "new_leadership") == total("politics") + 2))
    results.append(("not on its own reroll", total("politics", "new_leadership", fair=False) == total("politics")))
    results.append(("not with a non-Loyalty skill", total("trade", "new_leadership") == total("trade")))
    take()

    # --- Pull Together -----------------------------------------------------
    take("pull_together")
    fixed("critical_failure")
    real_roll = rules.roll
    rules.roll = lambda n, faces: (15, [15])
    res = STATE.kingdom_check("trade", 20)
    results.append(("Pull Together: a DC 11 flat check turns a critical failure into a failure",
                    res.grade == "failure" and res.notes and k["pull_together_dc"] == 16))
    fixed("critical_failure")
    res = STATE.kingdom_check("trade", 20)
    results.append(("once a turn", res.grade == "critical_failure"))
    k["turn"] += 1
    STATE.new_turn_feats()
    results.append(("the DC stays up for a turn it was used in", k["pull_together_dc"] == 16))
    k["turn"] += 1
    STATE.new_turn_feats()
    results.append(("and drops by 1 for a turn it was not", k["pull_together_dc"] == 15))
    rules.roll = lambda n, faces: (3, [3])
    fixed("critical_failure")
    res = STATE.kingdom_check("trade", 20)
    results.append(("a failed flat check leaves the critical failure", res.grade == "critical_failure"))
    rules.roll = real_roll
    take()

    # --- Focused Attention and Cooperative Leadership ------------------------
    STATE.apply_effect({"t": "focus", "q": "1"}, 1, "trade")
    results.append(("Focused Attention: +2 circumstance to the chosen skill",
                    names(STATE.skill_detail("trade")).get(rules.BY_ID["activities"]["focused_attention"]["name"]) == 2))
    fixed("success")
    STATE.kingdom_check("trade", 15)
    results.append(("used up by the next check with it", not any(m.get("once") for m in k["modifiers"])))
    take("cooperative_leadership")
    STATE.apply_effect({"t": "focus", "q": "1"}, 1, "trade")
    results.append(("Cooperative Leadership: +3 instead",
                    names(STATE.skill_detail("trade")).get(rules.BY_ID["activities"]["focused_attention"]["name"]) == 3))
    k["level"] = 11
    fixed("critical_failure")
    res = STATE.kingdom_check("trade", 30)
    results.append(("at 11th level the aided critical failure is a failure", res.grade == "failure"))
    k["proficiencies"]["trade"] = "expert"
    STATE.apply_effect({"t": "focus", "q": "1"}, 1, "trade")
    fixed("failure")
    res = STATE.kingdom_check("trade", 30)
    results.append(("and with expert rank a failure is a success", res.grade == "success"))
    k["level"] = 5
    take()

    # --- Fame and Fortune ----------------------------------------------------
    take("fame_and_fortune")
    k["bonus_dice"] = 0
    fixed("critical_success", 20)
    STATE.kingdom_check("trade", 10, "establish_trade_agreement")
    results.append(("Fame and Fortune: a critical success in the Activity phase, +1 die",
                    k["bonus_dice"] == 1))
    fixed("critical_success", 20)
    STATE.kingdom_check("trade", 10, "collect_taxes")
    results.append(("not in the Commerce phase", k["bonus_dice"] == 1))
    take()

    # --- Kingdom Assurance ---------------------------------------------------
    take("kingdom_assurance")
    k["feat_choices"]["kingdom_assurance"] = ["trade"]
    results.append(("Kingdom Assurance on a chosen trained skill", STATE.assurance_available("trade")))
    res = STATE.assurance_result("trade", 20)
    results.append(("10 + proficiency, nothing else",
                    res.total == 10 + rules.proficiency_bonus(5, "expert")))
    results.append(("once a turn", not STATE.assurance_available("trade")))
    results.append(("not on a skill not chosen", not STATE.assurance_available("arts")))
    take()

    # --- Endure Anarchy ----------------------------------------------------
    take("endure_anarchy")
    k["unrest"] = 8
    STATE.apply_effect({"t": "unrest", "q": "-1"}, -1)
    results.append(("Endure Anarchy: an activity lowering Unrest at 6+ takes 1 more", k["unrest"] == 6))
    STATE.apply_effect({"t": "unrest", "q": "-1"}, -1)
    results.append(("and again at 6", k["unrest"] == 4))
    STATE.apply_effect({"t": "unrest", "q": "-1"}, -1)
    results.append(("not below 6", k["unrest"] == 3))
    results.append(("anarchy at 24", STATE.anarchy_threshold == 24))
    k["unrest"] = 0
    take()

    # --- Quality of Life ---------------------------------------------------
    take("quality_of_life")
    k["commodities"]["luxuries"] = 0
    STATE.add_commodity("luxuries", 1)
    STATE.add_commodity("luxuries", 1)
    results.append(("Quality of Life: the first Luxuries of a turn +1", k["commodities"]["luxuries"] == 3))
    take()

    # --- Muddle Through ------------------------------------------------------
    thresholds = {rid: r["threshold"] for rid, r in k["ruins"].items()}
    take("muddle_through")
    k["feat_choices"]["muddle_through"] = {"plus2": "crime", "none": "decay", "applied": {}}
    STATE.muddle_through(True)
    moved = {rid: k["ruins"][rid]["threshold"] - thresholds[rid] for rid in thresholds}
    results.append(("Muddle Through: one threshold +2, two +1, one unchanged",
                    sorted(moved.values()) == [0, 1, 1, 2] and moved["crime"] == 2 and moved["decay"] == 0))
    STATE.muddle_through(False)
    results.append(("dropped: the thresholds back as they were",
                    all(k["ruins"][rid]["threshold"] == v for rid, v in thresholds.items())))
    take()

    # --- Crush Dissent and Liquidate Resources: offered ----------------------
    take("crush_dissent", "liquidate_resources")
    STATE.feat_offers.clear()
    STATE.modify_unrest(2)
    results.append(("Crush Dissent is offered when Unrest rises",
                    [o["kind"] for o in STATE.take_feat_offers()] == ["crush_dissent"]))
    k["rp"] = 1
    STATE.apply_effect({"t": "rp", "q": "-3"}, -3)
    offers = STATE.take_feat_offers()
    results.append(("Liquidate Resources is offered when an outcome cannot be paid",
                    [o["kind"] for o in offers] == ["liquidate_resources"]))
    results.append(("liquidated: RP at 1, 4 fewer dice next turn",
                    STATE.liquidate() and k["rp"] == 1 and k["penalty_dice"] == 4))
    results.append(("once a turn", not STATE.liquidate()))
    take()
finally:
    STATE.k = saved_kingdom
    rules.roll_check = saved_roll

for name, ok in results:
    print(f" {'ok' if ok else 'NO'}  {name}")
print(f"{sum(1 for _n, ok in results if ok)}/{len(results)} passed")
