"""Transactional service. Store implementations must compare shift revisions."""

import copy
import hmac
import re
import time
import uuid
from mail import notification, enabled
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
            outbox = notification(
                booking, shift, "confirmation", selection["manageToken"], self.clock()
            )
            result["notificationId"] = outbox["id"]
            booking["revision"] = 0
            booking["lastNotificationId"] = outbox["id"]
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
        return {"results": results, "emailEnabled": enabled()}

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
            "revision": booking.get("revision", 0),
            **{
                k: booking[k]
                for k in (
                    "id",
                    "shiftId",
                    "start",
                    "end",
                    "publicName",
                    "status",
                    "name",
                    "subJobPreferences",
                )
                if k in booking
            },
        }

    def resend(self, booking_id, token):
        booking = self.authorize(booking_id, token)
        if booking["status"] != "active":
            raise Problem("This signup is canceled.", "canceled", 409)
        shift = self.store.get("SHIFT#" + booking["shiftId"])
        row = notification(booking, shift, "confirmation", token, self.clock())
        self.store.queue_resend(booking, row, int(self.clock()))
        return {"queued": row["status"] == "pending"}

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
                self.store.commit_cancel(
                    shift,
                    new_shift,
                    booking,
                    outbox=notification(
                        booking, shift, "cancellation", now=self.clock()
                    ),
                )
                return {"status": "canceled"}
            except Contention:
                time.sleep(min(0.005 * 2**attempt, 0.1))
        raise Problem("The shift changed. Please retry.", "retry", 409)

    def change(self, booking_id, token, raw):
        request_id = raw.get("requestId")
        if not isinstance(request_id, str) or not re.fullmatch(
            r"[a-zA-Z0-9_-]{16,80}", request_id
        ):
            raise Problem("Invalid change identifier.")
        for attempt in range(8):
            booking = self.authorize(booking_id, token)
            if booking.get("lastChangeId") == request_id:
                return self.managed(booking_id, token)
            if booking["status"] != "active":
                raise Problem(
                    "This signup is canceled. Choose a new shift on the board.",
                    "canceled",
                    409,
                )
            if type(raw.get("revision")) is not int or raw["revision"] != booking.get(
                "revision", 0
            ):
                raise Problem(
                    "This signup changed. Reload before editing.", "stale", 409
                )
            target_id = raw.get("shiftId")
            if not isinstance(target_id, str) or len(target_id) > 80:
                raise Problem("Choose a shift.")
            source = self.store.get("SHIFT#" + booking["shiftId"])
            target = self.store.get("SHIFT#" + target_id)
            if (
                not source
                or not target
                or not target.get("open")
                or target["endAt"] <= self.clock()
            ):
                raise Problem("This shift is not accepting signups.", "closed", 409)
            start, end = validate_interval(target, raw.get("start"), raw.get("end"))
            preferences = task_preferences(target, raw)
            available = copy.deepcopy(target)
            available["roster"] = [
                p for p in available["roster"] if p["id"] != booking_id
            ]
            if not fits(available, start, end) or len(available["roster"]) >= 300:
                raise Problem(
                    "That window is full. Your original signup is unchanged.",
                    "full",
                    409,
                )
            updated = {
                **booking,
                "shiftId": target_id,
                "start": start,
                "end": end,
                "startAt": epoch(target["date"], start),
                "endAt": epoch(target["date"], end),
                "subJobPreferences": preferences,
                "revision": booking.get("revision", 0) + 1,
                "lastChangeId": request_id,
            }
            new_target = available
            new_target["revision"] += 1
            new_target["roster"].append(
                {
                    "id": booking_id,
                    "start": start,
                    "end": end,
                    "publicName": booking["publicName"],
                }
            )
            changes = [(target, new_target)]
            if target_id != booking["shiftId"]:
                new_source = copy.deepcopy(source)
                new_source["revision"] += 1
                new_source["roster"] = [
                    p for p in source["roster"] if p["id"] != booking_id
                ]
                changes.append((source, new_source))
            outbox = notification(updated, target, "changed", token, self.clock())
            updated["lastNotificationId"] = outbox["id"]
            try:
                self.store.commit_change(changes, booking, updated, outbox)
                return self.managed(booking_id, token)
            except Contention:
                time.sleep(0.01)
        raise Problem("The schedule changed. Please retry.", "retry", 409)


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
