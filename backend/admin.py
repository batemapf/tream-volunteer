"""Organizer operations. HTTP handlers require a validated organizer access token."""

import copy
import csv
import hashlib
import io
import json
import math
import time
import uuid
from datetime import date
from domain import (
    Problem,
    effective_capacity,
    epoch,
    validate_interval,
    normalize_sub_jobs,
)
from service import BookingService, Contention, public_shift


def shift_rows(store):
    registry = store.get("EVENT#2026") or {}
    return [
        s
        for s in store.get_many(["SHIFT#" + id for id in registry.get("shiftIds", [])])
        if s
    ]


def coverage(shift):
    points = {shift["start"], shift["end"]}
    t = shift["start"]
    while t < shift["end"]:
        points.add(t)
        t += 0.5
    for person in shift["roster"]:
        points.update([person["start"], person["end"]])
    points = sorted(p for p in points if shift["start"] <= p <= shift["end"])
    ceiling = effective_capacity(shift)
    return [
        {
            "start": start,
            "end": end,
            "count": sum(p["start"] <= start < p["end"] for p in shift["roster"]),
            "target": shift["capacity"],
            "limit": ceiling,
        }
        for start, end in zip(points, points[1:])
    ]


def conflict_key(a, b):
    return hashlib.sha256("|".join(sorted([a["id"], b["id"]])).encode()).hexdigest()


def detect_conflicts(bookings):
    groups = {}
    for booking in bookings:
        groups.setdefault(booking["email"], []).append(booking)
    result = []
    for people in groups.values():
        people.sort(key=lambda p: p["startAt"])
        for index, a in enumerate(people):
            for b in people[index + 1 :]:
                if b["startAt"] >= a["endAt"]:
                    break
                if a["id"] == b["id"]:
                    continue
                same_person = a["participantId"] == b["participantId"] or " ".join(
                    a["name"].casefold().split()
                ) == " ".join(b["name"].casefold().split())
                result.append(
                    {
                        "id": conflict_key(a, b),
                        "bookingIds": [a["id"], b["id"]],
                        "kind": "same_person" if same_person else "shared_email",
                        "email": a["email"],
                    }
                )
    return result


def clean_text(value, label, maximum, required=True):
    if (
        not isinstance(value, str)
        or len(value.strip()) > maximum
        or any(ord(c) < 32 and c not in "\n\t" for c in value)
    ):
        raise Problem("Enter valid " + label + ".")
    value = value.strip()
    if required and not value:
        raise Problem("Enter " + label + ".")
    return value


def number(value, label, minimum, maximum, integer=False):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not minimum <= value <= maximum
        or (integer and int(value) != value)
    ):
        raise Problem("Invalid " + label + ".")
    return int(value) if integer else value


