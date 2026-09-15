# -*- coding: utf-8 -*-
"""The way around the water is paid, and moves nothing where there is no water.

The journey node now carries **the side you entered from**, because how much
hexagon you must cross depends on where you enter and where you leave. It is
a change of identity, not an addition: the test that counts is that the
earlier numbers stay where they were, and rise only where the river forces
one to hug the shore.
"""
from kingmaker.geometry import atoms, hexgrid, sections
from kingmaker import travel as v
from kingmaker.state import STATE
from kingmaker.ui import theme

theme.notify = lambda *a, **k: None
theme.mark_dirty = lambda *a, **k: None

A, C = STATE.archive, STATE.campaign
m = STATE.k["map"]
orient = m["orientation"]
COLUMNS, ROWS = 9, 9
results = []


def inside(c):
    return 0 <= c[0] < COLUMNS and 0 <= c[1] < ROWS


def one(_c):
    return 1


def three(_c):
    return 3


# --- 1. without water, every number is the usual one ----------------------
# It is the condition making the change acceptable: on almost the whole map
# there is no water inside the hexagons, and there nothing must move a quarter.
field = v.cost_field((4, 4), one, orient, inside)
results.append(("without water the neighbour costs 1", field.costs.get((5, 4)) == 1))
results.append(("two hexes cost 2", field.costs.get((6, 4)) == 2))
results.append(("three cost 3", field.costs.get((7, 4)) == 3))
field3 = v.cost_field((4, 4), three, orient, inside)
results.append(("and with 3-activity terrain, 3 and 6",
              field3.costs.get((5, 4)) == 3 and field3.costs.get((6, 4)) == 6))
results.append(("the departure hexagon is not paid",
              field.costs.get((4, 4)) == 0))
results.append(("the path is still made of pairs only",
              all(len(p) == 2 for p in v.path((4, 4), (7, 4), one, orient,
                                                  inside))))

# In every direction, not only along a row: the quarter holds because a clean
# crossing passes through four atoms **in all fifteen** directions, and were
# it not so the costs would depend on how you turn.
neighbours = hexgrid.neighbours(4, 4, orient)
results.append(("and costs 1 towards all six neighbours",
              {field.costs.get(tuple(x)) for x in neighbours} == {1}))

# --- 2. a cutting river: whoever stays on their shore pays no more --------
HOME = (4, 4)
water = {HOME: sections.canonical([(0, 3)])}
banks = sections.map_sections({}, None, orient)
faces = sections.faces_of([(0, 3)], orient)
banks = {HOME: faces}
edge = atoms.edge_atoms(orient)
closed = atoms.closed_by_stretches([(0, 3)], orient)
costs = atoms.costs_inside(closed, (), 0.25, orient)
straight_ones = [(x, y) for x in range(6) for y in range(6)
          if x < y and costs.get((edge[x], edge[y])) == 0.75]
long_ones = [(x, y) for x in range(6) for y in range(6)
          if x < y and costs.get((edge[x], edge[y])) == 1.0]
results.append(("with a chord at the center some crossings stay straight",
              len(straight_ones) == 4))
results.append(("and some force one to hug the shore", len(long_ones) == 2))

# The path entering and leaving by the «straight» sides costs as always; the
# one that must hug the shore costs a quarter more. It is measured on the
# plan, which is the number the table reads.
def journey_between(d1, d2):
    enters = tuple(hexgrid.neighbours(HOME[0], HOME[1], orient)[d1])
    exits = tuple(hexgrid.neighbours(HOME[0], HOME[1], orient)[d2])
    cam = [enters, HOME, exits]
    rings = v.rings_on_course(cam, banks, water, {}, orient, one, 0)
    return sum(rings.values())


results.append(("whoever cuts straight pays nothing more",
              journey_between(*straight_ones[0]) == 0))
results.append(("whoever hugs the shore pays a quarter", journey_between(*long_ones[0]) == 0.25))

# --- 3. the river that merely touches is finally paid ---------------------
# It does not divide the hexagon into two shores, so for the earlier model it
# did not exist: no road changed and no cost. Now one goes around it.
touches = {HOME: sections.canonical([(0, None)])}
no_shores = {}
closed_t = atoms.closed_by_stretches([(0, None)], orient)
costs_t = atoms.costs_inside(closed_t, (), 0.25, orient)
worst = max((x, y) for x in range(6) for y in range(6)
               if x < y and costs_t.get((edge[x], edge[y])) == 1.75)
enters = tuple(hexgrid.neighbours(HOME[0], HOME[1], orient)[worst[0]])
exits = tuple(hexgrid.neighbours(HOME[0], HOME[1], orient)[worst[1]])
rings = v.rings_on_course([enters, HOME, exits], no_shores, touches, {}, orient,
                          one, 0)
results.append(("a river dividing nothing has no shores",
              len(sections.faces_of([(0, None)], orient)) == 1))
results.append(("but the way around its mouth costs one more activity",
              rings.get(HOME) == 1.0))
results.append(("that is, the hexagon costs twice what the wiki says",
              abs(1 + rings.get(HOME, 0) - 2.0) < 1e-9))

# --- 4. the plan says so, and in readable quarters ------------------------
waypoints = [(HOME, {"terrains": ["plains"]}, None),
         (exits, {"terrains": ["plains"]}, None)]
plan = v.plan_(waypoints, 7.5, "check", False, [0], {}, enters, False, None,
                    {HOME: 0.5})
results.append(("the plan adds the way around to the total", plan.total_cost == 2.5))
results.append(("and says so in words, in quarters",
              any("hug the shore" in a and "½" in a for a in plan.warnings)))
results.append(("half is written half", v._quarters(0.5) == "½"))
results.append(("and one activity and three quarters is written like this",
              v._quarters(1.75) == "1¾"))

# --- 5. the first and the last hexagon do not pay the way around ----------
# The first is not entered — one was already there — and in the last one
# stops, and stopping pays it in full anyway. They are the two rules keeping
# the earlier counts exactly where they were.
only_two = v.rings_on_course([HOME, exits], no_shores, touches, {}, orient,
                              one, 0)
results.append(("a path of two hexes pays no way around", only_two == {}))
results.append(("and the way around is not counted on the departure hexagon",
              HOME not in v.rings_on_course([HOME, exits, enters], no_shores,
                                             touches, {}, orient, one, 0)))

width = max(len(n) for n, _ in results)
print()
for name, ok in results:
    print(("  ok  " if ok else " NO   ") + name.ljust(width))
print(f"\n{sum(1 for _, ok in results if ok)}/{len(results)} passed")
