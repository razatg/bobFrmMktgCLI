"""Deterministic metric parsing and derivation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TypeAlias


MetricInput: TypeAlias = float | int | str | None


def number(value: MetricInput) -> float:
    if value is None:
        return 0.0
    text = str(value).strip().replace(",", "")
    if not text or text.upper() in {"NA", "NULL", "NAN"}:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def format_float(value: float) -> str:
    if value == 0:
        return "0"
    if abs(value) >= 100:
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return f"{value:.4f}".rstrip("0").rstrip(".")


def ratio(numerator: float, denominator: float, scale: float = 1.0) -> str:
    if denominator == 0:
        return "NA"
    return format_float(numerator / denominator * scale)


def derive_metrics(values: Mapping[str, float], primary_goal: str) -> dict[str, str]:
    """Compute ratios only after additive metrics have been aggregated."""
    impressions = values["impressions"]
    clicks = values["clicks"]
    cost = values["cost"]
    installs = values["installs"]
    in_app_conversions = values["in_app_conversions"]
    goal = installs if primary_goal == "installs" else in_app_conversions
    has_reach = "reach" in values and values.get("reach") not in (None, "", "NA")
    reach = values.get("reach", 0.0) if has_reach else 0.0
    return {
        "reach": format_float(reach) if has_reach else "NA",
        "impressions": format_float(impressions),
        "clicks": format_float(clicks),
        "cost": format_float(cost),
        "installs": format_float(installs),
        "in_app_conversions": format_float(in_app_conversions),
        "goal_conversions": format_float(goal),
        "cpm": ratio(cost, impressions, 1000),
        "frequency": ratio(impressions, reach) if has_reach else "NA",
        "ctr_percent": ratio(clicks, impressions, 100),
        "cpc": ratio(cost, clicks),
        "cti_percent": ratio(installs, clicks, 100),
        "conversion_rate_percent": ratio(goal, clicks, 100),
        "cpa": ratio(cost, goal),
        "cpi": ratio(cost, installs),
    }
