"""Explicit owner-requested reset. Preserve schedule/configuration and admin users."""

import argparse
import copy
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
import boto3

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from store import DynamoStore

STATE = Path(os.environ["RESET_STATE_FILE"])
FUNCTIONS = ("tream-dev-api", "tream-dev-mail")


def restore():
    if not STATE.exists():
        return
    client = boto3.client("lambda")
    for name, desired in json.loads(STATE.read_text()).items():
        current = client.get_function_concurrency(FunctionName=name).get(
            "ReservedConcurrentExecutions"
        )
        if current == desired:
            continue
        if desired is None:
            client.delete_function_concurrency(FunctionName=name)
        else:
            client.put_function_concurrency(
                FunctionName=name, ReservedConcurrentExecutions=desired
            )
    print("API and mail-worker concurrency restored.")


def scan(store):
    rows = []
    cursor = None
    while True:
        args = {"TableName": store.table, "ConsistentRead": True}
        if cursor:
            args["ExclusiveStartKey"] = cursor
        page = store.client.scan(**args)
        rows.extend(store.decode(row) for row in page.get("Items", []))
        cursor = page.get("LastEvaluatedKey")
        if not cursor:
            return rows


def main():
    if os.environ.get("RESET_CONFIRMATION") != "CLEAR_TEST_SIGNUPS":
        raise RuntimeError("Explicit reset confirmation is required")
    store = DynamoStore()
    assert store.table == "tream-dev-data", "Unexpected target table"
    client = boto3.client("lambda")
    original = {
        name: client.get_function_concurrency(FunctionName=name).get(
            "ReservedConcurrentExecutions"
        )
        for name in FUNCTIONS
    }
    STATE.write_text(json.dumps(original))
    try:
        for name in FUNCTIONS:
            client.put_function_concurrency(
                FunctionName=name, ReservedConcurrentExecutions=0
            )
        # Both handlers have 25-second timeouts. Drain prior invocations first.
        time.sleep(30)
        before = scan(store)
        counts = Counter(row["pk"].split("#", 1)[0] for row in before)
        print("Record counts before reset: " + json.dumps(dict(counts), sort_keys=True))
        known = {
            "SHIFT",
            "EVENT",
            "BOOKING",
            "IDEMP",
            "MAIL",
            "OUTBOX",
            "RECOVERYACCESS",
            "RECOVERYRATE",
            "CONFLICT",
            "DRAFT",
            "MAILFEEDBACK",
            "MAILWORKER",
            "AUDIT",
            "SUPPRESS",
        }
        assert set(counts) <= known, "Unexpected record type: review before deleting"
        preserved = {
            row["pk"]: copy.deepcopy(row)
            for row in before
            if row["pk"].startswith(("SHIFT#", "EVENT#"))
        }
        for row in before:
            if not row["pk"].startswith("SHIFT#"):
                continue
            store.client.update_item(
                TableName=store.table,
                Key=store.encode({"pk": row["pk"]}),
                UpdateExpression="SET roster = :empty, revision = revision + :one",
                ConditionExpression="revision = :revision",
                ExpressionAttributeValues=store.encode(
                    {":empty": [], ":one": 1, ":revision": row["revision"]}
                ),
            )
        deleted = Counter()
        keep_audit = "AUDIT#unloading-time-correction-2026"
        for row in before:
            key = row["pk"]
            kind = key.split("#", 1)[0]
            if kind in ("SHIFT", "EVENT", "SUPPRESS"):
                continue
            if key == keep_audit:
                # Preserve only the completed migration guard, with no booking/mail IDs.
                clean = {
                    k: row[k]
                    for k in ("pk", "action", "actor", "createdAt", "expiresAt")
                    if k in row
                }
                clean.update(
                    noticeRepairVersion=1, updatedBookings=0, notificationIds=[]
                )
                store.client.put_item(TableName=store.table, Item=store.encode(clean))
                continue
            if kind == "AUDIT" and row.get("kind") == "shift_edited":
                continue
            store.client.delete_item(
                TableName=store.table, Key=store.encode({"pk": key})
            )
            deleted[kind] += 1
        after = scan(store)
        remove_types = {
            "BOOKING",
            "IDEMP",
            "MAIL",
            "OUTBOX",
            "RECOVERYACCESS",
            "RECOVERYRATE",
            "CONFLICT",
            "DRAFT",
            "MAILFEEDBACK",
            "MAILWORKER",
        }
        assert not any(
            r["pk"].split("#", 1)[0] in remove_types for r in after
        ), "Signup-related records remain"
        actual = {r["pk"]: r for r in after if r["pk"] in preserved}
        assert set(actual) == set(preserved), "Schedule or event record missing"
        for key, previous in preserved.items():
            current = actual[key]
            if key.startswith("SHIFT#"):
                assert current["roster"] == [], "Shift still contains volunteers"
                assert {
                    k: v for k, v in current.items() if k not in ("revision", "roster")
                } == {
                    k: v for k, v in previous.items() if k not in ("revision", "roster")
                }, "Schedule configuration changed"
            else:
                assert current == previous, "Event configuration changed"
        print(
            "Deleted test signup records: " + json.dumps(dict(deleted), sort_keys=True)
        )
        print(
            json.dumps(
                {
                    "verified": True,
                    "scheduleRecordsPreserved": len(preserved),
                    "activeSignupCount": 0,
                    "privateBookingCount": 0,
                    "pendingNotifications": 0,
                    "organizerAccounts": "untouched",
                    "deliverySuppressions": "preserved",
                }
            )
        )
    finally:
        restore()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--restore", action="store_true")
    args = parser.parse_args()
    if args.restore:
        restore()
    else:
        main()
