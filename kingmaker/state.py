"""Kingdom state: data model, derived statistics and saving.

The kingdom lives in memory in `State.k` and is written to SQLite by `archive`.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from kingmaker import config, rules
from kingmaker import turn_memory as memory
from kingmaker.geometry import hexgrid
from kingmaker.storage import migrations
from kingmaker.rules import almanac
from kingmaker.storage.archive import Archive
from kingmaker.locale.i18n import t

log = logging.getLogger(__name__)

COMMODITY_IDS = [p["id"] for p in rules.COMMODITIES]
RUIN_IDS = [r["id"] for r in rules.RUINS]
ABILITY_IDS = [c["id"] for c in rules.ABILITIES]

# The structure trait whose benefits count once per settlement: PF2e's
# Edifice (Town Hall, Castle, Palace, Cathedral...). Its id is "building":
# the ids came from the Italian names, where «Edificio» is the Building
# trait and «Costruzione» the Edifice one, so the two read crossed.
EDIFICE = "building"

# The effect kinds that carry no number: applied whatever the row's value
# (`State.apply_effect`), and drawn without a number field (`turn._effect_rows`).
_NO_VALUE = {"lockout", "pending_check", "event_mark", "debt", "repay", "penalty",
             "unclaim", "claim", "relation", "agreement"}


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
        # Points that arrive at the start of the next Kingdom turn, on top of
        # the usual one (a Masterpiece's critical success): those of this
        # turn are lost when it ends, these are not in hand yet.
        "fame_next_turn": 0,
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
        # What some feats ask the table to choose: Civil Service's role,
        # Kingdom Assurance's skills, Muddle Through's Ruins.
        "feat_choices": {},
        # Once-per-turn feats, by the turn they were last used, and Pull
        # Together's flat-check DC, which rises with use.
        "feat_turns": {},
        "pull_together_dc": 11,
        # Extra Region activities this turn (a Claim Hex critical success),
        # Food paid toward this turn's Consumption, and the level-up choices
        # already made, by level.
        "region_bonus": {},
        # RP owed at the start of the next turn (Request Foreign Aid's
        # failure), added to the Resource Dice when they are rolled.
        "rp_next_turn": 0,
        "consumption_paid": {},
        "advancements": {},
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
        # The groups the kingdom deals with, each with the Negotiation DC the
        # GM gives it (Send Diplomatic Envoy and the activities after it).
        "partners": [],
        # The kingdom's ongoing events, named by the GM: the wiki keeps no
        # list of them, so the app tracks them instead of rolling them.
        "events": [],
        # What carries from one turn to the next (`turn_memory`): lock-outs,
        # repeats, streaks, debts, penalties, pending flat checks.
        "turn_memory": {"record": [], "last": {}, "streaks": {}, "lockouts": [],
                        "debts": {}, "penalties": [], "pending": []},
        # This turn's Leadership activities by leader ({role: {act: n}}) and
        # Civic activities by settlement ({settlement: n}); reset every turn.
        "turn_leaders": {},
        "turn_civic": {},
        # The leaders' week of downtime this month: {"turn", "ticks", "choices"}.
        "downtime": {},
        # Favored Land this turn: {"turn", "hex", "used", "as_one"}.
        "favored_land": {},
        # RP gained this turn that does not become XP (Request Foreign Aid).
        "rp_no_xp": 0,
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
        # the real date follows from there with the campaign's calendar,
        # Golarion's Absalom Reckoning unless the table wrote its own
        # (`almanac.calendar_of`). The Kingdom Turn closes at the end of the
        # month, not after a fixed number of days: the months of Golarion run
        # from 28 to 31.
        "clock": {
            "calendar": {"preset": almanac.PRESET},
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
        # Anarchy or a Ruin penalty that Fame/Infamy could still stave off:
        # set by `modify_unrest` and `modify_ruin`, offered to whoever made
        # the change (`take_fame_offers`). Not saved: an offer is for now.
        self.fame_offers: list[dict] = []
        self.feat_offers: list[dict] = []
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
        """The whole game from a save file — a zip with the images, or the
        database alone; returns the copy kept of the old one."""
        from kingmaker.storage import bundle
        kept = bundle.restore(self.archive, config.ASSETS_DIR, path)
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
        if "insider_trading" in self.k["feats"]:
            base += 1                  # Insider Trading: 1 bonus die every turn
        return max(0, base)

    def roll_resource_dice(self) -> tuple[int, int, int, list[int]]:
        """The Resource Dice of the turn: the RP become their total. Bonus and
        penalty dice count for a single roll, so they are used up here — from
        whichever button rolled. Returns (dice, faces, total, rolls)."""
        n, faces = self.resource_dice_count, self.resource_die
        tot, rolls = rules.roll(n, faces)
        tot += self.k["rp_next_turn"]          # owed from the last turn
        self.k["rp_next_turn"] = 0
        self.k["rp"] = tot
        self.k["rp_spent_turn"] = 0
        self.k["bonus_dice"] = 0
        self.k["penalty_dice"] = 0
        self.k["rp_no_xp"] = 0                 # foreign aid's RP: a new turn's RP
        return n, faces, tot, rolls

    def storage(self, commodity: str) -> int:
        """The size's storage, plus 1 for each structure that raises this
        commodity's capacity (a Granary for Food, a Lumberyard for Lumber…),
        plus what the table added by hand."""
        built = 0
        for sett in self.k["settlements"]:
            for sid, count in self.structures_of(sett).items():
                st = rules.BY_ID["structure"].get(sid) or {}
                if EDIFICE in st.get("traits", ()):
                    count = 1           # an Edifice counts once per settlement
                built += (st.get("storage") or {}).get(commodity, 0) * count
        return self.size_entry()["storage"] + built + self.k["storage_extra"].get(commodity, 0)

    @property
    def control_dc(self) -> int:
        base = rules.level_entry(self.level)["control_dc"]
        cd = base + self.size_entry()["dc_mod"]
        if self.role_vacant("ruler"):
            cd += 2          # the Ruler's vacancy penalty
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

    # ------------------------------------------------------- check modifiers
    # Typed bonuses and penalties do not stack: of each type the best bonus
    # and the worst penalty count. Vacancy penalties stack with each other,
    # and the ability and proficiency are not modifiers of a type at all.
    TYPED = ("status", "circumstance", "item")
    # The Army activities are the «Warfare activities» of the vacancy penalties.
    WARFARE_ACTIVITIES = {"recruit_army", "train_army", "offensive_gambit", "disband_army",
                          "deploy_army", "outfit_army", "recover_army", "garrison_army"}
    # The structures Fortified Fiefs helps to build or repair.
    FORTIFIED = {"barracks", "castle", "garrison", "keep", "stone_wall", "wooden_wall"}

    def role_vacant(self, rid: str) -> bool:
        """A role nobody holds this turn: empty, or its leader away — unless
        Civil Service covers it, and then it has no vacancy penalty."""
        if "civil_service" in self.k["feats"] and self.feat_choice("civil_service") == rid:
            return False
        data = self.k["roles"][rid]
        if any(p.get("kind") == "vacancy" for p in memory.active_penalties(self.k, role=rid)):
            return True         # the week of downtime missed, taken as the vacancy penalty
        return bool(data["absent"] or not (data["name"] or data.get("character_id")))

    def feat_choice(self, fid: str, default=None):
        """What the table chose for a feat (Civil Service's role, Kingdom
        Assurance's skills, Muddle Through's Ruins)."""
        return self.k["feat_choices"].get(fid, default)

    def _modifiers(self, skill_id: str, activity: str | None, variant: str | None,
                   hex_, settlement: str | None, event: str | None,
                   fair: bool, leader: str | None = None, subject: str | None = None,
                   extra=()) -> list[tuple[str, int, str | None]]:
        """Every modifier to a Kingdom check, as (name, value, type), before
        the stacking rules (`skill_detail`). `leader` is the role acting,
        `subject` the partner or Ruin the check is about, `extra` the typed
        bonuses the caller adds (an event's Watchtower, Favored Land), which
        stack by the same rules as the rest."""
        ability = rules.BY_ID["skills"][skill_id]["ability"]
        feats = set(self.k["feats"])
        out: list[tuple[str, int, str | None]] = [
            (rules.BY_ID["ability"][ability]["name"], self.ability_modifier(ability), "ability")]
        prof = self.k["proficiencies"].get(skill_id, "untrained")
        bc = rules.proficiency_bonus(self.level, prof)
        if bc:
            out.append((rules.BY_ID["proficiency"][prof]["name"], bc, "proficiency"))

        # Invested leaders: a status bonus to their ability's checks.
        for rid, data in self.k["roles"].items():
            if (data["invested"] and not data["absent"] and data["name"]
                    and rules.BY_ID["role"][rid]["ability"] == ability):
                out.append((t("state.invested_role_status"), rules.role_status_bonus(self.level), "status"))
        pen = rules.unrest_penalty(self.k["unrest"])
        if pen:
            out.append((t("state.unrest_status", unrest=self.k['unrest']), pen, "status"))
        ruin_ = next((r for r in rules.RUINS if r["ability"] == ability), None)
        if ruin_ and self.k["ruins"][ruin_["id"]]["penalty"]:
            out.append((t("state.ruin_item", name=ruin_["name"]),
                        -self.k["ruins"][ruin_["id"]]["penalty"], "item"))
        if activity:
            bonus = self.item_bonus(activity, skill_id, variant, hex_, settlement)
            if bonus:
                out.append((t("state.structure_item", name=bonus[0], settlement=bonus[2]), bonus[1], "item"))

        # Vacant roles: the vacancy penalties of the Leadership Roles.
        act = rules.BY_ID["activities"].get(activity) if activity else None
        step = act["step"] if act else None
        for rid, applies, value in (
                ("ruler", True, -1), ("counselor", ability == "culture", -1),
                ("emissary", ability == "loyalty", -1), ("treasurer", ability == "economy", -1),
                ("viceroy", ability == "stability", -1),
                ("general", activity in self.WARFARE_ACTIVITIES, -4),
                ("magister", activity in self.WARFARE_ACTIVITIES, -4),
                ("warden", step == "region", -4)):
            if applies and self.role_vacant(rid):
                out.append((t("state.vacancy", role=rules.BY_ID["role"][rid]["name"]), value, "vacancy"))

        # Kingdom feats.
        def feat(fid: str, value: int, kind: str) -> None:
            key = "state.mod_status" if kind == "status" else "state.mod_circumstance"
            out.append((t(key, name=rules.BY_ID["feat"][fid]["name"]), value, kind))

        if activity == "claim_hex" and self.level >= 4:
            out.append((t("map.hex_panel.expansion_expert_circumstance"), 2, "circumstance"))
        if "fortified_fiefs" in feats:
            if activity == "fortify_hex" or (activity == "build_structure" and variant in self.FORTIFIED):
                feat("fortified_fiefs", 2, "circumstance")
            if event == "defenses":
                feat("fortified_fiefs", 1, "status")
        if "insider_trading" in feats and activity in ("establish_work_site", "establish_trade_agreement",
                                                       "trade_commodities"):
            feat("insider_trading", 1, "status")
        if "practical_magic" in feats and skill_id == "magic":
            feat("practical_magic", 1, "status")
        if "civil_service" in feats and activity == "new_leadership":
            feat("civil_service", 2, "status")
        if "inspiring_entertainment" in feats and ability == "culture" and self.k["unrest"] >= 1:
            feat("inspiring_entertainment", 2, "status")
        if "crush_dissent" in feats and event == "bickering":
            feat("crush_dissent", 1, "status")
        if "quick_recovery" in feats and event == "ongoing":
            feat("quick_recovery", 4, "status")
        if ("free_and_fair" in feats and fair and ability == "loyalty"
                and activity in ("new_leadership", "pledge_of_fealty")):
            feat("free_and_fair", 2, "circumstance")

        # Temporary modifiers: those with neither «ability» nor «skill» apply
        # to every check.
        for m in self.active_modifiers(ability=ability, skills=skill_id):
            kind = {"circostanza": "circumstance"}.get(m.get("kind"), m.get("kind"))
            out.append((m["name"], m["valore"], kind))

        # The kingdom's own map and partners.
        if hex_ is not None and tuple(hex_) in self.secondary_hexes():
            out.append((t("state.secondary_territory"), -4, "circumstance"))
        if skill_id == "trade":
            cut_off = sum(1 for s in self.k["settlements"] if s.get("hex") and self.no_land_border(s))
            if cut_off:
                out.append((t("state.no_land_border", n=cut_off), -cut_off, "item"))
        if activity == "trade_commodities" and self.related_partners():
            # «If you trade with a group that you've established diplomatic
            # relations with, you gain a +1 circumstance bonus» (the activity).
            out.append((t("state.diplomatic_relations_bonus"), 1, "circumstance"))

        # What the turns remember: a leader's penalty, a partner's bonus.
        phase = act["phase"] if act else None
        for p in memory.active_penalties(self.k, role=leader, subject=subject, phase=phase):
            if p.get("kind") == "vacancy":
                continue                   # read by `role_vacant`, not a modifier
            out.append((p.get("reason") or "", p["value"], p.get("kind") or "circumstance"))
        out.extend(extra)
        return out

    def skill_detail(self, skill_id: str, activity: str | None = None,
                     variant: str | None = None, hex_: tuple[int, int] | None = None,
                     settlement: str | None = None, event: str | None = None,
                     fair: bool = True, leader: str | None = None, subject: str | None = None,
                     extra=()) -> list[tuple[str, int]]:
        """Breakdown of a Kingdom check's modifier, as (name, value): the
        skill alone, or — with `activity` — as that activity attempts it,
        with the structures' item bonus, the vacancy penalties of the roles
        it depends on and the feats that help it. `event` is the kind of
        event the check is about ("ongoing", "defenses", "bickering"), for
        the feats that help with those. `fair` False leaves Free and Fair's
        +2 out: its own reroll is attempted without it."""
        best: dict[tuple[str, bool], tuple[str, int]] = {}
        entries: list[tuple[str, int]] = []
        for name, value, kind in self._modifiers(skill_id, activity, variant, hex_,
                                                 settlement, event, fair, leader, subject, extra):
            if not value:
                continue
            if kind in self.TYPED:
                key = (kind, value >= 0)
                if key not in best or abs(value) > abs(best[key][1]):
                    best[key] = (name, value)
            else:
                entries.append((name, value))
        return entries + list(best.values())

    def skill_mod(self, skill_id: str) -> int:
        return sum(v for _n, v in self.skill_detail(skill_id))

    def check_detail(self, skill_id: str, activity: str | None = None,
                     variant: str | None = None, hex_: tuple[int, int] | None = None,
                     settlement: str | None = None, event: str | None = None,
                     fair: bool = True, leader: str | None = None, subject: str | None = None,
                     extra=()) -> list[tuple[str, int]]:
        """The breakdown of a Kingdom check: `skill_detail` for an activity."""
        return self.skill_detail(skill_id, activity, variant, hex_, settlement, event, fair,
                                 leader, subject, extra)

    def item_bonus(self, activity: str, skill: str | None = None, variant: str | None = None,
                   hex_: tuple[int, int] | None = None,
                   settlement: str | None = None) -> tuple[str, int, str] | None:
        """The item bonus the structures give to an activity, as (structure,
        value, settlement), or None.

        A settlement's structures help the activities attempted in the claimed
        hexes of its influence; the capital's help everywhere in the kingdom.
        `hex_` is where the activity happens, when it happens on the map;
        `settlement` the one the table attempts it in, when it does not.
        Identical structures in one settlement stack, up to that settlement's
        maximum item bonus; nothing else stacks, so the best one counts.
        `variant` tells apart what an activity makes (a lumber camp, a mine),
        for the structures that help only one of them."""
        best: tuple[str, int, str] | None = None
        for sett in self.k["settlements"]:
            if not (sett["id"] == self.k["capital"] or sett["id"] == settlement
                    or (hex_ is not None and tuple(hex_) in self.influence_of(sett))):
                continue
            cap = rules.BY_ID["settlement"][sett["kind"]]["item_bonus_max"]
            for sid, count in self.structures_of(sett).items():
                st = rules.BY_ID["structure"].get(sid)
                if st and EDIFICE in st.get("traits", ()):
                    count = 1           # an Edifice counts once per settlement
                for b in (st or {}).get("item_bonuses", ()):
                    if (b["activity"] != activity
                            or (b.get("skills") and skill not in b["skills"])
                            or (b.get("variant") and b["variant"] != variant)):
                        continue
                    value = max(b["value"], min(b["value"] * count, cap))
                    if best is None or value > best[1]:
                        best = (st["name"], value, sett["name"])
        return best

    def bonus_settlements(self, activity: str) -> list[dict]:
        """The settlements other than the capital whose structures help this
        activity, with any skill: those where attempting it is worth saying."""
        out = []
        for sett in self.k["settlements"]:
            if sett["id"] == self.k["capital"]:
                continue
            for sid in self.structures_of(sett):
                st = rules.BY_ID["structure"].get(sid) or {}
                if any(b["activity"] == activity for b in st.get("item_bonuses", ())):
                    out.append(sett)
                    break
        return out

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
            influenced |= self.influence_of(sett, claimed)
        return influenced

    def influence_of(self, sett: dict,
                     claimed: set[tuple[int, int]] | None = None) -> set[tuple[int, int]]:
        """The claimed hexes in one settlement's influence, its own included;
        nothing for a settlement not yet placed on the map."""
        if not sett.get("hex"):
            return set()
        if claimed is None:
            claimed = {(h["col"], h["row"]) for h in self.claimed_hexes()}
        radius = rules.BY_ID["settlement"][sett["kind"]]["influence"]
        if self.water_only(sett) and not self.has_bridge(sett):
            radius = 0          # an island: Influence 0
        origin_ = (sett["hex"][0], sett["hex"][1])
        return {pos for pos in claimed
                if hexgrid.distance(origin_, pos, self.orientation) <= radius} | {origin_}

    @staticmethod
    def water_only(sett: dict) -> bool:
        """Every border of the settlement is water: an island. Derived from the
        four borders (the stored flag of older saves counts too)."""
        borders = sett.get("borders") or {}
        return bool(sett.get("water_only")) or (
            len(borders) == 4 and all(v == "water" for v in borders.values()))

    @staticmethod
    def has_bridge(sett: dict) -> bool:
        """A bridge spans one of the settlement's water borders."""
        return bool(sett.get("border_bridges")) or bool(sett.get("has_bridge"))

    def no_land_border(self, sett: dict) -> bool:
        """No land border and no bridged water border: -1 item to Trade."""
        borders = sett.get("borders") or {}
        if any(v in ("land", "walls") for v in borders.values()):
            return False        # a walled border is a land border with walls
        if not borders:
            return False        # not drawn yet: the table has not said
        return not self.has_bridge(sett)

    def secondary_hexes(self) -> set[tuple[int, int]]:
        """The claimed hexes cut off from the capital's: no path of claimed
        hexes joins them. Derived, never stored; empty without a capital on
        the map."""
        cap = self.capital()
        if not cap or not cap.get("hex"):
            return set()
        claimed = {(h["col"], h["row"]) for h in self.claimed_hexes()}
        start = (cap["hex"][0], cap["hex"][1])
        if start not in claimed:
            return set()
        seen, todo = {start}, [start]
        while todo:
            c, r = todo.pop()
            for pos in hexgrid.neighbours(c, r, self.orientation):
                if pos in claimed and pos not in seen:
                    seen.add(pos)
                    todo.append(pos)
        return claimed - seen

    # --------------------------------------------------------------- consumption
    def consumption(self) -> dict:
        sett_tot = 0
        for sett in self.k["settlements"]:
            sett_tot += self.settlement_consumption(sett)

        influenced = self.influenced_hexes()
        farmland = [(h["col"], h["row"]) for h in self.claimed_hexes() if h.get("farmland")]
        farms = sum(1 for pos in farmland if pos in influenced)
        armies = self.k["army_consumption"]
        extra = self.k["consumption_extra"]
        total = max(0, sett_tot + armies - farms + extra)
        return {
            "settlements": sett_tot,
            "armies": armies,
            "farms": farms,
            # Farmland the kingdom has but that counts for nothing, being out
            # of every settlement's influence (a village's is its own hex):
            # shown, so that «farmland 0» with a field on the map is explained.
            "farms_outside": len(farmland) - farms,
            "events": extra,
            "total": total,
        }

    def settlement_consumption(self, sett: dict) -> int:
        """A settlement's Consumption: its type's, less 1 for each kind of
        structure that lowers it (a Stockyard, a Sewer System, a Mill when
        the settlement has a water border), to 0 at least, plus what the
        table added by hand."""
        own = rules.BY_ID["settlement"][sett["kind"]]["consumption"]
        water = "water" in (sett.get("borders") or {}).values()
        for sid in self.structures_of(sett):
            st = rules.BY_ID["structure"].get(sid) or {}
            if st.get("consumption_change") and (water or not st.get("consumption_needs_water")):
                own += st["consumption_change"]
        return max(0, own) + sett.get("consumption_extra", 0)

    # -------------------------------------------------------------- farmland
    def in_influence(self, col: int, row: int) -> bool:
        """The requirement of Establish Farmland, and the condition for a
        Farmland hex to reduce Consumption."""
        return (col, row) in self.influenced_hexes()

    @staticmethod
    def farmland_ground(h: dict) -> str | None:
        """What Establish Farmland is attempted on: "plains" or "hills" when
        that is the hex's predominant terrain — the first listed, the one the
        map colours it with — and None otherwise (a forest, a swamp). A hex
        whose terrain nobody has set yet counts as plains: the table judges.

        The predominant terrain, not any listed: a hex of plains with a few
        hills is attempted as plains, at 1 RP and the plain DC."""
        if not h.get("terrains"):
            return "plains"
        main = h["terrains"][0]
        return main if main in ("plains", "hills") else None

    def farmland_partners(self, col: int, row: int, hills: bool) -> list[dict]:
        """The hexes next to (col, row) that can take the second Farmland of
        a critical success: claimed, in a settlement's influence, without a
        settlement or Farmland already, and plains — or plains or hills when
        the attempt was in hills (`farmland_ground`)."""
        allowed = {"plains", "hills"} if hills else {"plains"}
        influenced = self.influenced_hexes()
        towns = {tuple(s["hex"][:2]) for s in self.k["settlements"] if s.get("hex")}
        found = []
        for c, r in hexgrid.neighbours(col, row, self.orientation):
            h = self.existing_hex(c, r)
            if (h is None or h["status"] != "claimed" or (c, r) not in influenced
                    or h.get("farmland") or h.get("settlement") or (c, r) in towns):
                continue
            if self.farmland_ground(h) not in allowed:
                continue
            found.append(h)
        return found

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

    def unclaim_hex(self, col: int, row: int) -> dict | None:
        """A hex the kingdom loses or abandons: no longer claimed, its farmland
        and work site gone (roads, fortifications and irrigation stay on the
        land). Its settlement leaves the kingdom as a freehold that remembers
        it, so Pledge of Fealty can bring it back as it was. Returns the
        settlement that left, or None."""
        h = self.existing_hex(col, row)
        if not h:
            return None
        h["status"] = "cleared"
        h["farmland"] = False
        h["work_site"] = None
        sett = self.settlement(h.get("settlement") or "")
        if sett:
            self.k["settlements"] = [s for s in self.k["settlements"] if s["id"] != sett["id"]]
            if self.k["capital"] == sett["id"]:
                self.k["capital"] = self.k["settlements"][0]["id"] if self.k["settlements"] else None
                if self.k["capital"]:
                    self.settlement(self.k["capital"])["capital"] = True
            sett["capital"] = False
            h["settlement"] = None
            h["features"] = [f for f in h["features"] if f.get("kind") != "settlement"]
            h["features"].append({"kind": "freehold", "name": sett["name"], "settlement_data": sett})
        self.record(t("state.hex_unclaimed", col=col, row=row) if not sett
                    else t("state.hex_unclaimed_freehold", col=col, row=row, name=sett["name"]), "map")
        return sett

    def claim_freehold(self, col: int, row: int) -> bool:
        """Pledge of Fealty with a freehold: its hex joins the kingdom, and its
        settlement too, as it was when the kingdom lost it (or new, with an
        empty grid). No XP for a hex claimed before. A hex not adjacent to the
        kingdom is a secondary territory, by `secondary_hexes`."""
        from kingmaker.settlements import new_settlement

        h = self.existing_hex(col, row)
        free = next((f for f in (h or {}).get("features", ()) if f.get("kind") == "freehold"), None)
        if free is None:
            return False
        h["status"] = "claimed"
        if not h.get("ever_claimed"):
            self.k["xp"] += 10
        h["ever_claimed"] = True
        h["features"].remove(free)
        sett = free.get("settlement_data") or new_settlement(free.get("name") or h.get("name") or f"{col},{row}",
                                                             (col, row))
        sett["capital"] = False
        sett.setdefault("border_walls", {})
        sett.setdefault("border_bridges", {})
        self.k["settlements"].append(sett)
        if not self.k["capital"]:
            self.k["capital"] = sett["id"]
            sett["capital"] = True
        self.link_settlement(sett["id"], col, row)
        self.check_size_milestones()
        self.record(t("state.freehold_joined", name=sett["name"], col=col, row=row), "settlement")
        return True

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
        if delta > 0 and self._envy_ignores():
            return 0
        before = self.k["unrest"]
        self.k["unrest"] = max(0, before + delta)
        real = self.k["unrest"] - before
        if reason and real:
            self.record(t("state.unrest", real=real, reason=reason), "unrest")
        if before < self.anarchy_threshold <= self.k["unrest"]:
            self._offer_fame({"kind": "unrest"})
        if real > 0 and "crush_dissent" in self.k["feats"] and not self.feat_used("crush_dissent"):
            self._offer_feat({"kind": "crush_dissent", "unrest": real})
        return real

    def _envy_ignores(self) -> bool:
        """Envy of the World (20th level): the first time in a Kingdom turn
        the kingdom would gain Unrest or Ruin, that increase is ignored."""
        if self.level < 20 or self.feat_used("envy_of_the_world"):
            return False
        self.use_feat("envy_of_the_world")
        self.record(t("state.envy_ignored"), "kingdom")
        return True

    def activity_unrest(self, delta: int, reason: str = "") -> int:
        """Unrest changed by a kingdom activity: Endure Anarchy takes 1 more
        off a decrease while Unrest is 6 or higher."""
        if delta < 0 and "endure_anarchy" in self.k["feats"] and self.k["unrest"] >= 6:
            delta -= 1
        return self.modify_unrest(delta, reason)

    def modify_ruin(self, rid: str, delta: int, reason: str = "") -> None:
        """Applies a delta to a Ruin, raising the penalty at every threshold crossed."""
        if delta > 0 and self._envy_ignores():
            return
        r = self.k["ruins"][rid]
        penalty_before = r["penalty"]
        if delta < 0 and r["points"] == 0 and r["penalty"] > 0:
            # Nothing left to take off the points: a DC 16 flat check takes
            # 1 off the penalty instead.
            flat, _rolls = rules.roll(1, 20)
            if flat >= 16:
                r["penalty"] -= 1
            self.record(t("state.ruin_flat_check", name=rules.BY_ID["ruin"][rid]["name"], roll=flat,
                          penalty=r["penalty"]), "ruin")
            return
        r["points"] = max(0, r["points"] + delta)
        r["threshold"] = max(1, r["threshold"])     # at 0 the loop would never end
        while r["points"] > r["threshold"]:
            r["points"] -= r["threshold"]
            r["penalty"] += 1
            self.record(t("state.crosses_threshold_penalty_now", name=rules.BY_ID['ruin'][rid]['name'], penalty=r['penalty']), "ruin")
        if reason:
            self.record(t("state.text", delta=delta, name=rules.BY_ID['ruin'][rid]['name'], reason=reason), "ruin")
        if r["penalty"] > penalty_before:
            self._offer_fame({"kind": "ruin", "ruin": rid, "penalty": penalty_before})

    # ------------------------------------------------------ Kingdom checks
    def feat_used(self, key: str) -> bool:
        """A once-per-turn feat already used this turn."""
        return self.k["feat_turns"].get(key) == self.k["turn"]

    def use_feat(self, key: str) -> None:
        self.k["feat_turns"][key] = self.k["turn"]

    def kingdom_check(self, skill_id: str, dc: int, activity: str | None = None,
                      variant: str | None = None, hex_: tuple[int, int] | None = None,
                      settlement: str | None = None, event: str | None = None,
                      fair: bool = True, worsens_by: int = 0, leader: str | None = None,
                      subject: str | None = None, extra=()) -> rules.Result:
        """A Kingdom skill check, with everything that touches one: the
        breakdown (`check_detail`), Anarchy's worsening, and then the feats
        that act on the result — a one-check bonus used up (Focused
        Attention, and Cooperative Leadership at 11th level), Pull Together
        on a critical failure, a Fame/Infamy point and Fame and Fortune's
        Resource Die on a critical success. Every check of the app rolls
        here, so each feat works the same from the sheet, the turn, the map
        and the city."""
        detail = self.check_detail(skill_id, activity, variant, hex_, settlement, event, fair,
                                   leader, subject, extra)
        res = rules.roll_check(sum(v for _n, v in detail), dc, detail,
                               worsens_by + (1 if self.in_anarchy else 0))
        feats = set(self.k["feats"])
        ability = rules.BY_ID["skills"][skill_id]["ability"]
        aided = [m for m in self.active_modifiers(ability=ability, skills=skill_id) if m.get("once")]
        if aided:
            # One check: the first one with that skill uses it up.
            self.k["modifiers"] = [m for m in self.k["modifiers"] if m not in aided]
            res.notes.append(t("state.focus_used", name=aided[0]["name"]))
            if "cooperative_leadership" in feats and self.level >= 11:
                expert = rules.meets_proficiency(self.k["proficiencies"].get(skill_id, "untrained"), "expert")
                if res.grade == "critical_failure":
                    res.grade = "failure"
                    res.notes.append(t("state.cooperative_cf"))
                elif res.grade == "failure" and expert:
                    res.grade = "success"
                    res.notes.append(t("state.cooperative_f"))
        if (res.grade == "critical_failure" and "pull_together" in feats
                and not self.feat_used("pull_together")):
            flat_dc = self.k["pull_together_dc"]
            flat, _rolls = rules.roll(1, 20)
            self.use_feat("pull_together")
            self.k["pull_together_dc"] = flat_dc + 5
            if flat >= flat_dc:
                res.grade = "failure"
            res.notes.append(t("state.pull_together_ok", roll=flat, dc=flat_dc) if flat >= flat_dc
                             else t("state.pull_together_no", roll=flat, dc=flat_dc))
            self.record(res.notes[-1], "check")
        self.fame_on_critical(res)
        act = rules.BY_ID["activities"].get(activity) if activity else None
        if (res.grade == "critical_success" and "fame_and_fortune" in feats
                and act and act["phase"] == "activity"):
            self.k["bonus_dice"] += 1
            res.notes.append(t("state.fame_and_fortune"))
        return res

    def assurance_available(self, skill_id: str) -> bool:
        """Kingdom Assurance: a chosen, trained skill, not yet used this turn."""
        return ("kingdom_assurance" in self.k["feats"]
                and skill_id in (self.feat_choice("kingdom_assurance") or [])
                and self.k["proficiencies"].get(skill_id, "untrained") != "untrained"
                and not self.feat_used(f"kingdom_assurance:{skill_id}"))

    def assurance_result(self, skill_id: str, dc: int) -> rules.Result:
        """Kingdom Assurance: no roll, 10 + the proficiency bonus, and no
        other modifier at all."""
        self.use_feat(f"kingdom_assurance:{skill_id}")
        prof = self.k["proficiencies"].get(skill_id, "untrained")
        bonus = rules.proficiency_bonus(self.level, prof)
        total = 10 + bonus
        name = rules.BY_ID["feat"]["kingdom_assurance"]["name"]
        res = rules.Result(10, bonus, total, dc, rules.success_grade(total, dc, 10),
                           [(name, 10), (rules.BY_ID["proficiency"][prof]["name"], bonus)])
        res.notes.append(t("state.assurance_note"))
        self.fame_on_critical(res)
        return res

    def muddle_through(self, on: bool) -> None:
        """Muddle Through on the Ruin thresholds: one +2, two +1, the fourth
        as it is, by the table's choice. Taken back exactly as given when
        the feat is dropped or the choice changes; thresholds edited by hand
        meanwhile keep their edit."""
        ruins = self.k["ruins"]
        choice = self.k["feat_choices"].setdefault(
            "muddle_through", {"plus2": RUIN_IDS[0], "none": RUIN_IDS[-1], "applied": {}})
        for rid, d in choice.get("applied", {}).items():
            ruins[rid]["threshold"] = max(1, ruins[rid]["threshold"] - d)
        choice["applied"] = {}
        if on:
            for rid in RUIN_IDS:
                d = 2 if rid == choice["plus2"] else 0 if rid == choice["none"] else 1
                if d:
                    ruins[rid]["threshold"] += d
                    choice["applied"][rid] = d

    # ------------------------------------------------------------- level up
    # The kingdom's advancement table: what each level grants, by name.
    BOOST_LEVELS = (5, 10, 15, 20)
    RUIN_RESISTANCE_LEVELS = (5, 8, 11, 14, 17, 20)

    def advancement(self, level: int) -> list[str]:
        """The choices a level asks for: "boosts", "skill", "ruin"."""
        out = []
        if level in self.BOOST_LEVELS:
            out.append("boosts")
        if level >= 3 and level % 2 == 1:
            out.append("skill")
        if level in self.RUIN_RESISTANCE_LEVELS:
            out.append("ruin")
        return out

    def advancement_done(self, level: int, what: str) -> bool:
        return what in self.k["advancements"].get(str(level), {})

    def boost_abilities(self, level: int, first: str, second: str) -> bool:
        """Ability boosts: two different abilities, +2 each (+1 from 18)."""
        if first == second or self.advancement_done(level, "boosts") or \
                not {first, second} <= set(self.k["abilities"]):
            return False
        for ab in (first, second):
            self.k["abilities"][ab] += 2 if self.k["abilities"][ab] < 18 else 1
        self.k["advancements"].setdefault(str(level), {})["boosts"] = [first, second]
        return True

    def skill_increase_options(self, level: int) -> dict[str, str]:
        """The skills a skill increase may raise, with the rank they reach:
        trained and expert always, master from 7th level, legendary from 15th."""
        ladder = ["untrained", "trained", "expert", "master", "legendary"]
        top = "legendary" if level >= 15 else "master" if level >= 7 else "expert"
        out = {}
        for a in rules.SKILLS:
            now = self.k["proficiencies"].get(a["id"], "untrained")
            if now != "legendary" and ladder.index(now) + 1 <= ladder.index(top):
                out[a["id"]] = ladder[ladder.index(now) + 1]
        return out

    def increase_skill(self, level: int, skill: str) -> bool:
        options = self.skill_increase_options(level)
        if skill not in options or self.advancement_done(level, "skill"):
            return False
        self.k["proficiencies"][skill] = options[skill]
        self.k["advancements"].setdefault(str(level), {})["skill"] = skill
        return True

    def ruin_resistance(self, level: int, rid: str) -> bool:
        """Ruin Resistance: that Ruin's threshold +2 and its penalty back to 0."""
        if rid not in self.k["ruins"] or self.advancement_done(level, "ruin"):
            return False
        self.k["ruins"][rid]["threshold"] += 2
        self.k["ruins"][rid]["penalty"] = 0
        self.k["advancements"].setdefault(str(level), {})["ruin"] = rid
        return True

    def new_turn_feats(self) -> None:
        """What the kingdom feats do as a Kingdom turn starts. Pull Together's
        DC drops by 1 (to 11 at least) for a turn it was not used in."""
        if self.k["feat_turns"].get("pull_together") != self.k["turn"] - 1:
            self.k["pull_together_dc"] = max(11, self.k["pull_together_dc"] - 1)

    # ------------------------------------------------- feats' offers
    def _offer_feat(self, offer: dict) -> None:
        """A choice a feat gives the table right after something happened
        (Crush Dissent, Liquidate Resources): offered, like the Fame ones,
        to whoever caused it."""
        pending = next((o for o in self.feat_offers if o["kind"] == offer["kind"]), None)
        if pending is None:
            self.feat_offers.append(offer)
        elif offer["kind"] == "rp_shortfall":
            # Every unpaid expense costs a Ruin point: a second shortfall
            # before the table answered is one more to choose.
            pending["count"] = pending.get("count", 1) + 1

    def take_feat_offers(self) -> list[dict]:
        offers, self.feat_offers = self.feat_offers, []
        return [o for o in offers if not self.feat_used(o["kind"])]

    def liquidate(self) -> bool:
        """Liquidate Resources: the expense counts as paid in full and RP
        stay at 1; next turn's Resource Dice are 4 fewer."""
        if "liquidate_resources" not in self.k["feats"] or self.feat_used("liquidate_resources"):
            return False
        self.use_feat("liquidate_resources")
        self.k["rp"] = max(1, self.k["rp"])
        self.k["penalty_dice"] += 4
        self.record(t("state.liquidated"), "resources")
        return True

    # ------------------------------------------------- staving off with Fame
    def _offer_fame(self, offer: dict) -> None:
        """Anarchy or a Ruin penalty just arrived, and Fame/Infamy may stave
        it off. One offer per thing: a second Ruin increase before the table
        answers keeps the penalty the Ruin had before the first."""
        if self.k["fame_points"] < 1:
            return
        key = (offer["kind"], offer.get("ruin"))
        if all((o["kind"], o.get("ruin")) != key for o in self.fame_offers):
            self.fame_offers.append(offer)

    def fame_offer_valid(self, offer: dict) -> bool:
        """Whether the offer still stands: points to spend, and the Anarchy or
        the penalty still there (somebody may have fixed it meanwhile)."""
        if self.k["fame_points"] < 1:
            return False
        if offer["kind"] == "unrest":
            return self.in_anarchy
        return self.k["ruins"][offer["ruin"]]["penalty"] > offer["penalty"]

    def take_fame_offers(self) -> list[dict]:
        """The offers still standing, handed over once."""
        offers, self.fame_offers = self.fame_offers, []
        return [o for o in offers if self.fame_offer_valid(o)]

    def stave_off(self, offer: dict) -> bool:
        """Spends every Fame/Infamy point to stave off the Anarchy or the Ruin
        penalty of `offer`: Unrest stops 1 below the Anarchy threshold, the
        Ruin 1 point below where its penalty would rise, the penalty as it
        was. False, and nothing spent, when the offer no longer stands."""
        if not self.fame_offer_valid(offer):
            return False
        spent = self.k["fame_points"]
        if offer["kind"] == "unrest":
            self.k["unrest"] = self.anarchy_threshold - 1
            self.record(t("state.fame_staved_anarchy", n=spent, fame=self.fame_name,
                          unrest=self.k["unrest"]), "unrest")
        else:
            r = self.k["ruins"][offer["ruin"]]
            r["penalty"] = offer["penalty"]
            r["points"] = r["threshold"]
            self.record(t("state.fame_staved_ruin", n=spent, fame=self.fame_name,
                          name=rules.BY_ID["ruin"][offer["ruin"]]["name"],
                          points=r["points"], penalty=r["penalty"]), "ruin")
        self.k["fame_points"] = 0
        return True

    def settlement_level(self, sett: dict) -> int:
        """Equal to the number of blocks with at least one structure (max 20)."""
        n = 0
        for grid in sett["grids"]:
            for block_ in grid:
                if any(l.get("structure") for l in block_):
                    n += 1
        return min(20, n)

    def structures_of(self, sett: dict) -> dict[str, int]:
        """The structures standing in the settlement, by id, with how many.
        One being demolished (a lot of it marked `demolishing`) stops working
        once demolition starts."""
        tally: dict[str, int] = {}
        for grid in sett["grids"]:
            for block_ in grid:
                seen = set()
                razing = {lot.get("gid") for lot in block_ if lot.get("demolishing")}
                for lot in block_:
                    name, gid = lot.get("structure"), lot.get("gid")
                    if not name or (gid and gid in razing):
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

    SETTLEMENT_ORDER = ("village", "town", "city", "metropolis")

    def check_milestones(self) -> bool:
        """The milestones that follow from the kingdom as it is, awarded
        whichever way it got there: not only a Claim Hex roll or the
        Expand button, but the hex editor, a Landmark marked on a hex
        already claimed, a settlement's type set by hand. Each one once
        (`award_milestone`); the two that are events, not states — the
        first diplomatic relation and trade agreement — come from the
        activities' effects. True when one was awarded now."""
        before = len(self.k["milestones"])
        claimed = self.claimed_hexes()
        for h in claimed:
            h["ever_claimed"] = True        # claimed again after a loss: no XP
        features = {f.get("kind") for h in claimed for f in h.get("features", ())}
        if "landmark" in features:
            self.award_milestone("first_landmark")
        if "refuge" in features:
            self.award_milestone("first_refuge")
        self.check_size_milestones()
        types = [s["kind"] for s in self.k["settlements"] if s["kind"] in self.SETTLEMENT_ORDER]
        top = max((self.SETTLEMENT_ORDER.index(k) for k in types), default=-1)
        for i, mid in enumerate(("first_village", "first_town", "first_city", "first_metropolis")):
            if top >= i:
                self.award_milestone(mid)
        if all(r["name"] or r.get("character_id") for r in self.k["roles"].values()):
            self.award_milestone("all_eight_leaders")
        if self.k["rp_spent_turn"] >= 100:
            self.award_milestone("rp_100")
        return len(self.k["milestones"]) > before

    # ------------------------------------------------------------ commodities/RP
    def add_commodity(self, commodity: str, quantity: int) -> int:
        """Adds Commodities within the storage limit. Returns what was lost."""
        limit = self.storage(commodity)
        if (commodity == "luxuries" and quantity > 0 and "quality_of_life" in self.k["feats"]
                and not self.feat_used("quality_of_life")):
            self.use_feat("quality_of_life")
            quantity += 1
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

    def _forced_short(self) -> None:
        """An expense forced by an outcome left the kingdom at 0 RP: +1 to a
        Ruin of the PCs' choice, for every such expense; Liquidate Resources
        may cover it instead."""
        self._offer_feat({"kind": "rp_shortfall", "count": 1})
        if "liquidate_resources" in self.k["feats"] and not self.feat_used("liquidate_resources"):
            self._offer_feat({"kind": "liquidate_resources"})

    def rp_shortfall(self, rid: str) -> bool:
        """The kingdom could not pay an expense: +1 to the Ruin the PCs chose.
        Every unpaid expense costs its point: nothing limits it to once a turn."""
        if rid not in self.k["ruins"]:
            return False
        self.modify_ruin(rid, 1, t("theme.rp_shortfall_reason"))
        return True

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

    @property
    def fame_name(self) -> str:
        """«Fame» or «Infamy», whichever the kingdom tracks."""
        return t("main.fame") if self.k["reputation"] == "fame" else t("main.infamy")

    def spend_fame(self) -> bool:
        """One Fame/Infamy point, for a reroll; False when there is none."""
        if self.k["fame_points"] < 1:
            return False
        self.k["fame_points"] -= 1
        return True

    def fame_from_structure(self, sid: str) -> int:
        """Building a famous or infamous structure: +1 point when the trait is
        the kingdom's, -1 when it is the opposite one; a structure with both
        counts as the kingdom's. Returns the change made."""
        traits = (rules.BY_ID["structure"].get(sid) or {}).get("traits", ())
        mine, other = (("famous", "infamous") if self.k["reputation"] == "fame"
                       else ("infamous", "famous"))
        delta = 1 if mine in traits else -1 if other in traits else 0
        before = self.k["fame_points"]
        self.k["fame_points"] = max(0, min(self.max_fame, before + delta))
        return self.k["fame_points"] - before

    # ------------------------------------------------- an activity's DC
    def activity_dc(self, act_id: str, *, subject: str | None = None, base: int | None = None,
                    extra=()) -> tuple[int, list[tuple[str, int]]]:
        """An activity's DC and its breakdown, `[(label, value), ...]`, the
        base first: the Control DC and the activity's modifier, a fixed DC,
        the partner's Negotiation DC, or `base` (a structure's DC); then what
        the turns remember (a repeat, a streak); then the caller's `extra`
        pairs. Every place that rolls an activity reads its DC here."""
        act = rules.BY_ID["activities"][act_id]
        cd = act["dc"]
        cdc = self.control_dc
        parts: list[tuple[str, int]] = []
        if cd["kind"] == "control":
            parts.append((t("turn.control_dc", control_dc=cdc), cdc))
            if cd.get("mod"):
                parts.append((cd.get("note") or t("turn.modifier"), cd["mod"]))
        elif cd["kind"] == "fixed":
            parts.append((t("turn.fixed_dc", dc=cd["valore"]), cd["valore"]))
        elif cd["kind"] == "none_":
            parts.append((cd.get("note") or t("turn.no_check"), 0))
        elif base is not None:
            parts.append((t("turn.fixed_dc", dc=base), base))
        else:
            partner = self.partner(subject) if subject else None
            if partner and act_id in ("send_diplomatic_envoy", "pledge_of_fealty"):
                parts.append((t("turn.dc_negotiation", name=partner["name"],
                                dc=partner["negotiation_dc"]), partner["negotiation_dc"]))
            elif partner and act_id == "request_foreign_aid":
                parts.append((t("turn.dc_negotiation", name=partner["name"],
                                dc=partner["negotiation_dc"]), partner["negotiation_dc"]))
                parts.append((t("turn.dc_foreign_aid"), 2))
            elif partner and act_id == "establish_trade_agreement":
                higher = max(partner["negotiation_dc"], cdc)
                parts.append((t("turn.dc_higher", name=partner["name"], dc=partner["negotiation_dc"],
                                control_dc=cdc), higher))
            else:
                parts.append((cd.get("note") or t("turn.dc_gm"), cdc))
        if act.get("repeat_dc") and self.repeated(act_id):
            parts.append((t("turn.dc_repeat"), act["repeat_dc"]))
        streak = memory.streak_dc(self.k, act_id, act.get("streak_dc"))
        if streak:
            parts.append((t("turn.dc_streak"), streak))
        parts.extend(extra)
        return sum(v for _n, v in parts), parts

    # ------------------------------------------------- what the turns remember
    def repeated(self, act_id: str) -> bool:
        return memory.repeated(self.k, act_id)

    def note_grade(self, act_id: str, grade: str) -> None:
        memory.note_grade(self.k, act_id, grade)

    def debt(self, key: str) -> dict | None:
        return memory.debt(self.k, key)

    def due_checks(self) -> list[dict]:
        """The flat checks the activities left for this turn's Event phase."""
        return memory.due_checks(self.k)

    def clear_pending(self, source: str, hex_) -> int:
        """A later success takes back a pending check (Irrigation on the same
        hex). Returns how many were removed."""
        pending = memory.memory(self.k)["pending"]
        keep = [e for e in pending if not (e.get("source") == source and e.get("hex")
                                           and list(e["hex"]) == list(hex_))]
        removed = len(pending) - len(keep)
        pending[:] = keep
        return removed

    def lockout_reason(self, act_id: str, subject: str | None = None) -> str:
        entry = memory.lockout(self.k, act_id, subject)
        if not entry:
            return ""
        return t("state.locked_out", activity=rules.BY_ID["activities"][act_id]["name"],
                 until=entry["until_turn"] + 1)

    def worsens_by(self, act_id: str, subject: str | None = None) -> int:
        """Degrees an activity's result is worsened by what the turns
        remember: Tap Treasury while the treasury is owed (two), an envoy to
        a partner at war (one)."""
        if act_id == "tap_treasury" and self.debt("tap_treasury"):
            return 2
        if act_id == "send_diplomatic_envoy" and subject and self.at_war_with(subject):
            return 1
        return 0

    def new_turn_memory(self) -> None:
        memory.new_turn(self.k)
        # A failed construction's free retry lasts one turn.
        for sett in self.k["settlements"]:
            for grid in sett.get("grids") or []:
                for block_ in grid:
                    for lot in block_:
                        failed = lot.get("failed")
                        if failed and failed.get("turn", 0) < self.k["turn"] - 1:
                            lot.pop("failed", None)

    # ------------------------------------------------- events
    def ongoing_events(self) -> list[dict]:
        return [e for e in self.k["events"] if e.get("ended_turn") is None]

    def event(self, eid: str | None) -> dict | None:
        return next((e for e in self.k["events"] if e["id"] == eid), None)

    def event_dc(self, ev: dict) -> int:
        """An event's DC: the Control DC and the event's level modifier."""
        return self.control_dc + int(ev.get("modifier") or 0)

    # ------------------------------------------------- partners
    def partner(self, pid: str | None) -> dict | None:
        return next((p for p in self.k["partners"] if p["id"] == pid), None)

    def relation(self, pid: str | None) -> dict | None:
        """The latest relation with that partner, or None."""
        found = [r for r in self.k["diplomatic_relations"] if r.get("partner") == pid]
        return found[-1] if found else None

    def at_war(self) -> list[dict]:
        return [r for r in self.k["diplomatic_relations"]
                if r.get("status") == "war" and r is self.relation(r.get("partner"))]

    def at_war_with(self, pid: str) -> bool:
        rel = self.relation(pid)
        return bool(rel and rel.get("status") == "war")

    def related_partners(self) -> list[dict]:
        """The partners the kingdom has diplomatic relations with now."""
        return [p for p in self.k["partners"]
                if (self.relation(p["id"]) or {}).get("status") == "relations"]

    def active_agreements(self) -> list[dict]:
        return [a for a in self.k["trade_agreements"]
                if isinstance(a, dict) and a.get("ended_turn") is None]

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
            bonus = self.k["region_bonus"]
            return 3 + (bonus.get("count", 0) if bonus.get("turn") == self.k["turn"] else 0)
        if step == "civic":
            # Civic Planning (12th level): one settlement attempts two.
            return len(self.k["settlements"]) + (1 if self.level >= 12 else 0)
        return None

    def add_region_activity(self) -> None:
        """A Claim Hex critical success: one more Region activity this turn."""
        bonus = self.k["region_bonus"]
        if bonus.get("turn") != self.k["turn"]:
            bonus.clear()
            bonus.update(turn=self.k["turn"], count=0)
        bonus["count"] += 1

    def activity_uses(self, act_id: str) -> int:
        return self.k["turn_activities"].get(act_id, 0)

    def step_uses(self, phase: str, step: str) -> int:
        return sum(n for aid, n in self.k["turn_activities"].items()
                   if (a := rules.BY_ID["activities"].get(aid))
                   and a["phase"] == phase and a["step"] == step)

    def mark_activity(self, act_id: str, *, role: str | None = None, character: str | None = None,
                      settlement: str | None = None, hex_=None, skill: str | None = None,
                      subject: str | None = None) -> None:
        """An activity attempted: counted for the turn, for its leader and
        its settlement, and written in the record the turns remember."""
        self.k["turn_activities"][act_id] = self.activity_uses(act_id) + 1
        if role:
            mine = self.k["turn_leaders"].setdefault(role, {})
            mine[act_id] = mine.get(act_id, 0) + 1
        if settlement:
            self.k["turn_civic"][settlement] = self.k["turn_civic"].get(settlement, 0) + 1
        act = rules.BY_ID["activities"].get(act_id) or {}
        if act.get("streak_dc"):
            memory.bump_streak(self.k, act_id, act["streak_dc"])
        memory.record_activity(self.k, act_id, role=role, character=character, settlement=settlement,
                               hex_=hex_, skill=skill, subject=subject)

    def downtime_choice(self, rid: str) -> str | None:
        """What an unticked leader chose this turn: "give_up" or "penalty"."""
        dt = self.k["downtime"]
        if dt.get("turn") != self.k["turn"]:
            return None
        return (dt.get("choices") or {}).get(rid)

    def leader_cap(self, rid: str) -> int:
        """How many Leadership activities that leader may attempt this turn."""
        return self.max_leadership_activities() - (1 if self.downtime_choice(rid) == "give_up" else 0)

    def role_label(self, rid: str) -> str:
        """«Ruler: Aldra», the role and who holds it."""
        data = self.k["roles"][rid]
        name = data.get("name") or ""
        if data.get("character_id"):
            char = self.archive.character(data["character_id"]) if self.archive else None
            if char:
                name = char["name"]
        role = rules.BY_ID["role"][rid]["name"]
        return f"{role}: {name}" if name else role

    def lockout_only(self, act: dict, subject: str | None = None, **where) -> bool:
        """The one reason this activity is refused is a lock-out, which the
        GM may override."""
        return bool(self.lockout_reason(act["id"], subject)) and not self._block_reason(act, **where)

    def activities_block(self, act: dict, *, leader: str | None = None, subject: str | None = None,
                         settlement: str | None = None) -> str:
        """Why this activity cannot be attempted right now — empty string if it can."""
        return (self._block_reason(act, leader=leader, settlement=settlement)
                or self.lockout_reason(act["id"], subject))

    def _block_reason(self, act: dict, *, leader: str | None = None,
                      settlement: str | None = None) -> str:
        """Every reason but a lock-out."""
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
        if act["id"] == "claim_hex" and self.activity_uses("claim_hex") >= self.claims_per_turn():
            return t("state.claims_used_up", n=self.claims_per_turn())
        max_ = self.step_limit(act["phase"], act["step"])
        if max_ is not None and self.step_uses(act["phase"], act["step"]) >= max_:
            name = {"leadership": t("state.leadership"), "region": t("state.region"),
                    "civic": t("state.civic")}.get(act["step"], act["step"])
            return t("state.activities_used_up_this", name=name, max=max_, max2=max_)
        if act.get("subject") == "event" and not any(
                not e.get("hire_locked") for e in self.ongoing_events()):
            return t("state.hire_no_event")
        # One leader, two or three Leadership activities, never the same twice.
        if leader and act["phase"] == "activity" and act["step"] == "leadership":
            mine = self.k["turn_leaders"].get(leader, {})
            label = self.role_label(leader)
            if act["id"] in mine:
                return t("state.leader_repeats", name=label, activity=act["name"])
            cap = self.leader_cap(leader)
            if sum(mine.values()) >= cap:
                return t("state.leader_used_up", name=label, n=cap)
        # One Civic activity per settlement; Civic Planning (12th level) lets
        # one settlement attempt a second once every other has acted.
        if settlement and act["phase"] == "activity" and act["step"] == "civic":
            used = self.k["turn_civic"]
            if used.get(settlement, 0) >= 1:
                others = [s["id"] for s in self.k["settlements"] if s["id"] != settlement]
                if not (self.level >= 12 and used.get(settlement, 0) == 1
                        and all(used.get(o, 0) >= 1 for o in others)
                        and not any(n >= 2 for n in used.values())):
                    sett = self.settlement(settlement)
                    return t("state.settlement_acted", name=sett["name"] if sett else "")
        return ""

    # ------------------------------------------------- activity effects
    def apply_effect(self, entry: dict, value: int, target: str | None = None,
                     dice: list | None = None, context: dict | None = None) -> str:
        """Applies a single effect and returns how to describe it in the journal.

        The Resource Dice an effect rolls go into `dice`, when given, as
        `{"rolls", "faces", "total", "spent"}`: the caller shows them to the table.
        `context` says what the outcome is about: the activity (`act`), its
        `subject` (a Ruin, a partner, a role), the `event`, the `leader`, the
        `hex` or `hexes`."""
        kind = entry["t"]
        context = context or {}
        if kind == "note":
            return ""
        if kind in _NO_VALUE:
            return self._apply_marker(entry, target, context)
        if kind != "mod" and value == 0:
            return ""
        if kind == "unrest":
            # An activity's decrease goes through Endure Anarchy; what is
            # written is what really changed.
            value = self.activity_unrest(value) if value < 0 else self.modify_unrest(value)
            if not value:
                return ""
        elif kind in ("ruin", "ruin_choice"):
            rid = entry["r"] if kind == "ruin" else target
            if not rid:
                return ""
            self.modify_ruin(rid, value)
            if entry.get("pen"):
                r = self.k["ruins"][rid]
                r["penalty"] = max(0, r["penalty"] + entry["pen"])
            return f"{rules.BY_ID['ruin'][rid]['name']} {value:+d}"
        elif kind == "rp":
            if value < 0:
                if not self.spend_rp(-value):
                    self._forced_short()
            else:
                self.k["rp"] += value
                if entry.get("no_xp"):
                    self.k["rp_no_xp"] = self.k.get("rp_no_xp", 0) + value
        elif kind == "xp":
            self.k["xp"] = max(0, self.k["xp"] + value)
        elif kind == "fame":
            self.k["fame_points"] = max(0, min(self.max_fame, self.k["fame_points"] + value))
        elif kind == "focus":
            # Focused Attention: +2 (+3 with Cooperative Leadership) to one
            # check with the chosen skill, this turn.
            if target not in rules.BY_ID["skills"]:      # chosen in the browser
                return ""
            bonus = 3 if "cooperative_leadership" in self.k["feats"] else 2
            name = rules.BY_ID["activities"]["focused_attention"]["name"]
            self.add_modifier(name, bonus, 1, skills=target, kind="circumstance")
            self.k["modifiers"][-1]["once"] = True
            return t("state.focus_given", name=name, value=bonus,
                     skill=rules.BY_ID["skills"][target]["name"])
        elif kind == "rp_next":
            self.k["rp_next_turn"] = max(0, self.k["rp_next_turn"] + value)
        elif kind == "fame_next":
            self.k["fame_next_turn"] = max(0, self.k["fame_next_turn"] + value)
        elif kind == "milestone":
            # Once per campaign: nothing to say when it was earned already.
            if not self.award_milestone(entry["m"]):
                return ""
        elif kind in ("commodity", "commodity_choice"):
            char_id = entry["p"] if kind == "commodity" else target
            if not char_id:
                return ""
            if value < 0:
                self.k["commodities"][char_id] = max(0, self.k["commodities"][char_id] + value)
            else:
                self.add_commodity(char_id, value)
            return f"{rules.BY_ID['commodity'][char_id]['name']} {value:+d}"
        elif kind == "resource_die":
            tot, rolls = rules.roll(abs(value), self.resource_die)
            if value < 0:
                if not self.spend_rp(tot):
                    self._forced_short()
            else:
                self.k["rp"] += tot
                if entry.get("no_xp"):
                    self.k["rp_no_xp"] = self.k.get("rp_no_xp", 0) + tot
            if dice is not None:
                dice.append({"rolls": rolls, "faces": self.resource_die, "total": tot,
                             "spent": value < 0})
            return t("state.resource_dice_spent" if value < 0 else "state.resource_dice_gained",
                     dice=f"{abs(value)}d{self.resource_die}", tot=tot,
                     rolls=", ".join(map(str, rolls)))
        elif kind == "bonus_dice":
            self.k["bonus_dice"] += value
        elif kind == "mod":
            self.add_modifier(entry["name"], entry["v"], entry["dur"],
                                       ability=entry.get("ability"), skills=entry.get("skill"))
        return rules.entry_label(entry, value)

    def _apply_marker(self, entry: dict, target: str | None, context: dict) -> str:
        """The effect kinds that write what the turns remember, or change the
        map or the partners, with no number to apply."""
        kind = entry["t"]
        act_id = context.get("act")
        act = rules.BY_ID["activities"].get(act_id) if act_id else None
        reason = act["name"] if act else (context.get("reason") or "")
        mem = memory.memory(self.k)
        turn = self.k["turn"]
        if kind == "lockout":
            scope = entry.get("scope", "self")
            if scope in ("ruin", "target"):
                subject = target or context.get("subject")
                if not subject:
                    return ""
            else:
                subject = None
            memory.add_lockout(self.k, act_id or "", subject, int(entry.get("turns") or 1), reason)
        elif kind == "pending_check":
            hex_ = context.get("hex")
            mem["pending"].append({
                "due_turn": turn, "phase": "event", "dc": entry.get("dc"),
                "dc_per_hex": act_id == "irrigation", "source": act_id or "",
                "hex": list(hex_) if hex_ else None,
                "remaining": entry.get("repeat"), "then": entry.get("event")})
        elif kind == "event_mark":
            ev = self.event(target or context.get("event"))
            if not ev:
                return ""
            mark = entry.get("mark")
            if mark == "ended":
                ev["ended_turn"] = turn
            elif mark == "hire_bonus":
                ev["hire_bonus"] = turn
            elif mark == "hire_failed":
                ev["hire_failed"] = True
            elif mark == "hire_locked":
                ev["hire_locked"] = True
            return rules.entry_label(entry, 0, ev["name"])
        elif kind == "debt":
            mem["debts"][entry["key"]] = {"since_turn": turn, "note": reason}
        elif kind == "repay":
            if mem["debts"].pop(entry["key"], None) is None:
                return ""
        elif kind == "penalty":
            scope = entry.get("scope", "kingdom")
            role = subject = None
            if scope == "leader":
                role = context.get("subject") if act_id == "new_leadership" else context.get("leader")
                if not role:
                    return ""
            elif scope == "partner":
                subject = target or context.get("subject")
                if not subject:
                    return ""
            turns = entry.get("turns")
            mem["penalties"].append({
                "role": role, "subject": subject, "value": int(entry.get("v") or 0),
                "kind": entry.get("kind", "circumstance"), "scope": scope, "reason": reason,
                "until_turn": turn + int(turns) - 1 if turns else None,
                "clears_on": entry.get("clears_on"), "phase": entry.get("phase"),
                "since_turn": turn})
            who = (self.role_label(role) if role else
                   (self.partner(subject) or {}).get("name", "") if subject else "")
            return rules.entry_label(entry, 0, who)
        elif kind == "unclaim":
            hexes = [tuple(h) for h in context.get("hexes") or ()]
            if not hexes:
                return ""
            for c, r in hexes:
                self.unclaim_hex(c, r)
            return rules.entry_label(entry, 0, ", ".join(f"{c},{r}" for c, r in hexes), n=len(hexes))
        elif kind == "claim":
            hex_ = context.get("hex")
            if not hex_ or not self.claim_freehold(*hex_):
                return ""
            return rules.entry_label(entry, 0, f"{hex_[0]},{hex_[1]}")
        elif kind == "relation":
            pid = target or context.get("subject")
            partner = self.partner(pid)
            if not partner:
                return ""
            status = entry.get("status", "relations")
            rel = self.relation(pid)
            if rel is None or rel.get("status") == "ended":
                if status == "ended":
                    return ""
                self.k["diplomatic_relations"].append({
                    "partner": pid, "since_turn": turn, "status": status,
                    "abstract_war": False, "bonus": 0, "note": ""})
            else:
                rel["status"] = status
            return rules.entry_label(entry, 0, partner["name"])
        elif kind == "agreement":
            pid = target or context.get("subject")
            partner = self.partner(pid)
            if not partner:
                return ""
            if entry.get("what", "new") == "new":
                self.k["trade_agreements"].append({"partner": pid, "since_turn": turn,
                                                   "ended_turn": None, "note": ""})
            else:
                found = [a for a in self.active_agreements() if a.get("partner") == pid]
                if not found:
                    return ""
                for a in found:
                    a["ended_turn"] = turn
            return rules.entry_label(entry, 0, partner["name"])
        return rules.entry_label(entry, 0)


STATE = State()
