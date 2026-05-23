# IaaC Recovery Suite — Stakeholder Map (PLC 1.3, draft)

## 1. Purpose & Scope

This document maps the **human side** of IaaC:

- Who matters in and around a deal.
- What they **care about** (goals, fears, metrics).
- How IaaC **helps** each one.
- What **friction** to expect.

It feeds:

- **1.1 Product Vision** — which problems are actually political, not technical.  
- **1.2 Market Research** — segment prioritization vs real buying centers.  
- **3.x Go-to-Market & Pricing** — who we sell *to* vs who we sell *through*.

We focus on **roles**, not job titles. Titles will vary; the patterns don’t.

---

## 2. Core Stakeholder Archetypes

### 2.1 Strategic Buyer

**Examples**

- CIO / CTO  
- Head of Cloud / Head of Infrastructure  
- Managing Partner (law firms)  
- Practice Lead / Partner (consulting firms)  
- Partner Principal (AWS partners)  
- VP Platform / VP Engineering (SaaS)

**Goals**

- Reduce **business risk** (outage, data loss, failed migration).  
- Show **board / clients / regulators** that DR and migrations are under control.  
- Avoid building a huge in-house DR/migration team.  
- Keep **cloud costs** and **tool sprawl** under control.

**Fears**

- “We discover our DR is theater when something actually breaks.”  
- “Migrations or account restructures turn into public disasters.”  
- Vendor lock-in that is hard to unwind.  
- Buying “yet another tool” that tech teams quietly ignore.

**What IaaC offers**

- **Environment-level safety net**: account/region reconstruction, not just backups.  
- A narrative for board and external stakeholders:  
  - “We don’t just have snapshots; we have **reproducible environment images (run-ids)**.”  
- A way to standardize DR/migrations without adding headcount.

**Key messaging**

- “This turns your AWS environment into a **managed asset** (imageable, testable, redeployable), not just a pile of resources.”  
- “It reduces the probability of catastrophic DR or migration failure — that’s what you’re actually buying.”

---

### 2.2 Technical Influencer

**Examples**

- Lead Cloud Architect  
- SRE / Platform Engineering Lead  
- Senior DevOps / Infra Engineer  
- MSP Lead Engineer / Technical Owner  
- Principal Consultant (cloud/DR practice)

**Goals**

- Replace brittle **bash + Python + IaC spaghetti** with something structured.  
- Keep **root cause** of DR/migration issues observable and traceable.  
- Run **repeatable drills** without breaking prod or burning weeks.  
- Have a tool that fits into CI/CD and infra-as-code workflows.

**Fears**

- Tools that look pretty in slides but are **operationally painful**.  
- Black-box automation that makes debugging impossible.  
- Vendor tooling that fights IaC, tagging strategies, or AWS best practices.  
- Being blamed when DR/migration fails, even if management underinvested.

**What IaaC offers**

- A **single, structured pipeline**: discover → image → simulate → deploy → report.  
- **Run-id** concept that maps nicely to infra realities:  
  - “When I say run-id X, everyone knows exactly what environment snapshot I mean.”  
- Clear artifacts: JSON manifests, logs, reports — **debuggable**, not magic.

**Key messaging**

- “You’re already scripting this. We’re packaging it without taking control away.”  
- “Run-ids and manifests are designed so *you* can debug and extend them.”  
- “This is built to sit on top of your existing AWS + IaC, not replace it.”

---

### 2.3 Risk / Compliance / Security Stakeholder

**Examples**

- Chief Risk Officer / CISO  
- Compliance Officer (SOC 2, ISO 27001, HIPAA, PCI, etc.)  
- Data Protection Officer (DPO)  
- Internal Auditor / Governance Lead  
- Security & Compliance Partner in law firms

**Goals**

- Answer **audits and security questionnaires** without improvisation.  
- Ensure DR and migrations are **documented, tested, and provable**.  
- Show clear **evidence** of controls and their effectiveness.  
- Have a defensible position if something goes wrong.

**Fears**

