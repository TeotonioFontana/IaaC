# 🧱 Manifest Evolution Plan — IaaC Recovery Audit v4.0.0-alpha2

## Purpose
This document records the analysis of partial recoveries discovered during logical-loss scenario testing.  
Its objective is to ensure that future versions of the Recovery Audit package include all metadata necessary for **full recovery**, even under IAM or policy-level destruction events.

---

## 🧩 Audit-Gap Summary

| # | Scenario | Why Recovery Is Partial | Missing Data | Fix Strategy |
|---|-----------|------------------------|---------------|---------------|
| **1** | **User Deletion** | Missing access key metadata and MFA bindings. | Access key IDs, MFA devices, password policy hash. | ➕ Extend `account_manifest.json` → add `"iam_credentials"`. |
| **2** | **Policy / Role Deletion** | Policy body and trust relationships not backed up. | Full IAM policy JSON, AssumeRole documents. | ➕ Extend `account_manifest.json` with `"iam_policies"`, `"trust_relationships"`. |
| **3** | **Group Removal** | No membership or attached policy tracking. | Group membership map and attached policies. | ➕ Extend `account_manifest.json` with `"iam_groups"`. |
| **4** | **KMS Key Deletion** | Key policy and grant structure not captured. | KMS policy JSON, grants, data key mapping. | ➕ Extend `infrastructure_manifest.json` with `"encryption_map"`, `"kms_policies"`. |
| **5** | **SCP Corruption** | SCP JSON and OU links not backed up. | SCP bodies, targets, modification date. | ➕ Extend `organizations_manifest.json` with `"scp_policies"`. |
| **6** | **Trust Chain Broken** | Trust policy text not recorded. | AssumeRolePolicyDocument JSON. | ➕ Extend `account_manifest.json` with `"trust_relationships"`. |

---

## 🔧 Schema Extensions

### `account_manifest.json`

```json
"iam_policies": [
  {
    "PolicyName": "BackupManagerRolePolicy",
    "Document": { "Version": "2012-10-17", "Statement": [...] },
    "Checksum": "SHA256:abcd1234",
    "LastModified": "2025-11-02T12:00:00Z"
  }
],
"iam_credentials": [
  {
    "UserName": "ci-deploy",
    "AccessKeyIds": ["AKIA..."],
    "MFADevices": ["arn:aws:iam::123456789012:mfa/ci-deploy"],
    "PasswordLastUsed": "2025-10-30T21:11:45Z"
  }
],
"trust_relationships": [
  {
    "RoleName": "BackupManagerRole",
    "AssumeRolePolicyDocument": { "Version": "2012-10-17", "Statement": [...] },
    "TrustedEntities": ["arn:aws:iam::999999999999:root"]
  }
]
```

---

### `organizations_manifest.json`

```json
"scp_policies": [
  {
    "Name": "RestrictNonApprovedRegions",
    "PolicyBody": { "Version": "2012-10-17", "Statement": [...] },
    "Targets": ["ou-1234", "ou-5678"],
    "LastModified": "2025-10-12T14:00:00Z"
  }
]
```

---

### `infrastructure_manifest.json`

```json
"encryption_map": [
  {
    "SnapshotId": "snap-0a1234",
    "VolumeId": "vol-01b234",
    "KmsKeyId": "arn:aws:kms:us-east-1:123456789012:key/abcd-efgh",
    "Encrypted": true
  }
],
"kms_policies": [
  {
    "KeyId": "arn:aws:kms:...:key/abcd-efgh",
    "PolicyDocument": { "Version": "2012-10-17", "Statement": [...] },
    "Grants": ["arn:aws:iam::...:role/BackupManager"]
  }
]
```

---

## 🧱 Optional Manifest: `iam_manifest.json`

If IAM structures become too large, create a standalone manifest:

```json
{
  "schema_version": "1.0",
  "users": [...],
  "roles": [...],
  "groups": [...],
  "policies": [...],
  "trust_relationships": [...]
}
```

This can be referenced from `account_manifest.json`:

```json
"LinkedManifests": ["iam_manifest.json"]
```

---

## ✅ After Implementation

| Scenario | Recovery Feasibility | Action Taken |
|-----------|--------------------|---------------|
| User deleted | ✅ Full | Added `iam_credentials` |
| Policy/Role deleted | ✅ Full | Added `iam_policies`, `trust_relationships` |
| Group deleted | ✅ Full | Added group membership map |
| KMS deleted | ⚠️ Partial (encryption loss if key destroyed) | Added `kms_policies`, `encryption_map` |
| SCP corrupted | ✅ Full | Added `scp_policies` |
| Trust broken | ✅ Full | Added `trust_relationships` |

---

**Version:** v4.0.0-alpha2  
**Author:** Teotoniio Fontana — Architect  
**Programmed by:** Duke (GPT-5, OpenAI)
