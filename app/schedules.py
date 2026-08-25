"""Schedule validation and next_run_at computation."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.schema_validate import ValidationError

SCHEDULE_KINDS = frozenset({"once", "daily", "weekly", "interval", "on_date_column"})
TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
MIN_INTERVAL = 60


def validate_schedule(schedule: dict[str, Any], *, allow_on_date_column: bool = True) -> None:
    if not isinstance(schedule, dict):
        raise ValidationError("bad_schedule", "schedule must be an object.")
    kind = schedule.get("kind")
    if kind not in SCHEDULE_KINDS:
        raise ValidationError("bad_schedule", f"Unknown schedule kind: {kind!r}.")
    if kind == "on_date_column" and not allow_on_date_column:
        raise ValidationError("bad_schedule", "on_date_column is not allowed for jobs.")
    if "cron" in schedule:
        raise ValidationError("cron_forbidden", "cron strings are not allowed.")
    if kind == "once":
        if not isinstance(schedule.get("at"), str) or not schedule["at"].strip():
            raise ValidationError("bad_schedule", "once schedule requires at.")
    elif kind == "daily":
        _validate_time(schedule.get("time"))
    elif kind == "weekly":
        wd = schedule.get("weekday")
        if not isinstance(wd, int) or wd < 0 or wd > 6:
            raise ValidationError("bad_schedule", "weekly schedule requires weekday 0-6.")
        _validate_time(schedule.get("time"))
    elif kind == "interval":
        every = schedule.get("every_seconds")
        if not isinstance(every, int) or every < MIN_INTERVAL:
            raise ValidationError("bad_schedule", f"interval requires every_seconds >= {MIN_INTERVAL}.")
    elif kind == "on_date_column":
        for key in ("table", "column", "time"):
            if not isinstance(schedule.get(key), str) or not schedule[key].strip():
                raise ValidationError("bad_schedule", f"on_date_column requires {key}.")


def _validate_time(value: Any) -> None:
    if not isinstance(value, str) or not TIME_RE.match(value):
        raise ValidationError("bad_schedule", "time must be HH:MM.")


def _tzinfo(tz_name: str | None, default_tz: str) -> ZoneInfo:
    name = (tz_name or default_tz or "UTC").strip()
    try:
        return ZoneInfo(name)
    except Exception as exc:
        raise ValidationError("bad_tz", f"Invalid timezone: {name!r}.") from exc


def _parse_once_at(at: str, tz: ZoneInfo) -> datetime:
    raw = at.strip()
    if raw.endswith("Z"):
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.astimezone(tz)
    if "+" in raw[10:] or (len(raw) > 10 and raw[10] in "-"):
        return datetime.fromisoformat(raw).astimezone(tz)
    naive = datetime.fromisoformat(raw)
    return naive.replace(tzinfo=tz)


def _combine_date_time(d: datetime, time_str: str, tz: ZoneInfo) -> datetime:
    hour, minute = map(int, time_str.split(":"))
    return datetime(d.year, d.month, d.day, hour, minute, tzinfo=tz)


def compute_next_run_at(
    schedule: dict[str, Any],
    *,
    tz_name: str | None,
    default_tz: str,
    now: datetime | None = None,
    last_run_at: datetime | None = None,
) -> datetime | None:
    validate_schedule(schedule, allow_on_date_column=True)
    tz = _tzinfo(tz_name, default_tz)
    now = (now or datetime.now(tz)).astimezone(tz)
    kind = schedule["kind"]

    if kind == "once":
        at = _parse_once_at(schedule["at"], tz)
        if at <= now:
            return at
        return at

    if kind == "daily":
        candidate = _combine_date_time(now, schedule["time"], tz)
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate

    if kind == "weekly":
        target_wd = int(schedule["weekday"])
        candidate = _combine_date_time(now, schedule["time"], tz)
        days_ahead = (target_wd - candidate.weekday()) % 7
        if days_ahead == 0 and candidate <= now:
            days_ahead = 7
        candidate = _combine_date_time(now + timedelta(days=days_ahead), schedule["time"], tz)
        return candidate

    if kind == "interval":
        every = int(schedule["every_seconds"])
        base = last_run_at.astimezone(tz) if last_run_at else now
        nxt = base + timedelta(seconds=every)
        if nxt <= now:
            nxt = now + timedelta(seconds=every)
        return nxt

    if kind == "on_date_column":
        return None

    return None


def schedule_summary(schedule: dict[str, Any]) -> str:
    kind = schedule.get("kind", "?")
    if kind == "once":
        return f"once at {schedule.get('at', '?')}"
    if kind == "daily":
        return f"daily at {schedule.get('time', '?')}"
    if kind == "weekly":
        days = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
        wd = int(schedule.get("weekday", 0))
        return f"weekly {days[wd]} at {schedule.get('time', '?')}"
    if kind == "interval":
        return f"every {schedule.get('every_seconds')}s"
    if kind == "on_date_column":
        return f"on {schedule.get('table')}.{schedule.get('column')} at {schedule.get('time')}"
    return str(kind)
