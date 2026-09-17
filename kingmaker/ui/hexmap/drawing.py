"""The map SVG: grid, fog, water, journey arrows, icons, labels.

It used to live in `ui/hexmap.py`; the `hexmap` facade still re-exports everything.
"""
from __future__ import annotations

import logging
import html
import math
from kingmaker.state import STATE
from kingmaker.geometry import waterways, hexgrid, sections
from kingmaker.travel import daily
from kingmaker import rules

from kingmaker.ui.hexmap import common as _common
from kingmaker.ui.hexmap import markers as _markers
from kingmaker.ui.hexmap import water as _water
from kingmaker.ui.hexmap import travel as _journey
from kingmaker.locale.i18n import t, tn
from kingmaker.locale import i18n

log = logging.getLogger(__name__)


def _svg_layers(sel: dict, view) -> tuple[str, str]:
    """The drawing in two strings: the ground and what moves on it.

    The ground — fills, fog, the ctrl selection, the water, the icons and
    the names — changes when a hex or the water is edited; the live layer —
    journeys, the decided route, the markers, the chosen hex, a water
    proposal — changes at every marker moved. Each goes to an element of its
    own in the page, so a boarding sends a couple of KB to a window instead
    of the whole map. `_svg_grid` is the two joined, the ground first.
    """
    m = STATE.k["map"]
    size = float(m["size"])
    origin = (float(m["origin_x"]), float(m["origin_y"]))
    orient = m["orientation"]
    # With the fog in hand the GM must be able to click any cell, even a
    # never-touched one: while in that mode the whole grid is visible.
    show = bool(m["show_grid"]) or bool(view.gm and sel.get("fog_mode"))
    # How wide a label can be: the distance between two neighbouring hexes of
    # the same row, minus a margin. It changes with the grid orientation.
    name_width = size * (1.73 if orient == "pointy" else 1.5) * 0.94
    # How much the fills cover: it is a viewer's preference, and the window
    # keeps it as it keeps the zoom.
    coverage = float(sel.get("terrain_veil", m.get("terrain_veil", _common.TERRAIN_VEIL)))
    # The ctrl selection is a GM tool: it must not be able to appear on a
    # player's map even by mistake. Coordinates arrive as lists, and in a set
    # they must become tuples.
    waiting = ({tuple(c) for c in (sel.get("fog_selection") or ())}
                 if view.gm else set())
    ground_key = (STATE.archive.rev, STATE.k.get("_rev"), id(view), bool(view.gm),
                    show, coverage, frozenset(waiting),
                    bool(sel.get("show_icons", True)), size, origin, orient,
                    int(m["rows"]), int(m["columns"]))
    if sel.get("_ground_key") == ground_key and sel.get("_ground"):
        ground_layer, veil_layer, chosen_layer, icons_layer = sel["_ground"]
    else:
        ground_layer, veil_layer, chosen_layer, icons_layer = _ground_layers(
            sel, view, m, size, origin, orient, show, name_width, coverage,
            waiting)
        sel["_ground_key"] = ground_key
        sel["_ground"] = (ground_layer, veil_layer, chosen_layer, icons_layer)

    parts: list[str] = []
    # The character markers sit above everything else: they are the first
    # thing one looks for on the map. Boats sit just below: they are a place
    # to board, not someone to look in the face.
    parts.extend(_markers._svg_markers(
        view, size, origin, orient, set(sel.get("travel_pcs") or ()),
        {sel.get("travel_vehicle")} if sel.get("travel_vehicle") else set()))

    if sel["col"] is not None and not sel.get("travel_mode"):
        pts = hexgrid.polygon_points(sel["col"], sel["row"], size, origin, orient)
        parts.append(f'<polygon points="{pts}" fill="none" stroke="#ffffff" stroke-width="3" '
                     f'stroke-dasharray="6 4"/>')

    # Borders sit above the fog — a river is seen from the bank too — but
    # below the journey arrows, which must stay readable when they cross a
    # bridge.
    borders_layer = ""
    water_key = (STATE.archive.rev, id(view), size, origin, orient,
                    sel.get("border_mode") in ("bridge", "ford"),
                    bool(sel.get("show_lake_names", True)), bool(sel.get("water_mode")))
    # Hidden with the icon of the Waters button: nothing is drawn and the
    # cached layer is left alone, ready for when the lines come back. (The
    # cache used to be read before the switch was looked at: hiding the
    # lines redrew them from the copy.)
    show_water = bool(sel.get("show_borders", True)) and _common.waters_active()
    if not show_water:
        borders_layer = ""
    elif sel.get("_water_key") == water_key and "_water_svg" in sel:
        borders_layer = sel["_water_svg"]
    else:
        borders_now = STATE.archive.campaign_borders(STATE.campaign)
        banks_now = STATE.archive.campaign_banks(STATE.campaign)
        lakes_now = STATE.archive.campaign_lakes(STATE.campaign)
        # The lake names are read over the water, so they sit above the
        # lines — except while the Waters mode is on, when the lines are what
        # one is working on and the tag must not cover them.
        names_layer = (_svg_lake_names(view, lakes_now, size, origin, orient)
                       if sel.get("show_lake_names", True) else "")
        editing = bool(sel.get("water_mode"))
        borders_layer = (
            # The lake sits under all the rest of the water: it is the ground
            # the lines are read on, not one more line.
            _svg_lakes(view, lakes_now, size, origin, orient)
            + (names_layer if editing else "")
            + _svg_banks_and_crossings(view, banks_now, size, origin, orient,
                                STATE.archive.bank_points(STATE.campaign))
            + _svg_borders(view, borders_now, size, origin, orient)
            # The direction above the water: an arrow is read only if it sits
            # on the line it speaks of, and the line is already drawn below.
            + _svg_currents(view, borders_now, banks_now, size, origin, orient)
            # And, only while holding the Bridge or the Ford, the seams
            # between one water stretch and the next: they are the pieces a
            # click hops over, and without seeing them one does not know where
            # one is about to place it.
            + (_svg_seams(view, _common.sections_map(), size, origin, orient)
               if sel.get("border_mode") in ("bridge", "ford") else "")
            + ("" if editing else names_layer))
    if show_water:
        sel["_water_key"], sel["_water_svg"] = water_key, borders_layer

    # The journeys already under way, and below them the proposal being looked
    # at: so one sees where the party is going even after confirming.
    journeys_layer = _svg_journeys_in_progress(view, sel, size, origin, orient)
    route_now = sel.get("route") if sel.get("by_river") else None
    path_layer = _svg_path(sel.get("path") or [], size, origin,
                                    orient, sel.get("plan"),
                                    sel.get("branches") or [], sel.get("rendezvous"),
                                    sel.get("singles") or [],
                                    points=(route_now or {}).get("points"),
                                    shores=_markers._shores_of(sel))

    # The fog sits between the fills and the icons: it covers the terrain but
    # leaves names and symbols readable, which the GM needs precisely there.
    # The proposal sits on top of everything: it is what is being looked at now.
    proposal_layer = _svg_water_proposal(sel.get("water_proposal"), size,
                                          origin, orient)
    # And the vertex already taken, if you are choosing two: without seeing it
    # one understands neither which you took nor which hex it is on.
    # The vertex the current direction starts from: without seeing it one does
    # not know where one is going down from.
    current_departure = sel.get("current_from")
    if current_departure is not None:
        try:
            px, py = waterways.node_point(current_departure, size, origin, orient)
        except (IndexError, TypeError):
            px = None
        if px is not None:
            proposal_layer += (
                f'<circle cx="{px:.1f}" cy="{py:.1f}" '
                f'r="{max(size * 0.1, 3):.1f}" fill="none" stroke="{CURRENT_COLOR}" '
                f'stroke-width="{max(size * 0.035, 1.6):.1f}"/>')

    proposal_layer += _svg_lake_in_progress(sel.get("lake_points") or [],
                                          size, origin, orient)

    in_progress = sel.get("cut_in_progress")
    if in_progress:
        # The hexes still in play, outlined: they are the ones sharing the
        # taken vertex, and the second click will choose one. Seeing them
        # avoids finding out only afterwards that you drew on the wrong one.
        candidates = "".join(
            hexgrid.polygon_path(c[0], c[1], size, origin, orient)
            for c in {tuple(c) for c, _k in in_progress.get("owners") or ()})
        if candidates:
            proposal_layer += (
                f'<path d="{candidates}" fill="none" stroke="{PROPOSAL_COLOR}" '
                f'stroke-width="{max(size * 0.03, 1.4):.1f}" '
                f'stroke-dasharray="{size * 0.09:.1f} {size * 0.07:.1f}" '
                f'stroke-opacity="0.75"/>')
        point = in_progress.get("point")
        if point is not None:
            proposal_layer += (
                f'<circle cx="{point[0]:.1f}" cy="{point[1]:.1f}" '
                f'r="{max(size * 0.09, 3):.1f}" fill="{PROPOSAL_COLOR}" '
                f'stroke="#ffffff" stroke-width="{max(size * 0.02, 1):.1f}"/>')
    ground = ground_layer + veil_layer + chosen_layer + borders_layer + icons_layer
    live = journeys_layer + path_layer + "".join(parts) + proposal_layer
    return ground, live


