# -*- coding: utf-8 -*-
"""When a journey is no longer made, nothing of it remains on the map.

A plan is made of six pieces drawn from different places — arrow, hexes
underneath, approach roads, meeting-point circle, separate journeys, water
route — and as long as each erased them on its own half a plan stayed stuck
to the map. The worst case: the travellers are dissolved and their pieces
remain, but the box with «Cancel» vanishes with the group, so there is
nothing left to click to remove them.
"""
import io
import os

from kingmaker.access import permissions
from kingmaker.state import STATE
from kingmaker.ui import hexmap, theme
import helpers

m = STATE.k["map"]
size = float(m["size"])
origin = (float(m["origin_x"]), float(m["origin_y"]))
orient = m["orientation"]
results = []


class FakePlan:
    possible = True
    total_cost = 6
    days = 4
    max_estimate = False


class FakeRendezvous:
    point = (9, 5)
    union_days = 1.0


class FakeMap:
    def refresh(self):
        pass


def whole_plan():
    """A window carrying a nicely loaded group journey."""
    return {"plan": FakePlan(), "path": [(9, 5), (10, 5), (11, 5)],
            "branches": [[(8, 5), (9, 5)]], "singles": [], "rendezvous": FakeRendezvous(),
            "route": None, "by_river": False, "land": None,
            "travel_pcs": ["a", "b"], "together": True, "map": FakeMap(),
            "travel_mode": "choose", "fog_mode": None,
            "fog_selection": [], "water_mode": False, "border_mode": None,
            "water_proposal": None, "cut_in_progress": None,
            "current_from": None, "lake_points": [], "lake_id": None,
            "place_pc": None, "place_vehicle": None,
            "travel_vehicle": None, "landing": None}


def drawn(mine):
    """What of this plan really ends up inside the SVG."""
    return hexmap._svg_path(mine.get("path") or [], size, origin, orient,
                                mine.get("plan"), mine.get("branches") or [],
                                mine.get("rendezvous"), mine.get("singles") or [])


# --- 1. the whole plan is seen, and forgetting it removes it all ----------
mine = whole_plan()
results.append(("a group plan is seen on the map", len(drawn(mine)) > 0))
hexmap._forget_plan(mine)
results.append(("forgetting it nothing stays drawn", drawn(mine) == ""))

# --- 2. the piece that remained: branches and meeting-point circle --------
# Before, resetting `path` was enough to look clean, but the approach roads
# and the meeting-point circle are drawn separately and stayed there.
vehicle = whole_plan()
vehicle["plan"] = None
vehicle["path"] = []
results.append(("with only the arrow removed the meeting point would remain",
              len(drawn(vehicle)) > 0))

# --- 3. and the separate journeys, which have their own arrow and label ---
scattered = whole_plan()
scattered["singles"] = [{"name": "Dagny", "path": [(9, 5), (10, 5)],
                      "days": 4, "color": "#7fc3e8"}]
scattered["plan"] = None
scattered["path"] = []
results.append(("and so would the journeys of those going on their own",
              "km-path" in drawn(scattered) and len(drawn(scattered)) > 60))
hexmap._forget_plan(scattered)
results.append(("forgetting them, those go too", drawn(scattered) == ""))

# --- 4. every way out of the journey forgets everything -------------------
# `_redraw_travel` talks to the browser and to the other windows: here only
# what remains in the state matters, so it is silenced.
real_redraw = hexmap._redraw_travel
helpers.silence("_redraw_travel", lambda mine, mapping: None)
try:
    exits = [
        ("«Annulla»", lambda mine: hexmap._reset_journey(mine, FakeMap())),
        ("togliere uno dal gruppo",
         lambda mine: hexmap._remove_from_group("a", mine, FakeMap())),
        ("changing one's mind about travelling together",
         lambda mine: hexmap._change_together(mine, FakeMap(), False)),
        ("choosing other travellers",
         lambda mine: hexmap._choose_travellers(mine, ["c"])),
        ("dissolving the group from the menu",
         lambda mine: hexmap._choose_travellers(mine, [])),
        ("turning the Journey mode off",
         lambda mine: hexmap._single_mode(mine, "")),
    ]
    for name, log_out in exits:
        mine = whole_plan()
        mine["singles"] = [{"name": "Dagny", "path": [(9, 5), (10, 5)],
                           "days": 4, "color": "#7fc3e8"}]
        log_out(mine)
        results.append((f"after {name} the map is clean", drawn(mine) == ""))
finally:
    helpers.silence("_redraw_travel", real_redraw)

