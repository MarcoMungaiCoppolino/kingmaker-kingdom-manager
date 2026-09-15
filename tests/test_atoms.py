# -*- coding: utf-8 -*-
"""The hex as 24 fixed pieces: the properties everything else rests on.

It is not a behaviour test, it is a **geometry** test: the things in here
are either true by construction or the model does not stand. They run on
every drawable cut, not on a sample, because any error fits a sample.
"""
import itertools

from kingmaker.geometry import atoms, sections

results = []
ORIENTATIONS = ("pointy", "flat")
HEX_AREA = 3 * 3 ** 0.5 / 2

# --- 1. twenty-four, and the count is closed ------------------------------
# The nine diagonals make 24 pieces; adding the six radii to the center or
# the six sides adds not a single one. It is the reason a water line is
# **exactly** a set of borders between atoms, and not approximately.
chords = [(a, b) for a, b in itertools.combinations(range(6), 2)]
radii = [(k, None) for k in range(6)]
for orient in ORIENTATIONS:
    results.append((f"[{orient}] twenty-four atoms",
                  len(atoms.atoms(orient)) == atoms.HOW_MANY))
    results.append((f"[{orient}] thirty-six sides",
                  len(atoms.sides(orient)) == atoms.SIDE_COUNT))
    results.append((f"[{orient}] adding spokes and sides does not change the cut-out",
                  len(sections.faces_of(list(atoms.DIAGONALS) + chords + radii,
                                       orient)) == atoms.HOW_MANY))
    results.append((f"[{orient}] the atoms cover the hexagon, exactly",
                  abs(sum(a.area for a in atoms.atoms(orient))
                      - HEX_AREA) < 1e-9))
    results.append((f"[{orient}] six atoms touch the edge, one per side",
                  sorted(atoms.edge_atoms(orient)) == list(range(6))))

# Every border lies on a drawable line: it is the property that makes the
# model exact. It is tested the other way round — every border must be closed
# by at least one line — because that way none can be forgotten.
for orient in ORIENTATIONS:
    covered = set()
    for cut in chords + radii:
        covered |= atoms.closed_by_stretches([cut], orient)
    results.append((f"[{orient}] every side lies on a drawable line",
                  covered == set(range(atoms.SIDE_COUNT))))

# --- 2. the clean hex costs four, in every direction ----------------------
# It is the number that holds the cost up: a quarter per atom is paid, and
# four quarters make the full cost of the rules. If this changed, every
# journey on the map would change.
for orient in ORIENTATIONS:
    edge = atoms.edge_atoms(orient)
    pairs = list(itertools.combinations(sorted(edge), 2))
    n_items = {atoms.dist(edge[x], edge[y], frozenset(), orient)
              for x, y in pairs}
    results.append((f"[{orient}] a clean hexagon costs 4 atoms, in all 15 "
                  "directions", n_items == {4}))

# --- 3. without the jumps by point the count falls apart -----------------
# Worth testing: it is the reason the jumps by point exist, and without this
# line they would look like a convenience instead of a necessity.
sides_only = {i: {b for n, (who, _t) in enumerate(atoms.sides("pointy"))
                 for a, b in (who, who[::-1]) if a == i}
             for i in range(atoms.HOW_MANY)}


def sides_only_count(from_, a):
    from collections import deque
    if from_ == a:
        return 1
    seen, queue = {from_: 1}, deque([from_])
    while queue:
        q = queue.popleft()
        for r in sides_only[q]:
            if r not in seen:
                seen[r] = seen[q] + 1
                if r == a:
                    return seen[r]
                queue.append(r)
    return None


edge = atoms.edge_atoms("pointy")
without = {sides_only_count(edge[x], edge[y])
         for x, y in itertools.combinations(sorted(edge), 2)}
results.append(("without the jumps by point a clean hex would cost 4, 7 or 8",
              without == {4, 7, 8}))

