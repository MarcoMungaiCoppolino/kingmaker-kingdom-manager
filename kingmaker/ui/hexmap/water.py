"""The Waters box and its brushes: stretches, bridges and fords, currents, lakes, eraser, image reading, charts.

It used to live in `ui/hexmap.py`; the `hexmap` facade still re-exports everything.
"""
from __future__ import annotations

import logging
import json
import math
import uuid
from nicegui import ui
from kingmaker.state import STATE
from kingmaker.ui import theme
from kingmaker.water import reading as water_reading, chart as water_chart
from kingmaker.geometry import waterways, hexgrid, sections
from kingmaker import config
from kingmaker.access import permissions

from kingmaker.ui.hexmap import common as _common
from kingmaker.ui.hexmap import drawing as _drawing
from kingmaker.locale.i18n import t, tn

log = logging.getLogger(__name__)


# The brushes of the Waters box: for each, what a click on the map does. They
# receive the window, the event, the point in pixels and the redraw function.
def _refresh_waters(mine: dict) -> None:
    if mine.get("waters"):
        mine["waters"].refresh()

def _color_brush(mine: dict, e, point, draw) -> None:
    """The GM points at what the water looks like *on this map*. The point is
    kept and not the colour: so a re-reading looks at today's image."""
    points = STATE.k["map"].setdefault("water_samples", [])
    points.append([round(point[0], 1), round(point[1], 1)])
    theme.mark_dirty()
    theme.notify(t("map.water.colour_picked", len=len(points), v=tn("common.point_word", len(points))), "positive")
    _refresh_waters(mine)

def _lake_brush(mine: dict, e, point, draw) -> None:
    _lake_point(mine, point)
    draw()
    _refresh_waters(mine)

def _current_brush(mine: dict, e, point, draw) -> None:
    # With ctrl one removes instead of marking — or with the direction eraser
    # on, which is the same thing without needing the keyboard.
    if e.ctrl or mine.get("remove_direction"):
        _remove_direction_under(mine, point)
    else:
        _current_direction(mine, point)
    draw()
    _send_network(mine)
    _refresh_waters(mine)

def _water_brush(mine: dict, e, point, draw) -> None:
    """Water: two points of the same hex. Bridge and Ford: **one click on the
    water line** to hop over — the two-point gesture belongs to Water only."""
    if mine["border_mode"] != "water":
        mine["cut_in_progress"] = None
        if not _crossing_under(point, mine["border_mode"]):
            theme.notify(
                t("map.water.click_water_line_hop", BORDER_NAMES=border_name(mine['border_mode'])), "warning")
    else:
        _cut_hex(mine, point)
    draw()
    _refresh_waters(mine)

def _eraser_brush(mine: dict, e, point, draw) -> None:
    """The eraser does not look at the hex: it looks at which line is under it."""
    if _erase_under(point):
        theme.mark_dirty()
        draw()
        _refresh_waters(mine)

_BRUSHES = {"color": _color_brush, "lake": _lake_brush,
             "current": _current_brush, "water": _water_brush,
             "ford": _water_brush, "bridge": _water_brush,
             "land": _eraser_brush}

# --------------------------------------------------------------------------
# The «Waters» box: everything needed to mark the water, in the place where
# one looks at the map. Before, half of it sat in the bar above the map and
# half in the GM screen tab, and to use it one had to know they were the same
# thing.
# What comes out of each brush on the edge between two hexes is called, out
# loud. Needed to say it in the notification: «Bridge between 9,4 and 10,4».
BORDER_NAMES = {"water": "map.water.water_border", "ford": "map.water.ford", "bridge": "map.water.bridge"}


def border_name(kind: str) -> str:
    """The name of what a brush leaves on the edge, in the viewer's language."""
    return t(BORDER_NAMES[kind]) if kind in BORDER_NAMES else kind

BRUSHES = (("water", "map.water.water", "water", "blue"),
            ("ford", "map.water.ford", "waves", "cyan"),
            ("bridge", "map.water.bridge", "commit", "amber"),
            # The current draws no water: it reads it. It sits with the others
            # because it is the last gesture of drawing a river — first where
            # it runs, then which way it goes.
            ("current", "map.water.current", "double_arrow", "teal"),
            # The lake is not a line: it is what the lines close. It sits with
            # the brushes all the same, because it is the last gesture of
            # drawing the water — after where it runs and which way it goes,
            # what shape it has.
            ("lake", "map.water.lake", "water_drop", "light-blue"),
            # `auto_fix_normal` and not `ink_eraser`: the latter is in the
            # Material *Symbols*, and the page loads the Material *Icons*. A
            # name the font does not have leaves no hole: it prints the
            # string, and that is why the button had no icon.
            ("land", "map.water.eraser", "auto_fix_normal", "grey"))

