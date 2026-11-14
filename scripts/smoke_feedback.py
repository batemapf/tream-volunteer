"""Real SES simulator → EventBridge → feedback persistence; no human recipients."""

import os
import sys
import time
from pathlib import Path
import boto3

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from store import DynamoStore
from feedback import suppression_key, is_suppressed

ses, store = boto3.client("sesv2"), DynamoStore()
configuration = "tream-dev"
checks = [
    ("success@simulator.amazonses.com", "delivery", False),
    ("bounce@simulator.amazonses.com", "bounce", True),
    ("complaint@simulator.amazonses.com", "complaint", True),
]
ids = []
try:
    for recipient, kind, suppressed in checks:
        result = ses.send_email(
            FromEmailAddress="feedback-test@brentholidaysale.com",
            ConfigurationSetName=configuration,
            Destination={"ToAddresses": [recipient]},
            Content={
                "Simple": {
                    "Subject": {"Data": "Tream SES feedback simulator check"},
                    "Body": {
                        "Text": {
                            "Data": "Automated delivery feedback test. AWS simulator only; no volunteer signup."
                        }
                    },
                }
            },
        )
        ids.append((recipient, kind, suppressed, result["MessageId"]))
        time.sleep(1.1)
    deadline = time.monotonic() + 240
    pending = list(ids)
    while pending and time.monotonic() < deadline:
        for item in pending[:]:
            recipient, kind, suppressed, message_id = item
            receipt = store.get("MAILFEEDBACK#" + message_id + "#" + kind)
            if receipt:
                assert (
                    is_suppressed(store, recipient) == suppressed
                ), "Incorrect suppression behavior"
                assert (
                    "recipient" not in receipt and "mail" not in receipt
                ), "Unnecessary provider payload retained"
                print(
                    "PASS: real SES "
                    + kind
                    + " event received; suppression="
                    + str(suppressed),
                    flush=True,
                )
                pending.remove(item)
        if pending:
            time.sleep(5)
    assert not pending, "Feedback events did not arrive before timeout"
    print(
        "PASS: actual SES simulator delivery, permanent bounce and complaint traversed EventBridge; hashed suppression verified. No human mail sent."
    )
finally:
    for recipient, kind, _, message_id in ids:
        store.client.delete_item(
            TableName=store.table,
            Key=store.encode({"pk": "MAILFEEDBACK#" + message_id + "#" + kind}),
        )
        store.client.delete_item(
            TableName=store.table, Key=store.encode({"pk": suppression_key(recipient)})
        )
