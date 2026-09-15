# -*- coding: utf-8 -*-
"""The figures of chapter 9 (water travel), drawn with the app's real geometry.

Regenerate with:

    python docs/manual/water_figures.py

No figure is drawn by hand: the hexes come from `hexgrid`, the model's
sections from `waterways.banks_from_cuts`, and the «real» faces from a planar
cut made in here. So a figure cannot tell something other than what the
program does: if the model changes, the figures change with it.

The planar cut lives here and not in the app on purpose: it serves to
**show** the difference between sections and faces, which is the subject of
the last chapter. The day it became the real model, it would move into
`waterways`.
"""
from __future__ import annotations

import itertools
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

import itertools                                          # noqa: E402

from kingmaker.geometry import waterways, hexgrid, sections  # noqa: E402

FOLDER = os.path.join(HERE, "img")
SIZE = 100.0
ORIENT = "pointy"

# Colours chosen to stand on both a light and a dark background: no white and
# no black, only half tones.
EDGE = "#8b949e"
WATER = "#4a9fd8"
BRIDGE = "#d7a13b"
LABEL_TEXT = "#7d8590"
STRONG = "#c9d1d9"
TINTS = ["#4fb3a5", "#d7b263", "#a586d0", "#e0705d", "#5aa9e6", "#8fbf5a",
         "#d07ba8", "#69b3d6"]
ROAD = "#8fbf5a"      # the road of whoever walks
MISTAKE = "#e0705d"     # what the model would do if read wrongly


# --------------------------------------------------------------- geometry
# The old model of the banks (groups of sides), which the figures tell as
# «before»: the app no longer uses it.
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




def corners(cx: float = 0.0, cy: float = 0.0) -> list:
    return hexgrid.hex_corners(cx, cy, SIZE, ORIENT)


def vertex(k: int, cx: float = 0.0, cy: float = 0.0):
    """Vertex number `k` **of the ring**, which is not corner number `k`.

    `hex_corners` returns the six corners in trigonometric angle order; the
    side ring meets them in another order, and vertex `k` is the one between
    side `SIDE_RING[k]` and the next. The correspondence between the two
    numberings is kept by `hexgrid.vertex_order`, and it is the same the water
    brush uses when you take two points on the map.

    Drawing corner `k` here instead of vertex `k` changed no count — the two
    numberings resemble each other up to a rotation — but showed the water
    lines turned by one vertex relative to the coloured sections: the drawing
    told a cut other than the one the figure was about.
    """
    return corners(cx, cy)[hexgrid.vertex_order(ORIENT)[k % 6]]


def side_to_center(d: int, cx: float = 0.0, cy: float = 0.0):
    """The midpoint of the side towards neighbour `d`."""
    a, b = hexgrid.side_corners(d)
    p, q = corners(cx, cy)[a], corners(cx, cy)[b]
    return ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)


def faces(chords) -> list:
    """The real faces of a hex cut by these chords.

    The count is not redone here: `kingmaker.sections` does it, which is the
    same code the program decides where you can walk with. A figure that
    illustrates a model and recomputes it on its own is a figure that sooner
    or later tells a model other than the real one — and it already happened,
    with the chords drawn on one vertex and the fills on another.

    Only the unit change remains here: `sections` works on a hex of radius 1
    centered at the origin, the drawing on one of radius `SIZE`.
    """
    return [[(x * SIZE, y * SIZE) for x, y in f.ring]
            for f in sections.faces_of(chords, ORIENT)]

def barycenter(polygon):
    area = cx = cy = 0.0
    for i, (x1, y1) in enumerate(polygon):
        x2, y2 = polygon[(i + 1) % len(polygon)]
        junction = x1 * y2 - x2 * y1
        area += junction
        cx += (x1 + x2) * junction
        cy += (y1 + y2) * junction
    if abs(area) < 1e-9:
        return (0.0, 0.0)
    return (cx / (3 * area), cy / (3 * area))


# ------------------------------------------------------------------ drawing
def open_(width: float, height: float, title: str = "") -> list:
    return [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 '
            f'{width:.0f} {height:.0f}" width="{width:.0f}" '
            f'height="{height:.0f}" font-family="system-ui, sans-serif">'
            f'<title>{title}</title>']


