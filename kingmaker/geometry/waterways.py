"""The network of watercourses: the drawn stretches, and which way they flow.

Borders and banks say *where* the water is. So far they served one purpose:
barring the way to whoever walks. But the same lines, for a boat, are the exact
opposite of a wall — they are the road. This module takes them and makes a
graph:

* the **nodes** are the grid vertices, plus the center of a hex where three or
  more stretches meet;
* the **arcs** are the drawn stretches: the side between two hexes when water
  runs on it, and the cut crossing a hex from one vertex to another.

A vertex does not belong to one hex: it belongs to **three**, and it is the
same point. For the graph to really close — for the river leaving a hex to be
the same one entering the next — that point must have a single name, and not
three depending on who looks at it. Hence `vertex_key`: among the three ways
of calling it the smallest is kept, and whoever looks for it finds it.

**The direction.** The rules say going downriver is open terrain and going
upriver is difficult or greater difficult, depending on currents and weather.
To apply them one must know which way the water flows, and on the map it is
written nowhere: it is an extra datum someone has to put in. Here a direction
is simply **the order of the two ends of a stretch**: upstream first,
downstream second. Whoever passes compares the way they are going with the
one written — if they match they go down, if opposite they go up. A stretch
without a direction is not an error: it is a piece of river nobody has said
which way it goes yet, and travel says so instead of making it up.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

from kingmaker.geometry import atoms, hexgrid, sections

# Glossary:
#   line (drawn): a segment of water as the hand drew it — vertex↔vertex or
#     vertex↔center inside a hex (`banks.points`), or a side between two hexes
#     (`borders`).
#   piece: an atom side on a line (¼ activity for a boat); edge: a hex side
#     (½). They are the `Arc`s of the `Network`.
#   junction/node: where two pieces touch — "v" corner, "c" center, "x" inner
#     point; the boat sits and stops on these.
#   current: the direction (upstream→downstream) of a drawn line, not of a piece.

# A node is a tuple: ("v", col, row, k) for a grid vertex, ("c", col, row) for
# the center of a hex. The center is needed only where three or more stretches
# meet inside the same cell: there the meeting point is not a vertex, and
# without a node of its own the confluence would be three stretches that do
# not touch.
VERTEX = "v"
CENTER = "c"
JUNCTION = "x"          # an inner point of the hex where two lines meet

# The cut of a hex goes from one vertex to another; the chord between two
# vertices `d` places apart in the ring measures 2·size·sin(30°·d). With d=1 it
# is the side.
def _chord(d: int, size: float) -> float:
    return 2.0 * size * math.sin(math.radians(30.0 * d))


# ------------------------------------------------------------------- vertices
_OWNERS: dict = {}


def _owners_table(orient: str, tie: tuple) -> tuple:
    """Who else owns vertex `k`, as an offset and their own index.

    Derived once per orientation and cell parity, by measuring on a reference
    hex: the shape of the grid does not change from one cell to the next, only
    the staggering of the rows (or columns) does, and that depends on parity.
    Measured and not hand-written, so it stays exact even if one day the
    geometry changes.
    """
    key = (orient, tie)
    if key in _OWNERS:
        return _OWNERS[key]
    size, origin = 100.0, (0.0, 0.0)
    base = (10 + tie[0], 10 + tie[1])
    my_items = hexgrid.vertices_of(base, size, origin, orient)
    neighbours = hexgrid.neighbours(base[0], base[1], orient)
    tolerance = (size * 1e-6) ** 2
    table = []
    for k, point in enumerate(my_items):
        others = []
        for near in neighbours:
            for kk, q in enumerate(hexgrid.vertices_of(near, size, origin, orient)):
                if ((point[0] - q[0]) ** 2 + (point[1] - q[1]) ** 2) < tolerance:
                    others.append((near[0] - base[0], near[1] - base[1], kk))
                    break
        table.append(tuple(others))
    _OWNERS[key] = tuple(table)
    return _OWNERS[key]


def vertex_owners(coord, k: int, orient: str) -> list:
    """All the ways of calling that point: `(hex, index)`, this one included."""
    col, row = int(coord[0]), int(coord[1])
    table = _owners_table(orient, (col & 1, row & 1))
    outside = [((col, row), k % 6)]
    for dcol, drow, kk in table[k % 6]:
        outside.append(((col + dcol, row + drow), kk))
    return outside


def vertex_key(coord, k: int, orient: str) -> tuple:
    """The unique name of that point: the smallest of the three that share it."""
    (col, row), kk = min(vertex_owners(coord, k, orient))
    return (VERTEX, col, row, kk)


def center_key(coord) -> tuple:
    return (CENTER, int(coord[0]), int(coord[1]))


def junction_key(coord, index: int) -> tuple:
    """An inner junction: it belongs to a single hex, so there is nothing to choose."""
    return (JUNCTION, int(coord[0]), int(coord[1]), int(index))


def node_point(node, size: float, origin, orient: str):
    """Where it falls on the drawing, in pixels."""
    if node[0] == CENTER:
        return hexgrid.hex_center(node[1], node[2], size, origin, orient)
    if node[0] == JUNCTION:
        cx, cy = hexgrid.hex_center(node[1], node[2], size, origin, orient)
        ux, uy = atoms.inner_junctions(orient)[node[3]]
        return cx + ux * size, cy + uy * size
    return hexgrid.vertices_of((node[1], node[2]), size, origin, orient)[node[3]]


def node_hexes(node, orient: str) -> list:
    """The hexes that point belongs to: three for a corner, one for the others."""
    if node[0] == VERTEX:
        return [c for c, _k in vertex_owners((node[1], node[2]), node[3], orient)]
    return [(node[1], node[2])]


def node_of_unit_point(coord, point, orient: str, surface: float = 1e-4):
    """The node sitting at that point of the hex (radii from the center), or None.

    A corner becomes its canonical name — the same from whichever of the three
    hexes one looks at it — the center its own, an inner junction its number.
    """
    coord = (int(coord[0]), int(coord[1]))
    if abs(point[0]) < surface and abs(point[1]) < surface:
        return center_key(coord)
    for k, corner in enumerate(sections.unit_corners(orient)):
        if abs(point[0] - corner[0]) < surface and abs(point[1] - corner[1]) < surface:
            return vertex_key(coord, k, orient)
    for index, p in enumerate(atoms.inner_junctions(orient)):
        if abs(point[0] - p[0]) < surface and abs(point[1] - p[1]) < surface:
            return junction_key(coord, index)
    return None


def unit_point_of_node(node, coord, orient: str):
    """Where that node is in the frame of `coord`, in radii from the center. None if not its own."""
    coord = (int(coord[0]), int(coord[1]))
    if node[0] == CENTER:
        return (0.0, 0.0) if (node[1], node[2]) == coord else None
    if node[0] == JUNCTION:
        if (node[1], node[2]) != coord:
            return None
        return tuple(atoms.inner_junctions(orient)[node[3]])
    for c, k in vertex_owners((node[1], node[2]), node[3], orient):
        if tuple(c) == coord:
            return tuple(sections.unit_corners(orient)[k])
    return None


def node_end(node, coord, orient: str):
    """The line end that node is for `coord`: a vertex 0..5, None the center.

    Returns `(found, end)`: an inner junction is not a line end.
    """
    if node[0] == CENTER:
        return ((node[1], node[2]) == tuple(coord)), None
    if node[0] == JUNCTION:
        return False, None
    for c, k in vertex_owners((node[1], node[2]), node[3], orient):
        if tuple(c) == tuple(coord):
            return True, k
    return False, None


def side_vertices(direction: int) -> tuple:
    """The two vertices at the ends of the side in that direction."""
    k2 = hexgrid.SIDE_RING.index(direction % 6)
    return (k2 - 1) % 6, k2


def banks_from_cuts(cut_ones) -> list:
    """The shores of a hex, from the vertices where a line touches the edge.

    It is the general rule, and holds for every shape: the shores are the
    **edge arcs** between two consecutive cut points. A single cut point
    divides nothing — a river entering and stopping in the middle leaves the
    hex whole — two divide it in two, three in three.

    From here also follows that passing through the center does not change
    the shores: the center does not touch the edge, so it does not cut. The
    drawing changes, and that is all.
    """
    points = sorted({int(k) % 6 for k in cut_ones})
    if len(points) < 2:
        return []
    outside = []
    for index, start_ in enumerate(points):
        end = points[(index + 1) % len(points)]
        arc = [hexgrid.SIDE_RING[(start_ + 1 + step) % 6]
                for step in range((end - start_) % 6)]
        if arc:
            outside.append(sorted(arc))
    return sorted(outside, key=lambda g: g[0])


def vertex_cuts(groups) -> list:
    """The cuts of a hex as pairs of vertices, or as radii to the center.

    Every entry is `(k1, k2)` for a stretch from vertex to vertex, or
    `(k, None)` for a radius going from the vertex to the center: that is the
    confluence case, where the stretches are more than two and meet in the
    middle.
    """
    if len(groups or []) < 2:
        return []
    whose = {}
    for index, group in enumerate(groups):
        for direction in group:
            whose[direction] = index
    junctions = []
    for position, direction in enumerate(hexgrid.SIDE_RING):
        after = hexgrid.SIDE_RING[(position + 1) % 6]
        if direction not in whose or after not in whose:
            continue
        if whose[direction] != whose[after]:
            junctions.append(position)
    if len(junctions) == 2:
        return [(junctions[0], junctions[1])]
    if len(junctions) > 2:
        return [(k, None) for k in junctions]
    return []


# --------------------------------------------------------------------- network
@dataclass(frozen=True)
class Arc:
    """A piece of water a boat takes one step on: an atom side, or a hex side.

    `kind` is `piece` (an atom side, a quarter of the way) or `edge` (a whole
    hex side, half the way). `parent` is the **drawn** line this piece belongs
    to — its two ends, in order — and it is on that one that the current's
    direction is written; `straight_on` says whether going from `a` to `b` is
    going in the direction `parent[0] -> parent[1]`. A lake piece has no
    parent: it is still water.
    """

    a: tuple
    b: tuple
    kind: str                     # piece | edge
    hexes: tuple                # the hexes that piece touches
    length: float              # in units of `size`, i.e. hex radii
    parent_: tuple | None = None    # the two ends of the drawn line, ordered
    straight_on: bool = True          # a -> b goes as parent[0] -> parent[1]
    lake: bool = False            # still water: no direction

    @property
    def key(self) -> tuple:
        return (self.a, self.b) if self.a <= self.b else (self.b, self.a)

    def ends_direction(self, from_, a) -> tuple | None:
        """The ends of the drawn line in the direction one goes from `from_` to `a`."""
        if self.parent_ is None:
            return None
        forward = (from_, a) == (self.a, self.b)
        if not forward and (from_, a) != (self.b, self.a):
            return None
        straight = self.straight_on if forward else not self.straight_on
        return self.parent_ if straight else (self.parent_[1], self.parent_[0])


@dataclass
class Network:
    """All the pieces of water of a map, and who touches whom."""

    arcs: dict = field(default_factory=dict)          # key -> Arc
    neighbours: dict = field(default_factory=dict)         # node -> [(node, Arc)]
    parents: set = field(default_factory=set)            # the drawn lines

    def add(self, arc: Arc) -> None:
        if arc.a == arc.b or arc.key in self.arcs:
            return
        self.arcs[arc.key] = arc
        self.neighbours.setdefault(arc.a, []).append((arc.b, arc))
        self.neighbours.setdefault(arc.b, []).append((arc.a, arc))
        if arc.parent_ is not None:
            self.parents.add(arc.parent_)

    @property
    def empty_one(self) -> bool:
        return not self.arcs

    def arc_between(self, a, b) -> Arc | None:
        return self.arcs.get((a, b) if a <= b else (b, a))

    def has_stretch(self, a, b) -> bool:
        """Does the drawn line with these two ends exist?"""
        return ((a, b) if a <= b else (b, a)) in self.parents


def build(borders: dict, banks: dict, orient: str = "pointy",
               segments: dict | None = None, lakes=None,
               columns: int = 0, rows: int = 0, size: float = 1.0,
               origin=(0.0, 0.0)) -> Network:
    """The network from what is drawn on the map.

    Every line drawn inside a hex splits into the **atom sides** composing it
    — four for a chord, two for a radius — and every piece is a boat step:
    from one junction to the next, a quarter of the way. A hex side stays a
    single piece, half the way. A lake is a hex with **all** the lines: its 36
    atom sides and its six sides are water, without current.

    All three kinds of border count, not only `water`: a ford and a bridge are
    *ways of passing* a watercourse, so the water is very much there. Marking
    a ford and watching the river vanish from the route would be odd to
    explain.
    """
    network = Network()
    for (ca, ra, cb, rb), _entry in (borders or {}).items():
        a, b = (ca, ra), (cb, rb)
        neighbours = hexgrid.neighbours(ca, ra, orient)
        try:
            direction = neighbours.index(b)
        except ValueError:
            continue              # no longer neighbours: the grid changed
        k1, k2 = side_vertices(direction)
        ends = tuple(sorted((vertex_key(a, k1, orient),
                             vertex_key(a, k2, orient))))
        network.add(Arc(ends[0], ends[1], kind="edge", hexes=(a, b),
                           length=_chord(1, 1.0), parent_=ends))
    # The **union** of the two dictionaries, not the banks alone. A hex the
    # river enters and stops in has no shores — it does not divide it — so it
    # does not appear among the banks; but its stretch is water all the same.
    for coord in sorted(set(banks or {}) | set(segments or {})):
        coord = (int(coord[0]), int(coord[1]))
        groups = (banks or {}).get(coord)
        drawn_ones = (segments or {}).get(coord)
        if drawn_ones:
            for one, two in drawn_ones:
                a, b = node_from_text(one), node_from_text(two)
                if a is None or b is None or a == b:
                    continue
                found_a, ka = node_end(a, coord, orient)
                found_b, kb = node_end(b, coord, orient)
                if not (found_a and found_b):
                    continue
                _add_row(network, coord, ka, kb, orient)
            continue
        for k1, k2 in vertex_cuts(groups):
            _add_row(network, coord, k1, k2, orient)

    # And the lakes: every cell is a hex with all the lines — but only the
    # points **inside the drawn shape** are water. A cell belongs to the lake
    # when its center does, and a cell on the shore has vertices outside the
    # ring: without this check the boat sailed to them, and the arrow left
    # the water. Where a river already runs the river stays, with its
    # direction. A lake with no ring (filled by flooding, from before the
    # shapes) keeps its whole cells.
    for lake in (lakes or ()):
        in_lake = _lake_membership(lake, size, origin, orient)
        for cell in (lake.get("cells") or ()):
            coord = (int(cell[0]), int(cell[1]))
            if columns and rows and not (0 <= coord[0] < columns
                                          and 0 <= coord[1] < rows):
                continue
            for _who, (p, q) in atoms.sides(orient):
                na = node_of_unit_point(coord, p, orient)
                nb = node_of_unit_point(coord, q, orient)
                if na is None or nb is None or network.arc_between(na, nb) is not None:
                    continue
                if not (in_lake(na) and in_lake(nb)):
                    continue
                na, nb = sorted((na, nb))
                network.add(Arc(na, nb, kind="piece", hexes=(coord,),
                                   length=_unit_length(p, q), lake=True))
            neighbours = hexgrid.neighbours(coord[0], coord[1], orient)
            for direction in range(6):
                k1, k2 = side_vertices(direction)
                na, nb = sorted((vertex_key(coord, k1, orient),
                                 vertex_key(coord, k2, orient)))
                if network.arc_between(na, nb) is not None:
                    continue
                if not (in_lake(na) and in_lake(nb)):
                    continue
                beside = tuple(neighbours[direction])
                network.add(Arc(na, nb, kind="edge", hexes=(coord, beside),
                                   length=_chord(1, 1.0), lake=True))
    return network


def lake_frame(lake: dict, size: float, origin, orient: str) -> list:
    """The drawn ring of a lake in pixels, or [] if it has none (or is bent)."""
    frame = []
    for text in lake.get("points") or ():
        node = node_from_text(text)
        if node is None:
            return []
        try:
            frame.append(node_point(node, size, origin, orient))
        except (IndexError, TypeError):
            return []
    return frame if len(frame) >= 3 else []


def _lake_membership(lake: dict, size: float, origin, orient: str):
    """«Is this junction in the lake?» — inside the ring or on it. Without a
    ring every point of the lake's cells is."""
    frame = lake_frame(lake, size, origin, orient)
    if not frame:
        return lambda node: True
    tolerance = size * 0.02

    def inside(node) -> bool:
        try:
            x, y = node_point(node, size, origin, orient)
        except (IndexError, TypeError):
            return False
        return _on_outline(x, y, frame, tolerance) or _inside_ring(x, y, frame)
    return inside


