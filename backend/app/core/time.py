from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone, tzinfo


def local_timezone() -> tzinfo:
    return datetime.now().astimezone().tzinfo or timezone.utc


def utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def db_datetime(value: datetime) -> datetime:
    return utc_datetime(value).replace(tzinfo=None)


def local_today() -> date:
    return datetime.now(local_timezone()).date()


def local_day_bounds_utc(day: date) -> tuple[datetime, datetime]:
    tz = local_timezone()
    start_local = datetime.combine(day, time.min, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    return utc_datetime(start_local), utc_datetime(end_local)
