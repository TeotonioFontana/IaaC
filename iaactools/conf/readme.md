# EBS Volume Full Backup — README (v1.17.0)

Back up all your EBS volumes, cross-region. The script can:
- create **EBS snapshots** (and copy them to a DR region, optionally **encrypted**),
- produce **full block‑level images** of volumes to **S3** (via a helper EC2 instance and SSM),
- write a **manifest** JSON you can archive to S3.

It’s driven by a **JSON config** (safe and easy to version). CLI flags still override config values.

---

## Quick start

### 1) Prereqs
- Python 3.8+
- `pip install boto3`
- IAM permissions (see **Permissions**)
- For full‑volume imaging: a **helper EC2 instance** in the **destination** region with the SSM agent online and an instance profile that can write to your S3 bucket.

### 2) Create a config: `conf/backup-default.json`
```json
{
  "profile": null,
  "src_region": "us-east-2",
  "dst_region": "us-east-1",
  "states": "in-use,available",

  "filter_tag": [],
  "tag": ["Project=IaaC"],

  "backup_type": "snapshot",

  "helper_instance_id": null,
  "fullvol_s3_bucket": null,
  "fullvol_s3_prefix": "ebs-full/",
  "fullvol_format": "raw.gz",
  "fullvol_keep_temp_volume": false,

  "encrypt_dst": true,
  "kms_key_id": null,
  "delete_src_after_copy": false,

  "ssm_inspect": false,
  "verbose": true,
  "yes": false,

  "log_file": "results/backup-log.json",
  "log_json": true,
  "log_json_array": false,
  "log_level": "INFO",
  "manifest_file": "results/ebs_backup_manifest.json",

  "s3_bucket": "tf-backup",
  "s3_prefix": "ebs-backups/",
  "s3_region": "us-east-1",
  "s3_storage_class": "DEEP_ARCHIVE"
}
```

### 3) Run
```bash
python ebs_backup.py --config conf/backup-default.json
```
You’ll be asked to confirm phases because `verbose=true` and `yes=false`.  
For non‑interactive runs add `--yes` (or set `"yes": true`).

---

## What the script does

1. **Intro** — prints script identity, account, regions, and chosen options.
2. **Discover** — lists EBS volumes in `src_region`, logs size/type/AZ/tags/attachments.
   - `--ssm-inspect` adds best‑effort mount points via SSM.
3. **Plan** — totals capacity and (in `--verbose`) asks to proceed.
4. **Backup** — per volume:
   - **Snapshots**: create in source → wait → copy to destination (encrypt if chosen) → wait → (optional) purge source snapshot.
   - **Full‑volume**: create temp volume from **destination** snapshot → attach to **helper instance** → SSM streams a raw image to S3 → detach → delete temp volume.
5. **Manifest** — appends results to `manifest_file`; optionally uploads it to S3.

> Snapshots are **named** after the volume’s `Name` tag (fallback: `VolumeId`). Snapshot/copy IDs are always echoed to **stderr**.

---

## Config reference

### AWS basics
- `profile`: AWS profile (or `null` for default chain).
- `src_region` / `dst_region`: where volumes live vs. where copies/temp volumes are made.
- `states`: comma list; usually `"in-use,available"`.

### Selection & tagging
- `filter_tag`: e.g. `["Backup=Yes"]` to include only matching volumes.
- `tag`: tags added to snapshots (and preserved on copies).

### Backup type
- `backup_type`: `"snapshot"` (default) | `"full-volume"` | `"both"`.

### Snapshot behavior
- `encrypt_dst`: encrypt the **destination** snapshots (recommended).
- `kms_key_id`: destination KMS key (alias or ARN). `null` -> default EBS key.
- `delete_src_after_copy`: delete the **source** snapshot only after a successful **encrypted** copy.

### Full‑volume imaging (when `backup_type` is `"full-volume"` or `"both"`)
- `helper_instance_id`: instance **in dst_region** for attaching a temp volume.
- `fullvol_s3_bucket`: S3 bucket for the images (falls back to `s3_bucket`).
- `fullvol_s3_prefix`: S3 key prefix, e.g. `"ebs-full/"`.
- `fullvol_format`: `"raw"` or `"raw.gz"` (default).
- `fullvol_keep_temp_volume`: keep temp volume (debug).

