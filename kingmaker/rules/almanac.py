"""The campaign calendar and the passing of days.

Time is counted in **absolute days** from a start date: a single integer to
save, and no date arithmetic scattered across the app. The calendar turns
that count into a date, and says when a month ends.

Why the month and not «thirty days»: the rules say Kingdom Turns «occur at the
end of each month of game time», and the months of Golarion run from 28 to 31
days. A turn therefore lasts as long as the month it falls in, not a round
figure of our choosing.

Golarion's Absalom Reckoning (`data/calendar.json`) is the preset. A table may
write its own calendar instead (`calendar_of`, stored in the kingdom's clock
block): months with their days, a leap rule and an era. It must stay usable
by the Kingdom turn, so `Calendar.validate` refuses a month too short to hold
a leader's week of downtime.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from kingmaker.locale.i18n import t

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

PRESET = "golarion"
# Limits of a calendar a table writes: generous, only there so that a typing
# slip cannot make a year of a thousand months.
MAX_MONTHS = 24
MAX_MONTH_DAYS = 100
MAX_NAME = 40
MAX_ERA = 12


@dataclass(frozen=True)
class Month:
    name: str
    days: int


@dataclass(frozen=True)
class Leap:
    """Every `every` years, counted from a leap year `anchor_year`, the month
    at index `month` has `days` more days."""
    every: int
    anchor_year: int
    month: int
    days: int = 1


@dataclass(frozen=True)
class Calendar:
    """A year of named months. `preset` is set for the calendars the app ships
    (only Golarion's), whose era is a catalog text; a table's own calendar has
    `preset` None and its era as typed."""

    name: str
    months: tuple[Month, ...]
    leap: Leap | None = None
    era: str = ""
    preset: str | None = None

    # ------------------------------------------------------------ the year
    def is_leap_year(self, year: int) -> bool:
        """True if that year has the leap days. The source gives the cadence
        and one reference year: the rest follows, without listing the years."""
        if self.leap is None:
            return False
        return (year - self.leap.anchor_year) % self.leap.every == 0

    def days_in_month(self, year: int, month: int) -> int:
        days = self.months[month].days
        if self.leap is not None and month == self.leap.month and self.is_leap_year(year):
            days += self.leap.days
        return days

    def month_name(self, month: int) -> str:
        return self.months[month].name

    def era_label(self) -> str:
        if self.preset == PRESET:
            return t("clock.era_golarion")
        return self.era

    def format(self, date: "Data") -> str:
        era = self.era_label()
        text = f"{date.day} {self.month_name(date.month)} {date.year}"
        return f"{text} {era}" if era else text

    def shortest_month(self) -> int:
        return min(m.days for m in self.months)

    def longest_month(self) -> int:
        """The longest a month gets, its leap days included: only the month
        that grows in a leap year gains them."""
        leap = self.leap
        return max(m.days + (leap.days if leap is not None and i == leap.month else 0)
                   for i, m in enumerate(self.months))

    # ------------------------------------------------------------ counting
    def date_plus_days(self, start_: "Data", days: int) -> "Data":
        """The date reached by adding `days` to the start date.

        Counted forward month by month instead of with a formula: months have
        different lengths and there is the leap day in between, and an
        explicit loop is easier to verify than a clever division.
        """
        year, month, day = start_.year, start_.month, start_.day + int(days)
        count = len(self.months)
        while day > self.days_in_month(year, month):
            day -= self.days_in_month(year, month)
            month += 1
            if month >= count:
                month = 0
                year += 1
        while day < 1:
            month -= 1
            if month < 0:
                month = count - 1
                year -= 1
            day += self.days_in_month(year, month)
        return Data(year, month, day, self)

    def days_between(self, before: "Data", after: "Data") -> int:
        """How many days separate two dates (negative if `after` comes first)."""
        if (after.year, after.month, after.day) < (before.year, before.month, before.day):
            return -self.days_between(after, before)
        total = 0
        year, month = before.year, before.month
        while (year, month) != (after.year, after.month):
            total += self.days_in_month(year, month)
            month += 1
            if month >= len(self.months):
                month = 0
                year += 1
        return total + after.day - before.day

    def date(self, year: int, month: int, day: int) -> "Data":
        """A date of this calendar, brought inside it: a month index past the
        last month and a day past the month's end are clamped."""
        month = max(0, min(int(month), len(self.months) - 1))
        day = max(1, min(int(day), self.days_in_month(int(year), month)))
        return Data(int(year), month, day, self)

    # ------------------------------------------------------------ checks
    def validate(self) -> list[tuple[str, dict]]:
        """Why this calendar cannot run a kingdom, as catalog keys with their
        parameters; empty when it can. A month is a Kingdom turn, and a leader
        owes a week of downtime in each, so no month may be shorter than that
        week."""
        problems: list[tuple[str, dict]] = []
        if not self.name.strip():
            problems.append(("calendar.problem.no_name", {}))
        if not self.months:
            problems.append(("calendar.problem.no_months", {}))
            return problems
        if len(self.months) > MAX_MONTHS:
            problems.append(("calendar.problem.too_many_months", {"n": MAX_MONTHS}))
        names = [m.name.strip() for m in self.months]
        if any(not n for n in names):
            problems.append(("calendar.problem.unnamed_month", {}))
        if len({n.casefold() for n in names if n}) < len([n for n in names if n]):
            problems.append(("calendar.problem.same_name", {}))
        for m in self.months:
            if m.days < LEADER_REST_DAYS:
                problems.append(("calendar.problem.month_too_short",
                                 {"month": m.name or "?", "days": LEADER_REST_DAYS}))
            elif m.days > MAX_MONTH_DAYS:
                problems.append(("calendar.problem.month_too_long",
                                 {"month": m.name or "?", "days": MAX_MONTH_DAYS}))
        if self.leap is not None:
            if self.leap.every < 1:
                problems.append(("calendar.problem.leap_every", {}))
            if not 0 <= self.leap.month < len(self.months):
                problems.append(("calendar.problem.leap_month", {}))
            if not 1 <= self.leap.days <= MAX_MONTH_DAYS:
                problems.append(("calendar.problem.leap_days", {"days": MAX_MONTH_DAYS}))
        return problems

    # ------------------------------------------------------------ saving
    def to_dict(self) -> dict:
        """What the kingdom's clock block stores."""
        if self.preset:
            return {"preset": self.preset}
        return {"preset": None, "name": self.name, "era": self.era,
                "months": [{"name": m.name, "days": m.days} for m in self.months],
                "leap": None if self.leap is None else
                {"every": self.leap.every, "anchor_year": self.leap.anchor_year,
                 "month": self.leap.month, "days": self.leap.days}}

    @classmethod
    def from_dict(cls, data: dict) -> "Calendar":
        """A table's calendar from the clock block. Raises ValueError or
        TypeError on a shape it cannot read; `calendar_of` falls back then."""
        months = tuple(Month(str(m["name"])[:MAX_NAME], int(m["days"]))
                       for m in data.get("months") or [])
        leap_data = data.get("leap")
        leap = None
        if leap_data:
            leap = Leap(int(leap_data["every"]), int(leap_data["anchor_year"]),
                        int(leap_data["month"]), int(leap_data.get("days", 1)))
        return cls(name=str(data.get("name") or "")[:MAX_NAME], months=months, leap=leap,
                   era=str(data.get("era") or "")[:MAX_ERA], preset=None)


def _golarion() -> Calendar:
    months = tuple(Month(m["name"], int(m["days"])) for m in MONTHS)
    leap_month = next(i for i, m in enumerate(months) if m.name == LEAP_YEAR["month"])
    return Calendar(name="Absalom Reckoning", months=months, preset=PRESET,
                    leap=Leap(int(LEAP_YEAR["every_years"]), int(LEAP_YEAR["last_known"]),
                              leap_month, 1))


GOLARION = _golarion()


@dataclass(frozen=True)
class Data:
    """A day of a calendar: Golarion's unless another is given."""

    year: int
    month: int                   # index into the calendar's months
    day: int                     # 1-based
    calendar: Calendar = field(default=GOLARION, compare=False, repr=False)

    @property
    def month_name(self) -> str:
        return self.calendar.month_name(self.month)

    def __str__(self) -> str:
        return self.calendar.format(self)


def calendar_of(k: dict | None) -> Calendar:
    """The campaign's calendar: Golarion unless the table wrote its own. A
    stored calendar that cannot be read, or could not run a kingdom, falls
    back to Golarion rather than stopping the clock."""
    stored = ((k or {}).get("clock") or {}).get("calendar") or {}
    if stored.get("preset", PRESET) == PRESET:
        return GOLARION
    try:
        calendar = Calendar.from_dict(stored)
    except (KeyError, TypeError, ValueError):
        return GOLARION
    return GOLARION if calendar.validate() else calendar


# ------------------------------------------------------------- the functions
# The module's functions as they were before calendars could change: each
# works in the calendar of the date it is given (Golarion by default).
def is_leap_year(year: int, calendar: Calendar = GOLARION) -> bool:
    return calendar.is_leap_year(year)


def days_in_month(year: int, month: int, calendar: Calendar = GOLARION) -> int:
    return calendar.days_in_month(year, month)


def date_plus_days(start_: Data, days: int) -> Data:
    return start_.calendar.date_plus_days(start_, days)


def days_between(before: Data, after: Data) -> int:
    return before.calendar.days_between(before, after)


# ------------------------------------------------------------------ month and turn
def days_left_in_month(data: Data) -> int:
    """How many days are left before the end of the month, i.e. the Kingdom Turn."""
    return data.calendar.days_in_month(data.year, data.month) - data.day


def last_of_month(data: Data) -> bool:
    return data.day >= data.calendar.days_in_month(data.year, data.month)


# ------------------------------------------------------------------ save
def from_dict(data: dict | None, calendar: Calendar = GOLARION) -> Data:
    data = data or {}
    return calendar.date(int(data.get("year", DEFAULT_YEAR)),
                         int(data.get("month", DEFAULT_MONTH)),
                         int(data.get("day", DEFAULT_DAY)))


def to_dict(data: Data) -> dict:
    return {"year": data.year, "month": data.month, "day": data.day}