def edited_shift(old, payload):
    updated = copy.deepcopy(old)
    for field, maximum in [("name", 100), ("role", 50), ("location", 180)]:
        if field in payload:
            updated[field] = clean_text(payload[field], field, maximum)
    if "date" in payload:
        try:
            if (
                not isinstance(payload["date"], str)
                or date.fromisoformat(payload["date"]).isoformat() != payload["date"]
            ):
                raise ValueError()
        except ValueError:
            raise Problem("Choose a valid date.") from None
        updated["date"] = payload["date"]
    for field in ("start", "end"):
        if field in payload:
            updated[field] = number(payload[field], field, 0, 24)
    if updated["start"] >= updated["end"] or any(
        abs(h * 60 - round(h * 60)) > 0.00001
        for h in (updated["start"], updated["end"])
    ):
        raise Problem("Choose a valid shift window in whole minutes.")
    if "capacity" in payload:
        updated["capacity"] = number(payload["capacity"], "capacity", 1, 500, True)
    if "overflowPercent" in payload:
        updated["overflowPercent"] = number(
            payload["overflowPercent"], "overflow percentage", 0, 100
        )
    for field in ("open", "flex"):
        if field in payload:
            if not isinstance(payload[field], bool):
                raise Problem("Invalid " + field + ".")
            updated[field] = payload[field]
    if "subJobs" in payload:
        updated["subJobs"] = normalize_sub_jobs(payload["subJobs"])
    if "attendance" in payload:
        policy = payload["attendance"]
        if not isinstance(policy, dict) or set(policy) - {
            "incrementMinutes",
            "minMinutes",
            "maxMinutes",
            "allowedStarts",
            "allowedEnds",
        }:
            raise Problem("Invalid attendance policy.")
        updated["attendance"] = {**updated.get("attendance", {}), **policy}
    policy = updated.get("attendance", {})
    increment = number(
        policy.get("incrementMinutes", 30), "time increment", 5, 120, True
    )
    if increment not in (5, 10, 15, 20, 30, 60, 120):
        raise Problem("Choose a 5, 10, 15, 20, 30, 60 or 120 minute increment.")
    duration = (updated["end"] - updated["start"]) * 60
    minimum = number(
        policy.get("minMinutes", increment), "minimum commitment", increment, duration
    )
    number(policy.get("maxMinutes", duration), "maximum commitment", minimum, 1440)
    for key in ("allowedStarts", "allowedEnds"):
        values = policy.get(key)
        if values is not None:
            if not isinstance(values, list) or not 1 <= len(values) <= 288:
                raise Problem("Invalid " + key + ".")
            for t in values:
                number(t, key, updated["start"], updated["end"])
                if abs(
                    (t - updated["start"]) * 60 / increment
                    - round((t - updated["start"]) * 60 / increment)
                ) > 0.00001 and t not in (updated["start"], updated["end"]):
                    raise Problem("Allowed times must match the configured increment.")
    starts = policy.get("allowedStarts") or [
        updated["start"] + i * increment / 60
        for i in range(int(duration / increment) + 1)
    ]
    ends = policy.get("allowedEnds") or [
        updated["start"] + i * increment / 60
        for i in range(int(duration / increment) + 1)
    ]
    if updated["end"] not in ends:
        ends.append(updated["end"])
    possible = False
    for start in starts:
        for end in ends:
            try:
                validate_interval(updated, start, end)
                possible = True
                break
            except Problem:
                pass
        if possible:
            break
    if not possible:
        raise Problem("This policy leaves no valid commitment window.")
    if updated["date"] != old["date"] and old["roster"]:
        raise Problem(
            "Existing volunteers are booked on the current date. Resolve those commitments before changing it.",
            "existing_bookings",
            409,
        )
    for person in old["roster"]:
        try:
            validate_interval(updated, person["start"], person["end"])
        except Problem:
            raise Problem(
                "This change would invalidate an existing commitment. Resolve it before editing the shift.",
                "existing_bookings",
                409,
            ) from None
    if any(s["count"] > s["limit"] for s in coverage(updated)):
        raise Problem(
            "This limit is below current attendance. Resolve the excess commitments first.",
            "existing_bookings",
            409,
        )
    updated["startAt"] = epoch(updated["date"], updated["start"])
    updated["endAt"] = epoch(updated["date"], updated["end"])
    if updated["endAt"] > old["publicUntil"]:
        raise Problem(
            "This date is outside the loaded event window. Update event settings before moving the shift.",
            "event_window",
            409,
        )
    updated["revision"] += 1
    return updated


def csv_cell(value):
    text = str(value)
    return (
        "'" + text
        if text.lstrip().startswith(("=", "+", "-", "@"))
        or text.startswith(("\t", "\r", "\n"))
        else text
    )