def hexagon(cx, cy, fill_="none", thickness=2.0):
    points = " ".join(f"{x:.1f},{y:.1f}" for x, y in corners(cx, cy))
    return (f'<polygon points="{points}" fill="{fill_}" stroke="{EDGE}" '
            f'stroke-width="{thickness}" stroke-linejoin="round"/>')


def shape(polygon, tint, opacity=0.30, cx=0.0, cy=0.0):
    points = " ".join(f"{x + cx:.1f},{y + cy:.1f}" for x, y in polygon)
    return (f'<polygon points="{points}" fill="{tint}" fill-opacity="{opacity}" '
            f'stroke="{tint}" stroke-width="1" stroke-opacity="0.5"/>')


def row(a, b, color=WATER, thickness=4.0, dash=""):
    extra = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" '
            f'y2="{b[1]:.1f}" stroke="{color}" stroke-width="{thickness}" '
            f'stroke-linecap="round"{extra}/>')


def caption(text, x, y, body=13, color=LABEL_TEXT, weight=500, still="middle"):
    return (f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{still}" '
            f'font-size="{body}" fill="{color}" font-weight="{weight}">'
            f'{text}</text>')


def dot(x, y, radius, color, inside=""):
    outside = (f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius:.1f}" fill="{color}" '
             f'fill-opacity="0.85"/>')
    if inside:
        outside += caption(inside, x, y + radius * 0.35, radius * 1.1, "#12100b", 700)
    return outside


def save(name: str, pieces: list) -> None:
    os.makedirs(FOLDER, exist_ok=True)
    # `newline` fixed because the files end up in git: without it, on Windows
    # they would come out with the platform's line endings and git would
    # rewrite them every time they are regenerated.
    with open(os.path.join(FOLDER, name), "w", encoding="utf-8",
              newline="\n") as f:
        f.write("\n".join(pieces) + "\n</svg>\n")
    print("  written", os.path.join("docs", "manual", "img", name))


# ------------------------------------------------------------- the figures
def figure_numbering():
    """Sides, vertices and center: who is numbered how."""
    width, height = 640, 300
    cx, cy = 170, 150
    dx = 330
    outside = open_(width, height, "Sides and vertices")

    outside.append(hexagon(cx, cy))
    for d in range(6):
        x, y = side_to_center(d, cx, cy)
        outside.append(dot(x, y, 13, EDGE, str(d)))
    outside.append(caption("the six SIDES, like the neighbours", cx, cy - 125, 14, STRONG, 600))
    outside.append(caption("side d looks onto neighbour d", cx, cy + 130, 12))

    outside.append(hexagon(cx + dx, cy))
    for k in range(6):
        x, y = vertex(k, cx + dx, cy)
        outside.append(dot(x, y, 13, BRIDGE, str(k)))
    outside.append(dot(cx + dx, cy, 9, LABEL_TEXT))
    outside.append(caption("the six VERTICES, around the ring", cx + dx, cy - 125, 14, STRONG, 600))
    outside.append(caption("vertex k sits between sides SIDE_RING[k] and [k+1]",
                         cx + dx, cy + 130, 12))
    outside.append(caption("and in the middle, the center", cx + dx, cy + 148, 12))
    save("hex-numbering.svg", outside)


def figure_three_waters():
    """The three tables: border, cut, lake."""
    width, height = 820, 300
    cy = 145
    seats = [190, 470, 700]
    outside = open_(width, height, "Where the water is")

    # border: two real neighbours, and the line on the side they share
    cx = seats[0]
    step = math.sqrt(3) * SIZE
    left_, right_ = cx - step / 2, cx + step / 2
    outside.append(hexagon(left_, cy))
    outside.append(hexagon(right_, cy))
    # The side they share is the one towards the neighbour on the right, i.e.
    # direction 0: its two corners are given by `side_corners`, which speaks
    # of **corners** and not of ring vertices.
    first, second = hexgrid.side_corners(0)
    outside.append(row(corners(left_, cy)[first], corners(left_, cy)[second],
                      WATER, 6))
    outside.append(caption("borders", cx, cy - 115, 14, STRONG, 600))
    outside.append(caption("the water BETWEEN two hexes", cx, cy + 125, 12))

    # cut: a hex with the chord
    cx = seats[1]
    outside.append(hexagon(cx, cy))
    outside.append(row(vertex(0, cx, cy), vertex(3, cx, cy), WATER, 6))
    outside.append(caption("banks", cx, cy - 115, 14, STRONG, 600))
    outside.append(caption("the water INSIDE a hex", cx, cy + 125, 12))

    # lake: a closed ring
    cx = seats[2]
    outside.append(hexagon(cx, cy))
    ring = [vertex(k, cx, cy) for k in range(6)]
    inside = [((x + cx) / 2, (y + cy) / 2) for x, y in ring]
    points = " ".join(f"{x:.1f},{y:.1f}" for x, y in inside)
    outside.append(f'<polygon points="{points}" fill="{WATER}" fill-opacity="0.35" '
                 f'stroke="{WATER}" stroke-width="4" stroke-linejoin="round"/>')
    outside.append(caption("lakes", cx, cy - 115, 14, STRONG, 600))
    outside.append(caption("the water as an AREA", cx, cy + 125, 12))
    save("three-waters.svg", outside)


