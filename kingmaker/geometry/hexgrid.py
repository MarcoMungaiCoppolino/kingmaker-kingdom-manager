"""Geometry of the hex grid.

Supports both orientations in offset coordinates:
  * "pointy"  -> points up/down, staggered rows (odd-r)
  * "flat"    -> flat sides up/down, staggered columns (odd-q)
"""
from __future__ import annotations

import math
from functools import lru_cache


# ---------------------------------------------------------------- conversions
def offset_to_cube(col: int, row: int, orientation: str = "pointy") -> tuple[int, int, int]:
    if orientation == "pointy":            # odd-r
        x = col - (row - (row & 1)) // 2
        z = row
    else:                                   # odd-q
        x = col
        z = row - (col - (col & 1)) // 2
    return x, -x - z, z


def cube_to_offset(x: int, z: int, orientation: str = "pointy") -> tuple[int, int]:
    if orientation == "pointy":
        col = x + (z - (z & 1)) // 2
        row = z
    else:
        col = x
        row = z + (x - (x & 1)) // 2
    return col, row


def distance(a: tuple[int, int], b: tuple[int, int], orientation: str = "pointy") -> int:
    ax, ay, az = offset_to_cube(a[0], a[1], orientation)
    bx, by, bz = offset_to_cube(b[0], b[1], orientation)
    return max(abs(ax - bx), abs(ay - by), abs(az - bz))


def neighbours(col: int, row: int, orientation: str = "pointy") -> list[tuple[int, int]]:
    x, y, z = offset_to_cube(col, row, orientation)
    dirs = [(1, -1, 0), (1, 0, -1), (0, 1, -1), (-1, 1, 0), (-1, 0, 1), (0, -1, 1)]
    return [cube_to_offset(x + dx, z + dz, orientation) for dx, _dy, dz in dirs]


# ------------------------------------------------------------------- pixel/hex
def hex_center(col: int, row: int, size: float, origin: tuple[float, float],
               orientation: str = "pointy") -> tuple[float, float]:
    """Pixel center of hex (col, row). `size` = radius (center→vertex)."""
    ox, oy = origin
    if orientation == "pointy":
        w = math.sqrt(3) * size
        h = 2 * size
        x = ox + w * (col + 0.5 * (row & 1))
        y = oy + h * 0.75 * row
    else:
        w = 2 * size
        h = math.sqrt(3) * size
        x = ox + w * 0.75 * col
        y = oy + h * (row + 0.5 * (col & 1))
    return x, y


def hex_corners(cx: float, cy: float, size: float, orientation: str = "pointy") -> list[tuple[float, float]]:
    offset = -30.0 if orientation == "pointy" else 0.0
    pts = []
    for i in range(6):
        angle = math.radians(60 * i + offset)
        pts.append((cx + size * math.cos(angle), cy + size * math.sin(angle)))
    return pts


def pixel_to_hex(px: float, py: float, size: float, origin: tuple[float, float],
                 orientation: str = "pointy") -> tuple[int, int]:
    """The hex containing the point (px, py)."""
    ox, oy = origin
    x, y = px - ox, py - oy
    if orientation == "pointy":
        q = (math.sqrt(3) / 3 * x - 1 / 3 * y) / size
        r = (2 / 3 * y) / size
    else:
        q = (2 / 3 * x) / size
        r = (-1 / 3 * x + math.sqrt(3) / 3 * y) / size
    cx, cz = _axial_round(q, r)
    return cube_to_offset(cx, cz, orientation)


def _axial_round(q: float, r: float) -> tuple[int, int]:
    x, z = q, r
    y = -x - z
    rx, ry, rz = round(x), round(y), round(z)
    dx, dy, dz = abs(rx - x), abs(ry - y), abs(rz - z)
    if dx > dy and dx > dz:
        rx = -ry - rz
    elif dy > dz:
        ry = -rx - rz
    else:
        rz = -rx - ry
    return int(rx), int(rz)


def polygon_points(col: int, row: int, size: float, origin: tuple[float, float],
                   orientation: str = "pointy") -> str:
    cx, cy = hex_center(col, row, size, origin, orientation)
    pts = hex_corners(cx, cy, size, orientation)
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)


@lru_cache(maxsize=8192)
def polygon_path(col: int, row: int, size: float, origin: tuple[float, float],
                 orientation: str = "pointy") -> str:
    """Outline of the hex as a `d` sub-path of a <path>.

    Shorter than the point list of a <polygon>: on a large grid the difference
    is tens of KB sent at every redraw.
    """
    # Cached because it never changes: it depends only on where the hex is and
    # on how the grid is calibrated. A redraw asks for more than eight hundred
    # of them — the whole grid, plus the fog, plus the selections — and redoing
    # the six corners with sine and cosine every time was the most expensive
    # piece of the whole drawing. If the calibration changes, the arguments
    # change and the cache fills up again with the right ones: nothing to
    # invalidate by hand.
    cx, cy = hex_center(col, row, size, origin, orientation)
    pts = hex_corners(cx, cy, size, orientation)
    return "M" + " ".join(f"{x:.1f} {y:.1f}".replace(".0", "") for x, y in pts) + "Z"


