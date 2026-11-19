"""A bounded situation brief and thin CLI integration for investigation/recall."""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import io
import json
from pathlib import Path

from lib.bob.platform import core
from lib.bob.platform.dates import resolve_period_dates, today
from lib.bob.performance.adhoc import AnalysisError, catalog
from lib.bob.performance.adhoc_data import prepare_dataset, selected_account
from lib.bob.performance.checks import evidence_status
from lib.bob.decisions import records
from lib.bob.search import search, skills_search
from lib.bob.platform.presentation import _aggregate_period_rows, _build_comparison_rows
from lib.bob.platform.metrics import derive_metrics, number
from lib.bob.performance.creatives import creative_baseline


def build_brief(*, focus: str = "all", period: str = "wow", offline: bool = False,
                max_fetches: int = 4, campaigns: tuple[str, ...] = (), question: str = "") -> dict:
    account, profile = selected_account(allow_local=True)
    if ":" in period:
        start, end = (dt.date.fromisoformat(value) for value in period.split(":"))
        if start > end:
            raise ValueError("period is reversed")
        windows = [(start, end)]
    else:
        windows = resolve_period_dates(period)
    result = {"account": account, "goals": profile.get("goals", {}),
              "settings": {key: profile.get(key) for key in ("primary_goal", "cac_ceiling", "bid_budget_change_pct", "bid_budget_cooldown_days")},
              "sections": {}, "next_looks": catalog(), "fetches": 0}
    kt = core.account_wiki_dir(account) / "KT.md"
    rules = kt.read_text() if kt.exists() else ""
    if len(rules) > 16000:
        raise ValueError("account rules exceed brief budget; curate KT before making recommendations")
    result["account_rules"] = rules
    datasets = ["campaign_network_period"]
    if focus in {"all", "bids"}:
        datasets.append("bid_budget_inputs")
    if focus in {"all", "creative"}:
        datasets.append("creative_period")
    datasets.append("change_history")
    prepared_rows = {}
    for dataset in datasets:
        periods = windows[:2] if dataset in {"campaign_network_period", "creative_period"} else windows[:1]
        for index, (start, end) in enumerate(periods):
            section = f"{dataset}:{'current' if index == 0 else 'baseline'}"
            try:
                # Always try local preparation first. Only absent evidence consumes fetch budget.
                try:
                    prepared, metadata = _prepare(dataset, start, end, question, False)
                except AnalysisError:
                    if offline or result["fetches"] >= max_fetches:
                        raise AnalysisError("evidence unavailable within the fetch budget")
                    result["fetches"] += 1
                    prepared, metadata = _prepare(dataset, start, end, question, True)
                rows = [row for row in prepared.rows if not campaigns or str(row.get("campaign_id")) in campaigns]
                prepared_rows[section] = rows
                source = Path(metadata["source"])
                result["sections"][section] = {
                    "status": "available", "rows": len(rows),
                    "preview": sorted(rows, key=lambda row: float(row.get("cost") or 0), reverse=True)[:10],
                    "preview_truncated": len(rows) > 10,
                    "source": str(source.relative_to(core.STATE_ROOT)),
                    "data_status": evidence_status(source, start, end, on_date=today()),
                }
                if dataset == "campaign_network_period":
                    result["sections"][section]["account_totals"] = _aggregate_period_rows(rows, ["customer_id"], str(profile.get("primary_goal", "in_app_conversions")))
                if dataset == "creative_period":
                    creative_rows = [dict(row, **derive_metrics(
                        {key: number(row.get(key)) for key in ('cost', 'impressions', 'clicks', 'installs', 'in_app_conversions')},
                        str(profile.get('primary_goal', 'in_app_conversions')))) for row in rows]
                    flags = creative_baseline(creative_rows, float(profile.get('creative_min_impressions', 50000)), str(profile.get('primary_goal', 'in_app_conversions')))
                    result['sections'][section]['baseline'] = {
                        'low_action_count': sum(row['flag'] == 'low-action' for row in flags),
                        'low_watch_count': sum(row['flag'] == 'low-watch' for row in flags),
                        'preview': flags[:10], 'preview_truncated': len(flags) > 10}
            except (AnalysisError, OSError, ValueError, SystemExit) as exc:
                result["sections"][section] = {"status": "unavailable", "reason": str(exc)[:300]}
    current = prepared_rows.get('campaign_network_period:current')
    baseline = prepared_rows.get('campaign_network_period:baseline')
    if current is not None and baseline is not None:
        drivers = _build_comparison_rows(current, baseline, ['campaign_id', 'network'], str(profile.get('primary_goal', 'in_app_conversions')))
        result['performance_drivers'] = sorted(drivers, key=lambda row: abs(float(row.get('current_cost') or 0) - float(row.get('baseline_cost') or 0)), reverse=True)[:10]
    if focus in {'all', 'bids'}:
        result['baseline'] = _baseline(profile)
    history = records.recent(core.STATE_ROOT, account, entities=campaigns)
    result["history"] = [{key: item.get(key) for key in ("decision_id", "situation", "recommendation", "prediction", "review")} for item in history]
    result["reviews_due"] = [item["decision_id"] for item in history
                             if not item.get("review") and str(item.get('review_due') or item.get("prediction", {}).get("review_date", "9999")) <= str(today())]
    return result