# --- 4b. and the real gesture: clicking the face of whoever was leaving ---
# It is how a group is really dissolved, with a finger on the portrait, and
# it has its own road in the code: if that one forgets half the plan the
# arrow stays on the map with no button left to remove it.
on_the_map = [p for p in STATE.characters() if p["hex_col"] is not None]
if on_the_map:
    char = on_the_map[0]

    class Allowed:
        id, username, role = "check", "check", permissions.ADMIN
        active = True

    real_user = theme.user
    real_redraw = hexmap._redraw_travel
    theme.user = lambda: Allowed()
    helpers.silence("_redraw_travel", lambda mine, mapping: None)
    try:
        mine = whole_plan()
        mine["travel_pcs"] = [char["id"]]
        hexmap._portrait_click(char, mine, FakeMap())   # it is removed
        results.append(("clicking the portrait of whoever was leaving the map is clean",
                      drawn(mine) == "" and char["id"] not in mine["travel_pcs"]))
    finally:
        theme.user = real_user
        helpers.silence("_redraw_travel", real_redraw)
else:
    print("   (no character on the map: the click on the portrait is not tested)")

# --- 5. and there is no going back to erasing one piece at a time ---------
# The rule lives in one place: if someone puts a partial reset back by hand,
# this test says so before it ends up on the table's map.
source_text = helpers.map_source()
results.append(("a plan is reset from a single point",
              source_text.count('mine["path"] = []') == 1))

# --- 6. the arrow the browser draws is really erased ----------------------
# The ruler's arrow is not drawn by the server: the browser writes it inside
# a group of its own, and to keep it from flickering it keeps a log of what
# is already written in there. Two functions — the group journey's and the
# separate journeys' — wrote the innerHTML on their own without updating it,
# and at the end of the gesture the erasing found the log already at
# «nothing» and touched nothing more: the arrows of a journey of two or more
# stayed stuck to the map, and went away neither by choosing someone else nor
# by leaving Travel.
#
# The test is on the source because that code runs in the browser and there
# is no browser here: the rule is that in the group one writes **only**
# through `write`, which is also the only place one erases from.
ruler_ = io.open(os.path.join("kingmaker", "ui", "static", "travel_drag.js"),
                   encoding="utf-8").read()
writes = [r.strip() for r in ruler_.splitlines()
             if "group.innerHTML" in r]
results.append(("in the ruler group one writes from a single point",
              writes == ["group.innerHTML = html;"]))
inner_write = ruler_.split("const write = (group, html) => {")[1].split("};")[0]
results.append(("and that point is `write`, which keeps the log up to date",
              "group.innerHTML = html;" in inner_write
              and "written.set(group, html);" in inner_write))
results.append(("the two that draw several arrows go through it too",
              ruler_.count("write(group, html);") == 1
              and ruler_.count("write(group, html + labels);") == 1))
results.append(("and closing the gesture the group empties",
              "write(finished.group, '');" in ruler_))

# --- 7. entering a new cell costs a moment of dwelling --------------------
# The hand's jitter crossed the side of the hex and the arrow entered at
# once. On a side it went unnoticed — re-entering shortens — but on a vertex
# three cells touch, and circling it lengthened the course by three steps per
# loop: since passing again is allowed, those steps no longer remove
# themselves.
results.append(("there is a dwell time before entering",
              "const HALT =" in ruler_))
results.append(("and a threshold to enter at once when well inside",
              "const INSIDE =" in ruler_))
results.append(("the mouse move proposes, it does not decide",
              "propose(nearestIndex(point.x, point.y), point);" in ruler_
              and "decidi(indiceVicino(" not in ruler_))
results.append(("every different cell cancels the previous wait",
              ruler_.count("forgetHalt();") >= 3))
inner_close = ruler_.split("const close = (e) => {")[1].split("const finished = state;")[0]
results.append(("and letting go the waiting cell is taken anyway",
              "decide(wait);" in inner_close))
# On the water the first step is «press and you have the road», at once; from
# there the hand guides junction by junction, and the junctions are close
# together: the same wait as on land, or a hand crossing the river drew
# loops by itself. And no «well inside» shortcut: a point has no inside.
inner_propose = ruler_.split("const propose = (cell, point) => {")[1].split(chr(10) + "  };")[0]
water_branch = inner_propose.split("if (field().water) {")[1].split("} else if")[0]
results.append(("on the water the first step is taken at once",
              "if (!state.steps.length)" in water_branch and "decide(cell);" in water_branch))
results.append(("and from then on the hand guides by edges, with no wait",
              "waterGuide(point)" in water_branch and "HALT" not in water_branch))
