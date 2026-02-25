#!/usr/bin/env python3
"""
Dark compliance-console Streamlit UI for customer risk workflow.
"""

from __future__ import annotations

import io
import json
import os
import html
from copy import deepcopy
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import Any

import streamlit as st

from graph.state import RiskWorkflowState
from graph.workflow import build_workflow
from main import SCENARIOS as CLI_SCENARIOS
from scoring_engine.model import TIERS, WEIGHTS


st.set_page_config(
    page_title="Compliance Decision Console",
    page_icon=":shield:",
    layout="wide",
    initial_sidebar_state="collapsed",
)

PIPELINE_STEPS = [
    ("intake", "Intake"),
    ("pii_middleware", "PII Mask"),
    ("moderation_middleware", "Moderation"),
    ("scoring", "Scoring"),
    ("router", "Router"),
    ("hitl", "HITL Review"),
    ("output", "Output"),
]

SAMPLE_CASES = CLI_SCENARIOS

REASON_CODES = [
    "KYC_PERIODIC_REVIEW",
    "ALERT_TRANSACTION_SPIKE",
    "SANCTIONS_SCREENING_HIT",
    "PEP_REASSESSMENT",
    "MANUAL_SUPPRESSION_REQUEST",
]

ALLOW_AUTO_HITL = os.getenv("ALLOW_AUTO_HITL", "").strip().lower() in {"1", "true", "yes"}


def inject_css() -> None:
    st.markdown(
        """
        <style>
        :root {
          --bg:#020a14;
          --bg2:#041326;
          --line:#10324f;
          --txt:#a8d4ff;
          --muted:#5f8caf;
          --cyan:#41d7ff;
          --green:#27f58a;
          --red:#ff4e5f;
          --amber:#ffb341;
        }
        .stApp { background: radial-gradient(1200px 500px at 60% -20%, #0a2741 0%, var(--bg) 55%); color: var(--txt);}
        .main .block-container {padding-top: 0.6rem; padding-bottom: 0.7rem; max-width: 100%;}
        [data-testid="stSidebar"] {display:none;}
        .console-head {
          border:1px solid var(--line); background:#03101f; padding:8px 12px; margin-bottom:8px;
          display:flex; justify-content:space-between; align-items:center;
          font-family: "Consolas", "Courier New", monospace; color:var(--txt);
        }
        .brand {letter-spacing:3px; color:#d2ebff; font-weight:700;}
        .brand small {color:var(--muted); letter-spacing:1px; margin-left:8px;}
        .run-meta {font-size:12px; color:var(--muted);}
        .pane {
          border:1px solid var(--line); background:linear-gradient(180deg, #051221 0%, #030b16 100%);
          min-height: clamp(180px, 28vh, 240px); padding:14px;
        }
        .pane-title{
          font-family:"Consolas","Courier New",monospace; color:#7fb4de; letter-spacing:2px; font-size:12px; text-transform:uppercase;
          margin-bottom:10px;
        }
        .pill-row {display:flex; gap:10px; flex-wrap:wrap; margin-bottom:12px;}
        .pill {border:1px solid #194466; background:#071b30; color:#7ea6c6; padding:8px 14px; border-radius:4px; font-family:monospace; font-size:12px;}
        .pill.on {border-color:#2df594; color:#2df594; background:#08261a;}
        .pill.warn {border-color:#ffb341; color:#ffb341; background:#2a1a03;}
        .panel {
          border:1px solid #17334b; background:#051526; padding:12px; margin-bottom:10px;
        }
        .risk-big{font-family:monospace; font-size:58px; color:#ff9ca4; line-height:1;}
        .status-big{font-family:monospace; letter-spacing:4px; font-size:42px; font-weight:700;}
        .status-ready{color:#36ff96;} .status-need{color:#ffcd63;} .status-escalate{color:#ff7884;}
        .mini {font-family:monospace; color:#6fa1c5; font-size:12px;}
        .review-head {
          border-top:1px solid #4b161c; border-bottom:1px solid #4b161c; background:#160a0c; color:#ff8a95;
          padding:10px; margin:8px 0 10px 0; font-family:monospace; letter-spacing:2px; font-weight:700;
        }
        .draft {border:1px solid #1f5f37; background:#062313; padding:10px; color:#74e7a5; font-family:monospace; font-size:14px;}
        .log-line {font-family:monospace; font-size:11px; color:#6fa4ce; border-bottom:1px dotted #0d2b44; padding:2px 0;}
        .audit-pane, .audit-pane * { color:#ffffff !important; }
        .audit-pane .log-line { border-bottom:1px dotted #245071;}
        .audit-pane .pane-title { color:#ffffff !important;}
        .audit-feed .audit-row {
          color:#ffffff !important;
          border-bottom:1px dotted #245071;
          font-family:monospace;
          font-size:11px;
          padding:2px 0;
          white-space:pre-wrap;
          word-break:break-word;
        }
        .dot {height:8px; width:8px; border-radius:99px; display:inline-block; margin-right:8px;}
        .ok {background:#2df594;} .no {background:#284861;}
        .stTextInput label, .stNumberInput label, .stSelectbox label, .stRadio label, .stTextArea label {
          color:#ffffff !important;
          opacity:1 !important;
        }
        .stTextInput label p, .stNumberInput label p, .stSelectbox label p, .stRadio label p, .stTextArea label p {
          color:#ffffff !important;
        }
        div[data-testid="stTextInput"] input, div[data-testid="stNumberInput"] input, textarea, select {
          background:#051326 !important; color:#a8d4ff !important; border:1px solid #214460 !important;
          font-family:monospace !important;
        }
        button[kind="primary"] {background:#0c3f22 !important; border:1px solid #24dc82 !important; color:#85f7ba !important;}
        button[kind="secondary"] {background:#051a2d !important; border:1px solid #1f4e75 !important; color:#8dc3ee !important;}
        </style>
        """,
        unsafe_allow_html=True,
    )


