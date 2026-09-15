"""The hand-drawn cut: two clicks on the vertices, even when they fall in other hexes."""
import re

from kingmaker.geometry import hexgrid
from kingmaker import travel as v
from kingmaker.state import STATE
from kingmaker.ui import hexmap, theme
from kingmaker.access import permissions
# The water brushes are the GM's: here they act.
permissions.can = lambda *a, **k: True

theme.notify = lambda *a, **k: None
theme.mark_dirty = lambda *a, **k: None

A, C = STATE.archive, STATE.campaign
m = STATE.k["map"]
size = float(m["size"])
origin = (float(m["origin_x"]), float(m["origin_y"]))
orient = m["orientation"]
columns, rows = int(m["columns"]), int(m["rows"])
results = []


def clean():
    for c in list(A.campaign_banks(C)):
        A.set_banks(C, c, None)


def click(mine, point):
    """The click as the map delivers it: only the pixel coordinates."""
    hexmap._cut_hex(mine, point)


def hexagon_in_progress(mine):
    """Which hexes the cut could end up on, after the first click."""
    return {c for c, _k in mine["cut_in_progress"]["owners"]}


COORD = (9, 4)
CENTER = hexgrid.hex_center(COORD[0], COORD[1], size, origin, orient)
vert = hexmap.vertices_of(COORD, size, origin, orient)
inner_direction = lambda k, q=0.25: (vert[k][0] + (CENTER[0] - vert[k][0]) * q,
                                  vert[k][1] + (CENTER[1] - vert[k][1]) * q)

# --- 1. how many vertices fall outside: it is the reason for the defect ---
outside = sum(1 for x, y in vert
            if hexgrid.pixel_to_hex(x, y, size, origin, orient) != COORD)
results.append((f"{outside} vertices out of 6 fall in another hexagon", outside > 0))

# --- 2. two clicks exactly on the vertices: it must work all the same -----
# The defect was here: the first click fixed the hexagon with pixel_to_hex,
# and right on a vertex that question often answers with the neighbour.
clean()
mine = {"cut_in_progress": None}
click(mine, vert[0])
results.append(("the first click takes a vertex",
              mine["cut_in_progress"] is not None))
results.append(("and the right hexagon is among the candidates",
              COORD in hexagon_in_progress(mine)))
click(mine, vert[3])
banks = A.campaign_banks(C)
results.append(("the second click closes the cut", mine["cut_in_progress"] is None))
results.append(("and the cut has been written", len(banks) == 1))
results.append(("right on the hexagon of the two vertices", COORD in banks))

# --- 3. the cut really divides ------------------------------------------
groups = banks[COORD]
results.append(("two shores", len(groups) == 2))
a = {d for _n, d in v.steps_from((COORD[0], COORD[1], 0), orient, banks)}
b = {d for _n, d in v.steps_from((COORD[0], COORD[1], 1), orient, banks)}
results.append(("the two shores do not talk", bool(a) and bool(b) and not (a & b)))

# --- 4. click inside the hexagon: the hexagon is that one ----------------
clean()
mine = {"cut_in_progress": None}
click(mine, inner_direction(1))
click(mine, inner_direction(4))
results.append(("clicking inside, the cut ends up there", COORD in A.campaign_banks(C)))

# --- 5. the same vertex twice cancels -----------------------------------
clean()
mine = {"cut_in_progress": None}
click(mine, inner_direction(2))
click(mine, inner_direction(2))
results.append(("the same vertex twice: cancels",
              mine["cut_in_progress"] is None and not A.campaign_banks(C)))

# --- 6. the second click counts even if it falls outside the hexagon -----
clean()
mine = {"cut_in_progress": None}
click(mine, inner_direction(0))
far = (vert[3][0] - 40, vert[3][1] + 25)      # well beyond the edge
results.append(("that point falls in another hexagon",
              hexgrid.pixel_to_hex(far[0], far[1], size, origin, orient)
              != COORD))
click(mine, far)
results.append(("but the cut stays on the hexagon of the two vertices",
              COORD in A.campaign_banks(C)))

# --- 6b. the two clicks on the bare vertices *always* give the right hexagon
# Sixteen hexagons for all thirty pairs of vertices: the proof that the
# defect is closed, not dodged on a lucky case.
clean()
wrong = 0
for col in range(6, 10):
    for row in range(3, 7):
        target = (col, row)
        points = hexmap.vertices_of(target, size, origin, orient)
        for k1 in range(6):
            for k2 in range(6):
                if k1 == k2:
                    continue
                clean()
                for key in list(A.campaign_borders(C)):
                    A.set_border(C, (key[0], key[1]),
                                      (key[2], key[3]), None)
                mine = {"cut_in_progress": None}
                click(mine, points[k1])
                click(mine, points[k2])
                expected_side = hexmap.side_between_vertices(target, k1, k2, orient)
                if expected_side is not None:
                    cfg = A.campaign_borders(C)
                    if hexgrid.border_key(target, expected_side) not in cfg:
                        wrong += 1
                elif target not in A.campaign_banks(C):
                    wrong += 1
