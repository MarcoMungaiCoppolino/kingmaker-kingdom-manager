"""Two click modes must never be on together, in either direction."""
from kingmaker.ui import hexmap

MODES = ("fog", "travel", "water")


def window():
    return {"fog_mode": None, "fog_selection": [], "water_mode": False,
            "border_mode": None, "water_proposal": None, "travel_mode": None,
            "place_pc": None, "plan": None, "path": [], "branches": [],
            "singles": [], "rendezvous": None, "travel_pcs": [],
            "cut_in_progress": None, "current_from": None, "lake_points": [],
            "lake_id": None}


def switch_on(mine, which):
    """What the switch does: turns the others off, then turns its own on."""
    hexmap._single_mode(mine, which)
    if which == "fog":
        mine["fog_mode"] = "reveal"
    elif which == "travel":
        mine["travel_mode"] = "choose"
    elif which == "water":
        mine["water_mode"] = True
        mine["border_mode"] = "water"


def lit_ones(mine):
    return {n for n, v in (("fog", mine["fog_mode"]),
                           ("travel", mine["travel_mode"]),
                           ("water", mine["water_mode"])) if v}


results = []

# all six transitions, in both directions
for from_ in MODES:
    for a in MODES:
        if from_ == a:
            continue
        mine = window()
        switch_on(mine, from_)
        switch_on(mine, a)
        results.append((f"{from_} -> {a}: only {a} stays on", lit_ones(mine) == {a}))

# turning the last one off leaves nothing on
for which in MODES:
    mine = window()
    switch_on(mine, which)
    hexmap._single_mode(mine, "")
    results.append((f"{which} -> spenta: nessuna modalita' accesa", lit_ones(mine) == set()))

# leaving the journey the plan is not left hanging
mine = window()
switch_on(mine, "travel")
mine.update(plan="fake", path=[(1, 1)], travel_pcs=["x"], rendezvous="fake")
switch_on(mine, "water")
results.append(("switching to the waters the travel plan is cleared",
              mine["plan"] is None and mine["path"] == []
              and mine["travel_pcs"] == [] and mine["rendezvous"] is None))

# leaving the waters the unapplied proposal vanishes
mine = window()
switch_on(mine, "water")
mine["water_proposal"] = "fake_one"
switch_on(mine, "travel")
results.append(("switching to the journey the water proposal is discarded",
              mine["water_proposal"] is None and mine["border_mode"] is None))

# the pending fog does not survive a change of mode
mine = window()
switch_on(mine, "fog")
mine["fog_selection"] = [[1, 1], [2, 2]]
switch_on(mine, "water")
results.append(("switching to the waters the fog choice is emptied",
              mine["fog_selection"] == []))

# --- the half stretch left in hand ---------------------------------------
# The first vertex taken with the Water brush is seen on the map: a red dot
# and the two dashed cells sharing it. Turning the Waters off it stayed drawn
# — and to get rid of it one had to go through Journey, which is the only
# road that cleared it by chance.
VEHICLE = {"point": (100.0, 100.0), "owners": [((3, 3), 0), ((3, 2), 2)]}


def with_half_stretch():
    mine = window()
    switch_on(mine, "water")
    mine["cut_in_progress"] = dict(VEHICLE)
    mine["current_from"] = ("v", 3, 3, 0)
    mine["lake_points"] = ["v:3:3:0"]
    return mine


mine = with_half_stretch()
hexmap._single_mode(mine, "")
results.append(("turning the Waters off the half stretch goes away",
              mine["cut_in_progress"] is None))
results.append(("and with it the half direction and the lake outline",
              mine["current_from"] is None and mine["lake_points"] == []
              and mine["lake_id"] is None))

mine = with_half_stretch()
switch_on(mine, "travel")
results.append(("and it holds switching to Journey too, as before",
              mine["cut_in_progress"] is None))

mine = with_half_stretch()
switch_on(mine, "fog")
results.append(("and switching to the fog, which is the same exit",
              mine["cut_in_progress"] is None))

# Staying in the Waters instead it stays in hand: a vertex was clicked and
# the second is about to be, and clearing it there would be the opposite
# defect.
mine = with_half_stretch()
hexmap._single_mode(mine, "water")
results.append(("staying in the Waters the half stretch stays in hand",
              mine["cut_in_progress"] is not None))

# --- and the drawing follows the state ----------------------------------
# Clearing without redrawing is the way to have two things that do not look
# alike: the state says «nothing in hand», the map still shows the dot.
# Changing brush exactly this happened.
class FakeMap:
    def __init__(self):
        self.redraws = 0

    def refresh(self):
        self.redraws += 1


class FakeBox:
    def refresh(self):
        pass


mine = with_half_stretch()
mine["waters"] = FakeBox()
fake_one = FakeMap()
hexmap._brush(mine, fake_one, "current")
results.append(("changing brush the half stretch goes away",
              mine["cut_in_progress"] is None and mine["current_from"] is None))
results.append(("and the map is redrawn, or the dot would stay there",
              fake_one.redraws == 1))
results.append(("the new brush is the one asked for",
              mine["border_mode"] == "current"))
# Clicking the same brush again puts it down: it is the switch that was already there.
hexmap._brush(mine, fake_one, "current")
results.append(("and clicking it again puts it down", mine["border_mode"] is None))

width = max(len(n) for n, _ in results)
for name, ok in results:
    print(("  ok  " if ok else " NO   ") + name.ljust(width))
print(f"\n{sum(1 for _, ok in results if ok)}/{len(results)} passed")
