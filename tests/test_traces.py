"""The arrow seen while somebody else is still preparing it."""
import types

from nicegui import Client

from kingmaker.access import auth, permissions, view as view_mod
from kingmaker.state import STATE
from kingmaker.ui import hexmap, theme

results = []
A, C = STATE.archive, STATE.campaign
m = STATE.k["map"]
size = float(m["size"])
origin = (float(m["origin_x"]), float(m["origin_y"]))
orient = m["orientation"]

users = [auth.User(id=u["id"], username=u["username"], role=u["role"],
                      active=bool(u["active"]), must_change_pw=False)
          for u in A.list_users()]

# --- 1. one colour per person, and always the same ------------------------
colors = [hexmap.player_color(u) for u in users]
results.append((f"{len(users)} account, {len(set(colors))} colori diversi",
              len(set(colors)) == len(users)))
results.append(("asked twice gives the same colour",
              colors == [hexmap.player_color(u) for u in users]))
results.append(("they are all colours of the palette",
              all(c in hexmap.PLAYER_COLORS for c in colors)))
results.append(("without a user it does not blow up",
              hexmap.player_color(None) in hexmap.PLAYER_COLORS))

# --- 2. who may see an arrow while it is being drawn ----------------------
# Fake windows: `other_windows` reads from there, and they are not in
# `_REFRESH` so the pruning of closed windows does not touch them.
gm = next(u for u in users if permissions.can(u, permissions.SEE_SECRETS))
player = next(u for u in users if not permissions.can(u, permissions.SEE_SECRETS))
theme._WINDOWS["finta-gm"] = {"user": gm, "tab": "map"}
theme._WINDOWS["finta-giocatore"] = {"user": player, "tab": "map"}
theme._WINDOWS["finta-altrove"] = {"user": gm, "tab": "kingdom"}

characters = A.list_characters(C)
its_ones = [p["id"] for p in characters if p.get("user_id") == player.id]
others_pcs = [p["id"] for p in characters if p.get("user_id") != player.id]
results.append(("the save has both a player's character and somebody else's",
              bool(its_ones) and bool(others_pcs)))

own_public = hexmap._trace_audience(its_ones)
results.append(("the journey of one of their characters reaches the player",
              "finta-giocatore" in own_public))
results.append(("and reaches the GM too", "finta-gm" in own_public))

view = view_mod.MapView(player, STATE)
seen = {p["id"] for p in view.markers()}
hidden = [p for p in others_pcs if p not in seen]
if hidden:
    others_public = hexmap._trace_audience(hidden)
    results.append(("the journey of someone they do not see does not reach them",
                  "finta-giocatore" not in others_public))
    results.append(("but the GM it does", "finta-gm" in others_public))
else:
    results.append(("(no character hidden from this player: "
                  "the rule cannot be tested here)", True))

# --- 3. the traces store: it fills up and empties -------------------------
# `_send_traces` throws away the arrows of windows that are no longer
# there: here the test window must therefore appear alive.
WINDOW = "finestra-di-prova"
Client.instances[WINDOW] = object()
theme.user = lambda: gm
theme.current_window = lambda: WINDOW
hexmap._TRACES.clear()
# The traces are **polylines in pixels**, the same ones whoever draws sees.
P = [[100.0, 200.0], [150.5, 220.25], [210.0, 240.0]]
hexmap._live_trace({}, {"stretches": [P],
                          "labels": ["max 5 att · 3 giorni"], "pc": its_ones})
trace = hexmap._TRACES.get(WINDOW)
results.append(("a movement writes the trace", trace is not None))
results.append(("with the name of whoever draws and what they are doing",
              trace is not None
              and trace["title"] == f"{gm.username} is tracing"))
results.append(("and with their colour",
              trace is not None and trace["color"] == hexmap.player_color(gm)))
results.append(("the days travel with the arrow",
              trace is not None and trace["labels"] == ["max 5 att · 3 giorni"]))
results.append(("and it is marked as live, so it expires on its own",
              trace is not None and trace["live"] is True))
hexmap._live_trace({}, {"stretches": [], "pc": []})
results.append(("the release removes it", WINDOW not in hexmap._TRACES))

# --- 4. a stroke of a single point is not an arrow ------------------------
hexmap._live_trace({}, {"stretches": [[[100.0, 200.0]]], "pc": its_ones})
results.append(("a stroke of a single point is not sent",
              WINDOW not in hexmap._TRACES))

