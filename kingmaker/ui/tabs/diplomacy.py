"""The Diplomacy block of the kingdom sheet: partners, relations, agreements.

A partner is a group the kingdom deals with, by name, with the Negotiation DC
the GM gives it: all the wiki asks for («your GM has a list of every DC»).
Relations and trade agreements come from the activities' outcomes (Send
Diplomatic Envoy, Establish Trade Agreement); here the table sees them, and
declares war, makes peace or ends an agreement, each as a row it confirms.
NPC realms (2.4.0) will link to a partner later.
"""
from __future__ import annotations

import uuid

from nicegui import ui

from kingmaker.access import permissions
from kingmaker.locale.i18n import t
from kingmaker.state import STATE
from kingmaker.ui import theme

_PANELS = ("sheet.diplomacy", "turn.steps", "turn.journal")


# ------------------------------------------------------------- the writers
def new_partner(name: str, negotiation_dc: int, note: str = "") -> dict:
    """A partner added to the kingdom (no window needed: `_add_partner` is the button's)."""
    partner = {"id": uuid.uuid4().hex[:8], "name": name.strip(), "negotiation_dc": int(negotiation_dc),
               "realm": None, "note": note}
    STATE.k["partners"].append(partner)
    STATE.record(t("diplomacy.journal_added", name=partner["name"], dc=partner["negotiation_dc"]), "diplomacy")
    return partner


@theme.requires(permissions.EDIT_KINGDOM)
def _add_partner(name: str, negotiation_dc: int, note: str = "") -> dict | None:
    if not (name or "").strip():
        theme.notify(t("diplomacy.name_needed"), "warning")
        return None
    partner = new_partner(name, negotiation_dc, note)
    theme.save_and_refresh_panels(_PANELS)
    return partner


@theme.requires(permissions.EDIT_KINGDOM)
def _update_partner(pid: str, **fields) -> None:
    partner = STATE.partner(pid)
    if not partner:
        return
    allowed = {k: v for k, v in fields.items() if k in ("name", "negotiation_dc", "note")}
    if "negotiation_dc" in allowed:
        allowed["negotiation_dc"] = int(allowed["negotiation_dc"] or 0)
    partner.update(allowed)
    # A field being typed in: the other windows follow, this one keeps its focus.
    theme.save_light(_PANELS)


def in_use(pid: str) -> bool:
    """A relation or an agreement names the partner: it stays."""
    return (any(r.get("partner") == pid for r in STATE.k["diplomatic_relations"])
            or any(isinstance(a, dict) and a.get("partner") == pid for a in STATE.k["trade_agreements"]))


@theme.requires(permissions.EDIT_KINGDOM)
def _remove_partner(pid: str) -> None:
    partner = STATE.partner(pid)
    if not partner:
        return
    if in_use(pid):
        theme.notify(t("diplomacy.in_use"), "warning")
        return
    STATE.k["partners"] = [p for p in STATE.k["partners"] if p["id"] != pid]
    STATE.record(t("diplomacy.journal_removed", name=partner["name"]), "diplomacy")
    theme.save_and_refresh_panels(_PANELS)


@theme.requires(permissions.EDIT_KINGDOM)
def _set_abstract(pid: str, value: bool) -> None:
    rel = STATE.relation(pid)
    if rel:
        rel["abstract_war"] = bool(value)
        theme.save_and_refresh_panels(_PANELS)


def _propose(pid: str, entry: dict) -> None:
    """A change of relation or agreement, confirmed as a row."""
    from kingmaker.ui.tabs import turn
    partner = STATE.partner(pid)
    if not partner:
        return
    turn.propose_rows(lambda: t("diplomacy.title"), [dict(entry, auto=True)],
                      context={"subject": pid}, category="diplomacy")


