# -*- coding: utf-8 -*-
"""Build the English text files from the Archives of Nethys entries.

    python tools/aon_to_texts.py <aon_dir> [<out_dir>]

`<aon_dir>` holds the JSON saved by `tools/fetch_aon.py`. For structures,
activities and feats the entries are matched to ours by the slug of their
English name (the ids of `kingmaker/rules/data/*.json` are those slugs); vehicles
are matched through `VEHICLE_NAMES`, our Italian ids to the English names.
The markdown of Archives of Nethys is reduced to plain text: links become
their label, `<br />` a line break, the tags of the page skeleton go away.

The output has the same shape as `kingmaker/rules/data/lang/it/<file>` and is
written to `<out_dir>` (default: `kingmaker/rules/data/lang/en`). Whatever cannot
be matched is reported and left as it was in the output file, so nothing is
silently lost.
"""
from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "kingmaker" / "rules" / "data"
IT = DATA / "lang" / "it"

# Our vehicle ids (Italian slugs from the wiki) -> Archives of Nethys names.
VEHICLE_NAMES = {
    "aeronave": "Airship", "aliante": "Glider", "apparato_del_polipo": "Apparatus of the Octopus",
    "barca_a_remi": "Rowboat", "barca_planare": "Planar Skiff", "batisfera": "Bathysphere",
    "bici_automatizzata": "Automated Cycle", "calderone_del_volare": "Cauldron of Flying",
    "calpestatore_titanico": "Titanic Stomper", "carrello_a_vapore": "Steam Trolley",
    "carretto": "Cart", "carretto_a_vapore": "Steam Cart", "carro": "Wagon",
    "carro_da_guerra_leggero": "Chariot, Light", "carro_da_guerra_pesante": "Chariot, Heavy",
    "carro_meccanico": "Clockwork Wagon", "carrozza": "Carriage",
    "carrozza_corazzata": "Armored Carriage", "carrozza_lumaca": "Snail Coach",
    "castello_meccanico": "Clockwork Castle", "chiatta_della_sabbia": "Sand Barge",
    "cutter": "Cutter", "deltaplano_di_piccocroce": "Hillcross Glider", "elepoli": "Helepolis",
    "galea": "Galley", "gigante_a_vapore": "Steam Giant", "locanda_mobile": "Mobile Inn",
    "lucciola": "Firefly", "meccano_bombo": "Clockwork Bumblebee", "nave_a_vela": "Sailing Ship",
    "passolungo": "Strider", "pedalo_adattabile": "Adaptable Paddleboat",
    "ponte_d_oro_di_vonthos": "Vonthos's Golden Bridge", "saltatore_meccanico": "Clockwork Hopper",
    "salterello_d_artificio": "Firework Pogo", "scatorcio": "Clunkerjunker",
    "scavalcarupi": "Cliff Crawler", "scavasabbia": "Sand Diver", "slitta": "Sleigh",
    "sommergibile_squalo": "Shark Diver", "topografo_mobile": "Ambling Surveyor",
    "torre_d_assedio": "Siege Tower", "trivella_meccanica": "Clockwork Borer",
    "velocipede": "Velocipede", "velocista": "Speedster",
}

DEGREES = ("critical_success", "success", "failure", "critical_failure")
DEGREE_TITLES = {"Critical Success": "critical_success", "Success": "success",
                 "Failure": "failure", "Critical Failure": "critical_failure"}


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def clean(md: str) -> str:
    """Archives of Nethys markdown -> plain text with line breaks."""
    text = re.sub(r"<title[^>]*>.*?</title>", "", md, flags=re.S)
    text = re.sub(r"<traits>.*?</traits>", "", text, flags=re.S)
    text = re.sub(r"<actions[^>]*/>", "", text)
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"</?(column|row)[^>]*>", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)      # links -> label
    text = re.sub(r"\*\*Source\*\*[^\n]*\n", "", text)
    text = html.unescape(text)
    text = text.replace("\r", "")
    return text


