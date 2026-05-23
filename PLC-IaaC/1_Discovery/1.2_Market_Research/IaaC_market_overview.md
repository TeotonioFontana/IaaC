# IaaC Recovery Suite — Market Research (PLC 1.2)

## 1. Purpose & Scope

This document maps the **market landscape** for the IaaC Recovery Suite:

- Who we sell to (segments and buying roles).
- What alternatives exist (AWS-native and vendors).
- Where the **real gaps** are (especially around full-environment recovery and evidence).
- How we **prioritize segments** and GTM paths.

It feeds:

- **1.1 Product Vision** (validation and refinement of assumptions).
- **1.3 Stakeholder Map** (concrete org roles and power structures).
- **3.x Planning** (segment sequencing, roadmap focus, pricing).

---

## 2. Market Context

### 2.1 Problem Space

Across AWS-heavy organizations:

- Backups exist (EBS snapshots, RDS, S3 versioning), but are **fragmented** and often **untested**.
- Most tools aim at **data recovery**, not **full environment recovery** (VPCs, routing, IAM, Identity Center, helper infra).
- Regulatory pressure (SOC 2, ISO 27001, HIPAA, etc.) increasingly demands **provable DR**, not just “we think we have backups”.

The market is moving from “we have snapshots” to **“show me evidence that we can recover the entire account/region”**.

### 2.2 Target Segments (Macro View)

Based on prior persona and roadmap work, the core segments are:

1. **Managed Service Providers (MSPs)**
   - Sell DRaaS to multiple customers.
   - Need something they can **productize and resell** as a managed offer.

2. **Cloud-Native Mid-Market (SaaS / FinTech / HealthTech)**
   - Strong compliance pressure.
   - Lean teams seeking **automation** and **audit-ready proof**.

3. **Enterprise Cloud Teams (Finance, Energy, Pharma, Gov)**
   - Heavier governance and audits.
   - Longer cycles but **large contracts**.

4. **LegalTech & Law Firms**
   - High sensitivity to data integrity and evidence retention.
   - Strong synergy with **LexBrain / Hyperdocs**.

These segments share one pattern: **they need to demonstrate recoverability to someone else** (clients, auditors, regulators, boards).

---

## 3. Buyer Personas & Roles (Summary)

For each segment, the buying center clusters into three role types:

- **Strategic Buyer** – CIO/CTO/Managing Partner, or Head of Cloud/IT.
- **Technical Influencer** – SRE Lead, Cloud Architect, DevOps Lead.
- **Compliance / Risk Stakeholder** – Risk Officer, DPO, Internal Auditor.

### 3.1 Managed Service Providers (MSPs)

- **Strategic Buyer:** CTO / Head of Cloud Operations
  - Wants a **DRaaS product** that scales across many clients without growing headcount.
- **Technical Influencer:** Lead DevOps / Cloud Architect
  - Wants fewer custom scripts, more **automation, manifests, and logs**.
- **Operational Buyer:** Service Delivery Manager
  - Needs **SLA proof** and easy reporting per customer.

**Typical trigger:**

- A client asks for **provable DR** or MSP wants to launch/upgrade DRaaS offering.

### 3.2 Cloud-Native Mid-Market (SaaS / FinTech / HealthTech)

- **Strategic Buyer:** CTO / VP Engineering
  - Needs BC/DR without building a big DR team.
- **Technical Influencer:** Platform / SRE Lead
  - Wants **one tool** to orchestrate and simulate recoveries.
- **Stakeholder:** Compliance Officer / Risk Manager
  - Needs **hard evidence** for SOC 2 / ISO audits.

**Typical trigger:**

- Facing a **certification** or a heavy **security questionnaire** they cannot answer cleanly.

### 3.3 Enterprise Cloud Teams

- **Strategic Buyer:** CIO / Head of Infrastructure
  - Wants enterprise-grade resilience and compliance automation.
- **Stakeholder:** Cloud Governance / Risk Management
  - Needs **transparent auditability** and continuous verification.
- **Technical Influencer:** DR Lead / Senior Cloud Engineer
  - Wants to reduce **manual DR testing** and have a predictable playbook.

**Typical trigger:**

- Internal audit, regulatory change, or a **major migration** requiring formal DR readiness.

### 3.4 LegalTech & Law Firms

- **Strategic Buyer:** Managing Partner / COO
  - Wants guarantees that **case data and evidence** are recoverable.
- **Technical Influencer:** IT Director / Sysadmin
  - Needs backup automation that doesn’t disrupt case management.
- **Stakeholder:** Data Privacy / Compliance Partner
  - Needs **immutable logs** for client trust.

**Typical trigger:**

- Client contracts with strict **continuity clauses** or cybersecurity certifications.

---

## 4. Alternatives & Competitive Landscape

### 4.1 AWS-Native Solutions

1. **AWS Backup**
   - Centralized backup plans for AWS resources.
   - Strong on **backup automation**, weak on **full environment reconstruction**.

2. **AWS Elastic Disaster Recovery (CloudEndure)**
   - Host-level replication and quick failover.
   - Focus on **servers**, not complete AWS control-plane rebuild.

3. **AWS Resilience Hub**
   - Assessment and scenario testing tool for resilience posture.
   - Not a full **“export current state + replay in new region/account”** engine.

4. **Application Migration Service**
   - Streamlined **server migration**, but not infra+identity reconstruction.

