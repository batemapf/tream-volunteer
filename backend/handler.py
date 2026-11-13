import base64
import json
import os
import time
from domain import Problem
from service import BookingService, public_shift
from admin import AdminService, shift_rows

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


def organizer_actor(event):
    # Only the API Gateway JWT authorizer creates this trusted request context.
    claims = (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("jwt", {})
        .get("claims", {})
    )
    groups = claims.get("cognito:groups", [])
    if isinstance(groups, str):
        try:
            groups = json.loads(groups)
        except ValueError:
            groups = [g.strip(" []\"'") for g in groups.split(",")]
    if (
        not isinstance(groups, list)
        or "organizers" not in groups
        or claims.get("token_use") != "access"
        or not claims.get("sub")
    ):
        raise Problem("Organizer access is required.", "forbidden", 403)
    return claims["sub"]


def payload(event, headers):
    if headers.get("origin") != os.environ["SITE_ORIGIN"]:
        raise Problem("Open the signup page to make changes.", "origin", 403)
    raw = event.get("body") or "{}"
    try:
        if event.get("isBase64Encoded"):
            raw = base64.b64decode(raw).decode()
        if len(raw) > 40000:
            raise Problem("Submission is too large.", "size", 413)
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError()
    except (ValueError, TypeError, UnicodeDecodeError):
        raise Problem("Invalid submission.") from None
    return value


def handler(event, context):
    try:
        method = event["requestContext"]["http"]["method"]
        path = event.get("rawPath", "")
        headers = {k.lower(): v for k, v in event.get("headers", {}).items()}
        segments = path.strip("/").split("/")
        if path.startswith("/admin/"):
            actor = organizer_actor(event)
            admin = AdminService(store(), actor)
            if method == "GET" and path == "/admin/overview":
                return response(200, admin.overview())
            if method == "GET" and path == "/admin/messages":
                return response(200, admin.list_drafts())
            if method == "GET" and path == "/admin/export.csv":
                result = response(200, {})
                result["body"] = admin.export(event.get("queryStringParameters") or {})
                result["headers"].update(
                    {
                        "content-type": "text/csv; charset=utf-8",
                        "content-disposition": 'attachment; filename="tream-roster.csv"',
                    }
                )
                return result
            if method == "POST":
                body = payload(event, headers)
                if len(segments) == 3 and segments[1] == "shifts":
                    return response(200, admin.update_shift(segments[2], body))
                if (
                    len(segments) == 4
                    and segments[1] == "bookings"
                    and segments[3] == "cancel"
                ):
                    return response(200, admin.cancel_booking(segments[2]))
                if (
                    len(segments) == 4
                    and segments[1] == "conflicts"
                    and segments[3] == "review"
                ):
                    return response(200, admin.review_conflict(segments[2], body))
                if path == "/admin/messages/preview":
                    return response(200, admin.message_preview(body))
                if path == "/admin/messages":
                    return response(200, admin.save_message(body))
            return response(404, {"message": "Not found."})
        if method == "GET" and path == "/health":
            return response(
                200, {"ok": True, "environment": "development", "emailEnabled": False}
            )
        if method == "GET" and path == "/schedule":
            return response(
                200,
                {
                    "shifts": [
                        public_shift(s, time.time()) for s in shift_rows(store())
                    ],
                    "emailEnabled": False,
                },
            )
        token = headers.get("authorization", "").removeprefix("Bearer ")
        service = BookingService(store())
        if method == "GET" and len(segments) == 2 and segments[0] == "bookings":
            return response(200, service.managed(segments[1], token))
        if method == "POST":
            body = payload(event, headers)
            if path == "/bookings":
                return response(
                    200, service.batch(body.get("email"), body.get("selections"))
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
