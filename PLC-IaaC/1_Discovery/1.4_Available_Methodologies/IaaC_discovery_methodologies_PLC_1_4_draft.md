# IaaC Recovery Suite — Discovery Methodologies (PLC 1.4, draft)

## 1. Purpose & Scope

This chapter defines the **methodologies** supported by the IaaC framework for the **Discovery process**.

Discovery is how we go from **“an AWS org full of stuff”** to a **coherent environment model** that can be:

- Imaged into a run-id.  
- Used for DR, migration, and deployment scenarios.  
- Audited, diffed, and reasoned about.

This document focuses on:

- The **types of discovery runs** we support (methodologies).  
- The **axes we tune**: scope, depth, and frequency.  
- How each method plugs into the rest of the PLC (market, stakeholders, product vision).

Code-level details (modules, functions, CLI flags) live elsewhere; here we define the **conceptual menu** of discovery approaches.

---

## 2. Common Building Blocks

All Discovery methodologies share a set of core components implemented in the framework:

- **Phased Discovery Pipeline (Phase 0.x)**  
  Typical sequence (already in code as `discovery_core`):
  - **0.1 – Account Identity** (account ID, org/OU, Identity Center basics, regions enabled).  
  - **0.2 – CloudFormation / Stacks** (stacks, nested stacks, status, drift hints).  
  - **0.3 – Networking** (VPCs, subnets, route tables, gateways, security groups, endpoints).  
  - **0.4 – Compute** (EC2, ASG, ELB, ECS, Lambda, container registries, etc.).  
  - **0.5 – Storage & Data** (EBS, RDS, S3, EFS, backup vaults, snapshots).

- **Multi-region / Multi-account Orchestration**  
  Handled by `discovery_multi` / `discovery_ext`: loops over regions and (later) accounts with a controlled strategy (parallelism, throttling, failure isolation).

- **Manifest Model**  
  Output is normalized into a **discovery manifest**:
  - Per region, per account, per phase.  
  - Versioned and tagged with a **run-id** and timestamps.  
  - Designed to be consumed by: Backup Orchestrator, Recovery Audit, Deployment Engine.

- **Configuration & Policy**  
  All discovery methods are driven by **YAML/INI configs**:
  - List of **accounts/regions**.  
  - **Inclusion/exclusion rules** (tags, prefixes, OUs).  
  - **Depth levels** (basic vs deep introspection).  
  - **Safety limits** (timeouts, API quotas).

- **Safety & Observability**  
  - Logging by **phase 0.x** and by region/account.  
  - Metrics hooks (counts, durations, errors).  
  - Dry-run / simulation flags where appropriate.

On top of this, we define **Discovery methodologies** — combinations of these building blocks for different use cases.

---

## 3. Axes of Variation

Before defining methodologies, we fix the axes we can adjust:

1. **Scope**  
   - **Single-region / single-account**  
   - **Multi-region / single-account**  
   - **Multi-region / multi-account / org-wide**

2. **Depth**  
   - **Baseline (shallow)**: resource inventory, minimal attributes.  
   - **Deep**: extra calls for config, relationships, and “dangerous details” (e.g., IAM policy resolution, security group relationships).  
   - **Focused deep-dive**: deep only for selected services/tags.

3. **Frequency**  
   - **Ad-hoc**: on demand (before a DR drill, migration).  
   - **Scheduled**: periodic snapshots (daily/weekly/monthly).  
   - **Event-triggered** (future): on changes detected in CloudTrail/Config.

Each methodology is basically a **preset** over these axes plus some rules about **what we do with the output**.

---

## 4. Methodology A — Baseline Census Discovery

### 4.1 Intent

A **comprehensive but shallow** inventory of an environment, used to:

- Understand **“what is out there”**.  
- Provide the **baseline manifest** for later deltas and risk analysis.  
- Feed Phase 0 of the PLC (Product Vision & Market Research) with real-world constraints.

### 4.2 Characteristics

- **Scope**  
  - Multi-region, single account by default; can extend to multiple accounts.  

- **Depth**  
  - Baseline: limited attributes, no heavy deep dives.  
  - Enough to know: “We have X VPCs, Y EC2, Z RDS, N stacks, M TB of S3 (aggregated).”

- **Frequency**  
  - Typically **onboarding-only** and then **periodic** (e.g., monthly or quarterly).

### 4.3 Usage

- First-time customers (MSPs, enterprises, SaaS) to map their current AWS footprint.  
- Before defining DR scenarios, migrations, or pricing: we need the **census**.

---

## 5. Methodology B — Delta / Change-Aware Discovery

### 5.1 Intent

Detect **what changed** since the last baseline or last run-id:

- Reduce noise in reports.  
- Focus DR/migration planning on **real drift**.  
- Provide triggers for re-running DR drills or re-generating environment images.

### 5.2 Characteristics

- **Scope**  
  - Same as Baseline, but we only **highlight differences** vs previous manifest.  

- **Depth**  
  - Can be shallow or deep; the key is the **comparison step**:
    - newly created/removed resources,  
    - configuration drift (e.g., SG rules, route changes, stack status changes).

- **Frequency**  
  - Much more **frequent** than baseline (e.g., daily/weekly scans).  
  - Light enough to wire into a scheduled job.

### 5.3 Usage

- Detect whether a **DR plan or environment image is stale**.  
- Feed the **Sentinel/AI layer** with drift data.  
- Trigger alerts to Strategic/Technical stakeholders:
  - “Your DR posture changed because these resources appeared/disappeared.”

---

## 6. Methodology C — DR Drill-Oriented Discovery

