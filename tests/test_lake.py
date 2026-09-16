"""The lake: what the lines enclose floods, and inside one sails freely."""
import time
import uuid

from kingmaker.geometry import waterways, hexgrid
from kingmaker.access import auth, permissions, view as view_mod
from kingmaker import travel as v
from kingmaker.state import STATE
from kingmaker.ui import hexmap, theme
import helpers

# In the test nobody is logged in: the permissions would answer «no» to
# everything, and what is checked here is the gesture, not who may do it.
permissions.can = lambda *a, **k: True

told_ones = []
theme.notify = lambda text, *a, **k: told_ones.append(text)
theme.mark_dirty = lambda *a, **k: None
theme.refresh_panels = lambda *a, **k: None
theme.save_and_refresh = lambda *a, **k: None

A, C = STATE.archive, STATE.campaign
m = STATE.k["map"]
orient = m["orientation"]
columns, rows = int(m["columns"]), int(m["rows"])
results = []

gm_row = next(r for r in A._conn.execute(
    "SELECT * FROM users WHERE role IN ('gm','admin')"))
gm_user = auth.User(id=gm_row["id"], username=gm_row["username"],
                        role=gm_row["role"], active=True,
                        must_change_pw=False)


def clean():
    A.remove_lake(C)
    A.remove_currents(C)
    for c in list(A.campaign_banks(C)):
        A.set_banks(C, c, None)
    for k in list(A.campaign_borders(C)):
        A.set_border(C, (k[0], k[1]), (k[2], k[3]), None)


def ring(center):
    """Encloses a hexagon with six water lines: the smallest lake there is."""
    for near in hexgrid.neighbours(center[0], center[1], orient):
        A.set_border(C, center, tuple(near), "water")


# --- 1. the outline, point by point -------------------------------------
clean()
ROW_LINE = [(9, 4), (10, 4), (11, 4)]
inner_row = set(ROW_LINE)
size = float(m["size"])
origin = (float(m["origin_x"]), float(m["origin_y"]))


def vertex(coord, k):
    """The name of vertex `k` of that hexagon, as the archive writes it."""
    return waterways.node_text(waterways.vertex_key(coord, k, orient))


def vertex_click(mine, coord, k):
    """A click exactly on a vertex, as the hand would do it."""
    point = hexgrid.vertices_of(coord, size, origin, orient)[k]
    hexmap._lake_point(mine, point)


# A loop enclosing the three hexagons in a row: the outline vertices are taken.
RING = [vertex((9, 4), k) for k in (2, 3, 4)] +        [vertex((11, 4), k) for k in (5, 0, 1)]
nodes = [waterways.node_from_text(x) for x in RING]
cells = waterways.cells_in_polygon(nodes, columns, rows, size, origin, orient)
results.append(("a closed shape contains the hexes sitting inside it",
              set(ROW_LINE) <= set(cells)))
results.append(("and not those outside", (9, 6) not in cells and (2, 2) not in cells))
results.append(("with fewer than three points there is no shape",
              waterways.cells_in_polygon(nodes[:2], columns, rows, size,
                                          origin, orient) == []))

# --- 2. the gesture: the outline is clicked and one returns to the first --
mine = {}
for text in RING:
    node = waterways.node_from_text(text)
    vertex_click(mine, (node[1], node[2]), node[3])
results.append(("the points pile up as you click",
              mine.get("lake_points") == RING))
results.append(("and before closing there is no lake yet",
              A.campaign_lakes(C) == []))

first = waterways.node_from_text(RING[0])
vertex_click(mine, (first[1], first[2]), first[3])
lakes = A.campaign_lakes(C)
results.append(("returning to the first point the shape closes", len(lakes) == 1))
results.append(("the lake keeps the outline, not only the hexes",
              lakes[0]["points"] == RING))
results.append(("and the hexes inside", set(ROW_LINE) <= set(lakes[0]["cells"])))
results.append(("the hand stays free for the next one",
              mine.get("lake_points") == [] and mine.get("lake_id") is None))

# The same point twice is not taken.
mine = {}
vertex_click(mine, (9, 4), 2)
vertex_click(mine, (9, 4), 3)
how_many = len(mine["lake_points"])
vertex_click(mine, (9, 4), 3)
results.append(("the same point is not taken twice",
              len(mine["lake_points"]) == how_many and "already there" in told_ones[-1]))

