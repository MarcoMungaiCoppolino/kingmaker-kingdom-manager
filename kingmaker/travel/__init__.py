"""Travel on the map: what it costs, how long it takes, which way one passes.

Pure functions: no interface, no global state. They receive the hexes as
dictionaries and return numbers and warnings, so they can be tested by hand.

Every rule comes from `data/kingdom.json`, block «travel», transcribed from
the Hexploration rules. Nothing here is hand-written: if the rules assign no
category to a terrain, the planner stops and asks the GM instead of guessing.

Do not confuse this with `rules.disconnected_terrain_cost`, which is the RP
cost to *build* on a terrain: it has nothing to do with the cost to cross it.
"""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field

from kingmaker.geometry import waterways, atoms as atoms_mod, hexgrid, sections
from kingmaker import rules
from kingmaker.locale import units
from kingmaker.locale.i18n import t, tn

# Glossary, because the same thing has several names in the code:
#   section = shore = bank = face: a piece of hex cut out by the water
#     (`sections.Face`); its number is the index in the tuple of faces.
#   node (on land): (col, row, gate) — a hex and the section one is in; it
#     is the vertex of the graph `cost_field` runs on.
#   atom: one of the 24 fixed pieces of the hex (`atoms.py`); ¼ activity.
#   junction = node of the water network: ("v", ...) corner, ("c", ...)
#     center, ("x", ...) inner point; a boat sails on these (`route_towards`).
#   detour: the extra activities to coast along the water inside a hex.

TRAVEL = rules.TRAVEL                       # a language view: see rules.View
ORDER = TRAVEL["category_order"]           # from the easiest to the hardest
CATEGORIES = rules.derived(lambda: TRAVEL["categories"])
TERRAINS = rules.derived(lambda: TRAVEL["terrains"])


# ---------------------------------------------------------------- speed
def activities_per_day(speed_m: float) -> float:
    """How many exploration activities a day whoever goes at that Speed makes.

    Table of the rules: up to 10 feet -> 1/2, 15-25 -> 1, 30-40 -> 2, 45-55
    -> 3, 60 or more -> 4 (in metres: 3, 4.5-7.5, 9-12, 13.5-16.5, 18+).
    Half an activity a day means two days for every activity.
    """
    for row in TRAVEL["activities_per_day_table"]:
        limit = row["up_to"]
        if limit is None or speed_m <= float(limit):
            return float(row["activities"])
    return float(TRAVEL["activities_per_day_table"][-1]["activities"])


def best_vehicle_speed(vehicle: dict) -> tuple[str, float] | None:
    """The fastest movement among those listed on the page."""
    speed = (vehicle or {}).get("speed") or {}
    if not speed:
        return None
    kind = max(speed, key=lambda frac: float(speed[frac]))
    return kind, float(speed[kind])


# ---------------------------------------------------------------- terrain
@dataclass(frozen=True)
class Category:
    """The travel category of a hex, with the reason."""

    id: str | None                # open | difficult | greater_difficult, or None
    reason: str = ""
    is_uncertain: bool = False         # the rules leave two possibilities
    by_gm: bool = False           # set by hand on this hex
    is_unknown: bool = False          # nothing is known about the terrain yet
    from_table: bool = False      # decided by the table, not written in the rules
    water: bool = False           # crossed only by sailing

    @property
    def name(self) -> str:
        if self.is_unknown:
            return t("travel.unknown_terrain")
        return CATEGORIES[self.id]["name"] if self.id else t("travel.decided")

    @property
    def cost(self) -> int | None:
        return CATEGORIES[self.id]["cost"] if self.id else None


WORST = ORDER[-1]


def unknown_category() -> Category:
    """How much a hex nothing is known about yet counts.

    The party cannot know how long it will take to cross a place it has
    never been, but it can know how long it would take **at most**: we count
    it as the worst terrain. The resulting estimate is a ceiling, and the
    real journey can only be shorter.

    A fixed cost, the same for every unknown hex, tells nothing about what is
    inside: the fog stays fog for the planner too.
    """
    return Category(WORST, t("travel.never_explored_hex_counted"),
                     is_unknown=True)


def _worst(categories: list[str]) -> str:
    return max(categories, key=ORDER.index)


def _upgrade(category: str, grades: int = 1) -> str:
    """One step easier, without going below «open»."""
    return ORDER[max(0, ORDER.index(category) - grades)]


def terrain_name(tid: str) -> str:
    return rules.BY_ID["terrain"].get(tid, {}).get("name", tid)


def terrain_category(hexagon: dict, gm_difficulty: str | None = None,
                      sail: bool = False) -> Category:
    """The category of a hex, before roads are considered.

    If the hex has several terrains the hardest counts: it is the one the
    party has to cross anyway. A category imposed by the GM wins over
    everything, because they know what that piece of map is like.

    `sails` says whether the group carries a water vehicle. It changes only
    the water hexes, and there it changes everything: the rules say whoever
    travels on water finds open terrain almost everywhere, while whoever
    walks does not enter a lake at all.
    """
    if gm_difficulty:
        return Category(gm_difficulty, t("travel.category_decided_gm"), by_gm=True)

    # `None` is the hex the viewer does not see; a visible hex with no terrain
    # is just as unknown, and counts the same.
    terrains = list((hexagon or {}).get("terrains") or [])
    if not terrains:
        return unknown_category()

    found_ones: list[str] = []
    uncertain: list[str] = []
    without: list[str] = []
    waters: list[str] = []
    table: list[str] = []
    for tid in terrains:
        entry = TERRAINS.get(tid)
        if entry is None:
            without.append(terrain_name(tid))
            continue
        if entry.get("water"):
            waters.append(terrain_name(tid))
            continue
        if entry.get("category") is None:
            without.append(terrain_name(tid))
            continue
        found_ones.append(entry["category"])
        if entry.get("or_category"):
            uncertain.append(tid)
        if entry.get("source") == "table":
            table.append(tid)

    # Water decides on its own: either it is sailed, or there is no way
    # through. Averaging it with the land next to it in the same hex makes no
    # sense.
    if waters:
        names = ", ".join(waters)
        if not sail:
            return Category(None, t("travel.water_vehicle_needed_pass", names=names),
                             water=True)
        return Category(ORDER[0], t("travel.sailing_counts_open_terrain", names=names),
                         water=True)

    if without:
        return Category(None, t("travel.rules_assign_no_travel")
                               + ", ".join(without))
    category = _worst(found_ones)
    reasons: list[str] = []
    if uncertain:
        reasons.append(", ".join(terrain_name(frac) for frac in uncertain)
                      + t("travel.rules_give_difficult_greater"))
    if table:
        reasons.append(", ".join(terrain_name(frac) for frac in table)
                      + t("travel.category_chosen_table_not"))
    if reasons:
        return Category(category, " · ".join(reasons),
                         is_uncertain=bool(uncertain), from_table=bool(table))
    return Category(category)


CURRENT = rules.derived(lambda: TRAVEL["current"])


def current_category(direction: str | None,
                       gm_difficulty: str | None = None) -> Category:
    """The category of a hex crossed **following** a watercourse.

    It is the rules' line on the River terrain: downriver open terrain,
    upriver difficult or greater difficult depending on currents and weather.
    Between those two no choice is made — the easier counts and it is flagged,
    as for the forest: currents and weather belong to the table, not to the
    database.

    A stretch **without a direction** is not a stretch nothing is known
    about: it is water without current. There is nothing to go along with and
    nothing to go up against, it is walked both ways the same, and it counts
    as open terrain — which is what the rules give whoever travels on water.
    It is the case of every line of a lake, and the table's choice for a river
    nobody has marked the direction of yet.
    """
    if gm_difficulty:
        return Category(gm_difficulty, t("travel.category_decided_gm"), by_gm=True)
    if direction == "lake":
        entry = CURRENT["still"]
        return Category(entry["category"], t("travel.still_water_one_goes"))
    if direction == "downstream":
        entry = CURRENT["downstream"]
        return Category(entry["category"], t("travel.going_down_river") +
                         category_name(entry["category"]).lower())
    entry = CURRENT["upstream"]
    if direction == "upstream":
        return Category(entry["category"], CURRENT["upstream"]["note"],
                         is_uncertain=bool(entry.get("or_category")))
    stop = CURRENT["unknown_"]
    how = CURRENT[stop.get("as", "downstream")]
    return Category(how["category"], stop["note"],
                     from_table=stop.get("source") == "table")


def category_name(cid: str) -> str:
    return CATEGORIES.get(cid, {}).get("name", cid)


def current_cost(direction: str | None,
                   gm_difficulty: str | None = None) -> tuple[int | None, Category]:
    """Activities to cross a hex following the water.

    Roads do not enter into it: a road does not make going upriver easier,
    and adding the two advantages would be a number no rule says.
    """
    category = current_category(direction, gm_difficulty)
    if category.id is None:
        return None, category
    return CATEGORIES[category.id]["cost"], category


def travel_cost(hexagon: dict, gm_difficulty: str | None = None,
                    sail: bool = False) -> tuple[int | None, Category]:
    """Travel activities to *enter* this hex.

    Roads improve the terrain by one step, and here they count.
    """
    category = terrain_category(hexagon, gm_difficulty, sail)
    if category.id is None:
        return None, category
    final = category.id
    if (hexagon or {}).get("roads"):
        final = _upgrade(final, int(TRAVEL["roads"]["improves_by_steps"]))
    return CATEGORIES[final]["cost"], category


def reconnaissance_cost(hexagon: dict, gm_difficulty: str | None = None,
                       sail: bool = False) -> tuple[int | None, Category]:
    """Like Travel, but roads do not count: the rules say so explicitly."""
    category = terrain_category(hexagon, gm_difficulty, sail)
    if category.id is None:
        return None, category
    return CATEGORIES[category.id]["cost"], category


# ---------------------------------------------------------------- borders
BORDERS = rules.derived(lambda: TRAVEL["borders"]["kinds"])


def border_name(kind: str) -> str:
    return BORDERS.get(kind, {}).get("name", kind)


def border_cost(a: tuple[int, int], b: tuple[int, int], borders: dict,
                  sail: bool = False) -> int | None:
    """Extra activities to pass from `a` to `b`, or None if there is no way.

    A border is the only thing on the map that belongs to no hex: a river
    running along the edge lies between the two, and which of the two «owns»
    it is not a question with an answer. So it sits on a side, and its key is
    the ordered pair of the two hexes.

    An unmarked side is land and costs zero: without marked borders this
    function changes nothing in the path.
    """
    if not borders:
        return 0
    entry = borders.get(hexgrid.border_key(tuple(a), tuple(b)))
    if entry is None:
        return 0
    rule = BORDERS.get(entry.get("kind"), {})
    if not rule.get("passes", True) and not sail:
        return None
    return int(rule.get("extra_activities") or 0)


# -------------------------------------------------------------- pathfinding
# ------------------------------------------------------------------- banks
# A river crossing a hex does not close it: it cuts it. One enters from every
# side, but from one bank one does not reach the other without a bridge.
#
# The state is not on the traveller, it is in the graph: the pathfinder's
# node is (column, row, bank) instead of (column, row). It is the difference
# between an algorithm that works and one that seems to — if «which side am I
# on» were something the traveller carried along, the cost to get somewhere
# would depend on how you got there, and Dijkstra would not even notice.
#
# Outside here a hex stays two coordinates and no more: that is how players
# call it, and there is no reason to make them learn the banks. The courses
# leaving this module are lists of (column, row).
def bank_of_side(banks: dict, coord, direction: int) -> int:
    """Which section of the hex the side in that direction opens onto.

    The answer is always one, and not by luck: the sections are the faces the
    water cuts the hex into, and an edge side sits on the outline of exactly
    one face. It holds as long as the water stretches have a vertex or the
    center as ends, which is the only thing the brush can snap to.

    Zero is the answer for the uncut hex, which is almost the whole map.
    """
    faces = (banks or {}).get(tuple(coord))
    if not faces:
        return 0
    for index, face in enumerate(faces):
        if direction in sections.sides_of(face):
            return index
    return 0


def banks_of(banks: dict, coord) -> int:
    """How many banks that hex has: 1 if it is dry."""
    return len((banks or {}).get(tuple(coord)) or [0])


def node_of(banks: dict, coord, bank: int = 0) -> tuple[int, int, int]:
    """The graph node for a hex, with the bank brought within bounds."""
    coord = tuple(coord)
    n_items = banks_of(banks, coord)
    return (coord[0], coord[1], bank if 0 <= bank < n_items else 0)


def steps_from(node, orientation: str, banks: dict):
    """The possible steps from a node: (neighbour_node, neighbour_coordinates).

    From a bank one leaves only through the sides belonging to it, and
    arrives on the bank of the neighbour opening onto the same side.
    """
    col, row, bank = node
    faces = (banks or {}).get((col, row))
    neighbours = hexgrid.neighbours(col, row, orientation)
    # A section not touching the edge — an island in the middle of the hex —
    # has no sides to leave from, and indeed one does not leave: one enters
    # and leaves it only through an inner crossing.
    directions = sections.sides_of(faces[bank]) if faces else range(len(neighbours))
    for direction in directions:
        near = neighbours[direction]
        back = (direction + 3) % 6      # opposite sides are half a turn apart
        yield (near[0], near[1],
               bank_of_side(banks, near, back)), near


