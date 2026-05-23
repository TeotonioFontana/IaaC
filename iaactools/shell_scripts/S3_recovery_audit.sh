cd /Users/teotonio/Projetos/IaaC
python3 -m iaactools.codebase.recovery_orchestrator.s3_recovery_audit \
  --config /Users/teotonio/Projetos/IaaC/iaactools/conf/prod/audit_default.yaml \
  --run-id 20251030T132745Z \
  --region us-east-1 \
  --simulate \
  --verbose \
  --verify-snapshots
