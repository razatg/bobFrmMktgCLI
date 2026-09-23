"""Pure date and named-period resolution for Bob commands."""

from __future__ import annotations

import calendar
import datetime as dt
import os
import re

from .errors import die


DEFAULT_GRANULAR_QUERY_MAX_DAYS = 7


def today() -> dt.date:
    override = os.getenv("BOB_TODAY")
    return dt.date.fromisoformat(override) if override else dt.date.today()


def parse_date(value: str | None) -> dt.date | None:
    return dt.date.fromisoformat(value) if value else None


def split_date_range(
    start: dt.date,
    end: dt.date,
    max_days: int = DEFAULT_GRANULAR_QUERY_MAX_DAYS,
) -> list[tuple[dt.date, dt.date]]:
    """Split an inclusive range into contiguous, non-overlapping windows."""
    if max_days < 1:
        raise ValueError("max_days must be positive")
    windows: list[tuple[dt.date, dt.date]] = []
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + dt.timedelta(days=max_days - 1), end)
        windows.append((cursor, chunk_end))
        cursor = chunk_end + dt.timedelta(days=1)
    return windows


def normalize_period_name(period: str) -> str:
    normalized = re.sub(r"[\s-]+", "_", period.strip().lower())
    return {"last_week": "last_complete_week"}.get(normalized, normalized)


def iso_week_to_dates(week: int, year: int) -> tuple[dt.date, dt.date]:
    try:
        monday = dt.date.fromisocalendar(year, week, 1)
    except ValueError:
        die(f"ISO week {week} does not exist in year {year}")
    return monday, monday + dt.timedelta(days=6)


def last_complete_iso_week(reference: dt.date) -> tuple[int, int]:
    last_sunday = reference - dt.timedelta(days=reference.isoweekday())
    calendar_date = last_sunday.isocalendar()
    return calendar_date.week, calendar_date.year


def bid_budget_week_windows(reference: dt.date | None = None) -> list[tuple[dt.date, dt.date]]:
    """Return three contiguous rolling seven-day windows ending yesterday."""
    as_of = (reference or today()) - dt.timedelta(days=1)
    w0_start = as_of - dt.timedelta(days=6)
    w1_end = w0_start - dt.timedelta(days=1)
    w1_start = w1_end - dt.timedelta(days=6)
    w2_end = w1_start - dt.timedelta(days=1)
    w2_start = w2_end - dt.timedelta(days=6)
    return [(w0_start, as_of), (w1_start, w1_end), (w2_start, w2_end)]


def resolve_period_dates(period: str) -> list[tuple[dt.date, dt.date]]:
    period = normalize_period_name(period)
    yesterday = today() - dt.timedelta(days=1)
    if period == "yesterday":
        return [(yesterday, yesterday)]
    if period == "last_complete_week":
        week, year = last_complete_iso_week(today())
        return [iso_week_to_dates(week, year)]
    if period == "bid_budget_weeks":
        return bid_budget_week_windows()
    if period == "yesterday_vs_sdlw":
        same_day_last_week = yesterday - dt.timedelta(days=7)
        return [(yesterday, yesterday), (same_day_last_week, same_day_last_week)]
    if period == "wow":
        return [
            (yesterday - dt.timedelta(days=6), yesterday),
            (yesterday - dt.timedelta(days=13), yesterday - dt.timedelta(days=7)),
        ]
    if period == "mom":
        return [
            (yesterday - dt.timedelta(days=29), yesterday),
            (yesterday - dt.timedelta(days=59), yesterday - dt.timedelta(days=30)),
        ]
    if period == "3week_rolling":
        return [
            (yesterday - dt.timedelta(days=6), yesterday),
            (yesterday - dt.timedelta(days=13), yesterday - dt.timedelta(days=7)),
            (yesterday - dt.timedelta(days=20), yesterday - dt.timedelta(days=14)),
        ]
    if period == "mtd":
        current_start = yesterday.replace(day=1)
        prior_start = (current_start - dt.timedelta(days=1)).replace(day=1)
        prior_day = min(yesterday.day, calendar.monthrange(prior_start.year, prior_start.month)[1])
        return [(current_start, yesterday), (prior_start, prior_start.replace(day=prior_day))]
    partial = re.match(r"^partial_wow_(\d+)$", period)
    if partial:
        days = max(1, int(partial.group(1)))
        current_monday = today() - dt.timedelta(days=today().weekday())
        current_end = min(current_monday + dt.timedelta(days=days - 1), yesterday)
        prior_monday = current_monday - dt.timedelta(days=7)
        return [
            (current_monday, current_end),
            (prior_monday, prior_monday + dt.timedelta(days=days - 1)),
        ]
    die(f"unknown period name: {period}")
