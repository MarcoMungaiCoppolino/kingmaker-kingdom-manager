"""The network of the watercourses: vertices have a single name, and the river closes."""
from kingmaker.geometry import waterways, hexgrid
from kingmaker.state import STATE
import helpers


results = []
m = STATE.k["map"]
size = float(m["size"])
origin = (float(m["origin_x"]), float(m["origin_y"]))
orient = m["orientation"]

# --- 1. a vertex has a single name --------------------------------------
COORD = (9, 4)
names = set()
for coord, k in waterways.vertex_owners(COORD, 0, orient):
    names.add(waterways.vertex_key(coord, k, orient))
results.append(("a vertex belongs to three hexes",
              len(waterways.vertex_owners(COORD, 0, orient)) == 3))
results.append(("and from all three it is named the same way", len(names) == 1))

# And the name really corresponds to the same point on the drawing.
points = set()
for coord, k in waterways.vertex_owners(COORD, 0, orient):
    x, y = hexgrid.vertices_of(coord, size, origin, orient)[k]
    points.add((round(x, 3), round(y, 3)))
results.append(("and the three draw it in the same place", len(points) == 1))

# It holds for every vertex of every parity, not only for this one.
bent_ones = 0
for col in range(4, 8):
    for row in range(4, 8):
        for k in range(6):
            is_expected = hexgrid.vertices_of((col, row), size, origin, orient)[k]
            key = waterways.vertex_key((col, row), k, orient)
            where = waterways.node_point(key, size, origin, orient)
            if abs(where[0] - is_expected[0]) > 0.01 or abs(where[1] - is_expected[1]) > 0.01:
                bent_ones += 1
results.append(("96 vertices on 16 hexes: none ends up elsewhere", bent_ones == 0))

# --- 2. the side and its two vertices -----------------------------------
neighbours = hexgrid.neighbours(COORD[0], COORD[1], orient)
ok_sides = True
for direction, near in enumerate(neighbours):
    k1, k2 = waterways.side_vertices(direction)
    side = hexgrid.shared_side(COORD, near, size, origin, orient)
    my_items = hexgrid.vertices_of(COORD, size, origin, orient)
    ends = {(round(my_items[k1][0], 1), round(my_items[k1][1], 1)),
            (round(my_items[k2][0], 1), round(my_items[k2][1], 1))}
    if ends != {(round(side[0][0], 1), round(side[0][1], 1)),
                (round(side[1][0], 1), round(side[1][1], 1))}:
        ok_sides = False
results.append(("the two vertices of a side are those drawing it", ok_sides))

# --- 3. the network closes -----------------------------------------------
# A river flowing down: it enters from a side of 9,4, cuts it, and leaves on
# the edge between 9,4 and the neighbour beyond side 3.
GROUPS = [[0, 1, 2], [3, 4, 5]]
borders = {(9, 4, 10, 4): {"kind": "water"}}
banks = {(9, 4): GROUPS}
network = waterways.build(borders, banks, orient)
# A cut from a vertex to the opposite one is **four** atom sides, a border a
# whole hexagon side: five pieces, two drawn lines.
results.append(("a border and a cut make five pieces, of two lines",
              len(network.arcs) == 5 and len(network.parents) == 2))
results.append(("the pieces of the cut know which hexagon they are in",
              [a.hexes for a in network.arcs.values() if a.kind == "piece"]
              == [((9, 4),)] * 4))
results.append(("the border knows which two hexes it divides",
              [set(a.hexes) for a in network.arcs.values() if a.kind == "edge"]
              == [{(9, 4), (10, 4)}]))

# Do the two stretches touch? The cut goes from vertex 0 to 3; the side
# between 9,4 and 10,4 has two vertices of 9,4 as ends. If they share one,
# the graph closes.
grades = {n: len(v) for n, v in network.neighbours.items()}
results.append(("and they touch: a single chain, with two ends",
              list(grades.values()).count(1) == 2 and max(grades.values()) == 2))

# --- 4. walking along the water -----------------------------------------
ends = [n for n, how_many in grades.items() if how_many == 1]
road = waterways.course(network, ends[0], ends[1])
results.append(("from one end to the other one passes, crossing by crossing",
              road is not None and len(road) == 6))
results.append(("and one does not pass towards a point that is not on the water",
              waterways.course(network, ends[0], ("v", 0, 0, 0)) is None))

