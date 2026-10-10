# -*- coding: utf-8 -*-
"""Eight windows, random changes, and every visible panel checked against a
fresh render of itself.

The refresh bus decides which panels to redo after a change and in which
windows; a targeted list (`theme.stat_panels`) says which panels a figure
reaches. Either can be wrong in a way no unit test sees: a panel that reads
a figure nobody listed keeps its old number, silently, on some windows. So
here the interface is really built — NiceGUI's own user simulation, no
browser — for eight windows with three accounts on random tabs, a random
sequence of the changes made at the table is played from random windows,
and after each one every panel in front of somebody is compared with what
drawing it from scratch would give. A difference is a stale screen.
"""
import asyncio
import faulthandler
import os
import random
import re
import sys
import traceback

os.environ["NICEGUI_USER_SIMULATION"] = "true"

import httpx  # noqa: E402
from nicegui import Client, core, ui  # noqa: E402
from nicegui.testing.general import prepare_simulation  # noqa: E402
from nicegui.testing.user import User  # noqa: E402

# A stuck run dumps every stack and ends before run_all's 300 s, so the report
# says where it stuck instead of «no end».
faulthandler.dump_traceback_later(240, exit=True)

prepare_simulation()
from kingmaker import main, rules  # noqa: E402,F401
from kingmaker.access import auth  # noqa: E402
from kingmaker.state import STATE  # noqa: E402
from kingmaker.ui import theme  # noqa: E402
from kingmaker.ui.tabs import sheet, turn  # noqa: E402

results = []
random.seed(int(os.environ.get("KM_SEED", "7")))
ROUNDS = int(os.environ.get("KM_ROUNDS", "100"))
WINDOWS = int(os.environ.get("KM_WINDOWS", "8"))

accounts = {u["username"]: u for u in STATE.archive.list_users()}
_session = {"id": accounts["admin"]["id"]}
auth.id_in_session = lambda: _session["id"]
ui.run(storage_secret="simulated secret", reload=False, show=False)

TABS = ["map", "kingdom", "turn", "city", "party", "transport"]


# ------------------------------------------------------------ the snapshot
def snapshot(element) -> dict:
    """An element and its subtree, without the identifiers that differ
    between two renders of the same thing."""
    data = element._to_dict()
    out = {key: data.get(key) for key in ("tag", "class", "style", "text")}
    # a prop that names another element (a tooltip's target, a label's `for`)
    # differs between two renders by construction: masked
    out["props"] = {k: ("<id>" if isinstance(v, str)
                        and (re.fullmatch(r"#?c\d+", v) or "/_nicegui/" in v) else v)
                    for k, v in (data.get("props") or {}).items()}
    out["events"] = sorted((e.get("type", ""), str(e.get("args")), str(e.get("js_handler")))
                           for e in data.get("events", []))
    out["slots"] = {name: [snapshot(c) for c in slot.children]
                    for name, slot in element.slots.items()}
    return out


def first_difference(a, b, path="") -> str | None:
    if type(a) is not type(b):
        return f"{path}: {type(a).__name__} vs {type(b).__name__}"
    if isinstance(a, dict):
        for key in sorted(set(a) | set(b)):
            if key not in a or key not in b:
                return f"{path}/{key}: missing on one side"
            found = first_difference(a[key], b[key], f"{path}/{key}")
            if found:
                return found
        return None
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{path}: {len(a)} vs {len(b)} children"
        for i, (x, y) in enumerate(zip(a, b)):
            found = first_difference(x, y, f"{path}[{i}]")
            if found:
                return found
        return None
    return None if a == b else f"{path}: {str(a)[:60]!r} vs {str(b)[:60]!r}"


def fresh_render(ref, target) -> list:
    """The panel drawn again from scratch in the same window, then thrown away."""
    client = target.container.client
    with client:
        box = ui.element("div")
    with box:
        ref.func(*target.args, **target.kwargs)
    snap = [snapshot(c) for c in box.default_slot.children]
    box.delete()
    return snap