### Logging & confirmations
- `verbose`: ask confirmation before each phase.
- `yes`: auto‑confirm prompts.
- `log_file`: if set, all logs go to that file; stdout stays clean for pipelines.
- `log_json`: structured logs; `log_json_array`: single array (good for ingestion).
- `manifest_file`: path to append results (JSON).

### Manifest upload to S3
- `s3_bucket`, `s3_prefix`, `s3_region`: where to upload the **manifest** (optional).
- `s3_storage_class`: one of
  `STANDARD`, `STANDARD_IA`, `ONEZONE_IA`, `INTELLIGENT_TIERING`, `GLACIER_IR`, `GLACIER`, `DEEP_ARCHIVE`, `EXPRESS_ONEZONE`, `OUTPOSTS`, `SNOW`, `FSX_OPENZFS`, `REDUCED_REDUNDANCY`.

---

## Examples

### Snapshots only (prod, encrypted, purge source after copy)
```json
{
  "profile": "prod",
  "src_region": "us-east-2",
  "dst_region": "us-east-1",
  "filter_tag": ["Backup=Yes"],
  "tag": ["Project=IaaC", "Environment=Prod"],
  "backup_type": "snapshot",
  "encrypt_dst": true,
  "kms_key_id": "alias/ebs-dr-key-us-east-1",
  "delete_src_after_copy": true,
  "yes": true,
  "log_json": true,
  "log_json_array": true,
  "log_file": "results/prod-backup.json",
  "manifest_file": "results/prod-manifest.json",
  "s3_bucket": "tf-backup",
  "s3_prefix": "ebs/manifests/",
  "s3_region": "us-east-1",
  "s3_storage_class": "DEEP_ARCHIVE"
}
```
Run: `python ebs_backup.py --config conf/prod-snapshots.json`

### Full‑volume images only
```json
{
  "src_region": "us-east-2",
  "dst_region": "us-east-1",
  "backup_type": "full-volume",
  "helper_instance_id": "i-0abc123def456",
  "fullvol_s3_bucket": "tf-backup",
  "fullvol_s3_prefix": "ebs-full/",
  "fullvol_format": "raw.gz",
  "yes": true,
  "log_file": "results/fullvol.json",
  "log_json": true
}
```
Run: `python ebs_backup.py --config conf/fullvol.json`

### Both snapshots and full‑volume
```json
{
  "src_region": "us-east-2",
  "dst_region": "us-east-1",
  "backup_type": "both",
  "helper_instance_id": "i-0abc123def456",
  "s3_bucket": "tf-backup",
  "fullvol_s3_prefix": "ebs-full/",
  "encrypt_dst": true,
  "kms_key_id": "alias/ebs-dr-key-us-east-1",
  "yes": true
}
```
Run: `python ebs_backup.py --config conf/both.json`

---

## Permissions (minimum)

**EC2**  
`Describe*`, `CreateSnapshot`, `CopySnapshot`, `DeleteSnapshot` (if purging), `CreateTags`,  
`DescribeSnapshots`, **`CreateVolume`**, **`AttachVolume`**, **`DetachVolume`**, **`DeleteVolume`**.

**SSM** (if using SSM or full‑volume)  
`ssm:SendCommand`, `ssm:GetCommandInvocation`.
The **helper instance role** also needs `s3:PutObject` to the target bucket/prefix.

**S3**  
`PutObject` to the manifest bucket/prefix, and to the full‑volume image bucket/prefix (if used).

**KMS** (if encrypting)  
Grant `kms:Encrypt`, `kms:GenerateDataKey*`, `kms:Decrypt` as needed on the **destination region** key.

---

## Troubleshooting

- **Helper instance not found/SSM offline**: ensure it’s in `dst_region`, managed by SSM, and has network to S3/KMS.
- **KMS access denied**: the principal and the helper role must be allowed on the **destination** key; key policy & IAM policy both matter.
- **S3 storage class invalid**: must be uppercase and one of the listed options.
- **Log format**: when `log_file` is set, logs go only to that file. Snapshot/copy/purge notices are always echoed to **stderr** for operator visibility.
- **Dry run**: use `verbose=true` and `yes=false` to confirm each phase before it executes.

---

## CLI overrides

You can override config values on the command line:
```bash
python ebs_backup.py \
  --config conf/backup-default.json \
  --backup-type both \
  --helper-instance-id i-0abc123def456 \
  --kms-key-id alias/override-key \
  --yes
```