def sections_panel(cx, cy, chords, title, below, outside, show_faces=False):
    """A cut hex, with its sections (or its real faces) coloured.

    The drawing order is no detail: first the fills, then the edge, then the
    water, and the numbers **last**. With the water above the numbers — and
    with nine chords the water passes everywhere — the digits ended up under
    the lines and the panel became unreadable precisely in the case that had
    the most to explain.
    """
    if show_faces:
        pieces = faces(chords)
        fills = [(shape(p, TINTS[i % len(TINTS)], 0.35, cx, cy),
                      barycenter(p), i) for i, p in enumerate(pieces)]
        signs = [(cx + b[0], cy + b[1], i) for _f, b, i in fills]
        n_items = len(pieces)
    else:
        groups = waterways.banks_from_cuts([k for chord in chords for k in chord])
        fills, signs = [], []
        for index, group in enumerate(groups):
            polygon = bank_polygon(cx, cy, SIZE, ORIENT, group,
                                             len(groups) > 2)
            if len(polygon) >= 3:
                fills.append((shape(polygon, TINTS[index % len(TINTS)], 0.35),
                                  None, index))
            px, py = bank_center(cx, cy, SIZE, ORIENT, group,
                                         len(groups) > 2)
            signs.append((px, py, index))
        n_items = len(groups)

    for piece, _b, _i in fills:
        outside.append(piece)
    outside.append(hexagon(cx, cy))
    for a, b in chords:
        outside.append(row(vertex(a, cx, cy), vertex(b, cx, cy), WATER, 5))
    for px, py, index in signs:
        # A light halo under the number: with the water passing underneath, a
        # transparent dot is not enough to make the digit readable.
        outside.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="12" fill="#f6f8fa" '
                     f'fill-opacity="0.92"/>')
        outside.append(dot(px, py, 11, TINTS[index % len(TINTS)], str(index)))
    outside.append(caption(title, cx, cy - 122, 13, STRONG, 600))
    outside.append(caption(below, cx, cy + 132, 12))
    return n_items


def figure_sections():
    """How sections are counted: the vertices touched."""
    width, height = 720, 310
    cy, seats = 150, [120, 360, 600]
    outside = open_(width, height, "The sections")
    sections_panel(seats[0], cy, [(0, 3)], "one cut", "2 vertices touched, 2 sections", outside)
    sections_panel(seats[1], cy, [(0, 2)], "a corner cut",
                     "2 vertices touched, 2 sections", outside)
    sections_panel(seats[2], cy, [(0, 3), (1, 4)], "two cuts that cross",
                     "4 vertices touched, 4 sections", outside)
    save("sections.svg", outside)


