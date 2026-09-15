"""Switching the water borders off brings the journey back as it was, losing nothing."""
from kingmaker.geometry import hexgrid
from kingmaker.access import permissions
from kingmaker import travel as v
from kingmaker.access import view as view_mod
from kingmaker.state import STATE
from kingmaker.ui import hexmap, theme
import helpers

theme.notify = lambda *a, **k: None
theme.mark_dirty = lambda *a, **k: None

A, C = STATE.archive, STATE.campaign
m = STATE.k["map"]
ORIENT = m["orientation"]
COL, ROW_ = int(m["columns"]), int(m["rows"])
results = []


def inside(c):
    return 0 <= c[0] < COL and 0 <= c[1] < ROW_


class Fake:
    id, username, role = "check", "check", permissions.ADMIN
    active = True


view = view_mod.MapView(Fake(), STATE)
difficulty = A.campaign_difficulty(C)
vehicles = {x["id"]: x for x in A.list_stable(C)}
group = [p for p in STATE.characters() if p["name"] == "Corin"][:1]

# --- a river that really divides is prepared -----------------------------
for k in list(A.campaign_borders(C)):
    A.set_border(C, (k[0], k[1]), (k[2], k[3]), None)
for c in list(A.campaign_banks(C)):
    A.set_banks(C, c, None)
COORD = (9, 4)
A.set_banks(C, COORD, helpers.banks_between_vertices(0, 3))
near = hexgrid.neighbours(*COORD, ORIENT)[0]
A.set_border(C, COORD, near, "water")


def mode():
    return hexmap._crossing({"aboard": False}, group, vehicles, view,
                                   difficulty)


# --- 1. on: everything counts --------------------------------------------
STATE.k["map"]["waters_active"] = True
is_on = mode()
results.append(("on: the borders count", len(is_on.borders) == 1))
results.append(("on: the banks count", len(is_on.banks) == 1))
results.append(("on: the marked side is closed",
              is_on.passage is not None
              and is_on.passage(COORD, near) is None))
lit_exits = {d for _n, d in v.steps_from((COORD[0], COORD[1], 0), ORIENT,
                                           is_on.banks)}
results.append(("on: from a shore one leaves by three sides only",
              len(lit_exits) <= 3))

# --- 2. off: the journey goes back as it was -----------------------------
STATE.k["map"]["waters_active"] = False
is_off = mode()
results.append(("off: no border looked at", is_off.borders == {}))
results.append(("off: no bank looked at", is_off.banks == {}))
results.append(("off: no side is closed", is_off.passage is None))
off_exits = {d for _n, d in v.steps_from((COORD[0], COORD[1], 0), ORIENT,
                                           is_off.banks)}
results.append(("off: from that hexagon one leaves by every side",
              len(off_exits) == 6))

# --- 3. switching off does not erase -----------------------------------
results.append(("off: the borders are still in the database",
              len(A.campaign_borders(C)) == 1))
results.append(("off: the banks are still in the database",
              len(A.campaign_banks(C)) == 1))
# Lake and River are no longer terrains: an old save that marked a hex so
# loses the mark at load, and keeps whatever dry terrain it also had.
from kingmaker.storage import migrations   # noqa: E402
old_save = {"hexes": {"1,1": {"terrains": ["lake", "plains"]}, "2,2": {"terrains": ["river"]},
                      "3,3": {"terrains": ["forest"]}}}
results.append(("an old Lake terrain is dropped at load",
              migrations.drop_water_terrains(old_save)
              and old_save["hexes"]["1,1"]["terrains"] == ["plains"]
              and old_save["hexes"]["2,2"]["terrains"] == []
              and old_save["hexes"]["3,3"]["terrains"] == ["forest"]
              and not migrations.drop_water_terrains(old_save)))

# --- 4. and switching back on everything comes back -----------------------
STATE.k["map"]["waters_active"] = True
again = mode()
results.append(("back on: the borders come back", len(again.borders) == 1))
results.append(("back on: the banks come back", len(again.banks) == 1))

# --- 5. the drawing follows the switch -----------------------------------
sel = {"show_borders": True, "col": None, "row": None}
STATE.k["map"]["waters_active"] = False
results.append(("off: no water is drawn",
              hexmap.WATER_COLOR not in hexmap._svg_grid(sel, view)))
STATE.k["map"]["waters_active"] = True
results.append(("on: the water is drawn",
              hexmap.WATER_COLOR in hexmap._svg_grid(sel, view)))

width = max(len(n) for n, _ in results)
for name, ok in results:
    print(("  ok  " if ok else " NO   ") + name.ljust(width))
print(f"\n{sum(1 for _, ok in results if ok)}/{len(results)} passed")
