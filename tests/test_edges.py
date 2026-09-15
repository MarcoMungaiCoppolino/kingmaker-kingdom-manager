# -*- coding: utf-8 -*-
"""The edge of the map, the lake with centers on its outline, the departed route
drawn from the marker to the pointed piece, the vehicle as a unit with whoever
is aboard inside it, and the vehicle left behind at departure."""
import re

from kingmaker.geometry import waterways, hexgrid, sections
from kingmaker.travel import daily
from kingmaker.access import permissions
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
width, height = float(m["img_width"]), float(m["img_height"])
results = []


class Allowed:
    id, username, role = "check", "check", permissions.ADMIN
    active = True


theme.user = lambda: Allowed()

# --- 1. the edge of the map is the image, not the grid --------------------
# The grid is 30x24 but the image covers fewer rows: below there is darkness,
# and a journey could go for a walk there. A hexagon belongs to the map if its
# center falls on the image.
inside = hexmap.inside_map(m)
outside_before = next(r for r in range(int(m["rows"]))
                   if hexgrid.hex_center(5, r, size, origin, orient)[1] > height)
results.append(("below the edge of the image there is no map",
              not inside((5, outside_before)) and inside((5, outside_before - 1))))
results.append(("beyond the grid neither",
              not inside((-1, 3)) and not inside((int(m["columns"]), 3))))
results.append(("in the middle there is", inside((9, 4))))
results.append(("without the image's measures the grid counts",
              hexmap.inside_map(dict(m, img_width=0, img_height=0))
              ((5, outside_before))))

# --- 2. the lake: a center on the outline is inside -----------------------
# The outline points are vertices and centers: a shape on four vertices in a
# row has the center exactly on the chord closing it, and one drawn from one
# center to the other passes over both. Before, those centers fell outside
# depending on the rounding, and the shape «contained no hexagon».


def cells(names):
    nodes = [waterways.node_from_text(x) for x in names]
    return waterways.cells_in_polygon(nodes, int(m["columns"]), int(m["rows"]),
                                       size, origin, orient)


H = (6, 6)
six = [hexmap._point_name(H, k, orient) for k in range(6)]
results.append(("six vertices: the hexagon", cells(six) == [H]))
results.append(("half a hexagon on four vertices in a row: the hexagon belongs to the lake",
              cells(six[:4]) == [H]))
near = tuple(hexgrid.neighbours(H[0], H[1], orient)[0])
k1, k2 = waterways.side_vertices(0)
rhombus = [hexmap._point_name(H, None, orient), hexmap._point_name(H, k1, orient),
         hexmap._point_name(near, None, orient), hexmap._point_name(H, k2, orient)]
results.append(("a rhombus from one center to the other: both hexes",
              set(cells(rhombus)) == {H, near}))

# --- 3. the scene: a three-shore confluence with two chained bridges ------
for vg in A.list_journeys(C, "in_progress"):
    A.update_journey(vg["id"], status="cancelled")
for c in list(A.campaign_banks(C)):
    A.set_banks(C, c, None)
A.remove_crossings(C)
for k in list(A.campaign_borders(C)):
    A.set_border(C, (k[0], k[1]), (k[2], k[3]), None)
COORD = (9, 4)
A.set_banks(C, COORD, [[0, 1], [2, 3], [4, 5]])
banks = A.campaign_sections(C, orient)
faces = banks[COORD]
neighbours = hexgrid.neighbours(COORD[0], COORD[1], orient)
DA = tuple(neighbours[0])
for c in (COORD, DA):
    STATE.hex(c[0], c[1])["terrains"] = ["plains"]
for side_a, side_b in ((1, 2), (3, 4)):
    found = sections.hop_between_sides(faces, side_a, side_b)
    if found:
        A.set_crossing(C, COORD, found[0], found[1])

