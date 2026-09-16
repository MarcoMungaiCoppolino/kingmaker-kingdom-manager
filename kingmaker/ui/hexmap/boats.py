"""On a boat: the route on the water, placing a vehicle, boarding and landing.

It used to live in `ui/hexmap.py`; the `hexmap` facade still re-exports everything.
"""
from __future__ import annotations

import logging
from nicegui import ui
from kingmaker.state import STATE
from kingmaker.ui import theme
from kingmaker.geometry import waterways, hexgrid, sections
from kingmaker.geometry import atoms as atoms_mod
from kingmaker.access import permissions
from kingmaker import travel as travel_mod

from kingmaker.ui.hexmap import common as _common
from kingmaker.ui.hexmap import drawing as _drawing
from kingmaker.ui.hexmap import markers as _markers
from kingmaker.ui.hexmap import travel as _journey
from kingmaker.ui.hexmap import ruler as _ruler
from kingmaker.locale.i18n import t, tn

log = logging.getLogger(__name__)


def _vehicle_in_hand(mine: dict, kind: str | None = None) -> dict | None:
    """The vehicle taken in hand, if it is of the requested kind. None if there is none.

    Needed because «in hand» now means a wagon as much as a boat, and the two
    lead to two different journeys: the route along the river belongs to
    whoever floats.
    """
    sid = mine.get("travel_vehicle")
    entry = STATE.archive.stable_vehicle(sid) if sid else None
    if entry is None:
        return None
    # In the depot it is not in hand: one travels on it by boarding, and to
    # board it must be somewhere. Without this a stale link was enough — a
    # person still assigned to a boat put away — for the ruler to start
    # looking for water for a journey made on foot.
    if travel_mod.where_it_is(entry) is None:
        return None
    if kind is not None and travel_mod.vehicle_kind(entry) != kind:
        return None
    return entry

def _compute_route(mine: dict, mapping, point=None, drawn_one=None) -> bool:
    """The journey when a boat is in hand: water only, and one leaves from it.

    It is not the land journey with a variant: it is another journey. One
    leaves from where the boat is — not from where the characters are, who
    may still be ashore — and arrives only where the water leads. So it has
    its own arithmetic, and when there is no road it says so instead of
    falling back on a course on foot nobody asked for.
    """
    sid = mine.get("travel_vehicle")
    entry = STATE.archive.stable_vehicle(sid) if sid else None
    if entry is None or entry.get("hex_col") is None:
        mine["travel_vehicle"] = None
        return False
    departure = (int(entry["hex_col"]), int(entry["hex_row"]))
    if mine.get("col") is None:
        theme.notify(t("map.boats.right_click_hex_you"), "info")
        return True
    arrival = (mine["col"], mine["row"])

    by_id = {p["id"]: p for p in STATE.characters()}
    chosen = [by_id[i] for i in (mine.get("travel_pcs") or []) if i in by_id]
    if not chosen:
        # Nobody chosen: those on the boat leave. It is the only sensible
        # answer, and it avoids that a stray click on the map makes the route
        # of a boat still in the middle of the river vanish.
        chosen = STATE.archive.characters_on_vehicle(sid)
        mine["travel_pcs"] = [p["id"] for p in chosen]
    vehicles = _markers._vehicles_in_play()
    view = _common._current_view(mine)
    difficulty = STATE.archive.campaign_difficulty(STATE.campaign)
    mine["aboard"] = True
    route = _route_by_river(mine, chosen, vehicles, view, difficulty,
                             departure, arrival, boat=entry, point=point,
                             drawn_one=drawn_one)
    mine["rendezvous"] = None
    mine["branches"] = []
    mine["singles"] = []
    mine["land"] = None
    mine["by_river"] = True
    mine["route"] = route
    if route is None:
        _common._forget_plan(mine)
        _journey._redraw_travel(mine, mapping)
        theme.notify(t("map.boats.from_there_there_one"), "warning")
        return True
    mine["plan"] = route["plan"]
    mine["path"] = list(route["path"])
    mine["arrival_pos"] = route.get("arrival_pos")
    # Where one really arrives is told by the route, not by the clicked hex:
    # aiming at a river running on the edge one ends up in the cell beside,
    # and that is right — but the box must write that one, not the other.
    if route["path"]:
        mine.update(col=route["path"][-1][0], row=route["path"][-1][1])
    _journey._redraw_travel(mine, mapping)
    return True

