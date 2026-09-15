"""The hex as twenty-four fixed pieces, and the water that closes their passages.

The sections module (`sections.py`) cuts the hex up **starting from** what the
water draws inside it: no water, one piece; one line, two pieces. It works, and
it is exact, but it carries two limits that show in play.

A river that enters a hex and stops divides nothing, so it **does not count**:
it changes no road and no cost, even though on the map one has to walk around
it. And a piece of hex half a hex big is too coarse to say «I am there».

Here the point of view flips: the hex is **already** divided, always, into the
same pieces — the **atoms** — and a line of water does not create them, it
**closes passages** between pieces that were already there.

**Twenty-four, and it is a closed number.** The lines one can draw are always
the same: from a vertex to another, or from a vertex to the center. Drawing
them all cuts the hex into 24 pieces, and the count does not grow: the nine
diagonals alone make 24, and adding the six radii to the center or the six
sides adds not a single one, because the radii are already halves of the long
diagonals. From this follows the property everything rests on:

> the 36 borders between atoms **all** lie on a drawable line, and every
> drawable line is **exactly** a set of those borders.

Not approximately: literally, both ways round.

**How one moves.** In two ways, and they cost the same:

* by **side**, to an atom next door, if the border between the two is open;
* by **point**, to an atom touching the same point — cutting the corner
  through the junction — but only **if no water reaches that point**.

The second rule is the only delicate one, and it must be read this way and no
other. Saying «the sides of the two atoms being open is enough» looks like the
same thing, and on a junction where two lines meet it really is: the sides are
four, and all four belong to one of the two. But at the **center** of the hex
six atoms and six sides meet, and there «the sides of the two» are four out of
six: the two left out are precisely the ones the river runs on. With that
reading a chord drawn from side to side **does not divide the hex** —
measured: all fifteen crossings stay possible. Looking at the point, it
forbids nine.

**What it costs.** One pays on entering an atom, a quarter of that hex's cost.
The quarter is not a choice: the crossing of a clean hex passes through
**exactly four atoms, in all fifteen directions**, so four quarters make the
full cost of the rules, always, with nothing to calibrate. And where the water
forces a detour, the detour pays for itself: a river entering from a vertex and
stopping at the center does not divide the hex, but lengthens the longest
crossing from four atoms to eight.
"""
from __future__ import annotations

import itertools
import math
from collections import deque
from functools import lru_cache

from kingmaker.geometry import sections

# The nine diagonals: all chords between non-adjacent vertices. They alone
# suffice — adding radii and sides does not change the cut — but the reason
# they suffice is measured, not obvious, and lives in the module docstring.
DIAGONALS = tuple((a, b) for a, b in itertools.combinations(range(6), 2)
                  if (b - a) % 6 not in (1, 5))

HOW_MANY = 24            # atoms per hex, always
SIDE_COUNT = 36       # borders between atoms, always


def _key(p) -> tuple:
    return (round(p[0], 6), round(p[1], 6))


@lru_cache(maxsize=4)
def atoms(orient: str = "pointy") -> tuple:
    """The 24 pieces of the hex, always the same, numbered once and for all.

    They are `sections.Face` like the others — outline, hex sides touched,
    area, inner point — only here they do not depend on what was drawn: they
    are simply there. It is the property that makes the redraw problem vanish
    by construction: an atom number is never renumbered.

    The first six are those touching the edge, one per side, in side order:
    atom `d` is the one entered when arriving from neighbour `d`.
    """
    return sections.faces_of(DIAGONALS, orient)


@lru_cache(maxsize=4)
def sides(orient: str = "pointy") -> tuple:
    """The 36 borders between atoms: `((atom, atom), (point, point))`, numbered.

    A border's index is its name, and never changes. The water state of a hex
    then becomes a set of numbers between 0 and 35 — a 36-bit mask, which is
    also the most compact way to write it to disk or to put it in a water
    chart.
    """
    pieces = atoms(orient)
    whose: dict = {}
    for index, face in enumerate(pieces):
        ring = face.ring
        for k in range(len(ring)):
            a, b = ring[k], ring[(k + 1) % len(ring)]
            entry = whose.setdefault(frozenset((_key(a), _key(b))),
                                     [(a, b), set()])
            entry[1].add(index)
    outside = [(tuple(sorted(who)), stretch)
             for stretch, who in whose.values() if len(who) == 2]
    # Sorted by the pair of atoms: a border's number must be the same at
    # every start, or a mask saved yesterday would say something else.
    return tuple(sorted(outside, key=lambda entry: entry[0]))