def _water_panel(mine: dict, mapping) -> None:
    if not permissions.can(theme.user(), permissions.SEE_SECRETS):
        return
    if not mine.get("water_mode"):
        return                      # outside the mode it is useless

    m = STATE.k["map"]
    samples = m.get("water_samples") or []
    if not _common.waters_active():
        with ui.card().classes("km-panel w-full"):
            theme.title(t("map.water.waters"), 2)
            ui.label(t("map.water.water_borders_are_off")) \
                .style("color:var(--km-muted);font-size:.8rem")
            ui.label(t("map.water.what_you_already_marked")) \
                .style("color:var(--km-gold-dim);font-size:.76rem")
            ui.switch(t("map.water.use_water_borders"), value=False,
                      on_change=lambda e: _change_waters(mine, mapping, e.value)) \
                .props("dense color=amber")
        return
    borders = STATE.archive.campaign_borders(STATE.campaign)
    by_hand = sum(1 for v in borders.values() if v.get("source") != "traced")
    read_ones = len(borders) - by_hand
    cut_ones = len(STATE.archive.campaign_banks(STATE.campaign))
    inside_hex = [v for entries in
                      STATE.archive.campaign_crossings(STATE.campaign).values()
                      for v in entries]
    inner_crossings = len(inside_hex)
    inner_fords = sum(1 for v in inside_hex
                        if (v.get("kind") or "bridge") == "ford")

    with ui.card().classes("km-panel w-full"):
        with ui.row().classes("items-center gap-2 w-full no-wrap"):
            theme.title(t("map.water.waters"), 2)
            ui.element("div").style("flex:1")
            ui.html(t("map.water.span_class_km_chip_2", len=len(borders)))
            if cut_ones:
                ui.html(f'<span class="km-chip" style="font-size:.68rem">'
                        f'{t("map.water.cut_count", n=cut_ones)}</span>')
            if inner_crossings:
                ui.html(t("map.water.span_class_km_chip", inner_crossings=inner_crossings)
                        + (t("map.water.fordable", inner_fords=inner_fords) if inner_fords else '')
                        + '</span>')

        ui.label(t("map.water.river_does_not_sit")) \
            .style("color:var(--km-muted);font-size:.78rem")
        ui.label(t("map.water.not_rule_book_rules")) \
            .style("color:var(--km-gold-dim);font-size:.74rem")
        ui.switch(t("map.water.use_water_borders"), value=True,
                  on_change=lambda e: _change_waters(mine, mapping, e.value)) \
            .props("dense color=amber") \
            .tooltip(t("map.water.switching_them_off_travel"))

        # ---------------------------------------------------------- brush
        theme.sep()
        active = mine.get("border_mode")
        if active in ("water", "ford", "bridge"):
            in_progress = mine.get("cut_in_progress")
            if active == "water":
                ui.label(t("map.water.join_two_points_same")) \
                    .style("font-size:.76rem")
                ui.label(t("map.water.center_hex_counts_too")) \
                    .style("font-size:.74rem;color:var(--km-gold-dim);"
                           "white-space:normal")
            elif active == "bridge":
                ui.label(t("map.water.click_water_line_hop_2")) \
                    .style("font-size:.76rem")
            else:
                ui.label(t("map.water.click_water_line_ford")) \
                    .style("font-size:.76rem")
            if active != "water":
                pass
            elif in_progress:
                which_ones = sorted({f"{c[0]},{c[1]}"
                                for c, _k in in_progress["owners"]})
                ui.label(t("map.water.first_vertex_taken_click")
                         + " o ".join(which_ones) + ".") \
                    .style("font-size:.74rem;color:var(--km-gold)")
            else:
                ui.label(t("map.water.click_near_vertex_nearest")) \
                    .style("font-size:.74rem;color:var(--km-gold-dim)")
        elif active == "land":
            ui.label(t("map.water.eraser_hold_down_pass")) \
                .style("font-size:.76rem")
        elif active == "current":
            directions = STATE.archive.campaign_currents(STATE.campaign)
            ui.label(t("map.water.which_way_water_flows")) \
                .style("font-size:.76rem")
            ui.label(t("map.water.needed_because_rules_make")) \
                .style("font-size:.74rem;color:var(--km-gold-dim);white-space:normal")
            ui.label(t("map.water.remove_single_one_there")) \
                .style("font-size:.74rem;color:var(--km-gold-dim);"
                       "white-space:normal")
            if mine.get("remove_direction"):
                ui.label(t("map.water.direction_eraser_click_stretches")) \
                    .style("font-size:.74rem;color:var(--km-gold)")
            if mine.get("current_from") is not None:
                ui.label(t("map.water.upstream_taken_move_mouse")) \
                    .style("font-size:.74rem;color:var(--km-gold)")
            with ui.row().classes("items-center gap-2 flex-wrap"):
                ui.html(f'<span class="km-chip" style="font-size:.68rem">'
                        f'{len(directions)} '
                        f'{t("map.water.stretch_direction") if len(directions) == 1 else t("map.water.stretches_direction")}'
                        f'</span>')
                if directions:
                    army = bool(mine.get("remove_direction"))
                    (ui.button(t("map.water.remove_direction"), icon="backspace",
                               on_click=lambda: _toggle_remove_direction(mine, mapping))
                     .props("dense size=sm "
                            + ("color=teal" if army else "flat color=grey"))
                     .tooltip(t("map.water.every_click_removes_direction")))
                    (ui.button(t("map.water.remove_all_directions"), icon="delete_sweep",
                               on_click=lambda: _forget_currents(mine, mapping))
                     .props("dense flat size=sm color=grey"))
        elif active == "lake":
            _lakes_box(mine, mapping)
        else:
            ui.label(t("map.water.pick_brush_water_you")) \
                .style("font-size:.76rem")
        with ui.row().classes("gap-2 flex-wrap"):
            for tid, label, icon, color in BRUSHES:
                label = t(label)
                ui.button(label, icon=icon,
                          on_click=lambda _e, x=tid: _brush(mine, mapping, x)) \
                    .props("dense " + (f"color={color}" if active == tid
                                       else "flat color=grey"))

        # ------------------------------------------------- colour of the water
        theme.sep()
        with ui.row().classes("items-center gap-2 flex-wrap"):
            ui.button(t("map.water.pick_water_colour", len=len(samples)),
                      icon="colorize",
                      on_click=lambda: _brush(mine, mapping, "color")) \
                .props("dense " + ("color=teal" if active == "color"
                                   else "flat color=grey"))
            if samples:
                ui.button(icon="backspace",
                          on_click=lambda: _forget_color(mine)) \
                    .props("dense flat round size=sm color=grey") \
                    .tooltip(t("map.water.forget_picked_points"))
        if active == "color":
            ui.label(t("map.water.click_middle_lake_wide")) \
                .style("font-size:.74rem;color:var(--km-gold-dim)")

        # ------------------------------------------------------- the reading
        theme.sep()
        with ui.row().classes("items-center gap-2 flex-wrap"):
            ui.button(t("map.water.read_map"), icon="travel_explore",
                      on_click=lambda: _read_waters(mine, mapping)) \
                .props("dense color=amber" if samples else "dense flat color=grey")
            if read_ones:
                ui.html(t("map.water.span_class_km_chip_3", read_ones=read_ones, by_hand=by_hand))
        if not samples:
            ui.label(t("map.water.first_pick_water_colour")) \
                .style("font-size:.74rem;color:var(--km-gold-dim)")

        _reading_result(mine, mapping)

        # ------------------------------------------------- taking it away and bringing it back
        theme.sep()
        ui.label(t("map.water.water_chart")) \
            .style("font-size:.78rem;color:var(--km-gold)")
        ui.label(t("map.water.file_every_river_drawn")) \
            .style("font-size:.74rem;color:var(--km-gold-dim);white-space:normal")
        with ui.row().classes("gap-2 flex-wrap items-center"):
            ui.button(t("map.water.download_chart"), icon="download",
                      on_click=_download_chart) \
                .props("dense " + ("color=amber" if (borders or cut_ones)
                                   else "flat color=grey")) \
                .tooltip(t("map.water.borders_banks_crossings_json"))
        ui.upload(label=t("map.water.load_water_chart_json"),
                  on_upload=lambda e: _load_chart(mine, mapping, e),
                  auto_upload=True, max_file_size=MAX_CHART_BYTES) \
            .props("accept=.json,application/json").classes("w-full")

        _chart_result(mine, mapping)

        # ---------------------------------------------------------- cleanup
        if borders or cut_ones:
            theme.sep()
            with ui.row().classes("gap-2 flex-wrap"):
                ui.button(t("map.water.erase_all_water"), icon="delete_sweep",
                          on_click=lambda: _confirm_cleanup(mine, mapping,
                                                             len(borders), by_hand)) \
                    .props("dense flat color=red") \
                    .tooltip(t("map.water.borders_banks_together"))

def _dist_from_segment(point, a, b) -> float:
    """How far a point is from a segment, not from the line containing it."""
    px, py = point
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    along = dx * dx + dy * dy
    if along < 1e-9:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / along))
    return math.hypot(px - (ax + dx * t), py - (ay + dy * t))

@theme.requires(permissions.SEE_SECRETS)
def _erase_under(point) -> int:
    """Removes every water line passing under that point. How many it removed.

    A line is erased by passing over it, and «over» means near the
    *segment*: before, the rule was «near the hex center», which covered less
    than half the length of a cut — on the rest nothing happened, and from
    outside it looked like a broken button.
    """
    m = STATE.k["map"]
    size = float(m["size"])
    origin = (float(m["origin_x"]), float(m["origin_y"]))
    orient = m["orientation"]
    threshold = max(size * 0.13, 6.0)
    candidate = []

    # the side nearest to the point, if marked
    here, la = hexgrid.nearest_side(point[0], point[1], size, origin, orient)
    if (0 <= la[0] < int(m["columns"])) and (0 <= la[1] < int(m["rows"])):
        if hexgrid.border_key(here, la) in STATE.archive.campaign_borders(
                STATE.campaign):
            side = hexgrid.shared_side(here, la, size, origin, orient)
            if side:
                candidate.append((_dist_from_segment(point, *side), 1,
                                  ("border", here, la)))

    # the cuts of the hex under the point and of its neighbours: a cut reaches
    # the vertices, and there the point may already be in the next hex.
    banks = STATE.archive.campaign_banks(STATE.campaign)
    sections_now = _common.sections_map()
    drawn_ones = STATE.archive.bank_points(STATE.campaign)
    crossings = STATE.archive.campaign_crossings(STATE.campaign)
    for coord in [tuple(here)] + [tuple(v) for v in
                                 hexgrid.neighbours(here[0], here[1], orient)]:
        groups = banks.get(coord)
        faces_here = sections_now.get(coord)
        segments = drawn_ones.get(coord)
        if not groups and not segments:
            continue
        if segments:
            # A hand-drawn river is removed **one stretch at a time**: if you
            # made it in three pieces, getting one wrong must not cost you all
            # three. The stretch is the one you are passing over.
            for index, (a, b) in enumerate(
                    _drawing.segment_stretches(coord, segments, size, origin, orient)):
                candidate.append((_dist_from_segment(point, a, b), 1,
                                  ("stretch", coord, index)))
        else:
            for a, b, _one, _two in _drawing.cuts_of(coord, groups, size, origin, orient):
                candidate.append((_dist_from_segment(point, a, b), 1,
                                  ("bank", coord, None)))
        # And the bridge sits on the cut: it is removed by aiming at its span,
        # not at the river it hops over, or there would be no way to remove
        # one without the other. At equal distance it wins, being on top.
        for entry in crossings.get(coord, ()):
            span = _crossing_sign(coord, faces_here, entry, size,
                                                   origin, orient)
            if span is not None:
                candidate.append((_dist_from_segment(point, *span), 0,
                                  ("bridge", coord, entry["id"])))

    # One at a time, the nearest. Up to six lines converge on the vertices:
    # taking them all would mean that brushing a junction erases half a
    # river, and whoever passes the eraser is removing *that* line there.
    near_ones = [c for c in candidate if c[0] <= threshold]
    if not near_ones:
        return 0
    _dist, _priority, (gender, a, b) = min(near_ones, key=lambda c: (c[0], c[1]))
    if gender == "border":
        STATE.archive.set_border(STATE.campaign, a, b, None)
    elif gender == "bridge":
        STATE.archive.remove_crossing(STATE.campaign, b)
    elif gender == "stretch":
        _remove_stretch(a, b, orient)
    else:
        # The river goes and with it the bridges that hopped over it: staying
        # they would be bridges over nothing.
        STATE.archive.set_banks(STATE.campaign, a, None)
        STATE.archive.remove_crossings(STATE.campaign, a)
    return 1

