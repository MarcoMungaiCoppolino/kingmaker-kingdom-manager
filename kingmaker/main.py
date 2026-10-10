"""Entry point of the application."""
from __future__ import annotations

import hmac
import json
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

from fastapi import Request, Response
from nicegui import app, run, ui
from nicegui.storage import Storage

from kingmaker.access import auth, pairing, permissions
from kingmaker import __version__, config, rules
from kingmaker.locale import i18n
from kingmaker.locale.i18n import t, tn
from kingmaker.state import STATE
from kingmaker.storage import bundle
from kingmaker.ui import login, hexmap, theme
from kingmaker.ui.tabs import city, party, creation, clock, gm_screen, sheet, transport, turn


@ui.refreshable
def header(user: auth.User | None = None) -> None:
    k = STATE.k
    with ui.row().classes("w-full items-center gap-3 flex-wrap") \
            .style("padding:10px 16px;background:linear-gradient(90deg,#1f1a14,#14110d);"
                   "border-bottom:1px solid var(--km-line)"):
        # The `ui.html` element is a flex item of the header row: without a
        # width of its own the name wrapped under the crest.
        ui.html(f'<div class="km-title" style="font-size:1.4rem;display:flex;align-items:center;'
                f'gap:8px;white-space:nowrap">{theme.crest(30, margin="0")}'
                f'<span>{theme.esc(k["name"] or t("main.unnamed_kingdom"))}</span></div>')
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
    # The disguise too, for the same reason: the header's user bar reads it
    # from here, never from the session of whoever happens to act.
    theme.window_state()["real_id"] = auth.real_id()
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
            # The game of another PC, or of the time before the installer:
            # nothing to redo, load its file.
            if user.can(permissions.RESET_KINGDOM):
                with ui.card().classes("km-panel w-full"):
                    theme.title(t("main.have_save_title"), 2)
                    ui.label(t("main.have_save_text")).style("color:var(--km-muted);font-size:.85rem")
                    save_upload()
        return

    # The tab in the foreground decides which panels are worth redrawing when
    # the kingdom changes: the others wait to be reopened.
    # The tab names are language-neutral ids (`theme._TABS` and the ruler
    # compare against them); only the labels are translated.
    # In a narrow window the tabs do not fit: they scroll, and the arrows say
    # so (`mobile-arrows` shows them on touch screens too).
    with ui.tabs(on_change=lambda e: theme.active_tab(e.value)).classes("w-full") \
            .props("mobile-arrows outside-arrows") as tabs:
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
        # The save: download, load, start over. Administrators only, and
        # like the GM screen the panel is not even built for the others.
        t_save = ui.tab("save", label=t("tabs.save"), icon="download") \
            if permissions.can(user, permissions.EXPORT_SAVE) else None

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
        if t_save is not None:
            with ui.tab_panel(t_save):
                save_panel(user)

    theme.active_tab("map")


def manual_panel(user: auth.User) -> None:
    """Quick reference: structures, activities, feats, tables."""
    with ui.tabs().classes("w-full").props("mobile-arrows outside-arrows") as sub:
        s1 = ui.tab(t("main.structures"))
        s2 = ui.tab(t("main.activities"))
        s3 = ui.tab(t("main.feats"))
        s4 = ui.tab(t("main.tables"))
        s5 = ui.tab(t("main.privacy"))
    with ui.tab_panels(sub, value=s1).classes("w-full").style("background:transparent"):
        with ui.tab_panel(s1):
            _structures_table()
        with ui.tab_panel(s2):
            _activity_list()
        with ui.tab_panel(s3):
            sheet.feats_block()
        with ui.tab_panel(s4):
            _tables(user)
        with ui.tab_panel(s5):
            _privacy_page()