def _route_by_river(mine: dict, chosen: list[dict], vehicles: dict, view,
                     difficulty: dict, departure, arrival,
                     boat: dict | None = None, point=None,
                     drawn_one=None) -> dict | None:
    """The route along the water, if the party has a boat and the river reaches.

    It replaces nothing on its own: the land journey stays what is seen, and
    this appears alongside as a second possibility. Whoever plays chooses —
    sometimes the river is slower and is taken all the same, because on a
    boat one does not tire the same way, and that the app does not know.
    """
    if boat is not None:
        # With the boat in hand *it* is the traveller: the route is its own,
        # and does not depend on who boarded. Requiring it to be assigned to a
        # chosen character meant that deselecting the party made the route
        # vanish — and the boat was still there, in the middle of the river.
        vehicles_by_id = [boat]
    else:
        vehicles_by_id = [v for v in travel_mod.party_vehicles(chosen, vehicles)
                 if travel_mod.vehicle_kind(v) == "water" and v.get("available")]
        if not vehicles_by_id or not mine.get("aboard"):
            return None
    m = STATE.k["map"]
    network = _common.waters_network()
    if network.empty_one:
        return None
    currents = STATE.archive.campaign_currents(STATE.campaign)
    # From **where the boat is**: its junction. A boat without a junction
    # (from before this rule) still leaves from its hex.
    departure_node = waterways.vehicle_node(vehicles_by_id[0], m["orientation"], network)
    where_boat = travel_mod.where_it_is(vehicles_by_id[0])
    if departure_node is not None and where_boat is not None:
        departure = where_boat
    # If the hand left the arrow on a precise point, the route ends **there**:
    # inside a hex the water points are more than one, and stopping at the
    # wrong one means making a journey appear other than the one being looked
    # at.
    size = float(m["size"])
    origin_ = (float(m["origin_x"]), float(m["origin_y"]))
    found_one = None
    # First of all, the road the hand drew: it counts more than the cheapest,
    # because whoever followed the river with a finger does not want to see
    # it replaced by another. If it does not pass the check one falls back,
    # and says so.
    if drawn_one:
        states = _ruler.statuses_from_points(network, drawn_one, size, origin_,
                                m["orientation"])
        if states:
            found_one = travel_mod.route_along(network, currents, states,
                                              m["orientation"])
    arrival_node = None
    if found_one is None and point is not None:
        # Wide: one radius and a fifth, i.e. more than a hex. Whoever aims at
        # a river aims at the blue line, not at the center of the cell under
        # it — and the line may run on the edge, i.e. outside both the hexes
        # in sight.
        arrival_node = waterways.nearest_node(
            network, point, size, origin_, m["orientation"], threshold=size * 1.2)
    if found_one is None:
        found_one = travel_mod.route_towards(
            network, currents, departure, arrival, m["orientation"],
            arrival_node=arrival_node, departure_node=departure_node)
    if found_one is None and arrival_node is not None:
        # The point leads nowhere: fall back on the hex, which is the coarser
        # information but almost always good.
        found_one = travel_mod.route_towards(
            network, currents, departure, arrival, m["orientation"],
            departure_node=departure_node)
    if found_one is None:
        return None
    course, directions, road, steps = found_one
    if len(course) < 2:
        # The river touches the arrival hex but does not lead into it: better
        # not to offer a route ending somewhere else.
        return None
    speed, source, warnings = _ruler._party_pace(mine, chosen, vehicles)
    # The arithmetic is done by the route plan, not the land one: here one
    # pays what one sails — stretch by stretch — and not the hex one enters.
    # With a river running on the edge between two cells that cannot even be
    # said, and that is where the wobbly count came from.
    plan = travel_mod.route_plan(
        road, steps, speed, source, bool(mine.get("forced_march")),
        [int(p["con_mod"] or 0) for p in chosen])
    without = sum(1 for v in directions.values() if v is None)
    in_lake = sum(1 for v in directions.values() if v == "lake")
    plan.warnings = warnings + plan.warnings
    # The points it really passes through, to draw it: a grid vertex where
    # the water passes, the hex center where one floats in a lake.
    points = []
    for node, hexagon in road:
        try:
            points.append(waterways.node_point(node, size, origin_,
                                                 m["orientation"])
                         if node is not None
                         else hexgrid.hex_center(hexagon[0], hexagon[1], size,
                                                 origin_, m["orientation"]))
        except (IndexError, TypeError):
            continue
    # Where one **really** arrives: the last junction, in the frame of the
    # hex the route ends in. It is the boat's spot on arrival.
    last_node, last_hex = road[-1]
    arrival_pos = (waterways.unit_point_of_node(last_node, last_hex,
                                                    m["orientation"])
                   if last_node is not None else None)
    return {"path": list(course), "plan": plan, "directions": directions,
            "without_direction": without, "in_lake": in_lake, "points": points,
            "boat": travel_mod.vehicle_name_(vehicles_by_id[0]),
            "statuses": [(node, tuple(hexagon)) for node, hexagon in road],
            "arrival_pos": arrival_pos}

