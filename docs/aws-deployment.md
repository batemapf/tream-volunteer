# AWS deployment access

Region: **us-east-2 (Ohio)**. The AWS account ID and final sender identity are still needed. No deployment or AWS provisioning has been performed.

## Recommended: GitHub OIDC, no long-lived access keys

An AWS account administrator performs the bootstrap once:

1. In IAM → Identity providers, add an OpenID Connect provider for `https://token.actions.githubusercontent.com`, audience `sts.amazonaws.com`, unless it already exists.
2. In GitHub repository Settings → Environments, create `production`. Restrict deployment branches to `main`; enable required reviewers if available and desired.
3. Create an IAM role `tream-github-deploy` with the trust policy below. Replace `ACCOUNT_ID` with the actual 12-digit account ID.
4. Create the runtime boundary and attach the three deployment policies using [the Terraform bootstrap instructions](../infra/bootstrap/README.md). The trust policy alone allows authentication, not deployment. Do not attach AdministratorAccess.
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

## Terraform deployment permissions

Use Terraform directly, rather than the earlier CloudFormation service-role proposal. Ready-to-customize policies, bootstrap steps, service coverage and limitations are in [infra/bootstrap](../infra/bootstrap/README.md).

Create the administrator-owned runtime boundary first. Attach the three `deploy-*.json` permissions policies to `tream-github-deploy`. These grant broad selected-service provisioning access in us-east-2, account-wide CloudFront and certificate access in us-east-1/us-east-2; they are not resource-level least privilege. S3 and IAM are constrained by the documented project naming and boundary rules. Replace all `ACCOUNT_ID` placeholders.

The deployment role provisions infrastructure; each Lambda/Scheduler role gets its own smaller runtime permissions. Terraform uses private S3 state and native S3 locking. GoDaddy DNS updates remain separate. Final policies must be exercised against the implemented template; these JSON files are not yet AWS-validated.

## Access-key fallback

If OIDC is unavailable, create a dedicated non-root IAM user with only permission to assume the same deployment role. Add repository/environment Actions secrets `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`; keep `AWS_REGION` and `AWS_ROLE_ARN` as environment variables. Configure the credentials action with both secrets and `role-to-assume`, using ordinary `sts:AssumeRole` trust for that specific IAM user instead of the OIDC trust above. Session tagging permissions may be required by the action; explicitly disable session tagging or grant scoped `sts:TagSession` as appropriate.

Do not grant the IAM user broad deployment access, paste keys in chat, commit keys, or reuse personal/root credentials. Rotate/revoke these keys when moving to OIDC. OIDC is the preferred path and needs no access-key secrets.

References:
- https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws
- https://github.com/aws-actions/configure-aws-credentials
- https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/using-iam-servicerole.html

## First preflight result

Workflow: https://github.com/batemapf/tream-volunteer/actions/runs/43354018913

The configured role ARN passed the format check. AWS rejected OIDC role assumption with `Not authorized to perform sts:AssumeRoleWithWebIdentity`; state bucket, runtime boundary and SES checks did not run. No AWS resources were provisioned.

This job uses `environment: production`, so the trust policy subject must be `repo:batemapf/tream-volunteer:environment:production`, not a branch subject such as `repo:batemapf/tream-volunteer:ref:refs/heads/main`. Confirm the provider ARN uses the deployment role's account, the audience is `sts.amazonaws.com`, and the trust action is `sts:AssumeRoleWithWebIdentity`. The error alone does not identify which trust condition failed; an organizational deny is also possible.

After fixing trust, rerun AWS deployment preflight from the Actions tab. Do not add application permissions to fix a trust-policy failure.