- “DR is an undocumented tribal ritual.”  
- Audit findings: “No tested and documented DR process.”  
- Regulatory or contractual non-compliance leading to fines or lawsuits.  
- Tools that produce noisy logs but no **coherent evidence**.

**What IaaC offers**

- **Evidence packs** tied to run-ids:  
  - What was discovered, what was protected, what was simulated, what succeeded/failed.  
- Ability to show **sandbox DR/migration drills** into destination accounts/regions.  
- Structured mapping between **technical steps and controls** (e.g., SOC, ISO clauses).

**Key messaging**

- “We don’t just make DR *possible*; we make it **provable**.”  
- “Every run-id can produce an audit-ready narrative and dataset.”  
- “You can point auditors to **concrete drills**, not PowerPoint.”

---

### 2.4 Finance / Procurement

**Examples**

- CFO / VP Finance  
- Procurement Manager / Vendor Management  
- Commercial Lead in MSPs/consultancies

**Goals**

- Predictable costs; avoid surprise cloud and tool bills.  
- Clear relation between **costs and risk reduction**.  
- Negotiable contracts with **reasonable exit paths**.  
- Prefer **standard pricing models** (per account, per TB, per workload, etc.).

**Fears**

- “This will become another unbounded cloud bill.”  
- Paying for shelfware that dev/ops teams never adopt.  
- Vendor lock-in with painful ramp-down.  
- Complex, opaque metric units (credits, points, magic tokens).

**What IaaC offers**

- A **simple story**: pay per **covered account/org** + **run-id quota**.  
- Clear link between runs and value:  
  - DR drills, migration projects, and environment clones.  
- Partner/MSP models that match **project-based and recurring revenue** patterns.

**Key messaging**

- “You’re not paying per VM or per GB; you’re paying for **environment images and drills**.”  
- “You can see exactly which runs, accounts, and projects justify the spend.”  
- “We support simple tiers and partner discounts; no casino token nonsense.”

---

### 2.5 Operational Users / Delivery Teams

**Examples**

- DR Runbook Owners  
- MSP Service Delivery Managers / Ops Teams  
- L2/L3 Support who execute DR drills  
- Cloud Operations Center staff

**Goals**

- Procedures that **actually work** at 3 a.m.  
- Tools that don’t require five experts on the call.  
- Clear, machine- and human-readable **checklists and outputs**.  
- Ability to **rehearse** before the real incident.

**Fears**

- Being on point during a crisis with **fragile scripts** and incomplete docs.  
- “Shadow tools” that don’t match what was documented.  
- Blame games when things go wrong.

**What IaaC offers**

- Opinionated but flexible **pipelines** with visible stages and logs.  
- Ability to run **sandbox drills** into non-prod accounts.  
- Consistent **output formats** (manifests, PDF reports) they can attach to tickets and change records.

**Key messaging**

- “This is the tool you run when the incident happens — and before, in drills.”  
- “It produces artifacts that plug into your ticketing and change management.”  
- “Your 3 a.m. self will thank your daytime self.”

---

### 2.6 External Stakeholders

**Examples**

- External Auditors  
- Regulators / Supervisory Bodies  
- Key Enterprise Customers (for MSPs/SaaS)  
- AWS Partner Teams / AWS SA / PDM

**Goals**

- Assurance that DR and migrations are **structured, tested, and controlled**.  
- Evidence that **critical workloads** can be moved to safer regions/accounts.  
- Confidence in the **provider’s operational maturity**.

**Fears**

- “Paper DR” — all talk, zero drills.  
- Seeing the same DR incident story for the third year in a row.  
- Providers over-promising beyond their actual capabilities.

**What IaaC offers**

- Concrete **run-id histories** and drill reports.  
- Clear mapping between technical steps and business continuity scenarios.  
- For AWS: a tool that **aligns with orgs, accounts, landing zones, Identity Center**, not against them.

**Key messaging**

- “Here is the account/region image we keep, here is how we test it, here are the results.”  
- “We don’t depend on hero engineers; we depend on **repeatable runs**.”