# --- 5. malformed stuff must not bring the server down --------------------
for garbage in ({}, {"stretches": None}, {"stretches": [[["x", "y"], [1, 2]]]},
                   {"stretches": [[[1], [2]]]}, {"stretches": "no"},
                   {"stretches": [[[float("nan"), 1.0], [1.0, float("inf")]]]},
                   {"stretches": [[[9, 4], [10, 4]]], "pc": "non-una-lista"},
                   {"stretches": [[[9, 4], [10, 4]]], "labels": "no"},
                   {"stretches": [[[9, 4], [10, 4]]], "labels": [None]}):
    try:
        hexmap._live_trace({}, garbage)
    except Exception as error:      # noqa: BLE001 — it is precisely what is tested
        results.append((f"payload storto {garbage}: {error!r}", False))
        break
else:
    results.append(("nine bent payloads, none raises an exception", True))
hexmap._TRACES.clear()

# --- 6. the points stay those sent, rounded to the tenth ----------------
hexmap._live_trace({}, {"stretches": [P], "pc": its_ones})
saved = hexmap._TRACES[WINDOW]["stretches"][0]
results.append(("the points stay those whoever draws sent",
              saved == [(100.0, 200.0), (150.5, 220.2), (210.0, 240.0)]
              or saved == [(100.0, 200.0), (150.5, 220.3), (210.0, 240.0)]))
hexmap._TRACES.clear()


# --- 7. the plan: the one born from the right button ----------------------
def fake_plan(days, cost, maximum=False, possible=True):
    return types.SimpleNamespace(days=days, total_cost=cost,
                                 possible=possible, max_estimate=maximum)


results.append(("the plan text says activities and days",
              hexmap.plan_text(fake_plan(3, 7)) == "7 act · 3 days"))
results.append(("in the singular it says «day»",
              hexmap.plan_text(fake_plan(1, 2)) == "2 act · 1 day"))
results.append(("with unknown hexes it writes «max»",
              hexmap.plan_text(fake_plan(3, 7, maximum=True))
              == "max 7 act · 3 days"))
results.append(("with the meeting it says only the days",
              hexmap.plan_text(fake_plan(3, 7), of_group=True) == "3 days"))

mine = {"travel_pcs": its_ones, "path": [(9, 4), (10, 4), (11, 4)],
       "branches": [], "singles": [], "rendezvous": None, "plan": fake_plan(3, 7)}
hexmap._trace_from_plan(mine)
from_plan = hexmap._TRACES.get(WINDOW)
results.append(("a plan made with the right button is seen by the others",
              from_plan is not None))
results.append(("and says it is a journey in preparation",
              from_plan is not None
              and from_plan["title"] == f"{gm.username} is preparing"))
results.append(("with the plan's days",
              from_plan is not None and from_plan["labels"] == ["7 act · 3 days"]))
results.append(("and does not expire on its own: it stays until you change it",
              from_plan is not None and from_plan["live"] is False))
# What is published is **the polyline** this window draws, point by point:
# whoever watches sees what whoever draws sees.
wait = [(round(x, 1), round(y, 1)) for x, y in hexmap._polyline(
    mine["path"], size, origin, orient, hexmap._shores_of(mine))]
results.append(("and it is the polyline this window draws, point by point",
              from_plan is not None and from_plan["stretches"][0] == wait))

# A journey inside the hexagon: a single hexagon, but a road with its points.
# Before it was not published at all, because «fewer than two hexagons».
home_faces = hexmap.sections_map().get((9, 4)) or ()
if len(home_faces) > 1:
    at_home = {"travel_pcs": its_ones, "path": [(9, 4)], "branches": [], "singles": [],
               "rendezvous": None, "plan": fake_plan(1, 0.5),
               "nodes": ((9, 4, 0), (9, 4, 1)),
               "atom_stretches": {0: [0, 18, 16]},
               "arrival_pos": home_faces[1].point}
    hexmap._trace_from_plan(at_home)
    home = hexmap._TRACES.get(WINDOW)
    results.append(("a journey inside the hexagon is published, with its points",
                  home is not None and len(home["stretches"]) == 1
                  and len(home["stretches"][0]) >= 3))
    results.append(("and they are the points this window draws",
                  home is not None and home["stretches"][0] == [
                      (round(x, 1), round(y, 1)) for x, y in hexmap._polyline(
                          [(9, 4)], size, origin, orient,
                          hexmap._shores_of(at_home))]))
    hexmap._trace_from_plan(mine)

