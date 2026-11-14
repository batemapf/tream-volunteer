"""Approved one-time unloading correction; atomic, idempotent, no contact logging."""

import copy
import secrets
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from store import DynamoStore
from service import Contention
from domain import epoch, token_hash
from recovery import contact_hash
from mail import notification

store = DynamoStore()
for attempt in range(8):
    old = store.get("SHIFT#1")
    if not old:
        raise RuntimeError("Unloading shift is missing")
    if old["start"] == 16 and old["end"] == 18:
        assert all(
            16 <= r["start"] < r["end"] <= 18 for r in old["roster"]
        ), "Existing unloading hours need review"
        print("Unloading is already 4–6 p.m.; no duplicate notifications created.")
        break
    assert (old["date"], old["start"], old["end"]) == (
        "2026-12-02",
        10,
        13,
    ), "Unloading changed since approval; review before migration"
    assert (
        len(old["roster"]) == 2
    ), "Unloading signup count changed since approval; review before migration"
    bookings = store.get_many(["BOOKING#" + r["id"] for r in old["roster"]])
    assert all(
        b and b["status"] == "active" and b["shiftId"] == "1" for b in bookings
    ), "Unloading commitments changed"
    now = int(time.time())
    new = copy.deepcopy(old)
    new.update(
        start=16,
        end=18,
        startAt=epoch(old["date"], 16),
        endAt=epoch(old["date"], 18),
        revision=old["revision"] + 1,
    )
    new["roster"] = []
    operations = [
        store.put_op(new, "revision = :revision", {":revision": old["revision"]})
    ]
    notification_ids = []
    for booking in bookings:
        updated = {
            **booking,
            "start": 16,
            "end": 18,
            "startAt": epoch(old["date"], 16),
            "endAt": epoch(old["date"], 18),
            "revision": booking.get("revision", 0) + 1,
        }
        new["roster"].append(
            {
                "id": booking["id"],
                "start": 16,
                "end": 18,
                "publicName": booking["publicName"],
            }
        )
        token = secrets.token_urlsafe(32)
        grant = {
            "pk": "RECOVERYACCESS#" + token_hash(token),
            "contactHash": contact_hash(booking["email"]),
            "bookingId": booking["id"],
            "expiresAt": booking["expiresAt"],
        }
        outbox = notification(updated, new, "changed", token, now)
        updated["lastNotificationId"] = outbox["id"]
        notification_ids.append(outbox["id"])
        op = store.put_op(
            updated,
            "#status = :active AND (attribute_not_exists(revision) OR revision = :revision)",
            {":active": "active", ":revision": booking.get("revision", 0)},
        )
        op["Put"]["ExpressionAttributeNames"] = {"#status": "status"}
        operations.append(op)
        if outbox["status"] == "pending":
            outbox["notice"] = (
                "The unloading shift has been corrected to 4–6 p.m. on December 2. Your signup has been updated. If this time does not work for you, please change or cancel using the link below."
            )
        operations.extend(
            [
                store.put_op(grant, "attribute_not_exists(pk)"),
                store.put_op(outbox, "attribute_not_exists(pk)"),
            ]
        )
    # Encode the complete roster after constructing every revised commitment.
    operations[0] = store.put_op(
        new, "revision = :revision", {":revision": old["revision"]}
    )
    audit = {
        "pk": "AUDIT#unloading-time-correction-2026",
        "action": "unloading_time_corrected",
        "actor": "owner-approved-migration",
        "createdAt": now,
        "expiresAt": old["expiresAt"],
        "updatedBookings": len(bookings),
        "notificationIds": notification_ids,
    }
    operations.append(store.put_op(audit, "attribute_not_exists(pk)"))
    try:
        store.transact(operations)
        print(
            "Unloading corrected to 4–6 p.m.; two commitments updated and correction notifications created."
        )
        break
    except Contention:
        time.sleep(0.1)
else:
    raise RuntimeError("Unloading changed repeatedly; no partial updates applied")
