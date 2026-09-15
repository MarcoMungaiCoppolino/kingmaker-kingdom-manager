"""Clicking a marker must pick it, even if it is drawn beyond the edge."""
from kingmaker.geometry import hexgrid, sections
from kingmaker.access import permissions
from kingmaker.access import view as view_mod
from kingmaker.state import STATE
from kingmaker.ui import hexmap
import helpers

A, C = STATE.archive, STATE.campaign
m = STATE.k["map"]
size = float(m["size"])
origin = (float(m["origin_x"]), float(m["origin_y"]))
orient = m["orientation"]
banks = hexmap.sections_map()
# The test must not depend on what is on the map right now: if there is no
# cut hexagon one is made, so the worst case is always tested.
if not any(len(g) >= 2 for g in banks.values()):
    A.set_banks(C, (9, 4), helpers.banks_between_vertices(0, 3))
    banks = hexmap.sections_map()
results = []


class Fake:
    id, username, role = "check", "check", permissions.ADMIN
    active = True


view = view_mod.MapView(Fake(), STATE)
# The members of every hexagon are those of the drawing: people **and placed
# vehicles**, which sit in the badge of their piece like the people. It is
# the same list the click uses, or a marker would be seen in one place and
# picked in another.
per_hex = {c: g for c, g in hexmap._members_per_hex(view).items()
               if c[0] is not None}

if not per_hex:
    is_cut = next(c for c, g in banks.items() if len(g) >= 2)
    for p in STATE.characters()[:1]:
        A.update_character(p["id"], hex_col=is_cut[0], hex_row=is_cut[1],
                               bank=1)
    view = view_mod.MapView(Fake(), STATE)
    per_hex = {c: g for c, g in hexmap._members_per_hex(view).items()
                   if c[0] is not None}
results.append(("there are markers to test", bool(per_hex)))

# --- every marker, clicked where it is drawn, must be found --------------
tried = taken_ones = outside_own = 0
for coord, people in per_hex.items():
    cx, cy = hexgrid.hex_center(coord[0], coord[1], size, origin, orient)
    for group, x, y, _r in hexmap.marker_positions(
            people, cx, cy, size, coord, origin, orient, banks):
        tried += 1
        where_it_falls = hexgrid.pixel_to_hex(x, y, size, origin, orient)
        if where_it_falls != coord:
            outside_own += 1
        found = hexmap.marker_under(view, m, (x, y), where_it_falls)
        # A marker on the map is one per shore and may hold more than one:
        # clicking it must return **that** group, whole.
        if found is not None and [p["id"] for p in found] == [
                p["id"] for p in group]:
            taken_ones += 1
results.append((f"{taken_ones}/{tried} markers are picked by clicking them",
              tried > 0 and taken_ones == tried))
print(f"   ({outside_own} of these are drawn beyond the edge of their hexagon)")

# --- and on a cut hexagon, with four markers, the worst case -------------
cut_ones = [c for c in banks if len(banks[c]) >= 2]
if cut_ones:
    coord = cut_ones[0]
    # The fakes carry a **place**, not a shore number: since the position is
    # a point, a shore number written by hand says nothing.
    def on_shore(p, i, where):
        # The hexagon too, not only the place: the place is relative to the
        # center of **its** cell, and a fake copied from a real character
        # dragged it along together with its home coordinates.
        x, y = sections.section_spot(banks[where], i % len(banks[where]))
        return dict(p, id=f"finto{i}", hex_col=where[0], hex_row=where[1],
                    pos_x=x, pos_y=y)

    fakes = [on_shore(p, i, coord)
             for i, p in enumerate((list(per_hex.values())[0] * 4)[:4])]
    cx, cy = hexgrid.hex_center(coord[0], coord[1], size, origin, orient)
    seats = hexmap.marker_positions(fakes, cx, cy, size, coord, origin, orient, banks)
    # Four characters on two shores make **two** badges, not four: a row of
    # four does not fit in half a shore, and indeed it overflowed.
    results.append(("four characters on two shores make two badges",
                  len(seats) == len(banks[coord])))
    results.append(("and none of them is left out of the count",
                  sum(len(g) for g, _x, _y, _r in seats) == len(fakes)))
    distinct = len({(round(x), round(y)) for _g, x, y, _r in seats})
    results.append(("the badges sit in distinct places", distinct == len(seats)))
    inside = sum(1 for _g, x, y, _r in seats
                 if hexgrid.pixel_to_hex(x, y, size, origin, orient) == coord)
    print(f"   (of {len(seats)} badges on {coord}, {inside} fall inside their own hexagon)")

