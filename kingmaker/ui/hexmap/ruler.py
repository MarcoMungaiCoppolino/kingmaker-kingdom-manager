"""The ruler in the browser: the travel field, the traces of whoever is drawing, the release and block events.

It used to live in `ui/hexmap.py`; the `hexmap` facade still re-exports everything.
"""
from __future__ import annotations

import logging
import heapq
import json
import math
import time
from nicegui import Client, ui
from kingmaker.state import STATE
from kingmaker.ui import theme
from kingmaker.geometry import waterways, hexgrid, atoms as atoms_mod
from kingmaker.media import images
from kingmaker.access import permissions, view as view_mod
from kingmaker import travel as travel_mod

from kingmaker.ui.hexmap import common as _common
from kingmaker.ui.hexmap import drawing as _drawing
from kingmaker.ui.hexmap import markers as _markers
from kingmaker.ui.hexmap import travel as _journey
from kingmaker.ui.hexmap import boats as _boats
from kingmaker.locale.i18n import t
from kingmaker.locale import i18n

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Dragging the arrow: the arithmetic is done by the server once, the drawing
# by the browser at every mouse move.
#
# Dijkstra from a hex costs no more than reaching a single one: the same
# exploration that finds one course finds them all. So as soon as the group is
# chosen we send the browser the whole field — what reaching every cell costs
# and where one reaches it from — and from there on the drag is all its own:
# no trip over the network while the mouse moves, and the arrow follows the
# hand instead of chasing it.
def _label_texts() -> dict:
    """The words the browser writes on the dragged arrow, in the language of
    the window that asked for the field: the figures are its own, the words
    are the catalog's."""
    return {"day_one": t("drawing.days.one"), "day_other": t("drawing.days.other"),
            "plan_full": t("drawing.plan_full"), "max": t("drawing.max_prefix")}


