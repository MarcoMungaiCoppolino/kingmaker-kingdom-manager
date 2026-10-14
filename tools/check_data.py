# -*- coding: utf-8 -*-
"""Checks on the rules data: mechanics and per-language texts.

    python tools/check_data.py

- every language folder under `kingmaker/rules/data/lang/` has the same files, and
  every text file has the same shape as the reference one (`en`): the same
  ids, the same text keys — a hole in a language is reported, not hidden;
- every id referenced by the mechanics exists (structure upgrades, activity
  skills, terrain costs, government skills and feats, heartland terrains);
- every effect row has a known kind, and the kinds of 2.3.0 their fields
  (a lock-out's scope and turns, the event a pending check forces, ...);
  every activity sits in a known phase and step, its repeat, streak and
  subject are well formed; the rest days and the claim effects too;
- the merged tables of every language load without error.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DATA = ROOT / "kingmaker" / "rules" / "data"
LANG = DATA / "lang"


def shape(node, path="") -> set[str]:
    """The set of text slots in a text file: `path.to.key` with list entries
    named by id when they have one."""
    slots = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "id":
                continue
            here = f"{path}.{key}" if path else key
            if isinstance(value, (dict, list)):
                slots |= shape(value, here)
            else:
                slots.add(here)
    elif isinstance(node, list):
        for i, item in enumerate(node):
            if item is None:
                continue
            name = item["id"] if isinstance(item, dict) and "id" in item else str(i)
            slots |= shape(item, f"{path}[{name}]")
    return slots


# Every kind an effect row may have (`State.apply_effect`), and the values
# of the fields the newer kinds read.
EFFECT_KINDS = {"note", "unrest", "ruin", "ruin_choice", "rp", "xp", "fame", "fame_next", "rp_next",
                "focus", "milestone", "commodity", "commodity_choice", "resource_die", "bonus_dice",
                "mod", "lockout", "pending_check", "event_mark", "debt", "repay", "penalty",
                "unclaim", "claim", "relation", "agreement"}
LOCKOUT_SCOPES = {"self", "all", "ruin", "target"}
EVENT_MARKS = {"ended", "hire_bonus", "hire_failed", "hire_locked"}
PENALTY_SCOPES = {"leader", "partner", "kingdom"}
PENALTY_KINDS = {"circumstance", "status", "item", "vacancy"}
RELATION_STATUSES = {"relations", "war", "ended"}
AGREEMENT_WHATS = {"new", "ended"}
SUBJECTS = {"ruin", "role", "partner", "partner_related", "event", "freehold"}
ONLY_IF = {"fame", "no_fame", "repeated"}


def row_problems(where: str, row: dict, forced: set[str]) -> list[str]:
    """What is wrong with one effect row."""
    out = []
    kind = row.get("t")
    if kind not in EFFECT_KINDS:
        return [f"{where}: unknown effect kind {kind!r}"]
    if kind == "lockout" and (row.get("scope") not in LOCKOUT_SCOPES or not isinstance(row.get("turns"), int)):
        out.append(f"{where}: a lockout needs a scope in {sorted(LOCKOUT_SCOPES)} and int turns")
    if kind == "pending_check" and row.get("event") not in forced:
        out.append(f"{where}: pending_check names unknown event {row.get('event')!r}")
    if kind == "event_mark" and row.get("mark") not in EVENT_MARKS:
        out.append(f"{where}: event_mark has unknown mark {row.get('mark')!r}")
    if kind == "penalty" and (row.get("scope") not in PENALTY_SCOPES or row.get("kind") not in PENALTY_KINDS):
        out.append(f"{where}: a penalty needs a scope in {sorted(PENALTY_SCOPES)} "
                   f"and a kind in {sorted(PENALTY_KINDS)}")
    if kind == "relation" and row.get("status") not in RELATION_STATUSES:
        out.append(f"{where}: relation has unknown status {row.get('status')!r}")
    if kind == "agreement" and row.get("what") not in AGREEMENT_WHATS:
        out.append(f"{where}: agreement has unknown what {row.get('what')!r}")
    only_if = row.get("only_if")
    if only_if is not None and only_if not in ONLY_IF and not str(only_if).startswith("debt:"):
        out.append(f"{where}: unknown only_if {only_if!r}")
    return out


def effect_problems(lang: str, tables: dict) -> list[str]:
    """The activities' effect rows, phases, steps, repeats and subjects; the
    rest days and the hex features' claim effects."""
    out = []
    k = tables["KINGDOM"]
    forced = {e["id"] for e in k.get("forced_events", ())}
    steps = {(p["id"], s["id"]) for p in tables["TURN_PHASES"] for s in p["steps"]}
    for a in tables["ACTIVITIES"]:
        where = f"{lang}: activity {a['id']}"
        if (a.get("phase"), a.get("step")) not in steps:
            out.append(f"{where}: unknown phase/step {a.get('phase')!r}/{a.get('step')!r}")
        for grade, rows in (a.get("effects") or {}).items():
            for i, row in enumerate(rows):
                out += row_problems(f"{where} {grade}[{i}]", row, forced)
        for i, row in enumerate(a.get("cost_data") or ()):
            out += row_problems(f"{where} cost[{i}]", row, forced)
        if "repeat_dc" in a and not isinstance(a["repeat_dc"], int):
            out.append(f"{where}: repeat_dc is not an int")
        streak = a.get("streak_dc")
        if streak is not None and not (isinstance(streak, dict) and isinstance(streak.get("per_turn"), int)
                                       and isinstance(streak.get("decay"), int)):
            out.append(f"{where}: streak_dc must be {{per_turn: int, decay: int}}")
        if "subject" in a and a["subject"] not in SUBJECTS:
            out.append(f"{where}: unknown subject {a['subject']!r}")
        for ruin, skill in (a.get("subject_skills") or {}).items():
            if ruin not in tables["BY_ID"]["ruin"] or skill not in tables["BY_ID"]["skills"]:
                out.append(f"{where}: subject_skills pairs unknown {ruin!r} and {skill!r}")
    rest = k.get("leader_rest_days")
    if not isinstance(rest, int) or rest < 1:
        out.append(f"{lang}: kingdom leader_rest_days must be an int of 1 or more")
    for f in tables["HEX_FEATURES"]:
        for i, row in enumerate(f.get("claim_effects") or ()):
            out += row_problems(f"{lang}: hex feature {f['id']} claim_effects[{i}]", row, forced)
    return out