# --- 4. the two models tell the same hex ----------------------------------
# The atoms' provinces are the faces of `sections`. On **every** cut up to
# three lines, not on some: it is the only way to know the two models do not
# diverge in a case nobody had thought of.
possible_ones = chords + radii
everyone = [list(c) for q in (1, 2, 3) for c in itertools.combinations(possible_ones, q)]
different = lean = 0
for cuts in everyone:
    closed = atoms.closed_by_stretches(cuts, "pointy")
    tst = atoms.provinces(closed, "pointy")
    faces = sections.faces_of(cuts, "pointy")
    if len(tst) != len(faces):
        different += 1
    if sorted(d for p in tst for i in p for d in atoms.atoms("pointy")[i].sides) \
            != sorted(d for f in faces for d in f.sides):
        lean += 1
print(f"   ({len(everyone)} cuts tried)")
results.append(("the atoms' provinces are the sections' faces, always",
              different == 0))
results.append(("and they share out the hex sides the same way", lean == 0))

# --- 5. the cost never goes below the cost of the rules ------------------
# The water can only lengthen or forbid. If a crossing cost less than four
# atoms, a river would save time.
short = 0
histogram = {}
for cuts in everyone:
    closed = atoms.closed_by_stretches(cuts, "pointy")
    for x, y in itertools.combinations(sorted(edge), 2):
        n = atoms.dist(edge[x], edge[y], closed, "pointy")
        histogram[n] = histogram.get(n, 0) + 1
        if n is not None and n < 4:
            short += 1
print("   cost of the crossings: "
      + " ".join(f"{'forbidden' if n is None else str(n) + ' atoms'}:{q}"
                 for n, q in sorted(histogram.items(),
                                    key=lambda x: (x[0] is None, x[0]))))
results.append(("no crossing costs less than four atoms", short == 0))

# --- 6. the three cases chapter 12 tells ----------------------------------
def crossed_ones(cuts):
    closed = atoms.closed_by_stretches(cuts, "pointy")
    return sorted((atoms.dist(edge[x], edge[y], closed, "pointy") or 0)
                  for x, y in itertools.combinations(sorted(edge), 2))


straight_one = crossed_ones([(0, 3)])
results.append(("a chord from side to side forbids 9 crossings out of 15",
              straight_one.count(0) == 9))
touches = crossed_ones([(0, None)])
results.append(("a river that merely touches forbids none",
              touches.count(0) == 0))
results.append(("but lengthens the longest from 4 atoms to 8", max(touches) == 8))
results.append(("and leaves some at 4: whoever does not pass near it does not pay",
              touches.count(4) == 5))

# --- 7. the jumps by point do not join different provinces ---------------
# If they did, «being on the same shore» and «being able to reach each
# other» would no longer be the same thing, and the whole rest of the app
# speaks of shores.
wrong = 0
for cuts in everyone[:400]:
    closed = atoms.closed_by_stretches(cuts, "pointy")
    where = {}
    for number, group in enumerate(atoms.provinces(closed, "pointy")):
        for i in group:
            where[i] = number
    for i, neighbours in atoms.graph(closed, "pointy").items():
        for j in neighbours:
            if where[i] != where[j]:
                wrong += 1
results.append(("a step never leads into another province", wrong == 0))

# --- 8. the atoms are never renumbered ------------------------------------
# It is the property that makes the redraw business vanish on its own: a
# section number changes meaning as soon as the GM draws a line, an atom
# number does not, because atoms do not depend on what is drawn.
first_ones = [a.point for a in atoms.atoms("pointy")]
atoms.closed_by_stretches([(0, 3), (1, 4), (2, 5)], "pointy")
results.append(("the atoms stay the same whatever is drawn",
              [a.point for a in atoms.atoms("pointy")] == first_ones))