# -------------------------------------------------------------------- borders
# A river is not *in* a hex: it lies *between* two hexes. So a stable key for
# the side is needed, and its geometry to draw it.
def border_key(a: tuple[int, int], b: tuple[int, int]) -> tuple[int, int, int, int]:
    """The ordered pair: a physical border has one key, from both sides."""
    return (*a, *b) if tuple(a) <= tuple(b) else (*b, *a)


def side_corners(side: int) -> tuple[int, int]:
    """The two vertices closing the side towards neighbour number `side`.

    Holds for both orientations: the neighbours are numbered one way round and
    the vertices the other, and the arithmetic is always this.
    """
    first = (6 - (side % 6)) % 6
    return first, (first + 1) % 6


def shared_side(a: tuple[int, int], b: tuple[int, int], size: float,
                   origin: tuple[float, float], orientation: str = "pointy"):
    """The two vertices shared by two neighbouring hexes, or None if they do not touch.

    Found by pairing the vertices of the two hexes: the shared ones fall on the
    same point, up to floating-point rounding.
    """
    ca = hex_corners(*hex_center(a[0], a[1], size, origin, orientation), size, orientation)
    cb = hex_corners(*hex_center(b[0], b[1], size, origin, orientation), size, orientation)
    tolerance = max(size * 0.01, 0.5) ** 2
    common_ones = [p for p in ca
              if any((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 < tolerance for q in cb)]
    return (common_ones[0], common_ones[1]) if len(common_ones) == 2 else None


def nearest_side(px: float, py: float, size: float, origin: tuple[float, float],
                    orientation: str = "pointy"):
    """The hex under the point and the neighbour beyond the side nearest to it.

    The midpoint of a side is the midpoint between the two centers: it is
    enough to pick the neighbour whose midpoint falls closest to the click,
    without counting vertex angles.
    """
    col, row = pixel_to_hex(px, py, size, origin, orientation)
    cx, cy = hex_center(col, row, size, origin, orientation)
    best, dist = None, None
    for near in neighbours(col, row, orientation):
        vx, vy = hex_center(near[0], near[1], size, origin, orientation)
        mx, my = (cx + vx) / 2, (cy + vy) / 2
        d = (px - mx) ** 2 + (py - my) ** 2
        if dist is None or d < dist:
            best, dist = near, d
    return (col, row), best


# ------------------------------------------------------------------- vertices
def common_vertex(coord, d1: int, d2: int, size: float, origin, orient: str):
    """The vertex of the hex where two of its sides meet.

    Derived from the sides themselves rather than from the angles: two adjacent
    sides share one end and not the other, and finding it this way holds for
    both grid orientations without index tables.
    """
    around = neighbours(coord[0], coord[1], orient)
    a = shared_side(coord, around[d1], size, origin, orient)
    b = shared_side(coord, around[d2], size, origin, orient)
    if a is None or b is None:
        return None
    tolerance = max(size * 0.02, 1.0) ** 2
    for p in a:
        for q in b:
            if (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 < tolerance:
                return p
    return None


# In the order of the walk around the hex the sides are not 0,1,2,3,4,5:
# direction 1 sits next to 0 on the opposite side from 5. Walking by
# decreasing index takes them in the order they lie on the map.
SIDE_RING = (0, 5, 4, 3, 2, 1)


# Which corner of `hex_corners` is vertex `k` of the side ring.
# Computed once per orientation and then valid for every hex: the shape of a
# hex does not change from one cell to the next. Before, the count was redone
# for every pair of sides of every cell — two `hex_corners` and a trial
# comparison each — and it was the most expensive piece of the redraw.
_VERTEX_ORDER: dict[str, tuple] = {}


def vertex_order(orient: str) -> tuple:
    """The correspondence between the six corners and the six vertices, computed once.

    Computed with the slow method on a reference hex and kept: so it stays
    exact even if one day the geometry changes, instead of being a hand-written
    list of numbers nobody could rebuild.
    """
    if orient in _VERTEX_ORDER:
        return _VERTEX_ORDER[orient]
    reference, size, origin = (1, 1), 100.0, (0.0, 0.0)
    cx, cy = hex_center(reference[0], reference[1], size, origin, orient)
    corners = hex_corners(cx, cy, size, orient)
    order = []
    for k in range(6):
        v = common_vertex(reference, SIDE_RING[k], SIDE_RING[(k + 1) % 6],
                            size, origin, orient)
        if v is None:
            order.append(k)
            continue
        order.append(min(range(6), key=lambda i: (corners[i][0] - v[0]) ** 2
                                                  + (corners[i][1] - v[1]) ** 2))
    _VERTEX_ORDER[orient] = tuple(order)
    return _VERTEX_ORDER[orient]


def vertices_of(coord, size: float, origin, orient: str) -> list:
    """The six vertices of the hex, in the order of the side ring.

    Vertex `k` sits between side `SIDE_RING[k]` and side `SIDE_RING[k+1]`: it is
    the order `bank_stretches` draws them in, and the one needed to turn two
    clicks into two banks.
    """
    cx, cy = hex_center(coord[0], coord[1], size, origin, orient)
    corners = hex_corners(cx, cy, size, orient)
    return [corners[i] for i in vertex_order(orient)]
