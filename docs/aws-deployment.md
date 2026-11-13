# AWS deployment access

Region: **us-east-2 (Ohio)**. The AWS account ID and final sender identity are still needed. No deployment or AWS provisioning has been performed.

## Recommended: GitHub OIDC, no long-lived access keys

An AWS account administrator performs the bootstrap once:

1. In IAM → Identity providers, add an OpenID Connect provider for `https://token.actions.githubusercontent.com`, audience `sts.amazonaws.com`, unless it already exists.
2. In GitHub repository Settings → Environments, create `production`. Restrict deployment branches to `main`; enable required reviewers if available and desired.
3. Create an IAM role `tream-github-deploy` with the trust policy below. Replace `ACCOUNT_ID` with the actual 12-digit account ID.
4. Attach the scoped deployment policy after we finalize the infrastructure template. The trust policy alone allows authentication, not deployment. Do not attach AdministratorAccess.
5. Add GitHub environment variables under `production`: `AWS_ROLE_ARN=arn:aws:iam::ACCOUNT_ID:role/tream-github-deploy` and `AWS_REGION=us-east-2`.

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {
      "Federated": "arn:aws:iam::ACCOUNT_ID:oidc-provider/token.actions.githubusercontent.com"
    },
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {
        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
        "token.actions.githubusercontent.com:sub": "repo:batemapf/tream-volunteer:environment:production"
      }
    }
  }]
}
```

The environment restriction is essential: this subject identifies the GitHub environment, not a branch. Do not give untrusted pull-request code access to the production deployment job.

Workflow shape (documentation only; not installed as an active workflow):

```yaml
permissions:
  contents: read
jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: production
    permissions:
      contents: read
      id-token: write
    steps:
      - uses: actions/checkout@v4
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ vars.AWS_ROLE_ARN }}
          aws-region: ${{ vars.AWS_REGION }}
      - run: aws sts get-caller-identity
      # Add tests, build and deployment only after the template is defined.
```

Pin reviewed action revisions to commit SHAs when creating the real workflow.

## IAM requirements

Prefer CloudFormation with a dedicated service role:

| Identity | Required access |
| --- | --- |
| One-time account administrator | Create OIDC provider/deployment roles, attach reviewed policies and permission boundaries; SES account production-access setup and DNS identity configuration |
| GitHub deployment role | Manage only the named Tream CloudFormation stacks; upload/read deployment artifacts in the dedicated bucket; upload frontend objects and invalidate only the Tream CloudFront distribution; pass only the exact Tream CloudFormation execution role, conditioned on `iam:PassedToService=cloudformation.amazonaws.com` |
| CloudFormation execution role | Provision/update/delete the declared Tream resources: DynamoDB, Lambda, API Gateway, S3/CloudFront, Cognito, SQS, SES configuration, Scheduler, logs and runtime roles. Scope supported actions to the Tream resource namespace and us-east-2; allow global-service actions only as required. Bound IAM role creation and policy attachment with an administrator-controlled permissions boundary and tightly scoped PassRole |
| API Lambda runtime role | Only the required operations on Tream DynamoDB tables/indexes, logs and any specific queue used; no infrastructure administration |
| Mail worker runtime role | Consume the designated queue, access required private/outbox records, write logs, and `ses:SendEmail` (and `ses:SendRawEmail` only if required) for the verified sender identity; restrict From address |
| Reminder/Scheduler roles | Only invoke/send to the configured reminder target; no general email or account administration |

This is the permission design, not a ready-to-attach complete policy. Exact actions, ARNs, bootstrap resources and CloudFormation capabilities depend on the template. Generate and review the executable policies alongside that template before requesting credentials. A deployment role able to modify Lambda/runtime roles can indirectly access application data; its trust is therefore production-sensitive.

S3, Cognito and SES stay in us-east-2. CloudFront is global, and an ACM certificate for a CloudFront custom domain must be created in us-east-1. Do not accidentally deny those required exceptions with a blanket region condition.

## Access-key fallback

If OIDC is unavailable, create a dedicated non-root IAM user with only permission to assume the same deployment role. Add repository/environment Actions secrets `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`; keep `AWS_REGION` and `AWS_ROLE_ARN` as environment variables. Configure the credentials action with both secrets and `role-to-assume`, using ordinary `sts:AssumeRole` trust for that specific IAM user instead of the OIDC trust above. Session tagging permissions may be required by the action; explicitly disable session tagging or grant scoped `sts:TagSession` as appropriate.

Do not grant the IAM user broad deployment access, paste keys in chat, commit keys, or reuse personal/root credentials. Rotate/revoke these keys when moving to OIDC. OIDC is the preferred path and needs no access-key secrets.

References:
- https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws
- https://github.com/aws-actions/configure-aws-credentials
- https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/using-iam-servicerole.html
