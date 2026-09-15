"""On Air: whoever arrives for the first time must be able to get in.

The real case: from the public address, whoever had never entered found
«redirected you too many times». Whoever was already inside saw nothing odd —
with the session in their pocket that redirect never fires, and that is why
the defect stayed hidden: only those who could not get around it found it.

The cause: NiceGUI already has a `RedirectWithPrefixMiddleware` that adds
`X-Forwarded-Prefix` to every `Location`. Our redirect added it as well, and
the prefix ended up written twice.
"""
from nicegui.middlewares import RedirectWithPrefixMiddleware

from kingmaker.ui import login, theme

results = []
PREFIX = "/marcomungaicoppolino/device-0"


class Request:
    """That little of a request the prefix looks at."""

    def __init__(self, header=None, root_path=None):
        self.headers = {}
        if header is not None:
            self.headers["X-Forwarded-Prefix"] = header
        self.scope = {}
        if root_path is not None:
            self.scope["root_path"] = root_path


def after_nicegui(spot: str, prefix: str) -> str:
    """The `Location` as it really comes out, after NiceGUI's middleware.

    It is the same line as `nicegui/middlewares.py`: if the redirect starts
    with «/», the prefix is put there by it. Copying it here is the only way
    to test the piece that is not ours without bringing up a server.
    """
    return prefix + spot if spot.startswith("/") else spot


results.append(("NiceGUI's middleware is still the one adding the prefix",
              "X-Forwarded-Prefix" in
              RedirectWithPrefixMiddleware.dispatch.__code__.co_consts.__str__()))

# --- 1. the redirect we send ---------------------------------------------
# Bare: the prefix is none of our business, and putting it was the defect.
results.append(("the redirect we write is bare",
              login.OPEN_PAGES and "/login" in login.OPEN_PAGES))
outside = after_nicegui("/login", PREFIX)
results.append(("going through NiceGUI it becomes the right one",
              outside == PREFIX + "/login"))
results.append(("with device-0 written once only",
              outside.count("device-0") == 1))
results.append(("and at home, without a prefix, it stays /login",
              after_nicegui("/login", "") == "/login"))

# The earlier defect, redone: adding it ourselves too was enough.
before = after_nicegui(PREFIX + "/login", PREFIX)
results.append(("putting it ourselves too it came out doubled — the endless loop",
              before.count("device-0") == 2))

# --- 2. the login page is free -------------------------------------------
results.append(("/login is free", login._is_free("/login")))
results.append(("the root is not", not login._is_free("/")))
results.append(("NiceGUI's files are free, or the page arrives bare",
              login._is_free("/_nicegui/3.16.0/static/nicegui.js")
              and login._is_free("/_nicegui_ws/socket.io/")))
results.append(("the assets are not: it is the mount the filter must cover",
              not login._is_free("/assets/mappa.jpg")))
# The relay delivers the path already without the prefix, but behind a
# reverse proxy the root_path stays attached: it is removed before looking.
results.append(("and with the prefixed path /login stays free all the same",
              login._is_free(PREFIX + "/login", PREFIX)))
results.append(("while the prefixed root does not",
              not login._is_free(PREFIX + "/", PREFIX)))

# --- 3. the prefix is read once only -------------------------------------
read = theme.request_prefix
results.append(("at home there is no prefix", read(Request()) == ""))
results.append(("with the header alone that one counts — and it is the On Air case",
              read(Request(header=PREFIX)) == PREFIX))
results.append(("with the root_path alone that one counts",
              read(Request(root_path=PREFIX)) == PREFIX))
results.append(("when they say the same thing it is counted once only",
              read(Request(PREFIX, PREFIX)) == PREFIX))
results.append(("the trailing slash makes no difference",
              read(Request(PREFIX + "/", PREFIX)) == PREFIX))
results.append(("if one contains the other the longer wins",
              read(Request("/device-0", "/nome/device-0")) == "/nome/device-0"
              and read(Request("/nome/device-0", "/device-0"))
              == "/nome/device-0"))
results.append(("two different pieces still add up",
              read(Request("/fuori", "/dentro")) == "/fuori/dentro"))
results.append(("and without a request nothing is made up", read(None) == ""))

width = max(len(n) for n, _ in results)
for name, ok in results:
    print(("  ok  " if ok else " NO   ") + name.ljust(width))
print("")
print(str(sum(1 for _, ok in results if ok)) + "/" + str(len(results)) + " passate")
