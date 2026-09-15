"""Constants, window state, cursors, the view and the cached water (sections, network): what every other map module uses.

It used to live in `ui/hexmap.py`; the `hexmap` facade still re-exports everything.
"""
from __future__ import annotations

import logging
import urllib.parse
from nicegui import app, ui
from kingmaker.state import STATE
from kingmaker.ui import theme
from kingmaker.geometry import waterways, hexgrid
from kingmaker.access import auth, permissions, view as view_mod
from kingmaker import config, rules, travel as travel_mod
from kingmaker.media import images
from kingmaker.storage import migrations

from kingmaker.ui.hexmap import water as _water
from kingmaker.ui.hexmap import ruler as _ruler
from kingmaker.locale.i18n import t

log = logging.getLogger(__name__)


ASSETS = config.ASSETS_DIR

app.add_static_files("/assets", str(ASSETS))

# The two marker sub-folders. They live here because the map draws them, and
# to draw them it asks `images` for the shrunken copy: a marker is a circle
# as big as half a hex, and has no reason to be the two-megabyte file someone
# uploaded.
CHARACTER_FOLDER = ASSETS / "characters"

VEHICLE_FOLDER = ASSETS / "vehicles"

# Beyond this number of cells the grid is no longer drawn in full: every hex
# is a piece of SVG resent at every redraw, and above a few thousand the map
# starts to stutter.
MAX_GRID_CELLS = 4000

def full_grid() -> list[tuple[int, int]]:
    """Every cell of the grid, whether or not it exists among the saved hexes.

    A hex without data is not "non-existent": it is just a hex nobody has
    written anything on yet. Fog and counts must reason on the whole grid, or
    a never-clicked hex would be left out of every command.
    """
    m = STATE.k["map"]
    columns, rows = int(m["columns"]), int(m["rows"])
    return [(c, r) for r in range(rows) for c in range(columns)]

# The fog on the master's screen stays light: it must say "the players do not
# see here", not stop the GM from reading the map underneath.
FOG_GM = "#05060a59"      # how a player would see it at 35%
GM_FOG_MIN, GM_FOG_MAX = 0.10, 1.0

def _gm_fog(opacity: float) -> str:
    """The GM's fog, as thick as the GM asked: the same range as the
    players' one, so the two sliders read alike."""
    value = max(GM_FOG_MIN, min(GM_FOG_MAX, float(opacity)))
    return f"#05060a{int(round(value * 255)):02x}"

FOG_EDGE = "#b9c2cc"

# For the players the density is the GM's call: light if the PCs have an idea
# of what awaits them, pitch black if the Stolen Lands are a blank sheet.
FOG_MIN, FOG_MAX = 0.10, 1.0

def _player_fog(opacity: float) -> str:
    value = max(FOG_MIN, min(FOG_MAX, float(opacity)))
    return f"#05060a{int(round(value * 255)):02x}"

# Four «hex features» on the sheet are not list entries but hex fields.
# Preparing them as secrets is fine, but revealing them must tick the field:
# adding them to the list would leave the generic icon and a duplicate.
FIELD_OF_FEATURE = migrations.FIELD_OF_FEATURE

# The checks on uploaded files live in `images`: character portraits use them
# too, and they must be the same for everyone.
MAX_IMAGE_BYTES = images.MAX_MAP_BYTES

HEX_STATUSES = {
    "unknown": ("map.status.unknown", "#00000000", "#3a3128"),
    "reconnoitered": ("map.status.reconnoitered", "#ffffff10", "#7a6a4a"),
    "cleared": ("map.status.cleared", "#8fd46a1a", "#6f9a4e"),
    "claimed": ("map.status.claimed", "#d7b26326", "#d7b263"),
}

# How visible the terrain fill is, in hundredths of what it was. Needed because
# the map drawn underneath already has its colours: a fill saying «forest
# here» on top of a drawn forest covers the drawing instead of adding to it,
# and sometimes one wants to look at the map and not at its classification.
# It lives here and not in the rules data: it is a viewer's preference, like
# the zoom.
TERRAIN_VEIL = 1.0

def _with_veil(color: str, veil: float) -> str:
    """The same colour, with the transparency multiplied by `veil`.

    The alpha channel is touched and no `fill-opacity` is added: the fills sit
    in a single `path` per colour, and an extra attribute would drag the
    outlines along — which must stay readable instead, or at low veil the
    grid would vanish with the colour.
    """
    if veil >= 1.0 or not color.startswith("#"):
        return color
    digits = color[1:]
    if len(digits) == 6:
        digits += "ff"
    if len(digits) != 8:
        return color
    alpha = int(round(int(digits[6:], 16) * max(0.0, min(1.0, veil))))
    return "#" + digits[:6] + f"{alpha:02x}"