def _svg_grid(sel: dict, view) -> str:
    """The whole drawing as one string: the ground under the live layer."""
    ground, live = _svg_layers(sel, view)
    return ground + live

def _ground_layers(sel: dict, view, m: dict, size: float, origin, orient: str,
                     show: bool, name_width: float, coverage: float,
                     waiting: set) -> tuple[str, str, str, str]:
    """The grid, the fog, the hexes chosen with ctrl and the icons: the layers
    that do not change until the map changes. `_svg_grid` keeps them per
    window and redoes them only when the revision rises: before, 720 polygons
    were rebuilt at every redraw, even for a moved marker.
    """
    # The fog applies to everyone, but means two different things: to the GM
    # "the players do not see here", to the players "we have never been here".
    parts: list[str] = []
    veil: list[str] = []
    chosen: list[str] = []
    party_visible = (STATE.archive.visible_to_party(STATE.campaign)
                       if view.gm else None)
    veil_fill = (_common._gm_fog(m.get("gm_fog_opacity", 0.35)) if view.gm
                        else _common._player_fog(m.get("fog_opacity", 0.8)))
    # Hexes with the same look end up in a single <path>: a 30x24 grid is 720
    # polygons, and resending them one by one at every redraw weighs.
    cells: dict[tuple[str, str, float], list[str]] = {}

    in_the_map = _common.inside_map(m)
    for row in range(int(m["rows"])):
        for col in range(int(m["columns"])):
            # Outside the image there is no map: no grid in the dark.
            if not in_the_map((col, row)):
                continue
            # The highlight of what was chosen with ctrl is drawn before any
            # skip: one happens to choose still-empty hexes, and without a mark
            # one would not know they were taken.
            if (col, row) in waiting:
                chosen.append(hexgrid.polygon_path(col, row, size, origin, orient))

            # `view.hex_for` returns None for a hex this user does not know:
            # its data enters the SVG in no way.
            h = view.hex_for(col, row)
            state = h["status"] if h else "unknown"

            under_fog = ((col, row) not in party_visible if view.gm
                            else not view.can_see(col, row))
            if under_fog:
                veil.append(hexgrid.polygon_path(col, row, size, origin, orient))
                if h is None:
                    # Covered cell with no data: the fog already has its
                    # outline, and the base polygon would double the SVG
                    # without adding anything to see.
                    continue
            elif h is None and not show:
                # Visible but never touched: drawn only with the grid on.
                continue

            _lab, fill, stroke = _common.HEX_STATUSES[state]

            if h and h.get("terrains"):
                t = rules.BY_ID["terrain"].get(h["terrains"][0])
                if t:
                    fill = t["color"] + ("cc" if state == "claimed" else "66")
            fill = _common._with_veil(fill, coverage)

            thickness = 2.6 if state == "claimed" else 1.0
            cells.setdefault((fill, stroke, thickness), []).append(
                hexgrid.polygon_path(col, row, size, origin, orient))

            if h and sel.get("show_icons", True):
                cx, cy = hexgrid.hex_center(col, row, size, origin, orient)
                # Settlements, farms and work sites are both in the hex fields
                # and among the «hex features»: one thing deserves one icon.
                symbols: list[tuple[str, str, bool]] = []
                seen: set[str] = set()
                # The fields the GM keeps to themself: the icon is the same,
                # but it carries the padlock.
                covered = set(view.hidden_fields(col, row))

                def mark_(key: str, icon: str, badge_: str = "",
                          secret: bool = False) -> None:
                    if key not in seen:
                        seen.add(key)
                        symbols.append((icon, badge_, secret))

                if h.get("settlement"):
                    mark_("settlement", "🏘️")
                if h.get("work_site"):
                    commodity = h["work_site"]["commodity"]
                    # Resource hex: two Commodities a turn from a single site.
                    mark_(f"sito_lavoro:{commodity}", _common._work_site_icon(commodity),
                          "×2" if h["work_site"].get("doubled") else "",
                          "work_site" in covered)
                if h.get("farmland"):
                    mark_("farmland", "🌾", secret="farmland" in covered)
                if h.get("fortified"):
                    mark_("fortification", "🏰", secret="fortified" in covered)
                if h.get("roads"):
                    mark_("roads", "🛣️", secret="roads" in covered)
                for el in h.get("features", []):
                    if el["kind"] == "work_site":
                        mark_(f'sito_lavoro:{el.get("name")}', _common._work_site_icon(el.get("name")))
                    else:
                        mark_(el["kind"], _common.HEX_ICONS.get(el["kind"], "❔"))
                # Prepared but not yet on the hex: they exist only for the GM,
                # so they join the row too, with the padlock.
                for el in view.hidden_features(col, row):
                    mark_(f'segreto:{el.get("kind")}:{el.get("name")}',
                          _common._feature_icon(el), secret=True)
                parts.extend(_hex_icons(symbols[:4], cx, cy + size * 0.18, size * 0.45))

                if h.get("name"):
                    parts.append(_hex_label(h["name"], cx, cy - size * 0.42,
                                                size * 0.26, name_width))

    # The thick outlines (claimed hexes) last, so they win over the neighbours.
    ground = []
    for (fill, stroke, thickness), silhouettes in sorted(cells.items(), key=lambda v: v[0][2]):
        ground.append(f'<path d="{"".join(silhouettes)}" fill="{"none" if fill.endswith("00") else fill}" '
                     f'stroke="{stroke}" stroke-width="{thickness:g}"/>')
    veil_layer = ""
    if veil:
        veil_layer = (f'<path d="{"".join(veil)}" fill="{veil_fill}" '
                       f'stroke="{_common.FOG_EDGE}" stroke-width="1.1" '
                       f'stroke-dasharray="5 4" stroke-opacity="0.45"/>')

    # The hexes taken with ctrl, awaiting confirmation.
    chosen_layer = ""
    if chosen:
        chosen_layer = (f'<path d="{"".join(chosen)}" fill="#d7b26333" '
                         f'stroke="#d7b263" stroke-width="2.4"/>')

    return "".join(ground), veil_layer, chosen_layer, "".join(parts)

WATER_COLOR = "#4da6d9"