def sections(md: str) -> tuple[str, dict[str, str]]:
    """The body paragraph(s) and the `**Heading** text` blocks that follow."""
    text = clean(md)
    parts = re.split(r"\n---\n", text)
    body_parts, blocks = [], {}
    for part in parts:
        for chunk in re.split(r"\n\s*\n", part.strip()):
            chunk = chunk.strip()
            if not chunk:
                continue
            m = re.match(r"^\*\*([^*]+)\*\*\s*(.*)$", chunk, flags=re.S)
            if m and m.group(1).strip() not in DEGREE_TITLES:
                blocks[m.group(1).strip()] = m.group(2).strip()
            elif any(chunk.startswith(f"**{d}**") for d in DEGREE_TITLES):
                blocks["__degrees__"] = (blocks.get("__degrees__", "") + "\n" + chunk).strip()
            else:
                body_parts.append(chunk)
    return "\n\n".join(body_parts).strip(), blocks


def degrees(chunk: str) -> dict[str, str]:
    """`**Critical Success** ...\\n**Success** ...` -> one text per degree."""
    found = {}
    pieces = re.split(r"\*\*(Critical Success|Success|Failure|Critical Failure)\*\*\s*", chunk)
    for i in range(1, len(pieces) - 1, 2):
        found[DEGREE_TITLES[pieces[i]]] = pieces[i + 1].strip()
    return found


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


# Our ids whose English name does not slug to the id.
ALIASES = {"wooden_wall": "Wall, Wooden", "stone_wall": "Wall, Stone",
           "arcanists_tower": "Arcanist's Tower",
           "skill_training": "Skill Training (Kingdom)", "quick_recovery": "Quick Recovery (Kingdom)"}


DISPLAY = {"Wall, Wooden": "Wooden Wall", "Wall, Stone": "Stone Wall",
           "Chariot, Light": "Light Chariot", "Chariot, Heavy": "Heavy Chariot"}

# Texts of the app's own making (the structured effects, and the degrees the
# Italian wiki spells out where the book does not), translated by hand.
EFFECT_TEXTS = json.loads((Path(__file__).with_name("effect_texts_en.json")).read_text(encoding="utf-8"))
# The notes at the top of the files are the app's own: translated by hand.
TOP_NOTES = {
    "activities.json": {"_dc_note": "kind 'control' = the kingdom's Control DC + mod; 'fixed' = absolute value; 'special' = see note"},
    "vehicles.json": {
        "_note": "Transcribed from Archives of Nethys, nothing added by hand. «speed» reports the feet per movement kind as written on the vehicle's page, converted to metres; when the page gives no number, «speed» stays empty and «speed_depends_on» says what it depends on: «towing» = the Speed of the slowest creature towing it, «pilot» = the pilot's Speed, «not given» = the page does not give it as a distance. In those cases the table enters the value: the app does not guess it.",
        "_exploration_note": "Hexploration derives the activities per day from the party's Speed and does not say explicitly that a vehicle replaces it. Using the vehicle's Speed instead of the slowest member's is therefore a reading by the table, not a written rule: the app proposes it and says so every time.",
    },
}
OVERRIDES = {
    "activities": {
        "focused_attention": {"outcomes": {
            "critical_success": "As Success.",
            "success": "You grant that leader a +2 circumstance bonus to one kingdom check using that skill, provided that leader attempts the skill check during the same Kingdom turn.",
            "failure": "No benefit.",
            "critical_failure": "No benefit.",
        }},
    },
}


def display_name(name: str) -> str:
    """The name without the disambiguation Archives of Nethys adds."""
    return DISPLAY.get(name, re.sub(r"\s*\(Kingdom\)$", "", name))


def by_slug(rows: list[dict]) -> dict[str, dict]:
    table = {slug(r["name"]): r for r in rows}
    for ours, theirs in ALIASES.items():
        if slug(theirs) in table:
            table[ours] = table[slug(theirs)]
    return table


