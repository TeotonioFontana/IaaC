# -*- coding: utf-8 -*-
"""
===============================================================================
 phase8_ai_policy_check.py — v4.0.0-alpha1
===============================================================================
 Purpose............: Verify compliance and recovery readiness against AWS
                      documentation using OpenAI API (AI Sentinel).
-------------------------------------------------------------------------------
 Description
 ------------------------------------------------------------------------------
 Uses OpenAI API to query the latest AWS docs for potential policy or service
 changes that could impact recovery viability.  Phase 8 runs only if a valid
 OpenAI API key is available.
===============================================================================
"""
import os, logging
from openai import OpenAI

def run(cfg, logger: logging.Logger) -> dict:
    """Phase 8 — AI Sentinel validation (OpenAI doc cross-check)."""
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        logger.error("[AI] No OpenAI API key found — skipping AI validation.")
        return {"AI_Check": "SKIPPED", "Reason": "Missing API key"}

    client = OpenAI(api_key=api_key)
    prompt = (
        "Summarize any recent AWS documentation updates that may affect EC2 "
        "snapshot or S3 backup restore processes."
    )
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
            temperature=0.3,
        )
        summary = resp.choices[0].message.content.strip()
        logger.info("[AI] OpenAI Sentinel check completed.")
        return {"AI_Check": "OK", "Summary": summary}
    except Exception as e:
        logger.error(f"[AI] API call failed: {e}")
        return {"AI_Check": "FAILED", "Error": str(e)}

if __name__ == "__main__":
    print("Synthetic test: Phase 8 AI Sentinel stub.")
