"""
graph/nodes/output.py
=====================
Output Node — final node in every execution path.

Responsibilities:
  - Ensure final_response is populated regardless of path taken.
  - Produce the three required outputs from Section 4:
      1. Final system status  (READY / NEED_INFO / ESCALATE)
      2. Final client-facing response
      3. Verifiable execution evidence (audit log)
  - Write the audit log to stdout (always) and optionally to a .log file.
  - Ensure NO sensitive values appear in the log output.
"""

from __future__ import annotations
import os
import json
from datetime import datetime
from graph.state import RiskWorkflowState


_SEP = "═" * 70


def _build_final_response_if_missing(state: RiskWorkflowState) -> str:
    """
    If the workflow ended without setting final_response (e.g., READY path
    that never hit HITL), generate an appropriate auto-response here.
    """
    if state.final_response:
        return state.final_response

    cid = state.masked_customer_id or "UNKNOWN"
    status = state.terminal_status

    if status == "READY":
        intent_msg = {
            "rescore":       f"Customer {cid} has been re-scored. "
                             f"Risk score: {state.risk_score:.1f} ({state.risk_tier} tier). "
                             f"Status: Cleared for normal processing.",
            "suppress_flag": f"Flag suppression for customer {cid} has been approved. "
                             f"Risk score: {state.risk_score:.1f} ({state.risk_tier} tier). "
                             f"The flag has been suppressed as requested.",
            "explain_score": f"Score explanation for customer {cid}: "
                             f"Risk score {state.risk_score:.1f} ({state.risk_tier} tier). "
                             f"See score breakdown for feature-level detail.",
        }.get(state.intent or "", f"Request for customer {cid} processed. Status: READY.")
        return intent_msg

    elif status == "NEED_INFO":
        missing = ", ".join(state.missing_fields) if state.missing_fields else "unspecified fields"
        errors = " | ".join(state.errors) if state.errors else ""
        return (
            f"Cannot process request for customer {cid}. "
            f"Additional information required: {missing}. "
            f"{errors}"
        ).strip()

    return f"Request for customer {cid} completed with status: {status}."


def _build_audit_log(state: RiskWorkflowState) -> dict:
    """
    Build the structured audit log.
    CRITICAL: No raw PII — only masked identifiers appear here.
    """
    return {
        "run_id":              state.run_id,
        "timestamp":           state.timestamp,
        "intent":              state.intent,
        "customer_id_masked":  state.masked_customer_id or "NOT_SET",
        "terminal_status":     state.terminal_status,
        "route_taken":         state.route_taken,
        "node_path":           state.node_path,
        "risk_score":          state.risk_score,
        "risk_tier":           state.risk_tier,
        "pii_fields_redacted": state.pii_fields_redacted,
        "moderation_passed":   state.moderation_passed,
        "moderation_reason":   state.moderation_reason,
        "missing_fields":      state.missing_fields,
        "hitl_triggered":      state.hitl_triggered,
        "hitl_reviewer_action": state.hitl_reviewer_action,
        "hitl_reviewer_notes":  state.hitl_reviewer_notes,
        "tool_call_count":     state.tool_call_count,
        "model_call_count":    state.model_call_count,
        "errors":              state.errors,
        # final_response is included in the console output separately
    }


def output_node(state: RiskWorkflowState, log_dir: str = "logs") -> RiskWorkflowState:
    """
    Final output node. Produces all required Section 4 outputs.
    """
    state.node_path.append("output")

    # ── Ensure final response exists ──────────────────────────────────────────
    state.final_response = _build_final_response_if_missing(state)

    # ── Build audit log ───────────────────────────────────────────────────────
    audit = _build_audit_log(state)

    # ── Console Output (required Section 4 outputs) ───────────────────────────
    print("")
    print(_SEP)
    print("  RISK COMPLIANCE WORKFLOW — EXECUTION COMPLETE")
    print(_SEP)
    print(f"  Run ID          : {state.run_id}")
    print(f"  Timestamp       : {state.timestamp}")
    print(f"  ── TERMINAL STATUS ──────────────────────────────────────────")
    print(f"  Status          : {state.terminal_status}")
    print(f"  Route Taken     : {state.route_taken}")
    print(f"  Node Path       : {' → '.join(state.node_path)}")
    print(f"  ── CLIENT-FACING RESPONSE ───────────────────────────────────")
    print(f"")
    for line in (state.final_response or "").split(". "):
        if line.strip():
            print(f"  {line.strip()}.")
    print(f"")
    print(f"  ── RISK METRICS ─────────────────────────────────────────────")
    if state.risk_score is not None:
        print(f"  Risk Score      : {state.risk_score:.1f} / 100")
        print(f"  Risk Tier       : {state.risk_tier}")
    if state.hitl_triggered:
        print(f"  HITL Action     : {state.hitl_reviewer_action}")
    if state.errors:
        print(f"  Warnings        : {len(state.errors)} warning(s) — see audit log")
    print(_SEP)

    # ── Write audit log to file ───────────────────────────────────────────────
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, f"run_{state.run_id}_{state.timestamp[:10]}.json")
    with open(log_path, "w") as f:
        json.dump(audit, f, indent=2)

    print(f"  Audit log saved : {log_path}")
    print(_SEP)
    print("")

    return state
