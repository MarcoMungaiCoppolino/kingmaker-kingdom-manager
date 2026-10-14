"""A settlement as the kingdom document holds it: its Urban Grid and its fields.

Pure functions, with no interface: the City tab draws settlements, `State`
founds them again when a freehold pledges fealty (`claim_freehold`), and the
tests build them, all from here.
"""
from __future__ import annotations

import uuid


def empty_grid() -> list[list[dict]]:
    return [[{"structure": None, "gid": None} for _ in range(4)] for _ in range(9)]


def new_settlement(name: str, hexpos: tuple[int, int] | None = None) -> dict:
    return {
        "id": uuid.uuid4().hex[:8],
        "name": name,
        "kind": "village",
        "hex": list(hexpos) if hexpos else None,
        "grids": [empty_grid()],
        "active_blocks": [4],
        "borders": {"north": "land", "south": "land", "east": "land", "west": "land"},
        # Which border holds a wall (wooden or stone) and which water border a
        # bridge spans: set when a wall or a bridge is built on the grid.
        "border_walls": {},
        "border_bridges": {},
        "capital": False,
        "consumption_extra": 0,
        "water_only": False,
        "has_bridge": False,
        "note": "",
    }
