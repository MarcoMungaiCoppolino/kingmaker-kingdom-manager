"""Hand-written addresses must hold when publishing with On Air too.

On Air does not publish the app at the root of the domain: the address is
`https://.../<name>/device-0/`, and that piece reaches the app in the
`X-Forwarded-Prefix` header. NiceGUI adds it by itself to the addresses of
*its* elements (`ui.image`, `ui.interactive_image`: it does so in the browser
with `window.path_prefix`), but not to those we write inside the map's SVG.
And that is where a character's marker lives.
"""
import types

from kingmaker.access import auth, view as view_mod
from kingmaker.state import STATE
from kingmaker.ui import hexmap, theme

results = []
A, C = STATE.archive, STATE.campaign
m = STATE.k["map"]
size = float(m["size"])
origin = (float(m["origin_x"]), float(m["origin_y"]))
orient = m["orientation"]

PREFIX = "/marcomungaicoppolino/device-0"


def fake_request(prefix: str):
    return types.SimpleNamespace(headers={"X-Forwarded-Prefix": prefix},
                                 scope={"root_path": ""})


# --- 1. the prefix is read from the request and stays on the window ------
theme.window_state().pop("prefix", None)
results.append(("without a prefix the address does not change",
              theme.with_prefix("/assets/x.png") == "/assets/x.png"))
theme.set_prefix(fake_request(PREFIX))
results.append(("with a prefix the address carries it in front",
              theme.with_prefix("/assets/x.png")
              == PREFIX + "/assets/x.png"))
results.append(("an already relative address is not touched",
              theme.with_prefix("assets/x.png") == "assets/x.png"))
theme.set_prefix(fake_request(PREFIX + "/"))
results.append(("the trailing slash is not doubled",
              theme.with_prefix("/assets/x.png")
              == PREFIX + "/assets/x.png"))
theme.set_prefix(None)
results.append(("without a request it does not blow up",
              theme.with_prefix("/assets/x.png")
              == PREFIX + "/assets/x.png"))

# --- 2. the marker inside the SVG carries it ----------------------------
gm = next(auth.User(id=u["id"], username=u["username"], role=u["role"],
                      active=True, must_change_pw=False)
          for u in A.list_users() if u["role"] in ("gm", "admin"))
theme.user = lambda: gm
with_token = [p for p in A.list_characters(C)
             if p.get("token") and p["hex_col"] is not None]
# Whoever travels on a placed vehicle has no badge of their own — they are
# drawn inside the vehicle's — and this test looks precisely at the badges.
# They are made to get off, or another test that got them aboard is enough
# to make this one fail with nothing to do with the prefix.
for char in with_token:
    if char.get("stable_id"):
        A.update_character(char["id"], stable_id=None)
with_token = [p for p in A.list_characters(C)
             if p.get("token") and p["hex_col"] is not None]
results.append(("the save has a character with a marker", bool(with_token)))

view = view_mod.MapView(gm, STATE)
theme.set_prefix(fake_request(PREFIX))
drawing = "".join(hexmap._svg_markers(view, size, origin, orient, set()))
results.append(("the marker points inside the published app",
              f'href="{PREFIX}/assets/characters' in drawing))
results.append(("and not at the root of the domain",
              'href="/assets/characters' not in drawing))

theme.set_prefix(fake_request(""))
at_home = "".join(hexmap._svg_markers(view, size, origin, orient, set()))
results.append(("at home the usual address remains",
              'href="/assets/characters' in at_home))

# --- 3. the map background instead must NOT be touched -------------------
# NiceGUI takes care of it: `ui.interactive_image` adds the prefix in the
# browser, and putting it twice would be worse than not putting it.
theme.set_prefix(fake_request(PREFIX))
source_text, _w, _h = hexmap._background()
results.append(("the map background stays without a prefix",
              source_text.startswith("/assets/")))

# --- 4. the login redirect instead does NOT carry it ---------------------
# NiceGUI takes care of it, with its `RedirectWithPrefixMiddleware`: adding
# it ourselves too wrote it twice, and whoever entered for the first time
# found «redirected you too many times». Here only that the prefix reads
# right is checked; that the redirect is bare is tested by test_onair.
results.append(("the On Air prefix is read from the request",
              theme.request_prefix(fake_request(PREFIX))
              == PREFIX))
results.append(("and at home there is nothing to read",
              theme.request_prefix(fake_request("")) == ""))

theme.window_state().pop("prefix", None)

width = max(len(n) for n, _ in results)
for name, ok in results:
    print(("  ok  " if ok else " NO   ") + name.ljust(width))
print(f"\n{sum(1 for _, ok in results if ok)}/{len(results)} passed")
