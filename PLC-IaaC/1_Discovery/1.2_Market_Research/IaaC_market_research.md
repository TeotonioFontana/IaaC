# IaaC Recovery Suite — Market Research (PLC 1.2, updated)

## 1. Purpose & Scope

This document maps the **market landscape** for the IaaC Recovery Suite, extended to cover its **dual nature**:

- **Recovery**: Full-environment DR for AWS accounts/regions.
- **Deployment**: Re-deploying a captured environment into a **new account or region** while **preserving the original** as a frozen reference.

It answers:

- Who we sell to (segments and buying roles).
- What alternatives exist (AWS-native and vendors).
- Where the **real gaps** are (full-environment recovery + redeployment + evidence).
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
- When environments must be **recreated in a new account/region**, the process is:
  - Manual and script-heavy.
  - Error-prone and hard to audit.
  - Very hard to **repeat** with the same outcome.
- Regulatory pressure (SOC 2, ISO 27001, HIPAA, etc.) increasingly demands **provable DR**, not just “we think we have backups”.

The market is moving from “we have snapshots” to:

> **“Show me evidence that we can recover and re-deploy the entire account/region, and prove it in a separate destination account if needed.”**

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

**Additional strategic target segments (explicitly deployment-driven):**

5. **Consulting Companies (non-MSP)**  
   - Execute **one-off or programmatic cloud projects**: migrations, account restructures, DR readiness.  
   - Need a reusable engine to:
     - Export current state.
     - Replay it into **new accounts/regions**.
     - Produce client-facing documentation and evidence.

6. **AWS Partners (Consulting / ISV)**  
   - Build landing zones, DR patterns, and modernization programs on AWS.  
   - Need:
     - A **standardized tool** they can adopt across multiple clients.
     - Strong alignment with AWS best practices and Identity Center.

7. **SaaS Developers / Platform Teams**  
   - Maintain multi-account/multi-region platforms.  
   - Need:
     - Reliable ways to **clone production** into staging, diagnostics, or new regions.  
     - Safer, controlled **account-to-account deployments** while keeping the original untouched.

These segments share one thing: **they need to demonstrate recoverability and/or controlled redeployment to someone else** (clients, auditors, regulators, boards).

### 2.3 Recovery + Deployment Duality

A fundamental property of IaaC:

> Once it has the **full metadata** describing everything in the AWS account, the user can **deploy it to a new account or region while preserving the original**.

This duality is central to positioning:

- **Recovery mode**  
  - “Rebuild what we had at run-id X in a safe/sandbox account or region.”
- **Deployment mode**  
  - “Use run-id X as a **golden environment image** for migration, cloning, or diagnostics.”
- The original account remains **read-only reference**, with guardrails around what can be touched.

This moves IaaC beyond “Recovery Suite” into **“Recovery & Deployment Engine”** for AWS environments.

---

## 3. Buyer Personas & Roles (Summary)

For each segment, the buying center clusters into three role types:

- **Strategic Buyer** – CIO/CTO/Managing Partner, Head of Cloud/IT, or Partner-owner in consulting firms.
- **Technical Influencer** – SRE Lead, Cloud Architect, DevOps Lead, Platform Team Lead.
- **Compliance / Risk Stakeholder** – Risk Officer, DPO, Internal Auditor, Security/Compliance Partner.

### 3.1 Managed Service Providers (MSPs)

- **Strategic Buyer:** CTO / Head of Cloud Operations  
  - Wants a **DRaaS product** that scales across many clients without growing headcount.
- **Technical Influencer:** Lead DevOps / Cloud Architect  
  - Wants fewer custom scripts, more **automation, manifests, and logs**.
- **Operational Buyer:** Service Delivery Manager  
  - Needs **SLA proof** and easy reporting per customer.

**Typical trigger:**  
A client asks for **provable DR** or MSP wants to launch/upgrade DRaaS offering (recovery + periodic “re-deploy into sandbox” drills).

### 3.2 Cloud-Native Mid-Market (SaaS / FinTech / HealthTech)

- **Strategic Buyer:** CTO / VP Engineering  
  - Needs BC/DR without building a big DR team.
- **Technical Influencer:** Platform / SRE Lead  
  - Wants **one tool** to orchestrate and simulate recoveries and **account-to-account deployments**.
- **Stakeholder:** Compliance Officer / Risk Manager  
  - Needs **hard evidence** for SOC 2 / ISO audits.

**Typical trigger:**  
Facing a **certification** or a heavy **security questionnaire** they cannot answer cleanly (especially “show me you can rebuild in another region/account”).