def structures(aon: Path, it: dict) -> tuple[list, list]:
    rows = by_slug(load(aon / "structures.json"))
    out, missing = [], []
    for entry in it:
        row = rows.get(entry["id"])
        if row is None:
            missing.append(entry["id"])
            out.append(entry)
            continue
        body, blocks = sections(row["markdown"])
        new = {"id": entry["id"], "name": display_name(row["name"])}
        if "description" in entry:
            new["description"] = body
        if "cost_raw" in entry:
            new["cost_raw"] = row.get("cost") or blocks.get("Cost", "")
        if "construction" in entry:
            new["construction"] = {"raw": blocks.get("Construction", "").replace("\n", ", ")}
        if "item_bonus" in entry:
            new["item_bonus"] = blocks.get("Item Bonus", "")
        if "ruin" in entry:
            new["ruin"] = blocks.get("Ruin", "")
        if "effects" in entry:
            new["effects"] = blocks.get("Effects", "")
        if "consumption" in entry:
            new["consumption"] = blocks.get("Consumption", "")
        if "kingdom_effects" in entry:
            new["kingdom_effects"] = [{"text": blocks.get("Effects", "")} if k else None
                                      for k in entry["kingdom_effects"]]
        out.append(new)
    return out, missing


def activities(aon: Path, it: dict) -> tuple[dict, list]:
    rows = by_slug(load(aon / "activities.json"))
    out, missing = {k: v for k, v in it.items() if k != "activities"}, []
    out["activities"] = []
    for entry in it["activities"]:
        row = rows.get(entry["id"])
        if row is None:
            missing.append(entry["id"])
            out["activities"].append(entry)
            continue
        body, blocks = sections(row["markdown"])
        new = {"id": entry["id"], "name": display_name(row["name"])}
        if "traits" in entry:
            new["traits"] = list(row["trait"]) if isinstance(row["trait"], list) else json.loads(row["trait"].replace("'", '"'))
        if "requirements" in entry:
            new["requirements"] = blocks.get("Requirements", row.get("requirement") or "")
        if "cost" in entry:
            new["cost"] = blocks.get("Cost", "")
        if "description" in entry:
            new["description"] = body
        if "outcomes" in entry:
            new["outcomes"] = degrees(blocks.get("__degrees__", ""))
        for key, value in OVERRIDES["activities"].get(entry["id"], {}).items():
            new[key] = value
        if "effects" in entry:
            new["effects"] = {}
            for degree, items in entry["effects"].items():
                new["effects"][degree] = [effect_item(x, entry, row["name"]) for x in items]
        # The app's own notes on the DC and the structured cost: by hand.
        if "dc" in entry:
            new["dc"] = {"note": hand_text(entry["dc"].get("note", ""))}
        if "cost_data" in entry:
            new["cost_data"] = [({"text": hand_text(c["text"])} if c else None)
                                for c in entry["cost_data"]]
        out["activities"].append(new)
    return out, missing


ITALIAN_MODIFIERS = {k: v for k, v in EFFECT_TEXTS.items() if not k.startswith("_")}


def hand_text(italian: str) -> str:
    """One of the app's own texts, translated in `effect_texts_en.json`."""
    if italian in ITALIAN_MODIFIERS and ITALIAN_MODIFIERS[italian]:
        return ITALIAN_MODIFIERS[italian]
    ITALIAN_MODIFIERS.setdefault(italian, None)
    return italian


def effect_item(item, entry: dict, english_name: str):
    """The texts of one structured effect: the modifier's name, or the note."""
    if not item:
        return None
    new = {}
    if "name" in item:
        new["name"] = modifier_name(item["name"], entry, english_name)
    if "text" in item:
        new["text"] = ITALIAN_MODIFIERS.get(item["text"]) or item["text"]
        ITALIAN_MODIFIERS.setdefault(item["text"], None)
    return new