# The branches of a group journey travel with the common road.
mine["branches"] = [[(8, 4), (9, 4)], [(9, 6), (9, 5), (9, 4)]]
mine["rendezvous"] = types.SimpleNamespace(point=(9, 4))
hexmap._trace_from_plan(mine)
with_branches = hexmap._TRACES[WINDOW]
results.append(("a group journey sends the branches too",
              len(with_branches["stretches"]) == 3))
results.append(("with the meeting the label says only the days",
              with_branches["labels"] == ["3 days", "", ""]))

# Each on their own: one arrow each, with their name and their days.
mine.update(branches=[], rendezvous=None, singles=[
    {"name": "Aldric", "path": [(9, 4), (10, 4)], "plan": fake_plan(2, 4)},
    {"name": "Dagny", "path": [(9, 6), (9, 5)], "plan": fake_plan(5, 9)}])
hexmap._trace_from_plan(mine)
separate = hexmap._TRACES[WINDOW]
results.append(("leaving scattered one arrow each is sent",
              len(separate["stretches"]) == 2))
results.append(("each with its name and its days",
              separate["labels"] == ["Aldric · 4 act · 2 days",
                                        "Dagny · 9 act · 5 days"]))

# --- 8. a route on the water is published as the junctions it passes -----
# The land plan is a row of hexes turned into a polyline; a water route
# already is one — its points are the junctions the boat passes — and it was
# not published at all: whoever watched saw nothing while a boat was steered.
boat = next((v for v in A.list_stable(C) if v.get("hex_col") is not None), None)
route_mine = {"travel_pcs": [], "travel_vehicle": boat["id"] if boat else "no-boat",
              "by_river": True,
              "route": {"points": [(100.0, 200.0), (130.5, 210.36), (160.0, 240.0)]},
              "path": [(9, 4), (10, 4)], "branches": [], "singles": [], "rendezvous": None,
              "plan": fake_plan(2, 3)}
hexmap._TRACES.clear()
hexmap._trace_from_plan(route_mine)
by_water = hexmap._TRACES.get(WINDOW)
results.append(("a water route is published as the junctions it passes",
              by_water is not None
              and by_water["stretches"][0] == [(100.0, 200.0), (130.5, 210.4), (160.0, 240.0)]))
results.append(("with the route's days on it",
              by_water is not None and by_water["labels"][0] == "3 act · 2 days"))
results.append(("and the boat among those the arrow is about",
              by_water is not None and boat is not None and boat["id"] in by_water["pc"]))
if boat is not None:
    sees_boat = view_mod.MapView(player, STATE).can_see(int(boat["hex_col"]), int(boat["hex_row"]))
    results.append(("the player sees the boat's arrow exactly when they see its hex",
                  ("finta-giocatore" in hexmap._trace_audience([boat["id"]])) == sees_boat))
    results.append(("and the GM always",
                  "finta-gm" in hexmap._trace_audience([boat["id"]])))
hexmap._TRACES.clear()

# Applied or cancelled: it vanishes.
mine.update(path=[], branches=[], singles=[], plan=None)
hexmap._trace_from_plan(mine)
results.append(("when the journey departs the arrow vanishes",
              WINDOW not in hexmap._TRACES))

# --- 8. the arrow of a closed window is not left hanging ------------------
hexmap._trace_from_plan({"travel_pcs": its_ones, "path": [(9, 4), (10, 4)],
                           "branches": [], "singles": [], "rendezvous": None,
                           "plan": fake_plan(3, 7)})
results.append(("meanwhile it is there", WINDOW in hexmap._TRACES))
Client.instances.pop(WINDOW, None)
hexmap._send_traces()
results.append(("the window closed, its arrow vanishes",
              WINDOW not in hexmap._TRACES))

for key in ("finta-gm", "finta-giocatore", "finta-altrove"):
    theme._WINDOWS.pop(key, None)
hexmap._TRACES.clear()

width = max(len(n) for n, _ in results)
for name, ok in results:
    print(("  ok  " if ok else " NO   ") + name.ljust(width))
print(f"\n{sum(1 for _, ok in results if ok)}/{len(results)} passed")