def _water_only_box(mine: dict, route: dict) -> None:
    """The detail of a route, when the journey is by water and nothing else.

    It says the things that matter *here* and nowhere else: how many hexes go
    downriver, how many upriver, how many are lake. The activities and the
    days are already said by the boxes above, and repeating them would add
    nothing.
    """
    directions = route.get("directions") or {}
    down = sum(1 for v in directions.values() if v == "downstream")
    su = sum(1 for v in directions.values() if v == "upstream")
    lake = sum(1 for v in directions.values() if v == "lake")
    unknowns = sum(1 for v in directions.values() if v is None)
    theme.sep()
    with ui.row().classes("items-center gap-2 flex-wrap"):
        ui.html('<span style="font-size:.82rem">⛵ <b>' + t("map.boats.route_of", boat=theme.esc(route["boat"])) + '</b></span>')
    with ui.row().classes("items-center gap-2 flex-wrap"):
        for how_many, label, color in (
                (down, t("map.boats.downstream"), "var(--km-gold)"),
                (su, t("map.boats.upstream"), "var(--km-red)"),
                (lake, t("map.boats.lake"), _drawing.LAKE_COLOR),
                (unknowns, t("map.boats.without_direction"), "var(--km-muted)")):
            if not how_many:
                continue
            ui.html(f'<span class="km-chip" style="font-size:.68rem;'
                    f'border-color:{color}">{how_many} {theme.esc(label)}</span>')
    ui.label(t("map.boats.downstream_open_terrain_upstream")) \
        .style("font-size:.74rem;color:var(--km-muted);white-space:normal")

def _take_route(mine: dict, mapping, by_river: bool) -> None:
    """Switches from the land journey to the river one, or back."""
    route = mine.get("route")
    if by_river and route is None:
        return
    if by_river:
        mine["land"] = {"plan": mine.get("plan"),
                        "path": list(mine.get("path") or [])}
        mine["plan"] = route["plan"]
        mine["path"] = list(route["path"])
        mine["arrival_pos"] = route.get("arrival_pos")
        # A route is a single journey: rendezvous and separate journeys spoke
        # of the other course, and leaving them on would show two different
        # roads.
        mine["rendezvous"] = None
        mine["branches"] = []
        mine["singles"] = []
    else:
        back = mine.get("land") or {}
        mine["plan"] = back.get("plan")
        mine["path"] = list(back.get("path") or [])
    mine["by_river"] = bool(by_river)
    _journey._redraw_travel(mine, mapping)