def main() -> int:
    problems = []
    languages = sorted(p.name for p in LANG.iterdir() if p.is_dir())
    reference = "en"
    files = sorted(p.name for p in (LANG / reference).glob("*.json"))
    for lang in languages:
        for name in files:
            path = LANG / lang / name
            if not path.exists():
                problems.append(f"{lang}/{name}: missing")
                continue
            if lang == reference:
                continue
            ref = shape(json.loads((LANG / reference / name).read_text(encoding="utf-8")))
            here = shape(json.loads(path.read_text(encoding="utf-8")))
            for slot in sorted(ref - here):
                problems.append(f"{lang}/{name}: missing text {slot}")
            for slot in sorted(here - ref):
                problems.append(f"{lang}/{name}: extra text {slot} (not in {reference})")
    from kingmaker import rules
    for lang in languages:
        try:
            tables = rules.data(lang)
        except Exception as error:      # noqa: BLE001 — reported, not raised
            problems.append(f"{lang}: the tables do not load: {error!r}")
            continue
        by_id = tables["BY_ID"]
        for s in tables["STRUCTURES"]:
            for other in list(s.get("upgrade_of", [])) + list(s.get("upgrade_to", [])):
                if other not in by_id["structure"]:
                    problems.append(f"{lang}: structure {s['id']} refers to unknown {other!r}")
            for option in (s.get("construction") or {}).get("options", []):
                if option.get("skill") not in by_id["skills"]:
                    problems.append(f"{lang}: structure {s['id']} needs unknown skill {option.get('skill')!r}")
                if option.get("proficiency") not in by_id["proficiency"]:
                    problems.append(f"{lang}: structure {s['id']} needs unknown proficiency {option.get('proficiency')!r}")
            for trait in s.get("traits", []):
                if trait not in by_id["structure_trait"]:
                    problems.append(f"{lang}: structure {s['id']} has unknown trait {trait!r}")
        for a in tables["ACTIVITIES"]:
            for skill in a.get("skills", []):
                if skill != "*" and skill not in by_id["skills"]:
                    problems.append(f"{lang}: activity {a['id']} uses unknown skill {skill!r}")
        for g in tables["GOVERNMENTS"]:
            for skill in g.get("skills", []):
                if skill not in by_id["skills"]:
                    problems.append(f"{lang}: government {g['id']} trains unknown skill {skill!r}")
            if g.get("feat") and g["feat"] not in by_id["feat"]:
                problems.append(f"{lang}: government {g['id']} grants unknown feat {g['feat']!r}")
        for h in tables["HEARTLANDS"]:
            for terrain in h.get("terrains", []):
                if terrain not in by_id["terrain"]:
                    problems.append(f"{lang}: heartland {h['id']} names unknown terrain {terrain!r}")
        for terrain in tables["TERRAIN_COST"]:
            if not terrain.startswith("_") and terrain not in by_id["terrain"]:
                problems.append(f"{lang}: rugged terrain cost for unknown terrain {terrain!r}")
        for terrain in tables["TRAVEL"]["terrains"]:
            if terrain not in by_id["terrain"]:
                problems.append(f"{lang}: travel category for unknown terrain {terrain!r}")
        problems += effect_problems(lang, tables)
    for line in problems:
        print(line)
    print("no problems" if not problems else f"{len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