# --- 4. the vehicle is a unit: whoever is aboard sits inside its badge ----
# The test scene puts a boat on 9,4 with Dagny aboard — and Aldric on the
# ground right next to it: they are sent away, or boat and Aldric form a group.
for p_ in STATE.characters():
    if (p_["hex_col"], p_["hex_row"]) == COORD and not p_.get("stable_id"):
        A.update_character(p_["id"], hex_col=5, hex_row=5,
                               pos_x=None, pos_y=None)
STATE.load()
boat = next(x for x in A.list_stable(C) if x["vehicle"] == "barca_a_remi")
aboard = A.characters_on_vehicle(boat["id"])
view = hexmap._current_view({})
members = hexmap._members_per_hex(view).get(COORD) or []
vehicle_here = next((x for x in members if x.get("id") == boat["id"]), None)
results.append(("the placed vehicle is a member of its hexagon", vehicle_here is not None))
results.append(("and brings along whoever is aboard",
              vehicle_here is not None and aboard
              and {p["id"] for p in vehicle_here.get("passengers") or ()}
              == {p["id"] for p in aboard}))
results.append(("who is not a member on their own",
              all(x.get("id") not in {p["id"] for p in aboard} for x in members)))
results.append(("nor someone to pick by clicking the ground",
              all(p["id"] not in {q["id"] for q in aboard}
                  for p in hexmap.characters_on(COORD, view))))
drawing = "".join(hexmap._svg_markers(view, size, origin, orient, set()))
initial = (aboard[0]["name"] or "?")[:1].upper() if aboard else "?"
results.append(("and on the drawing their initial sits inside the vehicle's badge",
              f">{initial}<" in drawing))
results.append(("picking whoever is aboard lights up the vehicle",
              vehicle_here is not None and aboard
              and hexmap._taken(vehicle_here, {aboard[0]["id"]}, set())
              and not hexmap._taken(vehicle_here, {"nessuno"}, set())))

# --- 5. the departed route leaves from the marker and reaches the pointed piece
char = next(p for p in STATE.characters() if not p.get("stable_id"))
A.update_character(char["id"], hex_col=DA[0], hex_row=DA[1],
                       pos_x=None, pos_y=None)
STATE.load()


def window():
    return {"travel_mode": "choose", "travel_pcs": [char["id"]],
            "col": COORD[0], "row": COORD[1], "forced_march": False,
            "together": True, "aboard": False, "player_preview": False,
            "travel_vehicle": None, "plan": None, "path": [], "branches": [],
            "singles": [], "rendezvous": None, "route": None, "by_river": False,
            "land": None, "arrival_pos": None}


def tip(bank):
    return hexmap.bank_point(COORD, bank, size, origin, orient, banks)


def first_and_last(svg):
    """The first and last point of the first drawn route."""
    stretch = re.search(r'<path d="([^"]+)"', svg)
    if not stretch:
        return None, None
    points = [(float(x), float(y)) for x, y in
             re.findall(r"[ML]\s*([\d.\-]+) ([\d.\-]+)", stretch.group(1))]
    return (points[0], points[-1]) if points else (None, None)


def near_to(p, q, how_much=1.0):
    return p is not None and q is not None and abs(p[0] - q[0]) <= how_much \
        and abs(p[1] - q[1]) <= how_much


def anchor_of(who):
    """Where that character's badge sits, as the map draws it."""
    entry = A.character(who)
    here = (entry["hex_col"], entry["hex_row"])
    cx, cy = hexgrid.hex_center(here[0], here[1], size, origin, orient)
    seats = hexmap.marker_positions(hexmap.characters_on(here, hexmap._current_view({})),
                                       cx, cy, size, here, origin, orient, banks)
    return next(((x, y) for g, x, y, _r in seats if any(q["id"] == who for q in g)), None)


mine = window()
hexmap._compute_journey(mine, None, arrival_point=tip(2))
# With the right button the hand does not draw the nodes: the count finds
# them, and they freeze in the leg (further down). Here it is enough that the
# journey exists.
results.append(("the journey to the shore beyond is computed",
              mine.get("plan") is not None and mine["plan"].possible
              and mine.get("arrival_pos") is not None))
