"""The same questions as the check, but on the real map (the copy).

It uses `_crossing`, that is exactly the function the app uses: if here the
path goes around the water, it goes around in the interface too.
"""
from kingmaker.geometry import hexgrid
from kingmaker.access import permissions, view as view_mod
from kingmaker import travel as v
from kingmaker.state import STATE
from kingmaker.ui import hexmap

CAMP = STATE.campaign
ARCH = STATE.archive


class Fake:
    id, username, role = "check", "check", permissions.ADMIN
    active = True


view = view_mod.MapView(Fake(), STATE)
difficulty = ARCH.campaign_difficulty(CAMP)
vehicles = {x["id"]: x for x in ARCH.list_stable(CAMP)}
by_id = {p["id"]: p for p in STATE.characters()}
m = STATE.k["map"]
ORIENT = m["orientation"]
COL, ROW_ = int(m["columns"]), int(m["rows"])


def inside(c):
    return 0 <= c[0] < COL and 0 <= c[1] < ROW_


def road(from_, a, mine, chosen):
    cost_of, passage, borders, sail = hexmap._crossing(
        mine, chosen, vehicles, view, difficulty)
    return v.path(from_, a, cost_of, ORIENT, inside, passage), sail


results = []
group = [p for p in by_id.values() if p["name"] in ("Corin", "Dagny")]
mine = {"aboard": False}

# --- 1. the usual route, without borders ----------------------------------
ARCH.replace_traced(CAMP, [])
for k in list(ARCH.campaign_borders(CAMP)):
    ARCH.set_border(CAMP, (k[0], k[1]), (k[2], k[3]), None)
DA, A = (18, 5), (20, 4)
base, _ = road(DA, A, mine, group)
results.append(("departure route exists", base is not None and base[0] == DA and base[-1] == A))
print("   base:", base)

# --- 2. water on a side of the route: it must go around -------------------
side = (base[1], base[2]) if len(base) > 2 else (base[0], base[1])
ARCH.set_border(CAMP, side[0], side[1], "water")
ring, _ = road(DA, A, mine, group)
print("   with water:", ring)
results.append(("with the water the route changes", ring != base))
results.append(("and no longer crosses that side",
              ring is None or all(hexgrid.border_key(a, b) != hexgrid.border_key(*side)
                                  for a, b in zip(ring, ring[1:]))))

# --- 3. bridge: the earlier route comes back ------------------------------
ARCH.set_border(CAMP, side[0], side[1], "bridge")
with_bridge, _ = road(DA, A, mine, group)
results.append(("with the bridge the earlier route comes back", with_bridge == base))

# --- 4. ford: same route, one more activity -------------------------------
ARCH.set_border(CAMP, side[0], side[1], "ford")
with_ford, _ = road(DA, A, mine, group)
# Not «the same route»: a ford costs one more activity, and on a real map it
# may happen that at that price another way around costs the same. What
# matters is that one still passes there — the ford opens, it does not close.
results.append(("with the ford one still passes there", with_ford is not None))
cfg = ARCH.campaign_borders(CAMP)
waypoints = [hexmap._waypoint_for(view, difficulty, c) for c in base[1:]]
plan_g = v.plan_(waypoints, 7.5, "check", False, [0], cfg, DA, False)
plan_0 = v.plan_(waypoints, 7.5, "check", False, [0], {}, DA, False)
print("   activities with the ford:", plan_g.total_cost, "without:", plan_0.total_cost)
results.append(("the ford costs one more activity",
              plan_g.total_cost == plan_0.total_cost + 1))
results.append(("and the plan says so",
              any("ford" in a.lower() for a in plan_g.warnings)))

# --- 5. the lake hexagon: on foot no, by boat yes -------------------------
ARCH.set_border(CAMP, side[0], side[1], None)
# The lake hexagon is searched for, not written by hand: this test runs on
# the real map, and the real map changes while playing. A fixed coordinate in
# here is a test that one day fails for an unrelated reason.
# A lake is a drawn shape, not a terrain: its cells come from the lakes table.
LAKE = next((tuple(c) for lake in ARCH.campaign_lakes(CAMP)
             for c in (lake.get("cells") or ())), None)
print("   lake hexagon under test:", LAKE)

boat = {"id": "barca1", "vehicle": "barca_a_remi", "name": "Barca",
         "kind": "water", "available": 1, "seats": 4, "speed_m": 9.0}
boat_vehicles = dict(vehicles, barca1=boat)
by_boat = [dict(p, stable_id="barca1") for p in group]
boat_cost, _p, _c, sail = hexmap._crossing(
    {"aboard": True}, by_boat, boat_vehicles, view, difficulty)
results.append(("the group in the boat sails", sail is True))
results.append(("by boat the lake hex can be entered",
              LAKE is None or boat_cost(LAKE) is not None))

# --- 6. a Water Border does not stop whoever is in a boat -----------------
ARCH.set_border(CAMP, side[0], side[1], "water")
_cost, boat_passage, _cf, _n = hexmap._crossing(
    {"aboard": True}, by_boat, boat_vehicles, view, difficulty)
_cost2, foot_passage, _cf2, _n2 = hexmap._crossing(
    mine, group, vehicles, view, difficulty)
results.append(("on foot the border is closed",
              foot_passage(side[0], side[1]) is None))
results.append(("by boat the border is passed",
              boat_passage(side[0], side[1]) == 0))

# --- 7. the hand-drawn path hopping over the water is refused -------------
ARCH.set_border(CAMP, side[0], side[1], "water")
cost_of, passage, _cf, _n = hexmap._crossing(mine, group, vehicles, view, difficulty)
results.append(("hand-drawn path over the water: refused",
              hexmap._valid_course(base, DA, ORIENT, inside, cost_of, passage) is None))
results.append(("the same path without borders: accepted",
              hexmap._valid_course(base, DA, ORIENT, inside, cost_of, None) is not None))

# --- 8. the drawing produces SVG, and the ruler payload has the sides -----
svg = hexmap._svg_borders(view, ARCH.campaign_borders(CAMP),
                          float(m["size"]),
                          (float(m["origin_x"]), float(m["origin_y"])), ORIENT)
results.append(("the border is drawn", "<path" in svg and hexmap.WATER_COLOR in svg))

# --- cleanup: the copy goes back without borders --------------------------
ARCH.set_border(CAMP, side[0], side[1], None)
results.append(("is_clean", ARCH.campaign_borders(CAMP) == {}))

width = max(len(n) for n, _ in results)
print()
for name, ok in results:
    print(("  ok  " if ok else " NO   ") + name.ljust(width))
print(f"\n{sum(1 for _, ok in results if ok)}/{len(results)} passed")
