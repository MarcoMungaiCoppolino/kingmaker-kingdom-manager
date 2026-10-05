# 11. Tests and tools

## The rule before everything

**Never work on the live save.** `saves/kingmaker.db` is the table's game, opened by the app on
port 8080. Every test, every verification app, every script runs on a **copy** in a separate
`KINGMAKER_DATA_DIR`; the test app on **8081** (`launch_test.py` refuses to start if the data
folder is `saves/`).

```bash
# a copy (with the WAL, or the last piece is lost)
cp saves/kingmaker.db saves/kingmaker.db-wal <copy-folder>/
KINGMAKER_DATA_DIR=<copy-folder> python launch_test.py    # http://127.0.0.1:8081
```

## The suite — `tests/`

```bash
python tests/run_all.py                     # the whole suite
python tests/run_all.py test_lake.py        # a single file
```

`run_all.py` builds **a scene from scratch** (`scene.py` → `tests/scene/`, not versioned:
three test accounts, four characters with neutral fantasy names, a wagon, the grid with the
terrains alone from `scene_hexes.json`, and a one-pixel placeholder as the map image in the
scene's own `assets/` folder — `KINGMAKER_ASSETS_DIR` points there, so no test depends on
the images of this PC), then runs every `test_*.py` in its own process,
resetting the scene first (`stage.py`: the test river, the boat, everyone in their place, no
journey in progress) so a file does not inherit the state left by another, and adds up the
counts. The tests print ` ok`/` NO` per assertion and end with `N/M passed`. Today they are
**43 files, ≈1,160 assertions**, all green. `helpers.py` keeps the pieces of the old model the
tests use to build scenes (`banks_between_vertices`, `add_cut`), `silence` to replace a function
of the map in all its modules, and `map_source` for the tests that read the code. The runner
has no dependency: no pytest.

| Test | What it covers |
|---|---|
| `test_atoms`, `test_ring`, `test_faces`, `test_bank_model`, `test_atom_count` | the measured geometry: 24 atoms, 36 sides, crossings, faces, the count in quarters |
| `test_borders`, `test_cut`, `test_center`, `test_eraser`, `test_crossings`, `test_stretches` | the water brushes, bridges and fords, the eraser, the stretches |
| `test_waterways`, `test_current`, `test_route`, `test_lake`, `test_water_atoms`, `test_swimming`, `test_chart` | the network, the currents, the routes, the lakes, the boat on the junctions, swimming, the charts |
| `test_shores`, `test_arrival`, `test_pointed_shore`, `test_rendezvous`, `test_together`, `test_arrow`, `test_traces` | travel on foot: shores, arrival in the pointed piece, rendezvous, group, ruler, the others' arrows |
| `test_badges`, `test_marker_clicks`, `test_boarding`, `test_edges` | markers, groups, vehicles as units, the edge of the map, routes in progress |
| `test_real_map`, `test_map_banks`, `test_redraw`, `test_water_off` | on the real scene: connectivity unchanged, redraw with people inside, model switched off |
| `test_onair`, `test_prefix`, `test_map_view`, `test_veil`, `test_modes` | prefix, fog, view, click modes |
| `test_cleanup`, `test_security` | the defects of the 0.9 cleanup review (listed in the changelog) and the security review: schema, reset, frozen costs, boats and land journeys, ruler permissions, caches, journal, the brake by address, escapes, the last admin |
| `test_structures`, `test_migration_v27`, `test_i18n` | structure ids and effects, the schema 27 migration on `fixtures/v26.db`, the two languages per window and the catalog checkers |

How they are made, to write a new one:

```python
from kingmaker import permissions
from kingmaker.state import STATE
from kingmaker.ui import hexmap, theme
import helpers
theme.notify = lambda *a, **k: None          # no interface
permissions.can = lambda *a, **k: True
helpers.silence("_redraw_travel")             # in every module of the map
A, C = STATE.archive, STATE.campaign
results = []
# … the scene, then the assertions:
results.append(("what must hold", condition))
for name, ok in results: print(f" {'ok' if ok else 'NO'}  {name}")
print(f"{sum(1 for _n, ok in results if ok)}/{len(results)} passed")
```

The tests call **the app's functions**, not the interface: `hexmap._compute_journey`,
`_apply_journey`, `daily.advance_one_day`, `travel_field`… When a user is needed, `theme.user`
is faked (a class with the admin role). Without a window `i18n.current()` is English, so the
messages the tests look for are the English ones. The golden rules learned at our expense: after
`update_character` call `STATE.load()` if a panel keeps a copy; `stage` resets the Swim Speed
and the crossings too, because a test left them on the others.

