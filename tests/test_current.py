"""The direction of the current: the gesture, the archive, and the round trip through the chart."""
import json

from kingmaker.geometry import waterways
from kingmaker.water import chart as water_chart
from kingmaker import travel as travel_mod
from kingmaker.state import STATE
from kingmaker.ui import hexmap, theme
import helpers
from nicegui import ui
from kingmaker.access import permissions
# The water brushes are the GM's: here they act.
permissions.can = lambda *a, **k: True

told_ones = []
theme.notify = lambda text, *a, **k: told_ones.append(text)
theme.mark_dirty = lambda *a, **k: None
theme.refresh_panels = lambda *a, **k: None

A, C = STATE.archive, STATE.campaign
m = STATE.k["map"]
size = float(m["size"])
origin = (float(m["origin_x"]), float(m["origin_y"]))
orient = m["orientation"]

results = []


def clean():
    A.remove_lake(C)
    A.remove_currents(C)
    A.remove_crossings(C)
    for c in list(A.campaign_banks(C)):
        A.set_banks(C, c, None)
    for k in list(A.campaign_borders(C)):
        A.set_border(C, (k[0], k[1]), (k[2], k[3]), None)


def click(mine, node):
    """A click exactly on a node of the network."""
    hexmap._current_direction(mine, waterways.node_point(node, size, origin, orient))


# A river of three stretches: it cuts 9,4 from one vertex to the other, then
# runs along the edge between 9,4 and 10,4, then cuts 10,4.
clean()
GROUPS = [[0, 1, 2], [3, 4, 5]]
A.set_banks(C, (9, 4), GROUPS)
A.set_border(C, (9, 4), (10, 4), "water")
A.set_banks(C, (10, 4), GROUPS)
network = hexmap.waters_network()
results.append(("the drawn river makes three lines: four pieces, one side, four pieces",
              len(network.parents) == 3 and len(network.arcs) == 9))

grades = {n: len(v) for n, v in network.neighbours.items()}
ends = sorted(n for n, how_many in grades.items() if how_many == 1)
results.append(("with two free ends", len(ends) == 2))

# --- 1. the gesture: two clicks, and the direction is on every stretch between
mine = {}
click(mine, ends[0])
results.append(("the first click takes the upstream point and waits",
              mine.get("current_from") == ends[0] and not A.campaign_currents(C)))
click(mine, ends[1])
currents = A.campaign_currents(C)
results.append(("the second writes the direction on every stretch in between",
              len(currents) == 3 and mine.get("current_from") is None))

road = waterways.course(network, ends[0], ends[1])
results.append(("going down the marked direction one goes downstream, piece by piece",
              helpers.course_directions(currents, road, network)
              == ["downstream"] * 9))
results.append(("and retracing the road backwards one goes up",
              helpers.course_directions(currents, list(reversed(road)), network)
              == ["upstream"] * 9))

# --- 2. doing it the other way round turns the river ---------------------
mine = {}
click(mine, ends[1])
click(mine, ends[0])
currents = A.campaign_currents(C)
results.append(("marking it the other way round the river turns",
              len(currents) == 3
              and helpers.course_directions(currents, road, network)
              == ["upstream"] * 9))
results.append(("and says so, instead of adding lines on the sly",
              "turned" in told_ones[-1]))

# --- 3. what cannot be done ---------------------------------------------
mine = {}
click(mine, ends[0])
before = dict(A.campaign_currents(C))
click(mine, ends[0])
results.append(("upstream and downstream at the same point do nothing",
              A.campaign_currents(C) == before and mine.get("current_from") is None
              and "same point" in told_ones[-1]))

# A detached stretch cannot be reached: no direction, and it says so.
A.set_border(C, (20, 10), (21, 10), "water")
detached = [n for n in hexmap.waters_network().neighbours
            if n[1] in (20, 21) and n[2] in (10, 11)]
mine = {}
click(mine, ends[0])
click(mine, detached[0])
results.append(("towards a different river one does not go down",
              len(A.campaign_currents(C)) == 3 and "cannot go down" in told_ones[-1]))
A.set_border(C, (20, 10), (21, 10), None)

# The finger far from the water takes nothing.
mine = {}
hexmap._current_direction(mine, (5.0, 5.0))
results.append(("far from the water one does not even begin",
              mine.get("current_from") is None
              and "watercourse passes there" in told_ones[-1]))

# Without water drawn the brush says so instead of keeping quiet.
held_ones = dict(A.campaign_currents(C))
clean()
mine = {}
hexmap._current_direction(mine, waterways.node_point(ends[0], size, origin, orient))
results.append(("on a dry map the brush explains what is missing",
              "first the river" in told_ones[-1]))

