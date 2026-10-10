# -*- coding: utf-8 -*-
"""The campaign calendar: Golarion's, and the one a table writes.

1. Golarion gives exactly the dates it gave before calendars could change:
   the old functions are copied below, verbatim, and compared day by day
   over thirty years, leap years included.
2. A table's own calendar: its months, its leap rule, its era, the round
   trip through the save, and the checks that keep it usable by the
   Kingdom turn (no month shorter than the leaders' week of downtime).
3. An old save without a calendar opens on Golarion.
4. Switching calendars keeps the days already played: `days` does not move,
   only the start is re-expressed, so journeys keep their count.
5. The month's end closes the turn in a custom calendar too.
6. In a window: the date dialog and the calendar editor open for the GM.
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
from kingmaker import main  # noqa: E402,F401
from kingmaker.access import auth  # noqa: E402
from kingmaker.rules import almanac  # noqa: E402
from kingmaker.state import STATE, new_kingdom  # noqa: E402
from kingmaker.storage import migrations  # noqa: E402
from kingmaker.travel import daily  # noqa: E402
from kingmaker.ui.tabs import clock  # noqa: E402

results = []


# --- 1. Golarion, against the code it replaced -----------------------------
def old_is_leap_year(year):
    step = int(almanac.LEAP_YEAR["every_years"])
    return (year - int(almanac.LEAP_YEAR["last_known"])) % step == 0


def old_days_in_month(year, month):
    entry = almanac.MONTHS[month]
    days = int(entry["days"])
    if entry["name"] == almanac.LEAP_YEAR["month"] and old_is_leap_year(year):
        days += 1
    return days


def old_date_plus_days(year, month, day, days):
    day = day + int(days)
    while day > old_days_in_month(year, month):
        day -= old_days_in_month(year, month)
        month += 1
        if month >= len(almanac.MONTHS):
            month = 0
            year += 1
    while day < 1:
        month -= 1
        if month < 0:
            month = len(almanac.MONTHS) - 1
            year -= 1
        day += old_days_in_month(year, month)
    return year, month, day


start = almanac.from_dict({"year": 4700, "month": 0, "day": 1})
mismatch, month_ends = [], 0
total = sum(sum(old_days_in_month(y, m) for m in range(12)) for y in range(4700, 4731))
for n in range(total):
    old = old_date_plus_days(4700, 0, 1, n)
    new = almanac.date_plus_days(start, n)
    if (new.year, new.month, new.day) != old:
        mismatch.append((n, old, new))
    if almanac.last_of_month(new) != (old[2] >= old_days_in_month(old[0], old[1])):
        mismatch.append((n, "month end", new))
    month_ends += almanac.last_of_month(new)
    if almanac.days_between(start, new) != n:
        mismatch.append((n, "between", new))
results.append((f"Golarion: {total} days from 4700 to 4730 identical to the old code"
                f"{'' if not mismatch else ' NOT: ' + str(mismatch[:3])}", not mismatch))
results.append(("Golarion: one month end per month", month_ends == 31 * 12))
results.append(("Golarion: 4712 and 4720 are leap years, 4713 is not",
                almanac.is_leap_year(4712) and almanac.is_leap_year(4720) and not almanac.is_leap_year(4713)
                and almanac.days_in_month(4712, 1) == 29 and almanac.days_in_month(4713, 1) == 28))
results.append(("Golarion: the date reads with the era of the window's language",
                str(almanac.from_dict({"year": 4710, "month": 0, "day": 1})) == "1 Abadius 4710 AR"))
results.append(("Golarion is valid", not almanac.GOLARION.validate()))
results.append(("Golarion's turns last 28 to 31 days: the leap day goes to Calistril, not to the longest month",
                (almanac.GOLARION.shortest_month(), almanac.GOLARION.longest_month()) == (28, 31)))

# --- 2. a table's own calendar ----------------------------------------------
harptos = almanac.Calendar(
    name="Harptos", era="DR",
    months=(almanac.Month("Hammer", 31), almanac.Month("Alturiak", 30), almanac.Month("Ches", 30)),
    leap=almanac.Leap(every=4, anchor_year=1372, month=0, days=1))
results.append(("a table's calendar is valid when every month holds the downtime week",
                not harptos.validate()))
results.append(("its leap rule grows the chosen month",
                harptos.days_in_month(1372, 0) == 32 and harptos.days_in_month(1373, 0) == 31
                and harptos.days_in_month(1376, 0) == 32))
first = harptos.date(1373, 0, 1)
results.append(("its year wraps after its last month",
                harptos.date_plus_days(first, 31 + 30 + 30) == harptos.date(1374, 0, 1)))
results.append(("its era is the one typed", str(harptos.date(1373, 2, 5)) == "5 Ches 1373 DR"))
saved = harptos.to_dict()
back = almanac.Calendar.from_dict(saved)
results.append(("it goes through the save and back unchanged", back == harptos))
results.append(("calendar_of reads it from the clock block",
                almanac.calendar_of({"clock": {"calendar": saved}}) == harptos))
results.append(("a broken stored calendar falls back to Golarion",
                almanac.calendar_of({"clock": {"calendar": {"preset": None, "months": "nope"}}})
                is almanac.GOLARION
                and almanac.calendar_of({"clock": {"calendar": {"preset": None, "name": "X",
                                                                "months": [{"name": "A", "days": 5}]}}})
                is almanac.GOLARION))
short = almanac.Calendar(name="Short", months=(almanac.Month("Brief", 5), almanac.Month("Long", 30)))
problems = [key for key, _p in short.validate()]
results.append(("a 5-day month is refused: the leaders' week would not fit",
                problems == ["calendar.problem.month_too_short"]))
results.append(("a calendar without months, a name or with twin months is refused",
                [k for k, _ in almanac.Calendar(name="", months=()).validate()]
                == ["calendar.problem.no_name", "calendar.problem.no_months"]
                and "calendar.problem.same_name" in [k for k, _ in almanac.Calendar(
                    name="T", months=(almanac.Month("A", 30), almanac.Month("a", 30))).validate()]))
results.append(("a leap rule on a month that does not exist is refused",
                "calendar.problem.leap_month" in [k for k, _ in almanac.Calendar(
                    name="T", months=(almanac.Month("A", 30),),
                    leap=almanac.Leap(4, 0, 3, 1)).validate()]))
results.append(("a date past the month's end is brought inside it",
                harptos.date(1373, 1, 40) == harptos.date(1373, 1, 30)
                and harptos.date(1373, 9, 1).month == 2))

# --- 3. an old save -----------------------------------------------------------
old_save = new_kingdom()
del old_save["clock"]["calendar"]
opened = migrations.normalize(old_save, new_kingdom)
results.append(("an old save without a calendar opens on Golarion",
                opened["clock"]["calendar"] == {"preset": "golarion"}
                and almanac.calendar_of(opened) is almanac.GOLARION))
custom_save = new_kingdom()
custom_save["clock"]["calendar"] = saved
results.append(("and a custom one is kept through normalize",
                migrations.normalize(custom_save, new_kingdom)["clock"]["calendar"] == saved))

# --- 4 and 5. switching, and the month's end ----------------------------------
saved_kingdom = STATE.k
try:
    STATE.k = new_kingdom()
    STATE.k["clock"]["days"] = 100
    golarion_today = daily.current_date(STATE.k)
    today_there = harptos.date(1373, 1, 10)
    clock.save_calendar(harptos, today_there)
    results.append(("switching keeps the days played and gives the date chosen",
                    STATE.k["clock"]["days"] == 100 and daily.current_date(STATE.k) == today_there
                    and daily.current_date(STATE.k).calendar == harptos))
    journey_day = 40
    then = almanac.date_plus_days(almanac.from_dict(STATE.k["clock"]["start"], harptos), journey_day)
    results.append(("a journey's day count still lands 60 days before today",
                    almanac.days_between(then, daily.current_date(STATE.k)) == 60))
    clock.save_calendar(almanac.GOLARION, golarion_today)
    results.append(("and switching back gives Golarion's date again",
                    daily.current_date(STATE.k) == golarion_today
                    and almanac.calendar_of(STATE.k) is almanac.GOLARION))

    class Archive:
        @staticmethod
        def list_journeys(*_a):
            return []

    class Probe:
        k = STATE.k
        campaign = STATE.campaign
        archive = Archive()

    clock.save_calendar(harptos, harptos.date(1373, 1, 28))
    reports = [daily.advance_one_day(Probe) for _ in range(3)]
    results.append(("the turn closes at a custom month's end, not after 30 days",
                    [r.month_end for r in reports] == [False, True, False]
                    and reports[1].data == harptos.date(1373, 1, 30)
                    and reports[2].data == harptos.date(1373, 2, 1)))
finally:
    STATE.k = saved_kingdom

# --- 6. in a window ------------------------------------------------------------
accounts = {u["username"]: u for u in STATE.archive.list_users()}
auth.id_in_session = lambda: accounts["admin"]["id"]
ui.run(storage_secret="simulated secret", reload=False, show=False)


async def window_run() -> None:
    async with core.app.router.lifespan_context(core.app):
        user = User(httpx.AsyncClient(transport=httpx.ASGITransport(core.app), base_url="http://test"))
        await user.open("/")
        try:
            with user.client:
                clock._date_dialog()
                clock._calendar_dialog()
            await user.should_see("Calendar")
            await user.should_see("A calendar of our own")
            results.append(("the date dialog and the calendar editor open for the GM", True))
        except Exception as error:      # noqa: BLE001
            results.append((f"the date dialog and the calendar editor open for the GM: {error!r}", False))
        finally:
            user.client.delete()


asyncio.run(window_run())

for name, ok in results:
    print(f" {'ok' if ok else 'NO'}  {name}")
print(f"{sum(1 for _n, ok in results if ok)}/{len(results)} passed")
