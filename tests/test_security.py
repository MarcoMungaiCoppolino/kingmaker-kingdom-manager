# -*- coding: utf-8 -*-
"""The security defects closed before 1.0: each with its own test."""
import types

from kingmaker.access import auth, permissions
from kingmaker import config
from kingmaker.state import STATE
from kingmaker.ui import login, hexmap, theme
from kingmaker.ui.tabs import sheet, turn
from kingmaker.ui.hexmap import drawing, ruler
import helpers

theme.notify = lambda *a, **k: None
theme.mark_dirty = lambda *a, **k: None
theme.refresh_panels = lambda *a, **k: None
theme.refresh_ui = lambda *a, **k: None
# The redrawable panels have no page underneath, here: the refresh is a no-op.
from nicegui.functions import refreshable as _refreshable
_refreshable.refreshable.refresh = lambda self, *a, **k: None
helpers.silence("_redraw_travel")
helpers.silence("_send_field")

A, C = STATE.archive, STATE.campaign
results = []
real_user = theme.user          # before the tests replace it
from kingmaker.ui.hexmap import hex_panel
rows = {u["username"]: u for u in A.list_users()}
ADMIN = auth._from_row(rows["admin"])
GM = auth._from_row(rows["gm"])
PLAYER = auth._from_row(rows["player"])
SPECTATOR = auth.User(id="spett", username="spett", role=permissions.SPECTATOR,
                         active=True, must_change_pw=False)


def how(user):
    theme.user = lambda: user


# --- 1. the spectator only watches ----------------------------------------
level_before = STATE.k["level"]
how(SPECTATOR)
sheet._set_level(level_before + 3)
results.append(("a spectator does not change the kingdom's level",
              STATE.k["level"] == level_before))
turn_before = STATE.k["turn"]
turn._move_turn(1)
results.append(("nor the turn", STATE.k["turn"] == turn_before))
state_before = STATE.hex(3, 3)["status"]
hex_panel._set_field(hexagon_33 := STATE.hex(3, 3), "status", "claimed")
results.append(("nor a hexagon", hexagon_33["status"] == state_before))
how(PLAYER)
sheet._set_level(level_before + 3)
results.append(("a player instead does", STATE.k["level"] == level_before + 3))
sheet._set_level(level_before)
STATE.k["turn"] = turn_before

# --- 2. the resources defect: _set with three arguments -------------------
rp_before = STATE.k["rp"]
sheet._set_in(STATE.k, "rp", rp_before + 7)
results.append(("the resource boxes really write (it was a TypeError)",
              STATE.k["rp"] == rp_before + 7))
STATE.k["rp"] = rp_before

# --- 3. the GM's actions stay the GM's ------------------------------------
how(PLAYER)
before = A.campaign_borders(C)
hex_panel._change_border(3, 3, (4, 3), "water", lambda: None)
results.append(("a player does not mark water borders",
              A.campaign_borders(C) == before))
how(GM)
hex_panel._change_border(3, 3, (4, 3), "water", lambda: None)
results.append(("the GM does", A.campaign_borders(C) != before))
A.set_border(C, (3, 3), (4, 3), None)

# --- 4. usernames: identifiers, not text ----------------------------------
try:
    auth.create_user(A, "<img src=x>", "password-lunga-1", role=permissions.PLAYER)
    results.append(("a username with markup is refused", False))
except ValueError:
    results.append(("a username with markup is refused", True))

# --- 5. somebody else's password -----------------------------------------
try:
    auth.change_password(A, rows["gm"]["id"], "nuova-password-1", from_=PLAYER)
    results.append(("a player does not change the GM's password", False))
except ValueError:
    results.append(("a player does not change the GM's password", True))
results.append(("the GM still verifies their own",
              auth.verify(A, "gm", "prova-gm-1234") is not None))

# --- 6. the last administrator stays -------------------------------------
how(ADMIN)
login.users_panel = types.SimpleNamespace(refresh=lambda: None)
login._change_role(GM.id, permissions.ADMIN)
login._change_role(GM.id, permissions.GM)
results.append(("naming and then removing a second admin is fine",
              A.user_by_id(GM.id)["role"] == permissions.GM))
login._change_active(ADMIN.id, False)
results.append(("the last active administrator is not switched off",
              bool(A.user_by_id(ADMIN.id)["active"])))
login._change_role(ADMIN.id, permissions.PLAYER)
results.append(("and does not demote themselves",
              A.user_by_id(ADMIN.id)["role"] == permissions.ADMIN))

# --- 7. the window's identity is refreshed --------------------------------
theme._WINDOWS["fake_one"] = {"user": PLAYER, "user_rev": A.rev}
theme._window = lambda: "fake_one"
theme._kick_out = lambda cid: None
results.append(("as long as nobody writes, the snapshot holds", real_user() is PLAYER))
A.update_user(PLAYER.id, role=permissions.SPECTATOR)
results.append(("after a change of role the window sees it",
              real_user().role == permissions.SPECTATOR))
A.update_user(PLAYER.id, role=permissions.PLAYER, active=0)
results.append(("a switched-off account vanishes from the window", real_user() is None))
A.update_user(PLAYER.id, active=1)

# --- 8. the brake by address, depending on where it runs ------------------
fake = types.SimpleNamespace(ip="10.0.0.9",
                              request=types.SimpleNamespace(headers={"x-forwarded-for": "1.2.3.4, 10.0.0.1"}))
config.TRUST_PROXY, config.ON_AIR = False, False
results.append(("at home the client's address counts", auth.client_ip(fake) == "10.0.0.9"))
config.TRUST_PROXY = True
results.append(("behind a trusted proxy the first hop counts", auth.client_ip(fake) == "1.2.3.4"))
config.TRUST_PROXY, config.ON_AIR = False, True
results.append(("under On Air the brake by address switches off", auth.client_ip(fake) is None))
config.ON_AIR = False
auth._attempts.clear()
for _i in range(auth.MAX_ATTEMPTS + 2):
    auth.verify(A, "gm", "sbagliata", "9.9.9.9")
results.append(("hammering a name does not lock the address for everybody",
              auth.remaining_wait("admin", "9.9.9.9") == 0
              and auth.remaining_wait("gm", "9.9.9.9") > 0))
auth._attempts.clear()

# --- 9. the ruler does not make the server walk a million cells -----------
calls = []
helpers.silence("_compute_journey", lambda *a, **k: calls.append((a, k)))
theme.user = lambda: PLAYER
permissions.can = lambda *a, **k: True
mine = {"travel_mode": "choose", "travel_pcs": []}
huge = [[1, 1]] * (ruler.MAX_TRACE_POINTS + 1)
ruler._dragged_target(mine, None, {"path": huge})
results.append(("a path too long stops at the door", not calls))
ruler._dragged_target(mine, None, {"path": [[1, 1], [999, 999]]})
results.append(("and one outside the map too", not calls))
ruler._dragged_target(mine, None, {"path": [[3, 3], [4, 3]]})
results.append(("a good one passes", len(calls) == 1))

# --- 10. the escapes -----------------------------------------------------
results.append(("the server's SVG escapes the quotes too",
              drawing._esc('a"b<c') == "a&quot;b&lt;c"))
js = open("kingmaker/ui/static/travel_drag.js", encoding="utf-8").read()
results.append(("the label in the browser goes through the escape",
              "const esc = " in js and "${esc(text)}</text>" in js))

for name, ok in results:
    print(f" {'ok' if ok else 'NO'}  {name}")
print(f"\n{sum(1 for _n, e in results if e)}/{len(results)} passed")
