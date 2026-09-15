"""Who is where: members per hex, badges and groups, the click on a marker, the spot inside the hex (sections, shores).

It used to live in `ui/hexmap.py`; the `hexmap` facade still re-exports everything.
"""
from __future__ import annotations

import logging
import math
from typing import NamedTuple
from nicegui import ui
from kingmaker.state import STATE
from kingmaker.ui import theme, badges
from kingmaker.geometry import waterways, hexgrid, sections, atoms as atoms_mod
from kingmaker.media import images
from kingmaker import travel as travel_mod

from kingmaker.ui.hexmap import common as _common
from kingmaker.ui.hexmap import drawing as _drawing
from kingmaker.ui.hexmap import travel as _journey
from kingmaker.ui.hexmap import boats as _boats
from kingmaker.locale.i18n import t, tn

log = logging.getLogger(__name__)


def _is_a_vehicle(entry: dict) -> bool:
    """A member of a piece of hex is a person or a vehicle: vehicles carry the
    vehicle page on them, people do not."""
    return bool(entry) and "vehicle" in entry

def _members_per_hex(view) -> dict:
    # The cache lives **on the view**, not in a separate dictionary: two
    # different views (a fake one in the tests, the GM's preview) filter
    # differently, and a key made with `id(view)` was reused as soon as the
    # first was garbage-collected.
    key = (STATE.archive.rev, STATE.k.get("_rev"))
    copy_ = getattr(view, "_members_cache", None)
    if copy_ is not None and copy_[0] == key:
        return copy_[1]
    members = _compute_members_per_hex(view)
    try:
        view._members_cache = (key, members)
    except AttributeError:
        pass
    return members

def _compute_members_per_hex(view) -> dict:
    """Who is in every hex, **people and placed vehicles together**.

    A vehicle placed on the map is a member of its piece of hex like a person:
    if it ends up in the same piece as someone it sits in the group badge with
    them, with the count, and is chosen from the box that opens on click.
    Before, it had a badge of its own, shifted from the row of people: in a
    piece as big as an atom there was no room for two badges, and the wagon
    ended up outside its piece or on top of the faces.

    Whoever is aboard a placed vehicle is **not** a member on their own: they
    travel inside the vehicle, and the vehicle carries them (`passengers`) —
    on the map they show small inside its badge, and are taken by taking the
    vehicle. A wagon with two on it and one on foot beside it make a group of
    **two**: the wagon and the walker. Counting three said the passenger was
    there on their own, and that is not so.

    It is a single list, and both the drawing and the click use it: a marker
    is taken where it is drawn.
    """
    outside: dict = {}
    people = (view.markers() if view is not None
             else [p for p in STATE.characters() if p["hex_col"] is not None])
    vehicles = []
    for entry in STATE.archive.list_stable(STATE.campaign):
        where = travel_mod.where_it_is(entry)
        if where is None:
            continue
        if view is not None and not view.can_see(*where):
            continue
        vehicles.append((where, entry))
    placed = {entry["id"]: where for where, entry in vehicles}
    aboard: dict = {}
    for char in people:
        here = (char["hex_col"], char["hex_row"])
        sid = char.get("stable_id") or ""
        # Aboard only if the vehicle is placed **here**: a link pointing to a
        # vehicle elsewhere is stale, and whoever carries it is on foot.
        if sid in placed and placed[sid] == here:
            aboard.setdefault(sid, []).append(char)
            continue
        outside.setdefault(here, []).append(char)
    in_the = _common.inside_map()
    for where, entry in vehicles:
        # A boat on a corner belongs to three hexes: it goes under the
        # canonical one of the junction, so two boats on the same corner
        # written in two different hexes make a single group.
        node = _boats._boat_node(entry)
        if node is not None and in_the((node[1], node[2])):
            where = (int(node[1]), int(node[2]))
        outside.setdefault(where, []).append(
            dict(entry, passengers=aboard.get(entry["id"], [])))
    return outside

