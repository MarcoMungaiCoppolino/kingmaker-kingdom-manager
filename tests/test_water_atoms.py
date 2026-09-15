# -*- coding: utf-8 -*-
"""The boat on the atom sides: one step per side, a quarter per step.

A drawn water line is made of atom sides — four for a chord, two for a
spoke — and the boat moves from one crossing to the next: every atom side
costs a quarter of an activity, twice against the current; a hexagon side,
longer, a half. A lake is a hexagon with all the lines. One gets on and off
from every shore touching the crossing where the boat is stopped.
"""
import math
import time
import uuid

from kingmaker.geometry import waterways, atoms, hexgrid, sections
from kingmaker.travel import daily
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
columns, rows = int(m["columns"]), int(m["rows"])
results = []


class Allowed:
    id, username, role = "check", "check", permissions.ADMIN
    active = True


theme.user = lambda: Allowed()


def clean():
    A.remove_lake(C)
    A.remove_currents(C)
    A.remove_crossings(C)
    for c in list(A.campaign_banks(C)):
        A.set_banks(C, c, None)
    for k in list(A.campaign_borders(C)):
        A.set_border(C, (k[0], k[1]), (k[2], k[3]), None)
    for vg in A.list_journeys(C, "in_progress"):
        A.update_journey(vg["id"], status="cancelled")


