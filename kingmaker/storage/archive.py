"""Saving the game to SQLite.

The only point of the program that touches the database: everything else
keeps working on the in-memory dictionary of `state.State`.

Why no longer a single JSON file:

* rewriting thirty-two kilobytes at every change, twice a second, is wasted
  work — here only the rows that really changed are rewritten;
* two processes on the same file overwrote each other, while SQLite in WAL
  mode can handle several writers;
* the features that came later (who sees which hex, where the characters
  are) need to query single hexes, not re-read everything.

The kingdom sheet however remains a JSON document in one column. Splitting all
forty-three keys into tables would serve none of the planned features, and
would force half the interface to be rewritten. Hexes instead are a real
table, because those really are queried one by one.
"""
from __future__ import annotations

import json
import logging
import shutil
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from kingmaker import __version__
from kingmaker.storage import migrations
from kingmaker.geometry import waterways, hexgrid, sections as sections_mod

log = logging.getLogger(__name__)

# The number of the file's *format*. It changes only when the tables or the
# way rows are written change, never at a release that leaves them alone:
# 1.1.0 to 1.2.0 all write schema 29. Each step up has its migration, run in
# order on an older file (see `_open`); a file with a higher number than this
# is refused (`NewerSaveError`).
SCHEMA_VERSION = 29


class NewerSaveError(RuntimeError):
    """The save comes from a newer version of the app: its schema number is
    higher than the one this app knows.

    Opening it anyway would stamp it with the older number and write rows the
    newer version lays out differently, so it is refused before anything is
    written. `version` is the file's schema, `mine` this app's, `app` the
    newest app version that recorded itself in the file ("" if none did)."""

    def __init__(self, path: Path, version: int, mine: int, app: str = "") -> None:
        super().__init__(f"{path}: schema {version} is newer than this app's {mine}")
        self.path, self.version, self.mine, self.app = Path(path), version, mine, app