mine["travel_vehicle"] = "mezzo-finto"
mine["aboard"] = True
before_journeys = {vg["id"] for vg in A.list_journeys(C, "in_progress")}
hexmap._apply_journey(mine, None, [A.character(char["id"])], DA, COORD,
                        immediately=False)
new = next((vg for vg in A.list_journeys(C, "in_progress")
              if vg["id"] not in before_journeys), None)
results.append(("pressing Depart the journey departs", new is not None))
results.append(("and the vehicle is left behind, like the people",
              mine.get("travel_vehicle") is None and mine.get("travel_pcs") == []
              and not mine.get("aboard")))
leg = (new or {}).get("legs", [{}])[0]
where_v = ((new or {}).get("pos_x"), (new or {}).get("pos_y"))
results.append(("the leg freezes the touched nodes and the arrival place",
              bool(leg.get("nodes")) and leg.get("where") is not None
              and where_v[0] is not None
              and abs(float(leg["where"][0]) - float(where_v[0])) < 1e-9))
svg = hexmap._svg_journeys_in_progress(hexmap._current_view({}),
                                  {"show_journeys": True, "chosen_journey": None},
                                  size, origin, orient)
first, last = first_and_last(svg)
results.append(("the route leaves from the badge of whoever walks",
              near_to(first, anchor_of(char["id"]))))
results.append(("and reaches the pointed piece, not the center of the hexagon",
              near_to(last, tip(2))
              and not near_to(last, hexgrid.hex_center(COORD[0], COORD[1],
                                                          size, origin, orient))))
center_from = hexgrid.hex_center(DA[0], DA[1], size, origin, orient)
results.append(("and not from the center of the departure hexagon",
              not near_to(first, center_from)))

# A day passes: the route shortens and starts again from the badge, which has moved.
daily.advance_one_day(STATE)
STATE.load()
still_in_progress = A.list_journeys(C, "in_progress")
if any(vg["id"] == new["id"] for vg in still_in_progress):
    svg2 = hexmap._svg_journeys_in_progress(hexmap._current_view({}),
                                       {"show_journeys": True, "chosen_journey": None},
                                       size, origin, orient)
    first2, last2 = first_and_last(svg2)
    results.append(("the day after the route starts again from where the badge sits",
                  near_to(first2, anchor_of(char["id"]))))
    results.append(("and always ends in the pointed piece", near_to(last2, tip(2))))
    for _day in range(6):
        if not any(vg["id"] == new["id"] for vg in A.list_journeys(C, "in_progress")):
            break
        daily.advance_one_day(STATE)
STATE.load()
has_arrived = A.character(char["id"])
pointed_spot = sections.section_spot(faces, 2)
results.append(("and on arrival the marker sits in the pointed piece",
              (has_arrived["hex_col"], has_arrived["hex_row"]) == COORD
              and has_arrived.get("pos_x") is not None
              and abs(float(has_arrived["pos_x"]) - pointed_spot[0]) < 1e-6
              and abs(float(has_arrived["pos_y"]) - pointed_spot[1]) < 1e-6))

# --- 6. the place of the leg, leg by leg ----------------------------------
fake_journey = {"arrival": "9,4", "pos_x": 0.1, "pos_y": 0.2}
results.append(("a leg with its place uses it",
              daily._leg_spot(fake_journey, {"where": [0.3, 0.4]})
              == (0.3, 0.4)))
results.append(("an old leg ending at the arrival takes the journey's",
              daily._leg_spot(fake_journey, {"path": [[8, 4], [9, 4]]})
              == (0.1, 0.2)))
results.append(("but a branch stopping at the rendezvous does not",
              daily._leg_spot(fake_journey, {"path": [[8, 4], [8, 5]]})
              is None))

# ------------------------------------------------------------------ result
ok = sum(1 for _n, e in results if e)
for name, e in results:
    print(f" {'ok' if e else 'NO'}  {name}")
print(f"{ok}/{len(results)} passed")
