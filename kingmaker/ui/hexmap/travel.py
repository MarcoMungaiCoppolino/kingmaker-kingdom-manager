"""Travel on foot: computation, plan, departure, rendezvous, separate journeys, who is already on the road, the row of portraits.

It used to live in `ui/hexmap.py`; the `hexmap` facade still re-exports everything.
"""
from __future__ import annotations

import logging
import math
import time
import uuid
from dataclasses import dataclass, field
from nicegui import ui
from kingmaker.state import STATE
from kingmaker.ui import theme
from kingmaker.ui.tabs.party import pace
from kingmaker.geometry import waterways, hexgrid, sections
from kingmaker.travel import daily
from kingmaker.media import images
from kingmaker.access import permissions
from kingmaker import travel as travel_mod
from kingmaker.locale import units

from kingmaker.ui.hexmap import common as _common
from kingmaker.ui.hexmap import drawing as _drawing
from kingmaker.ui.hexmap import markers as _markers
from kingmaker.ui.hexmap import boats as _boats
from kingmaker.ui.hexmap import ruler as _ruler
from kingmaker.locale.i18n import t, tn

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Travel: where the characters are, how long they take to get elsewhere.
#
# How much a hex whose category we do not know weighs in the path search: the
# highest of the rules', so the path avoids it if there is an alternative, but
# does not declare it impossible.
_MAX_COST = max(c["cost"] for c in travel_mod.CATEGORIES.values())

#
# The panel proposes and does not apply: the plan is looked at, discussed and
# only then someone presses the button — the same rule as the turn activities.
# The panels that show where the characters and the vehicles stand: what a
# marker placed, boarded, landed, taken off the map or sent back to the shed
# has to redraw. Not the sheet, not the turn column: they do not read
# positions. `tests/test_windows.py` moves a marker and compares every panel
# in front with a fresh render, so a panel missing here fails the suite.
_MARKER_PANELS = ("hexmap.map", "hexmap.party", "hexmap.travel", "hexmap.detail",
                  "party.characters", "transport.list", "turn.journeys", "turn.journal")


def _travel_panel(mine: dict, mapping) -> None:
    user = theme.user()
    if not permissions.can(user, permissions.PLAN_TRAVEL):
        return
    if not mine.get("travel_mode"):
        return                      # outside the mode it is useless

    characters = STATE.characters()
    by_id = {p["id"]: p for p in characters}
    chosen = [by_id[i] for i in mine["travel_pcs"] if i in by_id]

    with ui.card().classes("km-panel w-full"):
        with ui.row().classes("items-center gap-2 w-full no-wrap"):
            theme.title(t("map.travel.travel"), 2)
            ui.element("div").style("flex:1")
            if mine.get("path"):
                ui.button(icon="close", on_click=lambda: _reset_journey(mine, mapping)) \
                    .props("flat dense round size=sm color=grey") \
                    .tooltip(t("map.travel.remove_route_from_map"))

        if not characters:
            ui.label(t("map.travel.no_character_create_them")) \
                .style("color:var(--km-muted);font-size:.82rem")
            return

        # Who leaves sits at the top, and it is no layout detail: a group's
        # journey is the thing this box exists for. Vehicles came later and
        # had taken the first place — with four vehicles in the list the
        # choice of travellers ended up below the fold of the screen, and
        # seemed gone.
        with ui.row().classes("items-center gap-1 w-full no-wrap"):
            ui.select({p["id"]: p["name"] for p in characters}, label=t("map.travel.who_leaves"),
                      value=list(mine["travel_pcs"]), multiple=True,
                      on_change=lambda e: _choose_travellers(mine, e.value)) \
                .props("outlined dense use-chips options-dense").classes("flex-1")
            # The way out when a marker ends up somewhere it cannot leave
            # from: off the map, and placed again from the Party tab.
            ui.button(icon="undo", on_click=lambda: _remove_from_map(mine, mapping)) \
                .props("flat dense round size=sm color=grey") \
                .tooltip(t("map.travel.remove_from_map"))

        if not chosen:
            ui.label(t("map.travel.map_click_hex_take")) \
                .style("font-size:.74rem;color:var(--km-muted);white-space:normal")

        occupied = _occupied_box(mine, mapping, chosen)

        departure, departure_warning = _departure_of(chosen)
        arrival = (mine["col"], mine["row"]) if mine["col"] is not None else None

        with ui.row().classes("gap-2 items-center flex-wrap"):
            scattered = _leave_scattered(chosen)
            from_ = ("sparsi" if scattered and departure else
                  f"{departure[0]},{departure[1]}" if departure else "—")
            ui.html(f'<span class="km-chip" style="font-size:.7rem">Da: {from_}</span>')
            ui.html(f'<span class="km-chip" style="font-size:.7rem">A: '
                    f'{f"{arrival[0]},{arrival[1]}" if arrival else t("map.travel.drag_arrow")}</span>')
            ui.checkbox(t("map.travel.forced_march"), value=bool(mine.get("forced_march")),
                        on_change=lambda e: _ruler._change_march(mine, mapping, e.value)) \
                .tooltip(t("map.travel.one_more_travel_activity"))
        # Being two is enough. Before, it appeared only if they left from
        # different hexes, because the toggle was born for the rendezvous —
        # whoever is far meets on the road — but the question it asks is not
        # «where are you now»: it is «do you wait for each other?». Two
        # leaving from the same hex at different Speeds are exactly the case
        # where one can arrive first, and that choice must be left to the
        # table instead of deciding for them that the quicker one slows down.
        if len(chosen) > 1:
            ui.checkbox(t("map.travel.travel_together"), value=bool(mine.get("together", True)),
                        on_change=lambda e: _change_together(mine, mapping, e.value)) \
                .tooltip(t("map.travel.off_everyone_goes_their"))
        _vehicles_box(mine, mapping, chosen)
        _map_vehicles_panel_box(mine, mapping)
        # «The journey leaves from the first» is true only when the app could
        # not do better. With a rendezvous one meets on the road, and with
        # «together» off everyone leaves from home: in both cases the warning
        # would tell something that does not happen.
        if departure_warning and not (scattered and (mine.get("rendezvous") is not None
                                                or mine.get("singles"))):
            ui.label(departure_warning).style("font-size:.74rem;color:var(--km-gold)")


        plan = mine.get("plan")
        if plan is not None:
            _plan_summary(plan, mine, mapping, chosen, departure, arrival,
                             occupied)

    _planned_journeys_list(mine, mapping)

def _choose_travellers(mine: dict, values) -> None:
    mine["travel_pcs"] = list(values or [])
    # Changing the group changes the Speed: the previous count no longer holds.
    _common._forget_plan(mine)
    _redraw_travel(mine, mine["map"])

def _remove_from_map(mine: dict, mapping) -> None:
    """Takes the chosen characters off the map: no hex, no vehicle.

    They go back to the Party tab, where «Put on the map» places them
    again. It is the way out when a marker got stuck somewhere no journey
    starts from. Whoever is on a journey is not moved: that journey would
    have to be cancelled first, and that is a decision, not a side effect.
    """
    user = theme.user()
    chosen = list(mine.get("travel_pcs") or [])
    if not chosen:
        theme.notify(t("map.travel.first_choose_who_leaves"), "warning")
        return
    if journeys_by_character(set(chosen)):
        theme.notify(t("map.travel.remove_on_journey"), "warning")
        return
    names = []
    for char_id in chosen:
        char = STATE.archive.character(char_id)
        if char is None or not permissions.can_on_character(user, char):
            continue
        STATE.archive.update_character(char_id, hex_col=None, hex_row=None,
                                       pos_x=None, pos_y=None, stable_id=None)
        names.append(char["name"])
    if not names:
        theme.notify(t("map.travel.remove_not_yours"), "negative")
        return
    mine["travel_pcs"] = []
    _common._forget_plan(mine)
    STATE.record(t("map.travel.removed_from_map", names=", ".join(sorted(names))), "map")
    theme.notify(t("map.travel.removed_from_map", names=", ".join(sorted(names))), "positive")
    theme.save_and_refresh_panels(_MARKER_PANELS)
    _redraw_travel(mine, mapping)


def _reset_journey(mine: dict, mapping) -> None:
    _common._forget_plan(mine)
    _redraw_travel(mine, mapping)

def _departure_of(chosen: list[dict]) -> tuple[tuple[int, int] | None, str]:
    """The hex the group leaves from, or the reason it is not known."""
    positions = {(p["hex_col"], p["hex_row"]) for p in chosen
                 if p["hex_col"] is not None and p["hex_row"] is not None}
    if not chosen:
        return None, ""
    if not positions:
        return None, (t("map.travel.none_chosen_characters_map"))
    if len(positions) > 1:
        where = " · ".join(f"{c},{r}" for c, r in sorted(positions))
        return sorted(positions)[0], (t("map.travel.chosen_characters_are_not", where=where))
    return positions.pop(), ""

def _valid_nodes(nodes, course, banks: dict | None) -> tuple:
    """The nodes the browser sent, if they tell *this* course.

    The browser is not trusted — it is the usual rule — but here there is
    nothing to recompute: the nodes say **on which shore** the hand passed,
    and that is something only the hand knows. It is checked that the hexes
    are its own and that every shore exists, and that is enough: if they do
    not add up they are dropped and the drawing rebuilds as it did before.
    """
    cleaned = []
    for entry in nodes or ():
        try:
            col, row, bank = int(entry[0]), int(entry[1]), int(entry[2])
        except (TypeError, ValueError, IndexError):
            return ()
        if not (0 <= bank < travel_mod.banks_of(banks, (col, row))):
            return ()
        cleaned.append((col, row, bank))
    # The same hexes, in the same order: an extra node is the shore change
    # inside a hex, and there the hex is the same twice in a row.
    hexes: list = []
    for col, row, _bank in cleaned:
        if not hexes or hexes[-1] != (col, row):
            hexes.append((col, row))
    if hexes != [tuple(c) for c in course]:
        return ()
    return tuple(cleaned)

