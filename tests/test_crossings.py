"""Bridges and fords on the river crossing a hex, not on the edge between two."""
import inspect

from kingmaker.geometry import atoms, hexgrid, sections
from kingmaker import travel as v
from kingmaker.state import STATE
from kingmaker.ui import hexmap, theme
import helpers
from kingmaker.access import permissions
# The water brushes are the GM's: here they act.
permissions.can = lambda *a, **k: True

theme.notify = lambda *a, **k: None
theme.mark_dirty = lambda *a, **k: None

A, C = STATE.archive, STATE.campaign
m = STATE.k["map"]
size = float(m["size"])
origin = (float(m["origin_x"]), float(m["origin_y"]))
orient = m["orientation"]
columns, rows = int(m["columns"]), int(m["rows"])
results = []

COORD = (9, 4)
GROUPS = [[0, 1, 2], [3, 4, 5]]     # the river passes between side 2 and side 3


def faces_here(coord=COORD):
    return A.campaign_sections(C, orient).get(tuple(coord)) or ()


def bridge_on_sides(coord, side_a, side_b, **extra):
    """Places a crossing naming it by its sides, as was done before.

    Now a bridge is written with the point where it hops over; here it is
    translated, so the test keeps speaking the language it was written in.
    """
    found = sections.hop_between_sides(faces_here(coord), side_a, side_b)
    assert found is not None, (coord, side_a, side_b)
    return A.set_crossing(C, coord, found[0], found[1], **extra)


def joins(entry, coord=COORD):
    """Which two sections a crossing joins, now."""
    return sections.crossing_shores(faces_here(coord), entry.get("ends"))


def clean():
    A.remove_lake(C)
    A.remove_crossings(C)
    for c in list(A.campaign_banks(C)):
        A.set_banks(C, c, None)
    for k in list(A.campaign_borders(C)):
        A.set_border(C, (k[0], k[1]), (k[2], k[3]), None)


def inside(c):
    return 0 <= c[0] < columns and 0 <= c[1] < rows


def one(_c):
    return 1


def three(_c):
    return 3


# --- 1. the schema is there and is empty ---------------------------------
clean()
from kingmaker.storage import archive as _archive_mod
results.append((f"the database is at version {_archive_mod.SCHEMA_VERSION}",
              A._recorded_version() == _archive_mod.SCHEMA_VERSION))
results.append(("the crossings table is there and is empty",
              A.campaign_crossings(C) == {}))

# --- 2. the cut separates, the bridge rejoins -----------------------------
A.set_banks(C, COORD, GROUPS)
banks = A.campaign_sections(C, orient)   # the real sections, not the groups of sides
a = {d for _n, d in v.steps_from((COORD[0], COORD[1], 0), orient, banks)}
b = {d for _n, d in v.steps_from((COORD[0], COORD[1], 1), orient, banks)}
results.append(("without crossings the two shores do not talk", not (a & b)))
results.append(("and inner_passages offers nothing",
              list(v.inner_passages((COORD[0], COORD[1], 0), banks, {})) == []))

bridge_on_sides(COORD, 0, 3)      # side 0 on this side, side 3 beyond
crossings = A.campaign_crossings(C)
results.append(("the bridge is written",
              len(crossings.get(COORD, [])) == 1
              and joins(crossings[COORD][0]) == (0, 1)
              and crossings[COORD][0]["kind"] == "bridge"))
results.append(("from one shore it leads to the other",
              [n for n, _v in v.inner_passages((COORD[0], COORD[1], 0), banks, crossings)]
              == [(COORD[0], COORD[1], 1)]))
results.append(("and the other way round too",
              [n for n, _v in v.inner_passages((COORD[0], COORD[1], 1), banks, crossings)]
              == [(COORD[0], COORD[1], 0)]))

# --- 3. and the pathfinder passes through, without paying it -------------
neighbours = hexgrid.neighbours(COORD[0], COORD[1], orient)
from_here, beyond = tuple(neighbours[0]), tuple(neighbours[3])
without = v.path(from_here, beyond, one, orient, inside, None, banks, 0, None)
with_ = v.path(from_here, beyond, one, orient, inside, None, banks, 0, crossings)
results.append(("without the bridge one goes around the hex",
              without is not None and COORD not in without))