@lru_cache(maxsize=4)
def _junctions(orient: str) -> tuple:
    """The inner junctions: for each, the atoms around it and the incident borders.

    The **hex corners are not junctions**: there atoms of different cells
    touch, and going from one to the other means leaving the hex, which is a
    step of another kind. Only the points where two water lines *could* meet
    count.
    """
    pieces = atoms(orient)
    corners = {_key(p) for p in sections.unit_corners(orient)}
    around: dict = {}
    for index, face in enumerate(pieces):
        for p in face.ring:
            around.setdefault(_key(p), set()).add(index)
    incident: dict = {}
    for number, (_who, (a, b)) in enumerate(sides(orient)):
        for p in (_key(a), _key(b)):
            incident.setdefault(p, []).append(number)
    outside = []
    for point, who in around.items():
        if point in corners or len(who) < 3:
            continue
        outside.append((point, tuple(sorted(who)),
                      tuple(sorted(incident.get(point, ())))))
    return tuple(sorted(outside))


@lru_cache(maxsize=4)
def inner_junctions(orient: str = "pointy") -> tuple:
    """The 13 inner points where the drawable lines meet, numbered.

    With the six corners they make the 19 points of the hex: they are the
    **junctions** a boat stops on. They are a point even where no line is
    drawn — the junction exists, it is the line that is missing — and this is
    what makes a lake the same thing as a river: a lake is a hex with all the
    lines.
    """
    return tuple(point for point, _who, _inc in _junctions(orient))


def _on(p, a, b, surface: float = 1e-6) -> bool:
    dx, dy = b[0] - a[0], b[1] - a[1]
    along = dx * dx + dy * dy
    if along <= 1e-12:
        return False
    t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / along
    if t < -surface or t > 1 + surface:
        return False
    return abs((p[0] - a[0]) * dy - (p[1] - a[1]) * dx) < surface * math.sqrt(along)


@lru_cache(maxsize=64)
def chord_pieces(ka, kb, orient: str = "pointy") -> tuple:
    """The atom sides lying on the line from end `ka` to end `kb`, in that order.

    An end is a vertex (0..5) or the center (None): the same two things the
    water brush snaps to. A chord between two non-adjacent vertices is
    **always four** atom sides, a radius from vertex to center two —
    measured, for all fifteen lines. It is the reason for the quarter: a boat
    pays a quarter per side, and a whole chord makes one activity.

    Every piece is `(p, q)` in hex radii from the center, oriented from `ka`
    towards `kb`. Empty if the two ends are neighbours in the ring: that is a
    side of the hex, which is not an atom side.
    """
    corners = sections.unit_corners(orient)
    a = (0.0, 0.0) if ka is None else corners[ka]
    b = (0.0, 0.0) if kb is None else corners[kb]
    if a == b:
        return ()

    def along(p):
        return (p[0] - a[0]) * (b[0] - a[0]) + (p[1] - a[1]) * (b[1] - a[1])

    outside = []
    for _who, (p, q) in sides(orient):
        if _on(p, a, b) and _on(q, a, b):
            if along(p) > along(q):
                p, q = q, p
            outside.append((p, q))
    outside.sort(key=lambda pq: along(pq[0]))
    return tuple(outside)


def canonical(cuts) -> tuple:
    """The stretches reduced to their minimal form, as `sections` reduces them."""
    return sections.canonical(cuts)


def closed_by_stretches(cuts, orient: str = "pointy") -> frozenset:
    """Which borders between atoms that water drawing closes.

    Every stretch is a pair of ends, where an end is the number of a ring
    vertex or `None` for the center — the same two things the brush knows how
    to snap to. A stretch lying on a hex side closes nothing: there the water
    is a Water Border, and lives in the other table.
    """
    return _closed(canonical(cuts), orient)


@lru_cache(maxsize=1024)
def _closed(cuts: tuple, orient: str) -> frozenset:
    corners = sections.unit_corners(orient)
    outside = set()
    for one, two in cuts:
        a = (0.0, 0.0) if one is None else corners[one % 6]
        b = (0.0, 0.0) if two is None else corners[two % 6]
        for number, (_who, (p, q)) in enumerate(sides(orient)):
            vehicle = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
            if all(sections._on_segment(x, a, b) for x in (p, q, vehicle)):
                outside.add(number)
    return frozenset(outside)


