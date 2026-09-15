"""Kingdom Creation wizard (Steps 1-10 of the rules)."""
from __future__ import annotations

from nicegui import ui

from kingmaker.storage import migrations
from kingmaker.access import permissions
from kingmaker import rules
from kingmaker.state import STATE
from kingmaker.ui import theme
from kingmaker.locale.i18n import t

CAR = rules.derived(lambda: {c["id"]: c["name"] for c in rules.ABILITIES})


# --------------------------------------------------------------------------
def compute_scores(draft: dict) -> tuple[dict[str, int], list[str]]:
    """Sums the boosts and flaws of the choices made. Returns (scores, warnings)."""
    scores = {c: 10 for c in CAR}
    warnings: list[str] = []

    chart_ = rules.BY_ID["charter"].get(draft.get("charter"))
    if chart_:
        for a in chart_["boosts"]:
            scores[a] += 2
        if chart_["flaw"]:
            scores[chart_["flaw"]] -= 2
        is_free = draft.get("charter_free_boost")
        if is_free:
            scores[is_free] += 2

    heartland_ = rules.BY_ID["territory"].get(draft.get("heartland"))
    if heartland_:
        scores[heartland_["boost"]] += 2

    gov = rules.BY_ID["government"].get(draft.get("government"))
    if gov:
        for a in gov["boosts"]:
            scores[a] += 2
        is_free = draft.get("government_free_boost")
        if is_free:
            scores[is_free] += 2

    for a in draft.get("final_boosts", []):
        if a:
            scores[a] += 2

    return scores, warnings


def free_charter_options(draft: dict) -> list[str]:
    chart_ = rules.BY_ID["charter"].get(draft.get("charter"))
    if not chart_:
        return []
    excluded = set(chart_["boosts"]) | ({chart_["flaw"]} if chart_["flaw"] else set())
    return [c for c in CAR if c not in excluded]


def free_government_options(draft: dict) -> list[str]:
    gov = rules.BY_ID["government"].get(draft.get("government"))
    if not gov:
        return []
    return [c for c in CAR if c not in gov["boosts"]]