def _unit_length(p, q) -> float:
    return math.hypot(q[0] - p[0], q[1] - p[1])


def _add_row(network: Network, coord, ka, kb, orient: str) -> None:
    """A line drawn inside the hex, split into its atom sides.

    Two neighbouring vertices are a side of the hex and have no atom sides
    under them: that line is a border, and lives in the borders table.
    """
    end_a = center_key(coord) if ka is None else vertex_key(coord, ka, orient)
    end_b = center_key(coord) if kb is None else vertex_key(coord, kb, orient)
    if end_a == end_b:
        return
    parent_ = tuple(sorted((end_a, end_b)))
    forwards = parent_ == (end_a, end_b)      # ka -> kb is parent[0] -> parent[1]
    for p, q in atoms.chord_pieces(ka, kb, orient):
        na = node_of_unit_point(coord, p, orient)
        nb = node_of_unit_point(coord, q, orient)
        if na is None or nb is None or na == nb:
            continue
        sorted_ones = na <= nb
        network.add(Arc(na if sorted_ones else nb, nb if sorted_ones else na,
                           kind="piece", hexes=(coord,),
                           length=_unit_length(p, q), parent_=parent_,
                           straight_on=(forwards == sorted_ones)))


# ------------------------------------------------------------------ courses
def course(network: Network, from_, a) -> list | None:
    """The shortest course along the water, as a list of nodes.

    Shortest in **number of stretches**, not in metres: whoever follows a
    river with a finger follows the river, and the stretches are the pieces
    the river was drawn in. A river normally has a single road, and where it
    forks the branches count, not their length.
    """
    if from_ == a:
        return [from_]
    if from_ not in network.neighbours or a not in network.neighbours:
        return None
    from_where = {from_: None}
    queue = deque([from_])
    while queue:
        here = queue.popleft()
        for other, _arc in network.neighbours.get(here, ()):
            if other in from_where:
                continue
            from_where[other] = here
            if other == a:
                road = [a]
                while from_where[road[-1]] is not None:
                    road.append(from_where[road[-1]])
                return list(reversed(road))
            queue.append(other)
    return None


