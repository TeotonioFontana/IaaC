# IaaC Recovery Suite — Discovery Methodologies (PLC 1.4, draft v2)

## 1. Purpose & Scope

This chapter defines **which methodologies** we use to run **PLC_1 Discovery** and its sub-items:

- **1.1 Product Vision**
- **1.2 Market Research**
- **1.3 Stakeholder Map**

It answers:

- How do we *actually* get the inputs for 1.1, 1.2, 1.3?
- Which methods are **mandatory**, which are **optional / nice-to-have**?
- What **artifacts** must exist at the end of PLC_1 for IaaC?

No AWS APIs here. This is about **product discovery**, not infra discovery.

---

## 2. Methodology Toolkit Overview

For PLC_1 we standardize on a small, opinionated toolkit:

1. **Problem Framing & Vision Methods**
   - North Star Narrative
   - “Future Press Release” (or one-pager)
   - Product Box / Elevator Pitch

2. **Customer & Market Discovery Methods**
   - Expert / Customer Discovery Interviews
   - Jobs-to-be-Done (JTBD) framing for key personas
   - Competitor & Alternative Tear-downs
   - Secondary Research (reports, docs, pricing pages)

3. **Stakeholder & Power Mapping Methods**
   - Power–Interest Matrix
   - Buying Center Map (Strategic / Technical / Risk / Finance / Ops)
   - RACI-style view for implementation vs decision power

Each PLC_1 subchapter picks a **subset** of these and defines the **minimum evidence** we want for IaaC.

---

## 3. Methods for 1.1 — Product Vision

### 3.1 Core Questions

- What *exactly* is IaaC solving in the world?
- For whom, in which environments, in which moments?
- Why is this **worth building now**, and why us?

### 3.2 Methods Used

1. **North Star Narrative (Mandatory)**  
   A one-page story that states, in plain language:

   - Who the hero is (e.g., MSP Cloud Lead, SaaS Platform Lead).
   - What nightmare they’re in today (DR theater, brittle migrations).
   - What life looks like with IaaC (environment images, run-ids, repeatable drills).
   - The measurable outcome (reduced DR risk, faster audits, safer migrations).

   **Output:** the current `1.1 Product Vision` doc is *the* North Star artifact. 1.4 just makes that explicit.

2. **Future Press Release (Recommended)**  
   A short, fake press release dated **2–3 years from now**, announcing IaaC’s success:

   - Headline: what the market is celebrating.
   - Customer quote: what a key segment (e.g., MSP or SaaS) says.
   - Metrics: “% reduction in DR drill time”, “number of accounts protected”, etc.

   **Use:** sanity-check the ambition and focus of 1.1.

3. **Product Box / Elevator Pitch (Mandatory for external comms)**  
   A concise boilerplate:

   > “IaaC is a Recovery & Deployment Engine for AWS environments that turns entire accounts/regions into reproducible images (run-ids) you can test, redeploy, and prove to auditors.”

   **Output:** A reusable 2–3 sentence pitch to be used in all PLC docs.

---

## 4. Methods for 1.2 — Market Research

### 4.1 Core Questions

- Which **segments** are we really going after and in what order?
- Who are the **main competitors and alternatives**?
- What gaps exist around **full-environment recovery + deployment + evidence**?

### 4.2 Methods Used

1. **Discovery Interviews (Mandatory for at least 3–5 real conversations)**  
   Semi-structured conversations with people in target roles:

   - MSP leads, SaaS platform leads, Enterprise cloud architects, etc.
   - Focus on **current behavior**, not hypothetical features:
     - “Tell me about your last DR test.”
     - “How do you move workloads between accounts/regions today?”
     - “What was painful in your last audit or migration?”

   **Artifacts:**
   - Short interview notes or summary bullets.
   - Extracted **Jobs-to-be-Done** and pains.

2. **Jobs-to-be-Done (JTBD) Framing (Recommended, light)**  
   For each priority segment, capture:

   - “When I’m **[situation]** …”
   - “I want to **[motivation]** …”
   - “So I can **[expected outcome]** …”

   Example for an MSP:

   - When I’m *preparing a new client for DR audits*,  
   - I want to *standardize the way we image and test their environments*,  
   - So I can *sell DRaaS without hidden operational bombs*.

   **Artifacts:**
   - 3–7 JTBD statements tied to segments defined in 1.2.

