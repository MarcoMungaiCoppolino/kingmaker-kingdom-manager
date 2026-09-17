"""The Map tab: `map_panel`, the click, the toggles, the fog, zoom and veil.

It used to live in `ui/hexmap.py`; the `hexmap` facade still re-exports everything.
"""
from __future__ import annotations

import logging
from nicegui import events, ui
from kingmaker.state import STATE
from kingmaker.ui import theme
from kingmaker.water import reading as water_reading
from kingmaker.geometry import hexgrid
from kingmaker.access import permissions

from kingmaker.ui.hexmap import common as _common
from kingmaker.ui.hexmap import drawing as _drawing
from kingmaker.ui.hexmap import markers as _markers
from kingmaker.ui.hexmap import water as _water
from kingmaker.ui.hexmap import hex_panel as _hexagon
from kingmaker.ui.hexmap import travel as _journey
from kingmaker.ui.hexmap import boats as _boats
from kingmaker.ui.hexmap import ruler as _ruler
from kingmaker.locale.i18n import t

log = logging.getLogger(__name__)


class _Refresher:
    """Exposes `.refresh()` like a refreshable, but updates the image in place.

    Recreating the element at every refresh would reload the background
    image, which for the Stolen Lands map can weigh several megabytes.

    `soon()` queues a redraw instead: the sliders emit up to twenty events a
    second and regenerating the SVG at every notch made the drag stutter.

    `refresh()` queues too: a single action on the map ends up asking for it
    several times (the actor, plus the round over every connected window)
    and every redraw is an SVG of tens of KB. The timer runs it once.
    """

    def __init__(self, fn) -> None:
        self._fn = fn
        self._dirty = False
        self.cid = theme.current_window()

    def refresh(self) -> None:
        # Asked from this window's own handler — the click that boarded, the
        # ruler let go — the map is drawn now, not at the next tick of the
        # timer up to 120 ms away. Asked from anywhere else (the bus, the
        # maintenance tick) it waits for the timer, which draws once.
        if theme.current_window() == self.cid:
            self._dirty = False
            self._fn()
        else:
            self._dirty = True

    def soon(self) -> None:
        self._dirty = True

    def scroll_(self) -> None:
        if self._dirty:
            self._dirty = False
            self._fn()