def figure_point():
    """The point of a section: centroid, pull-back, markers."""
    width, height = 700, 320
    cy, seats = 150, [140, 380, 600]
    outside = open_(width, height, "The point of a section")

    chords = [(0, 3)]
    for index, group in enumerate(waterways.banks_from_cuts([0, 3])):
        polygon = bank_polygon(seats[0], cy, SIZE, ORIENT, group)
        outside.append(shape(polygon, TINTS[index], 0.30))
    outside.append(hexagon(seats[0], cy))
    outside.append(row(vertex(0, seats[0], cy), vertex(3, seats[0], cy), WATER, 5))
    for index, group in enumerate(waterways.banks_from_cuts([0, 3])):
        bx, by = bank_center(seats[0], cy, SIZE, ORIENT, group)
        rx = seats[0] + (bx - seats[0]) * 0.82
        ry = cy + (by - cy) * 0.82
        outside.append(dot(rx, ry, 12, TINTS[index], str(index)))
    outside.append(caption("every section has its point", seats[0], cy - 122,
                         13, STRONG, 600))
    outside.append(caption("it is the centroid of the piece, pulled slightly", seats[0],
                         cy + 132, 12))
    outside.append(caption("towards the center so as not to sit on the water", seats[0],
                         cy + 150, 12))

    # confluence: the wedges with the center
    groups = waterways.banks_from_cuts([0, 2, 4])
    for index, group in enumerate(groups):
        polygon = bank_polygon(seats[1], cy, SIZE, ORIENT, group, True)
        outside.append(shape(polygon, TINTS[index], 0.30))
    outside.append(hexagon(seats[1], cy))
    for k in (0, 2, 4):
        outside.append(row(vertex(k, seats[1], cy), (seats[1], cy), WATER, 5))
    for index, group in enumerate(groups):
        px, py = bank_center(seats[1], cy, SIZE, ORIENT, group, True)
        px = seats[1] + (px - seats[1]) * 0.82
        py = cy + (py - cy) * 0.82
        outside.append(dot(px, py, 12, TINTS[index], str(index)))
    outside.append(caption("confluence: wedges with the center", seats[1], cy - 122,
                         13, STRONG, 600))
    outside.append(caption("the stretches all pull towards the middle", seats[1], cy + 132, 12))
    save("section-point.svg", outside)


def figure_bridge():
    """The elbow of the arrow where an inner bridge is passed."""
    width, height = 460, 300
    cx, cy = 230, 150
    outside = open_(width, height, "The elbow of the bridge")
    groups = waterways.banks_from_cuts([0, 3])
    for index, group in enumerate(groups):
        outside.append(shape(bank_polygon(cx, cy, SIZE, ORIENT, group),
                           TINTS[index], 0.22))
    outside.append(hexagon(cx, cy))
    outside.append(row(vertex(0, cx, cy), vertex(3, cx, cy), WATER, 5))

    one = bank_center(cx, cy, SIZE, ORIENT, groups[0])
    two = bank_center(cx, cy, SIZE, ORIENT, groups[1])
    one = (cx + (one[0] - cx) * 0.82, cy + (one[1] - cy) * 0.82)
    two = (cx + (two[0] - cx) * 0.82, cy + (two[1] - cy) * 0.82)
    vehicle = ((one[0] + two[0]) / 2, (one[1] + two[1]) / 2)
    outside.append(dot(vehicle[0], vehicle[1], 10, BRIDGE))
    for a, b in ((side_to_center(2, cx, cy), one), (one, two),
                 (two, side_to_center(4, cx, cy))):
        outside.append(row(a, b, STRONG, 4.5))
    for point in (one, two):
        outside.append(dot(point[0], point[1], 6, STRONG))
    outside.append(caption("enters here, bends, leaves there", cx, cy - 122,
                         13, STRONG, 600))
    outside.append(caption("the elbow is the bridge inside the hex", cx, cy + 132, 12))
    save("bridge-elbow.svg", outside)


def figure_limits():
    """The three cases that made the definition of section change."""
    width, height = 720, 960
    outside = open_(width, height, "Sections versus faces")
    cases = [
        ([(0, 2), (3, 5)], "two separate chords"),
        ([(0, 2), (2, 4), (4, 0)], "a triangle inside"),
        ([(a, b) for a, b in itertools.combinations(range(6), 2)
          if (b - a) % 6 not in (1, 5)], "all the diagonals"),
    ]
    for index, (chords, name) in enumerate(cases):
        cy = 175 + index * 305
        outside.append(caption(name, 360, cy - 148, 14, STRONG, 700))
        n_items = sections_panel(200, cy, chords, "as it counted before", "", outside)
        real_ones = sections_panel(520, cy, chords, "as it counts now", "", outside, True)
        outside.append(caption(f"{n_items} sections", 200, cy + 135, 12))
        outside.append(caption(f"{real_ones} sections", 520, cy + 135, 12, BRIDGE, 700))
        outside.append(f'<line x1="360" y1="{cy - 105}" x2="360" y2="{cy + 105}" '
                     f'stroke="{EDGE}" stroke-width="1" stroke-dasharray="4 5" '
                     f'stroke-opacity="0.5"/>')
    save("section-limits.svg", outside)


