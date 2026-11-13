"""Booking rules, independent of AWS. All committed intervals are half-open."""

import calendar
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


class Problem(Exception):
    def __init__(self, message, code="invalid", status=400):
        super().__init__(message)
        self.code, self.status = code, status


def public_name(name, consent):
    if not consent:
        return "Volunteer (name private)"
    parts = name.split()
    return parts[0] + (" " + parts[-1][0].upper() + "." if len(parts) > 1 else "")


def effective_capacity(shift):
    return math.floor(shift["capacity"] * (1 + shift.get("overflowPercent", 0) / 100))


def validate_interval(shift, start, end):
    if (
        isinstance(start, bool)
        or isinstance(end, bool)
        or not isinstance(start, (int, float))
        or not isinstance(end, (int, float))
    ):
        raise Problem("Choose valid arrival and departure times.")
    if (
        not math.isfinite(start)
        or not math.isfinite(end)
        or not shift["start"] <= start < end <= shift["end"]
    ):
        raise Problem("Choose hours within the shift window.")
    policy = shift.get("attendance", {})
    if not shift.get("flex", False) and (
        start != shift["start"] or end != shift["end"]
    ):
        raise Problem("This job requires the entire shift.")
    increment = policy.get("incrementMinutes", 30)
    if any(
        abs(
            (t - shift["start"]) * 60 / increment
            - round((t - shift["start"]) * 60 / increment)
        )
        > 0.00001
        for t in (start, end)
    ):
        raise Problem("Choose one of the offered time increments.")
    duration = (end - start) * 60
    if duration < policy.get("minMinutes", increment) or duration > policy.get(
        "maxMinutes", 1440
    ):
        raise Problem("These hours do not meet this job's commitment length.")
    if policy.get("allowedStarts") is not None and start not in policy["allowedStarts"]:
        raise Problem("That arrival is not available for this job.")
    if policy.get("allowedEnds") is not None and end not in policy["allowedEnds"]:
        raise Problem("That departure is not available for this job.")


def fits(shift, start, end):
    points = (
        {start}
        | {p["start"] for p in shift["roster"] if start <= p["start"] < end}
        | {p["end"] for p in shift["roster"] if start <= p["end"] < end}
    )
    return all(
        sum(p["start"] <= t < p["end"] for p in shift["roster"])
        < effective_capacity(shift)
        for t in points
    )


def epoch(date, hour, timezone_name="America/New_York"):
    minute = round(hour * 60)
    return int(
        datetime.fromisoformat(date)
        .replace(hour=minute // 60, minute=minute % 60, tzinfo=ZoneInfo(timezone_name))
        .timestamp()
    )


def retention_expiry(event_end):
    """27 calendar months, clamped for short target months."""
    date = datetime.fromtimestamp(event_end, timezone.utc)
    total = date.year * 12 + date.month - 1 + 27
    year, month = total // 12, total % 12 + 1
    return int(
        date.replace(
            year=year,
            month=month,
            day=min(date.day, calendar.monthrange(year, month)[1]),
        ).timestamp()
    )


def validate_selection(raw):
    if not isinstance(raw, dict):
        raise Problem("Invalid selection.")
    for field in ("idempotencyKey", "participantId"):
        if not isinstance(raw.get(field), str) or not re.fullmatch(
            r"[a-zA-Z0-9_-]{16,80}", raw[field]
        ):
            raise Problem("Missing selection identifier.")
    token = raw.get("manageToken", "")
    if not isinstance(token, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{43}", token):
        raise Problem("Missing secure management credential.")
    name = raw.get("name", "")
    if (
        not isinstance(name, str)
        or not 1 <= len(name.strip()) <= 70
        or any(ord(c) < 32 for c in name)
    ):
        raise Problem("Enter a name of 1–70 characters.")
    if not isinstance(raw.get("shareName", False), bool):
        raise Problem("Invalid public-name preference.")
    if not isinstance(raw.get("shiftId"), str) or not re.fullmatch(
        r"[a-zA-Z0-9_-]{1,60}", raw["shiftId"]
    ):
        raise Problem("Unknown shift.")
    return {**raw, "name": name.strip()}


def fingerprint(email, selection):
    return hashlib.sha256(
        json.dumps([email, selection], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()