def hex_nodes(network: Network, coord) -> list:
    """The network points touching that hex: where one boards."""
    coord = (int(coord[0]), int(coord[1]))
    outside = set()
    for arc in network.arcs.values():
        if coord in arc.hexes:
            outside.add(arc.a)
            outside.add(arc.b)
    return sorted(outside)


def nearest_node(network: Network, point, size: float, origin, orient: str,
                    threshold: float | None = None):
    """The network node nearest to the point, or None if they are all far."""
    best, dist = None, None
    for node in network.neighbours:
        x, y = node_point(node, size, origin, orient)
        d = (point[0] - x) ** 2 + (point[1] - y) ** 2
        if dist is None or d < dist:
            best, dist = node, d
    if best is None:
        return None
    if threshold is not None and dist > threshold ** 2:
        return None
    return best


# --------------------------------------------------------------------- lakes
def cells_in_polygon(points, columns: int, rows: int, size: float, origin,
                       orient: str) -> list:
    """The hexes whose center falls inside the drawn ring of vertices.

    A hand-drawn lake does not follow the hex edges: it cuts where the water
    cuts. So it is not filled by flooding — one looks at which centers are
    inside the shape. A hex belongs to the lake if its center does: it is the
    simplest rule one can explain aloud, and on a grid of 21 km per hex it is
    also the right one.
    """
    frame = [node_point(n, size, origin, orient) for n in points
              if n is not None]
    if len(frame) < 3:
        return []
    # A center sitting **on** the outline is inside. The outline points are
    # hex vertices and centers, so it happens often: a lake drawn from a
    # center to a vertex to the other center passes over the two centers, and
    # a shape on four consecutive vertices of the same hex has the center
    # exactly on the chord closing it. With the ray count alone those centers
    # fell on one side or the other depending on rounding, and a closed,
    # sensible shape could «contain no hex».
    tolerance = size * 0.02
    minx = min(x for x, _y in frame) - tolerance
    maxx = max(x for x, _y in frame) + tolerance
    miny = min(y for _x, y in frame) - tolerance
    maxy = max(y for _x, y in frame) + tolerance
    outside = []
    for row in range(rows):
        for col in range(columns):
            cx, cy = hexgrid.hex_center(col, row, size, origin, orient)
            if not (minx <= cx <= maxx and miny <= cy <= maxy):
                continue
            if (_on_outline(cx, cy, frame, tolerance)
                    or _inside_ring(cx, cy, frame)):
                outside.append((col, row))
    return outside


