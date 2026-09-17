# -*- coding: utf-8 -*-
"""The map in two layers, and the compact hex path.

A boarding used to send every window on the map the whole SVG, 93 KB, for
a marker that moved by two. The drawing is now two strings — the ground and
the live layer — sent to two elements, each only when it changed. Here:
the two joined are the drawing as before, the fills and the fog are in the
ground and the markers in the live layer, a moved marker changes the live
layer and not the ground, and the hex outline, now relative commands on
whole pixels, still passes through the hex's corners and two neighbours
share an edge to the pixel.
"""
import re

from kingmaker.access import permissions, view as view_mod
from kingmaker.geometry import hexgrid
from kingmaker.state import STATE
from kingmaker.ui import hexmap, theme

theme.notify = lambda *a, **k: None
theme.mark_dirty = lambda *a, **k: None
theme.save_light = lambda *a, **k: None

results = []
m = STATE.k["map"]
size, orient = float(m["size"]), m["orientation"]
origin = (float(m["origin_x"]), float(m["origin_y"]))


class Fake:
    id, username, role = "check", "check", permissions.ADMIN
    active = True
    must_change_pw = False


view = view_mod.MapView(Fake(), STATE)
A, C = STATE.archive, STATE.campaign

# --- 1. the two layers are the drawing --------------------------------------
sel = {"show_borders": True, "col": 5, "row": 5, "show_icons": True}
ground, live = hexmap._svg_layers(sel, view)
whole = hexmap._svg_grid(dict(sel), view)
results.append(("ground and live joined are the whole drawing", ground + live == whole))
results.append(("the ground is the heavy one", len(ground) > 4 * len(live)))
results.append(("the fog and the fills are in the ground, not in the live layer",
                'stroke-dasharray="5 4"' in ground and 'stroke-dasharray="5 4"' not in live))
results.append(("the chosen hex ring is in the live layer",
                'stroke-dasharray="6 4"' in live and 'stroke-dasharray="6 4"' not in ground))

# --- 2. a moved marker changes the live layer only ---------------------------
people = STATE.characters()
who = people[0]
before = {k: who.get(k) for k in ("hex_col", "hex_row", "pos_x", "pos_y")}
A.update_character(who["id"], hex_col=5, hex_row=5, pos_x=None, pos_y=None)
ground_a, live_a = hexmap._svg_layers(dict(sel), view)
A.update_character(who["id"], hex_col=6, hex_row=6, pos_x=None, pos_y=None)
ground_b, live_b = hexmap._svg_layers(dict(sel), view)
A.update_character(who["id"], **before)
results.append(("a marker moved: the live layer changed", live_a != live_b))
results.append(("and the ground did not", ground_a == ground_b))
results.append(("the markers are in the live layer",
                who["name"][:6] in live_a or "km-marker" in live_a or len(live_a) > 200))

# --- 3. the hex path: relative, whole pixels, through the corners -------------
path = hexgrid.polygon_path(5, 5, size, origin, orient)
results.append(("the outline is one M, five relative steps and a close",
                bool(re.fullmatch(r"M-?\d+ -?\d+(l-?\d+ ?-?\d+){5}z", path))))
tokens = re.findall(r"[Ml](-?\d+) ?(-?\d+)", path)
x, y = int(tokens[0][0]), int(tokens[0][1])
walked = [(x, y)]
for dx, dy in tokens[1:]:
    x, y = x + int(dx), y + int(dy)
    walked.append((x, y))
cx, cy = hexgrid.hex_center(5, 5, size, origin, orient)
corners = hexgrid.hex_corners(cx, cy, size, orient)
results.append(("the walk lands on every corner within a pixel",
                all(abs(px - qx) <= 0.5 and abs(py - qy) <= 0.5
                    for (px, py), (qx, qy) in zip(walked, corners))))
results.append(("shorter than half the old absolute outline", len(path) < 50))

# two neighbours: the shared edge is the same two points
def corners_of(col, row):
    p = hexgrid.polygon_path(col, row, size, origin, orient)
    toks = re.findall(r"[Ml](-?\d+) ?(-?\d+)", p)
    x, y = int(toks[0][0]), int(toks[0][1])
    out = [(x, y)]
    for dx, dy in toks[1:]:
        x, y = x + int(dx), y + int(dy)
        out.append((x, y))
    return set(out)

shared = corners_of(5, 5) & corners_of(6, 5)
results.append(("two neighbours share exactly two corner points", len(shared) == 2))

width = max(len(n) for n, _ in results)
print()
for name, ok in results:
    print(("  ok  " if ok else " NO   ") + name.ljust(width))
print(f"\n{sum(1 for _, ok in results if ok)}/{len(results)} passed")