def travel_field(mine: dict) -> dict:
    """The cost field to send the browser, or `{"active": False}`.

    With a single traveller it is theirs: what reaching every hex costs and
    what entering it costs. With several scattered travellers we send one
    each, so the browser can compute the rendezvous point on its own while
    you drag — with the same formula as the server — and show you the roads
    joining instead of a single arrow.
    """
    user = theme.user()
    if not permissions.can(user, permissions.PLAN_TRAVEL):
        return {"active": False}
    if mine.get("travel_mode") != "choose":
        return {"active": False}    # no ruler outside the mode
    # Only a **boat** changes the ruler: its road is the drawn water, and the
    # field is another. A wagon does not — it changes the Speed, not the road
    # — and the land field already knows it, because whoever is aboard has it
    # written on them. Asking it for any vehicle, with a wagon in hand the
    # ruler got the water field: on dry land there is nothing to follow, and
    # dragging no longer drew anything.
    if _boats._vehicle_in_hand(mine, "water") is not None:
        return route_field(mine)
    by_id = {p["id"]: p for p in STATE.characters()}
    chosen = [by_id[i] for i in mine.get("travel_pcs") or [] if i in by_id]
    departures = {p["id"]: (p["hex_col"], p["hex_row"]) for p in chosen
                if p["hex_col"] is not None and p["hex_row"] is not None}
    if not departures:
        return {"active": False}

    view = _common._current_view(mine)
    m = STATE.k["map"]
    columns, map_rows = int(m["columns"]), int(m["rows"])
    size = float(m["size"])
    origin = (float(m["origin_x"]), float(m["origin_y"]))
    orient = m["orientation"]
    difficulty = STATE.archive.campaign_difficulty(STATE.campaign)
    march = bool(mine.get("forced_march"))
    vehicles = _markers._vehicles_in_play()

    inside = _common.inside_map(m)

    mode = _journey._crossing(mine, chosen, vehicles, view, difficulty)
    cost_of, passage, borders, sail = mode
    banks, crossings = mode.banks, mode.crossings
    water = mode.water

    # The walkable cells, once: geometry, entry cost and whether the terrain
    # is unknown. One cell per *node*, not per hex: where the river cuts, the
    # two banks are two cells, **each with the point of its shore**. The
    # indices of this list are the key to everything else, so the travellers'
    # fields stay lists of numbers.
    #
    # The point per shore is no drawing whim: it is what makes a shore
    # something one can **point at**. As long as the two banks both sat at
    # the hex center, the mouse had no way to say which of the two it was
    # choosing — passing a bridge meant hitting its icon — and the drawn
    # arrow did not show which side of the water it was passing on.
    cells, index = [], {}
    for row in range(map_rows):
        for col in range(columns):
            entry_ = cost_of((col, row))
            if entry_ is None:
                continue
            hexagon, forced = _journey._hex_view(view, difficulty, (col, row))
            is_unknown = travel_mod.terrain_category(hexagon, forced, sail).is_unknown
            for bank in range(travel_mod.banks_of(banks, (col, row))):
                index[(col, row, bank)] = len(cells)
                px, py = _markers.bank_point((col, row), bank, size, origin, orient, banks)
                # And where the **row of markers** of that shore is, which is
                # not always the shore's point: in a whole hex the markers sit
                # below the center, and the arrow is born there. The server
                # has always drawn it so (`anchor_markers`, first point of
                # `course_points`); the ruler instead started from the cell's
                # point, so while dragging the arrow was born detached from
                # the marker and snapped back only when you let go. Two counts
                # of the same thing: one only, and the server sends it.
                ax, ay = _markers.anchor_markers((col, row), bank, size, origin,
                                          orient, banks)
                # And **which** shore it is: the browser sends it back when it
                # lets go, so the arrow left drawn is the one the hand drew
                # and not one rebuilt by likeness. In a hex with three bridges
                # the shores are reached by several roads, and «rebuild» meant
                # picking another: on release the arrow changed shape.
                # And the atom the shore's point falls in: it is where one
                # stops arriving there, and the browser must know it to count
                # the last piece of road as the server counts it.
                faces_here = (banks or {}).get((col, row)) or ()
                atom = (atoms_mod.atom_of_point(faces_here[bank].point, orient)
                         if 0 <= bank < len(faces_here) else 0)
                cells.append([col, row, round(px, 1), round(py, 1),
                              1 if is_unknown else 0, entry_,
                              round(ax, 1), round(ay, 1), bank, atom])

    # The adjacency is sent by the server instead of being deduced from the
    # geometry: two touching shores are close on the map and very far on foot
    # if there is no bridge between, and distance does not say that. So the
    # browser already knows where one passes, knowing nothing about rivers.
    neighbours = [[] for _ in cells]
    sides = []
    for node, i in index.items():
        here = (node[0], node[1])
        for other, vic in travel_mod.steps_from(node, orient, banks):
            j = index.get(other)
            if j is None or not inside(vic):
                continue
            extra = passage(here, vic) if passage else 0
            if extra is None:
                continue            # river without a bridge: that neighbour is not there
            neighbours[i].append(j)
            if extra:
                sides.append([i, j, extra])
        # And the bridges inside the hex: two cells with the same center the
        # ruler can walk. Without these the browser would draw the long way
        # round where the server passes the bridge, and the two arrows — the
        # dragged one and the confirmed one — would tell two different
        # journeys.
        for other, entry in travel_mod.inner_passages(node, banks, crossings):
            j = index.get(other)
            if j is None:
                continue
            neighbours[i].append(j)
            # `cost_inside` and not `inside`: `inside` here is already the
            # function saying whether a cell is in the map, and naming a
            # number like it replaced it for the rest of the loop. The field
            # stopped building and the ruler died silently.
            cost_inside = travel_mod.inner_cost(entry, here, cost_of)
            if cost_inside:
                sides.append([i, j, cost_inside])

    travellers = []
    for char in chosen:
        own_start = departures.get(char["id"])
        if own_start is None:
            continue
        speed, _source, _warnings = travel_mod.compose_speed([char], vehicles)
        origin_ = travel_mod.node_of(banks, own_start, _markers.section_of(char, banks))
        travellers.append({
            "id": char["id"],
            "name": char["name"],
            # The colour is for the ruler: with «together» off the arrows are
            # as many as the travellers, and all blue they cannot be told apart.
            "color": images.valid_color(char.get("color")),
            "origin": index.get(origin_, -1),
            "activities": travel_mod.available_activities(speed, march),
            "from": _ruler_field(neighbours, sides, cells,
                                      index.get(origin_, -1)),
        })
    if not travellers:
        return {"active": False}

    party_speed, _source, _warnings = _party_pace(mine, chosen, vehicles)
    near = hexgrid.neighbours(*next(iter(departures.values())), orient)[0]
    cx0, cy0 = hexgrid.hex_center(*next(iter(departures.values())), size, origin, orient)
    cx1, cy1 = hexgrid.hex_center(near[0], near[1], size, origin, orient)
    return {
        "active": True,
        "texts": _label_texts(),
        "size": size,
        # The colour of whoever holds the mouse: their arrow is that colour
        # for them too, or at the table it would not be recognised among the
        # others.
        "player_color": player_color(user),
        "step": round(math.hypot(cx1 - cx0, cy1 - cy0), 1),
        "activities_per_day": travel_mod.available_activities(party_speed, march),
        "together": bool(mine.get("together", True)),
        "cells": cells,
        "neighbours": neighbours,
        "sides": sides,
        "travellers": travellers,
        # The atom arithmetic. The geometry of the 24 atoms is the same in
        # every hex and travels **once**; for every cut hex a mask is sent
        # (which of the 36 borders the water closes), the openings (bridges
        # and fords: border and toll) and which shore every atom belongs to.
        # The browser rebuilds the graph from there and counts the quarters as
        # the server counts them — `atoms.course_by_waypoints` on this side,
        # `legCost` on that, and bench `bench10` comparing them.
        "atoms": atoms_mod.for_browser(orient),
        "compass": _compass(orient),
        "masks": _water_for_browser(banks, water, crossings, cost_of, orient,
                                        size, origin),
    }

def _compass(orient: str) -> dict:
    """From a hex to the six neighbours, in side order, by row parity.

    The browser must know **from which side** it enters a hex to count the
    atoms as the server does, and the sides are numbered by
    `hexgrid.neighbours`. Instead of redoing the cube geometry in JavaScript,
    the precomputed offsets are sent: six pairs for even rows and six for odd
    (for columns, with flat hexes).
    """
    outside = {}
    for tie in (0, 1):
        col, row = (0, tie) if orient == "pointy" else (tie, 0)
        outside[str(tie)] = [[c - col, r - row]
                              for c, r in hexgrid.neighbours(col, row, orient)]
    outside["tie"] = "row" if orient == "pointy" else "column"
    return outside