3. **Competitor & Alternative Tear-down (Mandatory)**  
   Structured review of:

   - **AWS-native**: Backup, DRS, Resilience Hub, MGN.  
   - **Vendors**: Veeam, Rubrik, Cohesity, Druva, N2WS, Zerto.  
   - **Homegrown scripts and runbooks**.

   For each, we capture:

   - What they **do well**.
   - Where they **stop** (no full environment image, no redeploy, weak evidence).
   - Rough **pricing shape** (per GB, per workload, per subscription).

   **Artifacts:**
   - The `1.2 Market Research` MD (already drafted) **is** the repository of this work.

4. **Secondary Research (Optional but Useful)**  
   - Analyst reports, AWS whitepapers, case studies.
   - We extract only what matters:
     - DR trends, compliance pressure, cloud adoption in target segments.

   **Artifacts:**
   - Short reference list + 3–5 key bullets feeding MR.

---

## 5. Methods for 1.3 — Stakeholder Map

### 5.1 Core Questions

- Who **decides**, who **uses**, who **blocks**, and who **pays**?
- What are their **goals and fears**?
- How does this differ by **segment** (MSP, SaaS, Enterprise, Consulting, AWS partners, Law firms)?

### 5.2 Methods Used

1. **Buying Center Mapping (Mandatory)**  
   For each segment, we map:

   - **Strategic Buyer**
   - **Technical Influencer**
   - **Risk/Compliance Stakeholder**
   - **Finance / Procurement**
   - **Operational User / Delivery**
   - **External stakeholders** (auditors, key customers, AWS)

   This is exactly what we’ve captured in the `1.3 Stakeholder Map` doc. 1.4 just codifies that as the method.

2. **Power–Interest Matrix (Recommended)**  
   For each role:

   - Power (decision/blocking capability) vs Interest (how much they care day-to-day).

   We classify into:

   - **High power / high interest** → core targets for messaging and demos.  
   - **High power / low interest** → need concise risk/ROI narrative.  
   - **Low power / high interest** → champions and early adopters.  
   - **Low power / low interest** → keep informed, don’t overshoot.

   **Artifacts:**
   - A simple table or 2×2 grid embedded or linked from 1.3.

3. **Rough RACI View (Optional, light)**  

   Not a full project RACI, just answering:

   - Who is **Responsible** for running DR drills/migrations?
   - Who is **Accountable** for DR/BC posture?
   - Who needs to be **Consulted** (Risk, AWS, auditors)?
   - Who needs to be **Informed** (board, customers)?

   **Artifacts:**
   - Short section in 1.3 or an appendix.

---

## 6. Evidence Levels & “Done” Criteria for PLC_1

To close PLC_1 for IaaC, we expect:

- **1.1 Product Vision**
  - North Star narrative written and stable.
  - One Future Press Release draft (even if rough).
  - Approved 2–3 sentence elevator pitch.

- **1.2 Market Research**
  - At least **3–5 interviews** summarized (MSPs, SaaS, Enterprise / Consulting mix).  
  - JTBD statements for top 2–3 segments.  
  - Competitor/alternative tear-down captured in the MR MD (done).  

- **1.3 Stakeholder Map**
  - Buying center mapped for each priority segment (done in 1.3).  
  - Power–Interest view at least sketched for MSP + SaaS + Enterprise.  

When these artifacts exist and are coherent, **PLC_1 is “good enough” to move into PLC_2/3** (Solution, Roadmap, and Planning).

---

## 7. How This Ties Back to IaaC Specifically

This isn’t generic startup theory; for IaaC:

- **Vision methods** keep us anchored on “Recovery + Deployment Engine for AWS environments with run-ids and evidence.”
- **Interview + JTBD methods** make sure we’re not fantasizing about DR/migration pain — we’re echoing MSPs, SaaS, Enterprises, Consulting firms, AWS partners, and Law firms.
- **Stakeholder mapping methods** align the tech (run-ids, manifests, drills, deployment) with the political reality (who signs, who blocks, who screams when DR fails).

