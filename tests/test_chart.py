"""The water chart: download it, send it back, and do not trust the file."""
import json

from kingmaker.water import chart as water_chart
from kingmaker.geometry import sections
from kingmaker.state import STATE

results = []
A, C = STATE.archive, STATE.campaign
m = STATE.k["map"]

COORD = (9, 4)
GROUPS = [[0, 1, 2], [3, 4, 5]]


def clean():
    A.remove_lake(C)
    A.remove_crossings(C)
    for c in list(A.campaign_banks(C)):
        A.set_banks(C, c, None)
    for k in list(A.campaign_borders(C)):
        A.set_border(C, (k[0], k[1]), (k[2], k[3]), None)


# --- 1. a full round trip: what goes out comes back the same -------------
clean()
A.set_border(C, (9, 4), (10, 4), "water")
A.set_border(C, (9, 4), (9, 3), "ford")
A.set_border(C, (11, 5), (12, 5), "bridge")
A.set_banks(C, COORD, GROUPS)
_found = sections.hop_between_sides(
    A.campaign_sections(C, m["orientation"])[COORD], 0, 3)
A.set_crossing(C, COORD, _found[0], _found[1],
                kind="ford", difficulty="greater_difficult")

document = water_chart.compose(m, A.campaign_borders(C), A.campaign_banks(C),
                                A.campaign_crossings(C), kingdom="Test Kingdom")
is_written = water_chart.text(document)
results.append(("the file is valid JSON", isinstance(json.loads(is_written), dict)))
results.append(("it says which format it is",
              document["format"] == "kingmaker.acque"))
results.append(("it carries the grid calibration along",
              all(document["map"][k] == m[k]
                  for k in ("orientation", "columns", "rows", "size",
                            "origin_x", "origin_y", "image"))))
results.append(("and the kingdom's name, to know where it comes from",
              document["kingdom"] == "Test Kingdom"))

chart = water_chart.read(is_written, m, "prova.json")
results.append(("it comes back valid", chart.is_valid))
results.append(("with the three borders", len(chart.borders) == 3))
results.append(("the kinds are those",
              sorted(t for _a, _b, t, _c in chart.borders)
              == ["bridge", "ford", "water"]))
results.append(("with the banks of the cut hex",
              chart.banks.get(COORD) == [sorted(g) for g in GROUPS]))
# A crossing is remembered by two points, one per shore: the chart carries
# those, and put back in it must find the same two shores again.
chart_faces = A.campaign_sections(C, m["orientation"])[COORD]
results.append(("and the crossing, kind and difficulty included",
              len(chart.crossings) == 1
              and chart.crossings[0][0] == COORD
              and chart.crossings[0][3:] == ("ford", "greater_difficult")
              and sections.crossing_shores(chart_faces,
                                           chart.crossings[0][1]) == (0, 1)))
results.append(("without rejects", chart.discarded == 0))
results.append(("and without warnings: same map, same grid", chart.warnings == []))

# --- 2. putting it back in -------------------------------------------------
clean()
counts = A.write_water_chart(
    C, [(a, b, t) for a, b, t, _c in chart.borders], chart.banks, chart.crossings,
    replace_=True)
results.append(("rewritten: three borders", counts["borders"] == 3))
results.append(("and they are in the database", len(A.campaign_borders(C)) == 3))
results.append(("the banks too", A.campaign_banks(C).get(COORD)
              == [sorted(g) for g in GROUPS]))
results.append(("and the crossing with its kind",
              (A.campaign_crossings(C).get(COORD) or [{}])[0].get("kind") == "ford"))

# «Add» does not take away what was there.
A.set_border(C, (20, 10), (21, 10), "water")
A.write_water_chart(C, [((5, 5), (6, 5), "water")], {}, [], replace_=False)
cfg = A.campaign_borders(C)
results.append(("adding, what was there before stays",
              len(cfg) == 5 and any(k[0] == 20 for k in cfg)))
# «Replace» instead makes a clean sweep.
A.write_water_chart(C, [((5, 5), (6, 5), "water")], {}, [], replace_=True)
results.append(("replacing, only the chart remains",
              len(A.campaign_borders(C)) == 1 and not A.campaign_banks(C)
              and not A.campaign_crossings(C)))

# --- 3. what is not a chart is refused ------------------------------------
results.append(("a file that is not JSON",
              not water_chart.read("this is not json {", m).is_valid))
results.append(("a JSON that is not a chart",
              not water_chart.read('{"ciao": 1}', m).is_valid))
results.append(("bytes not text",
              not water_chart.read(b"\\xff\\xfe\\x00binario", m).is_valid))
future = dict(document, version=99)
results.append(("a chart of a future version",
              not water_chart.read(water_chart.text(future), m).is_valid))

other_direction = json.loads(is_written)
other_direction["map"]["orientation"] = "flat"
refused = water_chart.read(json.dumps(other_direction), m)
results.append(("a different orientation is refused", not refused.is_valid))
results.append(("and explains why", "orientation" in refused.reason))

# --- 4. what is bent is discarded and counted -----------------------------
bent_one = json.loads(is_written)
bent_one["borders"] += [
    {"a": [1, 1], "b": [1, 2], "kind": "lava"},        # kind that does not exist
    {"a": "no", "b": [1, 2], "kind": "water"},          # bent coordinates
    {"a": [999, 1], "b": [999, 2], "kind": "water"},    # outside the grid
]
bent_one["banks"] += [
    {"hexagon": [3, 3], "groups": [[0, 1, 2]]},                # does not divide
    {"hexagon": [3, 4], "groups": [[0, 1], [2, 3]]},           # does not cover the six sides
    {"hexagon": [3, 5], "groups": [[0, 1, 2], [2, 3, 4, 5]]},  # one side on two banks
]
bent_one["crossings"] += [
    {"hexagon": [7, 7], "sides": [0, 3], "kind": "bridge"},      # no cut there
    {"hexagon": [9, 4], "sides": [0, 0], "kind": "bridge"},      # the same side twice
    {"hexagon": [9, 4], "sides": [0, 3], "kind": "teletrasporto"},
]
dirty = water_chart.read(json.dumps(bent_one), m)
results.append(("a chart with bent stuff inside stays valid", dirty.is_valid))
results.append(("but the bent entries are discarded and counted", dirty.discarded == 9))
results.append(("and the good ones are still there",
              len(dirty.borders) == 3 and len(dirty.banks) == 1))

# --- 5. a different grid: it is said, not refused --------------------------
other_one = json.loads(is_written)
other_one["map"]["image"] = "un-altra-mappa.jpg"
other_one["map"]["columns"] = 12
warned = water_chart.read(json.dumps(other_one), m)
results.append(("another image blocks nothing", warned.is_valid))
results.append(("but says so", any("another image" in a for a in warned.warnings)))
results.append(("and says about the different grid too",
              any("columns" in a for a in warned.warnings)))

narrow_one = json.loads(is_written)
narrow_one["borders"].append({"a": [29, 23], "b": [29, 22], "kind": "water"})
small_one = dict(m, columns=5, rows=5)
cut_one = water_chart.read(json.dumps(narrow_one), small_one)
results.append(("on a smaller grid what does not fit is lost",
              cut_one.is_valid and cut_one.discarded >= 4
              and not cut_one.borders))

clean()

width = max(len(n) for n, _ in results)
for name, ok in results:
    print(("  ok  " if ok else " NO   ") + name.ljust(width))
print(f"\n{sum(1 for _, ok in results if ok)}/{len(results)} passed")
