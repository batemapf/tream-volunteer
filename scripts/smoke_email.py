"""Opt-in real SES test to the owner only. Never run automatically on deploy."""

import json
import os
import secrets
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from store import DynamoStore

store = DynamoStore()
origin, api = os.environ["SITE_URL"], os.environ["API_URL"]
token, key = secrets.token_urlsafe(32), str(uuid.uuid4())
print("::add-mask::" + token, flush=True)
booking_id = None


def call(method, path, body=None, auth=False):
    request = urllib.request.Request(
        api + path,
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={
            "Content-Type": "application/json",
            "Origin": origin,
            **({"Authorization": "Bearer " + token} if auth else {}),
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def wait_mail(kind):
    deadline = time.monotonic() + 200
    # Events are discoverable via their IDs on the private booking record.
    booking = store.get("BOOKING#" + booking_id)
    id = booking.get("lastNotificationId") if kind == "changed" else None
    if kind == "confirmation":
        id = confirmation_id
    if kind == "cancellation":
        id = store.get("BOOKING#" + booking_id).get("cancelNotificationId")
    if not id:
        raise AssertionError("Missing notification identifier")
    while time.monotonic() < deadline:
        row = store.get("MAIL#" + id)
        if row["status"] == "sent":
            assert row.get("messageId"), "SES message ID missing"
            assert (
                "manageToken" not in row and "recipient" not in row
            ), "Sensitive payload retained after send"
            print("PASS: SES accepted " + kind + " notification", flush=True)
            return
        if row["status"] in ("failed", "suppressed", "disabled"):
            raise AssertionError("Notification failed: " + row["status"])
        time.sleep(5)
    raise AssertionError("Timed out waiting for " + kind + " mail")


def browser(action):
    subprocess.run(
        ["node", "scripts/browser_email.cjs"],
        check=True,
        env={
            **os.environ,
            "BOOKING_ID": booking_id,
            "MANAGE_TOKEN": token,
            "EMAIL_ACTION": action,
        },
    )


try:
    assert call("GET", "/health")["emailEnabled"] is True
    result = call(
        "POST",
        "/bookings",
        {
            "email": "batemapf@gmail.com",
            "selections": [
                {
                    "shiftId": "8",
                    "start": 9,
                    "end": 11,
                    "name": "Tream Email Test",
                    "shareName": False,
                    "participantId": str(uuid.uuid4()),
                    "idempotencyKey": key,
                    "manageToken": token,
                    "subJobs": ["sales"],
                }
            ],
        },
    )["results"][0]
    assert result["status"] == "booked", "Test booking failed"
    booking_id, confirmation_id = result["bookingId"], result["notificationId"]
    wait_mail("confirmation")
    before = store.get("BOOKING#" + booking_id)
    browser("view")
    assert store.get("BOOKING#" + booking_id) == before, "Opening link mutated booking"
    browser("change")
    changed = store.get("BOOKING#" + booking_id)
    assert changed["shiftId"] == "9" and changed["start"] == 14 and changed["end"] == 16
    assert not any(p["id"] == booking_id for p in store.get("SHIFT#8")["roster"])
    wait_mail("changed")
    browser("cancel")
    assert store.get("BOOKING#" + booking_id)["status"] == "canceled"
    assert not any(p["id"] == booking_id for p in store.get("SHIFT#9")["roster"])
    wait_mail("cancellation")
    print(
        "PASS: book → notify → read-only email link → rebook in mobile UI → notify → cancel in mobile UI → notify. Verify arrival in the real inbox separately."
    )
finally:
    if booking_id:
        booking = store.get("BOOKING#" + booking_id)
        if booking and booking["status"] == "active":
            call("POST", "/bookings/" + booking_id + "/cancel", {}, auth=True)
    print(
        "Email test signup is canceled; private delivery receipts retained for diagnostics."
    )
