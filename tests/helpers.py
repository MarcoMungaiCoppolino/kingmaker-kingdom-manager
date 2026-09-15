# -*- coding: utf-8 -*-
"""Test helpers: pieces of the **old** bank model (groups of sides), which the
app no longer uses but the tests use to build scenes and to measure the new
model against the previous one.
"""
from kingmaker.geometry import waterways, hexgrid
from kingmaker.ui import hexmap


def silence(name, value=lambda *a, **k: None):
    """Replaces a map function in **all** its modules.

    `hexmap` is a package whose `__init__` is a facade: every module calls its
    own functions by name, so changing it only on the facade would change
    nothing. Returns what was there, to put it back afterwards.
    """
    before = getattr(hexmap, name)
    for module in hexmap.MODULES + (hexmap,):
        if hasattr(module, name):
            setattr(module, name, value)
    return before

def map_source() -> str:
    """The map code, all the package's modules together: for the tests that
    look at the source (it used to be a single file)."""
    import glob
    import os
    return "".join(open(f, encoding="utf-8").read() for f in
                   sorted(glob.glob(os.path.join("kingmaker", "ui", "hexmap", "*.py"))))


SIDE_RING = hexgrid.SIDE_RING


def banks_between_vertices(k1: int, k2: int) -> list:
    """The two banks of a hex cut from one vertex to another."""
    if k1 == k2:
        return []
    first = [SIDE_RING[(k1 + 1 + i) % 6] for i in range((k2 - k1) % 6)]
    second = [d for d in SIDE_RING if d not in first]
    if not first or not second:
        return []
    return [sorted(first), sorted(second)]


def add_cut(groups, k1: int, k2: int) -> list:
    """The new cut is added to those the hex already has (refinement)."""
    new = banks_between_vertices(k1, k2)
    if not new:
        return list(groups or [])
    a, b = set(new[0]), set(new[1])
    departure = [list(g) for g in (groups or [])] or [list(SIDE_RING)]
    outside = []
    for group in departure:
        for part in ([d for d in group if d in a], [d for d in group if d in b]):
            if part:
                outside.append(sorted(part))
    return sorted(outside, key=lambda g: g[0])


def bank_polygon(cx, cy, size, orientation, group, center_col=False) -> list:
    """The piece of hex of a bank in the groups-of-sides model."""
    corners = hexgrid.hex_corners(cx, cy, size, orientation)
    taken_ones = set()
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
        outside.append((cx, cy))
    return outside


def bank_center(cx, cy, size, orientation, group, center_col=False) -> tuple:
    """The centroid of that piece (or the midpoint of its sides if it is a strip)."""
    points = bank_polygon(cx, cy, size, orientation, group, center_col)
    if len(points) < 3:
        corners = hexgrid.hex_corners(cx, cy, size, orientation)
        vehicles = []
        for side in group or ():
            first, second = hexgrid.side_corners(int(side))
            vehicles.append(((corners[first][0] + corners[second][0]) / 2,
                          (corners[first][1] + corners[second][1]) / 2))
        if not vehicles:
            return cx, cy
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
        return cx, cy
    return mx / (3 * double_area), my / (3 * double_area)


def course_directions(currents, road, network=None):
    """For every step of the course: downstream, upstream or None."""
    return [waterways.step_direction(currents, road[i], road[i + 1],
                                     network.arc_between(road[i], road[i + 1]) if network else None)
            for i in range(len(road) - 1)]
