"""
graph/nodes/scoring.py
======================
Scoring Node — invokes the risk scoring engine.

Responsibilities:
  - Extract customer features from raw_input.
  - Call compute_score() from the scoring engine.
  - Populate state with score, tier, breakdown, and missing_fields.
  - Respects ToolCallLimitMiddleware via call counter.
  - If the intent is "explain_score", scoring still runs (needed for explanation).
  - If the intent is "suppress_flag", a note is added but scoring still runs
    to validate the suppression is appropriate.
"""

from __future__ import annotations
from graph.state import RiskWorkflowState
from scoring_engine import compute_score
from middleware.call_limits import check_tool_call_limit


def scoring_node(state: RiskWorkflowState) -> RiskWorkflowState:
    """
    Run the risk scoring model against the customer feature data.
    """
    state.node_path.append("scoring")

    # Check call limit before invoking scoring tool
    check_tool_call_limit(state, increment=True)

    payload = state.raw_input or {}
    customer_features = payload.get("customer_features", {})

    if not customer_features:
        state.missing_fields = ["customer_features"]
        state.errors.append("Scoring: No customer_features provided in payload.")
        return state

    # ── Run the model ─────────────────────────────────────────────────────────
    result = compute_score(customer_features)

    state.risk_score = result.score
    state.risk_tier = result.tier
    state.score_breakdown = result.breakdown
    state.missing_fields = result.missing_fields

    # Attach explainability text to free_text_notes context for HITL display
    if state.intent == "explain_score":
        state.free_text_notes = (
            (state.free_text_notes or "") +
            "\n\n[EXPLAINABILITY REPORT]\n" +
            result.explainability_text
        )

    return state
