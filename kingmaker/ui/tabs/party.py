"""The party: the players' characters.

A character is edited by whoever plays it, and by the GM who governs them
all: the filter is not a hidden button but a query, in `characters_of_user`.

Portrait and marker are files inside `assets/characters`, served from
`/assets`, which sits behind authentication like everything else.

Vehicles have a tab all their own, in `ui/transport.py`: here only the chip
of the one assigned to a character appears.
"""
from __future__ import annotations

import time
import uuid

from nicegui import events, ui

from kingmaker import config, rules, travel as travel_mod
from kingmaker.media import images
from kingmaker.access import permissions
from kingmaker.locale import units
from kingmaker.state import STATE
from kingmaker.ui import theme, badges
from kingmaker.locale.i18n import t

# Portraits live in a sub-folder of their own: `assets/` is already full of
# maps, and this way the right folder is deleted without thinking.
CHARACTER_FOLDER = config.ASSETS_DIR / "characters"


def _url(name: str | None, side: int | None = images.PORTRAIT_SIDE) -> str:
    """The address of the portrait, at the size it is really looked at.

    The original file stays where it is: what ends up in the page is a
    lighter copy, because a portrait is seen in a box of a few hundred pixels
    and the rest is just stuff to download.
    """
    return images.address("/assets/characters", CHARACTER_FOLDER, name, side)


