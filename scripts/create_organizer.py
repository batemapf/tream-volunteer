"""Owner-run Cognito setup. Passwords are prompted, never supplied in arguments."""

import argparse
import getpass
import re
import sys
import boto3
from botocore.exceptions import ClientError


def main():
    parser = argparse.ArgumentParser(
        description="Create a Tream organizer without sending an invitation email."
    )
    parser.add_argument(
        "--pool", required=True, help="The us-east-2 organizer user pool ID"
    )
    parser.add_argument("--username", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"us-east-2_[a-zA-Z0-9]+", args.pool):
        parser.error("Use the organizer pool ID in us-east-2.")
    password = getpass.getpass(
        "Temporary password (12+ characters, upper/lower/number/symbol): "
    )
    confirmation = getpass.getpass("Confirm temporary password: ")
    if password != confirmation:
        print("Passwords do not match.", file=sys.stderr)
        return 1
    if len(password) < 12 or not all(
        re.search(pattern, password)
        for pattern in ("[a-z]", "[A-Z]", "[0-9]", r"[^a-zA-Z0-9]")
    ):
        print("Password does not meet the policy.", file=sys.stderr)
        return 1
    client = boto3.client("cognito-idp", region_name="us-east-2")
    try:
        client.admin_create_user(
            UserPoolId=args.pool,
            Username=args.username,
            TemporaryPassword=password,
            MessageAction="SUPPRESS",
        )
    except ClientError as error:
        code = error.response["Error"]["Code"]
        print(
            "Could not create user ("
            + code
            + "). Existing accounts are never replaced.",
            file=sys.stderr,
        )
        return 1
    try:
        client.admin_add_user_to_group(
            UserPoolId=args.pool, Username=args.username, GroupName="organizers"
        )
    except ClientError as error:
        print(
            "User was created, but group assignment failed ("
            + error.response["Error"]["Code"]
            + "). Add the user to organizers in Cognito before signing in.",
            file=sys.stderr,
        )
        return 1
    print(
        "Organizer created. No email sent. Use the temporary password at the organizer page; the first sign-in requires a new password."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