### 6.1 Intent

Discovery tuned for preparing and validating a **DR drill**:

- Answer: “If we start a DR test **right now**, what exactly are we protecting and rebuilding?”

### 6.2 Characteristics

- **Scope**  
  - Restricted to the **accounts/regions** included in the drill scenario.  

- **Depth**  
  - Deeper than Baseline where it matters:
    - **Dependency chains** (e.g., which subnets, route tables, SGs a workload actually uses).  
    - **Backup links** (snapshots, backup vaults, replication settings).  
  - May ignore services that are out-of-scope for the drill.

- **Frequency**  
  - Run **just before** the drill.  
  - Optionally **embedded into the drill pipeline** itself (pre-flight check).

### 6.3 Usage

- Attach to DR runbooks and orchestrators as the **first step** (“0.0 – Refresh Discovery”).  
- Generate **evidence artifacts** for Risk/Compliance:  
  - “Here is what we based this drill on.”

---

## 7. Methodology D — Migration / Deployment-Oriented Discovery

### 7.1 Intent

Discovery configured specifically for **migration and deployment** planning:

- Export enough detail to **rebuild** the environment in a **new account/region**.  
- Cleanly separate **what must move** from **what should be re-created or refactored**.

### 7.2 Characteristics

- **Scope**  
  - Typically single source account, multi-region (where workloads actually live).  
  - Destination account/region is used for **simulation**, not for discovery.

- **Depth**  
  - Deep on **infra+identity**:
    - VPC topologies, peering, transit, shared services.  
    - IAM roles, policies, and Identity Center mappings that matter for workloads.  
  - Can be more selective on “long tail” services.

- **Frequency**  
  - Project-based: run at the **start** of a migration and periodically as the plan evolves.

### 7.3 Usage

- Inputs to the **Deployment Engine**:
  - Which pieces can be rebuilt from IaC.  
  - Which pieces depend on stateful components (snapshots, data stores, S3).  
- Generate **design docs** for Architects and Principal Consultants:
  - Show them **what will actually move**.

---

## 8. Methodology E — Compliance / Audit Discovery

### 8.1 Intent

Discovery runs designed to support **compliance and audit** events:

- Produce **evidence-rich manifests** aligned with control frameworks.  
- Prioritize **traceability and labeling** over raw technical detail.

### 8.2 Characteristics

- **Scope**  
  - Driven by scope of the audit (e.g., “PCI accounts only”, “regulated workloads only”).  

- **Depth**  
  - Enough to:
    - Prove existence and configuration of DR capabilities.  
    - Tie resources to **criticality levels, owners, and controls** (tags/metadata).

- **Frequency**  
  - Typically around:
    - Formal **audit windows**,  
    - Major **certification milestones**,  
    - Key customer security reviews.

### 8.3 Usage

- Feed Risk/Compliance stakeholders with:
  - Structured manifests.  
  - Drill histories.  
  - Control mappings.  
- Provide a **consistent data source** for compliance reporting tools.

---

## 9. Methodology F — Org-Wide Risk Scan (Future / Optional)

*(Placeholder for roadmap; useful in PLC.)*

### 9.1 Intent

A light-weight, **org-wide sweep** that gives a **risk map**:

- Where are the dangerous concentrations of risk (no backups, weird networking, untagged infrastructure).  
- Which accounts/regions deserve deep dives and DR work first.

### 9.2 Characteristics

- **Scope**  
  - Entire AWS Organization (all accounts, all active regions).  

- **Depth**  
  - Very shallow per resource, but broad:
    - Counts, basic flags (“has backups?”, “public subnet?”, “unattached EBS?”).  
  - Heavy on **aggregation and scoring**, not details.

- **Frequency**  
  - Monthly or quarterly; can also be used after major org changes.

### 9.3 Usage

- Strategic and Technical stakeholders use it to:
  - **Prioritize which parts of the org** to protect with IaaC first.  
  - Decide where to invest in deeper discovery and DR planning.

---

## 10. Choosing a Methodology — Simple Matrix

We keep the decision simple:

| Situation | Recommended Methodology |
|----------|-------------------------|
| First time in a new account/region | **Baseline Census Discovery** |
| Need to know what changed vs last month | **Delta / Change-Aware Discovery** |
| About to run a DR drill | **DR Drill-Oriented Discovery** |
| Planning an account/region migration | **Migration / Deployment-Oriented Discovery** |
| Preparing for an audit or certification | **Compliance / Audit Discovery** |
| Org-level risk picture (where to start) | **Org-Wide Risk Scan** (future) |

Each methodology is just **a preset** of: scope, depth, frequency, and output format, wired on top of the same Discovery pipeline.

---

## 11. Integration into the PLC

- **1.1 Product Vision**  
  - References which methodologies are mandatory in the MVP (Baseline + DR Drill + Migration) and which are roadmap (Org-Wide Risk Scan).

- **1.2 Market Research**  
  - Links methodologies to segments:
    - MSPs → Baseline + Delta + DR Drill.  
    - SaaS / Mid-market → DR Drill + Migration.  
    - Enterprises → Compliance + Org-Wide Risk Scan (later).

- **1.3 Stakeholder Map**  
  - Shows which stakeholders care about which methodologies:
    - Technical Influencer → Baseline, Delta, Drill, Migration.  
    - Risk/Compliance → Compliance/Audit + Org-Wide Scan.  
    - Strategic Buyer → Risk Scan + high-level summaries.

- **3.x Planning**  
  - Uses this chapter to define **which methodologies ship in which release**, and how they appear in the UI/CLI.
