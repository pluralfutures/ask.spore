"""Public holidays the takedown clock skips (P2A-12 b): ``config/holidays.toml``.

The file names regions, each a list of dates, and marks one region ``active``::

    active = "none"

    [regions.none]
    name = "No public holidays (Monday to Friday only)"
    dates = []

    [regions.france]
    name = "France (metropolitan)"
    dates = [2026-11-01, 2026-11-11, 2026-12-25]

Dates are TOML local dates, in ascending order without repeats. ``load_settings`` reads
the file at startup and refuses to start on any problem (a missing file, a string or a
date-time instead of a date, an impossible date, an unknown key, an ``active`` region
that is not defined), as it does for ``models.toml``. Read with the standard library's
``tomllib``: no network and no holiday library. An empty active calendar keeps the
Monday-to-Friday rule.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Final

HOLIDAYS_FILE: Final = "holidays.toml"
_REGION: Final = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


@dataclass(frozen=True)
class HolidayCalendar:
    """The active region's public holidays."""

    region: str = "none"
    dates: frozenset[date] = field(default_factory=frozenset)


NO_HOLIDAYS: Final = HolidayCalendar()


def _region_problems(key: str, value: Any) -> tuple[list[date], list[str]]:
    where = f"{HOLIDAYS_FILE}: regions.{key}"
    if not _REGION.fullmatch(key):
        return [], [f"{where}: a region name is lower-case letters, digits, - or _"]
    if not isinstance(value, dict):
        return [], [f"{where} must be a table"]
    problems = [f"{where}: unknown key {k}" for k in sorted(set(value) - {"name", "dates"})]
    name = value.get("name")
    if not isinstance(name, str) or not name.strip():
        problems.append(f"{where}.name must be a non-empty string")
    dates = value.get("dates")
    if not isinstance(dates, list):
        return [], [*problems, f"{where}.dates must be a list of dates"]
    found: list[date] = []
    for index, item in enumerate(dates):
        # A TOML date-time is a datetime, which is also a date: refuse it explicitly.
        if isinstance(item, datetime) or not isinstance(item, date):
            problems.append(f"{where}.dates[{index}] is not a date (write it as 2026-11-01)")
            continue
        if found and item <= found[-1]:
            problems.append(f"{where}.dates[{index}] {item} is not after the date before it")
        found.append(item)
    return found, problems


def load_holidays(directory: Path) -> tuple[HolidayCalendar, list[str]]:
    """The active calendar of ``<directory>/holidays.toml``, or the problems found."""
    path = directory / HOLIDAYS_FILE
    try:
        raw: dict[str, Any] = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return NO_HOLIDAYS, [f"config file not found: {path}"]
    except tomllib.TOMLDecodeError as exc:
        return NO_HOLIDAYS, [f"{HOLIDAYS_FILE} is not valid TOML: {exc}"]
    problems = [
        f"{HOLIDAYS_FILE}: unknown key {k}" for k in sorted(set(raw) - {"active", "regions"})
    ]
    regions = raw.get("regions")
    if not isinstance(regions, dict) or not regions:
        return NO_HOLIDAYS, [*problems, f"{HOLIDAYS_FILE}: [regions] must define a region"]
    calendars: dict[str, list[date]] = {}
    for key, value in regions.items():
        dates, found = _region_problems(key, value)
        calendars[key] = dates
        problems += found
    active = raw.get("active")
    if not isinstance(active, str) or active not in calendars:
        problems.append(f"{HOLIDAYS_FILE}: active must name one of the regions defined")
    if problems or not isinstance(active, str):
        return NO_HOLIDAYS, problems
    return HolidayCalendar(active, frozenset(calendars[active])), []