def _svg_markers(view, size: float, origin, orient: str,
                   chosen: set | None = None,
                   choices: set | None = None) -> list[str]:
    """The character markers, in a row at the bottom of the hex.

    The round portrait is clipped with a real `clipPath` and not with a
    `clip-path: circle()` in the stylesheet: this way it stays round even
    where that shape is not supported, instead of becoming a square.
    """
    # Whoever travels on a placed vehicle is not here: they are drawn inside
    # the vehicle's badge. The filter is the same the click uses, or a face
    # would show where it cannot be clicked.
    per_hex = _members_per_hex(view)
    if not per_hex:
        return []
    choices = choices or set()

    # Vehicles have no position of their own: they are where whoever tows
    # them is. Drawing them here, with the markers, means they follow the
    # party without anyone having to remember to move them.
    vehicles = {v["id"]: v for v in STATE.archive.list_stable(STATE.campaign)}
    # Where the river cuts the hex, everyone is drawn towards their own bank.
    banks = _common.sections_map()

    chosen = chosen or set()
    outside: list[str] = []
    for (col, row), people in per_hex.items():
        cx, cy = hexgrid.hex_center(col, row, size, origin, orient)
        outside += _svg_vehicles_on([p for p in people if not _is_a_vehicle(p)],
                                 vehicles, cx, cy, size, chosen)
        seats = marker_positions(people, cx, cy, size, (col, row), origin,
                                    orient, banks)
        for i, (group, x, y, radius) in enumerate(seats):
            # How many are here, and how it is drawn. One: their face. More
            # than one: **the number**, and nothing else.
            #
            # Before, one saw the face of one of the many with a dot holding
            # the count in a corner, and it looked richer. But a face needs
            # room to be recognised, and a piece of hex as big as an atom has
            # none: so the marker had a fixed radius and the small pieces
            # stayed a place one could not stand in. A number instead reads
            # even small, and the badge can shrink down into an atom. Who is
            # there is told by the box that opens on click — where faces are
            # big and names written, which is the right place to recognise
            # someone.
            if len(group) > 1:
                outside += _stack(x, y, radius)
                outside += _group_badge(x, y, radius, len(group), size)
                if any(_taken(q, chosen, choices) for q in group):
                    outside += _chosen_ring(x, y, radius, size)
                continue
            char = group[0]
            if _is_a_vehicle(char):
                # A vehicle alone in its piece: its badge, where the anchor is,
                # with whoever is on it drawn inside, small.
                outside += _vehicle_marker(char, x, y, radius, size,
                                            _taken(char, chosen, choices))
                continue
            color = images.valid_color(char.get("color"))
            # The initials are drawn *always*, and the image goes on top. If
            # the image does not arrive — a slow device, a network that gives
            # up, a file that is gone — the initials in the character's colour
            # remain in its place instead of a hole: a marker that cannot be
            # seen is worth less than one drawn badly.
            initials = "".join(p[0] for p in (char.get("name") or "?").split()[:2]).upper()
            outside.append(
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius:.1f}" fill="#12100bee"/>'
                f'<text x="{x:.1f}" y="{y + radius * 0.36:.1f}" text-anchor="middle" '
                f'font-size="{radius * 0.95:.1f}" fill="{color}" font-weight="700" '
                f'font-family="Cinzel, Georgia, serif">{_drawing._esc(initials)}</text>')
            if char.get("token"):
                key = f"kmtok{col}_{row}_{i}"
                url = images.address(
                    theme.with_prefix("/assets/characters"), _common.CHARACTER_FOLDER,
                    str(char["token"]), images.MARKER_SIDE)
                outside.append(
                    f'<defs><clipPath id="{key}"><circle cx="{x:.1f}" cy="{y:.1f}" '
                    f'r="{radius:.1f}"/></clipPath></defs>'
                    f'<image href="{_drawing._esc(url)}" x="{x - radius:.1f}" y="{y - radius:.1f}" '
                    f'width="{radius * 2:.1f}" height="{radius * 2:.1f}" '
                    f'preserveAspectRatio="xMidYMid slice" clip-path="url(#{key})"/>')
            outside.append(
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius:.1f}" fill="none" '
                f'stroke="{color}" stroke-width="{max(1.0, size * 0.05):.1f}"/>')
            if char["id"] in chosen:
                outside += _chosen_ring(x, y, radius, size)
    return outside

def _taken(entry: dict, chosen: set, choices: set) -> bool:
    """Whether that member is in hand: the person, the vehicle, or whoever is aboard it."""
    if entry["id"] in chosen or entry["id"] in choices:
        return True
    return any(p["id"] in chosen for p in entry.get("passengers") or ())

def _group_badge(x: float, y: float, radius: float, how_many: int,
                      size: float) -> list[str]:
    """The marker of several people in the same piece: the count, in gold.

    Gold and not someone's colour: here there is no character to recognise,
    there is a place where many are. The colour of one of the many would say
    something false — that the badge is theirs.

    The body of the number narrows with the digits, or a «12» in an atom
    would stick out of its badge.
    """
    text = str(how_many)
    body = radius * (1.15 if len(text) < 2 else 0.92 if len(text) < 3 else 0.72)
    return [
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius:.1f}" fill="#12100bf2"/>',
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius:.1f}" fill="none" '
        f'stroke="{GROUP_COLOR}" stroke-width="{max(1.0, size * 0.045):.1f}"/>',
        f'<text x="{x:.1f}" y="{y + body * 0.35:.1f}" text-anchor="middle" '
        f'font-size="{body:.1f}" fill="{GROUP_COLOR}" font-weight="700" '
        f'font-family="Cinzel, Georgia, serif">{text}</text>']

# How big a marker's badge is: **what its piece of hex grants it**, not a
# fixed number. Before there were two numbers — 0.24 in a whole hex, 0.20 in
# a cut one — and they held as long as a hex was cut into two or three
# pieces. With twenty-four atoms a 0.20 badge is five times the piece it
# should sit in: one sees twenty-four overlapping discs and no longer
# understands who is where.
#
# The measure is **the area**, not the room around the centroid: where a
# river enters and stops, the piece stays as big as the hex but the centroid
# falls on the slit, and measuring from there would give zero for a piece
# that is the whole hex. The badge covers about **a tenth** of the area of
# its piece, and the two numbers of before come out on their own: a whole hex
# reaches the ceiling (0.24) and two shores make 0.20, exactly what the app
# has always drawn.
BADGE_SHARE = 0.311        # radius = this × √(area/π): a tenth of the area

BADGE_RADIUS = 0.24            # the ceiling: the badge of a whole hex

MIN_RADIUS = 0.055          # and the floor: below it a number cannot be read

BOAT_RADIUS = 0.16            # the badge of a boat, on its water junction

# The click target does not go below this, even when the badge is smaller:
# an atom drawn at ten pixels is perfectly visible and badly grabbed. Between
# two hit badges the nearest wins anyway, so being generous never steals a
# marker from the neighbour — it only widens the grip on the right one.
MIN_GRIP = 0.085

def badge_radius(face, size: float, max_: float = BADGE_RADIUS) -> float:
    """The marker radius of that piece of hex, in pixels.

    Two limits, serving two different things: **the area** says how big the
    piece is, and **the breath** how far one can go from its point without
    ending up in another piece (`sections.breath`). Normally the area rules —
    on the live save the breath squeezes none of the 166 pieces — but where
    the point of a wide piece happens to be a hair from a water line the
    breath keeps the badge from hopping over it: a marker sticking out beyond
    the water says the thing this model was built to no longer say.
    """
    area = abs(getattr(face, "area", 0.0) or 0.0)
    if not area:
        return size * max_
    how_much = BADGE_SHARE * math.sqrt(area / math.pi)
    wide = sections.breath(face)
    if wide:
        how_much = min(how_much, wide)
    return size * min(max_, max(MIN_RADIUS, how_much))

def _grip(radius: float, size: float) -> float:
    """How wide the click target is around a badge."""
    return max(radius, size * MIN_GRIP)

GROUP_COLOR = "#d7b263"      # the app's gold: «many are here», not «it is theirs»

