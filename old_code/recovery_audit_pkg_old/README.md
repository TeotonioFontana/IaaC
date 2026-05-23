# IaaC Recovery Suite — Audit Package v2.0.0

Engineer‑focused redesign (v2.0): modular, testable, SaaS‑ready.

## Modules

- `audit_config_validator.py` — strict CLI + config loader (YAML/JSON), schema checks, CLI overrides.
- `audit_core_logic.py` — core orchestrator (v2 skeleton): logging setup, JSON+PDF report writing.
- `pdf_report_utils.py` — report writers, always emit JSON and PDF under `/results/audit/<run_id>/`.
- `logger_utils.py` — unified logger with `--log-format text|json|both` (JSONL saved to `/results/audit/<run_id>/logs/audit.jsonl` when both).
- `s3_recovery_audit.py` — launcher with banner + safe exception handling.

## Output Layout
```
/results/audit/<run_id>/
├── audit_result.json
├── audit_report.pdf
└── logs/
    └── audit.jsonl   # only when --log-format both
```

## Run (skeleton)
```
python -m iaactools.codebase.recovery_audit_pkg.s3_recovery_audit   --config /path/to/audit.yaml   --run-id 20251101T235959Z   --log-format text --verbose
```

## Notes
- YAML parsing uses `yaml.safe_load` if available; otherwise, prefer JSON configs.
- PDF creation is lazy (imports reportlab at runtime) and falls back to a placeholder if missing.
- This is a **skeleton** for v2 integration; Option 2 will plug in S3/EC2 checks and phase logic.
