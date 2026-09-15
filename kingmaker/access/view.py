"""What the person looking at the map is allowed to see.

The principle is that a player must not *receive* what they do not know: the
filter lives here, before the hex becomes SVG or a panel, not in a `display:
none` in the stylesheet. Whoever opens the browser's developer tools must find
nothing more than what is on screen.

The GM (and the administrator) sees everything: for them the view filters
nothing.
"""
from __future__ import annotations

from kingmaker.access import permissions

# The hex keys a player may receive when they see it. Everything else (the GM
# notes, the features still hidden) lives in another table and never passes
# through here.
PUBLIC_FIELDS = (
    "col", "row", "status", "terrains", "features", "roads", "fortified",
    "farmland", "work_site", "settlement", "name", "note",
)

# Hex fields the GM can keep secret one by one, with the value to show in place
# of the real one while they are. Roads and fortifications may have been there
# before the kingdom existed: the party finds them, it does not inherit them.
HIDEABLE_FIELDS = {
    "roads": False,
    "fortified": False,
    "farmland": False,
    "work_site": None,
}


class MapView:
    """The hexes as a given user sees them.

    Built anew at every redraw: visibility changes while playing, and a view
    kept aside would show the world of a few minutes ago.
    """

    def __init__(self, user, state) -> None:
        self.user = user
        self._state = state
        self.gm = permissions.can(user, permissions.SEE_SECRETS) if user else False
        if self.gm:
            self._visible_set = None          # None = no limit
            self._secrets = state.archive.campaign_secrets(state.campaign)
        else:
            user_id = user.id if user else ""
            self._visible_set = state.archive.visible_hexes(state.campaign, user_id)
            # Even on a revealed hex some fields stay covered: we read them all
            # at once, not one query per cell.
            self._secrets = state.archive.campaign_secrets(state.campaign)

    # ------------------------------------------------------------ permissions
    def can_see(self, col: int, row: int) -> bool:
        return self._visible_set is None or (col, row) in self._visible_set

    # -------------------------------------------------------------- reading
    def hex_for(self, col: int, row: int) -> dict | None:
        """The hex as this user may receive it, or None if they do not know it.

        For the GM it is the real hex; for a player a copy with only the public
        fields, so a field added in the future does not become a leak by
        oversight.
        """
        if not self.can_see(col, row):
            return None
        hexagon = self._state.existing_hex(col, row)
        if hexagon is None:
            return None
        if self.gm:
            return hexagon
        cleaned_up = {c: hexagon.get(c) for c in PUBLIC_FIELDS}
        for field in self._secrets.get((col, row), {}).get("hidden_fields", ()):
            if field in HIDEABLE_FIELDS:
                cleaned_up[field] = HIDEABLE_FIELDS[field]
        return cleaned_up

    def visible_hexes(self) -> dict[str, dict]:
        """The hexes known to this user, keyed like the kingdom's."""
        outside = {}
        for key, hexagon in self._state.k["hexes"].items():
            col, row = hexagon["col"], hexagon["row"]
            cleaned_up = self.hex_for(col, row)
            if cleaned_up is not None:
                outside[key] = cleaned_up
        return outside

    def hidden_features(self, col: int, row: int) -> list:
        """Features only the GM knows exist. For everyone else it is always empty."""
        if not self.gm:
            return []
        return self._secrets.get((col, row), {}).get("hidden_features", [])

    def hidden_fields(self, col: int, row: int) -> list:
        if not self.gm:
            return []
        return self._secrets.get((col, row), {}).get("hidden_fields", [])

    # --------------------------------------------------------- GM only
    def gm_data(self, col: int, row: int) -> dict:
        """Hidden notes and features. For anyone else it is all empty."""
        if not self.gm:
            return {"gm_notes": "", "hidden_features": [], "gm_difficulty": None}
        return self._state.archive.gm_data(self._state.campaign, col, row)

    # -------------------------------------------------------------- markers
    def markers(self) -> list[dict]:
        """The characters to draw on the map, with where they are.

        A marker on a hex covered by fog does not arrive: saying «someone is
        here» on a never-explored cell would be information like any other. The
        characters of the person looking are the exception: where one's own PC
        stands is known anyway.
        """
        my_id = self.user.id if self.user else ""
        outside = []
        for char in self._state.archive.list_characters(self._state.campaign):
            col, row = char["hex_col"], char["hex_row"]
            if col is None or row is None:
                continue
            own_ = bool(my_id) and char.get("user_id") == my_id
            if not (own_ or self.can_see(col, row)):
                continue
            outside.append(char)
        return outside

    # ---------------------------------------------------------------- counts
    def counts(self) -> dict[str, int]:
        """How many hexes per status, over the whole grid.

        Hexes nobody has written anything on are not "non-existent": they are
        Unknown like the others, and they count. This way the total always
        matches the grid, and not the subset someone clicked first.
        """
        m = self._state.k["map"]
        total = int(m["columns"]) * int(m["rows"])
        outside: dict[str, int] = {}
        for hexagon in self.visible_hexes().values():
            state = hexagon.get("status", "unknown")
            outside[state] = outside.get(state, 0) + 1
        known_items = sum(outside.values())
        outside["unknown"] = outside.get("unknown", 0) + max(0, total - known_items)
        return outside
