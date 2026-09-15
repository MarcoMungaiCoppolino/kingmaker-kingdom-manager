# -*- coding: utf-8 -*-
"""The figures of the manual, taken from the real program.

Regenerate with a copy of the save in KINGMAKER_DATA_DIR (never the live one)
and `python docs/manual/manual_figures.py`: the map and the water network
come from the same functions that draw the app (`hexmap._svg_grid`,
`hexmap.waters_network`), so they cannot tell something different.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from kingmaker.geometry import waterways, hexgrid  # noqa: E402
from kingmaker.access import permissions
from kingmaker.state import STATE  # noqa: E402
from kingmaker.ui import hexmap, theme  # noqa: E402


def _silence(name, value):
    """The map is a package: a function must be replaced in every module."""
    for module in hexmap.MODULES + (hexmap,):
        if hasattr(module, name):
            setattr(module, name, value)

FOLDER = os.path.join(HERE, "img")


class Allowed:
    id, username, role = "manual", "manual", permissions.ADMIN
    active = True


def _crop(svg_inner: str, cells, size, origin, orient, name: str,
              margin: float = 0.6) -> None:
    xs, ys = [], []
    for c in cells:
        cx, cy = hexgrid.hex_center(c[0], c[1], size, origin, orient)
        xs += [cx - size, cx + size]
        ys += [cy - size, cy + size]
    x0, y0 = min(xs) - size * margin, min(ys) - size * margin
    w, h = max(xs) - x0 + size * margin, max(ys) - y0 + size * margin
    text = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x0:.0f} {y0:.0f} '
             f'{w:.0f} {h:.0f}" width="{w * 0.5:.0f}" height="{h * 0.5:.0f}">'
             f'<rect x="{x0:.0f}" y="{y0:.0f}" width="{w:.0f}" height="{h:.0f}" '
             f'fill="#161209"/>{svg_inner}</svg>')
    with open(os.path.join(FOLDER, name), "w", encoding="utf-8") as fh:
        fh.write(text)
    print("written", name)


def example_map() -> None:
    """A piece of map as the app draws it: river, shores, markers, arrow."""
    theme.notify = lambda *a, **k: None
    theme.mark_dirty = lambda *a, **k: None
    theme.refresh_panels = lambda *a, **k: None
    permissions.can = lambda *a, **k: True
    theme.user = lambda: Allowed()
    _silence("_redraw_travel", lambda *a, **k: None)
    _silence("_send_field", lambda *a, **k: None)
    A, C = STATE.archive, STATE.campaign
    m = STATE.k["map"]
    size = float(m["size"])
    origin = (float(m["origin_x"]), float(m["origin_y"]))
    orient = m["orientation"]
    for c in [(8, 3), (8, 4), (8, 5), (9, 3), (9, 5), (10, 3), (10, 5), (11, 3),
              (11, 5), (12, 3), (12, 5), (9, 4), (10, 4), (11, 4), (12, 4)]:
        h = STATE.hex(c[0], c[1])
        h["terrains"] = h.get("terrains") or ["plains"]
        h["status"] = "reconnoitered"
    char = next(p for p in STATE.characters() if not p.get("stable_id"))
    A.update_character(char["id"], hex_col=8, hex_row=4, pos_x=None, pos_y=None)
    STATE.load()
    mine = hexmap._mine()
    mine.update(travel_pcs=[char["id"]], travel_mode="choose", col=11, row=5,
               player_preview=False)
    hexmap._compute_journey(mine, None)
    view = hexmap._current_view(mine)
    svg = hexmap._svg_grid(mine, view)
    _crop(svg, [(8, 3), (12, 5)], size, origin, orient, "map-example.svg")


def water_network() -> None:
    """The boats' network: junctions and atom sides over the drawn river."""
    m = STATE.k["map"]
    size = float(m["size"])
    origin = (float(m["origin_x"]), float(m["origin_y"]))
    orient = m["orientation"]
    network = hexmap.waters_network()
    pieces = []
    for arc in network.arcs.values():
        a = waterways.node_point(arc.a, size, origin, orient)
        b = waterways.node_point(arc.b, size, origin, orient)
        color = "#d7b263" if arc.kind == "edge" else "#4da6d9"
        pieces.append(f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" '
                     f'stroke="{color}" stroke-width="{size * 0.05:.1f}" stroke-linecap="round"/>')
    nodes = []
    for node in network.neighbours:
        x, y = waterways.node_point(node, size, origin, orient)
        color = {"v": "#e0705d", "c": "#8fbf5a", "x": "#f5e3bb"}.get(node[0], "#fff")
        nodes.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{size * 0.07:.1f}" fill="{color}" '
                    f'stroke="#0b1015" stroke-width="1.2"/>')
    grid = "".join(
        f'<path d="{hexgrid.polygon_path(c, r, size, origin, orient)}" fill="none" '
        f'stroke="#4a3d2c" stroke-width="1.2"/>'
        for r in range(3, 6) for c in range(8, 13))
    _crop(grid + "".join(pieces) + "".join(nodes), [(9, 4), (11, 4)], size,
              origin, orient, "water-network.svg", margin=0.3)


if __name__ == "__main__":
    example_map()
    water_network()
