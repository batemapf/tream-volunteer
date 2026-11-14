"""Email-only recovery; no signup details or existence are returned publicly."""

import hashlib
import re
import secrets
import time
import uuid
from domain import Problem, token_hash
from mail import allowed

RESPONSE = {
    "message": "If that address has active signups, you’ll receive their links by email."
}


def contact_hash(email):
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()


def recover(store, email, source_ip, now=None):
    now = int(time.time() if now is None else now)
    email = email.strip().lower() if isinstance(email, str) else ""
    if len(email) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise Problem("Enter a valid email address.")
    hashed = contact_hash(email)
    if not store.claim_recovery(hashed, contact_hash(source_ip or "unknown"), now):
        return RESPONSE.copy()
    if not allowed(email):
        return RESPONSE.copy()
    bookings = [
        b
        for b in store.bookings_for_contact(hashed)
        if b.get("status") == "active" and b["expiresAt"] > now and b["endAt"] > now
    ]
    if not bookings:
        return RESPONSE.copy()
    bookings.sort(key=lambda b: (b["startAt"], b["name"], b["id"]))
    shifts = {
        s["id"]: s
        for s in store.get_many(
            ["SHIFT#" + id for id in dict.fromkeys(b["shiftId"] for b in bookings)]
        )
        if s
    }
    token = secrets.token_urlsafe(32)
    expiry = now + 86400
    records = [
        {
            "pk": "RECOVERYACCESS#" + token_hash(token),
            "contactHash": hashed,
            "expiresAt": expiry,
        }
    ]
    # One email per 40 commitments keeps family summaries below DynamoDB limits.
    for offset in range(0, len(bookings), 40):
        items = []
        for booking in bookings[offset : offset + 40]:
            shift = shifts.get(booking["shiftId"])
            if shift:
                items.append(
                    {
                        "bookingId": booking["id"],
                        "name": booking["name"],
                        "start": booking["start"],
                        "end": booking["end"],
                        "shift": {
                            k: shift.get(k, "") for k in ("name", "date", "location")
                        },
                    }
                )
        if not items:
            continue
        id = str(uuid.uuid4())
        records.append(
            {
                "pk": "MAIL#" + id,
                "id": id,
                "kind": "recovery",
                "recoveryContactHash": hashed,
                "status": "pending",
                "recordType": "mailPending",
                "recipient": email,
                "items": items,
                "manageToken": token,
                "attempts": 0,
                "createdAt": now,
                "expiresAt": expiry,
            }
        )
    # Grant contains only a contact hash; raw token lives only in short-lived outbox.
    store.commit_records(records[:1])
    for row in records[1:]:
        store.commit_records([row])
    return RESPONSE.copy()