@theme.requires(permissions.SEE_SECRETS)
def _remove_stretch(coord, index: int, orient: str) -> None:
    """Removes a single drawn stretch, and redoes the shores with those left.

    The bridges that hopped over *that* stretch go with it only if the hex
    stops being divided: as long as two shores exist, a bridge between them
    still makes sense.
    """
    segments = list(STATE.archive.bank_points(STATE.campaign).get(
        tuple(coord)) or [])
    if not (0 <= index < len(segments)):
        return
    segments.pop(index)
    cut_ones = []
    for a, b in segments:
        for name in (a, b):
            node = waterways.node_from_text(name)
            if node is None or node[0] != waterways.VERTEX:
                continue
            for c, k in waterways.vertex_owners((node[1], node[2]),
                                                     node[3], orient):
                if tuple(c) == tuple(coord):
                    cut_ones.append(k)
    groups = waterways.banks_from_cuts(cut_ones)
    STATE.archive.set_banks(STATE.campaign, coord, groups, points=segments)
    if len(groups) < 2:
        STATE.archive.remove_crossings(STATE.campaign, coord)

def _bridge_span(coord, faces, entry, size: float, origin, orient: str):
    """The deck of an inner bridge: the segment crossing the river.

    Centered **where the bridge was put**, not in the middle of the river: two
    crossings on the same water line must look like two things.
    """
    ends = entry.get("ends") if isinstance(entry, dict) else entry
    above = entry.get("at") if isinstance(entry, dict) else None
    segment = sections.deck(faces, ends, above)
    if segment is None:
        return None
    cx, cy = hexgrid.hex_center(coord[0], coord[1], size, origin, orient)
    return tuple((cx + x * size, cy + y * size) for x, y in segment)

def _ford_stretch(coord, faces, entry, size: float, origin, orient: str):
    """The piece of river a ford sits on, in pixels: **along** the water.

    A ford is not a deck, it is shallow water: it is drawn on the river, not
    across it. The piece is the atom side it was placed on (`at`); if that
    spot is no longer on the water — the GM redrew — the whole border between
    the two shores it joined.
    """
    ends = entry.get("ends") if isinstance(entry, dict) else entry
    above = entry.get("at") if isinstance(entry, dict) else None
    stretch = sections.inner_side_under(faces, above)
    if stretch is None:
        stretch = sections.border_stretch(faces, ends)
    if stretch is None:
        return None
    cx, cy = hexgrid.hex_center(coord[0], coord[1], size, origin, orient)
    return tuple((cx + x * size, cy + y * size) for x, y in stretch)

def _crossing_sign(coord, faces, entry, size: float, origin,
                                orient: str):
    """The segment a crossing is drawn with — and aimed at with the eraser.

    Bridge: the span across the water. Ford: the piece of river, along the
    water. A single place that knows it, so the eraser removes what is seen.
    """
    if (entry.get("kind") or "bridge") == "ford":
        return _ford_stretch(coord, faces, entry, size, origin, orient)
    return _bridge_span(coord, faces, entry, size, origin, orient)

def _network_and_geometry():
    """The network of watercourses and the numbers to draw it, in one go.

    Without the lakes: the mesh crossing them is not drawn on the map, and a
    lake has no current. It serves the boat to go where it wants, not the
    direction brush, which must be able to snap only to lines that are seen.
    """
    m = STATE.k["map"]
    size = float(m["size"])
    origin = (float(m["origin_x"]), float(m["origin_y"]))
    orient = m["orientation"]
    return _common.waters_network(lakes=[]), size, origin, orient

def _send_network(mine: dict) -> None:
    """Hands the network to the browser, so the guide follows the river on its own.

    The course is recomputed at every mouse move: asking the server thirty
    times a second makes no sense, and the browser already has the whole
    network. When one then clicks, the course is redone by the server —
    nothing of the one computed over there is kept, as for the travel ruler.
    """
    # With the direction eraser in hand the guide is useless: one is not
    # following a river from upstream to downstream, one is removing a mark.
    # Leaving it on means a course stretching under the mouse while the click
    # does something else.
    is_on = bool(mine.get("water_mode") and mine.get("border_mode") == "current"
                  and not mine.get("remove_direction"))
    data = {"active": is_on}
    if is_on:
        network, size, origin, orient = _network_and_geometry()
        data.update({
            "nodes": {waterways.node_text(n):
                     [round(v, 1) for v in waterways.node_point(
                         n, size, origin, orient)]
                     for n in network.neighbours},
            "arcs": [[waterways.node_text(a), waterways.node_text(b)]
                      for a, b in network.arcs],
            "from": waterways.node_text(mine["current_from"])
                  if mine.get("current_from") else None,
            "threshold": round(size * 0.6, 1),
            "side": round(max(size * 0.2, 5.0), 1),
        })
    try:
        ui.run_javascript(f"window.kmCurrent && window.kmCurrent"
                          f"({json.dumps(data)});")
    except Exception:
        # Outside a window there is nobody to talk to: it happens when the
        # redraw comes from a timer instead of a click.
        log.debug("water network not delivered", exc_info=True)

@theme.requires(permissions.SEE_SECRETS)
def _remove_direction_under(mine: dict, point) -> bool:
    """Removes the direction from the stretch under the pointer. The water stays.

    Needed because correcting a wrong direction must not cost the line: until
    yesterday the only way to remove one was deleting the river and redoing
    it, which is like tearing out a page to correct a word.
    """
    network, size, origin, orient = _network_and_geometry()
    currents = STATE.archive.campaign_currents(STATE.campaign)
    if not currents:
        theme.notify(t("map.water.there_no_direction_remove"), "warning")
        return False
    best, dist = None, None
    for a, b in network.arcs:
        key = waterways.text_key(a, b)
        if key not in currents:
            continue
        try:
            extremes = (waterways.node_point(a, size, origin, orient),
                       waterways.node_point(b, size, origin, orient))
        except (IndexError, TypeError):
            continue
        how_much = _dist_from_segment(point, *extremes)
        if dist is None or how_much < dist:
            best, dist = key, how_much
    if best is None or dist > max(size * 0.35, 8.0):
        theme.notify(t("map.water.there_no_stretch_marked"), "warning")
        return False
    STATE.archive.remove_currents(STATE.campaign, [best])
    theme.mark_dirty()
    # If it was the last, the direction eraser puts itself down: the button
    # that switches it off sits next to the count and vanishes with it, and
    # staying on would mean an eraser cursor that can no longer be changed.
    if mine.get("remove_direction") and not STATE.archive.campaign_currents(
            STATE.campaign):
        mine["remove_direction"] = False
        if mine.get("apply_slider"):
            mine["apply_slider"]()
    theme.notify(t("map.water.direction_removed_that_stretch"),
                   "positive")
    return True