def _route_box(mine: dict, mapping) -> None:
    """The choice between land and river, with the two figures side by side."""
    route = mine.get("route")
    if route is None:
        return
    if mine.get("travel_vehicle"):
        _water_only_box(mine, route)
        return
    by_river = bool(mine.get("by_river"))
    ashore = (mine.get("land") or {}).get("plan") if by_river else mine.get("plan")
    theme.sep()
    with ui.row().classes("items-center gap-2 flex-wrap"):
        ui.html(t("map.boats.span_style_font_size"))
        days = route["plan"].days if route["plan"].possible else None
        ui.html(f'<span class="km-chip" style="font-size:.68rem">'
                f'{days if days is not None else "—"} '
                f'{"day" if days == 1 else "days"}</span>')
        if ashore is not None and ashore.possible and days is not None:
            offset_ = days - ashore.days
            text = (t("map.boats.same_days_land") if offset_ == 0 else
                     f'{abs(offset_)} {"day" if abs(offset_) == 1 else "days"}'
                     + (t("map.boats.more") if offset_ > 0 else t("map.boats.less")) + t("map.boats.than_land"))
            ui.html(f'<span class="km-chip" style="font-size:.68rem;'
                    f'border-color:var(--km-gold-dim)">{theme.esc(text)}</span>')
        ui.element("div").style("flex:1")
        if by_river:
            ui.button(t("map.boats.go_back_land"), icon="undo",
                      on_click=lambda: _take_route(mine, mapping, False)) \
                .props("dense flat color=grey")
        else:
            ui.button(t("map.boats.take_river"), icon="sailing",
                      on_click=lambda: _take_route(mine, mapping, True)) \
                .props("dense color=teal")
    ui.label(t("map.boats.following_water_drawn_map", boat=route["boat"], v=len(route["path"]) - 1)
             + tn("map.boats.hexes", len(route["path"]) - 1)
             + ". " + t("map.boats.current_note")) \
        .style("font-size:.74rem;color:var(--km-muted);white-space:normal")

def _navigable_water(coord) -> bool:
    """Whether a boat fits in that hex: there is drawn water, or it is lake."""
    coord = (int(coord[0]), int(coord[1]))
    if coord in STATE.archive.lake_cells(STATE.campaign):
        return True
    return bool(waterways.hex_nodes(_common.waters_network(), coord))

def _all_water(coord) -> bool:
    """Whether that hex is water and nothing else: a lake, or a water terrain.

    It is the foot's question, not the boat's: from a wagon one does not get
    off into a lake, and a boat is not pulled onto a meadow. The answer comes
    from the hex terrains — which the rules mark `water` — and from the drawn
    lakes.
    """
    coord = (int(coord[0]), int(coord[1]))
    if coord in STATE.archive.lake_cells(STATE.campaign):
        return True
    hexagon = STATE.existing_hex(coord[0], coord[1])
    terrains = (hexagon or {}).get("terrains") or []
    entries = [travel_mod.TERRAINS.get(x) or {} for x in terrains]
    return bool(entries) and all(v.get("water") for v in entries)

def _nearest_atom_point(unit, orient: str):
    """The inner point of the atom nearest to `unit` (radii from the center):
    a place inside a piece, never on a water line."""
    return min((tuple(face.point) for face in atoms_mod.atoms(orient)),
               key=lambda p: (p[0] - unit[0]) ** 2 + (p[1] - unit[1]) ** 2)


def ashore_spot(coord, spot, orient: str | None = None) -> tuple[tuple[int, int], tuple[float, float]]:
    """Where whoever is left by a boat sets foot: `(hex, point)`.

    A boat sits on a water junction — a corner, the center, a point where
    lines meet — and whoever stayed aboard when it went back to the depot
    was left exactly there, on the water line, or in the middle of a lake:
    a place no journey starts from. Here they go to the inner point of the
    **nearest atom** of the same hex; when the hex is all water (a lake, a
    water terrain) to the nearest atom of the nearest neighbour that has dry
    ground, measured in pixels from where the boat was.
    """
    m = STATE.k["map"]
    orient = orient or m["orientation"]
    coord = (int(coord[0]), int(coord[1]))
    here = (0.0, 0.0) if spot is None or spot[0] is None else (float(spot[0]), float(spot[1]))
    if not _all_water(coord):
        return coord, _nearest_atom_point(here, orient)
    size = float(m["size"])
    origin = (float(m["origin_x"]), float(m["origin_y"]))
    cx, cy = hexgrid.hex_center(coord[0], coord[1], size, origin, orient)
    px, py = cx + here[0] * size, cy + here[1] * size
    on_map = _common.inside_map(m)
    best = None
    for other in hexgrid.neighbours(coord[0], coord[1], orient):
        other = (int(other[0]), int(other[1]))
        if not on_map(other) or _all_water(other):
            continue
        nx, ny = hexgrid.hex_center(other[0], other[1], size, origin, orient)
        point = _nearest_atom_point(((px - nx) / size, (py - ny) / size), orient)
        distance = (nx + point[0] * size - px) ** 2 + (ny + point[1] * size - py) ** 2
        if best is None or distance < best[0]:
            best = (distance, other, point)
    if best is None:
        return coord, _nearest_atom_point(here, orient)
    return best[1], best[2]


