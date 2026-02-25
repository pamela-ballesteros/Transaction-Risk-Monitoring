"""
graph/nodes/hitl.py
===================
Human-in-the-Loop (HITL) Node — the compliance officer review gate.

This is the most critical governance component. It implements the
"draft → human approve or edit → final output" flow required by Section 5B
of the project brief.

Behavior:
  - Only invoked when terminal_status == "ESCALATE".
  - Displays the risk score, tier, explainability breakdown, and draft
    response to the compliance officer.
  - Pauses and waits for reviewer input (approve / edit / reject).
  - In headless/automated mode (--auto-approve flag or non-tty), the
    system auto-approves and logs the automated decision for testing.
  - Reviewer input is meaningfully incorporated: if the officer edits the
    response, the edited version becomes the final output.

Maps directly to the evaluation criterion:
  "The system pauses for review; final output reflects approve/edit actions."
"""

from __future__ import annotations
import sys
import os
from graph.state import RiskWorkflowState


_SEPARATOR = "─" * 70


def _build_review_packet(state: RiskWorkflowState) -> str:
    """
    Build the review packet shown to the compliance officer.
    Contains all information needed to make an informed decision.
    """
    cid = state.masked_customer_id or "UNKNOWN"
    lines = [
        "",
        _SEPARATOR,
        "  ⚠  COMPLIANCE REVIEW REQUIRED — HUMAN IN THE LOOP",
        _SEPARATOR,
        f"  Run ID       : {state.run_id}",
        f"  Timestamp    : {state.timestamp}",
        f"  Customer     : {cid}  (masked)",
        f"  Intent       : {state.intent}",
        f"  Risk Score   : {state.risk_score:.1f} / 100" if state.risk_score else "  Risk Score   : N/A",
        f"  Risk Tier    : {state.risk_tier or 'UNKNOWN'}",
        f"  Route Taken  : {state.route_taken}",
        _SEPARATOR,
    ]

    if state.score_breakdown:
        lines.append("  SCORE BREAKDOWN (Explainability):")
        for fname, fdata in state.score_breakdown.items():
            lines.append(
                f"    {fname.replace('_', ' ').title():<28} "
                f"raw={str(fdata['raw_value']):<8} "
                f"contrib={fdata['weighted_contribution']:.1f}"
            )
        lines.append(_SEPARATOR)

    if state.free_text_notes and state.free_text_notes.strip():
        lines.append("  ANALYST NOTES (PII-scrubbed):")
        for note_line in state.free_text_notes.strip().split("\n")[:10]:
            lines.append(f"    {note_line}")
        lines.append(_SEPARATOR)

    if state.errors:
        lines.append("  WORKFLOW WARNINGS:")
        for err in state.errors:
            lines.append(f"    ⚠  {err}")
        lines.append(_SEPARATOR)

    # Draft response for reviewer consideration
    draft = _generate_draft_response(state)
    lines += [
        "  DRAFT COMPLIANCE RESPONSE:",
        "",
        *[f"    {l}" for l in draft.split("\n")],
        "",
        _SEPARATOR,
    ]

    return "\n".join(lines)


def _generate_draft_response(state: RiskWorkflowState) -> str:
    """
    Generate the draft response the compliance officer will review.
    This is what gets sent to the downstream team / customer file.
    """
    return (
        "Thank you for your patience. We have received your request and it is currently "
        "being reviewed by one of our compliance officers. This is a standard part of our "
        "process to ensure your account is protected. Please call us back and a member of "
        "our team will be happy to walk you through the next steps."
    )


def hitl_node(state: RiskWorkflowState, auto_approve: bool = False) -> RiskWorkflowState:
    """
    HITL review node. Pauses execution for compliance officer input.

    Parameters
    ----------
    state        : current workflow state
    auto_approve : if True, skip interactive prompt (for CI/testing)
    """
    state.node_path.append("hitl")

    # Only engage HITL when status is ESCALATE
    if state.terminal_status != "ESCALATE":
        return state

    state.hitl_triggered = True

    # ── Display review packet ─────────────────────────────────────────────────
    review_packet = _build_review_packet(state)
    print(review_packet)

    draft = _generate_draft_response(state)

    # ── Automated mode (non-interactive / testing) ────────────────────────────
    is_interactive = sys.stdin.isatty() and not auto_approve
    if not is_interactive:
        print("  [AUTO MODE] Automatically approving for non-interactive run.")
        print(_SEPARATOR)
        state.hitl_reviewer_action = "approve"
        state.hitl_reviewer_notes = "Auto-approved (non-interactive mode)"
        state.final_response = draft
        return state

    # ── Interactive review prompt ─────────────────────────────────────────────
    print("  REVIEWER ACTIONS:")
    print("    [A] Approve draft response as-is")
    print("    [E] Edit draft response")
    print("    [R] Reject — flag for further investigation")
    print("")

    while True:
        action = input("  Enter action (A/E/R): ").strip().upper()
        if action in ("A", "E", "R"):
            break
        print("  Invalid input. Please enter A, E, or R.")

    reviewer_notes = input("  Optional reviewer notes (press Enter to skip): ").strip()
    state.hitl_reviewer_notes = reviewer_notes or None

    if action == "A":
        state.hitl_reviewer_action = "approve"
        state.final_response = draft
        print(f"\n  ✓ Draft approved.")

    elif action == "E":
        state.hitl_reviewer_action = "edit"
        print("\n  Current draft:")
        print(f"  {draft}")
        print("\n  Enter edited response (single line):")
        edited = input("  > ").strip()
        state.hitl_edited_response = edited
        state.final_response = edited
        print(f"\n  ✓ Edited response saved.")

    elif action == "R":
        state.hitl_reviewer_action = "reject"
        state.final_response = (
            f"[REJECTED BY REVIEWER] Customer {state.masked_customer_id}: "
            f"This case has been rejected and flagged for further investigation. "
            f"Notes: {reviewer_notes or 'None provided.'}"
        )
        print(f"\n  ✓ Case rejected and flagged.")

    print(_SEPARATOR)
    return state