# --- 4. the direction is erased without touching the water --------------
A.set_banks(C, (9, 4), GROUPS)
A.set_border(C, (9, 4), (10, 4), "water")
A.set_banks(C, (10, 4), GROUPS)
mine = {}
click(mine, ends[0])
click(mine, ends[1])
results.append(("the directions come back", len(A.campaign_currents(C)) == 3))
hexmap._forget_currents(mine, None)
results.append(("the direction eraser removes them all", not A.campaign_currents(C)))
results.append(("and the water stays where it was",
              len(A.campaign_borders(C)) == 1 and len(A.campaign_banks(C)) == 2))

# --- 5. the drawing: one arrow per stretch with a direction -------------
class FullView:
    gm = True

    def can_see(self, *_a):
        return True


mine = {}
click(mine, ends[0])
click(mine, ends[1])
drawing = hexmap._svg_currents(FullView(), A.campaign_borders(C),
                               A.campaign_banks(C), size, origin, orient)
results.append(("three stretches with a direction, three arrows", drawing.count("<path") == 3))
A.remove_currents(C, [waterways.text_key(
    *network.arc_between(road[0], road[1]).parent_)])   # the line, not the piece
drawing = hexmap._svg_currents(FullView(), A.campaign_borders(C),
                               A.campaign_banks(C), size, origin, orient)
results.append(("one direction removed, one arrow fewer remains",
              drawing.count("<path") == 2))


class BlindView:
    gm = False

    def can_see(self, *_a):
        return False


results.append(("whoever does not see those hexes does not receive the arrows either",
              hexmap._svg_currents(BlindView(), A.campaign_borders(C),
                                   A.campaign_banks(C), size, origin,
                                   orient) == ""))

# --- 6. the chart carries the directions along --------------------------
mine = {}
click(mine, ends[0])
click(mine, ends[1])
document = water_chart.compose(m, A.campaign_borders(C), A.campaign_banks(C),
                                A.campaign_crossings(C), kingdom="Test Kingdom",
                                currents=A.campaign_currents(C))
results.append(("the chart is version 2", document["version"] == 2))
results.append(("and inside there are the three directions", len(document["currents"]) == 3))

chart = water_chart.read(water_chart.text(document), m, "prova.json")
results.append(("all three come back in", len(chart.currents) == 3))
clean()
counts = A.write_water_chart(
    C, [(a, b, t) for a, b, t, _c in chart.borders], chart.banks, chart.crossings,
    replace_=True, currents=chart.currents)
results.append(("and are written again", counts["currents"] == 3
              and len(A.campaign_currents(C)) == 3))
results.append(("with the right direction, not at random",
              helpers.course_directions(A.campaign_currents(C), road,
                                         hexmap.waters_network())
              == ["downstream"] * 9))

# A direction on a stretch the chart does not carry is not kept: it would say nothing.
bent_one = json.loads(water_chart.text(document))
bent_one["currents"] += [
    {"upstream": "v:2:2:0", "downstream": "v:2:2:3"},      # there is no river there
    {"upstream": "boh", "downstream": "v:9:4:0"},           # node that cannot be read
    {"upstream": "v:9:4:0", "downstream": "v:9:4:0"},       # the same point twice
]
dirty = water_chart.read(json.dumps(bent_one), m)
results.append(("directions sitting on no stretch are discarded",
              len(dirty.currents) == 3 and dirty.discarded == 3))

# A version 1 chart, without directions, still reads.
old_one = json.loads(water_chart.text(document))
old_one["version"] = 1
old_one.pop("currents")
ancient = water_chart.read(json.dumps(old_one), m)
results.append(("an old chart reads, simply without directions",
              ancient.is_valid and ancient.currents == []
              and len(ancient.borders) == 1))

# «Replace» takes away the earlier directions too, as it takes away the water.
A.write_water_chart(C, [((5, 5), (6, 5), "water")], {}, [], replace_=True)
results.append(("replacing the chart the old directions go too",
              not A.campaign_currents(C)))

clean()

# --- removing a direction without erasing the line ----------------------
# Correcting a wrong direction must not cost the river: until yesterday the
# only way was to erase it and redo it, which is like tearing out a page to
# correct a word.
A.set_banks(C, (9, 4), GROUPS)
A.set_border(C, (9, 4), (10, 4), "water")
A.set_banks(C, (10, 4), GROUPS)
network = hexmap.waters_network()
ends = sorted(network.arcs)[0]
A.set_currents(C, [ends])
results.append(("a marked direction is there", len(A.campaign_currents(C)) == 1))

destination = [(x + y) / 2 for x, y in
        zip(waterways.node_point(ends[0], size, origin, orient),
            waterways.node_point(ends[1], size, origin, orient))]