def _stack(x: float, y: float, radius: float) -> list[str]:
    """Two slightly offset discs behind the marker: there is more than one inside.

    It is the sign, not the count — the count is the dot. It lets one see that
    the badge can be opened even before reading the number.
    """
    return [f'<circle cx="{x + radius * 0.18:.1f}" cy="{y - radius * 0.18:.1f}" '
            f'r="{radius:.1f}" fill="#12100b" fill-opacity="0.55"/>',
            f'<circle cx="{x + radius * 0.09:.1f}" cy="{y - radius * 0.09:.1f}" '
            f'r="{radius:.1f}" fill="#12100b" fill-opacity="0.75"/>']

def _vehicle_marker(entry: dict, x: float, y: float, radius: float,
                       size: float, chosen_one: bool = False) -> list[str]:
    """The badge of a vehicle: the uploaded marker, or the symbol of what it is."""
    outside: list[str] = []
    is_off = not entry.get("available")
    edge = "#8a7a58" if is_off else "#d7b263"
    veiling = ' opacity="0.45"' if is_off else ""
    if entry.get("token"):
        key = f"kmvei{int(x)}_{int(y)}_{_drawing._esc(str(entry.get('id') or ''))}"
        url = images.address(
            theme.with_prefix("/assets/vehicles"), _common.VEHICLE_FOLDER,
            str(entry["token"]), images.MARKER_SIDE)
        outside.append(
            f'<defs><clipPath id="{key}"><circle cx="{x:.1f}" cy="{y:.1f}" '
            f'r="{radius:.1f}"/></clipPath></defs>'
            f'<image href="{_drawing._esc(url)}" x="{x - radius:.1f}" y="{y - radius:.1f}" '
            f'width="{radius * 2:.1f}" height="{radius * 2:.1f}" '
            f'preserveAspectRatio="xMidYMid slice" clip-path="url(#{key})"'
            f'{veiling}/>')
    else:
        # The symbol of what it is: a boat marked as a horse made one believe
        # the app had not recognised it as a boat. With someone aboard the
        # symbol rises a little, to leave room for the faces along the bottom
        # edge.
        with_people = bool(entry.get("passengers"))
        outside.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius:.1f}" fill="#12100bcc"/>'
            f'<text x="{x:.1f}" y="{y + radius * (0.1 if with_people else 0.38):.1f}" '
            f'text-anchor="middle" font-size="{radius * (0.85 if with_people else 1.05):.1f}">'
            f'{travel_mod.vehicle_symbol(entry)}</text>')
    outside += _passengers_in_badge(entry.get("passengers") or [], x, y, radius,
                                   size, is_off)
    outside.append(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius:.1f}" fill="none" '
        f'stroke="{edge}" stroke-width="{max(1.0, size * 0.04):.1f}" '
        f'stroke-dasharray="{size * 0.09:.1f} {size * 0.05:.1f}"/>')
    if chosen_one:
        outside += _chosen_ring(x, y, radius, size)
    return outside

def _passengers_in_badge(passengers: list, x: float, y: float, radius: float,
                          size: float, is_off: bool = False) -> list[str]:
    """Who is aboard, small inside the vehicle's badge, along the bottom edge.

    It is the same language as the «x2» of a Resource Hex: the vehicle stays
    the marker, and whoever travels on it shows inside — one sees who travels
    **with** whom without opening anything. Up to three faces; beyond, two
    and a «+n».
    """
    if not passengers:
        return []
    shown = list(passengers[:3]) if len(passengers) <= 3 else list(passengers[:2])
    rest = len(passengers) - len(shown)
    how_many = len(shown) + (1 if rest else 0)
    small = radius * 0.34
    step = small * 1.9
    x0 = x - step * (how_many - 1) / 2
    ay = y + radius * 0.48
    edge = max(0.8, size * 0.025)
    veiling = ' opacity="0.45"' if is_off else ""
    outside: list[str] = []
    for i, char in enumerate(shown):
        px = x0 + i * step
        color = images.valid_color(char.get("color"))
        initial = ((char.get("name") or "?").strip()[:1] or "?").upper()
        outside.append(
            f'<g{veiling}>'
            f'<circle cx="{px:.1f}" cy="{ay:.1f}" r="{small:.1f}" fill="#12100bee"/>'
            f'<text x="{px:.1f}" y="{ay + small * 0.36:.1f}" text-anchor="middle" '
            f'font-size="{small * 1.05:.1f}" fill="{color}" font-weight="700" '
            f'font-family="Cinzel, Georgia, serif">{_drawing._esc(initial)}</text>')
        if char.get("token"):
            key = f"kmpass{int(px)}_{int(ay)}_{_drawing._esc(str(char.get('id') or ''))}"
            url = images.address(
                theme.with_prefix("/assets/characters"), _common.CHARACTER_FOLDER,
                str(char["token"]), images.MARKER_SIDE)
            outside.append(
                f'<defs><clipPath id="{key}"><circle cx="{px:.1f}" cy="{ay:.1f}" '
                f'r="{small:.1f}"/></clipPath></defs>'
                f'<image href="{_drawing._esc(url)}" x="{px - small:.1f}" y="{ay - small:.1f}" '
                f'width="{small * 2:.1f}" height="{small * 2:.1f}" '
                f'preserveAspectRatio="xMidYMid slice" clip-path="url(#{key})"/>')
        outside.append(
            f'<circle cx="{px:.1f}" cy="{ay:.1f}" r="{small:.1f}" fill="none" '
            f'stroke="{color}" stroke-width="{edge:.1f}"/></g>')
    if rest:
        px = x0 + len(shown) * step
        outside.append(
            f'<g{veiling}><circle cx="{px:.1f}" cy="{ay:.1f}" r="{small:.1f}" '
            f'fill="#12100bee" stroke="{GROUP_COLOR}" stroke-width="{edge:.1f}"/>'
            f'<text x="{px:.1f}" y="{ay + small * 0.36:.1f}" text-anchor="middle" '
            f'font-size="{small * 0.95:.1f}" fill="{GROUP_COLOR}" font-weight="700" '
            f'font-family="Cinzel, Georgia, serif">+{rest}</text></g>')
    return outside

