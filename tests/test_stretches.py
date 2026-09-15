"""The cost of a water journey: what is travelled is paid."""
import math

from kingmaker.geometry import waterways
from kingmaker import travel as v
from kingmaker.state import STATE
from kingmaker.ui import hexmap, theme

theme.notify = lambda *a, **k: None
theme.mark_dirty = lambda *a, **k: None

A, C = STATE.archive, STATE.campaign
m = STATE.k["map"]
size = float(m["size"])
origin = (float(m["origin_x"]), float(m["origin_y"]))
orient = m["orientation"]
columns, rows = int(m["columns"]), int(m["rows"])
results = []


def inside(c):
    return 0 <= c[0] < columns and 0 <= c[1] < rows


def clean():
    A.remove_lake(C)
    A.remove_currents(C)
    A.remove_crossings(C)
    for c in list(A.campaign_banks(C)):
        A.set_banks(C, c, None)
    for k in list(A.campaign_borders(C)):
        A.set_border(C, (k[0], k[1]), (k[2], k[3]), None)


# --- 1. what a stretch is worth -----------------------------------------
def arc(kind, lake=False):
    return waterways.Arc(a=("v", 0, 0, 0), b=("v", 0, 0, 3), kind=kind,
                         hexes=((0, 0),), length=1.0, lake=lake)


# A boat step is an atom side — a quarter — or a whole hexagon side, which is
# longer: a half. Four atom sides are a chord from side to side, that is one
# activity.
results.append(("a hexagon side is half a hexagon of road",
              v.stretch_cost(arc("edge"), "downstream") == 0.5))
results.append(("an atom side a quarter",
              v.stretch_cost(arc("piece"), "downstream") == 0.25))
results.append(("and going up doubles, whatever the shape",
              v.stretch_cost(arc("edge"), "upstream") == 1.0
              and v.stretch_cost(arc("piece"), "upstream") == 0.5))
# A stretch without a direction is water without a current: it is travelled
# both ways the same, and counts as open ground. It is the rule lakes need,
# where no line has a direction and none wants one.
results.append(("a stretch without a direction counts as open ground",
              v.stretch_cost(arc("piece"), None) == 0.25
              and v.stretch_cost(arc("edge"), None) == 0.5))
results.append(("and a piece of lake too",
              v.stretch_cost(arc("piece", lake=True), "lake") == 0.25))

# --- 2. a real river: the count is the sum of the stretches -------------
clean()
RIVER = [(9, 4), (10, 4), (11, 4)]
for c in RIVER:
    A.set_banks(C, c, [[0, 1, 2], [3, 4, 5]])
for a, b in zip(RIVER, RIVER[1:]):
    A.set_border(C, a, b, "water")
network = hexmap.waters_network()
kinds = sorted(x.kind for x in network.arcs.values())
results.append(("three cuts of four pieces and two sides",
              kinds == ["edge"] * 2 + ["piece"] * 12 and len(network.parents) == 5))

found_one = v.route_towards(network, {}, (9, 4), (11, 4), orient)
results.append(("the route reaches the end", found_one is not None))
course, directions, road, steps = found_one
plan = v.route_plan(road, steps, 7.5, "check")
# Without a direction every stretch counts as open ground: cut 1, edge 0.5.
is_expected = 0.0
for i in range(len(road) - 1):
    a = network.arc_between(road[i][0], road[i + 1][0])
    is_expected += v.stretch_cost(a, None)
results.append(("the plan adds up the travelled stretches",
              plan.total_cost == math.ceil(is_expected - 1e-9)))
results.append(("and the legs stay one per hexagon",
              [(t.col, t.row) for t in plan.waypoints] == course[1:]))

# Marking the current the count halves: downstream is open ground.
# The direction is written on the drawn lines, not on the pieces: it is
# they that have the current, and the pieces inherit it.
steps = waterways.course_stretches(network, [s[0] for s in road if s[0]])
A.set_currents(C, steps)
currents = A.campaign_currents(C)
_c, _v, road_down, steps_down = v.route_towards(network, currents, (9, 4),
                                                (11, 4), orient)
down = v.route_plan(road_down, steps_down, 7.5, "check")
results.append(("with the current marked, going down costs as before",
              down.total_cost == plan.total_cost))
