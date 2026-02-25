"""
graph/nodes/router.py
=====================
Router Node — decides the terminal status and routes accordingly.

Routing Logic:
┌────────────────────────────────────────────────────────────────────────┐
│  Condition                              │ Terminal Status │ Route Label  │
├─────────────────────────────────────────┼─────────────────┼──────────────│
│  Moderation failed                      │ ESCALATE        │ mod_fail     │
│  Missing required fields                │ NEED_INFO       │ missing_data │
│  Risk tier = CRITICAL (score ≥ 80)      │ ESCALATE        │ critical_risk│
│  Risk tier = HIGH (score 60–79)         │ ESCALATE        │ high_risk    │
│  suppress_flag + score ≥ 60             │ ESCALATE        │ suppress_review│
│  Risk tier = MEDIUM (score 30–59)       │ READY           │ medium_auto  │
│  Risk tier = LOW  (score < 30)          │ READY           │ low_auto     │
└────────────────────────────────────────────────────────────────────────┘

Safety principle: When in doubt, ESCALATE. The system errs toward human
oversight rather than auto-approval for ambiguous cases.
"""

from __future__ import annotations
from graph.state import RiskWorkflowState


def router_node(state: RiskWorkflowState) -> RiskWorkflowState:
    """
    Evaluate scoring results and assign terminal_status + route_taken.
    """
    state.node_path.append("router")

    # ── Guard: already terminated (e.g., by intake or middleware) ─────────────
    if state.terminal_status is not None:
        return state

    # ── Moderation failure → always escalate ─────────────────────────────────
    if state.moderation_passed is False:
        state.terminal_status = "ESCALATE"
        state.route_taken = "moderation_failure"
        return state

    # ── Missing required scoring data → need more info ────────────────────────
    if state.missing_fields:
        state.terminal_status = "NEED_INFO"
        state.route_taken = "missing_data"
        return state

    # ── Score-based routing ───────────────────────────────────────────────────
    score = state.risk_score or 0.0
    tier = state.risk_tier or "UNKNOWN"

    # Suppress-flag requests at HIGH/CRITICAL risk require dual-control sign-off.
    # Threshold aligns with the ESCALATE boundary (≥40) from the calibrated model.
    if state.intent == "suppress_flag" and score >= 40:
        state.terminal_status = "ESCALATE"
        state.route_taken = "suppress_high_risk_review"
        return state

    if tier in ("CRITICAL",):
        state.terminal_status = "ESCALATE"
        state.route_taken = "critical_risk_auto_escalate"
        return state

    if tier == "HIGH":
        state.terminal_status = "ESCALATE"
        state.route_taken = "high_risk_escalate"
        return state

    # MEDIUM and LOW → auto-approve, no HITL needed
    state.terminal_status = "READY"
    state.route_taken = f"{tier.lower()}_risk_auto_approved"
    return state