# The vertex geometry lives in `hexgrid`, which is pure: here remain the names
# the rest of the module uses it under. The watercourse network needs it too,
# and that cannot drag the interface along to know where a vertex is.
SIDE_RING = hexgrid.SIDE_RING

_common_vertex = hexgrid.common_vertex

_vertex_order = hexgrid.vertex_order

vertices_of = hexgrid.vertices_of

# The proposal is not data yet, and must not look like it: orange against the
# blue of the real borders, and yellow on the hexes. They are the same two
# colours one looks at a proposal on paper with — they show over the green
# and brown of the map, and are confused with nothing else.
def bank_stretches(banks: dict, size: float, origin, orient: str,
                view=None, segments: dict | None = None) -> list[str]:
    """The drawing of the river where it cuts a hex, as SVG sub-paths.

    Without these stretches a watercourse would be seen in pieces — drawn
    where it passes between two hexes, invisible where it crosses one — and
    it would be precisely where it crosses one that the party would not
    understand why there is no way through.

    The cut follows from the only thing we know: which sides go together.
    Where two sides adjacent in the ring belong to different banks, the water
    runs between them, and the point is the vertex the two sides share.

    It lives in a function of its own because it is needed twice with two
    colours: blue for the banks already marked, orange for those the reading
    is proposing. The two must have the same shape, or looking at the
    proposal would say nothing about what accepting it will produce.
    """
    # We iterate over the **union** of the two dictionaries, not the banks
    # alone. A hex with the drawing but no shores — a river entering it and
    # stopping, thus not dividing it in two — does not appear among the banks
    # (`campaign_banks` keeps only who has more than one shore), and iterating
    # over those its stretch stayed saved and invisible: you drew it, the app
    # said «marked», and on the map there was nothing. A river merely touching
    # a hex very much exists, on real maps.
    stretches: list[str] = []
    for coord in sorted(set(banks or {}) | set(segments or {})):
        coord = (int(coord[0]), int(coord[1]))
        groups = (banks or {}).get(coord)
        if view is not None and not view.can_see(*coord):
            continue
        drawn_ones = (segments or {}).get(coord)
        if drawn_ones:
            # What you drew, not what the model rebuilds: passing through the
            # center or going straight divides the hex the same way, and only
            # the drawing knows which of the two it was.
            for a, b in segment_stretches(coord, drawn_ones, size, origin,
                                            orient):
                stretches.append(f"M{a[0]:.1f} {a[1]:.1f}L{b[0]:.1f} {b[1]:.1f}")
            continue
        for (x1, y1), (x2, y2), _one, _two in cuts_of(coord, groups, size,
                                                       origin, orient):
            stretches.append(f"M{x1:.1f} {y1:.1f}L{x2:.1f} {y2:.1f}")
    return stretches

def segment_stretches(coord, segments, size: float, origin,
                        orient: str) -> list:
    """The hand-drawn segments inside a hex, in pixels."""
    outside = []
    for a, b in segments or ():
        node_a, node_b = waterways.node_from_text(a), waterways.node_from_text(b)
        if node_a is None or node_b is None:
            continue
        try:
            outside.append((waterways.node_point(node_a, size, origin, orient),
                          waterways.node_point(node_b, size, origin, orient)))
        except (IndexError, TypeError):
            continue
    return outside

def cuts_of(coord, groups, size: float, origin, orient: str) -> list:
    """The water stretches inside a hex, and the sides each one separates.

    Every entry is `(a, b, side_one, side_two)`: the segment as drawn, and two
    sides of the hex sitting one on this side and one on the other of the
    water. The sides and not the shore numbers, because that is how a bridge
    is written: the numbers get reshuffled by the first new cut, «side 2»
    does not.
    """
    if len(groups or []) < 2:
        return []
    whose = {}
    for index, group in enumerate(groups):
        for direction in group:
            whose[direction] = index
    vertices = vertices_of(coord, size, origin, orient)
    junctions = []
    for position, direction in enumerate(SIDE_RING):
        after = SIDE_RING[(position + 1) % 6]
        if direction not in whose or after not in whose:
            continue
        if whose[direction] == whose[after]:
            continue
        # The vertex between the side at position `position` and the next is
        # precisely vertex `position`: that is how they are numbered.
        junctions.append((vertices[position], direction, after))
    # Two junctions are a river entering and leaving; more than two is a
    # confluence, and there all the stretches are drawn towards the center.
    if len(junctions) == 2:
        (a, one, two), (b, _u, _d) = junctions
        return [(a, b, one, two)]
    if len(junctions) > 2:
        center = hexgrid.hex_center(coord[0], coord[1], size, origin, orient)
        return [(point, center, one, two) for point, one, two in junctions]
    return []

def snappable_points(point, size: float, origin, orient: str,
                       columns: int, rows: int) -> list:
    """The grid points around the click, nearest first.

    They are the six vertices of every hex **plus its center**. The center was
    not a point: it appeared on its own, when a hex ended up with more than
    two shores and the stretches were all drawn to the middle — and from
    outside it looked like the line snapped at random. Treating it as an
    ordinary point makes it a choice instead of a surprise, and gives a steady
    hand where it is needed: a river turning inside a hex, or the shore of a
    lake that does not pass through a vertex.

    Every entry is `(distance, position, owners)` as for the vertices, where
    `owners` for a center is the single hex that has it.
    """
    found_items = list(near_vertices(point, size, origin, orient, columns, rows))
    here = hexgrid.pixel_to_hex(point[0], point[1], size, origin, orient)
    around_ = [tuple(here)] + [tuple(v) for v in
                              hexgrid.neighbours(here[0], here[1], orient)]
    for coord in around_:
        if not (0 <= coord[0] < columns and 0 <= coord[1] < rows):
            continue
        center = hexgrid.hex_center(coord[0], coord[1], size, origin, orient)
        dist = math.hypot(point[0] - center[0], point[1] - center[1])
        found_items.append((dist, center, [(coord, None)]))
    found_items.sort(key=lambda entry: entry[0])
    return found_items

def near_vertices(point, size: float, origin, orient: str,
                   columns: int, rows: int) -> list:
    """The grid vertices around the point, nearest first.

    A vertex does not belong to one hex: it belongs to *three*, and on the map
    it is a single point. Looking for it among the vertices of the hex under
    the pointer *and those of the six around* is the only way to always take
    the one being pointed at. Asking first «which hex did I click» and then
    «which of its six vertices» gave the right answer on the point and the
    wrong one on the hex: right next to a vertex the click falls in the
    neighbouring hex four times out of six.

    Every entry is `(distance, position, owners)`, where `owners` lists the
    pairs `(coord, k)` — the same point, numbered as each hex that has it
    numbers it. Coinciding points appear once: the tolerance is the same
    `_common_vertex` pairs two sides with.
    """
    here = hexgrid.pixel_to_hex(point[0], point[1], size, origin, orient)
    around_ = [tuple(here)] + [tuple(v) for v in
                              hexgrid.neighbours(here[0], here[1], orient)]
    found_items: list = []
    near = max(size * 0.02, 1.0) ** 2
    for coord in around_:
        if not (0 <= coord[0] < columns and 0 <= coord[1] < rows):
            continue
        for k, vertex in enumerate(vertices_of(coord, size, origin, orient)):
            if vertex is None:
                continue
            for entry in found_items:
                if ((entry[1][0] - vertex[0]) ** 2
                        + (entry[1][1] - vertex[1]) ** 2) < near:
                    entry[2].append((coord, k))
                    break
            else:
                d = math.hypot(point[0] - vertex[0], point[1] - vertex[1])
                found_items.append((d, vertex, [(coord, k)]))
    found_items.sort(key=lambda entry: entry[0])
    return found_items