# Hex columns kept separate because one filters or searches on them. The rest
# of the row goes into `extra`, so a new key is not lost.
HEX_COLUMNS = (
    "status", "terrains", "features", "roads", "fortified",
    "farmland", "work_site", "settlement", "name", "note",
)
# Which of those columns are lists or objects, and must therefore be serialised.
JSON_COLUMNS = {"terrains", "features", "work_site"}
BOOL_COLUMNS = {"roads", "fortified", "farmland"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS campaigns (
    id        TEXT PRIMARY KEY,
    name      TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kingdoms (
    campaign_id   TEXT PRIMARY KEY REFERENCES campaigns(id) ON DELETE CASCADE,
    document     TEXT NOT NULL,
    rev           INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS hexes (
    campaign_id      TEXT    NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    col              INTEGER NOT NULL,
    row             INTEGER NOT NULL,
    status            TEXT    NOT NULL DEFAULT 'unknown',
    terrains          TEXT    NOT NULL DEFAULT '[]',
    features         TEXT    NOT NULL DEFAULT '[]',
    roads           INTEGER NOT NULL DEFAULT 0,
    fortified      INTEGER NOT NULL DEFAULT 0,
    farmland INTEGER NOT NULL DEFAULT 0,
    work_site      TEXT,
    settlement     TEXT,
    name             TEXT    NOT NULL DEFAULT '',
    note             TEXT    NOT NULL DEFAULT '',
    extra            TEXT    NOT NULL DEFAULT '{}',
    PRIMARY KEY (campaign_id, col, row)
);

CREATE INDEX IF NOT EXISTS idx_hexes_status ON hexes(campaign_id, status);

-- What only the GM knows. It is never read on behalf of a player.
CREATE TABLE IF NOT EXISTS hexes_gm (
    campaign_id       TEXT    NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    col               INTEGER NOT NULL,
    row              INTEGER NOT NULL,
    gm_notes           TEXT    NOT NULL DEFAULT '',
    hidden_features TEXT    NOT NULL DEFAULT '[]',
    gm_difficulty     TEXT,
    -- Roads, fortification, farmland and work site are not «features»: they
    -- are fields of the hex. Here we list those the GM keeps to themselves
    -- until the party finds them.
    hidden_fields    TEXT    NOT NULL DEFAULT '[]',
    PRIMARY KEY (campaign_id, col, row)
);

-- Who has already seen which hex. `recipient` is '*' for the whole party,
-- otherwise a user id: so something can be revealed to a single person.
-- An asterisk instead of NULL because in SQLite two NULLs are not
-- considered equal, and the primary key would let duplicate rows through.
CREATE TABLE IF NOT EXISTS visibility (
    campaign_id  TEXT    NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    col          INTEGER NOT NULL,
    row         INTEGER NOT NULL,
    recipient TEXT    NOT NULL DEFAULT '*',
    revealed_at  TEXT    NOT NULL,
    PRIMARY KEY (campaign_id, col, row, recipient)
);

CREATE INDEX IF NOT EXISTS idx_visibility_recipient
    ON visibility(campaign_id, recipient);

CREATE TABLE IF NOT EXISTS characters (
    pos_y REAL,
    pos_x REAL,
    swim_speed_m REAL NOT NULL DEFAULT 0,
    id               TEXT    PRIMARY KEY,
    campaign_id      TEXT    NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    user_id        TEXT    REFERENCES users(id) ON DELETE SET NULL,
    name             TEXT    NOT NULL,
    speed_m       REAL    NOT NULL DEFAULT 7.5,
    con_mod INTEGER NOT NULL DEFAULT 0,
    color           TEXT    NOT NULL DEFAULT '#d7b263',
    hex_col          INTEGER,
    hex_row         INTEGER,
    active           INTEGER NOT NULL DEFAULT 1,
    created_at        TEXT    NOT NULL,
    -- Portrait and token: the file names inside `assets/characters`, not the
    -- paths, so moving the data folder does not break the images.
    portrait         TEXT,
    token            TEXT,
    -- Extra metres from feats or items, kept apart from the base Speed: so
    -- one sees where the total comes from.
    speed_bonus_m REAL    NOT NULL DEFAULT 0,
    note             TEXT    NOT NULL DEFAULT '',
    -- The stable vehicle they are travelling on, if they use one.
    stable_id        TEXT,
    -- Which bank of the hex they are on. It matters only where a river cuts
    -- it in two: there, knowing «which hex you are in» is not enough to know
    -- where you can leave from. Zero everywhere else, which is the normal case.
    bank             INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_characters_campaign ON characters(campaign_id, active);

CREATE TABLE IF NOT EXISTS users (
    id               TEXT    PRIMARY KEY,
    username      TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    pw_hash          TEXT    NOT NULL,
    salt             TEXT    NOT NULL,
    iterations       INTEGER NOT NULL,
    role            TEXT    NOT NULL DEFAULT 'player',
    active           INTEGER NOT NULL DEFAULT 1,
    must_change_pw INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT    NOT NULL,
    last_login   TEXT,
    -- The interface language this person chose ('en', 'it'); NULL until they
    -- choose, and then the browser's language is used.
    language          TEXT,
    -- Metres or feet for the Speeds shown ('m', 'ft'); NULL follows the language.
    units             TEXT,
    -- May this person's launcher host the game (GM role only; administrators
    -- always can): the trust decision behind the cloud sync (schema 29).
    can_host          INTEGER NOT NULL DEFAULT 0
);

-- The kingdom's stable: the vehicles the party really owns. `vehicle` is the
-- id in the rules catalogue; the rest belongs to this specimen (the name
-- they gave it, whether it is available, the Speed when the rules do not
-- give it in metres because it depends on what tows it, and how many
-- people fit on it when the rules describe the crew in words instead of a
-- number).
CREATE TABLE IF NOT EXISTS stable (
    pos_y REAL,
    pos_x REAL,
    bank INTEGER NOT NULL DEFAULT 0,
    hex_row INTEGER,
    hex_col INTEGER,
    id           TEXT    PRIMARY KEY,
    campaign_id  TEXT    NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    vehicle      TEXT    NOT NULL,
    name         TEXT    NOT NULL DEFAULT '',
    available  INTEGER NOT NULL DEFAULT 1,
    speed_m   REAL,
    seats        INTEGER,
    portrait     TEXT,
    token        TEXT,
    -- A water vehicle crosses Water Borders and lake hexes; a land one does
    -- not. It is the only difference between the two.
    kind         TEXT    NOT NULL DEFAULT 'land',
    note         TEXT    NOT NULL DEFAULT '',
    created_at    TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_stable_campaign ON stable(campaign_id);

-- A planned journey. It is born as a proposal and stays there until somebody
-- resolves it: it is the same rule as the turn's activities, proposed and
-- confirmed, never applied on the sly.
CREATE TABLE IF NOT EXISTS journeys (
    pos_y REAL,
    pos_x REAL,
    id             TEXT    PRIMARY KEY,
    campaign_id    TEXT    NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    characters     TEXT    NOT NULL DEFAULT '[]',
    stable_id      TEXT,
    departure       TEXT    NOT NULL,
    arrival         TEXT    NOT NULL,
    path       TEXT    NOT NULL DEFAULT '[]',
    activity_cost INTEGER NOT NULL DEFAULT 0,
    days         INTEGER NOT NULL DEFAULT 0,
    forced_march INTEGER NOT NULL DEFAULT 0,
    -- The plan freezes at departure: the cost of every waypoint and the
    -- activities per day stay those of that moment, so a journey already
    -- begun does not change underfoot if the GM retouches the terrain halfway.
    costs          TEXT    NOT NULL DEFAULT '[]',
    activities_per_day REAL   NOT NULL DEFAULT 1,
    progress      REAL    NOT NULL DEFAULT 0,
    departure_day INTEGER,
    -- A journey is made of legs. Usually a single one, with everybody in it;
    -- but if the party leaves scattered there are the approach legs (one per
    -- mover, at their Speed) and then the common one, which waits for all to
    -- arrive and goes at the slowest one's pace.
    legs         TEXT    NOT NULL DEFAULT '[]',
    status          TEXT    NOT NULL DEFAULT 'in_progress',
    turn_created   INTEGER NOT NULL DEFAULT 0,
    turn_resolved  INTEGER,
    created_by      TEXT,
    created_at      TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_journeys_status ON journeys(campaign_id, status);

-- The game log: it used to live inside the kingdom document, and four
-- hundred rows were rewritten at every save for a moved cursor.
CREATE TABLE IF NOT EXISTS log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id TEXT    NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    logged_at      TEXT    NOT NULL,
    turn       INTEGER NOT NULL DEFAULT 0,
    category   TEXT    NOT NULL DEFAULT 'info',
    text       TEXT    NOT NULL,
    detail   TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_log_campaign ON log(campaign_id, id);

-- A body of still water: a closed ring of drawn stretches and the hexes
-- inside it. It is not a terrain of the hex but a thing drawn over the grid,
-- like the borders: a lake sits *between* the lines enclosing it, and which
-- hexes it holds is said by the shape, not by a box ticked cell by cell.
--
-- The journey needs it: inside a lake there is no current to follow or go
-- up, so there is no direction and no stretches to follow — one goes where
-- one wants, and the rules say whoever sails finds open terrain. One leaves
-- where the lake touches a river.
CREATE TABLE IF NOT EXISTS lakes (
    campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    id          TEXT NOT NULL,
    name        TEXT NOT NULL DEFAULT '',
    cells       TEXT NOT NULL DEFAULT '[]',   -- JSON: [[col, row], ...]
    points       TEXT NOT NULL DEFAULT '[]',   -- JSON: the drawn loop of vertices
    source       TEXT NOT NULL DEFAULT 'gm',
    PRIMARY KEY (campaign_id, id)
);

-- Which way the water flows in a drawn stretch. The rules make the effort of
-- the journey depend on it — going down a river is open terrain, going up
-- is difficult or greater difficult — and there is no way to derive it from
-- the map: it is one more datum somebody must supply.
--
-- The direction *is* the order of the two ends: `upstream` first,
-- `downstream` then. Whoever passes there compares the direction they are
-- going in with the written one. `stretch` is the name of the piece of
-- river, the same from both directions (see waterways.key_text), so a
-- stretch is a single row. A stretch without a row is not an error: it is a
-- piece nobody has said the direction of yet, and the journey says so
-- instead of making it up.
CREATE TABLE IF NOT EXISTS currents (
    campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    stretch      TEXT NOT NULL,
    upstream       TEXT NOT NULL,
    downstream       TEXT NOT NULL,
    source       TEXT NOT NULL DEFAULT 'gm',
    PRIMARY KEY (campaign_id, stretch)
);

-- A border sits *between* two hexes, not inside one: a river running along
-- the edge belongs to both and to neither. It is the only thing on the map
-- that is not a property of the cell. The pair is ordered (see
-- hexgrid.border_key), so a physical border is a single row and is found
-- from both sides. A land border is not written: it is the absence of a
-- row, and an empty table equals the earlier map.
CREATE TABLE IF NOT EXISTS borders (
    campaign_id TEXT    NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    col_a       INTEGER NOT NULL,
    row_a      INTEGER NOT NULL,
    col_b       INTEGER NOT NULL,
    row_b      INTEGER NOT NULL,
    kind        TEXT    NOT NULL DEFAULT 'water',   -- water | ford | bridge
    -- 'gm' if a person marked it, 'traced' if it comes from reading the map
    -- image: it allows redoing the reading without erasing the hand-made work.
    source       TEXT    NOT NULL DEFAULT 'gm',
    note        TEXT    NOT NULL DEFAULT '',
    PRIMARY KEY (campaign_id, col_a, row_a, col_b, row_b)
);

-- The banks of a hex. A river crossing it does not close it: it *cuts* it,
-- and one enters from every side but does not pass from one bank to the
-- other. Here sit its six sides grouped by bank, as direction indices in
-- the order of hexgrid.neighbours(): [[0,1,5],[2,3,4]] means the river
-- passes between side 5 and side 2.
--
-- Only cut hexes have a row: whoever is missing is dry and has a single
-- bank, which is the case of almost the whole map. Empty table = the
-- earlier map, where a hex was a single node.
CREATE TABLE IF NOT EXISTS banks (
    campaign_id TEXT    NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    col         INTEGER NOT NULL,
    row        INTEGER NOT NULL,
    groups      TEXT    NOT NULL DEFAULT '[]',
    -- The segments drawn by hand inside the hex: pairs of points, where a
    -- point is a grid vertex or the center. The shores derive from here;
    -- `groups` keeps them ready-made because the journey asks for them at
    -- every step and redoing the count every time would be a waste.
    points       TEXT    NOT NULL DEFAULT '[]',
    source       TEXT    NOT NULL DEFAULT 'gm',   -- gm | traced
    PRIMARY KEY (campaign_id, col, row)
);

-- The crossings *inside* a hex: a river crossing it cuts it into two shores,
-- and until now there was no way to pass it there in the middle. A bridge on
-- the side of the hex lives in the `borders` table; this one sits on the
-- cut, and can be a bridge (costs nothing) or a ford (costs as much as
-- crossing that terrain).
--
-- A crossing is not named by shore number — that changes as soon as a second
-- cut divides the hex again — nor by pair of sides, which is how it used to
-- be named. The pair of sides holds as long as every shore touches the edge,
-- and stops holding for a shore enclosed in the middle of the hex: that one
-- has no sides, and a bridge reaching it could not even be written.
--
-- It is named by **where it is**: two points, one per shore, in hex radii
-- counted from the center of the cell. Whoever reads asks which sections
-- those two points fall in now: if they are two different sections and they
-- touch, the bridge joins them. If the GM redraws and the water no longer
-- passes there, that bridge no longer crosses anything and switches itself
-- off — which is exactly what it did before too.
--
-- A single point — the one where you hop over — would have been more
-- elegant, and for a while it was so. But a second river passing right under
-- the bridge brings that point onto a junction, where four sections meet and
-- «which two do you join» stops having an answer. Two points planted
-- **inside** the shores stay far from the junctions and hold.
CREATE TABLE IF NOT EXISTS crossings (
    campaign_id TEXT    NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    id          TEXT    NOT NULL,
    col         INTEGER NOT NULL,
    row        INTEGER NOT NULL,
    a_x         REAL    NOT NULL,   -- the point of the first shore
    a_y         REAL    NOT NULL,
    b_x         REAL    NOT NULL,   -- the point of the second
    b_y         REAL    NOT NULL,
    -- And where it sits, on the water. The shores say *what* it joins; this
    -- says *where*, and serves two things the shores alone cannot do:
    -- drawing it where it was placed, and keeping two crossings on the same
    -- river distinct — a bridge here and a ford further on join the same two
    -- shores, and without this they would be the same crossing.
    at_x     REAL,
    at_y     REAL,
    kind        TEXT    NOT NULL DEFAULT 'bridge',   -- bridge | ford
    difficulty  TEXT,                               -- the GM forces the category
    source       TEXT    NOT NULL DEFAULT 'gm',
    note        TEXT    NOT NULL DEFAULT '',
    PRIMARY KEY (campaign_id, id)
);
"""


def _ensure_legs(journey: dict) -> None:
    """An old journey, from when legs did not exist, has a single one.

    So the reader no longer has to wonder which version the row comes from:
    there are always legs, and the rest of the program knows a single shape.
    """
    if journey.get("legs"):
        return
    journey["legs"] = [{
        "characters": list(journey.get("characters") or []),
        "path": list(journey.get("path") or []),
        "costs": list(journey.get("costs") or []),
        "activities_per_day": float(journey.get("activities_per_day") or 1),
        "progress": float(journey.get("progress") or 0),
        "waiting": False,
    }]


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class Archive:
    """Access to the game database."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Rises at every write: whoever keeps a copy of what they read
        # (sections, water network, view) redoes it only when it changes.
        self.rev = 0
        # NiceGUI runs on a single loop, but the timer that writes to disk
        # starts from a callback of its own: the connection is shared, so a
        # lock protects it and not sqlite3's thread check.
        self._lock = threading.RLock()
        self._open()

    def _open(self) -> None:
        """Opens the file and brings it to today's schema. Called at start and
        again after a restore, when the file under the connection is another."""
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            version_before = self._recorded_version()
            if version_before > SCHEMA_VERSION:
                # Before any write, the journal mode included.
                history = self._read_history(self._conn)
                self._conn.close()
                raise NewerSaveError(self.path, version_before, SCHEMA_VERSION,
                                     history[-1].get("app", "") if history else "")
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            if 0 < version_before < 27:
                migrations.upgrade_storage_v27(self._conn, self.path)
            self._stash_tables()
            self._conn.executescript(SCHEMA)
            self._add_missing_columns(version_before)
            self._set_meta("schema_version", str(SCHEMA_VERSION))
            self._record_app(version_before)
            self._commit()
        # Last written version of every row, to rewrite only what changed.
        self._written_document: str | None = None
        self._written_hexes: dict[str, str] = {}

    # ------------------------------------------------------ backup, restore
    def backup_to(self, path: Path) -> Path:
        """A consistent copy of the whole database, the write-ahead log folded
        in: the file a person keeps as a backup or carries to another PC."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            target = sqlite3.connect(path)
            try:
                self._conn.backup(target)
            finally:
                target.close()
        return path

    # Why a file is refused as a save: catalog keys, shown by the interface.
    INSPECT_ERRORS = {"sqlite": "main.not_sqlite", "tables": "main.missing_tables",
                      "newer": "main.newer_schema"}

    @classmethod
    def inspect(cls, path: Path) -> dict:
        """What a save file holds, before trusting it: raises ValueError with a
        catalog key (and its params) when it is not a save of this app."""
        path = Path(path)
        with open(path, "rb") as f:
            if f.read(16) != b"SQLite format 3\x00":
                raise ValueError(cls.INSPECT_ERRORS["sqlite"], {})
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            conn.row_factory = sqlite3.Row
            tables = {r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            # A save older than 27 still speaks Italian: it is recognised by
            # the old table names and translated by `_open` after the copy.
            needed = ({"meta", "campaigns", "kingdoms", "users"}
                      if "campaigns" in tables else {"meta", "campagne", "regni", "utenti"})
            if not needed <= tables:
                raise ValueError(cls.INSPECT_ERRORS["tables"], {})
            version = cls._schema_of(conn)
            history = cls._read_history(conn)
            app = history[-1].get("app", "") if history else ""
            if version > SCHEMA_VERSION:
                raise ValueError(cls.INSPECT_ERRORS["newer"],
                                 {"version": version, "mine": SCHEMA_VERSION, "app": app})
            users_table = "users" if "users" in tables else "utenti"
            users = conn.execute(f"SELECT COUNT(*) FROM {users_table}").fetchone()[0]
            kingdom = ""
            doc_table, doc_col = (("kingdoms", "document") if "kingdoms" in tables
                                  else ("regni", "documento"))
            try:
                doc = conn.execute(f"SELECT {doc_col} FROM {doc_table} LIMIT 1").fetchone()
                if doc:
                    data = json.loads(doc[0])
                    kingdom = str(data.get("name") or data.get("nome") or "")
            except (sqlite3.Error, ValueError, TypeError):
                kingdom = ""
        finally:
            conn.close()
        return {"version": version, "users": int(users), "kingdom": kingdom, "app": app}

    def restore_from(self, path: Path) -> Path:
        """Replaces the whole database with the given save file.

        The current file is copied next to itself first, with the date in the
        name, so nothing is lost by a wrong click. The connection is closed,
        the file swapped, and `_open` brings the new one to today's schema —
        an old backup is migrated exactly as at a normal start. Returns the
        copy that was kept.
        """
        path = Path(path)
        self.inspect(path)                       # raises if it is not a save
        with self._lock:
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self._conn.close()
            stamp = time.strftime("%Y%m%d-%H%M%S")
            kept = self.path.with_name(f"{self.path.name}.before-restore-{stamp}.bak")
            shutil.copy2(self.path, kept)
            for suffix in ("-wal", "-shm"):
                leftover = Path(str(self.path) + suffix)
                if leftover.exists():
                    leftover.unlink()
            shutil.copy2(path, self.path)
            self._open()
            self.rev += 1
        log.info("save restored from %s; the previous one kept as %s", path.name, kept.name)
        return kept

    # ------------------------------------------------------------- migrations
    # Columns that arrived after the first version of the schema: `CREATE
    # TABLE IF NOT EXISTS` does not touch a table that already exists, so they
    # must be added by hand. Every entry is (version introducing it, table,
    # definition).
    ADDED_COLUMNS = (
        (5, "hexes_gm", "hidden_fields TEXT NOT NULL DEFAULT '[]'"),
        (6, "characters", "portrait TEXT"),
        (6, "characters", "token TEXT"),
        (6, "characters", "speed_bonus_m REAL NOT NULL DEFAULT 0"),
        (6, "characters", "note TEXT NOT NULL DEFAULT ''"),
        (6, "characters", "stable_id TEXT"),
        (7, "journeys", "costs TEXT NOT NULL DEFAULT '[]'"),
        (7, "journeys", "activities_per_day REAL NOT NULL DEFAULT 1"),
        (7, "journeys", "progress REAL NOT NULL DEFAULT 0"),
        (7, "journeys", "departure_day INTEGER"),
        (8, "journeys", "legs TEXT NOT NULL DEFAULT '[]'"),
        (9, "stable", "seats INTEGER"),
        (10, "stable", "portrait TEXT"),
        (10, "stable", "token TEXT"),
        (11, "stable", "kind TEXT NOT NULL DEFAULT 'land'"),
        # 13 and not 12: the `banks` table had already taken 12, and a column
        # labelled with the same version as the one that introduced it would
        # not be applied to a database that already got there.
        (13, "characters", "bank INTEGER NOT NULL DEFAULT 0"),
        # The `crossings` table is born at 14 with sides only; at 15 it becomes
        # the crossing in general, bridge or ford.
        (15, "crossings", "kind TEXT NOT NULL DEFAULT 'bridge'"),
        (15, "crossings", "difficulty TEXT"),
        # The Swim Speed: the rules put it next to the vehicle as a second way
        # of passing water, and until now the app knew only the vehicle. Zero
        # means «does not swim», which is the normal case.
        (16, "characters", "swim_speed_m REAL NOT NULL DEFAULT 0"),
        # The interface language chosen by each person (release 1.0.0).
        (27, "users", "language TEXT"),
        # Metres or feet, chosen by each person (schema 28).
        (28, "users", "units TEXT"),
        # Whose launcher may host the game (schema 29).
        (29, "users", "can_host INTEGER NOT NULL DEFAULT 0"),
        # A boat sits in the water on its own, and whoever boards it reaches
        # it. It is the opposite of a wagon, which sits where whoever tows it
        # is: a boat is not carried on one's shoulders to the river.
        (18, "stable", "hex_col INTEGER"),
        (18, "stable", "hex_row INTEGER"),
        # The shape of the lake as the hand drew it: a ring of vertices.
        # `cells` stays, derived from this, because travel reasons in hexes
        # and recomputing a point-in-polygon at every step would be wasteful.
        (19, "lakes", "points TEXT NOT NULL DEFAULT '[]'"),
        # The drawing of the river inside the hex, and not only the shores
        # that result from it: since one can pass through the center, the same
        # division into shores can be obtained with lines of different shape,
        # and which of the two you drew only the drawing knows.
        (20, "banks", "points TEXT NOT NULL DEFAULT '[]'"),
        # Which shore the vehicle is on, when a river cuts in two the hex that
        # hosts it. Needed to let people off **where it is**: a wagon stopped
        # at a ford is on this or that side of the water, and whoever gets off
        # ends up on the same side, not on the other bank.
        (21, "stable", "bank INTEGER NOT NULL DEFAULT 0"),
        # Where a marker is **inside** its hex, in hex radii counted from the
        # center. It replaces `bank`, which was the shore number: a number
        # counts faces and changes meaning as soon as the GM draws another
        # water line, a point stays where it is. The old column stays written
        # as it was last time, so an earlier version of the program reopens
        # the save without finding a hole.
        (23, "characters", "pos_x REAL"),
        (23, "characters", "pos_y REAL"),
        (23, "stable", "pos_x REAL"),
        (23, "stable", "pos_y REAL"),
        # Where a crossing sits, on the water. The two shores say what it
        # joins; this says where, and without it two crossings on the same
        # river — a bridge here, a ford further on — become the same crossing,
        # because the shores they join are the same.
        (24, "crossings", "at_x REAL"),
        (24, "crossings", "at_y REAL"),
        # Where one arrives **inside** the arrival hex. A journey only knew
        # «at 20,5», and in a hex the water divides that is not a place:
        # whoever arrived stopped on the shore they entered from, even if with
        # the ruler they had aimed at another. A point, as for markers and
        # bridges, because a shore number changes meaning as soon as the GM
        # draws another water line.
        (25, "journeys", "pos_x REAL"),
        (25, "journeys", "pos_y REAL"),
    )

    # Tables that at some version changed **shape**, not only columns: `CREATE
    # TABLE IF NOT EXISTS` does not touch them and `ALTER TABLE` is not
    # enough. They are set aside under the old name and whoever knows how to
    # translate them — that is `migrations`, because the map geometry is
    # needed — fishes them out.
    #
    # The column looked at is one of the **new** ones, and the table is set
    # aside when it is *missing*. Looking at an old column instead seems the
    # same and is worse: if the shape changes twice, the second time the old
    # column has been gone for a while and the rebuild would not trigger,
    # leaving standing a table no query can read.
    REBUILT_TABLES = ((23, "crossings", "a_x", "crossings_to_translate"),)

    def _stash_tables(self) -> None:
        """Renames the tables that changed shape, before recreating them.

        No conversion happens here: to translate a bridge written by sides into
        one written by point one must know how that hex is cut, and that is
        known by the map, which at this point has not been read yet. Here the
        old is only put in a safe place, and `migrations` fishes it out as
        soon as the kingdom is in memory.
        """
        for _version, table, column, stash in self.REBUILT_TABLES:
            try:
                columns = {r["name"] for r in
                           self._conn.execute(f"PRAGMA table_info({table})")}
            except sqlite3.OperationalError:
                continue
            if not columns or column in columns:
                continue        # does not exist yet, or is already as it should be
            self._conn.execute(f"DROP TABLE IF EXISTS {stash}")
            self._conn.execute(f"ALTER TABLE {table} RENAME TO {stash}")
            log.info("table %s stashed as %s", table, stash)

    def stashed_rows(self, stash: str) -> list[dict]:
        """The rows of a table awaiting translation, or nothing if there is none."""
        try:
            with self._lock:
                return [dict(r) for r in
                        self._conn.execute(f"SELECT * FROM {stash}")]
        except sqlite3.OperationalError:
            return []

    def drop_stash(self, stash: str) -> None:
        with self._lock:
            self._conn.execute(f"DROP TABLE IF EXISTS {stash}")
            self._commit()

    def _recorded_version(self) -> int:
        return self._schema_of(self._conn)

    @staticmethod
    def _schema_of(conn: sqlite3.Connection) -> int:
        """The schema number a file says it has; 0 for a new database."""
        for query in ("SELECT value FROM meta WHERE key='schema_version'",
                      # before schema 27 the meta table itself was in Italian
                      "SELECT valore AS value FROM meta WHERE chiave='schema_versione'"):
            try:
                row = conn.execute(query).fetchone()
            except sqlite3.OperationalError:
                continue
            return int(row[0]) if row else 0
        return 0                # not even the meta table exists: new database

    # Which versions of the app have opened this file, oldest first: one entry
    # per version, `{"app", "schema", "at"}`, where `schema` is the number the
    # file had before that version opened it (0: that version created it).
    # The schema number says what the file *is*; this says where it has been —
    # for whoever reads a bug report, for the cloud comparing two hosts, and
    # for a converter that one day has to tell apart two files of one schema.
    # Versions before 1.2.1 kept no list: a file they wrote starts it later.
    APP_HISTORY = "app_history"

    @classmethod
    def _read_history(cls, conn: sqlite3.Connection) -> list[dict]:
        try:
            row = conn.execute("SELECT value FROM meta WHERE key=?", (cls.APP_HISTORY,)).fetchone()
            history = json.loads(row[0]) if row else []
        except (sqlite3.Error, ValueError, TypeError):
            return []                   # an old file, or a list nobody can read
        return [h for h in history if isinstance(h, dict)] if isinstance(history, list) else []

    def _record_app(self, version_before: int) -> None:
        history = self._read_history(self._conn)
        if history and history[-1].get("app") == __version__:
            return
        history.append({"app": __version__, "schema": version_before,
                        "at": time.strftime("%Y-%m-%d")})
        self._set_meta(self.APP_HISTORY, _json(history))

    def app_history(self) -> list[dict]:
        """The versions of the app that have opened this file, oldest first."""
        with self._lock:
            return self._read_history(self._conn)

    def _add_missing_columns(self, version_before: int) -> None:
        """The columns added after the first version of the schema.

        It runs **on new databases too**, and it is no waste: the `CREATE
        TABLE` statements above were not kept up to date with this list, and a
        database created from scratch today found itself without
        `characters.pos_x` — i.e. without the spot inside the hex — and without
        `stable.hex_col`. A new game could not even put a marker on the map,
        while one migrated from an old version worked: the most unpleasant
        defect there is, because only beginners see it.

        Always running costs nothing and can break nothing: every column is
        added only if it is not there yet.
        """
        for from_version, table, definition in self.ADDED_COLUMNS:
            if version_before and version_before >= from_version:
                continue        # that version already saw it
            name = definition.split()[0]
            existing_ones = {r["name"] for r in
                         self._conn.execute(f"PRAGMA table_info({table})")}
            if name not in existing_ones:
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")
                log.info("added column %s.%s", table, name)

    def _commit(self) -> None:
        self._conn.commit()
        self.rev += 1

    # ------------------------------------------------------------------ meta
    def _set_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value))

    def read_meta(self, key: str) -> str | None:
        """A mark the app leaves for itself, or None if there is none.

        Needed by the migrations that do not add columns but **rewrite data**:
        the schema version is not enough to mark them, because it is raised as
        soon as the database opens, before the migration runs.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def write_meta(self, key: str, value: str) -> None:
        with self._lock:
            self._set_meta(key, value)
            self._commit()


    # -------------------------------------------------------------- campaigns
    def document_rev(self, campaign_id: str) -> int:
        """The revision the kingdom document was last written with
        (`STATE.k["_rev"]`, raised at every change), 0 when there is no
        kingdom yet. The cloud compares it with the one recorded at the last
        upload to tell a copy that fell behind from one that was played on."""
        with self._lock:
            row = self._conn.execute(
                "SELECT rev FROM kingdoms WHERE campaign_id=?", (campaign_id,)).fetchone()
        return int(row["rev"] or 0) if row else 0

    def campaign_exists(self, campaign_id: str) -> bool:
        with self._lock:
            return self._conn.execute(
                "SELECT 1 FROM kingdoms WHERE campaign_id=?", (campaign_id,)).fetchone() is not None

    def _ensure_campaign(self, campaign_id: str, name: str = "") -> None:
        self._conn.execute(
            "INSERT INTO campaigns (id, name, created_at) VALUES (?, ?, ?) "
            "ON CONFLICT(id) DO NOTHING",
            (campaign_id, name, time.strftime("%Y-%m-%dT%H:%M:%S")))

    # --------------------------------------------------------------- reading
    def read(self, campaign_id: str) -> dict | None:
        """The complete kingdom, hexes included, or None if the game is not there."""
        with self._lock:
            row = self._conn.execute(
                "SELECT document FROM kingdoms WHERE campaign_id=?", (campaign_id,)).fetchone()
            if row is None:
                return None
            document = json.loads(row["document"])
            hexes = {}
            for e in self._conn.execute(
                    "SELECT * FROM hexes WHERE campaign_id=?", (campaign_id,)):
                key = f'{e["col"]},{e["row"]}'
                hexes[key] = self._row_to_hex(e)

        document["hexes"] = hexes
        # From here on we know what is written on disk: the first save will
        # rewrite only what the user really touched.
        self._remember_written(document, hexes)
        return document

    @staticmethod
    def _row_to_hex(e: sqlite3.Row) -> dict:
        hexagon = {"col": e["col"], "row": e["row"]}
        for column in HEX_COLUMNS:
            value = e[column]
            if column in JSON_COLUMNS:
                hexagon[column] = json.loads(value) if value else (
                    None if column == "work_site" else [])
            elif column in BOOL_COLUMNS:
                hexagon[column] = bool(value)
            else:
                hexagon[column] = value
        hexagon.update(json.loads(e["extra"] or "{}"))
        return hexagon

    # -------------------------------------------------------------- writing
    def write(self, campaign_id: str, k: dict) -> None:
        """Saves the kingdom rewriting only what changed."""
        hexes = k.get("hexes") or {}
        document = {c: v for c, v in k.items() if c != "hexes"}
        document_text = _json(document)

        # We serialise before taking the lock: it is the slow part.
        new_items = {key: _json(datum) for key, datum in hexes.items()}
        changed_ones = [c for c, t in new_items.items() if self._written_hexes.get(c) != t]
        removed = [c for c in self._written_hexes if c not in new_items]
        document_changed = document_text != self._written_document

        if not (document_changed or changed_ones or removed):
            return

        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        with self._lock:
            self._ensure_campaign(campaign_id, str(k.get("name") or ""))
            if document_changed:
                self._conn.execute(
                    "INSERT INTO kingdoms (campaign_id, document, rev, updated_at) "
                    "VALUES (?, ?, ?, ?) ON CONFLICT(campaign_id) DO UPDATE SET "
                    "document=excluded.document, rev=excluded.rev, "
                    "updated_at=excluded.updated_at",
                    (campaign_id, document_text, int(k.get("_rev", 0)), now))
            for key in changed_ones:
                self._write_hex(campaign_id, hexes[key])
            for key in removed:
                col, row = key.split(",")
                self._conn.execute(
                    "DELETE FROM hexes WHERE campaign_id=? AND col=? AND row=?",
                    (campaign_id, int(col), int(row)))
            self._commit()

        self._written_document = document_text
        self._written_hexes = new_items

    def _write_hex(self, campaign_id: str, hexagon: dict) -> None:
        values = [campaign_id, int(hexagon["col"]), int(hexagon["row"])]
        for column in HEX_COLUMNS:
            value = hexagon.get(column)
            if column in JSON_COLUMNS:
                values.append(_json(value) if value is not None else None)
            elif column in BOOL_COLUMNS:
                values.append(1 if value else 0)
            else:
                values.append("" if value is None and column in ("name", "note") else value)
        known_ones = set(HEX_COLUMNS) | {"col", "row"}
        values.append(_json({c: v for c, v in hexagon.items() if c not in known_ones}))

        fields = ("campaign_id", "col", "row", *HEX_COLUMNS, "extra")
        placeholder = ", ".join("?" * len(fields))
        refresh = ", ".join(f"{c}=excluded.{c}" for c in (*HEX_COLUMNS, "extra"))
        self._conn.execute(
            f"INSERT INTO hexes ({', '.join(fields)}) VALUES ({placeholder}) "
            f"ON CONFLICT(campaign_id, col, row) DO UPDATE SET {refresh}",
            values)

    # The tables that belong to a campaign: resetting it means emptying them
    # all. Accounts stay: they belong to people, not to the game.
    CAMPAIGN_TABLES = ("hexes", "kingdoms", "hexes_gm", "visibility", "characters",
                        "stable", "journeys", "lakes", "currents", "borders", "banks",
                        "crossings", "log")

    def reset(self, campaign_id: str) -> None:
        """Deletes the game — kingdom, map, water, characters, vehicles, journeys,
        fog — and starts over. It used to remove only kingdom and hexes, and
        the new game was born with the characters and rivers of the old one."""
        with self._lock:
            for table in self.CAMPAIGN_TABLES:
                self._conn.execute(f"DELETE FROM {table} WHERE campaign_id=?",
                                   (campaign_id,))
            self._commit()
        self._written_document = None
        self._written_hexes = {}

    # -------------------------------------------------------------- journal
    def record(self, campaign_id: str, entry: dict) -> None:
        with self._lock:
            self._ensure_campaign(campaign_id)
            self._conn.execute(
                "INSERT INTO log (campaign_id, logged_at, turn, category, text, detail) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (campaign_id, str(entry.get("logged_at") or ""), int(entry.get("turn") or 0),
                 str(entry.get("category") or "info"), str(entry.get("text") or ""),
                 str(entry.get("detail") or "")))
            self._commit()

    def journal(self, campaign_id: str, how_many: int = 80) -> list[dict]:
        """The latest rows, newest first."""
        rows = self._conn.execute(
            "SELECT logged_at, turn, category, text, detail FROM log "
            "WHERE campaign_id=? ORDER BY id DESC LIMIT ?", (campaign_id, int(how_many)))
        return [dict(r) for r in rows]

    # ---------------------------------------------------------------- users
    def count_users(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    def count_active_admins(self, excluded_one: str | None = None) -> int:
        """How many active administrators remain, not counting `excluded_one`."""
        with self._lock:
            return self._conn.execute(
                "SELECT COUNT(*) FROM users WHERE role='admin' AND active=1 "
                "AND id != ?", (excluded_one or "",)).fetchone()[0]

    def user_by_name(self, username: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM users WHERE username = ?", (username.strip(),)).fetchone()
        return dict(row) if row else None

    def user_by_id(self, user_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None

    def list_users(self) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(
                "SELECT * FROM users ORDER BY username")]

    def create_user(self, data: dict) -> None:
        fields = ("id", "username", "pw_hash", "salt", "iterations", "role",
                 "active", "must_change_pw", "created_at")
        with self._lock:
            self._conn.execute(
                f"INSERT INTO users ({', '.join(fields)}) "
                f"VALUES ({', '.join('?' * len(fields))})",
                [data[c] for c in fields])
            self._commit()

    def update_user(self, user_id: str, **fields) -> None:
        if not fields:
            return
        allowed = {"username", "pw_hash", "salt", "iterations", "role",
                   "active", "must_change_pw", "last_login", "language", "units", "can_host"}
        unknowns = set(fields) - allowed
        if unknowns:
            raise ValueError(f"fields that cannot be modified: {sorted(unknowns)}")
        assignments = ", ".join(f"{c} = ?" for c in fields)
        with self._lock:
            self._conn.execute(f"UPDATE users SET {assignments} WHERE id = ?",
                               [*fields.values(), user_id])
            self._commit()

    def delete_user(self, user_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
            self._commit()

    # ------------------------------------------------------- GM secrets
    def gm_data(self, campaign_id: str, col: int, row: int) -> dict:
        with self._lock:
            r = self._conn.execute(
                "SELECT * FROM hexes_gm WHERE campaign_id=? AND col=? AND row=?",
                (campaign_id, col, row)).fetchone()
        if r is None:
            return {"gm_notes": "", "hidden_features": [], "gm_difficulty": None,
                    "hidden_fields": []}
        return {"gm_notes": r["gm_notes"],
                "hidden_features": json.loads(r["hidden_features"] or "[]"),
                "gm_difficulty": r["gm_difficulty"],
                "hidden_fields": json.loads(r["hidden_fields"] or "[]")}

    def write_gm_data(self, campaign_id: str, col: int, row: int, **fields) -> None:
        allowed = {"gm_notes", "hidden_features", "gm_difficulty", "hidden_fields"}
        unknowns = set(fields) - allowed
        if unknowns:
            raise ValueError(f"fields that cannot be modified: {sorted(unknowns)}")
        current_ones = self.gm_data(campaign_id, col, row)
        current_ones.update(fields)
        with self._lock:
            self._conn.execute(
                "INSERT INTO hexes_gm (campaign_id, col, row, gm_notes, "
                "hidden_features, gm_difficulty, hidden_fields) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(campaign_id, col, row) DO UPDATE SET "
                "gm_notes=excluded.gm_notes, hidden_features=excluded.hidden_features, "
                "gm_difficulty=excluded.gm_difficulty, "
                "hidden_fields=excluded.hidden_fields",
                (campaign_id, col, row, current_ones["gm_notes"],
                 _json(current_ones["hidden_features"]), current_ones["gm_difficulty"],
                 _json(current_ones["hidden_fields"])))
            self._commit()

    def campaign_difficulty(self, campaign_id: str) -> dict:
        """The travel categories set by hand by the GM, in a single read.

        The planner consults them for every hex it evaluates: a query per cell
        would be hundreds of trips to the database for every path.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT col, row, gm_difficulty FROM hexes_gm WHERE campaign_id=? "
                "AND gm_difficulty IS NOT NULL", (campaign_id,)).fetchall()
        return {(r["col"], r["row"]): r["gm_difficulty"] for r in rows}

    # --------------------------------------------------------------- borders
    def campaign_borders(self, campaign_id: str) -> dict:
        """All the marked borders, in a single read.

        Like `campaign_difficulty`: the planner queries them for every pair of
        neighbours it evaluates, and a query per side would be thousands of
        trips to the database for every path. The key is the ordered pair.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT col_a, row_a, col_b, row_b, kind, source, note "
                "FROM borders WHERE campaign_id=?", (campaign_id,)).fetchall()
        return {(r["col_a"], r["row_a"], r["col_b"], r["row_b"]):
                {"kind": r["kind"], "source": r["source"], "note": r["note"]}
                for r in rows}

    def set_border(self, campaign_id: str, a, b, kind: str | None,
                        source: str = "gm", note: str = "") -> None:
        """Marks, changes or deletes a border. `kind=None` turns it back to land."""
        key = hexgrid.border_key(tuple(a), tuple(b))
        with self._lock:
            if kind is None:
                self._conn.execute(
                    "DELETE FROM borders WHERE campaign_id=? AND col_a=? AND "
                    "row_a=? AND col_b=? AND row_b=?", (campaign_id, *key))
            else:
                self._conn.execute(
                    "INSERT INTO borders (campaign_id, col_a, row_a, col_b, row_b, "
                    "kind, source, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(campaign_id, col_a, row_a, col_b, row_b) DO UPDATE "
                    "SET kind=excluded.kind, source=excluded.source, note=excluded.note",
                    (campaign_id, *key, kind, source, note))
            self._commit()

    # ------------------------------------------------------------------ banks
    def campaign_banks(self, campaign_id: str) -> dict:
        """The banks of every cut hex, in a single read.

        The pathfinder consults them for every step it evaluates: as for the
        borders, a query per hex would be thousands of trips to the database.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT col, row, groups FROM banks WHERE campaign_id=?",
                (campaign_id,)).fetchall()
        outside = {}
        for r in rows:
            groups = json.loads(r["groups"] or "[]")
            if len(groups) > 1:
                outside[(r["col"], r["row"])] = [list(g) for g in groups]
        return outside

    def set_banks(self, campaign_id: str, coord, groups,
                     source: str = "gm", points=()) -> None:
        """Marks or deletes the banks of a hex. Empty `groups` makes it dry.

        `points` are the hand-drawn segments, when there are any: the shores
        follow from those, but the shape of the line does not — passing
        through the center or going straight from one vertex to another
        divides the hex the same way, and which of the two you drew only the
        drawing says.
        """
        col, row = int(coord[0]), int(coord[1])
        groups = list(groups or [])
        points = list(points or [])
        with self._lock:
            # Deleted only when nothing is left: neither shores nor drawing. A
            # stretch entering and stopping in the middle does not divide the
            # hex yet — zero shores — but it was drawn, and vanishing as soon
            # as drawn would be the most disconcerting thing it could do.
            if len(groups) < 2 and not points:
                self._conn.execute(
                    "DELETE FROM banks WHERE campaign_id=? AND col=? AND row=?",
                    (campaign_id, col, row))
            else:
                self._conn.execute(
                    "INSERT INTO banks (campaign_id, col, row, groups, points, source) "
                    "VALUES (?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(campaign_id, col, row) DO UPDATE SET "
                    "groups=excluded.groups, points=excluded.points, "
                    "source=excluded.source",
                    (campaign_id, col, row,
                     _json([sorted(g) for g in groups] if len(groups) >= 2
                           else []),
                     _json([[str(a), str(b)] for a, b in points]),
                     source))
            self._commit()

    # ----------------------------------------------------------------- crossings
    def campaign_crossings(self, campaign_id: str) -> dict:
        """The crossings inside the cut hexes, in a single read.

        `{(col, row): [{"id": ..., "where": (x, y), "kind": ...,
        "difficulty": ...}, ...]}`, where `where` is the point at which that
        bridge hops over the water, in hex radii from the cell center.

        As for borders and banks: the pathfinder consults them at every step,
        and a query per hex would be thousands of trips to the database for a
        single path.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, col, row, a_x, a_y, b_x, b_y, at_x, at_y, "
                "kind, difficulty FROM crossings WHERE campaign_id=?",
                (campaign_id,)).fetchall()
        outside: dict = {}
        for r in rows:
            outside.setdefault((r["col"], r["row"]), []).append({
                "id": r["id"],
                "ends": ((float(r["a_x"]), float(r["a_y"])),
                         (float(r["b_x"]), float(r["b_y"]))),
                "at": (None if r["at_x"] is None
                          else (float(r["at_x"]), float(r["at_y"]))),
                "kind": r["kind"] or "bridge",
                "difficulty": r["difficulty"] or None,
            })
        return outside

    def set_crossing(self, campaign_id: str, coord, ends, above=None,
                      kind: str = "bridge", difficulty: str | None = None,
                      source: str = "gm", note: str = "",
                      crossing_id: str | None = None) -> str:
        """Puts or changes a crossing inside a hex, and gives its id.

        `ends` are the two points that remember the joined shores; `at` is the
        point where one hops over. Two crossings with the same shores **and**
        the same spot are the same crossing, and the second changes the first
        instead of sitting next to it. Same shores but a different spot are
        two: a bridge here and a ford further on along the same river are two
        ways of passing, and both are kept.
        """
        col, row = int(coord[0]), int(coord[1])
        (ax, ay), (bx, by) = ((round(float(p[0]), 6), round(float(p[1]), 6))
                              for p in ends)
        sx, sy = ((None, None) if above is None
                  else (round(float(above[0]), 6), round(float(above[1]), 6)))
        with self._lock:
            old_row = self._conn.execute(
                "SELECT id FROM crossings WHERE campaign_id=? AND col=? AND row=? "
                "AND abs(a_x-?) < 1e-4 AND abs(a_y-?) < 1e-4 "
                "AND abs(b_x-?) < 1e-4 AND abs(b_y-?) < 1e-4 "
                "AND ((at_x IS NULL AND ? IS NULL) "
                "     OR (abs(at_x-?) < 1e-4 AND abs(at_y-?) < 1e-4))",
                (campaign_id, col, row, ax, ay, bx, by, sx, sx, sy)).fetchone()
            char_id = crossing_id or (old_row["id"] if old_row
                               else uuid.uuid4().hex[:12])
            self._conn.execute(
                "INSERT INTO crossings (campaign_id, id, col, row, a_x, a_y, b_x, "
                "b_y, at_x, at_y, kind, difficulty, source, note) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(campaign_id, id) DO UPDATE "
                "SET kind=excluded.kind, difficulty=excluded.difficulty, "
                "a_x=excluded.a_x, a_y=excluded.a_y, b_x=excluded.b_x, "
                "b_y=excluded.b_y, at_x=excluded.at_x, "
                "at_y=excluded.at_y, source=excluded.source, "
                "note=excluded.note",
                (campaign_id, char_id, col, row, ax, ay, bx, by, sx, sy, kind,
                 difficulty, source, note))
            self._commit()
        return char_id

    def remove_crossing(self, campaign_id: str, crossing_id: str) -> int:
        """Removes a single crossing, by id."""
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM crossings WHERE campaign_id=? AND id=?",
                (campaign_id, crossing_id))
            self._commit()
        return cur.rowcount or 0

    def remove_crossings(self, campaign_id: str, coord=None) -> int:
        """Removes the crossings of a hex, or all of them if none is given."""
        with self._lock:
            if coord is None:
                cur = self._conn.execute(
                    "DELETE FROM crossings WHERE campaign_id=?", (campaign_id,))
            else:
                cur = self._conn.execute(
                    "DELETE FROM crossings WHERE campaign_id=? AND col=? AND row=?",
                    (campaign_id, int(coord[0]), int(coord[1])))
            self._commit()
            return cur.rowcount or 0

    # ---------------------------------------------------------------- lakes
    def campaign_lakes(self, campaign_id: str) -> list[dict]:
        """The bodies of still water, with the cells they occupy."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, name, cells, points FROM lakes WHERE campaign_id=? "
                "ORDER BY name, id", (campaign_id,)).fetchall()
        outside = []
        for r in rows:
            try:
                cells = [(int(c[0]), int(c[1])) for c in json.loads(r["cells"])]
                points = [str(x) for x in json.loads(r["points"] or "[]")]
            except (ValueError, TypeError, json.JSONDecodeError, IndexError):
                continue
            outside.append({"id": r["id"], "name": r["name"], "cells": cells,
                          "points": points})
        return outside

    def lake_cells(self, campaign_id: str) -> dict:
        """`{(col, row): lake id}`, to ask quickly «is it lake?»."""
        outside = {}
        for lake in self.campaign_lakes(campaign_id):
            for cell in lake["cells"]:
                outside[cell] = lake["id"]
        return outside

    def bank_points(self, campaign_id: str) -> dict:
        """The segments drawn inside the hexes: `{hex: [(a, b), ...]}`.

        Kept apart from `campaign_banks` because they serve different things:
        that is the model — who touches whom — and travel queries it at every
        step; this is the drawing, and only whoever draws looks at it.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT col, row, points FROM banks WHERE campaign_id=?",
                (campaign_id,)).fetchall()
        outside = {}
        for r in rows:
            try:
                segments = [(str(s[0]), str(s[1]))
                            for s in json.loads(r["points"] or "[]")
                            if isinstance(s, (list, tuple)) and len(s) == 2]
            except (ValueError, TypeError, json.JSONDecodeError):
                continue
            if segments:
                outside[(r["col"], r["row"])] = segments
        return outside

    def campaign_sections(self, campaign_id: str,
                         orient: str = "pointy") -> dict:
        """The sections of every cut hex: `{hex: (Face, ...)}`.

        It is what `campaign_banks` meant to say and could not. The archive's
        banks are groups of **sides**, and a group of sides is not a piece of
        hex: when the water cuts in a slightly less trivial way the two counts
        come apart — `sections.py` explains and measures it. Here the
        **drawing** is read, which is the real thing, and the faces are cut.

        `campaign_banks` stays and is no contradiction: it serves to draw the
        water and to exchange charts, where groups of sides are still the
        format. This serves to travel.
        """
        return sections_mod.map_sections(
            self.bank_points(campaign_id),
            self.campaign_banks(campaign_id), orient)

    def campaign_water(self, campaign_id: str, orient: str = "pointy") -> dict:
        """The water stretches inside every hex: `{hex: (cut, ...)}`.

        It is `campaign_sections` seen from the other side. That says into
        which pieces the water divides a hex; this says **where it runs**,
        which is what is needed to know which passages it closes among the 24
        atoms. The hexes the water does not divide are in it too: a river
        entering and stopping makes no shores but must be walked around all
        the same.
        """
        return sections_mod.map_water(
            self.bank_points(campaign_id),
            self.campaign_banks(campaign_id), orient)

    def set_lake(self, campaign_id: str, lake_id: str, cells,
                     name: str = "", source: str = "gm", points=()) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO lakes (campaign_id, id, name, cells, points, source) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(campaign_id, id) DO UPDATE SET "
                "name=excluded.name, cells=excluded.cells, "
                "points=excluded.points, source=excluded.source",
                (campaign_id, lake_id, name,
                 _json([[int(c[0]), int(c[1])] for c in cells]),
                 _json([str(x) for x in points]), source))
            self._commit()

    def remove_lake(self, campaign_id: str, lake_id: str | None = None) -> int:
        """Removes a lake, or all of them. The water lines closing it stay."""
        with self._lock:
            if lake_id is None:
                cur = self._conn.execute(
                    "DELETE FROM lakes WHERE campaign_id=?", (campaign_id,))
            else:
                cur = self._conn.execute(
                    "DELETE FROM lakes WHERE campaign_id=? AND id=?",
                    (campaign_id, lake_id))
            how_many = cur.rowcount or 0
            self._commit()
        return how_many

    # ------------------------------------------------------------- currents
    def campaign_currents(self, campaign_id: str) -> dict:
        """The direction of every stretch: `{stretch: (upstream node, downstream node)}`.

        A single read, as for the borders: the planner asks the direction at
        every step of a route, and a query per stretch would be dozens of
        trips to the database for every boat journey.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT stretch, upstream, downstream FROM currents WHERE campaign_id=?",
                (campaign_id,)).fetchall()
        outside = {}
        for r in rows:
            upstream = waterways.node_from_text(r["upstream"])
            downstream = waterways.node_from_text(r["downstream"])
            if upstream is not None and downstream is not None:
                outside[r["stretch"]] = (upstream, downstream)
        return outside

    def set_currents(self, campaign_id: str, steps, source: str = "gm") -> int:
        """Marks the direction of one or more stretches. `steps` = (upstream, downstream) pairs.

        Setting again the direction of a stretch that already had one
        **overwrites** it, backwards too: it is the gesture that corrects a
        river drawn the wrong way round, and asking before deleting would make
        that impossible.
        """
        how_many = 0
        with self._lock:
            for upstream, downstream in steps:
                self._conn.execute(
                    "INSERT INTO currents (campaign_id, stretch, upstream, downstream, source) "
                    "VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(campaign_id, stretch) DO UPDATE SET "
                    "upstream=excluded.upstream, downstream=excluded.downstream, source=excluded.source",
                    (campaign_id, waterways.text_key(upstream, downstream),
                     waterways.node_text(upstream), waterways.node_text(downstream), source))
                how_many += 1
            self._commit()
        return how_many

    def remove_currents(self, campaign_id: str, stretches=None) -> int:
        """Removes the direction from some stretches, or from all if none is given."""
        with self._lock:
            if stretches is None:
                cur = self._conn.execute(
                    "DELETE FROM currents WHERE campaign_id=?", (campaign_id,))
                how_many = cur.rowcount or 0
            else:
                how_many = 0
                for stretch in stretches:
                    cur = self._conn.execute(
                        "DELETE FROM currents WHERE campaign_id=? AND stretch=?",
                        (campaign_id, stretch))
                    how_many += cur.rowcount or 0
            self._commit()
        return how_many

    def write_water_chart(self, campaign_id: str, borders, banks: dict,
                           crossings, replace_: bool = False,
                           currents=()) -> dict:
        """Writes in one go the water coming from a chart.

        A chart can carry hundreds of rows, and writing them one by one would
        mean hundreds of transactions: here it is a single one, and either all
        of it goes in or nothing does. With `replace_` what was there before
        goes away — borders, banks and crossings together, because they are
        three faces of the same water and mixing two maps would give rivers
        that do not close.

        `source` stays `chart`: so a re-reading of the image does not take
        them away, as it does not take away those marked by hand.
        """
        counts = {"borders": 0, "banks": 0, "crossings": 0, "currents": 0,
                    "removed": 0}
        with self._lock:
            if replace_:
                for table in ("borders", "banks", "crossings", "currents"):
                    cur = self._conn.execute(
                        f"DELETE FROM {table} WHERE campaign_id=?", (campaign_id,))
                    counts["removed"] += cur.rowcount or 0
            for a, b, kind in borders:
                key = hexgrid.border_key(tuple(a), tuple(b))
                self._conn.execute(
                    "INSERT INTO borders (campaign_id, col_a, row_a, col_b, row_b, "
                    "kind, source, note) VALUES (?, ?, ?, ?, ?, ?, 'carta', '') "
                    "ON CONFLICT(campaign_id, col_a, row_a, col_b, row_b) DO UPDATE "
                    "SET kind=excluded.kind, source=excluded.source",
                    (campaign_id, *key, kind))
                counts["borders"] += 1
            for coord, groups in banks.items():
                if len(groups) < 2:
                    continue
                self._conn.execute(
                    "INSERT INTO banks (campaign_id, col, row, groups, source) "
                    "VALUES (?, ?, ?, ?, 'carta') "
                    "ON CONFLICT(campaign_id, col, row) DO UPDATE SET "
                    "groups=excluded.groups, source=excluded.source",
                    (campaign_id, int(coord[0]), int(coord[1]),
                     _json([sorted(g) for g in groups])))
                counts["banks"] += 1
            for coord, ends, above, kind, difficulty in crossings:
                (ax, ay), (bx, by) = ((round(float(q[0]), 6),
                                       round(float(q[1]), 6)) for q in ends)
                sx, sy = ((None, None) if above is None
                          else (round(float(above[0]), 6),
                                round(float(above[1]), 6)))
                self._conn.execute(
                    "INSERT INTO crossings (campaign_id, id, col, row, a_x, a_y, "
                    "b_x, b_y, at_x, at_y, kind, difficulty, source, note) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'carta', '')",
                    (campaign_id, uuid.uuid4().hex[:12], int(coord[0]),
                     int(coord[1]), ax, ay, bx, by, sx, sy, kind, difficulty))
                counts["crossings"] += 1
            for upstream, downstream in currents or ():
                self._conn.execute(
                    "INSERT INTO currents (campaign_id, stretch, upstream, downstream, source) "
                    "VALUES (?, ?, ?, ?, 'carta') "
                    "ON CONFLICT(campaign_id, stretch) DO UPDATE SET "
                    "upstream=excluded.upstream, downstream=excluded.downstream, source=excluded.source",
                    (campaign_id, waterways.text_key(upstream, downstream),
                     waterways.node_text(upstream), waterways.node_text(downstream)))
                counts["currents"] += 1
            self._commit()
        return counts

    def replace_traced_banks(self, campaign_id: str, banks: dict) -> int:
        """Replaces the banks read from the image, leaving the hand-made ones alone.

        Same rule as for the borders: whoever decided in person decided, and a
        re-reading does not erase their work.
        """
        with self._lock:
            by_hand = {(r["col"], r["row"]) for r in self._conn.execute(
                "SELECT col, row FROM banks WHERE campaign_id=? AND source<>'traced'",
                (campaign_id,)).fetchall()}
            self._conn.execute(
                "DELETE FROM banks WHERE campaign_id=? AND source='traced'",
                (campaign_id,))
            new_ones = [(campaign_id, int(c[0]), int(c[1]),
                      _json([sorted(g) for g in groups]), "traced")
                     for c, groups in banks.items()
                     if len(groups) > 1 and (int(c[0]), int(c[1])) not in by_hand]
            self._conn.executemany(
                "INSERT INTO banks (campaign_id, col, row, groups, source) "
                "VALUES (?, ?, ?, ?, ?)", new_ones)
            self._commit()
        return len(new_ones)

    def replace_traced(self, campaign_id: str, borders) -> int:
        """Replaces the borders read from the map, leaving the hand-made ones alone.

        Whoever marked a border in person decided: a new reading of the image
        must not erase their work. That is why the source is in the row, and
        only `traced` is touched here.
        """
        entries = [(hexgrid.border_key(tuple(a), tuple(b)), kind)
                for a, b, kind in borders]
        with self._lock:
            by_hand = {(r["col_a"], r["row_a"], r["col_b"], r["row_b"])
                      for r in self._conn.execute(
                          "SELECT col_a, row_a, col_b, row_b FROM borders "
                          "WHERE campaign_id=? AND source<>'traced'",
                          (campaign_id,)).fetchall()}
            self._conn.execute(
                "DELETE FROM borders WHERE campaign_id=? AND source='traced'",
                (campaign_id,))
            new_items = [(campaign_id, *key, kind, "traced", "")
                     for key, kind in entries if key not in by_hand]
            self._conn.executemany(
                "INSERT INTO borders (campaign_id, col_a, row_a, col_b, row_b, "
                "kind, source, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", new_items)
            self._commit()
        return len(new_items)

    def campaign_secrets(self, campaign_id: str) -> dict:
        """Secret features and fields of the whole campaign, in a single read.

        The map asks for them for every hex at every redraw: a query per cell
        would be hundreds of trips to the database for every frame.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT col, row, hidden_features, hidden_fields FROM hexes_gm "
                "WHERE campaign_id=?", (campaign_id,)).fetchall()
        return {(r["col"], r["row"]): {
            "hidden_features": json.loads(r["hidden_features"] or "[]"),
            "hidden_fields": json.loads(r["hidden_fields"] or "[]"),
        } for r in rows}

    # ---------------------------------------------------------- visibility
    def visible_hexes(self, campaign_id: str, user_id: str) -> set[tuple[int, int]]:
        """The coordinates that user may see: their own plus everyone's."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT col, row FROM visibility WHERE campaign_id=? "
                "AND recipient IN ('*', ?)", (campaign_id, user_id)).fetchall()
        return {(r["col"], r["row"]) for r in rows}

    def visible_to_party(self, campaign_id: str) -> set[tuple[int, int]]:
        """The coordinates revealed to everyone, not counting those given to a single one."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT col, row FROM visibility WHERE campaign_id=? AND recipient='*'",
                (campaign_id,)).fetchall()
        return {(r["col"], r["row"]) for r in rows}

    def reveal(self, campaign_id: str, coords, recipient: str = "*") -> int:
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        with self._lock:
            before = self._conn.total_changes
            self._conn.executemany(
                "INSERT INTO visibility (campaign_id, col, row, recipient, revealed_at) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
                [(campaign_id, c, r, recipient, now) for c, r in coords])
            self._commit()
            return self._conn.total_changes - before

    def hide(self, campaign_id: str, coords, recipient: str | None = None) -> None:
        """Hides again. Without a recipient it removes the visibility for everyone."""
        with self._lock:
            for col, row in coords:
                if recipient is None:
                    self._conn.execute(
                        "DELETE FROM visibility WHERE campaign_id=? AND col=? AND row=?",
                        (campaign_id, col, row))
                else:
                    self._conn.execute(
                        "DELETE FROM visibility WHERE campaign_id=? AND col=? AND row=? "
                        "AND recipient=?", (campaign_id, col, row, recipient))
            self._commit()

    def count_visible(self, campaign_id: str) -> int:
        with self._lock:
            return self._conn.execute(
                "SELECT COUNT(DISTINCT col || ',' || row) FROM visibility "
                "WHERE campaign_id=? AND recipient='*'", (campaign_id,)).fetchone()[0]

    # ----------------------------------------------------------- characters
    def list_characters(self, campaign_id: str, active_only: bool = True) -> list[dict]:
        sql = "SELECT * FROM characters WHERE campaign_id = ?"
        if active_only:
            sql += " AND active = 1"
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql + " ORDER BY name", (campaign_id,))]

    def characters_of_user(self, campaign_id: str, user_id: str) -> list[dict]:
        """The characters linked to that account.

        The filter is in the query and not in an `if` after reading: this way
        another player's sheet does not even reach memory.
        """
        with self._lock:
            return [dict(r) for r in self._conn.execute(
                "SELECT * FROM characters WHERE campaign_id=? AND user_id=? "
                "AND active=1 ORDER BY name", (campaign_id, user_id))]

    def character(self, character_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM characters WHERE id = ?", (character_id,)).fetchone()
        return dict(row) if row else None

    def create_character(self, data: dict) -> None:
        fields = ("id", "campaign_id", "user_id", "name", "speed_m",
                 "con_mod", "color", "active", "created_at")
        with self._lock:
            self._conn.execute(
                f"INSERT INTO characters ({', '.join(fields)}) "
                f"VALUES ({', '.join('?' * len(fields))})",
                [data.get(c) for c in fields])
            self._commit()

    def update_character(self, character_id: str, **fields) -> None:
        if not fields:
            return
        allowed = {"user_id", "name", "speed_m", "con_mod",
                   "color", "hex_col", "hex_row", "bank", "pos_x", "pos_y",
                   "active", "portrait", "token", "speed_bonus_m",
                   "swim_speed_m", "note", "stable_id"}
        unknowns = set(fields) - allowed
        if unknowns:
            raise ValueError(f"fields that cannot be modified: {sorted(unknowns)}")
        assignments = ", ".join(f"{c} = ?" for c in fields)
        with self._lock:
            self._conn.execute(f"UPDATE characters SET {assignments} WHERE id = ?",
                               [*fields.values(), character_id])
            self._commit()

    def delete_character(self, character_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM characters WHERE id = ?", (character_id,))
            self._commit()

    # ---------------------------------------------------------------- stable
    def list_stable(self, campaign_id: str) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(
                "SELECT * FROM stable WHERE campaign_id=? ORDER BY name, vehicle",
                (campaign_id,))]

    def stable_vehicle(self, stable_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM stable WHERE id=?", (stable_id,)).fetchone()
        return dict(row) if row else None

    def create_stable_vehicle(self, data: dict) -> None:
        fields = ("id", "campaign_id", "vehicle", "name", "available",
                 "speed_m", "seats", "kind", "portrait", "token", "note",
                 "created_at", "hex_col", "hex_row")
        with self._lock:
            self._conn.execute(
                f"INSERT INTO stable ({', '.join(fields)}) "
                f"VALUES ({', '.join('?' * len(fields))})",
                [data.get(c) for c in fields])
            self._commit()

    def update_stable_vehicle(self, stable_id: str, **fields) -> None:
        if not fields:
            return
        allowed = {"vehicle", "name", "available", "speed_m", "seats",
                   "kind", "portrait", "token", "note", "hex_col", "hex_row",
                   "bank", "pos_x", "pos_y"}
        unknowns = set(fields) - allowed
        if unknowns:
            raise ValueError(f"fields that cannot be modified: {sorted(unknowns)}")
        assignments = ", ".join(f"{c} = ?" for c in fields)
        with self._lock:
            self._conn.execute(f"UPDATE stable SET {assignments} WHERE id = ?",
                               [*fields.values(), stable_id])
            self._commit()

    def delete_stable_vehicle(self, stable_id: str) -> None:
        with self._lock:
            # Whoever was on it goes back on foot, instead of pointing at nothing.
            self._conn.execute(
                "UPDATE characters SET stable_id=NULL WHERE stable_id=?", (stable_id,))
            self._conn.execute("DELETE FROM stable WHERE id=?", (stable_id,))
            self._commit()

    def move_vehicles_with(self, campaign_id: str, character_ids,
                           coord, stable_id: str | None = None,
                           where=None) -> list[str]:
        """Moves onto the hex the vehicles that are on the map and travel with them.

        A wagon has no position of its own: it is where whoever tows it is,
        and the marker is drawn there. A boat instead **is on the map** — it
        is in the middle of the river, and stays there even when the crew gets
        off. That is why it must be moved by hand: nobody does it in its
        place, and without this whoever travelled by boat reached the
        destination while the boat stayed behind, still where it had left.

        Only those **already on the map** are moved: putting one there that
        was not would mean making a wagon appear in the middle of the water.
        """
        from kingmaker import travel as travel_mod  # here, to avoid an import cycle
        ids = [x for x in (character_ids or []) if x]
        moved_ones = []
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM stable WHERE campaign_id=? AND hex_col IS NOT NULL",
                (campaign_id,)).fetchall()
            for r in rows:
                if r["id"] == stable_id:
                    moved_ones.append(r["id"])
                    continue
                if not ids:
                    continue
                # A boat sits in the water and is not carried on one's
                # shoulders: it follows only the journey it is the vehicle of.
                # Whoever gets off to go by land leaves it where it is (and the
                # caller removes their link).
                if travel_mod.vehicle_kind(dict(r)) == "water":
                    continue
                sign = ",".join("?" * len(ids))
                how_many = self._conn.execute(
                    f"SELECT COUNT(*) AS n FROM characters WHERE stable_id=? "
                    f"AND id IN ({sign})", (r["id"], *ids)).fetchone()
                if how_many["n"]:
                    moved_ones.append(r["id"])
            for sid in moved_ones:
                # The spot inside the hex too: where a river cuts it, the
                # vehicle arrives on the side the party arrived from, or
                # whoever gets off would end up on the other bank.
                self._conn.execute(
                    "UPDATE stable SET hex_col=?, hex_row=?, pos_x=?, pos_y=? "
                    "WHERE id=?",
                    (int(coord[0]), int(coord[1]),
                     None if where is None else round(float(where[0]), 6),
                     None if where is None else round(float(where[1]), 6), sid))
            if moved_ones:
                self._commit()
        return moved_ones

    def characters_on_vehicle(self, stable_id: str) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(
                "SELECT * FROM characters WHERE stable_id=? AND active=1 ORDER BY name",
                (stable_id,))]

    # --------------------------------------------------------------- journeys
    def create_journey(self, data: dict) -> None:
        fields = ("id", "campaign_id", "characters", "stable_id", "departure",
                 "arrival", "pos_x", "pos_y", "path", "costs", "legs",
                 "activity_cost", "days", "activities_per_day", "progress",
                 "departure_day", "forced_march", "status", "turn_created",
                 "created_by", "created_at")
        values = []
        for c in fields:
            value = data.get(c)
            values.append(_json(value)
                          if c in ("characters", "path", "costs", "legs")
                          else value)
        with self._lock:
            self._conn.execute(
                f"INSERT INTO journeys ({', '.join(fields)}) "
                f"VALUES ({', '.join('?' * len(fields))})", values)
            self._commit()

    def list_journeys(self, campaign_id: str, state: str | None = "in_progress") -> list[dict]:
        sql = "SELECT * FROM journeys WHERE campaign_id=?"
        params: list = [campaign_id]
        if state:
            sql += " AND status=?"
            params.append(state)
        with self._lock:
            rows = self._conn.execute(sql + " ORDER BY created_at DESC", params)
            outside = []
            for r in rows:
                entry = dict(r)
                entry["characters"] = json.loads(entry["characters"] or "[]")
                entry["path"] = json.loads(entry["path"] or "[]")
                entry["costs"] = json.loads(entry["costs"] or "[]")
                entry["legs"] = json.loads(entry["legs"] or "[]")
                _ensure_legs(entry)
                outside.append(entry)
        return outside

    def update_journey(self, journey_id: str, **fields) -> None:
        if not fields:
            return
        allowed = {"status", "turn_resolved", "progress", "departure_day",
                   "legs"}
        unknowns = set(fields) - allowed
        if unknowns:
            raise ValueError(f"fields that cannot be modified: {sorted(unknowns)}")
        values = [_json(v) if c == "legs" else v for c, v in fields.items()]
        assignments = ", ".join(f"{c} = ?" for c in fields)
        with self._lock:
            self._conn.execute(f"UPDATE journeys SET {assignments} WHERE id = ?",
                               [*values, journey_id])
            self._commit()

    # ----------------------------------------------------------------- misc
    def _remember_written(self, document: dict, hexes: dict) -> None:
        without = {c: v for c, v in document.items() if c != "hexes"}
        self._written_document = _json(without)
        self._written_hexes = {c: _json(d) for c, d in hexes.items()}

    def close(self) -> None:
        with self._lock:
            self._conn.close()
