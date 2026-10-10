"""Letting a day pass: journeys advance, the month ends, the turn is due.

It lives outside the interface because it is the part that can be tested by
hand: the open windows have nothing to do with a party having crossed one more
hex. The clock proper (the timer that calls this function) lives in
`ui/clock.py` instead.

The arithmetic is that of Hexploration: every day the party has a certain
number of activities, entering a hex costs 1, 2 or 3 of them, and one advances
when the activities set aside are enough to pay for the waypoint. So a swamp
hex with a single activity a day takes three days, and halfway through the
party is honestly still in the previous hex.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from kingmaker.geometry import waterways, hexgrid, sections
from kingmaker.rules import almanac
from kingmaker import travel as travel_mod
from kingmaker.locale.i18n import t


@dataclass
class Report:
    """What happened in the day that just passed."""

    data: almanac.Data
    arrived: list[tuple[str, tuple[int, int]]] = field(default_factory=list)
    advanced: list[tuple[str, tuple[int, int]]] = field(default_factory=list)
    month_end: bool = False          # the month is over: the Kingdom Turn is due



# ---------------------------------------------------------------- position
def waypoint_reached(costs: list, progress: float) -> tuple[int, float]:
    """How many waypoints have been paid in full, and how much is left over.

    `costs` is the cost of every waypoint after departure. The index returned
    is the one inside the full path (0 = still at the departure hex).
    """
    spent = 0.0
    for index, cost in enumerate(costs):
        next_ = spent + float(cost or 0)
        if progress + 1e-9 < next_:
            return index, progress - spent
        spent = next_
    return len(costs), progress - spent


def days_missing(costs: list, progress: float, day_activities: float) -> int:
    """Days left to reach the end, rounded up."""
    if day_activities <= 0:
        return 0
    remains = sum(float(c or 0) for c in costs) - progress
    if remains <= 0:
        return 0
    return int(-(-remains // day_activities))


# ------------------------------------------------------------------- advancing
def current_date(k: dict) -> almanac.Data:
    block = k.get("clock") or {}
    start_ = almanac.from_dict(block.get("start"), almanac.calendar_of(k))
    return almanac.date_plus_days(start_, int(block.get("days", 0)))


def advance_one_day(state) -> Report:
    """Moves the clock forward one day and moves whoever is travelling.

    It does not touch the Kingdom Turn: it only says, in the report, that the
    month is over. Closing the turn is a decision, and decisions are taken by
    someone pressing a button.
    """
    block = state.k.setdefault("clock", {})
    block["days"] = int(block.get("days", 0)) + 1
    data = current_date(state.k)
    report = Report(data=data, month_end=almanac.last_of_month(data))

    for journey in state.archive.list_journeys(state.campaign, "in_progress"):
        _advance_journey(state, journey, report)
    return report


def _active_legs(legs: list) -> list:
    """The legs that move today.

    Those that wait leave only when all the others are done: that is the
    rendezvous. As long as even one is on the road, the party does not move —
    that is exactly the point of travelling together.
    """
    free_ones = [t for t in legs if not t.get("waiting")]
    en_route = [t for t in free_ones if not _finished(t)]
    if en_route:
        return en_route
    return [t for t in legs if t.get("waiting") and not _finished(t)]


def _finished(leg: dict) -> bool:
    costs = list(leg.get("costs") or [])
    index, _rest = waypoint_reached(costs, float(leg.get("progress") or 0))
    return index >= len(costs)


def _advance_journey(state, journey: dict, report: Report) -> None:
    legs = list(journey.get("legs") or [])
    if not legs:
        # A journey without a frozen plan (recorded before legs existed): we
        # leave it where it is, it is resolved by hand from the Turn tab.
        return

    for leg in _active_legs(legs):
        _advance_leg(state, leg, report,
                       _leg_spot(journey, leg))

    # The legs are rewritten anyway: even a day that did not change hex used
    # up activities, and tomorrow those count.
    if all(_finished(t) for t in legs):
        state.archive.update_journey(journey["id"], legs=legs,
                                        status="completed",
                                        turn_resolved=state.k.get("turn", 0))
    else:
        state.archive.update_journey(journey["id"], legs=legs)


def final_spot(journey: dict):
    """The spot inside the arrival hex that this journey had aimed at."""
    x, y = journey.get("pos_x"), journey.get("pos_y")
    if x is None or y is None:
        return None
    try:
        return (float(x), float(y))
    except (TypeError, ValueError):
        return None


def _waypoint_junction(state, leg: dict, which: int):
    """Where the boat is at the end of waypoint `which`: `(hex, spot)`.

    A water leg carries its route, junction by junction, and for every waypoint
    the last junction that belongs to it. The spot is that point, in radii from
    the center of the waypoint's hex: it is how a boat says where it is. None
    for a land leg.
    """
    route = leg.get("route") or []
    waypoints = leg.get("waypoint_statuses") or []
    if not route or which >= len(waypoints):
        return None
    try:
        entry = route[int(waypoints[which])]
        node = waterways.node_from_text(entry[0])
        coord = (int(entry[1]), int(entry[2]))
    except (TypeError, ValueError, IndexError):
        return None
    if node is None:
        return None
    spot = waterways.unit_point_of_node(
        node, coord, state.k["map"]["orientation"])
    return (coord, spot)


def _leg_spot(journey: dict, leg: dict):
    """Where one ends up inside the last hex of **this** leg.

    The leg knows on its own, since it is frozen with the rest of the plan: an
    approach branch ends on the shore of the meeting point, the common road in
    the aimed piece. Old legs do not have it: for those the journey's spot
    applies, but only if the leg really ends in the arrival hex — giving it to
    a branch that stops at the meeting point put people on a point that means
    nothing in there.
    """
    where = leg.get("where")
    if where and len(where) == 2:
        try:
            return (float(where[0]), float(where[1]))
        except (TypeError, ValueError):
            pass
    path = leg.get("path") or []
    if path and f"{path[-1][0]},{path[-1][1]}" == str(
            journey.get("arrival") or ""):
        return final_spot(journey)
    return None


def _spot_entering(state, where, coming_from):
    """The spot of the shore one enters a hex from, or None if it is whole.

    Walking one day at a time, markers ended up on every intermediate hex with
    the **spot of the previous one** still on them: a point that means nothing
    in there, and the shore was recomputed at random. Now the spot is redone at
    every waypoint, as the map does when a journey is resolved by hand.
    """
    orient = state.k["map"]["orientation"]
    faces = state.archive.campaign_sections(
        state.campaign, orient).get(tuple(where))
    if not faces or len(faces) < 2 or coming_from is None:
        return None
    neighbours = hexgrid.neighbours(where[0], where[1], orient)
    try:
        direction = neighbours.index(tuple(coming_from))
    except ValueError:
        return None
    bank = travel_mod.bank_of_side({tuple(where): faces}, where, direction)
    return sections.section_spot(faces, bank)


def _advance_leg(state, leg: dict, report: Report,
                   final_spot=None) -> None:
    """Moves whoever walks this leg by one day."""
    costs = list(leg.get("costs") or [])
    path = [tuple(c) for c in (leg.get("path") or [])]
    if not costs or len(path) < 2:
        return

    before, _r = waypoint_reached(costs, float(leg.get("progress") or 0))
    progress = (float(leg.get("progress") or 0)
                 + float(leg.get("activities_per_day") or 0))
    after, _r = waypoint_reached(costs, progress)
    leg["progress"] = progress
    if after == before:
        return

    which = min(after, len(path) - 1)
    position = path[which]
    arrived = after >= len(costs)
    # Where one ends up **inside** the hex: on arrival the piece the journey
    # had aimed at, on the road the shore one enters from. On a boat instead
    # the **junction** the waypoint ends on: the leg carries it written down.
    spot = final_spot if arrived else None
    on_the_water = _waypoint_junction(state, leg, which)
    if on_the_water is not None:
        position, spot = on_the_water
    if spot is None:
        spot = _spot_entering(
            state, position, path[which - 1] if which else None)
    for char_id in leg.get("characters") or []:
        state.archive.update_character(
            char_id, hex_col=position[0], hex_row=position[1],
            pos_x=None if spot is None else spot[0],
            pos_y=None if spot is None else spot[1])
    # And the boat with them: it is on the map, and a day of travel moves it
    # as it moves those on board.
    moved_ones = state.archive.move_vehicles_with(state.campaign,
                                              leg.get("characters") or [], position,
                                              leg.get("stable_id"), where=spot)
    # Whoever goes by land is no longer aboard the boat left behind.
    for char_id in leg.get("characters") or []:
        char = state.archive.character(char_id)
        if char and char.get("stable_id") and char["stable_id"] not in moved_ones:
            state.archive.update_character(char_id, stable_id=None)
    names = _names(state, leg.get("characters") or [])
    (report.arrived if arrived else report.advanced).append((names, position))


def _names(state, ids: list) -> str:
    names = []
    for char_id in ids:
        char = state.archive.character(char_id)
        if char is not None:
            names.append(char["name"])
    return ", ".join(names) or t("daily.party")


def rest_of_leg(leg: dict) -> list:
    """The part of the leg still to walk, from the hex one is in now.

    Needed to draw on the map where the party is going: the arrow shortens by
    itself as it walks, instead of staying the one of departure day.
    """
    path = [tuple(c) for c in (leg.get("path") or [])]
    if len(path) < 2:
        return []
    index, _rest = waypoint_reached(list(leg.get("costs") or []),
                                     float(leg.get("progress") or 0))
    return path[min(index, len(path) - 1):]