@theme.requires(permissions.SEE_SECRETS)
def _current_direction(mine: dict, point) -> None:
    """The direction gesture: take a vertex and go down to another.

    Two clicks, as for the water, but here the second is not any vertex: it
    must be reachable along the water, and the course between the two is what
    takes the direction. The first click is upstream, the second downstream —
    it is the order a river is read in on a map, and whoever goes up does it
    backwards.
    """
    network, size, origin, orient = _network_and_geometry()
    if network.empty_one:
        theme.notify(t("map.water.there_no_watercourse_drawn"), "warning")
        return
    node = waterways.nearest_node(network, point, size, origin, orient,
                                    threshold=size * 0.6)
    if node is None:
        theme.notify(t("map.water.no_watercourse_passes_there"), "warning")
        return

    if mine.get("current_from") is None:
        mine["current_from"] = node
        theme.notify(t("map.water.upstream_point_taken_now"), "info")
        return

    departure = mine["current_from"]
    mine["current_from"] = None
    if node == departure:
        theme.notify(t("map.water.cancelled_upstream_downstream_are"), "warning")
        return
    road = waterways.course(network, departure, node)
    if road is None:
        theme.notify(t("map.water.from_there_there_one"), "warning")
        return
    # The water is followed from one junction to the next, but the direction
    # is written on the **drawn** line, once: the pieces inherit it.
    steps = waterways.course_stretches(network, road)
    before = STATE.archive.campaign_currents(STATE.campaign)
    turned = sum(1 for a, b in steps
                 if before.get(waterways.text_key(a, b)) == (b, a))
    how_many = STATE.archive.set_currents(STATE.campaign, steps)
    theme.mark_dirty()
    STATE.record(t("map.water.direction_current", how_many=how_many, v=tn("common.stretch_word", how_many)), "map")
    queue = "."
    if turned:
        queue = (t("map.water.turned_other_way_from", turned=turned) if turned == 1
                else t("map.water.turned_other_way_from_2", turned=turned))
    theme.notify(
        t("map.water.current_marked", how_many=how_many, v=tn("common.stretch_word", how_many), queue=queue), "positive")

@theme.requires(permissions.SEE_SECRETS)
def _crossing_under(point, kind: str) -> bool:
    """Places a Bridge or a Ford on the water stretch under the click.

    It is the right gesture for something that **has a place**. A bridge is
    not described by saying which two shores it joins — that is derived — it
    is pointed at where it is. Before, it was drawn like a chord between two
    vertices, and in a hex where the river enters from one vertex and leaves
    from another that chord ended up running **along** the water instead of
    across: the app refused, with the river in plain sight. Now one clicks the
    water to hop over.

    It holds for both places the water can be: a stretch inside the hex
    becomes a crossing, a wet side between two hexes becomes a border of that
    kind. Outside any water it does nothing and the caller says so, still
    having the two-vertex gesture to try.
    """
    m = STATE.k["map"]
    size = float(m["size"])
    origin = (float(m["origin_x"]), float(m["origin_y"]))
    orient = m["orientation"]
    columns, rows = int(m["columns"]), int(m["rows"])
    threshold = max(size * 0.13, 6.0)
    here, _the = hexgrid.nearest_side(point[0], point[1], size, origin, orient)
    sections_now = _common.sections_map()
    borders = STATE.archive.campaign_borders(STATE.campaign)
    best = None

    # The surrounding hexes too, not only the one under the pointer: a
    # stretch reaches the vertices, and there the point is already in the
    # next cell.
    around = [tuple(here)] + [tuple(v) for v in
                              hexgrid.neighbours(here[0], here[1], orient)]
    for coord in around:
        if not (0 <= coord[0] < columns and 0 <= coord[1] < rows):
            continue
        cx, cy = hexgrid.hex_center(coord[0], coord[1], size, origin, orient)
        faces = sections_now.get(coord)
        for (p, q), (one, two) in sections.inner_sides(faces or ()):
            a = (cx + p[0] * size, cy + p[1] * size)
            b = (cx + q[0] * size, cy + q[1] * size)
            how_much = _dist_from_segment(point, a, b)
            if how_much <= threshold and (best is None or how_much < best[0]):
                best = (how_much, "inside", coord,
                            (faces[one].point, faces[two].point),
                            ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2))
        for near in hexgrid.neighbours(coord[0], coord[1], orient):
            near = tuple(near)
            if hexgrid.border_key(coord, near) not in borders:
                continue
            side = hexgrid.shared_side(coord, near, size, origin, orient)
            if side is None:
                continue
            how_much = _dist_from_segment(point, *side)
            if how_much <= threshold and (best is None or how_much < best[0]):
                best = (how_much, "edge", coord, near, None)

    if best is None:
        return False
    _how_much, gender, coord, what, above = best
    name = border_name(kind)
    if gender == "edge":
        STATE.archive.set_border(STATE.campaign, coord, what, kind)
        theme.mark_dirty()
        theme.notify(t("map.water.between", name=name, coord=coord[0], coord2=coord[1], what=what[0], what2=what[1]), "positive")
        return True
    STATE.archive.set_crossing(STATE.campaign, coord, what, above, kind=kind)
    theme.mark_dirty()
    if kind == "ford":
        theme.notify(
            t("map.water.ford_river_crossing_one", coord=coord[0], coord2=coord[1]), "positive")
    else:
        theme.notify(t("map.water.bridge_from_one_shore", coord=coord[0], coord2=coord[1]), "positive")
    return True