### 3.3 Enterprise Cloud Teams

- **Strategic Buyer:** CIO / Head of Infrastructure  
  - Wants enterprise-grade resilience and compliance automation.
- **Stakeholder:** Cloud Governance / Risk Management  
  - Needs **transparent auditability** and continuous verification.
- **Technical Influencer:** DR Lead / Senior Cloud Engineer  
  - Wants to reduce **manual DR testing** and have a predictable playbook.

**Typical trigger:**  
Internal audit, regulatory change, or a **major migration** requiring formal DR and **cross-account deployment** readiness.

### 3.4 LegalTech & Law Firms

- **Strategic Buyer:** Managing Partner / COO  
  - Wants guarantees that **case data and evidence** are recoverable.
- **Technical Influencer:** IT Director / Sysadmin  
  - Needs backup automation that doesn’t disrupt case management.
- **Stakeholder:** Data Privacy / Compliance Partner  
  - Needs **immutable logs** and simple client-facing evidence.

**Typical trigger:**  
Client contracts with strict **continuity clauses** or cybersecurity certifications.

### 3.5 Consulting Companies

- **Strategic Buyer:** Practice Lead / Partner (Cloud / Infra / DR practice)  
  - Wants a **repeatable methodology + tool** to differentiate migration and DR projects.
- **Technical Influencer:** Principal Consultant / Senior Architect  
  - Wants to avoid “snowflake” scripts per engagement.
- **Stakeholder:** Delivery / PMO  
  - Needs predictable, auditable steps and artifacts for clients.

**Typical trigger:**  
Pipeline of migrations / restructures where they need to **standardize tooling** and speed up delivery.

### 3.6 AWS Partners

- **Strategic Buyer:** Partner Principal / Business Lead  
  - Wants offerings that align well with AWS GTM narratives.
- **Technical Influencer:** Lead Architect / Technical Account Owner  
  - Wants a tool they can **comfortably recommend** to many customers.
- **Stakeholder:** Partner Solutions Architect / Co-Sell Specialist  
  - Needs a story that **fits AWS patterns** (orgs, landing zones, Control Tower, Identity Center).

**Typical trigger:**  
Building or refreshing **DR, resilience, or migration accelerators** on AWS.

### 3.7 SaaS Developers / Platform Teams

- **Strategic Buyer:** VP Platform / CTO  
  - Wants a safer way to **replicate environments** and roll out new regions.
- **Technical Influencer:** Platform Engineering Lead  
  - Needs deterministic way to **clone prod to staging** and support tenant migrations.
- **Stakeholder:** Security / Compliance Lead  
  - Needs evidence that **critical platform environments** can be rebuilt elsewhere.

**Typical trigger:**  
Expanding to new regions or re-architecting the platform across multiple accounts/tenants.

---

## 4. Alternatives & Competitive Landscape

### 4.1 AWS-Native Solutions

1. **AWS Backup**  
   - Centralized backup plans for AWS resources.  
   - Strong on **backup automation**, weak on **full environment reconstruction** and **account-to-account deployment**.

2. **AWS Elastic Disaster Recovery (CloudEndure)**  
   - Host-level replication and quick failover.  
   - Focus on **servers**, not a complete AWS control-plane rebuild.

3. **AWS Resilience Hub**  
   - Assessment and scenario testing tool for resilience posture.  
   - Not a full **“export current state + replay in new region/account”** engine.

4. **Application Migration Service**  
   - Streamlined **server migration**, but not infra+identity reconstruction or environment imaging.

**Summary:**  
AWS-native tools cover **parts** of the problem (backups, replication, assessment), but none aims at **one-pass export + split + simulate + manifest + redeploy** at the account/region level, including identity and guardrails.

### 4.2 Third-Party DR / Backup Vendors

Representative players (non-exhaustive): **Zerto, Veeam, Rubrik, Cohesity, Druva, N2WS**.

Typical strengths:

- Rich data protection features (backups, replication, long-term retention).
- Integrations with multiple clouds and on-prem.
- Some support AWS snapshots and AMI orchestration.

Typical gaps vs IaaC vision:

- Limited or proprietary handling of **full AWS control-plane** (VPCs, route tables, SGs, IAM, Identity Center).
- Focus on **workload-level** recovery, not **whole-account rebuild**.
- Weak support for **structured, repeatable account-to-account redeployment** with strong evidence artifacts.

### 4.3 Our Differentiation

IaaC Recovery Suite is differentiated by:

1. **Full Environment Scope**  
   - Infra + data + identity, including IAM Identity Center mappings.  
   - Deterministic, runbook-driven **export → split → simulate → manifest** in a single pipeline.

2. **Environment Deployment & Cloning**  
   - From a captured run-id, IaaC can:
     - Rebuild the environment in a **different AWS account or region**.
     - Keep the **source account as read-only reference**.  
   - This directly supports migrations, landing zones, and diagnostic clones.

3. **Simulation & Evidence**  
   - Simulate recovery into **sandbox accounts/regions**.  
   - Generate **audit-ready evidence** (JSON/PDF, manifests, timing, control mapping).

4. **Guardrails & Governance**  
   - “Source is read-only, destination is mutable” semantics baked into IAM/SCP checks.  
   - Run IDs, logs, and manifests structured for compliance and audits.

5. **MSP / Consulting / Partner / Multi-Tenant Readiness**  
   - Design suitable for MSPs, consulting firms, and AWS partners:
     - Multi-account multi-client patterns.
     - White-label or co-branded offers.

6. **AI-Assisted Recovery Intelligence (Roadmap)**  
   - AI layer (Sentinel) that learns from runs, cloud evolution, and policy drift, predicting resilience decay instead of only reacting.

---

## 5. SWOT Matrix

### 5.1 Strengths

- **End-to-end scope**: Covers infra, data, and identity; focuses on **environment imaging**, not just backups.
- **Dual use: recovery + deployment**:
  - Recovery: Full-account/region DR.
  - Deployment: Account-to-account and region-to-region cloning while preserving the original.
- **Evidence-centric**:
  - Strong manifests and reports aimed at auditors, regulators, and demanding customers.
- **Channel-friendly**:
  - Designed for **MSPs, consulting companies, AWS partners**, and **SaaS platform teams**.
- **Synergy with other products**:
  - Especially for **LegalTech & Law Firms** via LexBrain/Hyperdocs, adding a legal evidence dimension.

### 5.2 Weaknesses

- **Perceived complexity**:
  - Full-environment imaging is heavier to explain than “backup and restore”.
- **AWS-first / AWS-only initially**:
  - Multi-cloud prospects may see it as limited until expansion.
- **Requires relatively mature AWS users**:
  - Organizations without basic AWS hygiene (org structure, IAM, tagging) may struggle.
- **Implementation effort**:
  - Onboarding may require guidance, especially for the first few accounts.

### 5.3 Opportunities

- **Rising DR/BC and compliance pressure**:
  - More audits, more questionnaires, more need to prove recovery and redeployment.
- **Continuous migrations & restructures**:
  - M&A, carve-outs, and landing zone adoption are ongoing, not one-off.
- **MSP, consulting, and partner channels**:
  - IaaC can become a standard component in **DRaaS** and **migration accelerators**.
- **SaaS/platform expansion**:
  - Region roll-outs and tenant migrations need exactly this tooling.
- **Product ecosystem**:
  - Integration with LexBrain/Hyperdocs and future SymK components.

### 5.4 Threats

- **AWS-native catching up**:
  - Resilience Hub, Backup, and DR services might extend toward environment imaging.
- **Large backup/DR vendors expanding scope**:
  - They could bolt control-plane discovery onto their existing offerings.
- **“Good enough” internal scripts and runbooks**:
  - Some organizations will stick to homegrown solutions until they experience a failure.
- **Budget constraints and tool sprawl**:
  - Security/Infra budgets are crowded; IaaC must show clear ROI vs “just another tool”.

---

## 6. Segment Attractiveness & Prioritization

### 6.1 Segment Attractiveness

High-level attractiveness assessment:

- **MSPs**
  - Pros: Faster sales cycles, channel leverage, recurring revenue, DRaaS packaging.  
  - Cons: Price-sensitive, strong expectations on multi-tenant features and SLAs.

- **Cloud-Native Mid-Market (SaaS / FinTech / HealthTech)**
  - Pros: Compliance-driven, open to new tools, strong need for automation and evidence.  
  - Cons: Need clear pricing and tight integration with their DevOps stack.

- **Enterprise Cloud Teams**
  - Pros: Largest deal sizes, strategic reference value.  
  - Cons: Long sales cycles, heavy security/vendor risk scrutiny.

- **LegalTech & Law Firms**
  - Pros: Strong synergy with your other products (LexBrain / Hyperdocs).  
  - Cons: Niche, often later in the adoption curve; benefit from proven references.

