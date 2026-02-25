"""
middleware/pii.py
=================
PIIMiddleware — equivalent to LangChain's PIIMiddleware pattern.

Responsibilities:
  - Detect and mask customer identifiers, SSNs, account numbers, emails,
    and phone numbers in the workflow state before any logging occurs.
  - Populates state.masked_customer_id and state.pii_fields_redacted.
  - All downstream nodes use masked values in logs; raw values stay in
    state.raw_input only and are never written to the audit trail.
"""

from __future__ import annotations
import re
from graph.state import RiskWorkflowState


_PII_PATTERNS = {
    "ssn":          re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "email":        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
    "phone":        re.compile(r"\b(\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
    "account_num":  re.compile(r"\b\d{10,16}\b"),
}


def mask_customer_id(customer_id: str) -> str:
    """
    Mask all but the last 2 characters of a customer ID for log safety.
    Always prepends at least 4 asterisks so the masked form is never
    identical to the original, even for short IDs like 'C014'.
      CUST-20241107-7842 → ****************42
      C014               → ****14
    """
    if not customer_id:
        return "UNKNOWN"
    visible_chars = min(2, len(customer_id))
    visible = customer_id[-visible_chars:]
    return f"{'*' * max(4, len(customer_id) - visible_chars)}{visible}"


def scrub_free_text(text: str) -> tuple[str, list[str]]:
    """
    Remove PII patterns from analyst free-text notes.
    Returns (scrubbed_text, list_of_redacted_field_types).
    """
    redacted = []
    scrubbed = text
    for pii_type, pattern in _PII_PATTERNS.items():
        if pattern.search(scrubbed):
            scrubbed = pattern.sub(f"[REDACTED-{pii_type.upper()}]", scrubbed)
            redacted.append(pii_type)
    return scrubbed, redacted


def run_pii_middleware(state: RiskWorkflowState) -> RiskWorkflowState:
    """
    LangGraph node function for PII middleware.
    """
    state.node_path.append("pii_middleware")

    if state.customer_id:
        state.masked_customer_id = mask_customer_id(state.customer_id)
        state.pii_fields_redacted.append("customer_id")

    if state.free_text_notes:
        scrubbed, found_types = scrub_free_text(state.free_text_notes)
        state.free_text_notes = scrubbed
        state.pii_fields_redacted.extend(found_types)

    return state