@theme.requires(permissions.SEE_SECRETS)
def _cut_hex(mine: dict, point) -> None:
    """The water brushes: two vertices of the same hex are joined.

    If the two vertices are neighbours in the ring, the chord between them
    *is* a side of the hex, and an edge line comes out. If they are far apart
    the chord crosses the hex, and a line through the middle comes out. It is
    the same gesture: a river is drawn by joining points, whether it then runs
    on the edge or through the middle is told by the drawing, not by a
    different button.

    It is the gesture of **Water** and nothing else. Bridge and Ford are not
    drawn between two vertices: they are placed by clicking the water line to
    hop over (`_crossing_under`). The two-point gesture with the bridge in
    hand stayed on as a fallback — orange outlines and a «first vertex» that
    meant nothing — and was removed from here, so it does not come back.

    The hex is decided by neither click alone: they decide it **together**. A
    vertex belongs to *three* hexes, so asking «which hex did I click» right
    on a vertex gives the wrong answer four times out of six — and before it
    was the first click that fixed the hex, so the second vertex was looked
    for among those of the wrong cell and a stretch other than the one
    pointed at came out. Now every click takes only the nearest grid point,
    and the hex is the one having both points: a single one if they are far
    apart, two if they are neighbours — but then the chord between them is
    the side they share, and it is the same from both sides.
    """
    m = STATE.k["map"]
    size = float(m["size"])
    origin = (float(m["origin_x"]), float(m["origin_y"]))
    orient = m["orientation"]
    columns, rows = int(m["columns"]), int(m["rows"])
    in_progress = mine.get("cut_in_progress")

    found_items = _drawing.snappable_points(point, size, origin, orient, columns, rows)
    if not found_items:
        return

    if in_progress is None:
        _d, position, owners = found_items[0]
        mine["cut_in_progress"] = {"point": position, "owners": owners}
        how_many = len({c for c, _k in owners})
        at_center = all(k is None for _c, k in owners)
        theme.notify(
            (t("map.water.center_hex_taken") if at_center else t("map.water.first_point_taken"))
            + (t("map.water.hexes_share_second_will", how_many=how_many) if how_many > 1 else "")
            + t("map.water.click_second"), "info")
        return

    mine["cut_in_progress"] = None

    # Two vertices are enough to say which hex is being worked on: it is the
    # one having both. If they are neighbours in the ring the hexes are two,
    # but the chord between them is the side they share, and from whichever
    # side one looks it is the same side; if they are far apart, the hex is
    # one.
    #
    # Among the vertices around here the nearest *that agrees with the first*
    # is taken, not simply the nearest: so the second click stays as tolerant
    # as it was — you may land quite far off — without being able any more
    # to silently move the hex you are drawing on.
    # The second vertex is looked for among those agreeing with the first,
    # but not at any distance: taking the nearest compatible one *and that is
    # all* means that, if the hand points at a spot unrelated to the first
    # vertex, a stretch comes out anyway — another one, on another hex. It is
    # exactly what was seen happening. Beyond this threshold one prefers to
    # draw nothing and say so.
    threshold = size * 0.6
    of_before = {c: k for c, k in in_progress["owners"]}
    chosen_one = None
    for dist, position, owners in found_items:
        if position == in_progress["point"] or dist > threshold:
            continue
        # Sorting by index is no longer possible: the center has no index, it
        # has None, and None does not compare with a number. The order only
        # serves to always pick the same hex all else being equal, and the
        # coordinate already gives that.
        common_ones = sorted(((c, of_before[c], k)
                         for c, k in owners if c in of_before),
                        key=lambda entry: (entry[0], entry[1] is None,
                                          -1 if entry[1] is None else entry[1],
                                          entry[2] is None,
                                          -1 if entry[2] is None else entry[2]))
        if common_ones:
            # Among several hexes sharing both points the first in coordinate
            # order wins: you draw the line where you want, and if they are
            # two it is the same side seen from two sides.
            chosen_one, k1, k2 = common_ones[0]
            break
    if chosen_one is None:
        which_ones = " o ".join(sorted({f"{c[0]},{c[1]}" for c, _k in
                                   in_progress["owners"]}))
        theme.notify(
            t("map.water.cancelled_there_no_second", which_ones=which_ones), "warning")
        return

    # From here on `k1` and `k2` are the vertex index, or None for the center.
    # The center does not touch the edge, so it is never a side and cuts
    # nothing on its own: it is a point the river passes through.
    if k1 is None or k2 is None:
        _drawn_stretch(mine, chosen_one, k1, k2, size, origin, orient)
        return

    # Neighbouring vertices: it is a side, and a side has its place — the
    # borders table. Writing it as an isolated shore would say almost the same
    # thing and would not be the same thing: a ford or a bridge is put on a
    # side.
    near = _drawing.side_between_vertices(chosen_one, k1, k2, orient)
    if near is not None:
        if not (0 <= near[0] < columns and 0 <= near[1] < rows):
            theme.notify(t("map.water.that_side_outside_map"), "warning")
            return
        STATE.archive.set_border(STATE.campaign, chosen_one, near, "water")
        theme.mark_dirty()
        theme.notify(t("map.water.between_2", water=border_name('water'), chosen_one=chosen_one[0], chosen_one2=chosen_one[1], near=near[0], near2=near[1]), "positive")
        return

    _drawn_stretch(mine, chosen_one, k1, k2, size, origin, orient)

def segments_of(coord, orient: str) -> list:
    """The stretches drawn inside the hex, as pairs of point names.

    A hex marked before the center was a point has no written segments: they
    are derived from how it is divided, which is exactly what was seen drawn.
    So adding a stretch to an old river does not erase it.
    """
    written = STATE.archive.bank_points(STATE.campaign).get(tuple(coord))
    if written:
        return [tuple(s) for s in written]
    groups = STATE.archive.campaign_banks(STATE.campaign).get(tuple(coord))
    outside = []
    for k1, k2 in waterways.vertex_cuts(groups or []):
        one = waterways.node_text(waterways.vertex_key(coord, k1, orient))
        two = (waterways.node_text(waterways.center_key(coord)) if k2 is None
               else waterways.node_text(waterways.vertex_key(coord, k2, orient)))
        outside.append((one, two))
    return outside

def _point_name(coord, k, orient: str) -> str:
    return waterways.node_text(waterways.center_key(coord) if k is None
                               else waterways.vertex_key(coord, k, orient))

@theme.requires(permissions.SEE_SECRETS)
def _drawn_stretch(mine: dict, coord, k1, k2, size: float,
                      origin, orient: str) -> None:
    """A water stretch inside the hex, between any two points.

    The shores are derived from the **vertices touched** by all the stretches
    together: a stretch ending at the center divides nothing on its own, but
    together with another starting from there it divides indeed. It is the
    general rule, and the center fits in without special cases.
    """
    before = STATE.archive.campaign_banks(STATE.campaign).get(tuple(coord))
    segments = segments_of(coord, orient)
    new = (_point_name(coord, k1, orient), _point_name(coord, k2, orient))
    if new in segments or (new[1], new[0]) in segments:
        theme.notify(t("map.water.that_stretch_already_there", coord=coord[0], coord2=coord[1]),
                       "warning")
        return
    segments.append(new)

    cut_ones = []
    for a, b in segments:
        for name in (a, b):
            node = waterways.node_from_text(name)
            if node is None or node[0] != waterways.VERTEX:
                continue
            for c, k in waterways.vertex_owners((node[1], node[2]), node[3],
                                                     orient):
                if tuple(c) == tuple(coord):
                    cut_ones.append(k)
    groups = waterways.banks_from_cuts(cut_ones)
    # The groups of sides stay written — the water drawing and the chart want
    # them — but how many shores there really are is told by the **faces**,
    # which is what one then walks on. Saying one number and using another
    # would be the surest way to make a right count look broken.
    faces = sections.faces_of(
        sections.local_cuts(coord, segments, orient), orient)
    STATE.archive.set_banks(STATE.campaign, coord, groups, points=segments)
    theme.mark_dirty()
    _describe_shores(coord, faces, bool(before))

# Beyond this number a hex stays right but stops being readable: the slices
# become too narrow for a marker to be told apart, and the model has nothing
# to do with it — it is the eye that cannot cope.
TOO_MANY_SHORES = 6

def _describe_shores(coord, faces, added: bool) -> None:
    """What to tell the GM after they drew a water line."""
    where = f"{coord[0]},{coord[1]}"
    if len(faces) < 2:
        # A stretch entering and stopping in the middle does not divide the
        # hex, and rightly so: the river is there, but one still passes
        # beyond. It is written all the same, or the drawing would vanish as
        # soon as made.
        theme.notify(
            t("map.water.stretch_marked_but_its", where=where), "info")
        return
    islands = sum(1 for f in faces if not f.sides)
    queue = t("map.water.stretch_was_added_those") if added else "."
    theme.notify(t("map.water.hex_shores", where=where, len=len(faces)) + queue, "positive")
    if islands:
        # A section not touching the edge very much exists, but has no sides
        # to leave from: without an inner crossing whoever is there is locked
        # in. Better to say it now than to find out when someone ends up there.
        n_items = (t("map.water.there_are_enclosed_shores", islands=islands) if islands > 1
                  else t("map.water.there_enclosed_shore"))
        theme.notify(
            t("map.water.middle_hex_does_not", where=where, n_items=n_items), "warning")
    if len(faces) > TOO_MANY_SHORES:
        theme.notify(
            t("map.water.shores_are_count_holds", where=where, len=len(faces)), "warning")

@theme.requires(permissions.SEE_SECRETS)
def _change_waters(mine: dict, mapping, is_on: bool) -> None:
    """Switches the whole water model on or off, deleting nothing."""
    STATE.k["map"]["waters_active"] = bool(is_on)
    mine["border_mode"] = None
    mine["cut_in_progress"] = None
    mine["current_from"] = None
    mine["remove_direction"] = False
    _send_network(mine)
    mine["water_proposal"] = None
    STATE.record(t("map.water.water_borders") + ("accesi" if is_on else "spenti"), "map")
    if mine.get("apply_slider"):
        mine["apply_slider"]()
    # Only the three boxes that really change, not the whole page.
    # `save_and_refresh` rebuilds *every* visible panel of *every* window —
    # header, clock, party, counts, turn sheet — and in NiceGUI rebuilding a
    # panel means redoing its elements and resending them. For a toggle it
    # was seconds of waiting; here the map, the Waters box and the hex sheet
    # change, and that is enough.
    theme.mark_dirty()
    theme.refresh_panels(("hexmap.map", "hexmap.waters", "hexmap.detail"))

