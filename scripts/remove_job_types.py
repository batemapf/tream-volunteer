"""Remove obsolete job-type metadata without changing hours, choices or bookings."""

import sys
from pathlib import Path
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from store import DynamoStore

store = DynamoStore()
registry = store.get("EVENT#2026") or {}
removed = 0
for id in registry.get("shiftIds", []):
    try:
        store.client.update_item(
            TableName=store.table,
            Key=store.encode({"pk": "SHIFT#" + id}),
            UpdateExpression="SET revision = revision + :one REMOVE #role",
            ConditionExpression="attribute_exists(#role)",
            ExpressionAttributeNames={"#role": "role"},
            ExpressionAttributeValues=store.encode({":one": 1}),
        )
        removed += 1
    except ClientError as error:
        if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
print(f"Removed obsolete job type from {removed} shifts; other fields unchanged.")