# Panels the other windows must redraw after a continuous edit (dragging a
# slider, typing a name).
_MAP = ("hexmap.map",)

_GRID = ("hexmap.map", "hexmap.sliders")

# The icons live in the data, next to the name and the description: here
# there was a second hand-written copy, and every new feature had to be added
# in two places — forgetting one, a question mark appeared on the map.
HEX_ICONS = {e["id"]: e["icon"] for e in rules.HEX_FEATURES}

# Work Site icon by the commodity produced, to tell them apart at a glance.
WORK_SITE_ICONS = {"lumber": "🪵", "stone": "🪨", "ore": "⛏️"}

# Distinguishes, in the «Add feature» menu, the already founded settlements from the feature kinds.
_SETTLEMENT_PREFIX = "ins::"

def _work_site_icon(commodity: str | None) -> str:
    return WORK_SITE_ICONS.get(commodity, "⚒️")

def _feature_icon(el: dict) -> str:
    """Icon of a feature entry, Work Site commodity included."""
    if el.get("kind") == "work_site":
        return _work_site_icon(el.get("name"))
    return HEX_ICONS.get(el.get("kind"), "❔")

def _feature_entry(e: dict, icon: bool = True) -> str:
    """How a Hex Feature reads in a menu.

    Those added by the table say so: they have no mechanics behind them, and
    finding them in a row with Refuge and Landmark with no distinction would
    suggest they are rules too.
    """
    text = f'{e["icon"]} {e["name"]}' if icon else e["name"]
    return text + (t("map.common.table_s") if e.get("source") == "table" else "")

def _mine() -> dict:
    """State of this player's window.

    The selected hex, the zoom and the menu choices are personal: the kingdom
    instead is shared, so it stays in `STATE`.
    """
    data = theme.window_state()
    if "hexmap" not in data:
        data["hexmap"] = {
            "col": None, "row": None,          # selected hex
            "map": None, "detail": None,  # this window's panels
            "zoom": float(STATE.k["map"].get("zoom", 1.0)),
            "terrain_veil": float(STATE.k["map"].get("terrain_veil",
                                                       TERRAIN_VEIL)),
            "claim": "exploration", "clear": "engineering",
            "player_preview": False,      # the GM looks through their eyes
            "fog_mode": None,               # None | "hide" | "reveal"
            "fog_selection": [],            # hexes taken with ctrl, pending
            "show_icons": True,              # hex icons and names
            "show_lake_names": True,         # the lake names on the map
            "water_mode": False,               # the «Waters» mode is on
            "border_mode": None,              # None | water | cut | ford | bridge | land | color
            "cut_in_progress": None,           # the first vertex taken, and who shares it
            "current_from": None,               # the vertex the current direction starts from
            "remove_direction": False,              # clicks remove directions instead of marking them
            "lake_points": [],                  # the ring of vertices being drawn
            "lake_id": None,                   # the lake being redrawn
            "route": None,                     # the water route, when there is one
            "by_river": False,                # the plan being looked at is the river one
            "show_borders": True,            # the borders drawn on the map
            "water_proposal": None,            # the image reading, not applied
            "travel_pcs": [],                  # who leaves, in the Travel panel
            "travel_mode": None,              # None | "choose" | "place"
            "place_pc": None,              # the character to put on the map
            "place_vehicle": None,         # the vehicle to put on the map
            "travel_vehicle": None,           # the vehicle one is travelling with
            "landing": None,                    # {"sid":…, "char_ids":[…]} waiting for the click
            "forced_march": False,
            "aboard": False,                   # everyone boards the vehicle
            "path": [],                    # the proposed course, to draw
            "plan": None,                     # the journey's arithmetic, if computed
            "show_journeys": True,             # the routes already under way on the map
            "together": True,                   # we wait for each other before going on
            "rendezvous": None,                    # where to meet, if leaving scattered
            "branches": [],                        # the approach roads
            "singles": [],                     # one path each
            "chosen_journey": None,            # the journey in progress lit up now
        }
    return data["hexmap"]