def _compute_journey(mine: dict, mapping, traced_one=None, common_traced=None,
                     traced_separate=None, arrival_point=None,
                     drawn_points=None, traced_nodes=None,
                     traced_branches=None) -> None:
    user = theme.user()
    if not permissions.can(user, permissions.PLAN_TRAVEL):
        theme.notify(t("map.travel.you_do_not_have"), "negative")
        return
    # With a boat in hand the journey is another: it leaves from it and goes
    # by water. It holds for the dragged arrow too — what the hand points at
    # is *where to arrive*, and the road to get there is chosen by the water.
    # A wagon instead does not change the journey, it changes the Speed: that
    # the land count already knows, because whoever is aboard has it written
    # on them.
    if _boats._vehicle_in_hand(mine, "water") is not None:
        drawn_boat = (traced_one or common_traced
                           or (traced_separate or [{}])[0].get("path"))
        if drawn_boat and len(drawn_boat) >= 2:
            try:
                mine.update(col=int(drawn_boat[-1][0]),
                           row=int(drawn_boat[-1][1]))
            except (TypeError, ValueError, IndexError):
                pass
        if _boats._compute_route(mine, mapping, arrival_point, drawn_points):
            return
    by_id = {p["id"]: p for p in STATE.characters()}
    chosen = [by_id[i] for i in mine["travel_pcs"] if i in by_id]
    if not chosen:
        theme.notify(t("map.travel.choose_least_one_character"), "warning")
        return
    departure, _warning = _departure_of(chosen)
    if departure is None:
        theme.notify(t("map.travel.no_chosen_character_map"), "warning")
        return
    # A hand-drawn common road makes sense only if the group is scattered: if
    # they all leave from the same hex there is no rendezvous, and that road
    # is simply the group's course.
    if common_traced:
        positions = {(p["hex_col"], p["hex_row"]) for p in chosen
                     if p["hex_col"] is not None and p["hex_row"] is not None}
        if len(positions) < 2 or not mine.get("together", True):
            traced_one, common_traced = common_traced, None

    # A dragged course carries its destination along: whoever draws it clicked
    # no hex, and requiring it would leave them without a journey.
    drawn = traced_one or common_traced
    if not drawn and traced_separate:
        drawn = next((v.get("path") for v in traced_separate
                          if len(v.get("path") or []) >= 2), None)
    if drawn and len(drawn) >= 2:
        try:
            mine.update(col=int(drawn[-1][0]), row=int(drawn[-1][1]))
        except (TypeError, ValueError, IndexError):
            traced_one = common_traced = traced_separate = None
    if mine["col"] is None:
        theme.notify(t("map.travel.click_destination_hex_map"), "warning")
        return
    arrival = (mine["col"], mine["row"])

    view = _common._current_view(mine)
    m = STATE.k["map"]
    columns, rows = int(m["columns"]), int(m["rows"])
    # The categories set by the GM apply to everyone, but only on the hexes
    # the viewer already knows: there they add nothing to what they see.
    difficulty = STATE.archive.campaign_difficulty(STATE.campaign)

    inside = _common.inside_map(m)

    # Vehicles are needed already here: if the group is aboard a boat, the
    # water stops being a wall and the cost of cells and sides change
    # together. A single place the answer comes from.
    vehicles = _markers._vehicles_in_play()
    mode = _crossing(mine, chosen, vehicles, view, difficulty)
    cell_cost, passage, borders, sail = mode
    banks, crossings = mode.banks, mode.crossings
    water = mode.water

    def cost_of(coord):
        """Activities to enter, or None if there really is no way through there.

        The fog does not stop the planner: never-explored hexes count at the
        worst cost, and the plan says so. Only the terrains the rules assign
        no category to remain impassable.
        """
        return cell_cost(coord)

    def uncertain_cost(coord):
        """As above, but passes even where the category is unknown.

        For the second attempt: if the first finds no road, the group has the
        right to know *why* — which hexes have no category — instead of
        reading «no way through». Those without a category weigh like the
        worst terrain, so the course avoids them if it can.
        """
        cost = cell_cost(coord)
        return cost if cost is not None else _MAX_COST

    # The drawn shores hold for **this** count and not the next: if they
    # stayed, a journey chosen with the right button would find itself with
    # the shores of the last hand-drawn arrow.
    mine["nodes"] = ()

    # A hand-drawn course counts more than the cheapest: if the group wants
    # to pass through the forest instead of the road, that is their business.
    # We check it all the same, because it comes from the browser.
    course = None
    if traced_one:
        # From **their** shore, not the first. Here the bank was not crossed,
        # and the check walked the course always starting from shore 0:
        # whoever stood on the other one had right courses refused — «the
        # traced path is not valid» — and in their place the cheapest way
        # appeared, which is another road. The defect had always been there
        # and did not show, because as long as both shores sat at the hex
        # center nobody could draw a course that depended on which of the two
        # it was.
        course = _valid_course(traced_one, departure, m["orientation"],
                                  inside, cost_of, passage, banks,
                                  _bank_of(chosen, departure, banks), crossings,
                                  traced_nodes)
        if course is None:
            theme.notify(t("map.travel.traced_path_not_valid"), "warning")
        else:
            # The shores the hand touched are kept: it is what makes the arrow
            # after release the same as before.
            mine["nodes"] = _valid_nodes(traced_nodes, course, banks)

    # The common road starts from the rendezvous, not from a character: it is
    # the only course the browser can send without it starting where someone
    # is.
    common_road = None
    common_bank = None
    if common_traced:
        # The common road starts from the meeting point. On which shore of
        # the meeting point the hand says, if it said (the drawn nodes); if
        # not they are all tried, and if the course holds from one of the
        # shores that is the one.
        start_ = tuple(common_traced[0])
        n_items = travel_mod.banks_of(banks, start_)
        order = list(range(n_items))
        try:
            told = int((traced_nodes or [[None, None, None]])[0][2])
            if 0 <= told < n_items:
                order = [told] + [r for r in order if r != told]
        except (TypeError, ValueError, IndexError):
            pass
        for bank in order:
            common_road = _valid_course(common_traced, start_,
                                            m["orientation"], inside, cost_of,
                                            passage, banks, bank, crossings,
                                            traced_nodes)
            if common_road is not None:
                common_bank = bank
                break
        if common_road is None:
            theme.notify(t("map.travel.traced_common_road_not"), "warning")
    if course is None:
        course = travel_mod.path(departure, arrival, cost_of,
                                       m["orientation"], inside, passage, banks,
                                       _bank_of(chosen, departure, banks), crossings,
                                       water)
    if course is not None:
        arrival = course[-1]
        mine.update(col=arrival[0], row=arrival[1])
    if course is None:
        # Try again admitting the hexes without a category: if that way one
        # arrives, the plan is born blocked and lists which hexes the GM must
        # decide.
        course = travel_mod.path(departure, arrival, uncertain_cost,
                                       m["orientation"], inside, passage, banks,
                                       _bank_of(chosen, departure, banks), crossings,
                                       water)
    if course is None:
        _common._forget_plan(mine)
        _redraw_travel(mine, mapping)
        theme.notify(t("map.travel.no_path_destination_cannot"), "warning")
        return

    speed, source, warnings = _ruler._party_pace(mine, chosen, vehicles)
    waypoints = [_waypoint_for(view, difficulty, coord) for coord in course[1:]]
    inner = travel_mod.inner_on_course(
        course, banks, crossings, m["orientation"], cost_of,
        _bank_of(chosen, departure, banks))
    # The detour around the water: how much more every hex costs because the
    # river forces one to coast along it instead of cutting straight. Without
    # this the pathfinder would choose the road taking the detour into
    # account and then the plan would show another one, cheaper than the one
    # that will really be made.
    # Where one arrives **inside** the arrival hex. In a hex the water
    # divides «arriving» is not one thing: stopping in the shore one enters
    # from and crossing to stop in the one beyond are two journeys, and the
    # second is longer. As long as the point did not reach this far, the
    # ruler let one aim at the shore beyond and then the marker stopped on
    # this one — the arrow seemed to «correct itself».
    mine["arrival_pos"] = _spot_from_point(arrival, arrival_point)
    # The atom count, **a single one**: the shores the hand touched, the
    # piece where one stops, and for every waypoint the atoms crossed — which
    # are also those the arrow is drawn on. It is the same count the browser
    # does while you drag, and they must say the same number.
    rings, stretches = travel_mod.atom_count(
        course, banks, water, crossings, m["orientation"], cost_of,
        mine.get("nodes"), mine["arrival_pos"], _bank_of(chosen, departure, banks))
    mine["atom_stretches"] = stretches
    if (rings.get(tuple(arrival), 0) is None and arrival_point is not None
            and not traced_one):
        # The course reaches the hex through the cheapest gate, and in a cut
        # hex that can open onto the wrong shore: from there the aimed piece
        # cannot be reached, but **from another side it can** — and the ruler,
        # which looks for the road to the shore and not to the hex, found it.
        # We try again as it does: to that shore, whatever the cost. Only if
        # even so one does not arrive does the warning apply.
        again = _course_to_shore(
            departure, arrival, _bank_from_point(arrival, arrival_point), cost_of,
            m["orientation"], inside, passage, banks,
            _bank_of(chosen, departure, banks), crossings, water)
        if again and len(again) > 1:
            course = again
            waypoints = [_waypoint_for(view, difficulty, coord) for coord in course[1:]]
            inner = travel_mod.inner_on_course(
                course, banks, crossings, m["orientation"], cost_of,
                _bank_of(chosen, departure, banks))
            rings, stretches = travel_mod.atom_count(
                course, banks, water, crossings, m["orientation"], cost_of,
                mine.get("nodes"), mine["arrival_pos"],
                _bank_of(chosen, departure, banks))
            mine["atom_stretches"] = stretches
    if rings.get(tuple(arrival), 0) is None:
        theme.notify(
            t("map.travel.that_piece_cannot_reached", arrival=arrival[0], arrival2=arrival[1]), "warning")
        mine["arrival_pos"] = None
        rings, stretches = travel_mod.atom_count(
            course, banks, water, crossings, m["orientation"], cost_of,
            mine.get("nodes"), None, _bank_of(chosen, departure, banks))
        mine["atom_stretches"] = stretches
    rings = {coord: extra for coord, extra in rings.items() if extra}
    plan = travel_mod.plan_(
        waypoints, speed, source, bool(mine.get("forced_march")),
        [int(p["con_mod"] or 0) for p in chosen],
        borders, departure, sail, inner, rings)
    plan.warnings = warnings + plan.warnings

    # If the group is scattered over several hexes the journey is made in two
    # stages: everyone reaches the rendezvous at their own Speed, and from
    # there one goes on together. The real count is done by `_rendezvous_for`.
    rendezvous = _rendezvous_for(mine, chosen, arrival, mode, cost_of, common_road,
                         common_bank, traced_branches if common_road else None)
    mine["rendezvous"] = rendezvous
    mine["branches"] = []
    mine["singles"] = []

    # «Travel together» off: there is not one journey, there are k. We
    # compute them all, so the gesture creating them is one and before
    # confirming one sees who arrives when.
    #
    # It holds even if they all leave from the same hex: the road is the same
    # for all, but not the Speed, and with the toggle off whoever goes faster
    # arrives first instead of waiting for the slowest.
    if rendezvous is None and not mine.get("together", True) and len(chosen) > 1:
        by_char_id = {v.get("id"): v.get("path")
                   for v in (traced_separate or []) if v.get("id")}
        separate = _separate_journeys(chosen, arrival, mode, cost_of,
                                    bool(mine.get("forced_march")), by_char_id)
        if separate:
            mine["singles"] = separate
            # The box speaks of a single plan: let us put the one of whoever
            # takes longest, which is the day the party is all together again
            # at the destination.
            longest = max(separate, key=lambda s: s["plan"].days)
            plan = longest["plan"]
            mine["path"] = list(longest["path"])
            mine["plan"] = plan
            _redraw_travel(mine, mapping)
            return
    if rendezvous is not None and rendezvous.point is not None:
        # With a rendezvous the plan describes the *common road*, and the
        # days are said by the rendezvous: adding up the activities of a
        # single leg would give one person's journey, not the group's.
        common = list(rendezvous.common)
        common_waypoints = [_waypoint_for(view, difficulty, c) for c in common[1:]]
        party_speed, group_source, group_warnings = _ruler._party_pace(
            mine, chosen, vehicles)
        plan = travel_mod.plan_(
            common_waypoints, party_speed, group_source,
            bool(mine.get("forced_march")),
            [int(p["con_mod"] or 0) for p in chosen],
            inner=travel_mod.inner_on_course(
                common, banks, crossings, m["orientation"], cost_of))
        plan.warnings = group_warnings + plan.warnings
        plan.forced_days = math.ceil(rendezvous.total_days - 1e-9)
        # An approach branch crossing unknown terrain makes the total
        # approximate too: it must be said all the same.
        for branch_course in rendezvous.approaches.values():
            for coord in branch_course[1:]:
                hexagon, forced = _hex_view(view, difficulty, tuple(coord))
                if travel_mod.terrain_category(hexagon, forced).is_unknown:
                    plan.unknowns += 1
        mine["path"] = common
        mine["branches"] = [list(c) for c in rendezvous.approaches.values()]
    else:
        mine["path"] = list(course)

    mine["plan"] = plan
    # And next to the land journey, the river one: it is always computed, so
    # whoever plays sees the two counts together instead of having to guess
    # whether the river is worth it.
    mine["by_river"] = False
    mine["land"] = None
    mine["route"] = _boats._route_by_river(mine, chosen, vehicles, view, difficulty,
                                    departure, arrival)
    _redraw_travel(mine, mapping)