# Closing with fewer than three points does nothing.
mine = {"lake_points": [RING[0], RING[1]]}
before = len(A.campaign_lakes(C))
hexmap._close_lake(mine)
results.append(("with two points nothing closes",
              len(A.campaign_lakes(C)) == before
              and "three points" in told_ones[-1]))

# Picking a lake up again puts its points back in hand.
mine = {}
hexmap._edit_lake(mine, A.campaign_lakes(C)[0])
results.append(("a lake is picked up again with its points",
              mine.get("lake_points") == RING
              and mine.get("lake_id") == A.campaign_lakes(C)[0]["id"]))
hexmap._close_lake(mine)
results.append(("and closing it again a single one remains, not two",
              len(A.campaign_lakes(C)) == 1))

# Removing it leaves the lines where they were.
hexmap._delete_lake(mine, A.campaign_lakes(C)[0]["id"])
results.append(("the lake is removed", A.campaign_lakes(C) == []))

# --- 3. inside the lake one sails freely --------------------------------
clean()
for cell in ROW_LINE:
    for near in hexgrid.neighbours(cell[0], cell[1], orient):
        if tuple(near) not in inner_row:
            A.set_border(C, cell, tuple(near), "water")
A.set_lake(C, "l1", ROW_LINE, points=RING)
network = hexmap.waters_network()

route = v.route_towards(network, {}, (9, 4), (11, 4), orient)
results.append(("from one shore of the lake to the other one passes", route is not None))

# In the middle of the lake, and not only from shore to shore: the center of
# the middle cell is a point like the others, and one gets there.
in_between = v.route_towards(network, {}, (9, 4), (10, 4), orient,
                         arrival_node=waterways.center_key((10, 4)))
results.append(("and one also reaches the middle of the lake, not only the shore",
              in_between is not None
              and in_between[2][-1][0] == waterways.center_key((10, 4))))
if in_between:
    results.append(("sailing it as still water, with no direction to respect",
                  set(in_between[1].values()) <= {"lake"}))
    results.append(("and every step inside the lake is still water",
                  all(network.arc_between(in_between[2][i][0],
                                    in_between[2][i + 1][0]).lake
                      for i in range(len(in_between[2]) - 1))))

# But only **inside the drawn shape**: a cell belongs to the lake when its
# center does, and a cell on the shore has vertices outside the ring. Those
# are dry: no lake step reaches them, or the arrow left the water.
ring_frame = waterways.lake_frame({"points": RING}, size, origin, orient)
dry_vertices = sorted({waterways.vertex_key(cell, k, orient)
                       for cell in ROW_LINE for k in range(6)
                       if not (waterways._on_outline(*waterways.node_point(
                                   waterways.vertex_key(cell, k, orient), size, origin, orient),
                               ring_frame, size * 0.02)
                               or waterways._inside_ring(*waterways.node_point(
                                   waterways.vertex_key(cell, k, orient), size, origin, orient),
                               ring_frame))})
results.append(("a lake cell on the shore has vertices outside the ring", len(dry_vertices) > 0))
results.append(("and no lake step reaches them",
              not any(a.lake for n in dry_vertices
                      for _o, a in network.neighbours.get(n, ()))))

# A lake is a hexagon with **all** the lines: its 36 atom sides and its six
# sides are water, and every crossing — corners, center, the thirteen inner
# ones — is a point the boat stops on. So a lake is the same thing as a
# river, only denser.
lake_stretches = [a for a in network.arcs.values() if a.lake]
lake_points = sorted({n for a in lake_stretches for n in (a.a, a.b)})
centers = [n for n in lake_points if n[0] == waterways.CENTER]
results.append(("the lake's points include the centers of its cells",
              {(c[1], c[2]) for c in centers} == set(ROW_LINE)))
# The thirteen inner points are the center and twelve crossings: the center
# already has its name.
results.append(("and the inner crossings, twelve per cell besides the center",
              sum(1 for n in lake_points if n[0] == waterways.JUNCTION)
              == 12 * len(ROW_LINE)))
unreachable = [b for b in lake_points[1:]
                   if waterways.course(network, lake_points[0], b) is None]
results.append(("and from any one all the others are reached",
              unreachable == []))
results.append(("the lake's pieces are atom sides and hexagon sides",
              {a.kind for a in lake_stretches} == {"piece", "edge"}))
results.append(("and cost a quarter and half a hexagon, at open ground",
              all(v.stretch_cost(a, "lake") == (v.QUARTER_STRETCH if a.kind == "piece"
                                                else v.HALF_STRETCH)
                  for a in lake_stretches)))