def figure_graph():
    """The travel node: (col, row, bank), and the steps between nodes."""
    width, height = 620, 320
    cy = 160
    left_, right_ = 190, 190 + math.sqrt(3) * SIZE
    outside = open_(width, height, "The travel graph")

    groups = waterways.banks_from_cuts([0, 3])
    for index, group in enumerate(groups):
        outside.append(shape(bank_polygon(left_, cy, SIZE, ORIENT, group),
                           TINTS[index], 0.22))
    outside.append(hexagon(left_, cy))
    outside.append(hexagon(right_, cy))
    outside.append(row(vertex(0, left_, cy), vertex(3, left_, cy), WATER, 5))

    one = bank_center(left_, cy, SIZE, ORIENT, groups[0])
    two = bank_center(left_, cy, SIZE, ORIENT, groups[1])
    three = (right_, cy)
    for point, label, tint in ((one, "0", TINTS[0]), (two, "1", TINTS[1]),
                                    (three, "0", TINTS[2])):
        outside.append(dot(point[0], point[1], 13, tint, label))
    outside.append(row(one, three, LABEL_TEXT, 2, "6 4"))
    outside.append(row(one, two, BRIDGE, 2, "6 4"))
    outside.append(caption("a node is (col, row, bank)", 310, cy - 130, 14, STRONG, 600))
    outside.append(caption("step between hexes: one leaves by the sides of one's own bank",
                         310, cy + 128, 12))
    outside.append(caption("step inside the hex: only with a bridge or a ford",
                         310, cy + 146, 12, BRIDGE))
    save("node-graph.svg", outside)


# ------------------------------------------------------- the 24-atom hex
# The water lines one can draw are always the same: from a vertex to another,
# or from a vertex to the center. Drawing them *all* cuts the hex into 24
# pieces, and those 24 pieces do not depend on what was really drawn: they are
# always there. A water line does not create them, it closes passages between
# them.
def atoms():
    """The 24 fixed pieces, and the 36 borders separating them.

    The count is closed: the nine diagonals alone make 24 pieces, and adding
    the six radii to the center or the six sides adds not a single one — the
    radii are already halves of the long diagonals. So every drawable line is
    a set of borders between atoms, exactly, and not approximately.
    """
    diagonals = [(a, b) for a, b in itertools.combinations(range(6), 2)
                 if (b - a) % 6 not in (1, 5)]
    pieces = sections.faces_of(diagonals, ORIENT)
    key = lambda q: (round(q[0], 6), round(q[1], 6))
    whose = {}
    for i, face in enumerate(pieces):
        ring = face.ring
        for k in range(len(ring)):
            a, b = ring[k], ring[(k + 1) % len(ring)]
            whose.setdefault(frozenset((key(a), key(b))),
                              [(a, b), set()])[1].add(i)
    borders = [(stretch, tuple(sorted(who)))
               for stretch, who in whose.values() if len(who) == 2]
    return pieces, borders


def atoms_panel(cx, cy, water, full_ones, route, title, below, outside,
                   sign=None):
    """A hex with its 24 atoms, a water line and perhaps a road."""
    pieces, borders = atoms()
    for (a, b), _who in borders:
        outside.append(f'<line x1="{cx + a[0] * SIZE:.1f}" y1="{cy + a[1] * SIZE:.1f}" '
                     f'x2="{cx + b[0] * SIZE:.1f}" y2="{cy + b[1] * SIZE:.1f}" '
                     f'stroke="{EDGE}" stroke-width="0.8" stroke-opacity="0.55"/>')
    for index, tint in (full_ones or {}).items():
        outside.append(shape([(cx + x * SIZE, cy + y * SIZE)
                            for x, y in pieces[index].ring], tint, 0.40))
    outside.append(hexagon(cx, cy))
    for one, two in water or ():
        a = vertex(one, cx, cy)
        b = (cx, cy) if two is None else vertex(two, cx, cy)
        outside.append(row(a, b, WATER, 5))
    if route:
        points = [(cx + pieces[i].point[0] * SIZE, cy + pieces[i].point[1] * SIZE)
                 for i in route]
        outside.append('<polyline points="'
                     + " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
                     + f'" fill="none" stroke="{ROAD}" stroke-width="3.5" '
                     f'stroke-linecap="round" stroke-linejoin="round"/>')
        for x, y in points:
            outside.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{ROAD}"/>')
    if sign:
        outside.append(sign)
    outside.append(caption(title, cx, cy - 122, 13, STRONG, 600))
    outside.append(caption(below, cx, cy + 132, 12))


