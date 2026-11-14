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
from recovery import contact_hash
from domain import token_hash

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


def browser(action, site=None):
    subprocess.run(
        ["node", "scripts/browser_email.cjs"],
        check=True,
        env={
            **os.environ,
            "SITE_URL": site or origin,
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
                    "phone": "+1 202-555-0123",
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
    requested_at = int(time.time())
    browser("recover")
    summaries = store.client.scan(
        TableName=store.table,
        ConsistentRead=True,
        FilterExpression="#kind = :kind AND recoveryContactHash = :hash AND createdAt >= :since",
        ExpressionAttributeNames={"#kind": "kind"},
        ExpressionAttributeValues=store.encode(
            {
                ":kind": "recovery",
                ":hash": contact_hash("batemapf@gmail.com"),
                ":since": requested_at,
            }
        ),
    )["Items"]
    summaries = [store.decode(row) for row in summaries]
    assert summaries, "Recovery email was not created"
    summary = max(summaries, key=lambda row: row["createdAt"])
    recovered_token = summary.get("manageToken")
    if recovered_token:
        print("::add-mask::" + recovered_token, flush=True)
        request = urllib.request.Request(
            api + "/bookings/" + booking_id,
            headers={"Authorization": "Bearer " + recovered_token, "Origin": origin},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            assert json.load(response)["id"] == booking_id
        assert any(
            item["bookingId"] == booking_id for item in summary["items"]
        ), "New signup missing from summary"
    deadline = time.monotonic() + 200
    while time.monotonic() < deadline:
        receipt = store.get(summary["pk"])
        if receipt["status"] == "sent":
            assert "items" not in receipt and "manageToken" not in receipt
            print(
                "PASS: SES accepted signup recovery email; private summary payload cleared",
                flush=True,
            )
            break
        assert receipt["status"] not in (
            "failed",
            "suppressed",
        ), "Recovery delivery failed"
        time.sleep(5)
    else:
        raise AssertionError("Recovery email delivery timed out")
    before = store.get("BOOKING#" + booking_id)
    browser("view")
    if os.environ.get("LEGACY_SITE_URL"):
        browser("view", os.environ["LEGACY_SITE_URL"])
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
        "PASS: book → notify → email recovery → read-only email link → rebook in mobile UI → notify → cancel in mobile UI → notify. Verify arrival in the real inbox separately."
    )
finally:
    if booking_id:
        booking = store.get("BOOKING#" + booking_id)
        if booking and booking["status"] == "active":
            call("POST", "/bookings/" + booking_id + "/cancel", {}, auth=True)
    print(
        "Email test signup is canceled; private delivery receipts retained for diagnostics."
    )
