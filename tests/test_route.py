"""The water route: the river is followed, and going down costs less than going up."""
from kingmaker.geometry import waterways
from kingmaker import travel as v
from kingmaker.state import STATE
import helpers

A, C = STATE.archive, STATE.campaign
m = STATE.k["map"]
orient = m["orientation"]

results = []


def clean():
    A.remove_lake(C)
    A.remove_currents(C)
    for c in list(A.campaign_banks(C)):
        A.set_banks(C, c, None)
    for k in list(A.campaign_borders(C)):
        A.set_border(C, (k[0], k[1]), (k[2], k[3]), None)


# A river flowing down: it cuts 9,4, runs along the edge between 9,4 and 10,4, cuts 10,4.
clean()
GROUPS = [[0, 1, 2], [3, 4, 5]]
A.set_banks(C, (9, 4), GROUPS)
A.set_border(C, (9, 4), (10, 4), "water")
A.set_banks(C, (10, 4), GROUPS)
network = waterways.build(A.campaign_borders(C), A.campaign_banks(C), orient)
grades = {n: len(x) for n, x in network.neighbours.items()}
ends = sorted(n for n, how_many in grades.items() if how_many == 1)

# --- 1. from the water to the hexagons ----------------------------------
road = waterways.course(network, ends[0], ends[1])
course, directions, _states, _p = v.route_towards(network, {}, (9, 4), (10, 4), orient)
results.append(("the route touches the two hexes of the river, in order",
              course == [(9, 4), (10, 4)]))
results.append(("and only one is entered: the departure one is not paid",
              list(directions) == [(10, 4)]))
results.append(("without a marked direction the step stays unanswered",
              directions[(10, 4)] is None))

# The case the path between nodes only got wrong: two hexagons attached
# along the river share the vertices, and looking for «the nearest node»
# gave a zero-length path instead of the route.
in_reverse, _directions, _s, _p = v.route_towards(network, {}, (10, 4), (9, 4), orient)
results.append(("leaving from the other end one goes the other way",
              in_reverse == [(10, 4), (9, 4)]))

# --- 2. the direction decides the effort --------------------------------
mine = {}
steps = waterways.course_stretches(network, road)   # on the drawn lines
A.set_currents(C, steps)                       # goes down as it is travelled
currents = A.campaign_currents(C)
_course, directions, _s, _p = v.route_towards(network, currents, (9, 4), (10, 4), orient)
results.append(("with the current marked, one goes down", directions[(10, 4)] == "downstream"))
# And the same stretch, travelled backwards, is gone up. It is no longer
# checked on the return route: now that a stretch on the edge leads into
# both hexagons, the route may come back by another road — and if that one
# goes down, it goes down. What must hold is the rule, not the coincidence.
results.append(("and the same stretch, backwards, is gone up",
              helpers.course_directions(currents, list(reversed(road)), network)
              == ["upstream"] * (len(road) - 1)))

# --- 3. the plan: open downstream, difficult upstream -------------------
def waypoints(course):
    return [(c, STATE.hex(c[0], c[1]), None) for c in course[1:]]


down = v.plan_(waypoints([(9, 4), (10, 4)]), 7.5, "check", departure=(9, 4),
                  sail=True, directions={(10, 4): "downstream"})
on_plan = v.plan_(waypoints([(9, 4), (10, 4)]), 7.5, "check", departure=(9, 4),
                       sail=True, directions={(10, 4): "upstream"})
unknown_ = v.plan_(waypoints([(9, 4), (10, 4)]), 7.5, "check", departure=(9, 4),
                     sail=True, directions={(10, 4): None})
results.append(("going down costs one activity: open ground",
              down.total_cost == 1))
results.append(("going up costs two: difficult terrain",
              on_plan.total_cost == 2))
results.append(("and says so, because the wiki leaves the higher one open too",
              any("greater difficult" in a for a in on_plan.warnings)))
# A stretch without a direction is not a river nothing is known about: it is
# water without a current, travelled both ways the same. It costs like going
# down, and it is what is needed inside a lake.
results.append(("a stretch without a direction counts as open ground",
              unknown_.total_cost == down.total_cost))
without = v.current_category(None)
results.append(("and says so, instead of pretending there is a current",
              without.id == "open" and "without a current" in without.reason
              and without.from_table))

# The hexagon's terrain has nothing to do with it: by boat the swamp is not crossed.
hexagon = STATE.hex(10, 4)
terrains_before = list(hexagon.get("terrains") or [])
hexagon["terrains"] = ["swamp"]
swamp = v.plan_(waypoints([(9, 4), (10, 4)]), 7.5, "check", departure=(9, 4),
                     sail=True, directions={(10, 4): "downstream"})
on_foot = v.plan_(waypoints([(9, 4), (10, 4)]), 7.5, "check", departure=(9, 4))
results.append(("by boat the swamp is not crossed: it is hugged",
              swamp.total_cost == 1 and on_foot.total_cost == 3))