# And going up it doubles instead: it is the only thing the direction changes.
backwards = {k: (b, a) for k, (a, b) in
                 ((k, (x[0], x[1])) for k, x in currents.items())}
su = v.route_towards(network, backwards, (9, 4), (11, 4), orient)
plan_on = v.route_plan(su[2], su[3], 7.5, "check")
results.append(("going up it costs twice",
              plan_on.total_cost > down.total_cost))
results.append(("and without a direction there is nothing left to warn about",
              not any("marked direction" in x for x in down.warnings)))

# --- 3. the ruler and the plan say the same number ----------------------
# It is the test that counts: the dragged arrow and the confirmed journey
# must tell the same journey, or one of the two is lying.
dists, _arcs = v.route_field(network, currents, (9, 4), orient,
                                 scale=hexmap.ROUTE_SCALE)
min_ = min(c for s, c in dists.items() if s[1] == (11, 4))
# The browser rounds like this: first it goes back to half activities —
# which is what a stretch is really worth — then up to the whole one. The
# pass through the half serves to remove the thousandths tie-breaker that
# keeps the paths in order: that dust, rounded up on its own, raised by a day
# a journey that did not cost it.
def like_the_ruler(scaled):
    return math.ceil(round(scaled / hexmap.ROUTE_SCALE * 4) / 4 - 1e-9)


results.append(("the ruler field and the plan give the same cost",
              like_the_ruler(min_) == down.total_cost))
results.append(("and the thousandths tie-breaker does not inflate the count",
              like_the_ruler(down.total_cost * hexmap.ROUTE_SCALE + 9)
              == down.total_cost))

# --- 4. a river on the edge no longer drives the count mad --------------
# Two hexagons attached with the water running on their edge: before, the
# cost depended on which of the two one claimed to have entered.
clean()
A.set_border(C, (9, 4), (10, 4), "water")
A.set_border(C, (10, 4), (11, 4), "water")
network = hexmap.waters_network()
one = v.route_towards(network, {}, (9, 4), (10, 4), orient)
results.append(("from one hexagon to the other along the edge one passes", one is not None))
if one:
    p1 = v.route_plan(one[2], one[3], 7.5, "check")
    results.append(("and it costs as much as the stretches travelled, not a hexagon",
                  p1.total_cost == math.ceil(
                      sum(v.stretch_cost(network.arc_between(one[2][i][0],
                                                       one[2][i + 1][0]), None)
                          for i in range(len(one[2]) - 1)) - 1e-9)))

clean()

# --- 5. the route ends where the arrow stopped --------------------------
# Inside the same hexagon the water points are more than one, and on an edge
# stretch there are two in different cells: without saying *where* the hand
# stopped, the server redid the route towards another end — and releasing
# the button a journey different from the one being looked at appeared.
clean()
for c in RIVER:
    A.set_banks(C, c, [[0, 1, 2], [3, 4, 5]])
for a, b in zip(RIVER, RIVER[1:]):
    A.set_border(C, a, b, "water")
network = hexmap.waters_network()
nodes = waterways.hex_nodes(network, (11, 4))
results.append(("the arrival hexagon has more than one water point", len(nodes) > 1))
finished_ones = set()
for node in nodes:
    found_one = v.route_towards(network, {}, (9, 4), (11, 4), orient,
                            arrival_node=node)
    if found_one is not None:
        finished_ones.add(found_one[2][-1][0])
results.append(("pointing at one the route ends on that one, not on another",
              finished_ones == set(nodes)))

# A point leading nowhere does not make everything fail: one falls back.
outside = waterways.vertex_key((2, 2), 0, orient)
results.append(("an unreachable point gives no route",
              v.route_towards(network, {}, (9, 4), (11, 4), orient,
                            arrival_node=outside) is None))
results.append(("but without the point the route is still there",
              v.route_towards(network, {}, (9, 4), (11, 4), orient) is not None))

clean()

# --- 6. the drawn road is worth more than the cheapest -------------------
# Whoever followed the river with a finger does not want to see it replaced
# by another costing one activity less: the hand-drawn one is retraced.
clean()
for c in RIVER:
    A.set_banks(C, c, [[0, 1, 2], [3, 4, 5]])