def map_panel() -> None:
    mine = _common._mine()
    rif: dict = {"img": None, "src": None}

    def draw() -> None:
        el = rif["img"]
        if el is None:
            return
        src, w, h = _common._background()
        if src != rif["src"]:
            rif["src"] = src
            el.set_source(src)
        # Two layers, two elements: the ground in a box under the image's own
        # SVG, the live things in that SVG. Each is sent only when it changed,
        # so a moved marker costs a window the markers, not the whole map. The
        # scripts (the ruler, the water tools) keep drawing into the image's
        # SVG, above the markers, as they always did.
        ground, live = _drawing._svg_layers(mine, _common._current_view(mine))
        box = rif.get("ground")
        if box is not None:
            box.set_content(
                f'<svg class="km-ground" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
                f'preserveAspectRatio="none" style="position:absolute;left:0;top:0;width:100%;height:100%">'
                f'{ground}</svg>')
        el.set_content(live)
        apply_zoom()

    def apply_zoom() -> None:
        el = rif["img"]
        if el is not None:
            el.style(f'width:{float(mine["zoom"]) * 100:.0f}%')

    def apply_slider() -> None:
        el = rif.get("img")
        if el is not None:
            el.style("display:block;max-width:none;" + _common._slider_for(mine))
        # The eraser lives in the browser and must know whether someone holds
        # it: without this toggle it would always drag, even outside the mode.
        lit = bool(mine.get("water_mode") and mine.get("border_mode") == "land")
        try:
            ui.run_javascript(f"window.kmWaterEraser = {'true' if lit else 'false'};")
        except Exception:
            # Outside a window there is nobody to talk to: it happens when the
            # redraw comes from a timer instead of a click.
            pass

    mine["apply_slider"] = apply_slider
    # The Waters box redraws the map from its buttons — closing a shape,
    # removing a lake — and without this it would have to wait for the next
    # click on the map to show it.
    mine["draw"] = draw

    def _click(e: events.MouseEventArguments) -> None:
        if e.image_x is None or e.image_y is None:
            return          # event without coordinates: it does not come from the map
        m = STATE.k["map"]
        col, row = hexgrid.pixel_to_hex(
            float(e.image_x), float(e.image_y),
            float(m["size"]), (float(m["origin_x"]), float(m["origin_y"])), m["orientation"])
        if not _common.inside_map(m)((col, row)):
            return

        # Right button: aims at the destination, as in a strategy game.
        # Dragging with the same button keeps panning the map: it is the
        # box's javascript that lets only still clicks through.
        if e.type == "contextmenu":
            _journey._journey_destination(mine, mapping, (col, row),
                                  (float(e.image_x), float(e.image_y)))
            return

        if mine.get("travel_mode") == "place" and mine.get("place_vehicle"):
            _boats._place_vehicle(mine, mapping, (col, row),
                          (float(e.image_x), float(e.image_y)))
            return

        if mine.get("travel_mode") == "place" and mine.get("place_pc"):
            _journey._place_marker(mine, mapping, (col, row),
                            (float(e.image_x), float(e.image_y)))
            return

        # Declaring where one lands: it is a click like the others, and worth
        # more than an automatic landing — from a wagon stopped at a ford one
        # gets off on this or that side of the river, and the difference is
        # known only to the player.
        if mine.get("travel_mode") == "place" and mine.get("landing"):
            _boats._land_here(mine, mapping, (col, row),
                        _journey._spot_from_point((col, row),
                                         (float(e.image_x),
                                          float(e.image_y))))
            return

        # Clicking a vehicle's badge means «I travel with this». It is the
        # opposite gesture from the characters', and rightly so: a vehicle is
        # reached where it is, and then one leaves with it.
        #
        # The order between the three gestures matters, and it is this: **a
        # face before a vehicle, a vehicle before the ground**. Before, it was
        # enough to click the hex and off it went, as long as vehicles were
        # only boats in the middle of the water, where there are no people
        # markers. With wagons stopped together with the group that rule ate
        # the most important gesture there is — clicking a hex to take whoever
        # stands on it — and the group box seemed gone.
        # (A placed vehicle is a member of its piece of hex, like a person:
        # `marker_under` finds it, and `_choose_from_click` knows what to do
        # with it. There is no longer a separate badge to hit.)

        # With the water in hand the click goes to the chosen brush (table
        # `_BRUSHES`), and in any case does not choose a hex: whoever is
        # looking at the rivers did not ask for a cell's sheet.
        if mine.get("water_mode"):
            brush = _water._BRUSHES.get(mine.get("border_mode"))
            if brush is not None and permissions.can(theme.user(), permissions.SEE_SECRETS):
                brush(mine, e, (float(e.image_x), float(e.image_y)), draw)
            return

        mode = mine.get("fog_mode")
        if mode and permissions.can(theme.user(), permissions.SEE_SECRETS):
            if e.ctrl:
                # With ctrl it accumulates: the confirmation comes when you let go.
                chosen = mine["fog_selection"]
                if [col, row] in chosen:
                    chosen.remove([col, row])
                else:
                    chosen.append([col, row])
                draw()
                if mine.get("fog_bar"):
                    mine["fog_bar"].refresh()
            else:
                _fog_dialog([(col, row)], mode, mine, mapping)
            return

        # In travel mode the click no longer chooses the hex: it chooses who
        # leaves. Clicking the ground takes every marker on it, clicking a
        # precise marker takes only that one, and with ctrl one adds instead
        # of starting over.
        if mine.get("travel_mode") == "choose":
            _markers._choose_from_click(mine, mapping, (col, row),
                              (float(e.image_x), float(e.image_y)), bool(e.ctrl))
            return

        mine.update(col=col, row=row)
        draw()
        detail.refresh()
        counts.refresh()
        # The chosen hex is also the journey's destination: without this the
        # Travel box would stay at «click a hex».
        if mine.get("travel") is not None:
            mine["travel"].refresh()

    mapping = _Refresher(draw)
    ui.timer(0.12, mapping.scroll_)

    def _button(e) -> None:
        """Ctrl released, we ask what to do with the chosen hexes."""
        is_ctrl = e.key.name == "Control" or e.key.code in ("ControlLeft", "ControlRight")
        if e.action.keyup and is_ctrl and mine.get("fog_selection"):
            coords = [tuple(c) for c in mine["fog_selection"]]
            _fog_dialog(coords, mine["fog_mode"], mine, mapping)

    # `ignore` empty because otherwise, with the focus left on the mode
    # button, the ctrl release would never arrive. We react only to that, so
    # it does not bother whoever is typing.
    ui.keyboard(on_key=_button, active=True, ignore=[])
    mine["map"] = mapping
    theme.register_refresh("hexmap.map", mapping)
    # The ruler dragged with the left button ends up here when you let go.
    ui.on("km_travel_target", lambda e: _ruler._dragged_target(mine, mapping, e.args))
    # And while you are still dragging it, so the others see it too.
    ui.on("km_live_trace", lambda e: _ruler._live_trace(mine, e.args))
    # When instead the arrow does not go on, the why.
    ui.on("km_travel_blocked", lambda e: _ruler._journey_blocked(mine, e.args))

    def _eraser(e) -> None:
        """The points the eraser passed over, in bunches while you drag."""
        if not (mine.get("water_mode") and mine.get("border_mode") == "land"):
            return
        if not permissions.can(theme.user(), permissions.SEE_SECRETS):
            return
        removed_ones = 0
        for point in (e.args or {}).get("points") or []:
            try:
                removed_ones += _water._erase_under((float(point[0]), float(point[1])))
            except (TypeError, ValueError, IndexError):
                continue
        if removed_ones:
            theme.mark_dirty()
            draw()
            if mine.get("waters"):
                mine["waters"].refresh()

    ui.on("km_water_eraser", _eraser)

    @ui.refreshable
    def detail() -> None:
        _hexagon._hex_panel(mine)

    mine["detail"] = detail
    theme.register_refresh("hexmap.detail", detail)

    @ui.refreshable
    def counts() -> None:
        # The numbers are already information: if a player read "48 unknown"
        # they would know how many hexes the GM prepared.
        by_state = _common._current_view(mine).counts()
        for state, (key_, _fill, stroke) in _common.HEX_STATUSES.items():
            lab = t(key_)
            n = by_state.get(state, 0)
            ui.html(f'<span class="km-chip" style="font-size:.7rem;border-color:{stroke}">'
                    f'{lab}: {n}</span>')

    mine["counts"] = counts
    theme.register_refresh("hexmap.counts", counts)

    with ui.row().classes("w-full items-start gap-4 no-wrap"):
        with ui.column().classes("gap-2").style("flex:1;min-width:0"):
            with ui.card().classes("km-panel w-full"):
                with ui.row().classes("items-center gap-3 flex-wrap"):
                    theme.title(t("map.page.stolen_lands"), 1)
                    ui.element("div").style("flex:1")
                    _journey._travel_toggle(mine, mapping)
                    _water._water_toggle(mine, mapping)
                    _icons_toggle(mine, mapping)
                    _preview_toggle(mine, mapping)
                    counts()
                _fog_controls(mine, mapping, rif)
                with ui.element("div").classes("km-drag").style(
                        "overflow:auto;max-height:76vh;border:1px solid var(--km-line);"
                        "border-radius:10px;background:#161209"):
                    rif["img"] = ui.interactive_image(
                        "", content="", events=["click", "contextmenu"], cross="#d7b263", on_mouse=_click) \
                        .style("display:block;max-width:none")
                    with rif["img"]:
                        rif["ground"] = ui.html("", sanitize=False).classes("km-ground-box")
                draw()
                if mine.get("apply_slider"):
                    mine["apply_slider"]()
                _zoom_slider(mine, apply_zoom)

                # The row of portraits below the map: who is there, where, and
                # the commands to send them off. It lives here and not in the
                # column beside because it is looked at together with the map.
                @ui.refreshable
                def map_party() -> None:
                    _journey._map_party_panel(mine, mapping)

                mine["party"] = map_party
                theme.register_refresh("hexmap.party", map_party)
                map_party()

            with ui.expansion(t("map.page.grid_calibration_background_image")).classes("km-panel w-full"):
                _hexagon._calibration_panel(mapping)

        with ui.column().classes("gap-3").style("width:440px;min-width:380px"):

            @ui.refreshable
            def waters() -> None:
                _water._water_panel(mine, mapping)

            mine["waters"] = waters
            theme.register_refresh("hexmap.waters", waters)
            waters()

            detail()

            @ui.refreshable
            def journey() -> None:
                _journey._travel_panel(mine, mapping)

            mine["travel"] = journey
            theme.register_refresh("hexmap.travel", journey)
            journey()