def _on_outline(x: float, y: float, frame: list, tolerance: float) -> bool:
    """The point lies on one of the outline sides, within `tolerance`."""
    how_many = len(frame)
    for i in range(how_many):
        (x1, y1), (x2, y2) = frame[i], frame[(i + 1) % how_many]
        dx, dy = x2 - x1, y2 - y1
        along = dx * dx + dy * dy
        if along <= 1e-12:
            continue
        t = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / along))
        if math.hypot(x - (x1 + t * dx), y - (y1 + t * dy)) <= tolerance:
            return True
    return False


def _inside_ring(x: float, y: float, frame: list) -> bool:
    """The ray count: how many times a half-line cuts the outline.

    Odd means inside. It works on a concave shape too, which is exactly the
    case of a lake with an inlet.
    """
    inside = False
    how_many = len(frame)
    for i in range(how_many):
        (x1, y1), (x2, y2) = frame[i], frame[(i + 1) % how_many]
        if (y1 > y) != (y2 > y):
            cut = x1 + (y - y1) * (x2 - x1) / ((y2 - y1) or 1e-9)
            if x < cut:
                inside = not inside
    return inside


def _dist_from_side(x: float, y: float, a, b) -> float:
    """How far a point is from segment a-b."""
    (x1, y1), (x2, y2) = a, b
    dx, dy = x2 - x1, y2 - y1
    along = dx * dx + dy * dy
    if along <= 1e-12:
        return math.hypot(x - x1, y - y1)
    how_much = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / along))
    return math.hypot(x - (x1 + how_much * dx), y - (y1 + how_much * dy))


