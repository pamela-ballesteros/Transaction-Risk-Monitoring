# Customer Risk Scoring — Governed, Auditable Compliance Workflow
### MBAN 5510 Final Project | Saint Mary's University Sobey School of Business

> **LinkedIn Demo:** (https://www.linkedin.com/feed/update/urn:li:activity:7432517664650182656/)
> **GitHub:** `pamela-ballesteros/customer-risk-scoring-langgraph`

---

## Table of Contents
1. [Project Overview](#1-project-overview)
2. [Architecture & Design Decisions](#2-architecture--design-decisions)
3. [Middleware Components Used](#3-middleware-components-used)
4. [Terminal Status Set](#4-terminal-status-set)
5. [Environment Setup](#5-environment-setup)
6. [How to Run the CLI](#6-how-to-run-the-cli)
7. [Human-in-the-Loop Workflow](#7-human-in-the-loop-workflow)
8. [Running Tests](#8-running-tests)
9. [Project-to-Brief Mapping](#9-project-to-brief-mapping)
10. [Assumptions](#10-assumptions)

---

## 1. Project Overview

This project elevates an existing Excel-to-Python customer risk scoring model
into a **governed, auditable compliance workflow** orchestrated by LangGraph.

The system processes three types of compliance requests, applies a middleware safety stack, produces
an explainability report at the point of human review, and emits a structured
audit log on every run.

### Domain Context
Financial institutions must assign risk scores to customers for AML/KYC compliance.
When a customer is flagged HIGH or CRITICAL, a human compliance officer must
review the case before any action proceeds — this is the **Human-in-the-Loop**
gate. The system implements this as a first-class LangGraph node, not as an
afterthought.

---

## 2. Architecture & Design Decisions

### Workflow Graph

```
START
  │
  ▼
[intake]  ──── NEED_INFO (invalid intent / missing customer_id) ────┐
  │                                                                  │
  ▼                                                                  │
[pii_middleware]     ← masks customer_id, scrubs PII from notes     │
  │                                                                  │
  ▼                                                                  │
[moderation_middleware]  ← screens free-text for flagged content    │
  │                                                                  │
  ▼                                                                  │
[scoring]    ← invokes the Excel-derived risk scoring engine        │
  │                                                                  │
  ▼                                                                  │
[router]     ← assigns READY / NEED_INFO / ESCALATE                 │
  │                                                                  │
  ├─── READY / NEED_INFO ──────────────────────────────────────────►│
  │                                                                  │
  └─── ESCALATE ──► [hitl]  ← compliance officer review gate        │
                      │                                              │
                      ▼                                              │
                   [output] ◄──────────────────────────────────────┘
                      │
                     END
```

### Key Design Decisions

**1. Middleware as First-Class Graph Nodes**  
Rather than wrapping middleware around the graph externally, each middleware
component is a named node in the StateGraph. This means every middleware
action appears in `node_path` and is fully traceable in the audit log.
This is a deliberate choice — in a regulated environment, you need to prove
that PII masking and moderation *actually ran*, not just that they were
configured.

**2. Safety-First Routing**  
The router errs toward ESCALATE on ambiguity. CRITICAL and HIGH tiers always
escalate. MEDIUM and LOW auto-approve. Flag suppression requests on any
HIGH/CRITICAL customer also escalate — an important safeguard against
compliance officers accidentally suppressing legitimate red flags.

**3. Scoring Engine Separation**  
The risk scoring model (`scoring_engine/`) is kept isolated from the
orchestration layer (`graph/`). This mirrors the existing repository structure
and means the model can be updated (e.g., retrained weights, new Excel input)
without touching the workflow logic.

**4. Sequential Fallback Mode**  
If LangGraph is not installed, the workflow falls back to an identical
sequential runner. This ensures the system runs end-to-end in any environment
without requiring the full dependency stack, which is practical for demo
purposes.

**5. Audit Log Design**  
The audit log intentionally contains `customer_id_masked` but never `customer_id`.
Raw PII is stored only in `state.raw_input` during runtime and is never
serialized to disk. This satisfies both the brief's log masking requirement
and real-world data residency constraints.

---

## 3. Middleware Components Used

| Middleware | Implementation | Purpose |
|---|---|---|
| **PIIMiddleware** | `middleware/pii.py` | Masks customer IDs and scrubs SSN/email/phone/account numbers from analyst notes before any logging |
| **OpenAIModerationMiddleware** | `middleware/moderation.py` | Screens free-text analyst notes via OpenAI Moderation API |
| **ModelFallbackMiddleware** | `middleware/moderation.py` | If OpenAI API is unavailable, falls back to keyword heuristic — run never crashes |
| **ToolCallLimitMiddleware** | `middleware/call_limits.py` | Caps tool invocations at `MAX_TOOL_CALLS` (default: 10); prevents runaway scoring loops |
| **ModelCallLimitMiddleware** | `middleware/call_limits.py` | Caps LLM calls at `MAX_MODEL_CALLS` (default: 5) |
| **HumanInTheLoopMiddleware** | `graph/nodes/hitl.py` | Full HITL gate: pause → display explainability packet → approve / edit / reject → incorporate into final output |
| **ContextEditingMiddleware** | `graph/nodes/hitl.py` | Reviewer can edit the draft response; edited version becomes `final_response` |

### Integration with LangGraph State and Routing

Each middleware node reads from and writes to `RiskWorkflowState`.
The router's conditional edges use state fields set by middleware:

- `moderation_passed = False` → router sends to ESCALATE (moderation_failure route)
- `pii_fields_redacted` → logged in audit trail, visible to HITL reviewer
- `tool_call_count > MAX_TOOL_CALLS` → raises `CallLimitExceededError`,
  sets `terminal_status = ESCALATE`, halts run

---

## 4. Terminal Status Set

The system uses exactly three terminal statuses, documented as a closed set:

| Status | Meaning | Typical Path |
|---|---|---|
| `READY` | Risk computed; tier is LOW or MEDIUM; auto-approved | Score < 40 |
| `NEED_INFO` | Required data is missing or request is malformed | Missing fields, invalid intent |
| `ESCALATE` | HIGH or CRITICAL risk, or governance trigger; requires human review | Score ≥ 40, moderation failure, suppress-flag on HIGH/CRITICAL customer |

**Score tier thresholds** (source: `scoring_engine/model.py`):

| Tier | Score Range | Terminal Status |
|---|---|---|
| `LOW` | 0 – 19.99 | READY |
| `MEDIUM` | 20.00 – 39.99 | READY |
| `HIGH` | 40.00 – 54.99 | ESCALATE |
| `CRITICAL` | ≥ 55.00 | ESCALATE |

Exit codes: `READY=0`, `NEED_INFO=2`, `ESCALATE=3`

---

## 5. Environment Setup

### Requirements
- Python 3.10+
- pip

### Install

```bash
git clone https://github.com/pamela-ballesteros/customer-risk-scoring-langgraph
cd customer-risk-scoring-langgraph
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Configure Environment Variables

```bash
cp .env.example .env
# Edit .env — add OPENAI_API_KEY if you want live moderation
# Leave blank to use heuristic moderation fallback (works without any API key)
```

**Note:** LangGraph is in `requirements.txt`. If it fails to install, the
system automatically uses the sequential fallback runner — all functionality
is identical.

---

## 6. How to Run the CLI

### Optional Web UI (Streamlit)

You can run the same workflow in a browser:

```bash
streamlit run ui_app.py
```

The UI lets you:
- choose intent (`rescore`, `suppress_flag`, `explain_score`)
- enter customer fields (`txn_count`, `avg_txn_amount`, `high_risk_country`)
- run the existing `build_workflow()` orchestration
- view terminal status, route, score, node path, HITL metadata, and final state JSON

By default, use **Auto-approve HITL** in the sidebar so web runs stay non-interactive.

---

### List available scenarios

```bash
python main.py --list-scenarios
```

Expected output:

```
Available test scenarios:
--------------------------------------------------
  C002                 intent=rescore         customer=C002
  C007                 intent=rescore         customer=C007
  C018                 intent=rescore         customer=C018
  C013                 intent=rescore         customer=C013
  C010                 intent=rescore         customer=C010
  C015                 intent=rescore         customer=C015
  C006                 intent=rescore         customer=C006
  C008                 intent=rescore         customer=C008
  C020                 intent=rescore         customer=C020
  C014                 intent=rescore         customer=C014
  C001                 intent=rescore         customer=C001
  C004                 intent=rescore         customer=C004
  C009                 intent=rescore         customer=C009
  suppress_C006        intent=suppress_flag   customer=C006
  suppress_C013        intent=suppress_flag   customer=C013
  explain_C008         intent=explain_score   customer=C008
  explain_C002         intent=explain_score   customer=C002
  missing_data         intent=rescore         customer=C-INCOMPLETE
```

---

### Scenario 1 — Normal Path (READY — Low Risk)

```bash
python main.py --scenario C002 --auto-approve
```

Expected output:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  MBAN 5510 — Customer Risk Scoring: Governed Compliance Workflow
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Intent    : rescore
  Customer  : C002
  Auto HITL : Yes
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Run ID      : 3A1F9C02
  Timestamp   : 2026-02-25T12:48:00.000000Z
  Customer    : ****02  (masked)
  Intent      : rescore
  Risk Score  : 6.4 / 100
  Risk Tier   : LOW
  Route Taken : low_risk_auto_approved
  Status      : READY

  Node Path   : intake → pii_middleware → moderation_middleware → scoring → router → output
```

---

### Scenario 2 — Normal Path (READY — Explain Score)

```bash
python main.py --scenario explain_C002 --auto-approve
```

Expected output:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  MBAN 5510 — Customer Risk Scoring: Governed Compliance Workflow
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Intent    : explain_score
  Customer  : C002
  Auto HITL : Yes
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Run ID      : 7BE9CC02
  Timestamp   : 2026-02-25T12:49:00.000000Z
  Customer    : ****02  (masked)
  Intent      : explain_score
  Risk Score  : 6.4 / 100
  Risk Tier   : LOW
  Route Taken : low_risk_auto_approved
  Status      : READY

  SCORE BREAKDOWN (Explainability):
    Txn Count          raw=12.0      contrib=5.7
    Avg Txn Amount     raw=90.0      contrib=0.7
    High Risk Country  raw=0         contrib=0.0

  Node Path   : intake → pii_middleware → moderation_middleware → scoring → router → output
```

---

### Scenario 3 — Escalation Path (ESCALATE — High Risk with HITL)

```bash
# Interactive: you will be prompted to approve / edit / reject
python main.py --scenario C008

# Non-interactive (for demo recording):
python main.py --scenario C008 --auto-approve
```

Expected output:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  MBAN 5510 — Customer Risk Scoring: Governed Compliance Workflow
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Intent    : rescore
  Customer  : C008
  Auto HITL : No (interactive)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠ COMPLIANCE REVIEW REQUIRED — HUMAN IN THE LOOP

  Run ID      : A4D2BC08
  Timestamp   : 2026-02-25T12:50:00.000000Z
  Customer    : ****08  (masked)
  Intent      : rescore
  Risk Score  : 46.4 / 100
  Risk Tier   : HIGH
  Route Taken : high_risk_escalate

  SCORE BREAKDOWN (Explainability):
    Txn Count          raw=25.0      contrib=13.1
    Avg Txn Amount     raw=1500.0    contrib=13.3
    High Risk Country  raw=1         contrib=20.0

  ANALYST NOTES (PII-scrubbed):
    Flagged: moderate-to-high transaction amounts from a high-risk country. EDD recommended.

  DRAFT COMPLIANCE RESPONSE:
    Customer ****08 has been flagged for enhanced due diligence (EDD). Risk score: 46.4
    (HIGH tier). The re-scoring request requires compliance officer sign-off before
    proceeding. Please review the score breakdown and supporting documentation before
    making a determination.

  REVIEWER ACTIONS:
    [A] Approve draft response as-is
    [E] Edit draft response
    [R] Reject — flag for further investigation

  Enter action (A/E/R):
```

---

### Scenario 4 — Escalation Path (ESCALATE — Critical Risk)

This is the highest-scoring customer in the dataset. The expected output below
reflects an actual run of `python main.py --scenario C014`.

```bash
python main.py --scenario C014
```

Expected output:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  MBAN 5510 — Customer Risk Scoring: Governed Compliance Workflow
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Intent    : rescore
  Customer  : C014
  Auto HITL : No (interactive)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠ COMPLIANCE REVIEW REQUIRED — HUMAN IN THE LOOP

  Run ID      : D6C0BCA9
  Timestamp   : 2026-02-25T12:47:30.257213Z
  Customer    : ****14  (masked)
  Intent      : rescore
  Risk Score  : 55.9 / 100
  Risk Tier   : CRITICAL
  Route Taken : critical_risk_auto_escalate

  SCORE BREAKDOWN (Explainability):
    Txn Count          raw=26.0      contrib=13.7
    Avg Txn Amount     raw=2500.0    contrib=22.2
    High Risk Country  raw=1         contrib=20.0

  ANALYST NOTES (PII-scrubbed):
    Flagged: highest risk score in dataset. Large transactions from high-risk country.
    Compliance review required.

  DRAFT COMPLIANCE RESPONSE:
    Customer ****14 has been flagged for enhanced due diligence (EDD). Risk score: 55.9
    (CRITICAL tier). The re-scoring request requires compliance officer sign-off before
    proceeding. Please review the score breakdown and supporting documentation before
    making a determination.

  REVIEWER ACTIONS:
    [A] Approve draft response as-is
    [E] Edit draft response
    [R] Reject — flag for further investigation

  Enter action (A/E/R):
```

---

### Scenario 5 — NEED_INFO Path (Missing Data)

```bash
python main.py --scenario missing_data --auto-approve
```

Expected output:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  MBAN 5510 — Customer Risk Scoring: Governed Compliance Workflow
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Intent    : rescore
  Customer  : C-INCOMPLETE
  Auto HITL : Yes
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Run ID      : 5F33A0D2
  Timestamp   : 2026-02-25T12:51:00.000000Z
  Customer    : ****D2  (masked)
  Intent      : rescore
  Status      : NEED_INFO
  Route Taken : need_info_missing_fields

  Additional information required: ['avg_txn_amount', 'high_risk_country']

  Node Path   : intake → pii_middleware → moderation_middleware → scoring → output
```

---

### Scenario 6 — Suppress Flag (ESCALATE — High Risk Customer)

```bash
python main.py --scenario suppress_C006 --auto-approve
```

Expected output:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  MBAN 5510 — Customer Risk Scoring: Governed Compliance Workflow
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Intent    : suppress_flag
  Customer  : C006
  Auto HITL : Yes
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠ COMPLIANCE REVIEW REQUIRED — HUMAN IN THE LOOP

  Run ID      : 2E81FA06
  Timestamp   : 2026-02-25T12:52:00.000000Z
  Customer    : ****06  (masked)
  Intent      : suppress_flag
  Risk Score  : 41.8 / 100
  Risk Tier   : HIGH
  Route Taken : suppress_flag_escalated

  SCORE BREAKDOWN (Explainability):
    Txn Count          raw=38.0      contrib=20.6
    Avg Txn Amount     raw=150.0     contrib=1.2
    High Risk Country  raw=1         contrib=20.0

  ANALYST NOTES (PII-scrubbed):
    Relationship manager requesting flag suppression. Customer disputes classification.

  DRAFT COMPLIANCE RESPONSE:
    Flag suppression request for customer ****06 requires compliance officer review.
    Risk score: 41.8 (HIGH tier). Suppression of HIGH/CRITICAL flags requires
    dual-control sign-off.

  REVIEWER ACTIONS:
    [A] Approve draft response as-is
    [E] Edit draft response
    [R] Reject — flag for further investigation

  Enter action (A/E/R):
```

---

### Scenario 7 — Suppress Flag (READY — Medium Risk Customer)

```bash
python main.py --scenario suppress_C013 --auto-approve
```

Expected output:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  MBAN 5510 — Customer Risk Scoring: Governed Compliance Workflow
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Intent    : suppress_flag
  Customer  : C013
  Auto HITL : Yes
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Run ID      : 9C44EB13
  Timestamp   : 2026-02-25T12:53:00.000000Z
  Customer    : ****13  (masked)
  Intent      : suppress_flag
  Risk Score  : 28.5 / 100
  Risk Tier   : MEDIUM
  Route Taken : suppress_flag_auto_approved
  Status      : READY

  Node Path   : intake → pii_middleware → moderation_middleware → scoring → router → output
```

---

### Run with a custom JSON payload

Feature schema (source: `scoring_engine/model.py`):

| Field | Type | Description |
|---|---|---|
| `txn_count` | integer | Number of transactions in the period |
| `avg_txn_amount` | float | Average transaction amount (CAD) |
| `high_risk_country` | 0 or 1 | 1 = high-risk jurisdiction, 0 = standard |

All three fields are required. Omitting any field produces `NEED_INFO`.

```bash
python main.py --payload '{
  "intent": "rescore",
  "customer_id": "CUST-DEMO-9999",
  "notes": "Manual review request.",
  "customer_features": {
    "txn_count": 30,
    "avg_txn_amount": 1500.0,
    "high_risk_country": 1
  }
}'
```

Expected output:

```
  Run ID      : F0A1BC99
  Timestamp   : 2026-02-25T12:54:00.000000Z
  Risk Score  : 47.6 / 100
  Risk Tier   : HIGH
  Route Taken : high_risk_escalate
  Status      : ESCALATE
```

---

### Run from a JSON file

```bash
python main.py --payload-file data/sample_customers.json
```

---

### Reference: All scenario scores

| Scenario | Intent | Customer | Score | Tier | Terminal Status |
|---|---|---|---|---|---|
| `C002` | rescore | C002 | 6.4 | LOW | READY |
| `C007` | rescore | C007 | 4.0 | LOW | READY |
| `C018` | rescore | C018 | 0.8 | LOW | READY |
| `C013` | rescore | C013 | 28.5 | MEDIUM | READY |
| `C010` | rescore | C010 | 22.9 | MEDIUM | READY |
| `C015` | rescore | C015 | 20.8 | MEDIUM | READY |
| `C006` | rescore | C006 | 41.8 | HIGH | ESCALATE |
| `C008` | rescore | C008 | 46.4 | HIGH | ESCALATE |
| `C020` | rescore | C020 | 47.8 | HIGH | ESCALATE |
| `C014` | rescore | C014 | **55.9** | **CRITICAL** | ESCALATE |
| `C001` | rescore | C001 | 53.4 | HIGH | ESCALATE |
| `C004` | rescore | C004 | 53.1 | HIGH | ESCALATE |
| `C009` | rescore | C009 | 40.2 | HIGH | ESCALATE |
| `suppress_C006` | suppress_flag | C006 | 41.8 | HIGH | ESCALATE |
| `suppress_C013` | suppress_flag | C013 | 28.5 | MEDIUM | READY |
| `explain_C008` | explain_score | C008 | 46.4 | HIGH | ESCALATE |
| `explain_C002` | explain_score | C002 | 6.4 | LOW | READY |
| `missing_data` | rescore | C-INCOMPLETE | — | UNKNOWN | NEED_INFO |

---

## 7. Human-in-the-Loop Workflow

### When HITL Triggers

The HITL node activates whenever `terminal_status == "ESCALATE"`:
- Risk tier is HIGH (score 40.00 – 54.99) or CRITICAL (score ≥ 55.00)
- Moderation failed on analyst notes
- Flag suppression requested for a HIGH or CRITICAL customer

### What the Reviewer Sees

The system pauses and displays a **review packet** containing:
1. Run ID and timestamp
2. Masked customer identifier (never raw PII)
3. Risk score, tier, and route label
4. Full score breakdown with per-feature contributions (explainability)
5. Scrubbed analyst notes (PII already removed by pii_middleware)
6. Draft compliance response

### Reviewer Actions

```
[A] Approve  — accept the draft response as-is
[E] Edit     — replace the draft with a custom response (typed inline)
[R] Reject   — flag the case for further investigation
```

After action selection, an optional free-text notes field is available.

### How Final Output is Produced

- **Approve:** `state.final_response = draft_response`
- **Edit:** `state.final_response = reviewer_typed_response`;
  original draft stored in `state.hitl_edited_response` for audit comparison
- **Reject:** `state.final_response` is set to a structured rejection notice
  including the reviewer's notes

The `hitl_reviewer_action` and `hitl_reviewer_notes` are both persisted in
the audit log JSON.

### Non-Interactive / CI Mode

Pass `--auto-approve` to bypass the prompt. The system logs
`"Auto-approved (non-interactive mode)"` as the reviewer notes.
This is used for tests and demo recording.

---

## 8. Running Tests

### Run all tests (no external dependencies needed)

```bash
python tests/test_workflow.py
```

### Run with pytest (recommended)

```bash
pytest tests/ -v
```

### Run with coverage report

```bash
pytest tests/ --cov=. --cov-report=term-missing
```

### Test Coverage

| Test Class | Tests | What is Verified |
|---|---|---|
| `TestScoringEngine` | 4 | Score correctness, tier thresholds, missing field detection, breakdown keys |
| `TestPIIMiddleware` | 4 | Customer ID masking, SSN scrubbing, email scrubbing, clean text passthrough |
| `TestCallLimits` | 2 | Limit exceeded raises error, normal count increments correctly |
| `TestWorkflowPaths` | 10 | All three terminal statuses, all three intents, HITL trigger, audit log creation, PII masking in output |

**Total: 20 tests, all passing.**

---

## 9. Project-to-Brief Mapping

### Section 2A — Supported Request Types

| Brief Requirement | This Implementation |
|---|---|
| Reschedule appointment | `rescore` intent — re-run the risk model for a customer |
| Cancel appointment | `suppress_flag` intent — override/suppress a compliance flag |
| Request prep instructions | `explain_score` intent — return a feature-level explainability report |

### Section 2B — Middleware Requirements

All middleware is implemented as named LangGraph nodes, fully integrated with
graph state and routing (see Section 3 above for the complete table).

### Section 3 — Required Interface

CLI entry point: `python main.py [options]`  
See Section 6 for all commands and expected outputs.

### Section 4 — Required Outputs

Every run produces:

1. **Final system status:** Printed as `Status : READY / NEED_INFO / ESCALATE`
2. **Final client-facing response:** Printed after the HITL review step (if triggered)
3. **Verifiable execution evidence:** Console output includes run ID, timestamp,
   node path, and route label; JSON audit log written to `logs/`

### Section 6 — Evaluation Dimensions

| Dimension | Implementation |
|---|---|
| System Design & Reasoning | Stateful StateGraph with typed state, conditional routing, and documented decision tables |
| Safety & Governance | HIGH/CRITICAL cases never auto-approve; moderation failure always escalates; suppress-flag on high-risk requires dual-control |
| Human Oversight | HITL node displays full explainability packet; approve/edit/reject meaningfully changes `final_response` |
| Technical Execution | 20 tests pass; sequential fallback ensures the app runs without LangGraph installed |
| Reproducibility | README contains exact commands + expected outputs; `.env.example` provided; no secrets committed |

---

## 10. Assumptions

1. **Scoring weights are illustrative.** The three-factor model replicates the
   Excel formula from `customer_risk_scoring.xlsx`. In production, weights would
   be calibrated against historical labeled data.

2. **No legal or compliance determination is automated.** Per the brief's
   constraint, the system never makes a final compliance ruling — it routes
   HIGH and CRITICAL cases to a human rather than automating the decision.

3. **OpenAI moderation is optional.** The system is fully functional without
   an OpenAI API key. The heuristic fallback (`ModelFallbackMiddleware` pattern)
   prevents any dependency from becoming a hard blocker.

4. **Single-record processing per run.** The current CLI processes one customer
   record per execution. Batch processing can be added by looping `main.py`
   over a list of payloads, which is a natural extension.

5. **LangGraph state is a dataclass.** LangGraph supports both TypedDict and
   dataclass state schemas. This implementation uses a dataclass for type
   safety and IDE autocompletion. The graph compilation is equivalent either way.

###Limitations:
Scalability & Production Scope
This system is designed as a governed compliance workflow prototype. It processes one customer record per CLI invocation and is not architected for concurrent or high-volume transaction throughput. A production deployment would require a message queue or streaming ingestion layer, a persistent case management database, and horizontal scaling support. These are intentional scope boundaries for an academic project, not oversights.