def _no_landing(entry: dict, coord) -> str | None:
    """Why one does not set foot there. None = one does.

    From a boat one lands **ashore**: inside a lake there is nothing to step
    onto, and the boat must first be brought to the edge. From a wagon one
    does not get off into water, for the same reason the other way round.
    """
    coord = (int(coord[0]), int(coord[1]))
    if not _all_water(coord):
        return None
    if travel_mod.vehicle_kind(entry) == "water":
        return (t("map.boats.open_water_from_boat", coord=coord[0], coord2=coord[1]))
    return (t("map.boats.water_from_there_one", coord=coord[0], coord2=coord[1]))

def _where_it_does_not_fit(entry: dict, coord) -> str | None:
    """Why that vehicle is not placed there. None = it is.

    A boat goes where the water really is — on the drawn river or inside a
    lake — because from a meadow no route would start and nobody would
    understand why. A wagon does the opposite: it does not fit in the lake.
    Whoever flies goes anywhere, and is the only one with nothing to ask.
    """
    coord = (int(coord[0]), int(coord[1]))
    kind = travel_mod.vehicle_kind(entry)
    if kind == "water" and not _navigable_water(coord):
        return (t("map.boats.there_no_drawn_water"))
    if kind == "land" and _all_water(coord):
        return (t("map.boats.water_land_vehicle_cannot", coord=coord[0], coord2=coord[1]))
    return None

def _placing_done(mine: dict) -> None:
    """The pointer goes back to saying what the mode says now.

    Changing the mode is not enough: the cursor lives in a style written on
    the image, and until it is rewritten the browser keeps the last. It must
    be called from **every** exit from «place» — placing a vehicle, placing a
    marker, letting someone off — because it is always the same defect.
    """
    if mine.get("apply_slider"):
        mine["apply_slider"]()

def _place_vehicle(mine: dict, mapping, coord, point=None) -> None:
    """Puts a vehicle on the map, and brings along whoever is already on it.

    The right place depends on where that vehicle goes — the water for a
    boat, the land for a wagon — but the gesture is the same for all, and
    that is the point: a vehicle is in a hex, and there one boards it.
    """
    sid = mine.get("place_vehicle")
    entry = STATE.archive.stable_vehicle(sid) if sid else None
    if entry is None:
        mine["travel_mode"] = None
        mine["place_vehicle"] = None
        _placing_done(mine)
        return
    if not permissions.can(theme.user(), permissions.MANAGE_STABLE):
        theme.notify(t("map.boats.you_do_not_have"), "negative")
        return
    if travel_mod.vehicle_kind(entry) == "water":
        # A boat sits on a water **junction**: it is placed by clicking near
        # one — a corner, the center, or a point where two lines meet — and
        # the hex is the junction's.
        found = _junction_under(point, coord=coord)
        if found is None:
            theme.notify(t("map.boats.there_no_water_stop"),
                           "warning")
            return
        coord, spot = found
    else:
        why = _where_it_does_not_fit(entry, coord)
        if why:
            theme.notify(why, "warning")
            return
        # The shore is told by the exact point of the click, as for a
        # character: a wagon stopped at a ford is on this or that side of the
        # water, and whoever gets off ends up on the same side.
        spot = _journey._spot_from_point(coord, point)
    STATE.archive.update_stable_vehicle(
        sid, hex_col=int(coord[0]), hex_row=int(coord[1]),
        pos_x=None if spot is None else spot[0],
        pos_y=None if spot is None else spot[1])
    # Whoever was already aboard goes where the vehicle is: they boarded, they
    # are not waiting for it ashore.
    boarded = _bring_aboard(sid, coord, spot)
    name = travel_mod.vehicle_name_(entry)
    STATE.record(t("map.boats.placed", name=name, coord=coord[0], coord2=coord[1]), "map")
    # We stay in Travel, we do not leave: after putting a vehicle on the map
    # the thing one wants to do is click it and leave, and closing the mode
    # would mean reopening it at once.
    mine["travel_mode"] = "choose"
    mine["place_vehicle"] = None
    _placing_done(mine)
    theme.notify(
        t("map.boats.text", name=name, coord=coord[0], coord2=coord[1])
        + (t("map.boats.aboard_short", names=boarded) if boarded else
           t("map.boats.now_get_whoever_that")),
        "positive")
    theme.save_and_refresh()
    _journey._redraw_travel(mine, mapping)
    theme.refresh_panels(("hexmap.map", "party.characters",
                             "transport.list"))