---

## 3. Segment-Specific Stakeholder Map

High-level matrix: **who matters most in each segment**.

### 3.1 MSPs

- **Primary**
  - Strategic Buyer: CTO / Head of Cloud Ops  
  - Technical Influencer: Lead Cloud Architect / DevOps Lead  
  - Operational: Service Delivery Manager  
- **Secondary**
  - Finance: Commercial / CFO  
  - External: End-customer security teams

**Win theme:**  
> “Turn DR and migrations into a **productized service** with repeatable runs and client-facing evidence.”

---

### 3.2 Cloud-Native Mid-Market (SaaS / FinTech / HealthTech)

- **Primary**
  - Strategic: CTO / VP Engineering  
  - Technical: Platform / SRE Lead  
  - Risk/Compliance: Security/Compliance Officer  
- **Secondary**
  - Finance / Procurement

**Win theme:**  
> “Automate DR and migrations to **tick compliance boxes** without building a DR department.”

---

### 3.3 Enterprise Cloud Teams

- **Primary**
  - Strategic: CIO / Head of Infrastructure  
  - Risk/Compliance: Governance & Risk Management  
  - Technical: DR Lead / Senior Cloud Engineer  
- **Secondary**
  - External: Regulators, big auditors  
  - Finance / Procurement

**Win theme:**  
> “Enterprise-grade **environment imaging and drills** that survive board scrutiny and regulatory audits.”

---

### 3.4 LegalTech & Law Firms

- **Primary**
  - Strategic: Managing Partner / COO  
  - Risk/Compliance: Data Privacy / Compliance Partner  
- **Secondary**
  - Technical: IT Director / Sysadmin  
  - External: Enterprise clients demanding continuity clauses

**Win theme:**  
> “Prove that **case data and evidence** survive region/account loss, with artifacts a lawyer actually understands.”

---

### 3.5 Consulting Companies

- **Primary**
  - Strategic: Practice Lead / Partner (Cloud/Infra/DR)  
  - Technical: Principal Consultant / Senior Architect  
- **Secondary**
  - Operational: Engagement Managers / PMO  
  - Finance: Partner Committee

**Win theme:**  
> “Standardize migrations and DR projects on a **reusable engine**, not per-project heroics.”

---

### 3.6 AWS Partners

- **Primary**
  - Strategic: Partner Principal / Business Lead  
  - Technical: Lead Architect / Technical Account Owner  
- **Secondary**
  - External: AWS SA / Co-sell teams  
  - Finance: Partner Ops

**Win theme:**  
> “Use IaaC as part of your **landing zone / resilience accelerator**, perfectly aligned with AWS constructs.”

---

### 3.7 SaaS Developers / Platform Teams

- **Primary**
  - Strategic: VP Platform / CTO  
  - Technical: Platform Engineering Lead / SRE Lead  
- **Secondary**
  - Risk/Compliance Lead  
  - Finance / Procurement

**Win theme:**  
> “Push a button to **clone prod into a safe account/region** — for DR drills, diagnostics, or expansion.”

---

## 4. Internal Stakeholders (Our Side)

For completeness, the internal map:

- **Product Management**
  - Owns positioning, segment focus, pricing axes (per account, per run-id).
- **Engineering**
  - Owns credibility with Technical Influencers; must avoid “magic black box” design.
- **Sales / Partner Management**
  - Owns relationships with MSPs, consultancies, AWS partners.
- **Customer Success / Support**
  - Owns DR drill onboarding, migration playbook templates, and run-id hygiene.
- **Marketing**
  - Owns narratives for Strategic Buyers and Risk/Compliance (case studies, whitepapers).

---

## 5. How to Use This Map

- In **product decisions**:  
  - Check which role is affected; avoid optimizing only for one archetype.
- In **sales playbooks**:  
  - Tailor **messages and demos** per stakeholder group.
- In **PLC documents**:  
  - Cross-link this map from **1.1 Product Vision** and **1.2 Market Research** wherever we talk about who benefits or who blocks.