def _svg_vehicles_on(people: list[dict], vehicles: dict, cx: float, cy: float,
                    size: float, chosen: set | None = None) -> list[str]:
    """The markers of the vehicles the people of this hex carry along.

    They sit above the row of characters and a hair bigger: a wagon is seen
    from afar, and must not cover the faces. One per vehicle, not one per
    passenger — the carriage is one even if three travel in it.

    Taking a character in hand lights up their vehicle too, with the same
    dashing: it is the shortest way to say «this wagon is theirs» without
    writing it anywhere.
    """
    chosen = chosen or set()
    present: dict[str, dict] = {}
    whose: dict[str, list[str]] = {}
    for char in people:
        key = char.get("stable_id") or ""
        entry = vehicles.get(key)
        if entry is None:
            continue
        # A boat put in the water has a marker of its own, where it is: if we
        # drew it here too there would be two, and the viewer would not know
        # which of the two is the boat.
        if entry.get("hex_col") is not None and entry.get("hex_row") is not None:
            continue
        present.setdefault(key, entry)
        whose.setdefault(key, []).append(char["id"])
    if not present:
        return []

    outside: list[str] = []
    radius = size * 0.27
    step = radius * 2.1
    y = cy - size * 0.06
    x0 = cx - step * (len(present) - 1) / 2
    for i, (entry_key, entry) in enumerate(present.items()):
        outside += _vehicle_marker(
            entry, x0 + i * step, y, radius, size,
            any(char_id in chosen for char_id in whose.get(entry_key, ())))
    return outside

def _chosen_ring(x: float, y: float, radius: float, size: float) -> list[str]:
    """The sign of «I took this in hand», around a marker.

    It is the same white dashing as the selected hex: whoever plays learns a
    single sign. We put a dark ring under it, or on the light of the map the
    white dashes vanish.
    """
    wide = radius * 1.32
    return [
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{wide:.1f}" fill="none" '
        f'stroke="#12100b" stroke-width="{max(2.4, size * 0.045):.1f}" '
        f'stroke-opacity="0.75"/>',
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{wide:.1f}" fill="none" '
        f'stroke="#ffffff" stroke-width="{max(1.6, size * 0.028):.1f}" '
        f'stroke-dasharray="{size * 0.06:.1f} {size * 0.045:.1f}"/>',
    ]

# --------------------------------------------------------------------------
# Travel mode: taking a group from the map and aiming it at a destination.
def characters_on(coord: tuple[int, int], view) -> list[dict]:
    """The markers on that hex, **on the ground**.

    Whoever travels on a placed vehicle has no marker of their own: they are
    drawn inside the vehicle's badge, small, as the «×2» of a Resource Hex
    sits on its icon. Before, they sat beside it, and with three passengers
    the hex became a row of faces in which the vehicle was just another pill
    — one no longer saw who travels **with** whom.

    It lives here and not in the drawing because the same list serves the
    click: a marker is taken where it is drawn, and one inside the vehicle is
    taken by clicking the vehicle.
    """
    # The same list as the drawing: whoever is aboard a placed vehicle is not
    # in it, they are inside the vehicle, and a click on the ground does not
    # take them alone.
    return [p for p in _members_per_hex(view).get(tuple(coord), [])
            if not _is_a_vehicle(p)]

# There is no pull towards the hex center any more, and the reason is that
# it is no longer needed. It was needed when a shore was a group of sides and
# its shape an approximate polygon, closed by a straight chord even where the
# water meandered: the centroid of that figure landed on the line, and one
# pulled back by eye. Now a section is the real face, and its point is the
# centroid of the face — inside by construction. Pulling it towards the hex
# center today would do the opposite harm: for a slice far from the center it
# would take it **outside** its section, and sometimes across the water.


def section_of(entry: dict, banks: dict | None) -> int:
    """Which section a marker or a vehicle is on now.

    On disk a **point** is written, not a number: the number counts faces and
    changes meaning as soon as the GM draws another water line. The section
    is an answer that is recomputed, and it is recomputed here.
    """
    col, row = entry.get("hex_col"), entry.get("hex_row")
    if col is None or row is None:
        return 0
    return sections.section_of(entry, (banks or {}).get((int(col), int(row))))

def spot_of_section(coord, bank: int, banks: dict | None):
    """The point to save to say «I am on this section of this hex».

    None where the water does not cut, and it means «in the middle»: it is
    almost the whole map, and writing a point there would be writing a
    precision that is not there.
    """
    return sections.section_spot((banks or {}).get(tuple(coord)), bank)

def bank_point(coord, bank: int, size: float, origin, orient: str,
               banks: dict | None) -> tuple[float, float]:
    """The point that *is* that shore: the centroid of its piece of hex.

    A hex stays two coordinates, and rightly so: it is how players call it.
    But where the river cuts, «where you are» is not enough to say where you
    can leave from, and drawing everything at the center — markers, arrows,
    vehicles — makes it look astride the water. Worse: two shores with the
    same point cannot even be pointed at with the mouse, and to pass a bridge
    one had to hit the icon.

    The shape of the piece and its centroid are known by `sections.py`, which
    cuts the real faces of the hex: here one only goes from its units — hex
    radii from the cell center — to the pixels of the drawing.

    Without a river — and that is almost every hex — it is the center, as it
    always was.
    """
    cx, cy = hexgrid.hex_center(coord[0], coord[1], size, origin, orient)
    faces = (banks or {}).get(tuple(coord))
    if not faces or len(faces) < 2 or not (0 <= bank < len(faces)):
        return cx, cy
    # The face already has its point, and it is inside by construction: no
    # more pieces without a centroid, and no more fallbacks on the hex
    # center. It is in hex radii, counted from the cell center.
    bx, by = faces[bank].point
    return cx + bx * size, cy + by * size

