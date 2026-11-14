import copy
import json
import unittest
from feedback import apply_event, suppression_key, is_suppressed
from test_booking import NOW


class FeedbackStore:
    def __init__(self):
        self.client = self
        self.table = "test"
        self.rows = {}

    def encode(self, value):
        return value

    def get(self, key):
        return self.rows.get(key)

    def update_item(self, **kwargs):
        key, values = kwargs["Key"]["pk"], kwargs["ExpressionAttributeValues"]
        self.rows[key] = {
            "pk": key,
            "reason": values[":reason"],
            "expiresAt": values[":expiry"],
            "suppressedAt": values[":time"],
        }

    def put_item(self, **kwargs):
        self.rows[kwargs["Item"]["pk"]] = kwargs["Item"]


def event(kind="Bounce", bounce_type="Permanent"):
    return {
        "source": "aws.ses",
        "detail": {
            "eventType": kind,
            "mail": {
                "messageId": "ses-test-id",
                "tags": {"ses:configuration-set": ["tream-dev"]},
            },
            "bounce": {
                "bounceType": bounce_type,
                "bouncedRecipients": [{"emailAddress": "Parent@Example.com"}],
            },
            "complaint": {
                "complainedRecipients": [{"emailAddress": "Parent@Example.com"}]
            },
        },
    }


class FeedbackTests(unittest.TestCase):
    def test_hard_bounce_and_duplicate_suppress_normalized_email_without_storing_it(
        self,
    ):
        store = FeedbackStore()
        apply_event(store, event(), NOW)
        snapshot = copy.deepcopy(store.rows)
        apply_event(store, event(), NOW)
        self.assertEqual(store.rows, snapshot)
        self.assertTrue(is_suppressed(store, " PARENT@example.com ", NOW))
        self.assertNotIn("parent@example.com", json.dumps(store.rows).lower())
        self.assertFalse(is_suppressed(store, "other@example.com", NOW))
        self.assertFalse(is_suppressed(store, "parent@example.com", 10**12))

    def test_complaint_suppresses_but_soft_bounce_and_delivery_do_not(self):
        for kind, bounce_type, suppressed in [
            ("Complaint", "Permanent", True),
            ("Bounce", "Transient", False),
            ("Bounce", "Undetermined", False),
            ("Delivery", "Permanent", False),
        ]:
            with self.subTest(kind=kind, bounce_type=bounce_type):
                store = FeedbackStore()
                apply_event(store, event(kind, bounce_type), NOW)
                self.assertEqual(
                    is_suppressed(store, "parent@example.com", NOW), suppressed
                )

    def test_other_application_and_untrusted_source_ignored(self):
        for source, config in [("aws.ses", "other-app"), ("custom.test", "tream-dev")]:
            value = event()
            value["source"] = source
            value["detail"]["mail"]["tags"]["ses:configuration-set"] = [config]
            store = FeedbackStore()
            self.assertTrue(apply_event(store, value, NOW)["ignored"])
            self.assertEqual(store.rows, {})

    def test_all_recipient_addresses_are_suppressed(self):
        value = event()
        value["detail"]["bounce"]["bouncedRecipients"].append(
            {"emailAddress": "second@example.com"}
        )
        store = FeedbackStore()
        self.assertEqual(apply_event(store, value, NOW)["suppressed"], 2)
        self.assertIsNotNone(store.get(suppression_key("second@example.com")))


class WorkerSuppressionTests(unittest.TestCase):
    def test_worker_checks_suppression_before_ses_and_fails_closed_on_database_error(
        self,
    ):
        import os
        import types
        from unittest.mock import Mock, patch
        import mail

        for failure in (False, True):
            with self.subTest(database_failure=failure):
                row = {
                    "pk": "MAIL#test",
                    "id": "test",
                    "recipient": "owner@example.com",
                    "expiresAt": NOW + 1000,
                    "attempts": 0,
                }
                store = Mock(table="test")
                store.encode.side_effect = lambda value: value
                store.decode.side_effect = lambda value: value
                store.client.query.return_value = {"Items": [row]}
                if failure:
                    store.get.side_effect = RuntimeError("database unavailable")
                else:
                    store.get.return_value = {"expiresAt": NOW + 1000}
                ses = Mock()

                class ClientError(Exception):
                    pass

                with patch.dict(
                    os.environ,
                    {
                        "EMAIL_ENABLED": "true",
                        "EMAIL_TEST_RECIPIENTS": "owner@example.com",
                    },
                ), patch.dict(
                    "sys.modules",
                    {
                        "store": types.SimpleNamespace(DynamoStore=lambda: store),
                        "boto3": types.SimpleNamespace(client=lambda name: ses),
                        "botocore.exceptions": types.SimpleNamespace(
                            ClientError=ClientError
                        ),
                    },
                ), patch(
                    "mail.time.time", return_value=NOW
                ):
                    self.assertEqual(mail.handler({}, None)["sent"], 0)
                ses.send_email.assert_not_called()
                final_updates = [
                    c.kwargs
                    for c in store.client.update_item.call_args_list
                    if ":status" in c.kwargs.get("ExpressionAttributeValues", {})
                ]
                self.assertEqual(len(final_updates), 0 if failure else 1)
                if not failure:
                    self.assertEqual(
                        final_updates[0]["ExpressionAttributeValues"][":status"],
                        "suppressed",
                    )
