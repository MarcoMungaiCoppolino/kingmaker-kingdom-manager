# -*- coding: utf-8 -*-
"""The defects found reading the code (the 0.9 cleanup review, listed in the changelog): each
with the proof that today it is gone."""
import shutil
import sqlite3
import tempfile
from pathlib import Path

from kingmaker.storage import archive as archive_mod
from kingmaker.access import auth, permissions
from kingmaker.geometry import hexgrid
from kingmaker import travel as v
from kingmaker.state import STATE
from kingmaker.ui import hexmap, theme
import helpers

theme.notify = lambda *a, **k: None
theme.mark_dirty = lambda *a, **k: None
theme.refresh_panels = lambda *a, **k: None
permissions.can = lambda *a, **k: True
helpers.silence("_redraw_travel", lambda *a, **k: None)
helpers.silence("_send_field", lambda *a, **k: None)

A, C = STATE.archive, STATE.campaign
m = STATE.k["map"]
orient = m["orientation"]
size = float(m["size"])
origin = (float(m["origin_x"]), float(m["origin_y"]))
results = []


class Allowed:
    id, username, role = "check", "check", permissions.ADMIN
    active = True


theme.user = lambda: Allowed()

# --- 1. D.1: a new database has every column from the CREATE TABLEs -------
conn = sqlite3.connect(":memory:")
conn.executescript(archive_mod.SCHEMA)
missing_items = []
for _ver, table, definition in archive_mod.Archive.ADDED_COLUMNS:
    name = definition.split()[0]
    columns = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    if name not in columns:
        missing_items.append(f"{table}.{name}")
results.append(("every column added later is in the CREATE TABLE too: " + ", ".join(missing_items),
              not missing_items))
conn.close()

# --- 2. D.2: resetting empties the whole campaign -------------------------
folder = tempfile.mkdtemp()
if True:
    arch = archive_mod.Archive(Path(folder) / "kingmaker.db")
    arch.write("x", {"name": "Prova", "hexes": {}})
    arch.create_character({"id": "p1", "campaign_id": "x", "user_id": None, "name": "Uno",
                           "speed_m": 7.5, "con_mod": 0, "color": "#d7b263",
                           "active": 1, "created_at": "2026-01-01T00:00:00"})
    arch.set_border("x", (1, 1), (2, 1), "water")
    arch.reveal("x", [(1, 1)], "*")
    before = (len(arch.list_characters("x")), len(arch.campaign_borders("x")),
             arch.count_visible("x"))
    arch.reset("x")
    after = (len(arch.list_characters("x")), len(arch.campaign_borders("x")),
            arch.count_visible("x"))
    results.append(("before resetting there was something", before == (1, 1, 1)))
    results.append(("afterwards there is nothing left: characters, water, fog", after == (0, 0, 0)))
    results.append(("resetting does not touch the accounts table",
                  "users" not in archive_mod.Archive.CAMPAIGN_TABLES))
    results.append(("every write raises the revision", arch.rev > 0))
    arch.close()
shutil.rmtree(folder, ignore_errors=True)

# --- 3. D.4: the costs frozen at departure include the detour ------------
# A chord from one vertex to the other: entering and leaving from the two
# ends of the same shore costs one more atom (the detour), and that quarter
# was in the plan's total but not in the per-waypoint costs the day consumes.
VEHICLE = (17, 8)
nb_vehicle = [tuple(c) for c in hexgrid.neighbours(VEHICLE[0], VEHICLE[1], orient)]
A.set_banks(C, VEHICLE, helpers.banks_between_vertices(0, 3))
banks = hexmap.sections_map()
water = A.campaign_water(C, orient)
crossings = A.campaign_crossings(C)
view = hexmap._current_view({})
difficulty = A.campaign_difficulty(C)
cost_of = lambda c: hexmap._cost_for(view, difficulty, c, False)
with_ring = None
for a in range(6):
    for b in range(6):
        if a == b:
            continue
        course = [nb_vehicle[a], VEHICLE, nb_vehicle[b]]
        rings, _tr = v.atom_count(course, banks, water, crossings, orient, cost_of,
                                    None, None, None)
        if rings.get(VEHICLE):
            with_ring = (course, {c: g for c, g in rings.items() if g})
            break
    if with_ring:
        break