def _plan_summary(plan, mine: dict, mapping, chosen: list[dict],
                     departure, arrival, occupied: bool = False) -> None:
    theme.sep()
    with ui.row().classes("gap-2 flex-wrap items-center"):
        theme.stat_box(plan.total_cost, t("map.travel.activities"))
        theme.stat_box(_activity_text(plan.day_activities), t("map.travel.per_day"))
        theme.stat_box(plan.days if plan.possible else "—", t("map.travel.days"))
    if plan.max_estimate:
        ui.label(t("map.travel.estimate_most_part_path")) \
            .style("font-size:.75rem;color:var(--km-gold)")
    _boats._route_box(mine, mapping)
    rendezvous = mine.get("rendezvous")
    if rendezvous is not None and rendezvous.point is not None:
        _rendezvous_box(rendezvous, chosen)
    if mine.get("singles"):
        _singles_box(mine["singles"])
    if plan.speed_source:
        step = pace(plan.speed_m)
        ui.label(t("map.travel.party_speed", speed_source=plan.speed_source)
                 + (f" — {step}" if step else "")) \
            .style("font-size:.75rem;color:var(--km-muted);white-space:normal") \
            .tooltip(t("map.travel.kilometres_come_from_travel"))

    with ui.element("div").classes("km-scroll w-full").style("max-height:180px"):
        for waypoint in plan.waypoints:
            with ui.row().classes("items-center gap-2 w-full no-wrap"):
                ui.html(f'<span class="km-chip" style="font-size:.64rem">'
                        f'{waypoint.col},{waypoint.row}</span>')
                ui.label(waypoint.name or waypoint.category.name) \
                    .style("font-size:.76rem;flex:1")
                if waypoint.roads:
                    ui.label("🛣️").tooltip(t("map.travel.road_one_degree_terrain"))
                if waypoint.inner_one == "ford":
                    ui.label("〰️").tooltip(
                        t("map.travel.river_crossing_hex_forded", inner_cost=waypoint.inner_cost))
                elif waypoint.inner_one == "bridge":
                    ui.label("🌉").tooltip(t("map.travel.bridge_over_river_crossing"))
                elif waypoint.inner_one == "swim":
                    ui.label("🏊").tooltip(
                        t("map.travel.river_cutting_hex_swum"))
                edge = "var(--km-red)" if waypoint.cost is None else "var(--km-line)"
                ui.html(f'<span class="km-chip" style="font-size:.64rem;'
                        f'border-color:{edge}">'
                        f'{waypoint.cost if waypoint.cost is not None else "?"}</span>')

    for text in plan.blocking:
        ui.html(f'<div class="km-fc" style="font-size:.76rem;white-space:normal">'
                f'⛔ {theme.esc(text)}</div>')
    for text in plan.warnings:
        ui.label(t("map.travel.text", text=text)).style("font-size:.74rem;color:var(--km-gold);"
                                     "white-space:normal")
    if plan.blocking:
        ui.label(t("map.travel.planner_stops_here_rules")).style("font-size:.74rem;color:var(--km-muted)")
        return

    if occupied:
        ui.label(t("map.travel.first_sort_out_whoever"))             .style("font-size:.74rem;color:var(--km-red);white-space:normal")
        return

    with ui.row().classes("gap-2 w-full"):
        ui.button(t("map.travel.apply_move"), icon="check",
                  on_click=lambda: _apply_journey(mine, mapping, chosen, departure,
                                                    arrival, immediately=True)) \
            .props("dense outline color=amber")             .tooltip(t("map.travel.skips_result_markers_arrive"))
        ui.button(t("map.travel.depart"), icon="flag",
                  on_click=lambda: _apply_journey(mine, mapping, chosen, departure,
                                                    arrival, immediately=False)) \
            .props("dense outline color=amber") \
            .tooltip(t("map.travel.sets_party_its_way"))

def _activity_text(value: float) -> str:
    return "½" if value == 0.5 else f"{value:g}"

def _can_move(user, chosen: list[dict]) -> bool:
    """Who can really move the markers.

    The GM everyone; a player if among those leaving there is at least one
    character of theirs — the group travels together and only one presses
    the button. Whoever did it stays recorded in the journal.
    """
    if permissions.can(user, permissions.SEE_SECRETS):
        return True
    return any(permissions.can_on_character(user, p) for p in chosen)

# What really changes when a group leaves: the markers on the map, the
# Travel box, the row of portraits, the Party list, the journeys in progress
# of the Turn tab and the journal, which gets the new row.
#
# Before, `save_and_refresh` was called here, which redoes *every* panel of
# *every* window: the Turn tab, the Kingdom blocks, the stable, the whole
# journal. Those sit in the heap without a window, so the «foreground tab
# only» filter does not stop them and they were rebuilt even with the Map in
# front. It was two and a half seconds of work to move a marker.
DEPARTURE_PANELS = ("hexmap.map", "hexmap.travel", "hexmap.party",
                     "party.characters", "turn.journeys", "turn.journal")

def _apply_journey(mine: dict, mapping, chosen: list[dict], departure, arrival,
                     immediately: bool) -> None:
    user = theme.user()
    if not _can_move(user, chosen):
        theme.notify(t("map.travel.you_can_only_move"),
                       "negative")
        return
    plan = mine.get("plan")
    if plan is None or not plan.possible:
        return
    occupied = journeys_by_character({p["id"] for p in chosen})
    if occupied:
        theme.notify(t("map.travel.somebody_party_already_travelling"), "negative")
        return

    if not immediately and len(chosen) > 1:
        # Two reasons to start k journeys instead of one. The first: a single
        # leg with people on different hexes inside would teleport them onto
        # the course of the first, so a rendezvous is needed. The second:
        # «together» off, wherever they are — it is the choice of not waiting
        # for each other, and it holds even leaving from the same hex, because
        # the Speed stays each one's own.
        scattered = _leave_scattered(chosen)
        if not mine.get("together", True) or (scattered and mine.get("rendezvous") is None):
            if mine.get("together", True):
                theme.notify(t("map.travel.there_no_meeting_point"), "warning")
            _parts_each_alone(mine, mapping, chosen, arrival)
            return

    names = ", ".join(p["name"] for p in chosen)
    rendezvous = mine.get("rendezvous")
    view = _common._current_view(mine)
    difficulty = STATE.archive.campaign_difficulty(STATE.campaign)
    vehicles = _markers._vehicles_in_play()
    borders = STATE.archive.campaign_borders(STATE.campaign)
    sail, _why = travel_mod.party_sails(
        chosen, vehicles, bool(mine.get("aboard")))
    # The cost of a waypoint is the cell plus the side crossed to enter it: a
    # ford on the path is an activity the group really pays.
    waypoint_costs_ = travel_mod.waypoint_costs(plan)
    db_path = [list(c) for c in mine["path"]]
    if len(db_path) == 1 and rendezvous is None:
        # The journey inside the departure hex: for whoever makes the days
        # pass it is a leg from a hex to itself, which costs the road.
        db_path = [db_path[0], list(db_path[0])]
        waypoint_costs_ = [plan.total_cost]
    drawing = _road_drawing(mine)
    vehicle = _journey_vehicle(mine, chosen)
    mode = _crossing(mine, chosen, vehicles, view, difficulty)
    legs = (_legs_from_rendezvous(rendezvous, chosen, mode, mine.get("forced_march"),
                                 plan.day_activities, drawing)
              if rendezvous is not None and not immediately else
              [{"characters": [p["id"] for p in chosen],
                "path": db_path,
                "costs": waypoint_costs_,
                "activities_per_day": plan.day_activities,
                # The vehicle travels with the leg, not with the characters: a
                # boat can leave even with nobody aboard, and whoever resolves
                # the day must know which one to move.
                "stable_id": vehicle,
                "progress": 0.0, "waiting": False,
                **drawing}])
    STATE.archive.create_journey({
        "id": uuid.uuid4().hex[:12],
        "campaign_id": STATE.campaign,
        "characters": [p["id"] for p in chosen],
        "stable_id": vehicle,
        "departure": f"{departure[0]},{departure[1]}",
        "arrival": f"{arrival[0]},{arrival[1]}",
        # Where one arrives inside that hex, when the water divides it. A
        # point and not a shore number: days pass between departure and
        # arrival, and in between the GM may have drawn another water line.
        "pos_x": (mine.get("arrival_pos") or (None, None))[0],
        "pos_y": (mine.get("arrival_pos") or (None, None))[1],
        "path": db_path,
        "costs": waypoint_costs_,
        "legs": legs,
        "activity_cost": plan.total_cost,
        "days": plan.days,
        "activities_per_day": plan.day_activities,
        "progress": 0.0,
        "departure_day": int((STATE.k.get("clock") or {}).get("days", 0)),
        "forced_march": 1 if plan.forced_march else 0,
        "status": "completed" if immediately else "in_progress",
        "turn_created": STATE.k["turn"],
        "created_by": user.id if user else None,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    })

    if immediately:
        # Where one enters from decides on which bank one stops, where a river
        # cuts the arrival hex.
        coming_from = (tuple(mine["path"][-2])
                      if len(mine.get("path") or []) > 1 else None)
        move_characters([p["id"] for p in chosen], arrival, coming_from,
                         stable_id=vehicle,
                         where=mine.get("arrival_pos"))
        STATE.record(
            t("map.travel.journey_from_activities_days", names=names, departure=departure[0], departure2=departure[1], arrival=arrival[0], arrival2=arrival[1], total_cost=plan.total_cost, days=plan.days), "map",
            t("map.travel.speed_label", source=plan.speed_source)
            + (t("turn.forced_march_suffix") if plan.forced_march else ""))
        theme.notify(t("map.travel.now", names=names, arrival=arrival[0], arrival2=arrival[1]))
    else:
        STATE.record(
            t("map.travel.departed_towards_activities_days", names=names, arrival=arrival[0], arrival2=arrival[1], total_cost=plan.total_cost, days=plan.days), "map")
        theme.notify(t("map.travel.way_they_advance_while"))

    # The whole proposal vanishes, not only the path: the branches and the
    # little circle of the meeting point are drawn separately, and leaving
    # them there would mean seeing the blue arrow of a journey that has by
    # now left, on top of its own dashed route.
    _common._forget_plan(mine)
    mine["travel_pcs"] = []
    # And the vehicle: it stayed in hand, lit on the map, while whoever was on
    # it had already been dropped.
    mine["travel_vehicle"] = None
    mine["aboard"] = False
    theme.save_and_refresh_panels(DEPARTURE_PANELS)
    _redraw_travel(mine, mapping)

def _journey_vehicle(mine: dict, chosen: list[dict]) -> str | None:
    """The vehicle leaving with this journey, or None.

    By river it is the boat in hand: the journey is its own. By land it is
    the wagon in hand, or the one someone among the chosen is already on. A
    **boat** instead never follows a land journey: whoever leaves on foot
    leaves it in the water where it is, and before it was dragged onto the
    arrival hex.
    """
    in_hand = mine.get("travel_vehicle")
    if mine.get("by_river") and in_hand:
        return in_hand
    candidates = [in_hand] + [p.get("stable_id") for p in chosen]
    for sid in candidates:
        entry = STATE.archive.stable_vehicle(sid) if sid else None
        if entry and travel_mod.vehicle_kind(entry) != "water":
            return sid
    return None

def _road_drawing(mine: dict) -> dict:
    """What is needed to redraw the road as it was: shores, atoms, arrival.

    A departed route was drawn from center to center: it did not start from
    the marker and did not arrive in the aimed piece, and the blue arrow you
    had in front and the amber route that remained were two different roads.
    Here the **nodes** touched (hex and shore), the **atoms** counted and the
    **arrival spot** are frozen in the leg: they are the same three data the
    proposal is drawn with, and with which the route is redrawn one day at a
    time.
    """
    where = mine.get("arrival_pos")
    nodes = [tuple(n) for n in (mine.get("nodes") or ())]
    path = [tuple(c) for c in (mine.get("path") or ())]
    if not nodes and len(path) > 1:
        # Aimed with the right button: the shores were found by the count,
        # not the hand. They are frozen all the same — rebuilding them every
        # time would mean redrawing the route on tomorrow's water, not on that
        # of when it left — and the last is the aimed piece.
        shores = _markers._shores_of(mine)
        if shores is not None:
            orient = STATE.k["map"]["orientation"]
            nodes = [tuple(n) for n in travel_mod.nodes_on_course(
                path, shores.banks, shores.crossings, orient,
                shores.from_where.get(path[0], 0))]
            if where and nodes and (nodes[-1][0], nodes[-1][1]) == path[-1]:
                faces = shores.banks.get(path[-1]) or ()
                bank = (sections.face_of_point(faces, tuple(where))
                        if len(faces) > 1 else None)
                if bank is not None:
                    nodes[-1] = (nodes[-1][0], nodes[-1][1], int(bank))
    outside = {
        "nodes": [[int(n[0]), int(n[1]), int(n[2])] for n in nodes],
        "stretches": {str(k): [int(a) for a in v]
                   for k, v in (mine.get("atom_stretches") or {}).items() if v},
        "where": [float(where[0]), float(where[1])] if where else None,
    }
    states = ((mine.get("route") or {}).get("statuses") or []) if mine.get("by_river") else []
    if states:
        # On a boat: the route junction by junction, and for every waypoint
        # the last junction that belongs to it. It is with this that the
        # passing day stops the boat on a junction and the route is redrawn on
        # the water.
        db_route, waypoint_statuses = [], []
        spot = -1
        for index, (node, hexagon) in enumerate(states):
            if node is None:
                continue
            if not db_route or db_route[-1][1:] != [int(hexagon[0]), int(hexagon[1])]:
                spot += 1
                waypoint_statuses.append(len(db_route))
            elif spot > 0:
                # For every waypoint paid the last junction of its hex; for the
                # first — not paid yet — the junction of the boat itself.
                waypoint_statuses[-1] = len(db_route)
            db_route.append([waterways.node_text(node), int(hexagon[0]),
                             int(hexagon[1])])
        if len(waypoint_statuses) == len(path):
            outside["route"] = db_route
            outside["waypoint_statuses"] = waypoint_statuses
    return outside