def inner_passages(node, banks: dict, crossings: dict):
    """The other shores of the same hex reachable from here.

    A river crossing a hex cuts it into two shores, and without a crossing
    between them there is no way through at all. On a real map bridges are
    almost always there in the middle, not on the edge between two hexes.

    A crossing is written as the **point where it hops over the water**, not
    as a pair of shore numbers: the numbers change as soon as a new cut
    divides the hex again, the point does not. The reader asks which two
    sections have that point on their outline, and they are always two. If
    the GM redrew and the water no longer passes there, that crossing crosses
    nothing any more and does nothing — which is the right answer.

    The old notation as a pair of sides is still accepted, because it is the
    format a water chart arrives in from outside.

    Returns pairs `(node, entry)`: the entry says whether it is a bridge or a
    ford, and what it costs is said by `inner_cost`.
    """
    col, row, bank = node
    faces = (banks or {}).get((col, row))
    for entry in (crossings or {}).get((col, row), ()):
        which_ones = _joined_shores(faces, (col, row), banks, entry)
        if which_ones is None:
            continue
        if bank == which_ones[0]:
            yield (col, row, which_ones[1]), entry
        elif bank == which_ones[1]:
            yield (col, row, which_ones[0]), entry


def inner_jumps(node, banks: dict, crossings: dict, max_: int = 6):
    """The other shores of the same hex reachable **in more than one hop**.

    `inner_passages` answers «from here, with one crossing, where do I get».
    This answers the question that comes next: «and with two?». Needed where
    the river cuts the hex into three or more pieces and the bridges make a
    chain — one enters the first shore, passes into the second, and only from
    that one leaves by the side needed. For a long time it was forbidden, and
    the ban was no rule: it was the limit of whoever read the course, who
    tried a single hop. A piece in the middle of a hex became a place one
    could not reach.

    Returns pairs `(node, chain)` in order of **number of hops**, where the
    chain is the entries of the crossings used: what it costs is said by
    `inner_cost`, one by one, because every passage is paid.

    `maximum` is a safety belt, not a rule: six hops want seven shores in the
    same hex, and at that point it is no longer a river, it is a maze.
    """
    departure = tuple(node)
    seen = {departure}
    queue = [(departure, ())]
    while queue:
        here, chain = queue.pop(0)
        if len(chain) >= max_:
            continue
        for other_one, entry in inner_passages(here, banks, crossings):
            if other_one in seen:
                continue
            seen.add(other_one)
            after = chain + (entry,)
            yield other_one, after
            queue.append((other_one, after))


def _joined_shores(faces, coord, banks: dict, entry: dict):
    """The two sections a crossing joins, or None if it joins none."""
    told_ones = entry.get("shores")
    if told_ones is not None:
        # The **computed** form: two shore numbers, not a spot. It is not
        # saved and not exchanged — it lives for the length of a question, and
        # is born in the same breath as the shores it names, so the numbers
        # have no time to mean something else. It is how «here one swims
        # across» is said: swimming one crosses everywhere, and there is no
        # particular spot to point at.
        one_f_, other_one = int(told_ones[0]), int(told_ones[1])
        if one_f_ == other_one or not (0 <= one_f_ < len(faces or ())
                                 and 0 <= other_one < len(faces or ())):
            return None
        return tuple(sorted((one_f_, other_one)))
    ends = entry.get("ends")
    if ends is not None:
        return sections.crossing_shores(faces, ends)
    sides = entry.get("sides")
    if not sides:
        return None
    first = bank_of_side(banks, coord, sides[0])
    other_one = bank_of_side(banks, coord, sides[1])
    return None if first == other_one else (first, other_one)


def inner_cost(entry: dict, coord, cost_of) -> int:
    """How many activities passing from one shore to the other inside the hex costs.

    A **bridge** costs nothing: the hex was already paid on entering, and
    crossing it remains a single crossing.

    A **ford** costs what that terrain costs, i.e. the same number paid to
    enter the hex: a river to ford in the plains is worth one activity, in
    the swamp three. It is not a line of the rules — the rules do not price
    fording a river inside a hex — but neither is it an invented number: it
    is the only one already written for that terrain, and it is the table's
    choice. The GM can force another on the single crossing.

    The rules remind that a stretch to swim or climb may call for a check
    (Athletics) once an hour: that stays with the table, and the plan says so.
    """
    if (entry.get("kind") or "bridge") != "ford":
        return 0
    forced = entry.get("difficulty")
    if forced in CATEGORIES:
        return int(CATEGORIES[forced]["cost"])
    entry_ = cost_of(tuple(coord))
    return int(entry_) if entry_ is not None else 1


# Which side one entered a hex from: it is the state needed to know how much
# hex is still to be crossed, and the node `(column, row, shore)` did not have
# it. What passing through a hex costs depends on **where you enter and where
# you leave**: entering and leaving from the two ends of the same shore means
# coasting along the river, and it is longer than cutting straight.
DEPARTURE = -1          # the node of whoever is already inside, and did not enter from a side


class OpenWater(dict):
    """The water as whoever swims sees it: drawn where it is, and closing nothing.

    A water stretch does two jobs: it says where the river runs — and serves
    the drawing, the currents, the boats — and it closes the passages between
    atoms, which is what stops whoever walks. The rules put the Swim Speed
    next to the vehicle: they are the two ways of crossing water. Whoever
    swims therefore sees the first job and not the second.

    Said this way — a water answering «nothing to close here» to any hex —
    rather than with an «if it swims» tucked into `stretches_of`,
    `openings_of`, `inside_the_hex`, `cost_field` and `rings_on_course`.
    Those are five places that must say the same thing, and five copies of
    the same condition are five ways of making them say different things.

    The sections instead **remain**: whoever swims walks on land like
    everyone, and it is on a shore that their marker is, from a shore that
    their arrow leaves, and a shore that the mouse points at. Removing them
    was the defect that showed: the ruler went back to aiming at hex centers
    while the confirmed journey was drawn on the shores, and the two arrows
    told two roads.
    """

    def __contains__(self, key) -> bool:
        return True

    def __getitem__(self, key) -> tuple:
        return ()

    def get(self, key, default_=None) -> tuple:
        return ()

    def __bool__(self) -> bool:
        # Empty inside, but there: whoever writes `water or {}` must not end
        # up with the water of whoever walks.
        return True


OPEN_WATER = OpenWater()


def swim_crossings(banks: dict | None, crossings: dict | None) -> dict:
    """The extra crossings of whoever swims: between every pair of shores.

    Whoever has a Swim Speed needs no bridge to change shore, and needs none
    **in a place**: they cross wherever. Here it becomes a crossing for every
    pair of shores of the hex, for free — free because that is what it costs
    today, not because swimming is comfortable: the rules do not price
    swimming across a river inside a hex, and putting a number on it would be
    inventing it.

    Every pair and not only the touching ones: the reader makes **one** shore
    hop at a time, and with three pieces in a row a single hop would not be
    enough to get from the first to the third.

    Needed because the ruler, the hand-drawn course and the drawn arrow all
    three ask the same thing — which shores of this hex touch — of
    `steps_from` and `inner_passages`. Answering here once is what keeps the
    three answers equal.
    """
    outside = {coord: list(entries) for coord, entries in (crossings or {}).items()}
    for coord, faces in (banks or {}).items():
        n_items = len(faces or ())
        if n_items < 2:
            continue
        # The real crossings of that hex are **replaced**, not added to:
        # whoever passes wherever and for free needs no bridge, and a ford
        # would make them pay a toll for not using it. Worse: bridge and swim
        # would join the same two shores, and whoever keeps the tolls in a
        # dictionary per pair of cells — the ruler, in the browser — would keep
        # a single one, chosen by order. The server count and the drawn one
        # would go back to not matching.
        outside[tuple(coord)] = [
            {"kind": "swim", "shores": (one_f_, other_one)}
            for one_f_ in range(n_items) for other_one in range(one_f_ + 1, n_items)]
    return outside


def stretches_of(banks: dict | None, water: dict | None, coord) -> tuple:
    """The water stretches inside a hex, from the drawing or derived from the shores.

    `water` is the right thing and comes from the archive; the shores are the
    fallback for whoever does not pass it — the tests, and the code not yet
    touched. Deriving them from the shores loses the shape of the drawing but
    not who touches whom, which is all that is needed to know where one
    passes.
    """
    coord = tuple(coord)
    if water is not None and coord in water:
        return water[coord]
    faces = (banks or {}).get(coord)
    if not faces or len(faces) < 2:
        return ()
    return sections.cuts_from_groups([list(sections.sides_of(f)) for f in faces])


def _side_between_shores(entry: dict, faces, closed, orientation: str):
    """The water stretch between the two shores a crossing joined."""
    ends = entry.get("ends")
    which_ones = (sections.crossing_shores(faces, ends) if ends and faces else None)
    if which_ones is None:
        return None
    where = {}
    for number, group in enumerate(atoms_mod.provinces(closed, orientation)):
        for atom in group:
            where[atom] = number
    sought = set()
    for index in which_ones:
        point = getattr(faces[index], "point", None)
        if point is None:
            return None
        sought.add(where.get(atoms_mod.atom_of_point(point, orientation)))
    if len(sought) != 2:
        return None
    for number in sorted(closed):
        one, two_ = atoms_mod.sides(orientation)[number][0]
        if {where.get(one), where.get(two_)} == sought:
            return number
    return None


def openings_of(coord, banks, water, crossings: dict | None, cost_of,
                orientation: str) -> tuple:
    """The water stretches the crossings of a hex reopen.

    A crossing **has a place**, and here that place becomes the stretch it
    sits on: one of the 36 borders between atoms. Before, it became the pair
    of atoms of the points of the two shores, which are in the middle of the
    shores and not on the river: the bridge behaved like a shortcut between
    two distant places instead of a passage over the water, and the course
    inside the hex came out too short.

    The two forms, and they differ on purpose:

    * a **bridge** reopens **its stretch** and nothing else — on a
      twenty-one-kilometre hex that is four — and costs nothing beyond
      walking;
    * a **ford** reopens **the whole line** it belongs to, because a shallow
      river is waded wherever, and every passage costs that terrain's cost.

    A stretch where the water no longer passes — the GM redrew — is
    discarded: a ford charging a toll on dry land would just be an error seen
    late.
    """
    coord = tuple(coord)
    entries = (crossings or {}).get(coord)
    if not entries:
        return ()
    stretches = stretches_of(banks, water, coord)
    closed = atoms_mod.closed_by_stretches(stretches, orientation)
    if not closed:
        return ()
    faces = (banks or {}).get(coord)
    outside: dict = {}
    for entry in entries:
        side = atoms_mod.side_of_point(entry.get("at"), closed, orientation)
        if side is None:
            # An old-style crossing, saying only which shores it joined: its
            # stretch is a closed border with one atom in one shore and the
            # other in the other. Looking for it this way instead of taking
            # the midpoint of the border between the two shores avoids the
            # crooked case: that midpoint can fall on the hex center, which
            # sits at the ends of several stretches, and «which stretch» would
            # stay unanswered.
            side = _side_between_shores(entry, faces, closed, orientation)
        if side is None or side not in closed:
            continue          # the water no longer passes there: it opens nothing
        price = float(inner_cost(entry, coord, cost_of))
        if (entry.get("kind") or "bridge") != "ford":
            outside[side] = min(outside.get(side, price), price)
            continue
        # The ford holds on the whole water line that stretch is part of.
        for cut in stretches:
            its_ones = atoms_mod.closed_by_stretches([cut], orientation)
            if side not in its_ones:
                continue
            for other in its_ones & closed:
                outside[other] = min(outside.get(other, price), price)
    return tuple(sorted(outside.items()))


def inside_the_hex(coord, cost: float, banks, water, crossings, cost_of,
                     orientation: str) -> dict:
    """What going from one atom to another inside that hex costs.

    The count lives here and not in the graph because after a bridge you are
    not on a side of the hex but in the middle, and from there you still have
    to reach an exit.
    """
    closed = atoms_mod.closed_by_stretches(stretches_of(banks, water, coord),
                                         orientation)
    return atoms_mod.costs_inside(
        closed, openings_of(coord, banks, water, crossings, cost_of, orientation),
        cost / 4.0, orientation)


def start_atom(banks, water, coord, bank: int,
                      orientation: str = "pointy") -> int:
    """Which atom whoever leaves from that shore of that hex is in."""
    faces = (banks or {}).get(tuple(coord))
    edge = atoms_mod.edge_atoms(orientation)
    if not faces or not (0 <= bank < len(faces)):
        return edge[0]
    point = getattr(faces[bank], "point", None)
    if point is None:
        # An old-style shore — a list of sides, without a shape. The first of
        # its sides counts: it is inside that shore, which is all that is
        # needed to know where one can leave from.
        its_ones = sections.sides_of(faces[bank])
        return edge[its_ones[0]] if its_ones else edge[0]
    return atoms_mod.atom_of_point(point, orientation)


