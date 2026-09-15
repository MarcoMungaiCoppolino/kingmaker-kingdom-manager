"""The veil of the fills: how much the terrain colours cover the drawing.

The map of the Stolen Lands already has its colours. A fill saying «here is
forest» over a drawn forest covers the drawing instead of adding something to
it, and sometimes one wants to look at the map and not at its classification.
"""
from kingmaker.access import permissions, view as view_mod
from kingmaker import rules
from kingmaker.state import STATE
from kingmaker.ui import hexmap, theme

theme.notify = lambda *a, **k: None
theme.mark_dirty = lambda *a, **k: None
theme.save_light = lambda *a, **k: None

m = STATE.k["map"]
results = []


class Fake:
    id, username, role = "check", "check", permissions.ADMIN
    active = True
    must_change_pw = False


view = view_mod.MapView(Fake(), STATE)
veil = hexmap._with_veil

# --- 1. the count on the alpha channel ----------------------------------
results.append(("at full veil the colour is not touched",
              veil("#8fd46a66", 1.0) == "#8fd46a66"))
results.append(("at half the transparency halves",
              veil("#8fd46a66", 0.5) == "#8fd46a33"))
results.append(("at zero the colour is there but is not seen",
              veil("#8fd46a66", 0.0) == "#8fd46a00"))
results.append(("a colour without alpha starts from opaque",
              veil("#123456", 0.5) == "#12345680"))
results.append(("what was already invisible stays invisible",
              veil("#00000000", 0.5) == "#00000000"))
results.append(("and what is not a colour passes untouched",
              veil("none", 0.4) == "none" and veil("", 0.4) == ""))
results.append(("out of range one comes back inside",
              veil("#8fd46a66", 5.0) == "#8fd46a66"
              and veil("#8fd46a66", -1.0) == "#8fd46a00"))

# --- 2. the drawing respects it -----------------------------------------
COL, ROW_ = 12, 9
hexagon = STATE.hex(COL, ROW_)
before = (list(hexagon.get("terrains") or []), hexagon.get("status"))
hexagon["terrains"] = ["forest"]
hexagon["status"] = "claimed"
color = rules.BY_ID["terrain"]["forest"]["color"]

sel = {"show_borders": True, "col": None, "row": None, "show_icons": False}
full = hexmap._svg_grid(dict(sel, terrain_veil=1.0), view)
results.append(("at full veil the fill is the data's",
              f'fill="{color}cc"' in full))

vehicle = hexmap._svg_grid(dict(sel, terrain_veil=0.5), view)
results.append(("at half veil the fill lightens",
              f'fill="{color}66"' in vehicle
              and f'fill="{color}cc"' not in vehicle))

is_off = hexmap._svg_grid(dict(sel, terrain_veil=0.0), view)
results.append(("with the veil off the fill covers nothing any more",
              f'fill="{color}00"' in is_off
              or f'fill="none"' in is_off))
results.append(("and the full colour no longer appears anywhere",
              f'fill="{color}cc"' not in is_off))

# The thing that makes the slider usable: the edges remain. With the fills
# off one must still understand where a hexagon ends and the neighbour begins.
edge = hexmap.HEX_STATUSES["claimed"][2]
results.append(("the hex edges do not fade with the fills",
              f'stroke="{edge}"' in is_off and f'stroke="{edge}"' in full))

# --- 3. the value the window remembers ----------------------------------
results.append(("an earlier save counts as full veil",
              m.get("terrain_veil", hexmap.TERRAIN_VEIL) == 1.0
              or hexmap.TERRAIN_VEIL == 1.0))
without = dict(sel)
without.pop("terrain_veil", None)
m.pop("terrain_veil", None)
results.append(("and with the value nowhere it draws full",
              f'fill="{color}cc"' in hexmap._svg_grid(without, view)))

# The veil is **personal**, like the zoom: the kingdom's sheet remembers it
# for the next time, but what the window has in hand wins. So the GM can keep
# the fills full to work while the players look at the drawing.
m["terrain_veil"] = 0.0
results.append(("with nothing in hand the one remembered in the sheet counts",
              f'fill="{color}cc"' not in hexmap._svg_grid(without, view)))
results.append(("but the window's wins, and it is personal",
              f'fill="{color}cc"' in
              hexmap._svg_grid(dict(sel, terrain_veil=1.0), view)))

hexagon["terrains"], hexagon["status"] = before
m["terrain_veil"] = 1.0

width = max(len(n) for n, _ in results)
# --- 3. hiding the water lines wins over the cached layer -------------------
# The icon of the Waters button hides the drawn water in this window. The
# layer is cached per window, and the cache used to be read before the
# switch was looked at: the lines came back from the copy.
from kingmaker.ui.hexmap import drawing as _drawing   # noqa: E402
shared = dict(sel, terrain_veil=1.0)
with_water = hexmap._svg_grid(shared, view)            # fills the cache in `shared`
hidden = hexmap._svg_grid(dict(shared, show_borders=False), view)
back = hexmap._svg_grid(dict(shared, show_borders=True), view)
results.append(("the water is drawn with the lines on",
              _drawing.WATER_COLOR in with_water or _drawing.LAKE_COLOR in with_water))
results.append(("and not at all once hidden, cache or no cache",
              _drawing.WATER_COLOR not in hidden and _drawing.LAKE_COLOR not in hidden))
results.append(("and it comes back when shown again", back == with_water))

for name, ok in results:
    print(("  ok  " if ok else " NO   ") + name.ljust(width))
print("")
print(str(sum(1 for _, ok in results if ok)) + "/" + str(len(results)) + " passate")
