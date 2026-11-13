# Organizer desk

Development URL: https://dy2majdy4ufxo.cloudfront.net/organizer.html

The page is publicly loadable, but all private data and organizer actions require a Cognito access token and membership in the `organizers` group. There is no public account registration. Volunteer signup remains account-free.

## Create your account (one-time owner setup)

After the organizer deployment succeeds:

1. Open Amazon Cognito in **us-east-2** and choose user pool **tream-dev-organizers**. The deployment workflow also outputs its pool ID.
2. Users → Create user. Choose a username and temporary password. Choose **not to send an invitation**; email is not required for these development accounts. Keep the password private.
3. Add the user to the existing **organizers** group (from the user's group memberships or the Groups tab).
4. Open the organizer URL and sign in with that username and temporary password. The page asks you to set your own password on first sign-in.
5. Create separate users for Dave and Andy when wanted; privately share their temporary credentials. Do not share one account.

A user who is not in the group cannot access organizer data even with a valid password. Access tokens last 15 minutes; the page asks for sign-in again after expiry. Tokens are kept in sessionStorage for the current browser tab, never passwords. Signing out clears the tab token, private view and dialogs; already-issued tokens can remain valid until expiry. Immediate server-side session revocation is not implemented by the API Gateway JWT authorizer.

No permanent organizer accounts are created by automation. Smoke tests create an uninvited synthetic account, test password change and group access, and delete it afterward.

## Tools

- **Coverage & shifts:** exact attendance counts by time segment, nominal target and effective limit, open/closed signup status, flexible/full-shift rules, and schedule/policy editing. A signup arriving/departing inside a segment creates its own boundary.
- **Volunteers:** private name and email search; day/job filters; contact selection; individual messaging entry point; authorized cancellation; filtered CSV download. CSV values are escaped and formula-prefixed cells neutralized.
- **Overlaps:** likely same-person versus shared-email/family flags. Mark reviewed with a note or cancel a specific commitment after confirmation. Flags never block parent signup.
- **Messages:** choose one/selected, a group (day/job type/shift), or all active volunteers. Contacts are deduplicated by email. Review the exact recipients and commitments, then save a private draft. Drafts can be loaded later and require a fresh recipient preview. Drafts expire after 30 days.

**Email sending remains disabled.** Saving a draft sends nothing and does not silently queue it for later automatic delivery. No automatic schedule-change or cancellation messages are sent yet. Annual-outreach preferences and opt-outs remain separate future work.

## Editing rules

Edits use the shift revision: a simultaneous signup or another organizer edit causes a conflict instead of overwriting their change. Refresh and try again.

The API rejects edits that would invalidate already-booked times, move an occupied shift to a different date, or reduce its effective capacity below existing attendance. Resolve those commitments first. A shift cannot be moved beyond the loaded event's end without updating event settings separately.

Attendance policy supports minimum/maximum duration, offered increments and optional explicit arrival/departure choices. Full shift means exactly the named start/end window; endpoints remain selectable even when the increment does not evenly divide its length. Actual approved policies/schedule are still pending.

## Password reset by the owner

Development accounts use administrator-controlled recovery rather than an email reset flow. In an authenticated AWS CloudShell session, a small Python helper can set a temporary password without putting it in shell arguments/history:

```python
import boto3, getpass
client = boto3.client('cognito-idp', region_name='us-east-2')
pool = input('User pool ID: ').strip()
username = input('Username: ').strip()
password = getpass.getpass('New temporary password: ')
client.admin_set_user_password(UserPoolId=pool, Username=username,
                              Password=password, Permanent=False)
```

Run with the owner's AWS identity; never use or post AWS keys/passwords in chat. The user must replace that temporary password at next sign-in.

## Operational notes

Organizer mutations write private audit records with actor identity and retention metadata. Private message drafts use a sparse DynamoDB index; a just-saved draft may need a brief refresh before appearing. A message recipient/content fingerprint prevents saving a preview if the actual recipient snapshot has changed.

The organizer list uses active commitments from the registered event shifts; it is not a historical canceled-booking/contact archive. CSV exports follow day/job/search filters. Exported files contain private contact details and need to be deleted under the project's retention policy.

This remains development. Sending, volunteer email-based management/recovery, public multi-selection UI, full retention cleanup and production launch still require implementation/configuration.
