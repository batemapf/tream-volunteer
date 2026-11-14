"""Private transactional outbox with explicit test/public delivery modes."""

import json
import os
import time
import uuid
from urllib.parse import urlencode
from feedback import is_suppressed


def enabled():
    return os.environ.get("EMAIL_ENABLED") == "true"


def allowed(email):
    if not enabled():
        return False
    email = email.strip().lower()
    if os.environ.get("EMAIL_DELIVERY_MODE") == "public":
        domain = email.rsplit("@", 1)[-1]
        # Reserved documentation/test domains are used by CI, never real inboxes.
        reserved = (
            "example.com",
            "example.org",
            "example.net",
            "example",
            "invalid",
            "test",
            "localhost",
        )
        return "@" in email and not any(
            domain == item or domain.endswith("." + item) for item in reserved
        )
    return email in os.environ.get("EMAIL_TEST_RECIPIENTS", "").lower().split(",")


def notification(booking, shift, kind, token=None, now=None):
    now = int(time.time() if now is None else now)
    id = str(uuid.uuid4())
    queued = allowed(booking["email"])
    row = {
        "pk": "MAIL#" + id,
        "id": id,
        "bookingId": booking["id"],
        "kind": kind,
        "status": "pending" if queued else "disabled",
        "createdAt": now,
        "expiresAt": min(booking["expiresAt"], now + 7 * 86400),
    }
    if queued:
        row.update(
            recordType="mailPending",
            recipient=booking["email"],
            details={k: booking[k] for k in ("name", "start", "end")},
            shift={
                k: shift.get(k, "Canal Park" if k == "location" else "")
                for k in ("name", "date", "location")
            },
            attempts=0,
        )
        if token:
            # Short-lived, private SSE-encrypted outbox only; removed after delivery.
            row["manageToken"] = token
    return row


def content(row):
    labels = {
        "confirmation": "Signup confirmed",
        "changed": "Signup changed",
        "cancellation": "Signup canceled",
    }
    d, s = row["details"], row["shift"]

    def hour(value):
        h = int(value)
        return f"{h % 12 or 12}:{round((value-h)*60):02d} {'am' if h < 12 else 'pm'}"

    subject = f"Brent PTA holiday sale: {labels[row['kind']]}"
    body = f"{labels[row['kind']]}, {d['name']}.\n\n{s['name']}\n{s['date']}\n{hour(d['start'])}–{hour(d['end'])} Eastern\n{s['location']}\n\n"
    if row.get("manageToken"):
        link = (
            os.environ["SITE_ORIGIN"]
            + "/manage.html#"
            + urlencode({"booking": row["bookingId"], "token": row["manageToken"]})
        )
        body += (
            "View, change, or cancel this signup:\n"
            + link
            + "\n\nOpening this link does not change your signup. Keep this link private.\n\n"
        )
    body += "Organized by Brent PTA.\nThis is a test signup for team review.\n"
    return subject, body


def handler(event, context):
    if not enabled():
        return {"sent": 0}
    from store import DynamoStore
    import boto3
    from botocore.exceptions import ClientError

    store, ses = DynamoStore(), boto3.client("sesv2")
    now = int(time.time())
    # This small AWS account cannot reserve Lambda concurrency. A table lease
    # serializes deliveries across invocations and preserves the 1/sec SES limit.
    try:
        store.client.update_item(
            TableName=store.table,
            Key=store.encode({"pk": "MAILWORKER#LEASE"}),
            UpdateExpression="SET leaseUntil = :lease, expiresAt = :expiry",
            ConditionExpression="attribute_not_exists(leaseUntil) OR leaseUntil <= :now",
            ExpressionAttributeValues=store.encode(
                {":lease": now + 30, ":expiry": now + 120, ":now": now}
            ),
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return {"sent": 0}
        raise
    pending = store.client.query(
        TableName=store.table,
        IndexName="recordType-createdAt",
        KeyConditionExpression="recordType = :type",
        ExpressionAttributeValues=store.encode({":type": "mailPending"}),
        Limit=10,
    )
    sent = 0
    for raw in pending.get("Items", []):
        row = store.decode(raw)
        if row.get("leaseUntil", 0) > now:
            continue
        try:
            store.client.update_item(
                TableName=store.table,
                Key=store.encode({"pk": row["pk"]}),
                UpdateExpression="SET leaseUntil = :lease, attempts = attempts + :one",
                ConditionExpression="#status = :pending AND (attribute_not_exists(leaseUntil) OR leaseUntil <= :now)",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues=store.encode(
                    {":lease": now + 90, ":one": 1, ":pending": "pending", ":now": now}
                ),
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                continue
            raise
        status, message_id = "failed", ""
        try:
            if (
                row["expiresAt"] <= now
                or not allowed(row["recipient"])
                or is_suppressed(store, row["recipient"], now)
            ):
                status = "suppressed"
            else:
                subject, body = content(row)
                result = ses.send_email(
                    FromEmailAddress=os.environ["EMAIL_FROM"],
                    ConfigurationSetName=os.environ["EMAIL_CONFIGURATION_SET"],
                    ReplyToAddresses=[os.environ["EMAIL_REPLY_TO"]],
                    Destination={"ToAddresses": [row["recipient"]]},
                    Content={
                        "Simple": {
                            "Subject": {"Data": subject, "Charset": "UTF-8"},
                            "Body": {"Text": {"Data": body, "Charset": "UTF-8"}},
                        }
                    },
                )
                message_id, status = result["MessageId"], "sent"
                sent += 1
                time.sleep(1.1)  # Account sandbox rate is one message per second.
        except Exception as e:
            print({"notificationId": row["id"], "errorType": type(e).__name__})
            if row.get("attempts", 0) < 4:
                continue  # Lease expiry retries transient failures; no booking rollback.
        if status == "failed":
            print(
                json.dumps(
                    {"event": "mail_delivery_failed", "notificationId": row["id"]}
                )
            )
        store.client.update_item(
            TableName=store.table,
            Key=store.encode({"pk": row["pk"]}),
            UpdateExpression="SET #status = :status, messageId = :message, completedAt = :now REMOVE recordType, manageToken, details, shift, recipient, leaseUntil",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues=store.encode(
                {":status": status, ":message": message_id, ":now": int(time.time())}
            ),
        )
    return {"sent": sent}