# Cursors: an eye to uncover, a barred eye to cover. They are SVGs put
# directly in the CSS rule, so no file needs serving.
_EYE = ('<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7-10-7-10-7z" fill="none" '
           'stroke="%s" stroke-width="2"/><circle cx="12" cy="12" r="3" fill="%s"/>')

_BAR = '<line x1="3" y1="21" x2="21" y2="3" stroke="%s" stroke-width="2.4"/>'

# The eraser: a tilted rectangle with the tip at the bottom left, where the
# cursor's hot spot is. Light with a dark edge, like the fog eye, so it shows
# on any piece of map.
_ERASER = ('<path d="M4 20h7l9-9-6-6-9 9z" fill="#f2e2c0" stroke="#3a2c14" '
          'stroke-width="1.6"/><path d="M9 15l6-6" stroke="#3a2c14" '
          'stroke-width="1.4"/>')

# A travel plan is not a single thing: it is the arrow, the watercoloured
# hexes under it, the approach roads, the little circle of the meeting point,
# the separate journeys of those going their own way and the water route with
# its alternative by land. They are six pieces drawn from different places,
# and as long as each one erased them on its own it was enough to forget one
# for **half** a plan to remain on the map: an arrow nobody is looking at any
# more, or a meeting-point circle in the middle of a road no longer taken.
# Worse, it was often a piece that could not even be removed: the box with
# «Cancel» appears only if someone is chosen, and precisely by choosing nobody
# that piece stayed.
#
# So it is forgotten from a single point. Whoever changes the group, dissolves
# it, puts the vehicle away or cancels the journey calls this, and need not
# know how many pieces a plan is made of.
def _forget_plan(mine: dict) -> None:
    """Clears away the journey being prepared, all of it."""
    mine["plan"] = None
    mine["path"] = []
    mine["branches"] = []
    mine["singles"] = []
    mine["rendezvous"] = None
    mine["route"] = None
    mine["by_river"] = False
    mine["land"] = None
    mine["arrival_pos"] = None
    mine["nodes"] = ()
    mine["atom_stretches"] = {}

# The modes that take the click on the map: fog, travel and waters. Two on at
# once would fight over the same gesture, so switching one on switches the
# others off. The rule is written here and nowhere else: when every toggle
# switched its neighbours off on its own, it was enough to add one for one of
# the combinations to forget to.
def _single_mode(mine: dict, held: str) -> None:
    """Switches off every click mode except `kept` ("" switches them all off)."""
    if held != "fog":
        mine["fog_mode"] = None
        mine["fog_selection"] = []
    if held != "water":
        mine["water_mode"] = False
        mine["border_mode"] = None
        mine["water_proposal"] = None
        mine["current_from"] = None
        mine["remove_direction"] = False
        mine["lake_points"] = []
        mine["lake_id"] = None
        # The half stretch left halfway — the first vertex taken, with its dot
        # and the two dashed cells — goes with the mode. Before it stayed drawn
        # on the map: switching Waters off to go read a hex left a red mark on
        # you that no longer meant anything, and the only way to remove it was
        # through Travel.
        mine["cut_in_progress"] = None
        # The current guide lives in the browser: leaving the waters it must
        # be switched off there, or it would keep following the mouse over
        # another mode.
        _water._send_network(mine)
    if held != "travel":
        mine["travel_mode"] = None
        mine["place_pc"] = None
        mine["place_vehicle"] = None
        mine["travel_vehicle"] = None
        mine["landing"] = None
        _forget_plan(mine)
        mine["travel_pcs"] = []
    # The plan is no longer in anyone's hands, so not on the others' screens
    # either: without this the arrow of an abandoned journey stayed on their
    # map until another one left.
    if held != "travel":
        _ruler._trace_from_plan(mine)
    # And the others' arrows leave this map at once when one starts drawing
    # rivers or laying fog: waiting for their next move would mean keeping
    # them in front until someone moves the mouse, and maybe they never do.
    if held in ("water", "fog"):
        try:
            ui.run_javascript(
                "window.kmOthersTrace && window.kmOthersTrace({tracce: []});")
        except Exception:
            log.debug("other windows' arrows not cleaned up", exc_info=True)
    else:
        _ruler._send_traces(also_to_me=True)      # coming back, they come back too
    # The boxes too, not only the buttons: the one of the mode just switched
    # off would stay drawn in the column next to the new one.
    for key in ("fog_bar", "travel_button", "water_button",
                   "waters", "travel", "detail"):
        if mine.get(key):
            mine[key].refresh()