def number(value, default_: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default_


# --------------------------------------------------------------------------
def party_panel() -> None:
    user = theme.user()
    if user is None:
        return
    theme.register_refresh("party.characters", list_characters)
    with ui.column().classes("w-full gap-3").style("max-width:1100px"):
        list_characters()


# ------------------------------------------------------------- characters
def visible_characters(user) -> list[dict]:
    """The characters this user is entitled to see on the sheet.

    The GM and the administrator see them all; a player sees their own. It is
    not a filter on the full list: the full list is not read at all.
    """
    if user is None:
        return []
    if permissions.can(user, permissions.MANAGE_CHARACTERS):
        return STATE.characters()
    return STATE.archive.characters_of_user(STATE.campaign, user.id)


@ui.refreshable
def list_characters() -> None:
    user = theme.user()
    listing = visible_characters(user)
    gm = permissions.can(user, permissions.MANAGE_CHARACTERS)
    vehicles = {v["id"]: v for v in STATE.archive.list_stable(STATE.campaign)}
    # The account name is seen only by whoever governs the characters, and we
    # read it once instead of once per sheet.
    account = ({u["id"]: u["username"] for u in STATE.archive.list_users()}
               if gm else None)

    with ui.card().classes("km-panel w-full"):
        with ui.row().classes("items-center gap-3 w-full no-wrap"):
            theme.title(t("party.characters"), 2)
            ui.element("div").style("flex:1")
            if gm:
                ui.button(t("party.new_character"), icon="person_add", on_click=_create_character) \
                    .props("dense outline color=amber")
        ui.label(t("party.portrait_token_are_yours")) \
            .style("color:var(--km-muted);font-size:.8rem")
        if not gm:
            ui.label(t("party.you_see_sheet_characters")) \
                .style("color:var(--km-gold-dim);font-size:.78rem")

        if not listing:
            ui.label(t("party.no_character_show")
                     if gm else t("party.no_character_linked_your")) \
                .style("color:var(--km-muted);font-size:.85rem")
            return

        with ui.row().classes("gap-3 flex-wrap w-full"):
            for char in listing:
                _short_tab(char, vehicles, user, account)


def _short_tab(char: dict, vehicles: dict, user, account: dict | None) -> None:
    """The character's calling card, with the marker and the numbers."""
    total = travel_mod.character_speed(char)
    activities = travel_mod.activities_per_day(total)
    stable_entry = vehicles.get(char.get("stable_id") or "")
    with ui.card().classes("km-panel").style("width:300px;padding:10px"):
        with ui.row().classes("items-center gap-2 no-wrap w-full"):
            badges.person_badge(char, 46)
            with ui.column().classes("gap-0").style("flex:1;min-width:0"):
                ui.html(f'<b class="km-title" style="font-size:1.05rem">'
                        f'{theme.esc(char["name"])}</b>')
                where = (t("party.hex", hex_col=char["hex_col"], hex_row=char["hex_row"])
                        if char["hex_col"] is not None else t("party.not_map_yet"))
                ui.label(where).style("font-size:.72rem;color:var(--km-muted)")
            if permissions.can_on_character(user, char):
                ui.button(icon="edit", on_click=lambda _=None, p=char: character_dialog(p)) \
                    .props("flat dense round size=sm color=amber").tooltip(t("party.edit_sheet"))

        if char.get("portrait"):
            ui.image(_url(char["portrait"])).classes("w-full") \
                .style("border-radius:8px;border:1px solid var(--km-line);"
                       "max-height:190px;object-fit:cover")

        with ui.row().classes("gap-2 flex-wrap items-center").style("margin-top:4px"):
            ui.html(t("party.span_class_km_chip", format_metres=format_metres(total)))
            ui.html(t("party.span_class_km_chip_2", activity_format=activity_format(activities)))
            if char.get("speed_bonus_m"):
                ui.html(f'<span class="km-chip" style="font-size:.66rem;'
                        f'border-color:var(--km-gold-dim)">'
                        f'{t("party.base_short")} {format_metres(char["speed_m"])} '
                        f'{format_metres(char["speed_bonus_m"], sign=True)}</span>')
        if stable_entry is not None:
            _vehicle_row(stable_entry)
        if char.get("user_id") and permissions.can(user, permissions.MANAGE_CHARACTERS):
            account_name = next((u["username"] for u in STATE.archive.list_users()
                                 if u["id"] == char["user_id"]), "?")
            ui.label(t("party.account", account_name=account_name)) \
                .style("font-size:.68rem;color:var(--km-muted)")


def _vehicle_row(entry: dict) -> None:
    catalogue = rules.BY_ID["vehicle"].get(entry["vehicle"], {})
    label = entry.get("name") or catalogue.get("name", entry["vehicle"])
    metres, _reason = travel_mod.speed_from_stable(entry)
    text = (f'{travel_mod.vehicle_symbol(entry)} {label}'
             + (f' · {format_metres(metres)}' if metres
                else t("party.speed_entered")))
    color = "var(--km-gold)" if entry.get("available") else "var(--km-red)"
    ui.html(f'<span class="km-chip" style="font-size:.68rem;border-color:{color}">'
            f'{theme.esc(text)}{"" if entry.get("available") else t("party.not_available")}</span>')


def format_metres(value, sign: bool = False) -> str:
    """A stored Speed, shown in the unit of the window."""
    return units.fmt(number(value), sign=sign)


EXPLORATION_TABLE = {"m": "party.hex_exploration_table_m",
                     "ft": "party.hex_exploration_table_ft"}


def activity_format(value: float) -> str:
    text = "½" if value == 0.5 else f"{value:g}"
    return t("party.activities", text=text)


def pace(speed_m: float) -> str:
    """«7.2 km/h · 57.6 km a day», from the Travel Speed table.

    Travel between hexes is counted in activities, not in kilometres, and
    rightly so: but «how fast do we go» is a question asked at the table, and
    the rules have the row with the answer. The distances hold on flat, clear
    terrain — difficult terrain halves them.
    """
    row = travel_mod.travel_speed(speed_m)
    if row is None:
        return ""
    hour, day, key = units.per_hour_and_day(row)
    return t(key, hour=hour, day=day)


# ---------------------------------------------------------------- dialog
def character_dialog(char: dict) -> None:
    """The full sheet: like «Edit» on Roll20, portrait and marker included."""
    user = theme.user()
    if not permissions.can_on_character(user, char):
        theme.notify(t("party.you_cannot_edit_this"), "negative")
        return
    gm = permissions.can(user, permissions.MANAGE_CHARACTERS)
    char_id = char["id"]

    with theme.dialog() as dlg, ui.card().classes("km-panel km-scroll") \
            .style("min-width:min(760px, 94vw);max-width:94vw"):
        theme.title(t("party.sheet", name=char["name"]), 2)

        @ui.refreshable
        def body() -> None:
            current_one = STATE.archive.character(char_id)
            if current_one is None:
                ui.label(t("party.character_no_longer_exists")).style("color:var(--km-red)")
                return
            with ui.row().classes("gap-4 items-start w-full no-wrap flex-wrap"):
                _image_box(current_one, "portrait", t("party.portrait"), 210, body.refresh)
                _image_box(current_one, "token", t("party.token_map"), 110, body.refresh)
                with ui.column().classes("gap-2").style("flex:1;min-width:280px"):
                    _fields(current_one, gm, body.refresh)

        body()
        theme.sep()
        with ui.row().classes("justify-between w-full items-center"):
            if gm:
                ui.button(t("common.delete"), icon="delete",
                          on_click=lambda: (dlg.close(), _confirm_deletion(char))) \
                    .props("flat color=red dense")
            else:
                ui.element("div")
            ui.button(t("common.close"), on_click=dlg.close).props("flat color=amber")
    dlg.open()


def _fields(char: dict, gm: bool, redraw) -> None:
    char_id = char["id"]
    total = travel_mod.character_speed(char)

    ui.input(t("party.name"), value=char["name"],
             on_change=lambda e: _edit(char_id, name=(e.value or "").strip())) \
        .props("outlined dense debounce=500").classes("w-full")

    with ui.row().classes("gap-2 items-center flex-wrap w-full"):
        ui.number(t("party.base_speed_m", unit=units.name()),
                  value=units.to_shown(number(char["speed_m"], 7.5)),
                  min=0, max=units.to_shown(60), step=units.step(),
                  on_change=lambda e: (_edit(char_id, speed_m=units.from_shown(number(e.value))), redraw())) \
            .props("outlined dense").classes("w-40") \
            .tooltip(t("party.speed_character_sheet"))
        ui.number(t("party.bonus_m", unit=units.name()),
                  value=units.to_shown(number(char.get("speed_bonus_m"))),
                  min=-units.to_shown(30), max=units.to_shown(30), step=units.step(),
                  on_change=lambda e: (_edit(char_id, speed_bonus_m=units.from_shown(number(e.value))),
                                       redraw())) \
            .props("outlined dense").classes("w-32") \
            .tooltip(t("party.extra_metres_from_feats"))
        ui.number(t("party.con_modifier"), value=int(char.get("con_mod") or 0),
                  min=-5, max=10, step=1,
                  on_change=lambda e: _edit(char_id, con_mod=int(number(e.value)))) \
            .props("outlined dense").classes("w-36") \
            .tooltip(t("party.how_many_days_forced"))
        ui.number(t("party.swim_speed_m", unit=units.name()),
                  value=units.to_shown(number(char.get("swim_speed_m"))),
                  min=0, max=units.to_shown(60), step=units.step(),
                  on_change=lambda e: (_edit(char_id,
                                                 swim_speed_m=units.from_shown(number(e.value))),
                                       redraw())) \
            .props("outlined dense").classes("w-44") \
            .tooltip(t("party.leave_zero_if_they"))

    ui.html(t("party.div_style_font_size", esc=theme.esc(format_metres(total)), esc2=theme.esc(activity_format(travel_mod.activities_per_day(total)))))
    ui.label(t(EXPLORATION_TABLE[units.current()])) \
        .style("font-size:.72rem;color:var(--km-muted)")
    swim = travel_mod.swim_speed(char)
    if swim:
        ui.label(t("party.swims_passes_water_border", format_metres=format_metres(swim))) \
            .style("font-size:.74rem;color:var(--km-gold-dim);white-space:normal")

    theme.sep()
    with ui.row().classes("gap-2 items-center flex-wrap w-full"):
        ui.color_input(t("party.color"), value=char.get("color") or "#d7b263",
                       on_change=lambda e: (_edit(char_id, color=e.value or "#d7b263"),
                                            redraw())) \
            .props("outlined dense").classes("w-40") \
            .tooltip(t("party.border_token_map"))
        # Only the vehicles placed **where they are**: one boards what is in
        # front of one, and a dropdown offering the carriage stopped on the
        # other side of the kingdom would promise something travel then does
        # not honour.
        here = ((char.get("hex_col"), char.get("hex_row"))
               if char.get("hex_col") is not None else None)
        vehicles = [v for v in STATE.archive.list_stable(STATE.campaign)
                   if travel_mod.where_it_is(v) == here and here is not None]
        options = {"": t("party.on_foot")} | {
            v["id"]: (v.get("name") or rules.BY_ID["vehicle"].get(v["vehicle"], {})
                      .get("name", v["vehicle"]))
            + ("" if v.get("available") else t("party.not_available"))
            for v in vehicles}
        ui.select(options, label=t("party.vehicle_if_one_front"),
                  value=char.get("stable_id") or "",
                  on_change=lambda e: (_climb(char_id, e.value or None), redraw())) \
            .props("outlined dense options-dense").classes("w-56") \
            .tooltip(t("party.only_vehicles_placed_their"))

    with ui.row().classes("gap-2 items-center flex-wrap w-full"):
        ui.number(t("party.hex_column"), value=char["hex_col"], step=1, format="%d",
                  on_change=lambda e: _place(char_id, "hex_col", e.value)) \
            .props("outlined dense clearable").classes("w-40")
        ui.number(t("party.hex_row"), value=char["hex_row"], step=1, format="%d",
                  on_change=lambda e: _place(char_id, "hex_row", e.value)) \
            .props("outlined dense clearable").classes("w-40")
        ui.label(t("party.empty_fields_remove_token")) \
            .style("font-size:.72rem;color:var(--km-muted)")

    if gm:
        users = {"": t("party.no_account")} | {
            u["id"]: u["username"] for u in STATE.archive.list_users()}
        ui.select(users, label=t("party.played"), value=char.get("user_id") or "",
                  on_change=lambda e: _edit(char_id, user_id=e.value or None)) \
            .props("outlined dense options-dense").classes("w-56") \
            .tooltip(t("party.who_sees_edits_this"))

    ui.textarea(t("party.notes"), value=char.get("note") or "",
                on_change=lambda e: _edit(char_id, note=e.value or "")) \
        .props("outlined dense autogrow debounce=600").classes("w-full")


def _image_box(char: dict, field: str, label: str, side: int, redraw) -> None:
    """Portrait or marker: preview, upload and removal."""
    char_id = char["id"]
    badge = field == "token"
    with ui.column().classes("gap-1 items-center").style(f"width:{side}px"):
        ui.label(label).style("font-size:.72rem;color:var(--km-muted)")
        if char.get(field):
            ui.image(_url(char[field])).style(
                f'width:{side}px;height:{side}px;object-fit:cover;'
                f'border:2px solid {images.valid_color(char.get("color"))};'
                f'border-radius:{"50%" if badge else "8px"}')
        elif badge:
            badges.person_badge(char, side)
        else:
            ui.html(f'<div style="width:{side}px;height:{side}px;border-radius:8px;'
                    f'background:#241d15;border:1px dashed var(--km-line);display:flex;'
                    f'align-items:center;justify-content:center;color:var(--km-muted);'
                    f'font-size:.72rem;text-align:center;padding:6px">{t("party.no_image")}</div>')

        async def load(e: events.UploadEventArguments) -> None:
            await _load_image(char_id, field, e, redraw)

        ui.upload(on_upload=load, auto_upload=True,
                  max_file_size=images.MAX_PORTRAIT_BYTES) \
            .props('accept=image/* flat dense').classes("w-full") \
            .style("max-width:100%")
        if char.get(field):
            ui.button(t("common.remove"), icon="close",
                      on_click=lambda: _remove_image(char_id, field, redraw)) \
                .props("flat dense size=sm color=grey")


async def _load_image(char_id: str, field: str, e: events.UploadEventArguments,
                           redraw) -> None:
    """The permission is checked again here: hiding the box is not a defence."""
    char = STATE.archive.character(char_id)
    if not permissions.can_on_character(theme.user(), char):
        theme.notify(t("party.you_cannot_edit_this"), "negative")
        return
    safe = images.safe_file_name(e.file.name)
    if safe is None:
        theme.notify(t("party.png_jpg_gif_webp"), "negative")
        return
    extension = safe[safe.rfind("."):]
    name = images.unique_name(f"{char_id}-{field}", extension)
    try:
        await images.accept(e.file, CHARACTER_FOLDER, name, images.MAX_PORTRAIT_BYTES)
    except images.ImageRejected as reason:
        theme.notify(str(reason), "negative")
        return
    old_one = char.get(field)
    STATE.archive.update_character(char_id, **{field: name})
    images.delete(CHARACTER_FOLDER, old_one)
    redraw()
    _propagate()


def _remove_image(char_id: str, field: str, redraw) -> None:
    char = STATE.archive.character(char_id)
    if not permissions.can_on_character(theme.user(), char):
        theme.notify(t("party.you_cannot_edit_this"), "negative")
        return
    STATE.archive.update_character(char_id, **{field: None})
    images.delete(CHARACTER_FOLDER, char.get(field))
    redraw()
    _propagate()


# ------------------------------------------------------------- writing
def _climb(char_id: str, sid: str | None) -> None:
    """Boards or gets off, with the same check the map does.

    The dropdown already shows only the vehicles that are there, but a
    dropdown is not a defence: the rule lives in `travel.ascent_blocked` and
    that is what decides, here as on the map.
    """
    char = STATE.archive.character(char_id)
    if not permissions.can_on_character(theme.user(), char):
        theme.notify(t("party.you_cannot_edit_this"), "negative")
        return
    if sid:
        entry = STATE.archive.stable_vehicle(sid)
        why = travel_mod.ascent_blocked(
            char, entry or {},
            STATE.archive.campaign_sections(STATE.campaign,
                                            STATE.k["map"]["orientation"]),
            STATE.k["map"]["orientation"])
        if why:
            theme.notify(why, "warning")
            _propagate()
            return
    if sid:
        # Aboard one is where the vehicle is: same hex, same spot.
        entry = STATE.archive.stable_vehicle(sid) or {}
        where_vehicle = travel_mod.where_it_is(entry)
        if where_vehicle is not None:
            STATE.archive.update_character(
                char_id, stable_id=sid, hex_col=where_vehicle[0], hex_row=where_vehicle[1],
                pos_x=entry.get("pos_x"), pos_y=entry.get("pos_y"))
            _propagate()
            return
    STATE.archive.update_character(char_id, stable_id=sid)
    _propagate()


def _edit(char_id: str, **fields) -> None:
    char = STATE.archive.character(char_id)
    if not permissions.can_on_character(theme.user(), char):
        theme.notify(t("party.you_cannot_edit_this"), "negative")
        return
    STATE.archive.update_character(char_id, **fields)
    if "name" in fields:
        # The name also lives in the Leadership roles that cite the character.
        for entry in STATE.k["roles"].values():
            if entry.get("character_id") == char_id:
                entry["name"] = fields["name"]
        theme.save_and_refresh()
    _propagate()


def _place(char_id: str, field: str, value) -> None:
    """Moves the marker, within the bounds of the grid."""
    if value in (None, ""):
        _edit(char_id, **{field: None})
        return
    m = STATE.k["map"]
    max_ = int(m["columns"] if field == "hex_col" else m["rows"]) - 1
    _edit(char_id, **{field: max(0, min(max_, int(number(value))))})


def _propagate() -> None:
    """Markers and sheets change for everyone: refreshes the other windows too."""
    list_characters.refresh()
    theme.refresh_panels(("party.characters", "transport.list",
                             "hexmap.map"))


def _create_character() -> None:
    if not permissions.can(theme.user(), permissions.MANAGE_CHARACTERS):
        theme.notify(t("party.only_game_master_can"), "negative")
        return
    with theme.dialog() as dlg, ui.card().classes("km-panel").style("min-width:340px"):
        theme.title(t("party.new_character"), 2)
        field = ui.input(t("party.name")).props("outlined dense autofocus").classes("w-full")

        def create() -> None:
            name = (field.value or "").strip()
            if not name:
                theme.notify(t("party.name_required"), "negative")
                return
            STATE.archive.create_character({
                "id": uuid.uuid4().hex[:12],
                "campaign_id": STATE.campaign,
                "user_id": None,
                "name": name,
                "speed_m": 7.5,
                "con_mod": 0,
                "color": "#d7b263",
                "active": 1,
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            })
            dlg.close()
            _propagate()

        with ui.row().classes("justify-end w-full"):
            ui.button(t("common.cancel"), on_click=dlg.close).props("flat")
            ui.button(t("common.create"), on_click=create).props("color=amber")
    dlg.open()


def _confirm_deletion(char: dict) -> None:
    if not permissions.can(theme.user(), permissions.MANAGE_CHARACTERS):
        theme.notify(t("party.only_game_master_can_2"), "negative")
        return
    roles = [rid for rid, v in STATE.k["roles"].items()
             if v.get("character_id") == char["id"]]
    with theme.dialog() as dlg, ui.card().classes("km-panel"):
        theme.title(t("party.delete_character"), 2)
        ui.label(t("party.will_removed_from_campaign", name=char["name"]))
        if roles:
            names = ", ".join(rules.BY_ID["role"][r]["name"] for r in roles)
            ui.label(t("party.holds_those_roles_will", names=names)) \
                .style("color:var(--km-gold);font-size:.82rem")

        def go() -> None:
            for rid in roles:
                STATE.k["roles"][rid]["character_id"] = None
                STATE.k["roles"][rid]["name"] = ""
            for field in ("portrait", "token"):
                images.delete(CHARACTER_FOLDER, char.get(field))
            STATE.archive.delete_character(char["id"])
            dlg.close()
            theme.save_and_refresh()
            _propagate()

        with ui.row():
            ui.button(t("common.delete"), on_click=go).props("color=red")
            ui.button(t("common.cancel"), on_click=dlg.close).props("flat")
    dlg.open()