def side_of_point(point, between=None, orient: str = "pointy"):
    """Which border between atoms passes through that point, or None if none does.

    It is the question one asks a bridge: a bridge sits **on a stretch**, and
    the stretch is one of the 36 borders. Knowing which is the only way to
    make it open that one and not half a hex.

    `among` restricts the choice to a set of borders — normally those the
    water closes — because a bridge sits on water and not on dry land.

    A point in the middle of a stretch answers one and one only. A point on a
    **junction** sits at the ends of several stretches, and there the question
    has no single answer: whoever has it inside, not at the ends, is
    preferred, and on a tie the first. It happens for bridges written the old
    way, when their spot came from the midpoint of the border between two
    shores and that midpoint could fall right on the center of the hex.
    """
    if point is None:
        return None
    candidates = (range(len(sides(orient))) if between is None
                 else sorted(int(x) for x in between))
    at_ends = None
    for number in candidates:
        _who, (a, b) = sides(orient)[number]
        if not sections._on_segment(point, a, b):
            continue
        if (sections._key(point) not in (sections._key(a),
                                           sections._key(b))):
            return number
        if at_ends is None:
            at_ends = number
    return at_ends


def graph(closed=frozenset(), openings=(), orient: str = "pointy") -> dict:
    """From every atom, those reachable in one step.

    Two ways, and they cost the same: by shared side if that side is open, and
    by shared point if no water reaches that point. The second is no free
    shortcut, it is the reason a clean hex always costs four atoms in every
    direction instead of four, seven or eight depending on the direction —
    measured, and it is the difference between honouring the rule of the
    wiki and breaking it.
    """
    return _graph(frozenset(closed), frozenset(openings), orient)


@lru_cache(maxsize=1024)
def _graph(closed: frozenset, openings: frozenset, orient: str) -> dict:
    outside: dict = {i: set() for i in range(len(atoms(orient)))}
    for number, (who, _stretch) in enumerate(sides(orient)):
        if number in closed and number not in openings:
            continue
        one, two = who
        outside[one].add(two)
        outside[two].add(one)
    for _point, who, incident in _junctions(orient):
        # A bridge opens **its stretch**, not the point where the stretch
        # ends: the river still runs there. So the jumps by point look at the
        # real water — `closed` — and do not notice bridges. Going around a
        # junction reached by water would mean walking dry over a film of
        # water, and the bridge does not put it there.
        if any(number in closed for number in incident):
            continue
        for one, two in itertools.combinations(who, 2):
            outside[one].add(two)
            outside[two].add(one)
    return {i: frozenset(v) for i, v in outside.items()}


def provinces(closed=frozenset(), orient: str = "pointy") -> tuple:
    """The pieces of hex the water really separates: the old «shores».

    They are the connected components of the atoms **by shared side only**,
    not by point: two atoms touching at a single point are not the same
    region, because a point has no area. The jumps by point change nothing in
    the count — if no water reaches a point, all the sides around it are open
    and those atoms talk to each other even going around one side at a time —
    so travelling and being in the same province stay the same thing.

    They coincide with the faces of `sections.faces_of`, and that is the proof
    that the two models describe the same hex.
    """
    return _provinces(frozenset(closed), orient)


@lru_cache(maxsize=1024)
def _provinces(closed: frozenset, orient: str) -> tuple:
    sides_only: dict = {i: set() for i in range(len(atoms(orient)))}
    for number, (who, _stretch) in enumerate(sides(orient)):
        if number in closed:
            continue
        one, two = who
        sides_only[one].add(two)
        sides_only[two].add(one)
    seen: set = set()
    outside = []
    for departure in sorted(sides_only):
        if departure in seen:
            continue
        group, queue = {departure}, deque([departure])
        seen.add(departure)
        while queue:
            here = queue.popleft()
            for other in sides_only[here]:
                if other not in seen:
                    seen.add(other)
                    group.add(other)
                    queue.append(other)
        outside.append(frozenset(group))
    # In the same order `sections` numbers its faces: by the lowest hex side
    # the province touches, islands at the end.
    pieces = atoms(orient)

    def order(group):
        its_ones = sorted(d for i in group for d in pieces[i].sides)
        area = sum(pieces[i].area for i in group)
        return (its_ones[0] if its_ones else 6, -area)

    return tuple(sorted(outside, key=order))


