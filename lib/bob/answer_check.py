"""Small, deterministic evidence checks at the answer boundary.

The model returns {answer, account, claims}. Plain text remains compatible but
its numerical statements are explicitly unchecked. This checks facts, not causality.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable
from itertools import islice

from lib.bob.platform.metrics import derive_metrics, number


@dataclass(frozen=True)
class AnswerCheck:
    answer: str
    warnings: tuple[str, ...] = ()
    blocked: bool = False


_NUMBERS = re.compile(r"(?<![\w])[-+−]?\d[\d,]*(?:\.\d+)?(?:[KMBkmb](?!\w))?")


def numerical_values(text: str) -> list[float]:
    """Conservative coverage: don't treat URLs, dates or list numbering as metrics."""
    text = re.sub(r"\]\([^)]*\)|https?://\S+|\[\[(?:artifact|chat-media):[^\]]*\]\]", "", text)
    text = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", "", text)
    text = re.sub(r"(?m)^\s*\d+[.)]\s+", "", text)
    return [_numeric(match.group()) for match in _NUMBERS.finditer(text)]


def _numeric(value: object) -> float:
    text = str(value).replace(",", "").replace("−", "-").strip()
    multiplier = {"k": 1e3, "m": 1e6, "b": 1e9}.get(text[-1:].lower(), 1)
    if multiplier != 1:
        text = text[:-1]
    result = float(text) * multiplier
    if not math.isfinite(result):
        raise ValueError("non-finite number")
    return result


def _source_rows(root: Path, account: str, source: str) -> list[dict[str, str]]:
    path = (root / source).resolve()
    processed = (root / "data" / "processed" / account).resolve()
    if path.is_relative_to((root / "data" / "processed").resolve()) and not path.is_relative_to(processed):
        raise PermissionError("source belongs to another account")
    if not path.is_relative_to(processed) or path.suffix != ".csv":
        raise ValueError("source is not selected-account processed evidence")
    if path.stat().st_size > 25_000_000:
        raise ValueError("source exceeds answer-check limit")
    with path.open(newline="") as handle:
        rows = list(islice(csv.DictReader(handle), 100001))
    if len(rows) > 100000:
        raise ValueError('evidence exceeds answer-check row budget')
    if any(str(row.get("customer_id", account)).replace("-", "") != account for row in rows):
        raise PermissionError("source contains another account")
    return rows


def _claim_value(claim: dict, rows: list[dict[str, str]], goal: str) -> float:
    entity = claim["entity"]
    if not isinstance(entity, dict) or any(key not in {
        "customer_id", "campaign_id", "ad_group_id", "asset_id", "network", "asset_type"
    } for key in entity):
        raise ValueError("claim requires explicit entity identifiers")
    selected = [row for row in rows if all(str(row.get(k, "")) == str(v) for k, v in entity.items())]
    if not selected:
        raise ValueError("claim entity is absent from evidence")
    metric = claim["metric"]
    additive = ("cost", "impressions", "clicks", "installs", "in_app_conversions", "primary_conversions")
    totals = {key: sum(number(row.get(key)) for row in selected) for key in additive}
    if metric in additive:
        if any(metric not in row for row in selected):
            raise ValueError("metric absent from source")
        return totals[metric]
    if metric in {"reach", "frequency"}:
        if len(selected) != 1:
            raise ValueError("reach cannot be rolled up")
        return _numeric(selected[0][metric])
    if metric == "primary_cpa":
        return totals["cost"] / totals["primary_conversions"]
    derived = derive_metrics(totals, goal)
    if metric in derived:
        required = {"cpi": ("cost", "installs"), "cpc": ("cost", "clicks"),
                    "cpm": ("cost", "impressions"), "ctr_percent": ("clicks", "impressions"),
                    "cti_percent": ("installs", "clicks"),
                    "cpa": ("cost", "installs" if goal == "installs" else "in_app_conversions")}
        if any(key not in row for key in required.get(metric, additive[:5]) for row in selected):
            raise ValueError("derived metric inputs absent")
        return _numeric(derived[metric])
    if len(selected) != 1:
        raise ValueError("non-additive field requires one source row")
    return _numeric(selected[0][metric])


