"""Entry point of the application."""
from __future__ import annotations

import sqlite3
import time

from nicegui import ui
from nicegui.storage import Storage

from kingmaker.access import auth, permissions
from kingmaker import config, rules
from kingmaker.locale import i18n
from kingmaker.locale.i18n import t, tn
from kingmaker.state import STATE
from kingmaker.ui import login, hexmap, theme
from kingmaker.ui.tabs import city, party, creation, clock, gm_screen, sheet, transport, turn


@ui.refreshable
def header(user: auth.User | None = None) -> None:
    k = STATE.k
    with ui.row().classes("w-full items-center gap-3 flex-wrap") \
            .style("padding:10px 16px;background:linear-gradient(90deg,#1f1a14,#14110d);"
                   "border-bottom:1px solid var(--km-line)"):
        ui.html('<div class="km-title" style="font-size:1.4rem">👑 '
                f'{theme.esc(k["name"] or t("main.unnamed_kingdom"))}</div>')
        if k["created"]:
            gov = rules.BY_ID["government"].get(k["government"])
            if gov:
                ui.html(f'<span class="km-chip" style="font-size:.72rem">{theme.esc(gov["name"])}</span>')
            ui.element("div").style("flex:1")
            theme.stat_box(k["level"], t("main.level"), t("main.maximum_level_party", party_level=k["party_level"]))
            theme.stat_box(k["xp"], t("main.xp"), t("main.1_000_xp_gain"))
            theme.stat_box(STATE.size_, t("main.size"), STATE.size_entry()["kind"])
            theme.stat_box(STATE.control_dc, t("main.control_dc"))
            theme.stat_box(k["rp"], t("main.rp"))
            theme.stat_box(k["unrest"], t("main.unrest"),
                           t("main.status_penalty", unrest_penalty=rules.unrest_penalty(k["unrest"])))
            theme.stat_box(f'{k["fame_points"]}/{STATE.max_fame}',
                           t("main.fame") if k["reputation"] == "fame" else t("main.infamy"))
            theme.stat_box(k["turn"], t("main.turn"))
            clock.bar()
        else:
            ui.element("div").style("flex:1")
            ui.label(t("main.kingdom_not_founded_yet")).style("color:var(--km-muted)")
        if user is not None:
            login.user_bar(user)


theme.register_refresh("main.header", header)


@ui.page("/")
def page_() -> None:
    user = auth.current_user(STATE.archive)
    if user is None:
        ui.navigate.to("/login")
        return

    theme.apply_theme()
    # From here on the panels ask `theme.user()`, not the session: during a
    # redraw the session would answer with whoever acted last.
    theme.set_user(user)
    # And under which path they are looking at us: with On Air it is not the
    # root of the domain, and the addresses we write by hand must know it.
    request_ = getattr(ui.context.client, "request", None)
    theme.set_prefix(request_)
    # The language: what this person chose, else what the browser asks for,
    # else the server's default.
    theme.set_language(login.language_for(user, request_))
    theme.set_units(login.units_for(user))
    ui.page_title(t("app.title"))

    header(user)
    # Whoever wears someone else's clothes must not change their password: that
    # is chosen by the person who really owns the account, when they log in.
    if user.must_change_pw and not auth.is_impersonating():
        login.change_password_dialog(user, mandatory=True)

    if not STATE.k["created"]:
        with ui.column().classes("w-full").style("padding:16px;max-width:1100px;margin:0 auto"):
            creation.creation_page(at_end=lambda: ui.navigate.reload())
        return

    # The tab in the foreground decides which panels are worth redrawing when
    # the kingdom changes: the others wait to be reopened.
    # The tab names are language-neutral ids (`theme._TABS` and the ruler
    # compare against them); only the labels are translated.
    with ui.tabs(on_change=lambda e: theme.active_tab(e.value)).classes("w-full") as tabs:
        t_map = ui.tab("map", label=t("tabs.map"), icon="map")
        t_kingdom = ui.tab("kingdom", label=t("tabs.kingdom"), icon="shield")
        t_turn = ui.tab("turn", label=t("tabs.turn"), icon="event")
        t_city = ui.tab("city", label=t("tabs.city"), icon="location_city")
        t_party = ui.tab("party", label=t("tabs.party"), icon="groups")
        # Vehicles belong to the kingdom, not to a character: they sit next to
        # the Party, not inside it.
        t_stable = ui.tab("transport", label=t("tabs.transport"), icon="commute")
        t_data = ui.tab("manual", label=t("tabs.manual"), icon="menu_book")
        # The GM screen exists only for those allowed to see secrets: if the
        # panel is never even created, there is nothing to discover.
        t_gm = ui.tab("gm", label=t("tabs.gm"), icon="visibility") \
            if permissions.can(user, permissions.SEE_SECRETS) else None

    with ui.tab_panels(tabs, value=t_map).classes("w-full").style("background:transparent"):
        with ui.tab_panel(t_map):
            hexmap.map_panel()
        with ui.tab_panel(t_kingdom):
            sheet.sheet_panel()
        with ui.tab_panel(t_turn):
            turn.turn_panel()
        with ui.tab_panel(t_city):
            city.city_panel()
        with ui.tab_panel(t_party):
            party.party_panel()
        with ui.tab_panel(t_stable):
            transport.transport_panel()
        with ui.tab_panel(t_data):
            manual_panel(user)
        if t_gm is not None:
            with ui.tab_panel(t_gm):
                gm_screen.gm_panel()

    theme.active_tab("map")