def atom_of_point(point, orient: str = "pointy") -> int:
    """Which atom that point falls in, in hex radii from the center."""
    found = sections.face_of_point(atoms(orient), point)
    return 0 if found is None else found


@lru_cache(maxsize=4)
def edge_atoms(orient: str = "pointy") -> dict:
    """For every side of the hex, the atom entered when arriving from there.

    They are six, one per side: of the other eighteen none touches the edge.
    So whoever enters a hex always enters a single atom, and there is nothing
    to choose.
    """
    return {face.sides[0]: index
            for index, face in enumerate(atoms(orient)) if face.sides}


def costs_inside(closed=frozenset(), openings=(), quarter: float = 0.25,
                 orient: str = "pointy") -> dict:
    """What moving inside a hex costs: from every atom to every other.

    Two kinds of step with two different prices, so counting steps is not
    enough. Moving to a neighbouring atom costs a **quarter** of the hex cost,
    and it is the rule everything else comes from: a clean crossing passes
    through four atoms, and four quarters make the full cost of the rules.
    Crossing a **bridge** or a **ford** costs what it costs — zero for a
    bridge, that terrain's cost for a ford — and not a quarter, because it is
    not a piece of walk, it is a way to hop over the water.

    `openings` is a sequence `(border, extra cost)`: the water stretches a
    crossing reopens. A **bridge** reopens its stretch and nothing else —
    about four kilometres on a twenty-one-kilometre hex — and costs nothing
    beyond the quarter walking costs. A **ford** reopens all the stretches of
    the line it is attached to, because a shallow river is waded wherever, and
    every passage costs that terrain's cost.

    This computation lives here and not in the travel graph for a precise
    reason: after a bridge you are not on a side of the hex but in the middle,
    and from there you still have to reach an exit.

    Returns `{(from, to): cost}` for every reachable pair.
    """
    return _costs_inside(frozenset(closed),
                         tuple(sorted((int(side), float(cost))
                                      for side, cost in openings)),
                         float(quarter), orient)


@lru_cache(maxsize=512)
def _costs_inside(closed: frozenset, openings: tuple, quarter: float,
                  orient: str) -> dict:
    import heapq
    neighbours = graph(closed, frozenset(side for side, _c in openings), orient)
    # How much more it costs to pass on a given border, if it is a ford.
    toll: dict = {}
    for side, cost in openings:
        who = sides(orient)[side][0]
        toll[(who[0], who[1])] = float(cost)
        toll[(who[1], who[0])] = float(cost)
    outside: dict = {}
    for departure in range(len(atoms(orient))):
        best_ones = {departure: 0.0}
        queue = [(0.0, departure)]
        while queue:
            cost, here = heapq.heappop(queue)
            if cost > best_ones.get(here, cost):
                continue
            for other in neighbours[here]:
                after = cost + quarter + toll.get((here, other), 0.0)
                if after < best_ones.get(other, after + 1):
                    best_ones[other] = after
                    heapq.heappush(queue, (after, other))
        for arrival, cost in best_ones.items():
            outside[(departure, arrival)] = cost
    return outside


def dist(from_: int, a: int, closed=frozenset(), orient: str = "pointy"):
    """How many atoms are crossed to go from one to the other, ends included.

    `None` if there is no way through. Serves the cost: one pays on entering
    an atom, so the count of atoms **is** the count of hex quarters.
    """
    if from_ == a:
        return 1
    neighbours = graph(closed, orient)
    seen, queue = {from_: 1}, deque([from_])
    while queue:
        here = queue.popleft()
        for other in neighbours[here]:
            if other in seen:
                continue
            seen[other] = seen[here] + 1
            if other == a:
                return seen[other]
            queue.append(other)
    return None


# ------------------------------------------------------- the mask and the browser
def mask(closed) -> int:
    """The closed borders as a single number: one bit per border, 36 bits.

    It is the format in which a hex's water **travels**: the browser is not
    sent the graph — 24 cells with their neighbours — but this number, and it
    rebuilds the graph itself from the atom geometry, which is the same for
    every hex and reaches it once. It fits exactly in a double, so it goes
    through JSON without losing a bit.
    """
    return sum(1 << int(number) for number in closed)