for a, b in zip(RIVER, RIVER[1:]):
    A.set_border(C, a, b, "water")
network = hexmap.waters_network()
economical = v.route_towards(network, {}, (9, 4), (11, 4), orient)
results.append(("the cheapest is there", economical is not None))
states = economical[2]
redone = v.route_along(network, {}, states, orient)
results.append(("retracing it the same one is obtained again",
              redone is not None and redone[0] == economical[0]
              and redone[3] == economical[3]))

# A road skipping a step is not a road: it is refused instead of guessing
# which one was meant.
if len(states) > 2:
    skipped = [states[0], states[2]] + list(states[3:])
    results.append(("a road with a hole is refused",
                  v.route_along(network, {}, skipped, orient) is None))
results.append(("and with a single point there is nothing to retrace",
              v.route_along(network, {}, states[:1], orient) is None))

# The points arriving from the browser become states: point and hexagon together.
size_ = float(m["size"])
origin__ = (float(m["origin_x"]), float(m["origin_y"]))
from_browser = [[*waterways.node_point(n, size_, origin__, orient), e[0], e[1]]
               for n, e in states]
results.append(("the browser's points come back as the same states",
              hexmap.statuses_from_points(network, from_browser, size_, origin__, orient)
              == states))
# What the ruler event carries goes through a check first, and the check must
# keep the hex: without it the drawn route was thrown away for the cheapest.
checked = hexmap._valid_points([list(p) for p in from_browser], with_hex=True)
results.append(("the check keeps point and hex together",
              [tuple(p) for p in checked] == [(round(p[0], 1), round(p[1], 1), p[2], p[3]) for p in from_browser]
              and hexmap.statuses_from_points(network, checked, size_, origin__, orient) == states))
results.append(("without the flag it keeps the point alone",
              all(len(p) == 2 for p in hexmap._valid_points([list(p) for p in from_browser]))))
results.append(("a hex outside the grid is dropped",
              hexmap._valid_points([[1.0, 2.0, 999, 3]], with_hex=True) == []))
results.append(("a point far from the water does not become a state",
              hexmap.statuses_from_points(network, [[5.0, 5.0, 2, 2]], size_, origin__,
                                     orient) == []))

# --- a river that merely touches the hexagon ------------------------------
# It enters from a vertex and stops at the center: it does not divide the
# hexagon into two shores, so it does not appear among the `banks`. For a
# while it was saved and invisible — you drew it, the app said «marked», and
# on the map there was nothing. And it was worse than a drawing defect: that
# stretch did not even enter the water network, so no boat passed there and
# no direction could be marked on it. On real maps a river brushing a hexagon
# exists.
clean()
TOUCH = (12, 6)
vehicle = [(waterways.node_text(waterways.vertex_key(TOUCH, 0, orient)),
          waterways.node_text(waterways.center_key(TOUCH)))]
A.set_banks(C, TOUCH, [], points=vehicle)
results.append(("a stretch that does not divide stays saved",
              A.bank_points(C).get(TOUCH) is not None))
results.append(("and makes no shores, rightly",
              A.campaign_banks(C).get(TOUCH) is None))
results.append(("but is drawn on the map",
              len(hexmap.bank_stretches(A.campaign_banks(C), size, origin, orient,
                                     None, A.bank_points(C))) == 1))
network_touches = hexmap.waters_network(lakes=[])
results.append(("and enters the water network",
              any(TOUCH in x.hexes for x in network_touches.arcs.values())))

# And the direction: it is marked on the stretch, and its arrow is drawn.
ends = waterways.node_from_text(vehicle[0][0]), waterways.node_from_text(vehicle[0][1])
A.set_currents(C, [(ends[0], ends[1])])


class OpenView:
    gm = True

    def can_see(self, *_a):
        return True


arrows = hexmap._svg_currents(OpenView(), A.campaign_borders(C),
                              A.campaign_banks(C), size, origin, orient)
results.append(("and a direction can be marked on it, with its arrow",
              bool(arrows.strip())))

clean()

width = max(len(n) for n, _ in results)
for name, ok in results:
    print(("  ok  " if ok else " NO   ") + name.ljust(width))
print("")
print(str(sum(1 for _, ok in results if ok)) + "/" + str(len(results)) + " passate")