def manual_panel(user: auth.User) -> None:
    """Quick reference: structures, activities, feats, tables."""
    with ui.tabs().classes("w-full") as sub:
        s1 = ui.tab(t("main.structures"))
        s2 = ui.tab(t("main.activities"))
        s3 = ui.tab(t("main.feats"))
        s4 = ui.tab(t("main.tables"))
    with ui.tab_panels(sub, value=s1).classes("w-full").style("background:transparent"):
        with ui.tab_panel(s1):
            _structures_table()
        with ui.tab_panel(s2):
            _activity_list()
        with ui.tab_panel(s3):
            sheet.feats_block()
        with ui.tab_panel(s4):
            _tables(user)


def _structures_table() -> None:
    rows = [{
        "name": s["name"], "level": s["level"], "lots": s["lots"],
        "traits": ", ".join(s["traits"]), "cost": s["cost_raw"],
        "construction": s["construction"]["raw"] if s["construction"] else "—",
        "bonus": s["item_bonus"] or "—",
        "effects": s["effects"] or "—",
    } for s in rules.STRUCTURES]
    columns = [
        {"name": "name", "label": t("main.structure"), "field": "name", "sortable": True, "align": "left"},
        {"name": "level", "label": t("main.lvl"), "field": "level", "sortable": True},
        {"name": "lots", "label": t("main.lots"), "field": "lots", "sortable": True},
        {"name": "traits", "label": t("main.traits"), "field": "traits", "align": "left"},
        {"name": "cost", "label": t("main.cost"), "field": "cost", "align": "left"},
        {"name": "construction", "label": t("main.construction"), "field": "construction", "align": "left"},
        {"name": "bonus", "label": t("main.item_bonus"), "field": "bonus", "align": "left"},
    ]
    table = ui.table(columns=columns, rows=rows, row_key="name", pagination=25) \
        .classes("w-full km-panel")
    table.add_slot("body", r'''
        <q-tr :props="props">
          <q-td v-for="col in props.cols" :key="col.name" :props="props">{{ col.value }}</q-td>
        </q-tr>
        <q-tr v-if="props.row.effetti !== '—'" :props="props">
          <q-td colspan="100%" style="color:#a2957c;font-size:.78rem;white-space:normal">
            {{ props.row.effetti }}
          </q-td>
        </q-tr>
    ''')


