# -*- coding: utf-8 -*-
"""A shore is a place: it is seen, it is pointed at, and the arrow passes inside it.

As long as the two banks of a cut hexagon both sat at the center, «this side»
and «beyond» the water were the same thing for the drawing and for the mouse:
the markers brushed against each other, the arrow passed over the river even
when the journey did not cross it, and to pick a bridge one had to hit its
icon. Here it is shown that every piece of hexagon has its own point, and
that everything drawn or clicked uses it.
"""
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
permissions.can = lambda *a, **k: True

A, C = STATE.archive, STATE.campaign
m = STATE.k["map"]
size = float(m["size"])
origin = (float(m["origin_x"]), float(m["origin_y"]))
orient = m["orientation"]
COORD = (9, 4)
GROUPS = [[0, 1, 2], [3, 4, 5]]


def spot(bank, coord=None):
    """The point to write to say «I am on that shore».

    On disk there is no longer a shore number: there is a place inside the
    hexagon, and the shore is recomputed around it. The tests write what the
    app writes.
    """
    faces = A.campaign_sections(C, orient).get(tuple(coord or COORD)) or ()
    return sections.section_spot(faces, bank) or (None, None)
results = []


def clean():
    A.remove_lake(C)
    A.remove_crossings(C)
    for c in list(A.campaign_banks(C)):
        A.set_banks(C, c, None)
    for k in list(A.campaign_borders(C)):
        A.set_border(C, (k[0], k[1]), (k[2], k[3]), None)


def inside_polygon(p, polygon):
    """Point inside a polygon, by counting the intersections."""
    inside = False
    for i, (x1, y1) in enumerate(polygon):
        x2, y2 = polygon[(i + 1) % len(polygon)]
        if (y1 > p[1]) != (y2 > p[1]):
            cut = x1 + (p[1] - y1) * (x2 - x1) / (y2 - y1)
            if p[0] < cut:
                inside = not inside
    return inside


# No vehicles on the map: a placed vehicle is a member of its piece of
# hexagon like a person, and the test scene puts one right here.
for _v in A.list_stable(C):
    A.update_stable_vehicle(_v["id"], hex_col=None, hex_row=None)
clean()
cx, cy = hexgrid.hex_center(COORD[0], COORD[1], size, origin, orient)

# --- 1. the geometry: the piece of hexagon and its centroid --------------
for group in GROUPS:
    polygon = helpers.bank_polygon(cx, cy, size, orient, group)
    center = helpers.bank_center(cx, cy, size, orient, group)
    results.append(("bank " + str(group) + " is a piece of hexagon with its vertices",
                  len(polygon) >= 3))
    results.append(("and its centroid sits inside it " + str(group),
                  inside_polygon(center, polygon)))

one = helpers.bank_center(cx, cy, size, orient, GROUPS[0])
two = helpers.bank_center(cx, cy, size, orient, GROUPS[1])
dist = ((one[0] - two[0]) ** 2 + (one[1] - two[1]) ** 2) ** 0.5
results.append(("the two shores sit in two different places", dist > size * 0.5))
results.append(("symmetric about the center, with a cut through the middle",
              abs((one[0] + two[0]) / 2 - cx) < 1e-6
              and abs((one[1] + two[1]) / 2 - cy) < 1e-6))

# --- 2. without water nothing changes -----------------------------------
is_free = (12, 6)
results.append(("a whole hexagon stays its center",
              hexmap.bank_point(is_free, 0, size, origin, orient, {})
              == hexgrid.hex_center(is_free[0], is_free[1], size, origin, orient)))

A.set_banks(C, COORD, GROUPS)
banks = A.campaign_sections(C, orient)   # the real sections: faces, not groups of sides
p0 = hexmap.bank_point(COORD, 0, size, origin, orient, banks)
p1 = hexmap.bank_point(COORD, 1, size, origin, orient, banks)
far_ones = ((p0[0] - p1[0]) ** 2 + (p0[1] - p1[1]) ** 2) ** 0.5
results.append(("inside a cut hexagon the two banks are two points",
              far_ones > size * 0.4))