def _brush(mine: dict, mapping, which: str) -> None:
    mine["border_mode"] = None if mine.get("border_mode") == which else which
    mine["cut_in_progress"] = None
    mine["current_from"] = None
    mine["remove_direction"] = False
    if mine.get("apply_slider"):
        mine["apply_slider"]()
    # The current guide lives in the browser: it must be switched on and off
    # together with the brush, or it would keep following the mouse under
    # another mode.
    _send_network(mine)
    mine["waters"].refresh()
    # The half stretch left in hand has gone from the state: it must go from
    # the drawing too, or a dot that no longer means anything stays on the
    # map. Resetting without redrawing is the way to have the two not match.
    mapping.refresh()

@theme.requires(permissions.SEE_SECRETS)
def _lake_point(mine: dict, point) -> None:
    """A point of the outline: the vertex is clicked, as for the river.

    Flooding was not enough, and the reason was good: a hand-drawn lake does
    not follow the hex edges — it cuts where the water cuts — so the ring of
    lines almost never closes, and the bucket spilled out of the map. Here
    you give the shape, point by point, and come back to the first to close it.
    """
    m = STATE.k["map"]
    size = float(m["size"])
    origin = (float(m["origin_x"]), float(m["origin_y"]))
    orient = m["orientation"]
    found_items = _drawing.snappable_points(point, size, origin, orient,
                                 int(m["columns"]), int(m["rows"]))
    if not found_items:
        theme.notify(t("map.water.there_no_grid_point"), "warning")
        return
    coord, k = found_items[0][2][0]
    text = _point_name(coord, k, orient)
    points = list(mine.get("lake_points") or [])

    if points and text == points[0]:
        _close_lake(mine)
        return
    if text in points:
        theme.notify(t("map.water.that_point_already_there"), "warning")
        return
    points.append(text)
    mine["lake_points"] = points
    if len(points) == 1:
        theme.notify(t("map.water.first_point_lake_follow"), "info")

@theme.requires(permissions.SEE_SECRETS)
def _close_lake(mine: dict) -> None:
    """Closes the shape and writes it: from here on it is a lake."""
    points = list(mine.get("lake_points") or [])
    if len(points) < 3:
        theme.notify(t("map.water.least_three_points_are"),
                       "warning")
        return
    m = STATE.k["map"]
    nodes = [waterways.node_from_text(x) for x in points]
    cells = waterways.cells_in_polygon(
        nodes, int(m["columns"]), int(m["rows"]), float(m["size"]),
        (float(m["origin_x"]), float(m["origin_y"])), m["orientation"])
    if not cells:
        theme.notify(t("map.water.shape_contains_center_no"),
                       "warning")
        return
    lake_id = mine.get("lake_id") or uuid.uuid4().hex[:8]
    old_ones = {x["id"]: x for x in STATE.archive.campaign_lakes(STATE.campaign)}
    name = (old_ones.get(lake_id) or {}).get("name") or ""
    STATE.archive.set_lake(STATE.campaign, lake_id, cells, name=name,
                                points=points)
    mine["lake_points"] = []
    mine["lake_id"] = None
    theme.mark_dirty()
    n_items = len(cells)
    STATE.record(t("map.water.marked_body_water", n_items=n_items, v="hexagon" if n_items == 1 else "hexes"), "map")
    theme.notify(
        t("map.water.lake_closed_points_inside", len=len(points), n_items=n_items, v="hexagon" if n_items == 1 else "hexes"),
        "positive")

def _lakes_box(mine: dict, mapping) -> None:
    """The lake brush, and the lakes there are: each with its points.

    A lake is a hand-drawn shape, and a hand-drawn shape gets things wrong:
    if one cannot see how it is made one does not know why the journey goes
    this way instead of that. So they are all here, with their points and
    their hexes, and each can be taken up again.
    """
    lakes = STATE.archive.campaign_lakes(STATE.campaign)
    points = list(mine.get("lake_points") or [])
    ui.label(t("map.water.click_vertices_outline_one")) \
        .style("font-size:.76rem")
    ui.label(t("map.water.no_longer_filled_flooding")) \
        .style("font-size:.74rem;color:var(--km-gold-dim);white-space:normal")
    ui.label(t("map.water.inside_lake_there_no")) \
        .style("font-size:.74rem;color:var(--km-gold-dim);white-space:normal")

    if points:
        theme.sep()
        with ui.row().classes("items-center gap-2 flex-wrap"):
            ui.html(f'<span class="km-chip" style="font-size:.68rem;'
                    f'border-color:{_drawing.LAKE_COLOR}">'
                    f'{len(points)} {"point" if len(points) == 1 else "points"}'
                    f'{t("map.water.redoing_lake") if mine.get("lake_id") else ""}'
                    f'</span>')
            ui.element("div").style("flex:1")
            ui.button(t("map.water.close_shape"), icon="check",
                      on_click=lambda: _end_lake(mine, mapping)) \
                .props("dense " + ("color=light-blue" if len(points) >= 3
                                   else "flat color=grey"))
            ui.button(icon="undo", on_click=lambda: _go_back(mine, mapping)) \
                .props("flat dense round size=sm color=grey") \
                .tooltip(t("map.water.remove_last_point"))
            ui.button(icon="close", on_click=lambda: _leave_lake(mine, mapping)) \
                .props("flat dense round size=sm color=grey") \
                .tooltip(t("map.water.drop_this_shape"))

    theme.sep()
    # Whether the lake names are drawn on the map: a viewer's choice, like
    # the hex icons, kept by the window and not by the kingdom.
    lit = bool(mine.get("show_lake_names", True))

    def toggle_names() -> None:
        mine["show_lake_names"] = not bool(mine.get("show_lake_names", True))
        mapping.refresh()
        _refresh_waters(mine)

    ui.button(t("map.water.lake_names"), icon="label" if lit else "label_off",
              on_click=toggle_names) \
        .props("dense " + ("color=light-blue" if lit else "flat color=grey")) \
        .tooltip(t("map.water.lake_names_tooltip"))
    if not lakes:
        ui.label(t("map.water.no_lake_marked")) \
            .style("font-size:.78rem;color:var(--km-muted)")
        return
    for lake in lakes:
        with ui.row().classes("items-center gap-2 w-full no-wrap flex-wrap"):
            ui.input(value=lake.get("name") or "", placeholder=t("map.water.unnamed"),
                     on_change=lambda e, x=lake: _lake_name(x, e.value)) \
                .props("outlined dense debounce=600").classes("w-40")
            ui.html(t("map.water.span_class_km_chip_4", LAKE_COLOR=_drawing.LAKE_COLOR, len=len(lake.get("points") or []), len2=len(lake.get("cells") or [])))
            ui.element("div").style("flex:1")
            ui.button(t("map.water.edit"), icon="edit",
                      on_click=lambda _e=None, x=lake: _resume_lake(mine, mapping, x)) \
                .props("dense flat color=light-blue")
            ui.button(icon="delete",
                      on_click=lambda _e=None, x=lake: _via_lake(mine, mapping, x["id"])) \
                .props("flat dense round size=sm color=red")

def _after_lake(mine: dict, mapping) -> None:
    if mine.get("draw"):
        mine["draw"]()
    if mine.get("waters"):
        mine["waters"].refresh()

def _end_lake(mine: dict, mapping) -> None:
    _close_lake(mine)
    _after_lake(mine, mapping)

def _go_back(mine: dict, mapping) -> None:
    _undo_lake_point(mine)
    _after_lake(mine, mapping)

def _leave_lake(mine: dict, mapping) -> None:
    mine["lake_points"] = []
    mine["lake_id"] = None
    _after_lake(mine, mapping)

def _resume_lake(mine: dict, mapping, lake: dict) -> None:
    _edit_lake(mine, lake)
    _after_lake(mine, mapping)

def _via_lake(mine: dict, mapping, lake_id: str) -> None:
    _delete_lake(mine, lake_id)
    _after_lake(mine, mapping)

def _lake_name(lake: dict, name: str) -> None:
    STATE.archive.set_lake(STATE.campaign, lake["id"], lake.get("cells") or [],
                                name=(name or "").strip(),
                                points=lake.get("points") or [])
    theme.mark_dirty()

