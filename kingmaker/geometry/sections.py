"""The sections of a hex: the pieces the water divides it into. For real.

For a long time a section was **a set of sides**: one looked at the edge
vertices touched by the water and took the edge arcs between two consecutive
touches (`waterways.banks_from_cuts`). It is a simple rule, and for the normal
case — a river entering on one side and leaving on the other — it is also
exact. But it is not what happens on the sheet.

What happens on the sheet is that the water lines cut the hex into **faces**,
like any planar drawing, and faces are not counted that way:

    cut                     model's sections      real faces
    a single chord          2                     2
    two crossing chords     4                     4
    two separate chords     **4**                 **3**
    confluence at center    6                     6
    triangle inside         **3**                 **4**
    all the diagonals       **6**                 **24**

The bold rows are the three ways the old model gets it wrong: it puts a **wall
where there is no water** — two arcs belonging to the same piece end up
counted as different shores — it cannot **name a region touching no side**,
and with nine chords it is off by twenty.

Here the definition changes, and becomes the geometric one: **a section is a
face of the planar arrangement** made of the hex edge plus the water lines
drawn inside.

**The principle everything else rests on.** A section is not something whose
name is kept: it is a question asked of a point. The indices coming out of
here are good for one computation and not a minute longer — whoever has to
remember *where they are* remembers a point, and the section is recomputed for
them. So when the GM redraws the water under someone's feet, that someone does
not move: it is the river that changed.

Everything in here works on a **unit hex**: center at (0, 0), radius 1. The
real coordinates are added by whoever draws, multiplying by `size` and adding
the cell center. One hex is like another, and redoing the geometry for each is
the quickest way to make it slow.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from functools import lru_cache

from kingmaker.geometry import waterways, hexgrid

# All tolerances are in hex radii, because the figure is unitary. `_HAIR`
# decides when two points are the same point: below it there is only
# floating-point noise, above it there are real junctions. `_MIN_AREA` drops
# faces with no area — it happens when a water line lies on a side of the
# hex, and the piece left on this side is a zero-width strip.
_HAIR = 1e-7
# How close to a line a point must be to count as *on* that line. On the unit
# hex the points that matter — vertices, center, junctions — are at least a
# few hundredths apart, so a millionth separates floating-point noise from a
# real distance with no risk of confusion.
_ABOVE = 1e-6
_MIN_AREA = 1e-6
_DIGITS = 6


@dataclass(frozen=True)
class Face:
    """A piece of hex, with its shape, its sides and its point.

    `ring` and `point` are in hex radii, counted from the cell center. `sides`
    are the directions towards the neighbours that piece faces, and **may be
    empty**: a face not touching the edge is an island, and one enters it only
    through an inner crossing. In the old model such a region could not even
    be named.
    """

    ring: tuple
    sides: tuple
    area: float
    point: tuple


def sides_of(section) -> tuple:
    """The sides of a section, whether it comes as a face or as an old group.

    The old model still runs in two honest places: the assisted reading of the
    image (`water_reading._banks_of`) proposes groups of sides, and the water
    chart imports them. Whoever reads the sides has no reason to know which of
    the two it came from.
    """
    return tuple(getattr(section, "sides", section) or ())


# ------------------------------------------------------------------ geometry
@lru_cache(maxsize=8)
def unit_corners(orient: str) -> tuple:
    """The six vertices of the **ring**, on the unit hex centered at the origin.

    They are not the six corners in `hex_corners` order: they are those in the
    order the side ring meets them, which is the numbering the water is drawn
    and saved with. The correspondence is kept by `hexgrid.vertex_order`.
    """
    corners = hexgrid.hex_corners(0.0, 0.0, 1.0, orient)
    return tuple(corners[i] for i in hexgrid.vertex_order(orient))


def _extreme(end_, corners):
    """The point of a segment end: a ring vertex, or the center."""
    if end_ is None:
        return (0.0, 0.0)
    return corners[int(end_) % 6]


def _key(p) -> tuple:
    return (round(p[0], _DIGITS), round(p[1], _DIGITS))


def _junction(a, b, c, d):
    """Where two segments cut each other, ends included. None if they do not."""
    r = (b[0] - a[0], b[1] - a[1])
    s = (d[0] - c[0], d[1] - c[1])
    den = r[0] * s[1] - r[1] * s[0]
    if abs(den) < _HAIR:
        return None                   # parallel, or overlapping: nothing new
    t = ((c[0] - a[0]) * s[1] - (c[1] - a[1]) * s[0]) / den
    u = ((c[0] - a[0]) * r[1] - (c[1] - a[1]) * r[0]) / den
    if -_HAIR < t < 1 + _HAIR and -_HAIR < u < 1 + _HAIR:
        return (a[0] + t * r[0], a[1] + t * r[1])
    return None


def _on_segment(p, a, b) -> bool:
    """Does the point fall on the segment, ends included?"""
    dx, dy = b[0] - a[0], b[1] - a[1]
    along = dx * dx + dy * dy
    if along <= _HAIR:
        return abs(p[0] - a[0]) + abs(p[1] - a[1]) < _ABOVE
    how_much = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / along
    if not (-_ABOVE < how_much < 1 + _ABOVE):
        return False
    how_much = max(0.0, min(1.0, how_much))
    return math.hypot(p[0] - (a[0] + how_much * dx),
                      p[1] - (a[1] + how_much * dy)) < _ABOVE


def _double_area(ring) -> float:
    double_ = 0.0
    for i, (x1, y1) in enumerate(ring):
        x2, y2 = ring[(i + 1) % len(ring)]
        double_ += x1 * y2 - x2 * y1
    return double_


def _inside(x: float, y: float, ring) -> bool:
    """The ray count: odd means inside. Holds for concave shapes too."""
    inside = False
    how_many = len(ring)
    for i in range(how_many):
        (x1, y1), (x2, y2) = ring[i], ring[(i + 1) % how_many]
        if (y1 > y) != (y2 > y):
            cut = x1 + (y - y1) * (x2 - x1) / ((y2 - y1) or 1e-12)
            if x < cut:
                inside = not inside
    return inside


def _inner_point(ring) -> tuple:
    """A point that is **inside** the face, not merely near it.

    Normally it is the centroid, which is also the best place to put a marker.
    But the centroid of a concave figure can fall outside — an L-shaped face,
    or one with a spur — and a marker drawn outside its own section tells a
    lie. When that happens one falls back on the centroid of the widest
    triangle of the fan: that one is inside by construction.
    """
    double_ = _double_area(ring)
    if abs(double_) > _HAIR:
        mx = my = 0.0
        for i, (x1, y1) in enumerate(ring):
            x2, y2 = ring[(i + 1) % len(ring)]
            junction = x1 * y2 - x2 * y1
            mx += (x1 + x2) * junction
            my += (y1 + y2) * junction
        center = (mx / (3 * double_), my / (3 * double_))
        if _inside(center[0], center[1], ring):
            return center
    best, how_much = None, 0.0
    for i in range(1, len(ring) - 1):
        a, b, c = ring[0], ring[i], ring[i + 1]
        area = abs((b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1]))
        point = ((a[0] + b[0] + c[0]) / 3, (a[1] + b[1] + c[1]) / 3)
        if area > how_much and _inside(point[0], point[1], ring):
            best, how_much = point, area
    return best if best is not None else (0.0, 0.0)


# --------------------------------------------------------------------- faces
def canonical(cuts) -> tuple:
    """The cuts reduced to their minimal form: sorted, without duplicates.

    It serves two things at once. The first is keeping the result in memory:
    two hexes drawn the same way have the same cut, and redoing the
    arrangement for each would be the quickest way to make slow a computation
    that is instantaneous. The second is that two equal drawings give the same
    faces **in the same order**, even if one was drawn backwards.
    """
    outside = set()
    for pair in cuts or ():
        try:
            one, two = pair
        except (TypeError, ValueError):
            continue
        a = None if one is None else int(one) % 6
        b = None if two is None else int(two) % 6
        if a == b:
            continue
        outside.add(tuple(sorted((a, b), key=lambda x: -1 if x is None else x)))
    return tuple(sorted(outside, key=lambda p: tuple(-1 if x is None else x
                                                   for x in p)))


def faces_of(cuts, orient: str = "pointy") -> tuple:
    """The faces of the hex cut by these segments."""
    return _faces(canonical(cuts), orient)


@lru_cache(maxsize=1024)
def _faces(cuts: tuple, orient: str) -> tuple:
    """The real count, on cuts already reduced to canonical form.

    `cuts` is a sequence of pairs of ends, where an end is the number of a
    ring vertex (0..5) or `None` for the center — the same two things the
    water brush knows how to snap to.

    The method is the standard one for reading a planar drawing: every segment
    is cut at every point where it crosses another, the neighbours of every
    node are sorted by angle, and the faces are walked always taking the
    rightmost turn. Turning always the same way the inner faces are walked in
    one sense and the outer ring — the edge seen from outside — in the other:
    the sign of the area tells them apart.

    A hex with no cuts gives **a single face**, with all six sides. A stretch
    entering and stopping in the middle still gives one: it is a dead branch,
    the walk enters and comes back out, and the hex is not divided. They are
    the two rules the old model already honoured, and they stay.
    """
    corners = unit_corners(orient)
    # The edge first, one segment per side: the side between vertex `k` and
    # `k+1` is direction `SIDE_RING[k+1]`, the only one of the two touching
    # both those vertices.
    segments = [(corners[k], corners[(k + 1) % 6], hexgrid.SIDE_RING[(k + 1) % 6])
                for k in range(6)]
    for pair in cuts or ():
        try:
            one, two = pair
        except (TypeError, ValueError):
            continue
        a, b = _extreme(one, corners), _extreme(two, corners)
        if _key(a) != _key(b):
            segments.append((a, b, None))

    seats: dict = {}
    for a, b, _d in segments:
        seats[_key(a)], seats[_key(b)] = a, b
    for i, j in itertools.combinations(range(len(segments)), 2):
        p = _junction(segments[i][0], segments[i][1],
                      segments[j][0], segments[j][1])
        if p is not None:
            seats[_key(p)] = p
    # Every segment is split at **all** the points falling on it, not only at
    # those found by crossing it with another. The two look the same and are
    # not: a radius starting from vertex 0 lies *inside* the chord going from
    # vertex 0 to 3, and two overlapping lines cross nowhere. Without this
    # step the long chord did not know it had a node in the middle, the face
    # walk went over the same lines again and the hex came out ten times its
    # own size. It holds for T junctions too, which are the same problem seen
    # smaller.
    above = [{k for k, p in seats.items() if _on_segment(p, a, b)}
             for a, b, _d in segments]

    neighbours: dict = {}
    edge: dict = {}
    for i, (a, _b, direction) in enumerate(segments):
        along = sorted(above[i], key=lambda k: (seats[k][0] - a[0]) ** 2
                       + (seats[k][1] - a[1]) ** 2)
        for one, two in zip(along, along[1:]):
            neighbours.setdefault(one, set()).add(two)
            neighbours.setdefault(two, set()).add(one)
            if direction is not None:
                edge[frozenset((one, two))] = direction

    around = {}
    for node, around_ in neighbours.items():
        around[node] = sorted(
            around_, key=lambda other: math.atan2(seats[other][1] - seats[node][1],
                                                  seats[other][0] - seats[node][0]))

    to_do = {(a, b) for a, around_ in neighbours.items() for b in around_}
    limit = 4 * len(to_do) + 12
    outside = []
    while to_do:
        departure = to_do.pop()
        ring = [departure]
        here = departure
        while len(ring) < limit:
            a, b = here
            back = math.atan2(seats[a][1] - seats[b][1],
                                  seats[a][0] - seats[b][0])
            chosen_one = min(around[b], key=lambda c: (
                (math.atan2(seats[c][1] - seats[b][1], seats[c][0] - seats[b][0])
                 - back) % (2 * math.pi)) or 2 * math.pi)
            next_ = (b, chosen_one)
            if next_ == departure:
                break
            ring.append(next_)
            to_do.discard(next_)
            here = next_
        outline = [seats[a] for a, _b in ring]
        double_ = _double_area(outline)
        if double_ > -_MIN_AREA:
            continue                  # the outer ring, or a face without area
        sides = sorted({edge[frozenset(step)] for step in ring
                       if frozenset(step) in edge})
        outline.reverse()
        outside.append(Face(ring=tuple(outline), sides=tuple(sides),
                            area=-double_ / 2.0, point=_inner_point(outline)))
    # An order that does not depend on how the visit went: whoever re-reads
    # the same drawing must be sure to find the same numbers again.
    #
    # Sorted **by the lowest side** the face touches, which is the same rule
    # the old model sorted its groups with. Not nostalgia: where the two
    # models agree — and that is almost the whole map, a river entering on one
    # side and leaving on the other — the numbers stay those of before, and
    # nothing moves under anyone's feet. Islands, which touch no side, go at
    # the end: they did not exist, so they cannot steal anyone's place.
    def order(f):
        return (min(f.sides) if f.sides else 6, -f.area, f.point)

    return tuple(sorted(outside, key=order))


def face_of_point(faces, point) -> int | None:
    """Which face that point falls in, in hex radii from the center.

    If it falls right on a water line — and it happens, because points come
    from a click or from an old centroid — no ring contains it: then the face
    with the nearest point wins, which is the answer an eye would give.
    """
    if not faces:
        return None
    x, y = float(point[0]), float(point[1])
    for index, face in enumerate(faces):
        if _inside(x, y, face.ring):
            return index
    return min(range(len(faces)),
               key=lambda i: (faces[i].point[0] - x) ** 2
               + (faces[i].point[1] - y) ** 2)


# ------------------------------------------------- from the saved drawing to the cuts
def local_cuts(coord, segments, orient: str = "pointy") -> tuple:
    """The segments drawn inside a hex, seen **from that hex**.

    In the archive a segment end is a node of the water network, and a vertex
    does not belong to one hex: it belongs to **three**, and has a single name
    for all three (`waterways.vertex_key`). Here the number that point has in
    the ring of *this* cell is needed, because that is what cuts the figure.
    """
    coord = (int(coord[0]), int(coord[1]))
    outside = []
    for pair in segments or ():
        ends = []
        for name in pair:
            node = name if isinstance(name, tuple) else waterways.node_from_text(name)
            if node is None:
                break
            if node[0] == waterways.CENTER:
                if (node[1], node[2]) != coord:
                    break        # the center of another hex: does not pass through here
                ends.append(None)
                continue
            own = next((k for c, k in waterways.vertex_owners(
                (node[1], node[2]), node[3], orient) if tuple(c) == coord), None)
            if own is None:
                break            # a vertex this hex does not own
            ends.append(own)
        if len(ends) == 2:
            outside.append(tuple(ends))
    return canonical(outside)


def cuts_from_groups(groups) -> tuple:
    """The cuts that would explain those groups of sides, for whoever lacks the drawing.

    Not every cut hex was drawn by hand: the assisted reading of the image
    (`water_reading.trace`) proposes groups of sides directly, and an imported
    water chart may carry them. Faces however want a figure, not a list.
    `waterways.vertex_cuts` does exactly this translation, and did it before
    this module existed: a cut from vertex to vertex when the shores are two,
    as many radii to the center when they are more.
    """
    return canonical(waterways.vertex_cuts(list(groups or [])))


def map_sections(points: dict | None, banks: dict | None = None,
                        orient: str = "pointy") -> dict:
    """The sections of the whole map: `{(col, row): (Face, ...)}`.

    Only the hexes **really divided** are in it, as in the old model: where
    the water does not cut, a hex stays a single place and need not appear.
    So on a map without rivers this dictionary is empty and travel is exactly
    what it always was, without a single extra computation.

    The drawing wins over the groups: if the hex has segments those are looked
    at, being the real thing; the groups remain for whoever lacks the drawing.
    """
    outside: dict = {}
    for coord in set(points or {}) | set(banks or {}):
        coord = (int(coord[0]), int(coord[1]))
        cuts = local_cuts(coord, (points or {}).get(coord), orient)
        if not cuts:
            cuts = cuts_from_groups((banks or {}).get(coord))
        faces = faces_of(cuts, orient)
        if len(faces) > 1:
            outside[coord] = faces
    return outside


def map_water(points: dict | None, banks: dict | None = None,
                      orient: str = "pointy") -> dict:
    """The water stretches of every hex, in the form `atoms.py` wants.

    Companion of `map_sections`, with the same rule on who wins: the drawing
    if there is one, the groups of sides for whoever lacks it. The difference
    is what comes out — there the **faces**, here the **cuts**, i.e. what is
    needed to know which borders between atoms the water closes.

    The hexes the water **does not divide** are in it too: a river entering
    and stopping makes no shores, so it does not appear among the banks, but
    it closes passages and must be walked around. It is the case the
    faces-only model could not represent.
    """
    outside: dict = {}
    for coord in set(points or {}) | set(banks or {}):
        coord = (int(coord[0]), int(coord[1]))
        cuts = local_cuts(coord, (points or {}).get(coord), orient)
        if not cuts:
            cuts = cuts_from_groups((banks or {}).get(coord))
        if cuts:
            outside[coord] = cuts
    return outside


def _old_bank_polygon(orient: str, group, center_col: bool) -> list:
    """The piece of hex of a shore in the old model (groups of sides).

    Only `remap_bank` needs it: a river entered on one side and left on the
    other, and what remained on this side was an arc of vertices closed by the
    chord between the two ends; at confluences every piece was a wedge from
    the center.
    """
    corners = hexgrid.hex_corners(0.0, 0.0, 1.0, orient)
    taken_ones: set = set()
    for side in group or ():
        first, second = hexgrid.side_corners(int(side))
        taken_ones.add(first)
        taken_ones.add(second)
    if len(taken_ones) < 2 or (len(taken_ones) < 3 and not center_col):
        return []
    departures = [i for i in taken_ones if (i - 1) % 6 not in taken_ones]
    if not departures:
        return [corners[i] for i in range(6)]
    here = departures[0]
    outside = []
    while here in taken_ones and len(outside) < 6:
        outside.append(corners[here])
        here = (here + 1) % 6
    if center_col:
        outside.append((0.0, 0.0))
    return outside


def _old_bank_center(orient: str, group, center_col: bool) -> tuple:
    """The centroid of that piece; for a zero-width strip, the midpoint of its
    sides (it was the shore of a water running along a side)."""
    points = _old_bank_polygon(orient, group, center_col)
    if len(points) < 3:
        corners = hexgrid.hex_corners(0.0, 0.0, 1.0, orient)
        vehicles = []
        for side in group or ():
            first, second = hexgrid.side_corners(int(side))
            vehicles.append(((corners[first][0] + corners[second][0]) / 2,
                          (corners[first][1] + corners[second][1]) / 2))
        if not vehicles:
            return 0.0, 0.0
        return (sum(p[0] for p in vehicles) / len(vehicles),
                sum(p[1] for p in vehicles) / len(vehicles))
    double_area = 0.0
    mx = my = 0.0
    for i, (x1, y1) in enumerate(points):
        x2, y2 = points[(i + 1) % len(points)]
        junction = x1 * y2 - x2 * y1
        double_area += junction
        mx += (x1 + x2) * junction
        my += (y1 + y2) * junction
    if abs(double_area) < 1e-9:
        return 0.0, 0.0
    return mx / (3 * double_area), my / (3 * double_area)


def remap_bank(old_groups, faces, index: int,
                 orient: str = "pointy") -> int:
    """The section number of before, translated into today's.

    It goes through the place, not the number, and it is the only way that
    holds: the old number counted edge arcs, the new one counts faces, and
    between the two there is no correspondence to write. But the old shore
    had a **point** — the centroid of its piece, which is the one the marker
    was drawn on — and that point today falls inside a single face.
    """
    groups = list(old_groups or [])
    if not faces:
        return 0
    if not (0 <= index < len(groups)):
        return 0
    point = _old_bank_center(orient, groups[index], len(groups) > 2)
    found_one = face_of_point(faces, point)
    return 0 if found_one is None else found_one


# --------------------------------------------------- where whoever is here is
def saved_spot(entry) -> tuple | None:
    """The spot of a marker inside its hex, or None if it has none.

    It is a point, not a shore number, and the difference is the whole point
    of this module: a number counts faces and changes meaning as soon as the
    GM draws another line; a point stays where it is. When the water changes,
    the section is recomputed and the marker does not move — because it is not
    the one that moved.

    In hex radii, counted from the cell center. None for whoever is simply at
    the center, which is almost everyone: where the water does not cut, a hex
    is a single place.
    """
    if entry is None:
        return None
    try:
        x, y = entry.get("pos_x"), entry.get("pos_y")
    except AttributeError:
        return None
    if x is None or y is None:
        return None
    return (float(x), float(y))


def section_of(entry, faces) -> int:
    """Which section a marker or a vehicle is on now.

    The question is asked of the saved point. Whoever has none — a marker
    from before, or one placed where the water does not cut — is on the first
    section, which is also the one it had before: sections are sorted by the
    lowest side, and the first is the same as always.
    """
    if not faces:
        return 0
    spot = saved_spot(entry)
    if spot is None:
        return 0
    found_one = face_of_point(faces, spot)
    return 0 if found_one is None else found_one


def section_spot(faces, index: int) -> tuple | None:
    """The point to save to say «I am on this section»."""
    if not faces or not (0 <= int(index) < len(faces)):
        return None
    return faces[int(index)].point


# ------------------------------------------------- the border between two faces
def _ring_sides(face) -> list:
    """The stretches of a face's outline, one per side.

    A section arriving as an old group of sides has no outline — it is not a
    figure, it is a list — and the right answer is «no stretch», not an
    error: whoever passes it is using the old model, and there a point bridge
    makes no sense anyway.
    """
    ring = getattr(face, "ring", None)
    if not ring:
        return []
    return [(ring[i], ring[(i + 1) % len(ring)]) for i in range(len(ring))]


def shared_edge(first: Face, other_one: Face):
    """The stretch of outline two faces share, or None.

    It is along that stretch that the water dividing them runs, and that is
    where a bridge sits. If the two faces do not touch there is nothing to
    cross: a crossing between two distant pieces would be a bridge hopping
    over a third piece without passing through it, and that is not a thing.

    When the shared stretches are more than one — it happens in an odd figure
    — the longest wins: that is the one a bridge fits on.
    """
    if first is other_one:
        return None
    its_ones = {frozenset((_key(a), _key(b))): (a, b)
            for a, b in _ring_sides(first)}
    best, how_much = None, 0.0
    for a, b in _ring_sides(other_one):
        key = frozenset((_key(a), _key(b)))
        if key not in its_ones:
            continue
        along = math.hypot(b[0] - a[0], b[1] - a[1])
        if along > how_much:
            best, how_much = (a, b), along
    return best


def point_between(first: Face, other_one: Face) -> tuple | None:
    """Where a bridge between two sections is planted: in the middle of their border."""
    stretch = shared_edge(first, other_one)
    if stretch is None:
        return None
    (x1, y1), (x2, y2) = stretch
    return ((x1 + x2) / 2, (y1 + y2) / 2)


def border_faces(faces, point) -> tuple:
    """The sections having that point on their outline.

    Needed to translate bridges written the old way, with a single point
    planted **on** the border instead of two planted inside the shores.
    Normally the answer is two; on a junction they are more, and that is
    precisely why that way of writing a bridge did not last.
    """
    if not faces or point is None:
        return ()
    x, y = float(point[0]), float(point[1])
    outside = []
    for index, face in enumerate(faces):
        if any(_on_segment((x, y), a, b) for a, b in _ring_sides(face)):
            outside.append(index)
    return tuple(outside)


def crossing_shores(faces, ends) -> tuple | None:
    """Which two sections a crossing joins, now.

    A bridge is remembered by **two points**, one per shore — the same rule by
    which where a marker is is remembered, and for the same reason: a point
    survives a water line drawn later, a number does not.

    For a while the points were one, the one where one hops over, and it was
    more elegant: the point sat **on** the border, and the two faces followed
    from there. But a second river passing right under the bridge sends that
    point onto a junction, where four sections meet, and «which two do you
    join» stops having an answer — the bridge went dark. Two points planted
    **inside** the two shores stay away from junctions and hold.

    None when the two points ended up in the same section — the water in
    between is gone — or in two that do not touch: a bridge hopping over a
    third piece without passing through it is not a thing.
    """
    if not faces or not ends:
        return None
    one_f_, other_one = ends
    i = face_of_point(faces, one_f_)
    j = face_of_point(faces, other_one)
    if i is None or j is None or i == j:
        return None
    if shared_edge(faces[i], faces[j]) is None:
        return None
    return tuple(sorted((i, j)))


def border_stretch(faces, ends):
    """The water stretch a bridge hops over, to draw its deck.

    The deck goes **across** the water, so one must know which way the water
    runs there. None if that bridge no longer joins two sections.
    """
    which_ones = crossing_shores(faces, ends)
    if which_ones is None:
        return None
    return shared_edge(faces[which_ones[0]], faces[which_ones[1]])


def deck(faces, ends, above, vehicle: float = 0.17):
    """The segment to draw for a crossing: across the water.

    Centered **where the bridge was put** and not in the middle of the river:
    two crossings on the same water line — a bridge here, a ford further on —
    must look like two things, not overlap.

    If the spot is no longer on the water — the GM redrew — it falls back on
    the midpoint of the border between the two shores, which is the most
    sensible place left.
    """
    stretch = border_stretch(faces, ends)
    if stretch is None:
        return None
    (x1, y1), (x2, y2) = stretch
    along = math.hypot(x2 - x1, y2 - y1) or 1.0
    dx, dy = (x2 - x1) / along, (y2 - y1) / along
    center = above if (above is not None
                       and _on_segment(above, stretch[0], stretch[1])) \
        else ((x1 + x2) / 2, (y1 + y2) / 2)
    return ((center[0] + dy * vehicle, center[1] - dx * vehicle),
            (center[0] - dy * vehicle, center[1] + dx * vehicle))


def touches_ring(face, point) -> bool:
    """Does the point sit on the outline of that face?

    In the middle of a ring side too, not only on one of its vertices: a water
    junction a boat sits on is in the middle of the chord acting as border,
    and the face's ring does not name that point.
    """
    ring = getattr(face, "ring", None) or ()
    for k in range(len(ring)):
        if _on_segment(point, ring[k], ring[(k + 1) % len(ring)]):
            return True
    return False


def inner_side_under(faces, point):
    """The inner water stretch that point falls on, or None.

    Needed by the ford: it is drawn along the piece of river one wades, and
    that piece is the atom side the ford was placed on.
    """
    if point is None:
        return None
    for (p, q), _who in inner_sides(faces):
        if _on_segment(point, p, q):
            return (p, q)
    return None


def inner_sides(faces) -> list:
    """The water stretches inside the hex, with the two sections they divide.

    An outline belongs to **two** faces when water runs through it and to a
    single one when it is the hex edge: telling them apart does not require
    knowing where the water was drawn, counting is enough. Every entry is
    `((point, point), (section, section))`.
    """
    count: dict = {}
    for index, face in enumerate(faces or ()):
        for a, b in _ring_sides(face):
            key = frozenset((_key(a), _key(b)))
            entry = count.setdefault(key, [(a, b), set()])
            entry[1].add(index)
    return [(stretch, tuple(sorted(who))) for stretch, who in count.values()
            if len(who) == 2]


def hop(faces, from_, a):
    """Where a hand-drawn chord hops over the water, and what it joins.

    The GM draws a line from one side of the river to the other: this is the
    gesture that places a bridge or a ford. Here one looks at which water
    stretch that line really cuts. If it cuts more than one — it happens in a
    hex with two rivers — the one nearest to the middle of the line wins,
    which is where the hand was aiming.

    The point returned is not the exact junction but the **middle of the
    hopped stretch**, and the choice matters: the junction can fall on a
    vertex, where three or four sections meet and «which two do you join»
    would stop having an answer. The middle of a stretch sits on the outline
    of two faces and no more, always.

    Returns `((point, point), point, (section, section))`: the two shore
    points, the point where one hops over, and the two sections. None if that
    line hops over nothing.
    """
    if not faces or len(faces) < 2:
        return None
    vehicle = ((from_[0] + a[0]) / 2, (from_[1] + a[1]) / 2)
    best = None
    for (p, q), which_ones in inner_sides(faces):
        junction = _junction(from_, a, p, q)
        if junction is None:
            continue
        how_much = math.hypot(junction[0] - vehicle[0], junction[1] - vehicle[1])
        if best is None or how_much < best[0]:
            best = (how_much, junction, which_ones)
    if best is None:
        return None
    i, j = best[2]
    return (faces[i].point, faces[j].point), best[1], (i, j)


def hop_between_sides(faces, side_a: int, side_b: int):
    """The same, but starting from two **sides**: to translate old bridges.

    A crossing had always been written as the pair of sides of the two shores
    it joined. Here one goes back from the shores to the water stretch dividing
    them, and takes its middle. None when those two sides ended up on the same
    section, which means that bridge no longer crossed anything.
    """
    one_f_ = other_one = None
    for index, face in enumerate(faces or ()):
        if side_a in face.sides:
            one_f_ = index
        if side_b in face.sides:
            other_one = index
    if one_f_ is None or other_one is None or one_f_ == other_one:
        return None
    above = point_between(faces[one_f_], faces[other_one])
    if above is None:
        return None
    return ((faces[one_f_].point, faces[other_one].point), above,
            tuple(sorted((one_f_, other_one))))


def breath(face) -> float:
    """How far one can go from a piece's point while staying **in that piece**.

    It is the distance from its point to the outline, in hex radii — but only
    to the outline separating it from something else. A piece can have
    **slits**: a water line entering and stopping in the middle of the hex
    divides nothing, and the face's ring walks it twice, once per side.
    Crossing a slit does not lead into another piece, it leads into the same
    one, and counting it as a wall would say that a piece as big as the whole
    hex has no room for a marker.

    Slits recognise themselves: they are the sides appearing **twice** in the
    ring. Nothing to infer from outside.

    It serves two things, which are the same thing said twice: how far a badge
    can be shifted from the point without sending it into a piece not its own,
    and how big it can be drawn.
    """
    point = getattr(face, "point", None)
    ring = getattr(face, "ring", None)
    if point is None or not ring:
        return 0.0
    px, py = point
    how_many: dict = {}
    sides = []
    for index, end_ in enumerate(ring):
        after = ring[(index + 1) % len(ring)]
        key = tuple(sorted((_key(end_), _key(after))))
        how_many[key] = how_many.get(key, 0) + 1
        sides.append((key, end_, after))
    outside = []
    for key, (ax, ay), (bx, by) in sides:
        if how_many[key] > 1:
            continue          # a slit: the same piece is on the other side
        dx, dy = bx - ax, by - ay
        along = dx * dx + dy * dy
        # The segment and not the line: a piece can be re-entrant, and the
        # line of a far side would pass where the outline is not.
        share = (0.0 if not along
                 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / along)))
        outside.append(math.hypot(px - (ax + share * dx), py - (ay + share * dy)))
    return min(outside) if outside else 0.0