results.append(("there is a pair of sides forcing a detour", with_ring is not None))
if with_ring:
    course, rings = with_ring
    waypoints = [((c[0], c[1]), STATE.existing_hex(c[0], c[1]) or {}, difficulty.get(c))
             for c in course[1:]]
    plan = v.plan_(waypoints, 7.5, "", False, [0], None, course[0], False,
                        v.inner_on_course(course, banks, crossings, orient, cost_of),
                        rings)
    frozen = v.waypoint_costs(plan)
    results.append(("the plan carries the detour on its waypoint",
                  any(t.ring > 0 for t in plan.waypoints)))
    results.append(("and the sum of the frozen costs is the plan's total",
                  abs(sum(frozen) - plan.total_cost) < 1e-6
                  and sum(frozen) > sum((t.cost or 0) for t in plan.waypoints)))
A.set_banks(C, VEHICLE, None)

# And from the ruler to the departure: what the journey writes is the total.
char = next(p for p in STATE.characters() if p["name"] == "Corin")
DA = (char["hex_col"], char["hex_row"])
neighbours = [tuple(c) for c in hexgrid.neighbours(DA[0], DA[1], orient)]
IN_BETWEEN = neighbours[0]
BEYOND_EDGE = tuple(hexgrid.neighbours(IN_BETWEEN[0], IN_BETWEEN[1], orient)[0])
A.set_border(C, DA, IN_BETWEEN, "ford")


def window(destination):
    return {"travel_mode": "choose", "travel_pcs": [char["id"]],
            "col": destination[0], "row": destination[1], "forced_march": False,
            "together": True, "aboard": False, "player_preview": False,
            "travel_vehicle": None, "plan": None, "path": [], "branches": [],
            "singles": [], "rendezvous": None, "route": None, "by_river": False,
            "land": None, "arrival_pos": None}


mine = window(BEYOND_EDGE)
hexmap._compute_journey(mine, None)
plan = mine.get("plan")
results.append(("the journey is computed", plan is not None and plan.possible))
if plan and plan.possible:
    before_journeys = {vg["id"] for vg in A.list_journeys(C, "in_progress")}
    hexmap._apply_journey(mine, None, [A.character(char["id"])], DA, BEYOND_EDGE, immediately=False)
    new = next((vg for vg in A.list_journeys(C, "in_progress")
                  if vg["id"] not in before_journeys), None)
    results.append(("the journey departs", new is not None))
    results.append(("and what it wrote is the plan's total, sides included",
                  new is not None
                  and abs(sum(new["costs"]) - plan.total_cost) < 1e-6
                  and abs(sum(new["legs"][0]["costs"]) - plan.total_cost) < 1e-6))
    if new:
        A.update_journey(new["id"], status="cancelled")
A.set_border(C, DA, IN_BETWEEN, None)

# --- 4. D.11: a boat does not follow whoever goes by land ----------------
dagny = next(p for p in STATE.characters() if p["name"] == "Dagny")
boat = next(x for x in A.list_stable(C) if x["name"] == "La Lontra")
results.append(("in the scene Dagny is aboard the placed boat",
              dagny["stable_id"] == boat["id"] and (boat["hex_col"], boat["hex_row"]) == (9, 4)))
hexmap.move_characters([dagny["id"]], (9, 6), coming_from=(9, 5))
boat_after = A.stable_vehicle(boat["id"])
dagny_after = A.character(dagny["id"])
results.append(("by land the boat stays where it was",
              (boat_after["hex_col"], boat_after["hex_row"]) == (9, 4)))
results.append(("and whoever went by land is no longer aboard",
              dagny_after["stable_id"] is None
              and (dagny_after["hex_col"], dagny_after["hex_row"]) == (9, 6)))
A.update_character(dagny["id"], stable_id=boat["id"], hex_col=9, hex_row=4)
hexmap.move_characters([dagny["id"]], (10, 4), coming_from=(9, 4), stable_id=boat["id"])
boat_after = A.stable_vehicle(boat["id"])
results.append(("with the journey's vehicle instead the boat moves",
              (boat_after["hex_col"], boat_after["hex_row"]) == (10, 4)))
results.append(("and whoever was aboard stays there",
              A.character(dagny["id"])["stable_id"] == boat["id"]))

# --- 5. D.5: the ruler events check the permission again -----------------
mine = window(BEYOND_EDGE)
permissions.can = lambda _u, action, *a, **k: action != permissions.PLAN_TRAVEL
hexmap._dragged_target(mine, None, {"path": [list(DA), list(IN_BETWEEN)]})
results.append(("without the permission the ruler release computes nothing",
              mine.get("plan") is None))