@dataclass
class Field:
    """The result of a Dijkstra on the map cut by the banks.

    `costs` is per hex — the cheapest among its banks — because that is how
    the rest of the app asks for it. `previous` works on nodes, which is how
    the graph is really made.
    """

    costs: dict = field(default_factory=dict)        # (col, row) -> cost
    node_costs: dict = field(default_factory=dict)   # (col, row, gate) -> cost
    previous_ones: dict = field(default_factory=dict)   # node -> node | None
    # The same field seen per **shore** instead of per gate: it is the
    # language the rest of the app speaks — the ruler sends one cell per
    # shore, not one per entry side — and the cost of a shore is the lowest
    # among the gates opening onto it.
    shore_costs: dict = field(default_factory=dict)  # (col, row, bank) -> cost
    # And for every shore, the node one reached it best with: needed to walk
    # a course back **to a precise shore**, which is what the rendezvous asks
    # — one meets on a shore, not in a hex.
    best_shore: dict = field(default_factory=dict)  # (col, row, bank) -> node

    def best_node(self, coord):
        """The cheapest gate of that hex, or None if it cannot be reached."""
        coord = tuple(coord)
        candidates = [n for n in self.node_costs if (n[0], n[1]) == coord]
        if not candidates:
            return None
        return min(candidates, key=lambda n: self.node_costs[n])

    def course_to_shore(self, departure, shore) -> list | None:
        """The course in hexes to **that shore** of the arrival hex.

        `course` reaches the hex through the cheapest gate, and in a cut hex
        that can open onto the wrong shore: for a rendezvous on a precise
        shore the road must end there, whatever it costs.
        """
        end = self.best_shore.get(tuple(shore))
        if end is None:
            return None
        return self._climb_back(departure, end)

    def course(self, departure, arrival) -> list | None:
        """The course in *hexes* between two hexes, arrival included."""
        end = self.best_node(arrival)
        if end is None:
            return None
        return self._climb_back(departure, end)

    def _climb_back(self, departure, end) -> list | None:
        departure = tuple(departure)
        nodes = [end]
        while self.previous_ones.get(nodes[-1]) is not None:
            nodes.append(self.previous_ones[nodes[-1]])
        if (nodes[-1][0], nodes[-1][1]) != departure:
            return None
        nodes.reverse()
        # Passing a bridge inside a hex changes shore without changing hex: in
        # the course, which is made of hexes, that step is not seen and must
        # not appear twice.
        outside: list = []
        for n in nodes:
            if not outside or outside[-1] != (n[0], n[1]):
                outside.append((n[0], n[1]))
        return outside


def _refresh(field: Field, node, cost: float, from_, full: float,
              bank: int) -> None:
    """Marks a node as reached, and with it the hex and shore it represents.

    `full` is what is left to pay of that hex to have really crossed it:
    whoever gets there and stops pays it all the same, because the rules
    price **the hex you enter**, not the metres you make inside. Whoever goes
    on will pay it on leaving, and it will be more if the water forces them
    to coast along.
    """
    field.node_costs[node] = cost
    field.previous_ones[node] = from_
    key = (node[0], node[1])
    whole = cost + full
    if whole < field.costs.get(key, whole + 1):
        field.costs[key] = whole
    shore_key = (node[0], node[1], bank)
    if whole < field.shore_costs.get(shore_key, whole + 1):
        field.shore_costs[shore_key] = whole
        field.best_shore[shore_key] = node


def cost_field(departure: tuple[int, int], cost_of, orientation: str = "pointy",
                inside=None, arrival: tuple[int, int] | None = None, passage=None,
                banks: dict | None = None, departure_bank: int = 0,
                crossings: dict | None = None, water: dict | None = None) -> Field:
    """Dijkstra from a hex: what reaching everywhere costs, and where from.

    With `arrival` it stops as soon as it reaches it, which is the single-path
    case; without, it explores everything — needed for dragging, where the
    browser must be able to redraw the arrow at every mouse move without
    asking the server anything.

    `cost_of(coord)` returns the activities to enter that hex, or None if it
    cannot be crossed. `passage(from, to)` does the same for the side between
    two hexes: None if there is no way through (a river without a bridge),
    otherwise the extra activities it costs (a ford). `banks` says into which
    shores the water divides a hex, `water` where the water runs inside it.

    **The node is `(column, row, gate)`**, where the gate is the side one
    entered from. It is no implementation detail: what passing through a hex
    costs depends on where you enter **and** where you leave, because
    entering and leaving from the two ends of the same shore means coasting
    along the river instead of cutting straight, and the node `(column, row,
    shore)` could not say that.

    The count is made so that **no earlier number moves**: entering a hex
    costs a quarter, leaving it costs the course inside — never less than
    three quarters — and stopping there pays it in full. In a hex the water
    does not force one to coast along it makes exactly the cost of the rules,
    in every direction.

    Bridges are no longer graph steps: they sit inside the hex cost, because
    after a bridge you are not on a side but in the middle, and from there
    you still have to reach an exit.

    Dijkstra and not A*: the grid is a few hundred cells, and a heuristic
    would only add a way of being wrong.
    """
    departure = tuple(departure)
    edge = atoms_mod.edge_atoms(orientation)
    field = Field(costs={departure: 0}, node_costs={(departure[0], departure[1],
                                                    DEPARTURE): 0},
                  previous_ones={(departure[0], departure[1], DEPARTURE): None},
                  shore_costs={(departure[0], departure[1], departure_bank): 0},
                  best_shore={(departure[0], departure[1], departure_bank):
                                   (departure[0], departure[1], DEPARTURE)})
    counter = 0
    queue: list = []

    def inside_of(coord, cost):
        return inside_the_hex(coord, cost, banks, water, crossings, cost_of,
                                orientation)

    def log_out(coord, from_atom, cost_here, min_, cost, node_from, pay=True):
        """Tries every exit from an atom, and queues those that hold.

        `pays` is false only for the departure hex: there nothing is paid,
        not even the piece of road made inside to reach the exit. It is the
        hex one was already in, and the rules price those one **enters** —
        and it is also what keeps the earlier counts where they were.
        """
        nonlocal counter
        table = inside_of(coord, cost_here)
        neighbours = hexgrid.neighbours(coord[0], coord[1], orientation)
        for direction, atom in edge.items():
            walk = table.get((from_atom, atom))
            if walk is None:
                continue          # no way out there: there is water in between
            near = neighbours[direction]
            if inside is not None and not inside(near):
                continue
            step = cost_of(near)
            if step is None:
                continue
            extra = passage(coord, near) if passage else 0
            if extra is None:
                continue          # there is water between the two and no way of passing it
            node = (near[0], near[1], (direction + 3) % 6)
            inside_here = max(min_, walk) if pay else 0.0
            after = cost + inside_here + step / 4.0 + extra
            if after < field.node_costs.get(node, after + 1):
                bank = bank_of_side(banks, near, (direction + 3) % 6)
                _refresh(field, node, after, node_from, step * 0.75, bank)
                counter += 1
                heapq.heappush(queue, (after, counter, node))

    # The hex one leaves from is not paid, and neither is the piece of road
    # made inside to reach the exit: it is the hex one was already in, and
    # the rules price those one **enters**. It is also what keeps the earlier
    # counts exactly where they were.
    log_out(departure, start_atom(banks, water, departure, departure_bank,
                                     orientation),
         cost_of(departure) or 1, 0.0, 0.0,
         (departure[0], departure[1], DEPARTURE), pay=False)

    while queue:
        cost, _order, current = heapq.heappop(queue)
        if arrival is not None and (current[0], current[1]) == tuple(arrival):
            break
        if cost > field.node_costs.get(current, cost):
            continue
        here = (current[0], current[1])
        cost_here = cost_of(here)
        if cost_here is None:
            continue
        log_out(here, edge[current[2]], cost_here, cost_here * 0.75, cost,
             current)
    return field


def path(departure: tuple[int, int], arrival: tuple[int, int], cost_of,
             orientation: str = "pointy", inside=None, passage=None,
             banks: dict | None = None, departure_bank: int = 0,
             crossings: dict | None = None,
             water: dict | None = None) -> list[tuple[int, int]] | None:
    """The cheapest course between two hexes, arrival included.

    Cheapest in *travel activities*, not in number of hexes: passing through
    three plains hexes costs less than two swamp ones, and the party goes
    that way.
    """
    if departure == arrival:
        return [departure]
    field = cost_field(departure, cost_of, orientation, inside, arrival,
                        passage, banks, departure_bank, crossings, water)
    return field.course(departure, arrival)


def shore_atoms(faces, orientation: str = "pointy") -> list:
    """For every shore of the hex, its atoms.

    **The faces** are asked, not `atoms.provinces`: the shore number the
    browser sends back and the one written in the cells come from
    `faces_of`, and the correspondence must be that one, not one resembling it.
    """
    outside = [set() for _ in (faces or ())]
    if not faces:
        return outside
    for number, piece in enumerate(atoms_mod.atoms(orientation)):
        which = sections.face_of_point(faces, piece.point)
        if which is not None and 0 <= which < len(outside):
            outside[which].add(number)
    return outside


def _shores_per_waypoint(course, nodes):
    """The shores touched at every waypoint of the course, from the drawn nodes.

    `None` if the nodes do not tell this course: then the road was not drawn
    inside the hexes, and the shortest is taken.
    """
    if not nodes:
        return None
    groups: list = []
    for entry in nodes:
        try:
            col, row, bank = int(entry[0]), int(entry[1]), int(entry[2])
        except (TypeError, ValueError, IndexError):
            return None
        if groups and groups[-1][0] == (col, row):
            groups[-1][1].append(bank)
        else:
            groups.append(((col, row), [bank]))
    if [g[0] for g in groups] != [tuple(c) for c in course]:
        return None
    return [g[1] for g in groups]


def atom_count(course, banks, water, crossings, orientation: str, cost_of,
                  nodes=None, final_spot=None, departure_bank: int = 0) -> tuple:
    """The count of a course **by atoms**: how much more every waypoint costs, and
    which atoms one passes through.

    It is the count the browser makes while you drag (`legCost`) and the
    server redoes when you let go, with the same rule: one enters a hex from
    a side, touches the shores the hand touched in the order it touched them,
    and leaves by the side leading to the next hex — or stops in the aimed
    piece. Every atom entered is a quarter. A hex cut straight makes four
    atoms, i.e. the cost of the rules, and the «more» is everything beyond.

    Returns `(rings, stretches)`: `rings` is `{(col, row): extra activities}`
    as `rings_on_course` has always given it; `stretches` is `{position:
    [atoms]}` for the waypoints in a cut hex, and serves the drawing. A
    waypoint one cannot reach — the aimed shore is across the water and there
    is no way through — is in `rings` with `None`, and the caller says so.

    The departure hex is not paid, not even the piece of road made inside: it
    is the one one was already in. With one exception, which is the journey
    **inside** the departure hex: one goes from one shore to the other
    without leaving. There is no hex one enters there, and the only thing to
    pay is the road — the atoms crossed, a quarter each, from the point one
    is at to the aimed piece. Before, it could not be done: a journey was at
    least two hexes, and to change shore at home one had to leave and come
    back.
    """
    steps = [tuple(c) for c in (course or [])]
    rings: dict = {}
    stretches: dict = {}
    if len(steps) == 1 and final_spot is not None:
        here = steps[0]
        cost = cost_of(here)
        cuts = stretches_of(banks, water, here)
        closed = atoms_mod.closed_by_stretches(cuts, orientation)
        if cost is None or not closed:
            return rings, stretches
        openings = openings_of(here, banks, water, crossings, cost_of, orientation)
        faces = (banks or {}).get(here) or ()
        shores = shore_atoms(faces, orientation) if faces else []
        per_waypoint = _shores_per_waypoint(steps, nodes)
        waypoints: list = []
        if per_waypoint is not None and len(faces) > 1:
            for bank in per_waypoint[0]:
                if 0 <= bank < len(shores) and (not waypoints or waypoints[-1] != bank):
                    waypoints.append(bank)
        sets = [shores[r] for r in waypoints]
        from_atom = start_atom(banks, water, here, departure_bank, orientation)
        destination = atoms_mod.atom_of_point(tuple(final_spot), orientation)
        outcome = atoms_mod.course_by_waypoints(closed, openings, from_atom, sets,
                                          destination, cost / 4.0, orientation,
                                          constrained=bool(sets))
        if outcome is None and sets:
            outcome = atoms_mod.course_by_waypoints(closed, openings, from_atom, [],
                                              destination, cost / 4.0, orientation)
        if outcome is None:
            rings[here] = None
            return rings, stretches
        walk, touched_atoms = outcome
        stretches[0] = touched_atoms
        if walk > 1e-9:
            rings[here] = round(walk, 6)
        return rings, stretches
    if len(steps) < 2:
        return rings, stretches
    edge = atoms_mod.edge_atoms(orientation)
    per_waypoint = _shores_per_waypoint(steps, nodes)
    for spot in range(1, len(steps)):
        here, before = steps[spot], steps[spot - 1]
        neighbours_before = hexgrid.neighbours(before[0], before[1], orientation)
        try:
            entry_ = (neighbours_before.index(here) + 3) % 6
        except ValueError:
            break                      # the course jumps: nothing to price
        cost = cost_of(here)
        if cost is None:
            continue
        cuts = stretches_of(banks, water, here)
        closed = atoms_mod.closed_by_stretches(cuts, orientation)
        last = spot == len(steps) - 1
        if not closed:
            continue                   # whole hex: it costs what it costs
        openings = openings_of(here, banks, water, crossings, cost_of, orientation)
        faces = (banks or {}).get(here) or ()
        shores = shore_atoms(faces, orientation) if faces else []
        waypoints: list = []
        if per_waypoint is not None and len(faces) > 1:
            # All the shores touched, the first included, in order, once in a
            # row: the road is constrained to pass through those and no other
            # in between — it is the tour the hand made.
            for bank in per_waypoint[spot]:
                if 0 <= bank < len(shores) and (not waypoints or waypoints[-1] != bank):
                    waypoints.append(bank)
        sets = [shores[r] for r in waypoints]
        if last:
            destination = (atoms_mod.atom_of_point(tuple(final_spot), orientation)
                    if final_spot is not None else None)
        else:
            neighbours_here = hexgrid.neighbours(here[0], here[1], orientation)
            try:
                destination = edge[neighbours_here.index(steps[spot + 1])]
            except ValueError:
                break
        outcome = atoms_mod.course_by_waypoints(closed, openings, edge[entry_],
                                          sets, destination, cost / 4.0,
                                          orientation, constrained=bool(sets))
        if outcome is None and sets:
            # The nodes tell a tour that from this side cannot be made (the
            # first shore is not the entry one, or the bridge is not there):
            # the constraint is dropped, and the shortest way counts.
            outcome = atoms_mod.course_by_waypoints(closed, openings, edge[entry_],
                                              [], destination, cost / 4.0,
                                              orientation)
        if outcome is None:
            rings[here] = None
            continue
        walk, touched_atoms = outcome
        stretches[spot] = touched_atoms
        extra = max(0.0, round(walk - cost * 0.75, 6))
        if extra > 1e-9:
            rings[here] = round((rings.get(here) or 0.0) + extra, 6)
    return rings, stretches


