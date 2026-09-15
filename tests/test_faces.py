# -*- coding: utf-8 -*-
"""A section is a face, not a set of sides.

The old model counted sections by looking at the vertices of the edge touched
by the water. For the normal case it worked out; for three cases it did not,
and the difference is measured in section 13 of `docs/manual/09-water-travel.md`.
Here it is shown that the new model catches all three, and that the properties
everything else rests on — every side on a single face, the faces covering the
hexagon, a point inside each one — hold for **every** drawable cut, not only
for those we thought of.
"""
import itertools
import math

from kingmaker.geometry import waterways, sections
from kingmaker import travel as v

ORIENT = "pointy"
HEX_AREA = 3 * math.sqrt(3) / 2
results = []

# --- 1. the six measured cases ---------------------------------------------
DIAGONALS = [(a, b) for a, b in itertools.combinations(range(6), 2)
             if (b - a) % 6 not in (1, 5)]
measures = [("a single chord", [(0, 3)], 2),
          ("two crossing chords", [(0, 3), (1, 4)], 4),
          ("two separate chords", [(0, 2), (3, 5)], 3),
          ("confluence at the center", [(0, 3), (1, 4), (2, 5)], 6),
          ("a triangle inside", [(0, 2), (2, 4), (4, 0)], 4),
          ("all the diagonals", DIAGONALS, 24)]
for name, cuts, is_expected in measures:
    n_items = len(sections.faces_of(cuts, ORIENT))
    results.append((f"{name}: {n_items} sections (expected {is_expected})", n_items == is_expected))

# The same three cases with the old model, to show it is not a tautological
# test: there the numbers are different.
old_items = {name: len(waterways.banks_from_cuts([k for c in cuts for k in c]))
           for name, cuts, _a in measures}
results.append(("the old model on «two separate chords» counted four",
              old_items["two separate chords"] == 4))
results.append(("and on «all the diagonals» stopped at six",
              old_items["all the diagonals"] == 6))

# --- 2. the island exists and cannot be reached on foot --------------------
island = sections.faces_of([(0, 2), (2, 4), (4, 0)], ORIENT)
without_sides = [f for f in island if not f.sides]
results.append(("the triangle in the middle is a section", len(without_sides) == 1))
results.append(("and touches no side, so it has no steps",
              not list(v.steps_from((4, 4, island.index(without_sides[0])), ORIENT,
                                  {(4, 4): island}))))
results.append(("while the other three do have steps",
              all(list(v.steps_from((4, 4, i), ORIENT, {(4, 4): island}))
                  for i, f in enumerate(island) if f.sides)))

# --- 3. the properties on EVERY drawable cut -------------------------------
# Everything the brush can hook: chords between two vertices and spokes from
# a vertex to the center, one, two and three at a time. Not a sample: all.
ends = ([(a, b) for a, b in itertools.combinations(range(6), 2)]
        + [(k, None) for k in range(6)])
everyone = [list(c) for q in (1, 2, 3) for c in itertools.combinations(ends, q)]
broken = {"area": 0, "sides": 0, "point": 0, "empty_ones": 0}
for orient in ("pointy", "flat"):
    for cuts in everyone:
        faces = sections.faces_of(cuts, orient)
        if abs(sum(f.area for f in faces) - HEX_AREA) > 1e-9:
            broken["area"] += 1
        if sorted(d for f in faces for d in f.sides) != list(range(6)):
            broken["sides"] += 1
        for f in faces:
            if not sections._inside(f.point[0], f.point[1], f.ring):
                broken["point"] += 1
            if f.area <= 1e-9:
                broken["empty_ones"] += 1
print(f"   ({len(everyone)} cuts for two orientations, "
      f"{len(everyone) * 2} hexes cut up)")
results.append(("the faces always cover the hexagon, exactly",
              broken["area"] == 0))
results.append(("every side always sits on a single face", broken["sides"] == 0))
results.append(("the point of a face always sits inside it",
              broken["point"] == 0))
results.append(("there is no face without an area", broken["empty_ones"] == 0))

# --- 4. the case that broke the tracer: two overlapping lines --------------
# A spoke leaving vertex 0 lies *inside* the chord going from vertex 0 to 3,
# and two overlapping lines cross nowhere: the point in the middle of the
# chord was not recorded, the walk around the faces went over the same lines
# again and the hexagon came out ten times its own size.
overlapping = sections.faces_of([(0, 3), (0, None)], ORIENT)
results.append(("an overlapping chord and spoke give two sections",
              len(overlapping) == 2))
