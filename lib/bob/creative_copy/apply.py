"""Validated partial-safe creative-copy application."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from lib.bob.platform.core import *
from lib.bob.platform.data import *
from lib.bob.platform.google_ads import *
from lib.bob.platform.presentation import *
from .suggest import *
from .rules import validate_copy


def _merge_proposal_choices(plan: dict, choices: list[dict]) -> list[dict]:
    """Accept existing agent suggestions or complete candidate rows, retaining evidence."""
    import copy
    baseline = plan.get('changes', [])
    result = []
    editable = {'campaign_id', 'campaign_name', 'ad_group_id', 'ad_group_name', 'ad_id', 'asset_id',
                'field_type', 'current_text', 'suggested_text', 'action', 'rationale'}
    identity = ('ad_group_id', 'ad_id', 'asset_id', 'field_type')
    for choice in choices:
        if not isinstance(choice, dict):
            die('each creative choice must be an object')
        if 'id' in choice or 'text' in choice:
            if set(choice) - {'id', 'text', 'rationale'} or 'id' not in choice or 'text' not in choice:
                die('suggestions require id and text, with optional rationale')
            matches = [row for index, row in enumerate(baseline, 1)
                       if str(row.get('group_id') if plan.get('groups') else index) == str(choice['id'])]
            if not matches:
                die(f"suggestion ID {choice['id']} is absent from the candidate plan")
            for row in matches:
                item = copy.deepcopy(row)
                item.update(suggested_text=choice['text'], action='replace',
                            rationale=choice.get('rationale') or row.get('rationale') or 'Selected by the baseline performance review')
                result.append(item)
        else:
            matches = [row for row in baseline if all(str(row.get(key, '')) == str(choice.get(key, '')) for key in identity)]
            if len(matches) > 1:
                die('candidate identity is ambiguous; regenerate the candidate plan')
            base = matches[0] if matches else {}
            unexpected = set(choice) - editable - set(base)
            if unexpected:
                die('unsupported creative fields: ' + ', '.join(sorted(unexpected)))
            if base and choice.get('current_text', base['current_text']) != base['current_text']:
                die('current copy differs from the candidate evidence')
            item = copy.deepcopy(base)
            item.update(choice)
            if base:
                item.setdefault('rationale', 'Selected by the baseline performance review')
            result.append(item)
    identities = [tuple(str(row.get(key, '')) for key in identity) for row in result]
    if len(set(identities)) != len(identities):
        die('duplicate creative choices; each target may appear only once')
    for index, row in enumerate(result, 1):
        if row.get('apply_status') == 'applied':
            die('an already-applied asset cannot be proposed again')
        row['change_index'] = index
    return result


def creative_copy_propose(args: argparse.Namespace) -> None:
    """Save final asset choices without requiring an agent to hand-edit a mutation file."""
    import copy
    import yaml
    profile = load_profile(required=True)
    account = str(profile['google_ads_customer_id']).replace('-', '')
    original, target = Path(args.plan).resolve(), Path(args.output).resolve()
    wiki = account_wiki_dir(account).resolve()
    if not original.is_relative_to(wiki) or not target.is_relative_to(wiki):
        die('creative proposals must stay in the selected account wiki')
    plan = yaml.safe_load(original.read_text())
    if str(plan.get('customer_id', '')).replace('-', '') != account or plan.get('applied'):
        die('creative baseline must be unapplied and belong to the selected account')
    if plan.get('apply_results') or plan.get('applied_at') or plan.get('last_apply_at'):
        die('execution has started; preserve receipts and reconcile or retry the existing plan')
    changes = json.loads(args.changes_json)
    errors = []
    if not isinstance(changes, list) or len(changes) > 1000:
        die('changes must be a bounded list')
    changes = _merge_proposal_choices(plan, changes)
    for index, change in enumerate(changes, 1):
        if not change.get('rationale'):
            die(f'creative choice #{index} requires an evidence-backed rationale')
        if change.get('action') not in {'replace', 'pause'} or not change.get('current_text'):
            die('creative choices require a supported action and the exact current text')
        if any(not str(change.get(field, '')).isdigit() for field in ('ad_group_id', 'ad_id', 'asset_id')):
            die('creative choices require exact ad group, ad and asset IDs')
        if change['action'] == 'replace':
            text = str(change.get('suggested_text') or '')
            protected = tuple(name for name in profile.get('goals', {}).get('protected_names', [])
                              if name.casefold() in change['current_text'].casefold())
            reasons = validate_copy(text, str(change.get('field_type', '')), protected_terms=protected)
            if reasons:
                errors.append({'row': index, 'asset_id': change['asset_id'], 'field': change.get('field_type'),
                               'text': text, 'characters': len(text),
                               'limit': {'HEADLINE': 30, 'DESCRIPTION': 90}.get(change.get('field_type')),
                               'reasons': list(reasons)})
    if errors:
        print(json.dumps({'saved': False, 'errors': errors}))
        raise SystemExit(2)
    plan.setdefault('baseline_changes', copy.deepcopy(plan.get('changes', [])))
    plan.update(changes=changes, decision_required=True, applied=False)
    for key in ('groups', 'approved_hash', 'apply_results', 'applied_at', 'applied_by', 'decision_id'):
        plan.pop(key, None)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(plan, sort_keys=False, allow_unicode=True))
    print(json.dumps({'saved': True, 'proposal': str(target),
                      'status': 'Draft saved; live checks and explicit approval still required.'}))


def creative_copy_apply(args: argparse.Namespace) -> None:
    """Review suggested copy, get user approval, push to Google Ads."""
    _require_write_permission()
    import datetime as _dt
    try:
        import yaml as _yaml
    except ImportError:
        die("pyyaml is required: pip install pyyaml")

    plan_path = Path(args.plan).expanduser()
    if not plan_path.exists():
        die(f"plan file not found: {plan_path}")
    plan = _yaml.safe_load(plan_path.read_text())
    if plan.get('decision_required') and not plan.get('decision_id'):
        die('Record and link the recommendation and prediction before applying this plan.')

    if plan.get("applied"):
        die(f"plan already applied on {plan.get('applied_at')}")
    if not plan.get("changes"):
        print("no changes in plan — nothing to apply")
        return

    changes = plan["changes"]
    groups = plan.get("groups", [])
    LIMITS = {"HEADLINE": 30, "DESCRIPTION": 90}
    actionable = [
        (i, c) for i, c in enumerate(changes, 1)
        if c.get("action") in ("replace", "pause") and c.get("apply_status") != "applied"
    ]
    if not actionable:
        print("no unapplied changes in plan — nothing to apply")
        return
    actionable_ids = {i for i, _ in actionable}

    # Merge --suggestions JSON without changing the persisted plan.
    sug_map: dict = {}
    if getattr(args, "suggestions", None):
        import json as _json
        try:
            suggestions = _json.loads(args.suggestions)
        except Exception as e:
            die(f"invalid --suggestions JSON: {e}")
        if not isinstance(suggestions, list) or not all(isinstance(s, dict) for s in suggestions):
            die('invalid --suggestions JSON: expected a list of {"id": ..., "text": ...} objects')
        try:
            suggestion_ids = [int(s["id"]) for s in suggestions]
            sug_map = {int(s["id"]): str(s["text"]).strip() for s in suggestions}
        except (KeyError, TypeError, ValueError) as exc:
            die(f"invalid --suggestions JSON: {exc}")
        from collections import Counter as _Counter
        duplicates = [i for i, count in _Counter(suggestion_ids).items() if count > 1]
        if duplicates:
            print(f"  ERROR: duplicate suggestion IDs: {duplicates[:5]}{'...' if len(duplicates) > 5 else ''}")
            return

    def _broadcast_groups() -> None:
        """Apply sug_map group texts to all matching changes."""
        for c in changes:
            gid = c.get("group_id")
            if c.get("apply_status") != "applied" and gid and sug_map.get(gid):
                c["suggested_text"] = sug_map[gid]

    def _broadcast_legacy() -> None:
        for i, c in enumerate(changes, 1):
            if c.get("apply_status") != "applied" and i in sug_map:
                c["suggested_text"] = sug_map[i]

    if groups:
        _broadcast_groups()
    else:
        _broadcast_legacy()

    # Validate suggestion IDs before doing anything irreversible.
    if not groups:
        sug_ids = list(sug_map.keys())
        out_of_range = [i for i in sug_ids if i not in actionable_ids]
        missing = [i for i, c in actionable
                   if i not in sug_map and c.get("action") == "replace" and not c.get("suggested_text")]
        if out_of_range:
            print(f"  ERROR: {len(out_of_range)} suggestion IDs do not belong to unapplied changes: "
                  f"{out_of_range[:5]}{'...' if len(out_of_range) > 5 else ''}")
        if missing:
            print(f"  ERROR: {len(missing)} replacement assets have no suggestion")
        if out_of_range or missing:
            print("  Suggestion set looks corrupted (ID drift). "
                  "Re-run suggest-creative-copy and regenerate all batches.")
            return
    else:
        expected = {int(c["group_id"]) for _, c in actionable if c.get("group_id") is not None}
        unexpected = sorted(set(sug_map) - expected)
        missing = sorted(gid for gid in expected if gid not in sug_map and not any(
            c.get("group_id") == gid and c.get("suggested_text") for _, c in actionable
        ))
        if unexpected or missing:
            if unexpected:
                print(f"  ERROR: unknown group suggestion IDs: {unexpected[:5]}")
            if missing:
                print(f"  ERROR: missing group suggestion IDs: {missing[:5]}")
            return

    # Character-limit failures invalidate the complete batch.
    invalid_suggestions = []
    if groups:
        active_groups = [g for g in groups if int(g["group_id"]) in expected]
        for g in active_groups:
            text = sug_map.get(g["group_id"], "") or next((
                c.get("suggested_text") for _, c in actionable
                if c.get("group_id") == g["group_id"] and c.get("suggested_text")
            ), "")
            limit = LIMITS.get(g["field_type"], 90)
            if not text or len(text) > limit:
                invalid_suggestions.append(
                    f"group {g['group_id']} [{g['field_type']}/{g.get('language', '')}] "
                    f"has {len(text)} chars (required 1–{limit})"
                )
        _broadcast_groups()
    else:
        for i, c in actionable:
            st = c.get("suggested_text")
            if c.get("action") != "replace":
                continue
            limit = LIMITS.get(c.get("field_type", ""), 90)
            if not st or len(st) > limit:
                invalid_suggestions.append(f"#{i} has {len(st or '')} chars (required 1–{limit})")
    if invalid_suggestions:
        for error in invalid_suggestions:
            print(f"  ERROR: {error}")
        print("No changes applied — fix the suggestions and review the complete plan again.")
        return

    # Pre-approval validation is separate from the fresh read after approval.
    from .rules import read_live_ads, validate_plan, refresh_copy_evidence
    from google.ads.googleads.client import GoogleAdsClient
    preview_profile = load_profile(required=True)
    preview_account = str(preview_profile.get('google_ads_customer_id', '')).replace('-', '')
    preview_client = GoogleAdsClient.load_from_storage(str(_runtime_write_config_path()))
    refresh_copy_evidence(preview_client, preview_account, plan, preview_profile)
    excluded_entities = tuple(preview_profile.get('goals', {}).get('excluded_entities', []))
    if any(str(change.get('campaign_id', '')) in excluded_entities for _, change in actionable):
        die('creative plan includes an excluded campaign')
    preview = validate_plan(plan, preview_account, read_live_ads(preview_client, preview_account, [c for _, c in actionable]), excluded_entities)
    for verdict in preview:
        if not verdict['allowed']:
            print(f"  HELD #{verdict['index'] + 1}: {'; '.join(verdict['reasons'])}")

    # Approval table
    if groups:
        print(f"\n{'#':<3}  {'Theme':<28}  {'Field':<12}  {'Lang':<10}  {'N':<4}  Suggested")
        print("─" * 100)
        for g in active_groups:
            gid = g["group_id"]
            text = sug_map.get(gid) or "—"
            chars = len(text) if text != "—" else 0
            theme_col = g.get("theme", g.get("field_type", ""))[:27]
            print(f"{gid:<3}  {theme_col:<28}  {g['field_type']:<12}  {g['language']:<10}  "
                  f"{g['asset_count']:<4}  \"{text[:45]}\"({chars})")
    else:
        print(f"\n{'#':<3}  {'Campaign':<22}  {'Field':<12}  {'Current':<32}  {'Suggested':<32}  Metric vs avg")
        print("─" * 120)
        for i, c in actionable:
            current = (c.get("current_text") or "")[:30]
            suggested = (c.get("suggested_text") or "—")[:30]
            cur_chars = len(c.get("current_text") or "")
            sug_chars = len(c.get("suggested_text") or "") if c.get("suggested_text") else 0
            ft = c.get("field_type", "")
            ctr_note = f"CTR {c.get('ctr_percent','')}%→{c.get('campaign_avg_ctr','')}%"
            print(f"{i:<3}  {c.get('campaign_name','')[:22]:<22}  {ft:<12}  "
                  f"\"{current}\"({cur_chars})  \"{suggested}\"({sug_chars})  {ctr_note}")

    print("\nApprove all? [y/n/edit N]: ", end="", flush=True)
    try:
        answer = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\nAborted.")
        return

    while answer.startswith("edit"):
        parts = answer.split()
        if len(parts) == 2 and parts[1].isdigit():
            num = int(parts[1])
            if groups:
                # N = group_id
                g_match = next((g for g in groups if g["group_id"] == num), None)
                if g_match:
                    ft = g_match["field_type"]
                    print(f"New text for group {num} ({ft}, limit {LIMITS.get(ft, 90)} chars): ", end="", flush=True)
                    try:
                        new_text = input().strip()
                    except (EOFError, KeyboardInterrupt):
                        break
                    limit = LIMITS.get(ft, 90)
                    if len(new_text) > limit:
                        print(f"  Still over limit ({len(new_text)} chars) — skipping")
                    else:
                        sug_map[num] = new_text
                        _broadcast_groups()
            else:
                idx = num - 1
                if 0 <= idx < len(changes):
                    ft = changes[idx]["field_type"]
                    print(f"New text for #{num} ({ft}, limit {LIMITS.get(ft, 90)} chars): ", end="", flush=True)
                    try:
                        new_text = input().strip()
                    except (EOFError, KeyboardInterrupt):
                        break
                    limit = LIMITS.get(ft, 90)
                    if len(new_text) > limit:
                        print(f"  Still over limit ({len(new_text)} chars) — skipping")
                    else:
                        changes[idx]["suggested_text"] = new_text
        # Re-show
        if groups:
            print(f"\n{'#':<3}  {'Theme':<28}  {'Field':<12}  {'Lang':<10}  {'N':<4}  Suggested")
            for g in active_groups:
                gid = g["group_id"]
                text = sug_map.get(gid) or "—"
                theme_col = g.get("theme", g.get("field_type", ""))[:27]
                print(f"{gid:<3}  {theme_col:<28}  {g['field_type']:<12}  {g['language']:<10}  "
                      f"{g['asset_count']:<4}  \"{text[:45]}\"")
        else:
            print(f"\n{'#':<3}  {'Field':<12}  {'Suggested'}")
            for i, c in actionable:
                print(f"{i:<3}  {c.get('field_type',''):<12}  {c.get('suggested_text') or '—'}")
        print("\nApprove all? [y/n/edit N]: ", end="", flush=True)
        try:
            answer = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            break

    if answer != "y":
        print("Aborted — no changes applied.")
        return

    from lib.bob.bid_budget.guards import plan_hash
    approved_hash = plan_hash({"customer_id": plan.get("customer_id"), "changes": [
        {key: change.get(key) for key in ("ad_group_id", "asset_id", "current_text", "suggested_text", "field_type", "action")}
        for _, change in actionable]})
    selected_profile = load_profile(required=True)
    if str(plan.get("customer_id", "")).replace("-", "") != str(selected_profile.get("google_ads_customer_id", "")).replace("-", ""):
        die("creative plan is outside the selected account")
    if plan.get("decision_id"):
        from lib.bob.decisions.records import get, update
        get(STATE_ROOT, str(plan["customer_id"]).replace("-", ""), plan["decision_id"])

    try:
        from google.ads.googleads.client import GoogleAdsClient  # type: ignore
        from google.ads.googleads.errors import GoogleAdsException  # type: ignore
        from google.protobuf.field_mask_pb2 import FieldMask  # type: ignore
    except ImportError:
        die("google-ads library required: pip install google-ads")

    profile = load_profile(required=False)
    config_path = str(_runtime_write_config_path())
    customer_id = str(plan.get("customer_id", profile.get("google_ads_customer_id", ""))).replace("-", "")

    try:
        client = GoogleAdsClient.load_from_storage(config_path)
    except Exception as exc:
        die(f"failed to load Google Ads client: {exc}")

    ga_svc = client.get_service("GoogleAdsService")
    refresh_copy_evidence(client, customer_id, plan, profile)
    ad_svc = client.get_service("AdService")
    select_fields = (
        "SELECT campaign.id, ad_group.id, ad_group_ad.resource_name, ad_group_ad.ad.id, ad_group_ad.status,"
        " ad_group_ad.ad.app_ad.headlines, ad_group_ad.ad.app_ad.descriptions"
        " FROM ad_group_ad"
    )
    local_failures: dict[int, str] = {}
    rows_by_ad: dict[str, dict[str, Any]] = {}
    exact_ids = sorted({str(c.get("ad_id", "")) for _, c in actionable if str(c.get("ad_id", "")).isdigit()})
    if exact_ids:
        query = (
            select_fields
            + f" WHERE ad_group_ad.ad.id IN ({', '.join(exact_ids)})"
            + " AND ad_group_ad.status != 'REMOVED'"
        )
        try:
            for row in ga_svc.search(customer_id=customer_id, query=query):
                rows_by_ad[str(row.ad_group_ad.ad.id)] = {
                    "ad": row.ad_group_ad,
                    "ad_group_id": str(row.ad_group.id),
                    "campaign_id": str(row.campaign.id),
                }
        except Exception as exc:
            die(f"creative copy validation failed while resolving target ads: {exc}")

    # Older plans did not persist ad_id. Resolve them only when the current text
    # identifies exactly one live ad in the stated ad group.
    legacy_by_group: dict[str, list[Any]] = {}
    for change_index, change in actionable:
        if str(change.get("ad_id", "")).isdigit():
            continue
        ad_group_id = str(change.get("ad_group_id", ""))
        if not ad_group_id.isdigit():
            local_failures[change_index] = f"asset {change.get('asset_id', '')}: invalid ad group ID"
            continue
        if ad_group_id not in legacy_by_group:
            query = (
                select_fields
                + f" WHERE ad_group.id = {ad_group_id}"
                + " AND ad_group_ad.status != 'REMOVED'"
            )
            try:
                legacy_rows = list(ga_svc.search(customer_id=customer_id, query=query))
                legacy_by_group[ad_group_id] = [row.ad_group_ad for row in legacy_rows]
                for row in legacy_rows:
                    rows_by_ad[str(row.ad_group_ad.ad.id)] = {'ad': row.ad_group_ad,
                        'ad_group_id': str(row.ad_group.id), 'campaign_id': str(row.campaign.id)}
            except Exception as exc:
                die(f"creative copy validation failed while resolving ad group {ad_group_id}: {exc}")
        field = str(change.get("field_type", ""))
        current = str(change.get("current_text", ""))
        candidates = []
        for row_ad in legacy_by_group[ad_group_id]:
            assets = row_ad.ad.app_ad.headlines if field == "HEADLINE" else row_ad.ad.app_ad.descriptions
            if any(asset.text == current for asset in assets):
                candidates.append(row_ad)
        if len(candidates) != 1:
            local_failures[change_index] = (
                f"asset {change.get('asset_id', '')}: expected one live target ad, found {len(candidates)}"
            )
            continue
        change["ad_id"] = str(candidates[0].ad.id)
        rows_by_ad[change["ad_id"]].update({"ad": candidates[0], "ad_group_id": ad_group_id})

    from collections import defaultdict as _defaultdict
    changes_by_ad: dict[str, list[tuple[int, dict]]] = _defaultdict(list)
    for index, change in actionable:
        if index in local_failures:
            continue
        ad_id = str(change.get("ad_id", ""))
        ad_group_id = str(change.get("ad_group_id", ""))
        field = str(change.get("field_type", ""))
        action = str(change.get("action", ""))
        current = str(change.get("current_text", ""))
        proposed = str(change.get("suggested_text") or "")
        row_errors = []
        if action == "replace":
            row_errors.extend(validate_copy(proposed, field,
                              protected_terms=tuple(change.get("protected_terms", [])),
                              existing_good=tuple(change.get("existing_good", []))))
        if not ad_id.isdigit() or ad_id not in rows_by_ad:
            row_errors.append(f"target ad {ad_id or 'missing'} was not found")
        elif rows_by_ad[ad_id]["ad_group_id"] != ad_group_id:
            row_errors.append(f"target ad is not in ad group {ad_group_id}")
        elif rows_by_ad[ad_id]['campaign_id'] in excluded_entities:
            row_errors.append('live campaign is excluded by account rules')
        elif change.get('campaign_id') and str(change['campaign_id']) != rows_by_ad[ad_id]['campaign_id']:
            row_errors.append('campaign identity does not match the live ad')
        elif rows_by_ad[ad_id]["ad"].status.name != 'ENABLED':
            row_errors.append('target ad is no longer enabled')
        if field not in LIMITS:
            row_errors.append(f"unsupported field type {field or 'missing'}")
        if action not in ("replace", "pause"):
            row_errors.append(f"unsupported action {action or 'missing'}")
        if not current:
            row_errors.append("current text is missing")
        if action == "replace" and (not proposed or len(proposed) > LIMITS.get(field, 90)):
            row_errors.append("proposed text is missing or over the limit")
        if action == "replace" and proposed == current:
            row_errors.append("proposed text is unchanged")
        if row_errors:
            local_failures[index] = f"asset {change.get('asset_id', '')}: " + "; ".join(row_errors)
            continue
        changes_by_ad[ad_id].append((index, change))

    ad_operations = []
    operation_contexts = []
    for ad_id, ad_changes in changes_by_ad.items():
        target = rows_by_ad.get(ad_id)
        if not target:
            continue
        row_ad = target["ad"]
        headlines = [asset.text for asset in row_ad.ad.app_ad.headlines]
        descriptions = [asset.text for asset in row_ad.ad.app_ad.descriptions]
        updated_fields: set[str] = set()
        ad_results = []
        ad_errors = []
        for change_index, change in ad_changes:
            field = change.get("field_type")
            values = headlines if field == "HEADLINE" else descriptions
            current = str(change.get("current_text", ""))
            matches = [position for position, text in enumerate(values) if text == current]
            if not matches:
                ad_errors.append(
                    f"asset {change.get('asset_id', '')}: current text is not present in target ad {ad_id}"
                )
                continue
            position = matches[0]
            if change.get("action") == "replace":
                values[position] = str(change.get("suggested_text"))
                status = "replaced"
            else:
                values.pop(position)
                status = "paused"
            updated_fields.add("app_ad.headlines" if field == "HEADLINE" else "app_ad.descriptions")
            ad_results.append({
                "change_index": change_index,
                "campaign": change.get("campaign_name", ""),
                "asset_id": change.get("asset_id", ""),
                "field_type": field,
                "ad_id": ad_id,
                "status": status,
                **({"suggested_text": change.get("suggested_text")} if status == "replaced" else {}),
            })
        if not 1 <= len(headlines) <= 5:
            ad_errors.append(f"ad {ad_id}: resulting headline count {len(headlines)} is outside 1–5")
        if not 1 <= len(descriptions) <= 5:
            ad_errors.append(f"ad {ad_id}: resulting description count {len(descriptions)} is outside 1–5")
        for label, values in (("headline", headlines), ("description", descriptions)):
            seen = set()
            duplicates = []
            for text in values:
                key = " ".join(str(text).split()).casefold()
                if key in seen and text not in duplicates:
                    duplicates.append(text)
                seen.add(key)
            if duplicates:
                ad_errors.append(f"ad {ad_id}: resulting {label}s contain duplicate text: {duplicates[0]!r}")
        if ad_errors:
            reason = "; ".join(ad_errors)
            for change_index, _ in ad_changes:
                local_failures.setdefault(change_index, reason)
            continue
        if not updated_fields:
            continue

        operation = client.get_type("AdOperation")
        ad_update = operation.update
        ad_update.resource_name = ad_svc.ad_path(customer_id, ad_id)
        for text in headlines:
            text_asset = client.get_type("AdTextAsset")
            text_asset.text = text
            ad_update.app_ad.headlines.append(text_asset)
        for text in descriptions:
            text_asset = client.get_type("AdTextAsset")
            text_asset.text = text
            ad_update.app_ad.descriptions.append(text_asset)
        mask = FieldMask()
        mask.paths.extend(sorted(updated_fields))
        operation.update_mask.CopyFrom(mask)
        ad_operations.append(operation)
        operation_contexts.append({"ad_id": ad_id, "results": ad_results})

    if not ad_operations:
        for error in local_failures.values():
            print(f"  ERROR: {error}")
        die("creative copy validation produced no valid operations — no changes were applied")

    def mutation_error(exc: Exception) -> str:
        if isinstance(exc, GoogleAdsException):
            messages = []
            for error in exc.failure.errors:
                detail = str(error.message)
                error_code = str(getattr(error, "error_code", "") or "").strip()
                location = str(getattr(error, "location", "") or "").strip()
                if error_code:
                    detail += f" [code={error_code}]"
                if location:
                    detail += f" [location={location}]"
                messages.append(detail)
            request_id = str(getattr(exc, "request_id", "") or "").strip()
            if request_id:
                messages.append(f"request_id={request_id}")
            return "; ".join(messages)
        return str(exc)

    def as_mutate_operations(operations):
        converted = []
        for ad_operation in operations:
            mutate_operation = client.get_type("MutateOperation")
            mutate_operation.ad_operation = ad_operation
            converted.append(mutate_operation)
        return converted

    def partial_errors(response):
        status = getattr(response, "partial_failure_error", None)
        if not status or not int(getattr(status, "code", 0) or 0):
            return []
        failure_type = type(client.get_type("GoogleAdsFailure"))
        errors = []
        for detail in getattr(status, "details", []):
            failure = failure_type.deserialize(detail.value)
            errors.extend(list(failure.errors))
        return errors

    def operation_error_map(response):
        mapped: dict[int, list[str]] = _defaultdict(list)
        unmapped = []
        for error in partial_errors(response):
            operation_index = None
            location = getattr(error, "location", None)
            for element in getattr(location, "field_path_elements", []) if location else []:
                if getattr(element, "field_name", "") == "mutate_operations":
                    operation_index = int(getattr(element, "index", 0))
                    break
            detail = str(getattr(error, "message", "Google Ads rejected the operation"))
            error_code = str(getattr(error, "error_code", "") or "").strip()
            if error_code:
                detail += f" [code={error_code}]"
            if operation_index is None:
                unmapped.append(detail)
            else:
                mapped[operation_index].append(detail)
        return {index: "; ".join(messages) for index, messages in mapped.items()}, unmapped

    def mutate_request(operations, *, validate_only: bool):
        mutate_operations = as_mutate_operations(operations)
        request = client.get_type("MutateGoogleAdsRequest")
        request.customer_id = customer_id
        request.mutate_operations.extend(mutate_operations)
        request.partial_failure = True
        request.validate_only = validate_only
        return request

    try:
        validation_response = ga_svc.mutate(request=mutate_request(ad_operations, validate_only=True))
    except Exception as exc:
        die(f"creative copy validation failed — no changes were applied: {mutation_error(exc)}")
    validation_failures, unmapped = operation_error_map(validation_response)
    if unmapped:
        die("creative copy validation returned an unmapped error — no changes were applied: " + "; ".join(unmapped))

    outcomes = dict(local_failures)
    surviving_operations = []
    surviving_contexts = []
    for operation_index, (operation, context) in enumerate(zip(ad_operations, operation_contexts)):
        if operation_index in validation_failures:
            for result in context["results"]:
                outcomes[result["change_index"]] = validation_failures[operation_index]
        else:
            surviving_operations.append(operation)
            surviving_contexts.append(context)
    if not surviving_operations:
        for error in outcomes.values():
            print(f"  ERROR: {error}")
        die("Google Ads rejected every creative operation during validation — no changes were applied")

    final_hash = plan_hash({"customer_id": plan.get("customer_id"), "changes": [
        {key: change.get(key) for key in ("ad_group_id", "asset_id", "current_text", "suggested_text", "field_type", "action")}
        for _, change in actionable]})
    if final_hash != approved_hash:
        die("creative proposal changed after approval; review it again")
    plan["approved_hash"] = approved_hash
    try:
        mutation_response = ga_svc.mutate(request=mutate_request(surviving_operations, validate_only=False))
    except Exception as exc:
        die(f"creative copy mutation response was unavailable — plan unchanged: {mutation_error(exc)}")
    mutation_failures, unmapped = operation_error_map(mutation_response)
    if unmapped:
        die("creative copy mutation returned an unmapped result — reconcile before retrying: " + "; ".join(unmapped))

    applied_at = _dt.datetime.now().isoformat(timespec="seconds")
    current_results = {}
    applied_count = 0
    for operation_index, context in enumerate(surviving_contexts):
        failure = mutation_failures.get(operation_index)
        for result in context["results"]:
            change_index = result["change_index"]
            if failure:
                outcomes[change_index] = failure
            else:
                applied_count += 1
                current_results[change_index] = result

    if not applied_count:
        for error in outcomes.values():
            print(f"  ERROR: {error}")
        die("Google Ads applied no creative changes — plan unchanged")

    for change_index, change in actionable:
        if change_index in current_results:
            change["apply_status"] = "applied"
            change["applied_at"] = applied_at
            change.pop("apply_error", None)
        else:
            change["apply_status"] = "failed"
            change["apply_error"] = outcomes.get(change_index, "Google Ads did not apply this change")
            change.pop("applied_at", None)

    previous_results = {
        int(result["change_index"]): result for result in plan.get("apply_results", [])
        if isinstance(result, dict) and str(result.get("change_index", "")).isdigit()
    }
    for change_index, result in current_results.items():
        previous_results[change_index] = result
    for change_index, reason in outcomes.items():
        change = changes[change_index - 1]
        previous_results[change_index] = {
            "change_index": change_index,
            "campaign": change.get("campaign_name", ""),
            "asset_id": change.get("asset_id", ""),
            "field_type": change.get("field_type", ""),
            "ad_id": change.get("ad_id", ""),
            "status": "failed",
            "error": reason,
        }

    remaining = [c for c in changes if c.get("action") in ("replace", "pause") and c.get("apply_status") != "applied"]
    plan["applied"] = not remaining
    plan["apply_status"] = "applied" if not remaining else "partial"
    plan["applied_at"] = applied_at if not remaining else None
    plan["last_apply_at"] = applied_at
    plan["apply_results"] = [previous_results[index] for index in sorted(previous_results)]
    plan["changes"] = changes
    plan_temp = plan_path.with_suffix(plan_path.suffix + ".tmp")
    plan_temp.write_text(_yaml.dump(plan, default_flow_style=False, allow_unicode=True, sort_keys=False))
    os.replace(plan_temp, plan_path)
    if plan.get("decision_id"):
        update(STATE_ROOT, customer_id, plan["decision_id"], "execution",
               {"executed_at": applied_at, "plan": str(plan_path),
                "results": plan["apply_results"], "complete": plan["applied"]})

    for result in current_results.values():
        if result["status"] == "replaced":
            print(f"  ✓ {result['campaign']} / {result['field_type']} — replaced: \"{result['suggested_text']}\"")
        else:
            print(f"  ✓ {result['campaign']} / {result['field_type']} — removed from app ad")
    for change_index in sorted(outcomes):
        print(f"  ✗ change #{change_index} — {outcomes[change_index]}")

    n_replaced = sum(1 for result in current_results.values() if result["status"] == "replaced")
    n_paused = sum(1 for result in current_results.values() if result["status"] == "paused")
    print(f"\n{n_replaced} new assets live, {n_paused} paused, {len(outcomes)} not applied — plan saved: {plan_path}")

__all__ = [name for name in globals() if not name.startswith("__")]