results.append(("with the bridge one passes inside", with_ is not None and COORD in with_))
results.append(("and it is shorter", with_ is not None and without is not None
              and len(with_) < len(without)))
results.append(("the bridge's hex appears once",
              with_ is not None and with_.count(COORD) == 1))
results.append(("the bridge costs no activities: three hexes, two entries",
              with_ == [from_here, COORD, beyond]))
results.append(("and does not count among the crossings to pay",
              v.inner_on_course(with_, banks, crossings, orient, one)[COORD]
              == ("bridge", 0)))

# --- 4. the ford: costs as much as that terrain ---------------------------
bridge_on_sides(COORD, 0, 3, kind="ford")
fords = A.campaign_crossings(C)
results.append(("the ford is written as such",
              fords[COORD][0]["kind"] == "ford"))
entry = fords[COORD][0]
results.append(("in a 1-activity terrain the ford costs 1",
              v.inner_cost(entry, COORD, one) == 1))
results.append(("in a 3-activity terrain it costs 3",
              v.inner_cost(entry, COORD, three) == 3))

bridge_on_sides(COORD, 0, 3, kind="ford", difficulty="greater_difficult")
is_forced = A.campaign_crossings(C)[COORD][0]
results.append(("with the difficulty forced by the GM that one counts",
              v.inner_cost(is_forced, COORD, one) == 3))
results.append(("and the GM can even make it easier than the terrain",
              v.inner_cost({"kind": "ford", "difficulty": "open"},
                              COORD, three) == 1))

bridge_on_sides(COORD, 0, 3, kind="ford")
fords = A.campaign_crossings(C)


def narrow(c):
    """A single one on the way to the ford, three all around: so the detour costs."""
    return 1 if tuple(c) in (from_here, COORD, beyond) else 3


course = v.path(from_here, beyond, narrow, orient, inside, None, banks, 0, fords)
results.append(("with the ford one passes all the same",
              course == [from_here, COORD, beyond]))
used_items = v.inner_on_course(course, banks, fords, orient, narrow)
results.append(("and the course knows it forded",
              used_items.get(COORD) == ("ford", 1)))

# The journey count notices: two entries plus the ford.
waypoints = [(c, {"terrains": ["plains"]}, None) for c in course[1:]]
without_ford = v.plan_(waypoints, 9.0)
with_ford = v.plan_(waypoints, 9.0, inner=used_items)
results.append(("the plan adds the ford's activity",
              with_ford.total_cost == without_ford.total_cost + 1))
results.append(("and says so, recalling the Athletics check",
              any("ford" in a and "Athletics" in a for a in with_ford.warnings)))
results.append(("the waypoint carries written that inside one fords",
              any(t.inner_one == "ford" and t.inner_cost == 1
                  for t in with_ford.waypoints)))

# Fording the river of the hex one leaves from: it is not a waypoint, it is paid.
at_departure = v.plan_(waypoints, 9.0, inner={from_here: ("ford", 2)})
results.append(("the ford of the departure hex enters the count too",
              at_departure.total_cost == without_ford.total_cost + 2))

# --- 5. the points and not the numbers: a second cut does not break it ----
# A bridge is remembered by two points, one per shore. A river drawn later
# renumbers the sections but does not move the points, and the bridge stays
# where it is.
bridge_on_sides(COORD, 0, 3)
crossings = A.campaign_crossings(C)
before = A.campaign_banks(C)[COORD]
groups_two = helpers.add_cut(before, 1, 5)
A.set_banks(C, COORD, groups_two)
banks_two = A.campaign_sections(C, orient)
results.append(("a second cut makes four shores", len(banks_two[COORD]) == 4))
joined = sections.crossing_shores(banks_two[COORD], crossings[COORD][0]["ends"])
results.append(("the bridge still joins two shores, and they are two different ones",
              joined is not None and joined[0] != joined[1]))