corners = hexgrid.hex_corners(cx, cy, size, orient)
results.append(("both inside the hexagon",
              inside_polygon(p0, corners) and inside_polygon(p1, corners)))


# --- 3. the ruler: two cells, two points --------------------------------
class Allowed:
    id, username, role = "check", "check", permissions.ADMIN
    active = True


theme.user = lambda: Allowed()
char = STATE.characters()[0]
before = (char["hex_col"], char["hex_row"], int(char.get("bank") or 0))
A.update_character(char["id"], hex_col=COORD[0], hex_row=COORD[1],
                       pos_x=spot(0)[0], pos_y=spot(0)[1])
mine = {"travel_mode": "choose", "travel_pcs": [char["id"]], "forced_march": False,
       "aboard": False, "together": True, "player_preview": False,
       "travel_vehicle": None}
field = hexmap.travel_field(mine)
my_ones = [c for c in (field.get("cells") or []) if (c[0], c[1]) == COORD]
results.append(("the cut hexagon sends the browser two cells", len(my_ones) == 2))
results.append(("and the two cells have different points",
              len(my_ones) == 2 and (my_ones[0][2], my_ones[0][3]) != (my_ones[1][2], my_ones[1][3])))
if len(my_ones) == 2:
    between = ((my_ones[0][2] - my_ones[1][2]) ** 2 + (my_ones[0][3] - my_ones[1][3]) ** 2) ** 0.5
    results.append(("far enough apart to point at them with the mouse", between > size * 0.4))
    print("   (the two shores are %.0f apart on a hexagon of radius %.0f)" % (between, size))

# --- 4. the markers sit in their shore, and are picked there ------------
people = [{"id": "a", "name": "Uno", "hex_col": COORD[0], "hex_row": COORD[1],
          "pos_x": spot(0)[0], "pos_y": spot(0)[1], "color": "#ffffff"},
         {"id": "b", "name": "Due", "hex_col": COORD[0], "hex_row": COORD[1],
          "pos_x": spot(1)[0], "pos_y": spot(1)[1], "color": "#ffffff"}]
seats = hexmap.marker_positions(people, cx, cy, size, COORD, origin, orient, banks)
by_id = {p["id"]: (x, y, r) for group, x, y, r in seats for p in group}
results.append(("two on the two shores are drawn in two places",
              by_id["a"][:2] != by_id["b"][:2]))
coord_faces = A.campaign_sections(C, orient)[COORD]


def shape(index):
    return [(cx + x * size, cy + y * size) for x, y in coord_faces[index].ring]


results.append(("each inside their shore",
              inside_polygon(by_id["a"][:2], shape(0))
              and inside_polygon(by_id["b"][:2], shape(1))))
whole_ones = hexmap.marker_positions(people, cx, cy, size, is_free, origin, orient, banks)
results.append(("and in a cut hexagon the badges are smaller",
              seats[0][3] < whole_ones[0][3]))

real_on_ = hexmap.characters_on
helpers.silence("characters_on", lambda c, vis: people if tuple(c) == COORD else [])
try:
    fake_view = type("V", (), {"gm": True,
                                 "markers": lambda self: people,
                                 "can_see": lambda self, c, r: True})()
    taken_ones = 0
    for group, x, y, _r in seats:
        where = hexgrid.pixel_to_hex(x, y, size, origin, orient)
        taken = hexmap.marker_under(fake_view, m, (x, y), where)
        if taken is not None and [q["id"] for q in taken] == [
                q["id"] for q in group]:
            taken_ones += 1
    results.append(("and clicking them picks precisely what is seen",
                  taken_ones == len(seats)))
finally:
    helpers.silence("characters_on", real_on_)