def _undo_lake_point(mine: dict) -> None:
    points = list(mine.get("lake_points") or [])
    if points:
        points.pop()
    mine["lake_points"] = points

@theme.requires(permissions.SEE_SECRETS)
def _edit_lake(mine: dict, lake: dict) -> None:
    """Takes a drawn lake up again: its points become editable."""
    mine["lake_points"] = list(lake.get("points") or [])
    mine["lake_id"] = lake["id"]
    mine["border_mode"] = "lake"
    if not mine["lake_points"]:
        theme.notify(t("map.water.this_lake_one_old"), "warning")

@theme.requires(permissions.SEE_SECRETS)
def _delete_lake(mine: dict, lake_id: str) -> None:
    STATE.archive.remove_lake(STATE.campaign, lake_id)
    if mine.get("lake_id") == lake_id:
        mine["lake_points"] = []
        mine["lake_id"] = None
    theme.mark_dirty()
    STATE.record(t("map.water.removed_body_water"), "map")
    theme.notify(t("map.water.lake_removed_lines_stay"), "positive")

def _toggle_remove_direction(mine: dict, mapping) -> None:
    """Switches the direction eraser on and off.

    Removing a single one could already be done — ctrl and a click — but a
    keyboard shortcut that appears nowhere, for whoever uses it, does not
    exist: at the table the box offered «Remove all directions» and it looked
    like the only way to correct one was to erase them all and redo them. Now
    it is a brush like the others, with its button and its cursor.

    It stays on until switched off: wrong directions come in bunches — a
    river traced backwards — and switching it on again at every stretch would
    be one more click every time.
    """
    mine["remove_direction"] = not mine.get("remove_direction")
    # The upstream already taken no longer matters: with the eraser in hand
    # the click does not look for the downstream, and leaving it there would
    # mean a lit dot on the map waiting for a second click that will not come.
    mine["current_from"] = None
    _send_network(mine)
    if mine.get("apply_slider"):
        mine["apply_slider"]()
    mine["waters"].refresh()
    mapping.refresh()

@theme.requires(permissions.SEE_SECRETS)
def _forget_currents(mine: dict, mapping) -> None:
    """Removes the direction from every stretch. The water stays where it is."""
    how_many = STATE.archive.remove_currents(STATE.campaign)
    mine["current_from"] = None
    # Without directions there is nothing left to erase, and the button that
    # switches it off goes with them: staying on would mean an eraser in hand
    # that cannot be put down.
    mine["remove_direction"] = False
    theme.mark_dirty()
    STATE.record(t("map.water.removed_direction_from", how_many=how_many, v=tn("common.stretch_word", how_many)), "map")
    theme.notify(t("map.water.directions_removed_rivers_stay", how_many=how_many),
                   "positive")
    _send_network(mine)
    if mine.get("apply_slider"):
        mine["apply_slider"]()
    theme.refresh_panels(("hexmap.map", "hexmap.waters"))

@theme.requires(permissions.SEE_SECRETS)
def _forget_color(mine: dict) -> None:
    STATE.k["map"]["water_samples"] = []
    theme.mark_dirty()
    mine["waters"].refresh()

def _read_waters(mine: dict, mapping) -> None:
    """Looks at the image and prepares a proposal. Writes nothing."""
    m = STATE.k["map"]
    if not (m.get("water_samples") or []):
        theme.notify(t("map.water.first_pick_water_colour_2"), "warning")
        return
    hexes = {(e["col"], e["row"]): e for e in STATE.k["hexes"].values()}
    columns, rows = int(m["columns"]), int(m["rows"])
    mine["water_proposal"] = water_reading.trace(
        config.ASSETS_DIR / m["image"], m, hexes,
        lambda c: 0 <= c[0] < columns and 0 <= c[1] < rows,
        m.get("water_samples"))
    mine["waters"].refresh()
    mapping.refresh()             # without this the proposal would not be seen

# A water chart is text: a few dozen KB for a whole map. The ceiling is wide
# enough not to fight with a huge map, and narrow enough that nobody uploads a
# film by mistake.
MAX_CHART_BYTES = 4 * 1024 * 1024

def _download_chart() -> None:
    """Sends the browser the file with all the water of this map."""
    document = water_chart.compose(
        STATE.k["map"],
        STATE.archive.campaign_borders(STATE.campaign),
        STATE.archive.campaign_banks(STATE.campaign),
        STATE.archive.campaign_crossings(STATE.campaign),
        kingdom=str(STATE.k.get("name") or ""),
        currents=STATE.archive.campaign_currents(STATE.campaign))
    how_many = (len(document["borders"]) + len(document["banks"])
              + len(document["crossings"]) + len(document["currents"]))
    name = water_chart.file_name(str(STATE.k.get("name") or ""))
    ui.download.content(water_chart.text(document), name)
    STATE.record(t("map.water.downloaded_water_chart_entries", how_many=how_many), "map")
    theme.notify(t("map.water.chart_downloaded", name=name), "positive")