def rings_on_course(course, banks, water, crossings, orientation: str, cost_of,
                     departure_bank: int = 0, nodes=None) -> dict:
    """How much **more** every hex of the course costs, because of the water.

    It is the detour count: entering a hex costs what the rules say, but if
    the water forces you to coast along instead of cutting straight that
    extra piece of road is paid, a quarter for every atom beyond the fourth.
    The bridges and fords the course uses are in it too, because they already
    sit in the count inside the hex: adding them again would charge them
    twice.

    The first hex and the last always give zero, for two different reasons:
    the first is not entered — one was already there — and in the last one
    stops, and stopping pays it in full anyway.

    `nodes` are the shores the hand touched, when the road was drawn: the
    count goes through those, in order, and every extra atom is paid
    (`atom_count`). It does not add up «to the centroid» of every shore — it
    was tried, and it made a 4½ hex cost 6 — but looks for the shortest
    course **touching** those shores: a bridge on your road stays free, a
    bridge out of the way is paid for what it is.

    Returns `{(col, row): extra activities}`, and for a course coasting along
    nothing it is empty.
    """
    steps = [tuple(c) for c in (course or [])]
    if len(steps) < 3:
        return {}
    # The last waypoint is not counted here — one stops, and stopping pays in
    # full — and the atom count prices it only if told where: without a final
    # spot it gives zero, which is what this function has always said.
    rings, _stretches = atom_count(steps, banks, water, crossings, orientation,
                                  cost_of, nodes)
    return {coord: extra for coord, extra in rings.items()
            if extra and coord != steps[-1]}


def inner_on_course(course, banks: dict, crossings: dict, orientation: str,
                        cost_of, departure_bank: int = 0) -> dict:
    """The crossings inside a hex this course must use.

    The course is a row of hexes — that is how players call it — and a shore
    change inside a hex is not seen there. But it is paid, and the journey
    count must know it. Here the course is walked again on the real graph,
    node by node: where to go on one must pass to the other shore, that hex
    is marked with what it costs.

    Returns `{(col, row): (kind, cost)}`. Empty when there are no inner
    crossings, which is almost always.
    """
    if not crossings or len(course or []) < 1:
        return {}
    outside: dict = {}
    node = node_of(banks, tuple(course[0]), departure_bank)
    for next_ in course[1:]:
        next_ = tuple(next_)
        if any(vic == next_
               for _n, vic in steps_from(node, orientation, banks)):
            node = next(n for n, vic in steps_from(node, orientation, banks)
                        if vic == next_)
            continue
        for other_one, chain in inner_jumps(node, banks, crossings):
            forward = next((n for n, vic in steps_from(other_one, orientation, banks)
                           if vic == next_), None)
            if forward is None:
                continue
            here = (node[0], node[1])
            # A chain of crossings is paid **in full**: two bridges are two
            # passages, and the kind reported is the most expensive, because
            # it is the one the table must know about.
            cost = sum(inner_cost(entry, here, cost_of) for entry in chain)
            kinds = [(entry.get("kind") or "bridge") for entry in chain]
            kind = "ford" if "ford" in kinds else (kinds[0] if kinds else "bridge")
            outside[here] = (kind, cost)
            node = forward
            break
        else:
            return outside          # no way through there: the rest makes no sense
    return outside


def nodes_on_course(course, banks: dict, crossings: dict | None,
                     orientation: str, departure_bank: int = 0) -> list[tuple]:
    """The course as whoever walks really walks it: node by node.

    A course is a row of hexes — that is how players call it — and which
    shore one passes on is not seen there. The graph however knows, and
    walking it again returns the nodes `(col, row, bank)`: one per hex,
    **two** for the one where one changes shore passing an inner bridge.

    It serves the drawing. An arrow drawn from center to center, in a hex the
    river cuts, passes over it even when the journey does not cross it — and
    when it really crosses it one does not see where. With the nodes both are
    seen: the road stays on its side, and the bridge is that elbow going from
    one shore to the other.

    When the course does not hold — there is no way through there — what was
    understood up to there is returned: a piece of drawn road is better than
    nothing, and the real count is done by another function.
    """
    steps = [tuple(c) for c in (course or [])]
    if not steps:
        return []
    node = node_of(banks, steps[0], departure_bank)
    outside = [node]
    for next_ in steps[1:]:
        forward = next((n for n, vic in steps_from(node, orientation, banks)
                       if vic == next_), None)
        if forward is None and crossings:
            for other_one, chain in inner_jumps(node, banks, crossings):
                candidate = next(
                    (n for n, vic in steps_from(other_one, orientation, banks)
                     if vic == next_), None)
                if candidate is not None:
                    # An elbow for every shore touched: the arrow must pass
                    # where one really passes, and with two bridges those are
                    # two bends, not a straight shortcut.
                    for step in _shore_chain(node, other_one, banks, crossings,
                                                   len(chain)):
                        outside.append(step)
                    forward = candidate
                    break
        if forward is None:
            return outside
        node = forward
        outside.append(node)
    return outside


def _shore_chain(from_, a, banks: dict, crossings: dict, jumps: int) -> list:
    """The shores touched going from one to the other inside the same hex.

    It serves the drawing: the arrow must bend in each, or with two bridges
    it would cut straight over the piece in between — which is precisely the
    lie the elbows were put there not to tell.
    """
    if jumps <= 1:
        return [a]
    # The course is redone backwards: from the destination one goes back one
    # hop at a time, taking each time a shore nearer to the departure.
    road = [a]
    how_many = {n: len(c) for n, c in inner_jumps(from_, banks, crossings)}
    how_many[tuple(from_)] = 0
    here = a
    while how_many.get(here, 0) > 1:
        before = next((n for n, _v in inner_passages(here, banks, crossings)
                      if how_many.get(n, 99) == how_many[here] - 1), None)
        if before is None:
            break
        road.append(before)
        here = before
    road.reverse()
    return road


def banks_on_course(course, banks: dict, crossings: dict | None,
                     orientation: str, departure_bank: int = 0) -> list[int]:
    """The shore one enters on in every hex of the course, one per hex."""
    nodes = nodes_on_course(course, banks, crossings, orientation, departure_bank)
    outside: list[int] = []
    last = None
    for col, row, bank in nodes:
        # The elbow of a bridge is the same hex twice **in a row**: there the
        # hex is one. Further on the same hex may come back — a course may
        # cross itself — and that is a real waypoint.
        if last == (col, row):
            continue
        last = (col, row)
        outside.append(bank)
    return outside


# ------------------------------------------------------------------- plan
@dataclass
class Waypoint:
    col: int
    row: int
    name: str = ""
    category: Category = field(default_factory=lambda: Category(None))
    roads: bool = False
    cost: int | None = None
    border: str = ""             # the kind of side crossed to enter it
    border_cost: int = 0        # and how much more it cost
    inner_one: str = ""             # the crossing used *inside* the hex
    inner_cost: int = 0        # and how much it cost
    ring: float = 0.0             # the extra for coasting along the water inside


@dataclass
class Plan:
    """A travel proposal: it is looked at, discussed, and only then applied."""

    waypoints: list[Waypoint] = field(default_factory=list)
    total_cost: int = 0
    day_activities: float = 1.0
    speed_m: float = 0.0
    speed_source: str = ""
    forced_march: bool = False
    march_days: int = 0
    unknowns: int = 0               # waypoints whose terrain is unknown
    # When the group leaves scattered the days do not follow from the cost of
    # a single leg: it is the rendezvous count that says them, and we write
    # them here.
    forced_days: int | None = None
    # What is paid before the first waypoint: the ford or the detour inside
    # the departure hex. It is in the total, and must be frozen with the
    # waypoints.
    departure_cost: float = 0.0
    warnings: list[str] = field(default_factory=list)
    blocking: list[str] = field(default_factory=list)

    @property
    def possible(self) -> bool:
        # A journey without waypoints can be a journey: the one from one
        # shore to the other of the same hex, which costs the road and no hex;
        # or that of a group whose meeting point is the destination itself —
        # the common road is zero long, but the approach branches are the
        # journey, and the days are said by the rendezvous.
        return ((bool(self.waypoints) or self.total_cost > 0
                 or self.forced_days is not None)
                and not self.blocking)

    @property
    def max_estimate(self) -> bool:
        """True if the count is a ceiling and not a measurement.

        A single never-explored hex is enough: that one we count at the worst
        cost, and from there on the total is «at most so much», not «so much».
        """
        return self.unknowns > 0

    @property
    def days(self) -> int:
        """Days rounded up: half a day is spent outdoors anyway."""
        if self.forced_days is not None:
            return self.forced_days
        if self.day_activities <= 0:
            return 0
        return math.ceil(self.total_cost / self.day_activities)


def available_activities(speed_m: float, forced_march: bool = False) -> float:
    """Activities per day, with the optional extra activity from forced march.

    The rules grant forced march *one extra Travel activity*: it does not
    increase the other exploration activities.
    """
    base = activities_per_day(speed_m)
    if forced_march:
        base += float(TRAVEL["forced_march"]["extra_activities"])
    return base


# ------------------------------------------------------ how far one goes
#
# Two different tables, and better not to confuse them. Travel between hexes
# is counted in *activities per day* (`activities_per_day`): a hex is a day
# and a half of walking, and kilometres do not enter the count. The Travel
# Speed table answers another question — «how fast do we go» — and it is the
# one needed when the table wants the number in kilometres, or when the GM
# asks for a check every hour for a stretch to swim or climb and reads the
# progress on the same row.
TRAVEL_SPEED = rules.derived(lambda: TRAVEL["travel_speed"])


def travel_speed(speed_m: float) -> dict | None:
    """Metres per minute, km per hour and km per day for that Speed.

    The nine rows of the table are read as written. For the Speeds the table
    skips — 13.5 and 16.5 metres — and those beyond 18, one continues with the
    table's own proportion: it is the factor reproducing all nine rows
    exactly, not an added rule.
    """
    if not speed_m or speed_m <= 0:
        return None
    for row in TRAVEL_SPEED["table"]:
        if abs(float(row["metres"]) - float(speed_m)) < 1e-9:
            return {**row, "from_table": True}
    factor = float(TRAVEL_SPEED["between_the_lines"]["km_hour_per_metre"])
    hours = float(TRAVEL_SPEED["hours_per_day"])
    km_hour = speed_m * factor
    return {"metres": speed_m, "metres_per_minute": speed_m * 10,
            "km_hour": km_hour, "km_day": km_hour * hours,
            "from_table": False}


def sustainable_march_days(con_mod: list[int]) -> int:
    """Days of forced march before becoming Fatigued: the lowest Con."""
    if not con_mod:
        return 1
    return max(1, min(int(m) for m in con_mod))


def _quarters(value: float) -> str:
    """A number of activities written as a human would read it.

    Costs come in quarters — a quarter of hex per atom — and writing «+0.25
    activities» is true but unreadable. A quarter is a quarter.
    """
    whole_ones, rest = divmod(round(value * 4), 4)
    piece = {0: "", 1: "\u00bc", 2: "\u00bd", 3: "\u00be"}[rest]
    if whole_ones and piece:
        return f"{whole_ones}{piece}"
    return piece or str(whole_ones)


def waypoint_costs(plan: Plan) -> list[float]:
    """What every waypoint costs, frozen at departure: it is what the passing
    day consumes (`daily.waypoint_reached`).

    Waypoint by waypoint: the hex, the side, and the detour inside the hex;
    what is paid before moving (ford or detour in the departure hex) is on
    the first. Before, the detour was not there, and a journey of 2.5
    activities arrived in 2.
    """
    costs = [float(frac.cost or 0) + float(frac.border_cost or 0) + float(frac.ring or 0)
             for frac in plan.waypoints]
    if costs and plan.departure_cost:
        costs[0] += float(plan.departure_cost)
    return costs


