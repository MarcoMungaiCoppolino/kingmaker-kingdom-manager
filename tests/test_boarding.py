"""Boarding and landing: one boards what is in front of one, one lands by saying where."""
import time
import uuid

from kingmaker.geometry import waterways, hexgrid, sections
from kingmaker.access import auth, permissions
from kingmaker import travel as v
from kingmaker.state import STATE
from kingmaker.ui import hexmap, theme
from kingmaker.access import view as view_mod
import helpers

permissions.can = lambda *a, **k: True
permissions.can_on_character = lambda *a, **k: True

told_ones = []
theme.notify = lambda text, *a, **k: told_ones.append(text)
theme.mark_dirty = lambda *a, **k: None
theme.refresh_panels = lambda *a, **k: None
theme.save_and_refresh = lambda *a, **k: None
helpers.silence("_redraw_travel", lambda *a, **k: None)

A, C = STATE.archive, STATE.campaign
m = STATE.k["map"]
orient = m["orientation"]
results = []


def clean():
    A.remove_lake(C)
    A.remove_currents(C)
    for c in list(A.campaign_banks(C)):
        A.set_banks(C, c, None)
    for k in list(A.campaign_borders(C)):
        A.set_border(C, (k[0], k[1]), (k[2], k[3]), None)


def new_vehicle(vehicle, kind, name):
    sid = uuid.uuid4().hex[:12]
    A.create_stable_vehicle({"id": sid, "campaign_id": C, "vehicle": vehicle,
                           "name": name, "available": 1, "speed_m": 12,
                           "kind": kind, "note": "",
                           "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                           "hex_col": None, "hex_row": None})
    A.update_stable_vehicle(sid, seats=6)
    return sid


clean()
LAND = (14, 8)
OTHER = (16, 8)
STATE.hex(*LAND)["terrains"] = ["plains"]
STATE.hex(*OTHER)["terrains"] = ["plains"]
for vic in hexgrid.neighbours(LAND[0], LAND[1], orient):
    STATE.hex(vic[0], vic[1])["terrains"] = ["plains"]

pc = STATE.characters()[0]
before = (pc.get("hex_col"), pc.get("hex_row"), pc.get("stable_id"))

# --- 1. the pure rules --------------------------------------------------
wagon = {"vehicle": "wagon", "name": "Il Carro", "kind": "land",
         "hex_col": LAND[0], "hex_row": LAND[1]}
near = {"name": "Tizio", "hex_col": LAND[0], "hex_row": LAND[1]}
far = {"name": "Caio", "hex_col": OTHER[0], "hex_row": OTHER[1]}
lost = {"name": "Sempronio", "hex_col": None, "hex_row": None}

results.append(("whoever is there boards", v.ascent_blocked(near, wagon) is None))
results.append(("whoever is far does not, and knows why",
              "not a far one" in (v.ascent_blocked(far, wagon) or "")))
results.append(("whoever is not on the map neither",
              "not on the map yet" in
              (v.ascent_blocked(lost, wagon) or "")))
results.append(("and a vehicle in the depot cannot be boarded",
              "is not on the map" in
              (v.ascent_blocked(near, {"vehicle": "wagon"}) or "")))

beside = hexgrid.neighbours(LAND[0], LAND[1], orient)[0]
results.append(("one gets off where the vehicle is",
              v.descent_blocked(wagon, LAND, orient) is None))
results.append(("and in a neighbouring hex",
              v.descent_blocked(wagon, beside, orient) is None))
results.append(("not three hexes away",
              "sets foot where the vehicle is" in
              (v.descent_blocked(wagon, (2, 2), orient) or "")))
results.append(("and the judgement on the place is given by whoever knows the map",
              v.descent_blocked(wagon, LAND, orient,
                                 landing_spot=lambda c: "no") == "no"))
results.append(("one does not get off a vehicle in the depot",
              "nowhere to get off" in
              (v.descent_blocked({"vehicle": "wagon"}, LAND, orient) or "")))

# --- 2. a wagon is placed on land, not in the lake ----------------------
sid = new_vehicle("wagon", "land", "Il Carro")
mine = {"place_vehicle": sid, "travel_mode": "place"}
hexmap._place_vehicle(mine, None, LAND)
results.append(("a wagon is put on the map like a boat",
              v.where_it_is(A.stable_vehicle(sid)) == LAND))
results.append(("and the marker is there, not on someone",
              LAND in {v.where_it_is(x) for x in A.list_stable(C)}))

LAKE = [(9, 4), (10, 4), (11, 4)]
A.set_lake(C, "l1", LAKE)
mine = {"place_vehicle": sid, "travel_mode": "place"}
told_ones.clear()
hexmap._place_vehicle(mine, None, (10, 4))
results.append(("a wagon does not fit in the lake",
              v.where_it_is(A.stable_vehicle(sid)) == LAND
              and "is water" in told_ones[-1]))

# --- 3. whoever is there boards -----------------------------------------
A.update_character(pc["id"], hex_col=OTHER[0], hex_row=OTHER[1],
                       stable_id=None)
told_ones.clear()
hexmap._board({}, None, sid, [pc["id"]])
results.append(("from afar one does not board, and the app says so",
              A.character(pc["id"])["stable_id"] is None
              and "not a far one" in told_ones[-1]))

A.update_character(pc["id"], hex_col=LAND[0], hex_row=LAND[1])
hexmap._board({}, None, sid, [pc["id"]])
results.append(("being there one boards",
              A.character(pc["id"])["stable_id"] == sid))

# --- 4. from a wagon one gets off next to the wagon ---------------------
# Without asking where: a wagon is in a hex, on a precise shore, and whoever
# gets off sets foot there. Asking meant letting people be unloaded in a
# neighbouring hex, which is something a stopped wagon does not do.
results.append(("from a land vehicle there is nothing to declare",
              hexmap._must_declare_where(A.stable_vehicle(sid)) is False))
mine = {}
hexmap._ask_landing(mine, None, sid, [pc["id"]])
has_disembarked = A.character(pc["id"])
results.append(("they get off at once, where the wagon is",
              has_disembarked["stable_id"] is None
              and (has_disembarked["hex_col"], has_disembarked["hex_row"]) == LAND))
results.append(("and no question stays open",
              mine.get("landing") is None
              and mine.get("travel_mode") != "place"))

# The shore is the wagon's: where a river cuts the hex, whoever gets off
# ends up on the same side, not on the other bank.
# To test it a really cut hex is needed: where the water does not pass «the
# shore it is on» means nothing, and a shore number written there was a
# notation without content — something that with a spot can no longer be
# done, and it is the point of the whole change.
A.set_banks(C, LAND, [[0, 1, 2], [3, 4, 5]])
land_faces = A.campaign_sections(C, m["orientation"]).get(LAND) or ()
beyond = sections.section_spot(land_faces, 1)
A.update_stable_vehicle(sid, pos_x=beyond[0], pos_y=beyond[1])
A.update_character(pc["id"], stable_id=sid, pos_x=None, pos_y=None)
hexmap._ask_landing({}, None, sid, [pc["id"]])
results.append(("and on the shore it is on",
              sections.section_of(A.character(pc["id"]), land_faces) == 1))
A.update_stable_vehicle(sid, pos_x=None, pos_y=None)
A.set_banks(C, LAND, None)

A.delete_stable_vehicle(sid)

# --- 5. from a boat one lands ashore -------------------------------------
INSIDE = (10, 4)          # surrounded by lake
EDGE = (11, 4)
sidb = new_vehicle("barca_a_remi", "water", "La Lontra")
mine = {"place_vehicle": sidb, "travel_mode": "place"}
hexmap._place_vehicle(mine, None, INSIDE)
results.append(("a boat fits in the lake", v.where_it_is(A.stable_vehicle(sidb))
              == INSIDE))

A.update_character(pc["id"], hex_col=INSIDE[0], hex_row=INSIDE[1])
hexmap._board({}, None, sidb, [pc["id"]])
results.append(("and is boarded being there",
              A.character(pc["id"])["stable_id"] == sidb))

mine = {}
hexmap._ask_landing(mine, None, sidb, [pc["id"]])
told_ones.clear()
hexmap._land_here(mine, None, INSIDE)
results.append(("in the middle of the lake one does not land",
              A.character(pc["id"])["stable_id"] == sidb
              and "gets off ashore" in told_ones[-1]))
told_ones.clear()
hexmap._land_here(mine, None, EDGE)
results.append(("nor on another cell of the lake",
              A.character(pc["id"])["stable_id"] == sidb
              and "gets off ashore" in told_ones[-1]))

# The shore: a hex next to the lake that is not lake. From a boat one lands
# on a shore that **touches the junction** it sits on: from the center of the
# lake the shore is not touched, and the boat must first be brought to the
# corner that touches it.
bank = next(tuple(c) for c in hexgrid.neighbours(INSIDE[0], INSIDE[1], orient)
            if tuple(c) not in LAKE)
STATE.hex(*bank)["terrains"] = ["plains"]
told_ones.clear()
hexmap._land_here(mine, None, bank)
results.append(("from the center of the lake the shore is not touched, and it says so",
              A.character(pc["id"])["stable_id"] == sidb
              and "gets off ashore" in told_ones[-1]))
corner = next(k for k in range(6)
              if bank in [tuple(c) for c, _k in
                          waterways.vertex_owners(INSIDE, k, orient)])
corner_spot = sections.unit_corners(orient)[corner]
A.update_stable_vehicle(sidb, pos_x=corner_spot[0], pos_y=corner_spot[1])
hexmap._land_here(mine, None, bank)
results.append(("ashore yes, and that is where one sets foot",
              A.character(pc["id"])["stable_id"] is None
              and (A.character(pc["id"])["hex_col"],
                   A.character(pc["id"])["hex_row"]) == bank))

A.delete_stable_vehicle(sidb)
A.update_character(pc["id"], hex_col=before[0], hex_row=before[1],
                       stable_id=before[2])
clean()

# --- 6. the click: a face before a vehicle, a vehicle before the ground ---
# As long as vehicles were only boats in the middle of the water, clicking
# the hex was enough to take them: there are no people markers there. With
# wagons stopped together with the group that rule ate the most important
# gesture there is — clicking a hex to take whoever stands on it.
clean()
sid = new_vehicle("wagon", "land", "Il Carro")
mine = {"place_vehicle": sid, "travel_mode": "place"}
hexmap._place_vehicle(mine, None, LAND)
A.update_character(pc["id"], hex_col=LAND[0], hex_row=LAND[1],
                       stable_id=None, bank=0)

size = float(m["size"])
origin = (float(m["origin_x"]), float(m["origin_y"]))
cx, cy = hexgrid.hex_center(LAND[0], LAND[1], size, origin, orient)
# A GM view: here the click is tested, not the fog. Without a user the view
# behaves as a player and returns no marker.
gm_row = next(r for r in A._conn.execute(
    "SELECT * FROM users WHERE role IN ('gm','admin')"))
gm = auth.User(id=gm_row["id"], username=gm_row["username"],
                 role=gm_row["role"], active=True, must_change_pw=False)
view = view_mod.MapView(gm, STATE)

# A placed vehicle is a **member** of its piece of hex, like a person: with
# the character in the same piece they make a single badge, with the number,
# and the vehicle is chosen from the box. In a piece as big as an atom there
# was no room for two badges.
members = hexmap._members_per_hex(view).get(LAND) or []
results.append(("the placed vehicle is a member of the hex, with whoever is on it",
              any(x.get("id") == sid for x in members)
              and any(x.get("id") == pc["id"] for x in members)))
badges = hexmap.marker_positions(members, cx, cy, size, LAND, origin, orient,
                                   A.campaign_sections(C, orient))
results.append(("and in the same piece they make a single badge", len(badges) == 1))
group, gx, gy, gr = badges[0]
results.append(("holding both",
              {x["id"] for x in group} >= {sid, pc["id"]}))
taken = hexmap.marker_under(view, m, (gx, gy), LAND)
results.append(("clicking it takes the group, vehicle included",
              taken is not None and any(x.get("id") == sid for x in taken)))

# Sending the character away, the vehicle stays alone in its piece: then its
# badge is taken as a face is taken, where it is drawn.
elsewhere = tuple(hexgrid.neighbours(LAND[0], LAND[1], orient)[3])
A.update_character(pc["id"], hex_col=elsewhere[0], hex_row=elsewhere[1])
STATE.load()          # the view reads the characters from the in-memory state
view = view_mod.MapView(gm, STATE)
alone_items = hexmap.marker_positions(hexmap._members_per_hex(view).get(LAND) or [],
                                  cx, cy, size, LAND, origin, orient,
                                  A.campaign_sections(C, orient))
results.append(("alone the vehicle has its own badge",
              len(alone_items) == 1 and len(alone_items[0][0]) == 1))
_g, mx, my, _r = alone_items[0]
taken = hexmap.marker_under(view, m, (mx, my), LAND) or []
results.append(("clicking it takes the vehicle",
              len(taken) == 1 and taken[0].get("id") == sid))
land = (cx, cy - size * 0.6)
results.append(("and on the bare ground not",
              hexmap.marker_under(view, m, land, LAND) is None))
beside_wagon = tuple(hexgrid.neighbours(LAND[0], LAND[1], orient)[0])
results.append(("the vehicle is hit where it is drawn, from the neighbouring hex too",
              any(x.get("id") == sid for x in
                  hexmap.marker_under(view, m, (mx, my), beside_wagon) or [])))

# --- 6bis. one boards only from the same atom ----------------------------
# A piece of hex can be as big as an atom, and «being in the same hex» no
# longer means having the vehicle in front: there may be a river in between.
# On the scene's cut hex, the vehicle on shore 1 and the character on shore 0
# do not touch.
CUT = (9, 4)
banks_here = A.campaign_sections(C, orient)
faces_here = banks_here.get(CUT) or ()
if len(faces_here) >= 2:
    this_side = sections.section_spot(faces_here, 0)
    beyond = sections.section_spot(faces_here, 1)
    wagon_beyond = {"id": "fake", "vehicle": "wagon", "name": "Carro",
                   "hex_col": CUT[0], "hex_row": CUT[1],
                   "pos_x": beyond[0], "pos_y": beyond[1]}
    who_this_side = {"name": "Tizio", "hex_col": CUT[0], "hex_row": CUT[1],
                  "pos_x": this_side[0], "pos_y": this_side[1]}
    who_beyond = dict(who_this_side, pos_x=beyond[0], pos_y=beyond[1])
    results.append(("same hex but across the river: no boarding",
                  "pezzi diversi" in (v.ascent_blocked(who_this_side, wagon_beyond,
                                                        banks_here, orient) or "")))
    results.append(("in the same atom one boards",
                  v.ascent_blocked(who_beyond, wagon_beyond, banks_here, orient) is None))
    results.append(("and without the banks the earlier rule holds, per hex",
                  v.ascent_blocked(who_this_side, wagon_beyond) is None))

A.delete_stable_vehicle(sid)
A.update_character(pc["id"], hex_col=before[0], hex_row=before[1],
                       stable_id=before[2])
STATE.load()
clean()

# --- 7. the pointer goes back to what it was ------------------------------
# The cursor lives in a style written on the image: changing the mode is not
# enough, it must be rewritten. It was switched on entering «place» and not
# switched off leaving it — after letting someone off the arrow with the plus
# stayed on you, saying «now click where to put it» when there was nothing
# left to put.
results.append(("placing, the pointer says «click where»",
              hexmap._slider_for({"travel_mode": "place"})
              == "cursor:copy;"))
results.append(("and choosing it says something else",
              hexmap._slider_for({"travel_mode": "choose"})
              != hexmap._slider_for({"travel_mode": "place"})))

sid = new_vehicle("wagon", "land", "Il Carro")
A.update_character(pc["id"], hex_col=LAND[0], hex_row=LAND[1],
                       stable_id=None)


def with_slider(extra=None):
    """A window that remembers how many times its cursor was rewritten."""
    mine = {"travel_mode": "place", "counted": []}
    mine["apply_slider"] = lambda: mine["counted"].append(
        hexmap._slider_for(mine))
    mine.update(extra or {})
    return mine


mine = with_slider({"place_vehicle": sid})
hexmap._place_vehicle(mine, None, LAND)
results.append(("a vehicle placed, the pointer is rewritten",
              mine["counted"] and mine["counted"][-1] != "cursor:copy;"))

hexmap._board({}, None, sid, [pc["id"]])
mine = with_slider({"landing": {"sid": sid, "char_ids": [pc["id"]]}})
hexmap._land_here(mine, None, LAND)
results.append(("someone off, the pointer goes back in place",
              A.character(pc["id"])["stable_id"] is None
              and mine["counted"] and mine["counted"][-1] != "cursor:copy;"))

# And when the landing is refused the pointer **stays** the placing one: the
# gesture is not over, one still has to click somewhere else.
hexmap._board({}, None, sid, [pc["id"]])
mine = with_slider({"landing": {"sid": sid, "char_ids": [pc["id"]]}})
told_ones.clear()
hexmap._land_here(mine, None, (2, 2))
results.append(("but if the landing is refused the gesture is not over",
              mine["counted"] == [] and mine["travel_mode"] == "place"))

mine = with_slider({"place_pc": pc["id"]})
hexmap._place_marker(mine, None, LAND, None)
results.append(("and it holds for a character's marker too",
              mine["counted"] and mine["counted"][-1] == "cursor:auto;"))

A.delete_stable_vehicle(sid)
A.update_character(pc["id"], hex_col=before[0], hex_row=before[1],
                       stable_id=before[2])
clean()

# --- 8. choosing a face, and the vehicle carrying it ----------------------
# With a boat in hand, clicking a person ashore changed nothing: the journey
# stayed the water one, because the vehicle stayed in hand all the same. And
# the other way round: taking someone on a wagon one wants to see the wagon
# lit too — it is the same thing that leaves.
clean()
sid = new_vehicle("wagon", "land", "Il Carro")
mine = {"place_vehicle": sid, "travel_mode": "place"}
hexmap._place_vehicle(mine, None, LAND)

aboard_pcs = pc
on_foot = next(x for x in STATE.characters() if x["id"] != pc["id"])
A.update_character(aboard_pcs["id"], hex_col=LAND[0], hex_row=LAND[1],
                       stable_id=sid, bank=0)
A.update_character(on_foot["id"], hex_col=OTHER[0], hex_row=OTHER[1],
                       stable_id=None, bank=0)

results.append(("whoever is on a vehicle brings it along when chosen",
              hexmap._vehicle_of([aboard_pcs["id"]]) == sid))
results.append(("whoever walks brings nothing",
              hexmap._vehicle_of([on_foot["id"]]) is None))
results.append(("and a group on different vehicles keeps none",
              hexmap._vehicle_of([aboard_pcs["id"], on_foot["id"]]) is None))
results.append(("as does an empty choice", hexmap._vehicle_of([]) is None))

# The real gesture: the face is clicked on the map.
size = float(m["size"])
origin = (float(m["origin_x"]), float(m["origin_y"]))
# `_choose_from_click` builds the view on its own, from `theme.user()`:
# without a GM in there it looks as a player and finds no marker.
theme.user = lambda: gm
view = view_mod.MapView(gm, STATE)


def click_face(mine, who, where):
    cx, cy = hexgrid.hex_center(where[0], where[1], size, origin, orient)
    people = hexmap.characters_on(where, view)
    seats = hexmap.marker_positions(people, cx, cy, size, where, origin,
                                       orient, A.campaign_banks(C))
    point = next((x, y) for group, x, y, _r in seats
                 if any(q["id"] == who["id"] for q in group))
    # With a group of more than one the click would open the box instead of
    # choosing: here the choice matters, so ctrl is used, which adds the
    # whole group without opening anything.
    only = len(next(g for g, _x, _y, _r in seats
                    if any(q["id"] == who["id"] for q in g))) == 1
    hexmap._choose_from_click(mine, None, where, point, not only)


mine = {"travel_pcs": [], "travel_vehicle": sid, "travel_mode": "choose"}
click_face(mine, on_foot, OTHER)
results.append(("clicking whoever walks the vehicle is dropped",
              mine["travel_pcs"] == [on_foot["id"]]
              and mine["travel_vehicle"] is None))

# Whoever is aboard travels **inside** the vehicle: on the map they have no
# badge of their own, they show small in the vehicle's badge, and are taken by
# taking the vehicle. A click on the ground does not take them alone.
results.append(("whoever is aboard is not a member on their own: they are inside the vehicle",
              all(p_["id"] != aboard_pcs["id"]
                  for p_ in hexmap.characters_on(LAND, view))))
mine = {"travel_pcs": [], "travel_vehicle": None, "travel_mode": "choose"}
hexmap._choose_vehicle(mine, None, A.stable_vehicle(sid))
results.append(("taking the vehicle those on it come too",
              mine["travel_pcs"] == [aboard_pcs["id"]]
              and mine["travel_vehicle"] == sid))

# And the drawing shows it: the vehicle is the member, the passenger is
# inside — their face small in the vehicle's badge, not a group of two.
land_members = hexmap._members_per_hex(view).get(LAND) or []
vehicle_here = next((x for x in land_members if x.get("id") == sid), None)
results.append(("on the drawing the vehicle is the member, and the passenger is inside",
              vehicle_here is not None
              and any(p_["id"] == aboard_pcs["id"]
                      for p_ in vehicle_here.get("passengers") or ())
              and all(x.get("id") != aboard_pcs["id"] for x in land_members)))
in_row = "".join(hexmap._svg_markers(view, size, origin, orient, set()))
initial = (aboard_pcs["name"] or "?")[:1].upper()
results.append(("and on the drawing their initial is inside the vehicle's badge",
              f">{initial}<" in in_row))

# --- 9. and the ruler receives the right field ----------------------------
# Only a boat changes the road: with a wagon in hand the ruler got the water
# field, and on dry land there is nothing to follow — dragging no longer drew
# anything.
def field_of(mine):
    return hexmap.travel_field(mine)


field = field_of({"travel_pcs": [aboard_pcs["id"]], "travel_vehicle": sid,
                  "travel_mode": "choose", "forced_march": False,
                  "together": True, "aboard": True,
                  "player_preview": False})
results.append(("with a wagon in hand the ruler has the land field",
              field.get("active") is True and "water" not in field))
results.append(("and with the travellers in it",
              len(field.get("travellers") or []) == 1))

# The boat instead does: its road is the drawn water.
A.set_banks(C, (9, 4), [[0, 1, 2], [3, 4, 5]])
sidb = new_vehicle("barca_a_remi", "water", "La Lontra")
mine_b = {"place_vehicle": sidb, "travel_mode": "place"}
hexmap._place_vehicle(mine_b, None, (9, 4))
water_field = field_of({"travel_pcs": [], "travel_vehicle": sidb,
                        "travel_mode": "choose", "forced_march": False,
                        "together": True, "aboard": True,
                        "player_preview": False})
results.append(("with a boat in hand the ruler has the water field",
              water_field.get("water") is True))

# --- 10. and on the map both light up ------------------------------------
# The sign of «I took this in hand» is the same for a face and for a vehicle:
# a white dashed ring. Choosing whoever travels on a wagon both must light up
# — they are the same thing that leaves.
def rings(drawing):
    # The «in hand» ring has a dark circle under it: counting it holds both
    # for big badges and for the small faces inside a vehicle.
    return drawing.count('stroke="#12100b"')


# Vehicle and passenger in the same piece are **a single badge**, with the
# number: choosing whoever travels on the wagon lights that badge — which is
# both of them.
off_ones = "".join(hexmap._svg_markers(view, size, origin, orient, set(), set()))
lit_items = "".join(hexmap._svg_markers(view, size, origin, orient,
                                       {aboard_pcs["id"]}, {sid}))
results.append(("with nothing in hand nobody lights up",
              rings(off_ones) == 0))
results.append(("choosing whoever travels on a vehicle lights the group's badge, "
              "which is both", rings(lit_items) == 1))
# And the two boats stopped on the same junction — the scene's and the one
# just placed, both at the center of 9,4 — are a group with the number, like
# two people in the same piece.
results.append(("and two boats on the same junction make a group with the number",
              ">2</text>" in lit_items))

A.delete_stable_vehicle(sidb)
A.delete_stable_vehicle(sid)
A.update_character(aboard_pcs["id"], hex_col=before[0], hex_row=before[1],
                       stable_id=before[2])
clean()

# --- 11. whoever gets off no longer leaves --------------------------------
# The drawn journey belonged to that group on that vehicle: letting someone
# off it can no longer be made. It stayed drawn all the same, with its buttons
# below — «Depart» was there and nothing departed.
clean()
sid = new_vehicle("wagon", "land", "Il Carro")
mine = {"place_vehicle": sid, "travel_mode": "place"}
hexmap._place_vehicle(mine, None, LAND)
A.update_character(pc["id"], hex_col=LAND[0], hex_row=LAND[1],
                       stable_id=sid, bank=0)

mine = {"travel_mode": "choose", "travel_vehicle": sid,
       "travel_pcs": [pc["id"]], "plan": "fake", "path": [[1, 1], [2, 2]],
       "branches": ["x"], "singles": ["y"], "rendezvous": "z", "route": "r",
       "by_river": True, "landing": None}
hexmap._ask_landing(mine, None, sid, [pc["id"]])
results.append(("someone off, the proposed journey goes out",
              mine["plan"] is None and mine["path"] == []
              and mine["branches"] == [] and mine["singles"] == []
              and mine["rendezvous"] is None and mine["route"] is None
              and mine["by_river"] is False))
# The vehicle stays in hand — an empty boat is rowed all the same — but
# carries nobody any more, and without travellers the ruler has nothing to
# draw.
results.append(("and the travellers become those left aboard, i.e. nobody",
              mine["travel_pcs"] == []))
theme.user = lambda: gm
results.append(("so the ruler goes out, instead of offering a fake journey",
              hexmap.travel_field(dict(mine, forced_march=False,
                                        together=True, aboard=True,
                                        player_preview=False))
              .get("active") is not True))

# --- 12. and a journey already under way is cancelled, but asks first ------
import uuid as _uuid                                                  # noqa: E402
import time as _time                                                  # noqa: E402

A.update_character(pc["id"], hex_col=LAND[0], hex_row=LAND[1],
                       stable_id=sid)
vid = _uuid.uuid4().hex[:12]
A.create_journey({"id": vid, "campaign_id": C, "characters": [pc["id"]],
                "stable_id": sid, "departure": "14,8", "arrival": "16,8",
                "path": [[14, 8], [16, 8]], "costs": [1],
                "legs": [], "activity_cost": 1, "days": 1,
                "activities_per_day": 2, "progress": 0.0, "departure_day": 0,
                "forced_march": 0, "status": "in_progress",
                "turn_created": STATE.k["turn"], "created_by": None,
                "created_at": _time.strftime("%Y-%m-%dT%H:%M:%S")})
results.append(("the departed journey counts as in progress",
              pc["id"] in hexmap.journeys_by_character({pc["id"]})))

# Asking to get off arms nothing: first the question opens.
mine = {"travel_mode": "choose", "landing": None}
open_ones = []
import kingmaker.ui.theme as _theme                                   # noqa: E402
real_dialog = _theme.dialog
helpers.silence("_confirm_landing_while_travelling", (
    lambda mia_, mappa_, sid_, pids_, dove_: open_ones.append((sid_, list(pids_)))))
hexmap._ask_landing(mine, None, sid, [pc["id"]])
results.append(("with a journey in progress the landing stops and asks",
              open_ones == [(sid, [pc["id"]])] and mine.get("landing") is None))
results.append(("and the journey is still there, until confirmed",
              pc["id"] in hexmap.journeys_by_character({pc["id"]})))

# Confirming: the journey is cancelled and the landing is armed.
A.update_journey(vid, status="cancelled", turn_resolved=STATE.k["turn"])
results.append(("cancelled, it no longer counts as in progress",
              pc["id"] not in hexmap.journeys_by_character({pc["id"]})))
A.update_character(pc["id"], stable_id=sid, hex_col=LAND[0],
                       hex_row=LAND[1])
mine = {"travel_mode": "choose", "landing": None}
hexmap._ask_landing(mine, None, sid, [pc["id"]])
results.append(("and with no journeys in progress one just gets off",
              A.character(pc["id"])["stable_id"] is None))

A.delete_stable_vehicle(sid)
A.update_character(pc["id"], hex_col=before[0], hex_row=before[1],
                       stable_id=before[2])
clean()

# --- 9. a vehicle in the depot is in nobody's hand ------------------------
# The old link: a person still assigned to a boat put away. Taken at face
# value, choosing that person meant finding the boat in hand — and with a
# boat in hand the ruler looks for water. On a land journey it found none,
# drew nothing more, and without a path there is no count: the group travel
# box vanished without saying why.
depot = new_vehicle("chiatta", "water", "La Messa Via")   # without a hex
A.update_character(pc["id"], hex_col=LAND[0], hex_row=LAND[1],
                       stable_id=depot)
results.append(("a vehicle in the depot does not count as in the hand of its assignee",
              hexmap._vehicle_of([pc["id"]]) is None))
results.append(("not even if forced into their hand",
              hexmap._vehicle_in_hand({"travel_vehicle": depot}) is None))
results.append(("it is not among the vehicles one leaves with",
              depot not in hexmap._vehicles_in_play()))

# The test that matters: the ruler works all the same, so the group journey
# can be prepared.
class Allowed:
    id, username, role = "check", "check", permissions.ADMIN
    active = True


real_user = theme.user
theme.user = lambda: Allowed()
try:
    mine = {"travel_mode": "choose", "travel_pcs": [pc["id"]],
           "travel_vehicle": hexmap._vehicle_of([pc["id"]]),
           "forced_march": False, "together": True, "aboard": False,
           "player_preview": False}
    results.append(("with the vehicle in the depot the land ruler stays on",
                  hexmap.travel_field(mine).get("active") is True))
    # And the count does not take the Speed of a wagon locked in the shed.
    _spd, _source, warnings = v.group_pace([A.character(pc["id"])],
                                             hexmap._vehicles_in_play(), True)
    results.append(("and the group walks, saying so",
                  any("on foot" in x for x in warnings)))

    # Placed on the map, the same link counts again.
    A.update_stable_vehicle(depot, hex_col=LAND[0], hex_row=LAND[1])
    results.append(("placed on the map, the vehicle is in hand again",
                  hexmap._vehicle_of([pc["id"]]) == depot))
    results.append(("and is back among the vehicles one leaves with",
                  depot in hexmap._vehicles_in_play()))
finally:
    theme.user = real_user
A.update_character(pc["id"], stable_id=None)
A.delete_stable_vehicle(depot)

# --- a boat taken back to the depot sets its passengers on dry ground ---
# A boat on the river's chord, with someone aboard exactly on the line: taken
# back, they must stand inside an atom, not on the water; in a lake, in the
# nearest neighbour with ground.
clean()
RIVER_ROW = [(9, 4), (10, 4), (11, 4), (12, 4)]
for c in RIVER_ROW:
    A.set_banks(C, c, [[0, 1, 2], [3, 4, 5]])
for a, b in zip(RIVER_ROW, RIVER_ROW[1:]):
    A.set_border(C, a, b, "water")
boat = new_vehicle("barca_a_remi", "water", "Ferry")
corner = tuple(sections.unit_corners(orient)[3])
A.update_stable_vehicle(boat, hex_col=10, hex_row=4, pos_x=corner[0], pos_y=corner[1])
sailor = STATE.characters()[0]
A.update_character(sailor["id"], stable_id=boat, hex_col=10, hex_row=4, pos_x=corner[0], pos_y=corner[1])
hexmap._put_back_in_depot({"travel_vehicle": None, "travel_pcs": []}, None, boat)
landed = A.character(sailor["id"])
results.append(("back in the depot, the passenger is on the ground of the same hex",
              landed["stable_id"] is None and (landed["hex_col"], landed["hex_row"]) == (10, 4)))
faces = hexmap.sections_map().get((10, 4)) or ()
on_a_face = sections.face_of_point(faces, (landed["pos_x"], landed["pos_y"])) if faces else 0
results.append(("and inside a piece, not on the water line",
              landed["pos_x"] is not None and (landed["pos_x"], landed["pos_y"]) != corner
              and on_a_face is not None))
# The lake: the boat in the middle of a lake cell, the passenger goes to a neighbour.
def _vertex_name(coord, k):
    return waterways.node_text(waterways.vertex_key(coord, k, orient))
ring = [_vertex_name((9, 4), k) for k in (2, 3, 4)] + [_vertex_name((11, 4), k) for k in (5, 0, 1)]
A.set_lake(C, "l1", [(9, 4), (10, 4), (11, 4)], points=ring)
A.update_stable_vehicle(boat, hex_col=10, hex_row=4, pos_x=0.0, pos_y=0.0)
A.update_character(sailor["id"], stable_id=boat, hex_col=10, hex_row=4, pos_x=0.0, pos_y=0.0)
hexmap._put_back_in_depot({"travel_vehicle": None, "travel_pcs": []}, None, boat)
landed = A.character(sailor["id"])
results.append(("from a lake the passenger lands in a neighbouring hex with ground",
              landed["stable_id"] is None and (landed["hex_col"], landed["hex_row"]) != (10, 4)
              and (landed["hex_col"], landed["hex_row"]) in {tuple(n) for n in hexgrid.neighbours(10, 4, orient)}
              and landed["pos_x"] is not None))
A.remove_lake(C)
A.delete_stable_vehicle(boat)
clean()

# --- the way out: the chosen characters taken off the map ----------------
told_ones.clear()
A.update_character(sailor["id"], hex_col=10, hex_row=4, pos_x=0.1, pos_y=0.1, stable_id=None)
mine_off = {"travel_pcs": [sailor["id"]], "travel_vehicle": None, "plan": None}
hexmap._remove_from_map(mine_off, None)
gone = A.character(sailor["id"])
results.append(("taken off the map: no hex, no point, no vehicle, and the choice cleared",
              gone["hex_col"] is None and gone["pos_x"] is None and gone["stable_id"] is None
              and mine_off["travel_pcs"] == []))
A.update_character(sailor["id"], hex_col=10, hex_row=4)

width = max(len(n) for n, _ in results)
for name, ok in results:
    print(("  ok  " if ok else " NO   ") + name.ljust(width))
print("")
print(str(sum(1 for _, ok in results if ok)) + "/" + str(len(results)) + " passate")
