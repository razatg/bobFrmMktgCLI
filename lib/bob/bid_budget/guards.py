"""Validate the actual proposed changes, independently of the scenario matrix."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class CampaignState:
    campaign_id: str
    enabled: bool
    target_cpa: float
    daily_budget: float
    installs: float | None
    actual_cpa: float | None
    last_change: dt.date | None
    budget_id: str


@dataclass(frozen=True)
class Verdict:
    campaign_id: str
    allowed: bool
    reasons: tuple[str, ...]
    warnings: tuple[str, ...] = ()


def plan_hash(plan: dict) -> str:
    """Only proposal content is approved; mutable execution receipts aren't."""
    payload = {key: value for key, value in plan.items()
               if key not in {"approved_hash", "applied", "applied_at", "applied_by", "apply_results"}}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False,
                                     separators=(",", ":")).encode()).hexdigest()


def step_error(proposed: object, current: float, cap: float) -> str | None:
    try:
        value = float(proposed)
    except (ValueError, TypeError):
        return "proposed value must be numeric"
    if not math.isfinite(value) or value <= 0 or not math.isfinite(current) or current <= 0:
        return "current and proposed values must be finite and positive"
    return None


def eligibility(installs: float, cpa: float, last_change: dt.date | None, *,
                on_date: dt.date, ceiling: float, cooldown_days: int) -> tuple[bool, bool, bool]:
    """Shared baseline/final-plan business checks; scenario choice stays separate."""
    volume_ok = math.isfinite(installs) and installs >= 10
    cac_ok = math.isfinite(cpa) and math.isfinite(ceiling) and 0 < cpa <= ceiling
    cooldown_ok = cooldown_days >= 0 and (last_change is None or (on_date - last_change).days > cooldown_days)
    return volume_ok, cac_ok, cooldown_ok


def _change_verdict(change: dict, state: CampaignState | None, profile: dict,
                    on_date: dt.date) -> Verdict:
    cid = str(change.get("campaign_id", ""))
    if cid in profile.get('goals', {}).get('excluded_entities', []):
        return Verdict(cid, False, ('campaign is excluded by account rules',))
    if state is None:
        return Verdict(cid, False, ("campaign absent from selected-account live state",))
    reasons: list[str] = []
    action = change.get("action")
    actions = {"increase_bid", "decrease_bid", "increase_bid_and_budget", "decrease_bid_and_budget"}
    if action not in actions:
        return Verdict(cid, False, ("unsupported action",))
    if not state.enabled:
        reasons.append("campaign is not enabled")
    ceiling = float(profile.get("cac_ceiling", 200))
    cpa = state.actual_cpa if state.actual_cpa is not None else state.target_cpa
    volume_ok, cac_ok, cooldown_ok = eligibility(state.installs or 0, cpa, state.last_change,
        on_date=on_date, ceiling=ceiling, cooldown_days=int(profile.get("bid_budget_cooldown_days", 14)))
    warnings = []
    if state.installs is not None and not volume_ok:
        warnings.append("limited recent install volume")
    approach = profile['goals']['usual_approach']
    if state.actual_cpa is not None and not cac_ok and approach.get('cac_reference') is not None:
        warnings.append("acquisition cost exceeds the reference or evidence is unavailable")
    if state.last_change is not None and not cooldown_ok and approach.get('preferred_wait_days') is not None:
        warnings.append("change is sooner than the preferred waiting period")
    cap = float(profile.get("bid_budget_change_pct", 10))
    for field, current in (("target_cpa", state.target_cpa), ("daily_budget", state.daily_budget)):
        proposed = change.get(f"proposed_{field}")
        needed = field == "target_cpa" or "budget" in action
        if not needed:
            continue
        error = step_error(proposed, current, cap)
        if error:
            reasons.append(f"{field}: {error}")
            continue
        if approach.get('typical_change_pct') is not None and abs(float(proposed) - current) / current * 100 > cap + 1e-8:
            warnings.append(f"{field}: change exceeds the usual adjustment")
        if field == "daily_budget" and str(change.get("campaign_budget_id", "")) != state.budget_id:
            reasons.append("budget identity changed")
        direction = float(proposed) - current
        if ("increase" in action and direction < 0) or ("decrease" in action and direction > 0):
            reasons.append(f"{field}: direction contradicts action")
    if warnings and not (change.get('rationale') and change.get('forecast')):
        reasons.append("departure requires rationale (evidence, trade-off and risk) and forecast (expected outcome and review window)")
    return Verdict(cid, not reasons, tuple(reasons), tuple(warnings))


def validate_plan(plan: dict, profile: dict, live: dict[str, CampaignState], *,
                  on_date: dt.date, permission: str = "read", applied_today: int = 0) -> list[Verdict]:
    from lib.bob.platform.goals import with_goal_aliases
    profile = with_goal_aliases(profile)
    account = str(profile.get("google_ads_customer_id", "")).replace("-", "")
    if not account or str(plan.get("customer_id", "")).replace("-", "") != account:
        raise ValueError("plan is outside the selected account")
    if permission != "read_write":
        raise PermissionError("READ & WRITE permission is required")
    settings = (float(profile.get("cac_ceiling", 200)), float(profile.get("bid_budget_change_pct", 10)))
    if any(not math.isfinite(value) or value < 0 for value in settings):
        raise ValueError("reference values must be finite and nonnegative")
    if int(profile.get("bid_budget_cooldown_days", 14)) < 0:
        raise ValueError("cooldown must be nonnegative")
    changes = plan.get("changes")
    if not isinstance(changes, list) or not all(isinstance(c, dict) for c in changes):
        raise ValueError("plan changes must be a list")
    ids = [str(c.get("campaign_id", "")) for c in changes]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate campaign actions")
    budgets = [str(c.get("campaign_budget_id", "")) for c in changes if "budget" in str(c.get("action", ""))]
    if len(budgets) != len(set(budgets)):
        raise ValueError("a shared budget cannot be changed twice in one proposal")
    excluded = set(profile.get('goals', {}).get('excluded_entities', []))
    if any(state.campaign_id in excluded and state.budget_id in budgets for state in live.values()):
        raise ValueError('budget change would affect an excluded campaign')
    return [_change_verdict(c, live.get(str(c.get("campaign_id", ""))), profile, on_date)
            for c in changes]


def read_live_state(client, account: str, on_date: dt.date, cooldown_days: int) -> dict[str, CampaignState]:
    """Read execution-critical settings only; performance/history belong to analysis.

    Date/lookback arguments remain accepted for existing callers.
    """
    service = client.get_service("GoogleAdsService")
    query = """SELECT campaign.id, campaign.status, campaign.target_cpa.target_cpa_micros,
      campaign_budget.id, campaign_budget.amount_micros
      FROM campaign WHERE campaign.status != 'REMOVED' """
    return {str(row.campaign.id): CampaignState(
        str(row.campaign.id), row.campaign.status.name == "ENABLED",
        row.campaign.target_cpa.target_cpa_micros / 1e6,
        row.campaign_budget.amount_micros / 1e6, None, None, None, str(row.campaign_budget.id))
        for row in service.search(customer_id=account, query=query, timeout=15)}