def _water_for_browser(banks, water, crossings, cost_of, orient: str,
                          size: float, origin) -> dict:
    """The water inside every cut hex, in the shortest format there is.

    `{"col,row": [mask, [[border, toll], ...], "shore per atom"]}`. The mask
    is a number; the openings are those of `openings_of`, i.e. the same the
    server's arithmetic uses; the string says, for each of the 24 atoms, the
    number of the shore it is in — the face numbering, not the province one,
    because that is the one the cells carry.
    """
    outside: dict = {}
    for coord, faces in (banks or {}).items():
        if len(faces or ()) < 2:
            continue
        closed = atoms_mod.closed_by_stretches(
            travel_mod.stretches_of(banks, water, coord), orient)
        if not closed:
            continue
        shores = travel_mod.shore_atoms(faces, orient)
        whose = ["0"] * atoms_mod.HOW_MANY
        for number, group in enumerate(shores):
            for atom in group:
                whose[atom] = str(number)
        openings = travel_mod.openings_of(coord, banks, water, crossings, cost_of,
                                           orient)
        cx, cy = hexgrid.hex_center(coord[0], coord[1], size, origin, orient)
        outside[f"{coord[0]},{coord[1]}"] = [
            atoms_mod.mask(closed),
            [[int(side), float(cost)] for side, cost in openings],
            "".join(whose),
            # The center in pixels: atoms are in hex radii from the center,
            # and the browser must be able to draw them where they are.
            [round(cx, 1), round(cy, 1)]]
    return outside

def _ruler_field(neighbours, sides, cells, origin_: int) -> list:
    """The cost field **as the browser sees it**, on the graph we send it.

    It is not the server's field, and on purpose. The server counts by gates
    — which side you enter a hex from, because that is what how much hex you
    have to cross depends on — while the ruler has one cell per **shore**,
    which is the right granularity for a dragged gesture: six cells per hex
    would make the drag jittery, and Phase 6 took a while to make it calm.

    Before, this field came from the server and the adjacencies from the
    shore graph: two different counts, and the browser could no longer
    rebuild a course that added up — the arrow was truncated. Computing it
    **here**, on the same graph we send, makes it consistent by construction:
    what the browser draws while you drag is exactly what that graph says. On
    release the arithmetic is redone by the server, with the gates, and can
    come a hair higher where the water forces one to coast along: of that
    count only the last is kept, as it always was.
    """
    if origin_ < 0 or origin_ >= len(cells):
        return [None] * len(cells)
    extra = {(a, b): c for a, b, c in sides}
    dists = [None] * len(cells)
    dists[origin_] = 0
    queue = [(0, origin_)]
    while queue:
        cost, here = heapq.heappop(queue)
        if dists[here] is not None and cost > dists[here]:
            continue
        for other in neighbours[here]:
            # As in the browser: a step inside a hex costs **a quarter** of
            # that hex. If here and there did not give the same number, the
            # dragged arrow and the field it is rebuilt on would go back to
            # telling two roads.
            same = (cells[here][0], cells[here][1]) == (cells[other][0],
                                                        cells[other][1])
            entry_ = cells[other][5] or 0
            entrance = entry_ / 4.0 if same else entry_
            after = cost + entrance + extra.get((here, other), 0)
            if dists[other] is None or after < dists[other]:
                dists[other] = after
                heapq.heappush(queue, (after, other))
    return dists

