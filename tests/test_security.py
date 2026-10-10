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

# --- 11. a player's page talks to the host and to nobody else -------------
# The typefaces used to come from Google Fonts: every player's browser told
# Google its address on every page. Now they are served by the app, and the
# stylesheet must name no outside host at all.
results.append(("the stylesheet fetches nothing from outside",
                "http://" not in theme.CSS and "https://" not in theme.CSS
                and "@import" not in theme.CSS))
fonts = theme.STATIC_DIR / "fonts"
named = {f"{stem}-{subset}.woff2" for stem in ("cinzel", "ibm-plex-sans", "press-start-2p")
         for subset in ("latin", "latin-ext")}
results.append(("every font the stylesheet names is shipped",
                all((fonts / name).is_file() for name in named)
                and all(name in theme.CSS for name in named)))
results.append(("the fonts' licences travel with them",
                len(list(fonts.glob("OFL-*.txt"))) == 3))
results.append(("the fonts reach the login page before anyone signs in",
                login._is_free("/_km/fonts/cinzel-latin.woff2")
                and login._is_free("/name/device-0/_km/fonts/cinzel-latin.woff2", "/name/device-0")
                and not login._is_free("/_km/")))

# --- the brakes everyone shares, the line when a name's trips, weak passwords
import time  # noqa: E402
auth._failures.clear()
quiet = auth.remaining_wait("someone")
auth._failures.extend([time.monotonic()] * auth.GLOBAL_MAX)
results.append(("past GLOBAL_MAX failures from everyone, everyone waits",
                quiet == 0 and auth.global_wait() > 0 and auth.remaining_wait("someone") > 0))
auth._failures.clear()
results.append(("and the wait clears with the failures", auth.remaining_wait("someone") == 0))
noted = []
hook_before = auth.on_abuse
auth.on_abuse = lambda name, how_many: noted.append((name, how_many))
auth._attempts.pop("tripwire", None)
for _ in range(auth.MAX_ATTEMPTS):
    auth.verify(A, "tripwire", "wrong-password-1")
results.append(("the hook fires once, when a name's brake trips",
                noted == [("tripwire", auth.MAX_ATTEMPTS)]))
results.append(("the login page wires that hook to the journal", hook_before is login._abuse_noted))
auth.on_abuse = hook_before
auth._attempts.pop("tripwire", None)
auth._failures.clear()
for password, why in (("password1", "a common"), ("Password123", "a common, whatever the case"),
                      ("tmpuser1", "the username as"), ("tmpuser", "the username as")):
    try:
        auth.check_password(password, "tmpuser")
        refused = False
    except ValueError:
        refused = True
    results.append((f"{why} password is refused", refused))
try:
    auth.check_password("prova-tmp-9876", "tmpuser")
    passes = True
except ValueError:
    passes = False
results.append(("an ordinary password passes", passes))
results.append(("the list of common passwords is there and long enough to matter",
                len(auth.common_passwords()) >= 200 and "password" in auth.common_passwords()))

# --- the pairing code: once, three tries, ten minutes
from kingmaker.access import pairing  # noqa: E402
now = [1000.0]
pairing.clock = lambda: now[0]
code = pairing.new_code("admin")
results.append(("a code is two groups of four, from the readable alphabet",
                len(code) == 9 and code[4] == "-" and pairing.active() is not None
                and pairing.active()["made_by"] == "admin"))
results.append(("a wrong code does not pair", not pairing.check("zzzz-zzzz")))
results.append(("the right code pairs once, however typed",
                pairing.check(code.upper().replace("-", " ")) and not pairing.check(code)))
code = pairing.new_code("admin")
tries = [pairing.check("zzzz-zzzz") for _ in range(pairing.ATTEMPTS)]
results.append(("the third wrong try kills the code", not any(tries) and pairing.active() is None
                and not pairing.check(code)))
code = pairing.new_code("admin")
now[0] += pairing.LIFETIME + 1
results.append(("a code dies after ten minutes", pairing.active() is None and not pairing.check(code)))
results.append(("a new code retires the old one",
                (lambda a, b: not pairing.check(a) and pairing.check(b))(pairing.new_code("admin"),
                                                                           pairing.new_code("admin"))))
pairing.clock = time.monotonic
pairing.forget()
results.append(("making a code is the administrator's",
                permissions.MIN_ROLE[permissions.MANAGE_USERS] == permissions.ADMIN
                and not hasattr(permissions, "HOST_GAME")))


# ------------------------------------------------- the second factor (2.0.0)
from kingmaker.access import totp  # noqa: E402

gm_row = A.user_by_name("gm")
secret = totp.new_secret()
codes = totp.new_recovery_codes()
auth.enable_second_factor(A, gm_row["id"], secret, codes)
with_sf = auth.verify(A, "gm", "prova-gm-1234")
results.append(("the password alone still verifies, and the user says a second step is asked",
                with_sf is not None and with_sf.second_factor))
results.append(("the secret is kept base32 and the recovery codes only as hashes",
                A.user_by_id(gm_row["id"])["totp_secret"] == "".join(totp.encode_secret(secret).split())
                and codes[0] not in (A.user_by_id(gm_row["id"])["recovery_codes"] or "")))
results.append(("the current code passes", auth.second_factor_ok(A, gm_row["id"], totp.code_now(secret))))
results.append(("a wrong code does not", not auth.second_factor_ok(A, gm_row["id"], "000000")
                if totp.code_now(secret) != "000000" else True))
results.append(("a recovery code passes once and is spent",
                auth.second_factor_ok(A, gm_row["id"], codes[0].upper())
                and not auth.second_factor_ok(A, gm_row["id"], codes[0])
                and auth.recovery_codes_left(A, gm_row["id"]) == len(codes) - 1))
for _ in range(auth.MAX_ATTEMPTS):
    auth.second_factor_ok(A, gm_row["id"], "111111")
results.append(("wrong codes trip the same brake as wrong passwords",
                auth.remaining_wait("gm") > 0 and not auth.second_factor_ok(A, gm_row["id"], totp.code_now(secret))))
auth._attempts.clear()
auth.disable_second_factor(A, gm_row["id"], by="admin")
results.append(("cleared, the account asks no code and any code passes",
                not auth.verify(A, "gm", "prova-gm-1234").second_factor
                and auth.second_factor_ok(A, gm_row["id"], "whatever")))
results.append(("an account without a second factor passes without a code",
                auth.second_factor_ok(A, A.user_by_name("admin")["id"], "")))

for name, ok in results:
    print(f" {'ok' if ok else 'NO'}  {name}")
print(f"\n{sum(1 for _n, e in results if e)}/{len(results)} passed")
