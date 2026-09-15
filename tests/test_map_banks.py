"""The banks model on the real map: the two measured defects must vanish."""
from kingmaker.water import reading as water_reading
from kingmaker import config
from kingmaker.geometry import hexgrid, sections
from kingmaker.access import permissions
from kingmaker import travel as v
from kingmaker.access import view as view_mod
from kingmaker.state import STATE
from kingmaker.ui import hexmap

A, C = STATE.archive, STATE.campaign
m = STATE.k["map"]
ORIENT = m["orientation"]
COL, ROW_ = int(m["columns"]), int(m["rows"])
hexes = {(e["col"], e["row"]): e for e in STATE.k["hexes"].values()}


def inside(c):
    return 0 <= c[0] < COL and 0 <= c[1] < ROW_


class Fake:
    id, username, role = "check", "check", permissions.ADMIN
    active = True


# --- the map is read again and everything is applied ---------------------
outcome = water_reading.trace(config.ASSETS_DIR / m["image"], m, hexes, inside,
                      m.get("water_samples"))
A.replace_traced(C, [(a, b, t) for a, b, t, _c in outcome.borders])
A.replace_traced_banks(C, outcome.banks)

view = view_mod.MapView(Fake(), STATE)
difficulty = A.campaign_difficulty(C)
vehicles = {x["id"]: x for x in A.list_stable(C)}
group = [p for p in STATE.characters() if p["name"] in ("Corin", "Dagny")]
mode = hexmap._crossing({"aboard": False}, group, vehicles, view, difficulty)
cost_of, passage, borders, sail = mode
banks = mode.banks

print(f"borders: {len(borders)} | cut hexes: {len(banks)}")

# How many banks you find depends on how well the image reading manages to
# calibrate itself, and that depends on the colour samples the GM took: they
# are a datum of **their** map, which changes while they play. A fixed number
# in here is a test that one day fails for an unrelated reason — and it
# happened. What is needed is that there is at least one, and that it really
# cuts.
samples = len(m.get("water_samples") or [])
print(f"   (colour samples taken by the GM: {samples})")
results = []
results.append(("reading the map found some bank", len(banks) >= 1))
results.append(("and at least one cuts the hexagon in two",
              any(len(g) >= 2 for g in banks.values())))

# --- 1. the hexagons that were walled off before are now reached ---------
# A hexagon is reachable if some neighbour has a step arriving there.
def reachable(coord):
    for vic in hexgrid.neighbours(coord[0], coord[1], ORIENT):
        if not inside(vic) or cost_of(coord) is None:
            continue
        for bank in range(v.banks_of(banks, vic)):
            for node, where in v.steps_from((vic[0], vic[1], bank), ORIENT, banks):
                if where == tuple(coord) and (
                        passage is None or passage(vic, coord) is not None):
                    return True
    return False


walled_before = [(10, 9), (13, 4)]      # dry land, closed off by the old model
for coord in walled_before:
    results.append((f"{coord} is no longer walled off", reachable(coord)))

# --- 2. one walks along a river ----------------------------------------
# We look for a pair of neighbouring hexagons, both cut, and check that at
# least one of their banks talks to the other.
along = 0
for coord, groups in banks.items():
    for vic in hexgrid.neighbours(coord[0], coord[1], ORIENT):
        if tuple(vic) in banks and inside(vic):
            for bank in range(len(groups)):
                if any(d == tuple(vic) for _n, d in
                       v.steps_from((coord[0], coord[1], bank), ORIENT, banks)):
                    along += 1
                    break
results.append(("between neighbouring cut hexes one passes", along > 0))

# --- 3. inside a cut hexagon one does not hop over -----------------------
cut_one = next(c for c, g in banks.items() if len(g) == 2 and inside(c))
groups = banks[cut_one]
neighbours = hexgrid.neighbours(cut_one[0], cut_one[1], ORIENT)
from_one = neighbours[sections.sides_of(groups[0])[0]]
from_other = neighbours[sections.sides_of(groups[1])[0]]
field = v.cost_field(cut_one, cost_of, ORIENT, inside, passage=passage,
                      banks=banks, departure_bank=0)
results.append((f"from {cut_one} bank 0 one leaves towards {from_one}",
              from_one in field.costs and field.costs[from_one] is not None))
results.append(("and the other bank takes the way around, not a step",
              field.costs.get(from_other, 99) > (cost_of(from_other) or 1)))

# --- 4. the paths remain pairs of coordinates ---------------------------
departure = (group[0]["hex_col"], group[0]["hex_row"])
c = v.path(departure, (20, 4), cost_of, ORIENT, inside, passage, banks)
results.append(("a real path still exists", c is not None))
results.append(("and is made of pairs only",
              c is None or all(len(p) == 2 for p in c)))

# --- 5. the drawing of the banks comes out ------------------------------
svg = hexmap._svg_banks_and_crossings(view, A.campaign_banks(C), float(m["size"]),
                       (float(m["origin_x"]), float(m["origin_y"])), ORIENT)
results.append(("the banks are drawn", "<path" in svg))

# --- 6. the marker moves towards its bank --------------------------------
_origin = (float(m["origin_x"]), float(m["origin_y"]))
p0 = hexmap.bank_point(cut_one, 0, float(m["size"]), _origin, ORIENT, banks)
p1 = hexmap.bank_point(cut_one, 1, float(m["size"]), _origin, ORIENT, banks)
results.append(("the two banks move the marker to two different points", p0 != p1))
results.append(("and a dry hexagon does not move it at all",
              hexmap.bank_point((0, 0), 0, float(m["size"]), _origin, ORIENT, banks)
              == hexgrid.hex_center(0, 0, float(m["size"]), _origin, ORIENT)))

width = max(len(n) for n, _ in results)
print()
for name, ok in results:
    print(("  ok  " if ok else " NO   ") + name.ljust(width))
print(f"\n{sum(1 for _, ok in results if ok)}/{len(results)} passed")