def _privacy_page() -> None:
    """What the app keeps, what leaves the host's PC and to whom, and the
    licences: the same notice as PRIVACY.md, where every player can read it
    without leaving the game."""
    with ui.card().classes("km-panel w-full").style("max-width:900px"):
        ui.markdown(t("main.privacy_text")).style("font-size:.9rem;line-height:1.5")
        ui.label(t("main.privacy_version", version=__version__)) \
            .style("color:var(--km-muted);font-size:.8rem")


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
    ui.label(t("main.rules_source_pf2_altervista")) \
        .style("color:var(--km-muted);font-size:.8rem")


MAX_SAVE_BYTES = 512 * 1024 * 1024
BACKUP_FOLDER = "backups"


def save_panel(user: auth.User) -> None:
    """The Save tab: the whole game in one file, out and in, and the reset."""
    with ui.column().classes("w-full").style("max-width:760px;margin:0 auto"):
        with ui.card().classes("km-panel w-full"):
            theme.title(t("main.save_title"), 2)
            ui.label(t("main.save_intro")).style("white-space:normal;font-size:.85rem")
            ui.button(t("main.download_everything"), icon="download",
                      on_click=_download_bundle).props("color=amber") \
                .tooltip(t("main.download_everything_tooltip"))
            ui.label(t("main.save_file", path=STATE.archive.path)) \
                .style("color:var(--km-muted);font-size:.78rem")
        with ui.card().classes("km-panel w-full"):
            theme.title(t("main.load_title"), 2)
            ui.label(t("main.load_intro")).style("white-space:normal;font-size:.85rem")
            if user.can(permissions.RESET_KINGDOM):
                save_upload()
        with ui.card().classes("km-panel w-full"):
            theme.title(t("main.start_over_from_scratch"), 2)
            ui.label(t("main.reset_intro")).style("white-space:normal;font-size:.85rem")
            ui.button(t("main.start_over_from_scratch"), icon="delete_forever",
                      on_click=lambda: _confirm_reset(user)).props("flat color=red")


def save_upload() -> None:
    """The «Load a save» control: in the Save tab, and on the creation page
    for whoever arrives with a game already played elsewhere."""
    ui.upload(label=t("main.load_database"), on_upload=_load_database,
              auto_upload=True, max_file_size=MAX_SAVE_BYTES) \
        .props("accept=.zip,.db,.sqlite,.bak dense").classes("w-full")


def _download_bundle() -> None:
    """Everything in one zip — database, kingdom as JSON, images — written
    next to the save and sent."""
    who = auth.current_user(STATE.archive)
    if not permissions.can(who, permissions.EXPORT_SAVE):
        theme.notify(t("main.you_do_not_have"), "negative")
        return
    stamp = time.strftime("%Y%m%d-%H%M%S")
    name = f"kingmaker-{stamp}.zip"
    path = bundle.write(STATE.archive, STATE.export(), config.ASSETS_DIR,
                        config.DATA_DIR / BACKUP_FOLDER / name)
    STATE.record(t("main.downloaded_database", username=who.username), "account")
    theme.mark_dirty()
    ui.download.file(path, name)


