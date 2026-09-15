# -*- coding: utf-8 -*-
"""The GM redraws the water under people's feet, and the people do not move.

It is the reason why on disk there is no longer a shore number but a
**place**. A number counts the faces: draw another water line and the same
number points at another piece of hexagon, so whoever did not move finds
themselves on the other side of the river. A point stays where it is, and
the section is recomputed around it.

Here precisely that is tested, and also that not everything has become
permissive: two on opposite shores stay two, and the bridge joining them
keeps joining **those**.
"""
from kingmaker.geometry import sections
from kingmaker import travel as v
from kingmaker.state import STATE
from kingmaker.ui import hexmap, theme
import helpers

theme.notify = lambda *a, **k: None
theme.mark_dirty = lambda *a, **k: None

A, C = STATE.archive, STATE.campaign
m = STATE.k["map"]
size, orient = float(m["size"]), m["orientation"]
origin = (float(m["origin_x"]), float(m["origin_y"]))
HOME = (12, 6)
ONE_CUT = [[0, 1, 2], [3, 4, 5]]
results = []

A.remove_crossings(C)
for c in list(A.campaign_banks(C)):
    A.set_banks(C, c, None)
A.set_banks(C, HOME, ONE_CUT)
faces = A.campaign_sections(C, orient)[HOME]

people = STATE.characters()[:2]
assert len(people) == 2, "servono due characters"
for index, char in enumerate(people):
    point = sections.section_spot(faces, index)
    A.update_character(char["id"], hex_col=HOME[0], hex_row=HOME[1],
                           pos_x=point[0], pos_y=point[1])
ids = {p["id"] for p in people}


def shores():
    banks = hexmap.sections_map()
    return {p["id"]: hexmap.section_of(p, banks)
            for p in STATE.characters() if p["id"] in ids}


def in_pixels():
    banks = hexmap.sections_map()
    outside = {}
    for p in STATE.characters():
        if p["id"] in ids:
            outside[p["id"]] = hexmap.bank_point(
                HOME, hexmap.section_of(p, banks), size, origin, orient, banks)
    return outside


shores_before, pixel_before = shores(), in_pixels()
results.append(("with a single cut, the two sit on two shores",
              len(set(shores_before.values())) == 2))

# A bridge between the two shores, placed with the real gesture: two opposite vertices.
corners = sections.unit_corners(orient)
ends, above, joined = sections.hop(faces, corners[1], corners[4])
A.set_crossing(C, HOME, ends, above)
bridge = A.campaign_crossings(C)[HOME][0]
results.append(("and the bridge joins them",
              sections.crossing_shores(faces, bridge["ends"]) is not None))

# --- the GM draws a second river in the same hexagon ----------------------
A.set_banks(C, HOME, helpers.add_cut(ONE_CUT, 1, 5))
after_faces = A.campaign_sections(C, orient)[HOME]
after_shores, after_pixel = shores(), in_pixels()

results.append(("the second river makes more sections than before",
              len(after_faces) > len(faces)))
results.append(("the shore numbers really change",
              shores_before != after_shores))
results.append(("nobody changes hexagon",
              all((p["hex_col"], p["hex_row"]) == HOME
                  for p in STATE.characters() if p["id"] in ids)))
results.append(("nobody loses their place",
              all(sections.saved_spot(p) is not None
                  for p in STATE.characters() if p["id"] in ids)))
results.append(("everyone sits in the section containing their point",
              all(sections.face_of_point(after_faces, sections.saved_spot(p))
                  == after_shores[p["id"]]
                  for p in STATE.characters() if p["id"] in ids)))
results.append(("and they stay on two different shores",
              len(set(after_shores.values())) == 2))
# The drawing moves — the section is smaller, the centroid too — but by
# little: the marker stays in the half of the hexagon it was in.
rejects = [max(abs(pixel_before[i][0] - after_pixel[i][0]),
              abs(pixel_before[i][1] - after_pixel[i][1])) for i in ids]
print("   spostamento del disegno: %.0f e %.0f px su un raggio di %.0f"
      % (rejects[0], rejects[1], size))
results.append(("the marker moves a little, it does not jump the river",
              all(s < size * 0.6 for s in rejects)))

# --- the bridge survives, and still joins two shores ----------------------
banks = hexmap.sections_map()
crossings = A.campaign_crossings(C)
joined_after = sections.crossing_shores(after_faces, crossings[HOME][0]["ends"])
results.append(("the bridge still joins two shores", joined_after is not None))
results.append(("and from one you really pass to the other",
              joined_after is not None
              and (HOME[0], HOME[1], joined_after[1])
              in [n for n, _x in v.inner_passages(
                  (HOME[0], HOME[1], joined_after[0]), banks, crossings)]))
results.append(("and one still knows where to draw it",
              hexmap._bridge_span(HOME, after_faces, crossings[HOME][0],
                                         size, origin, orient) is not None))

# --- with the water removed, the bridge switches itself off ---------------
A.set_banks(C, HOME, None)
is_dry = hexmap.sections_map()
results.append(("with no more water the hexagon has no sections",
              HOME not in is_dry))
results.append(("and the bridge no longer crosses anything",
              not list(v.inner_passages((HOME[0], HOME[1], 0), is_dry,
                                          A.campaign_crossings(C)))))

A.remove_crossings(C)
for p in people:
    A.update_character(p["id"], pos_x=None, pos_y=None)

width = max(len(n) for n, _ in results)
print()
for name, ok in results:
    print(("  ok  " if ok else " NO   ") + name.ljust(width))
print(f"\n{sum(1 for _, ok in results if ok)}/{len(results)} passed")
