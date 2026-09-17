"""Kingdom sheet: abilities, rollable skills, leaders, feats and resources."""
from __future__ import annotations

import time
import uuid

from nicegui import ui

from kingmaker.access import auth, permissions
from kingmaker import rules
from kingmaker.locale import units
from kingmaker.state import STATE
from kingmaker.ui import theme
from kingmaker.locale.i18n import t


# --------------------------------------------------------------------------
@theme.requires(permissions.EDIT_KINGDOM)
def roll_skill(skill_id: str, cd: int, extra_title: str = "", outcome_text: str = "",
                 worsens_by: int = 0, show: bool = True) -> rules.Result:
    detail = STATE.skill_detail(skill_id)
    mod = sum(v for _n, v in detail)
    if STATE.in_anarchy:
        worsens_by += 1
    res = rules.roll_check(mod, cd, detail, worsens_by)
    name = rules.BY_ID["skills"][skill_id]["name"]

    STATE.fame_on_critical(res)

    label = f"{extra_title} · {name}" if extra_title else name
    STATE.record(t("sheet.vs_dc", label=label, label2=res.label, total=res.total, cd=cd), "check")
    # A roll writes a line in the journal and, on a critical, moves the fame:
    # those two panels, not the whole interface of every window.
    theme.save_and_refresh_panels(("turn.journal", "sheet.identita"))
    if show:
        theme.show_result(res, label, outcome_text)
    return res


# --------------------------------------------------------------------------
def _dc_dialog(skill_id: str) -> None:
    """Asks for the DC before rolling (useful for non-standard checks)."""
    with theme.dialog() as dlg, ui.card().classes("km-panel"):
        name = rules.BY_ID["skills"][skill_id]["name"]
        theme.title(t("sheet.check", name=name), 2)
        cd = ui.number(t("sheet.dc"), value=STATE.control_dc, format="%d").props("outlined dense").classes("w-40")
        ui.label(t("sheet.kingdom_control_dc", control_dc=STATE.control_dc)).style("color:var(--km-muted)")
        with ui.row():
            ui.button(t("sheet.roll"), on_click=lambda: (dlg.close(), roll_skill(skill_id, int(cd.value)))) \
                .props("color=amber")
            ui.button(t("common.cancel"), on_click=dlg.close).props("flat")
    dlg.open()


# --------------------------------------------------------------------------
@ui.refreshable
def abilities_block() -> None:
    k = STATE.k
    with ui.card().classes("km-panel w-full"):
        theme.title(t("sheet.abilities_ruins"), 2)
        for c in rules.ABILITIES:
            ruin_ = next(r for r in rules.RUINS if r["ability"] == c["id"])
            rd = k["ruins"][ruin_["id"]]
            with ui.row().classes("items-center gap-3 w-full no-wrap"):
                ui.number(value=k["abilities"][c["id"]], format="%d", min=0, max=30,
                          on_change=lambda e, cid=c["id"]: _set_ability(cid, e.value)) \
                    .props("outlined dense").classes("w-20")
                ui.html(f'<div class="km-title" style="min-width:96px">{theme.esc(c["name"])}</div>')
                ui.html(f'<div class="km-mod">{rules.modifier(k["abilities"][c["id"]]):+d}</div>')
                ui.element("div").style("flex:1")
                ui.html(f'<span style="color:var(--km-muted);min-width:88px">{theme.esc(ruin_["name"])}</span>')
                ui.number(value=rd["points"], format="%d", min=0,
                          on_change=lambda e, rid=ruin_["id"]: _set_ruin(rid, "points", e.value)) \
                    .props("outlined dense").classes("w-16").tooltip(t("sheet.ruin_points_accumulated"))
                ui.label("/").style("color:var(--km-muted)")
                ui.number(value=rd["threshold"], format="%d", min=1,
                          on_change=lambda e, rid=ruin_["id"]: _set_ruin(rid, "threshold", e.value)) \
                    .props("outlined dense").classes("w-16").tooltip(t("sheet.ruin_threshold"))
                ui.number(value=rd["penalty"], format="%d", min=0,
                          on_change=lambda e, rid=ruin_["id"]: _set_ruin(rid, "penalty", e.value)) \
                    .props("outlined dense").classes("w-16").tooltip(t("sheet.current_ruin_penalty"))
        ui.label(t("sheet.when_points_ruin_exceed")).style("font-size:.75rem;color:var(--km-muted)")