def _verify_claim(claim: dict, root: Path, account: str, goal: str,
                  cache: dict[str, list[dict[str, str]]]) -> float:
    start, end = (dt.date.fromisoformat(value) for value in claim["period"])
    if start > end:
        raise ValueError("reversed claim period")
    source = str(claim["source"])
    # A period aggregate is usable only for its exact period, not a substring window.
    if f"{account}_{start}_{end}" not in Path(source).name:
        raise ValueError("claim period does not match evidence")
    if source not in cache:
        if len(cache) >= 16:
            raise ValueError('too many evidence sources in one answer')
        cache[source] = _source_rows(root, account, source)
    if sum(len(rows) for rows in cache.values()) > 100000:
        raise ValueError('answer exceeds total evidence row budget')
    observed = _claim_value(claim, cache[source], goal)
    if claim.get("baseline_source"):
        baseline = dict(claim, source=claim["baseline_source"], period=claim["baseline_period"])
        baseline.pop("baseline_source", None)
        baseline.pop("baseline_period", None)
        prior_source = str(baseline['source'])
        if prior_source not in cache:
            if len(cache) >= 16:
                raise ValueError('too many evidence sources in one answer')
            cache[prior_source] = _source_rows(root, account, prior_source)
        baseline["value"] = _claim_value(baseline, cache[prior_source], goal)
        prior = _verify_claim(baseline, root, account, goal, cache)
        operation = claim.get("operation")
        if operation == "delta":
            observed -= prior
        elif operation == "delta_percent" and prior:
            observed = (observed - prior) / prior * 100
        else:
            raise ValueError("unsupported or undefined comparison")
    stated = _numeric(claim["value"])
    decimals = claim.get("decimals", 2)
    if not isinstance(decimals, int) or not 0 <= decimals <= 6:
        raise ValueError("invalid rounding precision")
    suffix = str(claim['value']).strip()[-1:].lower()
    display_scale = {'k': 1e3, 'm': 1e6, 'b': 1e9}.get(suffix, 1)
    if abs(stated - observed) > 0.5 * 10 ** -decimals * display_scale + 1e-8:
        raise ValueError("stated figure does not reconcile")
    return stated


def check_answer(raw: str, root: Path, account: str = "", goal: str = "in_app_conversions",
                 excluded_entities: tuple[str, ...] = (),
                 proposal_validator: Callable[[dict], list[dict]] | None = None) -> AnswerCheck:
    """Return display text and bounded diagnostics; foreign evidence fails closed."""
    envelope = None
    candidate = raw.strip()
    if candidate.startswith("```json") and candidate.endswith("```"):
        candidate = candidate[7:-3].strip()
    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict) and "answer" in parsed:
            envelope = parsed
    except (ValueError, TypeError):
        pass
    answer = str(envelope["answer"]) if envelope else raw
    account = account.replace("-", "")
    if envelope and str(envelope.get("account", "")).replace("-", "") != account:
        return AnswerCheck("", ("answer account differs from selected account",), True)
    if any(entity and entity in answer for entity in excluded_entities):
        return AnswerCheck("", ("answer includes an excluded entity",), True)
    warnings: list[str] = []
    proposal_claims: dict[tuple[str, str, str], float] = {}
    proposal_notes: list[str] = []
    proposals = envelope.get("plans", []) if envelope else []
    if not isinstance(proposals, list) or len(proposals) > 10:
        return AnswerCheck("", ("invalid proposal list",), True)
    for proposal in proposals:
        try:
            if proposal_validator is None:
                raise ValueError("proposal validation unavailable")
            verdicts = proposal_validator(proposal)
            if any(not verdict["allowed"] for verdict in verdicts):
                # There is no structured approval-card renderer yet. Hold the
                # proposal-bearing reply rather than showing an unsafe table.
                return AnswerCheck("The proposed changes did not pass validation. No changes were applied; revise the proposal before approval.",
                                   ("proposal contains denied actions",))
            for verdict in verdicts:
                proposal_notes.extend(verdict.get('warnings', []))
                for item in verdict.get('claims', []):
                    proposal_claims[(proposal['path'], str(item['campaign_id']), item['metric'])] = float(item['value'])
        except (OSError, ValueError, KeyError, TypeError, PermissionError):
            return AnswerCheck("The proposed changes could not be validated. No changes were applied; review the proposal before approval.",
                               ("proposal validation unavailable",))
    verified: list[float] = []
    cache: dict[str, list[dict[str, str]]] = {}
    claims = envelope.get("claims", []) if envelope else []
    if not isinstance(claims, list) or len(claims) > 500:
        claims = []
        warnings.append("invalid claims list")
    for index, claim in enumerate(claims):
        try:
            if not isinstance(claim, dict):
                raise ValueError("invalid claim")
            claim_account = str(claim.get("entity", {}).get("customer_id", account)).replace("-", "")
            if claim_account != account:
                return AnswerCheck("", ("claim belongs to another account",), True)
            if any(str(value) in excluded_entities for value in claim.get("entity", {}).values()):
                return AnswerCheck("", ("claim includes an excluded entity",), True)
            if claim.get('kind') == 'proposal':
                key = (claim['source'], str(claim['entity']['campaign_id']), claim['metric'])
                value = _numeric(claim['value'])
                if not math.isclose(value, proposal_claims[key], rel_tol=1e-9, abs_tol=.005):
                    raise ValueError('proposal claim does not match the validated plan')
                verified.append(value)
            else:
                verified.append(_verify_claim(claim, root, account, goal, cache))
        except PermissionError:
            return AnswerCheck("", ("evidence contains another account",), True)
        except (OSError, ValueError, KeyError, TypeError, ZeroDivisionError):
            warnings.append(f"claim {index + 1} could not be verified")
    uncovered = [value for value in numerical_values(answer)
                 if not any(math.isclose(value, checked, rel_tol=1e-8, abs_tol=1e-8) for checked in verified)]
    if uncovered:
        warnings.append("answer contains unchecked numerical statements")
    if proposal_notes:
        answer += '\n\nProposal review notes: ' + '; '.join(dict.fromkeys(proposal_notes)) + '.'
    return AnswerCheck(answer, tuple(warnings))


