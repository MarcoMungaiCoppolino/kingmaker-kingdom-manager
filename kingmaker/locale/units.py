# -*- coding: utf-8 -*-
"""Metres or feet: how a distance is shown, never how it is stored.

Every Speed lives in the database in metres — the Italian rules give them so,
and the whole travel arithmetic (`travel.activities_per_day`) reads metres.
Whoever plays with the English books thinks in feet: 5 feet are 1.5 metres,
so a Speed of 30 feet is 9 metres, exactly, and nothing is lost either way.

Like the language, the unit is a property of the window being drawn: a
player in feet and the GM in metres look at the same kingdom. `theme` sets
the resolver; without a window (tests, background work) the unit follows the
language — feet for English, metres for Italian.
"""
from __future__ import annotations

from kingmaker.locale import i18n

UNITS = ("m", "ft")
DEFAULT_BY_LANGUAGE = {"en": "ft", "it": "m"}
FEET_PER_METRE = 5.0 / 1.5          # 5 ft = 1.5 m, the rules' own conversion
NAMES = {"m": "m", "ft": "ft"}

# The sentence of the Travel Speed row, per unit (the catalog keys).
PACE_KEYS = {"m": "party.km_h_km_per", "ft": "party.mph_mi_per"}

# Set by `theme`: answers the unit of the window being drawn, or None.
units_resolver = lambda: None       # noqa: E731


def default_for(lang: str | None) -> str:
    return DEFAULT_BY_LANGUAGE.get(lang or "", "m")


def resolve(preferred: str | None, lang: str | None) -> str:
    """The person's choice if valid, otherwise what the language suggests."""
    return preferred if preferred in UNITS else default_for(lang)


def current() -> str:
    chosen = units_resolver()
    return chosen if chosen in UNITS else default_for(i18n.current())


def other() -> str:
    return "ft" if current() == "m" else "m"


def name() -> str:
    """The unit's symbol, for labels such as «Speed (ft)»."""
    return NAMES[current()]


def to_shown(metres: float | None) -> float:
    """From the stored metres to the number shown in the fields."""
    value = float(metres or 0.0)
    if current() == "ft":
        return round(value * FEET_PER_METRE, 2)
    return value


def from_shown(value: float | None) -> float:
    """From the number typed in a field back to metres."""
    number = float(value or 0.0)
    if current() == "ft":
        return round(number / FEET_PER_METRE, 4)
    return number


def step() -> float:
    """One rules' step of Speed: 5 feet, or 1.5 metres."""
    return 5.0 if current() == "ft" else 1.5


def _number(value: float, sign: bool = False) -> str:
    text = f"{value:+g}" if sign else f"{value:g}"
    # The decimal separator follows the language of the window, not the unit.
    return text.replace(".", ",") if i18n.current() == "it" else text


def fmt(metres: float | None, sign: bool = False) -> str:
    """«9 m» or «30 ft», ready to be shown."""
    return f"{_number(to_shown(metres), sign)} {name()}"


def per_hour_and_day(row: dict) -> tuple[str, str, str]:
    """From a row of the Travel Speed table: (per hour, per day, key of the
    sentence). In feet the rules count miles: 10 feet are one mile an hour
    and eight miles a day — the same proportion as the kilometres row."""
    if current() == "ft":
        mph = float(row["metres"]) * FEET_PER_METRE / 10.0
        return _number(round(mph, 2)), _number(round(mph * 8, 2)), PACE_KEYS["ft"]
    return _number(float(row["km_hour"])), _number(float(row["km_day"])), PACE_KEYS["m"]