# A detached stretch cannot be reached: the network makes up no bridges.
detached_one = waterways.build({(2, 2, 3, 2): {"kind": "water"},
                                (20, 10, 21, 10): {"kind": "water"}}, {}, orient)
nodes = sorted(detached_one.neighbours)
results.append(("two far stretches stay far",
              waterways.course(detached_one, nodes[0], nodes[-1]) is None))

# --- 5. the confluence passes through the center ------------------------
three = waterways.build({}, {(9, 4): [[0, 1], [2, 3], [4, 5]]}, orient)
results.append(("three shores make three spokes towards the center, two pieces each",
              len(three.arcs) == 6 and len(three.parents) == 3
              and all(a.kind == "piece" for a in three.arcs.values())))
center = waterways.center_key((9, 4))
results.append(("and the center holds them together", len(three.neighbours.get(center, [])) == 3))
ends_three = [n for n, v_ in three.neighbours.items() if len(v_) == 1]
results.append(("so from one branch to the other one passes",
              len(waterways.course(three, ends_three[0], ends_three[1]) or []) == 5))

# --- 6. the direction: going down and going up --------------------------
# The direction sits on the **drawn** line, and the pieces inherit it in the
# direction they are travelled.
first_piece = next(i for i in range(len(road) - 1)
                   if network.arc_between(road[i], road[i + 1]).kind == "piece")
one, two = road[first_piece], road[first_piece + 1]
arc_one = network.arc_between(one, two)
parent_ = arc_one.ends_direction(one, two)
currents = {waterways.text_key(*parent_): parent_}
results.append(("in the marked direction one goes down",
              waterways.step_direction(currents, one, two, arc_one) == "downstream"))
results.append(("the other way one goes up",
              waterways.step_direction(currents, two, one, arc_one) == "upstream"))
on_the_edge = next(i for i in range(len(road) - 1)
                 if network.arc_between(road[i], road[i + 1]).kind == "edge")
results.append(("where nobody said so nothing is made up",
              waterways.step_direction(currents, road[on_the_edge],
                                       road[on_the_edge + 1],
                                       network.arc_between(road[on_the_edge],
                                                     road[on_the_edge + 1])) is None))
directions = helpers.course_directions(currents, road, network)
results.append(("and the whole path says so step by step: four pieces "
              "downstream, the side without a direction",
              directions.count("downstream") == 4 and directions.count(None) == 1))

# The key of a stretch is the same from both directions: it is a single stretch.
results.append(("a stretch has a single name, from whichever side you look at it",
              waterways.text_key(one, two) == waterways.text_key(two, one)))
results.append(("and the name is read back",
              waterways.node_from_text(waterways.node_text(one)) == one))
results.append(("even that of a center",
              waterways.node_from_text(waterways.node_text(center)) == center))
results.append(("while a bent string does not become a node",
              waterways.node_from_text("boh") is None
              and waterways.node_from_text("v:1:2") is None))

# --- 7. the lengths come from the geometry ------------------------------
edge = [a for a in network.arcs.values() if a.kind == "edge"][0]
pieces = [a for a in network.arcs.values() if a.kind == "piece"]
results.append(("a side is as long as the radius", abs(edge.length - 1.0) < 1e-9))
results.append(("the four pieces of the cut make twice that",
              abs(sum(a.length for a in pieces) - 2.0) < 1e-9))

# --- 8. fords and bridges are water all the same ------------------------
mixed = waterways.build({(9, 4, 10, 4): {"kind": "ford"},
                             (9, 4, 9, 3): {"kind": "bridge"}}, {}, orient)
results.append(("a ford and a bridge remain river stretches",
              len(mixed.arcs) == 2 and len(mixed.parents) == 2))

# --- 9. the node nearest to the finger ----------------------------------
point = waterways.node_point(one, size, origin, orient)
results.append(("the finger on the vertex picks that vertex",
              waterways.nearest_node(network, point, size, origin, orient) == one))
results.append(("the finger far away picks nothing, if there is a threshold",
              waterways.nearest_node(network, (10.0, 10.0), size, origin, orient,
                                       threshold=size) is None))

width = max(len(n) for n, _ in results)
for name, ok in results:
    print(("  ok  " if ok else " NO   ") + name.ljust(width))
print(f"\n{sum(1 for _, ok in results if ok)}/{len(results)} passed")
