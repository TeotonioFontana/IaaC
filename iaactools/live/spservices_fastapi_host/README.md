# SPServices FastAPI host desired state

This package records and reconciles the AWS-managed operational state of the
shared FastAPI instance `i-09b159cf466411e48`. It is the reproducible source for:

- EBS encryption by default;
- the least-privilege CloudWatch metric policy on the instance role;
- disk metrics and alarms for the root and five application filesystems;
- the SNS alert destination;
- temporary migration-snapshot tagging and expiration;
- the canonical application-storage and bind-mount layout.

The checked-in CloudWatch Agent configuration must be installed at
`/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.d/file_amazon-cloudwatch-agent.json`.
The physical and bind mounts in `desired_state.yaml` must be represented in
`/etc/fstab`. Release pruning is owned by the SPServices deployment package:
`spservicesapi-release-retention.timer` keeps three immutable releases.

## Reconcile AWS state

Use a Python 3.10+ environment with this repository's dependencies and valid
AWS credentials:

```bash
python iaactools/live/spservices_fastapi_host/reconcile.py
python iaactools/live/spservices_fastapi_host/reconcile.py --apply
```

The first command is a plan. The second is idempotent. Email subscriptions still
require the recipient to click the AWS confirmation link.

## Automatic snapshot expiration

Deploy the narrow retention stack once:

```bash
aws cloudformation deploy \
  --region us-east-2 \
  --stack-name spservices-temporary-snapshot-retention \
  --template-file iaactools/live/spservices_fastapi_host/snapshot_retention.yaml \
  --capabilities CAPABILITY_IAM
```

The function can delete only snapshots tagged
`RetentionClass=temporary-migration`, and only after a valid `DeleteAfter` date.
All intermediate migration snapshots expire on 2026-11-07. The six detached
original volumes are retained separately as the rollback set through the same
date and are never deleted by the snapshot-retention function. The exact final
mapping and validation evidence are in `migration-20261008.yaml`.

## EBS encryption migration invariant

Never replace attached volumes before all encrypted snapshot copies are
`completed`. Preserve the original detached volumes for rollback, reattach the
encrypted volumes at the same API device names, then validate mounts, services,
HTTP health, CloudWatch metrics, and reverse-proxy traffic. Tag old volumes with
a future `DeleteAfter`; do not delete them during the migration window.
