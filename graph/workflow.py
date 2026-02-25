"""
graph/workflow.py
=================
LangGraph Workflow Assembly.

This module builds and compiles the StateGraph that orchestrates all nodes
and middleware in the correct order. The graph implements the middleware-style
orchestration pattern required by Section 2B of the project brief.

Architecture:
┌─────────────────────────────────────────────────────────────────────┐
│                    RISK COMPLIANCE WORKFLOW                         │
│                                                                     │
│  START → intake → pii_mw → moderation_mw → scoring → router        │
│                                                                     │
│  router ──ESCALATE──────────→ hitl → output → END                  │
│  router ──READY/NEED_INFO──→        output → END                   │
│  intake ──NEED_INFO (early)──────→  output → END                   │
│                                                                     │
│  Middleware applied as inline nodes in the main path:               │
│    • pii_middleware        (PIIMiddleware)                          │
│    • moderation_middleware (OpenAIModerationMiddleware +            │
│                             ModelFallbackMiddleware)                │
│    • call limit checks     (ToolCallLimit, ModelCallLimit)          │
└─────────────────────────────────────────────────────────────────────┘

LangGraph note: We use StateGraph with a dataclass state and a functional
node pattern. Each node receives the full state and returns the mutated state.
"""

from __future__ import annotations
from functools import partial
from typing import Callable

try:
    from langgraph.graph import StateGraph, END
    LANGGRAPH_AVAILABLE = True
except ImportError:
    LANGGRAPH_AVAILABLE = False

from graph.state import RiskWorkflowState
from graph.nodes.intake import intake_node
from graph.nodes.scoring import scoring_node
from graph.nodes.router import router_node
from graph.nodes.hitl import hitl_node
from graph.nodes.output import output_node
from middleware.pii import run_pii_middleware
from middleware.moderation import run_moderation_middleware


# ── Routing Functions ─────────────────────────────────────────────────────────

def _route_after_intake(state: RiskWorkflowState) -> str:
    """After intake: if early-termination (NEED_INFO), skip to output."""
    if state.terminal_status == "NEED_INFO":
        return "output"
    return "pii_middleware"


def _route_after_router(state: RiskWorkflowState) -> str:
    """After router: ESCALATE triggers HITL, others go straight to output."""
    if state.terminal_status == "ESCALATE":
        return "hitl"
    return "output"


# ── Graph Builder ─────────────────────────────────────────────────────────────

def build_workflow(auto_approve: bool = False, log_dir: str = "logs") -> Callable:
    """
    Build and return the compiled LangGraph workflow.

    Parameters
    ----------
    auto_approve : bypass interactive HITL prompt (for testing/CI)
    log_dir      : directory for audit log output

    Returns
    -------
    A callable that accepts RiskWorkflowState and returns RiskWorkflowState.
    If LangGraph is not installed, returns a fallback sequential runner.
    """

    # Bind parameters to nodes that need them
    hitl_bound = partial(hitl_node, auto_approve=auto_approve)
    output_bound = partial(output_node, log_dir=log_dir)

    if not LANGGRAPH_AVAILABLE:
        # ── Fallback: pure sequential runner (no LangGraph dependency) ────────
        print("[INFO] LangGraph not found. Running in sequential fallback mode.")
        return _build_sequential_runner(hitl_bound, output_bound)

    # ── LangGraph StateGraph ──────────────────────────────────────────────────
    graph = StateGraph(RiskWorkflowState)

    # Register nodes
    graph.add_node("intake",              intake_node)
    graph.add_node("pii_middleware",      run_pii_middleware)
    graph.add_node("moderation_middleware", run_moderation_middleware)
    graph.add_node("scoring",             scoring_node)
    graph.add_node("router",              router_node)
    graph.add_node("hitl",                hitl_bound)
    graph.add_node("output",              output_bound)

    # Set entry point
    graph.set_entry_point("intake")

    # Add edges
    graph.add_conditional_edges(
        "intake",
        _route_after_intake,
        {"output": "output", "pii_middleware": "pii_middleware"},
    )
    graph.add_edge("pii_middleware",        "moderation_middleware")
    graph.add_edge("moderation_middleware", "scoring")
    graph.add_edge("scoring",              "router")
    graph.add_conditional_edges(
        "router",
        _route_after_router,
        {"hitl": "hitl", "output": "output"},
    )
    graph.add_edge("hitl",   "output")
    graph.add_edge("output", END)

    compiled = graph.compile()

    def invoke_wrapper(state: RiskWorkflowState) -> RiskWorkflowState:
        return compiled.invoke(state)
    return invoke_wrapper


def _build_sequential_runner(hitl_fn: Callable, output_fn: Callable) -> Callable:
    """
    Fallback sequential runner that mirrors the LangGraph node sequence.
    Used when LangGraph is not installed — produces identical behavior.
    """
    def run(state: RiskWorkflowState) -> RiskWorkflowState:
        # intake
        state = intake_node(state)
        if state.terminal_status == "NEED_INFO":
            return output_fn(state)

        # middleware chain
        state = run_pii_middleware(state)
        state = run_moderation_middleware(state)

        # scoring
        state = scoring_node(state)

        # router
        state = router_node(state)

        # conditional: HITL or skip
        if state.terminal_status == "ESCALATE":
            state = hitl_fn(state)

        # output
        state = output_fn(state)
        return state

    return run