async def _load_chart(mine: dict, mapping, event) -> None:
    """Reads the uploaded chart and puts it *in proposal*, without applying it.

    Like the image reading: it is looked at in orange on the map, and only
    then decided. A file comes from outside, and from outside anything can
    come.
    """
    if not permissions.can(theme.user(), permissions.SEE_SECRETS):
        return
    file = event.file
    if file.size() > MAX_CHART_BYTES:
        theme.notify(t("map.water.file_too_large_water", v=MAX_CHART_BYTES // (1024 * 1024)),
                       "negative")
        return
    try:
        content_ = await file.text()
    except (UnicodeDecodeError, OSError):
        # A binary file renamed .json, or a disk acting up: the precise why is
        # told by `read`, which knows what it expected to find.
        content_ = await file.read()
    chart = water_chart.read(content_, STATE.k["map"],
                              file_name=file.name)
    mine["water_proposal"] = chart
    if not chart.is_valid:
        theme.notify(chart.reason, "negative")
    elif chart.empty_one:
        theme.notify(t("map.water.chart_contains_no_watercourse"), "warning")
    else:
        theme.notify(t("map.water.chart_read_borders_cut", len=len(chart.borders), len2=len(chart.banks)), "info")
    _after_borders(mine, mapping)

def _chart_result(mine: dict, mapping) -> None:
    """The box of the uploaded chart: what is inside, and the two ways."""
    chart = mine.get("water_proposal")
    if chart is None or getattr(chart, "origin", "") != "chart":
        return
    theme.sep()
    if chart.file_name:
        ui.label(chart.file_name).style("font-size:.76rem;color:var(--km-gold)")
    if not chart.is_valid:
        ui.label(chart.reason) \
            .style("color:var(--km-red);font-size:.78rem;white-space:normal")
        ui.button(t("common.close"), icon="close",
                  on_click=lambda: _discard_reading(mine, mapping)) \
            .props("dense flat color=grey")
        return

    provenance = []
    if chart.kingdom:
        provenance.append(t("map.water.drawn", kingdom=chart.kingdom))
    if chart.created_at:
        provenance.append(chart.created_at[:10])
    ui.label(tn("map.water.border_count", len(chart.borders)) + ", "
             + tn("map.water.cut_hex_count", len(chart.banks))
             + ", "
             + tn("map.water.crossing_count", len(chart.crossings))
             + ", "
             + tn("map.water.direction_count", len(chart.currents))
             + (" · " + ", ".join(provenance) if provenance else ".")) \
        .style("font-size:.8rem;white-space:normal")
    for warning in chart.warnings:
        ui.label("⚠ " + warning) \
            .style("color:var(--km-gold);font-size:.74rem;white-space:normal")
    if chart.discarded:
        ui.label(t("map.water.entries_discarded_malformed_hexes", discarded=chart.discarded)) \
            .style("color:var(--km-gold-dim);font-size:.74rem;white-space:normal")
    if chart.empty_one:
        ui.button(t("common.close"), icon="close",
                  on_click=lambda: _discard_reading(mine, mapping)) \
            .props("dense flat color=grey")
        return
    ui.html(t("map.water.map_you_see_b", PROPOSAL_COLOR=_drawing.PROPOSAL_COLOR)) \
        .style("color:var(--km-gold-dim);font-size:.74rem")
    with ui.row().classes("gap-2 flex-wrap"):
        ui.button(t("map.water.replace_everything"), icon="swap_horiz",
                  on_click=lambda: _accept_chart(mine, mapping, True)) \
            .props("dense color=amber") \
            .tooltip(t("map.water.away_water_there_now"))
        ui.button(t("map.water.add"), icon="add",
                  on_click=lambda: _accept_chart(mine, mapping, False)) \
            .props("dense flat color=amber") \
            .tooltip(t("map.water.keeps_what_there_lays"))
        ui.button(t("map.water.discard"), icon="close",
                  on_click=lambda: _discard_reading(mine, mapping)) \
            .props("dense flat color=grey")

@theme.requires(permissions.SEE_SECRETS)
def _accept_chart(mine: dict, mapping, replace_: bool) -> None:
    chart = mine.get("water_proposal")
    if chart is None or getattr(chart, "origin", "") != "chart" or not chart.is_valid:
        return
    counts = STATE.archive.write_water_chart(
        STATE.campaign,
        [(a, b, kind) for a, b, kind, _c in chart.borders],
        chart.banks, chart.crossings, replace_=replace_,
        currents=chart.currents)
    STATE.record(
        t("map.water.water_chart_borders_cut", v="sostituita" if replace_ else "aggiunta", borders=counts["borders"], banks=counts["banks"], crossings=counts["crossings"], currents=counts["currents"]), "map",
        chart.file_name + (t("map.water.earlier_entries_removed", removed=counts["removed"])
                           if counts["removed"] else ""))
    mine["water_proposal"] = None
    _after_borders(mine, mapping)
    theme.notify(t("map.water.chart_applied"), "positive")

def _reading_result(mine: dict, mapping) -> None:
    outcome = mine.get("water_proposal")
    if outcome is None or getattr(outcome, "origin", "") == "chart":
        return
    if not outcome.available:
        ui.label(outcome.reason).style("color:var(--km-gold);font-size:.78rem")
        return

    ui.label(t("map.water.borders_water_hexes_over", len=len(outcome.borders), examined=outcome.examined)) \
        .style("font-size:.8rem")
    if outcome.cut_ones:
        ui.label(t("map.water.hexes_are_crossed_watercourse", cut_ones=outcome.cut_ones)) \
            .style("font-size:.78rem")
    if outcome.outside_image:
        ui.label(t("map.water.sides_fall_outside_image", outside_image=outcome.outside_image)) \
            .style("color:var(--km-gold-dim);font-size:.74rem")
    ui.html(t("map.water.proposal_lakes_html", PROPOSAL_COLOR=_drawing.PROPOSAL_COLOR)) \
        .style("color:var(--km-gold-dim);font-size:.74rem")
    if outcome.empty_one:
        ui.label(t("map.water.i_found_nothing_propose")) \
            .style("color:var(--km-muted);font-size:.78rem")
        return
    with ui.row().classes("gap-2 flex-wrap"):
        ui.button(t("map.water.accept_reading"), icon="check",
                  on_click=lambda: _accept_borders(mine, mapping)) \
            .props("dense color=amber") \
            .tooltip(t("map.water.borders_banks_hexes", len=len(outcome.borders), cut_ones=outcome.cut_ones))
        ui.button(t("map.water.discard"), icon="close",
                  on_click=lambda: _discard_reading(mine, mapping)) \
            .props("dense flat color=grey")

@theme.requires(permissions.SEE_SECRETS)
def _accept_borders(mine: dict, mapping) -> None:
    """Applies the reading: the borders and the banks together.

    They are two faces of the same thing — where the water runs — and
    accepting only one would leave the map saying two different things about
    the same river.
    """
    outcome = mine.get("water_proposal")
    if outcome is None:
        return
    how_many = STATE.archive.replace_traced(
        STATE.campaign, [(a, b, kind) for a, b, kind, _c in outcome.borders])
    cut_ones = STATE.archive.replace_traced_banks(
        STATE.campaign, outcome.banks)
    STATE.record(t("map.water.read_from_image_water", how_many=how_many, cut_ones=cut_ones), "map",
                   t("map.water.proposal_accepted_what_was"))
    mine["water_proposal"] = None
    _after_borders(mine, mapping)

def _discard_reading(mine: dict, mapping) -> None:
    mine["water_proposal"] = None
    mine["waters"].refresh()
    mapping.refresh()

@theme.requires(permissions.SEE_SECRETS)
def _confirm_cleanup(mine: dict, mapping, how_many: int, by_hand: int) -> None:
    """Erasing everything is easy to press by mistake and long to redo."""
    with theme.dialog() as dlg, ui.card().classes("km-panel"):
        theme.title(t("map.water.erase_all_borders"), 2)
        ui.label(t("map.water.all_vanish", how_many=how_many)
                 + (t("map.water.including_you_marked_hand", by_hand=by_hand)
                    if by_hand else ".")
                 + t("map.water.hexes_terrains_are_not"))
        if by_hand:
            ui.label(t("map.water.if_you_only_want")) \
                .style("color:var(--km-gold-dim);font-size:.76rem")

        def go() -> None:
            for key in list(STATE.archive.campaign_borders(STATE.campaign)):
                STATE.archive.set_border(
                    STATE.campaign, (key[0], key[1]),
                    (key[2], key[3]), None)
            banks = STATE.archive.campaign_banks(STATE.campaign)
            for coord in list(banks):
                STATE.archive.set_banks(STATE.campaign, coord, None)
            removed_items = STATE.archive.remove_crossings(STATE.campaign)
            STATE.record(t("map.water.erased_water_borders_banks", how_many=how_many, len=len(banks), removed_items=removed_items), "map")
            dlg.close()
            _after_borders(mine, mapping)

        with ui.row():
            ui.button(t("map.water.erase_everything"), on_click=go).props("color=red")
            ui.button(t("common.cancel"), on_click=dlg.close).props("flat")
    dlg.open()

def _after_borders(mine: dict, mapping) -> None:
    """The borders change for everyone: redraws the others' windows too."""
    theme.save_and_refresh()
    mine["waters"].refresh()
    mine["detail"].refresh()
    mapping.refresh()

def _water_toggle(mine: dict, mapping) -> None:
    """The button that switches on the «Waters» mode, twin of the Travel one.

    As there, the icon is a toggle of its own: clicking it shows and hides the
    borders already marked and gets barred when they are off. The rest of the
    button enters and leaves the mode.
    """
    if not permissions.can(theme.user(), permissions.SEE_SECRETS):
        return

    @ui.refreshable
    def button() -> None:
        is_on = bool(mine.get("water_mode"))
        visible_ones = mine.get("show_borders", True)
        with ui.button(on_click=change) \
                .props("dense " + ("color=blue" if is_on else "flat color=grey")) \
                .tooltip(t("map.water.draws_rivers_fords_bridges")):
            icon = ui.icon("water").classes("" if visible_ones else "km-strike")
            # `.stop`: the click on the icon must not also enter or leave the
            # mode. They are two different toggles, as for Travel.
            icon.on("click.stop", toggle_borders)
            ui.label(t("map.water.waters")).style("margin-left:4px")

    def change() -> None:
        is_on = not mine.get("water_mode")
        _common._single_mode(mine, "water" if is_on else "")
        mine["water_mode"] = is_on
        # Switching on starts with the water brush, which is the one used 90%
        # of the time; switching off leaves nothing in hand.
        mine["border_mode"] = "water" if is_on else None
        if mine.get("apply_slider"):
            mine["apply_slider"]()
        button.refresh()
        mine["waters"].refresh()
        mine["detail"].refresh()
        mapping.refresh()

    def toggle_borders() -> None:
        mine["show_borders"] = not mine.get("show_borders", True)
        mapping.refresh()
        button.refresh()
        if mine.get("waters"):
            mine["waters"].refresh()

    mine["water_button"] = button
    button()
