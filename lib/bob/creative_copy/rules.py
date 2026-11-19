"""Copy checks with explicit account vocabulary; no guessed proper nouns."""
from __future__ import annotations

import unicodedata


def validate_copy(text: str, field: str, *, protected_terms: tuple[str, ...] = (),
                  existing_good: tuple[str, ...] = ()) -> tuple[str, ...]:
    errors: list[str] = []
    limits = {"HEADLINE": 30, "DESCRIPTION": 90}
    if field not in limits:
        return ("unsupported text field",)
    if not text.strip() or len(text) > limits[field]:
        errors.append("copy is empty or exceeds the character limit")
    if any(term.casefold() not in text.casefold() for term in protected_terms):
        errors.append("copy omitted a protected name")
    canonical = lambda value: " ".join(unicodedata.normalize("NFKC", value).casefold().split())
    if canonical(text) in {canonical(value) for value in existing_good}:
        errors.append("copy duplicates an existing GOOD/BEST asset")
    return tuple(errors)


def validate_plan(plan: dict, account: str, live: list[dict] | None = None,
                  excluded_entities: tuple[str, ...] = ()) -> list[dict]:
    if str(plan.get("customer_id", "")).replace("-", "") != account.replace("-", ""):
        raise ValueError("creative plan is outside the selected account")
    verdicts = []
    for index, change in enumerate(plan.get("changes", [])):
        if change.get("apply_status") == "applied":
            continue
        reasons = ()
        if str(change.get('campaign_id', '')) in excluded_entities:
            verdicts.append({'index': index, 'allowed': False, 'reasons': ('campaign excluded by account rules',)})
            continue
        if change.get("action") == "replace":
            reasons = validate_copy(str(change.get("suggested_text") or ""), str(change.get("field_type", "")),
                                    protected_terms=tuple(change.get("protected_terms", [])),
                                    existing_good=tuple(change.get("existing_good", [])))
        elif change.get("action") != "pause":
            reasons = ("unsupported creative action",)
        if live is not None:
            field = 'headlines' if change.get('field_type') == 'HEADLINE' else 'descriptions'
            matches = [ad for ad in live if ad['ad_group_id'] == str(change.get('ad_group_id', ''))
                       and (not change.get('ad_id') or ad['ad_id'] == str(change['ad_id']))
                       and change.get('current_text') in ad[field] and ad['enabled']]
            if len(matches) != 1:
                reasons += ('old text is absent, changed, disabled or ambiguous in live ads',)
            elif matches[0].get('campaign_id') in excluded_entities:
                reasons += ('live campaign is excluded by account rules',)
            elif change.get('campaign_id') and str(change['campaign_id']) != matches[0].get('campaign_id'):
                reasons += ('campaign identity does not match the live ad',)
        verdicts.append({"index": index, "allowed": not reasons, "reasons": reasons})
    return verdicts


def read_live_ads(client, account: str, changes: list[dict]) -> list[dict]:
    ids = sorted({str(change.get('ad_group_id', '')) for change in changes})
    if not ids or any(not value.isdigit() for value in ids):
        raise ValueError('live creative check requires numeric ad group IDs')
    query = '''SELECT campaign.id, ad_group.id, ad_group_ad.ad.id, ad_group_ad.status,
      ad_group_ad.ad.app_ad.headlines, ad_group_ad.ad.app_ad.descriptions
      FROM ad_group_ad WHERE ad_group.id IN (''' + ','.join(ids) + ") AND ad_group_ad.status != 'REMOVED'"
    return [{'campaign_id': str(row.campaign.id), 'ad_group_id': str(row.ad_group.id), 'ad_id': str(row.ad_group_ad.ad.id),
             'enabled': row.ad_group_ad.status.name == 'ENABLED',
             'headlines': [asset.text for asset in row.ad_group_ad.ad.app_ad.headlines],
             'descriptions': [asset.text for asset in row.ad_group_ad.ad.app_ad.descriptions]}
            for row in client.get_service('GoogleAdsService').search(customer_id=account, query=query, timeout=15)]


def refresh_copy_evidence(client, account: str, plan: dict, profile: dict) -> None:
    """Peer labels and required names come from evidence/config, not plan assertions."""
    ids = sorted({str(change.get('ad_group_id', '')) for change in plan.get('changes', [])})
    if not ids or any(not value.isdigit() for value in ids):
        raise ValueError('copy evidence requires exact ad group IDs')
    query = '''SELECT ad_group.id, ad_group_ad_asset_view.field_type,
      ad_group_ad_asset_view.performance_label, asset.text_asset.text
      FROM ad_group_ad_asset_view WHERE ad_group.id IN (''' + ','.join(ids) + ") AND asset.type = 'TEXT'"
    peers: dict[tuple[str, str], set[str]] = {}
    for row in client.get_service('GoogleAdsService').search(customer_id=account, query=query, timeout=15):
        view = row.ad_group_ad_asset_view
        if view.performance_label.name in {'GOOD', 'BEST'}:
            peers.setdefault((str(row.ad_group.id), view.field_type.name), set()).add(row.asset.text_asset.text)
    for change in plan.get('changes', []):
        current = str(change.get('current_text', ''))
        change['protected_terms'] = sorted(set(change.get('protected_terms', [])) | {
            name for name in profile.get('goals', {}).get('protected_names', []) if name.casefold() in current.casefold()})
        change['existing_good'] = sorted(peers.get((str(change.get('ad_group_id', '')), str(change.get('field_type', ''))), set()))