def _slider_for(mine: dict) -> str:
    """The right cursor for what the window is doing.

    The fog is the GM's, travel is not: keeping the tally in one place avoids
    a mode leaving the other's cursor standing.
    """
    if mine.get("fog_mode"):
        return _slider(mine["fog_mode"])
    if mine.get("water_mode"):
        if mine.get("border_mode") == "land":
            return _eraser_slider()
        # With the direction eraser in hand the same eraser applies: what the
        # click is about to do is seen before doing it, not after.
        if mine.get("border_mode") == "current" and mine.get("remove_direction"):
            return _eraser_slider()
        return "cursor:crosshair;"
    if mine.get("travel_mode") == "place":
        return "cursor:copy;"
    if mine.get("travel_mode") == "choose":
        return "cursor:crosshair;"
    return "cursor:auto;"

def _eraser_slider() -> str:
    """The pointer when you hold the eraser: it shows that it erases."""
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="26" height="26" '
           'viewBox="0 0 24 24"><g stroke-linecap="round" '
           'stroke-linejoin="round">' + _ERASER + "</g></svg>")
    # The hot spot is the bottom-left corner, i.e. where a real eraser touches
    # the sheet.
    return (f'cursor:url("data:image/svg+xml,{urllib.parse.quote(svg)}") '
            f'4 22, crosshair;')

def _slider(mode: str | None) -> str:
    # Outside the modes an explicit value is needed: `Element.style()` merges
    # the declarations, it does not remove them, so an empty string would
    # leave the eye standing even after switching the button off.
    if mode is None:
        return "cursor:auto;"
    color = "#ffd77a" if mode == "reveal" else "#ff9a9a"
    inside = _EYE % (color, color)
    if mode == "hide":
        inside += _BAR % color
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="26" height="26" '
           'viewBox="0 0 24 24">'
           '<g stroke-linecap="round" stroke-linejoin="round" '
           'style="paint-order:stroke;stroke:#000;stroke-width:3.5">'
           + inside + "</g></svg>")
    return f'cursor:url("data:image/svg+xml,{urllib.parse.quote(svg)}") 13 13, crosshair;'

def _current_view(mine: dict):
    """The view to draw with in this window.

    If the GM switched the preview on, we build the view of an ordinary
    player: so they see exactly what the players see, without logging out and
    back in with another account.
    """
    user = theme.user()
    preview = bool(mine.get("player_preview")
                     and permissions.can(user, permissions.SEE_SECRETS))
    # The view reads two tables (visibility and secrets) and four or five were
    # built per redraw: it is kept until someone writes.
    key = (getattr(user, "id", None), preview, STATE.archive.rev,
              STATE.k.get("_rev"))
    if mine.get("_view_key") == key and mine.get("_view") is not None:
        return mine["_view"]
    view = view_mod.MapView(_PREVIEW_USER if preview else user, STATE)
    mine["_view_key"], mine["_view"] = key, view
    return view

# A fictitious player with no id: sees only what was revealed to everyone.
_PREVIEW_USER = auth.User(id="", username="(anteprima)",
                                role=permissions.PLAYER, active=True,
                                must_change_pw=False)

# --------------------------------------------------------------------------
def _background() -> tuple[str, int, int]:
    m = STATE.k["map"]
    w, h = int(m["img_width"]), int(m["img_height"])
    if m["image"]:
        path = ASSETS / m["image"]
        if path.exists():
            return "/assets/" + urllib.parse.quote(str(m["image"])), w, h
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}">'
           f'<rect width="100%" height="100%" fill="#161209"/></svg>')
    return "data:image/svg+xml;utf8," + urllib.parse.quote(svg), w, h

def inside_map(m: dict | None = None):
    """The rule «this hex belongs to the map», as a function of (col, row).

    The grid is 30x24 but the image is not: on the live save it covers rows 1
    to 12, and below there is darkness. Before, the map ended where the
    **grid** ended, and a journey could go for a walk in the black beyond the
    edge of the image — traced, priced and departed, towards a place that
    cannot be seen. Now a hex belongs to the map if its **center falls on the
    image**: it is the same rule by which a hex belongs to a lake, and it
    holds for the grid drawing, for the click and for every travel
    computation, which all pass through here. Without the image size the grid
    remains.
    """
    m = STATE.k["map"] if m is None else m
    columns, rows = int(m["columns"]), int(m["rows"])
    size = float(m["size"])
    origin = (float(m["origin_x"]), float(m["origin_y"]))
    orient = m["orientation"]
    width = float(m.get("img_width") or 0)
    height = float(m.get("img_height") or 0)

    def inside(coord) -> bool:
        col, row = int(coord[0]), int(coord[1])
        if not (0 <= col < columns and 0 <= row < rows):
            return False
        if width <= 0 or height <= 0:
            return True
        cx, cy = hexgrid.hex_center(col, row, size, origin, orient)
        return 0 <= cx <= width and 0 <= cy <= height
    return inside

