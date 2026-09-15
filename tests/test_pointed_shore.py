# -*- coding: utf-8 -*-
"""The right button reaches the pointed shore even when the cheapest door of
the hexagon opens on the other one: the road is searched up to the shore, as
the ruler does, and not up to the hexagon."""
from kingmaker.geometry import hexgrid, sections
from kingmaker.access import permissions
from kingmaker import travel as v
from kingmaker.state import STATE
from kingmaker.ui import hexmap, theme
import helpers

told_ones = []
theme.notify = lambda text, *a, **k: told_ones.append(str(text))
theme.mark_dirty = lambda *a, **k: None
theme.refresh_panels = lambda *a, **k: None
theme.save_and_refresh = lambda *a, **k: None
theme.save_and_refresh_panels = lambda *a, **k: None
permissions.can = lambda *a, **k: True
permissions.can_on_character = lambda *a, **k: True
helpers.silence("_redraw_travel", lambda *a, **k: None)
helpers.silence("_send_field", lambda *a, **k: None)

A, C = STATE.archive, STATE.campaign
m = STATE.k["map"]
size = float(m["size"])
origin = (float(m["origin_x"]), float(m["origin_y"]))
orient = m["orientation"]
results = []


class Allowed:
    id, username, role = "check", "check", permissions.ADMIN
    active = True


theme.user = lambda: Allowed()

# --- the scene: a hexagon cut in two, without bridges, in the middle of the fields
for c in list(A.campaign_banks(C)):
    A.set_banks(C, c, None)
A.remove_crossings(C)
for k in list(A.campaign_borders(C)):
    A.set_border(C, (k[0], k[1]), (k[2], k[3]), None)
for vg in A.list_journeys(C, "in_progress"):
    A.update_journey(vg["id"], status="cancelled")
for x in A.list_stable(C):
    if x["vehicle"] == "barca_a_remi":
        A.delete_stable_vehicle(x["id"])
COORD = (9, 4)
A.set_banks(C, COORD, [[0, 1, 2], [3, 4, 5]])
banks = A.campaign_sections(C, orient)
faces = banks[COORD]
neighbours = [tuple(x) for x in hexgrid.neighbours(COORD[0], COORD[1], orient)]
for c in [COORD] + neighbours:
    STATE.hex(c[0], c[1])["terrains"] = ["plains"]
    for cc in hexgrid.neighbours(c[0], c[1], orient):
        STATE.hex(cc[0], cc[1])["terrains"] = ["plains"]
# One leaves from the neighbour beyond side 0: the cheapest door of 9,4 opens
# on shore 0. Shore 1 is across the river, and its door sits on the opposite
# side: one gets there only by going around.
FROM = neighbours[0]
char = next(p for p in STATE.characters() if not p.get("stable_id"))
A.update_character(char["id"], hex_col=FROM[0], hex_row=FROM[1],
                       pos_x=None, pos_y=None)
STATE.load()


def window():
    return {"travel_mode": "choose", "travel_pcs": [char["id"]],
            "col": COORD[0], "row": COORD[1], "forced_march": False,
            "together": True, "aboard": False, "player_preview": False,
            "travel_vehicle": None, "plan": None, "path": [], "branches": [],
            "singles": [], "rendezvous": None, "route": None, "by_river": False,
            "land": None, "arrival_pos": None, "nodes": (), "atom_stretches": {}}


def tip(bank):
    return hexmap.bank_point(COORD, bank, size, origin, orient, banks)


near_bank = v.bank_of_side(banks, COORD, 3) if hasattr(v, "bank_of_side") else 0
# From FROM (beyond side 0) one enters the shore that has side 0.
shore_this_side = next(i for i, f in enumerate(faces) if 0 in f.sides)
shore_beyond = 1 - shore_this_side

# --- 1. pointing the shore on this side: straight ------------------------
mine = window()
told_ones.clear()
hexmap._compute_journey(mine, None, arrival_point=tip(shore_this_side))
results.append(("pointing the shore one enters from, the path is two hexes",
              mine.get("path") == [FROM, COORD]))
results.append(("and one gets there", mine.get("arrival_pos") is not None
              and not any("cannot be reached" in x for x in told_ones)))

# --- 2. pointing the shore beyond: one goes around, one does not give up --
mine = window()
told_ones.clear()
hexmap._compute_journey(mine, None, arrival_point=tip(shore_beyond))
is_expected = sections.section_spot(faces, shore_beyond)
results.append(("pointing the shore beyond no warning arrives",
              not any("cannot be reached" in x for x in told_ones)))
results.append(("the journey ends in the pointed piece",
              mine.get("arrival_pos") is not None
              and abs(mine["arrival_pos"][0] - is_expected[0]) < 1e-6
              and abs(mine["arrival_pos"][1] - is_expected[1]) < 1e-6))
path = mine.get("path") or []
results.append(("and the path goes around: more than two hexes",
              len(path) > 2 and path[0] == FROM and path[-1] == COORD))
if len(path) > 2:
    entry_side = neighbours.index(path[-2]) if path[-2] in neighbours else None
    results.append(("entering from a side of the pointed shore",
                  entry_side is not None
                  and entry_side in faces[shore_beyond].sides))
results.append(("and the plan is there, dearer than the straight one",
              mine.get("plan") is not None and mine["plan"].possible
              and mine["plan"].total_cost > 1))

# ------------------------------------------------------------------ result
ok = sum(1 for _n, e in results if e)
for name, e in results:
    print(f" {'ok' if e else 'NO'}  {name}")
print(f"{ok}/{len(results)} passed")
