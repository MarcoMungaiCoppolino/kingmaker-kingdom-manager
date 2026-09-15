"""The panel of the chosen hex: GM screen, borders, crossings, kingdom actions (claim, clear, reconnoiter...), calibration.

It used to live in `ui/hexmap.py`; the `hexmap` facade still re-exports everything.
"""
from __future__ import annotations

import logging
import math
from nicegui import events, ui
from kingmaker.state import STATE
from kingmaker.ui.tabs import city
from kingmaker.ui import theme
from kingmaker.access import auth, permissions
from kingmaker.geometry import hexgrid, sections
from kingmaker.media import imgsize, images
from kingmaker import rules, travel as travel_mod

from kingmaker.ui.hexmap import common as _common
from kingmaker.locale.i18n import t

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------
def available_images() -> list[str]:
    easts = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
    return sorted(f.name for f in _common.ASSETS.iterdir() if f.suffix.lower() in easts)

@theme.requires(permissions.UPLOAD_IMAGE)
def _apply_image(name: str, mapping, rebuild=None) -> None:
    """Sets the background image and detects its real size."""
    m = STATE.k["map"]
    # The name comes from a dropdown, but a dropdown can be driven from the
    # console: only a file really in the images folder counts.
    if name:
        name = images.safe_file_name(name) or ""
        if name and not (_common.ASSETS / name).is_file():
            name = ""
    m["image"] = name
    dim = imgsize.sizes(_common.ASSETS / name) if name else None
    if dim:
        m["img_width"], m["img_height"] = dim
        theme.notify(t("map.hex_panel.loaded_px_use_fit", name=name, dim=dim[0], dim2=dim[1]))
    elif name:
        theme.notify(t("map.hex_panel.loaded_but_i_could", name=name), "warning")
    theme.save_and_refresh()
    mapping.refresh()
    if rebuild:
        rebuild.refresh()

@theme.requires(permissions.UPLOAD_IMAGE)
def _fit_grid(mapping) -> None:
    """Spreads `columns` hexes over the width of the image."""
    m = STATE.k["map"]
    width = float(m["img_width"]) or 1.0
    columns = max(1, int(m["columns"]))
    if m["orientation"] == "pointy":
        # width of a hex = sqrt(3)*size, plus half a hex of stagger
        size = width / (math.sqrt(3) * (columns + 0.5))
    else:
        # horizontal step = 1.5*size, plus half a hex at the edges
        size = width / (1.5 * columns + 0.5)
    m["size"] = round(size, 2)
    m["origin_x"] = round(size * (math.sqrt(3) / 2 if m["orientation"] == "pointy" else 1.0), 1)
    m["origin_y"] = round(size * (1.0 if m["orientation"] == "pointy" else math.sqrt(3) / 2), 1)
    theme.save_and_refresh()
    mapping.refresh()
    theme.notify(t("map.hex_panel.grid_fitted_radius_px", size=m['size'], columns=columns))

