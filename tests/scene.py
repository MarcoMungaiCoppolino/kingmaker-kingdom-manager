# -*- coding: utf-8 -*-
"""Builds the test scene from scratch: a kingdom, a map, three accounts, four
characters and a wagon. No personal data, no real password.

    KINGMAKER_DATA_DIR=<empty folder> python tests/scene.py

It refuses to run if the data folder is `saves/`: the real game is never
touched. The hex terrains come from `scene_hexes.json` (the same grid as the
table's map, without notes or names), so the tests that measure the real
map — connectivity, costs, shores — stay true.

Accounts: admin / gm / player, all with password `prova-<name>-1234`.
"""
import json
import os
import sys
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT_DIR = HERE.parent


def _check_folder() -> Path:
    data = os.environ.get("KINGMAKER_DATA_DIR", "").strip()
    if not data:
        sys.exit("Set KINGMAKER_DATA_DIR to a test folder.")
    folder = Path(data).resolve()
    if folder == (ROOT_DIR / "saves").resolve():
        sys.exit(f"KINGMAKER_DATA_DIR punta al salvataggio vivo ({folder}).")
    folder.mkdir(parents=True, exist_ok=True)
    for name in ("kingmaker.db", "kingmaker.db-wal", "kingmaker.db-shm", "regno.json"):
        try:
            (folder / name).unlink()
        except FileNotFoundError:
            pass
    return folder


CHARACTERS = [
    # name, con_mod, hex, account
    ("Aldric", 4, (8, 4), "player"),
    ("Brenna", 0, (16, 8), "player"),
    ("Corin", 1, (16, 9), "gm"),
    ("Dagny", 0, (9, 4), None),
]
ROLES = {"ruler": "Corin", "counselor": "Brenna",
         "emissary": "Aldric", "warden": "Dagny"}
PNG = {"general": "Tamsin", "magister": "Orrin", "treasurer": "Wenna", "viceroy": "Halvard"}


def build() -> None:
    _check_folder()
    sys.path.insert(0, str(ROOT_DIR))
    from kingmaker.access import auth, permissions
    from kingmaker.state import STATE
    A, C = STATE.archive, STATE.campaign
    k = STATE.k
    data = json.loads((HERE / "scene_hexes.json").read_text(encoding="utf-8"))
    k["name"] = "Test Kingdom"
    k["map"].update(data["map"])
    k["hexes"] = {f'{e["col"]},{e["row"]}': {
        "col": e["col"], "row": e["row"], "status": e["status"],
        "terrains": e["terrains"], "features": [], "roads": e["roads"],
        "fortified": e["fortified"], "farmland": False,
        "work_site": None, "settlement": None, "name": "", "note": ""}
        for e in data["hexes"]}
    k["clock"].update({"days": 227, "in_progress": False,
                       "seconds_per_day": 3.0, "turn_started_at": 30})
    k["turn"] = 3
    # The kingdom is founded, with a capital: without, the app shows only the
    # guided creation and the tabs do not appear.
    from kingmaker.ui.tabs.city import new_settlement
    capital = new_settlement("Test Capital", (18, 7))
    capital["capital"] = True
    k["settlements"].append(capital)
    k["capital"] = capital["id"]
    k["hexes"]["18,7"]["settlement"] = capital["id"]
    k["hexes"]["18,7"]["status"] = "claimed"
    k["created"] = True
    STATE.save()          # creates the campaign: the characters reference it

    users = {}
    for name, role in (("admin", permissions.ADMIN), ("gm", permissions.GM),
                        ("player", permissions.PLAYER)):
        users[name] = auth.create_user(A, name, f"prova-{name}-1234", role=role).id

    ids = {}
    for name, cos, (col, row), account in CHARACTERS:
        char_id = uuid.uuid4().hex[:12]
        A.create_character({"id": char_id, "campaign_id": C,
                            "user_id": users[account] if account else None,
                            "name": name, "speed_m": 7.5, "con_mod": cos,
                            "color": "#d7b263", "active": 1,
                            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S")})
        # A marker for one of them: the prefix tests look at the hrefs.
        A.update_character(char_id, hex_col=col, hex_row=row,
                               token="aldric.png" if name == "Aldric" else None)
        ids[name] = char_id
    for rid, name in ROLES.items():
        k["roles"][rid].update({"name": name, "character_id": ids[name], "pc": True})
    for rid, name in PNG.items():
        k["roles"][rid].update({"name": name, "character_id": None, "pc": False})

    A.create_stable_vehicle({"id": uuid.uuid4().hex[:12], "campaign_id": C,
                           "vehicle": "wagon", "name": "Il Carro", "available": 1,
                           "speed_m": None, "kind": "land", "note": "",
                           "created_at": time.strftime("%Y-%m-%dT%H:%M:%S")})
    STATE.save()
    # What the party knows is visible to everyone, as at the first migration:
    # STATE.load() does it by itself on reopening.
    STATE.load()
    print(f"scene ready: {len(k['hexes'])} hexes, {len(ids)} characters, "
          f"{len(users)} accounts, {A.count_visible(C)} visible")


if __name__ == "__main__":
    build()
