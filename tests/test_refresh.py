# -*- coding: utf-8 -*-
"""The refresh bus, after the evening it took four seconds per dice roll.

A shared panel (the Turn column, the Kingdom blocks) is drawn once per
window, and NiceGUI's `refresh()` rebuilds every copy at once: eight windows,
eight rebuilds, whatever tab each of them had in front. Here the bus is fed
fake panels with fake targets and asked the questions that matter: only the
windows on the tab are rebuilt, the others owe a redraw and get it when they
switch, one action means one rebuild however many times it asks, a panel
drawn inside another is not redone twice, and the panel's own `refresh()`
takes the same road.
"""
import asyncio

from kingmaker.ui import theme

results = []


class Slot:
    def __init__(self, parent):
        self.parent = parent


class Element:
    """What the bus reads of a NiceGUI element: its client, its parent, its
    deletion flag; `clear()` is what a rebuild starts with."""
    _next = 0

    def __init__(self, cid: str, parent=None, tag="div", props=None):
        Element._next += 1
        self.id = Element._next
        self.tag = tag
        self._props = props or {}
        self.client = type("C", (), {"id": cid})()
        self.parent_slot = Slot(parent) if parent is not None else None
        self.is_deleted = False
        self.cleared = 0

    def clear(self):
        self.cleared += 1


class Target:
    def __init__(self, container, args=()):
        self.container, self.args, self.kwargs, self.instance = container, args, {}, None

    def run(self, func):
        return func(*self.args, **self.kwargs)


class Panel:
    """A refreshable as the bus sees it: `targets`, `func`, `prune`, `refresh`."""

    def __init__(self, name):
        self.name = name
        self.targets = []
        self.rebuilt = []            # window ids, in order
        self.whole = 0               # NiceGUI's own refresh(), everything at once
        self.func = self._draw

    def _draw(self, *args):
        pass

    def drawn_in(self, cid, parent=None, tab=None):
        """A copy in a window: under a tab panel when `tab` is given (the
        bus reads the tab from the copy's ancestors), or straight on the
        page like the header."""
        if parent is None and tab is not None:
            parent = Element(cid, tag="q-tab-panel", props={"name": tab})
        box = Element(cid, parent)
        self.targets.append(Target(box))
        return box

    def prune(self):
        self.targets = [b for b in self.targets if not b.container.is_deleted]

    def refresh(self, *a, **k):
        self.whole += 1

    def rebuild_count(self):
        return [self.name + "@" + c for c in self.rebuilt]


def _watch(panel):
    real_rebuild = theme._rebuild

    def rebuild(ref, target):
        if ref is panel:
            panel.rebuilt.append(target.container.client.id)
            target.container.clear()
            return None
        return real_rebuild(ref, target)
    return rebuild


class Bus:
    """The bus with fake windows A (turn), B (map), C (turn) and a shared
    panel `turn.x` drawn in the three of them; restored on exit."""

    def __init__(self, name="turn.x"):
        self.name = name

    def __enter__(self):
        self.saved = (dict(theme._REFRESH.get(theme._GLOBAL, {})), dict(theme._WINDOWS),
                      {k: set(v) for k, v in theme._DIRTY.items()}, theme._rebuild, theme._window)
        theme._WINDOWS.update({"A": {"tab": "turn"}, "B": {"tab": "map"}, "C": {"tab": "turn"}})
        self.panel = Panel(self.name)
        tab = theme._tab_of(self.name)              # "turn" for turn.x, None for main.x
        for cid in "ABC":
            self.panel.drawn_in(cid, tab=tab)
        theme._REFRESH.setdefault(theme._GLOBAL, {})[self.name] = self.panel
        theme._route_through_bus(self.panel)
        theme._rebuild = _watch(self.panel)
        return self

    def __exit__(self, *exc):
        panels, windows, dirty, rebuild, window = self.saved
        theme._REFRESH[theme._GLOBAL] = panels
        theme._WINDOWS.clear()
        theme._WINDOWS.update(windows)
        theme._DIRTY.clear()
        theme._DIRTY.update(dirty)
        theme._rebuild = rebuild
        theme._window = window
        theme._PENDING.clear()


