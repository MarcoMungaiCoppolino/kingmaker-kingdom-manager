"""The eraser: passing over it a line vanishes, anywhere along the line."""
from kingmaker.geometry import hexgrid
from kingmaker.state import STATE
from kingmaker.ui import hexmap, theme
import helpers
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
results = []


def clean():
    for k in list(A.campaign_borders(C)):
        A.set_border(C, (k[0], k[1]), (k[2], k[3]), None)
    for c in list(A.campaign_banks(C)):
        A.set_banks(C, c, None)


COORD = (9, 4)
near = hexgrid.neighbours(*COORD, orient)[0]
vert = hexmap.vertices_of(COORD, size, origin, orient)


def on_the_segment(a, b, q):
    return (a[0] + (b[0] - a[0]) * q, a[1] + (b[1] - a[1]) * q)


# --- 1. a cut is erased along its whole length --------------------------
# It was the defect: «near the center» covered less than half of the line.
done_ones = 0
for q in (0.0, 0.15, 0.3, 0.5, 0.7, 0.85, 1.0):
    clean()
    A.set_banks(C, COORD, helpers.banks_between_vertices(0, 3))
    point = on_the_segment(vert[0], vert[3], q)
    hexmap._erase_under(point)
    if COORD not in A.campaign_banks(C):
        done_ones += 1
results.append((f"the cut is erased at all {done_ones}/7 points of the line",
              done_ones == 7))

# --- 2. and it is not erased if the eraser passes far away --------------
clean()
A.set_banks(C, COORD, helpers.banks_between_vertices(0, 3))
cx, cy = hexgrid.hex_center(*COORD, size, origin, orient)
# a point inside the hexagon but on a shore, far from the cut
far = on_the_segment((cx, cy), vert[1], 0.75)
hexmap._erase_under(far)
results.append(("passing far from the cut does not erase it",
              COORD in A.campaign_banks(C)))

# --- 3. a border is erased by passing over it ---------------------------
done_ones = 0
side = hexgrid.shared_side(COORD, near, size, origin, orient)
for q in (0.15, 0.35, 0.5, 0.65, 0.85):
    clean()
    A.set_border(C, COORD, near, "water")
    hexmap._erase_under(on_the_segment(side[0], side[1], q))
    if not A.campaign_borders(C):
        done_ones += 1
results.append((f"the border is erased at all {done_ones}/5 points of the side",
              done_ones == 5))

# --- 4. the center of the hexagon is over no side -----------------------
clean()
A.set_border(C, COORD, near, "water")
hexmap._erase_under((cx, cy))
results.append(("from the center a far side is not erased",
              len(A.campaign_borders(C)) == 1))

# --- 5. one pass erases everything it meets -----------------------------
clean()
A.set_banks(C, COORD, helpers.banks_between_vertices(0, 3))
A.set_border(C, COORD, near, "water")
before = len(A.campaign_borders(C)) + len(A.campaign_banks(C))
removed_ones = 0
for q in range(0, 21):
    removed_ones += hexmap._erase_under(on_the_segment(vert[0], vert[3], q / 20))
after = len(A.campaign_borders(C)) + len(A.campaign_banks(C))
results.append(("one pass over the cut removes the cut",
              before == 2 and COORD not in A.campaign_banks(C)))
results.append(("and every point removes a single line, not all the nearby ones",
              removed_ones <= 2))

# --- 6. the cut of a neighbouring hexagon too, if the line reaches there --
clean()
other = hexgrid.neighbours(*COORD, orient)[2]
A.set_banks(C, other, helpers.banks_between_vertices(0, 3))
vert_other = hexmap.vertices_of(other, size, origin, orient)
hexmap._erase_under(on_the_segment(vert_other[0], vert_other[3], 0.5))
results.append(("it erases on a neighbouring hexagon too",
              other not in A.campaign_banks(C)))

# --- 7. the basic geometry ----------------------------------------------
results.append(("distance from a segment: on the endpoint it is zero",
              abs(hexmap._dist_from_segment((0, 0), (0, 0), (10, 0))) < 1e-6))
results.append(("halfway along a horizontal segment, vertically, it is the height",
              abs(hexmap._dist_from_segment((5, 3), (0, 0), (10, 0)) - 3) < 1e-6))
results.append(("beyond the endpoint it measures from the endpoint, not from the line",
              abs(hexmap._dist_from_segment((20, 0), (0, 0), (10, 0)) - 10) < 1e-6))

clean()
width = max(len(n) for n, _ in results)
for name, ok in results:
    print(("  ok  " if ok else " NO   ") + name.ljust(width))
print(f"\n{sum(1 for _, ok in results if ok)}/{len(results)} passed")