results.append(("with ctrl the click removes it",
              hexmap._remove_direction_under({}, tuple(destination)) is True
              and A.campaign_currents(C) == {}))
results.append(("but the line stays where it was",
              len(hexmap.waters_network().arcs) == len(network.arcs)))
results.append(("and with no direction to remove it says so instead of breaking",
              hexmap._remove_direction_under({}, tuple(destination)) is False
              and "no direction" in told_ones[-1]))

A.set_currents(C, [ends])
far = (float(destination[0]) + size * 4, float(destination[1]) + size * 4)
results.append(("far from the stretches it removes nothing by mistake",
              hexmap._remove_direction_under({}, far) is False
              and len(A.campaign_currents(C)) == 1))

# --- the direction eraser: a button, not just a shortcut ----------------
# Ctrl and a click were already enough, but a keyboard shortcut that shows up
# nowhere, for whoever uses it, does not exist: the box only had «Remove all
# directions», and it looked like correcting one meant redoing everything.


class FakeBox:
    def __init__(self):
        self.redone_ones = 0

    def refresh(self):
        self.redone_ones += 1


sent = []
real_js = ui.run_javascript
ui.run_javascript = lambda codice, *a, **k: sent.append(codice)
try:
    two = sorted(network.arcs)[:2]
    A.set_currents(C, two)
    sliders = []
    mine = {"water_mode": True, "border_mode": "current",
           "current_from": sorted(network.neighbours)[0], "remove_direction": False,
           "waters": FakeBox(), "apply_slider": lambda: sliders.append(1)}
    hexmap._toggle_remove_direction(mine, FakeBox())
    results.append(("the button switches the direction eraser on",
                  mine["remove_direction"] is True))
    results.append(("and drops the upstream point that had already been taken",
                  mine["current_from"] is None))
    results.append(("the cursor becomes the eraser's",
                  hexmap._slider_for(mine) == hexmap._eraser_slider()))
    results.append(("and the guide following the river switches off",
                  sent and '"active": false' in sent[-1]))

    # Switched on, the click removes a single direction and the eraser stays
    # in hand: wrong directions come in bunches, and switching it back on
    # every time would be one more click.
    destination_two = [(x + y) / 2 for x, y in
                zip(waterways.node_point(two[1][0], size, origin, orient),
                    waterways.node_point(two[1][1], size, origin, orient))]
    results.append(("one click removes a single direction",
                  hexmap._remove_direction_under(mine, tuple(destination_two)) is True
                  and len(A.campaign_currents(C)) == 1))
    results.append(("and the eraser stays in hand for the next one",
                  mine["remove_direction"] is True))

    destination_one = [(x + y) / 2 for x, y in
                zip(waterways.node_point(two[0][0], size, origin, orient),
                    waterways.node_point(two[0][1], size, origin, orient))]
    hexmap._remove_direction_under(mine, tuple(destination_one))
    results.append(("the last one removed, the eraser puts itself down",
                  not A.campaign_currents(C) and mine["remove_direction"] is False))
    results.append(("and the lines are all still there",
                  len(hexmap.waters_network().arcs) == len(network.arcs)))

    # Changing brush or switching the waters off puts it down anyway: it is a
    # tool of the current, not a state that survives everything.
    A.set_currents(C, two)
    mine["remove_direction"] = True
    hexmap._brush(mine, FakeBox(), "water")
    results.append(("changing brush the direction eraser is put down",
                  mine["remove_direction"] is False))
    mine.update(water_mode=True, border_mode="current", remove_direction=True)
    hexmap._single_mode(mine, "")
    results.append(("and leaving the waters too",
                  mine["remove_direction"] is False))
finally:
    ui.run_javascript = real_js
    A.remove_currents(C)

# The click on the map must look at it, or the button would be a mere indicator.
source_text = helpers.map_source()
results.append(("and the click on the map listens to it as it listens to ctrl",
              'if e.ctrl or mine.get("remove_direction"):' in source_text))
results.append(("the box offers both «one» and «all»",
              't("map.water.remove_direction")' in source_text
              and 't("map.water.remove_all_directions")' in source_text))

# A stretch without a direction is not an unknown river: it is water without
# a current, and it is travelled both ways the same.
without = travel_mod.current_category(None)
results.append(("and a stretch without a direction counts as open ground",
              without.id == "open" and without.from_table))

clean()

width = max(len(n) for n, _ in results)
for name, ok in results:
    print(("  ok  " if ok else " NO   ") + name.ljust(width))
print(f"\n{sum(1 for _, ok in results if ok)}/{len(results)} passed")