def _icons_toggle(mine: dict, mapping) -> None:
    """Hides the hex icons and names, leaving the map drawn.

    They say what is on a hex, and for that they are right; but when you are
    following a river or drawing a route they are in front of you right where
    you look. The character markers stay: those are the *where you are*, not
    the *what is there*, and without them nothing of the map would make sense
    any more.
    """

    @ui.refreshable
    def button() -> None:
        lit_ones = mine.get("show_icons", True)
        with ui.button(on_click=change) \
                .props("dense " + ("flat color=grey" if lit_ones else "color=amber")) \
                .tooltip(t("map.page.hides_hex_icons_names")):
            ui.icon("label").classes("" if lit_ones else "km-strike")
            ui.label(t("map.page.icons")).style("margin-left:4px")

    def change() -> None:
        mine["show_icons"] = not mine.get("show_icons", True)
        button.refresh()
        mapping.refresh()

    mine["icons_button"] = button
    button()

def _preview_toggle(mine: dict, mapping) -> None:
    """The «master's screen» button: look at the map as they see it."""
    if not permissions.can(theme.user(), permissions.SEE_SECRETS):
        return

    def change(value: bool) -> None:
        mine["player_preview"] = value
        mapping.refresh()
        mine["detail"].refresh()
        mine["counts"].refresh()
        label.set_text(t("map.page.see_players") if not value
                           else t("map.page.you_are_seeing_players"))
        label.style(f'color:{"var(--km-gold)" if value else "var(--km-muted)"}')

    with ui.row().classes("items-center gap-2 no-wrap"):
        label = ui.label(t("map.page.see_players")) \
            .style("font-size:.75rem;color:var(--km-muted)")
        ui.switch(value=bool(mine.get("player_preview")),
                  on_change=lambda e: change(e.value)).props("dense color=amber") \
            .tooltip(t("map.page.shows_only_what_you"))