def side_between_vertices(coord, k1: int, k2: int, orient: str):
    """If the two vertices are neighbours in the ring, the side between them.

    A side of the hex is the chord between two *adjacent* vertices: it is the
    same gesture as a cut, only shorter. That is why the water brush is one —
    two vertices are joined, and where they fall decides whether the edge of
    a river or the river crossing the hex comes out.

    Returns the neighbour beyond that side, or None if the vertices are not adjacent.
    """
    if (k1 + 1) % 6 == k2:
        direction = SIDE_RING[k2]
    elif (k2 + 1) % 6 == k1:
        direction = SIDE_RING[k1]
    else:
        return None
    return hexgrid.neighbours(coord[0], coord[1], orient)[direction]

def _svg_banks_and_crossings(view, banks: dict, size: float, origin, orient: str,
                      segments: dict | None = None) -> str:
    """The river inside the hex and the bridges hopping over it, in this order.

    The two halves speak two different languages and rightly so: the river is
    drawn from the **stretches** someone drew, the bridge is placed on the
    **sections** those stretches cut out.
    """
    stretches = bank_stretches(banks, size, origin, orient, view, segments)
    river = ""
    if stretches:
        thickness = max(size * 0.055, 1.6)
        river = (f'<path d="{"".join(stretches)}" fill="none" stroke="{WATER_COLOR}" '
                 f'stroke-width="{thickness:.1f}" stroke-linecap="round" '
                 f'stroke-opacity="0.8"/>')
    return river + _svg_inner_crossings(view, _common.sections_map(),
                                      STATE.archive.campaign_crossings(STATE.campaign),
                                      size, origin, orient)

def _svg_seams(view, sections_now: dict, size: float, origin,
                  orient: str) -> str:
    """Where a water stretch ends and the next begins.

    Seen only with the Bridge or the Ford in hand, and they answer the
    question one asks at that moment: «if I click here, how much river am I
    hopping over?». A river drawn with a single line can be made of several
    stretches — every time another line cuts it, it divides there — and a
    bridge hops over **one**. Without this mark the division is not seen, and
    the bridge seems to go wherever it likes.

    A white tick across every seam: where the stretch ends because the water
    ends there is nothing to mark, and indeed nothing is marked.
    """
    if not sections_now:
        return ""
    stretches: list[str] = []
    for coord, faces in sections_now.items():
        if view is not None and not view.can_see(*coord):
            continue
        cx, cy = hexgrid.hex_center(coord[0], coord[1], size, origin, orient)
        how_many: dict = {}
        for (p, q), _which_ones in sections.inner_sides(faces):
            for extreme, other in ((p, q), (q, p)):
                key = (round(extreme[0], 6), round(extreme[1], 6))
                how_many.setdefault(key, []).append(other)
        for (px, py), others in how_many.items():
            if len(others) < 2:
                continue          # the water ends there: no seam
            ax, ay = cx + px * size, cy + py * size
            dx, dy = others[0][0] - px, others[0][1] - py
            along = math.hypot(dx, dy) or 1.0
            nx, ny = -dy / along, dx / along
            vehicle = size * 0.055
            stretches.append(f"M{ax - nx * vehicle:.1f} {ay - ny * vehicle:.1f}"
                          f"L{ax + nx * vehicle:.1f} {ay + ny * vehicle:.1f}")
    if not stretches:
        return ""
    return (f'<path d="{"".join(stretches)}" fill="none" stroke="#f0f6fc" '
            f'stroke-width="{max(size * 0.022, 1.0):.1f}" '
            f'stroke-linecap="round" stroke-opacity="0.9"/>')

def _svg_inner_crossings(view, banks: dict, crossings: dict, size: float, origin,
                       orient: str) -> str:
    """The bridges on the river crossing a hex.

    Same language as the bridges on the edge — a gap in the water and the
    glyph — because they are the same thing seen from inside instead of from
    outside: the point where the water stops being a wall.
    """
    if not crossings or not banks:
        return ""
    gaps: list[str] = []
    fords: list[str] = []
    glyphs: list[str] = []
    for coord, entries in crossings.items():
        faces = banks.get(tuple(coord))
        if not faces:
            continue
        if view is not None and not view.can_see(*coord):
            continue
        for entry in entries:
            sign = _water._crossing_sign(coord, faces, entry, size,
                                                origin, orient)
            if sign is None:
                continue
            (ax, ay), (bx, by) = sign
            ford = (entry.get("kind") or "bridge") == "ford"
            (fords if ford else gaps).append(
                f"M{ax:.1f} {ay:.1f}L{bx:.1f} {by:.1f}")
            # The glyph only on the bridge. The ford is the dotted line along
            # the water, like the ford on the edge between two hexes, and that
            # is all.
            if not ford:
                glyphs.append(
                    f'<text x="{(ax + bx) / 2:.1f}" y="{(ay + by) / 2:.1f}" '
                    f'text-anchor="middle" dominant-baseline="central" '
                    f'font-size="{size * 0.26:.1f}">🌉</text>')
    if not gaps and not fords:
        return ""
    thickness = max(size * 0.05, 1.6)
    outside = []
    # The bridge is a solid beam on this and that side of the water; the ford
    # is a row of **dots** on the water, along the river: with round caps
    # (`stroke-linecap="round"`) a zero-length dash is a dot as big as the
    # thickness, and the gap between one dot and the next is the rest of the
    # dasharray. Same language as the ford on the edge between two hexes.
    for stretches, extra in ((gaps, ""),
                          (fords, f' stroke-dasharray="0.1 {thickness * 2.2:.1f}"')):
        if stretches:
            outside.append(f'<path d="{"".join(stretches)}" fill="none" '
                         f'stroke="#e6d3a3" stroke-width="{thickness:.1f}" '
                         f'stroke-linecap="round" stroke-opacity="0.9"{extra}/>')
    return "".join(outside) + "".join(glyphs)

# The teal of the direction: it shows over the blue of the river without
# becoming another water line, and it is not the orange of proposals — a
# marked direction is data, not something to confirm.
CURRENT_COLOR = "#59e0c4"

# The light blue of the body of water: a glaze, not a fill — the drawing of
# the map is underneath, and a lake painted over would erase it.
LAKE_COLOR = "#7fc9f0"

# Into how many parts an activity is split in the field the ruler receives.
# It gives a weight even to the steps that cost nothing — inside a hex one
# passes for free — so the course can be walked backwards. A thousand and not
# a hundred: this way even a route of hundreds of pieces does not risk letting
# the longer road win.
ROUTE_SCALE = 1000

def _lake_ring(lake: dict, size: float, origin, orient: str) -> list:
    """The outline points, in pixels. Empty if the lake has none (or is bent)."""
    outside = []
    for text in lake.get("points") or ():
        node = waterways.node_from_text(text)
        if node is None:
            return []
        try:
            outside.append(waterways.node_point(node, size, origin, orient))
        except (IndexError, TypeError):
            return []
    return outside

def _lake_visible(view, lake: dict) -> bool:
    return any(view is None or view.can_see(c[0], c[1])
               for c in (lake.get("cells") or ())) or not lake.get("cells")


def _svg_lake_names(view, lakes: list, size: float, origin, orient: str) -> str:
    """The name of every named lake, a small tag in the lake colour at the
    middle of its shape (or of its hexes). Its own layer: above the water
    when reading the map, below it while editing the lines."""
    labels: list[str] = []
    for lake in lakes:
        if not _lake_visible(view, lake) or not (lake.get("name") or "").strip():
            continue
        ring = _lake_ring(lake, size, origin, orient)
        spots = ring if len(ring) >= 3 else [
            hexgrid.hex_center(c, r, size, origin, orient)
            for c, r in (lake.get("cells") or ())]
        if not spots:
            continue
        cx = sum(x for x, _y in spots) / len(spots)
        cy = sum(y for _x, y in spots) / len(spots)
        labels.append(_tag_label(str(lake["name"]).strip(), cx, cy, size * 0.22, LAKE_COLOR))
    return "".join(labels)


