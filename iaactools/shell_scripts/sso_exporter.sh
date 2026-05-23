#!/usr/bin/env bash
set -euo pipefail

# --- Config (edit as needed) ---
ARCH_PROFILE="architect"                      # SSO login profile (region-locked; NO auto-assume here)
ASSUME_ROLE_NAME="SSOExportReadOnly"
ASSUME_ROLE_ARN="arn:aws::iam::212533511020:role/${ASSUME_ROLE_NAME}"

HOME_REGION="us-east-2"                       # Identity Center home region (sso-admin / identitystore APIs)
ASSUME_REGION="us-east-1"                     # Region where sts:AssumeRole is allowed
INSTANCE_ARN="arn:aws:sso:::instance/ssoins-6684b776b34e737d"
IDENTITY_STORE_ID="d-9a671b8524"

OUT_DIR="/Users/teotonio/Projetos/IaaC/iaactools/cloud-formation/production/us-east-1/identity-store"
PROJECT_ROOT="/Users/teotonio/Projetos/IaaC"
TOOLS_DIR="${PROJECT_ROOT}/iaactools"
VENV_PATH="${PROJECT_ROOT}/.venv/bin/activate"
TRUST_DOC="${TOOLS_DIR}/conf/sso_export_readonly_trust.json"

# Prevent AWS CLI paging in any step
export AWS_PAGER=""
export AWS_SDK_LOAD_CONFIG=1

echo "==> Activating virtualenv: ${VENV_PATH}"
if [[ -f "${VENV_PATH}" ]]; then
  # shellcheck disable=SC1090
  source "${VENV_PATH}"
else
  echo "[FATAL] Virtualenv not found at ${VENV_PATH}" >&2
  exit 2
fi

cd "${TOOLS_DIR}"

echo "==> Verifying trust policy file: ${TRUST_DOC}"
[[ -f "${TRUST_DOC}" ]] || { echo "[FATAL] Missing trust policy JSON at ${TRUST_DOC}" >&2; exit 2; }

echo "==> Using profile for IAM ops: ${ARCH_PROFILE}"
# Who am I (pre-login)? Useful when running in CI shells (ignore failure).
aws --profile "${ARCH_PROFILE}" sts get-caller-identity >/dev/null 2>&1 || true

echo "==> Updating trust policy of role ${ASSUME_ROLE_NAME}"
AWS_PROFILE="${ARCH_PROFILE}" aws iam update-assume-role-policy \
  --role-name "${ASSUME_ROLE_NAME}" \
  --policy-document "file://${TRUST_DOC}"

echo "==> Reading back role trust"
AWS_PROFILE="${ARCH_PROFILE}" aws iam get-role \
  --role-name "${ASSUME_ROLE_NAME}" \
  --query 'Role.AssumeRolePolicyDocument.Statement[*].Principal' \
  --output json

echo "==> SSO login with profile: ${ARCH_PROFILE}"
aws sso login --profile "${ARCH_PROFILE}"

echo "==> Sanity: Caller identity as ${ARCH_PROFILE}"
AWS_PROFILE="${ARCH_PROFILE}" aws sts get-caller-identity

echo "==> Sanity: Attempt STS AssumeRole in ${ASSUME_REGION}"
AWS_PROFILE="${ARCH_PROFILE}" AWS_REGION="${ASSUME_REGION}" \
aws sts assume-role \
  --role-arn "arn:aws:iam::212533511020:role/${ASSUME_ROLE_NAME}" \
  --role-session-name "sso-exporter-drycheck" \
  --duration-seconds 900 >/dev/null && echo "[OK] AssumeRole precheck passed"

# (Option A) Let the Python script do the actual assume-role
echo "==> Running sso_exporter.py (script will assume ${ASSUME_ROLE_NAME}; STS in ${ASSUME_REGION}, APIs in ${HOME_REGION})"
echo "FLAGS"
echo "  --profile           ${ARCH_PROFILE}"
echo "  --region            ${HOME_REGION}"
echo "  --assume-sts-region ${ASSUME_REGION}"
echo "  --assume            arn:aws:iam::212533511020:role/${ASSUME_ROLE_NAME}"
echo "  --instance-arn      ${INSTANCE_ARN}"
echo "  --identity-store-id ${IDENTITY_STORE_ID}"
echo "  --out-dir           ${OUT_DIR}"

# IMPORTANT:
# - AWS_PROFILE is the NON-assuming architect profile
# - AWS_REGION is set to the STS region, because the script will call STS there
AWS_PROFILE="${ARCH_PROFILE}" AWS_REGION="${ASSUME_REGION}" \
python3 sso_exporter.py \
  --profile "${ARCH_PROFILE}" \
  --region  "${HOME_REGION}" \
  --assume-sts-region "${ASSUME_REGION}" \
  --assume "arn:aws:iam::212533511020:role/${ASSUME_ROLE_NAME}" \
  --instance-arn "${INSTANCE_ARN}" \
  --identity-store-id "${IDENTITY_STORE_ID}" \
  --out-dir "${OUT_DIR}"

echo "[DONE] Export complete -> ${OUT_DIR}"
