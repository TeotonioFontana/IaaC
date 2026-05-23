#!/usr/bin/env bash
# check-us2-ec2-backup-perms.sh
set -u

PROFILE="${PROFILE:-architect}"
REGION="${REGION:-us-east-2}"

pass() { printf "✅ %s\n" "$*"; }
fail() { printf "❌ %s\n" "$*" ; }
info() { printf "ℹ️  %s\n" "$*"; }

echo "== Checking EC2 backup permissions =="
echo "Profile: $PROFILE"
echo "Region : $REGION"
echo

# 0) Identity sanity
if ! ID_JSON=$(aws sts get-caller-identity --profile "$PROFILE" --region "$REGION" 2>/dev/null); then
  fail "STS call failed. Run: aws sso login --profile $PROFILE"
  exit 2
fi
ACCT=$(echo "$ID_JSON" | jq -r .Account)
ARN=$(echo "$ID_JSON" | jq -r .Arn)
pass "Authenticated as $ARN (account $ACCT)"

# 1) DescribeInstances
if aws ec2 describe-instances --profile "$PROFILE" --region "$REGION" --max-results 5 >/dev/null 2>&1; then
  pass "ec2:DescribeInstances allowed"
else
  ERR=$(aws ec2 describe-instances --profile "$PROFILE" --region "$REGION" --max-results 5 2>&1 | head -n1)
  fail "ec2:DescribeInstances denied: $ERR"
fi

# 2) DescribeVolumes
if aws ec2 describe-volumes --profile "$PROFILE" --region "$REGION" --max-results 5 >/dev/null 2>&1; then
  pass "ec2:DescribeVolumes allowed"
else
  ERR=$(aws ec2 describe-volumes --profile "$PROFILE" --region "$REGION" --max-results 5 2>&1 | head -n1)
  fail "ec2:DescribeVolumes denied: $ERR"
fi

# Pick a volume (if any) for a realistic dry-run
VOLID=$(aws ec2 describe-volumes --profile "$PROFILE" --region "$REGION" \
  --query 'Volumes[0].VolumeId' --output text 2>/dev/null || echo "None")

USE_VOL="vol-fffffffffffffffff"
if [ -n "$VOLID" ] && [ "$VOLID" != "None" ]; then
  USE_VOL="$VOLID"
  info "Using existing volume for dry-run: $USE_VOL"
else
  info "No volumes found; using dummy ID ($USE_VOL). Result should still show permission outcome, but may be less informative."
fi

# 3) CreateSnapshot (permission probe via --dry-run)
# Expected:
#   - If ALLOWED: "(DryRunOperation) ... Request would have succeeded, but DryRun flag is set."
#   - If DENIED  : "(UnauthorizedOperation) ..." or "AccessDenied"
SNAP_ERR=$(aws ec2 create-snapshot --profile "$PROFILE" --region "$REGION" \
  --volume-id "$USE_VOL" --description "perm-check" --dry-run 2>&1 || true)

if echo "$SNAP_ERR" | grep -q "DryRunOperation"; then
  pass "ec2:CreateSnapshot allowed (dry-run passed)"
elif echo "$SNAP_ERR" | grep -Eqi "UnauthorizedOperation|AccessDenied|ExplicitDeny"; then
  fail "ec2:CreateSnapshot denied: $(echo "$SNAP_ERR" | head -n1)"
else
  # Other errors (e.g., InvalidVolume.NotFound) with no AccessDenied usually still mean you had permission.
  if echo "$SNAP_ERR" | grep -qi "InvalidVolume.NotFound"; then
    pass "CreateSnapshot permission appears OK (got InvalidVolume.NotFound, which is expected with dummy/unknown volume)"
  else
    info "CreateSnapshot dry-run result was inconclusive:"
    echo "    $SNAP_ERR"
  fi
fi

echo
echo "== Done =="
echo "Tip: export PROFILE=architect REGION=us-east-2 and re-run to avoid flags."
