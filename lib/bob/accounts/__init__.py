"""Account onboarding, selection, credential setup, and setup repair."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from lib.bob.platform.core import *
from lib.bob.platform.google_ads import *
from lib.bob.platform.presentation import *
def setup_write_credentials(args: argparse.Namespace) -> None:
    _install_capability("write")
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
    except ImportError:
        die("google_auth_oauthlib could not be installed — ask Bob to fix setup and try again.")
    import yaml as _yaml
    import json as _json

    profile = load_profile(required=False)
    _normalize_account_config_files(profile)

    creds_json = Path(getattr(args, "creds", None) or "~/google-ads-creds.json").expanduser()
    if not creds_json.exists():
        die(f"client secrets not found: {creds_json}\nDownload it from Google Cloud Console → OAuth 2.0 Client IDs → Download JSON")

    garf_yaml = _resolve_profile_config_path(profile, write=False)
    gads_cfg = _yaml.safe_load(garf_yaml.read_text()) if garf_yaml.exists() else {}
    dev_token = gads_cfg.get("developer_token", "")
    login_cid = str(gads_cfg.get("login_customer_id", "")).replace("-", "")
    if not dev_token:
        die(f"developer_token not found in {garf_yaml}")

    out_path = Path(getattr(args, "output", None) or _default_write_config_path(_profile_customer_id(profile))).expanduser()

    print("Waiting for browser authorization — local server starting on http://127.0.0.1:8080 …")
    flow = InstalledAppFlow.from_client_secrets_file(
        str(creds_json), scopes=["https://www.googleapis.com/auth/adwords"]
    )
    credentials = flow.run_local_server(
        port=8080,
        open_browser=False,
        authorization_prompt_message="OAUTH_URL: {url}",
    )

    secrets = _json.loads(creds_json.read_text()).get("installed", {})
    write_cfg = {
        "developer_token": dev_token,
        "client_id": secrets.get("client_id", ""),
        "client_secret": secrets.get("client_secret", ""),
        "refresh_token": credentials.refresh_token,
        "login_customer_id": login_cid,
        "use_proto_plus": True,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        _yaml.dump(write_cfg, f, default_flow_style=False, sort_keys=False)
    print(f"\nWrite credentials saved: {out_path}")
    print("Run 'python3 lib/datapull.py check-config' to verify.")


CAMPAIGN_TYPES: list[tuple[str, str]] = [
    ("app", "App Campaigns"),
    ("search", "Search  [analysis features not wired yet — data only]"),
    ("performance_max", "Performance Max  [analysis features not wired yet — data only]"),
]

CAMPAIGN_GOAL_TYPES: dict[str, dict[str, str]] = {
    "installs": {"campaign_goal_type": "app_installs"},
    "in_app_conversions": {"campaign_goal_type": "app_in_app_conversions"},
}

CURRENCY_OPTIONS: list[tuple[str, str]] = [
    ("INR", "INR — Indian Rupee"),
    ("USD", "USD — US Dollar"),
    ("EUR", "EUR — Euro"),
    ("GBP", "GBP — British Pound"),
    ("BRL", "BRL — Brazilian Real"),
    ("AUD", "AUD — Australian Dollar"),
]

_GARF_READ_FORMAT = """\
  GARF read config format (google-ads-garf.yaml):
  ┌──────────────────────────────────────────┐
  │ developer_token: YOUR_TOKEN              │
  │ login_customer_id: 1234567890           │  ← MCC ID, no hyphens
  └──────────────────────────────────────────┘"""

_WRITE_CONFIG_FORMAT = """\
  Write config format (google-ads-api.yaml):
  ┌──────────────────────────────────────────┐
  │ developer_token: YOUR_TOKEN              │
  │ client_id: YOUR_CLIENT_ID               │
  │ client_secret: YOUR_SECRET              │
  │ refresh_token: WRITE_REFRESH_TOKEN      │
  │ login_customer_id: 1234567890           │
  └──────────────────────────────────────────┘"""


def _ob_prompt(label: str, default: str = "") -> str:
    """Single-line interactive prompt with optional default.

    Accepts empty string, 'y', 'yes', or 'same' as signals to use the default,
    so the prompt works reliably when relayed through a terminal emulator or agent.
    """
    if default:
        prompt_line = f"  {label} — default is {default}, type 'y' to accept or enter a value: "
    else:
        prompt_line = f"  {label}: "
    try:
        val = input(prompt_line).strip()
    except (EOFError, KeyboardInterrupt):
        print("\nAborted.")
        raise SystemExit(0)
    if default and val.lower() in ("", "y", "yes", "same", "default"):
        return default
    return val


def _ob_context(why: str, where: str = "") -> None:
    print(f"  Why this matters: {why}")
    if where:
        print(f"  Where to find it: {where}")


def _ob_prompt_help(label: str, why: str, where: str = "", default: str = "") -> str:
    _ob_context(why, where)
    return _ob_prompt(label, default)


def _ob_prompt_raw(label: str) -> str:
    """Single-line interactive prompt with no implicit default shortcuts."""
    try:
        return input(f"  {label}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nAborted.")
        raise SystemExit(0)


def _ob_numbered(
    label: str,
    options: list[tuple[str, str]],
    default: int = 1,
    why: str = "",
    where: str = "",
) -> tuple[str, str]:
    """Numbered-choice prompt. Returns (key, display_label)."""
    print(f"\n  {label}")
    if why:
        _ob_context(why, where)
    for i, (_, display) in enumerate(options, 1):
        marker = " *" if i == default else "  "
        print(f"{marker}  {i}) {display}")
    inline_options = "  ".join(f"{i}) {display}" for i, (_, display) in enumerate(options, 1))
    prompt = f"{label} {inline_options}"
    while True:
        raw = _ob_prompt_raw(prompt)
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]
        print(f"  Please choose a number from 1 to {len(options)}.")


def _validate_customer_id(cid: str) -> bool:
    return bool(re.fullmatch(r"\d{3}-\d{3}-\d{4}", cid.strip()))


def _check_config_path(path_str: str, is_write_config: bool = False) -> list[str]:
    """Return list of MISSING key names; empty list = all present."""
    path = Path(path_str).expanduser()
    if not path.exists():
        return ["FILE NOT FOUND"]
    text = path.read_text()
    present = set()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#") and ":" in line:
            key = line.split(":", 1)[0].strip()
            present.add(key)
    # Write config (bid-budget-apply) requires full OAuth2 credentials
    # GARF read config only needs developer_token and login_customer_id
    if is_write_config:
        required = {"developer_token", "client_id", "client_secret", "refresh_token", "login_customer_id"}
    else:
        required = {"developer_token", "login_customer_id"}
    return sorted(required - present)


def _yaml_scalar(value: str) -> str:
    return json.dumps(str(value))


def _write_garf_read_config(path_str: str, developer_token: str, login_customer_id: str) -> None:
    path = Path(path_str).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    text = (
        f"developer_token: {_yaml_scalar(developer_token)}\n"
        f"login_customer_id: {_yaml_scalar(login_customer_id.replace('-', ''))}\n"
    )
    path.write_text(text)


def _print_section(title: str) -> None:
    print(f"\n  ── {title} {'─' * max(0, 46 - len(title))}")


def _print_onboard_summary(profile: dict[str, Any]) -> None:
    """Print the confirm summary. Shared by interactive confirm and non-interactive dry-run."""
    ct_display = dict(CAMPAIGN_TYPES).get(profile["campaign_type"], profile["campaign_type"])
    print("\n  ── Confirm ──────────────────────────────────────────────────────")
    print(f"  Account:       {profile['account_name']} ({profile['google_ads_customer_id']})")
    mcc_id = profile.get("google_ads_mcc_id", "")
    mcc_name = profile.get("google_ads_mcc_name", "")
    if mcc_id:
        print(f"  MCC:           {mcc_name} ({mcc_id})" if mcc_name else f"  MCC:           {mcc_id}")
    print(f"  Campaign type: {ct_display.split('[')[0].strip()}")
    if profile["campaign_type"] == "app":
        print(f"  Primary goal:  {profile['primary_goal']}")
    print(f"  Currency:      {profile['currency']}")
    print(f"  Read access:   {'ready' if profile['google_ads_read_config_path'] else 'not set'}")
    print(f"  Write access:  {'ready' if profile['google_ads_write_config_path'] else 'not set'}")
    print(
        f"  CAC ceiling:   {profile['cac_ceiling']}  |  Change %: "
        f"{profile['bid_budget_change_pct']}  |  Cooldown: {profile['bid_budget_cooldown_days']}d"
    )


def _finalize_onboard(profile: dict[str, Any], write_creds_json_path: str, existing: list[dict]) -> None:
    """Save the account and run post-save setup. Shared by interactive and non-interactive paths.

    Assumes the profile is fully built and the read config (if any) is already written.
    """
    cid = profile["google_ads_customer_id"]
    account_name = profile["account_name"]
    campaign_type = profile["campaign_type"]
    google_ads_read_config_path = profile["google_ads_read_config_path"]
    google_ads_write_config_path = profile["google_ads_write_config_path"]

    _set_active_account(profile)
    new_entry = {
        "google_ads_customer_id": cid,
        "account_name": account_name,
        "campaign_type": campaign_type,
        "active": True,
    }
    updated = [dict(a, active=False) for a in existing] + [new_entry]
    _save_accounts_registry(updated)

    print("\n  Account saved.")

    if write_creds_json_path:
        print("\n  Setting up Google Ads write access now.")
        setup_write_credentials(
            argparse.Namespace(
                creds=write_creds_json_path,
                output=google_ads_write_config_path,
            )
        )

    runtime_issues = _repair_and_check_onboarding_runtime(
        require_read=bool(google_ads_read_config_path),
        require_write=bool(google_ads_write_config_path),
    )
    if runtime_issues:
        print(f"""
  {account_name} is saved, mate. One thing didn't install cleanly on the first try —
  ask me to "fix setup" and I'll have another go.