# -------------------------------------------------------------------- direction
def node_text(node) -> str:
    """The node as written in the database: short and readable at a glance."""
    return ":".join(str(p) for p in node)


def node_from_text(text: str):
    parts = (text or "").split(":")
    if parts[:1] == [CENTER] and len(parts) == 3:
        return (CENTER, int(parts[1]), int(parts[2]))
    if parts[:1] in ([VERTEX], [JUNCTION]) and len(parts) == 4:
        return (parts[0], int(parts[1]), int(parts[2]), int(parts[3]))
    return None


def text_key(a, b) -> str:
    """The name of a stretch, the same from whichever way one looks at it."""
    one, two = sorted((node_text(a), node_text(b)))
    return f"{one}|{two}"


def step_direction(currents: dict, from_, a, arc=None) -> str | None:
    """Going from `from_` to `a`, does one go down or up? None if nobody said.

    `currents` is `{key of the drawn line: (upstream, downstream)}`. The
    direction sits on the **drawn** line, not on the piece: a piece inherits
    it from its parent, in the direction it is walked (`Arc.ends_direction`).
    Without the arc the step itself is compared, which is the case of a hex
    side.
    """
    ends = arc.ends_direction(from_, a) if arc is not None else None
    if ends is None:
        ends = (from_, a)
    entry = (currents or {}).get(text_key(*ends))
    if not entry:
        return None
    upstream, downstream = entry
    if (upstream, downstream) == ends:
        return "downstream"
    if (upstream, downstream) == (ends[1], ends[0]):
        return "upstream"
    return None