def move_characters(ids: list[str], arrival: tuple[int, int],
                     coming_from=None, stable_id: str | None = None,
                     where=None) -> None:
    """Brings the markers onto the arrival hex, and the boat with them.

    It lives here and not in the Turn tab because it is the map that knows
    what «being on a hex» means; the turn calls it when it resolves a journey.

    `where` is the spot inside the hex, when the journey had one: it is the
    shore that was **aimed at**, and wins over everything. `coming_from` is
    the fallback — the previous hex of the course — and says the shore one
    enters from, which is where one stops when nobody asked to go further.

    And the vehicles on the map go with them. A wagon has no position of its
    own — it is where whoever tows it is — but a boat has one, because it is
    in the middle of the river: without moving it, whoever had travelled by
    boat reached the destination and the boat stayed still at the departure.
    """
    if where is None:
        where = _spot_arriving(arrival, coming_from)
    for char_id in ids:
        STATE.archive.update_character(
            char_id, hex_col=arrival[0], hex_row=arrival[1],
            pos_x=None if where is None else where[0],
            pos_y=None if where is None else where[1])
    moved_ones = STATE.archive.move_vehicles_with(STATE.campaign, ids, arrival, stable_id,
                                              where)
    _leave_remaining_vehicles(ids, moved_ones)

def _leave_remaining_vehicles(ids, moved_ones) -> None:
    """Whoever arrived on foot is no longer aboard the vehicle left behind."""
    for char_id in ids:
        char = STATE.archive.character(char_id)
        if char and char.get("stable_id") and char["stable_id"] not in moved_ones:
            STATE.archive.update_character(char_id, stable_id=None)

def _spot_from_point(coord, point):
    """The spot of the section the click fell in, or None if it does not cut."""
    return _markers.spot_of_section(coord, _bank_from_point(coord, point),
                            _common.sections_map())

def _spot_arriving(arrival, coming_from):
    """The spot one stops on when entering a hex from a given neighbour."""
    return _markers.spot_of_section(arrival, _bank_arriving(arrival, coming_from),
                            _common.sections_map())

def _bank_from_point(coord, point) -> int:
    """The section of the hex the click fell in.

    Not «the one with the nearest point»: **the one containing the click**.
    As long as a section was a group of sides nothing better could be asked,
    because a group of sides is not a figure and has no inside. A face has,
    and then the right question is the direct one — if the click falls inside
    the little triangle in the middle, the answer is the little triangle, not
    the big slice next to it.

    Outside every face — the click on the water line — nearness decides, and
    that is what `sections.face_of_point` does.
    """
    faces = _common.sections_map().get(tuple(coord))
    if not faces or len(faces) < 2 or point is None:
        return 0
    m = STATE.k["map"]
    size = float(m["size"])
    origin = (float(m["origin_x"]), float(m["origin_y"]))
    orient = m["orientation"]
    cx, cy = hexgrid.hex_center(coord[0], coord[1], size, origin, orient)
    where = ((point[0] - cx) / size, (point[1] - cy) / size)
    found_one = sections.face_of_point(faces, where)
    return 0 if found_one is None else found_one

def _bank_arriving(arrival, coming_from) -> int:
    """The bank one arrives on when entering from a given neighbour."""
    banks = _common.sections_map()
    if not banks.get(tuple(arrival)) or coming_from is None:
        return 0
    orient = STATE.k["map"]["orientation"]
    neighbours = hexgrid.neighbours(arrival[0], arrival[1], orient)
    try:
        direction = neighbours.index(tuple(coming_from))
    except ValueError:
        return 0
    return travel_mod.bank_of_side(banks, arrival, direction)

def _journey_destination(mine: dict, mapping, coord: tuple[int, int],
                          point=None) -> None:
    """The right button aimed at a hex: computes the journey to there.

    `point` is the exact coordinates of the click. On a boat they matter more
    than the hex: the water you are after may run on the **edge** of a cell,
    and requiring the clicked hex to have it on it means giving an error to
    whoever aimed at the river a finger further on.
    """
    if not permissions.can(theme.user(), permissions.PLAN_TRAVEL):
        return
    if mine.get("travel_mode") != "choose":
        return
    if not mine.get("travel_pcs"):
        theme.notify(t("map.travel.first_choose_who_leaves"), "warning")
        return
    mine.update(col=coord[0], row=coord[1])
    _compute_journey(mine, mapping, arrival_point=point)

def _place_marker(mine: dict, mapping, coord: tuple[int, int],
                    point=None) -> None:
    """Puts on the map a character that was not there yet.

    If the hex is cut by a river, the bank is decided by the exact point you
    clicked: it is the only way to say it without asking in words.
    """
    char_id = mine.get("place_pc")
    char = STATE.archive.character(char_id) if char_id else None
    if char is None:
        mine["travel_mode"] = None
        mine["place_pc"] = None
        _boats._placing_done(mine)
        return
    if not permissions.can_on_character(theme.user(), char):
        theme.notify(t("map.travel.you_cannot_move_this"), "negative")
        return
    spot = _spot_from_point(coord, point)
    STATE.archive.update_character(
        char_id, hex_col=coord[0], hex_row=coord[1],
        pos_x=None if spot is None else spot[0],
        pos_y=None if spot is None else spot[1])
    STATE.record(t("map.travel.put_map", name=char["name"], coord=coord[0], coord2=coord[1]), "map")
    mine["travel_mode"] = None
    mine["place_pc"] = None
    _boats._placing_done(mine)
    theme.save_and_refresh_panels(_MARKER_PANELS)
    _redraw_travel(mine, mapping)

def _redraw_travel(mine: dict, mapping) -> None:
    """Refreshes map, Travel box and row of portraits together.

    And the other windows: every plan change goes through here — the
    destination chosen with the right button, the count redone when you let
    go of the ruler, the cancelled journey — so it is the right place to tell
    the others what you are preparing.
    """
    _ruler._send_field(mine)
    _ruler._trace_from_plan(mine)
    mapping.refresh()
    for key in ("travel", "party", "travel_slider", "detail"):
        panel = mine.get(key)
        if panel is not None:
            panel.refresh()

# --------------------------------------------------------------------------
# The row of portraits below the map: who is there, where, and how far along
# their journey. It is also the place from which departure is confirmed.
def _map_party_panel(mine: dict, mapping) -> None:
    user = theme.user()
    if user is None:
        return
    characters = STATE.characters()
    if not characters:
        return
    visible_ones = {p["id"] for p in _common._current_view(mine).markers()}
    journeys = {}
    for v in STATE.archive.list_journeys(STATE.campaign, "in_progress"):
        for char_id in v["characters"]:
            journeys[char_id] = v
    chosen = set(mine.get("travel_pcs") or [])

    with ui.row().classes("items-center gap-2 w-full no-wrap") \
            .style("overflow-x:auto;padding:6px 2px 2px"):
        for char in characters:
            _map_portrait(char, mine, mapping, char["id"] in chosen,
                            char["id"] in visible_ones, journeys.get(char["id"]), user)
        ui.element("div").style("flex:1;min-width:8px")
        _departure_controls(mine, mapping)

def _map_portrait(char: dict, mine: dict, mapping, chosen_one: bool, on_the_map: bool,
                    journey: dict | None, user) -> None:
    """A portrait of the row: clicking it takes that character in hand."""
    color = images.valid_color(char.get("color"))
    edge = color if chosen_one else "var(--km-line)"
    shadow = "box-shadow:0 0 0 2px #7fc3e855;" if chosen_one else ""
    with ui.element("div") \
            .style(f'border:2px solid {edge};border-radius:10px;padding:3px;'
                   f'background:#191410;cursor:pointer;flex:0 0 auto;width:98px;{shadow}') \
            .on("click", lambda _=None, p=char: _portrait_click(p, mine, mapping)):
        with ui.row().classes("items-center gap-1 no-wrap"):
            initials = "".join(x[0] for x in (char["name"] or "?").split()[:2]).upper()
            below = (f'<div style="position:absolute;inset:0;border-radius:6px;'
                     f'background:#241d15;border:1px solid {color};display:flex;'
                     f'align-items:center;justify-content:center;color:{color};'
                     f'font-family:Cinzel,serif;font-size:.8rem">'
                     f'{theme.esc(initials)}</div>')
            above = ""
            if char.get("token") or char.get("portrait"):
                source_text = images.address(
                    theme.with_prefix("/assets/characters"), _common.CHARACTER_FOLDER,
                    str(char.get("token") or char.get("portrait")),
                    images.MARKER_SIDE)
                # The image as *background* and not as <img>: an <img> that
                # does not arrive draws the broken-image icon, a background
                # that does not arrive draws nothing and lets the initials
                # underneath show. No javascript, and the fallback is the
                # normal CSS case.
                above = (f'<div style="position:absolute;inset:0;'
                         f'border-radius:6px;border:1px solid {color};'
                         # No quotes around the address: the file name is made
                         # by `safe_file_name`, which leaves only letters,
                         # digits, dot and dash, and the remaining part is
                         # already percent-encoded.
                         f'background:url({theme.esc(source_text)}) '
                         f'center/cover no-repeat"></div>')
            ui.html(f'<div style="position:relative;width:34px;height:34px;'
                    f'flex:0 0 auto">{below}{above}</div>')
            ui.html(f'<b class="km-title" style="font-size:.66rem;line-height:1.1">'
                    f'{theme.esc(char["name"][:11])}</b>')
        if journey is not None:
            _progress_bar(journey)
        elif not on_the_map:
            ui.html(t("map.travel.div_style_font_size"))
        else:
            ui.html(f'<div style="font-size:.58rem;color:var(--km-muted)">'
                    f'{char["hex_col"]},{char["hex_row"]}</div>')
        if not permissions.can_on_character(user, char):
            ui.tooltip(t("map.travel.not_your_character_you"))

def _progress_bar(journey: dict) -> None:
    """How far to arrival, as a progress bar."""
    costs = list(journey.get("costs") or [])
    total = sum(float(c or 0) for c in costs)
    done = float(journey.get("progress") or 0)
    share = min(1.0, done / total) if total else 0.0
    missing_ones = daily.days_missing(costs, done,
                                       float(journey.get("activities_per_day") or 1))
    ui.html(f'<div style="height:5px;background:#241d15;border-radius:3px;'
            f'overflow:hidden;margin:2px 0"><div style="height:100%;width:'
            f'{share * 100:.0f}%;background:#7fc3e8"></div></div>'
            f'<div style="font-size:.58rem;color:var(--km-gold-dim)">'
            f'&#8594; {theme.esc(journey["arrival"])} · {missing_ones} '
            f'{tn("common.day_word", missing_ones)}</div>')

def _portrait_click(char: dict, mine: dict, mapping) -> None:
    """Click on the portrait: if it is on the map it takes it, if not it has it placed."""
    fresh = STATE.archive.character(char["id"]) or char
    if fresh["hex_col"] is None or fresh["hex_row"] is None:
        if not permissions.can_on_character(theme.user(), fresh):
            theme.notify(t("map.travel.not_your_character"), "negative")
            return
        mine["travel_mode"] = "place"
        mine["place_pc"] = fresh["id"]
        _redraw_travel(mine, mapping)
        theme.notify(t("map.travel.click_map_where", name=fresh["name"]), "info")
        return
    chosen = list(mine.get("travel_pcs") or [])
    if fresh["id"] in chosen:
        chosen.remove(fresh["id"])
    else:
        chosen.append(fresh["id"])
    mine["travel_pcs"] = chosen
    _common._forget_plan(mine)
    # Choosing someone means wanting to move them: we switch the mode on, or
    # the box to look at the journey would stay hidden.
    if chosen and not mine.get("travel_mode"):
        mine["travel_mode"] = "choose"
        if mine.get("apply_slider"):
            mine["apply_slider"]()
    _redraw_travel(mine, mapping)

