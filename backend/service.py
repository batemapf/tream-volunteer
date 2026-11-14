"""Transactional service. Store implementations must compare shift revisions."""

import copy
import hmac
import re
import time
import uuid
from domain import (
    Problem,
    effective_capacity,
    epoch,
    fits,
    fingerprint,
    public_name,
    token_hash,
    validate_interval,
    validate_selection,
    task_preferences,
)


class Contention(Exception):
    pass


class BookingService:
    def __init__(self, store, clock=time.time):
        self.store, self.clock = store, clock

    def book(self, email, raw):
        email = email.strip().lower() if isinstance(email, str) else ""
        if len(email) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
            raise Problem("Enter a valid contact email.")
        selection = validate_selection(raw)
        digest = fingerprint(email, selection)
        for attempt in range(8):
            previous = self.store.get("IDEMP#" + selection["idempotencyKey"])
            if previous:
                if previous["fingerprint"] != digest:
                    raise Problem(
                        "This submission identifier was already used for different details.",
                        "idempotency_conflict",
                        409,
                    )
                if previous["expiresAt"] <= self.clock():
                    raise Problem("This signup has expired.", "expired", 410)
                return previous["result"]
            shift = self.store.get("SHIFT#" + selection["shiftId"])
            if (
                not shift
                or not shift.get("open", False)
                or shift["endAt"] <= self.clock()
            ):
                raise Problem("This shift is not accepting signups.", "closed", 409)
            preferences = task_preferences(shift, selection)
            start, end = selection.get("start"), selection.get("end")
            start, end = validate_interval(shift, start, end)
            if not fits(shift, start, end):
                raise Problem(
                    "Part of this window is full. Try another time.", "full", 409
                )
            if len(shift["roster"]) >= 300:
                raise Problem(
                    "Please contact the organizer for this shift.", "roster_limit", 409
                )
            booking_id = str(uuid.uuid4())
            result = {
                "status": "booked",
                "bookingId": booking_id,
                "shiftId": shift["id"],
                "subJobPreferences": preferences,
                "start": start,
                "end": end,
                "publicName": public_name(
                    selection["name"], selection.get("shareName", False)
                ),
            }
            booking = {
                "pk": "BOOKING#" + booking_id,
                "id": booking_id,
                "shiftId": shift["id"],
                "participantId": selection["participantId"],
                "email": email,
                "name": selection["name"],
                "publicName": result["publicName"],
                "subJobPreferences": preferences,
                "start": start,
                "end": end,
                "startAt": epoch(shift["date"], start),
                "endAt": epoch(shift["date"], end),
                "status": "active",
                "tokenHash": token_hash(selection["manageToken"]),
                "expiresAt": shift["expiresAt"],
                "createdAt": int(self.clock()),
            }
            new_shift = copy.deepcopy(shift)
            new_shift["revision"] += 1
            new_shift["roster"].append(
                {
                    "id": booking_id,
                    "start": start,
                    "end": end,
                    "publicName": result["publicName"],
                }
            )
            idem = {
                "pk": "IDEMP#" + selection["idempotencyKey"],
                "fingerprint": digest,
                "result": result,
                "expiresAt": shift["expiresAt"],
            }
            # No outbound email in this development slice. Private outbox survives provider unavailability.
            outbox = {
                "pk": "OUTBOX#" + booking_id,
                "bookingId": booking_id,
                "kind": "confirmation",
                "status": "pending_disabled",
                "expiresAt": min(shift["expiresAt"], int(self.clock()) + 30 * 86400),
            }
            try:
                self.store.commit_booking(shift, new_shift, booking, idem, outbox)
                return result
            except Contention:
                time.sleep(min(0.005 * 2**attempt, 0.1))
        raise Problem("Another signup changed this shift. Please retry.", "retry", 409)

    def batch(self, email, selections):
        if not isinstance(selections, list) or not 1 <= len(selections) <= 20:
            raise Problem("Choose between 1 and 20 commitments.")
        results = []
        for raw in selections:
            key = raw.get("idempotencyKey") if isinstance(raw, dict) else None
            try:
                results.append({"idempotencyKey": key, **self.book(email, raw)})
            except Problem as error:
                results.append(
                    {
                        "idempotencyKey": key,
                        "status": "failed",
                        "code": error.code,
                        "message": str(error),
                    }
                )
        return {"results": results, "emailEnabled": False}

    def authorize(self, booking_id, token):
        if not re.fullmatch(r"[a-zA-Z0-9_-]{43}", token or ""):
            raise Problem(
                "This management link is invalid or expired.", "unauthorized", 403
            )
        booking = self.store.get("BOOKING#" + booking_id)
        if (
            not booking
            or booking["expiresAt"] <= self.clock()
            or not hmac.compare_digest(booking["tokenHash"], token_hash(token))
        ):
            raise Problem(
                "This management link is invalid or expired.", "unauthorized", 403
            )
        return booking

    def managed(self, booking_id, token):
        booking = self.authorize(booking_id, token)
        return {
            k: booking[k]
            for k in ("id", "shiftId", "start", "end", "publicName", "status")
        }

    def cancel(self, booking_id, token):
        for attempt in range(8):
            booking = self.authorize(booking_id, token)
            if booking["status"] == "canceled":
                return {"status": "canceled"}
            shift = self.store.get("SHIFT#" + booking["shiftId"])
            new_shift = copy.deepcopy(shift)
            new_shift["revision"] += 1
            new_shift["roster"] = [
                p for p in new_shift["roster"] if p["id"] != booking_id
            ]
            try:
                self.store.commit_cancel(shift, new_shift, booking)
                return {"status": "canceled"}
            except Contention:
                time.sleep(min(0.005 * 2**attempt, 0.1))
        raise Problem("The shift changed. Please retry.", "retry", 409)


def public_shift(shift, now):
    allowed = (
        "id",
        "date",
        "name",
        "role",
        "start",
        "end",
        "capacity",
        "flex",
        "overflowPercent",
        "attendance",
        "location",
    )
    result = {k: shift[k] for k in allowed if k in shift}
    result["subJobs"] = [
        {key: option[key] for key in ("id", "label", "description") if key in option}
        for option in shift.get("subJobs", [])
        if option.get("enabled", True)
    ]
    result["effectiveCapacity"] = effective_capacity(shift)
    result["open"] = shift.get("open", False) and shift["endAt"] > now
    result["roster"] = (
        [{k: p[k] for k in ("start", "end", "publicName")} for p in shift["roster"]]
        if shift["publicUntil"] > now
        else []
    )
    return result
