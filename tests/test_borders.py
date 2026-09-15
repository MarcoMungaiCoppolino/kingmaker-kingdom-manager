"""The side model: go around it, pass it by the bridge, pay it by the ford."""
from kingmaker.geometry import hexgrid
from kingmaker import travel as v

ORIENT = "pointy"
COLUMNS, ROWS = 12, 9


def inside(c):
    return 0 <= c[0] < COLUMNS and 0 <= c[1] < ROWS


def cost_of(_c):
    return 1                      # plains everywhere: only the side counts


def wall(column):
    """Every side between column `column` and the next, as water."""
    outside = {}
    for row in range(ROWS):
        for near in hexgrid.neighbours(column, row, ORIENT):
            if near[0] > column and inside(near):
                outside[hexgrid.border_key((column, row), near)] = {"kind": "water"}
    return outside


def passes(borders, sail=False):
    return lambda a, b: v.border_cost(a, b, borders, sail)


def cost(course, borders, sail=False):
    tot = sum(cost_of(c) for c in course[1:])
    for a, b in zip(course, course[1:]):
        tot += v.border_cost(a, b, borders, sail) or 0
    return tot


A, B = (2, 4), (8, 4)
results = []

# 1. without borders, the usual path
base = v.path(A, B, cost_of, ORIENT, inside)
results.append(("without borders: straight", len(base) == 7 and base[0] == A and base[-1] == B))

# 2. the wall crosses the whole map: no way through at all
everything = wall(5)
is_closed = v.path(A, B, cost_of, ORIENT, inside, passes(everything))
results.append(("full wall: no way", is_closed is None))

# 3. one side removed at the bottom: the path must exist and pass there
gap_ = dict(everything)
del gap_[hexgrid.border_key((5, 0), [n for n in hexgrid.neighbours(5, 0, ORIENT)
                                          if n[0] > 5 and inside(n)][0])]
opening = hexgrid.border_key((5, 0), [n for n in hexgrid.neighbours(5, 0, ORIENT)
                                           if n[0] > 5 and inside(n)][0])
ring = v.path(A, B, cost_of, ORIENT, inside, passes(gap_))
crosses = [hexgrid.border_key(a, b) for a, b in zip(ring, ring[1:])
              if hexgrid.border_key(a, b) in everything] if ring else []
results.append(("gap: lengthens the road and passes only there",
              ring is not None and len(ring) > len(base) and crosses == [opening]))

# 4. no side of the path is a closed border
results.append(("the path crosses no water",
              all(v.border_cost(a, b, gap_) is not None
                  for a, b in zip(ring, ring[1:]))))

# 5. bridge in place of the wall on the direct route: the earlier path is back
# the side of the direct route the wall really closes
straight_side = next(hexgrid.border_key(a, b) for a, b in zip(base, base[1:])
                   if hexgrid.border_key(a, b) in everything)
bridge = dict(everything)
bridge[straight_side] = {"kind": "bridge"}
with_bridge = v.path(A, B, cost_of, ORIENT, inside, passes(bridge))
results.append(("bridge: the direct route is back", with_bridge == base))

# 6. ford: same route, but one more activity
ford = dict(everything)
ford[straight_side] = {"kind": "ford"}
with_ford = v.path(A, B, cost_of, ORIENT, inside, passes(ford))
results.append(("ford: same route", with_ford == base))
results.append(("ford: costs 1 more",
              cost(with_ford, ford) == cost(base, {}) + 1))

# 7. the ford is worth it only as long as it costs less than the detour
results.append(("ford cheaper than the detour",
              cost(with_ford, ford) < cost(ring, gap_)))

# 8. a boat passes the wall as if it were not there
by_boat = v.path(A, B, cost_of, ORIENT, inside, passes(everything, sail=True))
results.append(("by boat: straight through", by_boat == base))

# 9. without marked borders, `passage` changes nothing at all
results.append(("empty table = the earlier map",
              v.path(A, B, cost_of, ORIENT, inside, passes({})) == base))

# 10. the reverse field sees the same wall as the forward field
forward = v.cost_field(A, cost_of, ORIENT, inside, passage=passes(everything))
back = v.inverse_cost_field(A, cost_of, ORIENT, inside, passes(everything))
results.append(("forward and reverse field: same reachable cells",
              set(forward.costs) == set(back.costs)))
results.append(("the wall really divides the map",
              all(c[0] <= 5 for c in forward.costs)))

# 11. rendezvous_on refuses a hand-drawn course crossing the water
through = v.path(A, B, cost_of, ORIENT, inside)
r = v.rendezvous_on({"x": (2, 2), "y": (2, 6)}, through, {"x": 1.0, "y": 1.0},
                cost_of, ORIENT, inside, passage=passes(everything))
results.append(("hand rendezvous on the water: refused", r is None))
r2 = v.rendezvous_on({"x": (2, 2), "y": (2, 6)}, through, {"x": 1.0, "y": 1.0},
                 cost_of, ORIENT, inside, passage=passes(bridge))
results.append(("hand rendezvous on the bridge: accepted", r2 is not None))

# 12. rendezvous_point does not propose a meeting point beyond the water
rad = v.rendezvous_point({"x": (1, 4), "y": (3, 4)}, B, {"x": 1.0, "y": 1.0},
                        cost_of, ORIENT, inside, passage=passes(everything))
results.append(("automatic rendezvous: nobody beyond the wall", rad is None))

width = max(len(n) for n, _ in results)
for name, ok in results:
    print(("  ok  " if ok else " NO   ") + name.ljust(width))
print()
print(f"{sum(1 for _, ok in results if ok)}/{len(results)} passed")
