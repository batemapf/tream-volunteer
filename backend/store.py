"""DynamoDB persistence; private records never become public API responses."""
import json
import os
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
        return json.loads(json.dumps(obj, default=lambda x: int(x) if x % 1 == 0 else float(x)))

    def get(self, key):
        result = self.client.get_item(TableName=self.table, Key=self.encode({"pk": key}), ConsistentRead=True)
        return self.decode(result["Item"]) if "Item" in result else None

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
            if error.response["Error"]["Code"] in ("TransactionCanceledException", "TransactionConflictException"):
                reasons = error.response.get("CancellationReasons", [])
                if not reasons or all(r.get("Code") in (None, "None", "ConditionalCheckFailed", "TransactionConflict") for r in reasons):
                    raise Contention() from None
            raise

    def commit_booking(self, old, new, booking, idem, outbox):
        self.transact([self.put_op(new, "revision = :revision", {":revision": old["revision"]}), self.put_op(booking, "attribute_not_exists(pk)"), self.put_op(idem, "attribute_not_exists(pk)"), self.put_op(outbox, "attribute_not_exists(pk)")])

    def commit_cancel(self, old, new, booking):
        self.transact([
            self.put_op(new, "revision = :revision", {":revision": old["revision"]}),
            {"Update": {"TableName": self.table, "Key": self.encode({"pk": booking["pk"]}), "UpdateExpression": "SET #status = :canceled", "ConditionExpression": "#status = :active", "ExpressionAttributeNames": {"#status": "status"}, "ExpressionAttributeValues": self.encode({":canceled": "canceled", ":active": "active"})}}
        ])