# The mesh is not seen: a lake is recognised by its blue glaze, not by a
# cobweb of lines. The direction brush, which hooks the drawn lines, must not
# even find it.
_brush_r, _s, _o, _or = hexmap._network_and_geometry()
results.append(("the lake's mesh does not end up under the direction brush",
              not any(a.lake for a in _brush_r.arcs.values())))
svg_lake = hexmap._svg_lakes(None, A.campaign_lakes(C), size, origin, orient)
results.append(("and on the drawing the lake stays a glaze, not lines",
              svg_lake.count("<line") == 0))

plan = v.plan_([(c, STATE.hex(*c), None) for c in [(10, 4), (11, 4)]],
                    7.5, "check", departure=(9, 4), sail=True,
                    directions={(10, 4): "lake", (11, 4): "lake"})
results.append(("and costs like open ground: two cells, two activities",
              plan.total_cost == 2))
results.append(("without warnings about a current to go up",
              not any("upstream" in a for a in plan.warnings)))
results.append(("still water explains itself",
              "still water" in v.current_category("lake").reason))

# Without the lake marked the ring is water anyway and a boat can hug it —
# what the lake adds is the inside: the shore is gone around all the same,
# the center is not.
without_lake = hexmap.waters_network(lakes=[])
results.append(("without the lake the shore is hugged all the same",
              v.route_towards(without_lake, {}, (9, 4), (11, 4), orient)
              is not None))
results.append(("but the middle cannot be reached: there is no point",
              waterways.center_key((10, 4)) not in without_lake.neighbours))

# --- 4. the boat sits on the map ----------------------------------------
for x in A.list_stable(C):
    if x["vehicle"] == "barca_a_remi":
        A.delete_stable_vehicle(x["id"])