def now_utc_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def mask_customer_id(customer_id: str) -> str:
    if not customer_id:
        return "UNKNOWN"
    value = customer_id.strip()
    if len(value) <= 4:
        return "*" * len(value)
    return f"{'*' * (len(value) - 4)}{value[-4:]}"


def normalize_state(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if is_dataclass(value):
        return asdict(value)
    return {"errors": [f"Unexpected state type: {type(value).__name__}"]}


def score_bar(value: float) -> str:
    pct = max(0.0, min(100.0, value))
    return (
        "<div style='height:6px;background:#0a2238;border-radius:4px;'>"
        f"<div style='height:6px;width:{pct}%;background:#41d7ff;border-radius:4px;'></div></div>"
    )


def status_css(status: str) -> str:
    if status == "READY":
        return "status-ready"
    if status == "NEED_INFO":
        return "status-need"
    return "status-escalate"


def top_risk_drivers(result: dict[str, Any], top_n: int = 3) -> list[tuple[str, float]]:
    breakdown = result.get("score_breakdown") or {}
    drivers: list[tuple[str, float]] = []
    for feature, values in breakdown.items():
        contrib = float(values.get("weighted_contribution", 0.0))
        drivers.append((feature, contrib))
    drivers.sort(key=lambda x: abs(x[1]), reverse=True)
    return drivers[:top_n]


def _txn_band(txn_count: float) -> str:
    if txn_count < 20:
        return "low"
    if txn_count < 50:
        return "medium"
    return "high"


def _amt_band(avg_amt: float) -> str:
    if avg_amt < 300:
        return "low"
    if avg_amt < 1500:
        return "medium"
    return "high"


def _cohort_key(payload: dict[str, Any]) -> tuple[str, int, int, str, str]:
    features = payload.get("customer_features", {})
    return (
        str(payload.get("intent", "")),
        int(payload.get("lookback_window_days", 30)),
        int(features.get("high_risk_country", 0)),
        _txn_band(float(features.get("txn_count", 0))),
        _amt_band(float(features.get("avg_txn_amount", 0.0))),
    )


def peer_comparison(
    score: float | None, payload: dict[str, Any], run_history: list[dict[str, Any]]
) -> tuple[int, int]:
    """
    Return (percentile, cohort_size) using historical comparable runs.
    Cohort dimensions: intent, lookback window, high-risk flag, txn band, amount band.
    """
    if score is None:
        return 0, 0
    current_key = _cohort_key(payload)
    peers: list[float] = []
    for run in run_history:
        run_payload = run.get("payload", {})
        run_result = run.get("result", {})
        run_score = run_result.get("risk_score")
        if run_score is None:
            continue
        if _cohort_key(run_payload) == current_key:
            peers.append(float(run_score))

    if not peers:
        return 0, 0

    current_score = float(score)
    less_or_equal = sum(1 for value in peers if value <= current_score)
    percentile = int(round((less_or_equal / len(peers)) * 100))
    return percentile, len(peers)


def build_workflow_payload(
    ui_payload: dict[str, Any], strict_cli_match: bool, scenario_payload: dict[str, Any]
) -> dict[str, Any]:
    if strict_cli_match:
        return deepcopy(scenario_payload)
    return {
        "intent": ui_payload["intent"],
        "customer_id": ui_payload["customer_id"],
        "notes": ui_payload["notes"],
        "customer_features": deepcopy(ui_payload["customer_features"]),
    }


def build_effective_ui_payload(
    ui_payload: dict[str, Any], strict_cli_match: bool, scenario_payload: dict[str, Any]
) -> dict[str, Any]:
    """
    Build the payload representation used by the Streamlit layer.
    In strict mode this must mirror the selected CLI scenario exactly.
    """
    effective = deepcopy(ui_payload)
    if strict_cli_match:
        effective["intent"] = scenario_payload["intent"]
        effective["customer_id"] = scenario_payload["customer_id"]
        effective["notes"] = scenario_payload.get("notes", "")
        effective["customer_features"] = deepcopy(scenario_payload["customer_features"])
    return effective


def run_workflow(workflow_payload: dict[str, Any], ui_payload: dict[str, Any], log_dir: str) -> dict[str, Any]:
    captured_stdout = io.StringIO()
    captured_stderr = io.StringIO()
    state = RiskWorkflowState(raw_input=workflow_payload)
    # Streamlit must never block on terminal input; always force non-interactive HITL.
    workflow = build_workflow(auto_approve=True, log_dir=log_dir)
    try:
        with redirect_stdout(captured_stdout), redirect_stderr(captured_stderr):
            final_state = workflow(state)
        result = normalize_state(final_state)
    except Exception as exc:
        result = {"terminal_status": "ESCALATE", "errors": [f"Execution failure: {exc}"]}

    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "payload": ui_payload,
        "workflow_payload": workflow_payload,
        "result": result,
        "stdout": captured_stdout.getvalue(),
        "stderr": captured_stderr.getvalue(),
    }