def _departure_controls(mine: dict, mapping) -> None:
    """Confirms or cancels the proposed journey, at the end of the row of portraits."""
    if mine.get("travel_mode") == "place":
        ui.html(t("map.travel.span_class_km_chip"))
        ui.button(t("common.cancel"), on_click=lambda: _cancel_position(mine, mapping)) \
            .props("dense flat size=sm color=grey")
        return

    plan = mine.get("plan")
    if plan is None:
        if mine.get("travel_pcs"):
            ui.html(t("map.travel.span_class_km_chip_2"))
        return
    if not plan.possible:
        ui.html(t("map.travel.span_class_km_chip_3"))
        ui.button(t("common.cancel"), on_click=lambda: _reset_journey(mine, mapping)) \
            .props("dense flat size=sm color=grey")
        return

    by_id = {p["id"]: p for p in STATE.characters()}
    chosen = [by_id[i] for i in mine.get("travel_pcs") or [] if i in by_id]
    if journeys_by_character({p["id"] for p in chosen}):
        ui.html(t("map.travel.span_class_km_chip_4"))
        return

    days = plan.days
    # «at most» when the count rests on never-seen hexes: the same thing the
    # arrow on the map and the warning in the Travel box say.
    ceiling = t("map.travel.most") if plan.max_estimate else ""
    ui.html(t("map.travel.span_class_km_chip_5", ceiling=ceiling, total_cost=plan.total_cost, days=days, v=tn("common.day_word", days)))
    ui.button(t("map.travel.depart"), icon="flag", on_click=lambda: _parts(mine, mapping)) \
        .props("dense color=amber") \
        .tooltip(t("map.travel.sets_party_its_way"))
    ui.button(t("common.cancel"), on_click=lambda: _reset_journey(mine, mapping)) \
        .props("dense flat size=sm color=grey")

def _cancel_position(mine: dict, mapping) -> None:
    mine["travel_mode"] = None
    mine["place_pc"] = None
    _redraw_travel(mine, mapping)

def _parts(mine: dict, mapping) -> None:
    """The «Depart» button of the row of portraits.

    Works out again who leaves and from where: between computing the path and
    the click time may have passed, and the group may no longer be the same.
    """
    by_id = {p["id"]: p for p in STATE.characters()}
    chosen = [by_id[i] for i in mine.get("travel_pcs") or [] if i in by_id]
    departure, _warning = _departure_of(chosen)
    plan = mine.get("plan")
    if not chosen or departure is None or plan is None or not plan.possible:
        return
    path = mine.get("path") or []
    at_home = len(path) == 1 and mine.get("arrival_pos")
    at_meeting_point = len(path) == 1 and mine.get("rendezvous") is not None
    if len(path) < 2 and not (at_home or at_meeting_point):
        return
    _apply_journey(mine, mapping, chosen, departure, tuple(path[-1]), immediately=False)

def _travel_toggle(mine: dict, mapping) -> None:
    """The button that switches travel mode on.

    The icon is also a toggle of its own: clicking it shows and hides the
    routes already under way on the map, and gets barred when they are
    hidden. The rest of the button enters and leaves the mode.
    """
    if not permissions.can(theme.user(), permissions.PLAN_TRAVEL):
        return

    @ui.refreshable
    def button() -> None:
        is_on = mine.get("travel_mode") == "choose"
        routes = mine.get("show_journeys", True)
        with ui.button(on_click=change)                 .props("dense " + ("color=amber" if is_on else "flat color=grey"))                 .tooltip(t("map.travel.click_marker_whoever_leaves")):
            icon = ui.icon("hiking").classes("" if routes else "km-strike")
            # `.stop` because the click on the icon must not also enter or
            # leave the mode: they are two different toggles.
            icon.on("click.stop", toggle_routes)
            ui.label(t("map.travel.travel")).style("margin-left:4px")

    def change() -> None:
        is_on = mine.get("travel_mode") != "choose"
        _common._single_mode(mine, "travel" if is_on else "")
        mine["travel_mode"] = "choose" if is_on else None
        if is_on:
            # The hex chosen before is not a destination: entering the mode the
            # «To:» must go back to empty instead of showing a leftover nobody
            # just pointed at.
            mine.update(col=None, row=None)
        if mine.get("apply_slider"):
            mine["apply_slider"]()
        _redraw_travel(mine, mapping)
        mine["detail"].refresh()
        button.refresh()

    def toggle_routes() -> None:
        mine["show_journeys"] = not mine.get("show_journeys", True)
        mapping.refresh()
        button.refresh()

    mine["travel_button"] = button
    button()

def _hex_view(view, difficulty: dict, coord):
    """(hex, imposed difficulty) as the viewer may see them."""
    if not view.can_see(*coord):
        return None, None
    hexagon = view.hex_for(*coord)
    if not _common.waters_active():
        hexagon = _common._without_water(hexagon)
    return hexagon, difficulty.get(coord)

def _bank_of(chosen: list[dict], coord, banks: dict | None = None) -> int:
    """The section whoever leaves from there is on.

    The group leaves from a single hex, so the first found there is enough:
    if they were on two different sections of the same hex they would not be
    a group. Whoever is aboard a vehicle placed there leaves from the
    **vehicle's** section: it is the vehicle that leaves, and a passenger who
    boarded from a sheet may have no spot of their own written — with two
    aboard, one with the wagon's spot and one without, the course started now
    from one shore now from the other.
    """
    for char in chosen:
        if (char.get("hex_col"), char.get("hex_row")) != tuple(coord):
            continue
        sid = char.get("stable_id") or ""
        entry = STATE.archive.stable_vehicle(sid) if sid else None
        if entry is not None and travel_mod.where_it_is(entry) == tuple(coord):
            return _markers.section_of(entry, banks)
        return _markers.section_of(char, banks)
    return 0

def _course_to_shore(departure, arrival, bank: int, cost_of, orientation: str,
                         inside, passage, banks, departure_bank: int, crossings,
                         water) -> list | None:
    """The course to **that shore** of the arrival hex, or None.

    The whole field is explored, without stopping at the first gate of the
    hex: the aimed shore may have its best gate on another side.
    """
    field = travel_mod.cost_field(departure, cost_of, orientation, inside,
                                    None, passage, banks, departure_bank, crossings,
                                    water)
    return field.course_to_shore(departure, (int(arrival[0]), int(arrival[1]),
                                                int(bank)))

def _cost_for(view, difficulty: dict, coord, sail: bool = False):
    """Activities to enter that hex, or None if there is no way through there."""
    hexagon, forced = _hex_view(view, difficulty, coord)
    return travel_mod.travel_cost(hexagon, forced, sail)[0]

def _aboard_by_water(mine: dict, chosen: list[dict],
                       vehicles: dict | None = None) -> bool:
    """The group is on a vehicle that passes water, right now.

    It distinguishes swimming from sailing, and two ask the question: the
    pathfinder and the arrow drawing. It lives here once, because if the two
    answered differently the usual defect would return — one road computed
    and another drawn.
    """
    if not mine.get("aboard") or not chosen:
        return False
    if vehicles is None:
        vehicles = _markers._vehicles_in_play()
    return any(travel_mod.crosses_water(entry)
               for entry in travel_mod.party_vehicles(chosen, vehicles))

def _crossing(mine: dict, chosen: list[dict], vehicles: dict, view,
                     difficulty: dict):
    """How *this* group crosses the map: the cells and the sides.

    A single place the two functions the pathfinder wants come from, so the
    plan, the rendezvous, the ruler and the departure all answer the same
    question. If the group has a boat both change together: water hexes
    become passable and Water Borders stop stopping it.

    `passage` stays None when no border is marked: so on a map without water
    the pathfinder is exactly the one of before, without even one extra call
    per side. The `banks` do the same: where there are none, a hex stays a
    single node.
    """
    sail, _why = travel_mod.party_sails(
        chosen, vehicles, bool(mine.get("aboard")))
    # Swimming and sailing both pass water, and are not the same thing. A
    # **boat** sits on the water: for it shores do not exist, and the river
    # is the road. Whoever **swims** walks on land like everyone, and crosses
    # where needed: the shores remain, and it is on a shore that their marker
    # is, from a shore that their arrow leaves, a shore that the mouse points
    # at. Treating them the same was the defect that showed: with swimming the
    # ruler went back to aiming at hex centers while the confirmed journey was
    # drawn on the shores, and the two arrows told two different roads.
    # Whoever swims **but is on a boat** sails: they are aboard, and aboard
    # one goes by water. Swimming counts when it is the way one crosses, not
    # when it is just something written on the sheet.
    swims = (travel_mod.party_swims(chosen)[0]
             and not _aboard_by_water(mine, chosen, vehicles))
    if _common.waters_active():
        borders = STATE.archive.campaign_borders(STATE.campaign)
        banks = {} if (sail and not swims) else _common.sections_map()
        # Without banks there are no shores to join, and the bridges inside
        # the hex have nothing to do: whoever sails passes anyway.
        crossings = STATE.archive.campaign_crossings(STATE.campaign) if banks else {}
        # And where the water runs **inside** every hex: the shores say into
        # how many pieces it divides it, this says where it runs, which is
        # what is needed to know how much one must coast along. The hexes the
        # water does not divide are in it too: a river entering and stopping
        # makes no shores but must be walked around all the same.
        #
        # For whoever swims the water is where it is and closes nothing, and
        # every pair of shores touches: the counts stay those of before — a
        # hex stopping nobody costs what the rules say — and the shores are
        # there to say where you are.
        if swims and banks:
            water = travel_mod.OPEN_WATER
            crossings = travel_mod.swim_crossings(banks, crossings)
        else:
            water = ({} if sail
                     else STATE.archive.campaign_water(
                         STATE.campaign, STATE.k["map"]["orientation"]))
    else:
        borders, banks, crossings, water = {}, {}, {}, {}
        swims = False

    def cost_of(coord):
        return _cost_for(view, difficulty, coord, sail)

    passage = None
    if borders:
        def passage(a, b):                                       # noqa: F811
            return travel_mod.border_cost(a, b, borders, sail)

    return _Crossing(cost_of, passage, borders, sail, banks, crossings,
                            water, swims, view, difficulty, vehicles,
                            _common.inside_map(STATE.k["map"]),
                            STATE.k["map"]["orientation"])

@dataclass
class _Crossing:
    """How a group crosses the map: cells, sides and banks, all together."""

    cost_of: object
    passage: object
    borders: dict
    sail: bool
    banks: dict
    crossings: dict = field(default_factory=dict)
    water: dict = field(default_factory=dict)
    swims: bool = False
    # The rest of the context it was built with: so rendezvous, separate
    # journeys and legs receive it whole instead of as six parameters.
    view: object = None
    difficulty: dict = field(default_factory=dict)
    vehicles: dict = field(default_factory=dict)
    inside: object = None
    orientation: str = "pointy"

    def __iter__(self):
        """Still unpacks as before, for whoever uses only the first four."""
        return iter((self.cost_of, self.passage, self.borders, self.sail))

    def banks_of(self, chosen: list[dict]) -> dict:
        """The bank everyone is on right now, for the pathfinder."""
        return {p["id"]: _markers.section_of(p, self.banks) for p in chosen}

def _waypoint_for(view, difficulty: dict, coord):
    """The waypoint in the form `travel.plan_` wants."""
    hexagon, forced = _hex_view(view, difficulty, coord)
    return coord, hexagon, forced

