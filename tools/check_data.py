# -*- coding: utf-8 -*-
"""Checks on the rules data: mechanics and per-language texts.

    python tools/check_data.py

- every language folder under `kingmaker/rules/data/lang/` has the same files, and
  every text file has the same shape as the reference one (`en`): the same
  ids, the same text keys — a hole in a language is reported, not hidden;
- every id referenced by the mechanics exists (structure upgrades, activity
  skills, terrain costs, government skills and feats, heartland terrains);
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
    for line in problems:
        print(line)
    print("no problems" if not problems else f"{len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