permissions.can = lambda *a, **k: True
hexmap._dragged_target(mine, None, {"path": [list(DA), list(IN_BETWEEN)]})
results.append(("with the permission it does", mine.get("plan") is not None))

# --- 6. D.12 / E.1 / E.2: the caches last until someone writes -----------
mine = window(BEYOND_EDGE)
v1 = hexmap._current_view(mine)
results.append(("the view is not rebuilt at every panel",
              hexmap._current_view(mine) is v1))
s1 = hexmap.sections_map()
r1 = hexmap.waters_network()
results.append(("nor the sections, nor the water network",
              hexmap.sections_map() is s1 and hexmap.waters_network() is r1))
A.set_banks(C, (2, 2), [[0, 1, 2], [3, 4, 5]])
results.append(("but after a write they are redone",
              hexmap.sections_map() is not s1 and hexmap.waters_network() is not r1
              and hexmap._current_view(mine) is not v1))
results.append(("and say the new thing", (2, 2) in hexmap.sections_map()))
A.set_banks(C, (2, 2), None)

# --- 6bis. E.6: the log is in a table, not in the document ---------------
STATE.record("log test", "check", "a detail")
last_one = STATE.journal(1)
results.append(("a recorded row is read back from the table",
              bool(last_one) and last_one[0]["text"] == "log test"
              and last_one[0]["detail"] == "a detail"))
results.append(("and the kingdom document no longer carries the log", "log" not in STATE.k))
results.append(("but the export does", '"log"' in STATE.export()))

# --- 6ter. E.3: the map's ground layers are redone only if needed --------
mine = window(BEYOND_EDGE)
view = hexmap._current_view(mine)
hexmap._svg_grid(mine, view)
ground_1 = mine.get("_ground")
hexmap._svg_grid(mine, view)
results.append(("the grid is not rebuilt if nothing changes",
              ground_1 is not None and mine.get("_ground") is ground_1))
STATE.k["_rev"] = STATE.k.get("_rev", 0) + 1     # what mark_dirty does
hexmap._svg_grid(mine, hexmap._current_view(mine))
results.append(("and is redone when something changes", mine.get("_ground") is not ground_1))

# --- 6quater. G.6: the login brake holds by address too -------------------
auth._attempts.clear()
for _i in range(auth.MAX_ATTEMPTS_PER_IP):
    auth._mark_failure("ip:10.0.0.1")
results.append(("after too many attempts from an address one waits, with any name",
              auth.remaining_wait("nome-mai-visto", "10.0.0.1") > 0
              and auth.remaining_wait("nome-mai-visto", "10.0.0.2") == 0))
auth._attempts.clear()

# --- 6quinquies. ctrl+click in the group box: more than one at a time ----
aldric = next(p for p in STATE.characters() if p["name"] == "Aldric")
brenna = next(p for p in STATE.characters() if p["name"] == "Brenna")
dagny = next(p for p in STATE.characters() if p["name"] == "Dagny")
boat = next(x for x in A.list_stable(C) if x["name"] == "La Lontra")
A.update_character(dagny["id"], stable_id=boat["id"], hex_col=9, hex_row=4)
mine = window(BEYOND_EDGE)
hexmap._apply_choice(mine, None, [aldric["id"], brenna["id"]])
results.append(("two people chosen with ctrl leave together, without a vehicle",
              mine["travel_pcs"] == [aldric["id"], brenna["id"]] and mine["travel_vehicle"] is None))
mine = window(BEYOND_EDGE)
hexmap._apply_choice(mine, None, [aldric["id"]], boat["id"])
results.append(("a vehicle chosen with ctrl carries those on it, plus whoever was added",
              mine["travel_vehicle"] == boat["id"] and mine["aboard"]
              and set(mine["travel_pcs"]) == {dagny["id"], aldric["id"]}))
results.append(("and nobody twice", len(mine["travel_pcs"]) == len(set(mine["travel_pcs"]))))

# --- 7. D.8: failed attempts do not pile up forever ----------------------
auth._attempts.clear()
import time as _t
auth._attempts["old"] = (3, _t.monotonic() - 10 * auth.WAIT_AFTER_ATTEMPTS - 5)
auth._mark_failure("new")
results.append(("an old entry vanishes at the first following failure",
              "old" not in auth._attempts and "new" in auth._attempts))
auth._attempts.clear()

width = max(len(n) for n, _ in results)
print()
for name, ok in results:
    print(f" {'ok' if ok else 'NO'}  {name}")
print(f"\n{sum(1 for _n, e in results if e)}/{len(results)} passed")
