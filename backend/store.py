"""DynamoDB persistence; private records never become public API responses."""

import json
import os
import time
from decimal import Decimal
import boto3
from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
from botocore.exceptions import ClientError
from service import Contention


class DynamoStore:
    def __init__(self):
        self.client = boto3.client("dynamodb")
        self.table = os.environ["TABLE_NAME"]
        self.serializer, self.deserializer = TypeSerializer(), TypeDeserializer()

    def encode(self, item):
        normalized = json.loads(json.dumps(item), parse_float=Decimal)
        return {k: self.serializer.serialize(v) for k, v in normalized.items()}

    def decode(self, item):
        obj = {k: self.deserializer.deserialize(v) for k, v in item.items()}
        return json.loads(
            json.dumps(obj, default=lambda x: int(x) if x % 1 == 0 else float(x))
        )

    def get(self, key):
        result = self.client.get_item(
            TableName=self.table, Key=self.encode({"pk": key}), ConsistentRead=True
        )
        return self.decode(result["Item"]) if "Item" in result else None

    def get_many(self, keys):
        unique = list(dict.fromkeys(keys))
        found = {}
        for start in range(0, len(unique), 100):
            pending = {
                self.table: {
                    "Keys": [
                        self.encode({"pk": key}) for key in unique[start : start + 100]
                    ],
                    "ConsistentRead": True,
                }
            }
            for attempt in range(6):
                result = self.client.batch_get_item(RequestItems=pending)
                for raw in result.get("Responses", {}).get(self.table, []):
                    item = self.decode(raw)
                    found[item["pk"]] = item
                pending = result.get("UnprocessedKeys", {})
                if not pending:
                    break
                time.sleep(0.02 * 2**attempt)
            if pending:
                raise RuntimeError("Incomplete database read")
        return [found.get(key) for key in keys]

    def list_drafts(self, now):
        result = self.client.query(
            TableName=self.table,
            IndexName="recordType-createdAt",
            KeyConditionExpression="#type = :type",
            FilterExpression="expiresAt > :now",
            ExpressionAttributeNames={"#type": "recordType"},
            ExpressionAttributeValues=self.encode(
                {":type": "messageDraft", ":now": int(now)}
            ),
            ScanIndexForward=False,
            Limit=50,
        )
        return [self.decode(raw) for raw in result.get("Items", [])]

    def commit_records(self, records):
        self.transact([self.put_op(row) for row in records])

    def commit_admin_shift(self, old, new, audit):
        self.transact(
            [
                self.put_op(
                    new, "revision = :revision", {":revision": old["revision"]}
                ),
                self.put_op(audit, "attribute_not_exists(pk)"),
            ]
        )

    def put_op(self, item, condition=None, values=None):
        op = {"TableName": self.table, "Item": self.encode(item)}
        if condition:
            op["ConditionExpression"] = condition
        if values:
            op["ExpressionAttributeValues"] = self.encode(values)
        return {"Put": op}

    def transact(self, operations):
        try:
            self.client.transact_write_items(TransactItems=operations)
        except ClientError as error:
            if error.response["Error"]["Code"] in (
                "TransactionCanceledException",
                "TransactionConflictException",
            ):
                reasons = error.response.get("CancellationReasons", [])
                if not reasons or all(
                    r.get("Code")
                    in (None, "None", "ConditionalCheckFailed", "TransactionConflict")
                    for r in reasons
                ):
                    raise Contention() from None
            raise

    def commit_booking(self, old, new, booking, idem, outbox):
        self.transact(
            [
                self.put_op(
                    new, "revision = :revision", {":revision": old["revision"]}
                ),
                self.put_op(booking, "attribute_not_exists(pk)"),
                self.put_op(idem, "attribute_not_exists(pk)"),
                self.put_op(outbox, "attribute_not_exists(pk)"),
            ]
        )

    def commit_cancel(self, old, new, booking, audit=None):
        operations = [
            self.put_op(new, "revision = :revision", {":revision": old["revision"]}),
            {
                "Update": {
                    "TableName": self.table,
                    "Key": self.encode({"pk": booking["pk"]}),
                    "UpdateExpression": "SET #status = :canceled",
                    "ConditionExpression": "#status = :active",
                    "ExpressionAttributeNames": {"#status": "status"},
                    "ExpressionAttributeValues": self.encode(
                        {":canceled": "canceled", ":active": "active"}
                    ),
                }
            },
        ]
        if audit:
            operations.append(self.put_op(audit, "attribute_not_exists(pk)"))
        self.transact(operations)
