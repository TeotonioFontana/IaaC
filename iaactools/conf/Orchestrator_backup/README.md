# Orchestrator Config Pack

This bundle contains ready-to-use configuration files for:
- `orchestrate_backup.py` (via `--config`)
- Trust policy and inline permissions for the `SSOExportReadOnly` role
- Example EBS backup configuration

**Important:** Review ARNs, regions, and paths to ensure they match your environment.

## Files

- `orchestrator-preview.yaml` — safe dry-run (no side effects)
- `orchestrator-simulate.yaml` — read-only run + dry-run where supported
- `orchestrator-execute.yaml` — full export run (still read-only for source region)
- `orchestrator-minimal.json` — minimal JSON variant
- `sso_export_readonly_trust.json` — trust policy for SSOExportReadOnly
- `sso_export_readonly_policy.json` — inline permissions for SSO/IdentityStore read
- `backup-full-volumes.json` — example EBS backup settings

## Usage

Preview:
```bash
python orchestrate_backup.py --config orchestrator-preview.yaml
```

Simulate:
```bash
python orchestrate_backup.py --config orchestrator-simulate.yaml
```

Execute:
```bash
python orchestrate_backup.py --config orchestrator-execute.yaml
```

Minimal JSON:
```bash
python orchestrate_backup.py --config orchestrator-minimal.json
```

## Notes
- Home/Source region: us-east-2
- STS region for AssumeRole: us-east-1
- Tools dir: /Users/teotonio/Projetos/IaaC/iaactools
- Output root: /Users/teotonio/Projetos/IaaC/iaactools
- Account ID: 212533511020
- Identity Center:
  - InstanceArn: arn:aws:sso:::instance/ssoins-6684b776b34e737d
  - IdentityStoreId: d-9a671b8524