def course_stretches(network, road: list) -> list:
    """The drawn lines a course walks, as (upstream, downstream) pairs.

    It is what the direction brush writes: the water is followed from one
    junction to the next, but the direction is marked on the whole line,
    once.
    """
    outside: list = []
    for i in range(len(road) - 1):
        arc = network.arc_between(road[i], road[i + 1])
        if arc is None or arc.lake:
            continue
        ends = arc.ends_direction(road[i], road[i + 1])
        if ends is None:
            ends = (road[i], road[i + 1])
        if ends not in outside:
            outside.append(ends)
    return outside


# ------------------------------------------------------------------ boats
def vehicle_node(entry: dict, orient: str, network=None):
    """The junction a boat sits on: the node at the spot written in the stable.

    The saved spot is a point in radii from the center (`pos_x`, `pos_y`), and
    a boat sits on a junction: the one falling on it is taken. A boat placed
    before this rule — or brought ashore by a land journey — may sit on none:
    then, if the network is there, the nearest water junction in its hex is
    taken; without it, None.
    """
    col, row = (entry or {}).get("hex_col"), (entry or {}).get("hex_row")
    if col is None or row is None:
        return None
    coord = (int(col), int(row))
    x, y = entry.get("pos_x"), entry.get("pos_y")
    point = ((float(x), float(y)) if x is not None and y is not None
             else (0.0, 0.0))
    exact = node_of_unit_point(coord, point, orient, surface=0.03)
    if exact is not None and (network is None or exact in network.neighbours):
        return exact
    if network is None:
        return None
    best, dist = None, None
    for node in hex_nodes(network, coord):
        here = unit_point_of_node(node, coord, orient)
        if here is None:
            continue
        d = (here[0] - point[0]) ** 2 + (here[1] - point[1]) ** 2
        if dist is None or d < dist:
            best, dist = node, d
    return best


def touching_faces(node, banks: dict, orient: str) -> set:
    """The shores touching that point: `{(hex, section number)}`.

    From there one boards a boat stopped at that point, and there one lands. A
    corner belongs to three hexes, and from all three; inside a whole hex the
    shore is zero, i.e. the hex itself.
    """
    outside: set = set()
    for coord in node_hexes(node, orient):
        coord = (int(coord[0]), int(coord[1]))
        point = unit_point_of_node(node, coord, orient)
        if point is None:
            continue
        faces = (banks or {}).get(coord)
        if not faces or len(faces) < 2:
            outside.add((coord, 0))
            continue
        for index, face in enumerate(faces):
            if sections.touches_ring(face, point):
                outside.add((coord, index))
    return outside
