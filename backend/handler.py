import base64
import json
import os
import time
from domain import Problem
from service import BookingService, public_shift

_store = None


def store():
    global _store
    if _store is None:
        from store import DynamoStore

        _store = DynamoStore()
    return _store


def response(status, body):
    return {
        "statusCode": status,
        "headers": {
            "content-type": "application/json",
            "cache-control": "no-store",
            "x-content-type-options": "nosniff",
            "referrer-policy": "no-referrer",
        },
        "body": json.dumps(body),
    }


def handler(event, context):
    try:
        method = event["requestContext"]["http"]["method"]
        path = event.get("rawPath", "")
        headers = {k.lower(): v for k, v in event.get("headers", {}).items()}
        if method == "GET" and path == "/health":
            return response(
                200, {"ok": True, "environment": "development", "emailEnabled": False}
            )
        if method == "GET" and path == "/schedule":
            registry = store().get("EVENT#2026")
            shifts = [
                store().get("SHIFT#" + key)
                for key in (registry or {}).get("shiftIds", [])
            ]
            return response(
                200,
                {
                    "shifts": [public_shift(s, time.time()) for s in shifts if s],
                    "emailEnabled": False,
                },
            )
        token = headers.get("authorization", "").removeprefix("Bearer ")
        segments = path.strip("/").split("/")
        service = BookingService(store())
        if method == "GET" and len(segments) == 2 and segments[0] == "bookings":
            return response(200, service.managed(segments[1], token))
        if method == "POST":
            if headers.get("origin") != os.environ["SITE_ORIGIN"]:
                raise Problem("Open the signup page to make changes.", "origin", 403)
            raw = event.get("body") or "{}"
            if event.get("isBase64Encoded"):
                raw = base64.b64decode(raw).decode()
            if len(raw) > 40000:
                raise Problem("Submission is too large.", "size", 413)
            try:
                payload = json.loads(raw)
                if not isinstance(payload, dict):
                    raise ValueError()
            except (ValueError, TypeError):
                raise Problem("Invalid submission.") from None
            if path == "/bookings":
                return response(
                    200, service.batch(payload.get("email"), payload.get("selections"))
                )
            if (
                len(segments) == 3
                and segments[0] == "bookings"
                and segments[2] == "cancel"
            ):
                return response(200, service.cancel(segments[1], token))
        return response(404, {"message": "Not found."})
    except Problem as error:
        return response(error.status, {"message": str(error), "code": error.code})
    except Exception as error:
        # Avoid exception strings/tracebacks that can contain payloads or credentials.
        print(
            json.dumps(
                {
                    "errorType": type(error).__name__,
                    "requestId": getattr(context, "aws_request_id", "local"),
                }
            )
        )
        return response(
            503,
            {
                "message": "Temporarily unavailable. Please retry.",
                "code": "unavailable",
            },
        )