# ------------------------------------------------------------- the block
@ui.refreshable
def diplomacy_block() -> None:
    k = STATE.k
    with ui.card().classes("km-panel w-full"):
        theme.title(t("diplomacy.title"), 2)
        ui.label(t("diplomacy.intro")).style("font-size:.78rem;color:var(--km-muted);white-space:normal")
        if not k["partners"]:
            ui.label(t("diplomacy.none")).style("font-size:.8rem;color:var(--km-muted)")
        for partner in k["partners"]:
            _partner_row(partner)
        theme.sep()
        form = {"name": "", "dc": 15}
        with ui.row().classes("items-center gap-2 w-full"):
            ui.input(t("diplomacy.name"), on_change=lambda e: form.update(name=e.value or "")) \
                .props("outlined dense").classes("w-48")
            ui.number(t("diplomacy.negotiation_dc"), value=15, format="%d",
                      on_change=lambda e: form.update(dc=int(e.value or 0))) \
                .props("outlined dense").classes("w-32")
            ui.button(t("diplomacy.add"), on_click=lambda: _add_partner(form["name"], form["dc"])) \
                .props("dense color=amber")
        agreements = STATE.active_agreements()
        if agreements:
            theme.sep()
            theme.title(t("diplomacy.agreements"), 3)
            for a in agreements:
                partner = STATE.partner(a.get("partner")) or {}
                with ui.row().classes("items-center gap-2 w-full"):
                    ui.label(t("diplomacy.agreement_line", name=partner.get("name", "?"), since=a.get("since_turn", 0))) \
                        .style("font-size:.85rem;flex:1")
                    ui.button(t("diplomacy.end_agreement"),
                              on_click=lambda _e=None, pid=a.get("partner"): _propose(pid, {"t": "agreement", "what": "ended"})) \
                        .props("dense flat color=grey")


def _partner_row(partner: dict) -> None:
    pid = partner["id"]
    rel = STATE.relation(pid)
    status = (rel or {}).get("status")
    with ui.column().classes("gap-1 w-full").style("border-left:2px solid var(--km-line);padding-left:8px"):
        with ui.row().classes("items-center gap-2 w-full"):
            ui.input(t("diplomacy.name"), value=partner["name"],
                     on_change=lambda e: _update_partner(pid, name=e.value or partner["name"])) \
                .props("outlined dense debounce=500").classes("w-48")
            ui.number(t("diplomacy.negotiation_dc"), value=partner["negotiation_dc"], format="%d",
                      on_change=lambda e: _update_partner(pid, negotiation_dc=e.value)) \
                .props("outlined dense debounce=500").classes("w-32")
            label = t(f"diplomacy.status_{status}") if status else t("diplomacy.status_none")
            colour = {"war": "km-fc", "relations": "km-s"}.get(status, "")
            ui.html(f'<span class="km-chip {colour}" style="font-size:.7rem">{theme.esc(label)}'
                    + (f' · {theme.esc(t("diplomacy.since", turn=rel["since_turn"]))}' if rel and status != "ended" else "")
                    + '</span>')
            ui.element("div").style("flex:1")
            ui.button(icon="delete", on_click=lambda: _remove_partner(pid)) \
                .props(f'dense flat round color=grey {"disable" if in_use(pid) else ""}') \
                .tooltip(t("diplomacy.in_use") if in_use(pid) else t("diplomacy.remove"))
        with ui.row().classes("items-center gap-2 flex-wrap"):
            if status in ("relations", "war"):
                if status == "relations":
                    ui.button(t("diplomacy.declare_war"),
                              on_click=lambda: _propose(pid, {"t": "relation", "status": "war"})) \
                        .props("dense flat color=red")
                else:
                    ui.button(t("diplomacy.make_peace"),
                              on_click=lambda: _propose(pid, {"t": "relation", "status": "relations"})) \
                        .props("dense flat color=amber")
                    ui.checkbox(t("diplomacy.abstract_war"), value=bool(rel.get("abstract_war")),
                                on_change=lambda e: _set_abstract(pid, e.value)).props("dense")
                ui.button(t("diplomacy.end_relations"),
                          on_click=lambda: _propose(pid, {"t": "relation", "status": "ended"})) \
                    .props("dense flat color=grey")
        if partner.get("note"):
            ui.label(partner["note"]).style("font-size:.75rem;color:var(--km-muted)")


def diplomacy_inputs() -> list:
    k = STATE.k
    return [k["partners"], k["diplomatic_relations"], k["trade_agreements"], k["turn"]]