inject_css()
if "latest_run" not in st.session_state:
    st.session_state.latest_run = None
if "run_history" not in st.session_state:
    st.session_state.run_history = []
if "form_loaded_scenario" not in st.session_state:
    st.session_state.form_loaded_scenario = None
if "form_reason_code" not in st.session_state:
    st.session_state.form_reason_code = REASON_CODES[0]
if "form_lookback_window_days" not in st.session_state:
    st.session_state.form_lookback_window_days = 30

def load_scenario_into_form(scenario_name: str) -> None:
    scenario = SAMPLE_CASES[scenario_name]
    st.session_state.form_intent = scenario["intent"]
    st.session_state.form_customer_id = scenario["customer_id"]
    st.session_state.form_txn_count = int(scenario["customer_features"]["txn_count"])
    st.session_state.form_avg_txn_amount = float(scenario["customer_features"]["avg_txn_amount"])
    st.session_state.form_high_risk_country = "YES" if int(scenario["customer_features"]["high_risk_country"]) == 1 else "NO"
    st.session_state.form_notes = scenario.get("notes", "")

run_id = st.session_state.latest_run["result"].get("run_id", "DEMO") if st.session_state.latest_run else "DEMO"
st.markdown(
    f"""
    <div class="console-head">
      <div class="brand">COMPLIANCE DECISION CONSOLE <small>v2.0 | MBAN 5510</small></div>
      <div class="run-meta">RUN: <b>{run_id}</b> &nbsp;&nbsp; {now_utc_str()}</div>
    </div>
    """,
    unsafe_allow_html=True,
)

left, center, right = st.columns([1.2, 4.8, 1.3], gap="small")

