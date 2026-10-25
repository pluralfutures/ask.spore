"""P2A-12 (b): the takedown clock's public holidays, ``config/holidays.toml``.

Read at startup with the standard library and validated like ``models.toml``: a
malformed file refuses startup. The active region's dates are left out of the working-day
count; an empty calendar keeps the Monday-to-Friday rule.
"""

from __future__ import annotations

import shutil
import tempfile
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from app.content.register import TakedownItem, takedown_due_on, working_days_after
from app.core.config import DEFAULT_CONFIG_DIR, ConfigError, load_settings
from app.core.holidays import HOLIDAYS_FILE, HolidayCalendar, load_holidays
from tests.test_config import ENV, write_config

GOOD = """active = "test"

[regions.test]
name = "Synthetic region"
dates = [2026-11-11]
"""


def load_holidays_text(text: str) -> tuple[HolidayCalendar, list[str]]:
    with tempfile.TemporaryDirectory() as directory:
        (Path(directory) / HOLIDAYS_FILE).write_text(text, encoding="utf-8")
        return load_holidays(Path(directory))


def _problems(tmp_path: Path, text: str) -> list[str]:
    config = write_config(tmp_path)
    (config / HOLIDAYS_FILE).write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError) as refused:
        load_settings(environ=ENV, config_dir=config)
    return [p for p in refused.value.problems if HOLIDAYS_FILE in p or "holidays" in p]


# --- negative cases first ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (GOOD.replace("2026-11-11", "2026-13-01"), "not valid TOML"),
        (GOOD.replace("2026-11-11", "2026-02-30"), "not valid TOML"),
        (GOOD.replace("2026-11-11", '"2026-11-11"'), "dates[0] is not a date"),
        (GOOD.replace("2026-11-11", "2026-11-11T00:00:00"), "dates[0] is not a date"),
        (GOOD.replace("2026-11-11", "11/11/2026"), "not valid TOML"),
        (GOOD.replace("2026-11-11", "20261111"), "dates[0] is not a date"),
        (GOOD.replace("2026-11-11", "2026-11-11, 2026-11-01"), "not after the date before it"),
        (GOOD.replace("2026-11-11", "2026-11-11, 2026-11-11"), "not after the date before it"),
        (GOOD.replace("dates = [2026-11-11]", 'dates = "2026-11-11"'), "must be a list"),
        (GOOD.replace('active = "test"', 'active = "elsewhere"'), "active must name"),
        (GOOD.replace('active = "test"\n', ""), "active must name"),
        (GOOD.replace('name = "Synthetic region"\n', ""), "name must be a non-empty"),
        (GOOD + "observed = true\n", "unknown key observed"),
        (GOOD.replace("[regions.test]", "[regions.Test]").replace('"test"', '"Test"'), "lower"),
        ('active = "none"\n', "[regions] must define a region"),
    ],
)
def test_a_malformed_calendar_refuses_startup(tmp_path: Path, text: str, expected: str) -> None:
    problems = _problems(tmp_path, text)
    assert any(expected in p for p in problems), problems


def test_a_missing_calendar_refuses_startup(tmp_path: Path) -> None:
    config = write_config(tmp_path)
    (config / HOLIDAYS_FILE).unlink()
    with pytest.raises(ConfigError) as refused:
        load_settings(environ=ENV, config_dir=config)
    assert any("holidays.toml" in p and "not found" in p for p in refused.value.problems)


def test_the_calendar_is_never_fetched_or_taken_from_a_library() -> None:
    source = (Path(__file__).parents[1] / "app" / "core" / "holidays.py").read_text()
    imports = {
        line.split()[1] for line in source.splitlines() if line.startswith(("import ", "from "))
    }
    assert imports <= {
        "__future__",
        "re",
        "tomllib",
        "dataclasses",
        "datetime",
        "pathlib",
        "typing",
    }


# --- the clock --------------------------------------------------------------------------