## The four checkers

```bash
python tools/check_names.py     # no undefined name anywhere (symtable)
python tools/check_i18n.py      # catalogs whole, no t() at module level, no shadowed t
python tools/check_texts.py     # no label, chip or caption written straight into a ui.* call
python tools/check_data.py      # both languages have the same shape; every id referenced exists
```

`test_i18n.py` runs the last three, so the suite fails when a catalog is broken or a text
bypasses it. `check_texts.py` reads the AST: a constant string (or an f-string with words in
it) given to a `ui.*` / `theme.*` call, or used as a table column label, is reported. It is
what found the last Italian labels of 1.0.0 — the hex status counts, the identity chips, the
Manual's table headers — and, along the way, three translated strings used as identifiers
(a commodity id, an enum sent to the ruler, a kind compared later), which is the worse bug.

## The ruler benches

`tests/benches/bench10.html` and `bench11.html` load `travel_drag.js` in the browser and
compare it with the server: 575 water configurations and 1,725 courses (`atom_cases.json`, from
`atom_cases.py`), and the drawn roads with their cost and their points (`atom_field.json`, from
`dump_atoms.py` with `KINGMAKER_DATA_DIR=tests/scene`). They are served from the **root of the
repo** with `python -m http.server 8091` and opened at
`http://127.0.0.1:8091/tests/benches/bench10.html`: they must say **EQUAL**. They are the only
verification of the JavaScript: there is no Node on the author's machine.

## The release tools

`tools/` also keeps the one-off tools of release 1.0.0, for the record: `rename.py` and
`rename_map.csv` (the token-level renamer that turned the Italian identifiers, keys and schema
into English), `comments.py`, `comments_js.py`, `test_labels.py` (the comment and label
translation pipeline), `extract_strings.py` (the interface texts into the catalogs),
`split_texts.py` (mechanics apart from texts), `split_data.py` (structure ids and effects),
`fetch_aon.py` and `aon_to_texts.py` (the English rules texts from Archives of Nethys), and
`rename_local.py`.

## The build

`packaging/build.py` freezes the app with PyInstaller, smoke-tests what it built and makes
the Windows installer or the Linux tarball; `.github/workflows/release.yml` runs it on every
version tag. Chapter 12 has the details. `tests/test_launcher.py` covers the launcher's logic;
`tests/test_sync.py` the cloud, against the one-process Dropbox of `tests/fake_dropbox.py`;
`tests/test_refresh.py` the refresh bus of chapter 4, with fake panels and windows;
`tests/test_windows.py` eight real windows (NiceGUI's user simulation, no browser), random
changes, every panel in front compared with a fresh render of itself; `tests/test_layers.py`
the map's two layers and the compact hex outline; `tests/test_screens.py` every launcher window
on small screens, every control in reach (it needs a display, and says so when there is none);
`tests/test_farmland.py` Farmland, influence and Consumption; `tests/test_shared_rolls.py` a
roll seen from three windows (admin, GM, player), in each one's language, with a hex under the
fog kept from the player.

## The figures

- `docs/manual/water_figures.py`: the figures of chapter 9, from the real geometry.
- `docs/manual/manual_figures.py`: the figures of this manual, from the drawing functions of
  the app on the test scene. Regenerated with `KINGMAKER_DATA_DIR=tests/scene python
  docs/manual/manual_figures.py` (after `python tests/run_all.py`, which builds the scene).

## The screenshots

The images in `img/screenshots/` were taken from the test app (`python tests/launch_scene.py`,
on 8081, with the scene built from scratch: no data of the table), after a login made by hand
with one of the test accounts, in release 0.9 — hence the Italian labels. The page photographed
itself with `html2canvas` loaded in the browser and sent the PNG to a small local receiver;
then Pillow reduced them to 1400 px in JPEG. To retake them, repeat the round: there is no
script, because the login is not automated. `launcher.jpg` is the tkinter window of chapter 12,
grabbed with Pillow's `ImageGrab` on a scratch game folder, and so is `wizard.jpg`. The
pictures of the wizard itself, `kingmaker/launcher/guide/*.png`, are crops of the Dropbox App
Console grabbed from the screen while the owner was signed in, the account avatar and the
App key blurred.

## Verifying in the browser

Claude's browser pane cannot enter the app (it types no passwords): the visual verification is
done by whoever plays, on 8081. What can be verified without entering: the login page and its
language toggle, the SVGs generated by the server (like the figures), the benches, and
everything the tests exercise.
