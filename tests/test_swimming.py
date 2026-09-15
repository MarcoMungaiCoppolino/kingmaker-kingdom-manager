# -*- coding: utf-8 -*-
"""Whoever swims crosses the water, but walks on the land: the shores remain.

Swimming and sailing both pass the water, and for a while the app treated
them the same. They are not the same thing: a **boat** sits on the water, and
for it the shores do not exist — the river is the road; whoever **swims**
walks on the land like everybody and crosses where they need to.

The defect showed with the ruler. Treating swimming as a boat the hexagon
lost its shores, so the browser received **a single cell, at the center**:
the dragged arrow went back to hopping from one center to the next as in the
old model, while the confirmed journey — drawn on the shores — passed
elsewhere. Two arrows, two roads, and whoever dragged did not see the one
they would take.

Here the distinction is tested, and above all that the **numbers do not
move**: whoever swims pays today what they paid yesterday.
"""
from kingmaker.geometry import hexgrid, sections
from kingmaker.access import permissions
from kingmaker import travel as v
from kingmaker.state import STATE
from kingmaker.ui import hexmap, theme

theme.notify = lambda *a, **k: None
theme.mark_dirty = lambda *a, **k: None
theme.refresh_panels = lambda *a, **k: None
permissions.can = lambda *a, **k: True

A, C = STATE.archive, STATE.campaign
m = STATE.k["map"]
size = float(m["size"])
origin = (float(m["origin_x"]), float(m["origin_y"]))
orient = m["orientation"]
columns, map_rows = int(m["columns"]), int(m["rows"])
COORD = (9, 4)
GROUPS = [[0, 1, 2], [3, 4, 5]]
results = []


class Allowed:
    id, username, role = "check", "check", permissions.ADMIN
    active = True


theme.user = lambda: Allowed()


def clean():
    A.remove_lake(C)
    A.remove_crossings(C)
    for c in list(A.campaign_banks(C)):
        A.set_banks(C, c, None)
    for k in list(A.campaign_borders(C)):
        A.set_border(C, (k[0], k[1]), (k[2], k[3]), None)


def spot(bank, coord=COORD):
    faces = A.campaign_sections(C, orient).get(tuple(coord)) or ()
    return sections.section_spot(faces, bank) or (None, None)


def inside(coord):
    return 0 <= coord[0] < columns and 0 <= coord[1] < map_rows


clean()
A.set_banks(C, COORD, GROUPS)
banks = A.campaign_sections(C, orient)
water = A.campaign_water(C, orient)
results.append(("the scene is a hexagon cut into two shores",
              len(banks.get(COORD) or ()) == 2))

# Who leaves: a single one, planted on shore 0 of the cut hexagon.
char = STATE.characters()[0]
A.update_character(char["id"], hex_col=COORD[0], hex_row=COORD[1],
                       pos_x=spot(0)[0], pos_y=spot(0)[1],
                       swim_speed_m=0)
STATE.load()
PC_ID = char["id"]


def window(**extra):
    mine = {"travel_mode": "choose", "travel_pcs": [PC_ID],
           "forced_march": False, "aboard": False, "together": True,
           "player_preview": False, "travel_vehicle": None}
    mine.update(extra)
    return mine


def swim_the_mode(mode) -> bool:
    """Whether this way of crossing is swimming.

    With `getattr` and not with the direct attribute because the test must be
    able to run on the earlier code too, where swimming was not a thing
    distinct from sailing: there it must **fail**, not error out — a test
    that blows up does not say which piece was missing.
    """
    return bool(getattr(mode, "swims", False))


def mode_of(mine):
    chosen = [p for p in STATE.characters() if p["id"] in (mine["travel_pcs"] or [])]
    return hexmap._crossing(mine, chosen, hexmap._vehicles_in_play(),
                                   hexmap._current_view(mine),
                                   A.campaign_difficulty(C))


# --- 1. on dry feet: the river is a wall, and the shores are two ----------
mode = mode_of(window())
results.append(("whoever cannot swim does not cross", not mode.sail and not swim_the_mode(mode)))
results.append(("and sees the two shores", len(mode.banks.get(COORD) or ()) == 2))
dry_field = hexmap.travel_field(window())
dry_cells = [c for c in dry_field["cells"] if (c[0], c[1]) == COORD]
results.append(("the ruler sends them two cells", len(dry_cells) == 2))