def _junction_under(point, threshold: float | None = None, coord=None):
    """The water junction near the click: `(hex, spot)`, or None.

    The hex is the one the junction belongs to — for a corner, the one of the
    three containing the click, if it contains it, or the first — and the
    spot is the junction's point in radii from the center of that hex.
    Without a point — the vehicle comes from a tab, not a click — the center
    of the requested hex applies.
    """
    m = STATE.k["map"]
    size = float(m["size"])
    origin = (float(m["origin_x"]), float(m["origin_y"]))
    orient = m["orientation"]
    if point is None:
        if coord is None:
            return None
        point = hexgrid.hex_center(int(coord[0]), int(coord[1]), size, origin,
                                   orient)
    network = _common.waters_network()
    if network.empty_one:
        return None
    node = waterways.nearest_node(network, point, size, origin, orient,
                                    threshold=size * 0.6 if threshold is None else threshold)
    if node is None:
        return None
    in_the = _common.inside_map(m)
    hexes = [tuple(c) for c in waterways.node_hexes(node, orient) if in_the(c)]
    if not hexes:
        return None
    clicked = hexgrid.pixel_to_hex(point[0], point[1], size, origin, orient)
    coord = tuple(clicked) if tuple(clicked) in hexes else hexes[0]
    spot = waterways.unit_point_of_node(node, coord, orient)
    return (coord, spot) if spot is not None else None

def _boat_node(entry: dict):
    """The junction a water vehicle sits on, or None (land vehicle, or old boat)."""
    if not _markers._is_a_vehicle(entry) or travel_mod.vehicle_kind(entry) != "water":
        return None
    return waterways.vehicle_node(entry, STATE.k["map"]["orientation"])

def _bring_aboard(sid: str, coord, where=None) -> str:
    """Moves whoever is on it to where the vehicle is. Returns the names, to say so."""
    names = []
    for char in STATE.archive.characters_on_vehicle(sid):
        STATE.archive.update_character(
            char["id"], hex_col=int(coord[0]), hex_row=int(coord[1]),
            pos_x=None if where is None else where[0],
            pos_y=None if where is None else where[1])
        names.append(char["name"])
    return ", ".join(sorted(names))

def _board(mine: dict, mapping, sid: str, char_ids) -> None:
    """Boards whoever is in the vehicle's hex. Not the others, and says so.

    The check is one — one boards what is in front of one — and lives in
    `travel.ascent_blocked`, which is a pure function and knows nothing of
    the interface. Here only who one has the right to move is looked at: the
    dropdown not showing other people's characters is not a defence.
    """
    entry = STATE.archive.stable_vehicle(sid) if sid else None
    if entry is None:
        return
    user = theme.user()
    boarded, rejected = [], []
    for char_id in list(char_ids or []):
        char = STATE.archive.character(char_id)
        if char is None or not permissions.can_on_character(user, char):
            continue
        if (char.get("stable_id") or "") == sid:
            continue
        why = travel_mod.ascent_blocked(
            char, entry, _common.sections_map(), STATE.k["map"]["orientation"])
        if why:
            rejected.append(why)
            continue
        # A character is on a single vehicle: boarding here means getting off
        # where they were, and the single field does it by itself. And they
        # are **where the vehicle is**: same hex and same spot — a boat stopped
        # at a corner is boarded from the neighbouring hex too, and from
        # there one moves.
        where_vehicle = travel_mod.where_it_is(entry)
        STATE.archive.update_character(
            char_id, stable_id=sid, hex_col=where_vehicle[0], hex_row=where_vehicle[1],
            pos_x=entry.get("pos_x"), pos_y=entry.get("pos_y"))
        boarded.append(char["name"])
    if boarded:
        name = travel_mod.vehicle_name_(entry)
        STATE.record(t("map.boats.aboard", name=name, join=", ".join(sorted(boarded))), "map")
        theme.notify(t("map.boats.aboard_2", name=name, join=", ".join(sorted(boarded))),
                       "positive")
        if mine.get("travel_vehicle") == sid:
            mine["travel_pcs"] = [p["id"] for p in
                                 STATE.archive.characters_on_vehicle(sid)]
    for why in rejected:
        theme.notify(why, "warning")
    if boarded:
        theme.save_and_refresh()
        _journey._redraw_travel(mine, mapping)
        theme.refresh_panels(("hexmap.map", "party.characters",
                                 "transport.list"))

