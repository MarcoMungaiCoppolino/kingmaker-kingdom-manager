"""A test scene: a river with a real bend, and a boat on it."""
import time, uuid
from kingmaker.state import STATE
A, C = STATE.archive, STATE.campaign
m = STATE.k["map"]; orient = m["orientation"]
A.remove_lake(C); A.remove_currents(C); A.remove_crossings(C)
# Everyone goes back to their place and on foot, and no journey stays in
# progress: a test must not inherit the moves made by another.
from scene import CHARACTERS
_seats = {name: coord for name, _cos, coord, _acc in CHARACTERS}
for _p in STATE.characters():
    _where = _seats.get(_p["name"])
    if _where:
        A.update_character(_p["id"], hex_col=_where[0], hex_row=_where[1],
                               pos_x=None, pos_y=None, stable_id=None)
for _v in A.list_journeys(C, "in_progress"):
    A.update_journey(_v["id"], status="cancelled")
# And nobody swims, unless the test asks for it: the scene is shared by
# every file, and a Swim Speed left on a character lets the water be crossed
# in the tests that want it to be a wall.
for _p in STATE.characters(): A.update_character(_p['id'], swim_speed_m=0)
for c in list(A.campaign_banks(C)): A.set_banks(C, c, None)
for k in list(A.campaign_borders(C)): A.set_border(C, (k[0],k[1]), (k[2],k[3]), None)
# a river meandering inside four hexes in a row: every hex cut from one
# vertex to another, and the edges between them marked
RIVER = [(9,4),(10,4),(11,4),(12,4)]
for c in RIVER:
    A.set_banks(C, c, [[0,1,2],[3,4,5]])
for a, b in zip(RIVER, RIVER[1:]):
    A.set_border(C, a, b, "water")
for x in A.list_stable(C):
    if x["vehicle"] == "barca_a_remi": A.delete_stable_vehicle(x["id"])
sid = uuid.uuid4().hex[:12]
A.create_stable_vehicle({"id": sid, "campaign_id": C, "vehicle": "barca_a_remi",
    "name": "La Lontra", "available": 1, "speed_m": None, "kind": "",
    "note": "", "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    "hex_col": 9, "hex_row": 4})
A.update_stable_vehicle(sid, seats=6)
pc = ([p for p in STATE.characters() if p["name"] == "Dagny"] or STATE.characters())[0]
A.update_character(pc["id"], stable_id=sid, hex_col=9, hex_row=4)
print("ready", pc["name"], sid, len(A.campaign_borders(C)), len(A.campaign_banks(C)))