def plan_(raw_waypoints, speed_m: float, speed_source: str = "",
              forced_march: bool = False,
              con_mod: list[int] | None = None,
              borders: dict | None = None, departure: tuple[int, int] | None = None,
              sail: bool = False, inner: dict | None = None,
              rings: dict | None = None,
              directions: dict | None = None) -> Plan:
    """Puts together the count of the journey from the course already chosen.

    `raw_waypoints` is the course *excluding* the departure hex: the cost is
    paid on the one entered, so the one one leaves from does not count. Every
    entry is (coordinates, hex, category imposed by the GM).

    `borders` and `departure` serve the sides: the first side crossed is the
    one between the departure hex and the first waypoint, and the departure
    is not in the list. `sails` says whether the group carries a water
    vehicle.

    `directions` is the water route: `{(col, row): "downstream" | "upstream"
    | None}` for the hexes crossed **following** a watercourse instead of
    walking inside them. Where there is an entry that rules, and the terrain
    does not count: whoever goes down the Shrike by boat does not cross the
    swamp, they coast along it.

    `inner` are the crossings *inside* a hex the course uses — a bridge or a
    ford on the river cutting it — in the form `{(col, row): (kind, cost)}`.
    They are added to the total even when they fall on the departure hex,
    which is not in the list of waypoints: one may well start the journey by
    fording the river at home.
    """
    plan = Plan(speed_m=speed_m, speed_source=speed_source,
                  forced_march=forced_march)
    plan.day_activities = available_activities(speed_m, forced_march)

    if speed_m <= 0:
        plan.blocking.append(
            t("travel.no_speed_fill_sheet"))

    before = tuple(departure) if departure is not None else None
    waypoint_coords = {(c, r) for (c, r), _e, _d in raw_waypoints}
    for coord, (inner_kind_, cost_inside) in (inner or {}).items():
        if coord in waypoint_coords or inner_kind_ != "ford" or not cost_inside:
            continue
        # The hex one leaves from is not a waypoint — its terrain is not
        # paid, because one does not enter it — but the river cutting it is
        # forded all the same, and that activity is due.
        plan.total_cost += cost_inside
        plan.departure_cost += cost_inside
        plan.warnings.append(
            t("travel.hex_departing_fording_river", coord=coord[0], coord2=coord[1], cost_inside=cost_inside))
    for coord, ring in (rings or {}).items():
        if coord in waypoint_coords or not ring:
            continue
        # The journey inside the departure hex: no hex entered, only the road
        # from one shore to the other.
        plan.total_cost += ring
        plan.departure_cost += ring
        plan.warnings.append(
            t("travel.hex_moving_from_one", coord=coord[0], coord2=coord[1], quarters=_quarters(ring)))
    for (col, row), hexagon, gm_difficulty in raw_waypoints:
        if directions is not None and (col, row) in directions:
            cost, category = current_cost(directions[(col, row)], gm_difficulty)
        else:
            cost, category = travel_cost(hexagon or {}, gm_difficulty, sail)
        # The side between the previous waypoint and this one: a river to ford
        # costs, one without a bridge cannot be passed at all.
        side_kind, extra = "", 0
        if borders and before is not None:
            entry = borders.get(hexgrid.border_key(before, (col, row)))
            if entry is not None:
                side_kind = entry.get("kind") or ""
                extra = border_cost(before, (col, row), borders, sail)
        inner_kind, inner_cost = (inner or {}).get((col, row), ("", 0))
        plan.waypoints.append(Waypoint(
            col=col, row=row, name=(hexagon or {}).get("name") or "",
            category=category, roads=bool((hexagon or {}).get("roads")),
            cost=cost, border=side_kind, border_cost=extra or 0,
            inner_one=inner_kind, inner_cost=inner_cost))
        if extra is None:
            plan.blocking.append(
                t("travel.hex_border_party_has", col=col, row=row, border_name=border_name(side_kind)))
        elif extra:
            plan.total_cost += extra
            plan.warnings.append(
                t("travel.hex_border_activities", col=col, row=row, lower=border_name(side_kind).lower(), extra=extra))
        before = (col, row)
        ring = (rings or {}).get((col, row), 0)
        if ring:
            plan.total_cost += ring
            plan.waypoints[-1].ring = float(ring)
            if inner_kind == "ford":
                plan.warnings.append(
                    t("travel.hex_river_crossing_forded", col=col, row=row, quarters=_quarters(ring)))
            else:
                plan.warnings.append(
                    t("travel.hex_water_forces_one", col=col, row=row, quarters=_quarters(ring)))
        elif inner_kind == "ford" and inner_cost:
            # A ford the count inside the hex did not see: it happens when the
            # course arrives at or leaves from there and the detour is not
            # measured.
            plan.total_cost += inner_cost
            plan.waypoints[-1].ring = float(inner_cost)
            plan.warnings.append(
                t("travel.hex_river_crossing_forded_2", col=col, row=row, inner_cost=inner_cost))
        if cost is None:
            plan.blocking.append(t("travel.hex", col=col, row=row, reason=category.reason))
        else:
            plan.total_cost += cost
        if category.is_unknown:
            plan.unknowns += 1
        elif category.is_uncertain:
            plan.warnings.append(t("travel.hex_now_counts", col=col, row=row, reason=category.reason, name=category.name))

    if plan.unknowns:
        unknown_cost = CATEGORIES[WORST]["cost"]
        how_many = plan.unknowns
        hexes = tn("common.hex_word", how_many)
        explored = (t("travel.has_never_been_explored") if how_many == 1
                     else t("travel.have_never_been_explored"))
        plan.warnings.append(
            t("travel.path_counted_worst_cost", how_many=how_many, hexes=hexes, explored=explored, unknown_cost=unknown_cost, lower=CATEGORIES[WORST]['name'].lower())
        )

    if forced_march:
        sustainable = sustainable_march_days(con_mod or [])
        plan.march_days = sustainable
        plan.warnings.append(
            t("travel.forced_march_travel_activities", extra_activities=TRAVEL['forced_march']['extra_activities'], sustainable=sustainable, v='day' if sustainable == 1 else 'days', sustainable_days=TRAVEL['forced_march']['sustainable_days'], beyond=TRAVEL['forced_march']['beyond']))
        if plan.possible and plan.days > sustainable:
            plan.warnings.append(
                t("travel.journey_lasts_days_more", days=plan.days, sustainable=sustainable))

    if speed_m and activities_per_day(speed_m) < 1:
        plan.warnings.append(
            t("travel.this_speed_more_than"))
    return plan


# ----------------------------------------------------------- water routes
def route_field(network, currents: dict, departure, orientation: str = "pointy",
                scale: int = 1, departure_node=None) -> tuple:
    """All the water reachable from where the boat is, in a single visit.

    It serves the ruler: while you drag, the arrow must already be the water
    one — if the browser reasons on the land field it draws you a road that
    does not exist, and you find out only on letting go.

    What comes out are the **states** of the water journey, not the hexes:
    `(where I am on the water, which hex I am in)`. It is the difference
    between an arrow jumping from one center to the next and one following
    the river: a hex crossed by a bend is not a point, it is a piece of path
    with a shape of its own.

    `scale` serves the ruler, and for a precise reason. A step inside the same
    hex costs nothing — the bend crossing it, the bridge hopping over it —
    and a course made of zero-cost steps **cannot be walked backwards**:
    whoever redoes it going down the distances never goes down, and bounces
    between the same two points. Counting in hundredths and adding a
    hundredth per step, every step costs something: between two roads worth
    the same the one with fewer pieces wins, and the course is always found
    again.

    Returns `(distances, arcs)`: `{state: cost}` and `{(state_a, state_b):
    (weight, direction)}`, both in the requested scale.
    """
    departure = tuple(departure)
    # From **where the boat is**: a junction, not every point of its hex at
    # zero cost. Without a junction (an old boat) the hex still counts.
    if departure_node is not None and departure_node in network.neighbours:
        start_ = [(departure_node, departure)]
    else:
        start_ = [(n, departure) for n in waterways.hex_nodes(network, departure)]
    if not start_:
        return {}, {}
    dists = {state: 0 for state in start_}
    arcs: dict = {}
    seen: set = set()
    queue = [(0, i, state) for i, state in enumerate(start_)]
    heapq.heapify(queue)
    counter = len(start_)
    while queue:
        cost, _n, state = heapq.heappop(queue)
        if state in seen:
            continue
        seen.add(state)
        for next_, direction, real in _water_steps(
                network, currents, state, orientation):
            step_cost_ = real * scale + (1 if scale > 1 else 0)
            arcs[(state, next_)] = (step_cost_, direction)
            new = cost + step_cost_
            if next_ in seen:
                continue
            if next_ in dists and dists[next_] <= new:
                continue
            dists[next_] = new
            heapq.heappush(queue, (new, counter, next_))
            counter += 1
    return dists, arcs


# How much a water stretch counts, compared with the time it takes to cross a
# whole hex. A short stretch — a side of the hex, or a radius from the edge to
# the center — is half; a stretch joining two non-adjacent sides crosses the
# cell, and is worth one. It is not a rule of the rulebook, which does not
# measure watercourses inside a hex: it is the table's way of giving every
# piece of drawing its weight, instead of charging the hex to whoever enters
# — which with a river on the edge does not even say which of the two you
# entered.
QUARTER_STRETCH = 0.25
HALF_STRETCH = 0.5
WHOLE_STRETCH = 1.0

# A boat step is an atom side — a quarter — or a whole hex side, which is
# longer: a half. A chord from side to side is four atom sides, i.e. one
# activity, like crossing the hex on foot.
STRETCH_FACTOR = {"piece": QUARTER_STRETCH, "edge": HALF_STRETCH}


def stretch_cost(arc, direction: str | None) -> float:
    """What sailing a water stretch costs, in Travel activities.

    The direction decides the effort — downriver open terrain, upriver
    difficult — and the shape of the stretch decides how much road it is:
    half a hex or a whole one.
    """
    how_much = STRETCH_FACTOR.get(getattr(arc, "kind", ""), WHOLE_STRETCH)
    return how_much * float(current_cost(direction)[0] or 0)


def _water_steps(network, currents: dict, state, orientation: str) -> list:
    """From a state of the water journey, where one can go and at what price.

    A single place the answer comes from: both the real route and the field
    the ruler receives use it, and if they answered in two different ways the
    dragged arrow and the confirmed journey would tell two stories.
    """
    node, here = state
    steps = []
    for other, arc in (network.neighbours.get(node, ()) if node is not None else ()):
        # Inside a lake there is no current to go along with: still water, and
        # it counts as open terrain. A direction marked there would make no
        # sense and is not even looked at.
        direction = ("lake" if getattr(arc, "lake", False)
                 else waterways.step_direction(currents, node, other, arc))
        price = stretch_cost(arc, direction)
        # Every stretch costs what it is long, not «the hex you enter».
        # Before, one paid on entry, and with a river running on the edge
        # between two cells one does not even know which of the two you
        # entered: the count changed depending on how it had been drawn, and
        # the arrow seemed to have gone mad. The stretch instead is one thing,
        # and it is measured.
        # A stretch on the edge belongs to **two** hexes, and sailing it one
        # can stay on this side or pass to the other: it is the same water.
        # Before, one stayed by force where one was — it served not to be
        # charged the hex twice — and the consequence was that with a border
        # river in the next cell one did not get there at all. Now the price
        # belongs to the stretch, not to the hex, and the choice can be left
        # open.
        neighbours = set(hexgrid.neighbours(here[0], here[1], orientation)) | {here}
        for after in arc.hexes:
            if after in neighbours:
                steps.append(((other, after), direction, price))
    return steps


def route_plan(road: list, steps: list, speed_m: float,
                   speed_source: str = "", forced_march: bool = False,
                   con_mod: list[int] | None = None) -> Plan:
    """The count of a water journey, **stretch by stretch**.

    It does not go through `plan_`, and it is no shortcut: that one counts the
    hexes one enters, and a river running on the edge between two cells does
    not say which of the two you entered. Here what is sailed is counted —
    every stretch is worth half a hex or a whole one according to its shape,
    and what it costs is said by the direction of the current.

    The waypoints stay one per hex, because that is how a journey is read and
    how a marker is moved: the stretches sailed inside the same hex add up
    into a single waypoint.
    """
    plan = Plan(speed_m=speed_m, speed_source=speed_source,
                  forced_march=forced_march)
    plan.day_activities = available_activities(speed_m, forced_march)
    if speed_m <= 0:
        plan.blocking.append(
            t("travel.no_speed_fill_sheet"))
    if len(road) < 2:
        return plan

    without_direction = 0
    upstream_of = 0
    in_lake = 0
    # Every step ends in a hex: that is where what it costs is added up.
    per_waypoint: list[list] = []
    for index, (direction, price) in enumerate(steps):
        after = road[index + 1][1]
        if direction == "lake":
            in_lake += 1
        elif direction == "upstream":
            upstream_of += 1
        elif direction is None and price:
            # A zero-cost step is not a stretch: it is entering or leaving
            # still water staying in the same hex, and has no direction to
            # mark.
            without_direction += 1
        if per_waypoint and per_waypoint[-1][0] == after:
            per_waypoint[-1][1] += price
        else:
            per_waypoint.append([after, price, direction])

    for coord, price, direction in per_waypoint:
        category = current_category(direction)
        plan.waypoints.append(Waypoint(col=coord[0], row=coord[1],
                                 category=category, cost=price))
        plan.total_cost += price
    # Half an activity does not exist on the sheet: what is really paid is the
    # whole activity that half falls in.
    plan.total_cost = math.ceil(plan.total_cost - 1e-9)

    if in_lake:
        plan.warnings.append(
            f"{in_lake} " + (t("travel.stretch_crosses") if in_lake == 1
                             else t("travel.stretches_cross"))
            + t("travel.still_water_lake_there"))
    if upstream_of:
        plan.warnings.append(
            f"{upstream_of} " + (t("travel.stretch_gone_up") if upstream_of == 1
                             else t("travel.stretches_gone_up"))
            + t("travel.against_current_rules_give"))
    if without_direction:
        plan.warnings.append(
            f"{without_direction} " + (t("travel.stretch_has_no") if without_direction == 1
                                 else t("travel.stretches_have_no"))
            + t("travel.marked_direction_water_without"))

    if forced_march:
        sustainable = sustainable_march_days(con_mod or [])
        plan.march_days = sustainable
        plan.warnings.append(
            t("travel.forced_march_travel_activities_2", extra_activities=TRAVEL['forced_march']['extra_activities'], sustainable=sustainable, v='day' if sustainable == 1 else 'days'))
    return plan