def _valid_course(traced_one, departure, orientation, inside, cost_of,
                    passage=None, banks=None, departure_bank: int = 0,
                    crossings=None, nodes=None):
    """Cleans the course drawn with the mouse, or None if it does not stand.

    It comes from the browser, so it is not trusted: it must start from where
    the group is, stay inside the map, proceed hex by hex without jumps, not
    cross terrains one cannot travel on, not hop over a closed border and not
    jump from one bank to the other inside the same hex. The cost is
    recomputed by the server anyway: nothing of the browser's count is kept.

    **Passing through the same hex again is allowed**, and is paid every
    time. Before, it was forbidden, and with itself it forbade a road that
    exists on the map: one enters a hex cut by a river, goes on, and further
    on a bridge brings one back to the other shore of the same hex. That
    shore could no longer be reached, because the hex «had already been
    used». The count adds up steps and not hexes, so two passages cost twice:
    counting them once would be the shortcut that lets whoever wanders more
    arrive first.

    The course comes in and goes out as a list of hexes — that is how the
    players call it — but in here one walks on the nodes, which are (hex,
    bank).
    """
    steps: list[tuple[int, int]] = []
    node = None
    for entry in traced_one:
        try:
            step = (int(entry[0]), int(entry[1]))
        except (TypeError, ValueError, IndexError):
            return None
        if not inside(step):
            return None
        if not steps:
            node = travel_mod.node_of(banks, step, departure_bank)
            steps.append(step)
            continue
        if step == steps[-1]:
            continue                           # still on the same cell
        if cost_of(step) is None:
            return None                        # there is no way through there
        if passage is not None and passage(steps[-1], step) is None:
            return None                        # there is water between the two and it cannot be forded
        # The step must be among those leaving from the bank we are on: this
        # is what prevents hopping the river inside a hex.
        forward = next((n for n, vic in travel_mod.steps_from(node, orientation, banks)
                       if vic == step), None)
        if forward is None and nodes:
            # The shores the hand drew: **its own** is tried before looking for
            # any. Accepting the course by passing elsewhere and then drawing
            # it there is precisely the defect one starts from.
            reachable_ones = {n for n, _c in
                             travel_mod.inner_jumps(node, banks, crossings)}
            for entry in nodes:
                try:
                    other_one = (int(entry[0]), int(entry[1]), int(entry[2]))
                except (TypeError, ValueError, IndexError):
                    break
                if other_one not in reachable_ones:
                    continue
                candidate = next(
                    (n for n, vic in travel_mod.steps_from(other_one, orientation, banks)
                     if vic == step), None)
                if candidate is not None:
                    node, forward = other_one, candidate
                    break
        if forward is None and crossings:
            # Crossings inside the hex: one changes shore staying where one
            # is, and from there the step exists. **In a chain too**, if the
            # bridges chain up: where the river cuts the hex into three or
            # more pieces one enters the first, passes into the second, and
            # only from that one leaves by the side needed. Trying a single
            # one was no rule, it was the limit of this reading — and it made a
            # piece in the middle of a hex a place one could not reach.
            for other_one, _chain in travel_mod.inner_jumps(node, banks, crossings):
                if other_one == node:
                    continue
                candidate = next(
                    (n for n, vic in travel_mod.steps_from(other_one, orientation, banks)
                     if vic == step), None)
                if candidate is not None:
                    node, forward = other_one, candidate
                    break
        if forward is None:
            return None                        # a jump, or the other bank
        node = forward
        steps.append(step)

    if steps and steps[0] == tuple(departure) and len(steps) == 1:
        # A journey inside the departure hex: the row of hexes is a single
        # one, but the nodes say the shore changes. How much it costs and
        # whether it can be done is decided by the atom count, not by this
        # check.
        how_many = sum(1 for entry in (nodes or ()) if
                     (int(entry[0]), int(entry[1])) == tuple(departure))
        return steps if how_many >= 2 else None
    if len(steps) < 2 or steps[0] != tuple(departure):
        return None
    if len(steps) > _common.MAX_GRID_CELLS:
        return None
    return steps

# --------------------------------------------------------------------------
# Leaving scattered. If the travellers are not all on the same hex, the
# journey has two stages: first everyone reaches the rendezvous point at
# their *own* Speed, then one goes on together at the pace of the slowest —
# which is what the rules say, applied only to the part really done together.
def _activities_of(char: dict, vehicles: dict, march: bool) -> float:
    """Activities per day of a character, vehicle and forced march included."""
    speed, _source, _warnings = travel_mod.compose_speed([char], vehicles)
    return travel_mod.available_activities(speed, march)

def _valid_branches(traced_branches, chosen: list[dict], orientation: str,
                 inside, cost_of, passage, banks, crossings) -> dict:
    """The branches the browser sent, if they hold: `{char_id: course}`.

    Each must start from where that character is and stand like any drawn
    course (`_valid_course`). Those that do not hold are dropped, and for
    that character the branch is redone by the count.
    """
    outside: dict = {}
    by_id = {p["id"]: p for p in chosen}
    for entry in traced_branches if isinstance(traced_branches, list) else []:
        if not isinstance(entry, dict):
            continue
        char = by_id.get(str(entry.get("id")))
        path = entry.get("path")
        if char is None or not isinstance(path, list) or len(path) < 2:
            continue
        if char.get("hex_col") is None:
            continue
        departure = (char["hex_col"], char["hex_row"])
        course = _valid_course(path, departure, orientation, inside,
                                  cost_of, passage, banks,
                                  _markers.section_of(char, banks), crossings,
                                  entry.get("nodes"))
        if course:
            outside[char["id"]] = course
    return outside

def _rendezvous_for(mine: dict, chosen: list[dict], arrival, mode, cost_of,
                common_road=None, common_bank: int | None = None,
                traced_branches=None):
    """The rendezvous plan, or None if they already all leave from the same hex.

    With `common_road` the road the group makes as one is the hand-drawn one
    and the meeting point is its first hex; if it does not hold — someone
    cannot get there — one goes back to finding it alone, which is better
    than giving nothing.
    """
    view, difficulty, vehicles = mode.view, mode.difficulty, mode.vehicles
    passage, banks, crossings, water = mode.passage, mode.banks, mode.crossings, mode.water
    departures = {p["id"]: (p["hex_col"], p["hex_row"]) for p in chosen
                if p["hex_col"] is not None and p["hex_row"] is not None}
    where_they_are = {p["id"]: _markers.section_of(p, banks) for p in chosen}
    if len(set(departures.values())) < 2:
        return None
    if not mine.get("together", True):
        return None                 # everyone on their own: no rendezvous to compute

    m = STATE.k["map"]
    march = bool(mine.get("forced_march"))
    activities = {p["id"]: _activities_of(p, vehicles, march) for p in chosen}

    inside = _common.inside_map(m)

    # The pace of the united group is not necessarily that of the slowest: if
    # they all get on the wagon it is the wagon's, and the rendezvous moves
    # accordingly — it goes to fetch whoever fell behind instead of waiting.
    together = _ruler._party_activities(mine, chosen, vehicles)

    if common_road:
        # The branches as the ruler showed them: kept if they hold, so on
        # release they do not change shape. Roads at equal cost are more than
        # one, and recomputing them means being able to pick another.
        branches = _valid_branches(traced_branches, chosen, m["orientation"], inside,
                            cost_of, passage, banks, crossings)
        is_set = travel_mod.rendezvous_on(departures, common_road, activities,
                                        cost_of, m["orientation"], inside,
                                        party_pace=together, passage=passage,
                                        banks=banks, departure_banks=where_they_are,
                                        crossings=crossings, water=water, bank=common_bank,
                                        branches=branches)
        if is_set is not None:
            return is_set
    return travel_mod.rendezvous_point(
        departures, arrival, activities, cost_of, m["orientation"], inside,
        party_pace=together, passage=passage, banks=banks,
        departure_banks=where_they_are, crossings=crossings, water=water)

def _legs_from_rendezvous(rendezvous, chosen: list[dict], mode, march: bool,
                       common_pace: float | None = None,
                       drawing: dict | None = None) -> list[dict]:
    """The legs to save: the approaches, and then the common one.

    Every leg carries the **spot** where it ends: the branches on the shore
    of the meeting point, the common road in the aimed piece (`drawing`, with
    the nodes and atoms of the road). So whoever makes the days pass stops
    people where the plan said, and the route is redrawn as it was seen.
    """
    view, difficulty, vehicles = mode.view, mode.difficulty, mode.vehicles
    borders, sail = mode.borders, mode.sail
    march = bool(march)
    meeting_spot = _markers.spot_of_section(
        rendezvous.point, int(getattr(rendezvous, "bank", 0) or 0), _common.sections_map())
    at_meeting_point = list(meeting_spot) if meeting_spot else None
    activities = {p["id"]: _activities_of(p, vehicles, march) for p in chosen}

    def costs_of(course):
        """What every step costs: the cell entered, plus the side.

        The plan is frozen at departure, so the fords must be frozen now too:
        if the GM builds a bridge there tomorrow, the journey already under
        way must not shorten on its own.
        """
        outside = []
        for before, after in zip(course, course[1:]):
            step = _cost_for(view, difficulty, tuple(after), sail) or 0
            if borders:
                step += travel_mod.border_cost(
                    tuple(before), tuple(after), borders, sail) or 0
            outside.append(step)
        return outside
    legs = []
    for char_id, course in rendezvous.approaches.items():
        if len(course) < 2:
            continue                # already on the spot: nothing to do
        legs.append({
            "characters": [char_id],
            "path": [list(c) for c in course],
            "costs": costs_of(course),
            "activities_per_day": activities.get(char_id, 1.0),
            "progress": 0.0,
            "waiting": False,
            "where": at_meeting_point,
        })
    if len(rendezvous.common) > 1:
        legs.append({
            "characters": [p["id"] for p in chosen],
            "path": [list(c) for c in rendezvous.common],
            "costs": costs_of(rendezvous.common),
            "activities_per_day": common_pace or (min(activities.values())
                                                if activities else 1.0),
            "progress": 0.0,
            "waiting": True,        # one leaves when everyone is there
            **(drawing or {}),
        })
    return legs

def _leave_scattered(chosen: list[dict]) -> bool:
    positions = {(p["hex_col"], p["hex_row"]) for p in chosen
                 if p["hex_col"] is not None}
    return len(positions) > 1

def _separate_journeys(chosen: list[dict], arrival, mode, cost_of, march: bool,
                     traced: dict | None = None) -> list[dict]:
    """Everyone's journey on their own: a path and a count each.

    To see before leaving what «Travel together» off will really do: k
    distinct journeys, each at its own Speed. Before, we drew a single one —
    that of the first in the row — and nothing was known of the others until
    they had left.

    `traced` are the hand-drawn roads, one per character: when they exist
    they count, as for the lone traveller. The server checks them all the
    same, and the one that does not hold goes back to the cheapest.
    """
    view, difficulty, vehicles = mode.view, mode.difficulty, mode.vehicles
    orientation, inside = mode.orientation, mode.inside
    passage, borders, sail = mode.passage, mode.borders, mode.sail
    banks, crossings, water = mode.banks, mode.crossings, mode.water
    traced = traced or {}
    outside = []
    for char in chosen:
        if_it_leaves = (char["hex_col"], char["hex_row"])
        if if_it_leaves[0] is None or if_it_leaves[1] is None:
            continue
        course = None
        drawn = traced.get(char["id"])
        if drawn and len(drawn) >= 2:
            course = _valid_course(drawn, if_it_leaves, orientation,
                                      inside, cost_of, passage, banks,
                                      _markers.section_of(char, banks), crossings)
        if course is None:
            course = travel_mod.path(if_it_leaves, arrival, cost_of,
                                           orientation, inside, passage, banks,
                                           _markers.section_of(char, banks), crossings, water)
        if course is None or len(course) < 2:
            continue
        waypoints = [_waypoint_for(view, difficulty, c) for c in course[1:]]
        speed, source, _warnings = travel_mod.compose_speed([char], vehicles)
        plan = travel_mod.plan_(
            waypoints, speed, source, march,
            [int(char["con_mod"] or 0)], borders, if_it_leaves, sail,
            travel_mod.inner_on_course(
                course, banks, crossings, orientation, cost_of,
                _markers.section_of(char, banks)),
            travel_mod.rings_on_course(
                course, banks, water, crossings, orientation, cost_of,
                _markers.section_of(char, banks)))
        if not plan.possible:
            continue
        outside.append({
            "id": char["id"], "name": char["name"],
            "color": images.valid_color(char.get("color")),
            "path": [tuple(c) for c in course],
            "days": plan.days, "unknowns": plan.unknowns,
            "plan": plan,
        })
    return outside