def _is_cut(coord, banks: dict | None) -> bool:
    """Is the hex divided by the water into more than one piece?"""
    if not banks or coord is None:
        return False
    return len((banks or {}).get(tuple(coord)) or []) > 1

def _shores_of(sel: dict) -> "Shores | None":
    """The shores for this window's drawing, or None if there is no water.

    `None` is not an error case: it is the map without rivers, where a shore
    means nothing and the course is drawn on the centers as it always was.
    """
    if not _common.waters_active():
        return None
    banks = _common.sections_map()
    if not banks:
        return None
    chosen = set(sel.get("travel_pcs") or ())
    travelling = [p for p in STATE.characters() if p["id"] in chosen]
    from_where, by_id = {}, {}
    for char in travelling:
        if char["hex_col"] is None:
            continue
        # Two on opposite shores of the same hex travel together on a single
        # road: it starts from one of the two, and the bridge in between is a
        # step of the journey like the others. For the **separate** journeys
        # instead everyone leaves from home, and that is told by `by_id`.
        from_where.setdefault((char["hex_col"], char["hex_row"]),
                           section_of(char, banks))
        by_id[char["id"]] = section_of(char, banks)
    # The same crossings the pathfinder used, swimming included: it is
    # `nodes_on_course` that walks the road again to know which shore one
    # passes on, and if the passages here were fewer than there the arrow
    # would stop halfway — drawn up to the river and then nothing.
    crossings = STATE.archive.campaign_crossings(STATE.campaign)
    if travelling and travel_mod.party_swims(travelling)[0]             and not _journey._aboard_by_water(sel, travelling):
        crossings = travel_mod.swim_crossings(banks, crossings)
    # The meeting point is a shore: the common road starts from it, and the
    # branches reach it. Without this the common road started from shore 0 of
    # its first hex, which in a cut hex may be across the water.
    rendezvous = sel.get("rendezvous")
    meeting_point = getattr(rendezvous, "point", None)
    if meeting_point is not None:
        from_where[tuple(meeting_point)] = int(getattr(rendezvous, "bank", 0) or 0)
    return Shores(banks=banks, crossings=crossings, from_where=from_where, by_id=by_id,
                  nodes=tuple(sel.get("nodes") or ()),
                  stretches=dict(sel.get("atom_stretches") or {}))

class Shores(NamedTuple):
    """What the drawing needs to know which side of the water one passes on.

    `from_where` is the shore the leaver is on, hex by hex: a course starts
    where its traveller is, and without that datum the first waypoint would
    have to be guessed. It lives here and not in three scattered parameters
    because the courses to draw are three — the common road, the rendezvous
    branches, the separate journeys — and they must all answer the same way.
    """
    banks: dict
    crossings: dict
    from_where: dict          # hex -> shore, for the common road
    by_id: dict           # character -> shore, for the separate journeys
    # The shores the hand touched, when the road was drawn. Without them the
    # drawing rebuilds them looking for a way through — and in a hex with
    # three bridges the ways are more than one: on release the arrow changed
    # shape on its own, because it found another.
    nodes: tuple = ()
    # And the atoms the arithmetic crossed, waypoint by waypoint: the arrow
    # goes through those, so what is seen is what is paid.
    stretches: dict = None

def anchor_markers(coord, bank: int, size: float, origin, orient: str,
                     banks: dict | None) -> tuple[float, float]:
    """Where the row of markers of that shore is.

    It is also the point the journey arrow starts from: an arrow born from the
    hex center while the leaver is drawn elsewhere looks like someone else's
    road. A single place that knows it, or the day the row moves the arrow is
    left behind.
    """
    if _is_cut(coord, banks) and origin is not None:
        return bank_point(coord, bank, size, origin, orient, banks)
    cx, cy = hexgrid.hex_center(coord[0], coord[1], size, origin, orient)
    return cx, cy + size * 0.60

def course_points(course, size: float, origin, orient: str,
                      banks: dict | None, crossings: dict | None = None,
                      departure_bank: int = 0,
                      nodes=None, stretches=None) -> list[tuple[float, float]]:
    """The polyline to draw a course on, shore by shore.

    From center to center, in a hex the river cuts, the arrow passes over the
    water even when the journey does not cross it: the viewer does not know
    which way one is going, and the drawn road says something that does not
    happen. Here every waypoint takes the point of **its** shore, and the
    first takes the markers' anchor: the arrow comes out of the leaver.
    """
    steps = [tuple(c) for c in (course or [])]
    if not steps:
        return []
    # The nodes the hand drew, if any: the arrow after release must be the one
    # of before. Without them the course is walked again looking for a way
    # through — which is right, but where the ways are more than one it is
    # not necessarily the one you drew.
    by_hand = bool(nodes)
    if not nodes:
        nodes = travel_mod.nodes_on_course(steps, banks or {}, crossings, orient,
                                            departure_bank)
    outside = []
    if stretches:
        # By atoms: where the arithmetic went by atoms, the arrow goes through
        # the same. The first waypoint is the leaver's anchor; the waypoints
        # in whole hexes keep their point; the last, if it has an aimed piece,
        # ends on the point of that piece — where the marker is placed.
        pieces = atoms_mod.atoms(orient)
        first = nodes[0] if nodes else (steps[0][0], steps[0][1], departure_bank)
        outside.append(anchor_markers((first[0], first[1]), first[2], size,
                                      origin, orient, banks))
        last_bank = nodes[-1][2] if nodes else 0
        if not by_hand:
            # Without the hand's shores the last is the one **the atoms end
            # in**, not the one entered from: aiming with the right button at
            # the shore beyond, the arrow reached it through the atoms and
            # then came back to the point of the entry shore.
            last_ones = stretches.get(len(steps) - 1) or stretches.get(str(len(steps) - 1))
            faces = (banks or {}).get(steps[-1]) or ()
            if last_ones and len(faces) > 1:
                found_one = sections.face_of_point(faces, pieces[last_ones[-1]].point)
                if found_one is not None:
                    last_bank = int(found_one)
        if len(steps) == 1 and stretches.get(0):
            # Inside the departure hex: from the anchor, through the atoms, to
            # the point of the shore one stops on.
            cx, cy = hexgrid.hex_center(steps[0][0], steps[0][1], size, origin,
                                        orient)
            outside += [(cx + pieces[a].point[0] * size, cy + pieces[a].point[1] * size)
                      for a in stretches[0][1:]]
            outside.append(bank_point(steps[0], last_bank, size, origin, orient,
                                    banks))
            return outside
        for spot in range(1, len(steps)):
            col, row = steps[spot]
            cx, cy = hexgrid.hex_center(col, row, size, origin, orient)
            atoms_here = stretches.get(spot) or stretches.get(str(spot))
            if atoms_here:
                outside += [(cx + pieces[a].point[0] * size,
                           cy + pieces[a].point[1] * size) for a in atoms_here]
            else:
                bank = next((n[2] for n in nodes if (n[0], n[1]) == (col, row)), 0)
                outside.append(bank_point((col, row), bank, size, origin, orient,
                                        banks))
        if _is_cut(steps[-1], banks):
            outside.append(bank_point(steps[-1], last_bank, size, origin,
                                    orient, banks))
        return outside
    for spot, (col, row, bank) in enumerate(nodes):
        if spot == 0:
            outside.append(anchor_markers((col, row), bank, size, origin,
                                          orient, banks))
        else:
            outside.append(bank_point((col, row), bank, size, origin, orient, banks))
    return outside

