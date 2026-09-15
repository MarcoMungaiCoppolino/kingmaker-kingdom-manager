"""The kingdom's transport: the vehicles the party really owns.

A tab of its own, not a box at the bottom of the Party: vehicles belong to
the kingdom, not to a character, and they are managed by whoever plays the
kingdom while a character is edited by whoever plays it. They were two lists
with two different rules inside the same page, and it was confusing.

Inside, the vehicles are split by **where they go**: the Stable holds the land
ones, the Harbour the water ones, and — if you have any — the Sky those that
fly. It is not a cosmetic ordering: it is the only difference travel really
looks at. A boat crosses a Water Border and follows the course of a river, a
wagon stops on the bank like whoever goes on foot, and whoever flies passes
over both («If you're flying or traveling on water, almost all hexes are open
terrain»).

Where a vehicle goes is said by the rules, not by the table: the fastest
movement among those written on its page is looked at — the Apparatus of the
Octopus walks at 5 feet and swims at 40, and it is a water thing. When the
page gives no Speed — a wagon goes as fast as the creature towing it — the
app does not guess and puts it in the Stable until you tell it.

The catalogue comes from the vehicles pages of Archives of Nethys and of
pf2.altervista.org, transcribed in `data/vehicles.json`. Where the page gives
no number — the Speed of a wagon depends on who tows it — the app does not
make it up: it asks, saying why.

Image and marker live in `assets/vehicles`, next to the characters' and
served by the same authenticated `/assets`. The marker appears on the map in
the hex the vehicle was placed in — a vehicle is in a place, like anyone else.

This page is the **depot**: vehicles are bought, named, seats and Speed are
counted. Who boards and who gets off is decided on the map instead, in
Travel, because that is where one sees whether someone is in front of the
wagon or three hexes away.
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
from kingmaker.ui.tabs.party import activity_format, format_metres, number
from kingmaker.locale.i18n import t

# Vehicles have their own sub-folder, like the characters: this way the right
# one is emptied without thinking about it.
VEHICLE_FOLDER = config.ASSETS_DIR / "vehicles"


def vehicle_url(name: str | None) -> str:
    return images.address("/assets/vehicles", VEHICLE_FOLDER, name,
                              images.PORTRAIT_SIDE)


def transport_panel() -> None:
    if theme.user() is None:
        return
    theme.register_refresh("transport.list", list_transports)
    with ui.column().classes("w-full gap-3").style("max-width:1100px"):
        list_transports()


def _propagate() -> None:
    """Transport changes the map too: the vehicle markers are there."""
    theme.refresh_panels(("transport.list", "party.characters",
                             "hexmap.map", "hexmap.travel", "hexmap.party"))


# The three depots, in the order they appear. Each with its trade written
# beside: the split serves to know what the vehicle does, not to tidy up.
DEPOTS = (
    ("land", "🐎"),
    ("water", "⛵"),
    ("air", "🎈"),
)
# Title and explanation of each depot: `transport.depot.<kind>` and
# `transport.depot_explain.<kind>` in the catalogs.


@ui.refreshable
def list_transports() -> None:
    user = theme.user()
    can_manage = permissions.can(user, permissions.MANAGE_STABLE)
    entries = STATE.archive.list_stable(STATE.campaign)
    per_depot: dict[str, list] = {key: [] for key, _icon in DEPOTS}
    for entry in entries:
        per_depot.setdefault(travel_mod.vehicle_kind(entry), []).append(entry)

    with ui.card().classes("km-panel w-full"):
        with ui.row().classes("items-center gap-3 w-full no-wrap"):
            theme.title(t("transport.transport"), 2)
            ui.element("div").style("flex:1")
            if can_manage:
                ui.button(t("transport.add_vehicle"), icon="add", on_click=_catalogue_dialog) \
                    .props("dense outline color=amber")
        ui.label(t("transport.vehicles_kingdom_owns_whoever")) \
            .style("color:var(--km-muted);font-size:.8rem")
        ui.label(t("transport.vehicle_data_from_rules")) \
            .style("color:var(--km-gold-dim);font-size:.76rem")

        if not entries:
            ui.label(t("transport.you_have_no_vehicle")) \
                .style("color:var(--km-muted);font-size:.85rem")
            return

        for key, icon in DEPOTS:
            title = t(f"transport.depot.{key}")
            explain = t(f"transport.depot_explain.{key}")
            group = per_depot.get(key) or []
            # Stable and Harbour are always there, even empty: they show that
            # the place to put a boat exists. Not the Sky — appearing to say
            # «nothing here» to whoever has no airship is just one more line
            # to read.
            if not group and key == "air":
                continue
            theme.sep()
            with ui.row().classes("items-center gap-2 w-full no-wrap"):
                ui.html(f'<b class="km-title" style="font-size:.95rem">{icon} '
                        f'{theme.esc(title)}</b>')
                ui.html(f'<span class="km-chip" style="font-size:.66rem">'
                        f'{len(group)}</span>')
            ui.label(explain) \
                .style("color:var(--km-muted);font-size:.76rem;white-space:normal")
            if not group:
                ui.label(t("transport.empty") if key == "land" else
                         t("transport.no_boat_without_one")) \
                    .style("color:var(--km-muted);font-size:.8rem")
                continue
            for entry in group:
                _stable_row(entry, can_manage)


def _why_where_it_goes(entry: dict) -> str:
    """Where the depot this vehicle sits in comes from."""
    from_catalogue = travel_mod.kind_from_catalogue(entry.get("vehicle") or "")
    chosen_one = (entry.get("kind") or "").strip()
    name = travel_mod.where_name(travel_mod.vehicle_kind(entry))
    if chosen_one and from_catalogue and chosen_one != from_catalogue:
        return (t("transport.chosen_table_rules_give", name=name, get=travel_mod.where_name(from_catalogue)))
    if from_catalogue:
        return t("transport.from_rules_catalogue_speed", name=name)
    return (t("transport.rules_give_no_speed"))


def _stable_row(entry: dict, can_manage: bool) -> None:
    catalogue = rules.BY_ID["vehicle"].get(entry["vehicle"], {})
    metres, reason = travel_mod.speed_from_stable(entry)
    seats, why_seats = travel_mod.vehicle_seats(entry)
    aboard = STATE.archive.characters_on_vehicle(entry["id"])
    sid = entry["id"]

    with ui.column().classes("gap-1 w-full") \
            .style("border-top:1px solid var(--km-line);padding-top:8px"):
        with ui.row().classes("items-center gap-2 w-full no-wrap flex-wrap"):
            badges.vehicle_badge(entry, 32)
            ui.html(f'<b class="km-title" style="min-width:150px">'
                    f'{theme.esc(catalogue.get("name", entry["vehicle"]))}</b>')
            if can_manage:
                ui.input(value=entry.get("name") or "", placeholder=t("transport.name_you_gave"),
                         on_change=lambda e, i=sid: _edit_stable_entry(i, name=e.value or "")) \
                    .props("outlined dense debounce=500").classes("w-44")
            elif entry.get("name"):
                ui.label(entry["name"]).style("font-size:.85rem")
            ui.html(f'<span class="km-chip" style="font-size:.66rem">'
                    f'{t("common.level_short", level=catalogue.get("level", "?"))} · {theme.esc(catalogue.get("price", ""))}'
                    f'</span>')
            if metres:
                ui.html(t("transport.span_class_km_chip", esc=theme.esc(format_metres(metres)), esc2=theme.esc(activity_format(travel_mod.activities_per_day(metres)))))
            ui.element("div").style("flex:1")
            if can_manage:
                ui.checkbox(t("transport.available"), value=bool(entry.get("available")),
                            on_change=lambda e, i=sid: _edit_stable_entry(
                                i, available=1 if e.value else 0)) \
                    .tooltip(t("transport.untick_when_vehicle_broken"))
                ui.button(icon="delete", on_click=lambda _=None, v=entry: _delete_stable_entry(v)) \
                    .props("flat dense round size=sm color=red")
            elif not entry.get("available"):
                ui.html(t("transport.span_class_km_chip_2"))

        with ui.row().classes("items-center gap-2 w-full no-wrap flex-wrap"):
            ui.label(catalogue.get("speed_text") or "") \
                .style("font-size:.74rem;color:var(--km-muted);flex:1;min-width:200px")
            if can_manage:
                # A single field: the hint changes because the reason to fill
                # it changes, not the field.
                help_ = (reason if metres is None
                         else t("transport.leave_empty_use_catalogue"))
                ui.number(t("transport.speed_m", unit=units.name()),
                          value=(units.to_shown(entry["speed_m"])
                                 if entry.get("speed_m") else None),
                          min=0, max=units.to_shown(60), step=units.step(),
                          on_change=lambda e, i=sid: _edit_stable_entry(
                              i, speed_m=units.from_shown(number(e.value)) or None)) \
                    .props("outlined dense clearable").classes("w-36") \
                    .tooltip(help_)
                # Seats serve to decide whether the whole party fits when
                # travelling aboard: without a number, that choice stays closed.
                ui.number(t("transport.seats"), value=entry.get("seats"),
                          min=1, max=200, step=1,
                          on_change=lambda e, i=sid: _edit_stable_entry(
                              i, seats=int(number(e.value)) or None)) \
                    .props("outlined dense clearable").classes("w-28") \
                    .tooltip(why_seats if seats is None else
                             t("transport.leave_empty_use_that", why_seats=why_seats))
                # Where it goes: it is the only difference travel looks at, and
                # it comes from the catalogue. The dropdown serves to overrule
                # it when the table built something the wiki does not know.
                ui.select({"land": t("transport.land"), "water": t("transport.water"),
                           "air": t("transport.flies")},
                          value=travel_mod.vehicle_kind(entry),
                          label=t("transport.where_goes"),
                          on_change=lambda e, i=sid: _edit_stable_entry(
                              i, kind=e.value or "land")) \
                    .props("outlined dense options-dense").classes("w-36") \
                    .tooltip(_why_where_it_goes(entry))
        if metres is None and reason:
            ui.label(t("transport.speed_entered", reason=reason)) \
                .style("font-size:.72rem;color:var(--km-gold)")
        if seats is None and why_seats:
            ui.label(t("transport.seats_counted_until_there", why_seats=why_seats)) \
                .style("font-size:.72rem;color:var(--km-gold)")
        _crew(entry, aboard)
        if can_manage:
            with ui.expansion(t("transport.image_token")).classes("w-full") \
                    .props("dense dense-toggle"):
                ui.label(t("transport.token_appears_map_hex")) \
                    .style("font-size:.74rem;color:var(--km-muted)")
                with ui.row().classes("gap-3 items-start flex-wrap"):
                    _image_box(entry, "portrait", "Immagine", 132)
                    _image_box(entry, "token", t("transport.token"), 92)
            ui.input(value=entry.get("note") or "", placeholder=t("transport.notes"),
                     on_change=lambda e, i=sid: _edit_stable_entry(i, note=e.value or "")) \
                .props("outlined dense debounce=600").classes("w-full")
        elif entry.get("note"):
            ui.label(entry["note"]).style("font-size:.76rem;color:var(--km-muted)")


def _crew(entry: dict, aboard: list[dict]) -> None:
    """Who is on it and where the vehicle is. From here one looks, one does not change.

    The dropdown that used to be here — «Aboard», tick and board — was handy
    and said something false: that one can board a vehicle from anywhere in
    the kingdom. Boarding is a gesture made **being there**, and the place
    where one is is the map: now that is where one boards and gets off, with
    the check that gesture requires. Here the count remains, which is what one
    comes looking for when opening Transport.
    """
    where = travel_mod.where_it_is(entry)
    if where is None:
        text = (t("transport.shed_not_map_so"))
        if aboard:
            # An earlier save could have people «on» a vehicle that is
            # nowhere: it is said as it is, instead of pretending.
            text += (t("transport.we_still_have")
                      + ", ".join(p["name"] for p in aboard)
                      + t("transport.aboard_link_from_before"))
        ui.label(text) \
            .style("font-size:.74rem;color:var(--km-muted);white-space:normal")
        return
    row = t("transport.map", where=where[0], where2=where[1])
    if aboard:
        row += t("transport.aboard_list", names=", ".join(p["name"] for p in aboard))
    ui.label(row).style("font-size:.74rem;color:var(--km-muted)")
    ui.label(t("transport.who_boards_who_gets")) \
        .style("font-size:.72rem;color:var(--km-muted);white-space:normal")
    if aboard:
        _capacity_warning(entry, len(aboard))


def _capacity_warning(entry: dict, how_many: int) -> None:
    """Compares who is on it with the seats that vehicle has.

    It is a reminder, not a ban: who fits is decided by the table. The number
    is the same the planner looks at, so it does not happen that here it is
    fine and on the map it is not.
    """
    seats, why = travel_mod.vehicle_seats(entry)
    if seats is None or how_many <= seats:
        return
    ui.label(t("transport.seats_but_assigned_characters", seats=seats, why=why, how_many=how_many)) \
        .style("font-size:.72rem;color:var(--km-gold)")


def _edit_stable_entry(sid: str, **fields) -> None:
    if not permissions.can(theme.user(), permissions.MANAGE_STABLE):
        theme.notify(t("transport.you_do_not_have"), "negative")
        return
    STATE.archive.update_stable_vehicle(sid, **fields)
    list_transports.refresh()
    _propagate()


def _delete_stable_entry(entry: dict) -> None:
    if not permissions.can(theme.user(), permissions.MANAGE_STABLE):
        theme.notify(t("transport.you_do_not_have"), "negative")
        return
    catalogue = rules.BY_ID["vehicle"].get(entry["vehicle"], {})
    label = entry.get("name") or catalogue.get("name", entry["vehicle"])
    with theme.dialog() as dlg, ui.card().classes("km-panel"):
        theme.title(t("transport.remove_vehicle_from_stable"), 2)
        ui.label(t("transport.disappears_from_stable_whoever", label=label))

        def go() -> None:
            STATE.archive.delete_stable_vehicle(entry["id"])
            STATE.record(t("transport.removed_from_stable", label=label), "map")
            dlg.close()
            theme.save_and_refresh()
            _propagate()

        with ui.row():
            ui.button(t("common.remove"), on_click=go).props("color=red")
            ui.button(t("common.cancel"), on_click=dlg.close).props("flat")
    dlg.open()


def _catalogue_dialog() -> None:
    """The catalogue, to choose what to put in the stable."""
    if not permissions.can(theme.user(), permissions.MANAGE_STABLE):
        theme.notify(t("transport.you_do_not_have"), "negative")
        return
    choice: dict = {"id": None}

    with theme.dialog() as dlg, ui.card().classes("km-panel") \
            .style("min-width:min(880px, 94vw);max-width:94vw"):
        theme.title(t("transport.vehicle_catalogue"), 2)
        ui.label(t("transport.transcribed_from_rules")) \
            .style("color:var(--km-muted);font-size:.78rem")

        rows = []
        for v in sorted(rules.VEHICLES, key=lambda x: (x["level"], x["name"])):
            best = travel_mod.best_vehicle_speed(v)
            rows.append({
                "id": v["id"], "name": v["name"], "level": v["level"],
                "price": v["price"], "size": v["size"],
                "crew": v["crew"], "passengers": v["passengers"],
                "speed": (f'{best[0]} {units.fmt(best[1])}'
                             if best else v["speed_text"]),
                "rarity": v["rarity"], "source": v["source"],
            })
        columns = [
            {"name": "name", "label": t("transport.vehicle"), "field": "name", "sortable": True,
             "align": "left"},
            {"name": "level", "label": t("transport.lvl"), "field": "level", "sortable": True},
            {"name": "speed", "label": t("transport.speed"), "field": "speed", "align": "left"},
            {"name": "crew", "label": t("transport.crew"), "field": "crew",
             "align": "left"},
            {"name": "passengers", "label": t("transport.pass"), "field": "passengers"},
            {"name": "price", "label": t("transport.price"), "field": "price", "align": "left"},
            {"name": "size", "label": t("transport.size"), "field": "size", "align": "left"},
        ]
        def chosen_one(e) -> None:
            choice["id"] = e.selection[0]["id"] if e.selection else None
            button.set_enabled(bool(choice["id"]))

        ui.table(columns=columns, rows=rows, row_key="id", pagination=12,
                 selection="single", on_select=chosen_one) \
            .classes("w-full km-panel").props("dense")

        def add() -> None:
            if not choice["id"]:
                return
            catalogue = rules.BY_ID["vehicle"][choice["id"]]
            STATE.archive.create_stable_vehicle({
                "id": uuid.uuid4().hex[:12],
                "campaign_id": STATE.campaign,
                "vehicle": choice["id"],
                "name": "",
                "available": 1,
                "speed_m": None,
                # From the catalogue, not «land» by habit: a Rowboat is born in
                # the Harbour. If the page does not say where it goes, the row
                # stays empty and the trade is decided by `vehicle_kind`.
                "kind": travel_mod.kind_from_catalogue(choice["id"]) or "",
                "note": "",
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            })
            STATE.record(t("transport.added_stable", name=catalogue["name"]), "map")
            dlg.close()
            theme.save_and_refresh()
            _propagate()
            list_transports.refresh()

        with ui.row().classes("justify-end w-full items-center"):
            ui.button(t("common.cancel"), on_click=dlg.close).props("flat")
            button = ui.button(t("transport.put_stable"), on_click=add).props("color=amber")
            button.set_enabled(False)
    dlg.open()


# ------------------------------------------------------------- images
def _image_box(entry: dict, field: str, label: str, side: int) -> None:
    """Image or marker of the vehicle: preview, upload, removal.

    Same trade as the characters' box, and same defences: the file name is
    regenerated by us, the content must really be an image, and the
    permission is checked again on upload — hiding the box is not a defence.
    """
    sid = entry["id"]
    badge = field == "token"
    with ui.column().classes("gap-1 items-center").style(f"width:{side}px"):
        ui.label(label).style("font-size:.72rem;color:var(--km-muted)")
        if entry.get(field):
            ui.image(vehicle_url(entry[field])).style(
                f'width:{side}px;height:{side}px;object-fit:cover;'
                f'border:2px solid var(--km-gold-dim);'
                f'border-radius:{"50%" if badge else "8px"}')
        else:
            ui.html(f'<div style="width:{side}px;height:{side}px;'
                    f'border-radius:{"50%" if badge else "8px"};background:#241d15;'
                    f'border:1px dashed var(--km-line);display:flex;'
                    f'align-items:center;justify-content:center;color:var(--km-muted);'
                    f'font-size:{side * 0.4:.0f}px">'
                    f'{travel_mod.vehicle_symbol(entry)}</div>')

        async def load(e: events.UploadEventArguments) -> None:
            await _load_image(sid, field, e)

        ui.upload(on_upload=load, auto_upload=True,
                  max_file_size=images.MAX_PORTRAIT_BYTES)             .props('accept=image/* flat dense').classes("w-full").style("max-width:100%")
        if entry.get(field):
            ui.button(t("common.remove"), icon="close",
                      on_click=lambda i=sid, c=field: _remove_image(i, c))                 .props("flat dense size=sm color=grey")


async def _load_image(sid: str, field: str,
                           e: events.UploadEventArguments) -> None:
    if not permissions.can(theme.user(), permissions.MANAGE_STABLE):
        theme.notify(t("transport.you_do_not_have"), "negative")
        return
    entry = STATE.archive.stable_vehicle(sid)
    if entry is None:
        return
    safe = images.safe_file_name(e.file.name)
    if safe is None:
        theme.notify(t("transport.png_jpg_gif_webp"), "negative")
        return
    name = images.unique_name(f"{sid}-{field}", safe[safe.rfind("."):])
    try:
        await images.accept(e.file, VEHICLE_FOLDER, name,
                               images.MAX_PORTRAIT_BYTES)
    except images.ImageRejected as reason:
        theme.notify(str(reason), "negative")
        return
    old_one = entry.get(field)
    STATE.archive.update_stable_vehicle(sid, **{field: name})
    images.delete(VEHICLE_FOLDER, old_one)
    list_transports.refresh()
    _propagate()


def _remove_image(sid: str, field: str) -> None:
    if not permissions.can(theme.user(), permissions.MANAGE_STABLE):
        theme.notify(t("transport.you_do_not_have"), "negative")
        return
    entry = STATE.archive.stable_vehicle(sid)
    if entry is None:
        return
    STATE.archive.update_stable_vehicle(sid, **{field: None})
    images.delete(VEHICLE_FOLDER, entry.get(field))
    list_transports.refresh()
    _propagate()
