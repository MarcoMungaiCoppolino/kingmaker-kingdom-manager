# -*- coding: utf-8 -*-
"""One arrives **in the piece you aimed at**, and crossing the hex is paid.

Two defects that were the same thing seen from two sides.

The ruler let one aim at any piece of the arrival hex, but the journey only
knew «at 20,5»: whoever arrived stopped on the shore they entered from, and
the arrow seemed to correct itself as soon as you let go of the button. Now
the journey carries **a point** along, like markers and crossings, and
stopping across the water costs the piece of road it takes to get there.

And a step **inside** a hex cost zero, so in a hex with three shores and
three crossings one could circle forever without the count rising. Now it
costs **a quarter** of that hex — the same coin the server counts atoms with
— so four steps inside a hex make one activity. The ban on crossing twice,
which was the wrong remedy, is gone: with two chained crossings one reaches
even the piece not touching the side you entered from.
"""
from kingmaker.geometry import atoms, hexgrid, sections
from kingmaker.access import permissions
from kingmaker import travel as v
from kingmaker.state import STATE
from kingmaker.ui import hexmap, theme
import helpers

told_ones = []
theme.notify = lambda text, *a, **k: told_ones.append(str(text))
theme.mark_dirty = lambda *a, **k: None
theme.refresh_panels = lambda *a, **k: None
theme.save_and_refresh = lambda *a, **k: None
theme.save_and_refresh_panels = lambda *a, **k: None
permissions.can = lambda *a, **k: True
permissions.can_on_character = lambda *a, **k: True
helpers.silence("_redraw_travel", lambda *a, **k: None)
helpers.silence("_send_field", lambda *a, **k: None)

A, C = STATE.archive, STATE.campaign
m = STATE.k["map"]
size = float(m["size"])
origin = (float(m["origin_x"]), float(m["origin_y"]))
orient = m["orientation"]
COORD = (9, 4)
results = []


class Allowed:
    id, username, role = "check", "check", permissions.ADMIN
    active = True


theme.user = lambda: Allowed()

# --- the scene: a three-shore confluence, with two chained bridges ------
for c in list(A.campaign_banks(C)):
    A.set_banks(C, c, None)
A.remove_crossings(C)
for k in list(A.campaign_borders(C)):
    A.set_border(C, (k[0], k[1]), (k[2], k[3]), None)
A.set_banks(C, COORD, [[0, 1], [2, 3], [4, 5]])
banks = A.campaign_sections(C, orient)
faces = banks[COORD]
results.append(("three shores, one per pair of sides",
              [sorted(f.sides) for f in faces] == [[0, 1], [2, 3], [4, 5]]))

neighbours = hexgrid.neighbours(COORD[0], COORD[1], orient)
DA = tuple(neighbours[0])          # one enters from side 0, i.e. into shore 0
for c in (COORD, DA):
    STATE.hex(c[0], c[1])["terrains"] = ["plains"]


def put_crossings(pairs):
    A.remove_crossings(C)
    for side_a, side_b in pairs:
        found = sections.hop_between_sides(faces, side_a, side_b)
        if found:
            A.set_crossing(C, COORD, found[0], found[1])


# Shore 0 (sides 0,1) — shore 1 (sides 2,3) — shore 2 (sides 4,5).
# Two chained bridges: 0-1 and 1-2. From shore 0 to 2 two passages are needed.
put_crossings([(1, 2), (3, 4)])
crossings = A.campaign_crossings(C)
results.append(("and two crossings, chained", len(crossings.get(COORD) or ()) == 2))

node0 = (COORD[0], COORD[1], 0)
one_jump = [n for n, _v in v.inner_passages(node0, banks, crossings)]
results.append(("with one hop from shore 0 only shore 1 is reached",
              one_jump == [(COORD[0], COORD[1], 1)]))
# With `getattr` because the test must be able to run on the earlier code
# too, where a chain of crossings could not even be named: there it must
# **fail**, not error out.
jumps = getattr(v, "inner_jumps", lambda *a, **k: ())
chain = {n: len(c) for n, c in jumps(node0, banks, crossings)}
results.append(("with two, shore 2 too",
              chain.get((COORD[0], COORD[1], 2)) == 2))