def route_along(network, currents: dict, states,
                orientation: str = "pointy") -> tuple | None:
    """The route **as it was drawn**, if it is a real route.

    The cheapest count is the one proposed; what the hand drew is another
    thing, and counts more: whoever followed the river with a finger does not
    want to see the road replaced by another costing an hour less. Here that
    one is walked again, one step at a time, and every step is checked to
    really exist — nothing of the browser's count is kept, as for the land
    ruler.

    Returns the same thing as `route_towards`, or None if that road cannot be
    made.
    """
    states = [s for s in states if s is not None]
    if len(states) < 2:
        return None
    road = [states[0]]
    steps = []
    for wanted in states[1:]:
        possible_ones = _water_steps(network, currents, road[-1], orientation)
        chosen_one = next((v for v in possible_ones if v[0] == wanted), None)
        if chosen_one is None:
            # The same junction, counted in another hex. The ruler's field
            # has one cell per state and the adjacencies are symmetric, so
            # the hand can step from a piece inside hex A onto a shared
            # vertex counted in hex B, while the server's steps only lead to
            # that vertex counted in A. The junctions are what the hand drew;
            # which hex the server books them in is its own affair.
            same_node = next((v for v in possible_ones if v[0][0] == wanted[0]), None)
            if same_node is not None and wanted[1] in (
                    set(waterways.node_hexes(wanted[0], orientation)) | {same_node[0][1]}):
                # keep the hand's booking: the junction really touches that hex
                chosen_one = (wanted, same_node[1], same_node[2])
            else:
                chosen_one = same_node
        if chosen_one is None:
            # The requested step does not exist: the drawn road is not valid,
            # and no guess is made about which was meant.
            return None
        road.append(chosen_one[0])
        steps.append((chosen_one[1], chosen_one[2]))
    course = []
    for _node, hexagon in road:
        if not course or course[-1] != hexagon:
            course.append(hexagon)
    directions = {}
    for index in range(1, len(road)):
        if road[index][1] != road[index - 1][1]:
            directions[road[index][1]] = steps[index - 1][0]
    return course, directions, road, steps


def route_towards(network, currents: dict, departure, arrival,
                orientation: str = "pointy", arrival_node=None,
                departure_node=None) -> tuple | None:
    """The cheapest route from the departure hex to the arrival hex.

    Looking for it among the nodes alone is not enough, for a reason seen at
    once on a map: two hexes adjoining along the river **share the
    vertices**, so the node nearest to the arrival may already be a node of
    the departure, and the course would come out zero long. What is looked
    for is not a node: it is the moment the boat **enters** the arrival hex.
    So the state of the journey is the pair `(where I am on the water, which
    hex I am in)`, and one goes on until the second is the destination.

    The cost is the real one, not the number of stretches: staying in the
    same hex costs nothing, entering a new one costs what the direction of
    the current says. So between two roads on the water the one the group
    would pay less comes out, not the one drawn with fewer pieces.

    In a **lake** there is no river to follow, but the points are there all
    the same: the outline, the inside and the cell centers are joined in a
    mesh that is not drawn on the map. The boat goes from one point to the
    next, and every step costs the same. There is no current to go along
    with or up against, and one goes where one wants. There the state has
    `None` in place of the node — one floats, one does not coast along — and
    one re-enters a stretch where the lake touches a river.

    `lakes` is `{(col, row): lake id}`, `inside` says which coordinates are in
    the grid.

    Returns `(the hexes crossed, the direction one enters each with, the
    states crossed)`, or None if one cannot get there by water. The states
    serve to draw it: a route is seen only if it follows the lines, and from
    hex center to hex center it would pass through the fields.
    """
    departure, arrival = tuple(departure), tuple(arrival)
    if departure_node is not None and departure_node in network.neighbours:
        start_ = [(departure_node, departure)]
    else:
        start_ = [(n, departure) for n in waterways.hex_nodes(network, departure)]
    if not start_:
        return None
    if not waterways.hex_nodes(network, arrival):
        return None
    from_where: dict = {state: (None, None, 0.0) for state in start_}
    queue = [(0, i, state) for i, state in enumerate(start_)]
    heapq.heapify(queue)
    seen: set = set()
    counter = len(start_)
    while queue:
        cost, _n, state = heapq.heappop(queue)
        if state in seen:
            continue
        seen.add(state)
        node, here = state
        # `arrival_node` says *where* the arrow stopped, not only in which
        # hex: inside the same hex there are several water points, and on an
        # edge stretch there are two in different cells. Without it, the
        # count redone by the server stopped at another end, and on letting
        # go a journey other than the one being looked at appeared.
        has_arrived = (node == arrival_node if arrival_node is not None
                    else here == arrival)
        if has_arrived and state not in start_:
            road = []
            step = state
            while step is not None:
                road.append(step)
                step = from_where[step][0]
            road.reverse()
            course, directions = [], {}
            for state_here in road:
                if not course or course[-1] != state_here[1]:
                    course.append(state_here[1])
            # The steps with their price, taken from where they were weighed:
            # the journey count is not redone from scratch, or the two answers
            # may diverge — and that is exactly what had happened.
            steps = [(from_where[road[i]][1], from_where[road[i]][2])
                     for i in range(1, len(road))]
            for i in range(1, len(road)):
                if road[i][1] != road[i - 1][1]:
                    directions[road[i][1]] = from_where[road[i]][1]
            return course, directions, list(road), steps
        steps = _water_steps(network, currents, state, orientation)
        for next_, direction, step_cost_ in steps:
            if next_ in seen or next_ in from_where:
                # already seen, or already queued by a road no more expensive:
                # the first out of the queue is the good one, and Dijkstra
                # guarantees it.
                continue
            from_where[next_] = (state, direction, step_cost_)
            heapq.heappush(queue, (cost + step_cost_, counter, next_))
            counter += 1
    return None


# --------------------------------------------------- characters and vehicles
def character_speed(character: dict) -> float:
    """Base Speed plus the bonuses from feats or items, in metres."""
    base = float((character or {}).get("speed_m") or 0.0)
    bonus = float((character or {}).get("speed_bonus_m") or 0.0)
    return max(0.0, base + bonus)


# Where a vehicle goes, derived from how the rules write its Speed. One
# movement per element; the fastest decides, because it is the one the
# vehicle really travels with: the Apparatus of the Octopus walks at 5 feet
# and swims at 40, and it is a water thing.
WHERE_IT_GOES = {"land_": "land", "scalable": "land",
           "swim": "water", "fly": "air"}
WHERE_NAMES = {"land": "travel.where.land", "water": "travel.where.water",
               "air": "travel.where.air"}


def where_name(kind: str) -> str:
    """Where a vehicle goes, as an adjective in the viewer's language."""
    return t(WHERE_NAMES[kind]) if kind in WHERE_NAMES else kind
# The fallback symbol when a vehicle has no uploaded marker. It lives here
# and not in the interface because three different places use it — the map,
# the Transport page, the character sheet — and as long as it was hand-written
# in each, a water vehicle showed as a horse on the map.
WHERE_SYMBOLS = {"land": "🐎", "water": "⛵", "air": "🎈"}


def vehicle_symbol(entry: dict) -> str:
    return WHERE_SYMBOLS.get(vehicle_kind(entry), WHERE_SYMBOLS["land"])


def kind_from_catalogue(vehicle_id_: str) -> str | None:
    """Land, water or air according to the rules page. None if it does not say.

    A wagon has no written Speed — it depends on who tows it — and there the
    app does not guess: it returns None and asks, as it does for the metres.
    """
    choice = best_vehicle_speed(rules.BY_ID["vehicle"].get(vehicle_id_, {}))
    return WHERE_IT_GOES.get(choice[0]) if choice else None


def vehicle_kind(entry: dict) -> str:
    """Where *this* specimen goes: what the table chose, or the catalogue.

    The stable row always wins: a raft may be marked by hand, and the
    catalogue does not know what you built.
    """
    if not entry:
        return "land"
    chosen_one = (entry.get("kind") or "").strip()
    if chosen_one in WHERE_NAMES:
        return chosen_one
    return kind_from_catalogue(entry.get("vehicle") or "") or "land"


def where_it_is(entry: dict):
    """The hex a vehicle is in, or None if it is not on the map."""
    if not entry:
        return None
    col, row = entry.get("hex_col"), entry.get("hex_row")
    if col is None or row is None:
        return None
    return (int(col), int(row))


def atom_of(entry: dict, faces, orientation: str = "pointy") -> int | None:
    """Which atom a marker or a vehicle is in, inside a cut hex.

    `None` for a whole hex: there the atom is not a place one stands in, and
    whoever is there is «in front». Whoever has no written point is on shore
    0, as the map draws it.
    """
    if not faces or len(faces) < 2:
        return None
    x, y = entry.get("pos_x"), entry.get("pos_y")
    point = ((float(x), float(y)) if x is not None and y is not None
             else sections.section_spot(faces, 0))
    if point is None:
        return None
    return atoms_mod.atom_of_point(tuple(point), orientation)


def ascent_blocked(char: dict, vehicle: dict, banks: dict | None = None,
                    orientation: str = "pointy") -> str | None:
    """Why that character cannot board that vehicle. None = they can.

    With `banks` the rule looks **inside** the hex too: one boards only from
    the same atom the vehicle is in. A piece of hex can be as small as an
    atom, and «being in the same hex» no longer means having it in front —
    there may be a river in between.

    A single rule, and it holds for the wagon as for the boat: **one boards
    what is in front of one**. Before, a vehicle was assigned from a
    dropdown, and the wagon appeared next to its owner wherever they were:
    handy to write, and false to play — nobody boards a carriage three hexes
    away.

    The rules say nothing about this, and could not: it is a choice of the
    table on how the vehicles are accounted for. But it is the choice that
    makes the rest true, because it is the one that keeps the vehicle's
    marker and that of whoever travels on it in the same place.
    """
    where = where_it_is(vehicle)
    name = vehicle_name_(vehicle)
    if where is None:
        return (t("travel.not_map_put_hex", name=name))
    if char.get("hex_col") is None or char.get("hex_row") is None:
        return (t("travel.not_map_yet_they", v=char.get('name') or t('travel.whoever_boards')))
    its_own = (int(char["hex_col"]), int(char["hex_row"]))
    # A boat sits on a water junction, and is boarded from every shore
    # touching that point: a corner belongs to three hexes, and from all
    # three one boards. It is the rule that makes a lake the same thing as a
    # river — the bank is a piece of hex touching the water, not «the boat's
    # hex».
    if vehicle_kind(vehicle) == "water":
        node = waterways.vehicle_node(vehicle, orientation)
        if node is not None:
            mine = (its_own, sections.section_of(char, (banks or {}).get(its_own)))
            if mine not in waterways.touching_faces(node, banks or {}, orientation):
                return (t("travel.not_shore_touching_point", v=char.get('name') or t('travel.whoever_boards'), name=name))
            return None
    if its_own != where:
        return (t("travel.one_boards_vehicle_front", v=char.get('name') or t('travel.whoever_boards'), its_own=its_own[0], its_own2=its_own[1], name=name, where=where[0], where2=where[1]))
    faces = (banks or {}).get(its_own)
    if faces and len(faces) > 1:
        own = atom_of(char, faces, orientation)
        its_vehicle = atom_of(vehicle, faces, orientation)
        if own is not None and its_vehicle is not None and own != its_vehicle:
            return (t("travel.are_but_two_different", v=char.get('name') or t('travel.whoever_boards'), name=name, its_own=its_own[0], its_own2=its_own[1]))
    return None


