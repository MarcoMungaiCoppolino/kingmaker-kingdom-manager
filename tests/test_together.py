# -*- coding: utf-8 -*-
"""«Travel together» holds for those leaving from the same hexagon too.

The switch was born for the meeting — scattered people who meet up on the
road — and appeared only if the positions differed. But the question it asks
is not «where are you», it is «do you wait for each other?»: two leaving from
the same cell with different Speeds are exactly the case where one may arrive
first, and deciding for them that the faster one slows down is a choice that
is not the app's to make.
"""

from kingmaker.geometry import hexgrid
from kingmaker.access import permissions
from kingmaker.state import STATE
from kingmaker.ui import hexmap, theme
import helpers

permissions.can = lambda *a, **k: True
permissions.can_on_character = lambda *a, **k: True
permissions.can_on_someone = lambda *a, **k: True
told_ones = []
theme.notify = lambda text, *a, **k: told_ones.append(text)
theme.mark_dirty = lambda *a, **k: None
theme.refresh_panels = lambda *a, **k: None
theme.save_and_refresh = lambda *a, **k: None
theme.save_and_refresh_panels = lambda *a, **k: None
helpers.silence("_redraw_travel", lambda *a, **k: None)
helpers.silence("_send_field", lambda *a, **k: None)

A, C = STATE.archive, STATE.campaign
m = STATE.k["map"]
orient = m["orientation"]
results = []


class Allowed:
    id, username, role = "check", "check", permissions.ADMIN
    active = True


theme.user = lambda: Allowed()
helpers.silence("_can_move", lambda user, chosen: True)

# --- the scene: two travellers on the same cell, one faster -------------
TOGETHER = (14, 8)
META = (17, 8)
for coord in [TOGETHER, META]:
    STATE.hex(*coord)["terrains"] = ["plains"]
for step in range(TOGETHER[0], META[0] + 1):
    STATE.hex(step, 8)["terrains"] = ["plains"]
    for vic in hexgrid.neighbours(step, 8, orient):
        STATE.hex(vic[0], vic[1])["terrains"] = ["plains"]

everyone = STATE.characters()
slow, quick = everyone[0], everyone[1]
before = [(p["id"], p.get("hex_col"), p.get("hex_row"), p.get("stable_id"),
          p.get("speed_m")) for p in (slow, quick)]
for p in (slow, quick):
    A.update_character(p["id"], hex_col=TOGETHER[0], hex_row=TOGETHER[1],
                           bank=0, stable_id=None)
A.update_character(slow["id"], speed_m=7.5)
A.update_character(quick["id"], speed_m=18)


def window(together):
    return {"travel_mode": "choose", "travel_pcs": [slow["id"], quick["id"]],
            "col": META[0], "row": META[1], "forced_march": False,
            "together": together, "aboard": False, "player_preview": False,
            "travel_vehicle": None, "plan": None, "path": [], "branches": [],
            "singles": [], "rendezvous": None, "route": None, "by_river": False,
            "land": None}


results.append(("the two leave from the same hexagon",
              not hexmap._leave_scattered(
                  [A.character(slow["id"]), A.character(quick["id"])])))

# --- 1. with «together» on a single journey remains ---------------------
mine = window(True)
hexmap._compute_journey(mine, None)
results.append(("with «together» on the plan is one",
              mine["plan"] is not None and not mine["singles"]))
joined_days = mine["plan"].days if mine["plan"] is not None else None

# --- 2. off, there is one for each ---------------------------------------
mine = window(False)
hexmap._compute_journey(mine, None)
results.append(("off, from the same hexagon, the journeys become two",
              len(mine["singles"]) == 2))
by_name = {v["name"]: v for v in mine["singles"]}
results.append(("one for each of the two chosen",
              {slow["name"], quick["name"]} == set(by_name)))
results.append(("and whoever goes faster takes less",
              len(by_name) == 2
              and by_name[quick["name"]]["days"]
              < by_name[slow["name"]]["days"]))
results.append(("while the count at the top stays the slowest one's",
              mine["plan"] is not None
              and mine["plan"].days == by_name[slow["name"]]["days"]
              == joined_days))

# --- 3. and at departure two journeys depart, not one --------------------
chosen = [A.character(slow["id"]), A.character(quick["id"])]
before_journeys = {v["id"] for v in A.list_journeys(C, "in_progress")}
hexmap._apply_journey(mine, None, chosen, TOGETHER, META, immediately=False)
new_items = [v for v in A.list_journeys(C, "in_progress")
         if v["id"] not in before_journeys]
results.append(("pressing Depart two distinct journeys depart", len(new_items) == 2))
results.append(("each with its traveller",
              sorted(len(v["characters"]) for v in new_items) == [1, 1]))
results.append(("and nobody waits for the other: different days",
              len({v["days"] for v in new_items}) == 2))
for v in new_items:
    A.update_journey(v["id"], status="cancelled", turn_resolved=STATE.k["turn"])

# --- 4. the switch must be visible ---------------------------------------
# It sits inside the box, which without a NiceGUI page is not drawn: here
# the condition it appears under is looked at. Before it was «different
# positions», and it is the reason why from the same hexagon there was
# nothing to switch off.
source_text = helpers.map_source()
after = source_text.split('ui.checkbox(t("map.travel.travel_together")')[0]
condition = after.rstrip().splitlines()[-1].strip()
results.append(("the switch appears as soon as there are two",
              condition == "if len(chosen) > 1:"))

for char_id, col, row, sid, spd in before:
    A.update_character(char_id, hex_col=col, hex_row=row, stable_id=sid,
                           speed_m=spd)

width = max(len(n) for n, _ in results)
print()
for name, ok in results:
    print(("  ok  " if ok else " NO   ") + name.ljust(width))
print(f"\n{sum(1 for _, ok in results if ok)}/{len(results)} passed")