async def _load_database(event) -> None:
    """An uploaded save, a zip or a bare database: looked at first, then
    replaced only on confirmation."""
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
    suffix = ".zip" if str(file.name).lower().endswith(".zip") else ".db"
    path = folder / f"uploaded-{stamp}{suffix}"
    path.write_bytes(await file.read())
    try:
        info = bundle.inspect(path)
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
                   v=tn("main.restore_accounts", info["users"]),
                   images=tn("main.restore_images", info["assets"]))) \
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
    from https://on-air.nicegui.io it stays the same.
    """
    # Browser sessions go with the data, not with the folder you launched the
    # command from: otherwise starting the app from another folder would log
    # everyone out for no apparent reason.
    Storage.path = config.DATA_DIR / "sessions"
    Storage.path.mkdir(parents=True, exist_ok=True)
    config.ON_AIR = bool(online)
    _first_start()
    app.on_startup(lambda: _announce_ready(host, port))
    launcher_route(os.environ.get(LAUNCHER_SECRET_VARIABLE, "").strip(),
                   os.environ.get(SYNC_CREDENTIAL_VARIABLE, "").strip(),
                   sign_seed=os.environ.get(LAUNCHER_SIGN_VARIABLE, "").strip(),
                   launcher_id=os.environ.get(LAUNCHER_ID_VARIABLE, "").strip())
    # Behind HTTPS the session cookie must never travel in the clear.
    cookie = {"https_only": True, "same_site": "lax"} if config.HTTPS else None
    ui.run(host=host, port=port, title="Kingmaker Kingdom Manager",
           favicon=str(theme.CREST_FILE), dark=True, show=show, reload=False,
           storage_secret=config.storage_secret(), on_air=online,
           session_middleware_kwargs=cookie)


LAUNCHER_SECRET_VARIABLE = "KINGMAKER_LAUNCHER_SECRET"
SYNC_CREDENTIAL_VARIABLE = "KINGMAKER_SYNC_CREDENTIAL"
# The hosting launcher's signing seed and id: with them the game vouches
# for a newcomer at pairing (`sync.make_admission`), in the launcher's name.
LAUNCHER_SIGN_VARIABLE = "KINGMAKER_LAUNCHER_SIGN"
LAUNCHER_ID_VARIABLE = "KINGMAKER_LAUNCHER_ID"
# The paths the launcher uses; `login.OPEN_PAGES` lists them so the access
# middleware lets them through to their own checks.
LAUNCHER_PATHS = ("/_launcher/shutdown", "/_launcher/status", "/_launcher/snapshot",
                  "/_launcher/synced", "/_launcher/whoami", "/_launcher/pairing",
                  "/_launcher/pair", "/_launcher/credential")


def launcher_route(secret: str, credential_json: str = "", sign_seed: str = "",
                   launcher_id: str = "") -> None:
    """The routes for the launcher, registered only when it started us.

    A signal cannot reach a child without a console — and the installed app
    has none — so the launcher asks over HTTP instead, with a secret it made
    up for this start and passed in the environment. Wrong secret, or a
    caller that is not this machine: 404, as if the route did not exist.
    Without a secret none of the local routes is registered at all.

    - `POST /_launcher/shutdown`: stop, the last save written.
    - `GET /_launcher/status`: `{"rev"}`, so the launcher knows when the game
      changed without asking for a copy.
    - `POST /_launcher/snapshot`: a database-only bundle (`bundle.write_snapshot`),
      what the launcher uploads to the cloud; `?epoch=&seq=` go in its manifest.
    - `POST /_launcher/synced`: `{"epoch","seq"}` recorded in `meta`, so the
      database itself knows which cloud copy it matches.
    - `GET /_launcher/whoami?nonce=<hex>`: open to the network, from anywhere:
      `{"proof": HMAC-SHA256(secret, nonce), "app"}`. The launcher asks it
      through the table's public address and knows whether the program that
      answers there is this server; it reveals nothing, the secret being
      this start's alone.
    - `POST /_launcher/pairing`: local, with the secret: a fresh pairing code
      (`access.pairing`), the launcher's own door to the same thing the
      accounts dialog does in the game.
    - `POST /_launcher/pair`: the other route open to the network — the
      launcher of a new host sends `{"code","host_name"}` and, for the right
      code while it lives, receives the cloud credential this server was
      given at start, once. Never registered without one. A wrong, used or
      expired code, or the table's brake for everyone: 404.
    - `POST /_launcher/credential`: the hand-out of 1.x, answered with 410.
    """
    if not secret:
        return

    def _local(request: Request) -> bool:
        client = request.client.host if request.client else ""
        offered = request.headers.get("x-launcher-secret", "")
        return client in ("127.0.0.1", "::1") and hmac.compare_digest(offered, secret)

    @app.post("/_launcher/shutdown")
    async def _shutdown(request: Request) -> Response:
        if not _local(request):
            return Response(status_code=404)
        app.shutdown()
        return Response(status_code=204)

    @app.get("/_launcher/status")
    async def _status(request: Request) -> Response:
        if not _local(request):
            return Response(status_code=404)
        return Response(json.dumps({"rev": STATE.archive.rev, "kingdom": STATE.k.get("name") or "",
                                    "synced": synced_marks()}),
                        media_type="application/json")

    @app.post("/_launcher/snapshot")
    async def _snapshot(request: Request) -> Response:
        if not _local(request):
            return Response(status_code=404)
        marks = {}
        for key in ("epoch", "seq"):
            value = request.query_params.get(key)
            if value is not None and value.isdigit():
                marks[key] = int(value)
        theme.write_to_disk()
        with tempfile.TemporaryDirectory(prefix="km-snap-") as tmp:
            target = bundle.write_snapshot(STATE.archive, config.ASSETS_DIR,
                                           Path(tmp) / "snapshot.zip", marks)
            data = target.read_bytes()
        return Response(data, media_type="application/zip",
                        headers={"X-Kingmaker-Rev": str(STATE.archive.rev)})

    @app.post("/_launcher/synced")
    async def _synced(request: Request) -> Response:
        if not _local(request):
            return Response(status_code=404)
        try:
            payload = json.loads((await request.body()).decode("utf-8") or "{}")
            epoch, seq = int(payload["epoch"]), int(payload["seq"])
        except (ValueError, KeyError, TypeError):
            return Response(status_code=400)
        # The document's revision travels with the marks: at the next start
        # the launcher compares it with the one the file has, and knows a
        # copy that fell behind the cloud from one that was played on since.
        STATE.archive.write_meta("sync_marks", json.dumps(
            {"epoch": epoch, "seq": seq, "krev": int(STATE.k.get("_rev", 0))}))
        return Response(status_code=204)

    @app.get("/_launcher/whoami")
    async def _whoami(request: Request) -> Response:
        nonce = str(request.query_params.get("nonce", ""))[:64]
        if not nonce or any(c not in "0123456789abcdef" for c in nonce):
            return Response(status_code=404)
        proof = hmac.new(secret.encode("utf-8"), nonce.encode("ascii"), "sha256").hexdigest()
        return Response(json.dumps({"proof": proof, "app": __version__}),
                        media_type="application/json")

    credential = None
    if credential_json:
        try:
            credential = json.loads(credential_json)
        except ValueError:
            credential = None
    if not isinstance(credential, dict) or not credential:
        return

    @app.post("/_launcher/credential")
    async def _credential(request: Request) -> Response:
        # The hand-out of 1.x — a game password for the credential — is gone:
        # a launcher of that age gets a 410 and shows its "refused" sentence,
        # and the guide says to update. Removed for good in 3.0.
        return Response(json.dumps({"error": "update-launcher"}), status_code=410,
                        media_type="application/json")

    @app.post("/_launcher/pairing")
    async def _pairing(request: Request) -> Response:
        """A code for the launcher that started us (local, with the secret):
        the administrator's launcher offers it too, the accounts dialog in
        the game being the usual place."""
        if not _local(request):
            return Response(status_code=404)
        code = pairing.new_code("launcher")
        STATE.record(t("login.pair_made", username=t("main.the_launcher")), "account")
        theme.mark_dirty()
        return Response(json.dumps({"code": code, "expires_in": pairing.LIFETIME}),
                        media_type="application/json")

    @app.post("/_launcher/pair")
    async def _pair(request: Request) -> Response:
        """Open to the network: `{"code","host_name"}` → the credential, once,
        for the right code while it lives. Everything wrong is a 404, and
        the table's brake for everyone applies here too."""
        try:
            payload = json.loads((await request.body()).decode("utf-8") or "{}")
            code, host_name = str(payload["code"]), str(payload.get("host_name", ""))[:80]
            new_id, new_key = str(payload.get("host_id", ""))[:32], str(payload.get("key", ""))[:64]
        except (ValueError, KeyError, TypeError):
            return Response(status_code=404)
        if auth.global_wait() > 0 or not pairing.check(code):
            return Response(status_code=404)
        # The admission: the newcomer's id and key, signed with the hosting
        # launcher's seed, so every launcher of the table can tell the
        # newcomer's copies from a key thief's. Without a seed (a launcher
        # from before the signatures) the credential goes out alone.
        admission = None
        if sign_seed and launcher_id and new_id and new_key:
            from kingmaker.launcher import sync
            try:
                admission = sync.make_admission(bytes.fromhex(sign_seed), launcher_id, new_id,
                                                host_name, new_key)
            except ValueError:
                admission = None
        STATE.record(t("main.launcher_paired", host=host_name or "?"), "account")
        theme.mark_dirty()
        return Response(json.dumps({"credential": credential, "table_id": credential.get("table_id", ""),
                                    "table": credential.get("table", ""),
                                    "kingdom": STATE.k.get("name") or "",
                                    "admission": admission}),
                        media_type="application/json")


