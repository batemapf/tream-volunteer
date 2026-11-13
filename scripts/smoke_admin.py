"""Live Cognito + organizer API integration. Temporary user and synthetic records only."""

import json
import os
import secrets
import sys
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
import boto3

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from store import DynamoStore
from admin import conflict_key

base, origin = os.environ["API_URL"], os.environ["SITE_URL"]
pool, client = os.environ["ORGANIZER_POOL_ID"], os.environ["ORGANIZER_CLIENT_ID"]
cognito = boto3.client("cognito-idp", region_name="us-east-2")
store = DynamoStore()
username = "smoke-" + uuid.uuid4().hex
password = "Tream!7aA" + secrets.token_urlsafe(24)
contact_email = "organizer-smoke-" + uuid.uuid4().hex + "@example.com"
new_password = "Tream!8bB" + secrets.token_urlsafe(24)
print("::add-mask::" + password)
print("::add-mask::" + new_password)
created = False
token = None
selections = []
bookings = []
draft_id = None
browser_draft_id = None
review_key = None


def call(method, path, payload=None, bearer=None, expected=200):
    headers = {"Origin": origin, "Content-Type": "application/json"}
    if bearer:
        headers["Authorization"] = "Bearer " + bearer
    for attempt in range(5):
        req = urllib.request.Request(
            base + path,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                status = response.status
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            status = error.code
            raw = error.read().decode("utf-8")
        if status in (429, 503) and attempt < 4:
            time.sleep(1 + attempt)
            continue
        assert status == expected, f"{method} {path}: expected {expected}, got {status}"
        return raw if path.startswith("/admin/export.csv") else json.loads(raw)
    raise AssertionError("Request retries exhausted")


def create_selection(shift, name):
    item = {
        "shiftId": shift,
        "name": name,
        "shareName": False,
        "start": 10,
        "end": 11,
        "idempotencyKey": str(uuid.uuid4()),
        "participantId": str(uuid.uuid4()),
        "manageToken": secrets.token_urlsafe(32),
    }
    selections.append(item)
    return item


try:
    call("GET", "/admin/overview", expected=401)
    cognito.admin_create_user(
        UserPoolId=pool,
        Username=username,
        TemporaryPassword=password,
        MessageAction="SUPPRESS",
    )
    created = True
    challenge = cognito.initiate_auth(
        ClientId=client,
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters={"USERNAME": username, "PASSWORD": password},
    )
    assert (
        challenge.get("ChallengeName") == "NEW_PASSWORD_REQUIRED"
    ), "Temporary password challenge missing"
    auth = cognito.respond_to_auth_challenge(
        ClientId=client,
        ChallengeName="NEW_PASSWORD_REQUIRED",
        Session=challenge["Session"],
        ChallengeResponses={
            "USERNAME": challenge.get("ChallengeParameters", {}).get(
                "USER_ID_FOR_SRP", username
            ),
            "NEW_PASSWORD": new_password,
        },
    )
    token = auth["AuthenticationResult"]["AccessToken"]
    print("::add-mask::" + token)
    call("GET", "/admin/overview", bearer=token, expected=403)
    cognito.admin_add_user_to_group(
        UserPoolId=pool, Username=username, GroupName="organizers"
    )
    auth = cognito.initiate_auth(
        ClientId=client,
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters={"USERNAME": username, "PASSWORD": new_password},
    )
    token = auth["AuthenticationResult"]["AccessToken"]
    print("::add-mask::" + token)
    before = call("GET", "/admin/overview", bearer=token)
    first = next(s for s in before["shifts"] if s["id"] == "0")
    # No-op edit still exercises validated JWT, revision check, DynamoDB transaction and audit.
    call(
        "POST",
        "/admin/shifts/0",
        {"revision": first["revision"], "capacity": first["capacity"]},
        token,
    )
    call(
        "POST",
        "/admin/shifts/0",
        {"revision": first["revision"], "capacity": first["capacity"]},
        token,
        expected=409,
    )
    batch = call(
        "POST",
        "/bookings",
        {
            "email": contact_email,
            "selections": [
                create_selection("0", "=Smoke Formula"),
                create_selection("1", "Second Family Member"),
            ],
        },
    )
    bookings = [r for r in batch["results"] if r["status"] == "booked"]
    assert len(bookings) == 2, "Synthetic organizer bookings failed"
    overview = call("GET", "/admin/overview", bearer=token)
    pair = next(
        c
        for c in overview["conflicts"]
        if set(c["bookingIds"]) == {b["bookingId"] for b in bookings}
    )
    assert pair["kind"] == "shared_email"
    review_key = pair["id"]
    call(
        "POST",
        "/admin/conflicts/" + review_key + "/review",
        {"note": "Synthetic test: two family members."},
        token,
    )
    reviewed = call("GET", "/admin/overview", bearer=token)
    assert next(c for c in reviewed["conflicts"] if c["id"] == review_key)["reviewed"]
    exported = call("GET", "/admin/export.csv?q=" + contact_email, bearer=token)
    assert "'=Smoke Formula" in exported, "CSV formula protection absent"
    payload = {
        "subject": "Synthetic draft",
        "body": "No email should be sent.",
        "selector": {
            "mode": "selected",
            "bookingIds": [b["bookingId"] for b in bookings],
        },
    }
    preview = call("POST", "/admin/messages/preview", payload, token)
    assert (
        preview["recipientCount"] == 1 and preview["volunteerCount"] == 2
    ), "Family recipient deduplication failed"
    draft = call(
        "POST",
        "/admin/messages",
        {**payload, "fingerprint": preview["fingerprint"]},
        token,
    )
    draft_id = draft["id"]
    assert draft["emailEnabled"] is False
    if os.environ.get("PLAYWRIGHT_MODULE"):
        browser_env = {
            **os.environ,
            "TREAM_TEST_USERNAME": username,
            "TREAM_TEST_PASSWORD": new_password,
            "TREAM_TEST_EMAIL": contact_email,
        }
        checked = subprocess.run(
            ["node", "scripts/browser_organizer.cjs"],
            env=browser_env,
            text=True,
            capture_output=True,
        )
        for line in checked.stdout.splitlines():
            if line.startswith("{"):
                browser_draft_id = json.loads(line).get("browserDraftId")
            elif line.startswith("PASS:"):
                print(line)
        if checked.returncode:
            print(checked.stderr)
            raise AssertionError("Organizer browser integration failed")
    for booking in bookings:
        call("POST", "/admin/bookings/" + booking["bookingId"] + "/cancel", {}, token)
    public = json.dumps(call("GET", "/schedule"))
    assert contact_email not in public and "=Smoke Formula" not in public
    print(
        "PASS: no-token rejection, first-password challenge, non-organizer rejection, organizer access, shift revisions, conflict review, private export/formula protection, family-recipient preview, disabled draft and admin cancellation."
    )
finally:
    for selection in selections:
        idem = store.get("IDEMP#" + selection["idempotencyKey"])
        if idem:
            id = idem["result"]["bookingId"]
            booking = store.get("BOOKING#" + id)
            if booking and booking["status"] == "active":
                call(
                    "POST", "/bookings/" + id + "/cancel", {}, selection["manageToken"]
                )
            for prefix in ("BOOKING#", "OUTBOX#"):
                store.client.delete_item(
                    TableName=store.table, Key=store.encode({"pk": prefix + id})
                )
        store.client.delete_item(
            TableName=store.table,
            Key=store.encode({"pk": "IDEMP#" + selection["idempotencyKey"]}),
        )
    if browser_draft_id:
        store.client.delete_item(
            TableName=store.table, Key=store.encode({"pk": "DRAFT#" + browser_draft_id})
        )
    for key in (
        ("DRAFT#" + draft_id) if draft_id else None,
        ("CONFLICT#" + review_key) if review_key else None,
    ):
        if key:
            store.client.delete_item(
                TableName=store.table, Key=store.encode({"pk": key})
            )
    if created:
        cognito.admin_delete_user(UserPoolId=pool, Username=username)
    print(
        "Temporary organizer user and synthetic private bookings/draft/review cleaned up. Audit entries remain under their retention limits."
    )