def _fog_controls(mine: dict, mapping, rif: dict) -> None:
    """Fog: covering and uncovering hexes by clicking them directly on the map."""
    if not permissions.can(theme.user(), permissions.SEE_SECRETS):
        return

    apply_slider = mine["apply_slider"]

    @ui.refreshable
    def bar() -> None:
        mode = mine["fog_mode"]
        waiting = len(mine["fog_selection"])
        # One box around the whole bar: the caption, the three buttons and
        # the two sliders are one tool, and the frame says so.
        with ui.row().classes("items-center gap-2 flex-wrap") \
                .style("border:1px solid var(--km-line);border-radius:10px;"
                       "padding:4px 12px 4px 6px"):
            ui.html(t("map.page.span_class_km_chip"))
            ui.button(t("map.page.cover"), icon="visibility_off",
                      on_click=lambda: change_mode("hide")) \
                .props("dense " + ("color=red" if mode == "hide" else "flat color=grey")) \
                .tooltip(t("map.page.then_click_hexes_hide"))
            ui.button(t("map.page.uncover"), icon="visibility",
                      on_click=lambda: change_mode("reveal")) \
                .props("dense " + ("color=amber" if mode == "reveal" else "flat color=grey")) \
                .tooltip(t("map.page.then_click_hexes_reveal"))
            ui.button(t("map.page.reset"), icon="restart_alt", on_click=_confirm_reset_map) \
                .props("dense flat color=grey") \
                .tooltip(t("map.page.puts_fog_back_every"))
            _density_slider(mine, mapping)
            if waiting:
                ui.button(t("map.page.confirm", waiting=waiting), icon="check",
                          on_click=lambda: _fog_dialog(
                              [tuple(c) for c in mine["fog_selection"]],
                              mine["fog_mode"], mine, mapping)) \
                    .props("dense color=amber")
                ui.button(t("map.page.cancel_selection"),
                          on_click=lambda: _after_fog(mine, mapping)) \
                    .props("dense flat color=grey")
            if mode:
                ui.label(t("map.page.hold_ctrl_pick_more")
                         + (t("map.page.waiting_release_ctrl_confirm", waiting=waiting)
                            if waiting else "")) \
                    .style("font-size:.72rem;color:var(--km-gold-dim)")

    def change_mode(new: str) -> None:
        is_on = mine["fog_mode"] != new
        _common._single_mode(mine, "fog" if is_on else "")
        mine["fog_mode"] = new if is_on else None
        mine["fog_selection"] = []
        apply_slider()
        bar.refresh()
        mapping.refresh()

    def _confirm_reset_map() -> None:
        # The whole grid, not only the hexes already saved: otherwise one
        # uncovered with ctrl without ever being opened would never go back
        # under the fog.
        unknown_ones = [(c, r) for c, r in _common.full_grid()
                       if (STATE.existing_hex(c, r) or {}).get("status", "unknown")
                       == "unknown"]
        with theme.dialog() as dlg, ui.card().classes("km-panel"):
            theme.title(t("map.page.reset_fog"), 2)
            ui.label(t("map.page.hexes_still_unknown_will", len=len(unknown_ones)))

            def go() -> None:
                STATE.archive.hide(STATE.campaign, unknown_ones)
                STATE.record(t("map.page.fog_reset_hexes", len=len(unknown_ones)), "map")
                dlg.close()
                _after_fog(mine, mapping)

            with ui.row():
                ui.button(t("map.page.reset"), on_click=go).props("color=red")
                ui.button(t("common.cancel"), on_click=dlg.close).props("flat")
        dlg.open()

    mine["fog_bar"] = bar
    bar()