# --------------------------------------------------------------------------
def creation_page(at_end) -> None:
    k = STATE.k
    draft: dict = {
        "name": k.get("name", ""),
        "charter": k.get("charter"),
        "charter_free_boost": k.get("charter_free_boost"),
        "heartland": k.get("heartland"),
        "government": k.get("government"),
        "government_free_boost": k.get("government_free_boost"),
        "final_boosts": list(k.get("final_boosts") or [None, None]),
        "roles": {r["id"]: dict(k["roles"][r["id"]]) for r in rules.ROLES},
        "invested_count": [rid for rid, d in k["roles"].items() if d["invested"]],
        "leader_skills": {},
        "capital": "",
        "hex_col": None,
        "hex_row": None,
        "reputation": k.get("reputation", "fame"),
        "party_level": k.get("party_level", 1),
    }
    if len(draft["final_boosts"]) < 2:
        draft["final_boosts"] = [None, None]

    theme.title(t("creation.kingdom_creation"), 1)
    ui.label(t("creation.follow_ten_steps_rules")) \
        .style("color:var(--km-muted)")

    @ui.refreshable
    def preview() -> None:
        scores, _ = compute_scores(draft)
        with ui.row().classes("gap-2 flex-wrap items-center"):
            for cid, name in CAR.items():
                mod = rules.modifier(scores[cid])
                theme.stat_box(f"{scores[cid]}", t("creation.text", name=name, mod=mod))

    with ui.card().classes("km-panel w-full"):
        preview()

    with ui.stepper().props("vertical flat").classes("w-full km-panel") as stepper:

        # ---------------------------------------------------------- Step 1
        with ui.step(t("creation.step_1_kingdom_concept")):
            ui.label(t("creation.decide_together_what_kind")) \
                .style("color:var(--km-muted)")
            ui.input(t("creation.kingdom_name")).bind_value(draft, "name").props("outlined dense").classes("w-96")
            ui.number(t("creation.party_level_maximum_kingdom"), min=1, max=20,
                      format="%d").bind_value(draft, "party_level").props("outlined dense").classes("w-96")
            with ui.stepper_navigation():
                ui.button(t("common.next"), on_click=stepper.next).props("color=amber")

        # ---------------------------------------------------------- Step 2
        with ui.step(t("creation.step_2_choose_charter")):
            ui.label(t("creation.charter_grants_two_ability")) \
                .style("color:var(--km-muted)")

            @ui.refreshable
            def charter_block() -> None:
                for c in rules.CHARTERS:
                    chosen_one = draft["charter"] == c["id"]
                    with ui.card().classes("km-panel w-full cursor-pointer") \
                            .style(f"border-color:{'var(--km-gold)' if chosen_one else 'var(--km-line)'}") \
                            .on("click", lambda _e, cid=c["id"]: _choose_charter(cid)):
                        with ui.row().classes("items-center gap-3"):
                            ui.html(f'<b class="km-title">{theme.esc(c["name"])}</b>')
                            for a in c["boosts"]:
                                ui.html(f'<span class="km-chip km-sc">+ {CAR[a]}</span>')
                            ui.html(f'<span class="km-chip">{t("creation.free_boost")}</span>')
                            if c["flaw"]:
                                ui.html(f'<span class="km-chip km-fc">− {CAR[c["flaw"]]}</span>')
                        ui.label(c["desc"]).style("font-size:.85rem;color:var(--km-muted)")
                options = free_charter_options(draft)
                if options:
                    ui.select({o: CAR[o] for o in options}, label=t("creation.free_boost_charter")) \
                        .bind_value(draft, "charter_free_boost").props("outlined dense").classes("w-72") \
                        .on_value_change(lambda _e: preview.refresh())

            def _choose_charter(cid: str) -> None:
                draft["charter"] = cid
                draft["charter_free_boost"] = None
                charter_block.refresh()
                preview.refresh()

            charter_block()
            with ui.stepper_navigation():
                ui.button(t("common.next"), on_click=stepper.next).props("color=amber")
                ui.button(t("common.back"), on_click=stepper.previous).props("flat")

        # ---------------------------------------------------------- Step 3
        with ui.step(t("creation.step_3_choose_heartland")):
            ui.label(t("creation.kingdom_starts_from_single")).style("color:var(--km-muted)")

            @ui.refreshable
            def heartland_block() -> None:
                for h in rules.HEARTLANDS:
                    chosen_one = draft["heartland"] == h["id"]
                    with ui.card().classes("km-panel w-full cursor-pointer") \
                            .style(f"border-color:{'var(--km-gold)' if chosen_one else 'var(--km-line)'}") \
                            .on("click", lambda _e, tid=h["id"]: _choose_heartland(tid)):
                        with ui.row().classes("items-center gap-3"):
                            ui.html(f'<b class="km-title">{theme.esc(h["name"])}</b>')
                            ui.html(f'<span class="km-chip km-sc">+ {CAR[h["boost"]]}</span>')
                        ui.label(h["desc"]).style("font-size:.85rem;color:var(--km-muted)")

            def _choose_heartland(tid: str) -> None:
                draft["heartland"] = tid
                heartland_block.refresh()
                preview.refresh()

            heartland_block()
            with ui.stepper_navigation():
                ui.button(t("common.next"), on_click=stepper.next).props("color=amber")
                ui.button(t("common.back"), on_click=stepper.previous).props("flat")

        # ---------------------------------------------------------- Step 4
        with ui.step(t("creation.step_4_choose_government")):
            ui.label(t("creation.government_grants_two_specific")).style("color:var(--km-muted)")

            @ui.refreshable
            def government_block() -> None:
                for g in rules.GOVERNMENTS:
                    chosen_one = draft["government"] == g["id"]
                    with ui.card().classes("km-panel w-full cursor-pointer") \
                            .style(f"border-color:{'var(--km-gold)' if chosen_one else 'var(--km-line)'}") \
                            .on("click", lambda _e, gid=g["id"]: _choose_government(gid)):
                        with ui.row().classes("items-center gap-2 flex-wrap"):
                            ui.html(f'<b class="km-title">{theme.esc(g["name"])}</b>')
                            for a in g["boosts"]:
                                ui.html(f'<span class="km-chip km-sc">+ {CAR[a]}</span>')
                            ui.html(f'<span class="km-chip">{t("creation.free_boost")}</span>')
                            for a in g["skills"]:
                                ui.html(f'<span class="km-chip">{t("creation.trained", name=rules.BY_ID["skills"][a]["name"])}</span>')
                            ui.html(t("creation.span_class_km_chip", esc=theme.esc(rules.BY_ID["feat"][g["feat"]]["name"])))
                        ui.label(g["desc"]).style("font-size:.85rem;color:var(--km-muted)")
                options = free_government_options(draft)
                if options:
                    ui.select({o: CAR[o] for o in options}, label=t("creation.free_boost_government")) \
                        .bind_value(draft, "government_free_boost").props("outlined dense").classes("w-72") \
                        .on_value_change(lambda _e: preview.refresh())

            def _choose_government(gid: str) -> None:
                draft["government"] = gid
                draft["government_free_boost"] = None
                government_block.refresh()
                preview.refresh()

            government_block()
            with ui.stepper_navigation():
                ui.button(t("common.next"), on_click=stepper.next).props("color=amber")
                ui.button(t("common.back"), on_click=stepper.previous).props("flat")

        # ---------------------------------------------------------- Step 5
        with ui.step(t("creation.step_5_finalize_scores")):
            ui.label(t("creation.choose_two_different_abilities")) \
                .style("color:var(--km-muted)")
            with ui.row():
                for i in range(2):
                    ui.select({c: n for c, n in CAR.items()}, label=t("creation.final_boost", v=i + 1),
                              value=draft["final_boosts"][i],
                              on_change=lambda e, idx=i: (_set_final(idx, e.value))) \
                        .props("outlined dense").classes("w-56")

            def _set_final(idx: int, val) -> None:
                draft["final_boosts"][idx] = val
                preview.refresh()

            with ui.stepper_navigation():
                ui.button(t("common.next"), on_click=stepper.next).props("color=amber")
                ui.button(t("common.back"), on_click=stepper.previous).props("flat")

        # ---------------------------------------------------------- Steps 6-7
        with ui.step(t("creation.steps_6_7_details")):
            ui.label(t("creation.assign_eight_roles_invest")).style("color:var(--km-muted)")

            @ui.refreshable
            def roles_block() -> None:
                gov = rules.BY_ID["government"].get(draft.get("government"))
                already_trained = set(gov["skills"]) if gov else set()
                leader_choices = {v for v in draft["leader_skills"].values() if v}

                for r in rules.ROLES:
                    rd = draft["roles"][r["id"]]
                    with ui.card().classes("km-panel w-full"):
                        with ui.row().classes("items-center gap-3 w-full"):
                            ui.html(f'<b class="km-title" style="min-width:110px">{theme.esc(r["name"])}</b>')
                            ui.html(f'<span class="km-chip">{CAR[r["ability"]]}</span>')
                            ui.input(t("creation.character"), value=rd["name"],
                                     on_change=lambda e, rid=r["id"]: _set_name(rid, e.value)) \
                                .props("outlined dense").classes("w-52")
                            ui.checkbox(t("creation.pc"), value=rd["pc"],
                                        on_change=lambda e, rid=r["id"]: _set_pc(rid, e.value))
                            ui.checkbox(t("creation.invested"), value=r["id"] in draft["invested_count"],
                                        on_change=lambda e, rid=r["id"]: _toggle_invested(rid, e.value))
                            if r["id"] in draft["invested_count"]:
                                available_ones = {
                                    a["id"]: a["name"] for a in rules.SKILLS
                                    if a["id"] not in already_trained
                                    and (a["id"] not in leader_choices
                                         or draft["leader_skills"].get(r["id"]) == a["id"])
                                }
                                ui.select(available_ones, label=t("creation.train"),
                                          value=draft["leader_skills"].get(r["id"]),
                                          on_change=lambda e, rid=r["id"]: _set_skill(rid, e.value)) \
                                    .props("outlined dense").classes("w-44")
                        ui.label(t("creation.vacancy_penalty", absence_penalty=r['absence_penalty'])) \
                            .style("font-size:.78rem;color:var(--km-muted)")

                n = len(draft["invested_count"])
                color = "var(--km-gold)" if n == 4 else "var(--km-red)"
                ui.html(t("creation.div_style_color_invested", color=color, n=n))

            def _set_name(rid: str, val: str) -> None:
                draft["roles"][rid]["name"] = val

            def _set_pc(rid: str, val: bool) -> None:
                draft["roles"][rid]["pc"] = val

            def _toggle_invested(rid: str, val: bool) -> None:
                if val and rid not in draft["invested_count"]:
                    draft["invested_count"].append(rid)
                elif not val and rid in draft["invested_count"]:
                    draft["invested_count"].remove(rid)
                    draft["leader_skills"].pop(rid, None)
                roles_block.refresh()

            def _set_skill(rid: str, val: str) -> None:
                draft["leader_skills"][rid] = val
                roles_block.refresh()

            roles_block()
            with ui.stepper_navigation():
                ui.button(t("common.next"), on_click=stepper.next).props("color=amber")
                ui.button(t("common.back"), on_click=stepper.previous).props("flat")

        # ---------------------------------------------------------- Steps 8-10
        with ui.step(t("creation.steps_8_10_first")):
            ui.label(t("creation.first_village_capital_sits")).style("color:var(--km-muted)")
            ui.input(t("creation.capital_name")).bind_value(draft, "capital") \
                .props("outlined dense").classes("w-72")
            with ui.row():
                ui.number(t("creation.starting_hex_column"), format="%d").bind_value(draft, "hex_col") \
                    .props("outlined dense").classes("w-48")
                ui.number(t("creation.starting_hex_row"), format="%d").bind_value(draft, "hex_row") \
                    .props("outlined dense").classes("w-48")
            ui.label(t("creation.you_can_leave_coordinates")) \
                .style("font-size:.78rem;color:var(--km-muted)")
            theme.sep()
            ui.radio({"fame": t("creation.fame"), "infamy": t("creation.infamy")}).bind_value(draft, "reputation").props("inline")
            ui.label(t("creation.famous_kingdom_supports_its")) \
                .style("font-size:.8rem;color:var(--km-muted)")

            with ui.stepper_navigation():
                ui.button(t("creation.found_kingdom"), on_click=lambda: _found(draft, at_end)).props("color=amber")
                ui.button(t("common.back"), on_click=stepper.previous).props("flat")


