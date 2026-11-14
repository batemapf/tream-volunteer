"""Exercise the deployed development API, then remove only this run's test data."""

import concurrent.futures
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from domain import epoch, retention_expiry
from store import DynamoStore

base, origin = os.environ["API_URL"], os.environ["SITE_URL"]
store = DynamoStore()
keys = []
temporary_shift = "smoke-" + uuid.uuid4().hex


def call(method, path, payload=None, token=None, expected=200):
    headers = {"Origin": origin, "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    for attempt in range(5):
        req = urllib.request.Request(
            base + path,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=25) as response:
                status = response.status
                data = json.load(response)
        except urllib.error.HTTPError as error:
            status = error.code
            data = json.load(error)
        if status in (429, 503) and attempt < 4:
            time.sleep(1 + attempt)
            continue
        assert status == expected, f"{method} {path}: expected {expected}, got {status}"
        return data
    raise AssertionError("Request retries exhausted")


def selection(shift="0", **changes):
    item = {
        "shiftId": shift,
        "start": 10,
        "end": 11,
        "name": "Smoke PrivateName",
        "shareName": False,
        "idempotencyKey": str(uuid.uuid4()),
        "participantId": str(uuid.uuid4()),
        "manageToken": secrets.token_urlsafe(32),
        **changes,
    }
    keys.append("IDEMP#" + item["idempotencyKey"])
    return item


def book(items):
    return call(
        "POST", "/bookings", {"email": "smoke@example.com", "selections": items}
    )


try:
    assert call("GET", "/health")["emailEnabled"] is False
    before = call("GET", "/schedule")
    assert before["shifts"], "Schedule not seeded"
    valid = selection("8", start=9, end=11, subJobs=["cashier", "tree-prep"])
    mixed = book([selection("does-not-exist"), valid])
    assert [r["status"] for r in mixed["results"]] == ["failed", "booked"]
    booked = mixed["results"][1]
    assert [p["label"] for p in booked["subJobPreferences"]] == [
        "Cashiering",
        "Tree Prep (Chainsaw/Baling/Loading)",
    ], "Task choices not saved"
    private = store.get("BOOKING#" + booked["bookingId"])
    assert [p["id"] for p in private["subJobPreferences"]] == ["cashier", "tree-prep"]

    assert (
        book([valid])["results"][0]["bookingId"] == booked["bookingId"]
    ), "Retry created duplicate"
    serialized = json.dumps(call("GET", "/schedule"))
    for secret in [
        "Smoke PrivateName",
        "smoke@example.com",
        valid["manageToken"],
        "tokenHash",
        "participantId",
    ]:
        assert secret not in serialized, "Private data leaked"
    assert (
        call("GET", "/bookings/" + booked["bookingId"], token=valid["manageToken"])[
            "status"
        ]
        == "active"
    )
    call(
        "POST",
        "/bookings/" + booked["bookingId"] + "/cancel",
        {},
        token=secrets.token_urlsafe(32),
        expected=403,
    )
    call(
        "POST",
        "/bookings/" + booked["bookingId"] + "/cancel",
        {},
        token=valid["manageToken"],
    )
    # Independent fixture never appears in the public event registry.
    fixture = {
        **before["shifts"][0],
        "pk": "SHIFT#" + temporary_shift,
        "id": temporary_shift,
        "capacity": 1,
        "overflowPercent": 0,
        "revision": 0,
        "roster": [],
        "open": True,
        "endAt": epoch("2026-12-02", 15),
        "expiresAt": retention_expiry(epoch("2026-12-06", 19)),
        "publicUntil": epoch("2026-12-07", 0),
    }
    store.client.put_item(
        TableName=store.table,
        Item=store.encode(fixture),
        ConditionExpression="attribute_not_exists(pk)",
    )
    contenders = [selection(temporary_shift) for _ in range(5)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        outcomes = list(pool.map(lambda item: book([item])["results"][0], contenders))
    assert sum(r["status"] == "booked" for r in outcomes) == 1, "Atomic capacity failed"
    later = selection(temporary_shift, start=11, end=12)
    assert (
        book([later])["results"][0]["status"] == "booked"
    ), "Departure consumed later capacity"
    print(
        "PASS: deployed health, schedule, batch partial success, idempotency, private projection, management authorization, cancellation, competing last-space claims and partial departure."
    )
finally:
    # Idempotency records recover booking IDs even if a response was interrupted.
    for key in keys:
        idem = store.get(key)
        if idem:
            result = idem["result"]
            booking_id = result["bookingId"]
            booking = store.get("BOOKING#" + booking_id)
            if (
                booking
                and booking["shiftId"] != temporary_shift
                and booking["status"] == "active"
            ):
                for item in [valid] if "valid" in globals() else []:
                    if item["idempotencyKey"] == key.removeprefix("IDEMP#"):
                        call(
                            "POST",
                            "/bookings/" + booking_id + "/cancel",
                            {},
                            token=item["manageToken"],
                        )
            for prefix in ("BOOKING#", "OUTBOX#"):
                store.client.delete_item(
                    TableName=store.table, Key=store.encode({"pk": prefix + booking_id})
                )
        store.client.delete_item(TableName=store.table, Key=store.encode({"pk": key}))
    store.client.delete_item(
        TableName=store.table, Key=store.encode({"pk": "SHIFT#" + temporary_shift})
    )
    print("Smoke-test private records and temporary capacity fixture cleaned up.")
