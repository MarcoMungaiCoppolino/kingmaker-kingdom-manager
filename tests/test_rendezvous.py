# -*- coding: utf-8 -*-
"""Travelling together, with the shores: the rendezvous is a shore and one attaches to it.

The meeting point was a **hexagon**. In a hexagon cut by the water that is
not a place: the approach branches could arrive on the shore on this side
and the common road leave from the one beyond, without anybody having paid
the river. And even in a whole hexagon the two drawings did not touch: the
branch ended on the shore's point, the common road left from the markers'
anchor, half a radius lower.

Now the rendezvous is a **shore**: the meeting candidates are shores, every
branch arrives at that one, the common road leaves from it, and the drawing
attaches the branches at the point where the circle sits and the common road
begins.
"""
from kingmaker.geometry import hexgrid, sections
from kingmaker.access import permissions
from kingmaker import travel as v
from kingmaker.state import STATE
from kingmaker.ui import hexmap, theme
import helpers

theme.notify = lambda *a, **k: None
theme.mark_dirty = lambda *a, **k: None
theme.refresh_panels = lambda *a, **k: None
permissions.can = lambda *a, **k: True
helpers.silence("_redraw_travel", lambda *a, **k: None)
helpers.silence("_send_field", lambda *a, **k: None)

A, C = STATE.archive, STATE.campaign
m = STATE.k["map"]
size = float(m["size"])
origin = (float(m["origin_x"]), float(m["origin_y"]))
orient = m["orientation"]
columns, rows = int(m["columns"]), int(m["rows"])
results = []


class Allowed:
    id, username, role = "check", "check", permissions.ADMIN
    active = True


theme.user = lambda: Allowed()

# --- the scene: a river from vertex to vertex on (9,4), a bridge, and two
# leaving from opposite sides. The destination lies beyond. ---------------
COORD = (9, 4)
for c in list(A.campaign_banks(C)):
    A.set_banks(C, c, None)
for k in list(A.campaign_borders(C)):
    A.set_border(C, (k[0], k[1]), (k[2], k[3]), None)
A.remove_crossings(C)
A.set_banks(C, COORD, [[0, 1, 2], [3, 4, 5]])
banks = A.campaign_sections(C, orient)
faces = banks[COORD]
found = sections.hop_between_sides(faces, 0, 3)
A.set_crossing(C, COORD, found[0], found[1])
crossings = A.campaign_crossings(C)
water = A.campaign_water(C, orient)
vic = hexgrid.neighbours(COORD[0], COORD[1], orient)
for c in [COORD] + [tuple(x) for x in vic]:
    STATE.hex(c[0], c[1])["terrains"] = ["plains"]
THIS_SIDE, BEYOND = tuple(vic[0]), tuple(vic[3])       # shore 0 and shore 1
one, two = STATE.characters()[0], STATE.characters()[1]
before = {p["id"]: (p["hex_col"], p["hex_row"]) for p in (one, two)}
A.update_character(one["id"], hex_col=THIS_SIDE[0], hex_row=THIS_SIDE[1],
                       pos_x=None, pos_y=None)
A.update_character(two["id"], hex_col=BEYOND[0], hex_row=BEYOND[1],
                       pos_x=None, pos_y=None)
STATE.load()
difficulty = A.campaign_difficulty(C)
view = hexmap._current_view({"player_preview": False})


def inside(c):
    return 0 <= c[0] < columns and 0 <= c[1] < rows


def cost_of(c):
    return hexmap._cost_for(view, difficulty, c, False)


# --- 1. the meeting point is a shore -----------------------------------
# The destination is two steps beyond the shore on the far side: the natural
# rendezvous is the cut hexagon, and its shore is the one to continue from.
destination = tuple(hexgrid.neighbours(BEYOND[0], BEYOND[1], orient)[3])
STATE.hex(destination[0], destination[1])["terrains"] = ["plains"]
departures = {one["id"]: THIS_SIDE, two["id"]: BEYOND}
activities = {one["id"]: 1.0, two["id"]: 1.0}
rendezvous = v.rendezvous_point(departures, destination, activities, cost_of, orient, inside,
                           banks=banks, departure_banks={}, crossings=crossings, water=water)
results.append(("a meeting point is found", rendezvous is not None and rendezvous.point is not None))
results.append(("and it has a shore, not only a hexagon",
              rendezvous is not None and hasattr(rendezvous, "bank")
              and 0 <= rendezvous.bank < v.banks_of(banks, rendezvous.point)))
print(f"   (rendezvous on {rendezvous.point} shore {rendezvous.bank}, "
      f"{rendezvous.total_days:g} days)")

# --- 2. the branches all arrive on that shore ---------------------------
on_the_shore = 0
for char_id, course in rendezvous.approaches.items():
    if len(course) < 2:
        # Whoever is already in the rendezvous hexagon must already be on the shore.
        on_the_shore += 1
        continue
    departure_bank = 0
    course_shores = v.banks_on_course(course, banks, crossings, orient, departure_bank)
    if course_shores and course_shores[-1] == rendezvous.bank:
        on_the_shore += 1