**Summary:** AWS-native tools cover **parts** of the problem (backups, replication, assessment), but none aims at **one-pass export + split + simulate + manifest** at the account/region level including identity.

### 4.2 Third-Party DR / Backup Vendors

Representative players (non-exhaustive): **Zerto, Veeam, Rubrik, Cohesity, Druva, N2WS**.

Typical strengths:

- Rich data protection features (backups, replication, long-term retention).
- Integrations with multiple clouds and on-prem.
- Some support AWS snapshots and AMI orchestration.

Typical gaps vs IaaC vision:

- Limited or proprietary handling of **full AWS control-plane** (VPCs, route tables, SGs, IAM, Identity Center).
- Focus on **workload-level** recovery, not **whole-account rebuild**.
- Evidence and audit features vary, often not tightly aligned with **region-level DR simulation**.

### 4.3 Our Differentiation

IaaC Recovery Suite is differentiated by:

1. **Full Environment Scope**
   - Infra + data + identity, including IAM Identity Center mappings.
   - Deterministic, runbook-driven **export → split → simulate → manifest** in a single pipeline.

2. **Simulation & Evidence**
   - Simulate recovery into **sandbox accounts/regions**.
   - Generate **audit-ready evidence** (JSON/PDF, manifests, timing, control mapping).

3. **Guardrails & Governance**
   - “Source is read-only, destination is mutable” semantics baked into IAM/SCP checks.
   - Run IDs, logs, and manifests structured for compliance and audits.

4. **MSP & Multi-Tenant Readiness**
   - Design suitable for MSPs / DRaaS, enabling white-label or co-branded offers.

5. **AI-Assisted Recovery Intelligence (Roadmap)**
   - AI layer (Sentinel) that learns from runs, cloud evolution, and policy drift, predicting resilience decay instead of only reacting.

---

## 5. Segment Attractiveness & Prioritization

### 5.1 Segment Attractiveness

High-level attractiveness assessment:

- **MSPs**
  - Pros: Faster sales cycles, channel leverage, recurring revenue, DRaaS packaging.
  - Cons: Price-sensitive, strong expectations on multi-tenant features and SLAs.

- **Cloud-Native Mid-Market**
  - Pros: Compliance-driven, open to new tools, strong need for automation.
  - Cons: Need clear pricing and tight integration with their existing DevOps stack.

- **Enterprise Cloud Teams**
  - Pros: Largest deal sizes, strategic reference value.
  - Cons: Long sales cycles, heavy security/vendor risk scrutiny.

- **LegalTech & Law Firms**
  - Pros: Strong synergy with your other products (LexBrain / Hyperdocs).
  - Cons: Niche, often later in the adoption curve; benefit from proven references.

### 5.2 Prioritization

Recommended sequencing:

1. **MSPs** — fastest path to recurring ARR and DRaaS credibility.
2. **Cloud-Native SaaS / FinTech** — compliance-driven early adopters; great for case studies.
3. **Enterprise Cloud Teams** — follow after credibility; focus on co-sell with AWS / auditors.
4. **LegalTech & Law Firms** — strategic niche, coupled to LexBrain positioning.

This order is coherent with the IaaC Product Vision and commercial logic.

---

## 6. Buying Triggers & Objections

### 6.1 Common Buying Triggers

Across segments, buying tends to start when:

- Preparing for **SOC 2 / ISO 27001 / HIPAA** or similar audits.
- Answering complex **customer security questionnaires**.
- Experiencing an **incident** (near-miss or actual outage) that exposes DR gaps.
- Planning **region migrations** or **account reorganizations**.
- MSPs launching a new or updated **DRaaS offering**.

### 6.2 Typical Objections

1. “We already use AWS Backup / Elastic DR.”
   - Response: These handle backups and host replication, not **full-account rebuild + evidence**.

2. “Our vendor handles DR.”
   - Response: Many vendors focus on data and VM replication; few provide **end-to-end control-plane + identity + compliance evidence**.

3. “This sounds complex / risky.”
   - Response: Emphasize **simulation**, **dry-runs**, and **guardrails**; start with non-critical accounts.

4. “We don’t have time to integrate a new tool.”
   - Response: Position as **layer on top of existing AWS setup**, not a replacement of current backups.

---

## 7. Market Size & Commercial Potential (High Level)

Exact TAM/SAM/SOM sizing would require external data, but from a qualitative view:

- The **AWS-heavy mid-market** + **enterprises** needing audited DR is large and growing.
- DRaaS is a known, monetizable category for MSPs.
- Willingness to pay is tied directly to **reduced risk**, **audit speed**, and **downtime avoidance**.

Pricing can be structured in tiers from **team** (few accounts, basic automation) to **enterprise** (multi-account orgs, scheduled drills, evidence packs), plus **consulting add-ons** for DR readiness assessments.

---

## 8. Risks & Unknowns

Key risks to monitor:

- **AWS-native evolution** (Resilience Hub, Backup, DR services) closing part of the gap.
- Large vendors expanding into **control-plane + identity** territory.
- MSP channel complexity: onboarding, enablement, co-marketing costs.

Unknowns that should be validated in early discovery calls:

- How often target customers **actually run DR drills** today.
- Who “owns” DR internally (SRE, Security, Ops, Infra, or someone else).
- Appetite for **SaaS control plane** vs **on-prem / self-hosted** deployment.

---

## 9. Suggested Machine View — `market_research.json` (Sketch)

The companion `market_research.json` captures segments, competitors and differentiators in a machine-readable way for later tools and AI support.