@theme.requires(permissions.EDIT_KINGDOM)
def _set_ability(cid: str, val) -> None:
    if val is None:
        return
    STATE.k["abilities"][cid] = int(val)
    theme.save_and_refresh()
    skills_block.refresh()


@theme.requires(permissions.EDIT_KINGDOM)
def _set_ruin(rid: str, field: str, val) -> None:
    if val is None:
        return
    STATE.k["ruins"][rid][field] = int(val)
    theme.save_and_refresh()
    skills_block.refresh()


# --------------------------------------------------------------------------
@ui.refreshable
def skills_block() -> None:
    """The sixteen skills as one element.

    A card, a column, two chips, a Quasar select, a modifier and two buttons
    with tooltips were twelve elements per skill, and the select carried its
    options every time; the block is now one piece of markup with a native
    select per skill and the dice drawn as icons. The browser says which
    control was used (`data-km`); `_skill_click` and `_skill_change` do the
    rest, reading the key as untrusted input.
    """
    k = STATE.k
    with ui.card().classes("km-panel w-full"):
        with ui.row().classes("items-center gap-3 w-full"):
            theme.title(t("sheet.kingdom_skills"), 2)
            ui.element("div").style("flex:1")
            ui.html(t("sheet.span_class_km_chip", control_dc=STATE.control_dc))
        roll_hint = theme.esc(t("sheet.basic_check_against_dc", control_dc=STATE.control_dc))
        dc_hint = theme.esc(t("sheet.roll_against_different_dc"))
        cells = []
        for a in rules.SKILLS:
            prof = k["proficiencies"].get(a["id"], "untrained")
            mod = STATE.skill_mod(a["id"])
            ability = rules.BY_ID["ability"][a["ability"]]
            options = "".join(
                f'<option value="{c["id"]}"{" selected" if c["id"] == prof else ""}>'
                f'{theme.esc(c["name"][:3])}</option>' for c in rules.PROFICIENCIES)
            cells.append(
                f'<div class="km-skill" title="{theme.esc(a["desc"])}">'
                f'<div><b>{theme.esc(a["name"])}</b><br><span style="font-size:.68rem;color:var(--km-muted)">'
                f'{theme.esc(ability["abbr"])} · {theme.esc(rules.BY_ID["proficiency"][prof]["name"])}</span></div>'
                f'<select class="km-select" data-km="prof.{a["id"]}">{options}</select>'
                f'<div class="km-mod">{mod:+d}</div>'
                f'<div class="km-icons"><i class="material-icons km-icon-btn amber" data-km="roll.{a["id"]}" '
                f'title="{roll_hint}">casino</i>'
                f'<i class="material-icons km-icon-btn" data-km="dc.{a["id"]}" title="{dc_hint}">tune</i></div>'
                f'</div>')
        block = "".join(cells)
        ui.html(block, sanitize=False).classes("km-skills w-full") \
            .on("click", lambda e: _skill_click(e.args), js_handler=theme.PICK) \
            .on("change", lambda e: _skill_change(e.args), js_handler=theme.PICK_VALUE)


_SKILL_IDS = {a["id"] for a in rules.SKILLS}
_PROFICIENCY_IDS = {c["id"] for c in rules.PROFICIENCIES}


def _skill_click(key) -> None:
    kind, _sep, aid = str(key).partition(".")
    if aid not in _SKILL_IDS:
        return
    if kind == "roll":
        roll_skill(aid, STATE.control_dc)
    elif kind == "dc":
        _dc_dialog(aid)


def _skill_change(args) -> None:
    key, value = theme.key_value(args)
    kind, _sep, aid = key.partition(".")
    if kind == "prof" and aid in _SKILL_IDS and value in _PROFICIENCY_IDS:
        _set_proficiency(aid, value)


def _skills_inputs() -> list:
    return [STATE.control_dc, STATE.k["proficiencies"],
            [STATE.skill_mod(a["id"]) for a in rules.SKILLS]]


@theme.requires(permissions.EDIT_KINGDOM)
def _set_proficiency(aid: str, val: str) -> None:
    STATE.k["proficiencies"][aid] = val
    theme.save_and_refresh()
    skills_block.refresh()


