"""One account brief, with legacy settings translated at the boundary."""
from __future__ import annotations


APPROACH_FIELDS = {
    'cac_reference': ('cac_ceiling', 200),
    'typical_change_pct': ('bid_budget_change_pct', 10),
    'preferred_wait_days': ('bid_budget_cooldown_days', 14),
}


def account_goals(profile: dict) -> dict:
    goals = dict(profile.get('goals') or {})
    approach = dict(goals.get('usual_approach') or {})
    for name, (legacy, default) in APPROACH_FIELDS.items():
        approach.setdefault(name, profile.get(legacy, default))
    goals['usual_approach'] = approach
    return goals


def with_goal_aliases(profile: dict) -> dict:
    """Old callers read derived aliases; Goals wins if both are present."""
    profile = dict(profile)
    profile['goals'] = account_goals(profile)
    for name, (legacy, _) in APPROACH_FIELDS.items():
        value = profile['goals']['usual_approach'].get(name)
        profile[legacy] = value if value is not None else APPROACH_FIELDS[name][1]
    return profile