# --- 9. the count inside a hex, bridges included --------------------------
# `costs_inside` answers «what does going from this atom to that one cost»,
# **after** getting there: the entry quarter is paid by whoever enters. So
# the clean crossing is worth 0.25 (entering) + 0.75 (crossing) = 1, the full
# cost of the rules. It is the number that must not move.
QUARTER = 0.25
is_clean = atoms.costs_inside(frozenset(), (), QUARTER, "pointy")
between_sides = {is_clean.get((edge[x], edge[y]))
            for x, y in itertools.combinations(sorted(edge), 2)}
results.append(("in a clean hex crossing costs 0.75 from every side to "
              "every other", between_sides == {0.75}))
results.append(("i.e. a whole hex costs exactly the cost of the rules",
              all(abs(QUARTER + c - 1.0) < 1e-9 for c in between_sides)))

closed_one = atoms.closed_by_stretches([(0, 3)], "pointy")
inner_closed = atoms.costs_inside(closed_one, (), QUARTER, "pointy")
values = [inner_closed.get((edge[x], edge[y]))
          for x, y in itertools.combinations(sorted(edge), 2)]
results.append(("with a chord through the center, nine crossings have no price",
              values.count(None) == 9))
results.append(("and the others cost 0.75 or 1: coasting along is paid",
              set(v for v in values if v is not None) == {0.75, 1.0}))

touches_ch = atoms.closed_by_stretches([(0, None)], "pointy")
inner_touch = atoms.costs_inside(touches_ch, (), QUARTER, "pointy")
values = [inner_touch[(edge[x], edge[y])]
          for x, y in itertools.combinations(sorted(edge), 2)]
results.append(("a river that merely touches forbids nothing", None not in values))
results.append(("but the detour around the mouth comes to cost double",
              abs(max(values) - 1.75) < 1e-9))

# A crossing reopens **a stretch**, not a pair of distant atoms: a bridge
# sits on the water, it is not a shortcut between any two places.
one_stretch = sorted(closed_one)[0]
bridge_col = atoms.costs_inside(closed_one, ((one_stretch, 0.0),), QUARTER, "pointy")
results.append(("a bridge on a stretch reopens every crossing",
              all(bridge_col.get((edge[x], edge[y])) is not None
                  for x, y in itertools.combinations(sorted(edge), 2))))
# Crossing never costs **less** than cutting through a clean hex: the bridge
# opens a road, it does not gift a shorter one. Where it happens to be right
# on the way it can cost exactly as much as dry land, and rightly so — a
# bridge on your course does not make you lose time.
results.append(("crossing never costs less than a clean hex",
              min(bridge_col[(edge[x], edge[y])]
                  for x, y in itertools.combinations(sorted(edge), 2)
                  if inner_closed.get((edge[x], edge[y])) is None) >= 0.75))
ford_col = atoms.costs_inside(closed_one, tuple((l, 1.0) for l in closed_one), QUARTER,
                               "pointy")
results.append(("a ford on the whole line charges its price at every "
              "passage",
              min(ford_col[(edge[x], edge[y])]
                  for x, y in itertools.combinations(sorted(edge), 2)
                  if inner_closed.get((edge[x], edge[y])) is None) >= 1.75))
# The bridge opens its stretch, not the point where it ends: going around a
# junction reached by water stays forbidden, or one would walk dry over a
# film of water the bridge does not cover.
without_bridge = atoms.graph(closed_one, (), "pointy")
with_bridge = atoms.graph(closed_one, (one_stretch,), "pointy")
who = atoms.sides("pointy")[one_stretch][0]
results.append(("the bridge opens the step between the two atoms of its stretch",
              who[1] in with_bridge[who[0]] and who[1] not in without_bridge[who[0]]))
results.append(("and opens nothing else",
              sum(len(v) for v in with_bridge.values())
              == sum(len(v) for v in without_bridge.values()) + 2))

width = max(len(n) for n, _ in results)
print()
for name, ok in results:
    print(("  ok  " if ok else " NO   ") + name.ljust(width))
print(f"\n{sum(1 for _, ok in results if ok)}/{len(results)} passed")