def route_field(mine: dict) -> dict:
    """The ruler's field when a boat is in hand: water only.

    Same shape as the land one — cells, adjacencies, costs — but the cells
    are not hexes: they are the **water points**. A grid vertex the river
    passes through is a cell; the center of a lake hex is a cell. So the
    dragged arrow follows the drawn lines instead of jumping from one center
    to the next, which on a bend means cutting across the fields.

    The cost is all on the **sides**, and the cell costs nothing: entering a
    hex is paid once, on entering, and crossing it from one vertex to another
    is not entering it a second time.
    """
    user = theme.user()
    sid = mine.get("travel_vehicle")
    entry = STATE.archive.stable_vehicle(sid) if sid else None
    if entry is None or entry.get("hex_col") is None:
        return {"active": False}
    departure = (int(entry["hex_col"]), int(entry["hex_row"]))
    m = STATE.k["map"]
    size = float(m["size"])
    origin = (float(m["origin_x"]), float(m["origin_y"]))
    orient = m["orientation"]
    network = _common.waters_network()
    dists, arcs = travel_mod.route_field(
        network, STATE.archive.campaign_currents(STATE.campaign),
        departure, orient, scale=_drawing.ROUTE_SCALE,
        departure_node=waterways.vehicle_node(entry, orient, network))
    if len(dists) < 2:
        return {"active": False}

    view = _common._current_view(mine)
    cells, index = [], {}
    for state in sorted(dists, key=lambda s: (s[1], str(s[0]))):
        node, hexagon = state
        if not view.can_see(*hexagon):
            continue
        if node is None:
            x, y = hexgrid.hex_center(hexagon[0], hexagon[1], size, origin, orient)
        else:
            try:
                x, y = waterways.node_point(node, size, origin, orient)
            except (IndexError, TypeError):
                continue
        index[state] = len(cells)
        # The seventh entry says whether the point is a **line end** — a
        # vertex or a center, where drawn lines meet and bend — or an inner
        # junction along a line. The hand guides from line end to line end;
        # the inner junctions in between are filled in.
        bend = 1 if node is None or node[0] in (waterways.VERTEX, waterways.CENTER) else 0
        cells.append([hexagon[0], hexagon[1], round(x, 1), round(y, 1), 0, 0, bend])
    neighbours = [set() for _ in cells]
    sides = []
    for (from_, a), (cost, _direction) in arcs.items():
        i, j = index.get(from_), index.get(a)
        if i is None or j is None:
            continue
        # The adjacency must be given in **both** directions, and the weight
        # in one only. The water graph is directed where you do not expect
        # it: going from a hex to the next the step costs, going back one
        # ends up in a different state — same point, other hex. The ruler
        # however walks the course backwards looking for who brought us here,
        # and looks among the neighbours: if only the places one can go to
        # are there, who brought us here is never found and the arrow stops.
        neighbours[i].add(j)
        neighbours[j].add(i)
        if cost:
            sides.append([i, j, cost])
    neighbours = [sorted(x) for x in neighbours]
    # `cells[i][5]` stays zero: the cost of a water journey is all on the
    # sides, because it depends on where you come from — going down and up
    # the same stretch do not cost the same.

    by_id = {p["id"]: p for p in STATE.characters()}
    chosen = [by_id[i] for i in mine.get("travel_pcs") or [] if i in by_id]
    vehicles = _markers._vehicles_in_play()
    mine["aboard"] = True
    speed, _source, _warnings = _party_pace(mine, chosen, vehicles)
    activities = travel_mod.available_activities(
        speed, bool(mine.get("forced_march")))
    origins = [index[s] for s in dists
               if dists[s] == 0 and s in index]
    if not origins:
        return {"active": False}
    near = hexgrid.neighbours(departure[0], departure[1], orient)[0]
    cx0, cy0 = hexgrid.hex_center(*departure, size, origin, orient)
    cx1, cy1 = hexgrid.hex_center(near[0], near[1], size, origin, orient)
    return {
        "active": True,
        "texts": _label_texts(),
        "size": size,
        "player_color": player_color(user),
        "step": round(math.hypot(cx1 - cx0, cy1 - cy0), 1),
        "activities_per_day": activities,
        "scale": _drawing.ROUTE_SCALE,
        # The ruler must know it is following a river: there the cells are
        # points and not hexes, and the road is not guided by hand.
        "water": True,
        "together": True,
        "cells": cells,
        "neighbours": neighbours,
        "sides": sides,
        "travellers": [{
            "id": sid,
            "name": travel_mod.vehicle_name_(entry),
            "color": _drawing.LAKE_COLOR,
            # Where the boat is there are several boarding points, all at
            # zero cost: the ruler wants one, and any one will do.
            "origin": origins[0],
            "activities": activities,
            "from": [dists.get(s) for s in index],
        }],
    }

def _send_field(mine: dict) -> None:
    """Hands the field to the browser. Outside a window it does nothing.

    The field is built *outside* the try, and it is no detail: before, it was
    inside, and an error in building it ended up in the same `except` covering
    the normal case of «there is no window to talk to» — hence at debug
    level, i.e. invisible. The browser kept the last field received, the
    ruler stopped working, and the log had nothing. An error here is an
    error, and must be said.
    """
    if mine.get("travel_mode") != "choose":
        return          # without a ruler in hand the browser does not use it
    key = (tuple(mine.get("travel_pcs") or ()), mine.get("travel_vehicle"),
              bool(mine.get("forced_march")), bool(mine.get("together", True)),
              bool(mine.get("aboard")), bool(mine.get("player_preview")),
              STATE.archive.rev, STATE.k.get("_rev"))
    if mine.get("_field_key") == key and mine.get("_field_json"):
        text = mine["_field_json"]
    else:
        text = json.dumps(travel_field(mine))
        mine["_field_key"], mine["_field_json"] = key, text
    try:
        ui.run_javascript(f"window.kmTravelField = {text};")
    except Exception:
        # It happens when the redraw comes from a timer and not from a click:
        # there is no window to talk to, and the field will arrive at the
        # user's next gesture.
        log.debug("travel field not delivered", exc_info=True)

# --------------------------------------------------------------------------
# The arrow someone else is drawing *right now*.
#
# Until now the ruler was a private matter: the arrow was drawn by the browser
# of whoever dragged, and the others saw the journey only when done. At the
# table that does not work — while one discusses the route the others look at
# a still map, and «no wait, that way» has nothing to refer to. So while
# dragging the road is sent to the others too, with the name of whoever is
# drawing it and a colour of their own.
#
# It travels as a row of hexes, not of pixels: the grid calibration belongs to
# the kingdom and every window knows it, so a few dozen bytes per move are
# enough. The server puts them back into pixels, being the only place where
# the calibration is surely the right one.