# --- the click on the ground must pick nobody ----------------------------
coord = next(iter(per_hex))
cx, cy = hexgrid.hex_center(coord[0], coord[1], size, origin, orient)
top = (cx, cy - size * 0.55)          # well above the row of markers
results.append(("clicking the ground picks no marker",
              hexmap.marker_under(view, m, top, coord) is None))

# --- the worst case built on purpose: four on a cut hexagon --------------
# `characters_on` is replaced, so the test does not depend on who is really
# on the map and covers the case that used to break.
cut_ones = [c for c in banks if len(banks[c]) >= 2]
if cut_ones:
    coord = cut_ones[0]
    fakes = [dict({"id": f"f{i}", "name": f"F{i}", "hex_col": coord[0],
                   "hex_row": coord[1], "color": "#fff"},
                  **dict(zip(("pos_x", "pos_y"),
                             sections.section_spot(
                                 banks[coord], i % len(banks[coord])))))
             for i in range(4)]
    # The fakes slip into the members list, which is what the click uses: it
    # is the same as the drawing's, people and placed vehicles together.
    real = hexmap._members_per_hex
    helpers.silence("_members_per_hex", lambda v: {coord: fakes})
    try:
        cx, cy = hexgrid.hex_center(coord[0], coord[1], size, origin, orient)
        seats = hexmap.marker_positions(fakes, cx, cy, size, coord, origin,
                                           orient, banks)
        taken_ones = 0
        beyond_ = 0
        for group, x, y, _r in seats:
            where = hexgrid.pixel_to_hex(x, y, size, origin, orient)
            if where != coord:
                beyond_ += 1
            t2 = hexmap.marker_under(view, m, (x, y), where)
            if t2 is not None and [q["id"] for q in t2] == [
                    q["id"] for q in group]:
                taken_ones += 1
        results.append((f"four on {coord}: {taken_ones}/{len(seats)} badges are "
                      f"picked ({beyond_} drawn beyond the edge)",
                      taken_ones == len(seats)))
    finally:
        helpers.silence("_members_per_hex", real)

# --- the group badge opens instead of choosing blindly -------------------
# A row of four badges does not fit in half a shore, and indeed it
# overflowed: a single one per shore, with the sign that inside there is more
# than one, and clicking it opens it — like the app folder on a phone.
cut_ones = [c for c in banks if len(banks[c]) >= 2]
if cut_ones:
    coord = cut_ones[0]
    four = [dict({"id": f"g{i}", "name": f"G{i}", "hex_col": coord[0],
                     "hex_row": coord[1], "color": "#fff"},
                    **dict(zip(("pos_x", "pos_y"),
                               sections.section_spot(
                                   banks[coord], i % len(banks[coord])))))
               for i in range(4)]
    cx, cy = hexgrid.hex_center(coord[0], coord[1], size, origin, orient)
    seats = hexmap.marker_positions(four, cx, cy, size, coord, origin,
                                       orient, banks)
    results.append(("four on two shores make two badges of two",
                  sorted(len(g) for g, _x, _y, _r in seats) == [2, 2]))

    real_on_ = hexmap.characters_on
    real_open = hexmap._open_group
    open_ones = []
    helpers.silence("characters_on", lambda c, vis: four if tuple(c) == coord else [])
    helpers.silence("_open_group", lambda mine, mapping, g: open_ones.append(g))
    try:
        fake_view = type("V", (), {"gm": True,
                                     "markers": lambda self: four,
                                     "can_see": lambda self, c, r: True})()
        group, gx, gy, _r = seats[0]
        mine = {"travel_pcs": [], "travel_mode": "choose"}
        real_view = hexmap._current_view
        real_redraw = hexmap._redraw_travel
        helpers.silence("_current_view", lambda _m: fake_view)
        helpers.silence("_redraw_travel", lambda *a, **k: None)
        try:
            hexmap._choose_from_click(mine, None, coord, (gx, gy), False)
            results.append(("a click on a group badge opens it",
                          len(open_ones) == 1
                          and [x["id"] for x in open_ones[0]]
                          == [x["id"] for x in group]))
            results.append(("and chooses nobody blindly",
                          mine["travel_pcs"] == []))
            hexmap._choose_from_click(mine, None, coord, (gx, gy), True)
            results.append(("with ctrl instead it adds up the whole group, without opening",
                          len(open_ones) == 1
                          and sorted(mine["travel_pcs"])
                          == sorted(x["id"] for x in group)))
        finally:
            helpers.silence("_current_view", real_view)
            helpers.silence("_redraw_travel", real_redraw)
    finally:
        helpers.silence("characters_on", real_on_)
        helpers.silence("_open_group", real_open)

width = max(len(n) for n, _ in results)
print()
for name, ok in results:
    print(("  ok  " if ok else " NO   ") + name.ljust(width))
print(f"\n{sum(1 for _, ok in results if ok)}/{len(results)} passed")