def _ask_landing(mine: dict, mapping, sid: str, char_ids) -> None:
    """Opens the question «where do you land»: the answer is a click on the map.

    Letting someone off **where the vehicle is** seemed the obvious thing,
    and it is not: from a wagon stopped at a ford one gets off on this or that
    side of the river, from a boat one lands ashore and the shore has two
    sides. Declaring it costs a click and removes a whole category of «I did
    not mean there».
    """
    if not char_ids:
        theme.notify(t("map.boats.there_nobody_let_off"), "warning")
        return
    # If any of them is already on the way, letting them off means stopping
    # that journey: it is something to ask before, not to find out after.
    en_route = _journey.journeys_by_character(set(char_ids))
    if en_route:
        _confirm_landing_while_travelling(mine, mapping, sid, char_ids, en_route)
        return
    _arm_landing(mine, mapping, sid, char_ids)

def _must_declare_where(entry: dict) -> bool:
    """Whether getting off this vehicle requires saying **where**.

    Only for water. A boat sits on the water, and the water of a hex can run
    on the **edge** between two cells: from there one lands on this or that
    side, and which of the two nobody knows but the player.

    Not from a wagon: the wagon is in a hex, on a precise shore, and whoever
    gets off sets foot next to the wagon. Asking anyway meant letting people
    be unloaded in a neighbouring hex, which is something a stopped wagon
    does not do.
    """
    return travel_mod.vehicle_kind(entry) == "water"

def _confirm_landing_while_travelling(mine: dict, mapping, sid: str, char_ids,
                                en_route: dict) -> None:
    """Asks before stopping a journey already under way.

    Getting off a vehicle while on the road is not a detail to be settled in
    silence: that journey can no longer be made, and cancelling it without
    saying so would be the same as doing it on the sly.
    """
    names = {p["id"]: p["name"] for p in STATE.characters()}
    journeys = {v["id"]: v for v in en_route.values()}
    who = ", ".join(sorted(names.get(i, "?") for i in en_route))
    with theme.dialog() as dlg, ui.card().classes("km-panel"):
        theme.title(t("map.boats.stop_journey"), 2)
        how_many = len(journeys)
        ui.label(f'{who} '
                 + (t("map.boats.text_2") if len(en_route) == 1 else t("map.boats.are"))
                 + t("map.boats.already_way_getting_off")
                 + (t("map.boats.that_journey_cancelled") if how_many == 1
                    else t("map.boats.those_journeys_cancelled", n=how_many)))             .style("white-space:normal")
        ui.label(t("map.boats.whoever_was_way_stays"))             .style("font-size:.78rem;color:var(--km-muted);white-space:normal")

        def go() -> None:
            for journey in journeys.values():
                STATE.archive.update_journey(
                    journey["id"], status="cancelled",
                    turn_resolved=STATE.k["turn"])
                STATE.record(t("map.boats.journey_cancelled_somebody_got", arrival=journey["arrival"]), "map")
            mine["chosen_journey"] = None
            theme.refresh_panels(("hexmap.map", "hexmap.travel",
                                     "turn.journeys"))
            dlg.close()
            _arm_landing(mine, mapping, sid, char_ids)

        with ui.row().classes("justify-end w-full"):
            ui.button(t("map.boats.leave"), on_click=dlg.close).props("flat")
            ui.button(t("map.boats.cancel_journey_get_off"), on_click=go) \
                .props("color=red")
    dlg.open()