# --- 5. the path knows which shore it passes on -------------------------
_found = sections.hop_between_sides(A.campaign_sections(C, orient)[COORD], 0, 3)
A.set_crossing(C, COORD, _found[0], _found[1])
crossings = A.campaign_crossings(C)
neighbours = hexgrid.neighbours(COORD[0], COORD[1], orient)
this_side, beyond = tuple(neighbours[0]), tuple(neighbours[3])
shores = v.banks_on_course([this_side, COORD, beyond], banks, crossings, orient, 0)
from_other_side = v.banks_on_course([beyond, COORD, this_side], banks, crossings, orient, 0)
results.append(("the shore one enters on depends on where one comes from",
              len(shores) == 3 and len(from_other_side) == 3
              and shores[1] != from_other_side[1]))
nodes = v.nodes_on_course([this_side, COORD, beyond], banks, crossings, orient, 0)
results.append(("and passing the bridge inside the hexagon is one more node",
              len(nodes) == 4
              and nodes[1][:2] == COORD and nodes[2][:2] == COORD
              and nodes[1][2] != nodes[2][2]))
without_bridge = v.nodes_on_course([this_side, COORD, beyond], banks, {}, orient, 0)
results.append(("without a bridge the path stops where there is no passage",
              len(without_bridge) == 2))
along = v.banks_on_course([this_side, COORD, this_side], banks, crossings, orient, 0)
results.append(("staying on this side one does not change shore",
              len(along) == 3 and len(set(along[1:])) == 1))

points = hexmap.course_points([this_side, COORD, beyond], size, origin, orient,
                                 banks, crossings, 0)
results.append(("and the arrow passes inside it, not over the river",
              len(points) == 4
              and inside_polygon(points[1],
                                     helpers.bank_polygon(cx, cy, size, orient,
                                                           GROUPS[nodes[1][2]]))
              and inside_polygon(points[2],
                                     helpers.bank_polygon(cx, cy, size, orient,
                                                           GROUPS[nodes[2][2]]))))
results.append(("and leaves from where the markers sit, not from the center",
              points[0] == hexmap.anchor_markers(this_side, 0, size, origin,
                                                  orient, banks)))

A.update_character(char["id"], hex_col=before[0], hex_row=before[1],
                       pos_x=None, pos_y=None)
clean()


# --- 6. the drawn path is checked from the right shore ------------------
# The defect seen at the table: you draw a road that exists from your shore,
# release the button, and the server answers «the traced path is not valid»
# and puts the cheapest way in its place — because it retraced the path
# always starting from shore 0.
A.remove_crossings(C)                       # without a bridge the two shores do not talk
A.set_banks(C, COORD, GROUPS)
banks = A.campaign_sections(C, orient)   # the real sections: faces, not groups of sides
neighbours = hexgrid.neighbours(COORD[0], COORD[1], orient)
only_beyond = tuple(neighbours[3])          # it is reached only from shore 1
for coord in [COORD, only_beyond]:
    STATE.hex(coord[0], coord[1])["terrains"] = ["plains"]

helpers.silence("_redraw_travel", lambda *a, **k: None)
helpers.silence("_send_field", lambda *a, **k: None)
theme.mark_dirty = lambda *a, **k: None


def window():
    return {"travel_mode": "choose", "travel_pcs": [char["id"]],
            "col": only_beyond[0], "row": only_beyond[1], "forced_march": False,
            "together": True, "aboard": False, "player_preview": False,
            "travel_vehicle": None, "plan": None, "path": [], "branches": [],
            "singles": [], "rendezvous": None, "route": None, "by_river": False,
            "land": None}


traced_one = [list(COORD), list(only_beyond)]
A.update_character(char["id"], hex_col=COORD[0], hex_row=COORD[1],
                       pos_x=spot(1)[0], pos_y=spot(1)[1])
