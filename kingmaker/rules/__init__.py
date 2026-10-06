"""Kingdom rules — Pathfinder 2e Kingmaker.

The Italian texts come from https://pf2.altervista.org/wiki/Regni and linked
pages, the English ones from Archives of Nethys. This module holds only the
computation logic: no invented data.
"""
from __future__ import annotations

import json
import random
import re
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from kingmaker.locale import i18n
from kingmaker.locale.i18n import t

DATA_DIR = Path(__file__).parent / "data"
LANG_DIR = DATA_DIR / "lang"
# The mechanics files; the texts of each live in `lang/<code>/<same name>`.
FILES = ("kingdom.json", "structures.json", "activities.json", "feats.json",
         "vehicles.json")


def _load(path: Path) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def merge_texts(mechanics, texts):
    """Puts the texts of one language back into the mechanics, in place.

    The text file mirrors the shape of the mechanics file and holds only the
    text fields; list entries carry their `id`, and are matched by it (by
    position when there is none). The inverse of `tools/split_texts.py`.
    """
    if texts is None:
        return mechanics
    if isinstance(mechanics, dict) and isinstance(texts, dict):
        for key, value in texts.items():
            if key == "id" and key in mechanics:
                continue
            if key in mechanics and isinstance(mechanics[key], (dict, list)) \
                    and isinstance(value, (dict, list)):
                merge_texts(mechanics[key], value)
            else:
                mechanics[key] = value
        return mechanics
    if isinstance(mechanics, list) and isinstance(texts, list):
        by_id = {m.get("id"): m for m in mechanics if isinstance(m, dict) and "id" in m}
        for i, tx in enumerate(texts):
            if tx is None:
                continue
            target = by_id.get(tx.get("id")) if isinstance(tx, dict) and "id" in tx else None
            if target is None and i < len(mechanics):
                target = mechanics[i]
            if target is not None:
                merge_texts(target, tx)
        return mechanics
    return mechanics


_MECHANICS = {name: _load(DATA_DIR / name) for name in FILES}
_TABLES: dict[str, dict] = {}


def data(lang: str | None = None) -> dict:
    """The rules tables in one language, texts merged into the mechanics.

    Built once per language and kept: English first, so a text missing from
    another language shows the English one instead of a hole.
    """
    lang = lang if lang in i18n.LANGUAGES else i18n.current()
    if lang in _TABLES:
        return _TABLES[lang]
    merged = {}
    for name in FILES:
        base = deepcopy(_MECHANICS[name])
        for code in dict.fromkeys((i18n.DEFAULT, lang)):
            path = LANG_DIR / code / name
            if path.exists():
                merge_texts(base, _load(path))
        merged[name] = base
    k = merged["kingdom.json"]
    tables = {
        "KINGDOM": k,
        "STRUCTURES": merged["structures.json"],
        "ACTIVITIES": merged["activities.json"]["activities"],
        "FEATS": merged["feats.json"]["feats"],
        # Vehicles live in a file of their own: a long catalogue that concerns
        # travel on the map, not the kingdom sheet.
        "VEHICLES": merged["vehicles.json"]["vehicles"],
        "ABILITIES": k["abilities"], "RUINS": k["ruins"], "SKILLS": k["skills"],
        "CHARTERS": k["charters"], "HEARTLANDS": k["heartlands"],
        "GOVERNMENTS": k["governments"], "ROLES": k["roles"],
        "PROFICIENCIES": k["proficiencies"], "SETTLEMENT_TYPES": k["settlement_types"],
        "COMMODITIES": k["commodities"], "TERRAINS": k["terrains"],
        "HEX_FEATURES": k["hex_features"], "MILESTONE_XP": k["milestone_xp"],
        "TURN_PHASES": k["turn_phases"], "TRAVEL": k["travel"],
        # Building on Rugged Terrain — RP cost per terrain type.
        "TERRAIN_COST": k["disconnected_terrain_cost"],
    }
    tables["BY_ID"] = {
        "ability": {c["id"]: c for c in tables["ABILITIES"]},
        "ruin": {r["id"]: r for r in tables["RUINS"]},
        "skills": {a["id"]: a for a in tables["SKILLS"]},
        "charter": {c["id"]: c for c in tables["CHARTERS"]},
        "territory": {h["id"]: h for h in tables["HEARTLANDS"]},
        "government": {g["id"]: g for g in tables["GOVERNMENTS"]},
        "role": {r["id"]: r for r in tables["ROLES"]},
        "proficiency": {c["id"]: c for c in tables["PROFICIENCIES"]},
        "structure_trait": {x["id"]: x for x in k["structure_traits"]},
        "settlement": {x["id"]: x for x in tables["SETTLEMENT_TYPES"]},
        "commodity": {p["id"]: p for p in tables["COMMODITIES"]},
        "terrain": {x["id"]: x for x in tables["TERRAINS"]},
        "feature": {e["id"]: e for e in tables["HEX_FEATURES"]},
        "activities": {a["id"]: a for a in tables["ACTIVITIES"]},
        "feat": {f["id"]: f for f in tables["FEATS"]},
        "structure": {s["id"]: s for s in tables["STRUCTURES"]},
        "vehicle": {v["id"]: v for v in tables["VEHICLES"]},
    }
    _TABLES[lang] = tables
    return tables