def _svg_lakes(view, lakes: list, size: float, origin, orient: str) -> str:
    """The bodies of still water, glazed in light blue.

    A hand-drawn lake shows by **its** shape, not by the hexes it occupies:
    water does not have the grid's edges, and glazing whole hexes would make a
    lake look square when it is not. The hexes remain what travel counts on,
    and they are another matter.
    """
    if not lakes:
        return ""
    outside: list[str] = []
    stretches: list[str] = []
    for lake in lakes:
        visible = _lake_visible(view, lake)
        ring = _lake_ring(lake, size, origin, orient) if visible else []
        if len(ring) >= 3:
            points = " ".join(f"{x:.1f},{y:.1f}" for x, y in ring)
            outside.append(f'<polygon points="{points}" fill="{LAKE_COLOR}33" '
                         f'stroke="{LAKE_COLOR}88" '
                         f'stroke-width="{max(size * 0.03, 1.4):.1f}" '
                         f'stroke-linejoin="round"/>')
            continue
        # Old lakes, filled by flooding, have no outline: they are still glazed
        # by hexes, which is how they were born.
        for col, row in lake.get("cells") or ():
            if view is not None and not view.can_see(col, row):
                continue
            stretches.append(hexgrid.polygon_path(col, row, size, origin, orient))
    if stretches:
        outside.append(f'<path d="{"".join(stretches)}" fill="{LAKE_COLOR}33" '
                     f'stroke="{LAKE_COLOR}55" '
                     f'stroke-width="{max(size * 0.02, 1.0):.1f}"/>')
    return "".join(outside)

def _svg_lake_in_progress(points: list, size: float, origin, orient: str) -> str:
    """The outline while you are drawing it: the points taken and the line between them."""
    frame = []
    for text in points or ():
        node = waterways.node_from_text(text)
        if node is None:
            continue
        try:
            frame.append(waterways.node_point(node, size, origin, orient))
        except (IndexError, TypeError):
            continue
    if not frame:
        return ""
    outside = []
    if len(frame) > 1:
        line = "M" + "L".join(f"{x:.1f} {y:.1f}" for x, y in frame)
        outside.append(f'<path d="{line}" fill="none" stroke="{LAKE_COLOR}" '
                     f'stroke-width="{max(size * 0.04, 1.8):.1f}" '
                     f'stroke-linecap="round" stroke-linejoin="round" '
                     f'stroke-dasharray="{size * 0.1:.1f} {size * 0.06:.1f}"/>')
    for index, (x, y) in enumerate(frame):
        # The first shows bigger: it is the one to click again to close.
        radius = max(size * (0.11 if index == 0 else 0.07), 3)
        outside.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius:.1f}" '
                     f'fill="{LAKE_COLOR}" stroke="#0b1015" '
                     f'stroke-width="{max(size * 0.015, 1):.1f}"/>')
    return "".join(outside)

def _svg_currents(view, borders: dict, banks: dict, size: float, origin,
                  orient: str) -> str:
    """The direction arrows, one per stretch, in the middle of the stretch.

    Drawn only where someone said so: a stretch without an arrow is a piece of
    river whose flow is unknown, and leaving it bare is the only way to show
    it.
    """
    currents = STATE.archive.campaign_currents(STATE.campaign)
    if not currents:
        return ""
    # With the drawn segments, not without: a direction is written on the
    # stretch **as it was drawn**, and a network rebuilt from the shores alone
    # has stretches of a different shape — the arrow did not find its stretch
    # and was not drawn. It happens as soon as a river passes through the
    # center of the hex.
    network = waterways.build(
        borders, banks, orient,
        STATE.archive.bank_points(STATE.campaign))
    side = max(size * 0.2, 5.0)
    outside: list[str] = []
    # One arrow per drawn line, not per piece: the direction belongs to the line.
    hexes_of: dict = {}
    for arc in network.arcs.values():
        if arc.parent_ is not None:
            hexes_of.setdefault(arc.parent_, set()).update(arc.hexes)
    for parent_ in sorted(hexes_of, key=str):
        entry = currents.get(waterways.text_key(*parent_))
        if not entry:
            continue
        if view is not None and not any(view.can_see(*c)
                                         for c in hexes_of[parent_]):
            continue
        upstream, downstream = entry
        try:
            ax, ay = waterways.node_point(upstream, size, origin, orient)
            bx, by = waterways.node_point(downstream, size, origin, orient)
        except (IndexError, TypeError):
            continue
        mx, my = (ax + bx) / 2, (ay + by) / 2
        along = math.hypot(bx - ax, by - ay) or 1.0
        dx, dy = (bx - ax) / along, (by - ay) / along
        p = side * 0.5
        points = [(mx + dx * p, my + dy * p),
                 (mx - dx * p * 0.6 - dy * p * 0.55, my - dy * p * 0.6 + dx * p * 0.55),
                 (mx - dx * p * 0.6 + dy * p * 0.55, my - dy * p * 0.6 - dx * p * 0.55)]
        trace = "L".join(f"{x:.1f} {y:.1f}" for x, y in points)
        outside.append(f'<path d="M{trace}Z" fill="{CURRENT_COLOR}" '
                     f'stroke="#0b1015" stroke-width="{side * 0.1:.1f}" '
                     f'stroke-linejoin="round"/>')
    return "".join(outside)

PROPOSAL_COLOR = "#ff7043"


def _svg_water_proposal(outcome, size: float, origin, orient: str) -> str:
    """The borders the reading *proposes*, until someone accepts them.

    Drawn above everything else because they are meant to be looked at one by
    one: it is the step where snowy peaks mistaken for water are discarded.
    """
    if outcome is None or not getattr(outcome, "available", False):
        return ""
    # The wet sides *and* the cuts inside the hexes: the proposal is made of
    # both, and showing only half made it look like the reading had found four
    # scattered stretches instead of a system of rivers.
    stretches: list[str] = list(bank_stretches(getattr(outcome, "banks", None) or {},
                                         size, origin, orient))
    for a, b, _kind, _trust in outcome.borders:
        side = hexgrid.shared_side(tuple(a), tuple(b), size, origin, orient)
        if side is None:
            continue
        (x1, y1), (x2, y2) = side
        stretches.append(f"M{x1:.1f} {y1:.1f}L{x2:.1f} {y2:.1f}")

    outside: list[str] = []
    if stretches:
        thickness = max(size * 0.055, 1.8)
        outside.append(f'<path d="{"".join(stretches)}" fill="none" '
                     f'stroke="{PROPOSAL_COLOR}" stroke-width="{thickness:.1f}" '
                     f'stroke-linecap="round"/>')
    return "".join(outside)

