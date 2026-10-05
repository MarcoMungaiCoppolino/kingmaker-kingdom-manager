# -*- coding: utf-8 -*-
"""A roll is seen by everybody at the table, not only by whoever rolled.

Three windows of the real app (NiceGUI's user simulation, no browser) — the
administrator, the GM, a player — and the rolls made in one of them: the
others get the same result screen, read-only, with the name of whoever
rolled above it, and in their own language. A roll about a hex the player
cannot see stays away from the player. A kingdom-turn activity keeps its
effects to apply in the window that rolled; the others only read.
"""
import asyncio
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ["NICEGUI_USER_SIMULATION"] = "true"

import httpx  # noqa: E402
from nicegui import core, ui  # noqa: E402
from nicegui.testing.general import prepare_simulation  # noqa: E402
from nicegui.testing.user import User  # noqa: E402

prepare_simulation()
from kingmaker import main, rules  # noqa: E402,F401
from kingmaker.access import auth  # noqa: E402
from kingmaker.locale import i18n  # noqa: E402
from kingmaker.state import STATE  # noqa: E402
from kingmaker.ui import theme  # noqa: E402
from kingmaker.ui.tabs import sheet, turn  # noqa: E402

results = []
accounts = {u["username"]: u for u in STATE.archive.list_users()}
_session = {"id": accounts["admin"]["id"]}
auth.id_in_session = lambda: _session["id"]
ui.run(storage_secret="simulated secret", reload=False, show=False)


def texts(user: User) -> list[str]:
    """Every text in the window, dialogs included: labels and buttons carry
    it in `text`, the titles and the roll's lines in their HTML `content`."""
    return [str(getattr(e, "text", "") or "") + str(getattr(e, "content", "") or "")
            for e in user.client.elements.values()]


def dialogs_with(user: User, text: str) -> int:
    """How many dialogs of the window show `text` somewhere: a screen counts
    once even when its title and outcome repeat the same words."""
    def inside(element):
        yield str(getattr(element, "text", "") or "") + str(getattr(element, "content", "") or "")
        for slot in element.slots.values():
            for child in slot.children:
                yield from inside(child)
    return sum(1 for e in user.client.elements.values()
               if type(e).__name__ == "Dialog" and any(text in s for s in inside(e)))


def sees(user: User, text: str) -> bool:
    return any(text in found for found in texts(user))


def count(user: User, text: str) -> int:
    return sum(1 for found in texts(user) if text in found)


async def drain() -> None:
    for _ in range(20):
        await asyncio.sleep(0)