def marker_positions(people: list[dict], cx: float, cy: float, size: float,
                        coord=None, origin=None, orient: str = "pointy",
                        banks: dict | None = None):
    """Where the marker of every shore is, and **who is inside it**.

    One marker per shore, not one per person. Before, they stood in a row, up
    to four, and the others became a «+n» that could not even be clicked: a
    row of four badges does not fit in half a shore, and indeed it stuck out.
    Now it is like the app folder on a phone — a single badge with the sign
    that there is more than one inside — and clicking it opens and one chooses.

    Returns `(group, x, y, radius)`: the group is the list of who is there,
    and **is never truncated**. It serves two trades, drawing and figuring
    out where the mouse clicked, and the two counts must come from the same
    place or sooner or later the click takes the wrong character.

    In a whole hex the badge sits below the center, as it always has. Where a
    river cuts, every shore has its own, inside its own piece of hex: those on
    this side and those on that side are not seen as next-door neighbours
    brushing against each other, they are seen separated by the water as they
    are.
    """
    if not people:
        return []
    # Boats sit on their junction, not on the shore's row: it is a point of
    # the water, and two boats on the same junction are a group with the
    # count, like two people in the same piece.
    outside = []
    rest = []
    if origin is not None:
        orient_here = orient
        m_here = STATE.k["map"]
        per_node: dict = {}
        for entry in people:
            node = _boats._boat_node(entry)
            if node is None:
                rest.append(entry)
            else:
                per_node.setdefault(node, []).append(entry)
        for node, group in sorted(per_node.items(), key=lambda kv: str(kv[0])):
            try:
                x, y = waterways.node_point(node, size, origin, orient_here)
            except (IndexError, TypeError):
                rest.extend(group)
                continue
            outside.append((group, x, y, size * BOAT_RADIUS))
        people = rest
        if not people:
            return outside
    is_cut = _is_cut(coord, banks) and origin is not None
    if not is_cut:
        return outside + [(list(people), cx, cy + size * 0.60, size * BADGE_RADIUS)]
    faces = (banks or {}).get(tuple(coord)) or ()
    per_bank: dict[int, list] = {}
    for char in people:
        per_bank.setdefault(section_of(char, banks), []).append(char)
    for bank, group in sorted(per_bank.items()):
        ax, ay = anchor_markers(coord, bank, size, origin, orient, banks)
        face = faces[bank] if 0 <= bank < len(faces) else None
        outside.append((group, ax, ay, badge_radius(face, size)))
    return outside

def marker_under(view, map_data: dict, point, coord):
    """The **group** the click landed on, or None if it hit the ground.

    A marker on the map is one per shore and can hold more than one, so the
    answer is a list: the caller decides whether to take the only one there
    or ask which.

    The neighbouring hexes are looked at too, not only the one under the
    pointer. A marker sits in a row below the center of its hex and, when
    there are four or when the river shifts it towards its bank, the drawing
    ends up beyond the edge. Asking «who is in the hex I clicked» then gave
    the wrong answer: the marker was visible and could not be taken. The
    right question is «which marker did I hit», and a marker is hit where it
    is drawn.

    The target however does not go below a minimum size, even where the badge
    is smaller than that: a marker inside an atom is perfectly visible and
    would be badly grabbed. Between two hit badges the nearest wins anyway,
    so the generous hand steals nothing from the neighbour — it only widens
    the grip on the one you were trying to take.
    """
    size = float(map_data["size"])
    origin = (float(map_data["origin_x"]), float(map_data["origin_y"]))
    orient = map_data["orientation"]
    banks = _common.sections_map()
    coord = tuple(coord)
    neighbours = [coord] + [tuple(v) for v in
                        hexgrid.neighbours(coord[0], coord[1], orient)]
    best, dist = None, None
    members = _members_per_hex(view)
    for where in neighbours:
        people = members.get(where)
        if not people:
            continue
        cx, cy = hexgrid.hex_center(where[0], where[1], size, origin, orient)
        for group, x, y, radius in marker_positions(
                people, cx, cy, size, where, origin, orient, banks):
            d = math.hypot(point[0] - x, point[1] - y)
            # The nearest among those hit: two markers of different hexes can
            # overlap, and the one you clicked on wins.
            if d <= _grip(radius, size) and (dist is None or d < dist):
                best, dist = group, d
    return best