def _arm_landing(mine: dict, mapping, sid: str, char_ids) -> None:
    """Lets people off, asking where only when the question makes sense."""
    entry = STATE.archive.stable_vehicle(sid) if sid else None
    if entry is None:
        return
    if not _must_declare_where(entry):
        # From a wagon one gets off next to the wagon, on its same shore:
        # there is nothing to choose, and one more click would be just one
        # more click (with the chance of getting it wrong).
        where = travel_mod.where_it_is(entry)
        mine["landing"] = {"sid": sid, "char_ids": list(char_ids)}
        _land_here(mine, mapping, where, sections.saved_spot(entry))
        return
    mine["travel_mode"] = "place"
    mine["landing"] = {"sid": sid, "char_ids": list(char_ids)}
    mine["place_vehicle"] = None
    mine["place_pc"] = None
    if mine.get("apply_slider"):
        mine["apply_slider"]()
    _journey._redraw_travel(mine, mapping)

def _land_here(mine: dict, mapping, coord, spot=None) -> None:
    """They land there, if one lands there.

    `spot` is passed by whoever already knows it — from a wagon one gets off
    where the wagon is. Clicking, the point of the click says it instead.
    """
    requested = mine.get("landing") or {}
    sid = requested.get("sid")
    entry = STATE.archive.stable_vehicle(sid) if sid else None
    if entry is None:
        mine["landing"] = None
        mine["travel_mode"] = "choose"
        _placing_done(mine)
        return
    why = travel_mod.descent_blocked(
        entry, coord, STATE.k["map"]["orientation"],
        landing_spot=lambda c: _no_landing(entry, c),
        banks=_common.sections_map(), spot=spot)
    if why:
        theme.notify(why, "warning")
        return
    user = theme.user()
    disembarked = []
    for char_id in requested.get("char_ids") or []:
        char = STATE.archive.character(char_id)
        if char is None or not permissions.can_on_character(user, char):
            continue
        STATE.archive.update_character(
            char_id, stable_id=None, hex_col=int(coord[0]), hex_row=int(coord[1]),
            pos_x=None if spot is None else spot[0],
            pos_y=None if spot is None else spot[1])
        disembarked.append(char["name"])
    mine["landing"] = None
    mine["travel_mode"] = "choose"
    _placing_done(mine)
    # The journey being looked at belonged to that group on that vehicle:
    # whoever gets off no longer makes it, and leaving it drawn with its
    # buttons below means offering a journey that cannot be made — «Depart»
    # stayed there and nothing departed.
    _common._forget_plan(mine)
    if mine.get("travel_vehicle") == sid:
        mine["travel_pcs"] = [p["id"] for p in
                             STATE.archive.characters_on_vehicle(sid)]
    if not disembarked:
        theme.notify(t("map.boats.nobody_got_off_they"),
                       "warning")
        return
    name = travel_mod.vehicle_name_(entry)
    text = ", ".join(sorted(disembarked))
    verb = t("map.boats.gets_off") if len(disembarked) == 1 else t("map.boats.get_off_plural")
    STATE.record(t("map.boats.got_off", name=name, coord=coord[0], coord2=coord[1], text=text), "map")
    theme.notify(t("map.boats.text_3", text=text, verb=verb, coord=coord[0], coord2=coord[1]), "positive")
    theme.save_and_refresh()
    _journey._redraw_travel(mine, mapping)
    theme.refresh_panels(("hexmap.map", "party.characters",
                             "transport.list"))

def _choose_vehicle(mine: dict, mapping, entry: dict) -> None:
    """Takes a vehicle in hand: from here on one travels with it."""
    if not permissions.can(theme.user(), permissions.PLAN_TRAVEL):
        return
    if mine.get("travel_vehicle") == entry["id"]:
        mine["travel_vehicle"] = None
        mine["travel_pcs"] = []
    else:
        mine["travel_vehicle"] = entry["id"]
        # Whoever is aboard leaves with it: it is the only sensible answer to
        # the question «who travels on this vehicle».
        mine["travel_pcs"] = [p["id"] for p in
                             STATE.archive.characters_on_vehicle(entry["id"])]
        mine["aboard"] = True
    _common._forget_plan(mine)
    mine["col"] = mine["row"] = None
    _journey._redraw_travel(mine, mapping)