told_ones.clear()
mine = window()
hexmap._compute_journey(mine, None, traced_one=traced_one)
results.append(("whoever is on the far shore keeps the road they drew",
              [tuple(c) for c in (mine.get("path") or [])]
              == [COORD, only_beyond]))
results.append(("and nobody tells them it is not valid",
              not any("not valid" in x for x in told_ones)))

# And the check has not become lenient: from the shore on this side that same
# path is a hop over the river, and stays refused.
A.update_character(char["id"], hex_col=COORD[0], hex_row=COORD[1],
                       pos_x=spot(0)[0], pos_y=spot(0)[1])
told_ones.clear()
mine = window()
hexmap._compute_journey(mine, None, traced_one=traced_one)
results.append(("but from the shore on this side the same hop stays refused",
              any("not valid" in x for x in told_ones)))
A.update_character(char["id"], hex_col=before[0], hex_row=before[1],
                       pos_x=None, pos_y=None)
clean()

# --- 7. every piece of hexagon has its own point, even the narrowest -----
# A piece of a single side exists where the water makes a confluence: there
# the stretches are drawn to the center, and the piece is a wedge opening
# from the center. Without the center in its shape that wedge had no area,
# the centroid fell back on the center of the hexagon, and the marker of
# whoever stood there was drawn in the middle — as if nowhere. On the map it
# showed, and indeed it was seen.
import itertools

all_cuts = []
for n_items in (1, 2, 3):
    for combination in itertools.combinations(
            [(a, b) for a, b in itertools.combinations(range(6), 2)]
            + [(k, None) for k in range(6)], n_items):
        all_cuts.append(list(combination))

hex_corners = hexgrid.hex_corners(cx, cy, size, orient)
tried, escaped, without_area, unpaired = 0, 0, 0, 0
for cuts in all_cuts:
    faces = sections.faces_of(cuts, orient)
    fake_ones = {COORD: faces}
    if sum(f.area for f in faces) < 2.59 or sum(f.area for f in faces) > 2.60:
        unpaired += 1                  # the faces must cover the whole hexagon
    if sorted(d for f in faces for d in f.sides) != list(range(6)):
        unpaired += 1                  # and every side sits on a single face
    for index, face in enumerate(faces):
        tried += 1
        if face.area <= 1e-9:
            without_area += 1
        point = hexmap.bank_point(COORD, index, size, origin, orient, fake_ones)
        shape = [(cx + x * size, cy + y * size) for x, y in face.ring]
        if len(faces) > 1 and not inside_polygon(point, shape):
            escaped += 1
results.append(("in every possible cut the point sits inside its section",
              tried > 300 and escaped == 0))
results.append(("no section without an area, in any cut", without_area == 0))
results.append(("the sections cover the hexagon and share the six sides",
              unpaired == 0))
print("   (%d sezioni provate su %d tagli diversi)"
      % (tried, len(all_cuts)))

# And in a confluence the wedges no longer overlap at the center.
fake_ones = {COORD: sections.faces_of([(0, None), (2, None), (4, None)], orient)}
points = [hexmap.bank_point(COORD, r, size, origin, orient, fake_ones)
         for r in range(3)]
results.append(("the wedges of a confluence have three distinct points",
              len({(round(x), round(y)) for x, y in points}) == 3))
results.append(("and none of them is the center of the hexagon",
              all(abs(x - cx) + abs(y - cy) > size * 0.1 for x, y in points)))

# The three cases the side-groups model got wrong, measured.
measures = [(2, [(0, 3)]), (4, [(0, 3), (1, 4)]), (3, [(0, 2), (3, 5)]),
          (6, [(0, 3), (1, 4), (2, 5)]), (4, [(0, 2), (2, 4), (4, 0)]),
          (24, [(a, b) for a, b in itertools.combinations(range(6), 2)
                if (b - a) % 6 not in (1, 5)])]
