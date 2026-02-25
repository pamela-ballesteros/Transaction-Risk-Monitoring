"""
middleware/moderation.py
========================
ModerationMiddleware — equivalent to OpenAIModerationMiddleware pattern.

Responsibilities:
  - Screen analyst free-text notes attached to customer records for content
    that should not proceed into the workflow (e.g., discriminatory language,
    content that could bias a compliance decision inappropriately).
  - Uses OpenAI moderation API when OPENAI_API_KEY is available.
  - Falls back to a lightweight keyword-based heuristic if API is unavailable
    (ModelFallbackMiddleware pattern).
  - Sets state.moderation_passed and state.moderation_reason.

If moderation fails, the workflow routes to ESCALATE for human review
rather than silently proceeding.
"""

from __future__ import annotations
import os
from graph.state import RiskWorkflowState


# ── Fallback keyword heuristic (when no API key available) ────────────────────
_FLAGGED_KEYWORDS = [
    "kill", "threat", "harm", "discriminat", "racist", "sexist",
    "fabricat", "fake", "falsif", "bribe",
]


def _heuristic_moderate(text: str) -> tuple[bool, str]:
    """
    Lightweight fallback moderation.
    Returns (passed: bool, reason: str).
    """
    lower = text.lower()
    for kw in _FLAGGED_KEYWORDS:
        if kw in lower:
            return False, f"Flagged by heuristic moderation: keyword '{kw}' detected."
    return True, "Passed heuristic moderation."


def _openai_moderate(text: str) -> tuple[bool, str]:
    """
    Call OpenAI moderation endpoint.
    Falls back to heuristic on any error (ModelFallbackMiddleware pattern).
    """
    try:
        import openai
        client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        response = client.moderations.create(input=text)
        result = response.results[0]
        if result.flagged:
            triggered = [cat for cat, val in result.categories.__dict__.items() if val]
            return False, f"OpenAI moderation flagged: {triggered}"
        return True, "Passed OpenAI moderation."
    except Exception as e:
        # ModelFallbackMiddleware: degrade gracefully
        return _heuristic_moderate(text)


def run_moderation_middleware(state: RiskWorkflowState) -> RiskWorkflowState:
    """
    LangGraph node function for moderation middleware.
    Only runs if free_text_notes is present.
    """
    state.node_path.append("moderation_middleware")

    if not state.free_text_notes or not state.free_text_notes.strip():
        state.moderation_passed = True
        state.moderation_reason = "No free-text notes to moderate."
        return state

    if os.environ.get("OPENAI_API_KEY"):
        passed, reason = _openai_moderate(state.free_text_notes)
    else:
        passed, reason = _heuristic_moderate(state.free_text_notes)

    state.moderation_passed = passed
    state.moderation_reason = reason

    return state