def visible_targets(cid: str):
    tab = theme._WINDOWS.get(cid, {}).get("tab")
    for owner in (theme._GLOBAL, cid):
        for name, ref in theme._REFRESH.get(owner, {}).items():
            if owner != theme._GLOBAL and not theme._visible(name, tab):
                continue
            for target in getattr(ref, "targets", []) or []:
                if theme._window_of(target) != cid or target.container.is_deleted:
                    continue
                if owner == theme._GLOBAL and not theme.target_in_front(target, tab):
                    continue
                yield name, ref, target


def check_window(cid: str) -> list[str]:
    problems = []
    for name, ref, target in visible_targets(cid):
        if name in theme._DIRTY.get(cid, ()) and name.split(".")[0] in theme._TABS:
            problems.append(f"{name} in front but owed")
        live = [snapshot(c) for c in target.container.default_slot.children]
        found = first_difference(live, fresh_render(ref, target))
        if found:
            problems.append(f"{name}: {found}")
    return problems


# ------------------------------------------------------------- the changes
def random_effect_rows() -> list[dict]:
    """The rows the outcome dialog would build for a random activity outcome."""
    for _ in range(50):
        act = random.choice(rules.ACTIVITIES)
        grade = random.choice(list((act.get("effects") or {}).keys()) or [None])
        entries = [v for v in (act.get("effects") or {}).get(grade, []) if v["t"] != "note"]
        if entries:
            break
    else:
        return []
    rows = []
    for v in entries:
        value = v["v"] if v["t"] == "mod" else rules.signed_value(v.get("q", "0"))[0]
        target = None
        kind = rules.entry_target(v)
        if kind:
            target = {"ruin": rules.RUINS, "skill": rules.SKILLS}.get(kind, rules.COMMODITIES)[0]["id"]
        rows.append({"entry": v, "active": True, "valore": value, "target": target})
    return rows


SKILLS = list(rules.BY_ID["skills"])
PROFICIENCIES = [c["id"] for c in rules.PROFICIENCIES]
ABILITIES = [c["id"] for c in rules.ABILITIES]
ROLES = [r["id"] for r in rules.ROLES]
FEATS = [f["id"] for f in rules.FEATS]
CHARACTERS = [p["id"] for p in STATE.characters()]


def move_marker() -> None:
    """What boarding, landing and placing do after moving somebody: the
    positions changed, the marker panels are redrawn, nothing else."""
    from kingmaker.ui.hexmap import travel as travel_ui
    who = random.choice(STATE.characters())
    STATE.archive.update_character(who["id"], hex_col=random.randint(3, 8),
                                   hex_row=random.randint(3, 8), pos_x=None, pos_y=None)
    STATE.record("moved for the test", "map")
    theme.save_and_refresh_panels(travel_ui._MARKER_PANELS)


def change_calendar() -> None:
    """The campaign's calendar switched, as the GM's editor does: the bar's
    date and the turn's days must follow everywhere."""
    from kingmaker.rules import almanac
    from kingmaker.ui.tabs import clock
    custom = almanac.Calendar(name="Test", era="TE",
                              months=(almanac.Month("Primo", 30), almanac.Month("Secondo", 28)))
    calendar = random.choice([almanac.GOLARION, custom])
    today = clock.data()
    clock.save_calendar(calendar, calendar.date(today.year, today.month, today.day))
    theme.save_and_refresh()


