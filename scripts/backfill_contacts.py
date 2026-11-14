"""Idempotent private lookup backfill; never prints contacts or modifies bookings."""

import sys
import time
from pathlib import Path
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from store import DynamoStore
from recovery import contact_hash

store = DynamoStore()
cursor = None
updated = 0
while True:
    args = {
        "TableName": store.table,
        "ConsistentRead": True,
        "FilterExpression": "begins_with(pk, :prefix)",
        "ExpressionAttributeValues": store.encode({":prefix": "BOOKING#"}),
    }
    if cursor:
        args["ExclusiveStartKey"] = cursor
    page = store.client.scan(**args)
    for raw in page.get("Items", []):
        row = store.decode(raw)
        if row.get("contactHash") or row.get("expiresAt", 0) <= time.time():
            continue
        try:
            store.client.update_item(
                TableName=store.table,
                Key=store.encode({"pk": row["pk"]}),
                UpdateExpression="SET contactHash = :hash, createdAt = if_not_exists(createdAt, :created)",
                ConditionExpression="attribute_exists(pk) AND attribute_not_exists(contactHash) AND email = :email",
                ExpressionAttributeValues=store.encode(
                    {
                        ":hash": contact_hash(row["email"]),
                        ":created": row.get("createdAt", int(time.time())),
                        ":email": row["email"],
                    }
                ),
            )
            updated += 1
        except ClientError as e:
            if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
    cursor = page.get("LastEvaluatedKey")
    if not cursor:
        break
print(f"Private contact lookup initialized for {updated} existing records.")
