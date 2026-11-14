"""SES configuration-set feedback. Never log addresses or raw provider events."""

import hashlib
import os
import time
from datetime import datetime
from domain import retention_expiry


def suppression_key(email):
    return "SUPPRESS#" + hashlib.sha256(email.strip().lower().encode()).hexdigest()


def is_suppressed(store, email, now=None):
    record = store.get(suppression_key(email))
    return bool(record and record["expiresAt"] > (time.time() if now is None else now))


def apply_event(store, event, now=None):
    now = int(time.time() if now is None else now)
    detail = event.get("detail", {})
    mail = detail.get("mail", {})
    configuration = os.environ.get("EMAIL_CONFIGURATION_SET", "tream-dev")
    if event.get("source") != "aws.ses" or configuration not in mail.get(
        "tags", {}
    ).get("ses:configuration-set", []):
        return {"ignored": True}
    kind = detail.get("eventType") or next(
        (
            k
            for k in (
                "bounce",
                "complaint",
                "delivery",
                "reject",
                "deliveryDelay",
                "renderingFailure",
            )
            if k in detail
        ),
        "unknown",
    )
    kind = kind.lower()
    message_id = mail.get("messageId")
    if not isinstance(message_id, str) or not 1 <= len(message_id) <= 200:
        raise ValueError("Missing SES message identifier")
    observed = now
    try:
        observed = min(
            now,
            int(
                datetime.fromisoformat(event["time"].replace("Z", "+00:00")).timestamp()
            ),
        )
    except (KeyError, TypeError, ValueError):
        pass
    addresses = []
    if kind == "complaint":
        addresses = [
            r.get("emailAddress")
            for r in detail.get("complaint", {}).get("complainedRecipients", [])
        ]
    elif kind == "bounce" and detail.get("bounce", {}).get("bounceType") == "Permanent":
        addresses = [
            r.get("emailAddress") for r in detail["bounce"].get("bouncedRecipients", [])
        ]
    addresses = {
        a.strip().lower() for a in addresses if isinstance(a, str) and "@" in a
    }
    # All writes are idempotent; retries cannot undo a suppression or create email.
    for email in addresses:
        store.client.update_item(
            TableName=store.table,
            Key=store.encode({"pk": suppression_key(email)}),
            UpdateExpression="SET reason = :reason, suppressedAt = if_not_exists(suppressedAt, :time), expiresAt = :expiry",
            ExpressionAttributeValues=store.encode(
                {
                    ":reason": kind,
                    ":time": observed,
                    ":expiry": retention_expiry(observed),
                }
            ),
        )
    receipt = {
        "pk": "MAILFEEDBACK#" + message_id + "#" + kind,
        "messageId": message_id,
        "kind": kind,
        "observedAt": observed,
        "suppressedCount": len(addresses),
        "expiresAt": observed + 30 * 86400,
    }
    # No address, email content, or management token is retained in receipts.
    store.client.put_item(TableName=store.table, Item=store.encode(receipt))
    return {"kind": kind, "suppressed": len(addresses)}


def handler(event, context):
    from store import DynamoStore

    return apply_event(DynamoStore(), event)