sid = uuid.uuid4().hex[:12]
A.create_stable_vehicle({"id": sid, "campaign_id": C, "vehicle": "barca_a_remi",
                       "name": "La Lontra", "available": 1, "speed_m": None,
                       "kind": "", "note": "",
                       "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                       "hex_col": None, "hex_row": None})
A.update_stable_vehicle(sid, seats=6)
pc = STATE.characters()[0]
A.update_character(pc["id"], stable_id=sid, hex_col=1, hex_row=1)

mine = {"place_vehicle": sid, "travel_mode": "place"}
helpers.silence("_redraw_travel", lambda *a, **k: None)
hexmap._place_vehicle(mine, None, (2, 2))
results.append(("a boat is not put where there is no water",
              A.stable_vehicle(sid)["hex_col"] is None
              and "no water" in told_ones[-1]))

mine = {"place_vehicle": sid, "travel_mode": "place"}
hexmap._place_vehicle(mine, None, (10, 4))
entry = A.stable_vehicle(sid)
results.append(("inside a lake it is, and stays there",
              (entry["hex_col"], entry["hex_row"]) == (10, 4)))
after = A.character(pc["id"])
results.append(("and whoever was aboard reaches it, instead of staying ashore",
              (after["hex_col"], after["hex_row"]) == (10, 4)))
results.append(("the mode switches itself off",
              mine.get("place_vehicle") is None))

results.append(("the boat is found by coordinate",
              [x["id"] for x in A.list_stable(C)
               if (x["hex_col"], x["hex_row"]) == (10, 4)] == [sid]))
results.append(("and where it is not, it is not found",
              not any((x["hex_col"], x["hex_row"]) == (2, 2)
                      for x in A.list_stable(C))))

# Taking it in hand takes whoever is aboard too.
mine = {}
hexmap._choose_vehicle(mine, None, entry)
results.append(("clicking it means travelling with it",
              mine.get("travel_vehicle") == sid))
results.append(("and whoever is aboard departs with it",
              mine.get("travel_pcs") == [pc["id"]] and mine.get("aboard")))
hexmap._choose_vehicle(mine, None, entry)
results.append(("clicking it again leaves it", mine.get("travel_vehicle") is None))

# Putting it back in the shed removes it from the map: whoever was aboard is
# set ashore, on foot — the boat was in a lake cell, so on the nearest
# neighbour with ground, never left in the water. Staying «on» a boat that is
# nowhere would be the ghost link one comes from.
hexmap._put_back_in_depot({}, None, sid)
results.append(("in the shed it vanishes from the map",
              A.stable_vehicle(sid)["hex_col"] is None))
_landed = A.character(pc["id"])
results.append(("but whoever was aboard is set ashore next to the lake",
              (_landed["hex_col"], _landed["hex_row"]) != (10, 4)
              and (_landed["hex_col"], _landed["hex_row"])
              in {tuple(n) for n in hexgrid.neighbours(10, 4, orient)}
              and _landed["pos_x"] is not None))
results.append(("and gets off, because the vehicle is no longer there",
              A.character(pc["id"])["stable_id"] is None))

A.delete_stable_vehicle(sid)
A.update_character(pc["id"], stable_id=None)
clean()

# --- 5. the ruler field: what the browser sees --------------------------
# The ruler draws the arrow on its own, while you drag, on the field the
# server sends it. The cells of that field are not hexagons but **water
# points**: it is the difference between an arrow hopping from one center to
# the next and one following the river.
for cell in ROW_LINE:
    for vic in hexgrid.neighbours(cell[0], cell[1], orient):
        if tuple(vic) not in inner_row:
            A.set_border(C, cell, tuple(vic), "water")
A.set_lake(C, "l1", ROW_LINE, points=RING)
A.set_banks(C, (11, 5), [[0, 1, 2], [3, 4, 5]])
A.set_border(C, (11, 5), (12, 5), "water")
A.set_banks(C, (12, 5), [[0, 1, 2], [3, 4, 5]])
network = hexmap.waters_network()
dists, arcs = v.route_field(network, {}, (9, 4), orient)
hexes = {s[1] for s in dists}
results.append(("the water field reaches the end of the river",
              (12, 5) in hexes))
results.append(("and does not touch dry land",
              (2, 2) not in hexes and (20, 15) not in hexes))
results.append(("the cells are water points, not hexes",
              any(s[0] is not None for s in dists)))
results.append(("and every step joins two real states",
              all(a in dists and b in dists for a, b in arcs)))

# The field and the route must say the same thing: they are the same journey,
# told once to the browser and once to the server.
route = v.route_towards(network, {}, (9, 4), (12, 5), orient)
plan = v.route_plan(route[2], route[3], 7.5, "check")
min_ = min(c for s, c in dists.items() if s[1] == (12, 5))
import math as _math
results.append(("the field and the route say the same cost",
              _math.ceil(min_ - 1e-9) == plan.total_cost))

# Inside the lake one passes at the cost of open ground; on a river without a
# direction one pays as if going upstream.
directions = {direction for (_a, _b), (_c, direction) in arcs.items()}
results.append(("between the lake's cells the step is still water", "lake" in directions))
results.append(("and on the river without a direction the step stays unanswered",
              None in directions))
results.append(("no step costs more than going upstream costs",
              max(c for c, _v in arcs.values())
              <= (v.current_cost("upstream")[0] or 0)))

# From a hexagon the water does not touch no field departs.
empty, _p = v.route_field(network, {}, (2, 2), orient)
results.append(("from dry land the field is empty", len(empty) == 0))

clean()

# --- 6. the boat is the traveller ---------------------------------------
# With a boat in hand the route is its own, and does not depend on who got
# aboard: an empty click on the map deselected the party and made the route
# of a boat still in the middle of the river vanish.
for cell in ROW_LINE:
    for vic in hexgrid.neighbours(cell[0], cell[1], orient):
        if tuple(vic) not in inner_row:
            A.set_border(C, cell, tuple(vic), "water")
A.set_lake(C, "l1", ROW_LINE, points=RING)
sid2 = uuid.uuid4().hex[:12]
A.create_stable_vehicle({"id": sid2, "campaign_id": C, "vehicle": "barca_a_remi",
                       "name": "La Rondine", "available": 1, "speed_m": None,
                       "kind": "", "note": "",
                       "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                       "hex_col": 9, "hex_row": 4})
A.update_stable_vehicle(sid2, seats=6)
boat = A.stable_vehicle(sid2)
gm_view = view_mod.MapView(gm_user, STATE)
diff = A.campaign_difficulty(C)
with_nobody = hexmap._route_by_river(
    {"aboard": True}, [], {sid2: boat}, gm_view, diff, (9, 4), (11, 4),
    boat=boat)
results.append(("with nobody chosen the boat's route is there all the same",
              with_nobody is not None))
results.append(("and passes through the lake",
              with_nobody and with_nobody["path"][-1] == (11, 4)))
without_boat = hexmap._route_by_river(
    {"aboard": True}, [], {sid2: boat}, gm_view, diff, (9, 4), (11, 4))
results.append(("while without a boat and without anybody there is no route",
              without_boat is None))
A.delete_stable_vehicle(sid2)
clean()

# --- 7. the boat moves with whoever is aboard ---------------------------
# A wagon has no position of its own: it sits where whoever drags it along
# sits. A boat has one, because it is in the middle of the river — and
# without moving it by hand whoever travelled by boat reached the destination
# while the boat stayed behind.
sid3 = uuid.uuid4().hex[:12]
A.create_stable_vehicle({"id": sid3, "campaign_id": C, "vehicle": "barca_a_remi",
                       "name": "La Cavedana", "available": 1,
                       "speed_m": None, "kind": "", "note": "",
                       "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                       "hex_col": 9, "hex_row": 4})
pc = STATE.characters()[0]
pcs_before = (pc["hex_col"], pc["hex_row"], pc.get("stable_id"))
A.update_character(pc["id"], stable_id=sid3, hex_col=9, hex_row=4)

# The boat is the journey's vehicle: without saying so, whoever arrives would
# have gone by land and the boat would have stayed in the water where it was
# (manual, 11.D.11).
hexmap.move_characters([pc["id"]], (11, 4), stable_id=sid3)
results.append(("whoever travels arrives",
              (lambda p: (p["hex_col"], p["hex_row"]))(
                  A.character(pc["id"])) == (11, 4)))
results.append(("and the boat gets there with them",
              (lambda v: (v["hex_col"], v["hex_row"]))(
                  A.stable_vehicle(sid3)) == (11, 4)))

# A vehicle that does not sit on the map is not put there by mistake.
sid4 = uuid.uuid4().hex[:12]
A.create_stable_vehicle({"id": sid4, "campaign_id": C, "vehicle": "wagon",
                       "name": "Il Carro", "available": 1, "speed_m": 7.5,
                       "kind": "land", "note": "",
                       "created_at": time.strftime("%Y-%m-%dT%H:%M:%S")})
A.update_character(pc["id"], stable_id=sid4)
hexmap.move_characters([pc["id"]], (12, 4))
results.append(("a wagon, which is not on the map, does not show up on it",
              A.stable_vehicle(sid4)["hex_col"] is None))

# And the boat moves even when nobody is aboard: it is its journey.
A.update_character(pc["id"], stable_id=None)
hexmap.move_characters([], (10, 4), stable_id=sid3)
results.append(("the empty boat goes where its journey goes",
              (lambda v: (v["hex_col"], v["hex_row"]))(
                  A.stable_vehicle(sid3)) == (10, 4)))

A.delete_stable_vehicle(sid3)
A.delete_stable_vehicle(sid4)
A.update_character(pc["id"], hex_col=pcs_before[0], hex_row=pcs_before[1],
                       stable_id=pcs_before[2])
clean()

width = max(len(n) for n, _ in results)
# --- the lake name sits above the water lines, below them while editing ----
A.set_lake(C, "l1", ROW_LINE, name="Mirror Lake", points=RING)
# a water line far from the lake, so there is something for the name to sit
# above or below
FAR = (14, 7)
A.set_border(C, FAR, tuple(hexgrid.neighbours(*FAR, orient)[0]), "water")
base_sel = {"show_borders": True, "col": None, "row": None, "show_icons": False}
reading = hexmap._svg_grid(dict(base_sel), gm_view)
editing = hexmap._svg_grid(dict(base_sel, water_mode=True), gm_view)
banks_mark = f'stroke="{hexmap.WATER_COLOR}"'
results.append(("the lake name is drawn", "Mirror Lake" in reading and "Mirror Lake" in editing))
results.append(("reading the map, the name comes after the water lines",
              banks_mark in reading and reading.rfind(banks_mark) < reading.find("Mirror Lake")))
results.append(("editing the water, the name comes before them",
              banks_mark in editing and editing.find("Mirror Lake") < editing.find(banks_mark)))
results.append(("hidden, it is gone",
              "Mirror Lake" not in hexmap._svg_grid(dict(base_sel, show_lake_names=False), gm_view)))

for name, ok in results:
    print(("  ok  " if ok else " NO   ") + name.ljust(width))
print("")
print(str(sum(1 for _, ok in results if ok)) + "/" + str(len(results)) + " passate")
