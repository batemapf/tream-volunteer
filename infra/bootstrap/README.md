# Terraform deployment IAM bootstrap

These are the proposed initial provisioning policies for direct Terraform deployments. They replace the earlier CloudFormation/service-role proposal. The configured deployment role has now successfully provisioned the first development stack; see docs/development-deployment.md. The templates here retain ACCOUNT_ID placeholders for setup reference.

## Scope and tradeoff

`deploy-regional.json` grants broad administration of the selected services **throughout us-east-2**, not just Tream resources. `deploy-global.json` grants account-wide CloudFront administration, ACM is administrable in us-east-1/us-east-2, and S3 is limited to the project bucket naming pattern. This is a practical initial provisioning envelope, **not a final least-privilege policy or an isolation boundary for unrelated workloads**. Use a dedicated project account if possible. Narrow resource scopes once the Terraform resource inventory is implemented and exercised.

Do not attach AdministratorAccess, IAMFullAccess, or PowerUserAccess in addition to these policies. The deployment role is sensitive: it can modify app code and access application/state data. Only trusted production workflow code should assume it.

## One-time administrator steps

Replace every `ACCOUNT_ID` in the JSON files with the actual 12-digit account ID. Do not paste unmodified placeholders into IAM.

1. Create/reuse the GitHub OIDC provider and `tream-github-deploy` role with the repo/environment trust policy in docs/aws-deployment.md.
2. IAM → Policies → Create policy → JSON: create **tream-runtime-boundary** from `runtime-boundary.json`. This must be administrator-controlled. It is a maximum permission ceiling, not a permission grant by itself.
3. Create three customer-managed policies from `deploy-regional.json`, `deploy-global.json`, and `deploy-iam.json`. Name them `tream-deploy-regional`, `tream-deploy-global`, and `tream-deploy-iam`.
4. Open role **tream-github-deploy** → Permissions → Add permissions → Attach policies. Attach those three deployment policies. Do **not** use the runtime boundary as a boundary on the deployment role.
5. Create the private Terraform state bucket `tream-ACCOUNT_ID-tfstate` in us-east-2 as a bootstrap step. Enable versioning, default SSE-S3 encryption and all public-access blocks. Use the backend key `production/terraform.tfstate` and Terraform >=1.10 native S3 locking (`use_lockfile = true`). Keep the bucket outside the application stack lifecycle. Set a finite lifecycle for old state versions; state can contain private values.
6. Set GitHub `production` environment variables `AWS_ROLE_ARN` and `AWS_REGION=us-east-2`. Restrict the environment to main. OIDC needs no AWS access-key secrets.

The state bucket can alternatively be created by a separate bootstrap Terraform stack with initially local state, then managed through its own backend. It cannot be created by the same initial remote-backend operation that already needs it to exist. Never commit state or plan artifacts to Git.

## What the policies cover

| Capability | Policy/API family |
| --- | --- |
| Lambda code, configuration, invocation permissions and queue event mappings | Regional `lambda:*` |
| DynamoDB tables/indexes, streams if needed, TTL, PITR and restore APIs | Regional `dynamodb:*` |
| HTTP API routes/integrations/stages, authorizers and custom domain mappings | Regional `apigateway:*` |
| Cognito organizer user pools, clients, domains, groups and users | Regional `cognito-idp:*` |
| Queues, dead-letter queues, attributes and queue policies | Regional `sqs:*` |
| Sender identities/DKIM, configuration sets, event destinations, templates, sending/account reads | Regional `ses:*` |
| Reminder schedules/groups and email-event rules/targets | Regional `scheduler:*` and `events:*` |
| Log groups/retention, dashboards, alarms and metrics | Regional `logs:*` and `cloudwatch:*` |
| Frontend and Terraform state bucket configuration/objects/locking | Global policy `s3:*`, restricted to `tream-ACCOUNT_ID-*` buckets and their objects |
| CloudFront distribution, origin access control, cache policies and invalidations | Global policy `cloudfront:*` |
| App/API certificates and validation records returned to us | `acm:*` in us-east-1/us-east-2; CloudFront certificates are in us-east-1 |
| Runtime-role creation, trust, inline policies, tags and role deletion | IAM policy, only roles named `tream-runtime-*`, with mandatory fixed boundary at creation |
| Passing roles | Only those runtime roles, only to Lambda, Scheduler or EventBridge |

Creation, read/refresh, update/tagging and deletion are included in service wildcards. Actual support may also depend on SCPs, existing resource policies, AWS quotas, provider behavior and resource configuration. Run IAM Access Analyzer policy validation and the first Terraform plan/apply in the target account before treating these as tested deployment credentials. Grant new permissions only for an identified template requirement.

## Runtime-role rules for Terraform

Every role managed by Terraform must:

- Use the name prefix `tream-runtime-` and the normal `/` IAM path.
- Set `permissions_boundary = "arn:aws:iam::ACCOUNT_ID:policy/tream-runtime-boundary"` at creation.
- Use inline role policies. Attaching/detaching AWS-managed policies is deliberately not authorized.
- Receive a narrow function-specific policy, not every permission the boundary permits.

The boundary caps access at project DynamoDB data, queues, Lambda invocation, precreated Lambda log groups, approved-region verified SES identities and the Tream metrics namespace. The mail worker's own policy additionally restricts sender identity/From address. It grants no IAM, provisioning or STS role-assumption permissions.

The deployment role cannot edit/delete the boundary, remove a role's boundary, edit its own role, create IAM users/access keys or change the OIDC provider. If the Terraform provider attempts to remove a permissions boundary before deleting a role, that action is intentionally denied: use administrator-assisted role cleanup or retain the role, rather than granting general boundary removal. Final destroy behavior must be exercised before launch. Boundary changes are a deliberate one-time administrator operation, not a routine GitHub deploy.

## Excluded by design

- IAM administration of the deployment role/provider/boundary is manual bootstrap.
- No CloudFormation: Terraform calls AWS APIs directly.
- No EC2/VPC/NAT/RDS/ECS/ECR, Route 53, custom KMS keys, Secrets Manager or AWS Backup vaults. Current serverless design uses managed encryption/PITR and does not need them. Revisit permissions if architecture changes.
- No AWS Organizations, account/billing administration, SES production-access approval guarantee, or GoDaddy DNS access. DNS records are added in GoDaddy separately.
- No automatic IAM service-linked-role creation. Default Cognito email configuration and the initial no-autoscaling serverless resources should avoid needing new ones; an administrator bootstraps one if a selected feature requires it. Do not add unrestricted `iam:CreateServiceLinkedRole`.

These policies cover our planned architecture, not every optional AWS feature. Cost budgets/account controls and any restore drill involving additional services require their own setup.

References:
- https://developer.hashicorp.com/terraform/language/backend/s3
- https://docs.aws.amazon.com/service-authorization/latest/reference/list_cloudfront.html
- https://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies_boundaries.html
