# -*- coding: utf-8 -*-
"""Phase 2 (one-off, kept for the record): structures get stable ids and
structured kingdom effects.

Before this script a structure was identified by its Italian name, everywhere:
`BY_ID["struttura"]`, the icons table, `miglioramento_di/a`, and — the part
that matters — the lots saved inside every settlement (`isolati[][].struttura`).
Its effects on Unrest and Ruin were parsed from the Italian description with
regular expressions at runtime.

After it: every structure has an English slug `id`, the effects are data
(`effetti_regno`, dumped once from the old parser so nothing changes), and the
saved lots are migrated by `migrazioni.normalizza` through
`LEGACY_STRUCTURE_NAMES`. The Italian field names stay for now: the rename
pass turns them into English together with the rest of the code.

    python tools/split_data.py
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DATA = ROOT / "kingmaker" / "rules" / "data" / "structures.json"

# Italian name (pf2.altervista.org) -> id from the official English name
# (Kingmaker Adventure Path, Archives of Nethys).
IDS = {
    "Casamenti": "tenement", "Macerie": "rubble", "Bettola": "tavern_dive",
    "Case": "houses", "Cimitero": "cemetery", "Distilleria": "brewery",
    "Emporio": "general_store", "Erbario": "herbalist", "Granaio": "granary",
    "Locanda": "inn", "Mura di Legno": "wooden_wall", "Santuario": "shrine",
    "Biblioteca": "library", "Discarica": "dump", "Mulino": "mill",
    "Municipio": "town_hall", "Orfanotrofio": "orphanage", "Ponte": "bridge",
    "Prigione": "jail", "Attività Commerciale": "trade_shop", "Caserma": "barracks",
    "Conceria": "tannery", "Deposito di Legname": "lumberyard", "Fonderia": "foundry",
    "Fortezza": "keep", "Fucina": "smithy", "Laboratorio Alchemico": "alchemy_laboratory",
    "Molo": "pier", "Monumento": "monument", "Parco": "park",
    "Recinto del Bestiame": "stockyard", "Salone per le Feste": "festival_hall",
    "Stalla": "stable", "Tagliapietre": "stonemason", "Taverna Popolare": "tavern_popular",
    "Torre di Guardia": "watchtower", "Artigiano Specializzato": "specialized_artisan",
    "Mercato": "marketplace", "Strade Lastricate": "paved_streets", "Banca": "bank",
    "Boschetto Sacro": "sacred_grove", "Gilda dei Ladri": "thieves_guild",
    "Guarnigione": "garrison", "Lampioni Magici": "magical_streetlamps",
    "Magione": "mansion", "Mura di Pietra": "stone_wall", "Museo": "museum",
    "Sede della Gilda": "guildhall", "Torre dell'Arcanista": "arcanists_tower",
    "Bottega di Lusso": "luxury_store", "Magazzino Sicuro": "secure_warehouse",
    "Mercato Nero": "illicit_market", "Sistema Fognario": "sewer_system",
    "Tempio": "temple", "Ambasciata": "embassy", "Bottega di Magia": "magic_shop",
    "Zona Portuale": "waterfront", "Arena": "arena", "Castello": "castle",
    "Ospedale": "hospital", "Taverna di Lusso": "tavern_luxury", "Teatro": "theater",
    "Villa Nobiliare": "noble_villa", "Accademia": "academy", "Cantiere": "construction_yard",
    "Tipografia": "printing_house", "Accademia Militare": "military_academy",
    "Serraglio": "menagerie", "Bottega dell'Occulto": "occult_shop",
    "Arena Gladiatoria": "gladiatorial_arena", "Cattedrale": "cathedral",
    "Palazzo": "palace", "Taverna Internazionale": "tavern_world_class",
    "Teatro Lirico": "opera_house", "Università": "university", "Zecca": "mint",
}


def main() -> None:
    from kingmaker import rules  # the old parser, still alive
    structures = json.loads(DATA.read_text(encoding="utf-8"))
    assert len(structures) == 76 and {s["name"] for s in structures} == set(IDS), \
        set(IDS) ^ {s["name"] for s in structures}
    assert len(set(IDS.values())) == 76
    with_effects = 0
    for st in structures:
        effects = rules.structure_effects(st) if "kingdom_effects" not in st else st["kingdom_effects"]
        new = {"id": IDS[st["name"]]}
        for key, value in st.items():
            if key in ("id", "kingdom_effects"):
                continue
            if key in ("upgrade_of", "upgrade_to"):
                value = [IDS.get(n, n) for n in value]
            new[key] = value
        new["kingdom_effects"] = effects
        with_effects += bool(effects)
        st.clear()
        st.update(new)
    DATA.write_text(json.dumps(structures, ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8", newline="\n")
    print(f"structures: 76 ids, {with_effects} with kingdom effects")

    # The legacy map for saved lots.
    mig = ROOT / "kingmaker" / "migrazioni.py"
    text = mig.read_text(encoding="utf-8")
    if "LEGACY_STRUCTURE_NAMES" not in text:
        rows = ["# Le strutture si salvavano col nome italiano dentro i lotti degli",
                 "# insediamenti; oggi hanno un id. La mappa serve a `normalizza`.",
                 "LEGACY_STRUCTURE_NAMES = {"]
        for name, sid in IDS.items():
            rows.append(f"    {json.dumps(name, ensure_ascii=False)}: {json.dumps(sid)},")
        rows.append("}")
        block = "\n".join(rows) + "\n\n\n"
        text = re.sub(r"^(def normalizza\()", block + r"\1", text, count=1, flags=re.M)
        text = text.replace(
            '''    base["ruoli"] = ruoli
    return base
''', '''    base["ruoli"] = ruoli

    # I lotti degli insediamenti: dal nome italiano della struttura al suo id.
    for ins in base.get("insediamenti") or []:
        for griglia in ins.get("griglie") or []:
            for isolato in griglia:
                for lotto in isolato:
                    nome = lotto.get("struttura")
                    if nome in LEGACY_STRUCTURE_NAMES:
                        lotto["struttura"] = LEGACY_STRUCTURE_NAMES[nome]
    return base
''', 1)
        mig.write_text(text, encoding="utf-8", newline="\n")
        print("migrazioni.py: LEGACY_STRUCTURE_NAMES + normalizza")


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# Step 2: the construction options and the traits reference ids, not names.
# «Sapienza Bellica» is how the Italian wiki sometimes spells Warfare; the
# matching by name silently dropped that option (Gladiatorial Arena).
# ---------------------------------------------------------------------------
SKILLS = {
    "Agricoltura": "agriculture", "Arti": "arts", "Commercio": "trade",
    "Difesa": "defense", "Esplorazione": "exploration", "Folklore": "folklore",
    "Governare": "statecraft", "Guerra": "warfare", "Sapienza Bellica": "warfare",
    "Industria": "industry", "Ingegneria": "engineering", "Intrigo": "intrigue",
    "Magia": "magic", "Nautica": "boating", "Politica": "politics",
    "Studio": "scholarship", "Terre Selvagge": "wilderness",
}
PROFICIENCIES = {"Senza Addestramento": "untrained", "Addestrato": "trained",
              "Esperto": "expert", "Maestro": "master", "Leggendario": "legendary"}
TRATTI = {"Costruzione": "edifice", "Edificio": "building", "Famoso": "famous",
          "Infame": "infamous", "Infrastruttura": "infrastructure", "Piazzale": "yard",
          "Residenziale": "residential"}


def step2() -> None:
    structures = json.loads(DATA.read_text(encoding="utf-8"))
    for st in structures:
        st["stretches"] = [TRATTI.get(t, t) for t in st["stretches"]]
        for opt in (st["construction"] or {}).get("options", []):
            opt["skills"] = SKILLS.get(opt["skills"], opt["skills"])
            opt["proficiency"] = PROFICIENCIES.get(opt["proficiency"], opt["proficiency"])
    DATA.write_text(json.dumps(structures, ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8", newline="\n")
    kingdom = ROOT / "kingmaker" / "rules" / "data" / "kingdom.json"
    k = json.loads(kingdom.read_text(encoding="utf-8"))
    if "structure_traits" not in k:
        k["structure_traits"] = [{"id": sid, "name": name} for name, sid in TRATTI.items()]
        kingdom.write_text(json.dumps(k, ensure_ascii=False, indent=1) + "\n",
                           encoding="utf-8", newline="\n")
    print("structures: skills, proficiencies and traits by id")


if __name__ == "__main__":
    step2()