results.append((f"every branch ends on the rendezvous shore "
              f"({on_the_shore}/{len(rendezvous.approaches)})",
              on_the_shore == len(rendezvous.approaches)))

# --- 3. the common road leaves from that shore -------------------------
common = rendezvous.common
results.append(("the common road begins at the rendezvous and ends at the destination",
              common and tuple(common[0]) == tuple(rendezvous.point)
              and tuple(common[-1]) == destination))
if len(common) > 1:
    from_shore = any(vic_ == tuple(common[1]) for _n, vic_ in v.steps_from(
        (rendezvous.point[0], rendezvous.point[1], rendezvous.bank), orient, banks))
    results.append(("and its first step leaves from the rendezvous shore, not "
                  "from the other", from_shore))

# --- 4. the drawing: the branches attach where the common road begins ---
mine = {"travel_pcs": [one["id"], two["id"]], "path": list(common),
       "branches": [list(c) for c in rendezvous.approaches.values() if len(c) > 1],
       "rendezvous": rendezvous, "singles": [], "plan": None, "nodes": (),
       "atom_stretches": {}, "arrival_pos": None}
shores = hexmap._shores_of(mine)
common_start = hexmap._polyline(common, size, origin, orient, shores)[0]
svg = hexmap._svg_branches(mine["branches"], rendezvous, size, origin, orient, shores)
attached = 0
for branch in mine["branches"]:
    # The last point of the branch, read from the real drawing.
    points = hexmap._polyline(branch, size, origin, orient, shores)
    points[-1] = hexmap.anchor_markers(tuple(rendezvous.point), rendezvous.bank, size,
                                        origin, orient, shores.banks)
    end = f"L{points[-1][0]:.1f} {points[-1][1]:.1f}"
    if end in svg and abs(points[-1][0] - common_start[0]) < 1e-6 \
            and abs(points[-1][1] - common_start[1]) < 1e-6:
        attached += 1
results.append((f"every drawn branch ends where the common road begins "
              f"({attached}/{len(mine['branches'])})",
              attached == len(mine["branches"]) and len(mine["branches"]) > 0))
results.append(("and the rendezvous circle sits at the same point",
              f'<circle cx="{common_start[0]:.1f}" cy="{common_start[1]:.1f}"' in svg))

# --- 5. the hand-drawn common road says the shore ------------------------
is_set = v.rendezvous_on(departures, [rendezvous.point] + list(common[1:]), activities,
                      cost_of, orient, inside, banks=banks, departure_banks={},
                      crossings=crossings, water=water, bank=rendezvous.bank)
results.append(("with the hand-drawn common road the rendezvous is the shore named",
              is_set is not None and is_set.bank == rendezvous.bank
              and is_set.point == rendezvous.point))
other_one = 1 - rendezvous.bank
set_other = v.rendezvous_on(departures, [rendezvous.point] + list(common[1:]),
                            activities, cost_of, orient, inside, banks=banks,
                            departure_banks={}, crossings=crossings, water=water, bank=other_one)
results.append(("and asking for the other shore the branches change accordingly",
              set_other is None or set_other.bank == other_one))

# --- 5bis. the rendezvous on a cut hexagon: whoever is beyond passes the bridge
# The drawn common road leaves from the cut hexagon, shore 1 (the far one):
# whoever is on this side must cross the bridge to get there, and their
# branch must end on that shore — not «in the hexagon», on the shore.
common_cut = [COORD, BEYOND, destination]
on_the_cut = v.rendezvous_on(departures, common_cut, activities, cost_of, orient,
                         inside, banks=banks, departure_banks={}, crossings=crossings,
                         water=water, bank=1)
results.append(("a rendezvous on the far shore of a cut hexagon is found",
              on_the_cut is not None and on_the_cut.point == COORD
              and on_the_cut.bank == 1))
if on_the_cut is not None:
    branch_one = on_the_cut.approaches[one["id"]]
    branch_two = on_the_cut.approaches[two["id"]]
    results.append(("whoever is on this side gets there by passing the bridge: the branch ends "
                  "on shore 1",
                  len(branch_one) >= 2
                  and v.banks_on_course(branch_one, banks, crossings, orient, 0)[-1] == 1))
    results.append(("and whoever is beyond gets there without crossing",
                  len(branch_two) >= 2
                  and v.banks_on_course(branch_two, banks, crossings, orient, 0)[-1] == 1))
    mine_t = {"travel_pcs": [one["id"], two["id"]], "path": list(common_cut),
             "branches": [list(c) for c in on_the_cut.approaches.values()],
             "rendezvous": on_the_cut, "singles": [], "plan": None, "nodes": (),
             "atom_stretches": {}, "arrival_pos": None}
    shores_t = hexmap._shores_of(mine_t)
    start_t = hexmap._polyline(common_cut, size, origin, orient, shores_t)[0]
    anchor_t = hexmap.anchor_markers(COORD, 1, size, origin, orient, shores_t.banks)
    results.append(("and the common road leaves from shore 1, not from 0",
                  abs(start_t[0] - anchor_t[0]) < 1e-6
                  and abs(start_t[1] - anchor_t[1]) < 1e-6))
    svg_t = hexmap._svg_branches(mine_t["branches"], on_the_cut, size, origin, orient, shores_t)
    # Every branch is two <path> — the dark shadow below and the line above —
    # so the attachment point appears twice per branch.
    results.append(("and the drawn branches attach there",
                  svg_t.count(f"L{anchor_t[0]:.1f} {anchor_t[1]:.1f}")
                  == 2 * len(mine_t["branches"]) and len(mine_t["branches"]) == 2))
    # With shore 0 asked for it is the other one who must pass the bridge.
    this_side = v.rendezvous_on(departures, common_cut, activities, cost_of, orient,
                         inside, banks=banks, departure_banks={}, crossings=crossings,
                         water=water, bank=0)
    results.append(("asking for shore 0, it is whoever is beyond who passes the bridge",
                  this_side is not None and this_side.bank == 0
                  and v.banks_on_course(this_side.approaches[two["id"]], banks,
                                         crossings, orient, 0)[-1] == 0))