class _Caller:
    """What `auth.client_ip` expects — the shape of a NiceGUI client — built
    from a plain FastAPI request."""

    def __init__(self, request: Request) -> None:
        self.request = request
        self.ip = request.client.host if request.client else None


def synced_marks() -> dict:
    """The `(epoch, seq)` of the cloud copy this database matches, or {}."""
    raw = STATE.archive.read_meta("sync_marks")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return {"epoch": int(data["epoch"]), "seq": int(data["seq"]),
                "krev": int(data.get("krev") or 0)}
    except (ValueError, KeyError, TypeError):
        return {}


def announce(kind: str, value: str) -> None:
    """One line for the launcher: `KM <kind> <value>`, on stdout, flushed.

    The launcher (`kingmaker.launcher`) starts the server as a child process
    and reads its output: these lines are the contract, the human text around
    them is free to change. Without a stdout (the installed app started by a
    double click, not by the launcher) there is nobody to tell.
    """
    if sys.stdout is None:
        return
    print(f"KM {kind} {value}", flush=True)


def _announce_ready(host: str, port: int) -> None:
    announce("ready", f"http://127.0.0.1:{port}")
    if host == "0.0.0.0":
        for address in lan_addresses():
            announce("lan", f"http://{address}:{port}")


def lan_addresses() -> list[str]:
    """The IPv4 addresses of this machine, without the loopback: what the
    others on the network type in their browser."""
    try:
        import ifaddr
    except ImportError:       # a NiceGUI dependency, but not a promise
        return []
    found = []
    for adapter in ifaddr.get_adapters():
        for ip in adapter.ips:
            address = str(ip.ip)
            # Loopback and link-local (169.254: an adapter with no network)
            # are no use to anyone; the home-network ranges come first.
            if ip.is_IPv4 and not address.startswith(("127.", "169.254.")):
                found.append(address)
    rank = {"192.168.": 0, "10.": 1}
    found.sort(key=lambda a: next((r for p, r in rank.items() if a.startswith(p)), 2))
    return found


def _first_start() -> None:
    """If there is no account yet, creates one and prints the password."""
    password = auth.ensure_admin(STATE.archive)
    if password is None:
        return
    if not os.environ.get(LAUNCHER_SECRET_VARIABLE, "").strip():
        # Started by hand: the console is the one place to read it. Under
        # the launcher a dialog shows it, and the log pane must not keep it.
        print()
        print("=" * 64)
        print("  First start: the administrator account has been created.")
        print("      username:  admin")
        print(f"      password:  {password}")
        print("  It is shown only now, so write it down. At the first login you will")
        print("  be asked to change it, and from there you can create the other accounts.")
        print("=" * 64)
        print()
    announce("admin-password", password)
