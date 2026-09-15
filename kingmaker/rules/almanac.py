"""The campaign calendar and the passing of days.

Pure functions over `data/calendar.json`, transcribed from the Absalom
Reckoning calendar. Time is counted in **absolute days** from a start date: a
single integer to save, and no date arithmetic scattered across the app.

Why the month and not «thirty days»: the rules say Kingdom Turns «occur at the
end of each month of game time», and the months of Golarion run from 28 to 31
days. A turn therefore lasts as long as the month it falls in, not a round
figure of our choosing.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

_DATA = json.loads((Path(__file__).parent / "data" / "calendar.json")
                   .read_text(encoding="utf-8"))

MONTHS = _DATA["months"]
LEAP_YEAR = _DATA["leap_year"]
LEADER_REST_DAYS = int(_DATA["leader_rest_days"])

# Start date of the Adventure Path: the campaign begins when the table decides,
# and this is only the proposal shown the first time.
DEFAULT_YEAR = 4710
DEFAULT_MONTH = 0            # Abadius
DEFAULT_DAY = 1


@dataclass(frozen=True)
class Data:
    """A day of the Absalom Reckoning calendar."""

    year: int
    month: int                   # index 0-11 in MONTHS
    day: int                 # 1-based

    @property
    def month_name(self) -> str:
        return MONTHS[self.month]["name"]

    def __str__(self) -> str:
        return f"{self.day} {self.month_name} {self.year} CA"


def is_leap_year(year: int) -> bool:
    """True if that year has the extra day at the end of Calistril.

    The source gives the cadence (every eight years) and a reference year: the
    rest follows, without listing the years one by one.
    """
    step = int(LEAP_YEAR["every_years"])
    return (year - int(LEAP_YEAR["last_known"])) % step == 0


def days_in_month(year: int, month: int) -> int:
    entry = MONTHS[month]
    days = int(entry["days"])
    if entry["name"] == LEAP_YEAR["month"] and is_leap_year(year):
        days += 1
    return days


# ------------------------------------------------------------------ conversions
def date_plus_days(start_: Data, days: int) -> Data:
    """The date reached by adding `days` to the start date.

    Counted forward month by month instead of with a formula: months have
    different lengths and there is the leap day in between, and an explicit
    loop is easier to verify than a clever division.
    """
    year, month, day = start_.year, start_.month, start_.day + int(days)
    while day > days_in_month(year, month):
        day -= days_in_month(year, month)
        month += 1
        if month >= len(MONTHS):
            month = 0
            year += 1
    while day < 1:
        month -= 1
        if month < 0:
            month = len(MONTHS) - 1
            year -= 1
        day += days_in_month(year, month)
    return Data(year, month, day)


def days_between(before: Data, after: Data) -> int:
    """How many days separate two dates (negative if `after` comes first)."""
    if (after.year, after.month, after.day) < (before.year, before.month, before.day):
        return -days_between(after, before)
    total = 0
    year, month = before.year, before.month
    while (year, month) != (after.year, after.month):
        total += days_in_month(year, month)
        month += 1
        if month >= len(MONTHS):
            month = 0
            year += 1
    return total + after.day - before.day


# ------------------------------------------------------------------ month and turn
def days_left_in_month(data: Data) -> int:
    """How many days are left before the end of the month, i.e. the Kingdom Turn."""
    return days_in_month(data.year, data.month) - data.day


def last_of_month(data: Data) -> bool:
    return data.day >= days_in_month(data.year, data.month)


# ------------------------------------------------------------------ save
def from_dict(data: dict | None) -> Data:
    data = data or {}
    return Data(int(data.get("year", DEFAULT_YEAR)),
                int(data.get("month", DEFAULT_MONTH)),
                int(data.get("day", DEFAULT_DAY)))


def to_dict(data: Data) -> dict:
    return {"year": data.year, "month": data.month, "day": data.day}
