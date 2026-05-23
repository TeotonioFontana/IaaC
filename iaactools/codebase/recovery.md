# Recovery Playbook — EBS Snapshots & Full-Volume Images

This guide covers multiple recovery paths using artifacts produced by `ebs_backup.py`:
- **Cross-region EBS Snapshots** (fastest typical restore)
- **Full-Volume Images to S3** (glass‑break / bare‑metal style)
- **AMI / Instance rebuild** (optional convenience)
- **Whole‑stack rebuild** (CloudFormation/Terraform)

> Use the **Manifest** your backup run wrote (e.g., `results/ebs_backup_manifest.json`) to identify
> the source volumes, snapshot IDs, and (if used) full-volume image locations and checksums.

---

## Scenario A — Restore a single volume from a destination snapshot (typical)

**When:** Instance disk corruption, volume lost, or you need a point-in-time rollback.

**Steps (in the DR/destination region):**
1. Find the `DstSnapshotId` for your volume in the manifest.
2. Create a new volume from the snapshot (choose size/type/AZ as needed):
   ```bash
   aws ec2 create-volume \
     --region us-east-1 \
     --snapshot-id snap-0abc... \
     --availability-zone us-east-1a \
     --volume-type gp3 \
     --tag-specifications 'ResourceType=volume,Tags=[{Key=Name,Value=restored-db}]'
   ```
3. Wait for `available`, then **attach** to your instance (stop instance if OS requires a clean attach point):
   ```bash
   aws ec2 attach-volume --region us-east-1 \
     --volume-id vol-0new... --instance-id i-0target... --device /dev/sdf
   ```
4. Mount on the OS and validate data; swap in for the failed disk as appropriate.

> Tip: If you must restore in the **source** region, use the `SrcSnapshotId` instead.

---

## Scenario B — Restore using a **full-volume image** (glass‑break)

**When:** Snapshots/metadata are unavailable, or you want a byte‑identical clone (e.g., for forensics or migration).

### Verify the image integrity (recommended)

1. Grab the checksum stored alongside the image:
   ```bash
   aws s3 cp s3://<bucket>/<prefix>/<name>.img(.gz).sha256 -
   ```
2. Locally verify against the object (download or stream) — **two options:**

- **Download then verify:**
  ```bash
  aws s3 cp s3://<bucket>/<key>.img.gz local.img.gz
  sha256sum -c <(aws s3 cp s3://<bucket>/<key>.img.gz.sha256 -)
  ```

- **Stream verify (no local file):**
  ```bash
  aws s3 cp s3://<bucket>/<key>.img.gz - | sha256sum | awk '{print $1}'
  # Compare the printed hash with the value in the .sha256 file
  ```

### Rehydrate to a new EBS volume

1. Create an empty volume (size ≥ original) in the **AZ where your helper/target instance lives**:
   ```bash
   aws ec2 create-volume --region us-east-1 --availability-zone us-east-1a \
     --size 100 --volume-type gp3 --tag-specifications 'ResourceType=volume,Tags=[{Key=Name,Value=rehydrated}]'
   ```
2. Attach it to a **helper instance** (e.g., `/dev/sdf`). Ensure the helper has SSM or SSH access and S3/KMS reachability.
3. Stream the image into the block device:
   - **If `img.gz`:**
     ```bash
     aws s3 cp s3://<bucket>/<key>.img.gz - | gunzip -c | sudo dd of=/dev/sdf bs=4M oflag=direct status=progress
     sync
     ```
   - **If `img`:**
     ```bash
     aws s3 cp s3://<bucket>/<key>.img - | sudo dd of=/dev/sdf bs=4M oflag=direct status=progress
     sync
     ```
4. Detach the volume from the helper and attach it to the **target** instance (or create an AMI from it).

---

## Scenario C — Build an AMI from a restored disk

**When:** You want to boot many identical instances from the recovered system disk.

1. From a restored root volume, create a **snapshot**:
   ```bash
   aws ec2 create-snapshot --region us-east-1 --volume-id vol-0restored...
   ```
2. Register an **AMI** from that snapshot (Linux example):
   ```bash
   aws ec2 register-image --region us-east-1 \
     --name "recovered-2025-10-09" \
     --root-device-name "/dev/xvda" \
     --block-device-mappings '[
       {"DeviceName":"/dev/xvda","Ebs":{"SnapshotId":"snap-0restored...","DeleteOnTermination":true}}
     ]' \
     --virtualization-type hvm \
     --architecture x86_64
   ```

---

## Scenario D — Whole‑stack rebuild (CloudFormation + artifacts)

**When:** You need to recreate the **entire environment** (region disaster, major corruption).

1. **Infra:** Deploy stack templates from your IaC repo (CloudFormation/Terraform).  
2. **Compute:** Use **current AMIs** for stateless tiers; for stateful tiers, attach volumes from **snapshots** or rehydrate from **full-volume images**.
3. **Data:** For databases, prefer **native backups / PITR** where available. EBS artifacts supplement, not replace, DB backups.
4. **Cutover:** Validate app health behind a staging ALB; flip DNS/weights when ready.
5. **Post-restore:** Rotate secrets/keys, check KMS grants, and tighten bucket policies.

---

## Scenario E — Cross-account or lost KMS key

- If snapshots are **KMS-encrypted**, ensure the **DR account/role** has access to the CMK, or **re-encrypt** to a DR CMK during copy (`--kms-key-id`).  
- If a key is **unavailable**, use full-volume images (encrypted by S3 if bucket policy enforces SSE-S3/SSE-KMS with a different key).

---

## Validations & sanity checks

- **Mount read-only** initially; run `fsck` for filesystems where appropriate.
- **Checksum**: verify `.sha256` before rehydrating; the hash is of the **stored object** (`.img` or `.img.gz`).
- **Bootability**: for root volumes, confirm fstab, bootloader, and NVMe device names match the target environment (e.g., `/dev/xvda` vs `/dev/nvme0n1`).

---

## Useful one-liners

- List snapshots by tag:
  ```bash
  aws ec2 describe-snapshots --filters "Name=tag:Project,Values=IaaC" --query "Snapshots[].{Id:SnapshotId,Start:StartTime,Desc:Description}" --output table
  ```

- Verify checksum without saving files locally:
  ```bash
  aws s3 cp s3://<bucket>/<key>.img.gz - | sha256sum | awk '{print $1}'
  ```

- Create volume from snapshot & attach:
  ```bash
  VOL=$(aws ec2 create-volume --region us-east-1 --snapshot-id snap-0abc --availability-zone us-east-1a --query VolumeId --output text)
  aws ec2 wait volume-available --region us-east-1 --volume-ids "$VOL"
  aws ec2 attach-volume --region us-east-1 --volume-id "$VOL" --instance-id i-0target --device /dev/sdf
  ```

---

## Where do I find what to restore?

Open your **manifest** and search by `VolumeId` or snapshot name. Each record contains:
- `SrcSnapshotId` and `DstSnapshotId`
- (If imaging used) `FullVolumeS3Bucket`, `FullVolumeS3Key`, **`FullVolumeChecksum`**, and `FullVolumeChecksumAlg`

Happy restoring. Keep calm and verify checksums. 🧩