def _svg_borders(view, borders: dict, size: float, origin, orient: str) -> str:
    """The marked borders, drawn on the side they divide.

    A border is shown to whoever sees at least one of the two hexes: it is the
    same rule as the fog, and knowing there is a river over there is part of
    what one sees standing on the bank. The three shapes are told apart even
    in black and white: water is solid, the ford dashed, the bridge has a gap
    in the middle.
    """
    if not borders:
        return ""
    full_ones: list[str] = []
    dashed: list[str] = []
    crossings: list[str] = []
    glyphs: list[str] = []
    for (ca, ra, cb, rb), entry in borders.items():
        if not (view.can_see(ca, ra) or view.can_see(cb, rb)):
            continue
        side = hexgrid.shared_side((ca, ra), (cb, rb), size, origin, orient)
        if side is None:
            continue            # no longer neighbours: the grid changed
        (x1, y1), (x2, y2) = side
        kind = entry.get("kind")
        if kind == "ford":
            dashed.append(f"M{x1:.1f} {y1:.1f}L{x2:.1f} {y2:.1f}")
        elif kind == "bridge":
            # Two half stretches and a gap in between: the bridge is the place
            # where the water breaks off, and one sees that it breaks off.
            for a, b in ((0.0, 0.34), (0.66, 1.0)):
                crossings.append(
                    f"M{x1 + (x2 - x1) * a:.1f} {y1 + (y2 - y1) * a:.1f}"
                    f"L{x1 + (x2 - x1) * b:.1f} {y1 + (y2 - y1) * b:.1f}")
            glyphs.append(
                f'<text x="{(x1 + x2) / 2:.1f}" y="{(y1 + y2) / 2:.1f}" '
                f'text-anchor="middle" dominant-baseline="central" '
                f'font-size="{size * 0.26:.1f}">🌉</text>')
        else:
            full_ones.append(f"M{x1:.1f} {y1:.1f}L{x2:.1f} {y2:.1f}")

    thickness = max(size * 0.075, 2.0)
    outside: list[str] = []
    # Same arithmetic as the ford on the river inside the hex: with the round
    # cap the real gap is `gap - thickness`, and below that threshold the
    # dashes vanish inside the line.
    for stretches, extra in ((full_ones, ""),
                          (crossings, ""),
                          (dashed,
                           f' stroke-dasharray="{thickness * 1.2:.1f} '
                           f'{thickness * 2.6:.1f}"')):
        if stretches:
            outside.append(f'<path d="{"".join(stretches)}" fill="none" '
                         f'stroke="{WATER_COLOR}" stroke-width="{thickness:.1f}" '
                         f'stroke-linecap="round" stroke-opacity="0.85"{extra}/>')
    return "".join(outside) + "".join(glyphs)

def _svg_singles(singles, size: float, origin, orient: str,
                 shores: _markers.Shores | None = None) -> str:
    """One path each, every one in its colour and with its label.

    It is «everyone on their own» drawn in full: a single gesture, and one
    sees where everyone goes and how long they take, instead of a single arrow
    telling one journey and keeping quiet about the others. The labels stack
    above the destination because the paths all end there, and overlapping
    they would not be readable.
    """
    if not singles:
        return ""
    outside: list[str] = []
    labels: list[str] = []
    for index, entry in enumerate(singles):
        course = [tuple(c) for c in (entry.get("path") or [])]
        if len(course) < 2:
            continue
        color = entry.get("color") or "#7fc3e8"
        centers = _polyline(course, size, origin, orient, shores,
                           (shores.by_id if shores else {}).get(entry.get("id")))
        line = "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in centers)
        (x1, y1), (x2, y2) = centers[-2], centers[-1]
        length = math.hypot(x2 - x1, y2 - y1) or 1.0
        dx, dy = (x2 - x1) / length, (y2 - y1) / length
        tip = size * 0.42
        bx, by = x2 - dx * tip * 0.55, y2 - dy * tip * 0.55
        wings = [(bx - dy * tip * 0.42, by + dx * tip * 0.42),
               (bx + dy * tip * 0.42, by - dx * tip * 0.42)]
        outside.append(
            f'<path d="{line}" fill="none" stroke="#0b1015" '
            f'stroke-width="{size * 0.12:.1f}" stroke-linecap="round" '
            f'stroke-linejoin="round" stroke-opacity="0.55"/>'
            f'<path d="{line}" fill="none" stroke="{color}" '
            f'stroke-width="{size * 0.07:.1f}" stroke-linecap="round" '
            f'stroke-linejoin="round"/>'
            f'<path d="M{x2:.1f} {y2:.1f} L{wings[0][0]:.1f} {wings[0][1]:.1f} '
            f'L{wings[1][0]:.1f} {wings[1][1]:.1f} Z" fill="{color}" '
            f'stroke="#0b1015" stroke-width="{size * 0.03:.1f}" '
            f'stroke-linejoin="round"/>')
        days = entry.get("days")
        if days is not None:
            ceiling = t("drawing.max_prefix") if entry.get("unknowns") else ""
            text = f'{entry.get("name", "?")} · {ceiling}{tn("drawing.days", days)}'
            labels.append(_tag_label(
                text, x2, y2 - size * (0.72 + 0.62 * len(labels)), size * 0.28,
                edge=color))
    return "".join(outside) + "".join(labels)

def plan_text(plan, of_group: bool = False, lang: str | None = None) -> str:
    """What the journey costs, as read on the arrow's label.

    It lives in a function of its own because the same figure goes to whoever
    watches from another window too: if a different one appeared there — or
    none — the table would be discussing two journeys instead of one. Each
    window reads it in its own language, which is why `lang` can be given.

    With a rendezvous only the days are said: the activities of the common
    road are not the cost of the journey, which starts from where everyone is.
    """
    days = plan.days
    ceiling = i18n.t_in(lang, "drawing.max_prefix") if getattr(plan, "max_estimate", False) else ""
    how_many = i18n.tn_in(lang, "drawing.days", days)
    if of_group:
        return f"{ceiling}{how_many}"
    return ceiling + i18n.t_in(lang, "drawing.plan_full", cost=plan.total_cost, days=how_many)

def _svg_path(course, size: float, origin, orient: str, plan=None,
                  branches=None, rendezvous=None, singles=None, points=None,
                  shores: _markers.Shores | None = None) -> str:
    """The arrow of the proposed journey, as in strategy games.

    The hexes crossed stay watercoloured underneath, but what is read at a
    glance is the arrow: where you leave from, where you arrive, and hanging at
    the end the label with what it costs in activities and days.
    """
    if singles:
        return '<g id="km-path">' + _svg_singles(singles, size, origin,
                                                     orient, shores) + '</g>'
    before = _journey._svg_branches(branches, rendezvous, size, origin, orient, shores)
    if not course:
        return before
    # With a water route the line goes through the points actually sailed —
    # the vertices where the river passes — instead of the hex centers: a
    # route cutting from center to center is not the one you drew, and on a
    # river bend it goes through the fields.
    centers = ([tuple(p) for p in points] if points and len(points) >= 2
              else _polyline(course, size, origin, orient, shores))
    # The **polyline** is looked at, not the row of hexes: a journey inside
    # the departure hex is a single hex, but its road — from the anchor,
    # through the atoms, to the aimed piece — has its points, and must be
    # drawn. As long as the hexes were looked at, the dragged arrow vanished
    # on release and the journey left without showing where.
    if len(centers) < 2:
        # A rendezvous coinciding with the destination: the branches are there
        # all the same, and that is what matters to see — together with the
        # **days**, which sit on the meeting point. The ruler shows them there
        # while you drag; without this line, they vanished on release.
        meeting_point = getattr(rendezvous, "point", None)
        if (meeting_point is not None and plan is not None
                and getattr(plan, "possible", False)):
            banks_here = shores.banks if shores is not None else None
            rendezvous_bank = int(getattr(rendezvous, "bank", 0) or 0)
            lx, ly = _markers.bank_point(tuple(meeting_point), rendezvous_bank, size, origin,
                                orient, banks_here)
            before += _tag_label(plan_text(plan, True), lx, ly - size * 0.72,
                                size * 0.3)
        return '<g id="km-path">' + before + '</g>' if before else before
    silhouettes = "".join(hexgrid.polygon_path(c, r, size, origin, orient) for c, r in course)
    line = "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in centers)

    # The tip looks where the last stretch looks, shortened a hair so the line
    # does not stick out above it.
    (x1, y1), (x2, y2) = centers[-2], centers[-1]
    length = math.hypot(x2 - x1, y2 - y1) or 1.0
    dx, dy = (x2 - x1) / length, (y2 - y1) / length
    tip = size * 0.42
    bx, by = x2 - dx * tip * 0.55, y2 - dy * tip * 0.55
    wings = [(bx - dy * tip * 0.42, by + dx * tip * 0.42),
           (bx + dy * tip * 0.42, by - dx * tip * 0.42)]
    arrow = (f'<path d="M{x2:.1f} {y2:.1f} L{wings[0][0]:.1f} {wings[0][1]:.1f} '
               f'L{wings[1][0]:.1f} {wings[1][1]:.1f} Z" fill="#7fc3e8" '
               f'stroke="#0b1015" stroke-width="{size * 0.03:.1f}" '
               f'stroke-linejoin="round"/>')

    label = ""
    if plan is not None and getattr(plan, "possible", False):
        of_group = rendezvous is not None and getattr(rendezvous, "point", None) is not None
        label = _tag_label(plan_text(plan, of_group), x2,
                               y2 - size * 0.72, size * 0.3)
    elif plan is not None:
        label = _tag_label(t("map.drawing.decided"), x2, y2 - size * 0.72, size * 0.3,
                               edge="#e0705d")

    # All inside a group with a name: while a new one is being traced the
    # browser hides this one, so two arrows are not seen together.
    return ('<g id="km-path">' + before
            + f'<path d="{silhouettes}" fill="#5b8fb02e" stroke="#7fc3e8" '
            f'stroke-width="1.4" stroke-opacity="0.7"/>'
            f'<path d="{line}" fill="none" stroke="#0b1015" '
            f'stroke-width="{size * 0.13:.1f}" stroke-linecap="round" '
            f'stroke-linejoin="round" stroke-opacity="0.55"/>'
            f'<path d="{line}" fill="none" stroke="#7fc3e8" '
            f'stroke-width="{size * 0.08:.1f}" stroke-linecap="round" '
            f'stroke-linejoin="round"/>' + arrow + label + '</g>')