# --- 2. with a Swim Speed: crosses, and the shores are there --------------
A.update_character(PC_ID, swim_speed_m=6)
STATE.load()
char = next(p for p in STATE.characters() if p["id"] == PC_ID)
results.append(("the Swim Speed is read", v.swim_speed(char) == 6))
results.append(("and on its own is enough to cross the water",
              v.party_swims([char])[0]))

mode = mode_of(window())
results.append(("whoever swims crosses", mode.sail and swim_the_mode(mode)))
# The defect: before, here the banks were empty, and the hexagon came back a single point.
results.append(("but the shores remain — it is not a boat",
              len(mode.banks.get(COORD) or ()) == 2))
results.append(("and the water is there, without closing anything",
              v.stretches_of(mode.banks, mode.water, COORD) == ()
              and v.stretches_of(banks, water, COORD) != ()))

# --- 3. the ruler points at the shores, like the confirmed arrow ----------
field = hexmap.travel_field(window())
my_ones = [c for c in field["cells"] if (c[0], c[1]) == COORD]
results.append(("the swimmer's ruler sends two cells, not one", len(my_ones) == 2))
results.append(("with two distinct points", len({(c[2], c[3]) for c in my_ones}) == 2))
expected = {(round(x, 1), round(y, 1)) for bank in range(2)
          for x, y in [hexmap.bank_point(COORD, bank, size, origin, orient, banks)]}
results.append(("and they are exactly the points drawn on",
              {(c[2], c[3]) for c in my_ones} == expected))
center = hexgrid.hex_center(COORD[0], COORD[1], size, origin, orient)
results.append(("neither of the two sits at the center of the hexagon",
              all(abs(c[2] - center[0]) + abs(c[3] - center[1]) > 1.0 for c in my_ones)))

# The two shores touch, for whoever swims: without this the arrow would go
# around the hexagon while the journey passes inside it.
numbers = [k for k, c in enumerate(field["cells"]) if (c[0], c[1]) == COORD]
results.append(("and for whoever swims they touch",
              len(numbers) == 2
              and numbers[1] in field["neighbours"][numbers[0]]
              and numbers[0] in field["neighbours"][numbers[1]]))
dry_ones = [k for k, c in enumerate(dry_field["cells"])
            if (c[0], c[1]) == COORD]
results.append(("while on dry feet they do not, which is the point of the river",
              len(dry_ones) == 2
              and dry_ones[1] not in dry_field["neighbours"][dry_ones[0]]))
results.append(("and passing from one to the other costs nothing more",
              not [1 for a, b, _c in (field.get("sides") or [])
                   if {a, b} == set(numbers)]))

# --- 4. the numbers do not move -----------------------------------------
# It is the test making the change acceptable: whoever swims must pay today
# what they paid yesterday, when for them the water simply did not exist.
old = v.cost_field(COORD, mode.cost_of, orient, inside,
                        passage=mode.passage, banks={}, departure_bank=0,
                        crossings={}, water={})
new = v.cost_field(COORD, mode.cost_of, orient, inside,
                      passage=mode.passage, banks=mode.banks, departure_bank=0,
                      crossings=mode.crossings, water=mode.water)
different = [c for c in set(old.costs) | set(new.costs)
           if abs(old.costs.get(c, -1) - new.costs.get(c, -1)) > 1e-9]
results.append(("reaches the same hexes as before",
              set(old.costs) == set(new.costs)))
results.append((f"and none of the {len(new.costs)} costs differently from before",
              not different))
if different:
    print("   (different: " + ", ".join(str(c) for c in sorted(different)[:6]) + ")")

# The way around the water is not paid: whoever swims hugs nothing.
neighbours = hexgrid.neighbours(COORD[0], COORD[1], orient)
this_side, beyond = tuple(neighbours[0]), tuple(neighbours[3])
rings = v.rings_on_course([this_side, COORD, beyond], mode.banks, mode.water,
                          mode.crossings, orient, mode.cost_of, 0)
results.append(("and pays no way around the river", not rings))
results.append(("where on foot one would not pass at all",
              v.inside_the_hex(COORD, 1, banks, water, {}, mode.cost_of,
                                 orient).get((0, 3)) is None))

# --- 5. the drawn arrow is no longer truncated --------------------------
# `nodes_on_course` retraces the road to know which shore it passes on: if the
# drawing's passages were fewer than the pathfinder's, the arrow would stop
# at the river and the rest would not be drawn.
drawing_shores = hexmap._shores_of(window())
course = [COORD, beyond]
nodes = v.nodes_on_course(course, drawing_shores.banks, drawing_shores.crossings,
                          orient, 0)