- **Consulting Companies**
  - Pros: High reuse of the tool across multiple client engagements; strong word-of-mouth potential.  
  - Cons: Often want **partner-friendly licensing** and may push for discounts.

- **AWS Partners**
  - Pros: Great leverage if integrated into AWS-aligned offerings; co-sell potential.  
  - Cons: Need very clean alignment with AWS best practices and partner programs.

- **SaaS Developers / Platform Teams**
  - Pros: Natural fit for **deployment/deployment** capabilities; continuous usage (not one-off).  
  - Cons: Require robust integration hooks (CI/CD, pipelines, secrets management).

### 6.2 Prioritization

Recommended sequencing:

1. **MSPs + Consulting Companies**  
   - Fastest path to recurring ARR and **DRaaS / migration services** credibility.

2. **Cloud-Native SaaS / FinTech / HealthTech + SaaS Developers**  
   - Compliance-driven early adopters; heavy users of **deployment/clone** capabilities.

3. **AWS Partners**  
   - Once product is stable and referenceable, use as a lever in partner-led deals.

4. **Enterprise Cloud Teams**  
   - After credibility is built; focus on co-sell with AWS and audit bodies.

5. **LegalTech & Law Firms**  
   - Strategic niche, coupled to LexBrain positioning and legal evidence story.

This order is coherent with the IaaC Product Vision and commercial logic.

---

## 7. Buying Triggers & Objections

### 7.1 Common Buying Triggers

Across segments, buying tends to start when:

- Preparing for **SOC 2 / ISO 27001 / HIPAA** or similar audits.
- Answering complex **customer security questionnaires**.
- Experiencing an **incident** (near-miss or actual outage) that exposes DR gaps.
- Planning **region migrations** or **account reorganizations** (exactly where the deployment capability shines).
- MSPs/consultancies launching a new or updated **DRaaS / migration offering**.
- SaaS platforms rolling out **new regions** or **tenant segmentation** across accounts.

### 7.2 Typical Objections

1. “We already use AWS Backup / Elastic DR.”  
   - Response: Those handle backups and host replication, not **full-account rebuild + redeployment + evidence**.

2. “Our vendor handles DR.”  
   - Response: Many vendors focus on data and VM replication; few provide **end-to-end control-plane + identity + compliance evidence + account-to-account cloning**.

3. “This sounds complex / risky.”  
   - Response: Emphasize **simulation**, **dry-runs into sandbox accounts**, and **guardrails**; start with non-critical accounts.

4. “We don’t have time to integrate a new tool.”  
   - Response: Position as a **layer on top of existing AWS setup**, not a replacement of current backups.

---

## 8. Market Size & Commercial Potential (High Level)

Exact TAM/SAM/SOM sizing will rely on external data, but from a qualitative view:

- The **AWS-heavy mid-market** + **enterprises** needing audited DR and deployment capability is large and growing.
- **DRaaS and migration services** are established, monetizable categories for MSPs and consulting firms.
- Willingness to pay ties directly to:
  - **Reduced risk** of catastrophic failure.
  - **Audit speed** and reduced pain in certification processes.
  - **Downtime avoidance** and smoother migrations.

Pricing can be structured in tiers:

- From **team** (few accounts, basic automation)  
- To **enterprise/partner** (multi-account orgs, scheduled drills, multi-tenant evidence packs)  
- Plus **consulting add-ons** for DR/migration readiness assessments.

---

## 9. Risks & Unknowns

Key risks to monitor:

- **AWS-native evolution** (Resilience Hub, Backup, DR services) closing part of the gap.
- Large vendors expanding into **control-plane + identity + deployment** territory.
- MSP/partner channel complexity: onboarding, enablement, co-marketing costs.
- “Do nothing” inertia: many orgs will postpone DR and migration improvements until after a scare.

Unknowns to validate in early discovery:

- How often target customers **actually run DR drills** today, and in what form.
- Who “owns” DR and migrations internally (SRE, Security, Ops, Infra, or someone else).
- Appetite for **SaaS control plane vs self-hosted** deployment models, especially in regulated sectors.

---

## 10. Suggested Machine View — `market_research.json` (Sketch)

The companion `market_research.json` should capture:

- Segments (including **Consulting Companies, AWS Partners, SaaS Developers**).
- Personas and roles.
- Competitors and gaps.
- SWOT factors tagged by segment.

This allows later tools/AI to:

- Recommend messaging by segment.
- Align playbooks (DR, migration, deployment scenarios).
- Cross-link with Product Vision and PLC phases.