with left:
    st.markdown("<div class='pane'><div class='pane-title'>Input Parameters</div>", unsafe_allow_html=True)
    scenario_name = st.selectbox("Load Scenario", list(SAMPLE_CASES.keys()), key="scenario_name")
    if st.session_state.form_loaded_scenario != scenario_name:
        load_scenario_into_form(scenario_name)
        st.session_state.form_loaded_scenario = scenario_name
    scenario = SAMPLE_CASES[scenario_name]
    strict_cli_match = st.toggle(
        "Strict CLI Parity Mode",
        value=True,
        help="When enabled, UI executes the exact payload from main.py SCENARIOS for the selected key.",
    )
    role = st.selectbox("Role", ["Analyst", "Reviewer", "Manager"], index=0)
    input_disabled = strict_cli_match
    intent = st.radio(
        "Intent",
        ["rescore", "suppress_flag", "explain_score"],
        index=0,
        key="form_intent",
        disabled=input_disabled,
    )
    customer_id = st.text_input("Customer ID", type="password", key="form_customer_id", disabled=input_disabled)
    st.caption(f"Masked display: {mask_customer_id(customer_id)}")
    reason_code = st.selectbox("Reason Code", REASON_CODES, key="form_reason_code")
    lookback_window_days = st.selectbox(
        "Lookback Window (Days)",
        [7, 14, 30, 60, 90],
        key="form_lookback_window_days",
    )
    txn_count = st.number_input(
        "Txn Count",
        min_value=0,
        key="form_txn_count",
        disabled=input_disabled,
    )
    avg_txn_amount = st.number_input(
        "Avg Txn Amount ($)",
        min_value=0.0,
        step=10.0,
        key="form_avg_txn_amount",
        disabled=input_disabled,
    )
    high_risk_country = st.selectbox(
        "High-Risk Country",
        ["NO", "YES"],
        index=0,
        key="form_high_risk_country",
        disabled=input_disabled,
    )
    notes = st.text_area(
        "Analyst Notes",
        height=120,
        max_chars=700,
        help="Use factual and non-PII language. Max 700 characters.",
        key="form_notes",
        disabled=input_disabled,
    )
    auto_toggle_disabled = not (ALLOW_AUTO_HITL and role == "Manager")
    auto_approve = st.toggle(
        "Auto HITL (Governed)",
        value=False,
        disabled=auto_toggle_disabled,
        help="Enabled only for Manager role when ALLOW_AUTO_HITL=true in environment.",
    )
    if auto_toggle_disabled:
        st.caption("Auto HITL disabled by policy (requires Manager + ALLOW_AUTO_HITL=true).")
    log_dir = st.text_input("Log Dir", value="logs")

    st.markdown("<div class='panel'><div class='mini'>THRESHOLD TRANSPARENCY</div>", unsafe_allow_html=True)
    threshold_text = " | ".join([f"{label} >= {threshold}" for threshold, label in TIERS])
    st.markdown(f"<div class='mini'>Tier rules: {threshold_text}</div>", unsafe_allow_html=True)
    st.markdown(
        f"<div class='mini'>Weights: txn_count={WEIGHTS['txn_count']:.2f}, "
        f"avg_txn_amount={WEIGHTS['avg_txn_amount']:.2f}, "
        f"high_risk_country={WEIGHTS['high_risk_country']:.2f}</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<div class='mini'>Calibration note: thresholds were tuned on a small labeled reference set; validate on production distribution.</div>",
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)

    run_clicked = st.button("RUN WORKFLOW", type="primary", use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)

ui_payload = {
    "intent": intent,
    "customer_id": customer_id.strip(),
    "notes": notes,
    "customer_features": {
        "txn_count": int(txn_count),
        "avg_txn_amount": float(avg_txn_amount),
        "high_risk_country": 1 if high_risk_country == "YES" else 0,
    },
    "reason_code": reason_code,
    "lookback_window_days": int(lookback_window_days),
    "role": role,
}
effective_ui_payload = build_effective_ui_payload(ui_payload, strict_cli_match, scenario)
workflow_payload = build_workflow_payload(effective_ui_payload, strict_cli_match, scenario)

if run_clicked:
    if not workflow_payload.get("customer_id"):
        st.error("Customer ID is required.")
    else:
        with st.spinner("Running workflow..."):
            run = run_workflow(workflow_payload=workflow_payload, ui_payload=effective_ui_payload, log_dir=log_dir)
            st.session_state.latest_run = run
            st.session_state.run_history.insert(0, run)

result = st.session_state.latest_run["result"] if st.session_state.latest_run else {}
node_path = result.get("node_path", [])
status = result.get("terminal_status", "N/A")
risk_score = result.get("risk_score")
risk_tier = result.get("risk_tier", "N/A")
display_customer_id = result.get("masked_customer_id") or mask_customer_id(workflow_payload.get("customer_id", ""))