class View:
    """A rules table that answers in the language of the window being drawn.

    `rules.STRUCTURES` is one of these: iterating, indexing and `.get()`
    reach the table of the current language (`i18n.current()`), so the
    panels keep writing `entry["name"]` and every window reads its own
    language. Derived tables in other modules are built the same way with
    `rules.derived(lambda: ...)`.
    """
    __slots__ = ("_getter",)

    def __init__(self, getter: Callable[[], Any]):
        self._getter = getter

    def _target(self):
        return self._getter()

    def __getitem__(self, key):
        return self._target()[key]

    def __iter__(self):
        return iter(self._target())

    def __len__(self):
        return len(self._target())

    def __contains__(self, key):
        return key in self._target()

    def __bool__(self):
        return bool(self._target())

    def __eq__(self, other):
        return self._target() == other

    __hash__ = None

    def __getattr__(self, name):
        return getattr(self._target(), name)

    def __repr__(self):
        return f"View({self._target()!r})"


def _table(name: str) -> View:
    return View(lambda: data()[name])


def derived(build: Callable[[], Any]) -> View:
    """A table computed from the rules, once per language."""
    cache: dict[str, Any] = {}

    def getter():
        lang = i18n.current()
        if lang not in cache:
            cache[lang] = build()
        return cache[lang]
    return View(getter)


KINGDOM = _table("KINGDOM")
STRUCTURES = _table("STRUCTURES")
ACTIVITIES = _table("ACTIVITIES")
FEATS = _table("FEATS")
VEHICLES = _table("VEHICLES")
ABILITIES = _table("ABILITIES")
RUINS = _table("RUINS")
SKILLS = _table("SKILLS")
CHARTERS = _table("CHARTERS")
HEARTLANDS = _table("HEARTLANDS")
GOVERNMENTS = _table("GOVERNMENTS")
ROLES = _table("ROLES")
PROFICIENCIES = _table("PROFICIENCIES")
SETTLEMENT_TYPES = _table("SETTLEMENT_TYPES")
COMMODITIES = _table("COMMODITIES")
TERRAINS = _table("TERRAINS")
HEX_FEATURES = _table("HEX_FEATURES")
MILESTONE_XP = _table("MILESTONE_XP")
TURN_PHASES = _table("TURN_PHASES")
TRAVEL = _table("TRAVEL")
BY_ID = _table("BY_ID")
TERRAIN_COST = _table("TERRAIN_COST")

PROFICIENCY_ORDER = ["untrained", "trained", "expert", "master", "legendary"]


# --------------------------------------------------------------------------
# Dice
# --------------------------------------------------------------------------
def roll(n: int, faces: int) -> tuple[int, list[int]]:
    """Rolls n dice with `faces` faces. Returns (total, rolls)."""
    rolls = [random.randint(1, faces) for _ in range(max(0, n))]
    return sum(rolls), rolls


# --------------------------------------------------------------------------
# Abilities and proficiencies
# --------------------------------------------------------------------------
def modifier(score: int) -> int:
    """Ability modifier, as for PF2e characters."""
    return (score - 10) // 2


