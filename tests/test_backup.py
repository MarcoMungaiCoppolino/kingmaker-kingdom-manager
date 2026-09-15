# -*- coding: utf-8 -*-
"""The save file as a backup: downloaded whole, looked at, restored.

Runs on the test scene like the rest of the suite: the copies are written in
a temporary folder and the scene itself is restored at the end, so the next
file finds it as `stage` left it.
"""
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from kingmaker.storage import archive as archive_mod  # noqa: E402
from kingmaker.locale import units, i18n
from kingmaker.state import STATE  # noqa: E402

A, C = STATE.archive, STATE.campaign
results = []
folder = Path(tempfile.mkdtemp(prefix="km-backup-"))


def counts() -> dict:
    return {
        "hexes": len(STATE.k["hexes"]),
        "users": len(A.list_users()),
        "characters": len(STATE.characters()),
        "stable": len(A.list_stable(C)),
        "borders": len(A.campaign_borders(C)),
        "banks": len(A.campaign_banks(C)),
        "lakes": len(A.campaign_lakes(C)),
        "name": STATE.k.get("name"),
    }


before = counts()

# 1. a backup is a complete, consistent SQLite file
copy = A.backup_to(folder / "kingmaker-copy.db")
results.append(("the backup file exists", copy.exists() and copy.stat().st_size > 0))
with sqlite3.connect(copy) as probe:
    tables = {r[0] for r in probe.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    hexes_in_copy = probe.execute("SELECT COUNT(*) FROM hexes").fetchone()[0]
results.append(("the copy holds the game tables", {"meta", "campaigns", "hexes", "users"} <= tables))
results.append(("the copy holds every hex", hexes_in_copy == before["hexes"]))

# 2. inspect says what the file is, and refuses what it is not
info = archive_mod.Archive.inspect(copy)
results.append(("inspect reads the schema version", info["version"] == archive_mod.SCHEMA_VERSION))
results.append(("inspect counts the accounts", info["users"] == before["users"]))
results.append(("inspect reads the kingdom name", info["kingdom"] == before["name"]))

text_file = folder / "not-a-save.db"
text_file.write_text("hello", encoding="utf-8")
try:
    archive_mod.Archive.inspect(text_file)
    refused = None
except ValueError as exc:
    refused = exc.args[0]
results.append(("a text file is refused as not SQLite", refused == "main.not_sqlite"))

empty_db = folder / "empty.db"
with sqlite3.connect(empty_db) as probe:
    probe.execute("CREATE TABLE something (x INTEGER)")
try:
    archive_mod.Archive.inspect(empty_db)
    refused = None
except ValueError as exc:
    refused = exc.args[0]
results.append(("a database without the game tables is refused", refused == "main.missing_tables"))

newer = folder / "newer.db"
shutil.copy2(copy, newer)
with sqlite3.connect(newer) as probe:
    probe.execute("UPDATE meta SET value=? WHERE key='schema_version'",
                  (str(archive_mod.SCHEMA_VERSION + 5),))
try:
    archive_mod.Archive.inspect(newer)
    refused = None
except ValueError as exc:
    refused = exc.args[0]
results.append(("a newer schema is refused", refused == "main.newer_schema"))

# 3. restoring the copy after a change brings everything back
STATE.k["name"] = "Changed Kingdom"
STATE.save()
A.write(C, STATE.k)
rev_before = A.rev
kept = STATE.restore(copy)
after = counts()
results.append(("the previous save is kept next to the file", kept.exists() and kept.name.startswith("kingmaker.db.before-restore-")))
results.append(("the name is back to the backup's", after["name"] == before["name"]))
results.append(("the counts are unchanged after the restore", {k: v for k, v in after.items() if k != "name"} == {k: v for k, v in before.items() if k != "name"}))
results.append(("the revision rose, so the windows re-read", A.rev > rev_before))
results.append(("the archive still answers after the swap", A.count_users() == before["users"]))
kept.unlink(missing_ok=True)

# 4. units: stored in metres, shown in the window's unit
units.units_resolver = lambda: "ft"
results.append(("9 m are shown as 30 ft", units.to_shown(9) == 30 and units.fmt(9) == "30 ft"))
results.append(("30 ft typed become 9 m", abs(units.from_shown(30) - 9) < 1e-9))
results.append(("a step is 5 ft", units.step() == 5))
units.units_resolver = lambda: "m"
results.append(("9 m stay 9 m", units.fmt(9) == "9 m" and units.step() == 1.5))
units.units_resolver = lambda: None
i18n.language_resolver = lambda: "en"
results.append(("without a choice English means feet", units.current() == "ft"))
i18n.language_resolver = lambda: "it"
results.append(("without a choice Italian means metres", units.current() == "m"))

shutil.rmtree(folder, ignore_errors=True)
for name, ok in results:
    print(f" {'ok' if ok else 'NO'}  {name}")
print(f"{sum(1 for _n, ok in results if ok)}/{len(results)} passed")
