# -*- coding: utf-8 -*-
"""A save written before 1.0.0 (schema 26, Italian names everywhere) opens
as it is, is copied aside first, and comes out in English."""
import json
import os
import shutil
import sqlite3
import tempfile

from kingmaker import __version__
from kingmaker.storage import legacy_names, migrations
from kingmaker.storage.archive import Archive, SCHEMA_VERSION
from kingmaker.state import State

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(HERE, "fixtures", "v26.db")
results = []

folder = tempfile.mkdtemp(prefix="km-v26-")
db = os.path.join(folder, "kingmaker.db")
shutil.copy(FIXTURE, db)


def tables(path):
    c = sqlite3.connect(path)
    names = sorted(r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")
                   if r[0] != "sqlite_sequence")
    counts = {t: c.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in names}
    c.close()
    return names, counts


before, counts_before = tables(db)
results.append(("the fixture is the old world", "esagoni" in before and "regni" in before))

A = Archive(db)
after, counts_after = tables(db)
results.append(("a copy is taken before touching anything",
                os.path.exists(db + ".pre-v27.bak")))
results.append(("the copy still speaks Italian", "esagoni" in tables(db + ".pre-v27.bak")[0]))
results.append(("the tables are in English and nothing else was created",
                set(after) == set(migrations.RENAMED_TABLES.values()) - {"crossings_to_translate"}
                | {"meta"}))
renamed = {migrations.RENAMED_TABLES.get(t, t): n for t, n in counts_before.items()}
# The one row added on the way: `meta.app_history`, the version that opened it.
renamed["meta"] += 1
results.append(("every row survived", all(counts_after.get(t) == n for t, n in renamed.items())))
results.append(("the version that converted it is written down",
                [h["app"] for h in A.app_history()] == [__version__]
                and A.app_history()[0]["schema"] == 26))
c = A._conn
results.append(("the schema version is the new one",
                c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
                == str(SCHEMA_VERSION)))
cols = {r[1] for r in c.execute("PRAGMA table_info(hexes)")}
results.append(("the hex columns are English", {"status", "terrains", "row", "campaign_id"} <= cols
                and not ({"stato", "riga"} & cols)))
statuses = {r[0] for r in c.execute("SELECT DISTINCT status FROM hexes")}
results.append(("hex statuses are ids from the rules",
                statuses <= set(legacy_names.HEX_STATUS.values())))
results.append(("user roles too",
                {r[0] for r in c.execute("SELECT DISTINCT role FROM users")} <= {"admin", "gm", "player", "spectator"}))
doc = json.loads(c.execute("SELECT document FROM kingdoms").fetchone()[0])


def keys_of(o, acc):
    if isinstance(o, dict):
        for k, v in o.items():
            acc.add(k)
            keys_of(v, acc)
    elif isinstance(o, list):
        for v in o:
            keys_of(v, acc)
    return acc


italian = keys_of(doc, set()) & set(legacy_names.DOCUMENT_KEYS)
results.append(("no Italian key is left in the document", not italian))
results.append(("the Magister is not mistaken for the Master proficiency",
                "magister" in doc["roles"] and "master" not in doc["roles"]))
results.append(("proficiencies are keyed by skill id with English ranks",
                set(doc["proficiencies"]) <= set(legacy_names.SKILL_IDS.values())
                and set(doc["proficiencies"].values()) <= set(legacy_names.PROFICIENCY_IDS.values())))
results.append(("the phase is an English id", doc["current_phase"] == "upkeep"))
lots = [lot["structure"] for s in doc["settlements"] for g in s["grids"] for b in g for lot in b
        if lot.get("structure")]
results.append(("settlement lots hold structure ids", all(x.isascii() and x == x.lower() for x in lots)))

S = State(A)
results.append(("and the kingdom loads", len(S.k["hexes"]) == counts_after["hexes"]
                and len(S.characters()) == counts_after["characters"]))

# Opening it again is a no-op.
A2 = Archive(db)
results.append(("opening it twice changes nothing", tables(db) == (after, counts_after)))

# A legacy JSON save goes through the same translation on import.
legacy = {"nome": "Regno", "malcontento": 3, "esagoni": {"1,1": {"stato": "rivendicato",
          "terreni": ["collina"], "elementi": [{"tipo": "rifugio", "nome": "x"}]}},
          "ruoli": {"maestro": {"nome": "Jhod"}}, "competenze": {"guerra": "maestro"},
          "fase_corrente": "commercio"}
translated = migrations.translate_document(legacy)
results.append(("a legacy JSON document translates too",
                translated["unrest"] == 3 and translated["hexes"]["1,1"]["status"] == "claimed"
                and translated["hexes"]["1,1"]["terrains"] == ["hills"]
                and translated["hexes"]["1,1"]["features"][0]["kind"] == "refuge"
                and translated["roles"]["magister"]["name"] == "Jhod"
                and translated["proficiencies"] == {"warfare": "master"}
                and translated["current_phase"] == "commerce"))

for name, ok in results:
    print(f" {'ok' if ok else 'NO'}  {name}")
print(f"\n{sum(1 for _n, e in results if e)}/{len(results)} passate")