def _density_slider(mine: dict, mapping) -> None:
    """How thick the fog is for the players.

    It applies to them only: on your screen the fog stays light, or you could
    no longer read the map you are preparing. At most it covers the
    background entirely, for when the Stolen Lands must be a blank sheet; at
    least the drawing shows through.
    """
    m = STATE.k["map"]
    lbl = ui.label("").style("font-size:.72rem;color:var(--km-muted)")

    def show(value: float) -> None:
        # No adjective: changing length it shifted the slider beside it.
        lbl.set_text(t("map.page.players_fog", int=int(value * 100)))

    def change(e) -> None:
        if e.value is None:
            return
        m["fog_opacity"] = float(e.value)
        show(float(e.value))
        # The density is shared: it changes every player's map.
        theme.save_light(_common._GRID)
        mapping.soon()

    show(float(m.get("fog_opacity", 0.8)))
    ui.slider(min=_common.FOG_MIN, max=_common.FOG_MAX, step=0.05,
              value=float(m.get("fog_opacity", 0.8)), on_change=change) \
        .props("dense").style("width:130px") \
        .tooltip(t("map.page.players_only_your_screen"))

    # And the GM's own fog, next to it: the same slider for the other side of
    # the screen. It is a setting of the kingdom too, so every GM window
    # reads the map with the same veil.
    gm_lbl = ui.label("").style("font-size:.72rem;color:var(--km-muted)")

    def show_gm(value: float) -> None:
        gm_lbl.set_text(t("map.page.gm_fog", int=int(value * 100)))

    def change_gm(e) -> None:
        if e.value is None:
            return
        m["gm_fog_opacity"] = float(e.value)
        show_gm(float(e.value))
        theme.save_light(_common._GRID)
        mapping.soon()

    show_gm(float(m.get("gm_fog_opacity", 0.35)))
    ui.slider(min=_common.GM_FOG_MIN, max=_common.GM_FOG_MAX, step=0.05,
              value=float(m.get("gm_fog_opacity", 0.35)), on_change=change_gm) \
        .props("dense").style("width:130px") \
        .tooltip(t("map.page.gm_fog_tooltip"))

