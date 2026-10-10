"""GM screen: the operations that apply to the whole map.

A single hex is governed from the Map tab, in the «GM» box next to its
details: switching tab to reveal one hex at a time was inconvenient. Here
remain the overview, the queue of what you prepared and the commands touching
the whole map.
"""
from __future__ import annotations

from nicegui import ui

from kingmaker.access import permissions
from kingmaker import rules
from kingmaker.state import STATE
from kingmaker.ui import hexmap, theme
from kingmaker.locale.i18n import t


def gm_panel() -> None:
    if not permissions.can(theme.user(), permissions.SEE_SECRETS):
        with ui.card().classes("km-panel w-full"):
            ui.label(t("gm_screen.this_section_reserved_game")) \
                .style("color:var(--km-muted)")
        return

    with ui.column().classes("w-full gap-3").style("max-width:780px"):
        _summary()
        _to_reveal()


@ui.refreshable
def _summary() -> None:
    prepared = len(STATE.k["hexes"])
    visible_ones = STATE.archive.count_visible(STATE.campaign)
    with ui.card().classes("km-panel w-full"):
        theme.title(t("gm_screen.gm_screen"), 2)
        ui.label(t("gm_screen.prepare_map_advance_reveal")) \
            .style("color:var(--km-muted);font-size:.8rem")
        ui.label(t("gm_screen.work_single_hex_go")) \
            .style("color:var(--km-gold-dim);font-size:.78rem")
        with ui.row().classes("gap-2 flex-wrap items-center"):
            theme.stat_box(prepared, t("gm_screen.hexes_prepared"))
            theme.stat_box(visible_ones, t("gm_screen.revealed_party"))
            theme.stat_box(max(0, prepared - visible_ones), t("gm_screen.still_secret"))
        with ui.row().classes("gap-2 flex-wrap"):
            ui.button(t("gm_screen.reveal_all_explored"), on_click=_reveal_explored) \
                .props("dense outline color=amber") \
                .tooltip(t("gm_screen.every_hex_that_no"))
            ui.button(t("gm_screen.hide_everything"), on_click=_confirm_hide_all) \
                .props("dense flat color=red")


@ui.refreshable
def _to_reveal() -> None:
    """The hexes you already worked on but the party does not see yet."""
    visible_ones = STATE.archive.visible_to_party(STATE.campaign)
    secrets = [e for e in STATE.k["hexes"].values()
               if (e["col"], e["row"]) not in visible_ones
               and (e.get("terrains") or e.get("features") or e.get("name")
                    or e["status"] != "unknown")]
    with ui.card().classes("km-panel w-full km-scroll").style("max-height:56vh"):
        theme.title(t("gm_screen.ready_reveal", len=len(secrets)), 3)
        if not secrets:
            ui.label(t("gm_screen.nothing_waiting_everything_you")) \
                .style("color:var(--km-muted);font-size:.8rem")
        for e in sorted(secrets, key=lambda x: (x["col"], x["row"])):
            with ui.row().classes("items-center gap-2 w-full no-wrap"):
                ui.html(f'<span class="km-chip" style="font-size:.68rem">'
                        f'{e["col"]},{e["row"]}</span>')
                terrains = ", ".join(rules.BY_ID["terrain"][terr]["name"]
                                    for terr in e.get("terrains", [])
                                    if terr in rules.BY_ID["terrain"])
                ui.label(e.get("name") or terrains or "—") \
                    .style("font-size:.8rem;flex:1")
                ui.html(f'<span class="km-chip" style="font-size:.62rem">'
                        f'{t(hexmap.HEX_STATUSES[e["status"]][0])}</span>')
                ui.button(t("gm_screen.reveal"), on_click=lambda _, x=e: _reveal([(x["col"], x["row"])])) \
                    .props("dense flat size=sm color=amber")


# ---------------------------------------------------------------------------
@theme.requires(permissions.SEE_SECRETS)
def _reveal(coords) -> None:
    STATE.archive.reveal(STATE.campaign, coords, "*")
    STATE.record(t("gm_screen.revealed_hexes_party", len=len(coords)), "map")
    _refresh_all()


@theme.requires(permissions.SEE_SECRETS)
def _reveal_explored() -> None:
    coords = [(e["col"], e["row"]) for e in STATE.k["hexes"].values()
                  if e["status"] != "unknown"]
    if not coords:
        theme.notify(t("gm_screen.nothing_has_been_explored"), "warning")
        return
    _reveal(coords)


@theme.requires(permissions.SEE_SECRETS)
def _confirm_hide_all() -> None:
    with theme.dialog() as dlg, ui.card().classes("km-panel"):
        theme.title(t("gm_screen.hide_whole_map"), 2)
        ui.label(t("gm_screen.players_will_go_back"))

        def go() -> None:
            coords = hexmap.full_grid()
            STATE.archive.hide(STATE.campaign, coords)
            STATE.record(t("gm_screen.whole_map_hidden_from"), "map")
            dlg.close()
            _refresh_all()

        with ui.row():
            ui.button(t("gm_screen.hide_everything"), on_click=go).props("color=red")
            ui.button(t("common.cancel"), on_click=dlg.close).props("flat")
    dlg.open()


def _refresh_all() -> None:
    """The map changes for everyone: redraws the others' windows too."""
    theme.save_and_refresh()
    _summary.refresh()
    _to_reveal.refresh()