def descent_blocked(vehicle: dict, coord, orientation: str = "pointy",
                     landing_spot=None, banks: dict | None = None,
                     spot=None) -> str | None:
    """Why one cannot land there. None = one can.

    Landing is not the automatic reverse of boarding, and that is why it is
    declared: from a stopped wagon one sets foot wherever around, from a boat
    not. `landing_spot` is the judgement on the place — it says whether that
    hex is land one stands on, or water one drowns in — and it is provided by
    whoever knows the map: here only that it is **the vehicle's or one next
    to it** is checked, because landing is a step, not a journey.
    """
    where = where_it_is(vehicle)
    name = vehicle_name_(vehicle)
    if where is None:
        return t("travel.not_map_there_nowhere", name=name)
    coord = (int(coord[0]), int(coord[1]))
    # From a boat one lands on a shore touching the junction it sits on: the
    # same rule as boarding, the other way round.
    if vehicle_kind(vehicle) == "water":
        node = waterways.vehicle_node(vehicle, orientation)
        if node is not None:
            faces = (banks or {}).get(coord)
            section = 0
            if faces and len(faces) > 1 and spot is not None:
                found_one = sections.face_of_point(faces, tuple(spot))
                section = 0 if found_one is None else int(found_one)
            if (coord, section) not in waterways.touching_faces(
                    node, banks or {}, orientation):
                return (t("travel.from_one_gets_off", name=name, coord=coord[0], coord2=coord[1]))
            if landing_spot is not None:
                why = landing_spot(coord)
                if why:
                    return why
            return None
    neighbours = set(hexgrid.neighbours(where[0], where[1], orientation)) | {where}
    if coord not in neighbours:
        return (t("travel.from_one_does_not", where=where[0], where2=where[1], coord=coord[0], coord2=coord[1]))
    if landing_spot is not None:
        why = landing_spot(coord)
        if why:
            return why
    return None


def crosses_water(entry: dict) -> bool:
    """Whether with this vehicle the water is not a wall.

    It holds for water ones and for those that fly: the rules put them
    together — «If you're flying or traveling on water, almost all hexes are
    open terrain». Following the course of a river instead is boat business,
    and that is looked at by the water journey.
    """
    return vehicle_kind(entry) in ("water", "air")


def swim_speed(character: dict) -> float:
    """The character's Swim Speed, in metres. Zero = does not swim.

    Kept separate from the base Speed and inheriting none of its bonuses: on
    a character sheet they are two different Speeds, and a feat lengthening
    the stride does not lengthen the stroke.
    """
    return max(0.0, float((character or {}).get("swim_speed_m") or 0.0))


def party_swims(characters: list[dict]) -> tuple[bool, str]:
    """Whether the group can pass the water swimming, and the reason for the answer.

    The rules put the Swim Speed next to the vehicle: they are the two ways
    of crossing. The usual rule holds though — the group goes together, and
    goes like its slowest member: if a single one does not swim, they all
    stay on the bank. It is no pedantry, it is the only reading that leaves
    nobody behind without saying so.
    """
    if not characters:
        return False, t("travel.nobody_leaves")
    dry = [p.get("name") or "?" for p in characters
               if not swim_speed(p)]
    if dry:
        how_many = len(dry)
        listing = ", ".join(sorted(dry)[:3]) + ("..." if how_many > 3 else "")
        return False, (t("travel.without_swim_speed", listing=listing) if how_many > 1
                       else t("travel.has_no_swim_speed", listing=listing))
    slowest = min(swim_speed(p) for p in characters)
    return True, (t("travel.everybody_has_swim_speed", slowest=slowest))


def vehicle_name_(entry: dict) -> str:
    """What this specimen is called: the name the table gave it, or the page's."""
    if not entry:
        return "vehicle"
    return entry.get("name") or rules.BY_ID["vehicle"].get(
        entry.get("vehicle"), {}).get("name", "vehicle")


def vehicle_seats(entry: dict) -> tuple[int | None, str]:
    """How many people fit on this vehicle, and where that number comes from.

    Same order as the Speed: first what the table counted, then the page —
    but only when the passengers are a number. Many pages write them in
    words («1 pilot, 20 rowers»), and there no guess is made: None, with the
    reason, and the table decides.
    """
    if not entry:
        return None, ""
    written = entry.get("seats")
    if written not in (None, ""):
        try:
            how_many = int(written)
        except (TypeError, ValueError):
            how_many = 0
        if how_many > 0:
            return how_many, t("travel.seats_by_table")
    catalogue = rules.BY_ID["vehicle"].get(entry.get("vehicle"))
    if catalogue is None:
        return None, t("travel.vehicle_not_catalogue")
    passengers = str(catalogue.get("passengers") or "").strip()
    if passengers.isdigit():
        # The pilot is one more than the passengers: the page counts them
        # separately.
        return int(passengers) + 1, t("travel.from_page_passengers_pilot", passengers=passengers)
    crew = str(catalogue.get("crew") or "").strip()
    how_many = crew.split(" ")[0] if crew else ""
    if passengers in ("", "-", "—", "–") and how_many.isdigit():
        # «Passengers -» is not silence, it is a zero: only the crew fits on
        # the page, and it says so.
        return int(how_many), t("travel.from_page_no_passengers", crew=crew)
    if passengers:
        return None, t("travel.page_writes_count_seats", passengers=passengers)
    return None, t("travel.page_does_not_say")


def speed_from_stable(entry: dict) -> tuple[float | None, str]:
    """How fast a stable vehicle goes, and where that number comes from.

    The order matters: if the table wrote a Speed for that specimen that one
    counts (it is the case of wagons, which go as fast as who tows them).
    Only then is the catalogue looked at. If there is neither, no guess is
    made: None and the reason are returned.
    """
    if entry is None:
        return None, ""
    caption = entry.get("speed_m")
    if caption:
        return float(caption), t("travel.speed_entered_table")
    catalogue = rules.BY_ID["vehicle"].get(entry.get("vehicle"))
    if catalogue is None:
        return None, t("travel.vehicle_not_catalogue")
    best = best_vehicle_speed(catalogue)
    if best is None:
        reason = {
            "towing": t("travel.page_says_speed_slowest"),
            "pilot": t("travel.page_says_speed_pilot"),
        }.get(catalogue.get("speed_depends_on"),
              t("travel.page_no_speed_metres"))
        return None, reason
    kind, metres = best
    return metres, f"{catalogue['name']}: {kind} {units.fmt(metres)}"


# The two notes the app repeats every time a vehicle enters the count. The
# first applies to whoever travels on it, the second to a whole group
# boarding it: they are two readings by the table, not two rules, and the
# second is bigger than the first.
VEHICLE_NOTE = "travel.vehicle_note"
EDGE_NOTE = "travel.edge_note"


def compose_speed(characters: list[dict],
                     vehicles: dict[str, dict] | None = None) -> tuple[float, str, list[str]]:
    """The Speed of the group that leaves, with the explanation and the warnings.

    The rule of the rulebook always holds — the group goes like its slowest
    member — but a character travelling on a vehicle moves at the vehicle's
    Speed. This last step the rules do not write in Hexploration: it is a
    reading by the table, and the app says so every time instead of passing
    it off as a rule.
    """
    vehicles = vehicles or {}
    warnings: list[str] = []
    entries: list[tuple[str, float]] = []
    used_a_vehicle = False

    for char in characters:
        name = char.get("name") or "?"
        stable_entry = vehicles.get(char.get("stable_id") or "")
        if stable_entry is not None:
            label = stable_entry.get("name") or rules.BY_ID["vehicle"].get(
                stable_entry.get("vehicle"), {}).get("name", "vehicle")
            if not stable_entry.get("available"):
                warnings.append(t("travel.marked_unavailable_stable_so", name=name, label=label))
            else:
                metres, reason = speed_from_stable(stable_entry)
                if metres is None:
                    warnings.append(t("travel.has_no_speed_metres", name=name, label=label, reason=reason))
                else:
                    used_a_vehicle = True
                    entries.append((f"{name} · «{label}» {units.fmt(metres)}", metres))
                    continue
        entries.append((f"{name} {units.fmt(character_speed(char))}",
                     character_speed(char)))

    if not entries:
        return 0.0, "", warnings
    minimum = min(v for _n, v in entries)
    slowest = next(n for n, v in entries if v == minimum)
    source = t("travel.slowest_of_party", slowest=slowest).replace(".", ",")
    if used_a_vehicle:
        warnings.append(t(VEHICLE_NOTE))
    return minimum, source, warnings


def party_vehicles(characters: list[dict],
                      vehicles: dict[str, dict] | None = None) -> list[dict]:
    """The vehicles the travellers carry along, one per specimen.

    A vehicle is in a single place: if two characters have the same stable
    row it is the same wagon, and counts once.
    """
    vehicles = vehicles or {}
    found_items: dict[str, dict] = {}
    for char in characters:
        key = char.get("stable_id") or ""
        entry = vehicles.get(key)
        if entry is not None and key not in found_items:
            found_items[key] = entry
    return list(found_items.values())


def party_sails(characters: list[dict], vehicles: dict[str, dict] | None = None,
                     aboard: bool = False) -> tuple[bool, str]:
    """Whether the group can cross the water, and the reason for the answer.

    The rules say that to travel on water a vehicle or a Swim Speed is
    needed. Here only the vehicle is looked at, and with the same fences that
    hold for the group pace: the vehicle must be available and have room for
    everyone, otherwise someone would stay on the bank.

    They must already be «everyone aboard»: boarding a boat is a choice the
    table makes, not something the app decides on its own because it suits
    the path.
    """
    if not characters:
        return False, t("travel.nobody_leaves")
    # Swimming comes before the vehicle: whoever swims needs to board
    # nothing, and asking them to embark to cross a river would be the app
    # imposing a passage the rules do not ask for.
    swimming, why_swim = party_swims(characters)
    if swimming:
        return True, why_swim
    if not aboard:
        # If someone swims, the real reason is not «you are not aboard»: it is
        # that one of you does not swim, and they have a name. Saying it
        # generically would force one to reopen the sheets one by one to
        # understand who is missing.
        if any(swim_speed(p) for p in characters):
            return False, (t("travel.not_everybody_can_swim", why_swim=why_swim))
        return False, (t("travel.party_not_aboard_cross"))
    vehicles_by_id = [v for v in party_vehicles(characters, vehicles)
             if crosses_water(v)]
    if not vehicles_by_id:
        return False, (t("travel.none_travellers_brings_along"))
    seats = 0
    for entry in vehicles_by_id:
        label = vehicle_name_(entry)
        if not entry.get("available"):
            continue
        how_many, why = vehicle_seats(entry)
        if how_many is None:
            return False, (t("travel.not_known_how_many_2", label=label, why=why))
        seats += how_many
    if not seats:
        return False, t("travel.water_vehicle_not_available")
    if seats < len(characters):
        return False, (t("travel.seats_water_vehicle_are", seats=seats, len=len(characters)))
    return True, t("travel.party_aboard_water_vehicle")


def group_pace(characters: list[dict], vehicles: dict[str, dict] | None = None,
                    aboard: bool = False) -> tuple[float, str, list[str]]:
    """The Speed the group proceeds at *as one*, and where it comes from.

    With `aboard` false the rule of the rulebook holds and nothing else: the
    group goes like its slowest member. With `aboard` true the table decided
    they all board the vehicles they carry along, and then — if the seats are
    enough for everyone — one goes at the Speed of the slowest vehicle among
    those used.

    Two fences, because neither is said by the rules and both would be odd to
    suffer: if the seats are not enough nobody boards and one goes back to
    the normal rule, and if the vehicle is slower than the group on foot one
    goes on foot — a heavy wagon does not force the party to slow down.

    That a passenger moves at the vehicle's Speed is a reading by the table,
    not a written rule: Hexploration does not speak of vehicles. The warning
    says so every time.
    """
    on_foot, source, warnings = compose_speed(characters, vehicles)
    if not aboard or not characters:
        return on_foot, source, warnings

    vehicles_by_id = party_vehicles(characters, vehicles)
    if not vehicles_by_id:
        warnings.append(t("travel.none_travellers_brings_along_2"))
        return on_foot, source, warnings

    # `compose_speed` has already had its say on every vehicle someone
    # carries along: repeating it on the group's behalf would be the same
    # sentence twice.
    def already_said(label: str) -> bool:
        return any(f"«{label}»" in a for a in warnings)

    total_seats, used_items = 0, []
    for entry in vehicles_by_id:
        label = vehicle_name_(entry)
        if not entry.get("available"):
            if not already_said(label):
                warnings.append(t("travel.not_available_stable_nobody", label=label))
            continue
        metres, reason = speed_from_stable(entry)
        if metres is None:
            if not already_said(label):
                warnings.append(t("travel.has_no_speed_metres_2", label=label, reason=reason))
            continue
        how_many, why = vehicle_seats(entry)
        if how_many is None:
            warnings.append(t("travel.not_known_how_many", label=label, why=why))
            return on_foot, source, warnings
        total_seats += how_many
        used_items.append((label, metres, how_many))

    if not used_items:
        return on_foot, source, warnings
    if total_seats < len(characters):
        warnings.append(t("travel.seats_are_not_enough", total_seats=total_seats, len=len(characters)))
        return on_foot, source, warnings

    label, metres, _q = min(used_items, key=lambda u: u[1])
    if metres <= on_foot:
        warnings.append(t("travel.m_no_faster_than", label=label, how_much=units.fmt(metres)))
        return on_foot, source, warnings

    names = ", ".join(f"«{e}»" for e, _m, _q in used_items)
    how_much = units.fmt(metres)
    edge_source = (t("travel.everybody_aboard_m_seats", names=names, how_much=how_much, total_seats=total_seats, len=len(characters)))
    # The single's note is already said by the group's, and louder.
    warnings = [a for a in warnings if a != t(VEHICLE_NOTE)] + [t(EDGE_NOTE)]
    return metres, edge_source, warnings