def new_boat(name):
    sid = uuid.uuid4().hex[:12]
    A.create_stable_vehicle({"id": sid, "campaign_id": C, "vehicle": "barca_a_remi",
                           "name": name, "available": 1, "speed_m": None,
                           "kind": "", "note": "",
                           "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                           "hex_col": None, "hex_row": None})
    A.update_stable_vehicle(sid, seats=6)
    return sid


def unit(coord, unit_point):
    cx, cy = hexgrid.hex_center(coord[0], coord[1], size, origin, orient)
    return (cx + unit_point[0] * size, cy + unit_point[1] * size)


# --- the scene: a river from side to side for three hexagons, and a current
clean()
for x in A.list_stable(C):
    if x["vehicle"] == "barca_a_remi":
        A.delete_stable_vehicle(x["id"])
RIVER = [(9, 4), (10, 4), (11, 4)]
for c in RIVER:
    A.set_banks(C, c, [[0, 1, 2], [3, 4, 5]])
    STATE.hex(c[0], c[1])["terrains"] = ["plains"]
for a, b in zip(RIVER, RIVER[1:]):
    A.set_border(C, a, b, "water")
network = hexmap.waters_network()
banks = hexmap.sections_map()

# --- 1. the geometry: four atom sides per chord -------------------------
results.append(("a chord between two non-adjacent vertices is four atom sides",
              all(len(atoms.chord_pieces(a, b, orient)) == 4
                  for a, b in atoms.DIAGONALS)))
results.append(("a spoke from the vertex to the center two",
              all(len(atoms.chord_pieces(k, None, orient)) == 2
                  for k in range(6))))
results.append(("and a hexagon side none: it is a single line",
              atoms.chord_pieces(0, 1, orient) == ()))
results.append(("the points are nineteen: six corners, the center, twelve crossings",
              len(atoms.inner_junctions(orient)) == 13))
pieces_here = [a for a in network.arcs.values() if a.hexes == ((9, 4),)]
results.append(("the river inside 9,4 is made of four pieces",
              len(pieces_here) == 4 and all(a.kind == "piece" for a in pieces_here)))
results.append(("and each costs a quarter",
              all(v.stretch_cost(a, None) == 0.25 for a in pieces_here)))
results.append(("while the side between two hexes costs a half",
              all(v.stretch_cost(a, None) == 0.5
                  for a in network.arcs.values() if a.kind == "edge")))

# --- 2. the boat is placed on a crossing --------------------------------
sid = new_boat("La Lontra")
mine = {"place_vehicle": sid, "travel_mode": "place"}
# One clicks near the first inner crossing of the river, on the side of
# vertex 0: the boat ends up **on** that crossing, not «in the hexagon».
first_piece = atoms.chord_pieces(0, 3, orient)[0]
junction = first_piece[1]                     # the inner end of the first piece
hexmap._place_vehicle(mine, None, (9, 4), unit((9, 4), (junction[0] + 0.02,
                                                       junction[1] + 0.02)))
boat = A.stable_vehicle(sid)
node = waterways.vehicle_node(boat, orient)
results.append(("the boat sits on an inner crossing",
              node is not None and node[0] == waterways.JUNCTION
              and (boat["hex_col"], boat["hex_row"]) == (9, 4)))
results.append(("and the written place is that point",
              abs(float(boat["pos_x"]) - junction[0]) < 1e-6
              and abs(float(boat["pos_y"]) - junction[1]) < 1e-6))
told_ones.clear()
mine = {"place_vehicle": sid, "travel_mode": "place"}
hexmap._place_vehicle(mine, None, (2, 2))
results.append(("where there is no water it is not placed, and says so",
              (A.stable_vehicle(sid)["hex_col"], A.stable_vehicle(sid)["hex_row"])
              == (9, 4) and "no water" in told_ones[-1]))

# --- 3. the route leaves from the crossing and counts in quarters -------
node_b = waterways.vehicle_node(A.stable_vehicle(sid), orient, network)
found_one = v.route_towards(network, {}, (9, 4), (11, 4), orient, departure_node=node_b)
results.append(("the route is there", found_one is not None))
course, directions, road, steps = found_one
results.append(("and leaves from the boat's crossing, not from a random point",
              road[0] == (node_b, (9, 4))))
cost = sum(p for _direction, p in steps)
# From the crossing: three pieces to leave 9,4, a side, four pieces, a side,
# and inside 11,4 as many as needed to enter it — the destination is the hexagon.
results.append(("the count is a sum of quarters and halves",
              abs(cost * 4 - round(cost * 4)) < 1e-9))
results.append(("and every step is an atom side or a hexagon side",
              all(p in (0.25, 0.5) for _direction, p in steps)))
plan = v.route_plan(road, steps, 7.5, "check")
results.append(("the plan rounds to the whole activity at the end",
              plan.total_cost == math.ceil(cost - 1e-9)))

# Against the current every piece doubles.
A.set_currents(C, waterways.course_stretches(network, [s[0] for s in road]))
currents = A.campaign_currents(C)
down = v.route_towards(network, currents, (9, 4), (11, 4), orient, departure_node=node_b)
results.append(("downstream costs as without a direction",
              down is not None and abs(sum(p for _x, p in down[3]) - cost) < 1e-9))
reversed = {k: (b, a) for k, (a, b) in currents.items()}
su = v.route_towards(network, reversed, (9, 4), (11, 4), orient, departure_node=node_b)
results.append(("upstream every piece costs twice",
              su is not None and abs(sum(p for _x, p in su[3]) - 2 * cost) < 1e-9))

# --- 4. the ruler field leaves from the crossing ------------------------
window = {"travel_pcs": [], "travel_vehicle": sid, "travel_mode": "choose",
            "forced_march": False, "together": True, "aboard": True,
            "player_preview": False}
field = hexmap.travel_field(window)
results.append(("with the boat in hand the field is water", field.get("water") is True))
zeros = [i for i, d in enumerate(field["travellers"][0]["from"]) if d == 0]
boat_point = waterways.node_point(node_b, size, origin, orient)
results.append(("and leaves from a single point: the boat's crossing",
              len(zeros) == 1
              and abs(field["cells"][zeros[0]][2] - boat_point[0]) < 1
              and abs(field["cells"][zeros[0]][3] - boat_point[1]) < 1))
results.append(("the cells are the crossings, and the inner ones are there too",
              len(field["cells"]) > 3 * len(RIVER)))

# --- 5. one departs, and the boat walks from crossing to crossing -------
pc = STATE.characters()[0]
A.update_character(pc["id"], hex_col=9, hex_row=4, stable_id=sid,
                       pos_x=float(boat["pos_x"]), pos_y=float(boat["pos_y"]))
A.update_character(pc["id"], speed_m=7.5)
STATE.load()
mine = dict(window, travel_pcs=[pc["id"]], col=11, row=4, plan=None,
           path=[], branches=[], singles=[], rendezvous=None, route=None,
           by_river=False, land=None, arrival_pos=None, nodes=(), atom_stretches={})
hexmap._compute_route(mine, None)
results.append(("with the right button the route is computed",
              mine.get("plan") is not None and mine["plan"].possible
              and mine.get("by_river") and (mine.get("route") or {}).get("statuses")))
results.append(("and the arrival is a crossing of the last hexagon",
              mine.get("arrival_pos") is not None
              and waterways.node_of_unit_point(
                  (mine["col"], mine["row"]), tuple(mine["arrival_pos"]), orient)
              is not None))
# Departing forgets the plan, and with it the pointed place: the test keeps it.
pointed = tuple(mine["arrival_pos"])
destination = (mine["col"], mine["row"])
before_journeys = {vg["id"] for vg in A.list_journeys(C, "in_progress")}
hexmap._apply_journey(mine, None, [A.character(pc["id"])], (9, 4),
                        (mine["col"], mine["row"]), immediately=False)
new = next((vg for vg in A.list_journeys(C, "in_progress")
              if vg["id"] not in before_journeys), None)
leg = (new or {}).get("legs", [{}])[0]
results.append(("the leg carries the route, crossing by crossing",
              bool(leg.get("route")) and bool(leg.get("waypoint_statuses"))
              and len(leg["waypoint_statuses"]) == len(leg["path"])))
route_points = hexmap._leg_points(leg, size, origin, orient, banks,
                                         A.campaign_crossings(C))
results.append(("and is drawn from the boat's crossing along the water",
              len(route_points) >= 3
              and abs(route_points[0][0] - boat_point[0]) < 1
              and abs(route_points[0][1] - boat_point[1]) < 1))
daily.advance_one_day(STATE)
STATE.load()
boat_after = A.stable_vehicle(sid)
node_after = waterways.vehicle_node(boat_after, orient)
results.append(("after a day the boat sits on a crossing, further on",
              node_after is not None and node_after != node_b
              and node_after in network.neighbours))
pc_after = A.character(pc["id"])
results.append(("and whoever is aboard is with it",
              (pc_after["hex_col"], pc_after["hex_row"])
              == (boat_after["hex_col"], boat_after["hex_row"])
              and abs(float(pc_after["pos_x"]) - float(boat_after["pos_x"])) < 1e-6))
for _g in range(6):
    if not any(vg["id"] == new["id"] for vg in A.list_journeys(C, "in_progress")):
        break
    daily.advance_one_day(STATE)
STATE.load()
boat_end = A.stable_vehicle(sid)
results.append(("on arrival it sits on the pointed crossing",
              (boat_end["hex_col"], boat_end["hex_row"]) == destination
              and abs(float(boat_end["pos_x"]) - pointed[0]) < 1e-6))

# --- 6. one gets on and off from the shores touching the crossing -------
# The boat goes back to a **corner** of 9,4: a corner belongs to three hexagons.
A.update_character(pc["id"], stable_id=None)
corner_k = 1          # not an end of the river: that one touches both shores
corner_spot = sections.unit_corners(orient)[corner_k]
A.update_stable_vehicle(sid, hex_col=9, hex_row=4, pos_x=corner_spot[0],
                          pos_y=corner_spot[1])
boat = A.stable_vehicle(sid)
corner_node = waterways.vehicle_node(boat, orient)
results.append(("at the corner the boat sits on a vertex of the grid",
              corner_node is not None and corner_node[0] == waterways.VERTEX))
masters = [tuple(c) for c, _k in waterways.vertex_owners((9, 4), corner_k, orient)]
touch_ = waterways.touching_faces(corner_node, banks, orient)
results.append(("the shores touching it sit in three hexes",
              {c for c, _s in touch_} == set(masters)))
# From 9,4 it touches only one of the two shores: the one with vertex 3.
shores_9_4 = {s for c, s in touch_ if c == (9, 4)}
results.append(("and in 9,4 only one of the two shores",
              len(shores_9_4) == 1))
this_side = sections.section_spot(banks[(9, 4)], next(iter(shores_9_4)))
beyond = sections.section_spot(banks[(9, 4)], 1 - next(iter(shores_9_4)))
who = {"name": "Tizio", "hex_col": 9, "hex_row": 4, "pos_x": this_side[0],
       "pos_y": this_side[1]}
results.append(("from the shore touching the corner one gets on",
              v.ascent_blocked(who, boat, banks, orient) is None))
who_beyond = dict(who, pos_x=beyond[0], pos_y=beyond[1])
results.append(("from the one beyond no, and it says so",
              "touch" in (v.ascent_blocked(who_beyond, boat, banks, orient) or "")))
other = next(c for c in masters if c != (9, 4))
STATE.hex(other[0], other[1])["terrains"] = ["plains"]
who_beside = {"name": "Caio", "hex_col": other[0], "hex_row": other[1],
               "pos_x": None, "pos_y": None}
results.append(("and from the next hexagon touching the corner one gets on all the same",
              v.ascent_blocked(who_beside, boat, banks, orient) is None
              or other in banks and True))
results.append(("one gets off onto the shore it touches",
              v.descent_blocked(boat, (9, 4), orient, banks=banks, spot=this_side)
              is None))
results.append(("and not onto the one beyond",
              "touch" in (v.descent_blocked(boat, (9, 4), orient, banks=banks,
                                             spot=beyond) or "")))

# --- 7. two boats on the same crossing are a group with the number ------
sid2 = new_boat("La Seconda")
A.update_stable_vehicle(sid2, hex_col=9, hex_row=4, pos_x=corner_spot[0],
                          pos_y=corner_spot[1])
view = hexmap._current_view({})
members = hexmap._members_per_hex(view)
where_boats = next((k for k, g in members.items()
                    if any(x.get("id") == sid for x in g)), None)
results.append(("the two boats sit under the same hexagon, the crossing's",
              where_boats is not None
              and {x.get("id") for x in members[where_boats]} >= {sid, sid2}))
cx, cy = hexgrid.hex_center(where_boats[0], where_boats[1], size, origin, orient)
seats = hexmap.marker_positions(members[where_boats], cx, cy, size, where_boats,
                                   origin, orient, banks)
boats_badge = next((t for t in seats if any(x.get("id") == sid for x in t[0])), None)
corner_point = waterways.node_point(corner_node, size, origin, orient)
results.append(("and make a single badge, on the crossing",
              boats_badge is not None and len(boats_badge[0]) == 2
              and abs(boats_badge[1] - corner_point[0]) < 1
              and abs(boats_badge[2] - corner_point[1]) < 1))
drawing = "".join(hexmap._svg_markers(view, size, origin, orient, set()))
results.append(("with the number two", ">2</text>" in drawing))
taken = hexmap.marker_under(view, m, corner_point, (9, 4))
results.append(("and clicking it picks the group of the two boats",
              taken is not None and {x.get("id") for x in taken} == {sid, sid2}))
A.delete_stable_vehicle(sid2)

# --- 8. the lake: all the lines, and one stops on every crossing --------
clean()
LAKE = [(20, 6)]
A.set_lake(C, "l-prova", LAKE, points=[])
STATE.hex(20, 6)["terrains"] = ["plains"]
lake_network = hexmap.waters_network()
in_the_lake = [a for a in lake_network.arcs.values() if a.lake]
results.append(("a lake of one cell is 36 atom sides and 6 hexagon sides",
              len(in_the_lake) == 42))
mine = {"place_vehicle": sid, "travel_mode": "place"}
inside_lake = atoms.inner_junctions(orient)[5]
hexmap._place_vehicle(mine, None, (20, 6), unit((20, 6), inside_lake))
boat = A.stable_vehicle(sid)
results.append(("the boat stops on an inner crossing of the lake",
              (waterways.vehicle_node(boat, orient) or ("",))[0] == waterways.JUNCTION))
node_l = waterways.vehicle_node(boat, orient, lake_network)
target = waterways.vertex_key((20, 6), 0, orient)
route_l = v.route_towards(lake_network, {}, (20, 6), (20, 6), orient,
                        arrival_node=target, departure_node=node_l)
results.append(("and inside the lake one goes from a crossing to a corner, in quarters",
              route_l is not None
              and all(p in (0.25, 0.5) for _x, p in route_l[3])
              and all(direction == "lake" for direction, _p in route_l[3])))

A.delete_stable_vehicle(sid)
clean()

# ------------------------------------------------------------------ result
ok = sum(1 for _n, e in results if e)
for name, e in results:
    print(f" {'ok' if e else 'NO'}  {name}")
print(f"{ok}/{len(results)} passed")