def _polyline(course, size: float, origin, orient: str,
              shores: _markers.Shores | None, bank: int | None = None) -> list:
    """The points of a course: on the shores if we know them, on the centers if not.

    Without `shores` it falls back on the hex centers, which is how it was
    always drawn: on maps without water the two coincide, and the tests that
    do not speak of rivers keep holding.
    """
    if shores is None:
        return [hexgrid.hex_center(c, r, size, origin, orient) for c, r in course]
    first = tuple(course[0]) if course else None
    if bank is None:
        bank = shores.from_where.get(first, 0)
    nodes = _nodes_for(course, getattr(shores, "nodes", ()))
    # The atoms count only for **the** road they were counted on: the
    # rendezvous branches and the separate journeys pass through here with
    # courses of their own, and the rule is the same as for the nodes — if it
    # is not this course, nothing.
    stretches = getattr(shores, "stretches", None) if nodes or not getattr(
        shores, "nodes", ()) else None
    return _markers.course_points(course, size, origin, orient, shores.banks,
                             shores.crossings, bank, nodes=nodes,
                             stretches=stretches if _stretches_for(course, stretches) else None)

def _stretches_for(course, stretches) -> bool:
    """Are the counted atoms of this course? The positions must fit."""
    if not stretches or not course:
        return False
    return all(0 <= int(k) < len(course) for k in stretches)

def _nodes_for(course, nodes) -> tuple:
    """The drawn nodes, if they belong to **this** course. Otherwise nothing.

    The same window draws three things — the road, the rendezvous branches,
    the separate journeys — and the nodes the hand drew belong to one only.
    The check is simple and enough: the hexes of the nodes, with consecutive
    duplicates squashed, must be exactly the course.
    """
    steps = [tuple(c) for c in (course or ())]
    if not nodes or not steps:
        return ()
    hexes: list = []
    for entry in nodes:
        where = (entry[0], entry[1])
        if not hexes or hexes[-1] != where:
            hexes.append(where)
    return tuple(nodes) if hexes == steps else ()

def _tag_label(text: str, cx: float, cy: float, body: float,
               edge: str = "#7fc3e8") -> str:
    """A dark tag with a short caption inside."""
    width = _text_width(text, body)
    height = body * 1.7
    return (f'<rect x="{cx - width / 2:.1f}" y="{cy - height / 2:.1f}" '
            f'width="{width:.1f}" height="{height:.1f}" rx="{height / 2:.1f}" '
            f'fill="#0b1015e6" stroke="{edge}" stroke-width="{body * 0.09:.2f}"/>'
            f'<text x="{cx:.1f}" y="{cy + body * 0.36:.1f}" text-anchor="middle" '
            f'font-size="{body:.1f}" fill="#e9e0cf" font-weight="700" '
            f'font-family="Cinzel, Georgia, serif">{_esc(text)}</text>')

def _dot(bx: float, by: float, radius: float, content_: str, thickness: float,
             edge: str = "#d7b263", color: str = "#f5e3bb") -> list[str]:
    """Dark pill with a sign inside, resting on the corner of an icon."""
    return [
        f'<circle cx="{bx:.1f}" cy="{by:.1f}" r="{radius:.1f}" '
        f'fill="#12100bf2" stroke="{edge}" stroke-width="{thickness:.2f}"/>',
        f'<text x="{bx:.1f}" y="{by + radius * 0.58:.1f}" text-anchor="middle" '
        f'font-size="{radius * 1.25:.1f}" fill="{color}" '
        f'font-family="Cinzel, Georgia, serif" font-weight="700">{content_}</text>',
    ]

def _hex_icons(symbols: list[tuple[str, str, bool]], cx: float, y: float,
               body: float) -> list[str]:
    """Row of icons at the center of the hex, each with its optional dots.

    We draw them one by one instead of as a single string: only so do we know
    where each icon falls and can rest the «×2» of the Resource hex on it,
    instead of writing it alongside.

    On the right the «×2», on the left the padlock of what the players do not
    see yet: a single icon with its dot, not two twin icons.
    """
    if not symbols:
        return []
    outside: list[str] = []
    step = body * 1.15
    radius = body * 0.27
    thickness = body * 0.045
    x0 = cx - step * (len(symbols) - 1) / 2
    for i, (icon, badge_, secret) in enumerate(symbols):
        x = x0 + i * step
        outside.append(f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="middle" '
                     f'font-size="{body:.1f}">{icon}</text>')
        if badge_:
            outside += _dot(x + body * 0.32, y - body * 0.04, radius,
                              badge_, thickness)
        if secret:
            outside += _dot(x - body * 0.32, y - body * 0.04, radius,
                              "🔒", thickness, edge="#9aa0a6", color="#e8eaed")
    return outside

def _text_width(name: str, body: float) -> float:
    """Indicative width of the name in bold Cinzel.

    The SVG is generated on the server, where we cannot really measure text:
    we weigh the letters by family (narrow, normal, wide) and keep a margin,
    so the label never cuts the name.
    """
    weight = 0.0
    for c in name:
        if c in "iljtfr.,;:'!| ":
            weight += 0.4
        elif c.isupper() or c in "mw":
            weight += 1.0
        else:
            weight += 0.7
    return (weight * 1.1 + 0.8) * body

def _split_name(name: str) -> list[str]:
    """Splits the name into two lines as balanced as possible."""
    words = name.split()
    if len(words) < 2:
        return [name]
    cuts = ((" ".join(words[:i]), " ".join(words[i:])) for i in range(1, len(words)))
    before, second_one = min(cuts, key=lambda c: abs(len(c[0]) - len(c[1])))
    return [before, second_one]