# A colour for every person at the table. They are not the character colours:
# those answer «whose marker is this», these «who is drawing», which at the
# table is another question — it often happens that one moves another's
# group. They are assigned by position in the account list, so they stay the
# same between one start and the next without an extra column to fill by hand.
PLAYER_COLORS = ("#7fc3e8", "#f0a35e", "#8fd97a", "#e77fb4",
                    "#e8d06a", "#b28ff0", "#6fd8c8", "#d98f7a")

_USER_COLORS: dict[str, str] = {}

def player_color(user) -> str:
    """The colour of whoever draws, always the same for the same person."""
    if user is None or not getattr(user, "id", ""):
        return PLAYER_COLORS[0]
    if user.id not in _USER_COLORS:
        listing = [u["id"] for u in STATE.archive.list_users()]
        for spot, uid in enumerate(listing):
            _USER_COLORS[uid] = PLAYER_COLORS[spot % len(PLAYER_COLORS)]
    return _USER_COLORS.get(user.id, PLAYER_COLORS[0])

# Window that is drawing -> the last road it sent.
_TRACES: dict[str, dict] = {}

# After how long a trace counts as abandoned: if the mouse release does not
# arrive (a window closed mid-gesture) the arrow must not stay there.
TRACE_EXPIRY = 8.0

def _trace_audience(pc: list) -> set:
    """Which windows may see this arrow while it is being drawn.

    The same rule as the routes already under way (`_svg_journeys_in_progress`):
    the GM sees everything, a player sees the journey of people they know the
    whereabouts of. Decided once at the start of the gesture and not at every
    move, because for the whole of a drag who leaves does not change.
    """
    # A boat in hand travels as a vehicle, and its id sits among the
    # travellers: whoever can see the hex the boat is in sees its arrow, as
    # they see the boat.
    vehicles = _markers._vehicles_in_play()
    boats = [vehicles[i] for i in pc if i in vehicles]
    outside = set()
    for cid, data in theme.other_windows():
        user = data.get("user")
        if user is None:
            continue
        view = view_mod.MapView(user, STATE)
        if view.gm or (set(pc) & {p["id"] for p in view.markers()}) or any(
                v.get("hex_col") is not None
                and view.can_see(int(v["hex_col"]), int(v["hex_row"])) for v in boats):
            outside.add(cid)
    return outside

def _journey_blocked(mine: dict, args) -> None:
    """The arrow bumped into something: say what, not only stop.

    The browser already signals it on its own — red flash and vibration — but
    those say «no», not «why not». The why comes from here, in words, and the
    browser asks to write it at most once every two and a half seconds: the
    hand bumps into a river twenty times a second, and twenty warnings would
    be worse than silence.
    """
    if mine.get("travel_mode") != "choose":
        return
    if not permissions.can(theme.user(), permissions.PLAN_TRAVEL):
        return
    reason = (args or {}).get("reason") or ""
    if reason == "unreachable":
        # Pressed on a cell no road reaches: with the right button the app
        # said so, holding the button it stayed mute.
        theme.notify(t("map.ruler.no_path_destination_cannot"), "warning")
        return
    if reason == "water" or bool((args or {}).get("water")):
        theme.notify(t("map.ruler.no_way_through_there"), "warning")
    else:
        theme.notify(t("map.ruler.arrow_cannot_get_there"), "warning")

def _trace_from_plan(mine: dict) -> None:
    """Publishes to the others the journey this window is preparing.

    The dragged ruler is sent by the browser while the hand moves; this
    instead covers all the rest — the destination chosen with the right
    button, the plan redone by the server when you let go, the cancelled
    journey — i.e. the moments when there is an arrow on the drawer's screen
    and there was nothing on the other screens.

    Called from `_redraw_travel`, which is the point every plan change goes
    through: so there is no case to remember to hook up.
    """
    user = theme.user()
    if not permissions.can(user, permissions.PLAN_TRAVEL):
        return
    stretches, labels = [], []
    plan = mine.get("plan")
    singles = mine.get("singles") or []
    # **The polyline** is published, the same this window draws: shores,
    # atoms, the piece where one stops. The watcher sees what the drawer
    # sees, and a journey inside the hex — a single hex, but a road with its
    # points — is seen from outside too.
    m = STATE.k["map"]
    size = float(m["size"])
    origin = (float(m["origin_x"]), float(m["origin_y"]))
    orient = m["orientation"]
    shores = _markers._shores_of(mine)

    def polyline(course, bank=None) -> list:
        points = _drawing._polyline(course, size, origin, orient, shores, bank)
        return [(round(x, 1), round(y, 1)) for x, y in points]

    route = mine.get("route")
    if mine.get("by_river") and route and route.get("points"):
        # A route on the water: the points are the junctions it passes
        # through, already in pixels — the same polyline this window draws.
        points = [(round(float(x), 1), round(float(y), 1)) for x, y in route["points"]]
        if len(points) >= 2:
            stretches.append(points)
            labels.append(("", plan, False) if plan is not None and plan.possible else "")
    elif singles:
        for entry in singles:
            course = [tuple(c) for c in (entry.get("path") or [])]
            if not course:
                continue
            bank = (shores.by_id.get(entry.get("id")) if shores is not None
                    else None)
            points = polyline(course, bank)
            if len(points) < 2:
                continue
            stretches.append(points)
            its_own = entry.get("plan")
            labels.append((entry.get("name", ""), its_own, False)
                          if its_own is not None and its_own.possible else "")
    else:
        course = [tuple(c) for c in (mine.get("path") or [])]
        rendezvous = mine.get("rendezvous")
        of_group = rendezvous is not None and getattr(rendezvous, "point", None) is not None
        points = polyline(course) if course else []
        if len(points) >= 2:
            stretches.append(points)
            labels.append(("", plan, of_group)
                          if plan is not None and plan.possible else "")
        # If the common road is zero long — the meeting point is the
        # destination — the days go on the first branch, which ends right
        # there: without this, the watcher saw the branches and no figure.
        group_caption = (("", plan, of_group)
                         if plan is not None and plan.possible
                         and of_group and len(points) < 2 else "")
        for branch in mine.get("branches") or []:
            steps = [tuple(c) for c in branch]
            points = polyline(steps) if steps else []
            if len(points) >= 2:
                stretches.append(points)
                labels.append(group_caption)
                group_caption = ""
    _publish_trace(user, stretches, labels, _travellers_of(mine),
                   "ruler.verb_preparing", live=False)