results.append(("and from one you really pass to the other",
              (COORD[0], COORD[1], joined[1])
              in [n for n, _v in v.inner_passages((COORD[0], COORD[1], joined[0]),
                                                    banks_two, crossings)]))

# The edge case, and its honest answer: a second river drawn **right under**
# the bridge. The two shores it joined end up in two opposite quarters, which
# touch only at the midpoint and not along a stretch: a bridge does not fit
# there, and that one stops crossing. With the old model it stayed, and
# joined two pieces that do not touch — it worked by describing something
# impossible.
A.set_banks(C, COORD, helpers.add_cut(before, 1, 4))
crossed = A.campaign_sections(C, orient)
results.append(("a river drawn under the bridge switches it off, and does not lie",
              sections.crossing_shores(crossed[COORD],
                                       crossings[COORD][0]["ends"]) is None))
A.set_banks(C, COORD, GROUPS)

# --- 6. the hand-drawn course ----------------------------------------------
A.set_banks(C, COORD, GROUPS)
banks = A.campaign_sections(C, orient)   # the real sections, not the groups of sides
by_hand = [from_here, COORD, beyond]
results.append(("by hand, without a crossing, the server refuses the hop",
              hexmap._valid_course(by_hand, from_here, orient, inside, one,
                                     None, banks, 0, None) is None))
results.append(("with the bridge it accepts it",
              hexmap._valid_course(by_hand, from_here, orient, inside, one,
                                     None, banks, 0, crossings) == by_hand))

# --- 6b. a course crossing itself ----------------------------------------
# The case that could not be done: one enters the cut hex from this side's
# shore, goes on, turns, and further on re-enters the **same hex** from the
# other shore. The hex «had already been used» and the server threw away the
# whole drawn course; now it is a road like the others, and every passage is
# paid.
return_ = [from_here, COORD, from_here, COORD]
revisited = hexmap._valid_course(return_, from_here, orient, inside, one,
                                   None, banks, 0, crossings)
results.append(("passing through the same hex again is allowed",
              revisited == return_))
results.append(("and the course stays as long as it was drawn",
              revisited is not None and len(revisited) == 4))

# The count adds up steps, not hexes: two passages cost twice.
def waypoints_of(course):
    return [(c, STATE.hex(*c), None) for c in course[1:]]


once = v.plan_(waypoints_of([from_here, COORD]), 9.0)
twice = v.plan_(waypoints_of(return_), 9.0)
results.append(("and passing twice costs twice",
              twice.total_cost > once.total_cost))
results.append(("with a waypoint for every passage, not one per hex",
              len(twice.waypoints) == 3))

# The real case, all together: the cut hex is crossed, one leaves, comes back
# in, and **only on the second visit** passes the bridge to leave by the other
# shore. It is the road the user could not draw.
bridge_col = [from_here, COORD, from_here, COORD, beyond]
results.append(("one comes back in and passes the bridge on the second visit",
              hexmap._valid_course(bridge_col, from_here, orient, inside, one,
                                     None, banks, 0, crossings) == bridge_col))
# Without the bridge that last step stays a shore hop, and is refused:
# passing again is allowed, hopping the river is not.
results.append(("but without the bridge the last step stays a hop",
              hexmap._valid_course(bridge_col, from_here, orient, inside, one,
                                     None, banks, 0, None) is None))