def _calibration_panel(mapping) -> None:
    m = STATE.k["map"]

    @theme.requires(permissions.UPLOAD_IMAGE)
    def upd(key: str, val) -> None:
        if val is None:
            return
        if key in ("columns", "rows"):
            val = max(1, int(val))
            other = int(m["rows"] if key == "columns" else m["columns"])
            if val * other > _common.MAX_GRID_CELLS:
                # Every cell is a piece of SVG resent at every redraw: beyond
                # a few thousand the map starts to stutter.
                val = max(1, _common.MAX_GRID_CELLS // max(1, other))
                theme.notify(
                    t("map.hex_panel.grid_stops_hexes_all", MAX_GRID_CELLS=_common.MAX_GRID_CELLS, key=key, val=val), "warning")
        m[key] = val
        theme.save_light(_common._GRID)
        mapping.refresh()
        if key in ("img_width", "img_height", "orientation"):
            sliders.refresh()   # the slider bounds change

    async def load(e: events.UploadEventArguments) -> None:
        if not permissions.can(auth.current_user(STATE.archive), permissions.UPLOAD_IMAGE):
            theme.notify(t("map.hex_panel.only_gm_can_change"), "negative")
            return
        name = images.safe_file_name(e.file.name)
        if name is None:
            theme.notify(t("map.hex_panel.png_jpg_gif_webp"), "negative")
            return
        try:
            await images.accept(e.file, _common.ASSETS, name, _common.MAX_IMAGE_BYTES)
        except images.ImageRejected as reason:
            theme.notify(str(reason), "negative")
            return
        _apply_image(name, mapping, image_choice)

    if permissions.can(theme.user(), permissions.UPLOAD_IMAGE):
        ui.upload(label=t("map.hex_panel.upload_map_image_png"), on_upload=load,
                  auto_upload=True, max_file_size=_common.MAX_IMAGE_BYTES) \
            .props("accept=image/*").classes("w-full")
    ui.label(t("map.hex_panel.you_can_also_copy", ASSETS=_common.ASSETS)) \
        .style("font-size:.75rem;color:var(--km-muted)")

    @ui.refreshable
    def image_choice() -> None:
        options = {"": t("map.hex_panel.no_image")} | {n: n for n in available_images()}
        with ui.row().classes("items-center gap-2 w-full no-wrap"):
            ui.select(options, label=t("map.hex_panel.background_image"), value=m["image"] if m["image"] in options else "",
                      on_change=lambda e: _apply_image(e.value or "", mapping, image_choice)) \
                .props("outlined dense").classes("w-96")
            ui.button(t("map.hex_panel.re_read_folder"), on_click=image_choice.refresh).props("dense flat color=amber")

    image_choice()

    ui.label(t("map.hex_panel.align_grid_until_polygons")) \
        .style("font-size:.78rem;color:var(--km-muted)")

    with ui.row().classes("gap-3 flex-wrap items-center"):
        ui.select({"pointy": t("map.hex_panel.pointy_top"), "flat": t("map.hex_panel.flat_top")}, label=t("map.hex_panel.orientation"),
                  value=m["orientation"], on_change=lambda e: upd("orientation", e.value)) \
            .props("outlined dense").classes("w-48")
        ui.number(t("map.hex_panel.image_width"), value=m["img_width"], format="%d",
                  on_change=lambda e: upd("img_width", int(e.value or 0))) \
            .props("outlined dense debounce=500").classes("w-40")
        ui.number(t("map.hex_panel.image_height"), value=m["img_height"], format="%d",
                  on_change=lambda e: upd("img_height", int(e.value or 0))) \
            .props("outlined dense debounce=500").classes("w-40")
        ui.number(t("map.hex_panel.columns"), value=m["columns"], format="%d",
                  on_change=lambda e: upd("columns", int(e.value or 1))) \
            .props("outlined dense debounce=500").classes("w-28")
        ui.number(t("map.hex_panel.rows"), value=m["rows"], format="%d",
                  on_change=lambda e: upd("rows", int(e.value or 1))) \
            .props("outlined dense debounce=500").classes("w-28")
        ui.checkbox(t("map.hex_panel.show_whole_grid"), value=m["show_grid"],
                    on_change=lambda e: upd("show_grid", e.value))             .tooltip(t("map.hex_panel.draws_hexes_still_unknown"))
        ui.button(t("map.hex_panel.fit_grid_image"), on_click=lambda: _fit_grid(mapping)) \
            .props("dense color=amber") \
            .tooltip(t("map.hex_panel.computes_radius_origin_so"))

    @ui.refreshable
    def sliders() -> None:
        width = float(m["img_width"]) or 2000.0
        height = float(m["img_height"]) or 733.0

        def slider(key: str, label: str, min_: float, max_: float, step: float) -> None:
            """A slider to feel the grid move, and a box to type the exact
            number: the slider steps are coarse on a big image, and a
            calibration copied from another table must be typed as it is.

            Updates only the value and the label; the map redraw is queued, so
            dragging the slider stays smooth."""
            with ui.row().classes("items-center gap-2 w-full no-wrap"):
                lbl = ui.label(t("map.hex_panel.text", label=label, m=m[key])) \
                    .style("font-size:.75rem;color:var(--km-muted);flex:1")
                box = ui.number(value=m[key], step=step, format="%g") \
                    .props("outlined dense").classes("w-28")

            def apply(value: float) -> None:
                if value is None or value == m[key]:
                    return                   # the echo of the other control
                m[key] = float(value)
                lbl.set_text(t("map.hex_panel.text_2", label=label, value=m[key]))
                theme.save_light(_common._GRID)   # the others see the grid move
                mapping.soon()

            def from_slider(e) -> None:
                apply(e.value)
                if e.value is not None and box.value != e.value:
                    box.set_value(e.value)

            def from_box(e) -> None:
                try:
                    value = float(e.value)
                except (TypeError, ValueError):
                    return
                apply(value)
                if bar.value != value:
                    bar.set_value(value)

            bar = ui.slider(min=min_, max=max_, step=step, value=m[key],
                            on_change=from_slider).props("label-always")
            box.on_value_change(from_box)

        slider("size", t("map.hex_panel.hex_radius"), 4, max(20, width / 6), 0.25)
        slider("origin_x", t("map.hex_panel.origin_x"), -width / 4, width / 4, 1)
        slider("origin_y", t("map.hex_panel.origin_y"), -height / 4, height / 4, 1)

    sliders()
    theme.register_refresh("hexmap.sliders", sliders)

# --------------------------------------------------------------------------
def _hex_panel(mine: dict) -> None:
    mapping = mine["map"]
    detail = mine["detail"]
    if mine.get("travel_mode") or mine.get("water_mode"):
        # While travelling or tracing water the place belongs to the mode's
        # box: the hex sheet comes back as soon as it is switched off.
        return
    if mine["col"] is None:
        with ui.card().classes("km-panel w-full"):
            ui.label(t("map.hex_panel.click_hex_map_see")) \
                .style("color:var(--km-muted)")
        return

    col, row = mine["col"], mine["row"]
    view = _common._current_view(mine)
    if not view.can_see(col, row):
        # Clicking must reveal nothing, not even "there is something here":
        # `STATE.hex()` would create the hex and show its content.
        with ui.card().classes("km-panel w-full"):
            theme.title(t("map.hex_panel.hex", col=col, row=row), 2)
            ui.label(t("map.hex_panel.unexplored_territory_nothing_known"))                 .style("color:var(--km-muted)")
        return
    h = STATE.hex(col, row)
    # Redraws the map without rebuilding every panel: redoing the panel at
    # every event destroyed the field the user was using.
    refresh = lambda: (mapping.refresh(), _hex_changed())  # noqa: E731

    # The GM commands live here, next to the chosen hex: switching to another
    # tab to reveal a hex was a pointless inconvenience.
    @ui.refreshable
    def regia() -> None:
        if view.gm and not mine.get("player_preview"):
            _gm_block(h, col, row, mine, refresh)

    regia()

    def refresh_fields() -> None:
        """After ticking a hex field.

        The GM box lists only the fields that are really there: if we do not
        redraw it, the «secret» tick appears only next time round.
        """
        refresh()
        regia.refresh()

    # The hex status changes often, and with it the badge above and the
    # activity buttons: they sit in a separate panel, so an edit does not
    # rebuild the fields that are long to redraw (and to resend) too.
    @ui.refreshable
    def actions() -> None:
        # The settlement on the hex is already at the top, among the hex
        # features; really deleting it is done from the City tab.
        theme.title(t("map.hex_panel.region_activities_this_hex"), 3)
        _hex_actions(h, mine)

    mine["actions"] = actions
    theme.register_refresh("hexmap.actions", actions)

    with ui.card().classes("km-panel w-full km-scroll"):
        with ui.row().classes("items-center gap-2 w-full"):
            theme.title(t("map.hex_panel.hex", col=col, row=row), 1)
            ui.element("div").style("flex:1")
            badge_ = ui.html(f'<span class="km-chip">{t(_common.HEX_STATUSES[h["status"]][0])}</span>')
            mine["badge"] = badge_

        ui.input(t("map.hex_panel.name_reference"), value=h["name"],
                 on_change=lambda e: (_set_field(h, "name", e.value or ""),
                                      theme.save_light(_common._MAP), mapping.soon())) \
            .props("outlined dense debounce=400").classes("w-full")

        ui.select({s: t(_common.HEX_STATUSES[s][0]) for s in _common.HEX_STATUSES}, label=t("map.hex_panel.status"), value=h["status"],
                  on_change=lambda e: _set_status(h, e.value, mapping, mine)) \
            .props("outlined dense").classes("w-full")

        ui.select({frac["id"]: frac["name"] for frac in rules.TERRAINS if not frac.get("legacy")}, label=t("map.hex_panel.terrains_present"),
                  value=h["terrains"], multiple=True,
                  on_change=lambda e: (_set_field(h, "terrains", e.value or []), refresh())) \
            .props("outlined dense use-chips").classes("w-full")
        if h["terrains"]:
            cost = rules.disconnected_terrain_cost(h["terrains"])
            ui.label(t("map.hex_panel.building_rugged_terrain_this", cost=cost)) \
                .style("font-size:.78rem;color:var(--km-gold-dim)")

        theme.sep()
        theme.title(t("map.hex_panel.terrain_features"), 3)
        for el in list(h["features"]):
            entry = rules.BY_ID["feature"].get(el["kind"], {})
            feature_icon = (_common._work_site_icon(el.get("name")) if el["kind"] == "work_site"
                        else _common.HEX_ICONS.get(el["kind"], "❔"))
            with ui.row().classes("items-center gap-2 w-full no-wrap"):
                ui.label(feature_icon)
                ui.label(entry.get("name", el["kind"]) + (f' · {el.get("name", "")}' if el.get("name") else "")) \
                    .style("flex:1;font-size:.85rem")
                ui.tooltip(entry.get("desc", ""))
                if permissions.can(theme.user(), permissions.SEE_SECRETS) \
                        and not mine.get("player_preview") \
                        and el["kind"] != "settlement":
                    ui.button(icon="visibility_off",
                              on_click=lambda _e, x=el: _make_secret(h, col, row, x, refresh)) \
                        .props("dense flat round color=grey") \
                        .tooltip(t("map.hex_panel.hide_from_players_again"))
                ui.button(icon="close", on_click=lambda _e, x=el: _remove_feature(h, x, refresh, detail)) \
                    .props("dense flat round color=grey") \
                    .tooltip(t("map.hex_panel.detach_settlement_from_this")
                             if el["kind"] == "settlement" else t("map.hex_panel.remove_feature"))
        with ui.row().classes("items-center gap-2 w-full"):
            # Work Site, Farmland, Roads and Fortification have their fields
            # below: putting them among the features too created two entries
            # for the same thing, which then diverged — and the list entry
            # showed the wrong icon on top of that.
            options = {e["id"]: _common._feature_entry(e, icon=False)
                       for e in rules.HEX_FEATURES
                       if e["id"] not in _common.FIELD_OF_FEATURE}
            # At the bottom of the list, the settlements already built:
            # choosing one anchors it to this hex, without going through the
            # City tab.
            for existing in STATE.k["settlements"]:
                if existing.get("hex") and tuple(existing["hex"]) == (col, row):
                    continue
                where = (t("map.hex_panel.off_map") if not existing.get("hex")
                        else t("map.hex_panel.now", hex=existing["hex"][0], hex2=existing["hex"][1]))
                options[f'{_common._SETTLEMENT_PREFIX}{existing["id"]}'] = f'🏘 {existing["name"]} — {where}'

            new = ui.select(options, label=t("map.hex_panel.add_feature")) \
                .props("outlined dense").classes("w-56")
            label = ui.input(t("map.hex_panel.detail_e_g_lumber")).props("outlined dense").classes("w-40")

            def add() -> None:
                if not new.value:
                    return
                if str(new.value).startswith(_common._SETTLEMENT_PREFIX):
                    _link_existing(new.value[len(_common._SETTLEMENT_PREFIX):], col, row, mapping, detail)
                    return
                h["features"].append({"kind": new.value, "name": label.value or ""})
                refresh()
                detail.refresh()

            ui.button(icon="add", on_click=add).props("dense flat round color=amber")

        theme.sep()
        with ui.row().classes("gap-4 flex-wrap"):
            ui.checkbox(t("map.hex_panel.roads"), value=h["roads"],
                        on_change=lambda e: (_set_field(h, "roads", e.value),
                                             refresh_fields()))
            ui.checkbox(t("map.hex_panel.fortified"), value=h["fortified"],
                        on_change=lambda e: (_set_field(h, "fortified", e.value),
                                             refresh_fields()))
            ui.checkbox(t("map.hex_panel.farmland"), value=h["farmland"],
                        on_change=lambda e: _set_farmland(h, e.value, refresh_fields))

        sl = h.get("work_site")
        with ui.row().classes("items-center gap-2 w-full"):
            ui.select({"": t("map.hex_panel.no_work_site"), "lumber": t("map.hex_panel.lumber_camp"),
                       "stone": t("map.hex_panel.quarry_stone"), "ore": t("map.hex_panel.mine_ore")},
                      label=t("map.hex_panel.work_site"), value=(sl["commodity"] if sl else ""),
                      on_change=lambda e: (_set_site(h, e.value, mapping),
                                          detail.refresh())) \
                .props("outlined dense").classes("w-56")
            if sl:
                ui.checkbox(t("map.hex_panel.doubled_resource_hex"), value=sl.get("doubled", False),
                            on_change=lambda e: (_set_field(sl, "doubled", e.value), refresh()))

        ui.textarea(t("map.hex_panel.notes"), value=h["note"],
                    on_change=lambda e: (_set_field(h, "note", e.value or ""),
                                         theme.save_light())) \
            .props("outlined dense autogrow debounce=400").classes("w-full")

        theme.sep()
        actions()

def _gm_block(h: dict, col: int, row: int, mine: dict, refresh) -> None:
    """What only the GM and their notes know about this hex."""
    data = STATE.archive.gm_data(STATE.campaign, col, row)
    visible = (col, row) in STATE.archive.visible_to_party(STATE.campaign)

    def redraw() -> None:
        refresh()
        mine["detail"].refresh()

    @theme.requires(permissions.SEE_SECRETS)
    def reveal(coords, recipient="*") -> None:
        STATE.archive.reveal(STATE.campaign, coords, recipient)
        redraw()

    @theme.requires(permissions.SEE_SECRETS)
    def hide() -> None:
        STATE.archive.hide(STATE.campaign, [(col, row)])
        redraw()

    with ui.card().classes("km-panel w-full").style("border-color:#7fb0e0"):
        with ui.row().classes("items-center gap-2 w-full no-wrap"):
            theme.title(t("map.hex_panel.gm_screen"), 3)
            ui.element("div").style("flex:1")
            cls_ = "km-sc" if visible else "km-fc"
            ui.html(f'<span class="km-chip {cls_}" style="font-size:.68rem">'
                    f'{t("map.hex_panel.revealed_party") if visible else "Segreto"}</span>')

        with ui.row().classes("gap-2 items-center flex-wrap"):
            if visible:
                ui.button(t("map.hex_panel.hide"), icon="visibility_off", on_click=hide) \
                    .props("dense flat color=red")
            else:
                ui.button(t("map.hex_panel.reveal_party"), icon="visibility",
                          on_click=lambda: reveal([(col, row)])) \
                    .props("dense color=amber")
            players = {u["id"]: u["username"] for u in STATE.archive.list_users()
                         if u["role"] == permissions.PLAYER and u["active"]}
            if players:
                choice = ui.select(players, value=next(iter(players))) \
                    .props("outlined dense options-dense").classes("w-32")
                ui.button(icon="person_add",
                          on_click=lambda: reveal([(col, row)], choice.value)) \
                    .props("dense flat round color=amber") \
                    .tooltip(t("map.hex_panel.reveal_this_hex_single"))

        ui.textarea(t("map.hex_panel.gm_notes_nobody_else"), value=data["gm_notes"],
                    on_change=lambda e: _write_gm_notes(col, row, e.value or "")) \
            .props("outlined dense autogrow").classes("w-full")

        _borders_block(col, row, redraw)

        # Roads, fortification, farmland and work site are not «features»:
        # they are hex fields, and before they came into the open together
        # with the hex. They may well have been there before the kingdom.
        present = [(c, t(e)) for c, e in HIDEABLE_FIELDS.items() if _active_field(h, c)]
        if present:
            ui.label(t("map.hex_panel.hex_fields_create_them")) \
                .style("font-size:.75rem;color:var(--km-muted)")
            hidden = set(data.get("hidden_fields") or ())
            with ui.row().classes("gap-3 flex-wrap items-center"):
                for field, label in present:
                    ui.checkbox(t("map.hex_panel.secret", get=_common.HEX_ICONS.get(field, ""), label=label),
                                value=field in hidden,
                                on_change=lambda e, c=field: _mark_field(
                                    col, row, c, e.value, redraw))

        # The features already visible, to be able to hide them again without
        # deleting them: one happens to reveal the wrong thing, and redoing it
        # from scratch is annoying.
        visible_ones = [e for e in h.get("features", []) if e.get("kind") != "settlement"]
        if visible_ones:
            ui.label(t("map.hex_panel.visible_features_crossed_out")) \
                .style("font-size:.75rem;color:var(--km-muted)")
            for el in list(visible_ones):
                entry = rules.BY_ID["feature"].get(el.get("kind"), {})
                with ui.row().classes("items-center gap-2 w-full no-wrap"):
                    ui.label(_common.HEX_ICONS.get(el.get("kind"), "❔"))
                    ui.label(entry.get("name", el.get("kind"))
                             + (f' · {el["name"]}' if el.get("name") else "")) \
                        .style("flex:1;font-size:.82rem")
                    ui.button(icon="visibility_off",
                              on_click=lambda _e, x=el: (
                                  _make_secret(h, col, row, x, refresh), redraw())) \
                        .props("dense flat round size=sm color=grey") \
                        .tooltip(t("map.hex_panel.hide_from_players_again_2"))

        ui.label(t("map.hex_panel.secret_features_you_reveal")) \
            .style("font-size:.75rem;color:var(--km-muted)")
        for i, el in enumerate(data["hidden_features"]):
            entry = rules.BY_ID["feature"].get(el.get("kind"), {})
            with ui.row().classes("items-center gap-2 w-full no-wrap"):
                ui.label(_common._feature_icon(el))
                ui.label(entry.get("name", el.get("kind"))
                         + (f' · {el["name"]}' if el.get("name") else "")) \
                    .style("flex:1;font-size:.82rem")
                ui.button(t("map.hex_panel.reveal"), on_click=lambda _e, j=i: _reveal_secret(
                    h, col, row, j, redraw)).props("dense flat size=sm color=amber")
                ui.button(icon="delete", on_click=lambda _e, j=i: _discard_secret(
                    col, row, j, redraw)).props("dense flat round size=sm color=red")

        with ui.row().classes("items-center gap-2 w-full no-wrap"):
            # Roads, fortification, farmland and work site are not here: they
            # are created with their fields below and then made secret with
            # the tick above. One way per thing.
            kind = ui.select({e["id"]: _common._feature_entry(e)
                              for e in rules.HEX_FEATURES
                              if e["id"] not in _common.FIELD_OF_FEATURE},
                             value="resource") \
                .props("outlined dense options-dense").classes("w-40")
            name = ui.input(t("map.hex_panel.detail")).props("outlined dense").classes("w-32")
            ui.button(icon="add", on_click=lambda: _add_secret(
                col, row, kind.value, name.value, redraw)) \
                .props("dense flat round color=amber").tooltip(t("map.hex_panel.add_secret_feature"))

# The six sides, called as whoever looks at the map would call them. The name
# follows from the neighbour's position instead of the `neighbours` order, so
# it holds for both grid orientations without double tables.
def _direction(dx: float, dy: float) -> str:
    grades = math.degrees(math.atan2(dy, dx)) % 360
    for threshold, name in ((30, "Est"), (90, "Sud-est"), (150, "Sud-ovest"),
                         (210, "Ovest"), (270, "Nord-ovest"), (330, "Nord-est")):
        if grades < threshold:
            return name
    return "Est"

@theme.requires(permissions.SEE_SECRETS)
def _change_border(col: int, row: int, near, kind: str, redraw) -> None:
    STATE.archive.set_border(STATE.campaign, (col, row), near,
                                   kind or None)
    theme.mark_dirty()
    redraw()

def _borders_block(col: int, row: int, redraw) -> None:
    """The six sides of the hex: land, water, ford or bridge.

    A border does not belong to this hex but to the side separating it from
    the neighbour: changing it from here or from the hex opposite is the same
    thing, and rightly so.
    """
    m = STATE.k["map"]
    size = float(m["size"])
    origin = (float(m["origin_x"]), float(m["origin_y"]))
    orient = m["orientation"]
    columns, rows = int(m["columns"]), int(m["rows"])
    borders = STATE.archive.campaign_borders(STATE.campaign)
    cx, cy = hexgrid.hex_center(col, row, size, origin, orient)

    choices = {"": "Terra"}
    choices.update({tid: f'{entry.get("icon", "")} {entry["name"]}'.strip()
                   for tid, entry in travel_mod.BORDERS.items()})

    with ui.expansion(t("map.hex_panel.terrain_borders"), icon="water").classes("w-full")             .props("dense expand-separator"):
        ui.label(t("map.hex_panel.river_lake_running_between"))             .style("font-size:.72rem;color:var(--km-gold-dim)")
        for near in hexgrid.neighbours(col, row, orient):
            if not (0 <= near[0] < columns and 0 <= near[1] < rows):
                continue
            vx, vy = hexgrid.hex_center(near[0], near[1], size, origin, orient)
            entry = borders.get(hexgrid.border_key((col, row), near)) or {}
            with ui.row().classes("items-center gap-2 w-full no-wrap"):
                ui.label(_direction(vx - cx, vy - cy)) \
                    .style("flex:1;font-size:.8rem")
                ui.label(t("map.hex_panel.text_3", near=near[0], near2=near[1])) \
                    .style("font-size:.72rem;color:var(--km-muted)")
                ui.select(choices, value=entry.get("kind") or "",
                          on_change=lambda e, v=near: _change_border(
                              col, row, v, e.value, redraw)) \
                    .props("outlined dense options-dense").classes("w-36")

        _crossings_block(col, row, redraw)

# What fording costs, when the terrain does not decide it. The names are
# those of the travel categories: it is the same number, asked for another
# reason.
def ford_difficulty_options() -> dict:
    options = {"": t("map.hex_panel.like_terrain")}
    options.update({k: f'{v["name"]} ({v["cost"]} {t("map.hex_panel.activities_abbr")})'
                    for k, v in travel_mod.CATEGORIES.items()})
    return options

def _crossings_block(col: int, row: int, redraw) -> None:
    """Bridges and fords on the river crossing *this* hex.

    Borders sit on the sides and show in the list above; these sit in the
    middle, and until there was somewhere to put them a river cutting a hex
    could not be hopped over in any way. Here the kind is changed and, for
    the ford, what passing it costs.
    """
    entries = STATE.archive.campaign_crossings(STATE.campaign).get((col, row)) or []
    if not entries:
        return
    theme.sep()
    ui.label(t("map.hex_panel.river_crossing_hex")) \
        .style("font-size:.78rem;color:var(--km-gold)")
    ui.label(t("map.hex_panel.ford_costs_much_that")) \
        .style("font-size:.72rem;color:var(--km-gold-dim);white-space:normal")
    faces = _common.sections_map().get((col, row)) or ()
    for entry in entries:
        char_id = entry["id"]
        joined = sections.crossing_shores(faces, entry.get("ends"))
        label = (t("map.hex_panel.between_shores", joined=joined[0], joined2=joined[1]) if joined
                     else t("map.hex_panel.no_longer_hops_over"))
        with ui.row().classes("items-center gap-2 w-full no-wrap"):
            ui.label(label) \
                .style("flex:1;font-size:.76rem;color:var(--km-muted)")
            ui.select({"bridge": t("map.hex_panel.bridge"), "ford": t("map.hex_panel.ford")},
                      value=entry.get("kind") or "bridge",
                      on_change=lambda e, x=char_id: _change_crossing(
                          col, row, x, kind=e.value, redraw=redraw)) \
                .props("outlined dense options-dense").classes("w-28")
            if (entry.get("kind") or "bridge") == "ford":
                ui.select(ford_difficulty_options(), value=entry.get("difficulty") or "",
                          on_change=lambda e, x=char_id: _change_crossing(
                              col, row, x, difficulty=e.value,
                              redraw=redraw)) \
                    .props("outlined dense options-dense").classes("w-44")
            ui.button(icon="delete",
                      on_click=lambda _e, x=char_id: _change_crossing(
                          col, row, x, remove=True, redraw=redraw)) \
                .props("dense flat round size=sm color=grey") \
                .tooltip(t("map.hex_panel.removes_crossing_river_becomes"))

@theme.requires(permissions.SEE_SECRETS)
def _change_crossing(col: int, row: int, crossing_id: str,
                            kind: str | None = None,
                            difficulty: str | None = None, remove: bool = False,
                            redraw=None) -> None:
    entries = STATE.archive.campaign_crossings(STATE.campaign).get((col, row)) or []
    current_one = next((v for v in entries if v["id"] == crossing_id), None)
    if current_one is None:
        return
    if remove:
        STATE.archive.remove_crossing(STATE.campaign, crossing_id)
    else:
        STATE.archive.set_crossing(
            STATE.campaign, (col, row), current_one["ends"], current_one.get("at"),
            kind=(kind if kind is not None else current_one.get("kind") or "bridge"),
            difficulty=((difficulty or None) if difficulty is not None
                        else current_one.get("difficulty")),
            crossing_id=crossing_id)
    if redraw:
        redraw()

# The fields the GM may keep to themself, with the name to show.
HIDEABLE_FIELDS = {
    "roads": "map.hex_panel.roads",
    "fortified": "map.hex_panel.fortified",
    "farmland": "map.hex_panel.farmland",
    "work_site": "map.hex_panel.work_site",
}

def _active_field(h: dict, field: str) -> bool:
    """Hiding it makes sense only if it is really on the hex."""
    value = h.get(field)
    return value is not None and value is not False

@theme.requires(permissions.SEE_SECRETS)
def _mark_field(col: int, row: int, field: str, secret: bool, redraw) -> None:
    data = STATE.archive.gm_data(STATE.campaign, col, row)
    hidden = [c for c in (data.get("hidden_fields") or []) if c != field]
    if secret:
        hidden.append(field)
    STATE.archive.write_gm_data(STATE.campaign, col, row, hidden_fields=hidden)
    redraw()

def _secrets(col: int, row: int) -> list:
    return STATE.archive.gm_data(STATE.campaign, col, row)["hidden_features"]

@theme.requires(permissions.SEE_SECRETS)
def _save_secrets(col: int, row: int, listing: list) -> None:
    STATE.archive.write_gm_data(STATE.campaign, col, row, hidden_features=listing)

@theme.requires(permissions.SEE_SECRETS)
def _add_secret(col: int, row: int, kind: str, name: str, redraw) -> None:
    listing = _secrets(col, row)
    listing.append({"kind": kind, "name": (name or "").strip()})
    _save_secrets(col, row, listing)
    redraw()

@theme.requires(permissions.SEE_SECRETS)
def _discard_secret(col: int, row: int, index: int, redraw) -> None:
    listing = _secrets(col, row)
    if 0 <= index < len(listing):
        listing.pop(index)
        _save_secrets(col, row, listing)
    redraw()

@theme.requires(permissions.SEE_SECRETS)
def _reveal_secret(h: dict, col: int, row: int, index: int, redraw) -> None:
    """From GM secret to real feature of the hex."""
    listing = _secrets(col, row)
    if not (0 <= index < len(listing)):
        return
    feature = listing.pop(index)
    field = _common.FIELD_OF_FEATURE.get(feature.get("kind"))
    if field == "work_site":
        h["work_site"] = {"commodity": feature.get("name") or "lumber",
                            "doubled": False}
    elif field:
        h[field] = True
    else:
        h["features"].append(feature)
    if field:
        # If it was also marked as a secret field, now it no longer is.
        data = STATE.archive.gm_data(STATE.campaign, col, row)
        remaining_ones = [c for c in (data.get("hidden_fields") or []) if c != field]
        STATE.archive.write_gm_data(STATE.campaign, col, row, hidden_fields=remaining_ones)
    _save_secrets(col, row, listing)
    entry = rules.BY_ID["feature"].get(feature.get("kind"), {})
    STATE.record(t("map.hex_panel.revealed_hex", get=entry.get("name", feature.get("kind")), col=col, row=row), "map")
    theme.save_and_refresh()
    redraw()

@theme.requires(permissions.SEE_SECRETS)
def _make_secret(h: dict, col: int, row: int, el: dict, refresh) -> None:
    """The reverse: an already visible feature goes back among the GM secrets."""
    if el in h["features"]:
        h["features"].remove(el)
    listing = _secrets(col, row)
    listing.append({"kind": el.get("kind"), "name": el.get("name", "")})
    _save_secrets(col, row, listing)
    theme.save_and_refresh()
    refresh()
    _common._mine()["detail"].refresh()

@theme.requires(permissions.EDIT_KINGDOM)
def _remove_feature(h: dict, el: dict, refresh, detail) -> None:
    """Removes a hex feature from the hex.

    For the settlement deleting the entry is not enough: the link with the
    city must be undone too, otherwise the hex stays hooked to a settlement
    that no longer appears in the list.
    """
    if el["kind"] == "settlement" and h.get("settlement"):
        STATE.unlink_settlement(h["col"], h["row"])
        theme.save_and_refresh()
        detail.refresh()
        theme.notify(t("map.hex_panel.settlement_detached_from_hex"))
        return
    if el in h["features"]:
        h["features"].remove(el)
    refresh()
    detail.refresh()

@theme.requires(permissions.EDIT_KINGDOM)
def _link_existing(sid: str, col: int, row: int, mapping, detail) -> None:
    """Anchors an already founded settlement to this hex."""
    sett = STATE.settlement(sid)
    error = STATE.link_settlement(sid, col, row)
    if error:
        theme.notify(error, "negative")
        return
    theme.save_and_refresh()
    mapping.refresh()
    detail.refresh()
    theme.notify(t("map.hex_panel.now_stands_hex", name=sett["name"], col=col, row=row))

# Panels touched by an edit to a hex: the map, the counts by status, the
# activity buttons, the header (kingdom size) and the City tab (consumption
# depends on farms and influence). Nothing else.
_AFTER_HEX_EDIT = ("hexmap.map", "hexmap.counts", "hexmap.actions",
                      "main.header", "city.content")

@theme.requires(permissions.EDIT_KINGDOM)
def _set_field(where: dict, key: str, value) -> None:
    """A hex field (or its site's): the setter for the box's inputs."""
    where[key] = value


@theme.requires(permissions.SEE_SECRETS)
def _write_gm_notes(col: int, row: int, text: str) -> None:
    STATE.archive.write_gm_data(STATE.campaign, col, row, gm_notes=text)


def _hex_changed(mine: dict | None = None) -> None:
    """Updates the actor at once and the others within half a second."""
    theme.save_light(_AFTER_HEX_EDIT)
    theme.refresh_locals(_AFTER_HEX_EDIT)

@theme.requires(permissions.EDIT_KINGDOM)
def _set_status(h: dict, val: str, mapping, mine: dict | None = None) -> None:
    previous_ = h["status"]
    h["status"] = val
    if val == "claimed" and previous_ != "claimed":
        STATE.check_size_milestones()
    if mine is not None and mine.get("badge") is not None:
        # The status badge is a line of HTML: it updates on its own, without
        # redoing the panel containing the menu just used.
        try:
            mine["badge"].set_content(f'<span class="km-chip">{t(_common.HEX_STATUSES[val][0])}</span>')
        except (RuntimeError, KeyError, AttributeError):
            mine["badge"] = None      # panel already rebuilt by another action
    mapping.refresh()
    _hex_changed(mine)

@theme.requires(permissions.EDIT_KINGDOM)
def _set_farmland(h: dict, val: bool, refresh) -> None:
    h["farmland"] = bool(val)
    # Farmland lives only in this field: it cleans up the old twin entries
    # among the hex features.
    h["features"] = [e for e in h["features"] if e["kind"] != "farmland"]
    refresh()

@theme.requires(permissions.EDIT_KINGDOM)
def _set_site(h: dict, val: str, mapping) -> None:
    if val:
        # Changing the commodity must not reset the «×2»: the Resource hex
        # stays what it is, only what is extracted changes. Rewriting it from
        # scratch made the doubling vanish without telling anyone.
        doubled = bool((h.get("work_site") or {}).get("doubled"))
        h["work_site"] = {"commodity": val, "doubled": doubled}
    else:
        h["work_site"] = None
    # The site lives only here: it cleans up the old twin entries among the
    # features.
    h["features"] = [e for e in h["features"] if e["kind"] != "work_site"]
    mapping.refresh()
    _hex_changed()

# --------------------------------------------------------------------------
def _hex_actions(h: dict, mine: dict) -> None:
    mapping = mine["map"]
    col, row = h["col"], h["row"]
    orient = STATE.orientation

    def adjacent_to_kingdom() -> bool:
        for c, r in hexgrid.neighbours(col, row, orient):
            vic = STATE.existing_hex(c, r)
            if vic and vic["status"] == "claimed":
                return True
        return False

    with ui.column().classes("gap-2 w-full"):
        # ---- Claim Hex
        with ui.row().classes("items-center gap-2 w-full no-wrap"):
            ui.select({a: rules.BY_ID["skills"][a]["name"]
                       for a in rules.BY_ID["activities"]["claim_hex"]["skills"]},
                      value="exploration", label=t("map.hex_panel.claim")).props("outlined dense") \
                .classes("w-44").bind_value(mine, "claim")
            enabled = h["status"] in ("reconnoitered", "cleared") and adjacent_to_kingdom()
            ui.button(t("map.hex_panel.claim_hex_1_rp"),
                      on_click=lambda: _claim(h, mine)) \
                .props(f'dense color=amber {"" if enabled else "disable"}') \
                .tooltip(t("map.hex_panel.requires_reconnoitered_hex_adjacent"))

        # ---- Reconnoiter: an exploration activity, not a kingdom one. It
        # costs as much as Travelling that hex, roads excluded, and brings the
        # hex to Reconnoitered, which is the requirement to claim it.
        with ui.row().classes("items-center gap-2 w-full no-wrap"):
            cost, _category = travel_mod.reconnaissance_cost(
                h, STATE.archive.campaign_difficulty(STATE.campaign).get((col, row)))
            how_much = t("map.hex_panel.cost_decided") if cost is None else t("map.hex_panel.activities", cost=cost)
            ui.button(t("map.hex_panel.reconnoiter", how_much=how_much),
                      on_click=lambda: _reconnoiter(h, mapping)) \
                .props(f'dense outline color=amber '
                       f'{"" if h["status"] == "unknown" else "disable"}') \
                .tooltip(t("map.hex_panel.exploration_activity_scouts_hex"))

        # ---- Clear Hex
        with ui.row().classes("items-center gap-2 w-full no-wrap"):
            ui.select({"engineering": t("map.hex_panel.engineering_prepare_demolish"),
                       "exploration": t("map.hex_panel.exploration_hazards")},
                      value="engineering", label=t("map.hex_panel.clear")).props("outlined dense") \
                .classes("w-56").bind_value(mine, "clear")
            ui.button(t("map.hex_panel.clear_hex"), on_click=lambda: _free(h, mine)).props("dense color=amber")

        with ui.row().classes("gap-2 flex-wrap"):
            ui.button(t("map.hex_panel.establish_work_site"), on_click=lambda: _work_site(h, mapping)) \
                .props("dense outline color=amber")
            ui.button(t("map.hex_panel.establish_farmland"), on_click=lambda: _farmland(h, mapping)) \
                .props("dense outline color=amber")
            ui.button(t("map.hex_panel.build_roads"), on_click=lambda: _roads(h, mapping)).props("dense outline color=amber")
            ui.button(t("map.hex_panel.fortify_hex"), on_click=lambda: _fortify(h, mapping)) \
                .props("dense outline color=amber")
            ui.button(t("map.hex_panel.establish_settlement"), on_click=lambda: _settlement(h, mapping)) \
                .props("dense outline color=amber")

def _cost(h: dict) -> int:
    return rules.disconnected_terrain_cost(h["terrains"])

def _dialog_result(act_id: str, res: rules.Result) -> str:
    return rules.BY_ID["activities"][act_id]["outcomes"].get(res.grade, "")

@theme.requires(permissions.EDIT_KINGDOM)
def _claim(h: dict, mine: dict) -> None:
    mapping = mine["map"]
    if not STATE.spend_rp(1):
        theme.notify(t("map.hex_panel.not_enough_rp_increase"), "warning")
    skill = mine["claim"]
    detail = STATE.skill_detail(skill)
    if STATE.level >= 4:
        detail.append((t("map.hex_panel.expansion_expert_circumstance"), 2))
    mod = sum(v for _n, v in detail)
    res = rules.roll_check(mod, STATE.control_dc, detail, 1 if STATE.in_anarchy else 0)
    STATE.fame_on_critical(res)
    STATE.mark_activity("claim_hex")
    if res.grade in ("success", "critical_success"):
        h["status"] = "claimed"
        STATE.k["xp"] += 10
        STATE.check_size_milestones()
        for el in h["features"]:
            if el["kind"] == "landmark":
                STATE.award_milestone("first_landmark")
            if el["kind"] == "refuge":
                STATE.award_milestone("first_refuge")
        STATE.record(t("map.hex_panel.claimed_hex_10_xp", col=h['col'], row=h['row']), "map")
    theme.save_and_refresh()
    mapping.refresh()
    theme.show_result(res, t("map.hex_panel.claim_hex", col=h['col'], row=h['row']),
                           _dialog_result("claim_hex", res))

@theme.requires(permissions.EDIT_KINGDOM)
def _reconnoiter(h: dict, mapping) -> None:
    if h["status"] != "unknown":
        return
    h["status"] = "reconnoitered"
    STATE.record(t("map.hex_panel.reconnoitered_hex", col=h['col'], row=h['row']), "map")
    theme.save_and_refresh()
    mapping.refresh()

@theme.requires(permissions.EDIT_KINGDOM)
def _free(h: dict, mine: dict) -> None:
    mapping = mine["map"]
    skill = mine["clear"]
    cd = STATE.control_dc + (2 if h["status"] != "claimed" else 0)
    if skill == "engineering":
        if not STATE.spend_rp(_cost(h)):
            theme.notify(t("map.hex_panel.not_enough_rp_increase"), "warning")
    res = rules.roll_check(STATE.skill_mod(skill), cd, STATE.skill_detail(skill),
                           1 if STATE.in_anarchy else 0)
    STATE.fame_on_critical(res)
    STATE.mark_activity("clear_hex")
    if res.grade in ("success", "critical_success") and h["status"] == "unknown":
        h["status"] = "cleared"
    elif res.grade in ("success", "critical_success") and h["status"] == "reconnoitered":
        h["status"] = "cleared"
    if res.grade == "critical_success":
        STATE.add_commodity("luxuries", 2)
    if res.grade == "critical_failure":
        STATE.k["unrest"] += 1
    theme.save_and_refresh()
    mapping.refresh()
    theme.show_result(res, t("map.hex_panel.clear_hex_2", col=h['col'], row=h['row']),
                           _dialog_result("clear_hex", res))

@theme.requires(permissions.EDIT_KINGDOM)
def _work_site(h: dict, mapping) -> None:
    with theme.dialog() as dlg, ui.card().classes("km-panel"):
        theme.title(t("map.hex_panel.establish_work_site_2"), 2)
        kind = ui.select({"lumber": t("map.hex_panel.lumber_camp"), "stone": t("map.hex_panel.quarry_stone"),
                          "ore": t("map.hex_panel.mine_ore")}, value="lumber", label=t("map.hex_panel.type")) \
            .props("outlined dense").classes("w-56")
        ui.label(t("map.hex_panel.cost_rp_most_inhospitable", cost=_cost(h))) \
            .style("color:var(--km-muted)")
        resource = any(e["kind"] == "resource" for e in h["features"])
        if resource:
            ui.label(t("map.hex_panel.this_hex_has_resource")).style("color:var(--km-gold-dim);font-size:.8rem")

        def go() -> None:
            dlg.close()
            if not STATE.spend_rp(_cost(h)):
                theme.notify(t("map.hex_panel.not_enough_rp_increase"), "warning")
            res = rules.roll_check(STATE.skill_mod("engineering"), STATE.control_dc,
                                   STATE.skill_detail("engineering"), 1 if STATE.in_anarchy else 0)
            STATE.fame_on_critical(res)
            STATE.mark_activity("establish_work_site")
            if res.grade in ("success", "critical_success"):
                # Only the dedicated field: the twin entry among the hex
                # features doubled the icon on the map and the row in the panel.
                h["work_site"] = {"commodity": kind.value, "doubled": resource}
                h["features"] = [e for e in h["features"] if e["kind"] != "work_site"]
                STATE.record(t("map.hex_panel.work_site_2", value=kind.value, col=h['col'], row=h['row']), "map")
            if res.grade == "critical_failure":
                STATE.k["unrest"] += 1
            theme.save_and_refresh()
            mapping.refresh()
            theme.show_result(res, t("map.hex_panel.establish_work_site_3"),
                                   _dialog_result("establish_work_site", res))

        with ui.row():
            ui.button(t("map.hex_panel.roll_engineering"), on_click=go).props("color=amber")
            ui.button(t("common.cancel"), on_click=dlg.close).props("flat")
    dlg.open()

@theme.requires(permissions.EDIT_KINGDOM)
def _farmland(h: dict, mapping) -> None:
    hills = "hills" in h["terrains"]
    cost = 2 if hills else 1
    cd = STATE.control_dc + (5 if hills else 0)
    if not STATE.spend_rp(cost):
        theme.notify(t("map.hex_panel.not_enough_rp_increase"), "warning")
    res = rules.roll_check(STATE.skill_mod("agriculture"), cd,
                           STATE.skill_detail("agriculture"), 1 if STATE.in_anarchy else 0)
    STATE.fame_on_critical(res)
    STATE.mark_activity("establish_farmland")
    if res.grade in ("success", "critical_success"):
        # Only the dedicated field: the twin entry among the hex features
        # doubled the icon on the map and the row in the panel.
        h["farmland"] = True
        h["features"] = [e for e in h["features"] if e["kind"] != "farmland"]
    theme.save_and_refresh()
    mapping.refresh()
    theme.show_result(res, t("map.hex_panel.establish_farmland"),
                           _dialog_result("establish_farmland", res))

@theme.requires(permissions.EDIT_KINGDOM)
def _roads(h: dict, mapping) -> None:
    if not STATE.spend_rp(_cost(h)):
        theme.notify(t("map.hex_panel.not_enough_rp_increase"), "warning")
    res = rules.roll_check(STATE.skill_mod("engineering"), STATE.control_dc,
                           STATE.skill_detail("engineering"), 1 if STATE.in_anarchy else 0)
    STATE.fame_on_critical(res)
    STATE.mark_activity("build_roads")
    if res.grade in ("success", "critical_success"):
        h["roads"] = True
    if res.grade == "critical_failure":
        STATE.k["unrest"] += 1
    theme.save_and_refresh()
    mapping.refresh()
    theme.show_result(res, t("map.hex_panel.build_roads"), _dialog_result("build_roads", res))

@theme.requires(permissions.EDIT_KINGDOM)
def _fortify(h: dict, mapping) -> None:
    cost = _cost(h)
    if not STATE.spend_rp(cost):
        theme.notify(t("map.hex_panel.not_enough_rp_increase"), "warning")
    detail = STATE.skill_detail("defense")
    if "fortified_fiefs" in STATE.k["feats"]:
        detail.append((t("map.hex_panel.fortified_fiefs_circumstance"), 2))
    res = rules.roll_check(sum(v for _n, v in detail), STATE.control_dc, detail,
                           1 if STATE.in_anarchy else 0)
    STATE.fame_on_critical(res)
    STATE.mark_activity("fortify_hex")
    if res.grade in ("success", "critical_success"):
        h["fortified"] = True
        STATE.k["unrest"] = max(0, STATE.k["unrest"] - 1)
        if res.grade == "critical_success":
            STATE.k["rp"] += cost // 2
    if res.grade == "critical_failure":
        STATE.k["unrest"] += 1
    theme.save_and_refresh()
    mapping.refresh()
    theme.show_result(res, t("map.hex_panel.fortify_hex"), _dialog_result("fortify_hex", res))

@theme.requires(permissions.EDIT_KINGDOM)
def _settlement(h: dict, mapping) -> None:
    if h.get("settlement"):
        theme.notify(t("map.hex_panel.this_hex_already_contains"), "warning")
        return
    with theme.dialog() as dlg, ui.card().classes("km-panel"):
        theme.title(t("map.hex_panel.establish_settlement"), 2)
        name = ui.input(t("map.hex_panel.village_name")).props("outlined dense").classes("w-64")
        skill = ui.select({a: rules.BY_ID["skills"][a]["name"]
                          for a in rules.BY_ID["activities"]["establish_settlement"]["skills"]},
                         value="industry", label=t("map.hex_panel.skill")).props("outlined dense").classes("w-56")
        ui.label(t("map.hex_panel.critical_success_1d6_rp")) \
            .style("color:var(--km-muted);font-size:.8rem")

        def go() -> None:
            if not name.value:
                theme.notify(t("map.hex_panel.name_required"), "negative")
                return
            dlg.close()
            res = rules.roll_check(STATE.skill_mod(skill.value), STATE.control_dc,
                                   STATE.skill_detail(skill.value), 1 if STATE.in_anarchy else 0)
            STATE.fame_on_critical(res)
            STATE.mark_activity("establish_settlement")
            costs = {"critical_success": 1, "success": 3, "failure": 6}
            if res.grade in costs:
                tot, _ = rules.roll(costs[res.grade], 6)
                if STATE.k["rp"] < tot:
                    res.grade = "critical_failure"
                else:
                    STATE.spend_rp(tot)
                    sett = city.new_settlement(name.value, (h["col"], h["row"]))
                    if not STATE.k["settlements"]:
                        sett["capital"] = True
                        STATE.k["capital"] = sett["id"]
                    STATE.k["settlements"].append(sett)
                    h["settlement"] = sett["id"]
                    if not any(e["kind"] == "settlement" for e in h["features"]):
                        h["features"].append({"kind": "settlement", "name": name.value})
                    STATE.award_milestone("first_village")
                    STATE.record(t("map.hex_panel.founded_village_rp", value=name.value, col=h['col'], row=h['row'], tot=tot), "settlement")
            theme.save_and_refresh()
            mapping.refresh()
            theme.show_result(res, t("map.hex_panel.establish_settlement"),
                                   _dialog_result("establish_settlement", res))

        with ui.row():
            ui.button(t("map.hex_panel.roll"), on_click=go).props("color=amber")
            ui.button(t("common.cancel"), on_click=dlg.close).props("flat")
    dlg.open()
