# Changelog

All notable changes to Kingmaker Kingdom Manager are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/). The narrative behind each version — what was tried,
what broke, what was learned — is in [docs/devlog.md](docs/devlog.md).

The versions before 1.0.0 were never tagged: the app was played from a working copy and the
numbers below were assigned afterwards, one per day of development, from the session history.

## [1.0.0] — 2026-09-15

The first public release. The whole codebase, the storage and the documentation are in
English; the interface is bilingual.

### Added
- **Bilingual interface (English / Italian)** with a per-user preference: the IT/EN toggle in
  the header and on the login page; the browser's language is used before a choice is made.
  Every text of the interface lives in `kingmaker/locale/lang/`, texts sent to other windows are
  rendered in each viewer's language.
- **English rule texts** transcribed from Archives of Nethys (structures, activities, feats,
  vehicles, terrains, tables), with the source URL recorded per file; the Italian texts from
  pf2.altervista.org remain. Mechanics and texts are now separate files
  (`kingmaker/rules/data/*.json` and `kingmaker/rules/data/lang/<code>/`).
- Structures have stable ids; their kingdom effects are structured data instead of prose
  parsed at runtime.
- `README.md` / `README.it.md`, a user guide in both languages, the code manual in English,
  this changelog and the devlog.
- `LICENSE` (MIT), `OPEN_GAME_LICENSE.md` (OGL 1.0a with Section 15), `NOTICE.md` (Paizo
  Community Use Policy).