def _travellers_of(mine: dict) -> list:
    """Who this arrow is about: the chosen characters, and the boat in hand."""
    who = [str(i) for i in (mine.get("travel_pcs") or [])]
    if mine.get("travel_vehicle"):
        who.append(str(mine["travel_vehicle"]))
    return who

def _label_text(spec, lang: str | None = None) -> str:
    """A label of a trace in the language of whoever reads it.

    A label is a plain string (the browser sent it while dragging) or a
    `(prefix, plan, of_group)` triple, rendered for every window in its own
    language: the figure is the same, the words are theirs.
    """
    if isinstance(spec, str):
        return spec
    prefix, plan, of_group = spec
    text = _drawing.plan_text(plan, of_group, lang)
    return f"{prefix} · {text}" if prefix else text


def _title_text(tr: dict, lang: str | None = None) -> str:
    return f"{tr['name']} {i18n.t_in(lang, tr['verb'])}".strip()


def _publish_trace(user, stretches: list, labels: list, pc: list,
                   verb: str, live: bool, blocked: bool = False) -> None:
    """Puts (or removes) this window's arrow among the others'.

    `verb` is a catalog key: what this person is doing, said in the language
    of whoever watches.
    """
    cid = theme.current_window()
    if not stretches:
        if _TRACES.pop(cid, None) is not None:
            _send_traces()
        return
    name = getattr(user, "username", "") if user else ""
    old_one = _TRACES.get(cid)
    _TRACES[cid] = {
        "name": name,
        "verb": verb,
        "title": f"{name} {t(verb)}".strip(),
        "color": player_color(user),
        "pc": pc,
        "stretches": stretches,
        "label_specs": labels,
        "labels": [_label_text(s) for s in labels],
        "live": live,
        # The arrow bumped into a river right now: the watcher sees it red as
        # whoever is drawing it does.
        "blocked": blocked,
        "logged_at": time.monotonic(),
        "public": (old_one["public"] if old_one and old_one["pc"] == pc
                     else _trace_audience(pc)),
    }
    _send_traces()

def _live_trace(mine: dict, args) -> None:
    """This window's ruler, while it is still being dragged."""
    user = theme.user()
    if not permissions.can(user, permissions.PLAN_TRAVEL):
        return
    # What arrives comes from the browser, and from the browser anything can
    # arrive: only what is really a polyline of points is kept.
    #
    # **Points in pixels**, not hexes: it is the polyline whoever drags sees
    # on their screen — from the anchor, through the atoms, to the aimed
    # piece — and the watcher must see that one. As long as the row of hexes
    # arrived and the server converted it back to centers, the others saw an
    # arrow from center to center over the water, and did not see a journey
    # inside the hex at all.
    data = args if isinstance(args, dict) else {}
    raw_ones = data.get("stretches") if isinstance(data.get("stretches"), list) else []
    captions = data.get("labels") if isinstance(data.get("labels"), list) else []
    stretches, labels = [], []
    for spot, stretch in enumerate(raw_ones[:MAX_TRACE_STRETCHES]):
        steps = _valid_points(stretch)
        if len(steps) > 1:
            stretches.append(steps)
            caption = captions[spot] if spot < len(captions) else ""
            labels.append(str(caption)[:60] if isinstance(caption, str) else "")
    pc_list = data.get("pc")
    pc = [str(i) for i in pc_list] if isinstance(pc_list, list) else []
    _publish_trace(user, stretches, labels, pc, "ruler.verb_tracing", live=True,
                      blocked=bool(data.get("blocked")))

MAX_TRACE_STRETCHES = 24          # arrows per window: k travellers, at most

MAX_TRACE_POINTS = 2000         # points per arrow: the atoms of a long journey

