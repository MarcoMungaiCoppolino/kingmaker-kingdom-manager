# -*- coding: utf-8 -*-
"""Every save format the app has written still opens, and a save from a
newer version is refused without being touched.

`tests/fixtures/` keeps one real save per schema the app has shipped:
`v26.db` (before 1.0.0, Italian names) and `v29.db` (1.1.0 to 1.2.0, built
from the test scene). When the schema goes up, the save of the outgoing
format goes in there too, `v<number>.db`, and this file opens it with no
change of its own: that is the promise that an old game is never left behind.
"""
import glob
import hashlib
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
sys.path.insert(0, BASE)

from kingmaker import __version__  # noqa: E402
from kingmaker.cli import NEWER_SAVE_EXIT  # noqa: E402
from kingmaker.storage import bundle  # noqa: E402
from kingmaker.storage.archive import Archive, NewerSaveError, SCHEMA_VERSION  # noqa: E402
from kingmaker.state import State, new_kingdom  # noqa: E402

results = []
folder = Path(tempfile.mkdtemp(prefix="km-formats-"))
fixtures = sorted(glob.glob(os.path.join(HERE, "fixtures", "v*.db")),
                  key=lambda p: int(re.search(r"v(\d+)\.db$", p).group(1)))


def schema(path) -> int:
    return Archive._schema_of(sqlite3.connect(path))


def digest(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


results.append(("there is a sample of today's format",
                any(f.endswith(f"v{SCHEMA_VERSION}.db") for f in fixtures)))

# --------------------------------------------------- every old format opens
for fixture in fixtures:
    name = os.path.basename(fixture)
    number = int(re.search(r"v(\d+)\.db$", name).group(1))
    db = folder / name
    shutil.copy(fixture, db)
    results.append((f"{name}: the file says schema {number}", schema(db) == number))
    info = bundle.inspect(db)
    results.append((f"{name}: Load a save looks at it without refusing",
                    info["version"] == number and info["kind"] == "db"))
    state = State(Archive(db))
    results.append((f"{name}: it opens at today's schema", schema(db) == SCHEMA_VERSION))
    results.append((f"{name}: the kingdom is there with every key of today",
                    bool(state.k.get("name")) and all(k in state.k for k in new_kingdom())))
    history = state.archive.app_history()
    results.append((f"{name}: this version is written down, with the schema it found",
                    bool(history) and history[-1]["app"] == __version__
                    and history[-1]["schema"] == number))
    state.save()
    state.archive.close()
    again = Archive(db)
    results.append((f"{name}: opening it again adds no second line for the same version",
                    again.app_history() == history))
    again.close()

# ------------------------------------------------------ a new file is born
fresh = Archive(folder / "fresh.db")
born = fresh.app_history()
results.append(("a new save records the version that created it",
                len(born) == 1 and born[0]["app"] == __version__ and born[0]["schema"] == 0))
fresh.close()

# ------------------------------------------- one version after another
older = folder / "older.db"
shutil.copy(os.path.join(HERE, "fixtures", f"v{SCHEMA_VERSION}.db"), older)
c = sqlite3.connect(older)
c.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('app_history', "
          "'[{\"app\":\"1.2.1-old\",\"schema\":29,\"at\":\"2026-10-01\"}]')")
c.commit()
c.close()
chain = Archive(older)
history = chain.app_history()
results.append(("a later version adds itself after the earlier ones",
                [h["app"] for h in history] == ["1.2.1-old", __version__]))
chain.close()

# ------------------------------------------- a save from a newer version
newer = folder / "newer.db"
shutil.copy(os.path.join(HERE, "fixtures", f"v{SCHEMA_VERSION}.db"), newer)
c = sqlite3.connect(newer)
c.execute("UPDATE meta SET value=? WHERE key='schema_version'", (str(SCHEMA_VERSION + 1),))
c.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('app_history', "
          "'[{\"app\":\"9.9.9\",\"schema\":0,\"at\":\"2030-01-01\"}]')")
c.commit()
c.close()
before = digest(newer)
try:
    Archive(newer)
    refused = None
except NewerSaveError as error:
    refused = error
results.append(("opening it is refused", refused is not None))
results.append(("the refusal says both numbers and who wrote it",
                refused is not None and refused.version == SCHEMA_VERSION + 1
                and refused.mine == SCHEMA_VERSION and refused.app == "9.9.9"))
results.append(("the file is left exactly as it was",
                digest(newer) == before and schema(newer) == SCHEMA_VERSION + 1
                and not os.path.exists(str(newer) + "-wal")))
try:
    bundle.inspect(newer)
    said = None
except ValueError as error:
    said = error.args
results.append(("Load a save refuses it too, with its reason",
                said is not None and said[0] == "main.newer_schema"
                and said[1]["app"] == "9.9.9"))

# The server started on it stops at once and says why, in words.
data = folder / "server"
data.mkdir()
shutil.copy(newer, data / "kingmaker.db")
env = dict(os.environ, PYTHONPATH=BASE, PYTHONIOENCODING="utf-8", KINGMAKER_LANG="en",
           KINGMAKER_DATA_DIR=str(data), KINGMAKER_ASSETS_DIR=str(folder / "assets"))
try:
    run = subprocess.run([sys.executable, "-c", "from kingmaker.cli import main; "
                          "main(['--serve', '--no-browser', '--port', '8099'])"],
                         cwd=BASE, env=env, capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=90)
    code, out = run.returncode, run.stdout + run.stderr
except subprocess.TimeoutExpired:
    code, out = None, "the server started instead of refusing"
results.append(("the server refuses to start, with its own exit code",
                code == NEWER_SAVE_EXIT))
results.append(("and says it in a sentence, not a traceback",
                "newer version of Kingmaker Kingdom Manager" in out and "9.9.9" in out
                and "Traceback" not in out))
results.append(("the server left the file alone too", digest(data / "kingmaker.db") == before))

shutil.rmtree(folder, ignore_errors=True)
for name, ok in results:
    print(f" {'ok' if ok else 'NO'}  {name}")
print(f"\n{sum(1 for _n, e in results if e)}/{len(results)} passed")