# --------------------------------------------------------------------------
@ui.refreshable
def roles_block() -> None:
    """The eight leadership roles as one element.

    Each row had a select of every character, an input, three checkboxes
    with tooltips and its chips: a dozen elements per role and the character
    list eight times over. The block is one piece of markup: a native select
    or input for who holds the role, the three ticks drawn as icons, the
    chips as before. `_role_click` and `_role_change` read the keys.
    """
    k = STATE.k
    characters = STATE.characters()
    by_id = {p["id"]: p for p in characters}

    with ui.card().classes("km-panel w-full"):
        with ui.row().classes("items-center w-full no-wrap"):
            theme.title(t("sheet.leadership_roles"), 2)
            ui.element("div").style("flex:1")
            if permissions.can(theme.user(), permissions.MANAGE_CHARACTERS):
                ui.button(icon="groups", on_click=characters_dialog) \
                    .props("flat dense round size=sm").tooltip(t("sheet.characters_campaign"))
        n_inv = sum(1 for d in k["roles"].values() if d["invested"])
        ui.label(t("sheet.invested_4_invested_role", n_inv=n_inv,
                   role_status_bonus=rules.role_status_bonus(STATE.level))) \
            .style("font-size:.78rem;color:var(--km-muted)")
        ui.label(t("sheet.distinct_pc_leaders_they", leader_pc=STATE.leader_pc())) \
            .style("font-size:.78rem;color:var(--km-muted)")

        def tick(key: str, on: bool, label: str, hint: str = "") -> str:
            title = f' title="{theme.esc(hint)}"' if hint else ""
            return (f'<span class="km-check{" on" if on else ""}" data-km="{key}"{title}>'
                    f'<i class="material-icons">{"check_box" if on else "check_box_outline_blank"}</i>'
                    f'{theme.esc(label)}</span>')

        rows = []
        for r in rules.ROLES:
            d = k["roles"][r["id"]]
            rid = r["id"]
            if d["pc"]:
                # A PC is chosen among the campaign's characters: this way two
                # roles held by the same character are really the same person.
                current = d.get("character_id") or ""
                options = f'<option value=""{" selected" if not current else ""}>{theme.esc(t("sheet.nobody"))}</option>'
                options += "".join(
                    f'<option value="{theme.esc(p["id"])}"{" selected" if p["id"] == current else ""}>'
                    f'{theme.esc(p["name"])}</option>' for p in characters)
                holder = f'<select class="km-select" data-km="char.{rid}" style="width:12rem">{options}</select>'
            else:
                holder = (f'<input class="km-input" data-km="name.{rid}" style="width:12rem" '
                          f'value="{theme.esc(d["name"])}" placeholder="{theme.esc(t("sheet.npc_name"))}">')
            chips = ""
            char = by_id.get(d.get("character_id") or "")
            if char and char.get("user_id"):
                chips += f'<span class="km-chip" style="font-size:.62rem">{theme.esc(t("sheet.linked_account"))}</span>'
            if d["absent"] or not _role_name(d, by_id):
                chips += (f'<span class="km-chip km-fc" style="font-size:.68rem;white-space:normal">'
                          f'{theme.esc(r["absence_penalty"])}</span>')
            rows.append(
                f'<div class="km-role"><b class="km-title" style="min-width:104px">{theme.esc(r["name"])}</b>'
                f'<span class="km-chip" style="font-size:.68rem">{theme.esc(rules.BY_ID["ability"][r["ability"]]["abbr"])}</span>'
                f'{holder}'
                + tick(f"pc.{rid}", bool(d["pc"]), t("sheet.pc"), t("sheet.ticked_player_plays_them"))
                + tick(f"inv.{rid}", bool(d["invested"]), t("sheet.invested"))
                + tick(f"abs.{rid}", bool(d["absent"]), t("sheet.vacant"), r["absence_penalty"])
                + f'{chips}</div>')
        block = "".join(rows)
        ui.html(block, sanitize=False).classes("w-full") \
            .on("click", lambda e: _role_click(e.args), js_handler=theme.PICK) \
            .on("change", lambda e: _role_change(e.args), js_handler=theme.PICK_VALUE)


