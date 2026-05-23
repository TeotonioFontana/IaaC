s3://212533511020-tf-iaac/
└─ tf-backup/
   ├─ runs/                                   # one folder per backup *generation*
   │  └─ 2025-10-15T00-51-50Z/                # run_id = UTC, colon-free ISO
   │     ├─ manifest.json                     # complete manifest for this run (immutable)
   │     ├─ logs/
   │     │  └─ backup-log.json                # JSON log for this run
   │     ├─ snapshots/                        # optional: per-snapshot metadata (lightweight)
   │     │  └─ snap-0abc...json
   │     └─ fullvol/                          # full-volume images captured in this run
   │        └─ vol-0123.../
   │           └─ <safe-name>-snap-....img.gz
   │
   ├─ index/                                  # fast lookups without scanning all runs
   │  ├─ latest.json                          # {"run_id":"2025-10-15T00-51-50Z"}
   │  ├─ by-volume/
   │  │  └─ vol-0123....json                  # append-only catalog of this volume’s backups
   │  └─ by-snapshot/
   │     └─ snap-0abc....json                 # points to run_id & artifacts
   │
   └─ retention/                               # optional: policy notes & markers
      └─ policies.md