# ------------------------------------------------------- travelling together
#
# The problem: k characters at different points, a single destination, and
# the rule that a group goes at the Speed of its slowest member. Where is it
# worth meeting, and is it really worth it?
#
# It is the *optimal meeting point* on a weighted graph — in the literature
# the median/center problem of a graph, or the rendezvous problem. The form
# we need is the «minimax plus tail» one: fixed a rendezvous hex m,
#
#     T(m) = max_i [ cost(p_i -> m) / activities_i ]  +  cost(m -> D) / common_activities
#            \________ whoever arrives last ________/   \___ then together, at the pace
#                                                            they have together ___/
#
# `common_activities` is normally the pace of the slowest member, which is
# the rule. But the group can also proceed at a pace none of its members
# would keep alone — it is the case of the wagon, when they all get on — and
# then that number comes from outside (`party_pace`). It changes the result
# more than it seems: as long as one goes like the slowest, meeting never
# gains anyone a day (T(m) >= T(D) for every m, and T(D) is the time they take
# going each on their own), and the rendezvous only serves to stay together.
# As soon as the united group is quicker, meeting becomes a real gain, and
# the rendezvous moves on its own towards whoever fell behind: it is the
# wagon going to fetch the slow one, and there is no extra rule to write to
# get it.
#
# and the m minimising T(m) is looked for, i.e. the moment *everyone* has
# reached the destination. Every approach leg is walked by whoever walks it,
# at their own Speed: only after the rendezvous does the slowest-member rule
# hold, and that is exactly what the rules say.
#
# Why compute it by brute force instead of a heuristic: the grid is a few
# hundred hexes and the travellers are four or five. k+1 Dijkstra are enough
# — one forward from every departure, one backwards from the destination —
# and then every hex is tried as rendezvous. It is the exact optimum, it is
# computed in milliseconds, and it has no parameters to tune that would one
# day give an odd result without anyone knowing why. A heuristic here would
# save nothing and could be wrong.
#
# The best rendezvous may well be the destination itself (nobody waits for
# anybody) or the departure of one of the travellers (the others reach
# them): they are candidates like all the others, so the choice «it is not
# worth meeting first» comes out of the count on its own, without special
# cases.
def _mark_back(field: Field, node, cost: float, from_) -> None:
    """Like `_refresh`, but for the backward field, which counts by shores.

    There the cost of a node **is** already the full cost of that hex: there
    is no quarter to add afterwards, because there are no gates.
    """
    field.node_costs[node] = cost
    field.previous_ones[node] = from_
    key = (node[0], node[1])
    if cost < field.costs.get(key, cost + 1):
        field.costs[key] = cost
    if cost < field.shore_costs.get(node, cost + 1):
        field.shore_costs[node] = cost
        field.best_shore[node] = node


def inverse_cost_field(destination: tuple[int, int], cost_of,
                        orientation: str = "pointy", inside=None, passage=None,
                        banks: dict | None = None,
                        crossings: dict | None = None) -> Field:
    """What reaching *the* destination costs from every hex.

    It is Dijkstra backwards: entering a hex one pays the cost of that hex,
    so going back one pays the one one comes from. We need it to know, for
    every possible rendezvous, how much road is left.

    The banks are fine backwards too without changing anything: if from one
    bank one passes to another, from that one comes back to this: the
    relation between the two nodes is symmetric even when the cost is not.

    **This field still reasons by shores, not by gates**, so it does not
    count the extra detour the water forces inside a hex: it gives a slightly
    optimistic cost. It serves to **choose** a rendezvous point among many,
    and for that it is fine: the plan then shown to the table is redone
    forward, with the exact count. Making it exact here too would mean
    reversing the reasoning on the gates — one enters from a side and leaves
    from another, and backwards the two swap — and it serves nothing that
    shows.
    """
    field = Field()
    for bank in range(banks_of(banks, destination)):
        node = (destination[0], destination[1], bank)
        field.node_costs[node] = 0
        field.previous_ones[node] = None
        field.shore_costs[node] = 0
        field.best_shore[node] = node
    field.costs[tuple(destination)] = 0
    counter = 0
    queue = [(0, 0, n) for n in field.node_costs]
    heapq.heapify(queue)
    while queue:
        cost, _order, current = heapq.heappop(queue)
        if cost > field.node_costs.get(current, cost):
            continue
        here = (current[0], current[1])
        step = cost_of(here)
        if step is None:
            continue
        for node, near in steps_from(current, orientation, banks):
            if inside is not None and not inside(near):
                continue
            if cost_of(near) is None:
                continue          # from an impassable hex one does not leave
            # The field is built backwards but the step is made forward: the
            # side is crossed from `neighbour` towards `current`, and it is in
            # that direction that it must be asked. Today the water is
            # symmetric and nothing changes, but the rules give the river
            # downriver open and upriver difficult: the day the direction
            # matters, here it is already right.
            extra = passage(near, here) if passage else 0
            if extra is None:
                continue
            new = cost + step + extra
            if new < field.node_costs.get(node, new + 1):
                _mark_back(field, node, new, current)
                counter += 1
                heapq.heappush(queue, (new, counter, node))
        # A crossing is passed in both directions: from here to the other
        # shore and vice versa, at the same price.
        for node, entry in inner_passages(current, banks, crossings):
            after = cost + inner_cost(entry, here, cost_of)
            if after < field.node_costs.get(node, after + 1):
                # `_mark_back` and not `_refresh`: this field counts by
                # shores, not by gates, and the cost of a node is already the
                # full one of its hex. Calling the other here was also an error
                # that showed only at the right moment — `_refresh` wants two
                # more arguments, the rest of hex to pay and the shore — so the
                # backward field **crashed** as soon as an inner crossing
                # entered the count. With four bridge hexes on the real map it
                # rarely happened; for whoever swims, who crosses in every cut
                # hex, it would have happened at the first rendezvous.
                _mark_back(field, node, after, current)
                counter += 1
                heapq.heappush(queue, (after, counter, node))
    return field


@dataclass
class Rendezvous:
    """Where and when it is worth meeting, and what waiting costs."""

    point: tuple[int, int] | None = None
    # The **shore** of the meeting point. A rendezvous was a hex, and in a hex
    # cut by the water that is not a place: the branches could arrive on this
    # side and the common road leave from that one, without anyone having
    # paid the river. One meets on a shore, and the branches all reach it.
    bank: int = 0
    total_days: float = 0.0
    union_days: float = 0.0
    approaches: dict = field(default_factory=dict)   # char_id -> course
    common: list = field(default_factory=list)          # from the rendezvous to the destination
    wait: dict = field(default_factory=dict)          # char_id -> days lost
    alone_ones: dict = field(default_factory=dict)         # char_id -> days alone


def _common_pace(activities: dict, party_pace: float | None) -> float:
    """Activities per day of the united group: those imposed, or the rule."""
    if party_pace:
        return max(float(party_pace), 1e-9)
    return max(min(activities.values()) if activities else 1.0, 1e-9)


def rendezvous_point(departures: dict, destination: tuple[int, int], activities: dict,
                    cost_of, orientation: str = "pointy", inside=None,
                    party_pace: float | None = None, passage=None,
                    banks: dict | None = None,
                    departure_banks: dict | None = None,
                    crossings: dict | None = None,
                    water: dict | None = None) -> Rendezvous | None:
    """The shore where it is worth meeting before going on together.

    `departures` and `activities` are per character: where they leave from
    and how many activities a day they make. `party_pace` is the group's
    pace after the rendezvous: without it, it is the slowest's, as the rule
    wants. Returns None if even a single one cannot reach the destination.
    """
    if not departures:
        return None
    departure_banks = departure_banks or {}
    fields = {char_id: cost_field(start_, cost_of, orientation, inside,
                              passage=passage, banks=banks,
                              departure_bank=departure_banks.get(char_id, 0),
                              crossings=crossings, water=water)
             for char_id, start_ in departures.items()}
    direction = inverse_cost_field(destination, cost_of, orientation, inside,
                                passage, banks, crossings)
    together = _common_pace(activities, party_pace)

    # The candidates are **shores**, not hexes: in a cut hex the two banks are
    # two places, and the meeting point is on one of the two.
    best, score = None, None
    for candidate, rest in direction.shore_costs.items():
        if any(candidate not in c.shore_costs for c in fields.values()):
            continue
        union = max(field.shore_costs[candidate] / max(activities.get(char_id, 1.0), 1e-9)
                     for char_id, field in fields.items())
        total = union + rest / together
        # First make nobody late, then meet as soon as possible. The order
        # matters: the rendezvous it chooses is always *free*, and at equal
        # arrival staying together for more road is preferred.
        candidate_score = (round(total, 6), round(union, 6))
        if score is None or candidate_score < score:
            best, score = candidate, candidate_score
    if best is None:
        return None
    when = score[0]

    rendezvous = Rendezvous(point=(best[0], best[1]), bank=int(best[2]),
                    total_days=when, union_days=score[1])
    _fill_rendezvous(rendezvous, fields, departures, activities, best, destination)

    # The common road, from the meeting point to the destination: it is read
    # from the reverse field, which is already built in the right direction —
    # **from that shore**, not from the cheapest gate of the hex. It comes out
    # in hexes, like everything this module hands to its users.
    node = best
    course = []
    while node is not None:
        course.append((node[0], node[1]))
        node = direction.previous_ones.get(node)
    rendezvous.common = course
    return rendezvous


def _fill_rendezvous(rendezvous: Rendezvous, fields: dict, departures: dict, activities: dict,
                   shore, destination) -> None:
    """How everyone reaches the meeting point — **that shore** — and how long they
    stand there waiting."""
    shore = tuple(shore)
    last = max(fields[char_id].shore_costs[shore] / max(activities.get(char_id, 1.0), 1e-9)
                 for char_id in departures)
    for char_id, field in fields.items():
        rendezvous.approaches[char_id] = (field.course_to_shore(departures[char_id], shore)
                                     or [])
        own_ = field.shore_costs[shore] / max(activities.get(char_id, 1.0), 1e-9)
        rendezvous.wait[char_id] = round(last - own_, 2)
        # How long they would take to go off on their own: it serves to tell
        # the table what waiting is costing, not to decide in their place.
        alone = field.costs.get(destination)
        if alone is not None:
            rendezvous.alone_ones[char_id] = round(alone / max(activities.get(char_id, 1.0), 1e-9), 2)


def rendezvous_on(departures: dict, common: list, activities: dict, cost_of,
              orientation: str = "pointy", inside=None,
              party_pace: float | None = None, passage=None,
              banks: dict | None = None,
              departure_banks: dict | None = None,
              crossings: dict | None = None,
              water: dict | None = None,
              bank: int | None = None,
              branches: dict | None = None) -> Rendezvous | None:
    """The rendezvous when the common road is drawn by the hand, not the algorithm.

    `branches` are the approaches as the ruler showed them, per character:
    they are kept in place of the recomputed ones **if** they end at the
    meeting point, on its shore. The count of days stays that of the fields —
    a branch shown by the ruler is already a shortest way in its model — but
    the road seen, and saved, is the one that was seen.

    `bank` is the shore of the meeting point, if the hand said it (it is the
    shore the drawn common road starts from); otherwise, among the shores of
    that hex, the one reached first is taken.

    `common` is a course already checked: the first hex is the meeting point,
    the last the destination. The meeting point is not searched for here, it
    is read — and underneath there is a choice, not an oversight. Whoever
    drags the arrow is guiding *one* line, and a rendezvous moving on its own
    while the hand draws the road would make it dance under their fingers.
    What is left to compute is how everyone reaches the meeting point and how
    many days the whole thing comes to cost.

    Returns None if even a single one does not reach the meeting point: in
    that case the drawing does not describe a journey that can be made, and
    the algorithm decides.
    """
    if not departures or len(common) < 2:
        return None
    point, destination = tuple(common[0]), tuple(common[-1])
    departure_banks = departure_banks or {}
    fields = {char_id: cost_field(start_, cost_of, orientation, inside,
                              passage=passage, banks=banks,
                              departure_bank=departure_banks.get(char_id, 0),
                              crossings=crossings, water=water)
             for char_id, start_ in departures.items()}
    candidate = ([int(bank)] if bank is not None
                 else list(range(banks_of(banks, point))))
    shore = None
    union = None
    for which in candidate:
        key = (point[0], point[1], which)
        if any(key not in c.shore_costs for c in fields.values()):
            continue
        here = max(field.shore_costs[key] / max(activities.get(char_id, 1.0), 1e-9)
                  for char_id, field in fields.items())
        if union is None or here < union:
            shore, union = key, here
    if shore is None:
        return None

    together = _common_pace(activities, party_pace)
    rest = sum(cost_of(tuple(c)) or 0 for c in common[1:])
    if passage:
        # The hand-drawn road pays the sides it crosses too.
        for before, after in zip(common, common[1:]):
            extra = passage(tuple(before), tuple(after))
            if extra is None:
                return None       # the drawing passes where there is no way
            rest += extra
    rendezvous = Rendezvous(point=point, bank=int(shore[2]),
                    total_days=round(union + rest / together, 6),
                    union_days=round(union, 6))
    _fill_rendezvous(rendezvous, fields, departures, activities, shore, destination)
    for char_id, course in (branches or {}).items():
        steps = [tuple(c) for c in course]
        if char_id not in departures or len(steps) < 2 or steps[-1] != point:
            continue
        if steps[0] != tuple(departures[char_id]):
            continue
        arrival_on = banks_on_course(steps, banks or {}, crossings, orientation,
                                     departure_banks.get(char_id, 0))
        if arrival_on and arrival_on[-1] == int(shore[2]):
            rendezvous.approaches[char_id] = steps
    rendezvous.common = [tuple(c) for c in common]
    return rendezvous