def _role_click(key) -> None:
    kind, _sep, rid = str(key).partition(".")
    roles = STATE.k["roles"]
    if rid not in roles:
        return
    d = roles[rid]
    if kind == "pc":
        _set_pc(rid, not d["pc"])
    elif kind == "inv":
        _set_role(rid, "invested", not d["invested"])
    elif kind == "abs":
        _set_role(rid, "absent", not d["absent"])


def _role_change(args) -> None:
    key, value = theme.key_value(args)
    kind, _sep, rid = key.partition(".")
    if rid not in STATE.k["roles"]:
        return
    if kind == "char":
        if value == "" or STATE.archive.character(value) is not None:
            _set_character(rid, value)
    elif kind == "name":
        _set_role(rid, "name", value.strip()[:80])


def _roles_inputs() -> list:
    return [STATE.k["roles"],
            [(p["id"], p["name"], p.get("user_id")) for p in STATE.characters()],
            STATE.level, STATE.leader_pc()]


@ui.refreshable
def _character_list() -> None:
    users = {"": t("sheet.no_account")} | {
        u["id"]: u["username"] for u in STATE.archive.list_users()}
    characters = STATE.characters()
    if not characters:
        ui.label(t("sheet.no_character_yet")).style("color:var(--km-muted);font-size:.8rem")
    for char in characters:
        with ui.row().classes("items-center gap-2 w-full no-wrap") \
                .style("border-top:1px solid var(--km-line);padding-top:6px"):
            ui.input(value=char["name"],
                     on_change=lambda e, i=char["id"]: _edit_character(i, name=e.value)) \
                .props("outlined dense").classes("w-40")
            ui.select(users, value=char["user_id"] or "",
                      on_change=lambda e, i=char["id"]: _edit_character(
                          i, user_id=e.value or None)) \
                .props("outlined dense options-dense").classes("w-36") \
                .tooltip(t("sheet.player_who_plays_them"))
            ui.number(t("sheet.speed_m", unit=units.name()), value=units.to_shown(char["speed_m"]),
                      min=0, max=units.to_shown(60), step=units.step(),
                      on_change=lambda e, i=char["id"]: _edit_character(
                          i, speed_m=units.from_shown(float(e.value or 0)))) \
                .props("outlined dense").classes("w-28") \
                .tooltip(t("sheet.used_compute_journeys_map"))
            ui.number(t("sheet.con_mod"), value=char["con_mod"], min=-5, max=10, step=1,
                      on_change=lambda e, i=char["id"]: _edit_character(
                          i, con_mod=int(e.value or 0))) \
                .props("outlined dense").classes("w-24") \
                .tooltip(t("sheet.days_forced_march_they"))
            ui.element("div").style("flex:1")
            ui.button(icon="delete", on_click=lambda _, p=char: _delete_character(p)) \
                .props("flat dense round size=sm color=red")


def characters_dialog() -> None:
    """The campaign's characters and who plays them."""
    if not permissions.can(auth.current_user(STATE.archive), permissions.MANAGE_CHARACTERS):
        theme.notify(t("sheet.only_gm_can_manage"), "negative")
        return
    with theme.dialog() as dlg, ui.card().classes("km-panel") \
            .style("min-width:min(820px, 94vw);max-width:94vw"):
        theme.title(t("sheet.characters"), 2)
        ui.label(t("sheet.character_may_hold_several")) \
            .style("color:var(--km-muted);font-size:.8rem")
        _character_list()
        theme.sep()
        with ui.row().classes("items-center gap-2 no-wrap"):
            new = ui.input(t("sheet.new_character")).props("outlined dense").classes("w-48")

            def create() -> None:
                name = (new.value or "").strip()
                if not name:
                    theme.notify(t("sheet.name_required"), "negative")
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
                new.set_value("")
                _character_list.refresh()
                roles_block.refresh()

            ui.button(t("common.add"), on_click=create).props("dense color=amber")
        with ui.row().classes("justify-end w-full"):
            ui.button(t("common.close"), on_click=dlg.close).props("flat")
    dlg.open()


@theme.requires(permissions.MANAGE_CHARACTERS)
def _edit_character(character_id: str, **fields) -> None:
    STATE.archive.update_character(character_id, **fields)
    if "name" in fields:
        # The name lives in two places: the table and the role that cites it.
        for entry in STATE.k["roles"].values():
            if entry.get("character_id") == character_id:
                entry["name"] = fields["name"]
        theme.save_and_refresh()
    roles_block.refresh()


