# -*- coding: utf-8 -*-
"""Split the rules data into mechanics and per-language texts.

    python tools/split_texts.py

One-off for release 1.0.0. Every file in `kingmaker/rules/data/*.json` is rewritten
with the mechanics only (numbers, ids, flags), and the texts go to
`kingmaker/rules/data/lang/it/<file>` with the same shape — a skeleton holding only
the text fields, list entries carrying their `id` so the two halves can be
matched again. `kingmaker/rules/data/lang/en/<file>` is created as a copy of the
Italian one where it does not exist yet: the English texts are transcribed
from Archives of Nethys afterwards, entry by entry.

Which keys are texts is decided by name (`TEXT_KEYS`), with the two
exceptions listed in `NOT_TEXT`: `structures[].traits` are ids, and the
`source` of a travel terrain is a flag. `rules.load()` does the merge back.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "kingmaker" / "rules" / "data"
LANG = DATA / "lang"

TEXT_KEYS = {
    "name", "desc", "description", "summary", "prerequisites", "requirements",
    "outcomes", "text", "cost_raw", "raw", "item_bonus", "ruin", "consumption",
    "note", "_note", "_page", "_kingdom_turn", "_leaders_rest", "_dc_note",
    "_exploration_note", "_hex_features_note", "party_speed", "sustainable_days",
    "beyond", "water_and_flight", "kind", "capabilities", "traits", "rarity", "size",
    "price", "crew", "passengers", "space", "piloting", "speed_text", "collision",
    "weekdays", "abbr", "effects", "cost", "source",
}
# (file, path-suffix) pairs that are NOT texts even though the key says so.
NOT_TEXT = {
    ("structures.json", "*.traits"),        # ids
    ("kingdom.json", "travel.terrains.*.source"),
    ("kingdom.json", "travel.current.*.source"),
    ("kingdom.json", "travel.borders._source"),
    ("kingdom.json", "travel.travel_speed._source"),
    ("kingdom.json", "travel.travel_speed.between_the_lines._source"),
    ("activities.json", "activities.*.effects"),      # structured
    ("activities.json", "activities.*.cost_data"),
    ("activities.json", "activities.*.dc.kind"),
    ("structures.json", "*.cost"),                    # numbers
    ("structures.json", "*.kingdom_effects.*.kind"),
    ("structures.json", "*.kingdom_effects.*.ruin"),  # a ruin id
    ("kingdom.json", "travel.categories.*.cost"),
    ("kingdom.json", "travel.other_activities.*.cost"),
    ("kingdom.json", "hex_features.*.source"),
    ("calendar.json", "months.*.name"),         # proper nouns, the same everywhere
}
# Mechanics keys that were left in Italian by the rename.
RENAMED_KEYS = {"oppure": "or_category", "come": "as"}


def is_text_value(value) -> bool:
    if isinstance(value, str):
        return True
    if isinstance(value, list):
        return bool(value) and all(isinstance(v, str) for v in value)
    if isinstance(value, dict):
        return bool(value) and all(isinstance(v, str) for v in value.values())
    return False


def matches(pattern: str, path: str) -> bool:
    p_parts, parts = pattern.split("."), path.split(".")
    if len(p_parts) != len(parts):
        return False
    return all(a == "*" or a == b for a, b in zip(p_parts, parts))


def split(node, file_name: str, path: str = ""):
    """Returns (mechanics, texts) for a JSON node."""
    if isinstance(node, dict):
        mech, texts = {}, {}
        for key, value in node.items():
            key_out = RENAMED_KEYS.get(key, key)
            here = f"{path}.{key}" if path else key
            excluded = any(f == file_name and matches(p, here) for f, p in NOT_TEXT)
            if key in TEXT_KEYS and is_text_value(value) and not excluded:
                texts[key_out] = value
            elif isinstance(value, (dict, list)):
                m, tx = split(value, file_name, here)
                mech[key_out] = m
                if tx not in ({}, [], None):
                    texts[key_out] = tx
            else:
                mech[key_out] = value
        if texts and "id" in node and "id" not in texts:
            texts = {"id": node["id"], **texts}
        return mech, texts
    if isinstance(node, list):
        mech, texts = [], []
        any_text = False
        for i, item in enumerate(node):
            m, tx = split(item, file_name, f"{path}.*" if path else "*")
            mech.append(m)
            texts.append(tx if tx not in ({}, []) else None)
            any_text = any_text or tx not in ({}, [], None)
        if not any_text:
            texts = []
        return mech, texts
    return node, None


def merge(mech, texts):
    """Puts the texts back into the mechanics (what `rules` does at load)."""
    if texts is None:
        return mech
    if isinstance(mech, dict) and isinstance(texts, dict):
        for key, value in texts.items():
            if key == "id" and key in mech:
                continue
            if key in mech and isinstance(mech[key], (dict, list)) and isinstance(value, (dict, list)):
                merge(mech[key], value)
            else:
                mech[key] = value
        return mech
    if isinstance(mech, list) and isinstance(texts, list):
        by_id = {m.get("id"): m for m in mech if isinstance(m, dict) and "id" in m}
        for i, tx in enumerate(texts):
            if tx is None:
                continue
            target = by_id.get(tx.get("id")) if isinstance(tx, dict) and "id" in tx else None
            if target is None and i < len(mech):
                target = mech[i]
            if target is not None:
                merge(target, tx)
        return mech
    return mech


def main() -> None:
    (LANG / "it").mkdir(parents=True, exist_ok=True)
    (LANG / "en").mkdir(parents=True, exist_ok=True)
    for path in sorted(DATA.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        mech, texts = split(data, path.name)
        # round trip must give back the original (keys renamed aside)
        check = json.loads(json.dumps(mech))
        merge(check, json.loads(json.dumps(texts)))
        original = json.loads(json.dumps(data).replace('"oppure":', '"or_category":').replace('"come":', '"as":'))
        assert check == original, f"{path.name}: the split does not round-trip"
        path.write_text(json.dumps(mech, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (LANG / "it" / path.name).write_text(
            json.dumps(texts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        en = LANG / "en" / path.name
        if not en.exists():
            shutil.copy(LANG / "it" / path.name, en)
        print(f"{path.name}: mechanics + texts written")


if __name__ == "__main__":
    main()
