# -*- coding: utf-8 -*-
"""The real payload of the three-crossing confluence, and for a few hand-drawn
roads what the server says: the plan's cost and the arrow's points
(bench11.html). Run it on the test scene, never on the live save."""
import io
import json
import os

from kingmaker.geometry import hexgrid, sections
from kingmaker.access import permissions
from kingmaker.state import STATE
from kingmaker.ui import hexmap, theme


def _silence(name, value):
    """The map is a package: a function must be replaced in every module."""
    for module in hexmap.MODULES + (hexmap,):
        if hasattr(module, name):
            setattr(module, name, value)


told_ones = []
theme.notify = lambda t, *a, **k: told_ones.append(str(t))
theme.mark_dirty = lambda *a, **k: None
theme.refresh_panels = lambda *a, **k: None
permissions.can = lambda *a, **k: True
_silence("_redraw_travel", lambda *a, **k: None)
_silence("_send_field", lambda *a, **k: None)


class FakeUser:
    id, username, role = "p", "p", permissions.ADMIN
    active = True


theme.user = lambda: FakeUser()
A, C = STATE.archive, STATE.campaign
m = STATE.k["map"]
orient = m["orientation"]
size = float(m["size"])
origin = (float(m["origin_x"]), float(m["origin_y"]))
COORD = (9, 4)
for c in list(A.campaign_banks(C)):
    A.set_banks(C, c, None)
for k in list(A.campaign_borders(C)):
    A.set_border(C, (k[0], k[1]), (k[2], k[3]), None)
A.remove_crossings(C)
A.set_banks(C, COORD, [[0, 1], [2, 3], [4, 5]])
faces = A.campaign_sections(C, orient)[COORD]
for x, y in ((1, 2), (3, 4), (5, 0)):
    t = sections.hop_between_sides(faces, x, y)
    if t:
        A.set_crossing(C, COORD, t[0], t[1])
around = hexgrid.neighbours(COORD[0], COORD[1], orient)
for c in [COORD] + [tuple(x) for x in around]:
    STATE.hex(c[0], c[1])["terrains"] = ["plains"]
FROM = tuple(around[0])
char = STATE.characters()[0]
A.update_character(char["id"], hex_col=FROM[0], hex_row=FROM[1], pos_x=None, pos_y=None)
STATE.load()
base = {"travel_mode": "choose", "travel_pcs": [char["id"]], "col": None, "row": None,
        "forced_march": False, "together": True, "aboard": False,
        "player_preview": False, "travel_vehicle": None, "plan": None,
        "path": [], "branches": [], "singles": [], "rendezvous": None, "route": None,
        "by_river": False, "land": None, "arrival_pos": None, "nodes": (),
        "atom_stretches": {}}


def roads_of(field, drawn):
    """What the server says about every drawn road: cost and arrow points."""
    cells = field["cells"]
    outcome = []
    for name, indices in drawn:
        traced = [[cells[k][0], cells[k][1]] for k in indices]
        nodes = [[cells[k][0], cells[k][1], cells[k][8]] for k in indices]
        mine = dict(base)
        told_ones.clear()
        end = indices[-1]
        hexmap._compute_journey(mine, None, traced,
                                arrival_point=(cells[end][2], cells[end][3]),
                                traced_nodes=nodes)
        shores = hexmap._shores_of(mine)
        points = hexmap._polyline(mine["path"], size, origin, orient, shores, 0)
        outcome.append({"name": name, "indices": indices,
                        "cost": mine["plan"].total_cost if mine.get("plan") else None,
                        "points": [[round(x, 1), round(y, 1)] for x, y in points],
                        "warnings": list(told_ones)})
        print(f"{name:16} plan {outcome[-1]['cost']}  points {len(points)}"
              + ("  WARNINGS " + str(told_ones) if told_ones else ""))
    return outcome


field = hexmap.travel_field(dict(base))
cells, neighbours = field["cells"], field["neighbours"]
inside = [k for k, c in enumerate(cells) if (c[0], c[1]) == COORD]
start = field["travellers"][0]["origin"]
u0 = next(j for j in neighbours[inside[0]] if tuple(cells[j][:2]) != COORD and j != start)
u1 = next(j for j in neighbours[inside[1]] if tuple(cells[j][:2]) != COORD)
u2 = next(j for j in neighbours[inside[2]] if tuple(cells[j][:2]) != COORD)
roads = roads_of(field, [
    ("straight", [start, inside[0], u0]),
    ("one crossing", [start, inside[0], inside[1], u1]),
    ("two crossings", [start, inside[0], inside[1], inside[2], u2]),
    ("round and back", [start, inside[0], inside[1], inside[2], inside[0], u0]),
    ("stops in C", [start, inside[0], inside[1], inside[2]])])

# And the journey inside the departure hexagon: the character sits on shore 0
# of COORD and goes to shore 2 passing through shore 1.
A.update_character(char["id"], hex_col=COORD[0], hex_row=COORD[1],
                   pos_x=sections.section_spot(faces, 0)[0],
                   pos_y=sections.section_spot(faces, 0)[1])
STATE.load()
field2 = hexmap.travel_field(dict(base))
inside2 = [k for k, c in enumerate(field2["cells"]) if (c[0], c[1]) == COORD]
roads2 = roads_of(field2, [("at home, via B", inside2[:3])])

here = os.path.dirname(os.path.abspath(__file__))
io.open(os.path.join(here, "atom_field.json"), "w", encoding="utf-8").write(
    json.dumps({"groups": [{"field": field, "roads": roads},
                           {"field": field2, "roads": roads2}]}))
print("written atom_field.json; masks:", list(field["masks"].keys()))