@theme.requires(permissions.MANAGE_CHARACTERS)
def _delete_character(char: dict) -> None:
    roles = [rid for rid, v in STATE.k["roles"].items()
             if v.get("character_id") == char["id"]]
    with theme.dialog() as dlg, ui.card().classes("km-panel"):
        theme.title(t("sheet.delete_character"), 2)
        ui.label(t("sheet.will_removed_from_campaign", name=char["name"]))
        if roles:
            names = ", ".join(rules.BY_ID["role"][r]["name"] for r in roles)
            ui.label(t("sheet.holds_those_roles_will", names=names)) \
                .style("color:var(--km-gold);font-size:.82rem")

        def go() -> None:
            for rid in roles:
                STATE.k["roles"][rid]["character_id"] = None
                STATE.k["roles"][rid]["name"] = ""
            STATE.archive.delete_character(char["id"])
            dlg.close()
            theme.save_and_refresh()
            _character_list.refresh()
            roles_block.refresh()

        with ui.row():
            ui.button(t("common.delete"), on_click=go).props("color=red")
            ui.button(t("common.cancel"), on_click=dlg.close).props("flat")
    dlg.open()


def _role_name(d: dict, by_id: dict) -> str:
    """Who holds the role: the character if there is one, otherwise the typed name."""
    char = by_id.get(d.get("character_id") or "")
    return char["name"] if char else (d.get("name") or "")


@theme.requires(permissions.EDIT_KINGDOM)
def _set_character(rid: str, character_id: str) -> None:
    d = STATE.k["roles"][rid]
    d["character_id"] = character_id or None
    char = STATE.archive.character(character_id) if character_id else None
    # The name is kept aligned: the journal and the exported saves need it, and
    # they know nothing about the characters table.
    d["name"] = char["name"] if char else ""
    _after_role_change()


@theme.requires(permissions.EDIT_KINGDOM)
def _set_pc(rid: str, value: bool) -> None:
    d = STATE.k["roles"][rid]
    d["pc"] = value
    if not value:
        # Back to being an NPC: the name stays as free text.
        d["character_id"] = None
    _after_role_change()


@theme.requires(permissions.EDIT_KINGDOM)
def _set_role(rid: str, field: str, val) -> None:
    STATE.k["roles"][rid][field] = val
    _after_role_change()


def _after_role_change() -> None:
    if all(r["name"] for r in STATE.k["roles"].values()):
        STATE.award_milestone("all_eight_leaders")
    theme.save_and_refresh()
    roles_block.refresh()
    skills_block.refresh()



