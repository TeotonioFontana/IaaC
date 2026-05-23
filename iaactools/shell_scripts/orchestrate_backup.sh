#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# orchestrate_backup.sh — Wrapper for ebs_backup.py (config-first)
# Modular orchestration: handles EBS snapshots, full-volume backups, and AMI ops
# ==============================================================================

# ---- Paths ----
PROJECT_ROOT="${PROJECT_ROOT:-/Users/teotonio/Projetos/IaaC}"
TOOLS_DIR="${TOOLS_DIR:-${PROJECT_ROOT}/iaactools/codebase}"

# New entry point (replaces orchestrate_backup_full.py)
ORCH_SCRIPT="${ORCH_SCRIPT:-${TOOLS_DIR}/ebs_backup.py}"

VENV_PATH="${VENV_PATH:-${PROJECT_ROOT}/.venv/bin/activate}"
ORCH_CONFIG="${ORCH_CONFIG:-${PROJECT_ROOT}/iaactools/conf/Orchestrator_backup/orchestrator-execute.yaml}"

# ---- AWS Safety Defaults ----
AWS_PROFILE="${AWS_PROFILE:-architect}"
AWS_REGION="${AWS_REGION:-us-east-2}"

# ---- Echo settings ----
echo "==> Wrapper settings"
echo "    PROJECT_ROOT : ${PROJECT_ROOT}"
echo "    TOOLS_DIR    : ${TOOLS_DIR}"
echo "    ORCH_SCRIPT  : ${ORCH_SCRIPT}"
echo "    VENV_PATH    : ${VENV_PATH}"
echo "    ORCH_CONFIG  : ${ORCH_CONFIG}"
echo "    AWS_PROFILE  : ${AWS_PROFILE}"
echo "    AWS_REGION   : ${AWS_REGION}"
echo

# ---- Sanity checks ----
[[ -f "${VENV_PATH}"   ]] || { echo "[FATAL] Virtualenv not found: ${VENV_PATH}" >&2; exit 2; }
[[ -f "${ORCH_SCRIPT}" ]] || { echo "[FATAL] Orchestrator not found: ${ORCH_SCRIPT}" >&2; exit 2; }
[[ -f "${ORCH_CONFIG}" ]] || { echo "[FATAL] Config file not found: ${ORCH_CONFIG}" >&2; exit 2; }

# ---- Activate venv ----
# shellcheck disable=SC1090
source "${VENV_PATH}"

# ---- Export AWS env vars ----
export AWS_PROFILE
export AWS_REGION
export AWS_DEFAULT_REGION="${AWS_REGION}"

# ---- Build command ----
CMD=( "${ORCH_SCRIPT}" --config "${ORCH_CONFIG}" )

echo "==> Running EBS Backup Orchestrator (config-first):"
printf '    %q ' python3 "${CMD[@]}"; echo
echo

python3 "${CMD[@]}"
RC=$?
if [[ $RC -eq 0 ]]; then
  echo "[DONE] EBS orchestration finished successfully."
else
  echo "[ERROR] EBS orchestration failed with exit code ${RC}."
fi
exit $RC