# --------------------------------------------------------------------------
@theme.requires(permissions.EDIT_KINGDOM)
def _found(draft: dict, at_end) -> None:
    if not draft["name"]:
        theme.notify(t("creation.kingdom_needs_name"), "negative")
        return
    if not (draft["charter"] and draft["heartland"] and draft["government"]):
        theme.notify(t("creation.charter_heartland_government_are"), "negative")
        return
    if len(draft["invested_count"]) != 4:
        theme.notify(t("creation.you_must_invest_exactly"), "negative")
        return

    k = STATE.k
    scores, _ = compute_scores(draft)

    k["name"] = draft["name"]
    k["level"] = 1
    k["party_level"] = int(draft["party_level"] or 1)
    k["charter"] = draft["charter"]
    k["charter_free_boost"] = draft["charter_free_boost"]
    k["heartland"] = draft["heartland"]
    k["government"] = draft["government"]
    k["government_free_boost"] = draft["government_free_boost"]
    k["final_boosts"] = [a for a in draft["final_boosts"] if a]
    k["abilities"] = scores
    k["reputation"] = draft["reputation"]

    # Proficiencies: two from the Government, one for each invested leader
    gov = rules.BY_ID["government"][draft["government"]]
    for a in gov["skills"]:
        k["proficiencies"][a] = "trained"
    for _rid, skill in draft["leader_skills"].items():
        if skill:
            k["proficiencies"][skill] = "trained"

    # Bonus feat of the government
    feat = rules.BY_ID["feat"].get(gov["feat"])
    k["feats"] = [feat["id"]] if feat else []

    for rid, rd in draft["roles"].items():
        k["roles"][rid] = {
            "name": rd["name"], "character_id": None, "pc": rd["pc"],
            "invested": rid in draft["invested_count"], "absent": False,
        }
    # The names just typed become real characters, with the same rule used for
    # games already under way: same name, same person.
    migrations.ensure_characters(STATE.archive, STATE.campaign, k)

    # Step 6 — starting statistics
    k["xp"] = 0
    k["turn"] = 0
    k["unrest"] = 0
    k["consumption_extra"] = 0
    for r in k["ruins"].values():
        r.update({"points": 0, "threshold": 10, "penalty": 0})
    for p in k["commodities"]:
        k["commodities"][p] = 0

    # Step 8 — starting hex and capital
    col, row = draft.get("hex_col"), draft.get("hex_row")
    if col is not None and row is not None:
        h = STATE.hex(int(col), int(row))
        h["status"] = "claimed"
        heartland_ = rules.BY_ID["territory"][draft["heartland"]]
        if not h["terrains"]:
            h["terrains"] = [heartland_["terrains"][0]]

    if draft["capital"]:
        from kingmaker.ui.tabs.city import new_settlement
        sett = new_settlement(
            draft["capital"],
            (int(col), int(row)) if col is not None and row is not None else None,
        )
        sett["capital"] = True
        k["settlements"].append(sett)
        k["capital"] = sett["id"]
        if col is not None and row is not None:
            STATE.hex(int(col), int(row))["settlement"] = sett["id"]
        STATE.award_milestone("first_village")

    if all(r["name"] for r in k["roles"].values()):
        STATE.award_milestone("all_eight_leaders")

    k["created"] = True
    STATE.record(t("creation.founded_kingdom", name=k['name']), "kingdom")
    theme.save_and_refresh()
    theme.notify(t("creation.has_been_founded", name=k['name']))
    at_end()