def _parts_each_alone(mine: dict, mapping, chosen: list[dict], arrival) -> None:
    """One journey each: nobody waits for anybody.

    It is the meaning of «together» off — and also the way to split the
    group, if the table decides waiting for the slowest is not worth it.
    Everyone goes at their own Speed along their own road.
    """
    view = _common._current_view(mine)
    m = STATE.k["map"]
    difficulty = STATE.archive.campaign_difficulty(STATE.campaign)
    vehicles = _markers._vehicles_in_play()
    inside = _common.inside_map(m)
    mode = _crossing(mine, chosen, vehicles, view, difficulty)
    cost_of, passage, borders, sail = mode
    march = bool(mine.get("forced_march"))
    user = theme.user()
    departed, still_ones = [], []

    # The roads are already those seen on the map, hand-drawn ones included:
    # redoing them here would mean starting a journey other than the one the
    # table was looking at when it pressed Depart.
    by_char_id = {p["id"]: p for p in chosen}
    listing = [v for v in (mine.get("singles") or []) if v["id"] in by_char_id]
    if {v["id"] for v in listing} != set(by_char_id):
        listing = _separate_journeys(chosen, arrival, mode, cost_of, march)
    arrived = {v["id"] for v in listing}
    still_ones += [p["name"] for p in chosen if p["id"] not in arrived]

    for entry in listing:
        char = by_char_id[entry["id"]]
        course = [tuple(c) for c in entry["path"]]
        plan = entry["plan"]
        if_it_leaves, where = course[0], course[-1]
        STATE.archive.create_journey({
            "id": uuid.uuid4().hex[:12], "campaign_id": STATE.campaign,
            "characters": [char["id"]], "stable_id": char.get("stable_id"),
            "departure": f"{if_it_leaves[0]},{if_it_leaves[1]}",
            "arrival": f"{where[0]},{where[1]}",
            "path": [list(c) for c in course],
            "costs": travel_mod.waypoint_costs(plan),
            "legs": [{"characters": [char["id"]],
                        "path": [list(c) for c in course],
                        "costs": travel_mod.waypoint_costs(plan),
                        "activities_per_day": plan.day_activities,
                        "progress": 0.0, "waiting": False,
                        "where": _road_drawing(mine)["where"]}],
            "activity_cost": plan.total_cost, "days": plan.days,
            "activities_per_day": plan.day_activities, "progress": 0.0,
            "departure_day": int((STATE.k.get("clock") or {}).get("days", 0)),
            "forced_march": 1 if march else 0, "status": "in_progress",
            "turn_created": STATE.k["turn"],
            "created_by": user.id if user else None,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S")})
        departed.append(t("map.travel.d", name=char["name"], days=plan.days))

    if departed:
        STATE.record(t("map.travel.departed_each_their_own", arrival=arrival[0], arrival2=arrival[1], join=", ".join(departed)), "map")
    if still_ones:
        theme.notify(t("map.travel.they_cannot_get_there") + ", ".join(still_ones), "warning")
    _common._forget_plan(mine)
    mine["travel_pcs"] = []
    # And the vehicle: it stayed in hand, lit on the map, while whoever was on
    # it had already been dropped.
    mine["travel_vehicle"] = None
    mine["aboard"] = False
    theme.save_and_refresh_panels(DEPARTURE_PANELS)
    _redraw_travel(mine, mapping)

def _vehicles_box(mine: dict, mapping, chosen: list[dict]) -> None:
    """The «everyone gets aboard» toggle, if there is a vehicle to use.

    Off on purpose: Hexploration says nowhere that a passenger moves at the
    vehicle's Speed, so it is not the app that decides the group travels by
    carriage. It is a choice, and it shows.
    """
    if not chosen:
        return
    vehicles = _markers._vehicles_in_play()
    vehicles_by_id = travel_mod.party_vehicles(chosen, vehicles)
    if not vehicles_by_id:
        return

    with ui.row().classes("gap-2 items-center flex-wrap"):
        ui.checkbox(t("map.travel.everybody_boards"), value=bool(mine.get("aboard")),
                    on_change=lambda e: _ruler._change_aboard(mine, mapping, e.value)) \
            .tooltip(t("map.travel.united_party_travels_vehicle"))
        for entry in vehicles_by_id:
            label = travel_mod.vehicle_name_(entry)
            metres, _reason = travel_mod.speed_from_stable(entry)
            how_many, why = travel_mod.vehicle_seats(entry)
            pieces = [units.fmt(metres) if metres is not None else t("map.travel.speed_decided"),
                     t("map.travel.seats", how_many=how_many) if how_many is not None else t("map.travel.seats_counted")]
            edge = ("var(--km-line)" if metres is not None and how_many is not None
                     else "var(--km-red)")
            ui.html(f'<span class="km-chip" style="font-size:.64rem;'
                    f'border-color:{edge}">{theme.esc(label)} · '
                    f'{theme.esc(" · ".join(pieces))}</span>') \
                .tooltip(why if how_many is None else
                         t("map.travel.seats_are_counted_party", why=why))

    # A vehicle is in a single place: if two characters leaving from different
    # hexes declare the same wagon, one of the two is imagining it.
    for entry in vehicles_by_id:
        above = [p for p in chosen if (p.get("stable_id") or "") == entry["id"]]
        where = {(p["hex_col"], p["hex_row"]) for p in above
                if p["hex_col"] is not None}
        if len(where) > 1:
            names = ", ".join(p["name"] for p in above)
            ui.label(t("map.travel.assigned_who_however_leave", vehicle_name=travel_mod.vehicle_name_(entry), names=names)) \
                .style("font-size:.74rem;color:var(--km-gold);white-space:normal")

def _change_together(mine: dict, mapping, value: bool) -> None:
    """Changing one's mind about travelling together redoes the count: it is a different plan."""
    mine["together"] = bool(value)
    _common._forget_plan(mine)
    _redraw_travel(mine, mapping)

def _singles_box(singles: list[dict]) -> None:
    """Who leaves on their own, and when they arrive.

    With «Travel together» off the journeys are as many as the travellers:
    the boxes above speak of the slowest, which is the day the party is all
    together again, and this list says the rest.
    """
    theme.sep()
    ui.html(t("map.travel.div_style_font_size_2"))
    for entry in sorted(singles, key=lambda s: s["days"]):
        with ui.row().classes("items-center gap-2 w-full no-wrap"):
            ui.html(f'<span style="width:10px;height:10px;border-radius:50%;'
                    f'background:{entry["color"]};flex:0 0 auto"></span>')
            ui.label(entry["name"]).style("font-size:.78rem;flex:1")
            ceiling = t("drawing.max_prefix") if entry.get("unknowns") else ""
            days = entry["days"]
            ui.html(f'<span class="km-chip" style="font-size:.64rem">'
                    f'{ceiling}{days} {tn("common.day_word", days)}</span>')
    ui.label(t("map.travel.they_all_leave_together")) \
        .style("font-size:.72rem;color:var(--km-muted);white-space:normal")

def _rendezvous_box(rendezvous, chosen: list[dict]) -> None:
    """Where one meets, who waits how long, and what waiting costs."""
    names = {p["id"]: p["name"] for p in chosen}
    theme.sep()
    days_text = f"{rendezvous.union_days:.1f}".replace(".0", "")
    ui.html(f'<div style="font-size:.8rem;color:var(--km-gold)">'
            + t("map.travel.rendezvous_at", col=rendezvous.point[0], row=rendezvous.point[1],
                days=t("drawing.days.one" if rendezvous.union_days == 1 else "drawing.days.other", n=days_text))
            + '</div>')
    ui.label(t("map.travel.everyone_gets_there_their")) \
        .style("font-size:.72rem;color:var(--km-muted);white-space:normal")
    for char_id, days in sorted(rendezvous.wait.items(), key=lambda x: -x[1]):
        alone = rendezvous.alone_ones.get(char_id)
        pieces = [f'{names.get(char_id, "?")}']
        if days > 0.05:
            pieces.append(t("map.travel.waits_d_rendezvous", days=days))
        if alone is not None and rendezvous.total_days - alone > 0.05:
            pieces.append(t("map.travel.alone_they_would_reach", alone=alone, total_days=rendezvous.total_days))
        if len(pieces) > 1:
            ui.label(" — ".join(pieces)) \
                .style("font-size:.72rem;color:var(--km-gold-dim);white-space:normal")

# --------------------------------------------------------------------------
# Who is already on the road. Putting the same character in two journeys
# means two legs moving them every day to two different places: the second
# wins by chance, by reading order. Better to notice before.
def journeys_by_character(ids=None) -> dict:
    """For every character on the way, the journey keeping them busy."""
    outside: dict[str, dict] = {}
    for journey in STATE.archive.list_journeys(STATE.campaign, "in_progress"):
        for char_id in journey.get("characters") or []:
            if ids is None or char_id in ids:
                outside[char_id] = journey
    return outside

def _map_vehicles_panel_box(mine: dict, mapping) -> None:
    """The kingdom's vehicles: where they are, who boards, and how one leaves with one.

    The direction is this, and it holds for the wagon as for the boat: **the
    vehicle is in a hex, and one boards it being there**. Before, it was the
    other way round for half of them — a boat was put in the water, a wagon
    was assigned from a dropdown and appeared next to its owner wherever they
    were. Handy, and false: nobody boards a carriage three hexes away, and
    with a vehicle that is nowhere there was not even a way to say where one
    gets off.
    """
    vehicles_by_id = STATE.archive.list_stable(STATE.campaign)
    if not vehicles_by_id:
        return
    can_place = permissions.can(theme.user(), permissions.MANAGE_STABLE)
    in_hand = mine.get("travel_vehicle")
    theme.sep()
    ui.label(t("map.travel.vehicles")).style("font-size:.78rem;color:var(--km-gold)")
    for entry in vehicles_by_id:
        sid = entry["id"]
        where = travel_mod.where_it_is(entry)
        aboard = STATE.archive.characters_on_vehicle(sid)
        with ui.row().classes("items-center gap-2 w-full no-wrap flex-wrap"):
            ui.html(f'<span style="font-size:.82rem">'
                    f'{travel_mod.vehicle_symbol(entry)} '
                    f'<b>{theme.esc(travel_mod.vehicle_name_(entry))}</b></span>')
            if where is not None:
                ui.html(f'<span class="km-chip" style="font-size:.66rem">'
                        f'{where[0]},{where[1]}</span>')
            else:
                ui.html('<span class="km-chip" style="font-size:.66rem;'
                        'border-color:var(--km-muted)">' + t("map.travel.in_depot") + '</span>')
            # The names of those aboard sit in the row below, next to the
            # button letting them off: it is about them, and reading them up
            # there among the vehicle's chips meant looking for them.
            if in_hand == sid:
                ui.html(t("map.travel.span_class_km_chip_6"))
            ui.element("div").style("flex:1")
            # Here there was «Travel with this / Leave it», and it is no longer
            # needed: a vehicle is taken **by clicking it on the map**, which
            # is the same gesture a character is taken with, and who travels
            # on it is decided with «Board». Two roads to the same thing were
            # one too many, and the one with the button was the less obvious.
            if can_place:
                ui.button("Spostalo" if where is not None else t("map.travel.put_map_2"),
                          icon="place",
                          on_click=lambda _e=None, i=sid: _take_vehicle(mine, mapping, i)) \
                    .props("dense flat color=amber")
                if where is not None:
                    ui.button(icon="undo",
                              on_click=lambda _e=None, i=sid: _put_back_in_depot(mine, mapping, i)) \
                        .props("flat dense round size=sm color=grey") \
                        .tooltip(t("map.travel.take_back_shed_goes"))
        if where is not None:
            _crew_row(mine, mapping, entry, where, aboard)

    if mine.get("place_vehicle"):
        placing = STATE.archive.stable_vehicle(mine["place_vehicle"])
        kind = travel_mod.vehicle_kind(placing or {})
        says = {"water": t("map.travel.must_hex_drawn_water"),
                "land": t("map.travel.must_hex_some_land"),
                "air": t("map.travel.any_hex_will_do")}
        ui.label(t("map.travel.click_map_where_put", get=says.get(kind, says['land']))) \
            .style("font-size:.74rem;color:var(--km-gold);white-space:normal")
    elif mine.get("landing"):
        ui.label(t("map.travel.click_hex_where_they")) \
            .style("font-size:.74rem;color:var(--km-gold);white-space:normal")
    elif in_hand:
        ui.label(t("map.travel.one_leaves_from_where")) \
            .style("font-size:.74rem;color:var(--km-gold-dim);white-space:normal")

def _crew_row(mine: dict, mapping, entry: dict, where, aboard: list) -> None:
    """Who boards and who gets off, for the vehicle in that hex.

    Two rows, and in this order: **first who is already there**, with their
    names and the button letting them off; **then who can board**, with the
    dropdown and the button embarking them. On a single row they fitted as
    long as the vehicle was empty: as soon as someone was aboard, the names,
    the dropdown and the two buttons no longer fitted and «Let them off»
    wrapped on its own, detached from the names it is about. Whoever has
    nobody aboard has no first row, and the dropdown stays attached to the
    vehicle as before.

    Who can board is whoever is there: the dropdown shows **only** the
    characters standing in the vehicle's hex, because a list offering those
    far away and then refusing is a list that wastes time. The real check is
    redone afterwards anyway — a dropdown is not a defence.
    """
    user = theme.user()
    sid = entry["id"]
    above = {p["id"] for p in aboard}
    # Who can board is told by the rule, not by the hex: a boat stopped at a
    # corner is boarded from three hexes, from every shore touching that point.
    banks_here = _common.sections_map()
    orient_here = STATE.k["map"]["orientation"]
    neighbours = [p for p in STATE.characters()
              if p["id"] not in above
              and permissions.can_on_character(user, p)
              and p.get("hex_col") is not None
              and travel_mod.ascent_blocked(p, entry, banks_here, orient_here) is None]
    my_aboard = [p for p in aboard if permissions.can_on_character(user, p)]

    # Who is already there. The names show even when there is nothing to do —
    # people on it who are not yours, and no button — or one would no longer
    # see who travels on it.
    if aboard:
        with ui.row().classes("items-center gap-2 w-full no-wrap flex-wrap") \
                .style("padding-left:14px"):
            ui.html('<span style="font-size:.74rem;color:var(--km-gold-dim)">'
                    + theme.esc(", ".join(x["name"] for x in aboard))
                    + '</span>')
            ui.element("div").style("flex:1")
            if my_aboard:
                ui.button(t("map.travel.let_them_off"), icon="logout",
                          on_click=lambda _e=None: _boats._ask_landing(
                              mine, mapping, sid, [p["id"] for p in my_aboard])) \
                    .props("dense flat color=grey") \
                    .tooltip(t("map.travel.from_boat_you_choose"))

    # And who can board, below: added to those above, not replacing them.
    if neighbours:
        with ui.row().classes("items-center gap-2 w-full no-wrap flex-wrap") \
                .style("padding-left:14px"):
            choice: dict = {"who": []}
            ui.select({p["id"]: p["name"] for p in neighbours}, multiple=True,
                      label=t("map.travel.who_boards"), value=[],
                      on_change=lambda e: choice.update(who=list(e.value or []))) \
                .props("outlined dense use-chips options-dense").classes("w-52") \
                .tooltip(t("map.travel.only_whoever_has_vehicle"))
            ui.button(t("map.travel.board"), icon="login",
                      on_click=lambda _e=None: _boats._board(
                          mine, mapping, sid, choice["who"])) \
                .props("dense flat color=amber")

def _take_vehicle(mine: dict, mapping, sid: str) -> None:
    mine["travel_mode"] = "place"
    mine["place_vehicle"] = sid
    mine["place_pc"] = None
    mine["landing"] = None
    if mine.get("apply_slider"):
        mine["apply_slider"]()
    _redraw_travel(mine, mapping)

def _put_back_in_depot(mine: dict, mapping, sid: str) -> None:
    """Takes the vehicle off the map. Whoever was on it is set down on the ground.

    From a wagon they stay where they were. From a boat they were **on the
    water** — the boat's junction, or the middle of a lake — and left there
    nobody could move them: they go ashore, to the nearest dry atom
    (`boats.ashore_spot`).
    """
    if not permissions.can(theme.user(), permissions.MANAGE_STABLE):
        return
    entry = STATE.archive.stable_vehicle(sid)
    on_water = (travel_mod.vehicle_kind(entry) == "water" and entry.get("hex_col") is not None)
    # A vehicle no longer on the map has nobody aboard: staying «on» a wagon
    # that is in the depot would mean travelling at its Speed without having
    # it in front, and it is exactly the ghost link one comes from.
    for char in STATE.archive.characters_on_vehicle(sid):
        fields: dict = {"stable_id": None}
        if on_water:
            where, spot = _boats.ashore_spot((entry["hex_col"], entry["hex_row"]),
                                             (entry.get("pos_x"), entry.get("pos_y")))
            fields.update(hex_col=where[0], hex_row=where[1], pos_x=spot[0], pos_y=spot[1])
        STATE.archive.update_character(char["id"], **fields)
    STATE.archive.update_stable_vehicle(sid, hex_col=None, hex_row=None)
    if mine.get("travel_vehicle") == sid:
        mine["travel_vehicle"] = None
        mine["travel_pcs"] = []
        _common._forget_plan(mine)
    STATE.record(t("map.travel.back_shed", vehicle_name=travel_mod.vehicle_name_(entry)),
                   "map")
    theme.notify(t("map.travel.back_shed_whoever_was"),
                   "positive")
    theme.save_and_refresh_panels(_MARKER_PANELS)
    _redraw_travel(mine, mapping)

def _occupied_box(mine: dict, mapping, chosen: list[dict]) -> bool:
    """Warns that someone is already travelling, and offers the two ways out.

    Returns True if there is at least one busy: as long as there is, the
    group cannot leave — either the old journey is cancelled, or whoever is
    making it is left out.
    """
    occupied = journeys_by_character({p["id"] for p in chosen})
    if not occupied:
        return False
    names = {p["id"]: p["name"] for p in chosen}
    with ui.column().classes("gap-1 w-full") \
            .style("border:1px solid var(--km-red);border-radius:8px;padding:6px"):
        ui.html(t("map.travel.b_class_km_fc"))
        for char_id, journey in occupied.items():
            with ui.row().classes("items-center gap-2 w-full no-wrap flex-wrap"):
                ui.label(t("map.travel.text_2", get=names.get(char_id, "?"), arrival=journey["arrival"])) \
                    .style("font-size:.76rem;flex:1;min-width:110px")
                ui.button(t("map.travel.cancel_their_journey"),
                          on_click=lambda _=None, v=journey: _cancel_journey_of(v, mine, mapping)) \
                    .props("dense flat size=sm color=red")
                ui.button(t("map.travel.remove_them_from_group"),
                          on_click=lambda _=None, i=char_id: _remove_from_group(i, mine, mapping)) \
                    .props("dense flat size=sm color=grey")
    return True

def _cancel_journey_of(journey: dict, mine: dict, mapping) -> None:
    STATE.archive.update_journey(journey["id"], status="cancelled",
                                    turn_resolved=STATE.k["turn"])
    STATE.record(t("map.travel.journey_cancelled_leave_again", arrival=journey["arrival"]), "map")
    _common._forget_plan(mine)
    theme.save_and_refresh_panels(_MARKER_PANELS)
    _redraw_travel(mine, mapping)

def _remove_from_group(char_id: str, mine: dict, mapping) -> None:
    mine["travel_pcs"] = [i for i in (mine.get("travel_pcs") or []) if i != char_id]
    _common._forget_plan(mine)
    _redraw_travel(mine, mapping)

# --------------------------------------------------------------------------
# The journeys already under way, listed below the planner. Choosing one —
# from the menu, from the marker of whoever is making it, or by clicking its
# route on the map — brings it to the top and lights it on the map.
def _planned_journeys_list(mine: dict, mapping) -> None:
    journeys = STATE.archive.list_journeys(STATE.campaign, "in_progress")
    if not journeys:
        return
    names = {p["id"]: p["name"] for p in STATE.characters()}
    chosen_one = mine.get("chosen_journey")
    # The chosen one first: it is the one being talked about.
    journeys.sort(key=lambda v: (v["id"] != chosen_one, v["created_at"]))

    with ui.card().classes("km-panel w-full"):
        theme.title(t("map.travel.journeys_under_way", len=len(journeys)), 3)
        for journey in journeys:
            _travel_section(journey, journey["id"] == chosen_one, names, mine, mapping)

def _travel_section(journey: dict, is_on: bool, names: dict, mine: dict, mapping) -> None:
    people = ", ".join(names.get(i, "?") for i in journey.get("characters") or [])
    missing_ones = max((daily.days_missing(
        frac.get("costs") or [], float(frac.get("progress") or 0),
        float(frac.get("activities_per_day") or 1)) for frac in journey.get("legs") or []),
        default=0)
    edge = "#7fc3e8" if is_on else "var(--km-line)"
    with ui.element("div").classes("w-full") \
            .style(f"border:1px solid {edge};border-radius:8px;margin-top:4px;"
                   f'{"background:#16202a" if is_on else ""}'):
        with ui.expansion(t("map.travel.text_3", people=people, arrival=journey["arrival"]), value=is_on) \
                .classes("w-full").props("dense header-class=km-title"):
            ui.html(t("map.travel.div_style_font_size_3", missing_ones=missing_ones, v=tn("common.day_word", missing_ones), turn_created=journey["turn_created"]))
            for leg in journey.get("legs") or []:
                who = ", ".join(names.get(i, "?") for i in leg.get("characters") or [])
                rest = daily.rest_of_leg(leg)
                state = (t("map.travel.waiting_others") if leg.get("waiting") and rest
                         else t("map.travel.hexes_go", v=len(rest) - 1) if len(rest) > 1
                         else "arrivato")
                ui.label(t("map.travel.text_4", who=who, state=state)) \
                    .style("font-size:.72rem;color:var(--km-gold-dim);white-space:normal")
            with ui.row().classes("gap-2 w-full").style("margin-top:4px"):
                ui.button(t("map.travel.show_map"), icon="my_location",
                          on_click=lambda _=None, v=journey: _choose_journey(v["id"], mine, mapping)) \
                    .props("dense flat size=sm color=amber")
                ui.button(t("common.cancel"), icon="close",
                          on_click=lambda _=None, v=journey: _cancel_journey_of(v, mine, mapping)) \
                    .props("dense flat size=sm color=red")

def _choose_journey(journey_id: str | None, mine: dict, mapping) -> None:
    """Lights a journey: it goes to the top of the list and lights up on the map."""
    mine["chosen_journey"] = journey_id
    _redraw_travel(mine, mapping)

def _passing_journey(coord) -> str | None:
    """The journey whose route passes through that hex, if there is one.

    It is the way to take a journey by clicking it on the map: only the part
    still to do is looked at, because the walked part is no longer drawn and
    clicking it would surprise.
    """
    for journey in STATE.archive.list_journeys(STATE.campaign, "in_progress"):
        for leg in journey.get("legs") or []:
            if tuple(coord) in {tuple(c) for c in daily.rest_of_leg(leg)}:
                return journey["id"]
    return None

def _svg_branches(branches, rendezvous, size: float, origin, orient: str,
              shores: _markers.Shores | None = None) -> str:
    """The approach roads and the circle of the meeting point.

    The server draws them, not only the browser while you drag: otherwise as
    soon as you let go — or if you choose the destination with the right
    button — a single line would remain, and of a group journey a third would
    be seen.
    """
    if not branches:
        return ""
    pieces: list[str] = []
    point = getattr(rendezvous, "point", None)
    rendezvous_bank = int(getattr(rendezvous, "bank", 0) or 0)
    for branch in branches:
        if len(branch) < 2:
            continue
        centers = _drawing._polyline(branch, size, origin, orient, shores)
        # The last point is **the anchor** of the meeting point: where the
        # circle is and where the common road starts from. Before, the branch
        # ended on the shore's point and the common road started from the
        # anchor — in a whole hex they are two places half a radius apart —
        # and the two arrows did not touch.
        if point is not None and centers:
            banks_here = shores.banks if shores is not None else None
            centers[-1] = _markers.anchor_markers(tuple(point), rendezvous_bank, size,
                                          origin, orient, banks_here)
        line = "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in centers)
        pieces.append(
            f'<path d="{line}" fill="none" stroke="#0b1015" '
            f'stroke-width="{size * 0.08:.1f}" stroke-linecap="round" '
            f'stroke-linejoin="round" stroke-opacity="0.55"/>'
            f'<path d="{line}" fill="none" stroke="{_drawing.BRANCH_COLOR}" '
            f'stroke-width="{size * 0.05:.1f}" stroke-linecap="round" '
            f'stroke-linejoin="round"/>')
    point = getattr(rendezvous, "point", None)
    if point is not None:
        cx, cy = (_drawing._polyline([point], size, origin, orient, shores) or
                  [hexgrid.hex_center(point[0], point[1], size, origin, orient)])[0]
        pieces.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{size * 0.2:.1f}" fill="none" '
            f'stroke="{_drawing.BRANCH_COLOR}" stroke-width="{size * 0.05:.1f}" '
            f'stroke-dasharray="{size * 0.09:.1f} {size * 0.07:.1f}"/>')
    return "".join(pieces)