# --------------------------------------------------------------------------
@ui.refreshable
def resources_block() -> None:
    k = STATE.k
    with ui.card().classes("km-panel w-full"):
        theme.title(t("sheet.resources"), 2)
        with ui.row().classes("items-center gap-2 flex-wrap"):
            theme.stat_box(k["rp"], t("sheet.rp_available"),
                           t("sheet.resource_points_current_turn"))
            theme.stat_box(f'{STATE.resource_dice_count}d{STATE.resource_die}', t("sheet.resource_dice"),
                           t("sheet.kingdom_level_4_bonus"))
            theme.stat_box(k["rp_spent_turn"], t("sheet.rp_spent_this_turn"))
            theme.stat_box(STATE.consumption()["total"], t("sheet.consumption"))
        with ui.row().classes("items-center gap-2"):
            ui.number(t("sheet.rp"), value=k["rp"], format="%d", min=0,
                      on_change=lambda e: _set_in(k, "rp", e.value)).props("outlined dense").classes("w-24")
            ui.number(t("sheet.bonus_dice"), value=k["bonus_dice"], format="%d",
                      on_change=lambda e: _set_in(k, "bonus_dice", e.value)).props("outlined dense").classes("w-28")
            ui.number(t("sheet.penalty_dice"), value=k["penalty_dice"], format="%d",
                      on_change=lambda e: _set_in(k, "penalty_dice", e.value)).props("outlined dense").classes("w-28")
            ui.button(t("sheet.roll_resource_dice"), on_click=_roll_resources).props("dense color=amber")

        theme.sep()
        cons = STATE.consumption()
        ui.label(t("sheet.consumption_settlements_armies_influenced", settlements=cons["settlements"], armies=cons["armies"], farms=cons["farms"], events=cons["events"], total=cons["total"])).style("font-size:.8rem;color:var(--km-muted)")
        with ui.row().classes("gap-2 items-center"):
            ui.number(t("sheet.army_consumption"), value=k["army_consumption"], format="%d", min=0,
                      on_change=lambda e: _set_in(k, "army_consumption", e.value)) \
                .props("outlined dense").classes("w-36")
            ui.number(t("sheet.event_consumption"), value=k["consumption_extra"], format="%d",
                      on_change=lambda e: _set_in(k, "consumption_extra", e.value)) \
                .props("outlined dense").classes("w-36")

        theme.sep()
        theme.title(t("sheet.commodities"), 3)
        with ui.row().classes("gap-3 flex-wrap"):
            for p in rules.COMMODITIES:
                limit = STATE.storage(p["id"])
                with ui.column().classes("gap-0 items-center"):
                    ui.html(f'<div style="font-size:1.4rem;text-align:center">{p["icon"]}</div>')
                    ui.number(value=k["commodities"][p["id"]], format="%d", min=0,
                              on_change=lambda e, char_id=p["id"]: _set_commodity(char_id, e.value)) \
                        .props("outlined dense").classes("w-24")
                    ui.html(f'<div style="font-size:.7rem;color:var(--km-muted);text-align:center">'
                            f'{p["name"]}<br>max {limit}</div>')
                    ui.tooltip(p["desc"])
        sites = [h for h in STATE.claimed_hexes() if h.get("work_site")]
        if sites:
            yield_: dict[str, int] = {}
            for h in sites:
                sl = h["work_site"]
                yield_[sl["commodity"]] = yield_.get(sl["commodity"], 0) + (2 if sl.get("doubled") else 1)
            ui.label(t("sheet.active_work_sites") + ", ".join(
                f'{rules.BY_ID["commodity"][p]["name"]} +{n}' for p, n in yield_.items())) \
                .style("font-size:.8rem;color:var(--km-gold-dim)")


@theme.requires(permissions.EDIT_KINGDOM)
def _set_in(d: dict, key: str, val) -> None:
    if val is None:
        return
    d[key] = int(val)
    theme.save_and_refresh()
    resources_block.refresh()


@theme.requires(permissions.EDIT_KINGDOM)
def _set_commodity(char_id: str, val) -> None:
    if val is None:
        return
    STATE.k["commodities"][char_id] = int(val)
    theme.save_and_refresh()


@theme.requires(permissions.EDIT_KINGDOM)
def _roll_resources() -> None:
    n, faces = STATE.resource_dice_count, STATE.resource_die
    tot, rolls = rules.roll(n, faces)
    STATE.k["rp"] = tot
    STATE.k["rp_spent_turn"] = 0
    STATE.record(t("sheet.resource_dice_d", n=n, faces=faces, tot=tot), "resources", str(rolls))
    theme.save_and_refresh()
    resources_block.refresh()
    theme.notify(t("sheet.d_rp", n=n, faces=faces, tot=tot, join=', '.join(map(str, rolls))))


