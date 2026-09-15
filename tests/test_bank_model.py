"""The case in the photo: one walks along the river, one does not cross it."""
from kingmaker.geometry import hexgrid
from kingmaker import travel as v

ORIENT = "pointy"
COLUMNS, ROWS = 9, 9


def inside(c):
    return 0 <= c[0] < COLUMNS and 0 <= c[1] < ROWS


def cost_of(_c):
    return 1


def size__(coord, north, sud):
    """The banks of a hex: two groups of directions."""
    return {coord: [sorted(north), sorted(sud)]}


results = []
D = hexgrid.neighbours(4, 4, ORIENT)          # the order of the directions

# A river flowing east-west across row 4: in every hex of that row the sides
# facing north are on one bank, those facing south on the other, and the two
# east/west sides — along the river — are... on both? No: on a single bank
# each would make no sense. A river entering from the west and leaving to
# the east leaves the west side and the east side *cut in half*; the model
# assigns them to the bank the sampling finds, and that is how one walks
# along the bank. Here we put both on the north bank: it is the «road on the
# shore» case.
def river_on_row(row, north_sides, south_sides):
    outside = {}
    for col in range(COLUMNS):
        outside[(col, row)] = [sorted(north_sides), sorted(south_sides)]
    return outside


# directions: 0=(1,-1,0) 1=(1,0,-1) 2=(0,1,-1) 3=(-1,1,0) 4=(-1,0,1) 5=(0,-1,1)
# for «pointy» odd-r: 0 = east, 3 = west; 1,2 lead up; 4,5 down
EAST, WEST = 0, 3
UP = [1, 2]
DOWN = [4, 5]

# The river crosses only columns 0..6: from 7 on the row is dry, so a way
# around exists — and it is the interesting case, not the total wall.
banks = {}
for col in range(7):
    banks[(col, 4)] = [sorted([EAST, WEST] + DOWN), sorted(UP)]

# --- 1. along the river one passes -----------------------------------------
c = v.path((1, 4), (6, 4), cost_of, ORIENT, inside, banks=banks)
results.append(("along the river one walks", c is not None and len(c) == 6))

# --- 2. from north to south through a river hex: no -----------------------
above = [n for n in hexgrid.neighbours(4, 4, ORIENT) if n[1] < 4][0]
below = [n for n in hexgrid.neighbours(4, 4, ORIENT) if n[1] > 4][0]
c = v.path(above, below, cost_of, ORIENT, inside, banks=banks)
cut_inside = c is not None and len(c) == 3 and (4, 4) in c
results.append(("from north to south one does not cut through the hex", not cut_inside))
results.append(("but a way around the river exists", c is not None and len(c) > 3))

# --- 3. one enters the river hex from both sides --------------------------
north_field = v.cost_field(above, cost_of, ORIENT, inside, banks=banks)
south_field = v.cost_field(below, cost_of, ORIENT, inside, banks=banks)
results.append(("from the north one enters", (4, 4) in north_field.costs))
results.append(("from the south one enters", (4, 4) in south_field.costs))
results.append(("and they are two different nodes",
              north_field.best_node((4, 4)) != south_field.best_node((4, 4))))

# --- 4. without banks, everything as before -------------------------------
base = v.path(above, below, cost_of, ORIENT, inside)
results.append(("without banks the course is the usual one",
              base is not None and len(base) == 3 and (4, 4) in base))

# --- 5. a bridge stitches the two banks back together ---------------------
with_bridge = dict(banks)
with_bridge[(4, 4)] = [sorted([EAST, WEST] + UP + DOWN)]     # a single bank
c = v.path(above, below, cost_of, ORIENT, inside, banks=with_bridge)
results.append(("with the bridge one cuts straight again",
              c is not None and (4, 4) in c and len(c) == 3))

# --- 6. the courses come out in hexes, not in nodes -----------------------
c = v.path((1, 4), (6, 4), cost_of, ORIENT, inside, banks=banks)
results.append(("the courses stay pairs of coordinates",
              all(isinstance(p, tuple) and len(p) == 2 for p in c)))

# --- 7. the rendezvous works with the banks -------------------------------
r = v.rendezvous_point({"a": (1, 4), "b": (6, 4)}, (3, 4), {"a": 1.0, "b": 1.0},
                      cost_of, ORIENT, inside, banks=banks)
results.append(("the rendezvous finds a point", r is not None and r.point is not None))
results.append(("and the common road is in hexes",
              r is not None and all(len(p) == 2 for p in r.common)))

# --- 8. the departure bank counts ----------------------------------------
# bank 0 = the one facing south (holds directions 4 and 5), bank 1 = north
south_bank = v.cost_field((4, 4), cost_of, ORIENT, inside, banks=banks,
                         departure_bank=0)
north_bank = v.cost_field((4, 4), cost_of, ORIENT, inside, banks=banks,
                          departure_bank=1)
results.append(("from the south bank the southern neighbour costs one step",
              south_bank.costs.get(below) == 1))
results.append(("from the north bank the northern neighbour costs one step",
              north_bank.costs.get(above) == 1))
results.append(("from the north bank the southern neighbour costs the detour, not one step",
              north_bank.costs.get(below, 99) > 1))
results.append(("from the south bank the northern neighbour costs the detour, not one step",
              south_bank.costs.get(above, 99) > 1))

width = max(len(n) for n, _ in results)
for name, ok in results:
    print(("  ok  " if ok else " NO   ") + name.ljust(width))
print(f"\n{sum(1 for _, ok in results if ok)}/{len(results)} passed")
