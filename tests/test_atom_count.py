# -*- coding: utf-8 -*-
"""The atom count: a single one, for the ruler and for the server.

Before there were two coins. The browser counted a quarter for every shore
hop; the server counted the shortest way between atoms from where you enter
to where you leave, and kept nothing of the road drawn by hand inside the
hex. On release the number changed, and with it the shape of the arrow.

Now it is a single count (`atoms.course_by_waypoints`, and its copy in
JavaScript): one enters from a side, touches the shores the hand touched in
the order it touched them, leaves by the side needed or stops in the aimed
piece, and every atom entered is a quarter. The browser does not get the
graph: it gets the atom geometry once and, for every cut hex, a 36-bit
**mask**.

Here the Python side is tested. The JavaScript side is tested by bench
`bench10` (identical graph and courses on 575 configurations) and `bench11`
(same number and same arrow on the real payload).
"""
import itertools
import json

from kingmaker.geometry import atoms, sections
from kingmaker.access import permissions
from kingmaker import travel as v
from kingmaker.state import STATE
from kingmaker.ui import hexmap, theme

theme.notify = lambda *a, **k: None
theme.mark_dirty = lambda *a, **k: None
theme.refresh_panels = lambda *a, **k: None
permissions.can = lambda *a, **k: True

A, C = STATE.archive, STATE.campaign
m = STATE.k["map"]
orient = m["orientation"]
O = orient
results = []


class Allowed:
    id, username, role = "check", "check", permissions.ADMIN
    active = True


theme.user = lambda: Allowed()

# --- 1. the mask: 36 bits that go and come back --------------------------
cuts = [(0, 3), (1, None)]
closed = atoms.closed_by_stretches(cuts, O)
number = atoms.mask(closed)
results.append(("the mask of a drawing is a number", isinstance(number, int)))
results.append(("that fits in 36 bits", 0 <= number < 2 ** 36))
results.append(("and from the number one gets back the same borders",
              atoms.from_mask(number) == closed))
results.append(("it goes through JSON without losing a bit",
              json.loads(json.dumps(number)) == number))
geo = atoms.for_browser(O)
results.append(("the geometry for the browser has 24 points, 36 sides, 13 junctions, "
              "6 edge atoms",
              (len(geo["points"]), len(geo["sides"]), len(geo["crossings_"]),
               len(geo["edge"])) == (24, 36, 13, 6)))

# --- 2. without waypoints it is the shortest way, i.e. the table ----------
edge = atoms.edge_atoms(O)
table = atoms.costs_inside(closed, (), 0.25, O)
equal = different = 0
for from_ in range(6):
    for a in range(6):
        outcome = atoms.course_by_waypoints(closed, (), edge[from_], [], edge[a], 0.25, O)
        is_expected = table.get((edge[from_], edge[a]))
        if (outcome is None and is_expected is None) or (
                outcome is not None and is_expected is not None
                and abs(outcome[0] - is_expected) < 1e-9):
            equal += 1
        else:
            different += 1
results.append((f"without waypoints the waypoint path is the table ({equal}/36)",
              different == 0))

# On every configuration up to two lines, for every pair of sides.
tp = list(atoms.DIAGONALS) + [(k, None) for k in range(6)]
different = tried = 0
for n in (1, 2):
    for combo in itertools.combinations(tp, n):
        ch = atoms.closed_by_stretches(list(combo), O)
        tab = atoms.costs_inside(ch, (), 0.25, O)
        for from_ in range(6):
            for a in range(6):
                tried += 1
                e = atoms.course_by_waypoints(ch, (), edge[from_], [], edge[a], 0.25, O)
                act = tab.get((edge[from_], edge[a]))
                if not ((e is None and act is None)
                        or (e is not None and act is not None
                            and abs(e[0] - act) < 1e-9)):
                    different += 1
results.append((f"and it is on {tried} crossings of at most {n} lines",
              different == 0))

# --- 3. with waypoints the road made is paid ------------------------------
# The confluence of the figure: three shores A B C, three bridges, one enters
# by side 0 and stops in C passing through B. Eleven atoms, two activities and
# three quarters.
CUTS = [(0, None), (2, None), (4, None)]
closed = atoms.closed_by_stretches(CUTS, O)
faces = sections.faces_of(CUTS, O)
shores = v.shore_atoms(faces, O)
results.append(("the three shores share out the 24 atoms",
              sorted(len(s) for s in shores) == [8, 8, 8]
              and set().union(*shores) == set(range(24))))
of_test = {a: k for k, s in enumerate(shores) for a in s}
A_, B_, C_ = of_test[edge[0]], of_test[edge[2]], of_test[edge[4]]


def bridge_between(p, q):
    cand = [n for n in closed
            if {of_test[x] for x in atoms.sides(O)[n][0]} == {p, q}]
    return max(cand, key=lambda n: sum(
        (atoms.atoms(O)[x].point[0] ** 2 + atoms.atoms(O)[x].point[1] ** 2)
        for x in atoms.sides(O)[n][0]))