# --- 1. only the windows on the tab ---------------------------------------
with Bus() as bus:
    theme.refresh_panels(("turn.x",))
    results.append(("a shared panel is rebuilt only in the windows on its tab",
                    sorted(bus.panel.rebuilt) == ["A", "C"]))
    results.append(("the window on another tab owes the redraw",
                    theme._DIRTY.get("B") == {"turn.x"} and "A" not in theme._DIRTY))
    results.append(("NiceGUI's own refresh-everything was not called",
                    bus.panel.whole == 0))

    # --- 2. and gets it when it comes to the tab, alone -----------------
    bus.panel.rebuilt.clear()
    theme._window = lambda: "B"
    theme.active_tab("turn")
    results.append(("switching to the tab redoes the panel in that window only",
                    bus.panel.rebuilt == ["B"]))
    results.append(("and the debt is cleared", not theme._DIRTY.get("B")))
    theme.active_tab("map")
    results.append(("switching to a tab without debts rebuilds nothing",
                    bus.panel.rebuilt == ["B"]))

# --- 3. the acting window is skipped when asked ---------------------------
with Bus() as bus:
    theme.refresh_panels(("turn.x",), exclude="A")
    results.append(("`exclude` leaves the acting window alone",
                    bus.panel.rebuilt == ["C"]))
    results.append(("without putting it in debt either", "A" not in theme._DIRTY))

# --- 4. the panel's own refresh() takes the bus ---------------------------
with Bus() as bus:
    bus.panel.refresh()
    results.append(("panel.refresh() rebuilds the windows on the tab",
                    sorted(bus.panel.rebuilt) == ["A", "C"] and bus.panel.whole == 0))
    results.append(("and marks the other", theme._DIRTY.get("B") == {"turn.x"}))
    bus.panel.refresh(1)
    results.append(("a refresh with arguments keeps NiceGUI's behaviour",
                    bus.panel.whole == 1))

# --- 5. one action, one rebuild -------------------------------------------
with Bus() as bus:
    async def twice():
        theme.refresh_panels(("turn.x",))
        theme.refresh_ui()
        bus.panel.refresh()
        before = list(bus.panel.rebuilt)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        return before
    before = asyncio.run(twice())
    results.append(("inside the event loop nothing is rebuilt during the handler",
                    before == []))
    results.append(("three requests in one action are one rebuild per window",
                    sorted(bus.panel.rebuilt) == ["A", "C"]))

# --- 6. a panel drawn inside another is not redone twice ------------------
with Bus() as bus:
    inner = Panel("turn.y")
    outer_box_a = bus.panel.targets[0].container          # window A
    inner.drawn_in("A", parent=outer_box_a)
    inner.drawn_in("C", tab="turn")                       # on its own there
    theme._REFRESH[theme._GLOBAL]["turn.y"] = inner
    real = theme._rebuild

    def rebuild(ref, target):
        if ref is inner:
            inner.rebuilt.append(target.container.client.id)
            return None
        return real(ref, target)
    theme._rebuild = rebuild
    theme.refresh_ui()
    results.append(("the outer panel is rebuilt in A and C",
                    sorted(bus.panel.rebuilt) == ["A", "C"]))
    results.append(("the inner one only where it stands on its own",
                    inner.rebuilt == ["C"]))
    bus.panel.rebuilt.clear()
    inner.rebuilt.clear()
    theme.refresh_panels(("turn.y",))
    results.append(("asked alone, the inner one is redone everywhere on the tab",
                    sorted(inner.rebuilt) == ["A", "C"] and bus.panel.rebuilt == []))

# --- 6b. a copy drawn in another tab is judged by where it sits -----------
with Bus() as bus:
    theme._WINDOWS["B"]["tab"] = "city"
    bus.panel.drawn_in("B", tab="city")                   # the adjustments in the City tab
    theme.refresh_panels(("turn.x",))
    # both copies in B are redone: the one in front and, with it, the hidden
    # one, so nothing is owed to that window
    results.append(("a copy of a turn panel in the City tab is rebuilt for the window on City",
                    sorted(bus.panel.rebuilt) == ["A", "B", "B", "C"] and "B" not in theme._DIRTY))
    bus.panel.rebuilt.clear()
    theme._WINDOWS["B"]["tab"] = "party"
    theme.refresh_panels(("turn.x",))
    results.append(("and owed when the window is on a tab with no copy",
                    sorted(bus.panel.rebuilt) == ["A", "C"] and theme._DIRTY.get("B") == {"turn.x"}))
    theme._window = lambda: "B"
    theme.active_tab("city")
    results.append(("coming back to City redoes it there",
                    bus.panel.rebuilt == ["A", "C", "B", "B"] and not theme._DIRTY.get("B")))