def _hex_label(name: str, cx: float, y: float, body: float, max_width: float) -> str:
    """Name of the hex on a dark label.

    Over the illustrated map the black outline alone is not enough: light text
    gets lost on rocks and woods, so we put a semi-transparent plaque behind
    it. Long names wrap onto two lines and, if that is not enough, shrink: the
    label must fit inside its own hex, or it lands on the neighbour's.
    """
    rows = [name]
    if _text_width(name, body) > max_width:
        rows = _split_name(name)

    def width_of(dim: float) -> float:
        return max(_text_width(r, dim) for r in rows)

    width = width_of(body)
    if width > max_width:
        body *= max(0.5, max_width / width)
        width = width_of(body)

    line_height = body * 1.12
    top_row = body * 1.45
    height = top_row + line_height * (len(rows) - 1)
    base_before = y - line_height * (len(rows) - 1)

    outside = [f'<rect x="{cx - width / 2:.1f}" y="{base_before - top_row * 0.78:.1f}" '
             f'width="{width:.1f}" height="{height:.1f}" rx="{top_row / 2:.1f}" '
             f'fill="#12100bd9" stroke="#d7b26359" stroke-width="{max(0.5, body * 0.05):.2f}"/>']
    for i, row in enumerate(rows):
        outside.append(
            f'<text x="{cx:.1f}" y="{base_before + i * line_height:.1f}" text-anchor="middle" '
            f'font-size="{body:.1f}" fill="#f5e3bb" font-weight="700" '
            f'font-family="Cinzel, Georgia, serif" letter-spacing="{body * 0.03:.2f}" '
            f'style="paint-order:stroke;stroke:#000;stroke-width:{body * 0.22:.2f}px;'
            f'stroke-linejoin:round">{_esc(row)}</text>')
    return "".join(outside)

def _esc(s: str) -> str:
    """Text ready for an SVG node or attribute: quotes too."""
    return html.escape(str(s), quote=True)

# --------------------------------------------------------------------------
# The journeys already under way, drawn on the map until they are over.
TRAVEL_COLOR = "#c8a24a"      # dull amber: distinct from the blue proposal

BRANCH_COLOR = "#9fd8f5"         # the approach roads, fainter

def _svg_journeys_in_progress(view, sel: dict, size: float, origin, orient: str) -> str:
    """The routes of those on the road, shortened as they walk.

    They stay visible even outside travel mode — forgetting where half the
    party is going is easy — but can be switched off with the toggle on the
    Travel button icon.
    """
    if not sel.get("show_journeys", True):
        return ""
    known = {p["id"] for p in view.markers()}
    banks = _common.sections_map() if _common.waters_active() else None
    crossings = STATE.archive.campaign_crossings(STATE.campaign) if banks else None
    pieces: list[str] = []
    for journey in STATE.archive.list_journeys(STATE.campaign, "in_progress"):
        for leg in journey.get("legs") or []:
            people = list(leg.get("characters") or [])
            # A journey of characters the viewer cannot see is none of their
            # concern: drawing it would tell where they ended up.
            if not view.gm and not (set(people) & known):
                continue
            points = _leg_points(leg, size, origin, orient, banks, crossings)
            if len(points) < 2:
                continue
            is_on = journey["id"] == sel.get("chosen_journey")
            pieces.append(_svg_route(points, size, is_on))
    return "".join(pieces)

def _leg_points(leg: dict, size: float, origin, orient: str,
                        banks: dict | None, crossings: dict | None) -> list:
    """The polyline of what is left of a leg: from the marker to the aimed piece.

    It starts where the walker is — the anchor of their shore, which is where
    their badge is drawn — passes through the shores and atoms the road had
    touched, and ends on the point of the piece where the journey stops. It is
    `course_points`, the same as the proposal's, on the data frozen in the leg
    at departure; it shortens by itself as the days pass. Old legs, without
    nodes, are redrawn looking for a way through, starting from the shore the
    walker is on.
    """
    path = [tuple(c) for c in (leg.get("path") or [])]
    if len(path) < 2:
        return []
    index, _rest = daily.waypoint_reached(
        list(leg.get("costs") or []), float(leg.get("progress") or 0))
    route = leg.get("route") or []
    waypoint_statuses = leg.get("waypoint_statuses") or []
    if route and waypoint_statuses:
        # On a boat: from the junction one is on, through the junctions left.
        if index >= len(waypoint_statuses):
            return []
        points = []
        for entry in route[int(waypoint_statuses[index]):]:
            node = waterways.node_from_text(entry[0])
            if node is None:
                continue
            try:
                points.append(waterways.node_point(node, size, origin, orient))
            except (IndexError, TypeError):
                continue
        return points if len(points) >= 2 else []
    # A journey inside a single hex is saved as [P, P]: for the drawing it is
    # one hex, with its atoms, until it has arrived.
    steps: list = []
    for c in path:
        if not steps or steps[-1] != c:
            steps.append(c)
    if len(steps) != len(path):
        if index > 0:
            return []
        index = 0
    index = min(index, len(steps) - 1)
    rest = steps[index:]
    nodes = _nodes_for(steps, tuple(tuple(int(x) for x in n)
                                  for n in (leg.get("nodes") or ())))
    rest_nodes = _nodes_from(nodes, index)
    stretches: dict = {}
    for k, v in (leg.get("stretches") or {}).items():
        try:
            spot = int(k) - index
        except (TypeError, ValueError):
            continue
        if spot >= 0 and v:
            stretches[spot] = [int(a) for a in v]
    if len(rest) < 2 and not (len(rest) == 1 and stretches.get(0)):
        return []
    departure_bank = int(rest_nodes[0][2]) if rest_nodes else 0
    if not rest_nodes:
        for char_id in leg.get("characters") or []:
            char = STATE.archive.character(char_id)
            if char is not None and (char.get("hex_col"),
                                     char.get("hex_row")) == rest[0]:
                departure_bank = _markers.section_of(char, banks)
                break
    return _markers.course_points(rest, size, origin, orient, banks, crossings,
                             departure_bank, nodes=rest_nodes or None,
                             stretches=stretches or None)

def _nodes_from(nodes, index: int) -> tuple:
    """The nodes from the `index`-th hex of the course onwards.

    Several consecutive nodes on the same hex are the same hex — a chain of
    bridges inside — and count as one.
    """
    seen, last = -1, None
    for spot, entry in enumerate(nodes or ()):
        where = (entry[0], entry[1])
        if where != last:
            seen += 1
            last = where
        if seen == index:
            return tuple(nodes[spot:])
    return ()

def _svg_route(points, size: float, is_on: bool = False) -> str:
    """A route already decided: dashed, with the destination marked.

    The lit one — chosen from the menu or clicked on the map — is thicker and
    lighter: with four routes around one needs to know which is being talked
    about.
    """
    line = "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in points)
    end_x, end_y = points[-1]
    color = "#ffd77a" if is_on else TRAVEL_COLOR
    thickness = size * (0.075 if is_on else 0.045)
    return (f'<path d="{line}" fill="none" stroke="#0b1015" '
            f'stroke-width="{thickness * 1.8:.1f}" stroke-linecap="round" '
            f'stroke-linejoin="round" stroke-opacity="0.5"/>'
            f'<path d="{line}" fill="none" stroke="{color}" '
            f'stroke-width="{thickness:.1f}" stroke-linecap="round" '
            f'stroke-linejoin="round" stroke-dasharray="{size * 0.12:.1f} '
            f'{size * 0.09:.1f}"/>'
            f'<circle cx="{end_x:.1f}" cy="{end_y:.1f}" r="{size * 0.1:.1f}" '
            f'fill="none" stroke="{color}" stroke-width="{thickness:.1f}"/>')
