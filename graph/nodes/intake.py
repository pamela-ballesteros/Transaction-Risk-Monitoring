"""
graph/nodes/intake.py
=====================
Intake Node — first node in the LangGraph workflow.

Responsibilities:
  - Parse the raw user payload into typed fields on the state.
  - Validate that required top-level fields are present.
  - Identify the intent (rescore / suppress_flag / explain_score).
  - If validation fails hard, route to NEED_INFO immediately.

Maps to the professor's "Supported Request Types":
  rescore         → re-score a customer (reschedule equivalent)
  suppress_flag   → override/suppress a flag (cancel equivalent)
  explain_score   → retrieve explainability report (prep instructions equivalent)

Feature schema (sourced from customer_risk_scoring.xlsx):
  txn_count         : int   — number of transactions in the period
  avg_txn_amount    : float — average transaction amount (USD)
  high_risk_country : int   — 1 if customer is in a high-risk jurisdiction, else 0
"""

from __future__ import annotations
from graph.state import RiskWorkflowState

VALID_INTENTS = {"rescore", "suppress_flag", "explain_score"}

# Required feature fields — exact columns from the Excel scoring model
REQUIRED_FEATURE_FIELDS = ["txn_count", "avg_txn_amount", "high_risk_country"]


def intake_node(state: RiskWorkflowState) -> RiskWorkflowState:
    """
    Parse raw_input, extract fields, validate intent.
    """
    state.node_path.append("intake")

    payload = state.raw_input or {}

    # ── Extract intent ────────────────────────────────────────────────────────
    intent = payload.get("intent", "").lower().strip()
    if intent not in VALID_INTENTS:
        state.errors.append(
            f"Intake: Unknown or missing intent '{intent}'. "
            f"Valid values: {sorted(VALID_INTENTS)}"
        )
        state.terminal_status = "NEED_INFO"
        state.route_taken = "invalid_intent"
        return state

    state.intent = intent

    # ── Extract customer identity ─────────────────────────────────────────────
    state.customer_id = payload.get("customer_id")
    if not state.customer_id:
        state.errors.append("Intake: customer_id is required.")
        state.terminal_status = "NEED_INFO"
        state.route_taken = "missing_customer_id"
        return state

    # ── Extract optional free-text notes ──────────────────────────────────────
    state.free_text_notes = payload.get("notes", "")

    return state