def _after_fog(mine: dict, mapping) -> None:
    """Redraws here and, within half a second, on the players' side too."""
    mine["fog_selection"] = []
    mapping.refresh()
    if mine.get("fog_bar"):
        mine["fog_bar"].refresh()
    if mine.get("counts"):
        mine["counts"].refresh()
    theme.save_light(_hexagon._AFTER_HEX_EDIT)
    theme.refresh_locals(("hexmap.counts",))

def _fog_dialog(coords: list, mode: str, mine: dict, mapping) -> None:
    """Who sees (or stops seeing) the hexes just chosen."""
    if not coords:
        return
    to_reveal = mode == "reveal"
    players = [u for u in STATE.archive.list_users()
                 if u["role"] == permissions.PLAYER and u["active"]]
    group = STATE.archive.visible_to_party(STATE.campaign)

    with theme.dialog() as dlg, ui.card().classes("km-panel").style("min-width:340px"):
        theme.title(t("map.page.uncover_hexes") if to_reveal else t("map.page.cover_hexes"), 2)
        listing = ", ".join(f"{c},{r}" for c, r in coords[:12])
        if len(coords) > 12:
            listing += f" … (+{len(coords) - 12})"
        how_many = len(coords)
        ui.label(t("map.page.text", how_many=how_many, v='hexagon' if how_many == 1 else 'hexes', listing=listing)) \
            .style("font-size:.8rem;color:var(--km-muted)")

        choice = ui.radio({"group": t("map.page.whole_party"), "some": t("map.page.only_some_players")},
                          value="group").props("dense")
        fields_ = {}
        with ui.column().classes("gap-0").bind_visibility_from(
                choice, "value", lambda v: v == "some"):
            for u in players:
                fields_[u["id"]] = ui.checkbox(u["username"])
            if not players:
                ui.label(t("map.page.there_are_no_active")) \
                    .style("font-size:.78rem;color:var(--km-muted)")

        warning = ui.label("").style("font-size:.75rem;color:var(--km-gold);min-height:1em")
        if not to_reveal:
            already_group = [c for c in coords if tuple(c) in group]
            if already_group:
                warning.set_text(
                    t("map.page.these_are_revealed_whole", len=len(already_group)))

        def confirm() -> None:
            if choice.value == "group":
                if to_reveal:
                    STATE.archive.reveal(STATE.campaign, coords, "*")
                else:
                    STATE.archive.hide(STATE.campaign, coords)
                to_whom = t("map.page.party")
            else:
                recipients = [uid for uid, c in fields_.items() if c.value]
                if not recipients:
                    warning.set_text(t("map.page.choose_least_one_player"))
                    return
                for uid in recipients:
                    if to_reveal:
                        STATE.archive.reveal(STATE.campaign, coords, uid)
                    else:
                        STATE.archive.hide(STATE.campaign, coords, uid)
                to_whom = t("map.page.players", len=len(recipients))
            verb = "Scoperti" if to_reveal else "Coperti"
            STATE.record(t("map.page.hexes", verb=verb, len=len(coords), to_whom=to_whom), "map")
            dlg.close()
            _after_fog(mine, mapping)

        with ui.row().classes("justify-end w-full"):
            ui.button(t("common.cancel"), on_click=lambda: (dlg.close(), _after_fog(mine, mapping))) \
                .props("flat")
            ui.button(t("common.confirm"), on_click=confirm).props("color=amber")
    dlg.open()