def figure_atoms_point():
    """Why the vertex rule looks at the point and not at the sides."""
    width, height = 720, 330
    outside = open_(width, height, "The point, not the sides")
    pieces, _borders = atoms()
    six, seven = pieces[6].point, pieces[7].point
    left_, right_, cy = 190, 530, 165

    # On the left: only the sides belonging to the two sections are looked at.
    # At the center six of them meet, and those four the river does not
    # touch: one passes, and the river divides nothing any more. They must be
    # drawn, or the caption speaks of four sides not seen in the figure.
    greens = "".join(
        row((left_, cy),
             (left_ + pieces[i].point[0] * SIZE * 1.55,
              cy + pieces[i].point[1] * SIZE * 1.55), ROAD, 3.5)
        for i in (8, 11, 9, 10))
    arrow = (greens
               + row((left_ + six[0] * SIZE, cy + six[1] * SIZE),
                      (left_ + seven[0] * SIZE, cy + seven[1] * SIZE),
                      MISTAKE, 3.5, "7 5")
               + f'<circle cx="{left_}" cy="{cy}" r="5" fill="{MISTAKE}"/>')
    atoms_panel(left_, cy, [(0, 3)], {6: TINTS[1], 7: TINTS[1]}, None,
                   "the sides of the two sections", "all four free: one passes",
                   outside, arrow)
    block = (f'<circle cx="{right_}" cy="{cy}" r="10" fill="{WATER}"/>'
              + caption("\u00d7", right_, cy + 4.5, 14, "#ffffff", 700))
    atoms_panel(right_, cy, [(0, 3)], {6: TINTS[1], 7: TINTS[1]}, None,
                   "the point", "water reaches it: no passing", outside, block)
    outside.append(caption("6", left_ + six[0] * SIZE + 22,
                         cy + six[1] * SIZE - 6, 12, STRONG, 700))
    outside.append(caption("7", left_ + seven[0] * SIZE - 22,
                         cy + seven[1] * SIZE + 14, 12, STRONG, 700))
    outside.append(caption("6", right_ + six[0] * SIZE + 22,
                         cy + six[1] * SIZE - 6, 12, STRONG, 700))
    outside.append(caption("7", right_ + seven[0] * SIZE - 22,
                         cy + seven[1] * SIZE + 14, 12, STRONG, 700))
    outside.append(caption("0 crossings forbidden out of 15", left_, cy + 152, 12,
                         MISTAKE, 700))
    outside.append(caption("9 crossings forbidden out of 15", right_, cy + 152, 12,
                         BRIDGE, 700))
    save("atoms-the-point.svg", outside)


def figure_atoms_ring():
    """What it costs to go around the mouth of a river that does not divide."""
    width, height = 720, 330
    outside = open_(width, height, "The cost of the detour")
    left_, right_, cy = 190, 530, 165
    atoms_panel(left_, cy, [], {}, [0, 11, 10, 5], "clean hex",
                   "from side 0 to side 5, straight", outside)
    atoms_panel(right_, cy, [(0, None)], {}, [0, 11, 6, 8, 9, 7, 10, 5],
                   "a river that only touches",
                   "same pair of sides, but around the mouth", outside)
    outside.append(caption("4 atoms \u00b7 1 activity\u00e0", left_, cy + 152, 12,
                         ROAD, 700))
    outside.append(caption("8 atoms \u00b7 2 activities\u00e0", right_, cy + 152, 12,
                         ROAD, 700))
    save("atoms-the-detour.svg", outside)


if __name__ == "__main__":
    print("Figures of docs/manual/09-water-travel.md:")
    figure_numbering()
    figure_three_waters()
    figure_sections()
    figure_point()
    figure_bridge()
    figure_graph()
    figure_limits()
    figure_atoms_point()
    figure_atoms_ring()
    print("done.")