results.append(("and the hexagon stays as big as it is",
              abs(sum(f.area for f in overlapping) - HEX_AREA) < 1e-9))
# The T junction: a spoke arriving in the middle of a chord.
ti = sections.faces_of([(0, 3), (1, None)], ORIENT)
results.append(("a spoke ending in the middle of a chord cuts in three",
              len(ti) == 3))

# --- 5. a line along a side cuts nothing -----------------------------------
# That is the water flowing on the edge, and it lives in the `borders`, not
# here. Before, it produced a zero-width shore with no centroid: the marker of
# whoever stood there ended up at the center of the hexagon, as if nowhere.
on_the_side = sections.faces_of([(0, 1)], ORIENT)
results.append(("a line lying on a side leaves the hexagon whole",
              len(on_the_side) == 1 and on_the_side[0].sides == (0, 1, 2, 3, 4, 5)))

# --- 6. a stretch that enters and stops does not divide --------------------
branch = sections.faces_of([(0, None)], ORIENT)
results.append(("a stretch that enters and stops in the middle does not divide",
              len(branch) == 1))

# --- 7. the numbers stay as before where the models agree ------------------
# It is what lets one sleep soundly: on the real map almost every cut hexagon
# has a river entering on one side and leaving on the other, and there the
# shore number must not change under anybody's feet.
equal = 0
for k1 in range(6):
    for k2 in range(6):
        groups = waterways.banks_from_cuts([k1, k2])
        if len(groups) != 2:
            continue
        faces = sections.faces_of(waterways.vertex_cuts(groups), ORIENT)
        if len(faces) != 2:
            continue
        if [list(f.sides) for f in faces] == [list(g) for g in groups]:
            equal += 1
results.append((f"on {equal} simple cuts the numbering is the identity",
              equal >= 15))

# --- 8. the translation of the old number goes through the place ------------
groups = [[0, 1, 2], [3, 4, 5]]
faces = sections.faces_of(sections.cuts_from_groups(groups), ORIENT)
results.append(("the old shore 0 finds the face with its sides again",
              sections.sides_of(faces[sections.remap_bank(groups, faces, 0,
                                                         ORIENT)]) == (0, 1, 2)))
results.append(("and the old 1 its own",
              sections.sides_of(faces[sections.remap_bank(groups, faces, 1,
                                                         ORIENT)]) == (3, 4, 5)))

# --- 9. from the saved drawing to the sections -----------------------------
COORD = (9, 4)
segments = [(waterways.node_text(waterways.vertex_key(COORD, 0, ORIENT)),
             waterways.node_text(waterways.vertex_key(COORD, 3, ORIENT)))]
results.append(("a saved segment is read back as a local cut",
              sections.local_cuts(COORD, segments, ORIENT) == ((0, 3),)))
mapping = sections.map_sections({COORD: segments}, {}, ORIENT)
results.append(("and the hexagon enters the sections map", COORD in mapping))
results.append(("a dry hexagon instead does not",
              sections.map_sections({(1, 1): []}, {}, ORIENT) == {}))
results.append(("whoever has only the groups and not the drawing gets there all the same",
              len(sections.map_sections({}, {COORD: groups},
                                              ORIENT).get(COORD, ())) == 2))

# --- 10. the same drawing always gives the same numbers --------------------
one = sections.faces_of([(0, 3), (1, 4)], ORIENT)
two = sections.faces_of([(4, 1), (3, 0)], ORIENT)          # written backwards
results.append(("the same cut written backwards gives the same faces",
              [f.sides for f in one] == [f.sides for f in two]))

# --- 11. the bank of a side is always a single one -------------------------
wrong = 0
for cuts in everyone[:400]:
    faces = sections.faces_of(cuts, ORIENT)
    for direction in range(6):
        index = v.bank_of_side({(4, 4): faces}, (4, 4), direction)
        if direction not in sections.sides_of(faces[index]):
            wrong += 1
results.append(("`bank_of_side` always answers with the right face",
              wrong == 0))

width = max(len(n) for n, _ in results)
print()
for name, ok in results:
    print(("  ok  " if ok else " NO   ") + name.ljust(width))
print(f"\n{sum(1 for _, ok in results if ok)}/{len(results)} passed")