def _zoom_slider(mine: dict, apply_zoom) -> None:
    m = STATE.k["map"]

    def set_(val: float) -> None:
        # The zoom is personal (everyone looks at the map as they like) and
        # changes only the image width: no need to regenerate the SVG.
        mine["zoom"] = m["zoom"] = round(float(val), 2)
        theme.save_light()
        apply_zoom()

    with ui.row().classes("items-center gap-2 w-full no-wrap"):
        ui.label(t("map.page.zoom")).style("font-size:.75rem;color:var(--km-muted)")
        ui.button(icon="zoom_out", on_click=lambda: cur.set_value(max(0.25, mine["zoom"] - 0.25))) \
            .props("dense flat round size=sm color=grey")
        cur = ui.slider(min=0.25, max=4, step=0.05, value=mine["zoom"],
                        on_change=lambda e: set_(e.value)).props("label-always").style("flex:1")
        ui.button(icon="zoom_in", on_click=lambda: cur.set_value(min(4.0, mine["zoom"] + 0.25))) \
            .props("dense flat round size=sm color=amber")
        ui.button("100%", on_click=lambda: cur.set_value(1.0)).props("dense flat color=grey")
    _veil_slider(mine)
    ui.label(t("map.page.hold_right_button_wheel")) \
        .style("font-size:.72rem;color:var(--km-muted)")

def _veil_slider(mine: dict) -> None:
    """How much the terrain fills cover.

    The map drawn underneath already has its colours, and a fill saying
    «forest here» on top of a drawn forest covers the drawing instead of
    adding to it. Sometimes one wants to look at the map, sometimes at its
    classification, and the viewer decides how much of one to let through the
    other.

    Unlike the zoom this changes the SVG — the colour of the fills is written
    in there — so the map is redrawn. The veil however stays **personal**,
    like the zoom: the GM can keep the fills solid to work and the players
    look at the drawing.
    """
    m = STATE.k["map"]

    def set_(val: float) -> None:
        mine["terrain_veil"] = m["terrain_veil"] = round(float(val), 2)
        theme.save_light()
        # Only the SVG is redrawn, not the whole box: rebuilding the frame
        # would reset the scroll, and dragging the slider the map would go
        # back to the corner at every notch.
        if mine.get("draw"):
            mine["draw"]()

    with ui.row().classes("items-center gap-2 w-full no-wrap"):
        ui.label(t("map.page.fills")).style("font-size:.75rem;color:var(--km-muted)") \
            .tooltip(t("map.page.how_much_terrain_colours"))
        ui.button(icon="visibility_off",
                  on_click=lambda: veil.set_value(0.0)) \
            .props("dense flat round size=sm color=grey") \
            .tooltip(t("map.page.only_drawing_colours_off"))
        veil = ui.slider(min=0, max=1, step=0.05,
                         value=float(mine.get("terrain_veil", 1.0)),
                         on_change=lambda e: set_(e.value)) \
            .props("label-always").style("flex:1")
        ui.button(icon="visibility", on_click=lambda: veil.set_value(1.0)) \
            .props("dense flat round size=sm color=amber") \
            .tooltip(t("map.page.full_fills"))