async def run() -> None:
    async with core.app.router.lifespan_context(core.app):
        windows = {}
        for name in ("admin", "gm", "player"):
            _session["id"] = accounts[name]["id"]
            u = User(httpx.AsyncClient(transport=httpx.ASGITransport(core.app), base_url="http://test"))
            await u.open("/")
            windows[name] = u
        admin, gm, player = windows["admin"], windows["gm"], windows["player"]
        with player.client:
            theme.set_language("it")

        # --- 1. a skill check from the sheet ---------------------------------
        skill = "agriculture"
        with admin.client:
            sheet.roll_skill(skill, STATE.control_dc)
        await drain()
        with gm.client:
            skill_gm = rules.BY_ID["skills"][skill]["name"]
        with player.client:
            skill_it = rules.BY_ID["skills"][skill]["name"]
        results.append(("the GM sees the roll, with who rolled",
                        sees(gm, "admin rolled") and sees(gm, skill_gm)))
        results.append(("the player sees it too, in Italian",
                        sees(player, "Tiro di admin") and sees(player, skill_it)))
        results.append(("the skill's name is translated, not copied from the roller",
                        skill_it != skill_gm))
        results.append(("whoever rolled has their own screen, not a copy",
                        not sees(admin, "admin rolled")))

        # --- 2. a roll about a hex -------------------------------------------
        seen = STATE.archive.visible_hexes(STATE.campaign, accounts["player"]["id"])
        hidden = next((h["col"], h["row"]) for h in STATE.k["hexes"].values()
                      if (h["col"], h["row"]) not in seen)
        shown = next(iter(sorted(seen)))
        res = rules.Result(15, 3, 18, 14, "success", [])
        before_gm, before_player = count(gm, "admin rolled"), count(player, "Tiro di admin")
        with admin.client:
            theme.show_result(res, lambda: "Hidden hex roll", where=hidden)
        await drain()
        results.append(("a roll on a hex the player cannot see reaches the GM",
                        count(gm, "admin rolled") == before_gm + 1 and sees(gm, "Hidden hex roll")))
        results.append(("but not the player", count(player, "Tiro di admin") == before_player
                        and not sees(player, "Hidden hex roll")))
        with admin.client:
            theme.show_result(res, lambda: "Visible hex roll", where=shown)
        await drain()
        results.append(("a roll on a hex the player sees reaches the player",
                        sees(player, "Visible hex roll")))

        # --- 3. a kingdom-turn activity --------------------------------------
        act_id = next(a["id"] for a in rules.ACTIVITIES
                      if (a.get("effects") or {}).get("success"))
        apply_label = i18n.text("turn.apply_effects", "en")
        apply_it = i18n.text("turn.apply_effects", "it")
        before_admin = count(admin, apply_label)
        with admin.client:
            act = rules.BY_ID["activities"][act_id]
            turn._outcome_dialog(act, rules.Result(15, 5, 20, 15, "success", []))
        await drain()
        with gm.client:
            act_gm = rules.BY_ID["activities"][act_id]["name"]
        with player.client:
            act_it = rules.BY_ID["activities"][act_id]["name"]
        results.append(("an activity's outcome reaches the others",
                        sees(gm, act_gm) and sees(player, act_it)))
        results.append(("the effects to apply stay with whoever rolled",
                        count(admin, apply_label) == before_admin + 1
                        and not sees(gm, apply_label) and not sees(player, apply_it)))

        # --- 4. plain dice ------------------------------------------------------
        def dice_screen(action, title_key):
            """Runs `action` from the admin's window: (admin, gm, player) each got
            one more screen titled `title_key`, the others with who rolled."""
            title_en, title_it = i18n.text(title_key, "en"), i18n.text(title_key, "it")
            before = (dialogs_with(admin, title_en), dialogs_with(gm, title_en),
                      dialogs_with(player, title_it),
                      dialogs_with(gm, "admin rolled"), dialogs_with(player, "Tiro di admin"))
            with admin.client:
                action()
            return (dialogs_with(admin, title_en) == before[0] + 1,
                    dialogs_with(gm, title_en) == before[1] + 1
                    and dialogs_with(gm, "admin rolled") == before[3] + 1,
                    dialogs_with(player, title_it) == before[2] + 1
                    and dialogs_with(player, "Tiro di admin") == before[4] + 1)

        mine, gms, players = dice_screen(turn._roll_resources, "theme.resource_dice")
        results.append(("Resource Dice: on screen for whoever rolled", mine))
        results.append(("and for the GM and the player, in Italian", gms and players))

        # Something to pay, whatever the scene's farms: an event's +2.
        extra_before = STATE.k["consumption_extra"]
        STATE.k["consumption_extra"] = 2
        mine, gms, players = dice_screen(lambda: turn._pay_consumption("unrest"),
                                         "turn.unpaid_consumption_title")
        STATE.k["consumption_extra"] = extra_before
        results.append(("the 1d4 of unpaid Consumption is shown at last, to whoever rolled", mine))
        results.append(("and to the others", gms and players))

        mine, gms, players = dice_screen(turn._check_event, "turn.check_random_events")
        results.append(("the random-event check reaches everybody", mine and gms and players))
        results.append(("with whether an event comes, not «Success»",
                        sees(player, "evento") and sees(gm, "event")))

        mine, gms, players = dice_screen(
            lambda: turn._simple_check(11, lambda: i18n.t("turn.loss_hex"),
                                       lambda: i18n.t("turn.kingdom_loses_no_hex"),
                                       lambda: i18n.t("turn.kingdom_loses_hex_pcs")),
            "turn.loss_hex")
        results.append(("a flat check reaches everybody, titled in each one's language",
                        mine and gms and players))

        effect = next(e for a in rules.ACTIVITIES for grade in (a.get("effects") or {}).values()
                      for e in grade if e["t"] == "resource_die")
        mine, gms, players = dice_screen(
            lambda: turn._apply_rows([{"active": True, "entry": effect, "valore": 1, "target": None}],
                                     "Test activity"),
            "theme.resource_dice")
        results.append(("Resource Dice rolled by an activity's effect reach everybody",
                        mine and gms and players))
        journal = [str(r) for r in STATE.archive.journal(STATE.campaign, 5)]
        results.append(("the effect's journal line speaks the roller's language (it was always Italian)",
                        any("Test activity" in r and ("RP gained" in r or "RP spent" in r) for r in journal)
                        and not any("spesi" in r or "guadagnati" in r for r in journal)))

        # Closed before the end, so their outbox loops stop on their own:
        # see `close_all` in test_windows.py, which hung without it.
        for u in windows.values():
            u.client.delete()


asyncio.run(run())

for name, ok in results:
    print(f" {'ok' if ok else 'NO'}  {name}")
print(f"{sum(1 for _n, ok in results if ok)}/{len(results)} passed")