# --- 1. the drawn course holds the chain --------------------------------
# Leaving by side 4 means leaving shore 2: entering by side 0 takes two
# crossings, and before it was forbidden.
exits_from = tuple(neighbours[4])
STATE.hex(exits_from[0], exits_from[1])["terrains"] = ["plains"]
difficulty = A.campaign_difficulty(C)
view = hexmap._current_view({"player_preview": False})
columns, map_rows = int(m["columns"]), int(m["rows"])


def inside(c):
    return 0 <= c[0] < columns and 0 <= c[1] < map_rows


def cost_of(c):
    return hexmap._cost_for(view, difficulty, c, False)


course = hexmap._valid_course([list(DA), list(COORD), list(exits_from)], DA,
                                 orient, inside, cost_of, None, banks, 0, crossings)
results.append(("a course using two crossings in a row is accepted",
              course == [DA, COORD, exits_from]))
inner = v.inner_on_course(course, banks, crossings, orient, cost_of, 0)
results.append(("and both crossings are counted",
              inner.get(COORD, ("", 0))[0] in ("bridge", "ford")))
nodes = v.nodes_on_course(course, banks, crossings, orient, 0)
inside_the_hex = [n for n in nodes if (n[0], n[1]) == COORD]
results.append(("and the arrow bends in all three shores",
              len(inside_the_hex) == 3))

# --- 2. a step inside the hex costs a quarter ---------------------------
cells = [[COORD[0], COORD[1], 0.0, 0.0, 0, 2, 0.0, 0.0],
         [COORD[0], COORD[1], 1.0, 0.0, 0, 2, 1.0, 0.0],
         [DA[0], DA[1], 9.0, 0.0, 0, 2, 9.0, 0.0]]
fake_neighbours = [[1, 2], [0], [0]]
fake_field = hexmap._ruler_field(fake_neighbours, [], cells, 0)
results.append(("the ruler charges a quarter for a step inside the hex",
              abs(fake_field[1] - 0.5) < 1e-9))
results.append(("and the whole hex to leave it", abs(fake_field[2] - 2) < 1e-9))

# --- 3. the journey arrives in the aimed piece --------------------------
char = STATE.characters()[0]
before = (char["hex_col"], char["hex_row"])
A.update_character(char["id"], hex_col=DA[0], hex_row=DA[1],
                       pos_x=None, pos_y=None)
STATE.load()


def window():
    return {"travel_mode": "choose", "travel_pcs": [char["id"]],
            "col": COORD[0], "row": COORD[1], "forced_march": False,
            "together": True, "aboard": False, "player_preview": False,
            "travel_vehicle": None, "plan": None, "path": [], "branches": [],
            "singles": [], "rendezvous": None, "route": None, "by_river": False,
            "land": None, "arrival_pos": None}


def tip(bank):
    """The pixel coordinates of that shore's point."""
    return hexmap.bank_point(COORD, bank, size, origin, orient, banks)


costs = {}
for bank in (0, 1, 2):
    mine = window()
    told_ones.clear()
    hexmap._compute_journey(mine, None, arrival_point=tip(bank))
    is_expected = sections.section_spot(faces, bank)
    near = (mine.get("arrival_pos") is not None
              and abs(mine["arrival_pos"][0] - is_expected[0]) < 1e-6
              and abs(mine["arrival_pos"][1] - is_expected[1]) < 1e-6)
    results.append((f"pointing at shore {bank}, the journey gets there", near))
    costs[bank] = mine["plan"].total_cost if mine.get("plan") else None
print("   (cost towards the three shores: "
      + ", ".join(f"{k}={costs[k]}" for k in sorted(costs)) + ")")
results.append(("stopping across the water costs more than stopping on this side",
              costs[0] is not None and costs[1] is not None
              and costs[2] is not None
              and costs[0] < costs[1] <= costs[2]))

# And the marker really ends up there.
mine = window()
hexmap._compute_journey(mine, None, arrival_point=tip(2))
try:
    hexmap.move_characters([char["id"]], COORD, DA,
                            where=mine.get("arrival_pos"))
except TypeError:
    # The earlier code did not know the arrival had a spot: the test must
    # fail on what follows, not stop here.
    hexmap.move_characters([char["id"]], COORD, DA)
STATE.load()
has_arrived = next(p for p in STATE.characters() if p["id"] == char["id"])
results.append(("and the marker stops on that shore, not the entry one",
              hexmap.section_of(has_arrived, banks) == 2))