def _valid_points(stretch, with_hex: bool = False) -> list:
    """A polyline as the browser sends it, cleaned: pairs of finite numbers.

    With `with_hex` every point may carry the hex it was counted in, as the
    water ruler sends it (`[x, y, col, row]`): `statuses_from_points` needs
    both, because one vertex belongs to several hexes. The check used to drop
    the hex, and the drawn route was silently replaced by the cheapest one.
    """
    steps = []
    for c in (stretch if isinstance(stretch, list) else [])[:MAX_TRACE_POINTS]:
        if not isinstance(c, (list, tuple)) or len(c) < 2:
            continue
        try:
            x, y = float(c[0]), float(c[1])
        except (TypeError, ValueError):
            continue
        if not (math.isfinite(x) and math.isfinite(y)):
            continue
        if with_hex and len(c) >= 4:
            try:
                col, row = int(c[2]), int(c[3])
            except (TypeError, ValueError):
                continue
            if not (0 <= col < int(STATE.k["map"]["columns"])
                    and 0 <= row < int(STATE.k["map"]["rows"])):
                continue
            steps.append((round(x, 1), round(y, 1), col, row))
            continue
        steps.append((round(x, 1), round(y, 1)))
    return steps

def _send_traces(also_to_me: bool = False) -> None:
    """Hands every other window the arrows being drawn right now.

    `also_to_me` is for whoever comes back to look at the map after being in
    another mode: we had taken the others' arrows from them, and without this
    they would not come back until someone moves the mouse.
    """
    m = STATE.k["map"]
    size = float(m["size"])
    origin = (float(m["origin_x"]), float(m["origin_y"]))
    orient = m["orientation"]
    now = time.monotonic()
    # Away with the arrows of those no longer here, and the dragged ones left
    # hanging: if the mouse release does not arrive — a window closed
    # mid-gesture — the arrow must not stay on the others' screens. A plan
    # instead stays until whoever made it changes it: it is precisely what is
    # being looked at together.
    for old_one in [c for c, tr in _TRACES.items()
                    if c not in Client.instances
                    or (tr["live"] and now - tr["logged_at"] > TRACE_EXPIRY)]:
        _TRACES.pop(old_one, None)

    def in_pixels(stretch) -> list:
        # Traces are already polylines in pixels — those whoever draws sees —
        # and pass through as they are.
        return [[round(float(x), 1), round(float(y), 1)] for x, y in stretch]

    windows = list(theme.other_windows())
    if also_to_me:
        windows.append((theme.current_window(), theme.window_state()))
    for cid, data in windows:
        client_ = Client.instances.get(cid)
        if client_ is None or data.get("tab") != "map":
            continue
        # Whoever is tracing rivers or laying fog is looking at the map for
        # another reason: a travel arrow on top of the drawing is just
        # something in the way.
        its = data.get("hexmap") or {}
        if its.get("water_mode") or its.get("fog_mode"):
            client_.run_javascript(
                "window.kmOthersTrace && window.kmOthersTrace({tracce: []});")
            continue
        lang = data.get("lang")
        outside = [{"title": _title_text(tr, lang), "color": tr["color"],
                  "labels": [_label_text(s, lang) for s in tr["label_specs"]],
                  "blocked": tr["blocked"],
                  "stretches": [in_pixels(t) for t in tr["stretches"]]}
                 for author, tr in _TRACES.items()
                 if author != cid and cid in tr["public"]]
        try:
            client_.run_javascript(
                "window.kmOthersTrace && window.kmOthersTrace("
                + json.dumps({"size": size, "traces": outside}) + ");")
        except Exception:
            # A window that just left: not an error, and next time round
            # `other_windows` will no longer name it.
            log.debug("trace not delivered to %s", cid, exc_info=True)

def statuses_from_points(network, points, size: float, origin, orient: str) -> list:
    """From the points the browser drew to the states of the water journey.

    Every entry arriving is `[x, y, column, row]`: where the cell fell and in
    which hex the ruler counted it. The point says **which water point**, the
    hex says **on which side** one was — both are needed, because one and the
    same vertex belongs to several hexes and the route tells them apart.
    """
    outside = []
    for entry in points or ():
        try:
            x, y = float(entry[0]), float(entry[1])
            hexagon = (int(entry[2]), int(entry[3]))
        except (TypeError, ValueError, IndexError):
            return []
        node = waterways.nearest_node(network, (x, y), size, origin, orient,
                                        threshold=size * 0.35)
        if node is None:
            return []
        outside.append((node, hexagon))
    return outside

def _valid_point(point):
    """The coordinates the browser says, if they are coordinates."""
    try:
        return (float(point[0]), float(point[1]))
    except (TypeError, ValueError, IndexError):
        return None

def _dragged_target(mine: dict, mapping, args) -> None:
    """The browser let go of the button on a hex: we compute for real.

    The real arithmetic is redone by the server with the same rules as the
    field, so the dragged arrow and the plan that appears cannot tell two
    different stories.
    """
    if not permissions.can(theme.user(), permissions.PLAN_TRAVEL):
        return          # an event can be emitted from the browser console too
    if isinstance(args, (list, tuple)):
        args = args[0] if args else {}
    if not isinstance(args, dict):
        return
    # Everything that arrives has a maximum size, and is measured **before**
    # walking over it: the arithmetic runs on the server's only event loop,
    # and a list of a million cells would stop it for everyone.
    separate = _valid_separate(args.get("separate"))
    if separate is None:
        return
    if separate:
        _journey._compute_journey(mine, mapping, traced_separate=separate)
        return
    traced_one = _valid_cells(args.get("path") or [])
    if traced_one is None:
        return
    if len(traced_one) >= 2:
        nodes = _valid_nodes(args.get("nodes"))
        # With several scattered travellers what the hand draws is the common
        # road, which starts from the rendezvous: it must be said, because
        # the server checks it starting from a different hex.
        if args.get("common"):
            branches = _branches_valid_shape(args.get("branches"))
            _journey._compute_journey(mine, mapping, common_traced=traced_one,
                             traced_nodes=nodes, traced_branches=branches)
        else:
            _journey._compute_journey(mine, mapping, traced_one,
                             arrival_point=_valid_point(args.get("point")),
                             drawn_points=_valid_points(args.get("points"), with_hex=True),
                             traced_nodes=nodes)
        return
    try:
        col, row = int(args["col"]), int(args["row"])
    except (KeyError, TypeError, ValueError):
        return
    mine.update(col=col, row=row)
    _journey._compute_journey(mine, mapping)

