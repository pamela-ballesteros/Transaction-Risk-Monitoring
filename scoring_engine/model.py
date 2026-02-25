"""
scoring_engine/model.py
=======================
Customer Risk Scoring Engine — Python implementation of the Excel model
from customer_risk_scoring.xlsx (sheet: customer_data).

Excel Formula (columns F, G, H):
  txn_norm   = (txn_count - MIN) / (MAX - MIN)          [min-max normalization]
  amt_norm   = (avg_txn_amount - MIN) / (MAX - MIN)      [min-max normalization]
  risk_score = (0.4 × txn_norm) + (0.4 × amt_norm) + (0.2 × high_risk_country)

Dataset statistics (from the 20-customer reference dataset, columns B & C):
  txn_count        : min=2,  max=72
  avg_txn_amount   : min=12, max=4500

Score range: 0.0 – 1.0 (internally), scaled to 0–100 for display.

Tier thresholds calibrated to the labeled dataset:
  All 4 flagged customers (C006, C008, C014, C020) scored ≥ 41.8.
  Thresholds set so ESCALATE captures 100% of flagged cases (recall = 1.0):
    CRITICAL : ≥ 55   — top-tier compliance action required
    HIGH     : 40–54  — enhanced due diligence, HITL review mandatory
    MEDIUM   : 20–39  — standard monitoring, auto-cleared
    LOW      :  < 20  — minimal risk, auto-cleared
"""

from __future__ import annotations
from dataclasses import dataclass


# ── Feature Weights (must sum to 1.0) ─────────────────────────────────────────
# Sourced directly from Excel formula: =(0.4*F) + (0.4*G) + (0.2*D)
WEIGHTS = {
    "txn_count":          0.40,   # transaction count — velocity indicator
    "avg_txn_amount":     0.40,   # average transaction amount — value indicator
    "high_risk_country":  0.20,   # binary flag: 1 = high-risk jurisdiction
}

# ── Min-Max Normalization Bounds ──────────────────────────────────────────────
# Derived from the 20-customer reference dataset in the Excel file.
# These are the population bounds used for normalization — update if the
# reference dataset grows.
TXN_COUNT_MIN,  TXN_COUNT_MAX  = 2,  72
AVG_AMT_MIN,    AVG_AMT_MAX    = 12, 4500

# ── Score Tier Thresholds (×100 scale) ────────────────────────────────────────
# Calibrated so all 4 labeled "flagged" customers fall in HIGH or CRITICAL.
TIERS = [
    (55, "CRITICAL"),
    (40, "HIGH"),
    (20, "MEDIUM"),
    (0,  "LOW"),
]

# ── Required Input Fields ─────────────────────────────────────────────────────
REQUIRED_FIELDS = ["txn_count", "avg_txn_amount", "high_risk_country"]


@dataclass
class ScoringResult:
    score: float            # 0–100 display scale
    tier: str               # LOW / MEDIUM / HIGH / CRITICAL
    breakdown: dict         # per-feature detail for explainability
    missing_fields: list    # empty if score is valid
    explainability_text: str


def _minmax(value: float, vmin: float, vmax: float) -> float:
    """Min-max normalization — mirrors Excel MIN/MAX formula."""
    if vmax == vmin:
        return 0.0
    return max(0.0, min(1.0, (value - vmin) / (vmax - vmin)))


def compute_score(customer_data: dict) -> ScoringResult:
    """
    Compute the risk score for a single customer.

    Parameters
    ----------
    customer_data : dict with keys txn_count, avg_txn_amount, high_risk_country

    Returns
    -------
    ScoringResult with score (0–100), tier, per-feature breakdown,
    and explainability text for the HITL review packet.
    """
    missing = [
        f for f in REQUIRED_FIELDS
        if f not in customer_data or customer_data[f] is None
    ]
    if missing:
        return ScoringResult(
            score=0.0,
            tier="UNKNOWN",
            breakdown={},
            missing_fields=missing,
            explainability_text=f"Score cannot be computed. Missing fields: {missing}",
        )

    txn   = float(customer_data["txn_count"])
    amt   = float(customer_data["avg_txn_amount"])
    hrc   = float(customer_data["high_risk_country"])   # 0 or 1

    # ── Normalization (replicates Excel columns F and G) ──────────────────────
    txn_norm = _minmax(txn, TXN_COUNT_MIN, TXN_COUNT_MAX)
    amt_norm = _minmax(amt, AVG_AMT_MIN,   AVG_AMT_MAX)

    # ── Weighted sum (replicates Excel column H) ──────────────────────────────
    raw_score = (0.40 * txn_norm) + (0.40 * amt_norm) + (0.20 * hrc)

    # Scale to 0–100 for display and tier routing
    score = round(raw_score * 100, 2)
    tier  = next(t for threshold, t in TIERS if score >= threshold)

    breakdown = {
        "txn_count": {
            "raw_value":            txn,
            "normalized_score":     round(txn_norm, 4),
            "weight":               0.40,
            "weighted_contribution": round(txn_norm * 0.40 * 100, 2),
        },
        "avg_txn_amount": {
            "raw_value":            amt,
            "normalized_score":     round(amt_norm, 4),
            "weight":               0.40,
            "weighted_contribution": round(amt_norm * 0.40 * 100, 2),
        },
        "high_risk_country": {
            "raw_value":            int(hrc),
            "normalized_score":     hrc,         # binary — no normalization needed
            "weight":               0.20,
            "weighted_contribution": round(hrc * 0.20 * 100, 2),
        },
    }

    explainability = _build_explanation(score, tier, breakdown, raw_score)

    return ScoringResult(
        score=score,
        tier=tier,
        breakdown=breakdown,
        missing_fields=[],
        explainability_text=explainability,
    )


def _build_explanation(
    score: float, tier: str, breakdown: dict, raw_score: float
) -> str:
    """
    Generate the explainability text shown to the compliance officer in the
    HITL review packet. Each line shows the raw input, its normalized form,
    and the weighted contribution — mirroring the Excel column layout.
    """
    lines = [
        f"Risk Score   : {score:.2f} / 100  (raw: {raw_score:.4f})",
        f"Risk Tier    : {tier}",
        f"Formula      : (0.40 × txn_norm) + (0.40 × amt_norm) + (0.20 × high_risk_country)",
        "",
        f"{'Feature':<22} {'Raw Value':>10}  {'Normalized':>10}  {'Weight':>7}  {'Contribution':>12}",
        "─" * 70,
    ]

    for fname, d in breakdown.items():
        lines.append(
            f"  {fname:<20} {str(d['raw_value']):>10}  "
            f"{d['normalized_score']:>10.4f}  "
            f"{d['weight']:>7.2f}  "
            f"{d['weighted_contribution']:>11.2f}pt"
        )

    top = max(breakdown.items(), key=lambda x: x[1]["weighted_contribution"])
    lines += [
        "─" * 70,
        f"  Primary driver: {top[0].replace('_', ' ').title()} "
        f"({top[1]['weighted_contribution']:.1f}pt of {score:.1f}pt total)",
    ]

    return "\n".join(lines)