# --- 5ter. the branches shown by the ruler are kept ---------------------
# At equal cost the roads are more than one: if the server recomputed the
# branches from scratch it could pick another, and on release the branch
# changed shape. A branch sent by the browser is kept, if it holds and ends
# on the right shore.
if on_the_cut is not None:
    branch_one = on_the_cut.approaches[one["id"]]
    # A different but valid branch: from THIS_SIDE one goes around the cut
    # hexagon and enters it from side 3, that is directly on shore 1 — one
    # more turn, but it is what «was seen». Consecutive neighbours touch.
    ring = [THIS_SIDE, tuple(vic[5]), tuple(vic[4]), BEYOND, COORD]
    if ring is not None:
        branch_col = v.rendezvous_on(departures, common_cut, activities, cost_of,
                               orient, inside, banks=banks, departure_banks={},
                               crossings=crossings, water=water, bank=1,
                               branches={one["id"]: ring})
        results.append(("a branch sent by the ruler is kept as it is",
                      branch_col is not None
                      and branch_col.approaches[one["id"]] == ring))
        results.append(("and the days do not change: the count is the fields'",
                      branch_col is not None
                      and abs(branch_col.total_days - on_the_cut.total_days) < 1e-9))
    # A branch ending elsewhere, or leaving from another place, is ignored.
    bent = v.rendezvous_on(departures, common_cut, activities, cost_of, orient,
                         inside, banks=banks, departure_banks={}, crossings=crossings,
                         water=water, bank=1,
                         branches={one["id"]: [THIS_SIDE, destination]})
    results.append(("a branch not ending at the rendezvous is ignored",
                  bent is not None
                  and bent.approaches[one["id"]] == branch_one))

# --- 5quater. the rendezvous is the destination: one departs, and the days show
# When it pays to meet directly at the destination the common road is zero
# long. The plan had no legs and was not «possible»: the days label vanished
# on release and «Depart» did not depart — while the ruler, during the drag,
# did show the days.
to_destination = v.rendezvous_point(departures, COORD, activities, cost_of, orient, inside,
                              banks=banks, departure_banks={}, crossings=crossings, water=water)
results.append(("with the destination one step from both, the rendezvous is the destination",
              to_destination is not None and to_destination.point == COORD
              and len(to_destination.common) == 1))
if to_destination is not None:
    plan_zero = v.plan_([], 7.5, "check", False, [0], {}, None, False,
                             None, None)
    plan_zero.forced_days = 2
    results.append(("a plan without a common road but with a meeting point is possible",
                  plan_zero.possible))
    mine_m = {"travel_pcs": [one["id"], two["id"]], "path": [COORD],
             "branches": [list(c) for c in to_destination.approaches.values()],
             "rendezvous": to_destination, "singles": [], "plan": plan_zero, "nodes": (),
             "atom_stretches": {}, "arrival_pos": None}
    svg_m = hexmap._svg_path([COORD], size, origin, orient, plan_zero,
                                 mine_m["branches"], to_destination, [], None,
                                 hexmap._shores_of(mine_m))
    results.append(("and the days label stays drawn on the rendezvous",
                  "2 days" in svg_m and "km-path" in svg_m))
    results.append(("«Depart» accepts a path of a single hexagon with the meeting point",
                  "at_meeting_point" in __import__("inspect").getsource(hexmap._parts)))

# --- 6. on the real map: the two real characters, a meeting point that attaches
A.update_character(one["id"], hex_col=before[one["id"]][0],
                       hex_row=before[one["id"]][1], pos_x=None, pos_y=None)
A.update_character(two["id"], hex_col=before[two["id"]][0],
                       hex_row=before[two["id"]][1], pos_x=None, pos_y=None)
STATE.load()

width = max(len(n) for n, _ in results)
print()
for name, ok in results:
    print(("  ok  " if ok else " NO   ") + name.ljust(width))
print(f"\n{sum(1 for _, ok in results if ok)}/{len(results)} passed")