def waters_network(borders=None, banks=None, segments=None,
               lakes=None) -> "acquavie.Rete":
    """The network of watercourses of this campaign, lakes included."""
    m = STATE.k["map"]
    all_from_db = borders is None and banks is None and segments is None and lakes is None
    key = (STATE.archive.rev, m["orientation"], int(m["columns"]), int(m["rows"]),
              float(m["size"]), float(m["origin_x"]), float(m["origin_y"]))
    if all_from_db and _WATER_CACHE.get("network_key") == key:
        return _WATER_CACHE["network"]
    network = _build_network(borders, banks, segments, lakes, m)
    if all_from_db:
        _WATER_CACHE["network"], _WATER_CACHE["network_key"] = network, key
    return network

def _build_network(borders, banks, segments, lakes, m) -> "acquavie.Rete":
    return waterways.build(
        STATE.archive.campaign_borders(STATE.campaign) if borders is None else borders,
        STATE.archive.campaign_banks(STATE.campaign) if banks is None else banks,
        m["orientation"],
        STATE.archive.bank_points(STATE.campaign) if segments is None
        else segments,
        STATE.archive.campaign_lakes(STATE.campaign) if lakes is None
        else lakes,
        int(m["columns"]), int(m["rows"]), float(m["size"]),
        (float(m["origin_x"]), float(m["origin_y"])))

# --------------------------------------------------------------------------
# What entering a hex costs, for whoever is looking at the map.
#
# A hex you do not know is not a wall: it is a question mark, and we count it
# at the worst cost. So a party can get an idea of how long it would take to
# reach the end of the world, knowing that it is the pessimistic estimate and
# that the real journey can only be shorter.
#
# Mind the line that really matters: the difficulty set by the GM is read
# **only** on the hexes the viewer already sees. Applying it to the others
# too would tell the player how rough a place they have never been is, and
# that is exactly the kind of news the fog exists not to give.
def waters_active() -> bool:
    """Whether this table uses the water borders or prefers telling them aloud.

    Switching them off deletes nothing: borders and banks stay where they were
    and come back when switched on again. Only travel stops looking at them,
    and with them the Lake and River terrains stop counting too — at that
    point it is the GM telling the party that the river cannot be forded, as
    has always been done at a table.
    """
    return bool(STATE.k["map"].get("waters_active", True))

def _without_water(hexagon: dict | None) -> dict | None:
    """The hex as if the water terrains were not there.

    Needed with the waters off: a hex marked Lake must no longer stop the
    party. If no terrain is left it becomes «never explored», which is crossed
    at the worst cost instead of being a wall.
    """
    if not hexagon:
        return hexagon
    terrains = list(hexagon.get("terrains") or ())
    dry_ones = [tid for tid in terrains
                if not (travel_mod.TERRAINS.get(tid) or {}).get("water")]
    if len(dry_ones) == len(terrains):
        return hexagon
    return {**hexagon, "terrains": dry_ones}

def sections_map() -> dict:
    """The sections of the cut hexes, for the map of this campaign.

    A single place to ask them from. It is not the same as `campaign_banks`,
    and the difference is the whole phase: those are groups of **sides**, and
    still serve to draw the water and to exchange charts; these are the
    **pieces of hex** the water really divides it into, and serve to travel,
    to place a marker and to aim with the mouse.
    """
    orient = STATE.k["map"]["orientation"]
    key = (STATE.archive.rev, orient)
    if _WATER_CACHE.get("sections_key") != key:
        _WATER_CACHE["sections"] = STATE.archive.campaign_sections(STATE.campaign, orient)
        _WATER_CACHE["sections_key"] = key
    return _WATER_CACHE["sections"]

# The caches of what is derived from the drawn water. Redone when
# `archive.rev` changes, i.e. at every write: before, `sections_map()` was
# recomputed some twenty times per redraw and `waters_network()` at every
# current arrow.
_WATER_CACHE: dict = {}