def _baseline(profile):
    from lib.bob.bid_budget import bid_budget_recommend
    output = io.StringIO()
    try:
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            bid_budget_recommend(argparse.Namespace(goal=profile.get('primary_goal'), cac_ceiling=None,
                change_pct=None, trend=None, bid_budget=None, dry_run=True))
        return {'status': 'available', 'summary': output.getvalue()[:12000], 'truncated': len(output.getvalue()) > 12000}
    except (SystemExit, OSError, ValueError):
        return {'status': 'unavailable', 'reason': 'Exact baseline windows or inputs unavailable; use registered drill-downs.'}


def _prepare(dataset, start, end, question, allow_fetch):
    # Existing fetch/aggregate commands write progress; the brief's stdout stays valid JSON.
    with contextlib.redirect_stdout(io.StringIO()):
        return prepare_dataset(dataset, str(start), str(end), "situation brief", question or "Situation brief",
                               f"brief-{dataset}", allow_fetch=allow_fetch, allow_local=True)


def _run(args):
    account, _ = selected_account(allow_local=True)
    if getattr(args, "account", None) and args.account.replace("-", "") != account:
        raise ValueError("requested account differs from the selected account")
    if args.command == "brief":
        output = build_brief(focus=args.focus, period=args.period, offline=args.offline,
                             max_fetches=args.max_fetches, campaigns=tuple(args.campaigns or ()), question=args.question)
    elif args.command == "search":
        output = search(core.STATE_ROOT, account, args.query, kind=args.kind, since=args.since)
    elif args.command == "skills":
        output = skills_search(core.ROOT, args.query)
    else:
        output = _decision(args, account)
    print(json.dumps(output, indent=2, ensure_ascii=False, allow_nan=False))


def _decision(args, account):
    if args.action == "record":
        payload = json.loads(Path(args.input).read_text())
        profile = core.load_profile(required=True)
        payload.setdefault('goals', profile.get('goals', {}))
        payload.setdefault('primary_goal', profile.get('primary_goal', 'in_app_conversions'))
        return records.record(core.STATE_ROOT, account, payload)
    if args.action == 'respond':
        return records.update(core.STATE_ROOT, account, args.id, 'human', {
            'response': args.response, 'note': args.note,
            'at': dt.datetime.now(dt.timezone.utc).isoformat()})
    if args.action == "show":
        return records.get(core.STATE_ROOT, account, args.id)
    if args.action == "link":
        if args.plan:
            import yaml
            records.get(core.STATE_ROOT, account, args.id)
            path = Path(args.plan).resolve()
            if not path.is_relative_to(core.account_wiki_dir(account).resolve()):
                raise ValueError("plan must be in the selected account wiki")
            plan = yaml.safe_load(path.read_text())
            if str(plan.get("customer_id", "")).replace("-", "") != account:
                raise ValueError("plan belongs to another account")
            plan["decision_id"] = args.id
            path.write_text(yaml.safe_dump(plan, sort_keys=False, allow_unicode=True))
            return {"decision_id": args.id, "linked_plan": str(path)}
        return records.update(core.STATE_ROOT, account, args.id, "execution", json.loads(Path(args.input).read_text()))
    from lib.bob.decisions.review import review
    return review(core.STATE_ROOT, account, args.id, args.source, on_date=today(),
                  maturity_days=args.maturity_days, confounders=args.confounder)


def register_commands(sub):
    brief = sub.add_parser("brief", help="bounded situation evidence, goals, rules and decision history")
    brief.add_argument("--account")
    brief.add_argument("--focus", choices=["all", "performance", "bids", "creative"], default="all")
    brief.add_argument("--period", default="wow")
    brief.add_argument("--campaigns", nargs="*")
    brief.add_argument("--offline", action="store_true")
    brief.add_argument("--max-fetches", type=int, choices=range(0, 9), default=4,
                       help="maximum dataset preparations needing a fetch; each may use seven-day chunks")
    brief.add_argument("--question", default="")
    brief.add_argument("--json", action="store_true", help="JSON is the default output")
    brief.set_defaults(func=_run)
    lookup = sub.add_parser("search", help="account-scoped text search over knowledge and decisions")
    lookup.add_argument("query")
    lookup.add_argument("--account")
    lookup.add_argument("--kind", choices=["", "kt", "analysis", "action", "decision"], default="")
    lookup.add_argument("--since", default="")
    lookup.set_defaults(func=_run)
    skills = sub.add_parser("skills", help="find situational recipes")
    skills.set_defaults(func=_run)
    skill_sub = skills.add_subparsers(dest="action", required=True)
    find = skill_sub.add_parser("search")
    find.add_argument("query", nargs="?", default="")
    find.set_defaults(func=lambda args: print(json.dumps(skills_search(core.ROOT, args.query), indent=2)))
    decisions = sub.add_parser("decision", help="record, recall, link or review a decision")
    decisions.set_defaults(func=_run)
    actions = decisions.add_subparsers(dest="action", required=True)
    for name in ("record", "show", "link", "review", "respond"):
        action = actions.add_parser(name)
        if name != "record":
            action.add_argument("id")
        if name == "record":
            action.add_argument("--input", required=True, help="JSON record or execution receipt")
        if name == "link":
            group = action.add_mutually_exclusive_group(required=True)
            group.add_argument("--input", help="actual execution receipt JSON")
            group.add_argument("--plan", help="attach decision identity to an existing account plan")
        if name == "review":
            action.add_argument("--source", required=True, help="exact-window processed CSV relative to state root")
            action.add_argument("--maturity-days", type=int, default=None)
            action.add_argument("--confounder", action="append", default=[])
        if name == 'respond':
            action.add_argument('--response', choices=['approved', 'rejected', 'overridden'], required=True)
            action.add_argument('--note', default='')
        action.set_defaults(func=_run)
