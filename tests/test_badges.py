# -*- coding: utf-8 -*-
"""One badge per piece, as much as the piece grants: even inside an atom.

The marker had two fixed sizes — 0.24 in a whole hex, 0.20 in a cut one —
and they held as long as a hex was divided into two or three pieces. With
twenty-four atoms a 0.20 badge is five times the piece it should sit in: one
sees twenty-four overlapping discs and no longer understands who is where.
It was the reason the small pieces stayed a place one could not stand in.

Now the measure is **the area of the piece** — the badge covers about a
tenth of it — and where there is more than one the badge carries **the
number** and not the face of one of the many: a face needs room to be
recognised, a number reads even small. Who is there is told by the box that
opens on click.

The two earlier sizes stay where they were, and not out of respect: they
come out of the new rule on their own.
"""
import itertools

from kingmaker.geometry import waterways, hexgrid, sections
from kingmaker.access import permissions
from kingmaker.state import STATE
from kingmaker.ui import hexmap, theme
import helpers

theme.notify = lambda *a, **k: None
theme.mark_dirty = lambda *a, **k: None
theme.refresh_panels = lambda *a, **k: None
permissions.can = lambda *a, **k: True

A, C = STATE.archive, STATE.campaign
m = STATE.k["map"]
size = float(m["size"])
origin = (float(m["origin_x"]), float(m["origin_y"]))
orient = m["orientation"]
COORD = (9, 4)
results = []


class Allowed:
    id, username, role = "check", "check", permissions.ADMIN
    active = True


theme.user = lambda: Allowed()

# No vehicles on the map: a placed vehicle is a member of its piece of hex
# like a person, and the test scene puts one right here.
for _v in A.list_stable(C):
    A.update_stable_vehicle(_v["id"], hex_col=None, hex_row=None)
# --- 1. the two usual sizes come out of the new rule ----------------------
whole = sections.faces_of([], orient)[0]
two = sections.faces_of([(0, 3)], orient)
results.append(("a whole hex makes a 0.24 badge",
              abs(hexmap.badge_radius(whole, 1.0) - 0.24) < 5e-4))
results.append(("two shores make one of 0.20",
              all(abs(hexmap.badge_radius(f, 1.0) - 0.20) < 5e-4
                  for f in two)))
results.append(("and a shore's badge is smaller than the whole one",
              hexmap.badge_radius(two[0], 1.0)
              < hexmap.badge_radius(whole, 1.0)))

# --- 2. where a river enters and stops, the piece stays big ---------------
# It is the case a measure taken from the centroid would count as tiny: the
# point falls on the slit, and from there to the outline there is zero. The
# area instead counts it for what it is, i.e. the whole hex.
gap = sections.faces_of([(0, None)], orient)[0]
results.append(("a river that enters and stops divides nothing",
              len(sections.faces_of([(0, None)], orient)) == 1))
results.append(("and the slit does not count as a wall: beyond it is the same "
              "piece", sections.breath(gap) > 0.8))
results.append(("so the badge stays that of a whole hex",
              abs(hexmap.badge_radius(gap, 1.0) - 0.24) < 5e-4))
# The slit recognises itself: it is the side the face's ring walks twice,
# once per side.
doubles = [x for x in set(gap.ring) if gap.ring.count(x) > 1]
results.append(("and is recognised from the ring, which walks it twice", bool(doubles)))

# --- 3. twenty-four atoms: twenty-four badges, each in its own ------------
DIAGONALS = [(a, b) for a, b in itertools.combinations(range(6), 2)
             if (b - a) % 6 not in (1, 5)]
atoms = sections.faces_of(DIAGONALS, orient)
results.append(("the nine diagonals make twenty-four pieces", len(atoms) == 24))
narrow_ones = [(hexmap.badge_radius(f, 1.0), sections.breath(f)) for f in atoms
           if hexmap.badge_radius(f, 1.0) > sections.breath(f)]
results.append((f"and everyone's badge fits inside ({len(narrow_ones)} overflow)",
              not narrow_ones))
print("   (in an atom the badge has radius %.3f, and the piece allows %.3f)"
      % (hexmap.badge_radius(atoms[0], 1.0), sections.breath(atoms[0])))

# On every configuration up to three lines, excluding the pieces a slit
# crosses — there «how much room is there around the point» means nothing,
# and it is the area that answers right.
# The real question is not «the badge fits in the largest circle that enters
# the piece» — that measure gets it wrong where a slit passes next to the
# point — but «the badge stays inside **its** piece». The badge's ring is
# taken and every point of it is asked which piece it falls in.
import math as _m

cuts = DIAGONALS + [(a, None) for a in range(6)]


def stays_in_own(faces, index) -> bool:
    face = faces[index]
    r = hexmap.badge_radius(face, 1.0)
    px, py = face.point
    for step in range(16):
        corner = step * _m.pi / 8
        # A hair inside the badge's edge: where the piece is narrow the badge
        # stays **tangent** to it, and a sample taken exactly on the edge
        # would fall on the water line, where «which piece are you in» has no
        # answer.
        where = (px + r * 0.98 * _m.cos(corner), py + r * 0.98 * _m.sin(corner))
        if sections.face_of_point(faces, where) != index:
            return False
    return True


