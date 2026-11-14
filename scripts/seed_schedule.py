"""Idempotent draft schedule import. Never overwrites live edits or bookings."""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from domain import epoch, retention_expiry, normalize_sub_jobs
from store import DynamoStore
from botocore.exceptions import ClientError

store = DynamoStore()
rows = json.loads(
    (Path(__file__).resolve().parents[1] / "backend/schedule-draft.json").read_text()
)
defaults = json.loads(
    (Path(__file__).resolve().parents[1] / "backend/job-defaults.json").read_text()
)
expiry = retention_expiry(epoch("2026-12-06", 19))
for row in rows:
    row["id"] = str(row["id"])
    sub_jobs = normalize_sub_jobs(
        row.get("subJobs", defaults.get(row["role"], {}).get("subJobs", []))
    )
    item = {
        **row,
        "pk": "SHIFT#" + row["id"],
        "revision": 0,
        "subJobs": sub_jobs,
        "roster": [],
        "open": True,
        "overflowPercent": row.get("overflowPercent", 0),
        "location": row.get("location", "Canal Park"),
        "attendance": {
            "incrementMinutes": 30,
            "minMinutes": 30,
            **row.get("attendance", {}),
        },
        "startAt": epoch(row["date"], row["start"]),
        "endAt": epoch(row["date"], row["end"]),
        "publicUntil": epoch("2026-12-07", 0),
        "expiresAt": expiry,
    }
    try:
        store.client.put_item(
            TableName=store.table,
            Item=store.encode(item),
            ConditionExpression="attribute_not_exists(pk)",
        )
    except ClientError as error:
        if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
    # Populate missing choices or migrate the exact original draft defaults.
    # Custom organizer choices and existing bookings stay unchanged.
    if sub_jobs:
        try:
            store.client.update_item(
                TableName=store.table,
                Key=store.encode({"pk": "SHIFT#" + row["id"]}),
                UpdateExpression="SET subJobs = :options, revision = revision + :one",
                ConditionExpression="attribute_exists(pk) AND (attribute_not_exists(subJobs) OR subJobs = :original)",
                ExpressionAttributeValues=store.encode(
                    {
                        ":options": sub_jobs,
                        ":one": 1,
                        ":original": normalize_sub_jobs(
                            [
                                {"id": "cashier", "label": "Cashier"},
                                {"id": "chainsaw", "label": "Chainsaw"},
                                {"id": "sales", "label": "Sales"},
                                {"id": "loading", "label": "Loading"},
                            ]
                        ),
                    }
                ),
            )
        except ClientError as error:
            if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
registry = {
    "pk": "EVENT#2026",
    "shiftIds": [str(r["id"]) for r in rows],
    "expiresAt": expiry,
}
try:
    store.client.put_item(
        TableName=store.table,
        Item=store.encode(registry),
        ConditionExpression="attribute_not_exists(pk)",
    )
except ClientError as error:
    if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
        raise
print("Draft schedule initialized; existing records left unchanged.")