def changes() -> list:
    ruins = list(STATE.k["ruins"])
    goods = list(STATE.k["commodities"])
    return [
        ("roll", lambda: sheet.roll_skill(random.choice(SKILLS), random.randint(10, 30))),
        ("rp +1", lambda: turn._adjust("rp|1")),
        ("rp -1", lambda: turn._adjust("rp|-1")),
        ("unrest +1", lambda: turn._adjust("unrest|1")),
        ("unrest -1", lambda: turn._adjust("unrest|-1")),
        ("xp +10", lambda: turn._adjust("xp|10")),
        ("fame +1", lambda: turn._adjust("fame_points|1")),
        ("ruin +1", lambda: turn._adjust(f"ruin.{random.choice(ruins)}|1")),
        ("commodity +1", lambda: turn._adjust(f"com.{random.choice(goods)}|1")),
        ("outcome effects", lambda: turn._apply_rows(random_effect_rows(), "test")),
        ("unrest via the step", lambda: turn._add_unrest(1)),
        ("xp via the step", lambda: turn._xp(10)),
        ("everything", theme.save_and_refresh),
        ("a bad key", lambda: turn._adjust("rp|nope")),
        ("a foreign key", lambda: turn._adjust("com.gold|1")),
        # the sheet: its setters, and the keys its blocks send from the browser
        ("proficiency", lambda: sheet._skill_change([f"prof.{random.choice(SKILLS)}",
                                                     random.choice(PROFICIENCIES)])),
        ("skill roll by key", lambda: sheet._skill_click(f"roll.{random.choice(SKILLS)}")),
        ("ability", lambda: sheet._set_ability(random.choice(ABILITIES), random.randint(8, 18))),
        ("ruin threshold", lambda: sheet._set_ruin(random.choice(ruins), "threshold", random.randint(5, 12))),
        ("role pc", lambda: sheet._role_click(f"pc.{random.choice(ROLES)}")),
        ("role invested", lambda: sheet._role_click(f"inv.{random.choice(ROLES)}")),
        ("role vacant", lambda: sheet._role_click(f"abs.{random.choice(ROLES)}")),
        ("role character", lambda: sheet._role_change([f"char.{random.choice(ROLES)}",
                                                       random.choice(CHARACTERS + [""])])),
        ("role name", lambda: sheet._role_change([f"name.{random.choice(ROLES)}",
                                                  random.choice(["Ser Bob", "", "Lady Ann"])])),
        ("feat", lambda: sheet._feat_click(f"feat.{random.choice(FEATS)}")),
        ("level", lambda: sheet._set_level(random.randint(1, 6))),
        ("rp typed", lambda: sheet._set_in(STATE.k, "rp", random.randint(0, 40))),
        ("commodity typed", lambda: sheet._set_commodity(random.choice(goods), random.randint(0, 4))),
        ("turn", lambda: turn._move_turn(random.choice([-1, 1]))),
        ("a marker moved", lambda: move_marker()),
        ("calendar", lambda: change_calendar()),
        ("a foreign feat", lambda: sheet._feat_click("feat.nope")),
        ("a foreign role", lambda: sheet._role_change(["char.nope", "x"])),
    ]


async def drain() -> None:
    for _ in range(500):
        await asyncio.sleep(0)
        if theme.redraws_idle():
            break
    await asyncio.sleep(0.02)
    for _ in range(50):
        if theme.redraws_idle():
            break
        await asyncio.sleep(0)


async def close_everything() -> None:
    """Every window still open, closed, whatever happened in the run, and a
    moment for its outbox loop to see the stop and end.

    A window's outbox loop waits with `asyncio.wait_for`, which on Python 3.10
    and 3.11 can lose a cancellation landing at the wrong moment: left to
    asyncio's cancellation at exit, one loop could keep the process alive
    forever. Closing the windows first ends the loops on their own. A run that
    raised half-way used to skip that, and hung instead of saying what went
    wrong — under load, as on the CI's runner, that was the first run."""
    for client in list(Client.instances.values()):
        try:
            client.delete()
        except Exception:                      # noqa: BLE001 — the others still close
            print(f"    closing window {client.id} raised:", file=sys.stderr)
            traceback.print_exc()
    alive: list[str] = []
    for _ in range(40):
        await asyncio.sleep(0.05)
        alive = [t.get_name() for t in asyncio.all_tasks() if t.get_name().startswith("outbox loop")]
        if not alive:
            return
    print("    outbox loops still running: " + ", ".join(alive), file=sys.stderr)