def _choose_from_click(mine: dict, mapping, coord, point, ctrl: bool) -> None:
    """Who leaves, decided by the click on the map.

    Three gestures, one per intention: the ground of the hex takes everyone
    standing on it (usually the group travelling together), a precise marker
    takes only that one, and ctrl adds to the choice instead of replacing it.
    Clicking where nobody is drops everything: it is the way to start over
    without leaving the mode.
    """
    view = _common._current_view(mine)
    group = marker_under(view, STATE.k["map"], point, coord)
    # A marker can hold more than one: clicking it opens it and asks which,
    # like an app folder on a phone. Not with ctrl — there one is adding to
    # the choice, and adding the whole group in one go is exactly what is
    # wanted.
    if group and len(group) > 1 and not ctrl:
        _open_group(mine, mapping, group)
        return
    if group and len(group) == 1 and _is_a_vehicle(group[0]):
        # A vehicle alone in its piece: it is taken in hand, with whoever is
        # on it.
        _boats._choose_vehicle(mine, mapping, group[0])
        return
    # With ctrl on a group containing a vehicle the people are added: the
    # vehicle comes by itself, if they are all aboard (`_vehicle_of`).
    people = [p for p in (list(group) if group else characters_on(coord, view))
             if not _is_a_vehicle(p)]
    chosen = list(mine.get("travel_pcs") or [])

    if not people:
        passing = _journey._passing_journey(coord)
        if passing is not None:
            # Free ground but crossed by a route: one is pointing at that, not
            # dropping the group.
            _journey._choose_journey(passing, mine, mapping)
            return
        if not chosen and not mine.get("chosen_journey"):
            return
        chosen = []
    elif ctrl:
        for char in people:
            if char["id"] in chosen:
                chosen.remove(char["id"])
            else:
                chosen.append(char["id"])
    else:
        new_items = [p["id"] for p in people]
        # Clicking the same choice again removes it: so even without ctrl one
        # can let go of the group in hand.
        chosen = [] if new_items == chosen else new_items

    mine["travel_pcs"] = chosen
    mine["travel_vehicle"] = _vehicle_of(chosen)
    _common._forget_plan(mine)
    # If the chosen ones are already travelling, we light up their journey:
    # it is the way to find it in the list without looking for it.
    travelling = _journey.journeys_by_character(set(chosen))
    mine["chosen_journey"] = (next(iter(travelling.values()))["id"]
                             if travelling else None)
    _journey._redraw_travel(mine, mapping)

def _apply_choice(mine: dict, mapping, people_ids: list, vehicle_id=None) -> None:
    """Takes in hand what was chosen in the group box.

    With a vehicle: one leaves with it, with whoever is on it and with whoever
    was added (like `_choose_vehicle`, which is the same rule from the click
    on the map). Without: the people only, and the vehicle comes by itself if
    they are all aboard the same one (`_vehicle_of`).
    """
    ids = list(dict.fromkeys(people_ids))
    if vehicle_id:
        aboard = [p["id"] for p in STATE.archive.characters_on_vehicle(vehicle_id)]
        ids = list(dict.fromkeys(aboard + ids))
        mine["travel_vehicle"] = vehicle_id
        mine["aboard"] = True
        mine["col"] = mine["row"] = None
    else:
        mine["travel_vehicle"] = _vehicle_of(ids)
    mine["travel_pcs"] = ids
    _common._forget_plan(mine)
    travelling = _journey.journeys_by_character(set(ids))
    mine["chosen_journey"] = (next(iter(travelling.values()))["id"]
                             if travelling else None)
    _journey._redraw_travel(mine, mapping)


