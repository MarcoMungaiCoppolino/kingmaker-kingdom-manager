# -*- coding: utf-8 -*-
"""Structures have a stable id; the effects on the kingdom are data, not
readings of the text. Old saves, which kept the Italian name in the lots, go
through the migration."""
import copy

from kingmaker.storage import migrations
from kingmaker import rules
from kingmaker.state import STATE, new_kingdom

results = []
S = rules.BY_ID["structure"]

# --- 1. ids: 76, unique, ASCII, and the references between structures use them
ids = [s["id"] for s in rules.STRUCTURES]
results.append(("76 structures with unique ids", len(ids) == 76 and len(set(ids)) == 76))
results.append(("the ids are ascii slugs",
              all(i.replace("_", "").isalnum() and i.isascii() and i == i.lower() for i in ids)))
references = [x for s in rules.STRUCTURES for x in s["upgrade_of"] + s["upgrade_to"]]
results.append(("the upgrades point at existing ids", references and all(x in S for x in references)))
results.append(("Tenements upgrade into Houses", S["houses"]["upgrade_of"] == ["tenement"]))
results.append(("Rubble cannot be built",
              "rubble" not in {s["id"] for s in rules.all_structures()}
              and len(rules.all_structures()) == 75))

# --- 2. structured effects: what the old text reader found -----------------
def effects(sid):
    return rules.structure_effects(S[sid])

with_effects = {s["id"] for s in rules.STRUCTURES if s["kingdom_effects"]}
# 29: the Barracks and the Magical Streetlamps had lost theirs (Archives of Nethys).
results.append(("29 structures touch Unrest or Ruins", len(with_effects) == 29))
results.append(("Houses reduce Unrest by 1",
              any(v["kind"] == "unrest" and v["sign"] == -1 and v["quantity"] == "1"
                  for v in effects("houses"))))
results.append(("the Jail reduces Crime",
              any(v["kind"] == "ruin" and v["ruin"] == "crime" and v["sign"] == -1
                  for v in effects("jail"))))
results.append(("the Thieves' Guild costs Crime",
              any(v["kind"] == "ruin" and v["ruin"] == "crime" and v["sign"] == 1
                  for v in effects("thieves_guild"))))
results.append(("a Hospital has no automatic effects", effects("hospital") == []))
results.append(("every entry has kind, sign, amount and text",
              all({"kind", "sign", "quantity", "text"} <= set(v) for s in rules.STRUCTURES
                  for v in s["kingdom_effects"])))
results.append(("the amount is always read",
              all(isinstance(rules.quantity_value(v["quantity"])[0], int)
                  for s in rules.STRUCTURES for v in s["kingdom_effects"])))

# --- 3. old lots are migrated from the name to the id ----------------------
old = copy.deepcopy(STATE.k)
old["settlements"] = [{
    "id": "x", "name": "Borgo", "grids": [[
        [{"structure": "Casamenti", "gid": 1}, {"structure": "Macerie", "gid": 2},
         {"structure": None, "gid": None}, {"structure": "tenement", "gid": 3}],
    ]],
}]
new = migrations.normalize(old, new_kingdom)
lots = new["settlements"][0]["grids"][0][0]
results.append(("«Casamenti» becomes tenement", lots[0]["structure"] == "tenement"))
results.append(("«Macerie» becomes rubble", lots[1]["structure"] == "rubble"))
results.append(("an empty lot stays empty", lots[2]["structure"] is None))
results.append(("an already new id stays as it is", lots[3]["structure"] == "tenement"))
results.append(("the names map covers every structure",
              set(migrations.LEGACY_STRUCTURE_NAMES.values()) == set(ids)))

# --- 4. whoever counts structures reasons by id ----------------------------
sett = {"grids": [[[{"structure": "castle", "gid": 1}, {"structure": "castle", "gid": 1}]]]}
results.append(("a Castle on two lots counts once", STATE.structures_of(sett) == {"castle": 1}))
cap_before = STATE.k["capital"]
STATE.k["settlements"].append({"id": "cap_prova", "name": "Prova", "grids": sett["grids"]})
STATE.k["capital"] = "cap_prova"
results.append(("with the Castle in the capital the leadership activities are 3",
              STATE.max_leadership_activities() == 3))
STATE.k["settlements"].pop()
STATE.k["capital"] = cap_before

for name, ok in results:
    print(f" {'ok' if ok else 'NO'}  {name}")
print(f"\n{sum(1 for _n, e in results if e)}/{len(results)} passed")

# --- 5. skills, proficiencies and traits are ids too -------------------------
extra_results = []
options = [o for s in rules.STRUCTURES if s["construction"] for o in s["construction"]["options"]]
extra_results.append(("every construction option points at a kingdom skill",
                    all(o["skill"] in rules.BY_ID["skills"] for o in options)))
extra_results.append(("and at a proficiency",
                    all(o["proficiency"] in rules.BY_ID["proficiency"] for o in options)))
extra_results.append(("the Gladiatorial Arena asks for Warfare (it was «Sapienza Bellica», ignored)",
                    S["gladiatorial_arena"]["construction"]["options"][0]["skill"] == "warfare"))
extra_results.append(("the traits are known ids",
                    all(t in rules.BY_ID["structure_trait"] for s in rules.STRUCTURES for t in s["traits"])))
extra_results.append(("Houses are residential", "residential" in S["houses"]["traits"]))
for name, ok in extra_results:
    print(f" {'ok' if ok else 'NO'}  {name}")
print(f"\n{sum(1 for _n, e in results + extra_results if e)}/{len(results) + len(extra_results)} passed")