# --- 6c. a panel that says what it reads is not rebuilt for nothing -------
with Bus() as bus:
    figures = {"rp": 3}
    theme._DEPENDS[id(bus.panel)] = lambda: [figures["rp"]]
    theme.refresh_panels(("turn.x",))
    theme.refresh_panels(("turn.x",))
    results.append(("the first refresh rebuilds, the second, with nothing moved, does not",
                    sorted(bus.panel.rebuilt) == ["A", "C"]))
    figures["rp"] = 4
    theme.refresh_panels(("turn.x",))
    results.append(("a moved figure rebuilds again",
                    sorted(bus.panel.rebuilt) == ["A", "A", "C", "C"]))
    theme._WINDOWS["A"]["lang"] = "it"
    theme.refresh_panels(("turn.x",))
    results.append(("a window's language is part of the fingerprint",
                    sorted(bus.panel.rebuilt) == ["A", "A", "A", "C", "C"]))
    # an inner panel is not left behind because its container was skipped
    inner = Panel("turn.z")
    inner.drawn_in("A", parent=bus.panel.targets[0].container)
    theme._REFRESH[theme._GLOBAL]["turn.z"] = inner
    real = theme._rebuild

    def rebuild(ref, target):
        if ref is inner:
            inner.rebuilt.append(target.container.client.id)
            return None
        return real(ref, target)
    theme._rebuild = rebuild
    theme.refresh_ui()
    results.append(("an inner panel is redone when its container is skipped as unchanged",
                    inner.rebuilt == ["A"]))
    theme._DEPENDS.pop(id(bus.panel), None)

# --- 7. a closed window disappears from the targets -----------------------
with Bus() as bus:
    bus.panel.targets[1].container.is_deleted = True      # B is gone
    theme.refresh_ui()
    results.append(("a deleted copy is pruned, not rebuilt and not owed",
                    sorted(bus.panel.rebuilt) == ["A", "C"] and "B" not in theme._DIRTY))

# --- 8. something with only a refresh() of its own -------------------------
with Bus() as bus:
    class Refresher:
        calls = 0

        def refresh(self):
            Refresher.calls += 1
    theme._WINDOWS["A"]["tab"] = "map"
    theme._refresh("A", {"hexmap.map": Refresher()}, ["hexmap.map"])
    results.append(("a panel without targets is refreshed whole, as before",
                    Refresher.calls == 1))
    theme._WINDOWS["A"]["tab"] = "turn"
    theme._refresh("A", {"hexmap.map": Refresher()}, ["hexmap.map"])
    results.append(("and owed when its tab is not in front",
                    Refresher.calls == 1 and theme._DIRTY.get("A") == {"hexmap.map"}))

# --- 9. inside the loop: the actor's window first, one window per turn ----
# `main.x` belongs to no tab, like the header: every window is rebuilt, and
# the order shows — the actor (C), the window on the map (B), the rest (A).
with Bus("main.x") as bus:
    theme._window = lambda: "C"                  # C acts

    async def staged():
        theme.refresh_panels(("main.x",))
        seen = []
        for _ in range(10):
            await asyncio.sleep(0)
            seen.append(list(bus.panel.rebuilt))
            if theme.redraws_idle():
                break
        return seen
    seen = asyncio.run(staged())
    results.append(("the actor's window is rebuilt first, then the map, then the rest",
                    bus.panel.rebuilt == ["C", "B", "A"]))
    results.append(("one window per turn of the loop, not all in one stretch",
                    any(0 < len(step) < 3 for step in seen)))

# --- 10. a request that arrives mid-flush --------------------------------
with Bus("main.x") as bus:
    theme._window = lambda: "C"

    async def interrupted():
        theme.refresh_panels(("main.x",))
        while not bus.panel.rebuilt:               # the first window is done
            await asyncio.sleep(0)
        first = list(bus.panel.rebuilt)
        theme.refresh_panels(("main.x",))          # a second action, meanwhile
        while not theme.redraws_idle():
            await asyncio.sleep(0)
        return first
    first = asyncio.run(interrupted())
    results.append(("the second request leaves the windows not yet done to its own batch",
                    first == ["C"] and bus.panel.rebuilt == ["C", "C", "B", "A"]))
    results.append(("and the queue is empty at the end", theme.redraws_idle()))

width = max(len(n) for n, _ in results)
print()
for name, ok in results:
    print(("  ok  " if ok else " NO   ") + name.ljust(width))
print(f"\n{sum(1 for _, ok in results if ok)}/{len(results)} passed")
