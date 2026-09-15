"""The hex center as a point: it is clicked, it is drawn, and it does not cut."""
from kingmaker.geometry import waterways, hexgrid
from kingmaker.state import STATE
from kingmaker.ui import hexmap, theme
from kingmaker.access import permissions
# The water brushes are the GM's: here they act.
permissions.can = lambda *a, **k: True

told_ones = []
theme.notify = lambda text, *a, **k: told_ones.append(text)
theme.mark_dirty = lambda *a, **k: None

A, C = STATE.archive, STATE.campaign
m = STATE.k["map"]
size = float(m["size"])
origin = (float(m["origin_x"]), float(m["origin_y"]))
orient = m["orientation"]
columns, rows = int(m["columns"]), int(m["rows"])
results = []
COORD = (9, 4)


def clean():
    A.remove_lake(C)
    A.remove_currents(C)
    A.remove_crossings(C)
    for c in list(A.campaign_banks(C)):
        A.set_banks(C, c, None)
    for k in list(A.campaign_borders(C)):
        A.set_border(C, (k[0], k[1]), (k[2], k[3]), None)


def click(mine, coord, k):
    """A click exactly on a point: a vertex, or the center if k is None."""
    point = (hexgrid.hex_center(coord[0], coord[1], size, origin, orient)
             if k is None
             else hexgrid.vertices_of(coord, size, origin, orient)[k])
    hexmap._cut_hex(mine, point)


# --- 1. the shore rule --------------------------------------------------
results.append(("two cut points make two shores",
              waterways.banks_from_cuts([0, 3]) == [[0, 1, 2], [3, 4, 5]]))
results.append(("three make three",
              len(waterways.banks_from_cuts([0, 2, 4])) == 3))
results.append(("a single one divides nothing",
              waterways.banks_from_cuts([0]) == []))
results.append(("and the center is not a cut point: it does not touch the edge",
              waterways.banks_from_cuts([]) == []))

# --- 2. the center is clicked -------------------------------------------
clean()
center = hexgrid.hex_center(COORD[0], COORD[1], size, origin, orient)
neighbours = hexmap.snappable_points(center, size, origin, orient, columns, rows)
results.append(("in the middle of the hex the nearest point is its center",
              neighbours[0][2] == [(COORD, None)]))
vertex = hexgrid.vertices_of(COORD, size, origin, orient)[0]
above = hexmap.snappable_points(vertex, size, origin, orient, columns, rows)
results.append(("on a vertex the vertex remains",
              above[0][2] and all(k is not None for _c, k in above[0][2])))

# --- 3. a stretch ending at the center does not divide -------------------
mine = {}
click(mine, COORD, 0)
click(mine, COORD, None)
results.append(("a stretch from the vertex to the center does not divide the hex",
              A.campaign_banks(C).get(COORD) is None))
results.append(("and says so instead of pretending",
              "does not divide the hex" in told_ones[-1]))

# --- 4. vertex, center, vertex: it divides, and the drawing passes there --
clean()
mine = {}
click(mine, COORD, 0)
click(mine, COORD, None)
mine = {}
click(mine, COORD, None)
click(mine, COORD, 3)
groups = A.campaign_banks(C).get(COORD)
results.append(("closing on the other side the hex divides in two",
              groups == [[0, 1, 2], [3, 4, 5]]))
segments = A.bank_points(C).get(COORD) or []
results.append(("and the two drawn stretches stay written", len(segments) == 2))
results.append(("one of which ends at the center",
              any(waterways.node_from_text(x)[0] == waterways.CENTER
                  for s in segments for x in s)))

# The drawing follows what you drew, not the chord between the two vertices.
stretches = hexmap.bank_stretches({COORD: groups}, size, origin, orient,
                            segments={COORD: segments})
results.append(("the drawing is made of two stretches, not one",
              len(stretches) == 2))
cx, cy = center
results.append(("and they pass through the center",
              all(f"{cx:.1f} {cy:.1f}" in x for x in stretches)))

direct = hexmap.bank_stretches({COORD: groups}, size, origin, orient)
results.append(("without the drawing it would go back to the straight chord",
              len(direct) == 1))