hexagon["terrains"] = terrains_before

# --- 4. where the river does not reach ----------------------------------
results.append(("a hexagon the water does not touch has no boardings",
              waterways.hex_nodes(network, (2, 2)) == []))
results.append(("and no route is made to it",
              v.route_towards(network, {}, (9, 4), (2, 2), orient) is None))
results.append(("while between two hexes on the river the route is there",
              v.route_towards(network, {}, (9, 4), (10, 4), orient) is not None))

# --- 5. swimming: one crosses, one does not sail ------------------------
swimmer = {"name": "Ondina", "swim_speed_m": 6.0}
on_foot_pcs = {"name": "Corin", "swim_speed_m": 0}
results.append(("whoever swims crosses the water on their own",
              v.party_sails([swimmer], {}, aboard=False)[0]))
results.append(("but one who cannot swim is enough and everybody stays ashore",
              not v.party_sails([swimmer, on_foot_pcs], {},
                                     aboard=False)[0]))
results.append(("and it says so by name",
              "Corin" in v.party_sails([swimmer, on_foot_pcs], {},
                                             aboard=False)[1]))

# --- 6. where a vehicle goes, according to the wiki ---------------------
results.append(("a rowboat is a water vehicle",
              v.kind_from_catalogue("barca_a_remi") == "water"))
results.append(("an airship flies", v.kind_from_catalogue("aeronave") == "air"))
results.append(("a wagon has no Speed written: the wiki does not say where it goes",
              v.kind_from_catalogue("wagon") is None))
results.append(("and so it stays in the stable until you say so",
              v.vehicle_kind({"vehicle": "wagon"}) == "land"))
results.append(("the Apparatus of the Octopus walks at 1.5 and swims at 12: it is a water vehicle",
              v.kind_from_catalogue("apparato_del_polipo") == "water"))
results.append(("what the table chooses wins over the catalogue",
              v.vehicle_kind({"vehicle": "barca_a_remi", "kind": "land"})
              == "land"))
results.append(("the water stops neither a boat nor whoever flies",
              v.crosses_water({"vehicle": "barca_a_remi"})
              and v.crosses_water({"vehicle": "aeronave"})
              and not v.crosses_water({"vehicle": "wagon"})))

clean()

# --- 7. the route as the panel builds it --------------------------------
from kingmaker.access import auth, view as view_mod
from kingmaker.ui import hexmap, theme

theme.notify = lambda *a, **k: None
theme.mark_dirty = lambda *a, **k: None

A.set_banks(C, (9, 4), GROUPS)
A.set_border(C, (9, 4), (10, 4), "water")
A.set_banks(C, (10, 4), GROUPS)
network = waterways.build(A.campaign_borders(C), A.campaign_banks(C), orient)
grades = {n: len(x) for n, x in network.neighbours.items()}
ends = sorted(n for n, q in grades.items() if q == 1)
road = waterways.course(network, ends[0], ends[1])
A.set_currents(C, [(road[i], road[i + 1])
                       for i in range(len(road) - 1)])

boat = {"id": "b1", "vehicle": "barca_a_remi", "name": "La Lontra",
         "available": 1, "seats": 6, "kind": "", "speed_m": None}
wagon = {"id": "c1", "vehicle": "wagon", "name": "Il Carro",
         "available": 1, "seats": 6, "kind": "land", "speed_m": 7.5}
vehicles = {"b1": boat, "c1": wagon}
pc = {"id": "p1", "name": "Ondina", "speed_m": 7.5, "speed_bonus_m": 0,
      "con_mod": 2, "hex_col": 9, "hex_row": 4, "bank": 0,
      "stable_id": "b1", "swim_speed_m": 0}
gm_row = next(r for r in A._conn.execute(
    "SELECT * FROM users WHERE role IN ('gm','admin')"))
gm = auth.User(id=gm_row["id"], username=gm_row["username"],
                 role=gm_row["role"], active=True, must_change_pw=False)
view = view_mod.MapView(gm, STATE)
difficulty = A.campaign_difficulty(C)

mine = {"aboard": True, "forced_march": False}
route = hexmap._route_by_river(mine, [pc], vehicles, view, difficulty,
                                (9, 4), (10, 4))
results.append(("with the group aboard a boat the route is there", route is not None))
if route:
    results.append(("and passes through the river's hexes",
                  route["path"] == [(9, 4), (10, 4)]))
    results.append(("going down, and so on open ground",
                  route["plan"].total_cost == 1))
    results.append(("and says with which boat", route["boat"] == "La Lontra"))

mine_ashore = {"aboard": False}
results.append(("without getting aboard the route is not offered",
              hexmap._route_by_river(mine_ashore, [pc], vehicles, view,
                                      difficulty, (9, 4), (10, 4)) is None))