def validate_proposal(reference: dict, root: Path, profile: dict, runtime_config: str | None) -> list[dict]:
    """Validate only account-scoped saved plans; live reads stay at this boundary."""
    import yaml
    account = str(profile.get("google_ads_customer_id", "")).replace("-", "")
    path = (root / reference["path"]).resolve()
    if not path.is_relative_to((root / "wiki" / account).resolve()) or path.suffix not in {".yaml", ".yml"}:
        raise ValueError("plan is outside the selected account")
    plan = yaml.safe_load(path.read_text())
    if reference.get("kind") == "copy":
        if not runtime_config:
            raise ValueError("live creative settings unavailable")
        from google.ads.googleads.client import GoogleAdsClient
        from lib.bob.creative_copy.rules import validate_plan, read_live_ads, refresh_copy_evidence
        client = GoogleAdsClient.load_from_storage(runtime_config)
        refresh_copy_evidence(client, account, plan, profile)
        return validate_plan(plan, account, read_live_ads(client, account, plan.get('changes', [])),
                             tuple(profile.get('goals', {}).get('excluded_entities', [])))
    if reference.get("kind") != "bid_budget" or not runtime_config:
        raise ValueError("unsupported plan or live settings unavailable")
    from google.ads.googleads.client import GoogleAdsClient
    from lib.bob.bid_budget.guards import read_live_state, validate_plan
    client = GoogleAdsClient.load_from_storage(runtime_config)
    from lib.bob.platform.dates import today
    on_date = today()
    states = read_live_state(client, account, on_date, int(profile.get("bid_budget_cooldown_days", 14)))
    verdicts = validate_plan(plan, profile, states, on_date=on_date, permission="read_write",
                             applied_today=sum(state.last_change == on_date for state in states.values()))
    changes = {str(change['campaign_id']): change for change in plan['changes']}
    return [{"allowed": verdict.allowed, "reasons": verdict.reasons, "warnings": verdict.warnings,
             "claims": [{'campaign_id': verdict.campaign_id, 'metric': metric, 'value': changes[verdict.campaign_id][metric]}
                        for metric in ('proposed_target_cpa', 'proposed_daily_budget')
                        if changes[verdict.campaign_id].get(metric) is not None]}
            for verdict in verdicts]