MAX_TRACED_NODES = 64          # shores touched along a drawn road


def _valid_cells(listing, max_: int = MAX_TRACE_POINTS):
    """A row of hexes as the browser sends it, or None if it does not hold:
    too long, not pairs of integers, or outside the map."""
    if not isinstance(listing, list) or len(listing) > max_:
        return None
    inside = _common.inside_map(STATE.k["map"])
    outside = []
    for cell in listing:
        try:
            col, row = int(cell[0]), int(cell[1])
        except (TypeError, ValueError, IndexError):
            return None
        if not inside((col, row)):
            return None
        outside.append([col, row])
    return outside


def _valid_nodes(nodes):
    """The touched shores: triples of integers, at most `MAX_TRACED_NODES`."""
    if not isinstance(nodes, list) or len(nodes) > MAX_TRACED_NODES:
        return None
    outside = []
    for n in nodes:
        try:
            outside.append([int(n[0]), int(n[1]), int(n[2])])
        except (TypeError, ValueError, IndexError):
            return None
    return outside


def _valid_separate(separate):
    """The courses of k travellers: [] if there are none, None if they do not hold."""
    if not separate:
        return []
    if not isinstance(separate, list) or len(separate) > MAX_TRACE_STRETCHES:
        return None
    outside = []
    for entry in separate:
        if not isinstance(entry, dict):
            return None
        course = _valid_cells(entry.get("path") or [])
        if course is None:
            return None
        outside.append({"id": str(entry.get("id", "")), "path": course})
    return outside


def _branches_valid_shape(branches):
    """The rendezvous branches, by shape only: the substance is checked by travel."""
    if not isinstance(branches, list) or len(branches) > MAX_TRACE_STRETCHES:
        return None
    outside = []
    for entry in branches:
        if not isinstance(entry, dict):
            continue
        course = _valid_cells(entry.get("path") or [])
        if course is None:
            continue
        outside.append({"id": str(entry.get("id", "")), "path": course})
    return outside


def _party_pace(mine: dict, chosen: list[dict], vehicles: dict):
    """Speed, explanation and warnings of the group moving as one.

    A single place the question «how fast does the group go together» goes
    through, so the plan, the rendezvous, the saved legs and the dragged arrow
    all answer the same way.
    """
    return travel_mod.group_pace(chosen, vehicles, bool(mine.get("aboard")))

def _party_activities(mine: dict, chosen: list[dict], vehicles: dict) -> float:
    speed, _source, _warnings = _party_pace(mine, chosen, vehicles)
    return travel_mod.available_activities(
        speed, bool(mine.get("forced_march")))

def _redo_plan(mine: dict, mapping) -> None:
    """Redoes the arithmetic on the path already drawn, without choosing another.

    Changing forced march or getting everyone aboard changes *how long it
    takes*, not *where one passes*: whoever just drew an arrow by hand wants
    to know what that road costs at the new pace, and seeing it replaced by
    the cheapest would be losing the work done. The path goes back in as if
    the mouse had just drawn it, and the server checks it again anyway.
    """
    if mine.get("singles"):
        # Everyone on their own: the roads to keep are k, not one.
        _journey._compute_journey(mine, mapping, traced_separate=[
            {"id": v["id"], "path": [list(c) for c in v["path"]]}
            for v in mine["singles"]])
        return
    path = [tuple(c) for c in (mine.get("path") or [])]
    if len(path) < 2 and not (len(path) == 1 and mine.get("arrival_pos")):
        _journey._redraw_travel(mine, mapping)          # nothing to redo
        return
    if mine.get("rendezvous") is not None:
        # With a rendezvous what is drawn is the common road: it starts from
        # the meeting point, not from where a character is.
        _journey._compute_journey(mine, mapping, common_traced=path)
    else:
        _journey._compute_journey(mine, mapping, traced_one=path)

def _change_aboard(mine: dict, mapping, value: bool) -> None:
    """Everyone getting aboard changes the group's pace, hence the days."""
    mine["aboard"] = bool(value)
    _redo_plan(mine, mapping)

def _change_march(mine: dict, mapping, value: bool) -> None:
    """Forced march changes the activities per day, hence the days.

    It must be resent to the browser too, or the dragged arrow would keep
    counting the days at the previous pace.
    """
    mine["forced_march"] = bool(value)
    _redo_plan(mine, mapping)