class AdminService:
    def __init__(self, store, actor, clock=time.time):
        self.store, self.actor, self.clock = store, actor, clock

    def audit(self, kind, target, details, expires):
        return {
            "pk": "AUDIT#" + str(uuid.uuid4()),
            "kind": kind,
            "target": target,
            "actor": self.actor,
            "details": details,
            "createdAt": int(self.clock()),
            "expiresAt": expires,
        }

    def data(self):
        shifts = shift_rows(self.store)
        ids = ["BOOKING#" + p["id"] for s in shifts for p in s["roster"] if "id" in p]
        rows = [
            b
            for b in self.store.get_many(ids)
            if b and b.get("status") == "active" and b["expiresAt"] > self.clock()
        ]
        return shifts, rows

    def overview(self):
        shifts, bookings = self.data()
        conflicts = detect_conflicts(bookings)
        reviews = {
            r["pk"].removeprefix("CONFLICT#"): r
            for r in self.store.get_many(["CONFLICT#" + c["id"] for c in conflicts])
            if r
        }
        for c in conflicts:
            review = reviews.get(c["id"])
            c["reviewed"] = bool(review)
            if review:
                c["note"] = review.get("note", "")
        public = []
        for s in shifts:
            item = public_shift(s, self.clock())
            item.update(
                {
                    "open": s.get("open", False),
                    "revision": s["revision"],
                    "subJobs": s.get("subJobs", []),
                    "coverage": coverage(s),
                }
            )
            public.append(item)
        allowed = (
            "id",
            "shiftId",
            "participantId",
            "name",
            "email",
            "publicName",
            "start",
            "end",
            "startAt",
            "endAt",
            "status",
        )
        return {
            "shifts": public,
            "bookings": [
                {
                    **{k: b[k] for k in allowed},
                    "subJobPreferences": b.get("subJobPreferences", []),
                }
                for b in bookings
            ],
            "conflicts": conflicts,
            "emailEnabled": False,
        }

    def update_shift(self, id, payload):
        old = self.store.get("SHIFT#" + id)
        if not old:
            raise Problem("Shift not found.", "not_found", 404)
        revision = payload.get("revision")
        if isinstance(revision, bool) or revision != old["revision"]:
            raise Problem(
                "Someone changed this shift. Refresh before saving.", "stale", 409
            )
        if set(payload) - {
            "revision",
            "name",
            "role",
            "location",
            "date",
            "start",
            "end",
            "capacity",
            "overflowPercent",
            "flex",
            "open",
            "attendance",
            "subJobs",
        }:
            raise Problem("Unknown shift fields.")
        new = edited_shift(old, payload)
        changed = {
            k: {"before": old.get(k), "after": new.get(k)}
            for k in payload
            if k != "revision" and old.get(k) != new.get(k)
        }
        audit = self.audit("shift_edited", id, changed, old["expiresAt"])
        try:
            self.store.commit_admin_shift(old, new, audit)
        except Contention:
            raise Problem(
                "A signup or edit changed the shift. Refresh and retry.", "stale", 409
            ) from None
        return {"status": "saved", "revision": new["revision"]}

    def cancel_booking(self, id):
        for attempt in range(8):
            booking = self.store.get("BOOKING#" + id)
            if not booking or booking["expiresAt"] <= self.clock():
                raise Problem("Booking not found.", "not_found", 404)
            if booking["status"] == "canceled":
                return {"status": "canceled"}
            old = self.store.get("SHIFT#" + booking["shiftId"])
            if not old:
                raise Problem("Shift not found.", "not_found", 404)
            new = copy.deepcopy(old)
            new["revision"] += 1
            new["roster"] = [p for p in new["roster"] if p["id"] != id]
            audit = self.audit("booking_canceled", id, {}, booking["expiresAt"])
            try:
                self.store.commit_cancel(old, new, booking, audit=audit)
                return {"status": "canceled", "emailEnabled": False}
            except Contention:
                time.sleep(0.01)
        raise Problem("The shift changed. Retry the cancellation.", "retry", 409)

    def review_conflict(self, key, payload):
        _, bookings = self.data()
        conflict = next((c for c in detect_conflicts(bookings) if c["id"] == key), None)
        if not conflict:
            raise Problem(
                "This overlap is no longer active. Refresh the list.", "not_found", 404
            )
        note = clean_text(payload.get("note", ""), "review note", 500, False)
        expires = min(
            b["expiresAt"] for b in bookings if b["id"] in conflict["bookingIds"]
        )
        review = {
            "pk": "CONFLICT#" + key,
            "note": note,
            "actor": self.actor,
            "reviewedAt": int(self.clock()),
            "expiresAt": expires,
        }
        self.store.commit_records(
            [review, self.audit("conflict_reviewed", key, {"note": note}, expires)]
        )
        return {"status": "reviewed"}

    def export(self, query):
        shifts, bookings = self.data()
        by_id = {s["id"]: s for s in shifts}
        buf = io.StringIO(newline="")
        writer = csv.writer(buf)
        writer.writerow(
            [
                "Volunteer",
                "Contact email",
                "Job",
                "Day",
                "Arrive",
                "Leave",
                "Public name",
                "Task preferences",
            ]
        )
        for b in bookings:
            s = by_id[b["shiftId"]]
            if (
                query.get("q")
                and query["q"].casefold()
                not in (b["name"] + " " + b["email"]).casefold()
            ):
                continue
            if query.get("day") and query["day"] != s["date"]:
                continue
            if query.get("shiftId") and query["shiftId"] != s["id"]:
                continue
            if query.get("role") and query["role"] != s["role"]:
                continue
            writer.writerow(
                [
                    csv_cell(v)
                    for v in [
                        b["name"],
                        b["email"],
                        s["name"],
                        s["date"],
                        self.hour(b["start"]),
                        self.hour(b["end"]),
                        b["publicName"],
                        "; ".join(p["label"] for p in b.get("subJobPreferences", [])),
                    ]
                ]
            )
        return "\ufeff" + buf.getvalue()

    @staticmethod
    def hour(t):
        return f"{int(t):02d}:{round((t%1)*60):02d}"

    def message_preview(self, payload):
        subject = clean_text(payload.get("subject", ""), "a subject", 180)
        if any(c in subject for c in ("\n", "\r")):
            raise Problem("Use one line for the subject.")
        body = clean_text(payload.get("body", ""), "a message", 8000)
        selector = payload.get("selector", {})
        if not isinstance(selector, dict):
            raise Problem("Choose recipients.")
        mode = selector.get("mode")
        if mode not in ("all", "selected", "group"):
            raise Problem("Choose recipients.")
        shifts, bookings = self.data()
        by_id = {s["id"]: s for s in shifts}
        if mode == "selected":
            ids = selector.get("bookingIds")
            if (
                not isinstance(ids, list)
                or not 1 <= len(ids) <= 500
                or not all(isinstance(id, str) for id in ids)
            ):
                raise Problem("Select at least one volunteer.")
            bookings = [b for b in bookings if b["id"] in ids]
        elif mode == "group":
            field = selector.get("field")
            value = selector.get("value")
            if (
                field not in ("date", "role", "shiftId")
                or not isinstance(value, str)
                or not value
            ):
                raise Problem("Choose a group.")
            bookings = [
                b
                for b in bookings
                if (b["shiftId"] if field == "shiftId" else by_id[b["shiftId"]][field])
                == value
            ]
        contacts = {}
        for b in bookings:
            contacts.setdefault(b["email"], []).append(
                {
                    "bookingId": b["id"],
                    "name": b["name"],
                    "shift": by_id[b["shiftId"]]["name"],
                    "date": by_id[b["shiftId"]]["date"],
                    "start": b["start"],
                    "end": b["end"],
                }
            )
        recipients = [
            {"email": email, "commitments": sorted(rows, key=lambda r: r["bookingId"])}
            for email, rows in sorted(contacts.items())
        ]
        if not recipients:
            raise Problem("No active volunteers match these recipients.")
        snapshot = {"subject": subject, "body": body, "recipients": recipients}
        digest = hashlib.sha256(
            json.dumps(snapshot, sort_keys=True).encode()
        ).hexdigest()
        return {
            **snapshot,
            "recipientCount": len(recipients),
            "volunteerCount": len(bookings),
            "fingerprint": digest,
            "emailEnabled": False,
        }

    def list_drafts(self):
        rows = self.store.list_drafts(self.clock())
        allowed = ("id", "subject", "body", "selector", "createdAt")
        return {
            "drafts": [
                {
                    **{key: row[key] for key in allowed},
                    "recipientCount": len(row["recipients"]),
                }
                for row in rows
            ]
        }

    def save_message(self, payload):
        preview = self.message_preview(payload)
        if preview["fingerprint"] != payload.get("fingerprint"):
            raise Problem(
                "Recipients or content changed. Preview again before saving.",
                "stale",
                409,
            )
        id = str(uuid.uuid4())
        expires = int(self.clock()) + 30 * 86400
        draft = {
            "pk": "DRAFT#" + id,
            "id": id,
            "subject": preview["subject"],
            "body": preview["body"],
            "recipients": preview["recipients"],
            "status": "draft_sending_disabled",
            "recordType": "messageDraft",
            "selector": payload["selector"],
            "createdAt": int(self.clock()),
            "actor": self.actor,
            "expiresAt": expires,
        }
        self.store.commit_records(
            [
                draft,
                self.audit(
                    "message_draft_saved",
                    id,
                    {"recipientCount": preview["recipientCount"]},
                    expires,
                ),
            ]
        )
        return {"id": id, "status": "draft_saved", "emailEnabled": False}