def from_mask(number: int) -> frozenset:
    return frozenset(k for k in range(SIDE_COUNT) if (int(number) >> k) & 1)


def for_browser(orient: str = "pointy") -> dict:
    """The atom geometry, once and for all, in the browser's format.

    Points, borders, junctions with their incident borders, edge atoms. From
    the same code that draws the figures of the document and does the server's
    arithmetic: it is the only way for the graph the browser rebuilds from a
    mask to be the same one the server uses for pricing — `atoms.graph` and
    its JavaScript copy read the same table.
    """
    return {
        "points": [[round(f.point[0], 6), round(f.point[1], 6)]
                  for f in atoms(orient)],
        "sides": [list(who) for who, _stretch in sides(orient)],
        "crossings_": [[list(who), list(incident)]
                    for _point, who, incident in _junctions(orient)],
        "edge": [edge_atoms(orient)[d] for d in range(6)],
    }


def course_by_waypoints(closed, openings, from_atom: int, waypoints, to_atom,
                    quarter: float = 0.25, orient: str = "pointy",
                    constrained: bool = False):
    """The shortest course inside a hex that touches **those waypoints, in that
    order**: `(cost, atoms)`, or `None` if there is none.

    It is the arithmetic of a hand-drawn road. Every waypoint is a set of
    atoms — a shore — and the road must enter them one after the other before
    reaching `to_atom` (an edge atom, to exit; the atom of the point where one
    stops; or `None`, i.e. «wherever, as long as the waypoints are done»).
    Without waypoints it is just the shortest way, the one of the
    `costs_inside` table: so a road not drawn costs what it used to.

    Layered Dijkstra: the state is (atom, waypoints done). Entering an atom of
    the waypoint due advances by one. A step costs a quarter, plus the toll if
    the border is a ford. It is the same arithmetic, line by line, as
    `courseByWaypoints` in the browser: the two must say the same number, and
    bench `bench10` verifies it on the 1561 configurations.

    With `constrained` the waypoints are **the whole** row of shores touched,
    the first included (the one `from_atom` is in), and between a waypoint and
    the next no third one is entered. It serves the hand-drawn road: the hand
    going from A to B through the bridge between the two must not see A → C → B
    drawn because that way cost a quarter less. The road is its own; the
    arithmetic only asks it to be the shortest **among those making that
    tour**.
    """
    import heapq
    openings = tuple(sorted((int(side), float(cost)) for side, cost in openings))
    neighbours = graph(frozenset(closed), frozenset(side for side, _c in openings),
                   orient)
    toll: dict = {}
    for side, cost in openings:
        who = sides(orient)[side][0]
        toll[(who[0], who[1])] = float(cost)
        toll[(who[1], who[0])] = float(cost)
    waypoints = [frozenset(int(x) for x in t) for t in (waypoints or ())]
    n_items = len(waypoints)

    def layer_after(atom, layer):
        return layer + 1 if layer < n_items and atom in waypoints[layer] else layer

    def is_allowed(other, layer):
        """With constrained waypoints: only the shore one is in, or the next."""
        if not constrained or not n_items:
            return True
        if layer and other in waypoints[layer - 1]:
            return True
        return layer < n_items and other in waypoints[layer]

    departure = (int(from_atom), layer_after(int(from_atom), 0))
    best_ones = {departure: 0.0}
    before: dict = {departure: None}
    queue = [(0.0, departure)]
    # At equal cost there are several courses, and the drawing shows one:
    # which, is decided by the order of extraction from the queue and the order
    # in which neighbours are looked at. Both are fixed — by cost, then by atom
    # number and layer; neighbours in ascending order — and the browser does
    # exactly the same, or the arrow would change shape on release.
    while queue:
        cost, state = heapq.heappop(queue)
        if cost > best_ones.get(state, cost):
            continue
        atom, layer = state
        if layer == n_items and (to_atom is None or atom == int(to_atom)):
            outside = [atom]
            while before[state] is not None:
                state = before[state]
                outside.append(state[0])
            outside.reverse()
            return cost, outside
        for other in sorted(neighbours[atom]):
            if not is_allowed(other, layer):
                continue
            after = (other, layer_after(other, layer))
            new = cost + quarter + toll.get((atom, other), 0.0)
            if new < best_ones.get(after, new + 1):
                best_ones[after] = new
                before[after] = state
                heapq.heappush(queue, (new, after))
    return None