def modifier_name(italian: str, entry: dict, english_name: str) -> str:
    """The name of a temporary modifier: the activity's English name with the
    bonus type, or a hand-written translation for the special ones."""
    if italian in ITALIAN_MODIFIERS:
        return ITALIAN_MODIFIERS[italian]
    kind = ""
    m = re.search(r"\(([^)]+)\)\s*$", italian)
    if m:
        kind = {"Circostanza": "circumstance", "Status": "status", "Oggetto": "item"}.get(m.group(1), m.group(1).lower())
    base = italian[:m.start()].strip() if m else italian
    if base == entry.get("name"):
        return f"{english_name} ({kind})" if kind else english_name
    ITALIAN_MODIFIERS.setdefault(italian, None)
    return italian


def feats(aon: Path, it: dict) -> tuple[dict, list]:
    rows = by_slug(load(aon / "feats.json"))
    out, missing = {k: v for k, v in it.items() if k != "feats"}, []
    out["feats"] = []
    for entry in it["feats"]:
        row = rows.get(entry["id"])
        if row is None:
            missing.append(entry["id"])
            out["feats"].append(entry)
            continue
        body, blocks = sections(row["markdown"])
        new = {"id": entry["id"], "name": display_name(row["name"])}
        if "traits" in entry:
            new["traits"] = list(row["trait"]) if isinstance(row["trait"], list) else json.loads(row["trait"].replace("'", '"'))
        if "prerequisites" in entry:
            new["prerequisites"] = blocks.get("Prerequisites", "")
        if "summary" in entry:
            new["summary"] = (row.get("summary") or body.split("\n")[0]).strip()
        if "description" in entry:
            new["description"] = body
        out["feats"].append(new)
    return out, missing


def vehicles(aon: Path, it: dict) -> tuple[dict, list]:
    rows = {}
    for r in load(aon / "vehicles.json"):
        # two entries per name (Gamemastery Guide and GM Core): ours are
        # transcribed from the former, so that one wins
        if r["name"] not in rows or r.get("primary_source") == "Gamemastery Guide":
            rows[r["name"]] = r
    out, missing = {k: v for k, v in it.items() if k != "vehicles"}, []
    out["vehicles"] = []
    for entry in it["vehicles"]:
        row = rows.get(VEHICLE_NAMES.get(entry["id"], ""))
        if row is None:
            missing.append(entry["id"])
            out["vehicles"].append(entry)
            continue
        body, blocks = sections(row["markdown"])
        new = {"id": entry["id"], "name": display_name(row["name"])}
        size = row.get("size")
        values = {
            "rarity": str(row.get("rarity") or "common").capitalize(),
            "size": ", ".join(size) if isinstance(size, list) else str(size or ""),
            "price": row.get("price_raw") or blocks.get("Price", ""),
            "crew": row.get("crew") or blocks.get("Crew", ""),
            "passengers": str(row.get("passengers_raw") or row.get("passengers") or blocks.get("Passengers", "")),
            "space": row.get("space") or blocks.get("Space", ""),
            "piloting": row.get("piloting_check") or blocks.get("Piloting Check", ""),
            "speed_text": row.get("speed_raw") or blocks.get("Speed", ""),
            "collision": blocks.get("Collision", ""),
            "source": row.get("primary_source") or "",
        }
        for ours, value in values.items():
            if ours in entry:
                new[ours] = str(value).strip()
        out["vehicles"].append(new)
    return out, missing


def main(aon: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {}
    for name, fn in (("structures.json", structures), ("activities.json", activities),
                     ("feats.json", feats), ("vehicles.json", vehicles)):
        result, missing = fn(aon, load(IT / name))
        if isinstance(result, dict):
            result.update(TOP_NOTES.get(name, {}))
        (out_dir / name).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                                    encoding="utf-8")
        report[name] = missing
    for name, missing in report.items():
        print(f"{name}: {len(missing)} unmatched {missing}")
    unknown = [k for k, v in ITALIAN_MODIFIERS.items() if v is None]
    if unknown:
        print("modifier names to translate by hand:", unknown)


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]) if len(sys.argv) > 2 else DATA / "lang" / "en")