async def play() -> None:
    users = []
    who = ["admin", "gm", "player"]
    for i in range(WINDOWS):
        name = who[i % len(who)]
        _session["id"] = accounts[name]["id"]
        u = User(httpx.AsyncClient(transport=httpx.ASGITransport(core.app), base_url="http://test"))
        await u.open("/")
        with u.client:
            theme.active_tab(random.choice(TABS))
        users.append((name, u))
    await drain()

    mismatches = []
    owed = []
    errors = []
    counts = {}
    rebuilds = {"n": 0}
    real_rebuild = theme._rebuild

    def counting(ref, target):
        rebuilds["n"] += 1
        return real_rebuild(ref, target)
    theme._rebuild = counting
    menu = changes()
    for round_ in range(ROUNDS):
        kind, action = random.choice(menu)
        name, actor = random.choice([w for w in users if w[0] != "player" or True])
        counts[kind] = counts.get(kind, 0) + 1
        try:
            with actor.client:
                action()
        except Exception as error:      # noqa: BLE001 — the report says which
            errors.append(f"{kind} from {name}: {error!r}")
        if random.random() < 0.3:        # somebody changes tab
            _n, other = random.choice(users)
            with other.client:
                theme.active_tab(random.choice(TABS))
        await drain()
        for _n, u in users:
            for problem in check_window(u.client.id):
                (owed if "owed" in problem else mismatches).append(
                    f"after {kind} (round {round_}): {problem}")
        if len(mismatches) > 12:
            break

    results.append((f"{ROUNDS} random changes from {WINDOWS} windows: every panel in front "
                    "equals a fresh render", not mismatches))
    results.append(("no panel in front is left owed", not owed))
    results.append(("no change raised", not errors))
    results.append(("the menu was really exercised",
                    len(counts) >= len(menu) * 2 // 3))
    print(f"    {rebuilds['n']} rebuilds for {ROUNDS} changes in {WINDOWS} windows", flush=True)
    for line in (mismatches + owed + errors)[:12]:
        print("   ", line)

    # a window that leaves mid-way
    _n, gone = users.pop()
    gone.client.delete()
    # Its session's storage goes too, as NiceGUI's prune would take it ten
    # seconds later: every panel drawn from here on must not ask that session.
    # The header's user bar did — the last window opened lends its request to
    # every redraw — and under load the prune landed in the final redraw.
    # (NiceGUI's own prune, not part of its public API: a later release may move it.)
    from nicegui.app.app import prune_user_storage
    await prune_user_storage(force=True)
    with users[0][1].client:
        theme.save_and_refresh()
    await drain()
    problems = [p for _n, u in users for p in check_window(u.client.id)]
    results.append(("a window that closed is forgotten, the others stay right",
                    not problems and gone.client.id not in theme._REFRESH))



async def run() -> None:
    # The windows close inside the lifespan, so its shutdown finds the outbox
    # loops already finished. A failure is held until the lifespan has ended:
    # thrown into it, it would skip NiceGUI's shutdown (nothing wraps its
    # yield), leaving the last save and the archive's close undone.
    failure: Exception | None = None
    async with core.app.router.lifespan_context(core.app):
        try:
            await play()
        except Exception as error:          # noqa: BLE001 — raised again below
            failure = error
        finally:
            await close_everything()
    if failure is not None:
        raise failure


asyncio.run(run())
faulthandler.cancel_dump_traceback_later()

width = max(len(n) for n, _ in results)
print()
for name, ok in results:
    print(("  ok  " if ok else " NO   ") + name.ljust(width))
print(f"\n{sum(1 for _, ok in results if ok)}/{len(results)} passed")