def _open_group(mine: dict, mapping, group: list) -> None:
    """The box that opens by clicking a marker holding more than one.

    On the map a marker is one per shore, or they would not fit in half a
    shore: when there is more than one inside, the badge carries the stack
    sign and the number, and clicking it opens here. Everyone with their
    portrait and their name, big enough to be recognised — which is the whole
    point, given that on the map at that size they could not be told apart.

    Three gestures, as on the map: a click takes **that one** and closes;
    «Everyone» takes them all; **ctrl+click** adds one at a time — people and
    vehicles, boats stopped on the same junction too — and «Take the chosen»
    closes. One vehicle at a time: one leaves with a single vehicle, and
    whoever is on it comes along.
    """
    people_ = [x for x in group if not _is_a_vehicle(x)]
    vehicles = [x for x in group if _is_a_vehicle(x)]
    choice = {"people": [], "vehicle": None}

    def take(ids: list, vehicle_id=None) -> None:
        dlg.close()
        _apply_choice(mine, mapping, ids, vehicle_id)

    def ctrl_pressed(e) -> bool:
        args = getattr(e, "args", None)
        return bool(args.get("ctrlKey")) if isinstance(args, dict) else False

    def person_click(e, char: dict) -> None:
        if not ctrl_pressed(e):
            take([char["id"]])
            return
        if char["id"] in choice["people"]:
            choice["people"].remove(char["id"])
        else:
            choice["people"].append(char["id"])
        body.refresh()

    def vehicle_click(e, entry: dict) -> None:
        if not ctrl_pressed(e):
            take([], entry["id"])
            return
        if choice["vehicle"] == entry["id"]:
            choice["vehicle"] = None
        else:
            if choice["vehicle"] is not None:
                theme.notify(t("map.markers.departing_single_vehicle_this"), "info")
            choice["vehicle"] = entry["id"]
        body.refresh()

    def chosen_count() -> int:
        aboard = 0
        if choice["vehicle"]:
            aboard = 1 + len([x for x in vehicles if x["id"] == choice["vehicle"]
                               for _p in (x.get("passengers") or [])])
        return len(choice["people"]) + aboard

    def vehicle_badge(entry: dict) -> None:
        passengers = list(entry.get("passengers") or [])
        taken = choice["vehicle"] == entry["id"]
        with ui.column().classes("items-center gap-1") \
                .style("cursor:pointer;width:76px;border-radius:8px;padding:4px"
                       + (";background:#d7b26322;outline:2px solid #d7b263" if taken else "")) \
                .on("click", lambda e, x=entry: vehicle_click(e, x), ["ctrlKey"]):
            badge = ui.element("div").classes("items-center justify-center") \
                .style("width:56px;height:56px;border-radius:50%;"
                       "border:2px dashed #d7b263;background:#12100b;"
                       "display:flex;overflow:hidden;position:relative")
            with badge:
                if entry.get("token"):
                    ui.image(images.address(
                        "/assets/vehicles", _common.VEHICLE_FOLDER,
                        str(entry["token"]), images.MARKER_SIDE)) \
                        .style("width:56px;height:56px;object-fit:cover")
                else:
                    ui.label(travel_mod.vehicle_symbol(entry)) \
                        .style("font-size:1.4rem" + (
                            ";margin-bottom:14px" if passengers else ""))
                if passengers:
                    with ui.element("div").style(
                            "position:absolute;left:0;right:0;bottom:2px;"
                            "display:flex;justify-content:center;gap:2px"):
                        for char in passengers[:3]:
                            badges.person_badge(char, 18)
                        if len(passengers) > 3:
                            ui.label(f"+{len(passengers) - 3}").style(
                                "font-size:.6rem;color:#d7b263;"
                                "font-weight:700;line-height:18px")
            vehicle_name = travel_mod.vehicle_name_(entry)
            if passengers:
                vehicle_name += " · " + ", ".join(
                    (p.get("name") or "?") for p in passengers)
            ui.label(vehicle_name) \
                .style("font-size:.72rem;color:var(--km-muted);"
                       "text-align:center;line-height:1.1")

    def person_badge(char: dict) -> None:
        color = images.valid_color(char.get("color"))
        taken = char["id"] in choice["people"]
        with ui.column().classes("items-center gap-1") \
                .style("cursor:pointer;width:76px;border-radius:8px;padding:4px"
                       + (";background:#d7b26322;outline:2px solid #d7b263" if taken else "")) \
                .on("click", lambda e, x=char: person_click(e, x), ["ctrlKey"]):
            initials = "".join(
                q[0] for q in (char.get("name") or "?").split()[:2]).upper()
            badge = ui.element("div").classes("items-center justify-center") \
                .style(f"width:56px;height:56px;border-radius:50%;"
                       f"border:2px solid {color};background:#12100b;"
                       f"display:flex;overflow:hidden")
            with badge:
                if char.get("token"):
                    ui.image(images.address(
                        "/assets/characters", _common.CHARACTER_FOLDER,
                        str(char["token"]), images.MARKER_SIDE)) \
                        .style("width:56px;height:56px;object-fit:cover")
                else:
                    ui.label(initials).style(
                        f"color:{color};font-weight:700;font-size:1.1rem")
            ui.label(char.get("name") or "?") \
                .style("font-size:.72rem;color:var(--km-muted);"
                       "text-align:center;line-height:1.1")

    @ui.refreshable
    def body() -> None:
        with ui.row().classes("items-start gap-3 flex-wrap"):
            for entry in vehicles:
                vehicle_badge(entry)
            for char in people_:
                person_badge(char)
        theme.sep()
        with ui.row().classes("items-center gap-2 w-full"):
            n = chosen_count()
            if n:
                ui.button(tn("markers.take_chosen", n),
                          icon="check",
                          on_click=lambda: take(list(choice["people"]), choice["vehicle"])) \
                    .props("unelevated dense").classes("km-btn")
            elif len(people_) > 1:
                ui.button(t("map.markers.all", len=len(people_)), icon="groups",
                          on_click=lambda: take([x["id"] for x in people_])) \
                    .props("unelevated dense").classes("km-btn")
            ui.element("div").style("flex:1")
            ui.button(t("map.markers.leave"), on_click=dlg.close).props("flat dense")

    with theme.dialog() as dlg, ui.card().classes("km-panel") \
            .style("min-width:280px"):
        ui.label(t("map.markers.there_are_here_whom", len=len(group))) \
            .style("font-size:.86rem;color:var(--km-gold)")
        ui.label(t("map.markers.click_takes_one_ctrl")) \
            .style("font-size:.7rem;color:var(--km-muted)")
        body()
    dlg.open()


def _vehicles_in_play() -> dict:
    """The vehicles that are somewhere, by id — those one leaves with.

    A vehicle in the depot carries nobody: it has no hex, so there is no place
    to board it. Whoever still counts as «theirs» stayed attached to it from
    when a vehicle had no position, and it is a link to be read for what it
    is: nothing.

    Taken at face value it changed the figures silently — the party travelled
    at the Speed of a wagon locked in the shed, or turned out able to cross
    water because «it has a boat» — and those numbers went straight into the
    travel box with nothing on the map explaining them.

    For the drawing the opposite holds and stays as it is: there the vehicles
    all show, each where it is.
    """
    return {v["id"]: v for v in STATE.archive.list_stable(STATE.campaign)
            if travel_mod.where_it_is(v) is not None}

def _vehicle_of(char_ids: list) -> str | None:
    """The vehicle the chosen ones travel on, if it is a single one.

    It keeps the two halves of the same choice together. Choosing a face left
    the previous vehicle in hand: with a boat still taken, the journey stayed
    the water one and clicking a person ashore changed nothing. And the other
    way round, taking someone on a wagon one wants to see **the wagon** lit
    too — they are the same thing that leaves.

    If the chosen ones are on different vehicles none is kept: they travel
    together on nothing, and lighting up the vehicle of one alone would say
    something false.

    And only the vehicles **placed on the map** are looked at, which is the
    same rule the passengers are drawn with: nobody is on a vehicle in the
    depot, and a `stable_id` pointing there is an old link, from when a
    vehicle had no position. Taken at face value it did real harm: choosing
    that person one found a boat locked in the shed in hand, the ruler
    switched to the water journey, there was no water to follow, and dragging
    on the map no longer drew anything — no path, so no arithmetic, so no
    group travel box. The panel looked emptied with no way to tell why.
    """
    vehicles = set()
    for char_id in char_ids or []:
        char = STATE.archive.character(char_id)
        sid = (char or {}).get("stable_id") or None
        entry = STATE.archive.stable_vehicle(sid) if sid else None
        vehicles.add(sid if entry is not None
                  and travel_mod.where_it_is(entry) is not None else None)
    return vehicles.pop() if len(vehicles) == 1 else None