def proficiency_bonus(kingdom_level: int, proficiency: str) -> int:
    entry = BY_ID["proficiency"].get(proficiency)
    if not entry or entry["level_bonus"] is None:
        return 0
    return kingdom_level + entry["level_bonus"]


def proficiency_rank(proficiency: str) -> int:
    return BY_ID["proficiency"].get(proficiency, {}).get("rank", 0)


def meets_proficiency(owned: str, request_: str | None) -> bool:
    if not request_:
        return True
    return proficiency_rank(owned) >= proficiency_rank(request_)


# --------------------------------------------------------------------------
# Kingdom size
# --------------------------------------------------------------------------
def size_entry(size_: int) -> dict:
    for entry in KINGDOM["size_table"]:
        if entry["min"] <= size_ <= entry["max"]:
            return entry
    return KINGDOM["size_table"][0]


def level_entry(level: int) -> dict:
    level = max(1, min(20, level))
    return KINGDOM["level_table"][level - 1]


# --------------------------------------------------------------------------
# Unrest and Ruin
# --------------------------------------------------------------------------
def unrest_penalty(unrest: int) -> int:
    """Status penalty to all kingdom checks."""
    pen = 0
    for threshold in KINGDOM["unrest_thresholds"]:
        if unrest >= threshold["min"]:
            pen = threshold["penalty"]
    return pen


def role_status_bonus(kingdom_level: int) -> int:
    """Expert government: +1 base, +2 at 8th, +3 at 16th."""
    if kingdom_level >= 16:
        return 3
    if kingdom_level >= 8:
        return 2
    return 1


# --------------------------------------------------------------------------
# Degrees of success
# --------------------------------------------------------------------------
GRADES = ["critical_failure", "failure", "success", "critical_success"]


def grade_label(grade: str) -> str:
    """The degree of success as shown to people, in the viewer's language."""
    return t(f"rules.grade.{grade}") if grade in GRADES else grade


def success_grade(total: int, cd: int, natural: int) -> str:
    if total >= cd + 10:
        grade = "critical_success"
    elif total >= cd:
        grade = "success"
    elif total <= cd - 10:
        grade = "critical_failure"
    else:
        grade = "failure"

    idx = GRADES.index(grade)
    if natural == 20:
        idx = min(3, idx + 1)
    elif natural == 1:
        idx = max(0, idx - 1)
    return GRADES[idx]


def shift_grade(grade: str, steps: int) -> str:
    return GRADES[max(0, min(3, GRADES.index(grade) + steps))]


@dataclass
class Result:
    natural: int
    modifier: int
    total: int
    cd: int
    grade: str
    detail: list[tuple[str, int]]
    # What happened to the result after the die: a feat that turned it
    # (Pull Together), a bonus used up (Focused Attention). Shown with it.
    notes: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return grade_label(self.grade)

    @property
    def margin(self) -> int:
        return self.total - self.cd


def roll_check(total_modifier: int, cd: int, detail: list[tuple[str, int]] | None = None,
               worsens_by: int = 0) -> Result:
    natural = random.randint(1, 20)
    total = natural + total_modifier
    grade = success_grade(total, cd, natural)
    if worsens_by:
        grade = shift_grade(grade, -worsens_by)
    return Result(natural, total_modifier, total, cd, grade, detail or [])


# --------------------------------------------------------------------------
# Costs
# --------------------------------------------------------------------------
def disconnected_terrain_cost(terrains: list[str]) -> int:
    """The highest RP cost among the hex's terrain features."""
    if not terrains:
        return 1
    return max(TERRAIN_COST.get(t, 1) for t in terrains)


def all_structures() -> list[dict]:
    return [s for s in STRUCTURES if s["id"] != "rubble"]


def activities_for_step(phase: str, step: str) -> list[dict]:
    return [a for a in ACTIVITIES if a["phase"] == phase and a["step"] == step]


