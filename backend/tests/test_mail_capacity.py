import os
import types
import unittest
from unittest.mock import Mock, patch
import mail
from test_booking import NOW


class WorkerCapacityTests(unittest.TestCase):
    def run_worker(self, context=None, elapsed=False, fail=False):
        store = Mock()
        store.decode.side_effect = lambda row: row
        store.encode.side_effect = lambda row: row
        store.client.query.return_value = {
            "Items": [
                {
                    "pk": f"MAIL#{i}",
                    "id": str(i),
                    "recipient": "parent@gmail.com",
                    "expiresAt": NOW + 1000,
                    "attempts": 0,
                }
                for i in range(120)
            ]
        }
        ses = Mock()
        ses.send_email.return_value = {"MessageId": "sent"}
        if fail:
            ses.send_email.side_effect = RuntimeError("temporary SES failure")

        class ClientError(Exception):
            pass

        with patch.dict(
            os.environ,
            {
                "EMAIL_ENABLED": "true",
                "EMAIL_DELIVERY_MODE": "public",
                "EMAIL_FROM": "volunteers@brentholidaysale.com",
                "EMAIL_REPLY_TO": "batemapf@gmail.com",
                "EMAIL_CONFIGURATION_SET": "tream-dev",
            },
        ), patch.dict(
            "sys.modules",
            {
                "store": types.SimpleNamespace(DynamoStore=lambda: store),
                "boto3": types.SimpleNamespace(client=lambda name: ses),
                "botocore.exceptions": types.SimpleNamespace(ClientError=ClientError),
            },
        ), patch(
            "mail.time.time", return_value=NOW
        ), patch(
            "mail.time.monotonic",
            side_effect=[0, 41] if elapsed else None,
            return_value=0,
        ), patch(
            "mail.time.sleep"
        ) as sleep, patch(
            "mail.is_suppressed", return_value=False
        ), patch(
            "mail.content", return_value=("Test", "Private")
        ):
            result = mail.handler({}, context)
        return result, store, ses, sleep

    def test_processes_larger_batch_at_safe_rate_and_preserves_leases(self):
        result, store, ses, sleep = self.run_worker()
        self.assertEqual(result["sent"], 120)
        self.assertEqual(ses.send_email.call_count, 120)
        self.assertEqual(store.client.query.call_args.kwargs["Limit"], 120)
        self.assertTrue(all(c.args == (0.2,) for c in sleep.call_args_list))
        self.assertEqual(
            store.client.update_item.call_args_list[0].kwargs[
                "ExpressionAttributeValues"
            ][":lease"],
            NOW + 55,
        )
        final = [
            c
            for c in store.client.update_item.call_args_list
            if ":status" in c.kwargs.get("ExpressionAttributeValues", {})
        ]
        self.assertEqual(len(final), 120)

    def test_time_budget_leaves_unclaimed_messages_pending(self):
        for context, elapsed in [
            (None, True),
            (Mock(get_remaining_time_in_millis=lambda: 5000), False),
        ]:
            result, store, ses, _ = self.run_worker(context, elapsed)
            self.assertEqual(result["sent"], 0)
            ses.send_email.assert_not_called()
            self.assertEqual(store.client.update_item.call_count, 1)

    def test_transient_send_failure_keeps_pending_record_for_retry(self):
        with patch("builtins.print"):
            result, store, ses, _ = self.run_worker(fail=True)
        self.assertEqual(result["sent"], 0)
        self.assertFalse(
            any(
                ":status" in c.kwargs.get("ExpressionAttributeValues", {})
                for c in store.client.update_item.call_args_list
            )
        )