def test_a_request_the_day_before_a_holiday_is_due_one_working_day_later() -> None:
    # Tue Nov 10, 2026, the day before Armistice Day (Wed Nov 11).
    requested = date(2026, 11, 10)
    plain = takedown_due_on(requested, licence_breach=False)
    assert plain == date(2026, 11, 24)  # today's rule, Monday to Friday
    with_holiday = takedown_due_on(
        requested, licence_breach=False, holidays=frozenset({date(2026, 11, 11)})
    )
    assert with_holiday == date(2026, 11, 25) == working_days_after(plain, 1)
    # A licence breach we find ourselves is due at once, holiday or not.
    assert (
        takedown_due_on(requested, licence_breach=True, holidays=frozenset({date(2026, 11, 11)}))
        == requested
    )


def test_an_empty_calendar_keeps_the_monday_to_friday_rule() -> None:
    for start in (date(2026, 10, 19) + timedelta(days=n) for n in range(14)):
        assert working_days_after(start, 10, frozenset()) == working_days_after(start, 10)
    assert working_days_after(date(2026, 10, 23), 10, ()) == date(2026, 11, 6)


def test_a_holiday_on_a_weekend_changes_nothing_and_several_add_up() -> None:
    saturday = date(2026, 11, 14)
    assert working_days_after(date(2026, 11, 10), 10, {saturday}) == date(2026, 11, 24)
    two = {date(2026, 11, 11), date(2026, 11, 12)}
    assert working_days_after(date(2026, 11, 10), 10, two) == date(2026, 11, 26)
    # A holiday on the request day itself does not count: the clock starts the day after.
    assert working_days_after(date(2026, 11, 11), 1, {date(2026, 11, 11)}) == date(2026, 11, 12)


def test_the_sla_timer_counts_on_the_same_calendar() -> None:
    holidays = frozenset({date(2026, 11, 11)})
    due = takedown_due_on(date(2026, 11, 10), licence_breach=False, holidays=holidays)
    item = TakedownItem(uuid4(), "ingested", "TD-1", date(2026, 11, 10), due)
    assert item.working_days_left(date(2026, 11, 10), holidays) == 10
    assert item.working_days_left(date(2026, 11, 10)) == 11  # without the calendar
    assert item.working_days_left(date(2026, 11, 26), holidays) == -1


# --- the repository file ----------------------------------------------------------------


def _easter(year: int) -> date:
    """Gregorian Easter Sunday (the anonymous Gregorian algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def test_the_repository_calendar_follows_france() -> None:
    """Owner decision, Oct 25, 2026: the clock follows France; ``none`` stays defined."""
    settings = load_settings(environ=ENV, config_dir=DEFAULT_CONFIG_DIR)
    assert settings.holidays.region == "france"
    assert date(2026, 11, 11) in settings.holidays.dates
    calendar, problems = load_holidays_text(
        (DEFAULT_CONFIG_DIR / HOLIDAYS_FILE)
        .read_text()
        .replace('active = "france"', 'active = "none"')
    )
    assert problems == [] and calendar == HolidayCalendar("none", frozenset())


def test_the_draft_france_calendar_has_the_national_holidays(tmp_path: Path) -> None:
    config = tmp_path / "config"
    shutil.copytree(DEFAULT_CONFIG_DIR, config)
    calendar, problems = load_holidays(config)
    assert problems == [] and calendar.region == "france"
    for year in (2026, 2027):
        easter = _easter(year)
        expected = {
            date(year, 1, 1),
            easter + timedelta(days=1),
            date(year, 5, 1),
            date(year, 5, 8),
            easter + timedelta(days=39),
            easter + timedelta(days=50),
            date(year, 7, 14),
            date(year, 8, 15),
            date(year, 11, 1),
            date(year, 11, 11),
            date(year, 12, 25),
        }
        assert {d for d in calendar.dates if d.year == year} == expected
