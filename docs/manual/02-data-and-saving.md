# 2. Data and saving

## Two ways of being on disk

The kingdom is **one document** (`STATE.k`, a dictionary) plus **real tables** for the things
that are queried one by one. The split is deliberate (`storage/archive.py`, module docstring): the forty
odd keys of the kingdom sheet need no query, the hexes do — the fog, the travel and the GM
screen ask «this hex» dozens of times per redraw.

```mermaid
erDiagram
    campaigns ||--|| kingdoms : "JSON document (STATE.k without hexes)"
    campaigns ||--o{ hexes : "one row per touched hex"
    campaigns ||--o{ hexes_gm : "notes, hidden features, difficulty, hidden fields"
    campaigns ||--o{ visibility : "who sees which hex ('*' = everyone)"
    campaigns ||--o{ characters : "hex_col/hex_row + pos_x/pos_y, stable_id, token"
    campaigns ||--o{ stable : "the owned vehicles: land/water/air, seats, position"
    campaigns ||--o{ journeys : "path, costs, legs (JSON), status"
    campaigns ||--o{ borders : "water between two hexes (ordered pair)"
    campaigns ||--o{ banks : "side groups + points (drawn segments)"
    campaigns ||--o{ crossings : "inner crossings: two ends + the point 'at'"
    campaigns ||--o{ lakes : "cells + the drawn ring of vertices"
    campaigns ||--o{ currents : "upstream → downstream per drawn line"
    campaigns ||--o{ log : "the kingdom journal"
    users ||--o{ characters : "user_id (who plays them)"
    users {
        text language "the chosen interface language"
    }
    meta }|--|| campaigns : "schema_version"
```

`SCHEMA` in `storage/archive.py` creates everything with `CREATE TABLE IF NOT EXISTS`; every table
carries a comment saying **why** it exists in that shape. They are worth reading: they are the
design decisions written next to the data.

### The document: `STATE.k`

`state.new_kingdom()` is the schema of the document — the full list of keys with their starting
values. The most important:

| Key | Content |
|---|---|
| `created`, `name`, `level`, `xp`, `turn`, `rp`, `unrest`, `fame_points` | the sheet |
| `abilities`, `proficiencies`, `roles`, `feats`, `ruins`, `commodities` | the tables of the sheet |
| `roles[rid]` = `{name, character_id, pc, invested, absent}` | a role may point at a character (table) or a written name (NPC) |
| `modifiers`, `turn_activities`, `milestones` | the state of the turn |
| `hexes` | `{"col,row": {...}}` — in memory, but on disk it is the `hexes` table |
| `settlements` | the Urban Grid of every city: `grids[g][block][lot]`, structures by id |
| `map` | image, orientation, `size`, `origin_x/y`, `columns/rows`, `image_width/image_height`, zoom, veil, fog |
| `clock` | start date, days passed, clock running, seconds per day |
| `waters` | whether the table uses the water model (`hexmap.waters_active`) |

The journal is not in the document: it is the `log` table (`STATE.record`, `STATE.journal`);
the `journal_into_table` migration moved the old rows once.

A hex (`state.hex(col, row)` creates it at the first touch) has `status` (unknown |
reconnoitered | cleared | claimed), `terrains`, `features`, `roads`, `fortified`, `farmland`,
`work_site`, `settlement`, `name`, `note`. The table columns are `HEX_COLUMNS`; a new key ends
up in `extra` (JSON) without touching the schema.

## The life cycle

```mermaid
sequenceDiagram
    participant Start
    participant STATE
    participant migrations
    participant archive
    participant UI
    participant timer as theme._maintenance (0.5 s)

    Start->>archive: Archive(): schema, upgrade_storage_v27 if the save is older (backup first)
    Start->>STATE: State() → load()
    STATE->>migrations: import_json (only if the DB is empty and regno.json exists)
    STATE->>archive: read(campaign) → document + hexes
    STATE->>migrations: normalize, unify_fields, ensure_characters, ensure_visibility, water_on_edge, renumber_sections, marker_spots, crossings_on_point
    Note over STATE: from here STATE.k is the kingdom
    UI->>STATE: edits STATE.k
    UI->>timer: theme.mark_dirty() / save_and_refresh()
    timer->>archive: write(campaign, k) at most every 2 s
    archive->>archive: serialise; rewrites ONLY the changed document/hexes
```

The points that are not seen but count:

- **`archive.write` is differential**: it keeps the last written version of document and hexes
  (`_remember_written`) and rewrites only what differs. Serialising the document at every
  `write` still costs, but happens outside the lock.
- **The separate tables are written at once**: `update_character`, `set_border`,
  `create_journey`… commit right there. Only the document and the hexes go through the timer.
  Hence a practical rule: after an `update_character` whoever reads `STATE.characters()` sees
  the new value (it is a query), but a panel keeping a copy in hand does not.
- **`_rev`**: `theme.mark_dirty` (so every `save_*`) increments `STATE.k["_rev"]` at every
  change; together with `archive.rev` (which rises at every `_commit`) it is the key of the
  copies the map keeps (view, sections, network, SVG layers, the ruler field); it ends up in
  the `kingdoms.rev` column.
- **A single lock** (`threading.RLock`) protects the connection: the timer writes from one
  callback, the pages from another.
- **WAL**: `PRAGMA journal_mode=WAL`, so a copy of the file for the tests is made by copying
  `.db` and `.db-wal` together.

## The migrations: three levels

1. **Added columns** — `Archive.ADDED_COLUMNS`: `(version, table, definition)`.
   `_add_missing_columns` runs on every database and adds only what is missing, so a fresh
   database and a migrated one end up with the same columns.
2. **Rebuilt tables** — `TABLES_REBUILT`: when a table changes shape it is renamed into a stash
   (`_stash_tables`) and `migrations.py` translates it once the kingdom is in memory (it needs
   the map geometry, which the archive does not have). Example: `crossings_on_point`.
3. **Kingdom data** — the functions of `migrations.py` called by `State.load`: idempotent, run
   at every start, do something only if they find the old format.

**Schema 27 — the English rename.** Release 1.0.0 renamed every table, column, document key
and stored enum value from Italian to English. `migrations.upgrade_storage_v27` does it on a
save older than 27, after `Archive.__init__` has checkpointed the WAL and copied the file to
`kingmaker.db.pre-v27.bak`: tables via `RENAMED_TABLES`, columns via `RENAMED_COLUMNS`,
document keys and values via `translate_document` with the maps in `legacy_names.py`
(`DOCUMENT_KEYS`, `HEX_STATUS`, `TERRAINS`, `FEATURE_KINDS`, the ids of abilities, skills,
activities, …). `is_legacy_document` recognises an old JSON export and the same translation is
applied on import. `rename_asset_folders` renames `assets/personaggi` → `characters`,
`veicoli` → `vehicles`, `miniature` → `thumbnails` at the first start. `tests/test_migration_v27.py`
drives it on `tests/fixtures/v26.db`.

`SCHEMA_VERSION` (28: schema 27 plus the `users.units` column) is written in `meta`. Adding a
column: one row in `ADDED_COLUMNS` with the new version **and** the same column in the `CREATE
TABLE` (a test compares the two), then raise `SCHEMA_VERSION`. Adding a table: the `CREATE
TABLE IF NOT EXISTS` in the `SCHEMA` is enough.

## Export, reset, copies

- **Download the JSON save** (Manual tab, admin only): `STATE.export()` — the whole `STATE.k`,
  hexes included, plus the last 400 rows of the journal. It does not contain the other tables
  (users, characters, water).
- **Start over**: `STATE.reset()` → `archive.reset` empties **every** table of the campaign
  (`CAMPAIGN_TABLES`: kingdom, hexes, secrets, fog, characters, vehicles, journeys, water,
  journal). The accounts stay.
- **Download / load the save file** (Manual tab, admin only): `Archive.backup_to` writes a
  consistent copy of the whole database with the SQLite backup API after a WAL checkpoint, sent
  as `kingmaker-<date>.db` from `saves/backups/`; `Archive.inspect` says what an uploaded file
  is (SQLite header, the game tables, schema version not newer than ours, kingdom name, number
  of accounts) or raises a `ValueError` carrying a catalog key; `Archive.restore_from` closes
  the connection, copies the current file to `kingmaker.db.before-restore-<date>.bak`, swaps
  the file in and reopens it through `_open`, so an old save is migrated exactly as at start;
  `STATE.restore` reloads the kingdom. `tests/test_backup.py` covers the round trip.
- **Copies**: `saves/backup-*` are copies made by hand before the big migrations, and
  `kingmaker.db.pre-v27.bak` is the automatic one. `KINGMAKER_DATA_DIR` moves the whole data
  folder (DB, sessions, cookie key).
