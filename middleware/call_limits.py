"""
middleware/call_limits.py
=========================
ToolCallLimitMiddleware + ModelCallLimitMiddleware equivalents.

Responsibilities:
  - Track tool call and model call counts against configured maximums.
  - If limits are exceeded, abort with a structured error instead of
    silently runaway execution — operationally critical in compliance
    workflows where each LLM call may have cost and audit implications.
  - Limits are set in RiskWorkflowState (MAX_TOOL_CALLS, MAX_MODEL_CALLS).
"""

from __future__ import annotations
from graph.state import RiskWorkflowState


class CallLimitExceededError(Exception):
    pass


def check_tool_call_limit(state: RiskWorkflowState, increment: bool = True) -> RiskWorkflowState:
    """
    Check and optionally increment the tool call counter.
    Raises CallLimitExceededError if the limit is breached.
    """
    if increment:
        state.tool_call_count += 1

    if state.tool_call_count > state.MAX_TOOL_CALLS:
        msg = (
            f"ToolCallLimitMiddleware: Limit of {state.MAX_TOOL_CALLS} tool calls exceeded "
            f"(current: {state.tool_call_count}). Run aborted."
        )
        state.errors.append(msg)
        state.terminal_status = "ESCALATE"
        state.route_taken = "tool_call_limit_exceeded"
        raise CallLimitExceededError(msg)

    return state


def check_model_call_limit(state: RiskWorkflowState, increment: bool = True) -> RiskWorkflowState:
    """
    Check and optionally increment the model call counter.
    """
    if increment:
        state.model_call_count += 1

    if state.model_call_count > state.MAX_MODEL_CALLS:
        msg = (
            f"ModelCallLimitMiddleware: Limit of {state.MAX_MODEL_CALLS} model calls exceeded "
            f"(current: {state.model_call_count}). Run aborted."
        )
        state.errors.append(msg)
        state.terminal_status = "ESCALATE"
        state.route_taken = "model_call_limit_exceeded"
        raise CallLimitExceededError(msg)

    return state
