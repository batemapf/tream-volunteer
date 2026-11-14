"""Read-only, aggregate-only operational check. Never print contacts or link tokens."""

import ast
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
import boto3

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from store import DynamoStore

now = int(time.time())
since = now - 86400
store = DynamoStore()
rows = []
cursor = None
while True:
    args = {"TableName": store.table}
    if cursor:
        args["ExclusiveStartKey"] = cursor
    page = store.client.scan(**args)
    rows.extend(store.decode(item) for item in page.get("Items", []))
    cursor = page.get("LastEvaluatedKey")
    if not cursor:
        break


def automated(row):
    email = row.get("email", "")
    domain = email.rsplit("@", 1)[-1]
    return (
        domain in ("example.com", "example.org", "example.net")
        or row.get("name") == "Tream Email Test"
    )


bookings = [r for r in rows if r["pk"].startswith("BOOKING#")]
recent = [r for r in bookings if r.get("createdAt", 0) >= since]
mail = [
    r for r in rows if r["pk"].startswith("MAIL#") and r.get("createdAt", 0) >= since
]
pending = [
    r
    for r in rows
    if r.get("recordType") == "mailPending" and r.get("status") == "pending"
]
feedback = [
    r
    for r in rows
    if r["pk"].startswith("MAILFEEDBACK#") and r.get("observedAt", 0) >= since
]
print(
    json.dumps(
        {
            "window": "last 24 hours",
            "checkedAtUTC": datetime.now(timezone.utc).isoformat(),
            "bookings": {
                "nonAutomatedActiveTotal": sum(
                    r.get("status") == "active" and not automated(r) for r in bookings
                ),
                "nonAutomatedCreated": dict(
                    Counter(r["status"] for r in recent if not automated(r))
                ),
                "automatedCreated": dict(
                    Counter(r["status"] for r in recent if automated(r))
                ),
            },
            "notifications": dict(Counter(r.get("status", "unknown") for r in mail)),
            "notificationKinds": dict(Counter(r.get("kind", "unknown") for r in mail)),
            "pendingCount": len(pending),
            "oldestPendingSeconds": max([now - r["createdAt"] for r in pending] or [0]),
            "failedNotifications": sum(r.get("status") == "failed" for r in mail),
            "feedback": dict(Counter(r["kind"] for r in feedback)),
            "activeSuppressions": sum(
                r["pk"].startswith("SUPPRESS#") and r.get("expiresAt", 0) > now
                for r in rows
            ),
        },
        indent=2,
    )
)
# Match private receipt message IDs in memory; output only aggregate delivery state.
sent = [r for r in mail if r.get("status") == "sent"]
confirmed = {r["messageId"] for r in feedback if r["kind"] == "delivery"}
print(
    json.dumps(
        {
            "sesAcceptedWithDeliveryReceipt": sum(
                r.get("messageId") in confirmed for r in sent
            ),
            "sesAcceptedWithoutRetainedDeliveryReceipt": sum(
                r.get("messageId") not in confirmed for r in sent
            ),
        }
    )
)

nonautomated_ids = {r["id"] for r in bookings if not automated(r)}
nonautomated_mail = [r for r in mail if r.get("bookingId") in nonautomated_ids]
missing_receipts = [r for r in sent if r.get("messageId") not in confirmed]
print(
    json.dumps(
        {
            "nonAutomatedNotificationStates": dict(
                Counter(r.get("status") for r in nonautomated_mail)
            ),
            "latestAcceptedWithoutReceiptUTC": (
                datetime.fromtimestamp(
                    max(r["createdAt"] for r in missing_receipts), timezone.utc
                ).isoformat()
                if missing_receipts
                else None
            ),
            "acceptedWithReceiptCreatedUTC": [
                datetime.fromtimestamp(r["createdAt"], timezone.utc).isoformat()
                for r in sent
                if r.get("messageId") in confirmed
            ],
        }
    )
)

logs = boto3.client("logs")
for function in ("api", "mail", "feedback"):
    group = "/aws/lambda/tream-dev-" + function
    errors = Counter()
    cursor = None
    seen = set()
    while True:
        args = {"logGroupName": group, "startTime": (now - 7200) * 1000, "limit": 10000}
        if cursor:
            args["nextToken"] = cursor
        page = logs.filter_log_events(**args)
        for event in page.get("events", []):
            if event["eventId"] in seen:
                continue
            seen.add(event["eventId"])
            message = event["message"].strip()
            value = None
            for parse in (json.loads, ast.literal_eval):
                try:
                    value = parse(message)
                    break
                except (ValueError, SyntaxError, TypeError):
                    pass
            if isinstance(value, dict):
                if value.get("errorType"):
                    errors["handled:" + value["errorType"]] += 1
                if value.get("event") == "mail_delivery_failed":
                    errors["exhaustedDeliveryRetries"] += 1
            elif (
                "[ERROR]" in message
                or "Task timed out" in message
                or "Traceback" in message
            ):
                errors["unstructuredErrorLines"] += 1
        new_cursor = page.get("nextToken")
        if not new_cursor or new_cursor == cursor:
            break
        cursor = new_cursor
    print(
        json.dumps(
            {"function": function, "last2hLogEvents": len(seen), "errors": dict(errors)}
        )
    )

cw = boto3.client("cloudwatch")
start = datetime.now(timezone.utc) - timedelta(hours=2)
for function in ("api", "mail", "feedback"):
    output = {"function": function, "metricsLast2h": {}}
    for metric in ("Invocations", "Errors", "Throttles"):
        result = cw.get_metric_statistics(
            Namespace="AWS/Lambda",
            MetricName=metric,
            Dimensions=[{"Name": "FunctionName", "Value": "tream-dev-" + function}],
            StartTime=start,
            EndTime=datetime.now(timezone.utc),
            Period=300,
            Statistics=["Sum"],
        )
        output["metricsLast2h"][metric] = sum(p["Sum"] for p in result["Datapoints"])
    print(json.dumps(output))
print(
    json.dumps(
        {
            "alarms": [
                {"name": a["AlarmName"], "state": a["StateValue"]}
                for a in cw.describe_alarms(AlarmNamePrefix="tream-dev-")[
                    "MetricAlarms"
                ]
            ]
        }
    )
)
sqs = boto3.client("sqs")
url = sqs.get_queue_url(QueueName="tream-dev-feedback-failures")["QueueUrl"]
print(
    json.dumps(
        {
            "feedbackFailedEventQueue": sqs.get_queue_attributes(
                QueueUrl=url,
                AttributeNames=[
                    "ApproximateNumberOfMessages",
                    "ApproximateNumberOfMessagesNotVisible",
                ],
            )["Attributes"]
        }
    )
)
account = boto3.client("sesv2").get_account()
print(
    json.dumps(
        {
            "sesProduction": account["ProductionAccessEnabled"],
            "sesSendingEnabled": account["SendingEnabled"],
            "quota": account["SendQuota"],
        }
    )
)