# --- 7. Bridge and Ford are placed by clicking the water -----------------
# Water is drawn between two points; Bridge and Ford are not: the water line
# to hop over is clicked, inside the hex or on the edge between two. The
# two-vertex gesture with the bridge in hand no longer exists — it stayed on
# as a fallback, and a stray click took a «first vertex» that meant nothing.
A.remove_crossings(C)
cuts = hexmap.cuts_of(COORD, GROUPS, size, origin, orient)
results.append(("the cut is drawn as a single segment", len(cuts) == 1))
(pa, pb, one_l, two_l) = cuts[0]
vehicle = ((pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2)
vertices = hexmap.vertices_of(COORD, size, origin, orient)


def draw(k1, k2, mine=None):
    """Two clicks on vertices `k1` and `k2` with Water in hand."""
    mine = {} if mine is None else mine
    hexmap._cut_hex(mine, vertices[k1])
    hexmap._cut_hex(mine, vertices[k2])
    return mine


results.append(("clicking the river with the Bridge in hand places a bridge",
              hexmap._crossing_under(vehicle, "bridge")))
crossings_here = A.campaign_crossings(C).get(COORD) or []
results.append(("and it is a bridge on the river, a single one",
              len(crossings_here) == 1 and crossings_here[0]["kind"] == "bridge"))
results.append(("and not one more water line",
              A.campaign_banks(C)[COORD] == GROUPS and not A.campaign_borders(C)))
results.append(("the bridge joins the two shores of the river it crossed",
              joins(crossings_here[0]) is not None))
results.append(("and one knows where to draw it",
              hexmap._bridge_span(COORD, faces_here(), crossings_here[0],
                                         size, origin, orient) is not None))

A.remove_crossings(C)
results.append(("with the Ford in hand, same click, a ford comes out",
              hexmap._crossing_under(vehicle, "ford")
              and (A.campaign_crossings(C).get(COORD) or [{}])[0].get("kind") == "ford"))
# The ford is drawn **along the water**, dotted — like the ford on the edge
# between two hexes — and not across like the bridge: the cross tick on the
# ford no longer exists.
ford_here = (A.campaign_crossings(C).get(COORD) or [{}])[0]
sign = hexmap._crossing_sign(COORD, faces_here(), ford_here,
                                           size, origin, orient)
results.append(("the ford is drawn along the water, not across",
              sign is not None
              and hexmap._dist_from_segment(sign[0], pa, pb) < 1.0
              and hexmap._dist_from_segment(sign[1], pa, pb) < 1.0))
svg_fords = hexmap._svg_inner_crossings(None, A.campaign_sections(C, orient),
                                      A.campaign_crossings(C), size, origin, orient)
results.append(("dotted, and without a glyph",
              'stroke-dasharray="0.1 ' in svg_fords and "🌉" not in svg_fords))

# On the edge: first the water between two hexes, then the click on the wet side.
A.remove_crossings(C)
draw(1, 2)
results.append(("Water between two neighbouring vertices stays a Water Border",
              len(A.campaign_borders(C)) == 1
              and list(A.campaign_borders(C).values())[0]["kind"] == "water"))
side = ((vertices[1][0] + vertices[2][0]) / 2, (vertices[1][1] + vertices[2][1]) / 2)
results.append(("clicking the wet side with the Bridge in hand it becomes an edge Bridge",
              hexmap._crossing_under(side, "bridge")
              and list(A.campaign_borders(C).values())[0]["kind"] == "bridge"
              and not A.campaign_crossings(C)))
results.append(("and with the Ford an edge Ford",
              hexmap._crossing_under(side, "ford")
              and list(A.campaign_borders(C).values())[0]["kind"] == "ford"))
for k in list(A.campaign_borders(C)):
    A.set_border(C, (k[0], k[1]), (k[2], k[3]), None)

# A bridge wants something to hop over: where there is no water the click
# writes nothing — and takes no vertex, because that gesture is Water's.
ELSEWHERE = (12, 6)
center_elsewhere = hexgrid.hex_center(ELSEWHERE[0], ELSEWHERE[1], size, origin,
                                           orient)
results.append(("on a hex without a river the bridge is not written",
              not hexmap._crossing_under(center_elsewhere, "bridge")
              and A.campaign_crossings(C).get(ELSEWHERE) is None
              and not A.campaign_borders(C)))
results.append(("and not even by mistake as a bank",
              A.campaign_banks(C).get(ELSEWHERE) is None))
results.append(("and the two-vertex gesture is Water's only",
              "kind" not in inspect.signature(hexmap._cut_hex).parameters
              and not hasattr(hexmap, "_attraversamento_disegnato")))
A.remove_crossings(C)

# --- 8. the eraser -----------------------------------------------------------
bridge_on_sides(COORD, one_l, two_l)
span = hexmap._bridge_span(
    COORD, faces_here(), (A.campaign_crossings(C).get(COORD) or [{}])[0],
    size, origin, orient)
results.append(("the bridge has a span to aim at", span is not None))
hexmap._erase_under(vehicle)
results.append(("the eraser on the bridge removes the bridge",
              not A.campaign_crossings(C) and COORD in A.campaign_banks(C)))
hexmap._erase_under(vehicle)
results.append(("passing over it again the river goes",
              COORD not in A.campaign_banks(C)))

A.set_banks(C, COORD, GROUPS)
bridge_on_sides(COORD, one_l, two_l)
hexmap._erase_under(vehicle)          # the bridge
hexmap._erase_under(vehicle)          # the river
results.append(("with the river erased no crossings over nothing remain",
              not A.campaign_crossings(C)))

# --- 9. the drawing -----------------------------------------------------------
A.set_banks(C, COORD, GROUPS)
bridge_on_sides(COORD, one_l, two_l)


class FullView:
    gm = True

    def can_see(self, *_a):
        return True


drawing = hexmap._svg_inner_crossings(FullView(), hexmap.sections_map(),
                                    A.campaign_crossings(C), size, origin, orient)
results.append(("the bridge is seen on the map", "🌉" in drawing))
bridge_on_sides(COORD, one_l, two_l, kind="ford")
drawn_ford = hexmap._svg_inner_crossings(FullView(), hexmap.sections_map(),
                                            A.campaign_crossings(C), size, origin,
                                            orient)
# The ford is the dashed line and no more: no glyph across the water, which
# on the drawing looked like a bandage on the river. It is the same language
# as the ford on the edge between two hexes.
results.append(("the ford is seen differently: dashed",
              "stroke-dasharray" in drawn_ford))
# The gap between one dash and the next must be measured net of the round
# caps: `stroke-linecap="round"` adds half a thickness per end, so with a gap
# as wide as the dash thickness nothing is left and the line reads solid. It
# is the reason the ford looked like a continuous line.
import re as _re
_m = _re.search(r'stroke-width="([0-9.]+)"[^>]*stroke-dasharray="([0-9.]+) ([0-9.]+)"',
                drawn_ford)
results.append(("the gap of the dashes is seen even with round caps",
              _m is not None and float(_m.group(3)) - float(_m.group(1)) > 1.0))
results.append(("and without any glyph on it",
              "〰️" not in drawn_ford
              and "🌉" not in drawn_ford))
results.append(("without crossings nothing is drawn",
              hexmap._svg_inner_crossings(FullView(), A.campaign_banks(C), {},
                                        size, origin, orient) == ""))

# --- 10. the field the ruler receives from the server --------------------
# Here the ruler died: a local variable named like the function `inside`
# shadowed it, `travel_field` raised an exception, and `_send_field`
# swallowed it at debug level. The browser kept the last good field and the
# drag stopped working without a line in the log. The test is that with a
# crossing inside a hex the field comes out *and is on*.
from kingmaker.access import auth, permissions  # noqa: E402

A.set_banks(C, COORD, GROUPS)
bridge_on_sides(COORD, one_l, two_l, kind="ford")
gm = next(auth.User(id=u["id"], username=u["username"], role=u["role"],
                      active=bool(u["active"]), must_change_pw=False)
          for u in A.list_users()
          if permissions.can(auth.User(id=u["id"], username=u["username"],
                                      role=u["role"], active=True,
                                      must_change_pw=False),
                          permissions.SEE_SECRETS))
theme.user = lambda: gm
who = next(p for p in A.list_characters(C)
           if p["hex_col"] is not None and p["hex_row"] is not None)
# The ruler is tested **from the hex next to** the cut one: from there this
# side's shore is one step away and the one beyond is reached only by
# crossing the bridge, which is the case this section is about. Starting from
# inside it would not work — both shores would sit at distance zero, and a
# cell at distance zero has no step it comes from — and starting from afar
# neither, because the other shore is reached by going around.
#
# It must be fixed: without it, it depended on where the save had left the
# first character, and another test was enough to move them so that the case
# was no longer that.
BESIDE = (10, 4)
where_was = (who["hex_col"], who["hex_row"], int(who.get("bank") or 0))
A.update_character(who["id"], hex_col=BESIDE[0], hex_row=BESIDE[1], bank=0)
who = A.character(who["id"])
mine = {"travel_mode": "choose", "travel_pcs": [who["id"]], "forced_march": False,
       "aboard": False, "together": True, "player_preview": False}
field = hexmap.travel_field(mine)
results.append(("the ruler field comes out on", field.get("active") is True))
results.append(("with almost every cell of the grid (lakes cannot be passed)",
              len(field.get("cells") or []) > columns * rows * 0.9))
indices = [i for i, c in enumerate(field["cells"])
          if (c[0], c[1]) == COORD]
results.append(("the cut hex has two cells", len(indices) == 2))
results.append(("and the ford joins them in the browser's graph",
              len(indices) == 2
              and indices[1] in field["neighbours"][indices[0]]
              and indices[0] in field["neighbours"][indices[1]]))
results.append(("with its cost among the sides",
              any(l[0] in indices and l[1] in indices and l[2] > 0
                  for l in field.get("sides") or [])))

# --- 11. the count of a step, as the ruler does it ------------------------
# The ruler redraws the arrow on its own while you drag, and to do so it walks
# backwards along the field: from where the mouse is it looks for a neighbour
# whose distance is exactly «mine minus what the step costs». If its count of
# a step is not the server's, at that step it finds nobody and stops: the
# arrow shows only the piece near the mouse, and the rest appears only on
# release — when the server answers.
#
# Here the browser's rule is redone in Python and checked to hold on
# **every** reachable cell. The bridge is the case that broke it: between the
# two banks of the same hex no new hex is entered, so the entry is not paid —
# and a bridge often does not even cost the crossing.
A.set_banks(C, COORD, GROUPS)
bridge_on_sides(COORD, one_l, two_l, kind="bridge")
field = hexmap.travel_field(mine)
cells = field["cells"]
extra = {(l[0], l[1]): l[2] for l in field.get("sides") or []}
indices = [i for i, c in enumerate(cells) if (c[0], c[1]) == COORD]
results.append(("with the bridge the cut hex still has two cells",
              len(indices) == 2))
results.append(("and the bridge costs nothing to cross",
              all((i, j) not in extra
                  for i in indices for j in indices if i != j)))


def same_hex(i, j):
    return (cells[i][0], cells[i][1]) == (cells[j][0], cells[j][1])


def right_step(from_, a_):
    """The new rule: inside the same hex **a quarter** is paid.

    A quarter and not zero: the hex is paid on entering, but passing from one
    shore to the other is still walking, and it is a quarter of a hex — the
    same coin the server counts atoms with. At zero one could circle inside a
    hex with three crossings without the count rising at all.
    """
    entry_ = cells[a_][5] or 0
    entrance = entry_ / 4.0 if same_hex(from_, a_) else entry_
    return entrance + extra.get((from_, a_), 0)


def old_step(from_, a_):
    """The earlier rule: the entry was always paid."""
    return (cells[a_][5] or 0) + extra.get((from_, a_), 0)


def orphans(step_cost):
    """The reachable cells for which the backwards course finds nobody."""
    from_where = field["travellers"][0]["from"]
    outside = []
    for j, dist in enumerate(from_where):
        if dist is None or dist == 0:
            continue
        found = False
        for i, neighbours_of_i in enumerate(field["neighbours"]):
            if j not in neighbours_of_i or from_where[i] is None:
                continue
            if from_where[i] + step_cost(i, j) == dist:
                found = True
                break
        if not found:
            outside.append(j)
    return outside


without_parent = orphans(right_step)
results.append(("with the right count every cell has a step it comes from",
              without_parent == []))
# And the proof the defect was there: with the earlier count someone stays
# orphaned, and it is precisely whoever is reached by passing the bridge.
old_items = orphans(old_step)
results.append(("with the earlier count instead someone stays orphaned",
              len(old_items) > 0))
results.append(("and they are cells of the bridge's hex, as said",
              any(i in indices for i in old_items)))

A.update_character(who["id"], hex_col=where_was[0], hex_row=where_was[1],
                       bank=where_was[2])
clean()

# --- 11. two crossings on the same river stay two -------------------------
# A bridge here and a ford further on join the **same** two shores: if the
# identity were only «which shores you join», the second would erase the
# first. It really happened, on a real map, and it is the reason a crossing
# is remembered also by **where it is**.
clean()
A.set_banks(C, COORD, GROUPS)
faces_two = faces_here()
corners_two = sections.unit_corners(orient)
here_ = sections.hop(faces_two, corners_two[1], corners_two[4])
stretch = sections.shared_edge(faces_two[0], faces_two[1])
further = ((stretch[0][0] * 0.75 + stretch[1][0] * 0.25),
             (stretch[0][1] * 0.75 + stretch[1][1] * 0.25))
A.set_crossing(C, COORD, here_[0], here_[1], kind="bridge")
A.set_crossing(C, COORD, here_[0], further, kind="ford")
two_entries = A.campaign_crossings(C).get(COORD) or []
results.append(("a bridge and a ford on the same river stay two",
              len(two_entries) == 2))
results.append(("and both join the same two shores",
              all(joins(x) == (0, 1) for x in two_entries)))
results.append(("but are drawn in two different places",
              len({hexmap._bridge_span(COORD, faces_two, x, size, origin,
                                              orient) for x in two_entries}) == 2))
# And putting an identical one back does not make a third.
A.set_crossing(C, COORD, here_[0], here_[1], kind="ford")
results.append(("putting the same crossing back does not create another",
              len(A.campaign_crossings(C).get(COORD) or []) == 2))
results.append(("but changes its kind",
              sorted(x["kind"] for x in A.campaign_crossings(C)[COORD])
              == ["ford", "ford"]))
clean()

# --- 12. with the Bridge in hand there is no hex to guess ------------------
# Two vertices may belong to more than one hex, and with the Bridge in hand
# one had to pick the one with the river under the chord — with two errors to
# explain when the chord ran along the water or sat on one side only. None of
# this exists any more: the bridge is placed by clicking the water, and the
# two-vertex gesture is Water's only, where there is nothing to choose.
results.append(("the choice of the hex for the bridge no longer exists",
              not hasattr(hexmap, "_dove_scavalca")
              and not hasattr(hexmap, "_perche_non_scavalca")))
clean()

# --- 13. the bridge is placed by clicking the water -----------------------
# It is the gesture that unblocks the real case: a hex where the river enters
# from one vertex and leaves from another. The two vertices the hand picks
# are the ends of the river, the chord between them runs **along** the water,
# and the two-vertex gesture refused with the river in plain sight. Clicking
# the water has no such problem.
clean()
A.set_banks(C, COORD, GROUPS)
click_faces = faces_here()
legs = sections.inner_sides(click_faces)
cx, cy = hexgrid.hex_center(COORD[0], COORD[1], size, origin, orient)
(pa, pb), _which_ones = legs[0]
on_the_water = (cx + (pa[0] + pb[0]) / 2 * size,
              cy + (pa[1] + pb[1]) / 2 * size)
results.append(("a click on the water places the bridge",
              hexmap._crossing_under(on_the_water, "bridge") is True))
placed = A.campaign_crossings(C).get(COORD) or []
results.append(("and it is a single one, between the right two shores",
              len(placed) == 1 and joins(placed[0]) == (0, 1)))
results.append(("with the Ford in hand a ford comes out",
              hexmap._crossing_under(on_the_water, "ford")
              and (A.campaign_crossings(C)[COORD][0]["kind"] == "ford")))
results.append(("and does not make a second: same water, same crossing",
              len(A.campaign_crossings(C).get(COORD) or []) == 1))
A.remove_crossings(C, COORD)
far = hexgrid.hex_center(COORD[0], COORD[1] + 3, size, origin, orient)
results.append(("far from the water it does nothing, and lets the other gesture be tried",
              hexmap._crossing_under(far, "bridge") is False))

# And on a wet side between two hexes the same click changes the border.
wet_neighbour = tuple(hexgrid.neighbours(COORD[0], COORD[1], orient)[0])
A.set_border(C, COORD, wet_neighbour, "water")
edge = hexgrid.shared_side(COORD, wet_neighbour, size, origin, orient)
on_edge = ((edge[0][0] + edge[1][0]) / 2, (edge[0][1] + edge[1][1]) / 2)
results.append(("a click on a wet side makes it an edge Bridge",
              hexmap._crossing_under(on_edge, "bridge")
              and A.campaign_borders(C)[
                  hexgrid.border_key(COORD, wet_neighbour)]["kind"] == "bridge"))

# The seams: seen where a river is made of several legs, not elsewhere.
class OpenView:
    gm = True

    def can_see(self, *_a):
        return True


one_leg = hexmap._svg_seams(OpenView(), {COORD: click_faces}, size,
                                  origin, orient)
results.append(("a river of a single piece has no seams", one_leg == ""))
A.set_banks(C, COORD, helpers.add_cut(GROUPS, 1, 4))
three = hexmap._svg_seams(OpenView(), hexmap.sections_map(), size, origin,
                           orient)
results.append(("two rivers crossing each other have the seam",
              three.count("M") >= 1))
clean()

# --- 14. the bridge opens its stretch, the ford the whole line -------------
# They are two different things and must be priced differently: a bridge is
# where it was built — four kilometres on a twenty-one-kilometre hex — while a
# shallow river is forded wherever, and every passage costs that terrain's
# cost.
clean()
A.set_banks(C, COORD, GROUPS)
water_here = A.campaign_water(C, orient)
banks_here = A.campaign_sections(C, orient)
closed = atoms.closed_by_stretches(water_here[COORD], orient)
results.append(("the river of a hex is made of several stretches", len(closed) > 1))

bridge_on_sides(COORD, 0, 3)
bridge_cross = v.openings_of(COORD, banks_here, water_here, A.campaign_crossings(C), one,
                         orient)
results.append(("a bridge reopens a single stretch", len(bridge_cross) == 1))
results.append(("and charges nothing beyond walking",
              bridge_cross[0][1] == 0.0))
results.append(("the reopened stretch is one of those the water closed",
              bridge_cross[0][0] in closed))

A.remove_crossings(C, COORD)
bridge_on_sides(COORD, 0, 3, kind="ford")
ford_cross = v.openings_of(COORD, banks_here, water_here, A.campaign_crossings(C), one,
                         orient)
results.append(("a ford reopens the whole water line",
              len(ford_cross) == len(closed)))
results.append(("and every passage costs as much as that terrain",
              {c for _l, c in ford_cross} == {1.0}))

# The bridge opens the stretch, not the point where the stretch ends: going
# around a junction reached by water stays forbidden.
A.remove_crossings(C, COORD)
bridge_on_sides(COORD, 0, 3)
without = atoms.graph(closed, (), orient)
with_ = atoms.graph(closed, (bridge_cross[0][0],), orient)
results.append(("the bridge opens exactly one step, both ways",
              sum(len(x) for x in with_.values())
              == sum(len(x) for x in without.values()) + 2))

# And after a river drawn later, the bridge still joins two shores.
A.set_banks(C, COORD, helpers.add_cut(GROUPS, 1, 5))
after_faces = A.campaign_sections(C, orient)[COORD]
entry = A.campaign_crossings(C)[COORD][0]
results.append(("a river drawn later does not take its place away",
              sections.crossing_shores(after_faces, entry["ends"]) is not None))
results.append(("and the stretch it reopens is still water",
              len(v.openings_of(COORD, A.campaign_sections(C, orient),
                                A.campaign_water(C, orient),
                                A.campaign_crossings(C), one, orient)) >= 1))

# With the water removed it reopens nothing: there is nothing to reopen.
A.set_banks(C, COORD, None)
results.append(("without water it reopens nothing",
              v.openings_of(COORD, A.campaign_sections(C, orient),
                            A.campaign_water(C, orient),
                            A.campaign_crossings(C), one, orient) == ()))
clean()

width = max(len(n) for n, _ in results)
for name, ok in results:
    print(("  ok  " if ok else " NO   ") + name.ljust(width))
print(f"\n{sum(1 for _, ok in results if ok)}/{len(results)} passed")