# --- 3bis. the arrow after release is the one you drew -------------------
# The defect: the browser sent only the **hexes**, and in a hex with three
# bridges the shores are reached by several roads. The drawing rebuilt one —
# legitimate, but not yours — and on release the arrow changed shape. Now the
# browser sends **the shores** too, and the drawing uses those.
put_crossings([(1, 2), (3, 4), (5, 0)])       # all three: several roads possible
crossings = A.campaign_crossings(C)
A.update_character(char["id"], hex_col=DA[0], hex_row=DA[1],
                       pos_x=None, pos_y=None)
STATE.load()
field = hexmap.travel_field(window())
field_cells = field["cells"]
its_ones = [k for k, c in enumerate(field_cells) if (c[0], c[1]) == COORD]
origin_ = field["travellers"][0]["origin"]
results.append(("the cell says which shore it is too",
              len(field_cells[origin_]) > 8
              and [field_cells[k][8] for k in its_ones] == [0, 1, 2]))
exit_ = next(j for j in field["neighbours"][its_ones[2]]
              if tuple(field_cells[j][:2]) != COORD)
drawn_one = [origin_, its_ones[0], its_ones[1], its_ones[2], exit_]
traced_one = [[field_cells[k][0], field_cells[k][1]] for k in drawn_one]
hand_nodes = [[field_cells[k][0], field_cells[k][1], field_cells[k][8]]
             for k in drawn_one]
mine = window()
told_ones.clear()
hexmap._compute_journey(
    mine, None, traced_one,
    arrival_point=(field_cells[exit_][2], field_cells[exit_][3]),
    traced_nodes=hand_nodes)
results.append(("the drawn course is kept, without redoing it",
              not any("not valid" in x for x in told_ones)))
results.append(("and the shores the hand touched are kept",
              list(mine.get("nodes") or ()) == [tuple(x) for x in hand_nodes]))
# The arrow passes **through the atoms** the count crossed: it starts from the
# leaver's anchor, touches every atom of the road inside the cut hex, and ends
# on the point of the aimed shore, where the marker is placed.
shores = hexmap._shores_of(mine)
points = hexmap._polyline(mine["path"], size, origin, orient, shores, 0)
stretches = mine.get("atom_stretches") or {}
# Only waypoint 1 is a cut hex: the exit one is whole, and for whole hexes
# there are no atoms to count.
results.append(("the count says which atoms the road passes through",
              set(stretches) == {1} and len(stretches[1]) > 4))
pieces = atoms.atoms(orient)
cxq, cyq = hexgrid.hex_center(COORD[0], COORD[1], size, origin, orient)
inner_expected = [(round(cxq + pieces[a].point[0] * size),
                  round(cyq + pieces[a].point[1] * size)) for a in stretches[1]]
inner_seen = [(round(x), round(y)) for x, y in points
                if hexgrid.pixel_to_hex(x, y, size, origin, orient) == COORD]
results.append((f"and the arrow passes inside: {len(stretches[1])} atoms inside the hexagon",
              inner_seen[:len(inner_expected)] == inner_expected))
results.append(("starting from the leaver's anchor",
              (round(points[0][0]), round(points[0][1])) == tuple(
                  round(v) for v in hexmap.anchor_markers(
                      DA, 0, size, origin, orient, shores.banks))))
# And every atom crossed is a quarter: the hand-drawn road — through the
# middle shore, over two chained bridges — makes more of them than the
# straight one.
results.append(("the extra atoms of the hand-drawn road are paid",
              mine["plan"].total_cost > 4.5))
# And the count never rises above what the ruler had shown.
extra_sides = {(a, b): c for a, b, c in field["sides"]}
ruler_ = 0.0
for i in range(1, len(drawn_one)):
    from_, a_ = drawn_one[i - 1], drawn_one[i]
    same = ((field_cells[from_][0], field_cells[from_][1])
              == (field_cells[a_][0], field_cells[a_][1]))
    entry_here = field_cells[a_][5] or 0
    ruler_ += (entry_here / 4.0 if same else entry_here)         + extra_sides.get((from_, a_), 0)
# The earlier ruler counted a quarter per shore hop: another coin. Now it
# counts the atoms like the server, and the number is the same: bench
# `bench11` verifies it on the real JavaScript. Here we verify that the plan is
# the atom count, and no longer that one.
rings_here, _t = v.atom_count(mine["path"], shores.banks,
                                A.campaign_water(C, orient), shores.crossings,
                                orient, cost_of, mine.get("nodes"),
                                mine.get("arrival_pos"))