wagon_col = dict(pc, stable_id="c1")
results.append(("with the wagon neither: a wagon does not go up a river",
              hexmap._route_by_river({"aboard": True}, [wagon_col], vehicles,
                                      view, difficulty, (9, 4), (10, 4))
              is None))
results.append(("and towards a hexagon the water does not touch there is no route",
              hexmap._route_by_river(mine, [pc], vehicles, view, difficulty,
                                      (9, 4), (2, 2)) is None))

# Without a marked direction the route exists all the same, but costs the worst count.
A.remove_currents(C)
in_the_dark = hexmap._route_by_river(mine, [pc], vehicles, view, difficulty,
                                  (9, 4), (10, 4))
results.append(("without a direction the route is still there, counted as going up",
              in_the_dark is not None and in_the_dark["without_direction"] >= 1
              and in_the_dark["plan"].total_cost >= route["plan"].total_cost))
results.append(("and writes it among the warnings",
              any("marked direction" in a for a in in_the_dark["plan"].warnings)))

clean()

# --- 8. the road the hand drew is the one kept ---------------------------
# The ruler sends the drawn junctions with the hex each was counted in. Two
# things used to throw them away: the payload check dropped the hex, and the
# field's adjacencies are symmetric while the server's steps are not — from
# a piece inside hex A one reaches the shared vertex counted in A, but the
# browser's cell for that vertex may be the one counted in B.
theme.user = lambda: gm
A.set_banks(C, (9, 4), GROUPS)
A.set_border(C, (9, 4), (10, 4), "water")
A.set_banks(C, (10, 4), GROUPS)
scene_boat = next(x for x in A.list_stable(C)
                  if v.vehicle_kind(x) == "water" and x.get("hex_col") is not None)
field_mine = {"travel_vehicle": scene_boat["id"], "travel_pcs": [], "aboard": True,
              "forced_march": False, "col": None, "row": None}
fld = hexmap.route_field(field_mine)
cells_w, nb_w, dists_w = fld["cells"], fld["neighbours"], fld["travellers"][0]["from"]
origin_w = fld["travellers"][0]["origin"]
import collections
parent_w = {origin_w: None}
queue_w = collections.deque([origin_w])
order_w = []
while queue_w:
    h = queue_w.popleft()
    order_w.append(h)
    for o in nb_w[h]:
        if o not in parent_w:
            parent_w[o] = h
            queue_w.append(o)

def hops_w(t):
    road = [t]
    while parent_w[road[-1]] is not None:
        road.append(parent_w[road[-1]])
    return list(reversed(road))

def cheapest_w(t):
    road = [t]
    while dists_w[road[-1]] not in (0, None):
        here = road[-1]
        road.append(next(o for o in nb_w[here]
                         if dists_w[o] is not None and dists_w[o] < dists_w[here]))
    return list(reversed(road))

drawn_w = next((hops_w(t) for t in order_w[1:]
                if dists_w[t] is not None and hops_w(t) != cheapest_w(t)), None)
results.append(("the scene offers a drawn road other than the cheapest", drawn_w is not None))
if drawn_w:
    sent = [[cells_w[i][2], cells_w[i][3], cells_w[i][0], cells_w[i][1]] for i in drawn_w]
    checked_w = hexmap._valid_points(sent, with_hex=True)
    kept = hexmap._route_by_river(
        field_mine, A.characters_on_vehicle(scene_boat["id"]),
        {x["id"]: x for x in A.list_stable(C)}, view, difficulty,
        (cells_w[drawn_w[0]][0], cells_w[drawn_w[0]][1]),
        (cells_w[drawn_w[-1]][0], cells_w[drawn_w[-1]][1]),
        boat=scene_boat, point=(cells_w[drawn_w[-1]][2], cells_w[drawn_w[-1]][3]),
        drawn_one=checked_w)
    size_w = float(STATE.k["map"]["size"])
    origin_px = (float(STATE.k["map"]["origin_x"]), float(STATE.k["map"]["origin_y"]))
    wanted_nodes = [n for n, _h in hexmap.statuses_from_points(
        hexmap.waters_network(), checked_w, size_w, origin_px, STATE.k["map"]["orientation"])]
    results.append(("the route keeps the junctions the hand drew, not the cheapest",
                  kept is not None and [n for n, _h in kept["statuses"]] == wanted_nodes))
    results.append(("and ends in the hex the hand counted",
                  kept is not None and kept["path"][-1] == (cells_w[drawn_w[-1]][0], cells_w[drawn_w[-1]][1])))

clean()

width = max(len(n) for n, _ in results)
for name, ok in results:
    print(("  ok  " if ok else " NO   ") + name.ljust(width))
print("")
print(str(sum(1 for _, ok in results if ok)) + "/" + str(len(results)) + " passate")