# --------------------------------------------------------------------------
@ui.refreshable
def feats_block() -> None:
    """The kingdom feats as one element, grouped by level.

    Thirty-four rows of a checkbox, three chips, a summary and a tooltip
    were six hundred elements per window; the list is one piece of markup,
    the tick an icon, the description the browser's own tooltip, and the
    feats sit under the level they need, the ones above the kingdom's level
    dimmed. A click anywhere on a feat toggles it, for the ones above the
    level too, as the checkbox did.
    """
    k = STATE.k
    with ui.card().classes("km-panel w-full"):
        theme.title(t("sheet.kingdom_feats"), 2)
        expected = 1 + (STATE.level // 2)   # government bonus + one every 2 levels from the 2nd
        ui.label(t("sheet.feats_owned_about_expected", len=len(k['feats']), expected=expected)) \
            .style("font-size:.78rem;color:var(--km-muted)")
        rows = []
        last_level = None
        for f in sorted(rules.FEATS, key=lambda x: (x["level"], x["name"])):
            if f["level"] != last_level:
                last_level = f["level"]
                rows.append(f'<div class="km-feat-level">{theme.esc(t("common.level_short", level=f["level"]))}</div>')
            owned = f["id"] in k["feats"]
            available = f["level"] <= STATE.level
            prerequisites = (f'<span class="km-chip" style="font-size:.65rem;color:var(--km-muted)">'
                             f'{theme.esc(f["prerequisites"])}</span>' if f["prerequisites"] else "")
            rows.append(
                f'<div class="km-feat{" on" if owned else ""}" data-km="feat.{f["id"]}" '
                f'style="opacity:{"1" if available else ".45"}" title="{theme.esc(f["description"])}">'
                f'<i class="material-icons">{"check_box" if owned else "check_box_outline_blank"}</i>'
                f'<div><b class="km-title">{theme.esc(f["name"])}</b> {prerequisites}'
                f'<div class="s">{theme.esc(f["summary"])}</div></div></div>')
        block = "".join(rows)
        ui.html(block, sanitize=False).classes("w-full") \
            .on("click", lambda e: _feat_click(e.args), js_handler=theme.PICK)


_FEAT_IDS = {f["id"] for f in rules.FEATS}


def _feat_click(key) -> None:
    kind, _sep, fid = str(key).partition(".")
    if kind == "feat" and fid in _FEAT_IDS:
        _toggle_feat(fid, fid not in STATE.k["feats"])


def _feats_inputs() -> list:
    return [STATE.k["feats"], STATE.level]


@theme.requires(permissions.EDIT_KINGDOM)
def _toggle_feat(fid: str, val: bool) -> None:
    if val and fid not in STATE.k["feats"]:
        STATE.k["feats"].append(fid)
    elif not val and fid in STATE.k["feats"]:
        STATE.k["feats"].remove(fid)
    theme.save_and_refresh()
    feats_block.refresh()


# --------------------------------------------------------------------------
@ui.refreshable
def identity_block() -> None:
    k = STATE.k
    chart_ = rules.BY_ID["charter"].get(k["charter"])
    heartland_ = rules.BY_ID["territory"].get(k["heartland"])
    gov = rules.BY_ID["government"].get(k["government"])
    with ui.card().classes("km-panel w-full"):
        theme.title(t("sheet.kingdom_identity"), 2)
        with ui.row().classes("gap-2 flex-wrap"):
            ui.input(t("sheet.name"), value=k["name"], on_change=lambda e: _set_txt("name", e.value)) \
                .props("outlined dense").classes("w-56")
            ui.number(t("sheet.level"), value=k["level"], min=1, max=20, format="%d",
                      on_change=lambda e: _set_level(e.value)).props("outlined dense").classes("w-28")
            ui.number(t("sheet.party_level"), value=k["party_level"], min=1, max=20, format="%d",
                      on_change=lambda e: _set("party_level", e.value)).props("outlined dense").classes("w-32")
            ui.number(t("sheet.xp"), value=k["xp"], min=0, format="%d",
                      on_change=lambda e: _set("xp", e.value)).props("outlined dense").classes("w-28")
        with ui.row().classes("gap-2 flex-wrap items-center"):
            if chart_:
                ui.html(f'<span class="km-chip">{t("sheet.charter")}: <b>{theme.esc(chart_["name"])}</b></span>')
            if heartland_:
                ui.html(f'<span class="km-chip">{t("sheet.heartland")}: <b>{theme.esc(heartland_["name"])}</b></span>')
            if gov:
                ui.html(f'<span class="km-chip">{t("sheet.government")}: <b>{theme.esc(gov["name"])}</b></span>')
            ui.html(f'<span class="km-chip">{t("sheet.size")}: <b>{STATE.size_}</b> '
                    f'({STATE.size_entry()["kind"]})</span>')
            cap = STATE.capital()
            if cap:
                ui.html(t("sheet.span_class_km_chip_2", esc=theme.esc(cap["name"])))
        if heartland_:
            ui.label(t("sheet.favored_terrain_once_per", name=heartland_["name"])) \
                .style("font-size:.78rem;color:var(--km-muted)")
        capabilities = rules.level_entry(STATE.level)["capabilities"]
        ui.label(t("sheet.level_capabilities") + ", ".join(capabilities)).style("font-size:.78rem;color:var(--km-gold-dim)")

        theme.sep()
        with ui.row().classes("items-center gap-3"):
            label = t("sheet.fame") if k["reputation"] == "fame" else t("sheet.infamy")
            ui.html(f'<span class="km-chip">{label}</span>')
            ui.number(value=k["fame_points"], min=0, format="%d",
                      on_change=lambda e: _set("fame_points", e.value)).props("outlined dense").classes("w-20")
            ui.label(f"/ {STATE.max_fame}").style("color:var(--km-muted)")
            ui.number(t("sheet.unrest"), value=k["unrest"], min=0, format="%d",
                      on_change=lambda e: _set_unrest(e.value)).props("outlined dense").classes("w-36")
            pen = rules.unrest_penalty(k["unrest"])
            if pen:
                ui.html(t("sheet.span_class_km_chip_3", pen=pen))
            if STATE.in_anarchy:
                ui.html(t("sheet.span_class_km_chip_4"))


@theme.requires(permissions.EDIT_KINGDOM)
def _set_txt(key: str, val) -> None:
    STATE.k[key] = val
    theme.save_and_refresh()


@theme.requires(permissions.EDIT_KINGDOM)
def _set(key: str, val) -> None:
    if val is None:
        return
    STATE.k[key] = int(val)
    theme.save_and_refresh()
    identity_block.refresh()
    skills_block.refresh()


@theme.requires(permissions.EDIT_KINGDOM)
def _set_level(val) -> None:
    if val is None:
        return
    STATE.k["level"] = int(val)
    theme.save_and_refresh()
    identity_block.refresh()
    skills_block.refresh()
    feats_block.refresh()


@theme.requires(permissions.EDIT_KINGDOM)
def _set_unrest(val) -> None:
    if val is None:
        return
    STATE.k["unrest"] = max(0, int(val))
    theme.save_and_refresh()
    identity_block.refresh()
    skills_block.refresh()


# --------------------------------------------------------------------------
def sheet_panel() -> None:
    # Three fifths and two fifths: the right column holds the resources with
    # their five commodities, the roles with a name and three ticks each,
    # and the feats; at a fixed 520 px they ran out of room while the left
    # column had more than the skills needed.
    with ui.row().classes("w-full items-start gap-4 no-wrap"):
        with ui.column().classes("gap-4").style("flex:3 1 0;min-width:0"):
            identity_block()
            abilities_block()
            skills_block()
        with ui.column().classes("gap-4").style("flex:2 1 0;min-width:520px"):
            resources_block()
            roles_block()
            feats_block()


# --------------------------------------------------------------------------
def _identity_inputs() -> list:
    k = STATE.k
    cap = STATE.capital()
    return [[k[f] for f in ("name", "level", "party_level", "xp", "charter", "heartland",
                            "government", "fame_points", "unrest", "reputation")],
            STATE.size_, STATE.size_entry()["kind"], cap["name"] if cap else None,
            STATE.max_fame, STATE.in_anarchy]


def _abilities_inputs() -> list:
    return [STATE.k["abilities"], STATE.k["ruins"]]


def _resources_inputs() -> list:
    k = STATE.k
    return [{f: k[f] for f in ("rp", "rp_spent_turn", "bonus_dice", "penalty_dice",
                               "army_consumption", "consumption_extra", "commodities")},
            STATE.resource_dice_count, STATE.resource_die, STATE.consumption(),
            {c["id"]: STATE.storage(c["id"]) for c in rules.COMMODITIES},
            [h["work_site"] for h in STATE.claimed_hexes() if h.get("work_site")]]


# Every block says what it reads: a copy whose inputs have not moved is not
# rebuilt (`theme.register_refresh`), and a full refresh after a roll costs
# the sheet nothing.
for _name, _ref, _inputs in (("sheet.identita", identity_block, _identity_inputs),
                             ("sheet.caratteristiche", abilities_block, _abilities_inputs),
                             ("sheet.abilita", skills_block, _skills_inputs),
                             ("sheet.risorse", resources_block, _resources_inputs),
                             ("sheet.ruoli", roles_block, _roles_inputs),
                             ("sheet.talenti", feats_block, _feats_inputs)):
    theme.register_refresh(_name, _ref, depends=_inputs)