results.append((f"and the plan's count ({mine['plan'].total_cost}) is the one "
              f"by atoms, not the quarter per hop ({ruler_})",
              abs(mine["plan"].total_cost - (4 + sum(
                  x for x in rings_here.values() if x))) < 1e-9
              and mine["plan"].total_cost != ruler_))

# --- 3ter. one travels inside the hex one is in too ----------------------
# Before, a journey was at least two hexes: to change shore at home one had
# to leave and come back. Now the road from one shore to the other of the
# same hex is a journey, and costs the atoms it crosses.
home = sections.section_spot(faces, 0)
A.update_character(char["id"], hex_col=COORD[0], hex_row=COORD[1],
                       pos_x=home[0], pos_y=home[1])
STATE.load()
mine = window()
told_ones.clear()
hexmap._compute_journey(mine, None, [list(COORD), list(COORD)],
                        arrival_point=tip(2),
                        traced_nodes=[[COORD[0], COORD[1], 0],
                                        [COORD[0], COORD[1], 1],
                                        [COORD[0], COORD[1], 2]])
results.append(("from one shore to the other of the same hex is a journey",
              mine.get("plan") is not None and mine["plan"].possible
              and mine.get("path") == [COORD]))
# Eleven atoms to go from A to C through B, a quarter each after the first:
# two activities and a half. More than a whole hex, and rightly so: it is a
# long tour inside a hex cut in three.
results.append(("which costs the road, by atoms: 2½",
              mine.get("plan") is not None
              and abs(mine["plan"].total_cost - 2.5) < 1e-9))
results.append(("and is drawn from the anchor through the atoms to the arrival point",
              len(hexmap._polyline(mine["path"], size, origin, orient,
                                   hexmap._shores_of(mine), 0)) > 3))
results.append(("without invalid-course warnings",
              not any("not valid" in x for x in told_ones)))
# And the confirmed arrow is seen: before, the drawing looked at the row of
# hexes — a single one, hence nothing — and on release the arrow vanished.
svg_home = hexmap._svg_path(mine["path"], size, origin, orient,
                                mine.get("plan"), [], None, [], None,
                                hexmap._shores_of(mine))
results.append(("and the confirmed arrow stays drawn, with its tip",
              "km-path" in svg_home and svg_home.count("<path") >= 3))
print("   (journey inside the hexagon: %s activities)"
      % (mine["plan"].total_cost if mine.get("plan") else None))
hexmap.move_characters([char["id"]], COORD, None, where=mine.get("arrival_pos"))
STATE.load()
has_arrived = next(p for p in STATE.characters() if p["id"] == char["id"])
results.append(("and at the end one stands on the aimed shore",
              hexmap.section_of(has_arrived, banks) == 2))
A.update_character(char["id"], hex_col=DA[0], hex_row=DA[1],
                       pos_x=None, pos_y=None)
STATE.load()

# --- 4. where there is no way from here, one goes around ------------------
# Without any crossing the three shores do not talk from inside: but the
# shore beyond has its sides, and from those one enters. The right button
# looks for the road to the aimed **shore**, like the ruler, not to the hex:
# it goes around instead of stopping on the entry shore.
A.remove_crossings(C)
A.update_character(char["id"], hex_col=DA[0], hex_row=DA[1],
                       pos_x=None, pos_y=None)
STATE.load()
mine = window()
told_ones.clear()
hexmap._compute_journey(mine, None, arrival_point=tip(2))
results.append(("without crossings, aiming at the shore beyond is not an error",
              not any("cannot be reached" in x for x in told_ones)))
results.append(("the journey still ends in the aimed piece",
              mine.get("arrival_pos") is not None
              and abs(mine["arrival_pos"][0]
                      - sections.section_spot(faces, 2)[0]) < 1e-6))
ring_path = mine.get("path") or []
results.append(("going around: more than two hexes, and entering from a side "
              "of the aimed shore",
              len(ring_path) > 2
              and ring_path[-2] in [tuple(x) for x in neighbours]
              and neighbours.index(ring_path[-2]) in faces[2].sides))

A.update_character(char["id"], hex_col=before[0], hex_row=before[1],
                       pos_x=None, pos_y=None)
A.set_banks(C, COORD, None)

width = max(len(n) for n, _ in results)
print()
for name, ok in results:
    print(("  ok  " if ok else " NO   ") + name.ljust(width))
print(f"\n{sum(1 for _, ok in results if ok)}/{len(results)} passed")