results.append(("the land cells keep their wait",
              "} else if (reallyInside(cell, point)) {" in inner_propose
              and "HALT)" in inner_propose))
# An edge is taken once the cursor has travelled a good part of it, and
# undone once it comes back near its start: both shares are written once.
results.append(("a junction is taken by travel along its side, and undone by travel",
              "const COMMIT = 0.65;" in ruler_ and "const BACK = 0.5;" in ruler_
              and "Math.max(COMMIT * side, px(PX_COMMIT))" in ruler_ and "line.at[k - 1] + BACK * side" in ruler_))
# The direction comes from the line — line end to line end, a crossing being
# an end too — and the steps from its junctions.
results.append(("the lines run from line end to line end, crossings included",
              "const isEnd = (i) =>" in ruler_ and "(adjacencies()[i] || []).length > 2" in ruler_
              and "if (isEnd(o)) ends.push(o); else queue.push(o);" in ruler_))
# Going back over the side just travelled is retracing: that side is never
# offered again as a new line, so the arrow shrinks instead of doubling back.
results.append(("the side just travelled is never armed backwards",
              "e.cells[0] === before" in ruler_))
# Thresholds in screen pixels, and a whole-line step when the sides are tiny.
results.append(("the thresholds are screen pixels, and tiny sides make the line one step",
              "const px = (n) => n / screenScale;" in ruler_ and "const PX_FINE = 12;" in ruler_
              and "if (!fineEnough(line)) return COMMIT * line.total;" in ruler_))
# Since every shore has the point of its piece of hex, «how far in you are»
# means something there too: passing a bridge is entering the other half of
# the same hex, and waiting a tenth of a second for every bridge would be
# felt.
deep_inside = ruler_.split("const reallyInside = (cell, point) => {")[1].split(chr(10) + "  };")[0]
results.append(("and the depth counts inside a shore too",
              "banks(cell)" not in deep_inside
              and "field().step" in deep_inside))

# --- 8. the line fades: new stretches full, old ones dimmed --------------
# With a course that crosses itself, two overlapping lines are
# indistinguishable: the fade says which was just drawn, and hence where to
# go back from.
inner_trace = ruler_.split("const trace = (points, color, thickness) => {")[1]
results.append(("the line is drawn in stretches, not all in one colour",
              "for (let i = first; i < last; i++)" in inner_trace))
results.append(("with the colour fading towards the outline's shadow",
              "blend(color," in inner_trace and "const SHADOW =" in ruler_))
results.append(("and a queue of fixed length, not a node per step",
              "const QUEUE =" in ruler_
              and "points.slice(0, first + 1)" in inner_trace))
# The queue is short on purpose: fading over fourteen stretches the
# difference between one and the next vanished, precisely where it matters —
# the last two or three.
results.append(("and short: the fade sits where the hand looks",
              "const QUEUE = 3;" in ruler_))

# --- 9. the filling goes straight, or does not fill ----------------------
# Bringing the hand near a river, the arrow did not bump into it: it went
# off looking for the bridge three hexes further with the same Dijkstra as
# the server, and you found yourself with a road you had not drawn.
results.append(("the gap is filled going straight, not by searching the road",
              "const inStraightLine =" in ruler_
              and "versoDritto" not in ruler_))
inner_straight = ruler_.split("const inStraightLine = (from, a) => {")[1].split(chr(10) + "  };")[0]
results.append(("every step of the filling must really get closer",
              "minimum > howMuch(here) - step * 0.5" in inner_straight))
results.append(("and no more than the hand can skip in one go",
              "added.length >= MAX_FILL" in inner_straight))
# The first step of the drag is the shortest way to the pressed cell,
# **always**, even for the next cell: hand guiding holds from the second
# step. For a while the next cell followed hand guiding («one step, or
# nothing»), so as not to see the arrow run off looking for a far bridge; but
# from inside a small piece of hex «one step» often does not exist, and the
# arrow stayed glued to the marker.
inner_refresh = ruler_.split("const refresh = (cell) => {")[1].split(chr(10) + "  };")[0]
results.append(("and the first step is always the shortest way, even next door",
              "state.steps = climbBack(dists, cell);" in inner_refresh
              and "lontano(" not in inner_refresh))
results.append(("and the «first ring» rule is gone",              "const VICINO" not in ruler_ and "const lontano" not in ruler_))

width = max(len(n) for n, _ in results)
print()
for name, ok in results:
    print(("  ok  " if ok else " NO   ") + name.ljust(width))
print(f"\n{sum(1 for _, ok in results if ok)}/{len(results)} passed")