def _activity_list() -> None:
    for phase in rules.TURN_PHASES:
        for step in phase["steps"]:
            atts = rules.activities_for_step(phase["id"], step["id"])
            if not atts:
                continue
            with ui.expansion(t("main.text", name=phase["name"], name2=step["name"])).classes("km-panel w-full"):
                for a in atts:
                    with ui.card().classes("km-panel w-full"):
                        with ui.row().classes("items-center gap-2 flex-wrap"):
                            ui.html(f'<b class="km-title">{theme.esc(a["name"])}</b>')
                            for trait in a["traits"]:
                                ui.html(f'<span class="km-chip" style="font-size:.65rem">{trait}</span>')
                            ui.button(icon="casino", on_click=lambda x=a: turn.run_activity(x)) \
                                .props("dense flat round color=amber")
                        if a["requirements"]:
                            ui.markdown(t("main.requirements", requirements=a["requirements"])).style("font-size:.82rem")
                        if a["cost"]:
                            ui.markdown(t("main.cost_2", cost=a["cost"])).style("font-size:.82rem")
                        ui.markdown(a["description"]).style("font-size:.85rem")
                        turn.outcomes_block(a)


def _download() -> None:
    """The save holds the whole campaign: the permission is checked again here.

    Hiding the button is not a defence: whoever knows the event could fire it
    all the same.
    """
    who = auth.current_user(STATE.archive)
    if not permissions.can(who, permissions.EXPORT_SAVE):
        theme.notify(t("main.you_do_not_have"), "negative")
        return
    STATE.record(t("main.downloaded_save", username=who.username), "account")
    theme.mark_dirty()
    ui.download.content(STATE.export(), "kingdom.json")


def _tables(user: auth.User) -> None:
    with ui.row().classes("w-full items-start gap-4 flex-wrap"):
        with ui.card().classes("km-panel"):
            theme.title(t("main.kingdom_size"), 2)
            ui.table(
                columns=[{"name": k, "label": lab, "field": k}
                         for k, lab in (("dim", t("main.size")), ("kind", t("main.nation_type")),
                                        ("die", t("main.resource_die")), ("dc", t("main.control_dc_mod")),
                                        ("mag", t("main.storage")))],
                rows=[{"dim": f'{v["min"]}–{v["max"] if v["max"] < 1000 else "+"}', "kind": v["kind"],
                       "die": f'1d{v["die"]}', "dc": f'+{v["dc_mod"]}', "mag": v["storage"]}
                      for v in rules.KINGDOM["size_table"]]).props("dense flat")
        with ui.card().classes("km-panel"):
            theme.title(t("main.settlement_types"), 2)
            ui.table(
                columns=[{"name": k, "label": lab, "field": k}
                         for k, lab in (("name", t("main.settlement")), ("blocks", t("main.blocks")),
                                        ("pop", t("main.population")), ("liv", t("main.level")),
                                        ("cons", t("city.consumption")), ("bo", t("main.max_item_bonus_short")),
                                        ("inf", t("city.influence")))],
                rows=[{"name": t("main.settlement_level", name=st["name"], level=st["kingdom_level"]), "blocks": st["blocks"],
                       "pop": st["population"], "liv": st["level"], "cons": st["consumption"],
                       "bo": f'+{st["item_bonus_max"]}', "inf": st["influence"]}
                      for st in rules.SETTLEMENT_TYPES]).props("dense flat")
        with ui.card().classes("km-panel"):
            theme.title(t("main.kingdom_levels"), 2)
            ui.table(
                columns=[{"name": "liv", "label": t("main.lvl"), "field": "liv"},
                         {"name": "dc", "label": t("main.control_dc"), "field": "dc"},
                         {"name": "cap", "label": t("main.capabilities"), "field": "cap", "align": "left"}],
                rows=[{"liv": v["level"], "dc": v["control_dc"], "cap": ", ".join(v["capabilities"])}
                      for v in rules.KINGDOM["level_table"]], pagination=20).props("dense flat")
        with ui.card().classes("km-panel"):
            theme.title(t("main.milestone_xp_awards"), 2)
            ui.table(columns=[{"name": "xp", "label": t("main.xp"), "field": "xp"},
                              {"name": "d", "label": t("main.milestone"), "field": "d", "align": "left"},
                              {"name": "ok", "label": t("main.achieved"), "field": "ok"}],
                     rows=[{"xp": m["xp"], "d": m["desc"],
                            "ok": "✔" if m["id"] in STATE.k["milestones"] else ""}
                           for m in rules.MILESTONE_XP]).props("dense flat")
        with ui.card().classes("km-panel"):
            theme.title(t("main.building_rugged_terrain"), 2)
            ui.table(columns=[{"name": "t", "label": t("main.terrain"), "field": "t", "align": "left"},
                              {"name": "rp", "label": t("main.rp"), "field": "rp"}],
                     rows=[{"t": terr["name"], "rp": terr["rp_cost"]} for terr in rules.TERRAINS
                           if not terr.get("legacy")]).props("dense flat")
        with ui.card().classes("km-panel").style("max-width:520px"):
            theme.title(t("main.terrain_features"), 2)
            for e in rules.HEX_FEATURES:
                # What does not come from the wiki says so here, where one reads
                # what it does: this is where one checks whether a thing is a rule.
                mark = t("main.table_addition") if e.get("source") == "table" else ""
                ui.markdown(t("main.text_2", icon=e["icon"], name=e["name"], mark=mark, desc=e["desc"]))                     .style("font-size:.8rem")
        with ui.card().classes("km-panel").style("max-width:520px"):
            theme.title(t("main.borders_between_hexes"), 2)
            borders = rules.TRAVEL["borders"]
            ui.markdown(t("main.no_border_marked_land"))                 .style("font-size:.8rem")
            for entry in borders["kinds"].values():
                cost = entry.get("extra_activities") or 0
                extra = (t("main.travel_activities", cost=cost) if cost else "")
                ui.markdown(t("main.table_addition_2", icon=entry["icon"], name=entry["name"], extra=extra, note=entry["note"]))                     .style("font-size:.8rem")
            # The note lives here and not in a code comment: this is where one
            # comes to check whether a thing is a rule or not.
            ui.markdown(borders["_note"]).style("font-size:.75rem;color:var(--km-gold-dim)")

    theme.sep()
    with ui.card().classes("km-panel w-full"):
        theme.title(t("main.data_save_file"), 2)
        ui.label(t("main.save_file", path=STATE.archive.path)) \
            .style("color:var(--km-muted);font-size:.8rem")
        ui.label(t("main.rules_source_pf2_altervista")) \
            .style("color:var(--km-muted);font-size:.8rem")
        if user.can(permissions.EXPORT_SAVE):
            with ui.row().classes("items-center gap-2 flex-wrap"):
                ui.button(t("main.download_database"), icon="save",
                          on_click=_download_database) \
                    .props("dense color=amber") \
                    .tooltip(t("main.download_database_tooltip"))
                ui.button(t("main.download_json_save"), on_click=_download) \
                    .props("dense outline color=amber") \
                    .tooltip(t("main.whole_campaign_gm_notes"))
                ui.button(t("main.start_over_from_scratch"),
                          on_click=lambda: _confirm_reset(user)) \
                    .props("dense flat color=red")
            if user.can(permissions.RESET_KINGDOM):
                ui.upload(label=t("main.load_database"), on_upload=_load_database,
                          auto_upload=True, max_file_size=MAX_SAVE_BYTES) \
                    .props("accept=.db,.sqlite,.bak dense").classes("w-full")
        else:
            ui.label(t("main.save_can_downloaded_reset")).style("color:var(--km-muted);font-size:.78rem")