# --- 5. the boat follows the drawing -------------------------------------
network = waterways.build({}, {COORD: groups}, orient,
                           {COORD: [tuple(s) for s in segments]})
results.append(("the network makes two lines, like the drawing, of two pieces each",
              len(network.parents) == 2 and len(network.arcs) == 4))
center_node = waterways.center_key(COORD)
results.append(("and the center is a node with two stretches",
              len(network.neighbours.get(center_node, [])) == 2))
ends = [n for n, v in network.neighbours.items() if len(v) == 1]
results.append(("from one end to the other one passes through the center",
              len(waterways.course(network, ends[0], ends[1]) or []) == 5
              and center_node in (waterways.course(network, ends[0], ends[1]) or [])))

# Without the drawing the network would go back to the single chord.
without = waterways.build({}, {COORD: groups}, orient)
results.append(("without a drawing the network makes a single line, the chord",
              len(without.parents) == 1 and len(without.arcs) == 4))

# --- 6. the same stretch is not added twice ------------------------------
mine = {}
before = len(A.bank_points(C).get(COORD) or [])
click(mine, COORD, None)
click(mine, COORD, 3)
results.append(("the same stretch twice does nothing",
              len(A.bank_points(C).get(COORD) or []) == before
              and "already there" in told_ones[-1]))

# --- 7. old rivers are not lost -------------------------------------------
# A hex marked before the center was a point has the shores but not the
# stretches: adding one must not erase what was seen.
clean()
A.set_banks(C, COORD, [[0, 1, 2], [3, 4, 5]])
results.append(("an old hex has no written stretches",
              A.bank_points(C).get(COORD) is None))
derived = hexmap.segments_of(COORD, orient)
results.append(("but they are derived from how it is divided", len(derived) == 1))
mine = {}
click(mine, COORD, 1)
click(mine, COORD, 4)
results.append(("and the new stretch adds to the old one",
              len(A.bank_points(C).get(COORD) or []) == 2
              and len(A.campaign_banks(C).get(COORD) or []) == 4))

# --- 8. the bridge is placed on the water, not on a point -----------------
# With the Bridge in hand no vertices nor the center are taken: the water
# line is clicked. On a dry point nothing is written.
center = hexgrid.hex_center(COORD[0], COORD[1], size, origin, orient)
A.set_banks(C, COORD, None)
results.append(("a bridge on a dry point is not placed",
              not hexmap._crossing_under(center, "bridge")
              and not A.campaign_crossings(C)))

clean()

# --- 9. the eraser removes one stretch at a time -------------------------
clean()
mine = {}
click(mine, COORD, 0)
click(mine, COORD, None)
mine = {}
click(mine, COORD, None)
click(mine, COORD, 3)
results.append(("two drawn stretches, two shores",
              len(A.bank_points(C).get(COORD) or []) == 2
              and len(A.campaign_banks(C).get(COORD) or []) == 2))

# The eraser passes over the first stretch: that one goes, not both.
first = hexmap.segment_stretches(
    COORD, A.bank_points(C)[COORD], size, origin, orient)[0]
vehicle = ((first[0][0] + first[1][0]) / 2, (first[0][1] + first[1][1]) / 2)
results.append(("the eraser finds something", hexmap._erase_under(vehicle) == 1))
results.append(("a single stretch remains",
              len(A.bank_points(C).get(COORD) or []) == 1))
results.append(("and the hex is no longer divided: a single stretch does not cut",
              A.campaign_banks(C).get(COORD) is None))

# Passing over it again that one goes too.
remaining_one = hexmap.segment_stretches(
    COORD, A.bank_points(C)[COORD], size, origin, orient)[0]
vehicle = ((remaining_one[0][0] + remaining_one[1][0]) / 2, (remaining_one[0][1] + remaining_one[1][1]) / 2)
hexmap._erase_under(vehicle)
results.append(("and passing over it again the hex is dry again",
              not A.bank_points(C).get(COORD)))

clean()

width = max(len(n) for n, _ in results)
for name, ok in results:
    print(("  ok  " if ok else " NO   ") + name.ljust(width))
print("")
print(str(sum(1 for _, ok in results if ok)) + "/" + str(len(results)) + " passate")