wrong_ones = [(is_expected, len(sections.faces_of(t, orient)))
             for is_expected, t in measures
             if len(sections.faces_of(t, orient)) != is_expected]
results.append(("the six test cuts give 2, 4, 3, 6, 4 and 24 sections",
              not wrong_ones))
island = sections.faces_of([(0, 2), (2, 4), (4, 0)], orient)
results.append(("the triangle in the middle exists and touches no side",
              sum(1 for f in island if not f.sides) == 1))

# --- 9. the arrow is born from the marker, even while you drag it --------
# The ruler receives, for every cell, the **shore's point** (where the mouse
# points at it) and the **markers' anchor** (where the badge sits, and where
# the arrow is born). In a cut hexagon they coincide; in a whole hexagon the
# markers sit below the center, and the arrow must leave from there. Sending
# only one, the dragged arrow was born detached from the marker and snapped
# back into place as soon as you released the button: two drawings of the
# same road.
clean()
A.set_banks(C, COORD, GROUPS)
banks = A.campaign_sections(C, orient)


def anchor_of_cell(entry):
    return (entry[6], entry[7]) if len(entry) > 7 else (entry[2], entry[3])


def single_window():
    return {"travel_mode": "choose", "travel_pcs": [char["id"]],
            "forced_march": False, "aboard": False, "together": True,
            "player_preview": False, "travel_vehicle": None}


def payload_from(where, bank_here):
    A.update_character(char["id"], hex_col=where[0], hex_row=where[1],
                           pos_x=spot(bank_here, where)[0],
                           pos_y=spot(bank_here, where)[1])
    STATE.load()
    return hexmap.travel_field(single_window())


# The whole hexagon to test on is not chosen by hand: it is taken from the
# field itself, or one ends up pointing at one that on the real map is a
# lake and for which the ruler sends no cell.
field_here = payload_from(COORD, 1)
whole = next((c[0], c[1]) for c in field_here["cells"]
              if (c[0], c[1]) != COORD and len(banks.get((c[0], c[1])) or ()) < 2)

for where, bank_here in ((COORD, 1), (whole, 0)):
    field_here = payload_from(where, bank_here)
    who = next(p for p in STATE.characters() if p["id"] == char["id"])
    its = field_here["cells"][field_here["travellers"][0]["origin"]]
    ecx, ecy = hexgrid.hex_center(where[0], where[1], size, origin, orient)
    badges = hexmap.marker_positions([who], ecx, ecy, size, where, origin,
                                       orient, banks)
    where_is = (round(badges[0][1], 1), round(badges[0][2], 1))
    name = "cut" if len(banks.get(where) or ()) > 1 else "whole"
    results.append((f"on a {name} hexagon the dragged arrow is born from the badge",
                  (its[0], its[1]) == where and anchor_of_cell(its) == where_is))
    near_here = tuple(hexgrid.neighbours(where[0], where[1], orient)[bank_here * 3])
    first = hexmap.course_points([where, near_here], size, origin, orient,
                                     banks, A.campaign_crossings(C), bank_here)[0]
    results.append((f"and the confirmed one leaves from the same place ({name})",
                  (round(first[0], 1), round(first[1], 1)) == where_is))
    # In a whole hexagon the anchor is **not** the cell's point: it is the
    # difference the ruler ignored. In a cut one they coincide, because the
    # marker sits at the point of its shore.
    detached_one = anchor_of_cell(its) != (its[2], its[3])
    results.append((f"and the anchor sits where it must, on a {name} hexagon",
                  detached_one == (name == "whole")))

A.update_character(char["id"], hex_col=before[0], hex_row=before[1],
                       pos_x=None, pos_y=None)
clean()

width = max(len(n) for n, _ in results)
print("")
for name, ok in results:
    print(("  ok  " if ok else " NO   ") + name.ljust(width))
print("")
print(str(sum(1 for _, ok in results if ok)) + "/" + str(len(results)) + " passate")