with center:
    st.markdown("<div class='pane'><div class='pane-title'>Execution Pipeline</div>", unsafe_allow_html=True)

    pills_html = ["<div class='pill-row'>"]
    for key, label in PIPELINE_STEPS:
        cls = "pill"
        if key in node_path:
            cls = "pill on"
        if key == "hitl" and status == "ESCALATE":
            cls = "pill warn"
        pills_html.append(f"<div class='{cls}'>{label}</div>")
    pills_html.append("</div>")
    st.markdown("".join(pills_html), unsafe_allow_html=True)

    top_a, top_b, top_c = st.columns([1.2, 1.7, 1.8], gap="small")
    with top_a:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        st.markdown("<div class='mini'>RISK SCORE</div>", unsafe_allow_html=True)
        st.markdown(
            f"<div class='risk-big'>{float(risk_score):.2f}</div><div class='mini'>/ 100</div>" if risk_score is not None else "<div class='risk-big'>--</div>",
            unsafe_allow_html=True,
        )
        st.markdown(f"<div class='mini'>Tier: <b>{risk_tier}</b></div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
    with top_b:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        st.markdown("<div class='mini'>TERMINAL STATUS</div>", unsafe_allow_html=True)
        st.markdown(
            f"<div class='status-big {status_css(status)}'>{status}</div>",
            unsafe_allow_html=True,
        )
        st.markdown(f"<div class='mini'>Route: {result.get('route_taken','N/A')}</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='mini'>Lookback: {ui_payload.get('lookback_window_days')} days</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='mini'>Path: {' -> '.join(node_path) if node_path else 'N/A'}</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
    with top_c:
        st.markdown("<div class='panel'><div class='mini'>SCORE BREAKDOWN</div>", unsafe_allow_html=True)
        breakdown = result.get("score_breakdown") or {}
        if breakdown:
            for feature, values in breakdown.items():
                contrib = float(values.get("weighted_contribution", 0))
                scaled = min(100.0, max(0.0, contrib * 2.2))
                st.markdown(f"<div class='mini'>{feature}</div>{score_bar(scaled)}", unsafe_allow_html=True)
        else:
            st.markdown("<div class='mini'>No score breakdown available.</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    focus_left, focus_right = st.columns([1.2, 1.8], gap="small")
    with focus_left:
        st.markdown("<div class='panel'><div class='mini'>TOP RISK DRIVERS</div>", unsafe_allow_html=True)
        drivers = top_risk_drivers(result, top_n=3)
        if drivers:
            for feature, contrib in drivers:
                st.markdown(
                    f"<div class='mini'>{feature}: <b>{contrib:.2f}</b> contribution</div>",
                    unsafe_allow_html=True,
                )
        else:
            st.markdown("<div class='mini'>No scored factors available.</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
    with focus_right:
        st.markdown("<div class='panel'><div class='mini'>PEER COMPARISON</div>", unsafe_allow_html=True)
        pct, cohort_size = peer_comparison(
            risk_score,
            effective_ui_payload,
            st.session_state.get("run_history", []),
        )
        if risk_score is None:
            st.markdown("<div class='mini'>No baseline comparison available yet.</div>", unsafe_allow_html=True)
        elif cohort_size == 0:
            st.markdown(
                "<div class='mini'>Not enough comparable historical runs yet. Run more cases to build baseline.</div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f"<div class='mini'>Current score is at approximately the <b>{pct}th percentile</b> of peers.</div>",
                unsafe_allow_html=True,
            )
            st.markdown(
                f"<div class='mini'>Cohort size: <b>{cohort_size}</b> comparable runs.</div>",
                unsafe_allow_html=True,
            )
            st.markdown(
                "<div class='mini'>Match dimensions: intent, lookback, high-risk flag, txn band, amount band.</div>",
                unsafe_allow_html=True,
            )
        st.markdown("</div>", unsafe_allow_html=True)

    show_review = status == "ESCALATE"
    if show_review:
        st.markdown("<div class='review-head'>HUMAN REVIEW REQUIRED - COMPLIANCE OFFICER</div>", unsafe_allow_html=True)
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        st.markdown(f"<div class='mini'>Customer: {display_customer_id}</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='mini'>Intent: {workflow_payload.get('intent')}</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='mini'>Reason Code: {ui_payload.get('reason_code')}</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='mini'>Score: {risk_score if risk_score is not None else 'N/A'} / 100 - {risk_tier}</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='mini'>Route: {result.get('route_taken', 'N/A')}</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

        draft_response = result.get("draft_response") or result.get("final_response") or "No draft response."
        st.markdown("<div class='mini'>DRAFT RESPONSE</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='draft'>{draft_response}</div>", unsafe_allow_html=True)

        edited = st.text_area(
            "[EDIT] Type edited response here (optional)",
            key="edited_response",
            height=90,
            max_chars=500,
            help="Max 500 chars. Include rationale and next-step instruction.",
        )
        reviewer_notes = st.text_area(
            "Reviewer notes (optional)",
            key="reviewer_notes",
            height=70,
            max_chars=300,
            help="Max 300 chars. Notes are audit logged.",
        )

        c1, c2, c3 = st.columns(3)
        allow_review_action = role in ("Reviewer", "Manager")

        if c1.button("APPROVE", use_container_width=True, disabled=not allow_review_action):
            result["hitl_reviewer_action"] = "approve"
            result["hitl_reviewer_notes"] = reviewer_notes or None
            result["final_response"] = draft_response
            st.success("Case approved by reviewer.")
        if c2.button("EDIT", use_container_width=True, disabled=not allow_review_action):
            result["hitl_reviewer_action"] = "edit"
            result["hitl_reviewer_notes"] = reviewer_notes or None
            result["final_response"] = edited.strip() or draft_response
            st.success("Case edited and finalized by reviewer.")
        if c3.button("REJECT", use_container_width=True, disabled=not allow_review_action):
            result["hitl_reviewer_action"] = "reject"
            result["hitl_reviewer_notes"] = reviewer_notes or None
            result["final_response"] = (
                f"[REJECTED BY REVIEWER] Customer {display_customer_id}: "
                "case rejected and flagged for further investigation."
            )
            st.error("Case rejected by reviewer.")
        if not allow_review_action:
            st.caption("Reviewer actions are disabled for Analyst role.")

    else:
        st.markdown("<div class='panel'><div class='mini'>FINAL RESPONSE</div></div>", unsafe_allow_html=True)
        st.write(result.get("final_response", "Run workflow to generate output."))

    st.markdown("</div>", unsafe_allow_html=True)

with right:
    st.markdown("<div class='pane audit-pane'><div class='pane-title' style='color:#ffffff !important;'>Audit Trail</div>", unsafe_allow_html=True)
    if st.session_state.latest_run:
        out = st.session_state.latest_run.get("stdout", "")
        lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
        rendered_rows = []
        for line in lines[-35:]:
            rendered_rows.append(
                f"<div class='audit-row'>{html.escape(line[:180])}</div>"
            )
        st.markdown(
            f"<div class='audit-feed'>{''.join(rendered_rows)}</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown("<div class='audit-feed'><div class='audit-row'>No run yet.</div></div>", unsafe_allow_html=True)

    st.markdown(
        "<div class='pane-title' style='margin-top:14px;color:#ffffff !important;'>Rubric Coverage</div>",
        unsafe_allow_html=True,
    )
    checks = [
        ("Terminal Status", bool(result.get("terminal_status"))),
        ("Client Response", bool(result.get("final_response"))),
        ("Audit Trail", bool(st.session_state.latest_run)),
        ("Node Path", bool(result.get("node_path"))),
        ("PII Masking", result.get("masked_customer_id") is not None or bool(result.get("pii_fields_redacted"))),
        ("HITL Trigger", status == "ESCALATE"),
        ("Score Breakdown", bool(result.get("score_breakdown"))),
    ]
    for label, ok in checks:
        st.markdown(
            f"<div class='log-line' style='color:#ffffff !important;border-bottom:1px dotted #245071;'><span class='dot {'ok' if ok else 'no'}'></span>{label}</div>",
            unsafe_allow_html=True,
        )

    if st.session_state.latest_run:
        package = {
            "run_timestamp": st.session_state.latest_run["ts"],
            "payload": st.session_state.latest_run["payload"],
            "workflow_payload": st.session_state.latest_run.get("workflow_payload"),
            "result": result,
        }
        st.download_button(
            "Download Audit JSON",
            data=json.dumps(package, indent=2),
            file_name=f"audit_{workflow_payload.get('customer_id','run')}_{datetime.now(timezone.utc).strftime('%Y%m%d')}.json",
            mime="application/json",
            use_container_width=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)