results.append(("the drawing reaches the end of the path",
              len(nodes) >= 2 and (nodes[-1][0], nodes[-1][1]) == beyond))
nodes_without = v.nodes_on_course(course, banks, A.campaign_crossings(C), orient, 0)
results.append(("while without swimming it would stop at the river",
              len(nodes_without) == 1))
points = hexmap.course_points(course, size, origin, orient,
                                 drawing_shores.banks, drawing_shores.crossings, 0)
results.append(("and the polyline has the elbow of the crossing",
              len(points) == len(nodes)))

# --- 6. a ford does not charge the toll to whoever swims -----------------
# Found by measuring on the real map: on a hexagon that **also** has a ford,
# bridge and swimming would join the same two shores, and whoever keeps the
# tolls in a dictionary per pair of cells — the ruler, in the browser —
# would keep only one, chosen by order. The ruler asked three activities for
# a crossing the server gave for free: the two arrows went back to not
# matching, which is precisely the defect we started from.
_hop = sections.hop_between_sides(banks[COORD], 0, 3)
A.set_crossing(C, COORD, _hop[0], _hop[1], kind="ford")
results.append(("the scene has a ford on the cut hexagon",
              any((x.get("kind") or "") == "ford"
                  for x in A.campaign_crossings(C).get(COORD) or ())))
ford_mode = mode_of(window())
ford_field = hexmap.travel_field(window())
its_ones = [k for k, c in enumerate(ford_field["cells"]) if (c[0], c[1]) == COORD]
results.append(("whoever swims passes from one to the other anyway",
              len(its_ones) == 2 and its_ones[1] in ford_field["neighbours"][its_ones[0]]))
results.append(("and the ruler does not charge them the ford's toll",
              not [1 for a, b, _c in (ford_field.get("sides") or [])
                   if {a, b} == set(its_ones)]))
inner = v.inner_on_course([COORD, beyond], ford_mode.banks,
                                ford_mode.crossings, orient, ford_mode.cost_of, 0)
results.append(("the plan says one swims across, not that one fords",
              inner.get(COORD, ("", 0))[0] == "swim"))
results.append(("and it costs nothing more",
              inner.get(COORD, ("", 1))[1] == 0))
# On dry feet the ford is paid, which is the point of the ford.
A.update_character(PC_ID, swim_speed_m=0)
STATE.load()
foot_mode = mode_of(window())
on_foot = v.inner_on_course([COORD, beyond], foot_mode.banks,
                                foot_mode.crossings, orient, foot_mode.cost_of, 0)
results.append(("while whoever cannot swim fords it, and pays it",
              on_foot.get(COORD, ("", 0))[0] == "ford"
              and on_foot.get(COORD, ("", 0))[1] > 0))
A.update_character(PC_ID, swim_speed_m=6)
STATE.load()
char = next(p for p in STATE.characters() if p["id"] == PC_ID)

# --- 7. the backwards field withstands the crossings --------------------
# Found as a consequence: `inverse_cost_field` — the one needed to choose where it
# pays to meet when the group leaves scattered — called the wrong function
# on the branch of the inner crossings, and blew up with a TypeError. With
# four bridge hexagons on the real map it happened rarely; for whoever
# swims, who crosses in every cut hexagon, it happens at the first meeting.
swim_mode = mode_of(window())
back = v.inverse_cost_field(beyond, swim_mode.cost_of, orient, inside,
                                 swim_mode.passage, swim_mode.banks,
                                 swim_mode.crossings)
results.append(("the backwards field is built without blowing up",
              len(back.costs) > 100))
results.append(("and reaches the two shores of the cut hexagon",
              all((COORD[0], COORD[1], k) in back.shore_costs
                  for k in range(2))))
with_bridge = v.inverse_cost_field(beyond, swim_mode.cost_of, orient, inside,
                                  swim_mode.passage, banks,
                                  A.campaign_crossings(C))
results.append(("and withstands the real crossings too",
              len(with_bridge.costs) > 100))

# --- 8. a boat stays a boat ----------------------------------------------
results.append(("whoever swims on foot is aboard nothing",
              not getattr(hexmap, "_aboard_by_water",
                          lambda *a: True)(window(), [char])))

A.update_character(PC_ID, swim_speed_m=0)

width = max(len(n) for n, _ in results)
print()
for name, ok in results:
    print(("  ok  " if ok else " NO   ") + name.ljust(width))
print(f"\n{sum(1 for _, ok in results if ok)}/{len(results)} passed")
