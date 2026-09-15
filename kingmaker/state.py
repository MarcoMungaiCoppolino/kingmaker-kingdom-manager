"""Kingdom state: data model, derived statistics and saving.

The kingdom lives in memory in `State.k` and is written to SQLite by `archive`.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from kingmaker import config, rules
from kingmaker.geometry import hexgrid
from kingmaker.storage import migrations
from kingmaker.rules import almanac
from kingmaker.storage.archive import Archive
from kingmaker.locale.i18n import t

log = logging.getLogger(__name__)

COMMODITY_IDS = [p["id"] for p in rules.COMMODITIES]
RUIN_IDS = [r["id"] for r in rules.RUINS]
ABILITY_IDS = [c["id"] for c in rules.ABILITIES]


# --------------------------------------------------------------------------
def new_kingdom() -> dict:
    return {
        "version": 1,
        "created": False,
        "name": "",
        "level": 1,
        "party_level": 1,
        "xp": 0,
        "turn": 0,
        "charter": None,
        "charter_free_boost": None,
        "heartland": None,
        "government": None,
        "government_free_boost": None,
        "final_boosts": [],
        "reputation": "fame",
        "fame_points": 0,
        "fame_bonus_max": 0,
        "abilities": {c: 10 for c in ABILITY_IDS},
        "proficiencies": {a["id"]: "untrained" for a in rules.SKILLS},
        "roles": {
            # `character_id` is the PC holding the role; `name` stays for NPCs
            # and as a fallback if the character disappears.
            r["id"]: {"name": "", "character_id": None, "pc": True,
                      "invested": False, "absent": False}
            for r in rules.ROLES
        },
        "feats": [],
        "unrest": 0,
        "ruins": {r: {"points": 0, "threshold": 10, "penalty": 0} for r in RUIN_IDS},
        "rp": 0,
        "rp_spent_turn": 0,
        "bonus_dice": 0,
        "penalty_dice": 0,
        "commodities": {p: 0 for p in COMMODITY_IDS},
        "storage_extra": {p: 0 for p in COMMODITY_IDS},
        "consumption_extra": 0,
        "army_consumption": 0,
        "modifiers": [],
        "turn_activities": {},
        "trade_agreements": [],
        "diplomatic_relations": [],
        "milestones": [],
        "event_dc": 16,
        "hexes": {},
        "settlements": [],
        "capital": None,
        "map": {
            "image": "",
            "orientation": "pointy",
            "size": 34.0,
            "origin_x": 40.0,
            "origin_y": 40.0,
            "columns": 30,
            "rows": 24,
            "img_width": 2000,
            "img_height": 733,
            "show_grid": True,
            "zoom": 1.0,
            # How much the terrain fills cover the drawn map: 1.0 solid, 0 only
            # the hex outlines. The drawn map has its own colours, and sometimes
            # one wants to look at that instead of its classification.
            "terrain_veil": 1.0,
            # How thick the fog is for players: 0.35 lets the map show through,
            # 1.0 covers it entirely. The GM always sees it light.
            "fog_opacity": 0.8,
            # And how thick it is on the GM screens: light by default, so the
            # map underneath stays readable while preparing it.
            "gm_fog_opacity": 0.35,
        },
        "current_phase": "upkeep",
        # The campaign clock. `days` are those elapsed since the start date;
        # the real date follows from there with the Absalom Reckoning
        # calendar. The Kingdom Turn closes at the end of the month, not after
        # a fixed number of days: the months of Golarion run from 28 to 31.
        "clock": {
            "start": {"year": almanac.DEFAULT_YEAR,
                       "month": almanac.DEFAULT_MONTH,
                       "day": almanac.DEFAULT_DAY},
            "days": 0,
            "in_progress": False,
            "seconds_per_day": 6.0,
            "turn_started_at": 0,
        },
    }


# --------------------------------------------------------------------------
class State:
    """Mutable container of the kingdom, with automatic saving."""

    def __init__(self, archive: Archive | None = None,
                 campaign: str = config.DEFAULT_CAMPAIGN):
        self.archive = archive if archive is not None else Archive(config.DB_FILE)
        migrations.rename_asset_folders(config.ASSETS_DIR)
        self.campaign = campaign
        self.k: dict = new_kingdom()
        self._listeners: list = []
        self.load()

    # ---------------------------------------------------------------- io
    def load(self) -> None:
        """Reads the game from the database, importing it from the old JSON if needed."""
        data = migrations.import_json(
            self.archive, self.campaign, config.SAVE_JSON, new_kingdom)
        if data is None:
            data = self.archive.read(self.campaign)
            if data is None:
                return
            # What comes from the database goes through normalisation too: a
            # game saved before a key existed must not come back without it.
            data = migrations.normalize(data, new_kingdom)
        self.k = data

        # The migrations of the tables that sit next to the kingdom: they run
        # once, are idempotent and apply to both origins.
        if migrations.unify_fields(self.k):
            self.save()
        if migrations.drop_water_terrains(self.k):
            self.save()
        if migrations.ensure_characters(self.archive, self.campaign, self.k):
            self.save()
        migrations.ensure_visibility(self.archive, self.campaign, self.k)
        migrations.water_on_edge(self.archive, self.campaign, self.k)
        migrations.renumber_sections(self.archive, self.campaign, self.k)
        migrations.marker_spots(self.archive, self.campaign, self.k)
        migrations.crossings_on_point(self.archive, self.campaign, self.k)
        if migrations.journal_into_table(self.archive, self.campaign, self.k):
            self.save()

    def save(self) -> None:
        self.archive.write(self.campaign, self.k)

    def export(self) -> str:
        data = dict(self.k)
        data["log"] = self.journal(400)
        return json.dumps(data, ensure_ascii=False, indent=1)

    def reset(self) -> None:
        self.archive.reset(self.campaign)
        self.k = new_kingdom()
        self.save()

    def restore(self, path) -> Path:
        """The whole game from a save file; returns the copy kept of the old one."""
        kept = self.archive.restore_from(path)
        self.k = new_kingdom()
        self.load()
        return kept

    # ------------------------------------------------------------ listeners
    def on_change(self, fn) -> None:
        self._listeners.append(fn)

    def notify(self, save: bool = True) -> None:
        if save:
            self.save()
        for fn in list(self._listeners):
            try:
                fn()
            except Exception:
                # The UI must not block the data, but a listener that blows up
                # silently is a real error: there are no expected failures here.
                log.exception("state listener failed: %r", fn)

    # ---------------------------------------------------------------- log
    def record(self, text: str, category: str = "info", detail: str = "") -> None:
        """A line in the game's journal (table `log`)."""
        self.archive.record(self.campaign, {
            "logged_at": time.strftime("%Y-%m-%dT%H:%M"),
            "turn": self.k["turn"],
            "category": category,
            "text": text,
            "detail": detail,
        })

    def journal(self, how_many: int = 80) -> list[dict]:
        return self.archive.journal(self.campaign, how_many)

    # ------------------------------------------------------- derived stats
    @property
    def level(self) -> int:
        return self.k["level"]

    @property
    def size_(self) -> int:
        return sum(1 for h in self.k["hexes"].values() if h.get("status") == "claimed")

    def size_entry(self) -> dict:
        return rules.size_entry(max(1, self.size_))

    @property
    def resource_die(self) -> int:
        return self.size_entry()["die"]

    @property
    def resource_dice_count(self) -> int:
        base = self.level + 4 + self.k["bonus_dice"] - self.k["penalty_dice"]
        return max(0, base)

    def storage(self, commodity: str) -> int:
        return self.size_entry()["storage"] + self.k["storage_extra"].get(commodity, 0)

    @property
    def control_dc(self) -> int:
        base = rules.level_entry(self.level)["control_dc"]
        cd = base + self.size_entry()["dc_mod"]
        gov = self.k["roles"]["ruler"]
        if gov["absent"] or not gov["name"]:
            cd += 2          # Ruler's Absence penalty
        return cd

    def ability_modifier(self, ability: str) -> int:
        return rules.modifier(self.k["abilities"].get(ability, 10))

    # ------------------------------------------------------------- changes
    def valid_modifiers(self) -> list[dict]:
        """Drops the temporary modifiers whose expiry turn has passed."""
        turn = self.k["turn"]
        return [m for m in self.k["modifiers"]
                if m.get("expiry") is None or m["expiry"] >= turn]

    def active_modifiers(self, ability: str | None = None, skills: str | None = None) -> list[dict]:
        out = []
        for m in self.valid_modifiers():
            if m.get("ability") and m["ability"] != ability:
                continue
            if m.get("skills") and m["skills"] != skills:
                continue
            out.append(m)
        return out

    def add_modifier(self, name: str, value: int, duration: int,
                              ability: str | None = None, skills: str | None = None,
                              kind: str = "circostanza") -> None:
        """`duration` 1 = the rest of this turn, 2 = until the end of the next, and so on."""
        entry = {"name": name, "valore": value, "kind": kind,
                "expiry": self.k["turn"] + max(1, duration) - 1}
        if ability:
            entry["ability"] = ability
        if skills:
            entry["skills"] = skills
        self.k["modifiers"].append(entry)

    def clean_modifiers(self) -> None:
        self.k["modifiers"] = self.valid_modifiers()

    def skill_detail(self, skill_id: str) -> list[tuple[str, int]]:
        """Breakdown of the skill modifier, to show it in the UI."""
        ab = rules.BY_ID["skills"][skill_id]
        ability = ab["ability"]
        entries: list[tuple[str, int]] = []

        ability_mod = self.ability_modifier(ability)
        entries.append((rules.BY_ID["ability"][ability]["name"], ability_mod))

        prof = self.k["proficiencies"].get(skill_id, "untrained")
        bc = rules.proficiency_bonus(self.level, prof)
        if bc:
            entries.append((rules.BY_ID["proficiency"][prof]["name"], bc))

        # Status bonus from invested Leadership roles (not cumulative: the best)
        status_bonus = 0
        for rid, data in self.k["roles"].items():
            if not data["invested"] or data["absent"] or not data["name"]:
                continue
            if rules.BY_ID["role"][rid]["ability"] == ability:
                status_bonus = max(status_bonus, rules.role_status_bonus(self.level))
        if status_bonus:
            entries.append((t("state.invested_role_status"), status_bonus))

        # Status penalty from Unrest
        pen = rules.unrest_penalty(self.k["unrest"])
        if pen:
            entries.append((t("state.unrest_status", unrest=self.k['unrest']), pen))

        # Item penalty from Ruin
        ruin_ = next((r for r in rules.RUINS if r["ability"] == ability), None)
        if ruin_:
            p = self.k["ruins"][ruin_["id"]]["penalty"]
            if p:
                entries.append((f"{ruin_['name']} (Oggetto)", -p))

        # Temporary modifiers: those with neither «ability» nor «skill» apply
        # everywhere. Bonuses and penalties of the same type do not stack: the
        # best and the worst count, as for any PF2e modifier.
        best_ones: dict[tuple[str, bool], dict] = {}
        for m in self.active_modifiers(ability=ability, skills=skill_id):
            kind = m.get("kind")
            if not kind:
                entries.append((m["name"], m["valore"]))
                continue
            key = (kind, m["valore"] >= 0)
            current = best_ones.get(key)
            if current is None or abs(m["valore"]) > abs(current["valore"]):
                best_ones[key] = m
        for m in best_ones.values():
            entries.append((m["name"], m["valore"]))

        return entries

    def skill_mod(self, skill_id: str) -> int:
        return sum(v for _n, v in self.skill_detail(skill_id))

    # ------------------------------------------------------------- hexes
    def hex(self, col: int, row: int) -> dict:
        key = f"{col},{row}"
        if key not in self.k["hexes"]:
            self.k["hexes"][key] = {
                "col": col, "row": row,
                "status": "unknown",       # unknown | reconnoitered | cleared | claimed
                "terrains": [],
                "features": [],               # [{"kind": id, "commodity": ..., "name": ...}]
                "roads": False,
                "fortified": False,
                "farmland": False,
                "work_site": None,          # {"commodity": "lumber", "doubled": bool}
                "settlement": None,
                "name": "",
                "note": "",
            }
        return self.k["hexes"][key]

    def existing_hex(self, col: int, row: int) -> dict | None:
        return self.k["hexes"].get(f"{col},{row}")

    def claimed_hexes(self) -> list[dict]:
        return [h for h in self.k["hexes"].values() if h["status"] == "claimed"]

    @property
    def orientation(self) -> str:
        return self.k["map"]["orientation"]

    def influenced_hexes(self) -> set[tuple[int, int]]:
        """Claimed hexes within the influence of a settlement."""
        influenced: set[tuple[int, int]] = set()
        claimed = {(h["col"], h["row"]) for h in self.claimed_hexes()}
        for sett in self.k["settlements"]:
            if not sett.get("hex"):
                continue          # settlement not yet placed on the map
            kind = rules.BY_ID["settlement"][sett["kind"]]
            radius = kind["influence"]
            if sett.get("water_only") and not sett.get("has_bridge"):
                radius = 0
            origin_ = (sett["hex"][0], sett["hex"][1])
            for pos in claimed:
                if hexgrid.distance(origin_, pos, self.orientation) <= radius:
                    influenced.add(pos)
            influenced.add(origin_)
        return influenced

    # --------------------------------------------------------------- consumption
    def consumption(self) -> dict:
        sett_tot = 0
        for sett in self.k["settlements"]:
            kind = rules.BY_ID["settlement"][sett["kind"]]
            sett_tot += kind["consumption"] + sett.get("consumption_extra", 0)

        influenced = self.influenced_hexes()
        farms = sum(
            1 for h in self.claimed_hexes()
            if h.get("farmland") and (h["col"], h["row"]) in influenced
        )
        armies = self.k["army_consumption"]
        extra = self.k["consumption_extra"]
        total = max(0, sett_tot + armies - farms + extra)
        return {
            "settlements": sett_tot,
            "armies": armies,
            "farms": farms,
            "events": extra,
            "total": total,
        }

    # ----------------------------------------------------------- settlements
    def settlement(self, sid: str) -> dict | None:
        return next((i for i in self.k["settlements"] if i["id"] == sid), None)

    def remove_settlement(self, sid: str) -> None:
        sett = self.settlement(sid)
        if not sett:
            return
        self.k["settlements"] = [i for i in self.k["settlements"] if i["id"] != sid]
        if sett.get("hex"):
            h = self.existing_hex(*sett["hex"])
            if h:
                h["settlement"] = None
                h["features"] = [e for e in h["features"] if e["kind"] != "settlement"]
        if self.k["capital"] == sid:
            self.k["capital"] = self.k["settlements"][0]["id"] if self.k["settlements"] else None
            if self.k["capital"]:
                self.settlement(self.k["capital"])["capital"] = True
        self.record(t("state.settlement_removed", name=sett['name']), "settlement")

    def lot_detail(self, sett: dict) -> dict:
        """Urban Grid counts: built blocks, Residential lots, occupied and free
        lots in the unlocked blocks."""
        used_blocks = 0
        residential_count = 0
        occupied = 0
        unlocked = 0
        for gi, grid in enumerate(sett["grids"]):
            active_ones = (sett["active_blocks"] if gi == 0 and sett["kind"] != "metropolis"
                      else range(len(grid)))
            for bi, block_ in enumerate(grid):
                if bi in active_ones:
                    unlocked += len(block_)
                used = False
                for lot in block_:
                    name = lot.get("structure")
                    if not name:
                        continue
                    used = True
                    occupied += 1
                    st = rules.BY_ID["structure"].get(name)
                    if st and "residential" in st["traits"]:
                        residential_count += 1
                if used:
                    used_blocks += 1
        return {
            "built_blocks": used_blocks,
            "residential_count": residential_count,
            "missing": max(0, used_blocks - residential_count),
            "occupied": occupied,
            "free": max(0, unlocked - occupied),
        }

    def link_settlement(self, sid: str, col: int, row: int) -> str:
        """Moves a settlement onto the given hex.

        For one created from the City tab form without coordinates, or one
        founded twice. Returns the error message, or "" on success.
        """
        sett = self.settlement(sid)
        if not sett:
            return t("state.no_such_settlement")
        h = self.hex(col, row)
        occupant = h.get("settlement")
        if occupant and occupant != sid:
            other = self.settlement(occupant)
            return t("state.hex_already_belongs", col=col, row=row, v=other["name"] if other else t("state.another_settlement"))

        if sett.get("hex") and tuple(sett["hex"]) != (col, row):
            old = self.existing_hex(*sett["hex"])
            if old:
                old["settlement"] = None
                old["features"] = [e for e in old["features"] if e["kind"] != "settlement"]

        sett["hex"] = [col, row]
        h["settlement"] = sid
        if not any(e["kind"] == "settlement" for e in h["features"]):
            h["features"].append({"kind": "settlement", "name": sett["name"]})
        self.record(t("state.now_stands_hex", name=sett['name'], col=col, row=row), "settlement")
        return ""

    def unlink_settlement(self, col: int, row: int) -> None:
        """Takes the settlement off the hex without deleting it from the kingdom:
        it stays in the City tab, ready to be linked elsewhere."""
        h = self.existing_hex(col, row)
        if not h:
            return
        sett = self.settlement(h.get("settlement") or "")
        h["settlement"] = None
        h["features"] = [e for e in h["features"] if e["kind"] != "settlement"]
        if sett:
            sett["hex"] = None
            self.record(t("state.no_longer_stands_hex", name=sett['name'], col=col, row=row), "settlement")

    def overcrowded(self, sett: dict) -> bool:
        """As many Residential lots are needed as there are built blocks."""
        return self.lot_detail(sett)["missing"] > 0

    def overcrowded_settlements(self) -> list[dict]:
        return [i for i in self.k["settlements"] if self.overcrowded(i)]

    # ------------------------------------------------- unrest and ruin
    def modify_unrest(self, delta: int, reason: str = "") -> int:
        """Applies a delta to Unrest (never below 0) and returns how much it really
        changed."""
        before = self.k["unrest"]
        self.k["unrest"] = max(0, before + delta)
        real = self.k["unrest"] - before
        if reason and real:
            self.record(t("state.unrest", real=real, reason=reason), "unrest")
        return real

    def modify_ruin(self, rid: str, delta: int, reason: str = "") -> None:
        """Applies a delta to a Ruin, raising the penalty at every threshold crossed."""
        r = self.k["ruins"][rid]
        r["points"] = max(0, r["points"] + delta)
        while r["points"] > r["threshold"]:
            r["points"] -= r["threshold"]
            r["penalty"] += 1
            self.record(t("state.crosses_threshold_penalty_now", name=rules.BY_ID['ruin'][rid]['name'], penalty=r['penalty']), "ruin")
        if reason:
            self.record(t("state.text", delta=delta, name=rules.BY_ID['ruin'][rid]['name'], reason=reason), "ruin")

    def settlement_level(self, sett: dict) -> int:
        """Equal to the number of blocks with at least one structure (max 20)."""
        n = 0
        for grid in sett["grids"]:
            for block_ in grid:
                if any(l.get("structure") for l in block_):
                    n += 1
        return min(20, n)

    def structures_of(self, sett: dict) -> dict[str, int]:
        tally: dict[str, int] = {}
        for grid in sett["grids"]:
            for block_ in grid:
                seen = set()
                for lot in block_:
                    name, gid = lot.get("structure"), lot.get("gid")
                    if not name:
                        continue
                    key = (name, gid)
                    if key in seen:
                        continue
                    seen.add(key)
                    tally[name] = tally.get(name, 0) + 1
        return tally

    def capital(self) -> dict | None:
        return self.settlement(self.k["capital"]) if self.k["capital"] else None

    def max_leadership_activities(self) -> int:
        """3 if the capital has a Castle, Palace or Town Hall, otherwise 2."""
        cap = self.capital()
        if not cap:
            return 2
        structures = self.structures_of(cap)
        return 3 if {"castle", "palace", "town_hall"} & set(structures) else 2

    def claims_per_turn(self) -> int:
        if self.level >= 9:
            return 3
        if self.level >= 4:
            return 2
        return 1

    # ---------------------------------------------------------------- milestones
    def award_milestone(self, mid: str) -> int:
        """Awards a Milestone if not already earned. Returns the XP granted."""
        if mid in self.k["milestones"]:
            return 0
        entry = next((m for m in rules.MILESTONE_XP if m["id"] == mid), None)
        if not entry:
            return 0
        self.k["milestones"].append(mid)
        self.k["xp"] += entry["xp"]
        self.record(t("state.milestone_reward_xp", desc=entry['desc'], xp=entry['xp']), "xp")
        return entry["xp"]

    def check_size_milestones(self) -> None:
        d = self.size_
        for threshold, mid in ((10, "size_10"), (25, "size_25"),
                            (50, "size_50"), (100, "size_100")):
            if d >= threshold:
                self.award_milestone(mid)

    # ------------------------------------------------------------ commodities/RP
    def add_commodity(self, commodity: str, quantity: int) -> int:
        """Adds Commodities within the storage limit. Returns what was lost."""
        limit = self.storage(commodity)
        current_one = self.k["commodities"][commodity]
        new = current_one + quantity
        lost = max(0, new - limit)
        self.k["commodities"][commodity] = max(0, min(limit, new))
        return lost

    def spend_rp(self, quantity: int) -> bool:
        """Spends RP. If it would go below 0, zeroes it and flags it (a Ruin must rise)."""
        if quantity <= 0:
            return True
        if self.k["rp"] >= quantity:
            self.k["rp"] -= quantity
            self.k["rp_spent_turn"] += quantity
            if self.k["rp_spent_turn"] >= 100:
                self.award_milestone("rp_100")
            return True
        self.k["rp_spent_turn"] += self.k["rp"]
        self.k["rp"] = 0
        return False

    # -------------------------------------------------------------- anarchy
    @property
    def anarchy_threshold(self) -> int:
        return 24 if "endure_anarchy" in self.k["feats"] else 20

    @property
    def in_anarchy(self) -> bool:
        return self.k["unrest"] >= self.anarchy_threshold

    @property
    def max_fame(self) -> int:
        return 3 + self.k["fame_bonus_max"]

    def fame_on_critical(self, result) -> bool:
        """Every Critical Success on a Kingdom check gives 1 Fame/Infamy point."""
        if result.grade == "critical_success" and self.k["fame_points"] < self.max_fame:
            self.k["fame_points"] += 1
            return True
        return False

    # ------------------------------------------------- turn activities
    def leader_pc(self) -> int:
        """How many distinct PCs hold a role.

        Counts characters, not names: two roles held by the same PC count as
        one. Roles with no linked character yet count by name, as before, so a
        game halfway through the migration does not lose the count.
        """
        distinct = set()
        for d in self.k["roles"].values():
            if not d.get("pc"):
                continue
            if d.get("character_id"):
                distinct.add(d["character_id"])
            elif d.get("name"):
                distinct.add(f"nome:{d['name']}")
        return len(distinct)

    def characters(self) -> list[dict]:
        return self.archive.list_characters(self.campaign)


    def step_limit(self, phase: str, step: str) -> int | None:
        """How many activities may be attempted in a step, or None if unlimited."""
        if phase != "activity":
            return None
        if step == "leadership":
            return self.max_leadership_activities() * max(1, self.leader_pc())
        if step == "region":
            return 3
        if step == "civic":
            return len(self.k["settlements"])
        return None

    def activity_uses(self, act_id: str) -> int:
        return self.k["turn_activities"].get(act_id, 0)

    def step_uses(self, phase: str, step: str) -> int:
        return sum(n for aid, n in self.k["turn_activities"].items()
                   if (a := rules.BY_ID["activities"].get(aid))
                   and a["phase"] == phase and a["step"] == step)

    def mark_activity(self, act_id: str) -> None:
        self.k["turn_activities"][act_id] = self.activity_uses(act_id) + 1

    def activities_block(self, act: dict) -> str:
        """Why this activity cannot be attempted right now — empty string if it can."""
        request_ = act.get("min_proficiency")
        if request_ and act["skills"] != ["*"] and not any(
                rules.meets_proficiency(self.k["proficiencies"].get(a, "untrained"), request_)
                for a in act["skills"]):
            return (t("state.kingdom_not_any_required", name=rules.BY_ID['proficiency'][request_]['name']))
        limit = act.get("turn_limit")
        if limit and self.activity_uses(act["id"]) >= limit:
            return t("state.already_attempted_this_kingdom", limit=limit)
        if self.in_anarchy and act["id"] != "quell_unrest":
            return t("state.kingdom_anarchy_only_quell")
        max_ = self.step_limit(act["phase"], act["step"])
        if max_ is not None and self.step_uses(act["phase"], act["step"]) >= max_:
            name = {"government": t("state.leadership"), "region": t("state.region"), "civic": t("state.civic")}[act["step"]]
            return t("state.activities_used_up_this", name=name, max=max_, max2=max_)
        return ""

    # ------------------------------------------------- activity effects
    def apply_effect(self, entry: dict, value: int, target: str | None = None) -> str:
        """Applies a single effect and returns how to describe it in the journal."""
        t = entry["t"]
        if t == "note":
            return ""
        if t != "mod" and value == 0:
            return ""
        if t == "unrest":
            self.modify_unrest(value)
        elif t in ("ruin", "ruin_choice"):
            rid = entry["r"] if t == "ruin" else target
            if not rid:
                return ""
            self.modify_ruin(rid, value)
            if entry.get("pen"):
                r = self.k["ruins"][rid]
                r["penalty"] = max(0, r["penalty"] + entry["pen"])
            return f"{rules.BY_ID['ruin'][rid]['name']} {value:+d}"
        elif t == "rp":
            if value < 0:
                self.spend_rp(-value)
            else:
                self.k["rp"] += value
        elif t == "xp":
            self.k["xp"] = max(0, self.k["xp"] + value)
        elif t == "fame":
            self.k["fame_points"] = max(0, min(self.max_fame, self.k["fame_points"] + value))
        elif t in ("commodity", "commodity_choice"):
            char_id = entry["p"] if t == "commodity" else target
            if not char_id:
                return ""
            if value < 0:
                self.k["commodities"][char_id] = max(0, self.k["commodities"][char_id] + value)
            else:
                self.add_commodity(char_id, value)
            return f"{rules.BY_ID['commodity'][char_id]['name']} {value:+d}"
        elif t == "resource_die":
            tot, rolls = rules.roll(abs(value), self.resource_die)
            if value < 0:
                self.spend_rp(tot)
            else:
                self.k["rp"] += tot
            return (f"{abs(value)}d{self.resource_die} = {tot} PR "
                    f"{'spesi' if value < 0 else 'guadagnati'} {rolls}")
        elif t == "bonus_dice":
            self.k["bonus_dice"] += value
        elif t == "mod":
            self.add_modifier(entry["name"], entry["v"], entry["dur"],
                                       ability=entry.get("ability"), skills=entry.get("skill"))
        return rules.entry_label(entry, value)


STATE = State()