overflow = tried = 0
for n_items in (1, 2, 3):
    for combo in itertools.combinations(cuts, n_items):
        faces_here = sections.faces_of(list(combo), orient)
        for index in range(len(faces_here)):
            tried += 1
            if not stays_in_own(faces_here, index):
                overflow += 1
results.append((f"on {tried} pieces of 575 different drawings, no badge leaves "
              f"its own ({overflow} do)", overflow == 0))

# --- 4. on the map: one badge per atom, and the right one is taken --------
for c in list(A.campaign_banks(C)):
    A.set_banks(C, c, None)
A.remove_crossings(C)
# On the archive the twenty-four atoms are written with the **drawing**, not
# with groups of sides: eighteen atoms out of twenty-four do not touch the
# edge, and a group of sides cannot even name them — it is the defect Phase 7
# closed.
def vertex_name(k):
    return waterways.node_text(waterways.vertex_key(COORD, k, orient))


segments = [(vertex_name(a), vertex_name(b)) for a, b in DIAGONALS]
A.set_banks(C, COORD, waterways.banks_from_cuts(list(range(6))),
               points=segments)
banks = A.campaign_sections(C, orient)
faces = banks.get(COORD) or ()
results.append(("the map hex has twenty-four shores", len(faces) == 24))

cx, cy = hexgrid.hex_center(COORD[0], COORD[1], size, origin, orient)
people = []
for index in range(len(faces)):
    px, py = sections.section_spot(faces, index)
    people.append({"id": f"p{index}", "name": f"Tizio {index}",
                  "hex_col": COORD[0], "hex_row": COORD[1],
                  "pos_x": px, "pos_y": py, "color": "#ffffff"})
seats = hexmap.marker_positions(people, cx, cy, size, COORD, origin, orient,
                                   banks)
results.append((f"ventiquattro persone in ventiquattro atomi fanno "
              f"{len(seats)} tondi", len(seats) == len(faces)))
results.append(("one each", all(len(g) == 1 for g, _x, _y, _r in seats)))
inside_its_own = 0
for group, x, y, radius in seats:
    index = hexmap.section_of(group[0], banks)
    wide = sections.breath(faces[index]) * size
    if radius <= wide + 1e-6:
        inside_its_own += 1
results.append((f"and each sits inside its own atom ({inside_its_own}/{len(seats)})",
              inside_its_own == len(seats)))
distinct = len({(round(x, 1), round(y, 1)) for _g, x, y, _r in seats})
results.append(("in twenty-four distinct places", distinct == len(seats)))

real_on = hexmap.characters_on
helpers.silence("characters_on", lambda c, vis: people if tuple(c) == COORD else [])
try:
    fake_one = type("V", (), {"gm": True, "markers": lambda self: people,
                           "can_see": lambda self, c, r: True})()
    taken_ones = 0
    for group, x, y, _r in seats:
        where = hexgrid.pixel_to_hex(x, y, size, origin, orient)
        taken = hexmap.marker_under(fake_one, m, (x, y), where)
        if taken is not None and [q["id"] for q in taken] == [q["id"] for q in group]:
            taken_ones += 1
    results.append((f"and clicking an atom picks whoever is there ({taken_ones}/{len(seats)})",
                  taken_ones == len(seats)))
finally:
    helpers.silence("characters_on", real_on)

# --- 5. a group's badge is the number, not a face -------------------------
A.set_banks(C, COORD, None)
A.set_banks(C, COORD, [[0, 1, 2], [3, 4, 5]])
banks = A.campaign_sections(C, orient)
faces = banks[COORD]
px, py = sections.section_spot(faces, 0)
three = [{"id": f"g{i}", "name": f"Tale {i}", "hex_col": COORD[0],
        "hex_row": COORD[1], "pos_x": px, "pos_y": py, "color": "#ff0000",
        "token": "finto.png"} for i in range(3)]
only = [dict(three[0], id="only")]

helpers.silence("characters_on", lambda c, vis: [])
try:
    def draw(who):
        fake_one = type("V", (), {"gm": True, "markers": lambda self: who,
                               "can_see": lambda self, c, r: True})()
        return "".join(hexmap._svg_markers(fake_one, size, origin, orient, set()))

    svg_group = draw(three)
    svg_only = draw(only)
    results.append(("three in the same piece draw a badge with the number 3",
                  ">3</text>" in svg_group))
    results.append(("and not the face of one of the three",
                  "<image" not in svg_group))
    results.append(("a single one instead is drawn with their face",
                  "<image" in svg_only and ">3</text>" not in svg_only))
    results.append(("and without a number on it",
                  svg_only.count("</text>") == 1))   # their initials, and no more
finally:
    helpers.silence("characters_on", real_on)

# --- 6. the click grip does not go below a minimum ------------------------
# A badge inside an atom is perfectly visible and would be badly grabbed: the
# target stays wide even when the drawing is small. Between two hit badges
# the nearest wins anyway, so the generous hand steals nothing from the
# neighbour.
results.append(("the grip of a big badge is the badge itself",
              hexmap._grip(size * 0.24, size) == size * 0.24))
results.append(("that of a badge inside an atom is wider than the badge",
              hexmap._grip(size * 0.055, size) > size * 0.055))

A.set_banks(C, COORD, None)

width = max(len(n) for n, _ in results)
print()
for name, ok in results:
    print(("  ok  " if ok else " NO   ") + name.ljust(width))
print(f"\n{sum(1 for _, ok in results if ok)}/{len(results)} passed")