# --------------------------------------------------------------------------
# Quantities written in the data: «2», «1d4+1»
# --------------------------------------------------------------------------
def quantity_value(quantity: str) -> tuple[int, str]:
    """«2» → (2, "2"); «1d4+1» → rolls the dice and describes the roll."""
    m = re.fullmatch(r"(\d+)d(\d+)(?:\s*\+\s*(\d+))?", quantity.strip(), re.I)
    if not m:
        return int(quantity), quantity
    total, rolls = roll(int(m.group(1)), int(m.group(2)))
    bonus = int(m.group(3) or 0)
    return total + bonus, f"{quantity} → {rolls}{f' +{bonus}' if bonus else ''} = {total + bonus}"


# --------------------------------------------------------------------------
# Effects of Kingdom activities
# --------------------------------------------------------------------------
_RE_SIGNED = re.compile(r"^([+-]?)(?:(\d+)d(\d+)(?:\s*\+\s*(\d+))?|(\d+))$", re.I)


def signed_value(q: str) -> tuple[int, str]:
    """«-1d6» → (-4, "1d6 → [4]"). The sign is the one written in the data."""
    m = _RE_SIGNED.match(str(q).strip())
    if not m:
        return 0, ""
    sign = -1 if m.group(1) == "-" else 1
    if m.group(5) is not None:
        return sign * int(m.group(5)), ""
    total, rolls = roll(int(m.group(2)), int(m.group(3)))
    bonus = int(m.group(4) or 0)
    die = f"{m.group(2)}d{m.group(3)}" + (f"+{bonus}" if bonus else "")
    return sign * (total + bonus), f"{die} → {rolls}" + (f" +{bonus}" if bonus else "")


def entry_target(entry: dict) -> str | None:
    """«ruin_choice» and «commodity_choice» ask what to apply the effect to."""
    return {"ruin_choice": "ruin", "commodity_choice": "commodity", "focus": "skill"}.get(entry["t"])


def entry_label(entry: dict, value: int) -> str:
    """Short description of an effect, with the value already rolled."""
    kind = entry["t"]
    if kind == "note":
        return entry["text"]
    if kind == "unrest":
        return t("rules.unrest", value=value)
    if kind == "ruin":
        return f"{BY_ID['ruin'][entry['r']]['name']} {value:+d}"
    if kind == "ruin_choice":
        pen = t("rules.penalty", pen=entry['pen']) if entry.get("pen") else ""
        return t("rules.ruin_your_choice", value=value, pen=pen)
    if kind == "rp":
        return f'{t("main.rp")} {value:+d}'
    if kind == "xp":
        return f'{t("main.xp")} {value:+d}'
    if kind == "fame":
        return t("rules.fame_infamy", value=value)
    if kind == "fame_next":
        return t("rules.fame_next_turn", value=value)
    if kind == "rp_next":
        return t("rules.rp_next_turn", value=value)
    if kind == "focus":
        return t("rules.focus")
    if kind == "milestone":
        found = next((m for m in MILESTONE_XP if m["id"] == entry["m"]), {"desc": entry["m"], "xp": 0})
        return t("rules.milestone", desc=found["desc"], xp=found["xp"])
    if kind == "commodity":
        return f"{BY_ID['commodity'][entry['p']]['name']} {value:+d}"
    if kind == "commodity_choice":
        return t("rules.commodity_your_choice", value=value)
    if kind == "resource_die":
        return t("rules.resource_die_gain" if value >= 0 else "rules.resource_die_spend", n=abs(value))
    if kind == "bonus_dice":
        return t("rules.resource_dice_next_turn", value=value)
    if kind == "mod":
        where = (BY_ID["skills"][entry["skill"]]["name"] if entry.get("skill")
                else BY_ID["ability"][entry["ability"]]["name"] if entry.get("ability")
                else t("rules.all_kingdom_checks"))
        when = t("rules.rest_turn") if entry["dur"] <= 1 else t("rules.turns", dur=entry['dur'])
        return t("rules.circumstance", v=entry['v'], where=where, when=when)
    return kind


def structure_effects(st: dict) -> list[dict]:
    """Changes to Unrest and Ruin that a structure proposes to the kingdom.

    They are **data** (`kingdom_effects` in `structures.json`), no longer a
    regex reading of the Italian text: this way the text can change language
    without changing the effects. They remain proposals to confirm: almost all
    of them count only «the first time in a Kingdom Turn» or depend on
    conditions that are the table's to judge.
    """
    return list(st.get("kingdom_effects") or [])