openings = [(bridge_between(A_, B_), 0.0), (bridge_between(B_, C_), 0.0), (bridge_between(A_, C_), 0.0)]
destination = atoms.atom_of_point(faces[C_].point, O)
straight_one = atoms.course_by_waypoints(closed, openings, edge[0], [], destination, 0.25, O)
# The hand's road: A, then B, then C — constrained, i.e. without passing
# through a third shore between one and the next.
for_b = atoms.course_by_waypoints(closed, openings, edge[0],
                              [shores[A_], shores[B_], shores[C_]], destination,
                              0.25, O, constrained=True)
# Without the constraint the count finds better — A, C, a hop into B, C again
# — which costs a quarter less but is not the tour the hand made.
free = atoms.course_by_waypoints(closed, openings, edge[0], [shores[B_]], destination,
                               0.25, O)
results.append(("from side 0 to C straight: 4 atoms, one activity",
              straight_one is not None and len(straight_one[1]) == 4
              and abs(straight_one[0] - 0.75) < 1e-9))
results.append(("through B as the hand did: 11 atoms, ten steps, 2½",
              for_b is not None and len(for_b[1]) == 11
              and abs(for_b[0] - 2.5) < 1e-9))
results.append(("without the constraint the count would find a shorter tour that is "
              "not the hand's",
              free is not None and free[0] < for_b[0]))
results.append(("and the hand's road does not enter C before B",
              for_b is not None and all(
                  a not in shores[C_] for a in for_b[1][:next(
                      k for k, a in enumerate(for_b[1]) if a in shores[B_])])))
results.append(("and the road to B really touches B",
              for_b is not None and any(a in shores[B_] for a in for_b[1])))
# That the waypoint does not lead «to the centroid of B» is told by the eleven
# atoms: to the centroid and back would be more. If then the shortest way
# inside B passes through its central atom, it is a fact of geometry, not a
# detour.
results.append(("where there is no way through, the course says so",
              atoms.course_by_waypoints(closed, (), edge[0], [], destination, 0.25, O)
              is None))

# --- 4. the tie-break is fixed: at equal cost always the same course -----
one = atoms.course_by_waypoints(closed, openings, edge[0], [shores[B_]], destination, 0.25, O)
two = atoms.course_by_waypoints(closed, openings, edge[0], [shores[B_]], destination, 0.25, O)
results.append(("the same course twice is the same course", one == two))

# --- 5. on the real map: the proposed road costs what it used to ---------
# Without a drawn road, the atom count is the shortest way: from every
# character, towards every reachable hex, the plan must say the same number
# as the cost field — which is the earlier count, and does not move.
banks = A.campaign_sections(C, orient)
water = A.campaign_water(C, orient)
crossings = A.campaign_crossings(C)
borders = A.campaign_borders(C)
difficulty = A.campaign_difficulty(C)
columns, rows = int(m["columns"]), int(m["rows"])
inside = lambda c: 0 <= c[0] < columns and 0 <= c[1] < rows
view = hexmap._current_view({"player_preview": False})
cost_of = lambda c: hexmap._cost_for(view, difficulty, c, False)
passage = (lambda a, b: v.border_cost(a, b, borders, False)) if borders else None
rejects, destinations, lost_ones = [], 0, 0
for char in STATE.characters()[:2]:
    if char["hex_col"] is None:
        continue
    departure = (char["hex_col"], char["hex_row"])
    bank = hexmap.section_of(char, banks)
    field = v.cost_field(departure, cost_of, orient, inside, None, passage,
                          banks, bank, crossings, water)
    for arrival, field_cost in list(field.costs.items())[::7]:
        if arrival == departure:
            continue
        course = field.course(departure, arrival)
        if not course:
            lost_ones += 1
            continue
        destinations += 1
        rings, _stretches = v.atom_count(course, banks, water, crossings, orient,
                                        cost_of, None, None)
        total_ = sum(cost_of(c) or 0 for c in course[1:])
        total_ += sum(passage(a, b) or 0 for a, b in zip(course, course[1:])) \
            if passage else 0
        total_ += sum(x for x in rings.values() if x)
        if abs(total_ - field_cost) > 1e-6:
            rejects.append((departure, arrival, total_, field_cost))
results.append((f"on {destinations} destinations from the real map, the proposed road costs "
              f"as much as the field ({len(rejects)} rejects)", not rejects and destinations > 50))
if rejects:
    print("   rejects:", rejects[:4])

width = max(len(n) for n, _ in results)
print()
for name, ok in results:
    print(("  ok  " if ok else " NO   ") + name.ljust(width))
print(f"\n{sum(1 for _, ok in results if ok)}/{len(results)} passed")