clean()
for key in list(A.campaign_borders(C)):
    A.set_border(C, (key[0], key[1]), (key[2], key[3]), None)
results.append((f"480 pairs of bare vertices, {wrong} ended up on the wrong "
              "hexagon", wrong == 0))

# --- 7. the eraser removes the cut by passing over it -------------------
clean()
mine = {"cut_in_progress": None}
click(mine, inner_direction(0))
click(mine, inner_direction(3))
groups = A.campaign_banks(C)[COORD]
stretch = hexmap.bank_stretches({COORD: groups}, size, origin, orient)[0]
n = [float(x) for x in re.findall(r'-?\d+\.?\d*', stretch)]
vehicle = ((n[0] + n[2]) / 2, (n[1] + n[3]) / 2)
hexmap._erase_under(vehicle)
results.append(("the eraser passed over the cut removes it",
              COORD not in A.campaign_banks(C)))

# --- 8. a second cut adds to the first, it does not erase it ------------
clean()
mine = {"cut_in_progress": None}
click(mine, inner_direction(0)); click(mine, inner_direction(3))
first = A.campaign_banks(C).get(COORD)
results.append(("the first cut gives two shores", first is not None and len(first) == 2))
mine = {"cut_in_progress": None}
click(mine, inner_direction(1)); click(mine, inner_direction(4))
second = A.campaign_banks(C).get(COORD)
results.append(("the second cut does not erase the first",
              second is not None and len(second) > len(first)))
results.append(("and the shores remain a cover of the six sides",
              second is not None
              and sorted(d for g in second for d in g) == list(range(6))))
results.append(("no shore talks with another",
              all(not ({d for _n, d in v.steps_from((COORD[0], COORD[1], a), orient, {COORD: second})}
                       & {d for _n, d in v.steps_from((COORD[0], COORD[1], b), orient, {COORD: second})})
                  for a in range(len(second)) for b in range(a + 1, len(second)))))
results.append(("and both cuts are drawn",
              len(hexmap.bank_stretches({COORD: second}, size, origin, orient)) >= 2))

# --- 9. the same cut twice changes nothing -------------------------------
mine = {"cut_in_progress": None}
click(mine, inner_direction(1)); click(mine, inner_direction(4))
results.append(("repeating the same cut adds no shores",
              A.campaign_banks(C).get(COORD) == second))

# --- 10. two *neighbouring* vertices give a side, not a cut --------------
clean()
for key in list(A.campaign_borders(C)):
    A.set_border(C, (key[0], key[1]), (key[2], key[3]), None)
mine = {"cut_in_progress": None}
click(mine, inner_direction(0)); click(mine, inner_direction(1))
cfg = A.campaign_borders(C)
is_expected = hexmap.side_between_vertices(COORD, 0, 1, orient)
results.append(("two neighbouring vertices write a border, not a bank",
              len(cfg) == 1 and not A.campaign_banks(C)))
results.append(("and it is precisely the side between those two vertices",
              is_expected is not None
              and hexgrid.border_key(COORD, is_expected) in cfg))
results.append(("marked as water",
              list(cfg.values())[0]["kind"] == "water"))

# --- 11. and all six sides are reached this way -------------------------
sides = {hexmap.side_between_vertices(COORD, k, (k + 1) % 6, orient) for k in range(6)}
results.append(("the six neighbouring vertices name the six sides",
              len(sides) == 6 and None not in sides))
results.append(("while two far vertices are not a side",
              all(hexmap.side_between_vertices(COORD, a, b, orient) is None
                  for a, b in ((0, 2), (0, 3), (1, 4), (2, 5)))))
for key in list(A.campaign_borders(C)):
    A.set_border(C, (key[0], key[1]), (key[2], key[3]), None)

# --- 12. two vertices that do not go together: nothing is made up --------
clean()
mine = {"cut_in_progress": None}
click(mine, inner_direction(0))
# the center of a far hexagon: none of its vertices is also one of COORD
elsewhere = hexgrid.hex_center(COORD[0] + 3, COORD[1], size, origin, orient)
click(mine, elsewhere)
results.append(("two vertices sharing no hexagon: cancels",
              mine["cut_in_progress"] is None and not A.campaign_banks(C)
              and not A.campaign_borders(C)))

width = max(len(n) for n, _ in results)
for name, ok in results:
    print(("  ok  " if ok else " NO   ") + name.ljust(width))
print(f"\n{sum(1 for _, ok in results if ok)}/{len(results)} passed")
