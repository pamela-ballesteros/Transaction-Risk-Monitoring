"""
graph/state.py
==============
Defines the shared state object that flows through every LangGraph node.
All fields are typed; None means "not yet populated".
"""

from __future__ import annotations
from typing import Annotated, Literal, Optional
from dataclasses import dataclass, field
from datetime import datetime
import uuid


# ── Terminal Status Set ────────────────────────────────────────────────────────
# Documented closed set required by Section 4 of the project brief.
#   READY       → score computed, low risk, auto-approved, no human review needed
#   NEED_INFO   → required fields missing; workflow paused pending data
#   ESCALATE    → high risk detected; routed to compliance officer for HITL review
TerminalStatus = Literal["READY", "NEED_INFO", "ESCALATE"]

# ── Request Intent Types ───────────────────────────────────────────────────────
# Maps to the three required intents in Section 2A:
#   rescore         → Re-score a customer record  (≈ reschedule appointment)
#   suppress_flag   → Override / suppress a risk flag (≈ cancel appointment)
#   explain_score   → Retrieve explainability report  (≈ prep instructions)
IntentType = Literal["rescore", "suppress_flag", "explain_score"]


@dataclass
class RiskWorkflowState:
    """
    Central state object passed between every node in the LangGraph workflow.
    Fields are populated progressively as execution moves through the graph.
    """

    # ── Run Identity ──────────────────────────────────────────────────────────
    run_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8].upper())
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

    # ── Raw Input (before PII masking) ────────────────────────────────────────
    raw_input: Optional[dict] = None          # original user payload
    intent: Optional[IntentType] = None       # parsed intent
    customer_id: Optional[str] = None         # original customer identifier
    free_text_notes: Optional[str] = None     # analyst free-text (moderation scanned)

    # ── After PII Middleware ──────────────────────────────────────────────────
    masked_customer_id: Optional[str] = None  # e.g. "CUST-****-7842"
    pii_fields_redacted: list[str] = field(default_factory=list)

    # ── After Moderation Middleware ───────────────────────────────────────────
    moderation_passed: Optional[bool] = None
    moderation_reason: Optional[str] = None

    # ── After Scoring Engine ──────────────────────────────────────────────────
    risk_score: Optional[float] = None        # 0.0 – 100.0
    risk_tier: Optional[str] = None           # LOW / MEDIUM / HIGH / CRITICAL
    score_breakdown: Optional[dict] = None    # feature-level explanation
    missing_fields: list[str] = field(default_factory=list)

    # ── After Router ─────────────────────────────────────────────────────────
    terminal_status: Optional[TerminalStatus] = None
    route_taken: Optional[str] = None         # human-readable path label

    # ── After HITL Node ──────────────────────────────────────────────────────
    hitl_triggered: bool = False
    hitl_reviewer_action: Optional[str] = None    # "approve" | "edit" | "reject"
    hitl_reviewer_notes: Optional[str] = None
    hitl_edited_response: Optional[str] = None

    # ── Final Output ──────────────────────────────────────────────────────────
    final_response: Optional[str] = None
    node_path: list[str] = field(default_factory=list)   # audit trail
    errors: list[str] = field(default_factory=list)

    # ── Call Limit Counters (ToolCallLimitMiddleware equivalent) ──────────────
    tool_call_count: int = 0
    model_call_count: int = 0
    MAX_TOOL_CALLS: int = 10
    MAX_MODEL_CALLS: int = 5