""")
        return

    read_status = (
        "Data access is ready. I'll pull data only when you ask a performance question."
        if google_ads_read_config_path
        else "Data access is not ready yet. I need the Google Ads developer token from Google Ads > Admin > API Center before I can fetch data from Google Ads."
    )
    write_status = (
        "Write access is ready."
        if google_ads_write_config_path
        else "Write access is not set up. No dramas — I can still save recommendations to the wiki for you to apply manually in Google Ads."
    )
    print(f"""
  Righto, {account_name} is set up.

  {read_status}
  {write_status}

  From now on, run commands as ./bob <subcommand>.
  Type ./bob to see what's available, or ./bob <name> --help for any one.

  Good first questions to ask next:
  1) What happened yesterday?
  2) How did yesterday compare to the same day last week?
  3) How did last week compare to the week before?
  4) Which campaigns are dragging?
""")


def _normalize_customer_id(raw: str) -> str:
    """Reformat a 10-digit string to DDD-DDD-DDDD; otherwise return stripped input unchanged."""
    raw = str(raw).strip()
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    return raw


def _onboard_from_answers(args: argparse.Namespace, existing: list[dict]) -> None:
    """Non-interactive onboarding: validate a JSON answers blob, then save (or --dry-run preview).

    The agent gathers answers conversationally and submits them here in one call — no input()
    round-trips (which deadlock when an agent runs the script non-interactively). All validation
    problems are reported together so the agent can re-ask only the bad fields and resubmit.
    """
    try:
        data = json.loads(args.answers)
    except (ValueError, json.JSONDecodeError) as e:
        die(f"--answers must be valid JSON: {e}")
    if not isinstance(data, dict):
        die("--answers must be a JSON object, e.g. '{\"customer_id\": \"123-456-7890\", ...}'")

    errors: list[str] = []

    # Agents must ask every onboarding field in chat before submitting --answers.
    # Missing optional keys usually mean the agent skipped a user-facing question,
    # so fail fast instead of silently accepting defaults.
    required_answer_keys = {
        "customer_id",
        "account_name",
        "campaign_type",
        "primary_goal",
        "currency",
        "mcc_id",
        "oauth_client_json_path",
        "cac_ceiling",
        "bid_budget_change_pct",
        "bid_budget_cooldown_days",
    }
    missing_answer_keys = sorted(k for k in required_answer_keys if k not in data)
    submitted_mcc_id = str(data.get("mcc_id", "")).strip()
    if submitted_mcc_id and submitted_mcc_id.lower() != "skip" and "mcc_name" not in data:
        missing_answer_keys.append("mcc_name")
    if "developer_token" not in data and "skip_read_access" not in data:
        missing_answer_keys.append("developer_token or skip_read_access")
    if missing_answer_keys:
        die(
            "onboarding answers are incomplete — agents must ask every setup question before "
            "submitting --answers. Missing: " + ", ".join(missing_answer_keys)
        )

    # Customer ID (required)
    cid_raw = str(data.get("customer_id", "")).strip()
    cid = _normalize_customer_id(cid_raw)
    if not cid:
        errors.append("customer_id is required (format DDD-DDD-DDDD)")
    elif not _validate_customer_id(cid):
        errors.append(f"customer_id '{cid_raw}' is invalid — expected 10 digits / DDD-DDD-DDDD")
    elif any(a.get("google_ads_customer_id") == cid for a in existing):
        errors.append(f"customer_id {cid} is already registered — use switch-account instead")

    # Campaign type (required enum)
    valid_ct = {k for k, _ in CAMPAIGN_TYPES}
    campaign_type = str(data.get("campaign_type", "")).strip().lower()
    if not campaign_type:
        errors.append(f"campaign_type is required — one of {sorted(valid_ct)}")
    elif campaign_type not in valid_ct:
        errors.append(f"campaign_type '{data.get('campaign_type')}' is invalid — one of {sorted(valid_ct)}")

    # Primary goal (enum, app only)
    primary_goal = str(data.get("primary_goal", "in_app_conversions")).strip().lower()
    campaign_goal_type = "app_in_app_conversions"
    if campaign_type == "app":
        if primary_goal not in CAMPAIGN_GOAL_TYPES:
            errors.append(
                f"primary_goal '{data.get('primary_goal')}' is invalid — one of {sorted(CAMPAIGN_GOAL_TYPES)}"
            )
        else:
            campaign_goal_type = CAMPAIGN_GOAL_TYPES[primary_goal]["campaign_goal_type"]
    else:
        primary_goal = "in_app_conversions"

    # Currency (required, 3-letter)
    currency = str(data.get("currency", "")).strip().upper()
    if not currency:
        errors.append("currency is required (3-letter code, e.g. INR)")
    elif not (len(currency) == 3 and currency.isalpha()):
        errors.append(f"currency '{data.get('currency')}' is invalid — use a 3-letter code like INR or USD")

    # MCC (optional)
    mcc_id_raw = str(data.get("mcc_id", "")).strip()
    mcc_id = ""
    if mcc_id_raw and mcc_id_raw.lower() != "skip":
        mcc_id = _normalize_customer_id(mcc_id_raw)
        if not _validate_customer_id(mcc_id):
            errors.append(f"mcc_id '{mcc_id_raw}' is invalid — expected DDD-DDD-DDDD")
    mcc_name = str(data.get("mcc_name", "")).strip()

    # Optional numeric defaults
    def _int_field(key: str, default: int, cap: int | None = None) -> int:
        if key not in data or data.get(key) in ("", None):
            return default
        try:
            iv = int(data[key])
        except (TypeError, ValueError):
            errors.append(f"{key} must be a whole number")
            return default
        return min(iv, cap) if cap is not None else iv

    cac_ceiling = _int_field("cac_ceiling", 200)
    bid_budget_change_pct = _int_field("bid_budget_change_pct", 10, cap=20)
    bid_budget_cooldown_days = _int_field("bid_budget_cooldown_days", 14)

    account_name = str(data.get("account_name", "")).strip() or cid

    # Optional write credentials (OAuth client JSON path)
    write_creds_json_path = ""
    google_ads_write_config_path = ""
    oauth_path = str(data.get("oauth_client_json_path", "")).strip()
    if oauth_path.lower() == "skip":
        oauth_path = ""
    if oauth_path:
        if not Path(oauth_path).expanduser().exists():
            errors.append(f"oauth_client_json_path '{oauth_path}' not found on this machine")
        elif cid and _validate_customer_id(cid):
            write_creds_json_path = oauth_path
            google_ads_write_config_path = _default_write_config_path(cid)

    developer_token = str(data.get("developer_token", "")).strip()
    skip_read_access = bool(data.get("skip_read_access"))
    google_ads_read_config_path = (
        _default_read_config_path(cid) if developer_token and cid and _validate_customer_id(cid) else ""
    )

    if errors:
        die("onboarding answers have problems — fix these and resubmit:\n  - " + "\n  - ".join(errors))

    # Completeness gate: a real save with no developer token produces an account that can't fetch
    # any data ("data access not ready"). Block it unless the agent explicitly confirms — after
    # asking the user — that there's no token yet. Runs before any write, so a blocked save has no
    # side effects.
    token_missing = not developer_token and not skip_read_access
    if token_missing and not getattr(args, "dry_run", False):
        die(
            "no Google Ads developer token provided — Bob can't fetch any data without it. "
            "Ask the user for it (Google Ads > Admin > API Center) and resubmit with "
            '"developer_token". Only if the user says they don\'t have one yet, resubmit with '
            '"skip_read_access": true.'
        )

    profile: dict[str, Any] = {
        "google_ads_customer_id": cid,
        "account_name": account_name,
        "google_ads_mcc_id": mcc_id,
        "google_ads_mcc_name": mcc_name,
        "campaign_type": campaign_type,
        "primary_goal": primary_goal,
        "currency": currency,
        "campaign_goal_type": campaign_goal_type,
        "creative_lookback_days": _int_field("creative_lookback_days", 15),
        "google_ads_read_config_path": google_ads_read_config_path,
        "google_ads_write_config_path": google_ads_write_config_path,
        "creative_min_impressions": 50000,
        "cac_ceiling": cac_ceiling,
        "bid_budget_change_pct": bid_budget_change_pct,
        "bid_budget_cooldown_days": bid_budget_cooldown_days,
    }

    if getattr(args, "dry_run", False):
        print("\n  (dry run — validated, nothing saved)")
        _print_onboard_summary(profile)
        if token_missing:
            print(
                "\n  ⚠ No developer token — Bob WON'T be able to fetch any data after saving.\n"
                "    Ask the user for it (Google Ads > Admin > API Center) before the real run.\n"
                "    Only pass \"skip_read_access\": true if they genuinely don't have one yet."
            )
        return

    if developer_token:
        login_customer_id = (mcc_id or cid).replace("-", "")
        _write_garf_read_config(google_ads_read_config_path, developer_token, login_customer_id)

    _print_onboard_summary(profile)
    _finalize_onboard(profile, write_creds_json_path, existing)


def onboard(args: argparse.Namespace) -> None:
    # Pick a mode up front. A bare `onboard` must NOT present a drivable prompt loop: agents end up
    # relaying the live prompts through a terminal (which double-asks questions, or hangs), instead
    # of gathering answers in chat and submitting them once. With neither mode chosen, just print
    # guidance and exit — no prompts to drive, no setup side effects.
    if not getattr(args, "answers", None) and not getattr(args, "interactive", False):
        print(
            "\nTo set up a Google Ads account with Bob:\n\n"
            '  • In your AI assistant, just say "set me up" — Bob asks you the questions and does the rest.\n'
            "  • Prefer a hands-on terminal? Run:\n"
            "      python3 lib/datapull.py onboard --interactive\n"
            "  • Automation / agents: gather the answers in chat, then run:\n"
            "      python3 lib/datapull.py onboard --answers '{\"customer_id\":\"…\", …}'\n"
            "    (run  python3 lib/datapull.py onboard --help  for the full key list)\n"
        )
        return

    ensure_local_setup_for_onboarding()
    ACCOUNTS_DIR.mkdir(parents=True, exist_ok=True)
    existing = _load_accounts_registry()

    # Migrate legacy single-account profile.json into registry on first onboard run
    if not existing and PROFILE_PATH.exists():
        legacy = load_profile(required=False)
        cid = legacy.get("google_ads_customer_id", "")
        if cid:
            legacy_entry = {
                "google_ads_customer_id": cid,
                "account_name": legacy.get("account_name", cid),
                "campaign_type": legacy.get("campaign_type", "app"),
                "active": True,
            }
            existing = [legacy_entry]
            _save_accounts_registry(existing)
            # Also write per-account profile file
            acct_dir = ACCOUNTS_DIR / cid.replace("-", "")
            acct_dir.mkdir(parents=True, exist_ok=True)
            with (acct_dir / "profile.json").open("w") as f:
                json.dump(legacy, f, indent=2)
                f.write("\n")

    # Non-interactive path: the agent gathered answers in chat and submitted them as JSON.
    # This avoids driving the blocking input() prompts below, which deadlock when an agent
    # runs the script as a one-shot command.
    if getattr(args, "answers", None):
        _onboard_from_answers(args, existing)
        return

    if existing:
        active = next((a for a in existing if a.get("active")), None)
        active_name = active.get("account_name", active.get("google_ads_customer_id", "")) if active else ""
        n = len(existing)
        print(f"\nHey mate. You've already got {n} account{'s' if n != 1 else ''} set up (active: {active_name}).")
        print("Let's add another one.\n")
    else:
        print("\nHey mate. Let's get you set up.\n")

    # ── ACCOUNT ──────────────────────────────────────────────────────────────
    _print_section("Google Ads Account")
    while True:
        cid = _ob_prompt_help(
            "Customer ID (e.g. 123-456-7890)",
            "This tells Bob exactly which Google Ads account to analyze.",
            "Google Ads account selector or the top bar of the account.",
        )
        if not cid:
            print("  Customer ID is required.")
            continue
        if not _validate_customer_id(cid):
            print("  Format must be DDD-DDD-DDDD (e.g. 123-456-7890).")
            continue
        if any(a.get("google_ads_customer_id") == cid for a in existing):
            print(f"  {cid} is already registered. Use 'switch-account' to activate it.")
            continue
        break

    account_name = _ob_prompt_help(
        "Account name (e.g. Acme App, Brand iOS)",
        "This is just the local nickname Bob shows when you switch accounts.",
        "Use the brand, app, market, or any name your team recognizes.",
    )
    if not account_name:
        account_name = cid

    # ── MCC ──────────────────────────────────────────────────────────────────
    _print_section("MCC (Manager Account)")
    _ob_context(
        "Bob uses this only when your Google Ads access goes through a manager account.",
        "Google Ads manager account selector or top bar. Type 'skip' if you do not use one.",
    )
    while True:
        mcc_id = _ob_prompt("MCC ID (e.g. 123-456-7890) — type 'skip' to leave blank")
        if not mcc_id or mcc_id.lower() == "skip":
            mcc_id = ""
            break
        if not _validate_customer_id(mcc_id):
            print("  Format must be DDD-DDD-DDDD. Type 'skip' to leave blank.")
            continue
        break
    mcc_name = (
        _ob_prompt_help(
            "MCC name (e.g. Acme MCC)",
            "This is just Bob's local nickname for the manager account.",
            "Use the manager account name shown in Google Ads.",
        )
        if mcc_id
        else ""
    )

    # ── CAMPAIGN TYPE ─────────────────────────────────────────────────────────
    _print_section("Campaign Type")
    ct_key, ct_display = _ob_numbered(
        "What campaign type are you running?",
        CAMPAIGN_TYPES,
        default=1,
        why="This controls the analysis assumptions Bob uses for performance reads.",
        where="Look at the campaign type column in Google Ads, or choose App campaigns if this account promotes an app.",
    )
    campaign_type = ct_key

    # ── PRIMARY GOAL (App only) ───────────────────────────────────────────────
    primary_goal = "in_app_conversions"
    campaign_goal_type = "app_in_app_conversions"
    if campaign_type == "app":
        _print_section("Primary Goal")
        goal_options = [("installs", "Installs"), ("in_app_conversions", "In-app conversions")]
        goal_key, _ = _ob_numbered(
            "What's the primary goal?",
            goal_options,
            default=2,
            why="Bob uses this as the main conversion metric when judging wins, losses, CPA, and recommendations.",
            where="Use the outcome your team optimizes the App campaigns for in Google Ads.",
        )
        primary_goal = goal_key
        campaign_goal_type = CAMPAIGN_GOAL_TYPES[goal_key]["campaign_goal_type"]

    # ── CURRENCY ──────────────────────────────────────────────────────────────
    _print_section("Currency")
    currency_options_display = CURRENCY_OPTIONS + [("OTHER", "Other — I'll type it")]
    cur_key, _ = _ob_numbered(
        "Currency?",
        currency_options_display,
        default=1,
        why="Bob uses this for cost labels, CAC thresholds, and bid/budget recommendations.",
        where="Google Ads billing or account settings. This should match how your costs are reported.",
    )
    if cur_key == "OTHER":
        while True:
            cur_key = _ob_prompt_help(
                "Currency code (3 letters, e.g. SGD)",
                "Bob needs the 3-letter code so reports and thresholds display cleanly.",
                "Use the ISO currency code from your billing currency, like USD, INR, AUD, or SGD.",
            ).upper()
            if len(cur_key) == 3 and cur_key.isalpha():
                break
            print("  Enter a 3-letter currency code.")
    currency = cur_key

    # ── GOOGLE ADS READ CONFIG ────────────────────────────────────────────────
    _print_section("Google Ads Reporting Access")
    google_ads_read_config_path = ""
    while True:
        has_token = _ob_prompt_help(
            "Do you have your Google Ads developer token? (y/n)",
            "This gives Bob read-only reporting access so he can pull performance data.",
            "Google Ads > Admin > API Center. Ask your Google Ads admin if you cannot see it.",
            "y",
        ).lower()
        if has_token not in {"y", "yes", "n", "no"}:
            print("  Reply y or n.")
            continue
        if has_token in {"n", "no"}:
            print("  No dramas. Setup can continue, but I won't be able to fetch Google Ads data until you add the developer token.")
            break
        developer_token = _ob_prompt_help(
            "Developer token",
            "Bob stores this locally and uses it only for Google Ads reporting pulls.",
            "Copy it from Google Ads > Admin > API Center.",
        )
        if not developer_token:
            print("  Developer token is required to set up reporting data pulls. Reply n to skip for now.")
            continue
        google_ads_read_config_path = _default_read_config_path(cid)
        login_customer_id = (mcc_id or cid).replace("-", "")
        config_path = Path(google_ads_read_config_path).expanduser()
        if config_path.exists():
            replace = _ob_prompt_help(
                "I found existing reporting access settings for this account. Replace them? (y/n)",
                "Replacing is only needed if the old token or manager account is wrong.",
                "Choose n if this account already fetched data correctly before.",
                "n",
            ).lower()
            if replace not in {"y", "yes"}:
                print("  Keeping the existing reporting access settings.")
                break
        _write_garf_read_config(google_ads_read_config_path, developer_token, login_customer_id)
        print("  Reporting access settings saved.")
        break

    # ── GOOGLE ADS WRITE CONFIG ───────────────────────────────────────────────
    _print_section("Google Ads Write Access (optional)")
    google_ads_write_config_path = ""
    write_creds_json_path = ""
    while True:
        has_api_json = _ob_prompt_help(
            "Optional: do you have the Google Cloud OAuth client JSON for live changes? (y/n)",
            "This is only for approved write-backs like bid, budget, or creative changes.",
            "Google Cloud Console > APIs & Services > Credentials > OAuth 2.0 Client IDs > Download JSON.",
            "n",
        ).lower()
        if has_api_json not in {"y", "yes", "n", "no"}:
            print("  Reply y or n.")
            continue
        if has_api_json in {"n", "no"}:
            print("  No dramas. Bob can still save bid, budget, and creative recommendations to the wiki for you to apply manually in Google Ads.")
            break
        print("  Download it from Google Cloud Console → OAuth 2.0 Client IDs → Download JSON.")
        print("  Save it somewhere on this machine, then paste the full path here.")
        raw_creds = _ob_prompt_help(
            "Path to OAuth client JSON",
            "Bob needs the local file path once so he can create write-access credentials.",
            "Paste the full path to the JSON file you downloaded.",
            "~/google-ads-creds.json",
        )
        creds_path = Path(raw_creds).expanduser()
        if not creds_path.exists():
            print("  I can't find that JSON file. Check where you saved it, or reply n to skip for now.")
            continue
        google_ads_write_config_path = _default_write_config_path(cid)
        write_creds_json_path = raw_creds
        print("  Got it — I'll turn that JSON into write access settings after saving the account.")
        break

    # ── OPTIONAL DEFAULTS ─────────────────────────────────────────────────────
    _print_section("Optional Defaults")
    cac_raw = _ob_prompt_help(
        f"CAC ceiling ({currency})",
        "Bob uses this as a guardrail before recommending bid or budget increases.",
        "Use your maximum acceptable cost per primary conversion. If unsure, use the default.",
        "200",
    )
    cac_ceiling = int(cac_raw) if cac_raw.isdigit() else 200
    pct_raw = _ob_prompt_help(
        "Max bid/budget change %",
        "This caps how aggressive Bob can be in recommendation plans.",
        "Use your team's normal weekly change limit. If unsure, use the default.",
        "10",
    )
    bid_budget_change_pct = min(int(pct_raw) if pct_raw.isdigit() else 10, 20)
    cd_raw = _ob_prompt_help(
        "Cooldown days between changes",
        "Bob avoids changing the same campaign again before this many days pass.",
        "Use your team's learning-window rule. If unsure, use the default.",
        "14",
    )
    bid_budget_cooldown_days = int(cd_raw) if cd_raw.isdigit() else 14
    creative_min_impressions = 50000

    # ── CONFIRM ────────────────────────────────────────────────────────────────
    profile: dict[str, Any] = {
        "google_ads_customer_id": cid,
        "account_name": account_name,
        "google_ads_mcc_id": mcc_id,
        "google_ads_mcc_name": mcc_name,
        "campaign_type": campaign_type,
        "primary_goal": primary_goal,
        "currency": currency,
        "campaign_goal_type": campaign_goal_type,
        "google_ads_read_config_path": google_ads_read_config_path,
        "google_ads_write_config_path": google_ads_write_config_path,
        "creative_min_impressions": creative_min_impressions,
        "cac_ceiling": cac_ceiling,
        "bid_budget_change_pct": bid_budget_change_pct,
        "bid_budget_cooldown_days": bid_budget_cooldown_days,
    }

    _print_onboard_summary(profile)

    confirm = _ob_prompt_help(
        "\n  Save this? (y/n)",
        "Bob needs your confirmation before saving this account setup locally.",
        "Review the summary above. Type y to save or n to stop.",
        "y",
    )
    if confirm.lower() != "y":
        print("No worries. Nothing saved.")
        return

    _finalize_onboard(profile, write_creds_json_path, existing)


def _resolve_account_target(accounts: list[dict], target: str) -> int:
    """Resolve a positional target to an index into `accounts`.

    Order: (1) exact Customer ID match, hyphens optional; (2) unique
    case-insensitive substring of account_name. Raises SystemExit on no match
    or ambiguous name match.
    """
    target_clean = target.strip()
    target_digits = target_clean.replace("-", "")
    for i, a in enumerate(accounts):
        cid = a.get("google_ads_customer_id", "")
        if cid == target_clean or cid.replace("-", "") == target_digits:
            return i
    needle = target_clean.lower()
    name_hits = [
        i for i, a in enumerate(accounts)
        if needle in a.get("account_name", "").lower()
    ]
    if len(name_hits) == 1:
        return name_hits[0]
    if len(name_hits) > 1:
        names = ", ".join(accounts[i].get("account_name", "") for i in name_hits)
        die(f"'{target}' matches multiple accounts: {names}. Use the Customer ID instead.")
    die(f"no account matches '{target}'. Run 'list-accounts' to see registered accounts.")


def switch_account(args: argparse.Namespace) -> None:
    accounts = _load_accounts_registry()
    if not accounts:
        print("No accounts registered. Run: python3 lib/datapull.py onboard")
        return

    target = getattr(args, "target", None) or getattr(args, "account_id", None)
    if target:
        choice_idx = _resolve_account_target(accounts, target)
    else:
        print("\nRegistered accounts:\n")
        for i, a in enumerate(accounts, 1):
            marker = "[ACTIVE]" if a.get("active") else "       "
            cid = a.get("google_ads_customer_id", "")
            name = a.get("account_name", cid)
            ctype = a.get("campaign_type", "")
            print(f"  {i}) {marker}  {name} — {cid}  ({ctype})")
        raw = _ob_prompt("\nSwitch to (number)")
        if not raw.isdigit() or not (1 <= int(raw) <= len(accounts)):
            print("No change.")
            return
        choice_idx = int(raw) - 1

    chosen = accounts[choice_idx]
    cid = chosen.get("google_ads_customer_id", "")
    acct_profile_path = ACCOUNTS_DIR / cid.replace("-", "") / "profile.json"
    if not acct_profile_path.exists():
        die(f"account profile not found: {acct_profile_path}. Re-run 'onboard' for this account.")

    updated = [dict(a, active=(i == choice_idx)) for i, a in enumerate(accounts)]
    _save_accounts_registry(updated)

    name = chosen.get("account_name", cid)
    print(f"\nSwitched to {name} ({cid}).")
    print(f"  Data:  {account_processed_dir(cid, 'account-network').parent}")
    print(f"  Wiki:  {account_wiki_dir(cid)}")


def repair_setup(args: argparse.Namespace) -> None:
    """Reinstall project dependencies and recheck local readiness.

    Agent-facing entry triggered by user phrases like "fix setup", "rerun setup",
    or "setup failed". No account prompts — strictly a dependency repair path.
    """
    print("\n  Reinstalling Bob's local tools...")
    try:
        _install_project_requirements()
    except subprocess.CalledProcessError:
        pass

    issues = _onboarding_runtime_issues(require_read=True, require_write=False)
    if not issues:
        print("  Setup looks good.")
        return

    print("  First install didn't take. Trying once more with verbose output...")
    _install_with_log(STATE_ROOT / "logs" / "setup.log")
    issues = _onboarding_runtime_issues(require_read=True, require_write=False)
    if not issues:
        print("  Setup looks good.")
        return

    print("\n  Still not right:")
    for issue in issues:
        print(f"  - {issue}")
    print(f"\n  Full install log: {STATE_ROOT / 'logs' / 'setup.log'}")


def list_accounts(args: argparse.Namespace) -> None:
    accounts = _load_accounts_registry()
    if not accounts:
        print("No accounts registered. Run: python3 lib/datapull.py onboard")
        return

    print(f"\n{'#':<3}  {'Status':<8}  {'Account':<28}  {'Customer ID':<14}  {'Type'}")
    print("  " + "─" * 70)
    for i, a in enumerate(accounts, 1):
        marker = "[ACTIVE]" if a.get("active") else "       "
        cid = a.get("google_ads_customer_id", "")
        name = a.get("account_name", cid)[:26]
        ctype = a.get("campaign_type", "")
        print(f"  {i:<3}  {marker}  {name:<28}  {cid:<14}  {ctype}")
    print()

__all__ = [name for name in globals() if not name.startswith("__")]