MAX_SAVE_BYTES = 512 * 1024 * 1024
BACKUP_FOLDER = "backups"


def _download_database() -> None:
    """A complete copy of the database, written next to the save and sent."""
    who = auth.current_user(STATE.archive)
    if not permissions.can(who, permissions.EXPORT_SAVE):
        theme.notify(t("main.you_do_not_have"), "negative")
        return
    stamp = time.strftime("%Y%m%d-%H%M%S")
    name = f"kingmaker-{stamp}.db"
    path = STATE.archive.backup_to(config.DATA_DIR / BACKUP_FOLDER / name)
    STATE.record(t("main.downloaded_database", username=who.username), "account")
    theme.mark_dirty()
    ui.download.file(path, name)


async def _load_database(event) -> None:
    """An uploaded save: looked at first, then replaced only on confirmation."""
    who = auth.current_user(STATE.archive)
    if not permissions.can(who, permissions.RESET_KINGDOM):
        theme.notify(t("main.you_do_not_have_4"), "negative")
        return
    file = event.file
    if file.size() > MAX_SAVE_BYTES:
        theme.notify(t("main.file_too_large", mb=MAX_SAVE_BYTES // (1024 * 1024)), "negative")
        return
    folder = config.DATA_DIR / BACKUP_FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = folder / f"uploaded-{stamp}.db"
    path.write_bytes(await file.read())
    try:
        info = STATE.archive.inspect(path)
    except ValueError as exc:
        key, params = (exc.args + ({},))[:2]
        theme.notify(t("main.not_a_save", reason=t(key, **params)), "negative")
        path.unlink(missing_ok=True)
        return
    except (OSError, sqlite3.Error) as exc:
        theme.notify(t("main.not_a_save", reason=str(exc)), "negative")
        path.unlink(missing_ok=True)
        return

    with theme.dialog() as dlg, ui.card().classes("km-panel").style("max-width:520px"):
        theme.title(t("main.restore_title"), 2)
        ui.label(t("main.restore_details", name=file.name, version=info["version"],
                   kingdom=info["kingdom"] or "?", users=info["users"],
                   v=tn("main.restore_accounts", info["users"]))) \
            .style("color:var(--km-gold);font-size:.85rem")
        ui.label(t("main.restore_warning")).style("white-space:normal;font-size:.82rem")

        def go() -> None:
            if not permissions.can(auth.current_user(STATE.archive), permissions.RESET_KINGDOM):
                theme.notify(t("main.you_do_not_have_4"), "negative")
                return
            kept = STATE.restore(path)
            STATE.record(t("main.restored_log", username=who.username, name=file.name), "account")
            theme.save_and_refresh()
            theme.notify(t("main.restored", name=file.name, keep=kept.name), "positive")
            dlg.close()
            ui.navigate.reload()

        with ui.row():
            ui.button(t("main.restore_button"), on_click=go).props("color=red")
            ui.button(t("common.cancel"), on_click=dlg.close).props("flat")
    dlg.open()


def _confirm_reset(user: auth.User) -> None:
    if not permissions.can(user, permissions.RESET_KINGDOM):
        theme.notify(t("main.you_do_not_have_2"), "negative")
        return
    with theme.dialog() as dlg, ui.card().classes("km-panel"):
        theme.title(t("main.start_over_from_scratch_2"), 2)
        ui.label(t("main.everything_belonging_game_will"))

        def go() -> None:
            if not permissions.can(auth.current_user(STATE.archive), permissions.RESET_KINGDOM):
                theme.notify(t("main.you_do_not_have_3"), "negative")
                return
            STATE.reset()
            dlg.close()
            ui.navigate.reload()

        with ui.row():
            ui.button(t("main.erase_everything"), on_click=go).props("color=red")
            ui.button(t("common.cancel"), on_click=dlg.close).props("flat")
    dlg.open()


def start(host: str = "127.0.0.1", port: int = 8080, show: bool = True,
          online: str | bool | None = None) -> None:
    """`online=True` publishes the game on the internet with NiceGUI On Air.

    Traffic goes through a nicegui.io relay and reaches this PC, which must stay
    on. Without a token the address changes at every start; with a free token
    from https://nicegui.io/on_air it stays the same.
    """
    # Browser sessions go with the data, not with the folder you launched the
    # command from: otherwise starting the app from another folder would log
    # everyone out for no apparent reason.
    Storage.path = config.DATA_DIR / "sessions"
    Storage.path.mkdir(parents=True, exist_ok=True)
    config.ON_AIR = bool(online)
    _first_start()
    # Behind HTTPS the session cookie must never travel in the clear.
    cookie = {"https_only": True, "same_site": "lax"} if config.HTTPS else None
    ui.run(host=host, port=port, title="Kingmaker Kingdom Manager",
           favicon="👑", dark=True, show=show, reload=False,
           storage_secret=config.storage_secret(), on_air=online,
           session_middleware_kwargs=cookie)


def _first_start() -> None:
    """If there is no account yet, creates one and prints the password."""
    password = auth.ensure_admin(STATE.archive)
    if password is None:
        return
    print()
    print("=" * 64)
    print("  First start: the administrator account has been created.")
    print("      username:  admin")
    print(f"      password:  {password}")
    print("  It is shown only now, so write it down. At the first login you will")
    print("  be asked to change it, and from there you can create the other accounts.")
    print("=" * 64)
    print()