- `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `.env.example` — **untested**, see the
  README.
- Four checkers in `tools/`: `check_names.py` (no undefined name), `check_i18n.py`
  (catalogs complete, no `t()` at import time), `check_texts.py` (no label or caption written
  straight into a `ui.*` call, bypassing the catalogs), `check_data.py` (both languages have
  the same shape, every referenced id exists); `tests/test_i18n.py` runs the last three.
- `KINGMAKER_LANG`, `KINGMAKER_HTTPS`, `KINGMAKER_TRUST_PROXY` settings.
- **Metres or feet**, chosen per person with the m/ft button in the header (5 ft = 1.5 m;
  feet by default with the English interface). Speeds stay stored in metres; every field and
  label follows the choice, and the Travel Speed line shows miles per hour and per day.
- **Save file backup**: in the Manual tab the administrator downloads the whole database
  (`kingmaker-<date>.db`) and can load one back; the current save is copied next to itself
  before being replaced, and an old file is migrated on the way in.
- A **GM fog** slider next to the players' one, for the veil on the GM screens.
- The grid calibration accepts **typed numbers** for radius and origin, next to the sliders.
- **Lake names** are drawn on the map, above the water lines (below them while the Waters
  mode is on), with a button in the Waters box to hide them.
- Schema 28: `users.units` column.

### Changed
- **Everything renamed to English**: modules (`archivio`→`archive`, `viaggio`→`travel`,
  `ui/mappa/`→`ui/hexmap/`, …), identifiers, dictionary keys, JavaScript globals and events, CSS
  classes, comments and docstrings, the test suite (`prove/`→`tests/`), the tools.
- **Package layout by layer**: the twenty-four flat modules are grouped into `rules/`
  (loader, calendar, data), `locale/` (i18n, units, catalogs), `geometry/`, `water/`,
  `travel/`, `storage/`, `access/`, `media/`, and inside `ui/` into `tabs/`, `hexmap/` (the
  map package, facade in `__init__.py`) and `static/` (the browser scripts). Imports are
  absolute; module names are unchanged.
- **Storage schema 27**: tables, columns, document keys and stored enum values are English.
  Existing saves are migrated automatically at the first start (see *Upgrading*).
- Tabs are addressed by language-neutral ids; the refresh bus and the ruler no longer compare
  labels.
- The test scene uses neutral fantasy names; three tests that grepped the source for Italian
  literals now look for catalog keys.
- `avvia.py` → `launch.py` (`--lan`, `--port`, `--no-browser`, `--online [TOKEN]`),
  `avvia_prova.py` → `launch_test.py`; the window title is «Kingmaker Kingdom Manager».
- **Lake and River are no longer terrains**: water is drawn on top of the terrain (borders,
  cuts, lakes) and only the drawn water counts. The two entries stay in the data as `legacy`
  for the heartland table; hexes marked Lake or River in an old save lose the mark at the
  first start. The image reading no longer proposes «lake hexes».
- Asset folders renamed at first start: `assets/personaggi` → `characters`,
  `veicoli` → `vehicles`, `miniature` → `thumbnails`.

### Fixed
- **Security** (second review, each with a test in `tests/test_security.py`): usernames and
  every user-typed text escaped wherever they reach SVG or HTML markup, including the ruler
  labels drawn in the browser; usernames restricted to `[A-Za-z0-9._-]{2,32}`; every mutating
  action re-checks the permission server-side (`EDIT_KINGDOM` was never checked), so a
  spectator is read-only by construction; an open window re-reads its identity when the
  archive changes (deactivated → logged out, changed role → applied); password change refused
  while impersonating and the self-change asks the current password; login throttling behind
  a proxy (`X-Forwarded-For` only with `KINGMAKER_TRUST_PROXY`, per-address bucket off under
  On Air); ruler payloads capped and validated before use; `Secure` cookie with
  `KINGMAKER_HTTPS`; session rotation on login and logout; the background image name goes
  through the safe-name filter; the last active administrator cannot be demoted, deactivated
  or deleted, nor can one change one's own role.
- The water route drawn by hand with the ruler was replaced by the cheapest one on release:
  the payload check dropped the hex of every point, and a drawn step onto a shared vertex
  counted in the next hex did not match the server's steps. Both fixed; the drawn junctions
  are kept. On the water the direction now comes from the **line** the cursor is on and the
  steps from its junctions, each taken once the cursor has travelled two thirds of the side
  leading to it and undone when it comes back halfway, the side just travelled never being
  offered backwards (a dashed preview shows the line being entered);
  thresholds are screen pixels, and zoomed far out a line is one step. A confluence no longer
  picks a line by itself.
- A boat's route was not shown to the other windows while it was being steered or once it
  was prepared; now it is published like a land journey, and whoever can see the boat's hex
  sees its arrow.
- Hiding the water lines with the icon of the Waters button had no effect once the layer was
  cached.
- A boat could sail to the vertices of a lake cell that lie outside the drawn shape: the lake
  mesh now holds only the points inside the ring (or on it).
- `launch.py --online` ignored its token argument.
- A cosmetic rename had shadowed `hexgrid.neighbours` inside `common_vertex`.

### Upgrading
- The save is migrated to schema 27 at the first start. `Archive` checkpoints the write-ahead
  log and copies `saves/kingmaker.db` to `saves/kingmaker.db.pre-v27.bak` **before** touching
  it; keep that file until you have played a session. Old JSON exports are recognised and
  translated on import.
- Any private script that read the Italian tables or document keys must be updated
  (`legacy_names.py` holds the maps).
- `saves/regno.json` is still imported into an empty database, then left where it is.

## [0.9.0] — 2026-09-13

### Added
- The code manual (`docs/manuale/`, 11 chapters) and the figures generated from the app's
  own drawing functions; screenshots of every tab.
- **Ctrl+click** on a badge adds people and vehicles one at a time; «Take the chosen».
- Reconnoiter from the hex box (`reconnaissance_cost` wired).
- A cleanup review (`docs/manuale/11-pulizia.md`): dead code removed, duplicates merged, the
  map split into the `ui/mappa/` package with `hexmap.py` as a facade, caches keyed on the
  archive revision, the journal moved into its own table.

### Fixed
- First security pass: ruler events check `PLAN_TRAVEL`; texts from the JSON escaped in
  `ui.html`; the login brake also counts by address; `_attempts` no longer grows forever;
  «Start over» empties every campaign table.
- Frozen journey costs lost the detour inside a cut hex; a boat followed a land journey; the
  map view was built four times per redraw.

## [0.8.1] — 2026-09-12

### Fixed
- Rounding of route costs done identically by the server and the dragged arrow.
- The two rulers (land and water) send a single cost per step; the browser rebuilt paths
  through inner bridges.

### Changed
- Docstrings trimmed to the «why»; the manual chapters started.

## [0.8.0] — 2026-09-11

### Changed
- **The hex as 24 atoms**: water lines close borders between fixed pieces instead of creating
  sections; a crossing of a clean hex is exactly 4 atoms in all 15 directions, so ¼ per atom
  reproduces the rules without calibration. The travel node became `(col, row, gate)`.
- The plan charges the detour around water inside a hex; the dragged ruler counts by atoms
  with the same layered Dijkstra as the server (`bench10`, `bench11` compare the two).
- Markers drawn per piece, sized by the piece; groups show a count; the badge of a boat sits
  on its junction.

### Added
- Inner bridges and fords as reopened atom borders; fords on the whole line, bridges on the
  stretch; swimming (`swim_speed_m`) crosses without a boat.

## [0.7.0] — 2026-09-10

### Added
- Boarding and landing on the map: vehicles are placed in a hex, one boards from the same
  piece, one lands ashore; the transport tab became the depot.
- Paths may cross themselves and pass the same hex twice; the dragged arrow fades on the last
  three stretches; blocked steps flash red, vibrate and say why.
- The travel arrow is shown live to the other windows, with its author's colour.

### Fixed
- The first drag step takes the shortest way; filling a jump goes straight only.

## [0.6.0] — 2026-09-09

### Changed
- Sections are the **faces** of the planar drawing of the water (`sezioni.facce_di`), not
  groups of sides; markers and arrows have a point per section; section numbers are derived
  from saved points, never stored.
- Crossings are stored as two shore points plus the point on the water.

### Added
- The water route on atom sides: junctions (corners, center, twelve inner points), pieces and
  edges, ¼ and ½ activity, double upstream; lakes as a triangular mesh of still water.

## [0.5.0] — 2026-09-08

### Added
- Water vehicles: routes along drawn rivers, currents (upstream/downstream brush), lakes drawn
  by hand, «⛵ By river» next to the land plan.
- The water chart (JSON export/import of borders, banks, crossings, currents with the grid
  calibration), the assisted reading of the water from the image (a proposal to accept).
- Thumbnails for portraits and tokens; the On Air prefix on SVG addresses.

### Changed
- Performance: differential saves, the SVG ground layers cached per window, the refresh bus
  redraws only panels in the foreground tab.

## [0.4.0] — 2026-09-07

### Added
- Vehicles from the rules catalogue (45), depots by kind (land, water, air), «All aboard».
- Water borders (water, ford, bridge) between hexes and banks inside a hex; the Waters mode
  with its brushes and eraser.
- **SQLite** storage (`saves/regno.db`) replacing the JSON file; separate tables for hexes,
  users, characters, vehicles, journeys and water.

## [0.3.0] — 2026-09-06

### Added
- Characters with portraits and tokens, linked to accounts and to leadership roles; markers
  on the map; the row of portraits.
- Travel: Dijkstra over the hex grid with the rules' costs, activities per day from Speed,
  forced march, unknown hexes counted as the worst, the ruler dragged in the browser, the
  rendezvous of a scattered party, separate journeys.
- The clock: Absalom Reckoning calendar, days passing on the server, journeys advancing, the
  Kingdom Turn at the end of the month.

## [0.2.0] — 2026-09-05

### Added
- Accounts and roles (admin, GM, player, spectator) with PBKDF2 passwords and login
  throttling; impersonation for the administrator.
- The GM screen: fog of war per player, secret features and hidden fields, «See as the
  players».
- Grid calibration on the uploaded map image; the terrain veil; the map remembers the scroll.
- LAN and NiceGUI On Air publishing from `avvia.py`.

## [0.1.0] — 2026-09-03

### Added
- The kingdom sheet, the guided creation, the Kingdom Turn with every activity and its four
  outcomes proposed and confirmed, the settlements with the Urban Grid and the 76 structures,
  the hex map with statuses, terrains and features, the in-app Manual, JSON save.
