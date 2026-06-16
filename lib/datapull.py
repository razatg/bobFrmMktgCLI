#!/usr/bin/env python3
"""Data pull commands for Bob Frm Mktg."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import importlib.metadata as importlib_metadata
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BOB_DIR = ROOT / ".bob"
PROFILE_PATH = BOB_DIR / "profile.json"
ACCOUNTS_DIR = BOB_DIR / "accounts"
ACCOUNTS_REGISTRY = BOB_DIR / "accounts.json"
VENV_DIR = ROOT / ".venv"
QUERIES_DIR = ROOT / "garf" / "queries"
RAW_DIR = ROOT / "garf" / "outputs" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"
REPORTS_DIR = ROOT / "validation" / "reports"
PULL_LOG_PATH = ROOT / "logs" / "pull-log.jsonl"
SIGNAL_LOG_PATH = ROOT / "logs" / "session-signals.jsonl"
SELF_IMPROVE_DIR = ROOT / "wiki" / "_self-improve"

# Team sync (./bob sync): wiki + self-improve signals shared with teammates via a plain shared
# folder (e.g. a synced Dropbox folder) — NEVER the public GitHub origin. No git involved: the
# append-only signal log and Index.md bullet lists are unioned, other wiki files are copied
# newer-wins (older kept as .bak). Both stay gitignored in the main repo. See `bob sync --help`.
SYNC_CONFIG_PATH = BOB_DIR / "sync.json"

DEFAULT_BOOTSTRAP = [
    {"query": "account_network_period", "period": "yesterday_vs_sdlw"},
    {"query": "account_network_period", "period": "wow"},
    {"query": "account_network_period", "period": "mom"},
    {"query": "account_network_period", "period": "mtd"},
    {"query": "campaign_network_period", "period": "yesterday_vs_sdlw"},
    {"query": "campaign_network_period", "period": "3week_rolling"},
    {"query": "creative_period",         "days": 30},
    {"query": "change_history",          "days": 14},
    {"query": "bid_budget_inputs",       "days": 7},
]

DATE_QUERIES = {
    "campaign_daily",
    "campaign_reach_daily",
    "network_daily",
    "creative_asset_daily",
    "conversion_action_daily",
    "bid_budget_inputs",
    "creative_conversion_action_daily",
    "account_network_period",
    "campaign_network_period",
    "adgroup_network_period",
    "creative_period",
}

DEFAULT_CREATIVE_MIN_IMPRESSIONS = 50000
STATIC_BANNER_REFRESH_DAYS = 90

STATIC_BANNER_SPECS: dict[str, dict[str, Any]] = {
    "horizontal": {
        "ratio": "1.91:1",
        "recommended_size": "1200 x 628",
        "minimum_size": "600 x 314",
        "max_images": 20,
    },
    "vertical": {
        "ratio": "4:5",
        "recommended_size": "1200 x 1500",
        "minimum_size": "320 x 400",
        "max_images": 20,
    },
    "square": {
        "ratio": "1:1",
        "recommended_size": "1200 x 1200",
        "minimum_size": "200 x 200",
        "max_images": 20,
    },
}

STATIC_IMAGE_FIELD_RATIOS: dict[str, str] = {
    "MARKETING_IMAGE": "horizontal",
    "PORTRAIT_MARKETING_IMAGE": "vertical",
    "SQUARE_MARKETING_IMAGE": "square",
    "AD_IMAGE": "unknown",
}

# Reach is optional: most grains don't have a safe/deduped reach metric, and treating it
# as a summed metric can silently turn "missing" into 0.
SUM_METRICS = ["impressions", "clicks", "cost", "installs", "in_app_conversions"]

ACCOUNT_DAILY_COLUMNS = [
    "date",
    "impressions",
    "clicks",
    "cost",
    "installs",
    "in_app_conversions",
    "ctr_percent",
    "cpc",
    "cti_percent",
    "conversion_rate_percent",
]

_METRIC_COLS = [
    "reach", "impressions", "clicks", "cost", "installs", "in_app_conversions",
    "goal_conversions", "cpm", "frequency", "ctr_percent", "cpc", "cti_percent",
    "conversion_rate_percent", "cpa", "cpi",
]

ACCOUNT_NETWORK_PERIOD_COLUMNS = ["customer_id", "customer_name", "network"] + _METRIC_COLS
CAMPAIGN_NETWORK_PERIOD_COLUMNS = [
    "customer_id", "campaign_id", "campaign_name", "campaign_status", "network",
] + _METRIC_COLS
CAMPAIGN_REACH_PERIOD_COLUMNS = [
    "customer_id", "campaign_id", "campaign_name", "campaign_status",
] + _METRIC_COLS
ADGROUP_NETWORK_PERIOD_COLUMNS = [
    "customer_id", "campaign_id", "campaign_name",
    "ad_group_id", "ad_group_name", "ad_group_status", "network",
] + _METRIC_COLS

CREATIVE_PERIOD_COLUMNS = [
    "customer_id", "campaign_id", "campaign_name",
    "ad_group_id", "ad_group_name",
    "asset_view_resource_name", "asset_resource_name",
    "asset_id", "asset_name", "asset_type", "field_type", "performance_label",
    "image_url", "image_width", "image_height", "mime_type", "file_size_bytes",
] + _METRIC_COLS

def _weekly_trend_columns(iso_weeks: list[int]) -> list[str]:
    """Generate campaign_weekly_trend column list for specific ISO week numbers."""
    cols = ["customer_id", "campaign_id", "campaign_name", "campaign_status",
            "current_iso_week", "prior1_iso_week", "prior2_iso_week"]
    for w in iso_weeks:
        cols += [
            f"w{w}_start", f"w{w}_end",
            f"w{w}_impressions", f"w{w}_clicks", f"w{w}_cost",
            f"w{w}_installs", f"w{w}_in_app_conversions",
            f"w{w}_cpm", f"w{w}_ctr_percent", f"w{w}_cpc",
            f"w{w}_cti_percent", f"w{w}_conversion_rate_percent",
        ]
    return cols + ["trend_direction", "signal_strength"]

BID_BUDGET_REC_COLUMNS = [
    "customer_id", "campaign_id", "campaign_name", "campaign_status",
    "current_iso_week", "w0_cpi", "ref_cpi", "cpi_pct_vs_ref",
    "w0_cpm", "ref_cpm", "cpm_pct_vs_ref",
    "w0_cpa", "cac_ceiling", "cac_guard_passed",
    "w0_installs", "min_installs_met",
    "last_bid_budget_change_date", "days_since_last_change", "cooldown_days", "cooldown_ok",
    "budget_utilization_pct", "budget_constrained",
    "w0_conv_rate_pct", "w1_conv_rate_pct", "conv_rate_declining",
    "action", "rationale", "forecast",
    "current_target_cpa", "proposed_target_cpa",
    "current_daily_budget", "proposed_daily_budget",
    "campaign_budget_id",
]

_COMPARISON_VOLUME_METRICS = ["reach", "impressions", "clicks", "cost", "installs", "in_app_conversions", "goal_conversions"]
_COMPARISON_RATIO_METRICS = ["cpm", "frequency", "ctr_percent", "cpc", "cti_percent", "conversion_rate_percent", "cpa", "cpi"]

def _comparison_cols(id_cols: list[str]) -> list[str]:
    cols = list(id_cols)
    for m in _COMPARISON_VOLUME_METRICS:
        cols += [f"current_{m}", f"baseline_{m}", f"delta_{m}_pct"]
    for m in _COMPARISON_RATIO_METRICS:
        cols += [f"current_{m}", f"baseline_{m}"]
    return cols

CAMPAIGN_SLICE_COMPARISON_COLUMNS = _comparison_cols(["campaign_id", "campaign_name", "campaign_status"])
ACCOUNT_WEEK_COMPARISON_COLUMNS   = _comparison_cols(["network"])
CAMPAIGN_WEEK_COMPARISON_COLUMNS  = _comparison_cols(["campaign_id", "campaign_name", "campaign_status"])

DEFAULT_TOLERANCES = {
    "impressions": ("relative", 0.01),
    "clicks": ("relative", 0.01),
    "cost": ("relative", 0.1),
    "installs": ("relative", 0.1),
    "in_app_conversions": ("relative", 0.1),
    "ctr_percent": ("absolute", 0.1),
    "cpc": ("relative", 0.1),
    "cti_percent": ("absolute", 0.1),
    "conversion_rate_percent": ("absolute", 0.1),
}

NETWORK_DISPLAY_NAMES: dict[str, str] = {
    "0": "Unspecified", "1": "Unknown",
    "2": "Google Search", "3": "Search partners",
    "4": "Google Display Network", "5": "YouTube Search",
    "6": "YouTube",     "7": "Mixed",     "8": "YouTube",
    "9": "Google TV",   "10": "Google Owned Channels",
    "11": "Gmail",      "12": "Discover",  "13": "Maps",
    # Text values from raw files and newer Google Ads API enum names
    "UNSPECIFIED": "Unspecified", "UNKNOWN": "Unknown",
    "SEARCH": "Google Search", "SEARCH_PARTNERS": "Search partners",
    "CONTENT": "Google Display Network", "YOUTUBE_SEARCH": "YouTube Search",
    "YOUTUBE_WATCH": "YouTube", "MIXED": "Mixed",
    "YOUTUBE": "YouTube",
    "GOOGLE_TV": "Google TV", "GOOGLE_OWNED_CHANNELS": "Google Owned Channels",
    "GMAIL": "Gmail", "DISCOVER": "Discover", "MAPS": "Maps",
    # Already-canonical historical labels
    "Search": "Google Search", "Search Partners": "Search partners",
    "Display": "Google Display Network", "Play": "YouTube",
}

def _canonical_network(value: Any) -> str:
    """Return a stable display key for Google Ads network enum values."""
    text = str(value).strip()
    return NETWORK_DISPLAY_NAMES.get(text, NETWORK_DISPLAY_NAMES.get(text.upper(), text))


def _display_network(code: str) -> str:
    return _canonical_network(code)


_NETWORK_PERIOD_KEY_COLS: dict[str, list[str]] = {
    "account_network_period": ["customer_id", "customer_name", "network"],
    "campaign_network_period": [
        "customer_id", "campaign_id", "campaign_name", "campaign_status", "network",
    ],
    "campaign_reach_period": [
        "customer_id", "campaign_id", "campaign_name", "campaign_status",
    ],
    "adgroup_network_period": [
        "customer_id", "campaign_id", "campaign_name",
        "ad_group_id", "ad_group_name", "ad_group_status", "network",
    ],
}

_NETWORK_PERIOD_COLUMNS: dict[str, list[str]] = {
    "account_network_period": ACCOUNT_NETWORK_PERIOD_COLUMNS,
    "campaign_network_period": CAMPAIGN_NETWORK_PERIOD_COLUMNS,
    "campaign_reach_period": CAMPAIGN_REACH_PERIOD_COLUMNS,
    "adgroup_network_period": ADGROUP_NETWORK_PERIOD_COLUMNS,
}

_NETWORK_PERIOD_SUBDIR: dict[str, str] = {
    "account_network_period": "account-network",
    "campaign_network_period": "campaign-network",
    "campaign_reach_period": "campaign-reach",
    "adgroup_network_period": "adgroup-network",
}


def die(message: str, code: int = 1) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(code)


def today() -> dt.date:
    override = os.getenv("BOB_TODAY")
    if override:
        return dt.date.fromisoformat(override)
    return dt.date.today()


def load_profile(required: bool = True) -> dict[str, Any]:
    """Load the active account profile from .bob/accounts/{id}/profile.json via accounts.json."""
    accounts = _load_accounts_registry()
    active = next((a for a in accounts if a.get("active")), None)
    if not active:
        if required:
            die("No active account found. Run: python3 lib/datapull.py onboard")
        return {}
    cid = str(active.get("google_ads_customer_id", "")).replace("-", "")
    acct_profile = ACCOUNTS_DIR / cid / "profile.json"
    if not acct_profile.exists():
        if required:
            die(f"Account profile missing: {acct_profile}. Run: python3 lib/datapull.py onboard")
        return {}
    with acct_profile.open() as f:
        return json.load(f)


def account_processed_dir(customer_id: str, subdir: str) -> Path:
    """data/processed/{customer_id}/{subdir}/ — per-account data store."""
    return PROCESSED_DIR / customer_id.replace("-", "") / subdir


def account_wiki_dir(customer_id: str) -> Path:
    """wiki/{customer_id}/ — per-account wiki store."""
    return ROOT / "wiki" / customer_id.replace("-", "")


def _resolve_processed_dir(subdir: str, customer_id: str | None) -> Path:
    """Return per-account dir if it exists, else fall back to legacy flat dir."""
    if customer_id:
        scoped = account_processed_dir(customer_id, subdir)
        if scoped.exists():
            return scoped
    return PROCESSED_DIR / subdir


def _load_accounts_registry() -> list[dict]:
    if not ACCOUNTS_REGISTRY.exists():
        return []
    with ACCOUNTS_REGISTRY.open() as f:
        return json.load(f)


def _save_accounts_registry(accounts: list[dict]) -> None:
    BOB_DIR.mkdir(parents=True, exist_ok=True)
    with ACCOUNTS_REGISTRY.open("w") as f:
        json.dump(accounts, f, indent=2)
        f.write("\n")


def _set_active_account(profile: dict) -> None:
    """Write profile to the per-account file. accounts.json active flag is the source of truth."""
    cid = str(profile.get("google_ads_customer_id", "")).replace("-", "")
    if cid:
        acct_dir = ACCOUNTS_DIR / cid
        acct_dir.mkdir(parents=True, exist_ok=True)
        with (acct_dir / "profile.json").open("w") as f:
            json.dump(profile, f, indent=2)
            f.write("\n")


def _profile_read_config_value(profile: dict[str, Any]) -> str:
    return str(profile.get("google_ads_read_config_path", "") or "").strip()


def _set_profile_read_config_value(profile: dict[str, Any], value: str) -> None:
    profile["google_ads_read_config_path"] = value


def parse_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    return dt.date.fromisoformat(value)


def resolve_range(args: argparse.Namespace) -> tuple[dt.date, dt.date]:
    end = parse_date(args.to) or (today() - dt.timedelta(days=1))
    if args.from_date:
        start = parse_date(args.from_date)
    else:
        days = int(args.days or 30)
        start = end - dt.timedelta(days=days - 1)
    if start is None:
        die("could not resolve start date")
    if start > end:
        die(f"start date {start} is after end date {end}")
    return start, end


def resolve_period_dates(period: str) -> list[tuple[dt.date, dt.date]]:
    """Return [(start, end), ...] for each fetch window in the named period pattern."""
    yesterday = today() - dt.timedelta(days=1)
    if period == "yesterday_vs_sdlw":
        sdlw = yesterday - dt.timedelta(days=7)
        return [(yesterday, yesterday), (sdlw, sdlw)]
    if period == "wow":
        return [
            (yesterday - dt.timedelta(days=6), yesterday),
            (yesterday - dt.timedelta(days=13), yesterday - dt.timedelta(days=7)),
        ]
    if period == "mom":
        return [
            (yesterday - dt.timedelta(days=29), yesterday),
            (yesterday - dt.timedelta(days=59), yesterday - dt.timedelta(days=30)),
        ]
    if period == "3week_rolling":
        return [
            (yesterday - dt.timedelta(days=6),  yesterday),
            (yesterday - dt.timedelta(days=13), yesterday - dt.timedelta(days=7)),
            (yesterday - dt.timedelta(days=20), yesterday - dt.timedelta(days=14)),
        ]
    if period == "mtd":
        # Current: 1st of this month → yesterday
        # Prior:   1st of prior month → same day-of-month last month
        a_start = yesterday.replace(day=1)
        a_end = yesterday
        b_start = (a_start - dt.timedelta(days=1)).replace(day=1)
        try:
            b_end = b_start.replace(day=a_end.day)
        except ValueError:
            # Prior month is shorter (e.g. Feb when today is Mar 31)
            import calendar as _cal
            b_end = b_start.replace(day=_cal.monthrange(b_start.year, b_start.month)[1])
        return [(a_start, a_end), (b_start, b_end)]
    m = re.match(r"^partial_wow_(\d+)$", period)
    if m:
        n = max(1, int(m.group(1)))
        yesterday = today() - dt.timedelta(days=1)
        monday_cur = today() - dt.timedelta(days=today().weekday())
        cur_start = monday_cur
        cur_end = min(monday_cur + dt.timedelta(days=n - 1), yesterday)
        monday_base = monday_cur - dt.timedelta(days=7)
        return [(cur_start, cur_end), (monday_base, monday_base + dt.timedelta(days=n - 1))]
    die(f"unknown period name: {period}")


def iso_week_to_dates(week: int, year: int) -> tuple[dt.date, dt.date]:
    """Return (monday, sunday) for the given ISO week and year."""
    try:
        monday = dt.date.fromisocalendar(year, week, 1)
    except ValueError:
        die(f"ISO week {week} does not exist in year {year}")
    return monday, monday + dt.timedelta(days=6)


def last_complete_iso_week(reference: dt.date) -> tuple[int, int]:
    """Return (week, year) for the most recently completed ISO week ending before reference."""
    last_sunday = reference - dt.timedelta(days=reference.isoweekday())
    cal = last_sunday.isocalendar()
    return cal.week, cal.year


def cmd_resolve_dates(args: argparse.Namespace) -> None:
    """Print concrete date ranges for a named period so the agent can construct fetch commands."""
    import calendar as _cal
    period = args.period.replace("-", "_")
    if period == "partial_wow":
        n = args.n if args.n else 3
        period = f"partial_wow_{n}"

    windows = resolve_period_dates(period)
    labels = ["current", "baseline", "prior-2"]
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    print(f"\nPeriod: {args.period}" + (f"  (first {args.n} days of week vs prior week)" if "partial_wow" in period else ""))
    print(f"  {'':12}  {'from':12}  {'to':12}  label")
    print(f"  {'':12}  {'────────────':12}  {'────────────':12}  ─────────────────────")
    for i, (start, end) in enumerate(windows):
        label = labels[i] if i < len(labels) else f"window-{i}"
        iso_w = start.isocalendar()
        week_label = f"W{iso_w.week} ({day_names[start.weekday()]} {start.day} {_cal.month_abbr[start.month]}–{day_names[end.weekday()]} {end.day} {_cal.month_abbr[end.month]})"
        print(f"  {label:<12}  {str(start):12}  {str(end):12}  {week_label}")
    print()


def run_id() -> str:
    return dt.datetime.now().strftime("%Y%m%dT%H%M%S")


def render_query(query_name: str, start: dt.date, end: dt.date) -> str:
    query_file = QUERIES_DIR / f"{query_name}.sql"
    if not query_file.exists():
        die(f"query file not found: {query_file}")
    text = query_file.read_text()
    yesterday = today() - dt.timedelta(days=1)
    sdlw = yesterday - dt.timedelta(days=7)
    return text.format(
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        period_start=start.isoformat(),
        period_end=end.isoformat(),
        yesterday=yesterday.isoformat(),
        sdlw=sdlw.isoformat(),
    )


def ensure_dirs() -> None:
    for path in [RAW_DIR, PROCESSED_DIR, REPORTS_DIR, ACCOUNTS_DIR]:
        path.mkdir(parents=True, exist_ok=True)


def _venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python3"


def _write_bob_launcher() -> None:
    launcher = ROOT / "bob"
    launcher.write_text(
        "#!/bin/bash\n"
        "# bob - launcher that prefers Bob's local environment, then a bundled runtime.\n"
        "set -e\n"
        "\n"
        'DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'
        "\n"
        "find_python() {\n"
        '    if [ -x "$DIR/.venv/bin/python3" ]; then\n'
        '        printf \'%s\\n\' "$DIR/.venv/bin/python3"\n'
        "        return 0\n"
        "    fi\n"
        '    if [ -x "$DIR/.venv/Scripts/python.exe" ]; then\n'
        '        printf \'%s\\n\' "$DIR/.venv/Scripts/python.exe"\n'
        "        return 0\n"
        "    fi\n"
        "\n"
        "    for candidate in \\\n"
        '        "$DIR/runtime/python/bin/python3" \\\n'
        '        "$DIR/runtime/python/bin/python" \\\n'
        '        "$DIR/runtime/python/python.exe" \\\n'
        '        "$DIR/runtime/python/Scripts/python.exe" \\\n'
        '        "$DIR/.runtime/python/bin/python3" \\\n'
        '        "$DIR/.runtime/python/bin/python" \\\n'
        '        "$DIR/.runtime/python/python.exe" \\\n'
        '        "$DIR/.runtime/python/Scripts/python.exe"\n'
        "    do\n"
        '        if [ -x "$candidate" ]; then\n'
        '            printf \'%s\\n\' "$candidate"\n'
        "            return 0\n"
        "        fi\n"
        "    done\n"
        "\n"
        "    if command -v python3 >/dev/null 2>&1; then\n"
        "        command -v python3\n"
        "        return 0\n"
        "    fi\n"
        "\n"
        "    return 1\n"
        "}\n"
        "\n"
        'PYTHON="$(find_python || true)"\n'
        'if [ -z "$PYTHON" ]; then\n'
        "    cat <<'EOF'\n"
        "Bob can't start because this folder does not include a Python runtime.\n"
        "\n"
        "Use the full Bob release package for your computer, then open that folder in your AI app and say: set me up\n"
        "EOF\n"
        "    exit 1\n"
        "fi\n"
        "\n"
        'exec "$PYTHON" "$DIR/lib/datapull.py" "$@"\n'
    )
    launcher.chmod(0o755)


def _install_project_requirements() -> None:
    if not VENV_DIR.exists():
        print("  Creating Bob's local Python environment...")
        subprocess.check_call([sys.executable, "-m", "venv", str(VENV_DIR)], cwd=ROOT)

    venv_python = _venv_python()
    pip_cmd = [str(venv_python), "-m", "pip"]
    print("  Installing what Bob needs...")
    subprocess.check_call(pip_cmd + ["install", "--quiet", "--upgrade", "pip"], cwd=ROOT)
    subprocess.check_call(pip_cmd + ["install", "--quiet", "-r", str(ROOT / "requirements.txt")], cwd=ROOT)
    _write_bob_launcher()


def ensure_local_setup_for_onboarding() -> None:
    """Prepare the local Python environment before asking account questions."""
    if os.environ.get("BOB_ONBOARD_SETUP_DONE") == "1":
        return

    print("\nGetting Bob ready on this machine...")
    _install_project_requirements()
    print("  Bob is ready.\n")

    venv_python = _venv_python()
    try:
        current_python = Path(sys.executable).resolve()
        target_python = venv_python.resolve()
    except OSError:
        current_python = Path(sys.executable)
        target_python = venv_python
    if current_python != target_python and venv_python.exists():
        env = os.environ.copy()
        env["BOB_ONBOARD_SETUP_DONE"] = "1"
        os.execve(str(venv_python), [str(venv_python), str(Path(__file__).resolve()), "onboard"], env)


def _missing_distributions(distribution_names: list[str]) -> list[str]:
    missing: list[str] = []
    for name in distribution_names:
        try:
            importlib_metadata.version(name)
        except importlib_metadata.PackageNotFoundError:
            missing.append(name)
    return missing


def _project_venv_bin() -> Path:
    return ROOT / ".venv" / ("Scripts" if os.name == "nt" else "bin")


def _project_venv_garf() -> Path:
    return _project_venv_bin() / ("garf.exe" if os.name == "nt" else "garf")


def _garf_executable_exists() -> bool:
    """True if garf is callable from the project's venv or system PATH.

    Anchored to the project venv first so the check works regardless of which
    Python interpreter ran this script (system python vs. the launcher).
    """
    return _project_venv_garf().exists() or shutil.which("garf") is not None


def _onboarding_runtime_issues(require_read: bool, require_write: bool) -> list[str]:
    """Return local dependency issues that would block immediate post-onboarding use.

    Checks are anchored to the project venv. If the venv exists, dependency
    presence is inferred from the canonical install artefacts (garf binary)
    rather than from the running interpreter's site-packages — this avoids
    false negatives when onboarding is invoked via system python.
    """
    issues: list[str] = []
    venv_present = _project_venv_bin().parent.exists()

    if require_read:
        if not venv_present:
            missing = _missing_distributions(["garf-executors", "garf-google-ads", "pyyaml"])
            if missing:
                issues.append("the reporting tools aren't installed yet")
        if not _garf_executable_exists():
            issues.append("the Google Ads data tool isn't installed yet")

    if require_write:
        if not venv_present:
            missing = _missing_distributions(["google-ads", "google-auth-oauthlib", "pyyaml"])
            if missing:
                issues.append("the live-changes tools aren't installed yet")

    return sorted(set(issues))


def _install_with_log(log_path: Path) -> bool:
    """Run _install_project_requirements with verbose output captured to log_path.

    Returns True on success, False on failure. Used as the second-attempt retry.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    venv_python = _venv_python()
    pip_cmd = [str(venv_python), "-m", "pip", "install", "-v", "-r", str(ROOT / "requirements.txt")]
    try:
        with open(log_path, "w") as logf:
            subprocess.check_call(pip_cmd, cwd=ROOT, stdout=logf, stderr=subprocess.STDOUT)
        return True
    except subprocess.CalledProcessError:
        return False
    except FileNotFoundError:
        return False


def _repair_and_check_onboarding_runtime(require_read: bool, require_write: bool) -> list[str]:
    issues = _onboarding_runtime_issues(require_read, require_write)
    if not issues:
        return []

    print("\n  Bob saved the account. Checking local setup before I call it ready...")
    try:
        _install_project_requirements()
    except subprocess.CalledProcessError:
        pass

    issues = _onboarding_runtime_issues(require_read, require_write)
    if not issues:
        return []

    # Second attempt: verbose install with output captured for diagnosis.
    print("  First install didn't take. Trying once more...")
    _install_with_log(ROOT / "logs" / "setup.log")
    return _onboarding_runtime_issues(require_read, require_write)


def garf_command(query_path: Path, output_dir: Path, account: str, config: str | None) -> list[str]:
    garf_exe = shutil.which("garf")
    if not garf_exe:
        candidate = Path(sys.executable).parent / "garf"
        if candidate.exists():
            garf_exe = str(candidate)
    if not garf_exe:
        garf_exe = "garf"
    cmd = [
        garf_exe,
        str(query_path),
        "--source",
        "google-ads",
        "--output",
        "csv",
        f"--csv.destination-folder={output_dir}",
        f"--source.account={account}",
    ]
    if config:
        cmd.append(f"--source.path-to-config={config}")
    return cmd


def newest_raw(query_name: str) -> Path:
    query_dir = RAW_DIR / query_name
    files = sorted(query_dir.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        die(f"no raw CSV found for {query_name} in {query_dir}")
    return files[0]


def find_raw_file_for_period(
    query_name: str,
    start: dt.date,
    end: dt.date,
    customer_id: str | None = None,
) -> Path | None:
    """Return the newest raw CSV for an exact query/customer/date window."""
    query_dir = RAW_DIR / query_name
    if not query_dir.exists():
        return None

    normalized_customer = customer_id.replace("-", "") if customer_id else ""
    matches: list[Path] = []
    for p in query_dir.glob("*.csv"):
        parts = p.stem.split("_")
        # filename: {customer_id}_{YYYY-MM-DD}_{YYYY-MM-DD}_{run_id}
        if len(parts) < 4:
            continue
        file_customer, file_start, file_end = parts[0], parts[1], parts[2]
        if normalized_customer and file_customer.replace("-", "") != normalized_customer:
            continue
        if file_start == start.isoformat() and file_end == end.isoformat():
            matches.append(p)

    if not matches:
        return None
    return sorted(matches, key=lambda p: (p.stem.split("_")[-1], p.stat().st_mtime), reverse=True)[0]


def find_period_files(query_name: str, n: int) -> list[Path]:
    """Return up to n raw CSV files for a query, sorted by start_date in filename descending."""
    query_dir = RAW_DIR / query_name
    if not query_dir.exists():
        return []
    dated: list[tuple[dt.date, Path]] = []
    for p in query_dir.glob("*.csv"):
        parts = p.stem.split("_")
        # filename: {customer_id}_{YYYY-MM-DD}_{YYYY-MM-DD}_{run_id}
        if len(parts) >= 3:
            try:
                dated.append((dt.date.fromisoformat(parts[1]), p))
            except ValueError:
                pass
    dated.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in dated[:n]]


def find_processed_files_for_period(
    subdir: str, windows: list[tuple[dt.date, dt.date]], customer_id: str | None = None
) -> list[Path | None]:
    """Return processed CSV files matching given (start, end) windows by filename date encoding."""
    proc_dir = _resolve_processed_dir(subdir, customer_id)
    if not proc_dir.exists():
        return [None] * len(windows)
    file_index: dict[tuple[str, str], Path] = {}
    for p in proc_dir.glob("*.csv"):
        parts = p.stem.split("_")
        if len(parts) >= 3:
            file_index[(parts[1], parts[2])] = p
    return [file_index.get((s.isoformat(), e.isoformat())) for s, e in windows]


def log_pull(
    query: str,
    from_date: str,
    to_date: str,
    account: str,
    run_id_val: str,
    output_file: str,
    reason: str,
    question: str = "",
    outcome: str = "fetched",
) -> None:
    """Append one entry to the pull log (logs/pull-log.jsonl).

    outcome values: 'fetched' (API called), 'skipped_raw' (file existed),
    'skipped_wiki' (wiki cache hit — agent writes via log-pull subcommand).
    """
    PULL_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": dt.datetime.now().isoformat(timespec="seconds"),
        "query": query,
        "from_date": from_date,
        "to_date": to_date,
        "account": account,
        "question": question,
        "reason": reason,
        "outcome": outcome,
        "run_id": run_id_val,
        "output_file": output_file,
    }
    with PULL_LOG_PATH.open("a") as f:
        json.dump(entry, f)
        f.write("\n")


def log_signal(
    event_type: str,
    note: str,
    account: str = "",
    user_text: str = "",
    intent: str = "",
    artifact: str = "",
    severity: str = "",
    source: str = "",
) -> dict:
    """Append one self-improvement signal to logs/session-signals.jsonl.

    Records only friction moments (a stumble, retry, correction, failsafe) — never
    the full conversation. Agent-agnostic: any agent (Claude, Gemini, Codex) captures
    signal by calling `./bob log-signal` or `./bob session-debrief`, so this depends on
    no runtime internals. `source` records how the signal was captured — "cli"
    (self-instrumented), "inline" (a mid-session log-signal), or "debrief" (a batched
    session-debrief at a success beat) — so a self-improve pass can see which path fired.
    Absent optional fields are omitted (not null), matching log_pull style.
    """
    SIGNAL_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry: dict[str, Any] = {
        "timestamp": dt.datetime.now().isoformat(timespec="seconds"),
        "event_type": event_type,
        "note": note,
    }
    if user_text:
        entry["user_text"] = user_text[:280]
    if intent:
        entry["intent"] = intent
    if artifact:
        entry["artifact"] = artifact
    if severity:
        entry["severity"] = severity
    if source:
        entry["source"] = source
    if account:
        entry["account"] = account
    agent = os.getenv("BOB_AGENT", "")
    if agent:
        entry["agent"] = agent
    with SIGNAL_LOG_PATH.open("a") as f:
        json.dump(entry, f)
        f.write("\n")
    return entry


def _read_signal_log() -> list[dict]:
    """Read logs/session-signals.jsonl into a list of dicts, tolerant of bad lines."""
    if not SIGNAL_LOG_PATH.exists():
        return []
    out = []
    for line in SIGNAL_LOG_PATH.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def write_metadata(path: Path, metadata: dict[str, Any]) -> None:
    with path.open("w") as f:
        json.dump(metadata, f, indent=2, sort_keys=True)
        f.write("\n")


def garf_failure_message(query_name: str, meta_file: Path, stdout: str, stderr: str) -> str:
    combined_output = f"{stdout}\n{stderr}".lower()
    network_error_patterns = (
        "could not contact dns servers",
        "hostname lookup error",
        "address lookup failed",
        "errors resolving googleads.googleapis.com",
        "temporary failure in name resolution",
        "name or service not known",
        "nodename nor servname",
    )
    if any(pattern in combined_output for pattern in network_error_patterns):
        host = "googleads.googleapis.com" if "googleads.googleapis.com" in combined_output else "the Google Ads API"
        return (
            f"Bob can't reach Google Ads from this environment ({host}). "
            "Check internet access, DNS, VPN/firewall/proxy, or whether the agent/terminal has network permissions. "
            f"See {meta_file}"
        )
    return f"GARF failed for {query_name}. See {meta_file}"


def fetch(args: argparse.Namespace) -> None:
    ensure_dirs()
    profile = load_profile(required=not bool(args.account))
    query_name = args.query
    account = args.account or profile.get("google_ads_customer_id")
    if not account:
        die("google_ads_customer_id missing from profile and --account not provided")
    account = str(account).replace("-", "")
    config = args.config or _profile_read_config_value(profile)
    if not config and not args.dry_run:
        die("I need the Google Ads developer token from Google Ads > Admin > API Center before I can fetch data from Google Ads.")
    if config:
        config = str(Path(config).expanduser())

    if query_name in DATE_QUERIES:
        start, end = resolve_range(args)
    else:
        end = parse_date(args.to) or (today() - dt.timedelta(days=1))
        start = parse_date(args.from_date) or (end - dt.timedelta(days=int(args.days or 30) - 1))

    rid = args.run_id or run_id()
    raw_query_dir = RAW_DIR / query_name
    raw_query_dir.mkdir(parents=True, exist_ok=True)

    # Deduplication: skip if exact (query, account, start, end) already exists
    question = getattr(args, "question", "") or ""
    reason = getattr(args, "reason", "") or ""
    if not getattr(args, "force", False) and not args.dry_run:
        existing = sorted(raw_query_dir.glob(f"{account}_{start}_{end}_*.csv"))
        if existing:
            print(f"skipping {query_name} {start}..{end} — already have {existing[-1].name}")
            log_pull(query_name, start.isoformat(), end.isoformat(), account, rid, str(existing[-1]), reason, question, outcome="skipped_raw")
            # Self-instrumentation: a fetch for a window already on disk is a redundant
            # fetch. Logged by the CLI itself — no agent cooperation required.
            try:
                log_signal(
                    event_type="redundant_fetch",
                    note=f"fetch {query_name} {start}..{end} but raw file already on disk ({existing[-1].name})",
                    account=account,
                    intent="fetch",
                    severity="friction",
                    source="cli",
                )
            except Exception:
                pass
            return

    rendered_query = render_query(query_name, start, end)
    rendered_query_path = raw_query_dir / f"{account}_{start}_{end}_{rid}.sql"
    rendered_query_path.write_text(rendered_query)

    output_file = raw_query_dir / f"{account}_{start}_{end}_{rid}.csv"
    meta_file = raw_query_dir / f"{account}_{start}_{end}_{rid}.meta.json"

    metadata = {
        "query_name": query_name,
        "customer_id": account,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "run_id": rid,
        "reason": reason,
        "source": "google-ads",
        "query_file": str(QUERIES_DIR / f"{query_name}.sql"),
        "rendered_query_file": str(rendered_query_path),
        "output_file": str(output_file),
    }

    if args.dry_run:
        metadata["dry_run"] = True
        write_metadata(meta_file, metadata)
        print(f"dry-run query written: {rendered_query_path}")
        print(f"metadata written: {meta_file}")
        return

    with tempfile.TemporaryDirectory(prefix="bob-garf-") as tmp:
        tmp_dir = Path(tmp)
        cmd = garf_command(rendered_query_path, tmp_dir, account, config)
        metadata["command"] = cmd
        try:
            result = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=False)
        except FileNotFoundError:
            die("garf executable not found. Install with: pip install garf-executors garf-google-ads")
        metadata["returncode"] = result.returncode
        metadata["stdout"] = result.stdout[-4000:]
        metadata["stderr"] = result.stderr[-4000:]
        if result.returncode != 0:
            failure_message = garf_failure_message(query_name, meta_file, result.stdout, result.stderr)
            if failure_message.startswith("Bob can't reach Google Ads"):
                metadata["diagnosis"] = "network_or_dns_unreachable"
            write_metadata(meta_file, metadata)
            die(failure_message)

        produced = sorted(tmp_dir.glob("*.csv"))
        if not produced:
            write_metadata(meta_file, metadata)
            die(f"GARF completed but no CSV was written to {tmp_dir}")
        shutil.move(str(produced[0]), output_file)

    write_metadata(meta_file, metadata)
    log_pull(query_name, start.isoformat(), end.isoformat(), account, rid, str(output_file), reason, question, outcome="fetched")
    print(f"raw output written: {output_file}")
    print(f"metadata written: {meta_file}")
    try:
        with open(output_file, newline="") as _f:
            _row_count = sum(1 for _ in csv.reader(_f)) - 1
    except Exception:
        _row_count = -1
    if _row_count == 0:
        print(
            f"WARNING: 0 rows for {account} / {query_name} / {start.isoformat()}..{end.isoformat()}. "
            f"The account may have no activity in this window.",
            file=sys.stderr,
        )


def bootstrap(args: argparse.Namespace) -> None:
    failures: list[str] = []
    for entry in DEFAULT_BOOTSTRAP:
        query_name = entry["query"]
        if "period" in entry:
            windows = resolve_period_dates(entry["period"])
            label = f"{query_name} ({entry['period']}, {len(windows)} windows)"
        else:
            windows = [None]
            label = f"{query_name} ({entry['days']} days)"
        print(f"\n==> fetching {label}")
        for window in windows:
            _reason = getattr(args, "reason", "") or ""
            _question = getattr(args, "question", "") or ""
            _force = getattr(args, "force", False)
            if window is not None:
                start, end = window
                child = argparse.Namespace(
                    query=query_name,
                    days=None,
                    from_date=start.isoformat(),
                    to=end.isoformat(),
                    account=args.account,
                    config=args.config,
                    dry_run=args.dry_run,
                    run_id=args.run_id,
                    reason=_reason,
                    question=_question,
                    force=_force,
                )
            else:
                child = argparse.Namespace(
                    query=query_name,
                    days=entry["days"],
                    from_date=args.from_date,
                    to=args.to,
                    account=args.account,
                    config=args.config,
                    dry_run=args.dry_run,
                    run_id=args.run_id,
                    reason=_reason,
                    question=_question,
                    force=_force,
                )
            try:
                fetch(child)
            except SystemExit as exc:
                failures.append(f"{query_name}: exit {exc.code}")
                if not args.keep_going:
                    raise
    if failures:
        print("\ncompleted with failures:")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)
    print("\nbootstrap fetch complete — running aggregates\n")

    if not args.dry_run:
        for grain in ("account_network_period", "campaign_network_period", "creative_period", "campaign_weekly_trend"):
            try:
                agg_args = argparse.Namespace(grain=grain, source=None, goal=None, input=None, customer=None, output=None)
                aggregate(agg_args)
            except SystemExit:
                print(f"  aggregate {grain}: skipped (no data yet)")
        print("\nbootstrap complete")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            first_line = sample.splitlines()[0] if sample.splitlines() else ""
            if first_line.count(",") >= first_line.count("\t") and "," in first_line:
                dialect = csv.excel
            else:
                dialect = csv.Sniffer().sniff(sample) if sample.strip() else csv.excel
        except Exception:
            dialect = csv.excel
        return list(csv.DictReader(f, dialect=dialect))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def number(value: Any) -> float:
    if value is None:
        return 0.0
    text = str(value).strip().replace(",", "")
    if text == "" or text.upper() in {"NA", "NULL", "NAN"}:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def ratio(num: float, den: float, scale: float = 1.0) -> str:
    if den == 0:
        return "NA"
    return format_float(num / den * scale)


def format_float(value: float) -> str:
    if value == 0:
        return "0"
    if abs(value) >= 100:
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return f"{value:.4f}".rstrip("0").rstrip(".")


def _derive_metrics(g: dict[str, float], primary_goal: str) -> dict[str, str]:
    """Compute derived metrics from summed base metrics."""
    goal = g["installs"] if primary_goal == "installs" else g["in_app_conversions"]
    # Reach is optional and must not silently become 0, so we treat missing/blank as NA.
    has_reach = "reach" in g and g.get("reach") not in (None, "", "NA")
    reach = g.get("reach") if has_reach else None
    return {
        "reach": format_float(reach) if has_reach else "NA",
        "impressions": format_float(g["impressions"]),
        "clicks": format_float(g["clicks"]),
        "cost": format_float(g["cost"]),
        "installs": format_float(g["installs"]),
        "in_app_conversions": format_float(g["in_app_conversions"]),
        "goal_conversions": format_float(goal),
        "cpm": ratio(g["cost"], g["impressions"], 1000),
        "frequency": ratio(g["impressions"], reach) if has_reach else "NA",
        "ctr_percent": ratio(g["clicks"], g["impressions"], 100),
        "cpc": ratio(g["cost"], g["clicks"]),
        "cti_percent": ratio(g["installs"], g["clicks"], 100),
        "conversion_rate_percent": ratio(goal, g["clicks"], 100),
        "cpa": ratio(g["cost"], goal),
        "cpi": ratio(g["cost"], g["installs"]),
    }


CURRENCY_SYMBOLS: dict[str, str] = {
    "INR": "₹", "USD": "$", "EUR": "€", "GBP": "£",
    "AUD": "A$", "CAD": "C$", "SGD": "S$",
}

# (display label, metric key in aggregated row, format kind)
METRIC_DISPLAY_SPEC: list[tuple[str, str, str]] = [
    ("Users",        "reach",                   "count"),
    ("Impressions",  "impressions",              "count"),
    ("Cost",         "cost",                     "cost"),
    ("CPM",          "cpm",                      "cost"),
    ("Frequency",    "frequency",                "ratio"),
    ("Clicks",       "clicks",                   "count"),
    ("CTR %",        "ctr_percent",              "percent"),
    ("CPC",          "cpc",                      "cost"),
    ("Installs",     "installs",                 "count"),
    ("CTI %",        "cti_percent",              "percent"),
    ("Conversions",  "goal_conversions",         "count"),
    ("Conv %",       "conversion_rate_percent",  "percent"),
    ("CPA",          "cpa",                      "cost"),
    ("CPI",          "cpi",                      "cost"),
]


def _currency_symbol(currency: str) -> str:
    return CURRENCY_SYMBOLS.get((currency or "").upper(), "")


def _fmt_display(val: Any, kind: str, sym: str = "") -> str:
    if str(val).upper() in ("NA", "", "NAN", "NONE"):
        return "NA"
    v = number(val)
    if v == 0 and kind in ("ratio", "frequency"):
        return "NA"
    if kind == "count":
        if v >= 1_000_000:
            return f"{v / 1_000_000:,.2f}M"
        return f"{v:,.0f}"
    if kind == "cost":
        if v >= 1_000_000:
            return f"{sym}{v / 1_000_000:,.2f}M"
        if v >= 1_000:
            return f"{sym}{v:,.2f}"
        return f"{sym}{v:.2f}"
    if kind == "percent":
        return f"{v:.2f}%"
    return f"{v:.2f}"  # ratio


def _fmt_delta_display(cur: Any, base: Any) -> str:
    if str(cur).upper() in ("NA", "", "NAN") or str(base).upper() in ("NA", "", "NAN"):
        return "NA"
    c, b = number(cur), number(base)
    if b == 0:
        return "NA" if c == 0 else "+∞"
    pct = (c - b) / b * 100
    return f"+{pct:.1f}%" if pct >= 0 else f"{pct:.1f}%"


def _print_metric_table(
    cur: dict[str, Any],
    base: dict[str, Any],
    cur_label: str,
    base_label: str,
    currency_sym: str,
) -> None:
    col_m = max(len(s[0]) for s in METRIC_DISPLAY_SPEC) + 1
    col_v = max(18, len(cur_label) + 2, len(base_label) + 2)
    col_d = 10
    hdr = f"  {'Metric':<{col_m}}  {cur_label:>{col_v}}  {base_label:>{col_v}}  {'Δ %':>{col_d}}"
    sep = "  " + "─" * col_m + "──" + "─" * col_v + "──" + "─" * col_v + "──" + "─" * col_d
    print(hdr)
    print(sep)
    for label, key, kind in METRIC_DISPLAY_SPEC:
        cur_fmt = _fmt_display(cur.get(key, "NA"), kind, currency_sym)
        base_fmt = _fmt_display(base.get(key, "NA"), kind, currency_sym)
        delta_fmt = _fmt_delta_display(cur.get(key, "NA"), base.get(key, "NA"))
        print(f"  {label:<{col_m}}  {cur_fmt:>{col_v}}  {base_fmt:>{col_v}}  {delta_fmt:>{col_d}}")


def _delta_pct(current: float, baseline: float) -> str:
    if baseline == 0:
        return "NA" if current == 0 else "+inf"
    return format_float((current - baseline) / baseline * 100)


def _date_label(path: Path) -> str:
    parts = path.stem.split("_")
    if len(parts) >= 3:
        return f"{parts[1]}–{parts[2]}"
    return path.name


def _build_comparison_rows(
    current_rows: list[dict],
    baseline_rows: list[dict],
    key_cols: list[str],
    primary_goal: str,
) -> list[dict[str, Any]]:
    """Aggregate both sets by key_cols, join, and compute delta_pct columns."""
    def _canonicalize_network_rows(rows: list[dict]) -> list[dict]:
        if "network" not in key_cols:
            return rows
        out = []
        for row in rows:
            normalized = dict(row)
            normalized["network"] = _canonical_network(row.get("network", ""))
            out.append(normalized)
        return out

    def _canonicalize_key_cols(row: dict) -> dict:
        out = {col: row.get(col, "") for col in key_cols}
        if "network" in out:
            out["network"] = _canonical_network(out["network"])
        return out

    current_rows = _canonicalize_network_rows(current_rows)
    baseline_rows = _canonicalize_network_rows(baseline_rows)
    cur_agg = {
        tuple(r.get(c, "") for c in key_cols): r
        for r in _aggregate_period_rows(current_rows, key_cols, primary_goal)
    }
    base_agg = {
        tuple(r.get(c, "") for c in key_cols): r
        for r in _aggregate_period_rows(baseline_rows, key_cols, primary_goal)
    }
    out: list[dict[str, Any]] = []
    for key in sorted(set(cur_agg) | set(base_agg)):
        cur = cur_agg.get(key, {})
        base = base_agg.get(key, {})
        rep = cur or base
        row: dict[str, Any] = _canonicalize_key_cols(rep)
        for m in _COMPARISON_VOLUME_METRICS:
            # Reach is optional: if absent, keep it as NA (not 0).
            if m == "reach" and ("reach" not in cur or "reach" not in base) and ("reach" not in rep):
                row["current_reach"] = "NA"
                row["baseline_reach"] = "NA"
                row["delta_reach_pct"] = "NA"
                continue
            c_val = number(cur.get(m, 0))
            b_val = number(base.get(m, 0))
            row[f"current_{m}"] = format_float(c_val)
            row[f"baseline_{m}"] = format_float(b_val)
            row[f"delta_{m}_pct"] = _delta_pct(c_val, b_val)
        for m in _COMPARISON_RATIO_METRICS:
            row[f"current_{m}"] = cur.get(m, "NA")
            row[f"baseline_{m}"] = base.get(m, "NA")
        out.append(row)
    return out


def _aggregate_period_rows(
    rows: list[dict],
    key_cols: list[str],
    primary_goal: str,
) -> list[dict]:
    """Group by key_cols, sum SUM_METRICS, recalculate derived metrics."""
    # reach (unique_users) is summed only when the source actually provides it
    # — i.e. the reach grain, which has no network split. Network/adgroup grains
    # never fetch unique_users, so reach stays absent here → NA in _derive_metrics,
    # preserving the "no reach for network/adgroup breakdowns" rule.
    reach_present = any(
        str(r.get("reach", "")).upper() not in ("", "NA", "NONE") for r in rows
    )
    sum_metrics = SUM_METRICS + (["reach"] if reach_present else [])
    grouped: dict[tuple, dict[str, Any]] = {}
    for row in rows:
        key = tuple(row.get(col, "") for col in key_cols)
        if key not in grouped:
            grouped[key] = {col: row.get(col, "") for col in key_cols}
            for m in sum_metrics:
                grouped[key][m] = 0.0
        for m in sum_metrics:
            grouped[key][m] += number(row.get(m))
    out = []
    for key in sorted(grouped):
        g = grouped[key]
        row_out = {col: g[col] for col in key_cols}
        row_out.update(_derive_metrics(g, primary_goal))
        out.append(row_out)
    return out


def aggregate(args: argparse.Namespace) -> None:
    profile = load_profile(required=False)
    grain = args.grain
    primary_goal = args.goal or profile.get("primary_goal") or "in_app_conversions"

    if grain == "account_daily":
        _agg_account_daily(args, profile, primary_goal)
    elif grain in _NETWORK_PERIOD_KEY_COLS:
        _agg_network_period(args, profile, grain, primary_goal)
    elif grain == "creative_period":
        _agg_creative_period(args, profile, primary_goal)
    elif grain == "campaign_weekly_trend":
        _agg_campaign_weekly_trend(args, profile, primary_goal)
    else:
        die(f"unknown grain: {grain}")


def _agg_account_daily(
    args: argparse.Namespace, profile: dict, primary_goal: str
) -> None:
    source = args.source or "campaign_daily"
    input_path = Path(args.input).expanduser() if args.input else newest_raw(source)
    rows = read_csv(input_path)
    grouped: dict[str, dict[str, float]] = {}
    for row in rows:
        date = row.get("date")
        if not date:
            continue
        if date not in grouped:
            grouped[date] = {m: 0.0 for m in SUM_METRICS}
        for m in SUM_METRICS:
            grouped[date][m] += number(row.get(m))

    out_rows: list[dict[str, Any]] = []
    for date in sorted(grouped):
        row_out: dict[str, Any] = {"date": date}
        row_out.update(_derive_metrics(grouped[date], primary_goal))
        out_rows.append(row_out)

    customer = args.customer or profile.get("google_ads_customer_id") or "unknown"
    if args.output:
        output_path = Path(args.output).expanduser()
    else:
        start = out_rows[0]["date"] if out_rows else "empty"
        end = out_rows[-1]["date"] if out_rows else "empty"
        output_path = account_processed_dir(customer, "account") / f"account_daily_{customer}_{start}_{end}.csv"
    write_csv(output_path, out_rows, ACCOUNT_DAILY_COLUMNS)
    print(f"processed aggregate written: {output_path}")
    if not out_rows:
        print("WARNING: aggregate account_daily produced 0 rows.", file=sys.stderr)


def _agg_network_period(
    args: argparse.Namespace, profile: dict, grain: str, primary_goal: str
) -> None:
    source = args.source or grain
    # Normalize to the hyphen-stripped form used by the processed dir, the raw
    # files, and find_processed_files_for_period — otherwise a hyphenated prefix
    # creates a duplicate file for the same window and the date-keyed selector
    # picks one at random.
    customer = (args.customer or profile.get("google_ads_customer_id") or "unknown").replace("-", "")
    from_date = getattr(args, "from_date", None)
    to_date = getattr(args, "to", None)
    if args.input:
        input_path = Path(args.input).expanduser()
    elif from_date or to_date:
        if not from_date or not to_date:
            die("aggregate period selection requires both --from and --to")
        try:
            start = dt.date.fromisoformat(from_date)
            end = dt.date.fromisoformat(to_date)
        except ValueError:
            die("--from and --to must be ISO dates: YYYY-MM-DD")
        selected = find_raw_file_for_period(source, start, end, customer)
        if not selected:
            die(f"no raw CSV found for {source} {start}–{end} for account {customer}")
        input_path = selected
    else:
        input_path = newest_raw(source)
    rows = read_csv(input_path)
    # Reach is optional; network is only present for the network-split grains.
    for row in rows:
        if "network" in row:
            row["network"] = _canonical_network(row.get("network", ""))
    out_rows = _aggregate_period_rows(rows, _NETWORK_PERIOD_KEY_COLS[grain], primary_goal)

    parts = input_path.stem.split("_")
    file_start = parts[1] if len(parts) >= 3 else "unknown"
    file_end = parts[2] if len(parts) >= 3 else "unknown"
    if args.output:
        output_path = Path(args.output).expanduser()
    else:
        subdir = _NETWORK_PERIOD_SUBDIR[grain]
        output_path = account_processed_dir(customer, subdir) / f"{customer}_{file_start}_{file_end}.csv"
    write_csv(output_path, out_rows, _NETWORK_PERIOD_COLUMNS[grain])
    print(f"processed aggregate written: {output_path}")
    if not out_rows:
        print(
            f"WARNING: aggregate {grain} produced 0 rows from {input_path.name}.",
            file=sys.stderr,
        )


def _agg_creative_period(
    args: argparse.Namespace, profile: dict, primary_goal: str
) -> None:
    source = args.source or "creative_period"
    input_path = Path(args.input).expanduser() if args.input else newest_raw(source)
    rows = read_csv(input_path)
    key_cols = [
        "customer_id", "campaign_id", "campaign_name",
        "ad_group_id", "ad_group_name",
        "asset_view_resource_name", "asset_resource_name",
        "asset_id", "asset_name", "asset_type", "field_type", "performance_label",
        "image_url", "image_width", "image_height", "mime_type", "file_size_bytes",
    ]
    out_rows = _aggregate_period_rows(rows, key_cols, primary_goal)
    min_imp = int(profile.get("creative_min_impressions", DEFAULT_CREATIVE_MIN_IMPRESSIONS))
    out_rows = [r for r in out_rows if number(r.get("impressions")) >= min_imp]

    parts = input_path.stem.split("_")
    file_start = parts[1] if len(parts) >= 3 else "unknown"
    file_end = parts[2] if len(parts) >= 3 else "unknown"
    customer = args.customer or profile.get("google_ads_customer_id") or "unknown"
    if args.output:
        output_path = Path(args.output).expanduser()
    else:
        output_path = account_processed_dir(customer, "creative") / f"{customer}_{file_start}_{file_end}.csv"
    write_csv(output_path, out_rows, CREATIVE_PERIOD_COLUMNS)
    print(f"processed aggregate written: {output_path} ({len(out_rows)} creatives >= {min_imp} impressions)")
    if not out_rows:
        print(
            f"WARNING: aggregate creative_period produced 0 rows above {min_imp} impressions.",
            file=sys.stderr,
        )


def _agg_campaign_weekly_trend(
    args: argparse.Namespace, profile: dict, primary_goal: str
) -> None:
    source = args.source or "campaign_network_period"
    period_files = find_period_files(source, 3)
    if len(period_files) < 3:
        die(
            f"need 3 {source} raw files for campaign_weekly_trend, found {len(period_files)}. "
            "Run: python3 lib/datapull.py bootstrap"
        )

    campaign_key_cols = ["customer_id", "campaign_id", "campaign_name", "campaign_status"]
    week_data: list[tuple[int, str, str, dict[str, dict]]] = []
    for path in period_files:
        parts = path.stem.split("_")
        w_start = parts[1] if len(parts) >= 3 else ""
        w_end = parts[2] if len(parts) >= 3 else ""
        try:
            iso_week = dt.date.fromisoformat(w_start).isocalendar().week
        except (ValueError, AttributeError):
            iso_week = 0
        agg = _aggregate_period_rows(read_csv(path), campaign_key_cols, primary_goal)
        week_data.append((iso_week, w_start, w_end, {r["campaign_id"]: r for r in agg}))

    w0_iso, w0_start, w0_end, w0 = week_data[0]
    w1_iso, w1_start, w1_end, w1 = week_data[1]
    w2_iso, w2_start, w2_end, w2 = week_data[2]
    goal_col = "installs" if primary_goal == "installs" else "in_app_conversions"

    def cpi(r: dict) -> float:
        cost = number(r.get("cost", 0))
        goal = number(r.get(goal_col, 0))
        return cost / goal if goal > 0 else 0.0

    def week_prefixed(iso_w: int, start: str, end: str, r: dict) -> dict:
        p = f"w{iso_w}"
        return {
            f"{p}_start": start,
            f"{p}_end": end,
            f"{p}_impressions": r.get("impressions", "0"),
            f"{p}_clicks": r.get("clicks", "0"),
            f"{p}_cost": r.get("cost", "0"),
            f"{p}_installs": r.get("installs", "0"),
            f"{p}_in_app_conversions": r.get("in_app_conversions", "0"),
            f"{p}_cpm": ratio(number(r.get("cost", 0)), number(r.get("impressions", 0)), 1000),
            f"{p}_ctr_percent": r.get("ctr_percent", "NA"),
            f"{p}_cpc": r.get("cpc", "NA"),
            f"{p}_cti_percent": r.get("cti_percent", "NA"),
            f"{p}_conversion_rate_percent": r.get("conversion_rate_percent", "NA"),
        }

    all_ids = set(w0) | set(w1) | set(w2)
    out_rows = []
    for cid in sorted(all_ids):
        r0, r1, r2 = w0.get(cid, {}), w1.get(cid, {}), w2.get(cid, {})
        rep = r0 or r1 or r2
        c0, c1, c2 = cpi(r0), cpi(r1), cpi(r2)

        # CPI lower = better; w0 is most recent
        if c0 > 0 and c1 > 0 and c2 > 0:
            w0_better = c0 < c1
            w1_better = c1 < c2
            if w0_better and w1_better:
                trend, signal = "improving", "confirmed"
            elif not w0_better and not w1_better:
                trend, signal = "deteriorating", "confirmed"
            elif w0_better and not w1_better:
                trend, signal = "improving", "early"
            else:
                trend, signal = "deteriorating", "blip"
        elif c0 > 0 and c1 > 0:
            trend = "improving" if c0 < c1 else "deteriorating"
            signal = "early"
        else:
            trend, signal = "stable", "early"

        row_out: dict[str, Any] = {
            "customer_id": rep.get("customer_id", ""),
            "campaign_id": cid,
            "campaign_name": rep.get("campaign_name", ""),
            "campaign_status": rep.get("campaign_status", ""),
            "current_iso_week": w0_iso,
            "prior1_iso_week": w1_iso,
            "prior2_iso_week": w2_iso,
        }
        row_out.update(week_prefixed(w0_iso, w0_start, w0_end, r0))
        row_out.update(week_prefixed(w1_iso, w1_start, w1_end, r1))
        row_out.update(week_prefixed(w2_iso, w2_start, w2_end, r2))
        row_out["trend_direction"] = trend
        row_out["signal_strength"] = signal
        out_rows.append(row_out)

    customer = args.customer or profile.get("google_ads_customer_id") or "unknown"
    if args.output:
        output_path = Path(args.output).expanduser()
    else:
        output_path = account_processed_dir(customer, "campaign-trend") / f"{customer}_{w0_start}_{w0_end}.csv"
    trend_cols = _weekly_trend_columns([w0_iso, w1_iso, w2_iso])
    write_csv(output_path, out_rows, trend_cols)
    print(f"processed aggregate written: {output_path} ({len(out_rows)} campaigns)")
    if not out_rows:
        print(
            "WARNING: aggregate campaign_weekly_trend produced 0 rows.",
            file=sys.stderr,
        )


def correlate_change_history(
    campaign_id: str,
    start_date: str,
    end_date: str,
    change_history_path: Path,
) -> list[dict]:
    """Return change events for a campaign within a date window, for diagnostic overlay."""
    if not change_history_path.exists():
        return []
    target = str(campaign_id).replace("-", "")
    results = []
    for row in read_csv(change_history_path):
        row_campaign = str(row.get("campaign_id", "")).replace("-", "")
        changed_at = row.get("changed_at", "")[:10]
        if row_campaign == target and start_date <= changed_at <= end_date:
            results.append(row)
    return results


def _print_grain_results(
    grain_name: str,
    key_cols: list[str],
    cur_rows: list[dict],
    base_rows: list[dict],
    cur_reach_rows: list[dict] | None,
    base_reach_rows: list[dict] | None,
    primary_goal: str,
    all_metrics: bool,
    currency_sym: str,
    cur_label: str,
    base_label: str,
    name_filter: str,
    output_path: str | None,
    output_account_path: str | None,
) -> None:
    goal_col = "installs" if primary_goal == "installs" else "in_app_conversions"
    rows = _build_comparison_rows(cur_rows, base_rows, key_cols, primary_goal)
    total_cur = _aggregate_period_rows(cur_rows, ["customer_id"], primary_goal)
    total_base = _aggregate_period_rows(base_rows, ["customer_id"], primary_goal)
    tc = total_cur[0] if total_cur else {}
    tb = total_base[0] if total_base else {}

    _all_metric_keys = [m for _, m, _ in METRIC_DISPLAY_SPEC]

    def _row_to_period_dicts(r: dict, include_reach: bool = True) -> tuple[dict, dict]:
        cur_d = {m: r.get(f"current_{m}", "NA") for m in _all_metric_keys}
        base_d = {m: r.get(f"baseline_{m}", "NA") for m in _all_metric_keys}
        if not include_reach:
            for d in (cur_d, base_d):
                d["reach"] = "NA"
                d["frequency"] = "NA"
        return cur_d, base_d

    def _mask_network_reach(row: dict) -> dict:
        masked = dict(row)
        for key in ("current_reach", "baseline_reach", "delta_reach_pct", "current_frequency", "baseline_frequency"):
            if key in masked:
                masked[key] = "NA"
        return masked

    if grain_name == "account_network_period":
        if all_metrics:
            print(f"\nAccount Summary — all metrics")
            _print_metric_table(tc, tb, cur_label, base_label, currency_sym)
            for row in rows:
                network = _display_network(row.get("network", ""))
                cur_net, base_net = _row_to_period_dicts(row, include_reach=False)
                print(f"\nNetwork: {network}")
                _print_metric_table(cur_net, base_net, cur_label, base_label, currency_sym)

        print(f"\nAccount × Network")
        hdr = f"  {'Network':<16}  {'Cur Goal':>12}  {'Base Goal':>12}  {'Δ%':>8}  {'Cur Cost':>12}  {'Base Cost':>12}  {'Δ%':>8}"
        print(hdr)
        print("  " + "─" * (len(hdr) - 2))
        for row in rows:
            g_cur = row[f'current_{goal_col}']
            g_base = row[f'baseline_{goal_col}']
            c_cur = row['current_cost']
            c_base = row['baseline_cost']
            print(
                f"  {_display_network(row.get('network', '')):<16}  "
                f"{_fmt_display(g_cur, 'count'):>12}  "
                f"{_fmt_display(g_base, 'count'):>12}  "
                f"{_fmt_delta_display(g_cur, g_base):>8}  "
                f"{_fmt_display(c_cur, 'cost', currency_sym):>12}  "
                f"{_fmt_display(c_base, 'cost', currency_sym):>12}  "
                f"{_fmt_delta_display(c_cur, c_base):>8}"
            )
        print(
            f"  {'TOTAL':<16}  "
            f"{_fmt_display(tc.get(goal_col, '0'), 'count'):>12}  "
            f"{_fmt_display(tb.get(goal_col, '0'), 'count'):>12}  "
            f"{_fmt_delta_display(tc.get(goal_col, '0'), tb.get(goal_col, '0')):>8}  "
            f"{_fmt_display(tc.get('cost', '0'), 'cost', currency_sym):>12}  "
            f"{_fmt_display(tb.get('cost', '0'), 'cost', currency_sym):>12}  "
            f"{_fmt_delta_display(tc.get('cost', '0'), tb.get('cost', '0')):>8}"
        )
        if output_account_path:
            write_csv(Path(output_account_path).expanduser(), [_mask_network_reach(r) for r in rows], ACCOUNT_WEEK_COMPARISON_COLUMNS)
            print(f"account comparison written: {output_account_path}")

    elif grain_name == "campaign_network_period":
        rows.sort(
            key=lambda r: abs(number(r[f"current_{goal_col}"]) - number(r[f"baseline_{goal_col}"])),
            reverse=True,
        )
        n = len(rows)
        n_label = f"{n} campaigns" + (f" matching '{name_filter}'" if name_filter else "")
        if all_metrics:
            # Use reach-only grain for Users/Frequency in the segment summary if available.
            # We intentionally do NOT compute a summed reach total across campaigns elsewhere.
            if cur_reach_rows is not None and base_reach_rows is not None:
                reach_tc_list = _aggregate_period_rows(cur_reach_rows, ["customer_id"], primary_goal)
                reach_tb_list = _aggregate_period_rows(base_reach_rows, ["customer_id"], primary_goal)
                reach_tc = reach_tc_list[0] if reach_tc_list else {}
                reach_tb = reach_tb_list[0] if reach_tb_list else {}
                # Merge reach + frequency onto the normal totals dicts for display.
                tc = dict(tc)
                tb = dict(tb)
                tc["reach"] = reach_tc.get("reach", "NA")
                tb["reach"] = reach_tb.get("reach", "NA")
                tc["frequency"] = reach_tc.get("frequency", "NA")
                tb["frequency"] = reach_tb.get("frequency", "NA")
            print(f"\nCampaign Segment Summary — all metrics ({n_label})")
            _print_metric_table(tc, tb, cur_label, base_label, currency_sym)

        print(f"\nCampaigns ({n_label}) — sorted by |goal Δ|")
        hdr = f"  {'Campaign':<45}  {'Cur Goal':>12}  {'Base Goal':>12}  {'Δ%':>8}  {'Cur Cost':>12}  {'Base Cost':>12}  {'Δ%':>8}"
        print(hdr)
        print("  " + "─" * (len(hdr) - 2))
        for row in rows:
            g_cur = row[f'current_{goal_col}']
            g_base = row[f'baseline_{goal_col}']
            c_cur = row['current_cost']
            c_base = row['baseline_cost']
            print(
                f"  {row['campaign_name']:<45}  "
                f"{_fmt_display(g_cur, 'count'):>12}  "
                f"{_fmt_display(g_base, 'count'):>12}  "
                f"{_fmt_delta_display(g_cur, g_base):>8}  "
                f"{_fmt_display(c_cur, 'cost', currency_sym):>12}  "
                f"{_fmt_display(c_base, 'cost', currency_sym):>12}  "
                f"{_fmt_delta_display(c_cur, c_base):>8}"
            )
        print(
            f"  {'— TOTAL —':<45}  "
            f"{_fmt_display(tc.get(goal_col, '0'), 'count'):>12}  "
            f"{_fmt_display(tb.get(goal_col, '0'), 'count'):>12}  "
            f"{_fmt_delta_display(tc.get(goal_col, '0'), tb.get(goal_col, '0')):>8}  "
            f"{_fmt_display(tc.get('cost', '0'), 'cost', currency_sym):>12}  "
            f"{_fmt_display(tb.get('cost', '0'), 'cost', currency_sym):>12}  "
            f"{_fmt_delta_display(tc.get('cost', '0'), tb.get('cost', '0')):>8}"
        )
        if output_path:
            write_csv(Path(output_path).expanduser(), rows, CAMPAIGN_WEEK_COMPARISON_COLUMNS)
            print(f"\ncampaign comparison written: {output_path}")


def slice_campaigns(args: argparse.Namespace) -> None:
    profile = load_profile(required=False)
    primary_goal = args.goal or profile.get("primary_goal") or "in_app_conversions"
    currency_sym = _currency_symbol(profile.get("currency", ""))
    pattern = (args.name_contains or "").lower()
    all_metrics = getattr(args, "all_metrics", False)
    customer_id = profile.get("google_ads_customer_id")

    if args.current and args.baseline:
        current_path: Path | None = Path(args.current).expanduser()
        baseline_path: Path | None = Path(args.baseline).expanduser()
    else:
        period = args.period or "yesterday_vs_sdlw"
        windows = resolve_period_dates(period)
        found = find_processed_files_for_period("campaign-network", [windows[0], windows[1]], customer_id)
        current_path, baseline_path = found[0], found[1]
        if not current_path or not baseline_path:
            missing = []
            if not current_path:
                missing.append(f"{windows[0][0]}_{windows[0][1]}")
            if not baseline_path:
                missing.append(f"{windows[1][0]}_{windows[1][1]}")
            die(
                f"processed campaign-network files not found for: {', '.join(missing)}\n"
                "Run: python3 lib/datapull.py aggregate --grain campaign_network_period"
            )

    all_cur = read_csv(current_path)
    all_base = read_csv(baseline_path)
    cur_label = _date_label(current_path)
    base_label = _date_label(baseline_path)
    if not all_cur or not all_base:
        empty_sides = []
        if not all_cur:
            empty_sides.append(cur_label)
        if not all_base:
            empty_sides.append(base_label)
        print(
            f"No data for {', '.join(empty_sides)} (account {customer_id}). "
            f"Nothing to compare.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    cur_rows = [r for r in all_cur if pattern in r.get("campaign_name", "").lower()]
    base_rows = [r for r in all_base if pattern in r.get("campaign_name", "").lower()]

    if not cur_rows and not base_rows:
        print(
            f"No campaigns matching {args.name_contains!r} in either period.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    print(f"\nCampaign slice: name contains '{args.name_contains}'")
    print(f"Current: {cur_label}  |  Baseline: {base_label}")

    _print_grain_results(
        "campaign_network_period",
        ["customer_id", "campaign_id", "campaign_name", "campaign_status"],
        cur_rows, base_rows, None, None, primary_goal, all_metrics, currency_sym,
        cur_label, base_label, pattern,
        args.output, None,
    )


def compare_weeks(args: argparse.Namespace) -> None:
    profile = load_profile(required=False)
    primary_goal = args.goal or profile.get("primary_goal") or "in_app_conversions"
    currency_sym = _currency_symbol(profile.get("currency", ""))
    name_filter = (args.name_contains or "").lower()
    all_metrics = getattr(args, "all_metrics", False)
    customer_id = profile.get("google_ads_customer_id")

    ref = today()
    if args.week:
        cur_week, cur_year = args.week, (args.year or ref.isocalendar().year)
    else:
        cur_week, cur_year = last_complete_iso_week(ref)

    if args.vs:
        base_week = args.vs
        base_year = cur_year if base_week <= cur_week else cur_year - 1
    else:
        base_week = cur_week - 1
        base_year = cur_year
        if base_week < 1:
            prev = cur_year - 1
            base_week = dt.date(prev, 12, 28).isocalendar().week
            base_year = prev

    cur_start, cur_end = iso_week_to_dates(cur_week, cur_year)
    base_start, base_end = iso_week_to_dates(base_week, base_year)
    cur_label = f"W{cur_week} ({cur_start}–{cur_end})"
    base_label = f"W{base_week} ({base_start}–{base_end})"

    print(f"\nISO week comparison:  W{cur_week} {cur_year} ({cur_start}–{cur_end})  vs  W{base_week} {base_year} ({base_start}–{base_end})")
    if name_filter:
        print(f"Campaign filter: name contains '{args.name_contains}'")

    grains: list[tuple[str, list[str]]] = []
    if args.grain in ("account", "both"):
        grains.append(("account_network_period", ["customer_id", "customer_name", "network"]))
    if args.grain in ("campaign", "both"):
        grains.append(("campaign_network_period", ["customer_id", "campaign_id", "campaign_name", "campaign_status"]))

    all_ok = True
    for grain_name, key_cols in grains:
        subdir = _NETWORK_PERIOD_SUBDIR[grain_name]
        found = find_processed_files_for_period(subdir, [(cur_start, cur_end), (base_start, base_end)], customer_id)
        cur_path, base_path = found[0], found[1]

        if not cur_path or not base_path:
            all_ok = False
            missing_windows = []
            if not cur_path:
                missing_windows.append((cur_week, cur_start, cur_end))
            if not base_path:
                missing_windows.append((base_week, base_start, base_end))
            missing = [f"W{week} ({start}–{end})" for week, start, end in missing_windows]
            print(f"\n[{grain_name}] processed files missing for: {', '.join(missing)}")
            print("Fetch and aggregate:")
            for _, start, end in missing_windows:
                raw_path = find_raw_file_for_period(grain_name, start, end, customer_id)
                if not raw_path:
                    print(f"  python3 lib/datapull.py fetch --query {grain_name} --from {start} --to {end}")
                print(f"  python3 lib/datapull.py aggregate --grain {grain_name} --from {start} --to {end}")
            continue

        cur_rows = read_csv(cur_path)
        base_rows = read_csv(base_path)
        if not cur_rows or not base_rows:
            empty_sides = []
            if not cur_rows:
                empty_sides.append(cur_label)
            if not base_rows:
                empty_sides.append(base_label)
            print(
                f"\n[{grain_name}] No data for {', '.join(empty_sides)} "
                f"(account {customer_id}). Nothing to compare.",
                file=sys.stderr,
            )
            all_ok = False
            continue
        if grain_name == "campaign_network_period" and name_filter:
            cur_rows = [r for r in cur_rows if name_filter in r.get("campaign_name", "").lower()]
            base_rows = [r for r in base_rows if name_filter in r.get("campaign_name", "").lower()]
            if not cur_rows and not base_rows:
                print(
                    f"\n[{grain_name}] no campaigns matching '{args.name_contains}' in either week.",
                    file=sys.stderr,
                )
                all_ok = False
                continue

        # Optional: reach-only grain for campaign segment metric table.
        cur_reach_rows = None
        base_reach_rows = None
        if grain_name == "campaign_network_period" and all_metrics:
            reach_found = find_processed_files_for_period(
                _NETWORK_PERIOD_SUBDIR["campaign_reach_period"],
                [(cur_start, cur_end), (base_start, base_end)],
                customer_id,
            )
            reach_cur_path, reach_base_path = reach_found[0], reach_found[1]
            if not reach_cur_path or not reach_base_path:
                missing = []
                if not reach_cur_path:
                    missing.append(f"W{cur_week} ({cur_start}–{cur_end})")
                if not reach_base_path:
                    missing.append(f"W{base_week} ({base_start}–{base_end})")
                print(f"\n[campaign_reach_period] processed files missing for: {', '.join(missing)}")
                print("Fetch and aggregate:")
                for start, end in [(cur_start, cur_end), (base_start, base_end)]:
                    raw_path = find_raw_file_for_period("campaign_reach_period", start, end, customer_id)
                    if not raw_path:
                        print(f"  python3 lib/datapull.py fetch --query campaign_reach_period --from {start} --to {end}")
                    print(f"  python3 lib/datapull.py aggregate --grain campaign_reach_period --from {start} --to {end}")
                all_ok = False
            else:
                cur_reach_rows = read_csv(reach_cur_path)
                base_reach_rows = read_csv(reach_base_path)

        _print_grain_results(
            grain_name, key_cols, cur_rows, base_rows, cur_reach_rows, base_reach_rows,
            primary_goal, all_metrics, currency_sym,
            cur_label, base_label, name_filter,
            args.output if grain_name == "campaign_network_period" else None,
            args.output_account if grain_name == "account_network_period" else None,
        )

    if not all_ok:
        raise SystemExit(1)


def _month_date_range(
    month: int, year: int, full: bool, reference: dt.date
) -> tuple[dt.date, dt.date]:
    """Return (start, end) for a calendar month.

    full=True  → 1st of month to last day of month (or yesterday if current month)
    full=False → MTD: 1st of month to the minimum of (same day-of-month as yesterday, last day of month)
    """
    import calendar as _cal
    first = dt.date(year, month, 1)
    last_day = _cal.monthrange(year, month)[1]
    last = dt.date(year, month, last_day)
    yesterday = reference - dt.timedelta(days=1)
    if full:
        end = min(last, yesterday)
    else:
        target_day = min(yesterday.day, last_day)
        end = dt.date(year, month, target_day)
    return first, end


def compare_months(args: argparse.Namespace) -> None:
    profile = load_profile(required=False)
    primary_goal = args.goal or profile.get("primary_goal") or "in_app_conversions"
    currency_sym = _currency_symbol(profile.get("currency", ""))
    name_filter = (args.name_contains or "").lower()
    all_metrics = getattr(args, "all_metrics", False)
    customer_id = profile.get("google_ads_customer_id")

    ref = today()
    cur_month = args.month or ref.month
    cur_year = args.year or ref.year

    if args.vs:
        base_month = args.vs
        base_year = cur_year if base_month <= cur_month else cur_year - 1
    else:
        base_month = cur_month - 1
        base_year = cur_year
        if base_month < 1:
            base_month = 12
            base_year = cur_year - 1

    cur_start, cur_end = _month_date_range(cur_month, cur_year, args.full, ref)
    base_start, base_end = _month_date_range(base_month, base_year, args.full, ref)

    import calendar as _cal
    cur_label = f"{_cal.month_abbr[cur_month]} {cur_year} ({cur_start}–{cur_end})"
    base_label = f"{_cal.month_abbr[base_month]} {base_year} ({base_start}–{base_end})"
    mode = "full month" if args.full else "MTD"
    print(f"\nMonth comparison ({mode}):  {cur_label}  vs  {base_label}")
    if name_filter:
        print(f"Campaign filter: name contains '{args.name_contains}'")

    grains: list[tuple[str, list[str]]] = []
    if args.grain in ("account", "both"):
        grains.append(("account_network_period", ["customer_id", "customer_name", "network"]))
    if args.grain in ("campaign", "both"):
        grains.append(("campaign_network_period", ["customer_id", "campaign_id", "campaign_name", "campaign_status"]))

    all_ok = True
    for grain_name, key_cols in grains:
        subdir = _NETWORK_PERIOD_SUBDIR[grain_name]
        found = find_processed_files_for_period(subdir, [(cur_start, cur_end), (base_start, base_end)], customer_id)
        cur_path, base_path = found[0], found[1]

        if not cur_path or not base_path:
            all_ok = False
            missing = []
            if not cur_path:
                missing.append(f"{_cal.month_abbr[cur_month]} ({cur_start}–{cur_end})")
            if not base_path:
                missing.append(f"{_cal.month_abbr[base_month]} ({base_start}–{base_end})")
            print(f"\n[{grain_name}] processed files missing for: {', '.join(missing)}")
            print("Fetch and aggregate:")
            for start, end in [(cur_start, cur_end), (base_start, base_end)]:
                print(f"  python3 lib/datapull.py fetch --query {grain_name} --from {start} --to {end}")
            print(f"  python3 lib/datapull.py aggregate --grain {grain_name}")
            continue

        cur_rows = read_csv(cur_path)
        base_rows = read_csv(base_path)
        if not cur_rows or not base_rows:
            empty_sides = []
            if not cur_rows:
                empty_sides.append(cur_label)
            if not base_rows:
                empty_sides.append(base_label)
            print(
                f"\n[{grain_name}] No data for {', '.join(empty_sides)} "
                f"(account {customer_id}). Nothing to compare.",
                file=sys.stderr,
            )
            all_ok = False
            continue

        if grain_name == "campaign_network_period" and name_filter:
            cur_rows = [r for r in cur_rows if name_filter in r.get("campaign_name", "").lower()]
            base_rows = [r for r in base_rows if name_filter in r.get("campaign_name", "").lower()]
            if not cur_rows and not base_rows:
                print(
                    f"\n[{grain_name}] no campaigns matching '{args.name_contains}' in either month.",
                    file=sys.stderr,
                )
                all_ok = False
                continue

        cur_reach_rows = None
        base_reach_rows = None
        if grain_name == "campaign_network_period" and all_metrics:
            reach_found = find_processed_files_for_period(
                _NETWORK_PERIOD_SUBDIR["campaign_reach_period"],
                [(cur_start, cur_end), (base_start, base_end)],
                customer_id,
            )
            reach_cur_path, reach_base_path = reach_found[0], reach_found[1]
            if not reach_cur_path or not reach_base_path:
                missing = []
                if not reach_cur_path:
                    missing.append(f"{cur_label}")
                if not reach_base_path:
                    missing.append(f"{base_label}")
                print(f"\n[campaign_reach_period] processed files missing for: {', '.join(missing)}")
                print("Fetch and aggregate:")
                for start, end in [(cur_start, cur_end), (base_start, base_end)]:
                    print(f"  python3 lib/datapull.py fetch --query campaign_reach_period --from {start} --to {end}")
                    print(f"  python3 lib/datapull.py aggregate --grain campaign_reach_period --from {start} --to {end}")
                all_ok = False
            else:
                cur_reach_rows = read_csv(reach_cur_path)
                base_reach_rows = read_csv(reach_base_path)

        _print_grain_results(
            grain_name, key_cols, cur_rows, base_rows, cur_reach_rows, base_reach_rows,
            primary_goal, all_metrics, currency_sym,
            cur_label, base_label, name_filter,
            args.output if grain_name == "campaign_network_period" else None,
            args.output_account if grain_name == "account_network_period" else None,
        )

    if not all_ok:
        raise SystemExit(1)


def load_mapping(path: str | None) -> dict[str, str]:
    if not path:
        return {}
    mapping_path = Path(path).expanduser()
    if not mapping_path.exists():
        die(f"mapping file not found: {mapping_path}")
    mapping: dict[str, str] = {}
    for raw_line in mapping_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            die(f"invalid mapping line: {raw_line}")
        key, value = line.split(":", 1)
        mapping[key.strip()] = value.strip().strip('"').strip("'")
    return mapping


def indexed(rows: list[dict[str, str]], grain: str) -> dict[str, dict[str, str]]:
    output: dict[str, dict[str, str]] = {}
    for row in rows:
        key = row.get(grain)
        if key:
            output[key] = row
    return output


def compare_status(metric: str, bob: float, manual: float, diff: float) -> tuple[str, float | str]:
    mode, threshold = DEFAULT_TOLERANCES.get(metric, ("relative", 0.1))
    if mode == "absolute":
        value = abs(diff)
        return ("pass" if value <= threshold else "fail", value)
    if manual == 0:
        value = 0 if bob == 0 else math.inf
        return ("pass" if bob == 0 else "fail", value)
    value = abs(diff / manual * 100)
    return ("pass" if value <= threshold else "fail", value)


def likely_causes(failed_metrics: set[str]) -> list[str]:
    causes: list[str] = []
    traffic = {"impressions", "clicks"}
    conversions = {"installs", "in_app_conversions", "cti_percent", "conversion_rate_percent"}
    if failed_metrics & conversions and not (failed_metrics & traffic):
        causes.append("Conversion action inclusion, biddable-vs-all conversion choice, or conversion lag.")
    if "cost" in failed_metrics and not (failed_metrics & traffic):
        causes.append("Cost unit, currency, or manual export rounding.")
    if failed_metrics & traffic:
        causes.append("Date range, timezone, customer ID, campaign type, or campaign status filter mismatch.")
    if not causes and failed_metrics:
        causes.append("Column mapping, rounding, or manual export formatting mismatch.")
    return causes


def validate_manual(args: argparse.Namespace) -> None:
    bob_path = Path(args.bob).expanduser()
    manual_path = Path(args.manual).expanduser()
    if not bob_path.exists():
        die(f"Bob aggregate not found: {bob_path}")
    if not manual_path.exists():
        die(f"manual aggregate not found: {manual_path}")

    mapping = load_mapping(args.mapping)
    grain = args.grain
    bob_rows = indexed(read_csv(bob_path), grain)
    manual_rows_raw = read_csv(manual_path)
    manual_rows: dict[str, dict[str, str]] = {}
    manual_grain = mapping.get(grain, grain)
    for row in manual_rows_raw:
        key = row.get(manual_grain)
        if key:
            manual_rows[key] = row

    metrics = [m for m in ACCOUNT_DAILY_COLUMNS if m != grain]
    comparison_rows: list[dict[str, Any]] = []
    failed: set[str] = set()

    for key in sorted(set(bob_rows) | set(manual_rows)):
        bob_row = bob_rows.get(key, {})
        manual_row = manual_rows.get(key, {})
        for metric in metrics:
            manual_col = mapping.get(metric, metric)
            if metric not in bob_row or manual_col not in manual_row:
                continue
            bob_value = number(bob_row.get(metric))
            manual_value = number(manual_row.get(manual_col))
            diff = bob_value - manual_value
            status, tolerance_value = compare_status(metric, bob_value, manual_value, diff)
            if status != "pass":
                failed.add(metric)
            rel = "NA" if manual_value == 0 else format_float(diff / manual_value * 100)
            comparison_rows.append(
                {
                    grain: key,
                    "metric": metric,
                    "bob_value": format_float(bob_value),
                    "manual_value": format_float(manual_value),
                    "absolute_diff": format_float(diff),
                    "relative_diff_percent": rel,
                    "tolerance_check_value": "inf" if tolerance_value == math.inf else format_float(float(tolerance_value)),
                    "status": status,
                }
            )

    if args.output_prefix:
        prefix = Path(args.output_prefix).expanduser()
    else:
        prefix = REPORTS_DIR / f"{bob_path.stem}_validation"
    csv_path = prefix.with_suffix(".csv")
    md_path = prefix.with_suffix(".md")
    fields = [
        grain, "metric", "bob_value", "manual_value",
        "absolute_diff", "relative_diff_percent", "tolerance_check_value", "status",
    ]
    write_csv(csv_path, comparison_rows, fields)
    write_validation_md(md_path, bob_path, manual_path, comparison_rows, failed, grain)
    print(f"validation CSV written: {csv_path}")
    print(f"validation report written: {md_path}")
    if failed:
        print(f"validation failed metrics: {', '.join(sorted(failed))}")
        raise SystemExit(2)
    print("validation passed")


def check_config(args: argparse.Namespace) -> None:
    profile = load_profile(required=False)
    migration_notes = [] if args.config else _normalize_account_config_files(profile)
    config = args.config or _profile_read_config_value(profile)
    if not config:
        die("I need the Google Ads developer token from Google Ads > Admin > API Center before I can fetch data from Google Ads.")
    config_path = Path(config).expanduser()
    if not config_path.exists():
        die(f"Google Ads GARF config not found: {config_path}\nExpected at {config_path} — create it or set google_ads_read_config_path in your account profile (.bob/accounts/<id>/profile.json)")
    text = config_path.read_text()
    keys = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        keys[key.strip()] = value.strip().strip("\"'")

    if migration_notes:
        for note in migration_notes:
            print(f"updated: {note}")

    # GARF read config — no OAuth client credentials required
    expected = ["developer_token", "login_customer_id"]
    print(f"GARF read config: {config_path}")
    for key in expected:
        value = keys.get(key, "")
        if not value:
            print(f"{key}: MISSING")
        elif key == "login_customer_id":
            normalized = value.replace("-", "")
            shape = "SET_WITH_HYPHENS" if "-" in value else "SET"
            print(f"{key}: {shape} length={len(normalized)}")
        else:
            print(f"{key}: SET")
    account = str(args.account or profile.get("google_ads_customer_id") or "").replace("-", "")
    print(f"target_customer_id: {'SET length=' + str(len(account)) if account else 'MISSING'}")
    if keys.get("login_customer_id") and account and keys["login_customer_id"].replace("-", "") == account:
        print("note: login_customer_id equals target_customer_id; omit login_customer_id unless this is a manager account.")

    write_path = _resolve_profile_config_path(profile, write=True)
    write_config = str(profile.get("google_ads_write_config_path", "") or "").strip()
    if write_config or write_path.exists():
        print(f"\nwrite config (bid-budget-apply): {write_path}")
        if not write_path.exists():
            print("  STATUS: FILE NOT FOUND")
            print("  Run this to generate write credentials (one-time OAuth2 flow):")
            print("    python3 lib/datapull.py setup-write-credentials")
            print("  The command prints a single-line OAuth URL. Open it in your browser to authorize.")
            print("  Once authorized, the file is saved automatically and bid-budget-apply will work.")
        else:
            wtext = write_path.read_text()
            wkeys: dict = {}
            for raw_line in wtext.splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or ":" not in line:
                    continue
                k, v = line.split(":", 1)
                wkeys[k.strip()] = v.strip().strip("\"'")
            for key in ["developer_token", "client_id", "client_secret", "refresh_token", "login_customer_id"]:
                val = wkeys.get(key, "")
                if not val:
                    print(f"  {key}: MISSING")
                elif key == "login_customer_id":
                    normalized = val.replace("-", "")
                    print(f"  {key}: SET length={len(normalized)}")
                else:
                    print(f"  {key}: SET")


def write_validation_md(
    path: Path,
    bob_path: Path,
    manual_path: Path,
    rows: list[dict[str, Any]],
    failed: set[str],
    grain: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    total = len(rows)
    failures = sum(1 for row in rows if row["status"] != "pass")
    lines = [
        "# Manual Validation Report",
        "",
        f"- Bob aggregate: `{bob_path}`",
        f"- Manual aggregate: `{manual_path}`",
        f"- Grain: `{grain}`",
        f"- Checks: {total}",
        f"- Failures: {failures}",
        "",
        "## Status",
        "",
        "PASS" if failures == 0 else "FAIL",
        "",
    ]
    if failed:
        lines.extend(["## Failed Metrics", ""])
        for metric in sorted(failed):
            lines.append(f"- `{metric}`")
        lines.extend(["", "## Likely Causes", ""])
        for cause in likely_causes(failed):
            lines.append(f"- {cause}")
        lines.append("")

    lines.extend([
        "## Largest Differences",
        "",
        "| Grain | Metric | Bob | Manual | Diff | Rel Diff % | Status |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ])
    for row in sorted(rows, key=lambda r: abs(number(r["absolute_diff"])), reverse=True)[:25]:
        lines.append(
            f"| {row[grain]} | {row['metric']} | {row['bob_value']} | {row['manual_value']} | "
            f"{row['absolute_diff']} | {row['relative_diff_percent']} | {row['status']} |"
        )
    lines.append("")
    path.write_text("\n".join(lines))


def newest_processed(subdir: str, customer_id: str | None = None) -> Path:
    proc_dir = _resolve_processed_dir(subdir, customer_id)
    files = sorted(proc_dir.glob("*.csv"), key=lambda p: p.stem.split("_")[1] if len(p.stem.split("_")) >= 2 else "", reverse=True)
    if not files:
        die(f"no processed file found in {proc_dir}")
    return files[0]


def bid_budget_recommend(args: argparse.Namespace) -> None:
    profile = load_profile(required=False)
    primary_goal = args.goal or profile.get("primary_goal") or "in_app_conversions"
    cac_ceiling = float(args.cac_ceiling or profile.get("cac_ceiling", 200))
    change_pct = min(float(args.change_pct or profile.get("bid_budget_change_pct", 10)), 20)
    min_installs = 10
    budget_constrained_threshold = 0.90
    cpm_tolerance = 1.05
    cooldown_days = int(profile.get("bid_budget_cooldown_days", 14))

    customer_id = profile.get("google_ads_customer_id")
    # Load trend file (most recent campaign-trend processed CSV)
    if args.trend:
        trend_path = Path(args.trend).expanduser()
    else:
        trend_path = newest_processed("campaign-trend", customer_id)
    trend_rows = read_csv(trend_path)

    # Load bid_budget_inputs (most recent raw)
    if args.bid_budget:
        bb_path = Path(args.bid_budget).expanduser()
    else:
        bb_path = newest_raw("bid_budget_inputs")
    bb_rows = read_csv(bb_path)

    # Index bid_budget_inputs by campaign_id (sum cost over 7 days per campaign)
    bb_index: dict[str, dict] = {}
    for row in bb_rows:
        cid = str(row.get("campaign_id", "")).replace("-", "")
        if cid not in bb_index:
            bb_index[cid] = dict(row)
            bb_index[cid]["_total_cost"] = 0.0
        bb_index[cid]["_total_cost"] += number(row.get("cost", 0))

    # Build cooldown index from change_history: last CAMPAIGN/CAMPAIGN_BUDGET update per campaign
    ch_index: dict[str, str] = {}  # campaign_id → most recent change date (ISO)
    ch_path = newest_raw("change_history") if True else None
    try:
        if ch_path and ch_path.exists():
            for row in read_csv(ch_path):
                cid = str(row.get("campaign_id", "")).replace("-", "")
                rtype = row.get("change_resource_type", "").upper()
                op = row.get("operation", "").upper()
                changed_at = (row.get("changed_at", "") or "")[:10]
                if cid and op == "UPDATE" and rtype in ("CAMPAIGN", "CAMPAIGN_BUDGET") and changed_at:
                    if cid not in ch_index or changed_at > ch_index[cid]:
                        ch_index[cid] = changed_at
    except Exception:
        pass  # change_history is informational; don't block recommend if unavailable

    today_str = today().isoformat()
    cooldown_cutoff = (today() - dt.timedelta(days=cooldown_days)).isoformat()

    changes: list[dict] = []
    holds: list[dict] = []
    skipped: list[dict] = []

    for row in trend_rows:
        cid = str(row.get("campaign_id", "")).replace("-", "")
        cname = row.get("campaign_name", "")
        cstatus = row.get("campaign_status", "")

        # Detect which ISO weeks are present
        try:
            w0_iso = int(row.get("current_iso_week", 0))
            w1_iso = int(row.get("prior1_iso_week", 0))
            w2_iso = int(row.get("prior2_iso_week", 0))
        except (ValueError, TypeError):
            skipped.append({"campaign_id": cid, "campaign_name": cname, "reason": "could not read ISO week columns"})
            continue

        def _w(iso: int, col: str) -> str:
            return row.get(f"w{iso}_{col}", "0") or "0"

        w0_cost = number(_w(w0_iso, "cost"))
        w0_inst = number(_w(w0_iso, "installs"))
        w0_imp = number(_w(w0_iso, "impressions"))
        w0_conv = number(_w(w0_iso, "in_app_conversions"))
        w1_cost = number(_w(w1_iso, "cost"))
        w1_inst = number(_w(w1_iso, "installs"))
        w1_imp = number(_w(w1_iso, "impressions"))
        w1_conv = number(_w(w1_iso, "in_app_conversions"))
        w2_cost = number(_w(w2_iso, "cost"))
        w2_inst = number(_w(w2_iso, "installs"))
        w2_imp = number(_w(w2_iso, "impressions"))

        # CPI = cost / installs
        w0_cpi = w0_cost / w0_inst if w0_inst > 0 else 0.0
        w1_cpi = w1_cost / w1_inst if w1_inst > 0 else 0.0
        w2_cpi = w2_cost / w2_inst if w2_inst > 0 else 0.0
        ref_cpi = (w1_cpi + w2_cpi) / 2 if (w1_cpi > 0 and w2_cpi > 0) else 0.0

        # CPM = cost / impressions * 1000
        w0_cpm = w0_cost / w0_imp * 1000 if w0_imp > 0 else 0.0
        w1_cpm = w1_cost / w1_imp * 1000 if w1_imp > 0 else 0.0
        w2_cpm = w2_cost / w2_imp * 1000 if w2_imp > 0 else 0.0
        ref_cpm = (w1_cpm + w2_cpm) / 2 if (w1_cpm > 0 and w2_cpm > 0) else 0.0

        # Post-install conversion rate (in_app / installs) for declining conv% guard
        w0_conv_rate = w0_conv / w0_inst * 100 if w0_inst > 0 and w0_conv > 0 else 0.0
        w1_conv_rate = w1_conv / w1_inst * 100 if w1_inst > 0 and w1_conv > 0 else 0.0
        conv_rate_declining = (
            w0_conv_rate > 0 and w1_conv_rate > 0
            and w0_conv_rate < w1_conv_rate * 0.95  # >5% drop in conv%
        )

        # Read bid_budget_inputs for this campaign early — needed by CAC guard
        bb = bb_index.get(cid, {})
        target_cpa_bid = number(bb.get("target_cpa", 0))

        # CPA for CAC guard: use actual W0 CPA if available; fall back to target_cpa bid
        w0_cpa = w0_cost / w0_conv if w0_conv > 0 else 0.0
        if w0_cpa > 0:
            cac_ok = w0_cpa <= cac_ceiling
        elif target_cpa_bid > 0:
            cac_ok = target_cpa_bid <= cac_ceiling  # bid above ceiling = skip
        else:
            cac_ok = False  # no conversion data and no bid → skip

        # Volume guard
        vol_ok = w0_inst >= min_installs

        # Cooldown guard: skip if campaign was changed within cooldown_days
        last_change = ch_index.get(cid, "")
        cooldown_ok = not last_change or last_change < cooldown_cutoff
        days_since_change = (
            (dt.date.fromisoformat(today_str) - dt.date.fromisoformat(last_change)).days
            if last_change else None
        )

        cpi_pct = (w0_cpi - ref_cpi) / ref_cpi * 100 if ref_cpi > 0 else 0.0
        cpm_pct = (w0_cpm - ref_cpm) / ref_cpm * 100 if ref_cpm > 0 else 0.0

        base_info = {
            "customer_id": row.get("customer_id", ""),
            "campaign_id": cid,
            "campaign_name": cname,
            "campaign_status": cstatus,
            "current_iso_week": w0_iso,
            "w0_cpi": format_float(w0_cpi),
            "ref_cpi": format_float(ref_cpi),
            "cpi_pct_vs_ref": format_float(cpi_pct),
            "w0_cpm": format_float(w0_cpm),
            "ref_cpm": format_float(ref_cpm),
            "cpm_pct_vs_ref": format_float(cpm_pct),
            "w0_cpa": format_float(w0_cpa),
            "cac_ceiling": format_float(cac_ceiling),
            "cac_guard_passed": str(cac_ok),
            "w0_installs": format_float(w0_inst),
            "min_installs_met": str(vol_ok),
            "last_bid_budget_change_date": last_change or "unknown",
            "days_since_last_change": str(days_since_change) if days_since_change is not None else "unknown",
            "cooldown_days": str(cooldown_days),
            "cooldown_ok": str(cooldown_ok),
        }

        if not vol_ok:
            skipped.append({"campaign_id": cid, "campaign_name": cname,
                            "reason": f"W{w0_iso} installs {w0_inst:.0f} below minimum {min_installs}"})
            continue
        if not cac_ok:
            skipped.append({"campaign_id": cid, "campaign_name": cname,
                            "reason": f"W{w0_iso} CPA {w0_cpa:.2f} exceeds CAC ceiling {cac_ceiling:.0f}"})
            continue
        if not cooldown_ok:
            skipped.append({"campaign_id": cid, "campaign_name": cname,
                            "reason": f"changed {days_since_change}d ago ({last_change}) — within {cooldown_days}-day cooldown"})
            continue
        if ref_cpi == 0:
            skipped.append({"campaign_id": cid, "campaign_name": cname,
                            "reason": "insufficient prior-week data for CPI reference"})
            continue

        # Budget utilization (bb already read above for CAC guard)
        daily_budget = number(bb.get("daily_budget", 0))
        target_cpa = target_cpa_bid
        budget_id = bb.get("campaign_budget_id", "")
        actual_7d_cost = bb.get("_total_cost", w0_cost)
        utilization = actual_7d_cost / (daily_budget * 7) if daily_budget > 0 else 0.0
        budget_const = utilization >= budget_constrained_threshold

        base_info["budget_utilization_pct"] = format_float(utilization * 100)
        base_info["budget_constrained"] = str(budget_const)
        base_info["w0_conv_rate_pct"] = format_float(round(w0_conv_rate, 2))
        base_info["w1_conv_rate_pct"] = format_float(round(w1_conv_rate, 2))
        base_info["conv_rate_declining"] = str(conv_rate_declining)
        base_info["current_target_cpa"] = format_float(target_cpa)
        base_info["current_daily_budget"] = format_float(daily_budget)
        base_info["campaign_budget_id"] = budget_id

        cpi_lower = w0_cpi < ref_cpi
        cpm_lower_or_same = w0_cpm <= ref_cpm * cpm_tolerance

        if cpi_lower and cpm_lower_or_same:
            # Conv% declining overrides any increase — more volume won't convert
            if conv_rate_declining:
                holds.append({**base_info,
                              "reason": (f"CPI efficient but post-install conv% declining "
                                         f"({w1_conv_rate:.1f}%% → {w0_conv_rate:.1f}%%) — "
                                         f"more installs won't convert until quality improves; hold")})
                continue
            if budget_const:
                action = "increase_bid_and_budget"
                rationale = (f"W{w0_iso} CPI {w0_cpi:.2f} is {abs(cpi_pct):.1f}%% below ref, "
                             f"CPM flat/lower, budget constrained — scale bid+budget")
            else:
                action = "increase_bid"
                rationale = (f"W{w0_iso} CPI {w0_cpi:.2f} is {abs(cpi_pct):.1f}%% below ref, "
                             f"CPM flat/lower, budget headroom available — scale bid")
            forecast = f"Higher spend and volume; CPI may edge up slightly toward target"
        elif cpi_lower and not cpm_lower_or_same:
            holds.append({**base_info,
                          "reason": f"CPM rising {cpm_pct:.1f}%% — CPI improvement is likely temporary; hold"})
            continue
        elif not cpi_lower and cpm_lower_or_same:
            holds.append({**base_info,
                          "reason": f"CPI worsening but CPM improving {abs(cpm_pct):.1f}%% — buying getting cheaper; wait"})
            continue
        else:
            if budget_const:
                action = "decrease_bid_and_budget"
                rationale = (f"W{w0_iso} CPI {w0_cpi:.2f} is {abs(cpi_pct):.1f}%% above ref, "
                             f"CPM also up, budget constrained — protect efficiency")
            else:
                action = "decrease_bid"
                rationale = (f"W{w0_iso} CPI {w0_cpi:.2f} is {abs(cpi_pct):.1f}%% above ref, "
                             f"CPM also up — tighten bid to protect CPI")
            forecast = f"Lower spend and volume; CPI should improve toward target"

        new_tgt = new_bgt = None
        if "bid" in action and target_cpa > 0:
            new_tgt = target_cpa * (1 + change_pct / 100) if "increase" in action else target_cpa * (1 - change_pct / 100)
        if "budget" in action and daily_budget > 0:
            new_bgt = daily_budget * (1 + change_pct / 100) if "increase" in action else daily_budget * (1 - change_pct / 100)

        changes.append({
            **base_info,
            "action": action,
            "rationale": rationale,
            "forecast": forecast,
            "proposed_target_cpa": format_float(new_tgt) if new_tgt else "",
            "proposed_daily_budget": format_float(new_bgt) if new_bgt else "",
        })

    # Print summary
    current_iso = trend_rows[0].get("current_iso_week", "?") if trend_rows else "?"
    print(f"\nBid/Budget Recommendations — W{current_iso}")
    print(f"  {len(changes)} changes  |  {len(holds)} holds  |  {len(skipped)} skipped\n")
    if changes:
        hdr = f"  {'Campaign':<45}  {'Action':<26}  {'Cur tCPA':>10}  {'New tCPA':>10}  {'Cur Bgt':>10}  {'New Bgt':>10}"
        print(hdr)
        print("  " + "─" * (len(hdr) - 2))
        for c in changes:
            print(
                f"  {c['campaign_name']:<45}  {c['action']:<26}  "
                f"{_fmt_display(c['current_target_cpa'], 'cost', _currency_symbol(profile.get('currency', '')))  :>10}  "
                f"{_fmt_display(c.get('proposed_target_cpa', 'NA'), 'cost', _currency_symbol(profile.get('currency', ''))):>10}  "
                f"{_fmt_display(c['current_daily_budget'], 'cost', _currency_symbol(profile.get('currency', ''))):>10}  "
                f"{_fmt_display(c.get('proposed_daily_budget', 'NA'), 'cost', _currency_symbol(profile.get('currency', ''))):>10}"
            )

    if args.dry_run:
        print("\n[dry-run] no files written")
        return

    # Write CSV
    customer = customer_id or "unknown"
    date_str = today().isoformat()
    csv_path = Path(args.output).expanduser() if args.output else (
        account_processed_dir(customer, "bid-budget-recs") / f"{customer}_{date_str}.csv"
    )
    all_rows = [{**c, **{k: "" for k in BID_BUDGET_REC_COLUMNS if k not in c}} for c in changes]
    write_csv(csv_path, all_rows, BID_BUDGET_REC_COLUMNS)
    print(f"\nrecommendation CSV written: {csv_path}")

    # Write YAML plan
    wiki_base = account_wiki_dir(customer) if customer != "unknown" else ROOT / "wiki"
    yaml_path = Path(args.yaml_output).expanduser() if args.yaml_output else (
        wiki_base / "action-items" / f"bid-budget-{date_str}.yaml"
    )
    yaml_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        import yaml as _yaml
        plan = {
            "generated": date_str,
            "customer_id": str(customer).replace("-", ""),
            "current_iso_week": int(current_iso) if str(current_iso).isdigit() else current_iso,
            "signal_basis": f"W{current_iso} CPI vs avg(prior 2 weeks)",
            "cac_ceiling": cac_ceiling,
            "change_pct": change_pct,
            "cooldown_days": cooldown_days,
            "changes": [
                {
                    "campaign_id": c["campaign_id"],
                    "campaign_name": c["campaign_name"],
                    "action": c["action"],
                    "field": "target_cpa" if "bid" in c["action"] else "daily_budget",
                    "current_target_cpa": number(c["current_target_cpa"]),
                    "proposed_target_cpa": number(c["proposed_target_cpa"]) if c.get("proposed_target_cpa") else None,
                    "current_daily_budget": number(c["current_daily_budget"]),
                    "proposed_daily_budget": number(c["proposed_daily_budget"]) if c.get("proposed_daily_budget") else None,
                    "campaign_budget_id": c.get("campaign_budget_id", ""),
                    "w0_cpi": number(c["w0_cpi"]),
                    "ref_cpi": number(c["ref_cpi"]),
                    "w0_cpm": number(c["w0_cpm"]),
                    "ref_cpm": number(c["ref_cpm"]),
                    "w0_conv_rate_pct": number(c.get("w0_conv_rate_pct", 0)),
                    "w1_conv_rate_pct": number(c.get("w1_conv_rate_pct", 0)),
                    "conv_rate_declining": c.get("conv_rate_declining", "False") == "True",
                    "last_bid_budget_change_date": c.get("last_bid_budget_change_date", "unknown"),
                    "days_since_last_change": c.get("days_since_last_change", "unknown"),
                    "cooldown_ok": c.get("cooldown_ok", "True") == "True",
                    "rationale": c["rationale"],
                    "forecast": c["forecast"],
                    "cac_guard_passed": c["cac_guard_passed"] == "True",
                }
                for c in changes
            ],
            "skipped": [{"campaign_id": s["campaign_id"], "campaign_name": s["campaign_name"], "reason": s["reason"]} for s in skipped],
            "applied": False,
            "applied_at": None,
            "applied_by": None,
        }
        yaml_path.write_text(_yaml.dump(plan, default_flow_style=False, allow_unicode=True, sort_keys=False))
        print(f"mutation plan written: {yaml_path}")
    except ImportError:
        print("note: pyyaml not installed — YAML plan not written. Run: pip install pyyaml")


def bid_budget_apply(args: argparse.Namespace) -> None:
    try:
        import yaml as _yaml
    except ImportError:
        die("pyyaml is required. Install: pip install pyyaml")

    plan_path = Path(args.plan).expanduser()
    if not plan_path.exists():
        die(f"plan file not found: {plan_path}")

    plan = _yaml.safe_load(plan_path.read_text())
    retry_fields: set[tuple[str, str]] | None = None
    if plan.get("applied"):
        prior_errors = [
            r for r in plan.get("apply_results", [])
            if r.get("status") == "error" and r.get("campaign") and r.get("field")
        ]
        if not prior_errors:
            die(f"plan already applied on {plan['applied_at']} by {plan['applied_by']}")
        retry_fields = {(r["campaign"], r["field"]) for r in prior_errors}
        print(f"retrying {len(retry_fields)} failed mutation(s) from partial apply")

    if not plan.get("changes"):
        print("no changes in plan — nothing to apply")
        return

    try:
        from google.ads.googleads.client import GoogleAdsClient  # type: ignore
        from google.protobuf.field_mask_pb2 import FieldMask  # type: ignore
    except ImportError:
        die("google-ads library is required. Install: pip install google-ads")

    profile = load_profile(required=False)
    config_path = str(_resolve_profile_config_path(profile, write=True))
    customer_id = str(plan.get("customer_id", profile.get("google_ads_customer_id", ""))).replace("-", "")

    try:
        client = GoogleAdsClient.load_from_storage(config_path)
    except Exception as exc:
        die(f"failed to load Google Ads client: {exc}")

    results: list[dict] = []
    campaign_ops: list = []
    budget_ops: list = []
    campaign_ids_for_budget: list[tuple] = []

    campaign_service = client.get_service("CampaignService")
    budget_service = client.get_service("CampaignBudgetService")

    for change in plan["changes"]:
        cid = str(change["campaign_id"])
        cname = change["campaign_name"]
        action = change["action"]

        if retry_fields is None or (cname, "target_cpa") in retry_fields:
            should_apply_bid = "bid" in action and change.get("proposed_target_cpa")
        else:
            should_apply_bid = False

        if retry_fields is None or (cname, "daily_budget") in retry_fields:
            should_apply_budget = (
                "budget" in action
                and change.get("proposed_daily_budget")
                and change.get("campaign_budget_id")
            )
        else:
            should_apply_budget = False

        if should_apply_bid:
            op = client.get_type("CampaignOperation")
            camp = op.update
            camp.resource_name = campaign_service.campaign_path(customer_id, cid)
            camp.target_cpa.target_cpa_micros = int(float(change["proposed_target_cpa"]) * 1_000_000)
            field_mask = FieldMask()
            field_mask.paths.append("target_cpa.target_cpa_micros")
            op.update_mask.CopyFrom(field_mask)
            campaign_ops.append((cname, cid, "target_cpa", change["proposed_target_cpa"], op))

        if should_apply_budget:
            op = client.get_type("CampaignBudgetOperation")
            bgt = op.update
            bgt.resource_name = budget_service.campaign_budget_path(customer_id, str(change["campaign_budget_id"]))
            budget_amount = int(round(float(change["proposed_daily_budget"])))
            bgt.amount_micros = budget_amount * 1_000_000
            field_mask = FieldMask()
            field_mask.paths.append("amount_micros")
            op.update_mask.CopyFrom(field_mask)
            budget_ops.append((cname, cid, "daily_budget", budget_amount, op))

    # Apply campaign (Target CPA) mutations
    if campaign_ops:
        try:
            response = campaign_service.mutate_campaigns(
                customer_id=customer_id,
                operations=[op for _, _, _, _, op in campaign_ops],
            )
            for (cname, cid, field, val, _), result in zip(campaign_ops, response.results):
                results.append({"campaign": cname, "field": field, "value": val, "status": "ok", "resource": result.resource_name})
                print(f"  ✓ {cname} — target_cpa → {val}")
        except Exception as exc:
            for cname, cid, field, val, _ in campaign_ops:
                results.append({"campaign": cname, "field": field, "value": val, "status": "error", "error": str(exc)})
            print(f"  ✗ campaign mutations failed: {exc}")

    # Apply budget mutations
    if budget_ops:
        try:
            response = budget_service.mutate_campaign_budgets(
                customer_id=customer_id,
                operations=[op for _, _, _, _, op in budget_ops],
            )
            for (cname, cid, field, val, _), result in zip(budget_ops, response.results):
                results.append({"campaign": cname, "field": field, "value": val, "status": "ok", "resource": result.resource_name})
                print(f"  ✓ {cname} — daily_budget → {val}")
        except Exception as exc:
            for cname, cid, field, val, _ in budget_ops:
                results.append({"campaign": cname, "field": field, "value": val, "status": "error", "error": str(exc)})
            print(f"  ✗ budget mutations failed: {exc}")

    prior_results = plan.get("apply_results", [])
    if retry_fields:
        results = [
            r for r in prior_results
            if (r.get("campaign"), r.get("field")) not in retry_fields
        ] + results

    errors = [r for r in results if r.get("status") == "error"]

    # Mark plan as applied only when every requested mutation has succeeded.
    import datetime as _dt
    plan["applied"] = not errors
    plan["applied_at"] = _dt.datetime.now().isoformat(timespec="seconds")
    plan["applied_by"] = "bid-budget-apply"
    plan["apply_results"] = results
    plan_path.write_text(_yaml.dump(plan, default_flow_style=False, allow_unicode=True, sort_keys=False))
    state = "applied" if plan["applied"] else "partially applied"
    print(f"\nplan marked {state}: {plan_path}")

    if errors:
        print(f"{len(errors)} mutation(s) failed — see plan file for details")
        raise SystemExit(2)


def bid_budget_retrospective(args: argparse.Namespace) -> None:
    try:
        import yaml as _yaml
    except ImportError:
        die("pyyaml is required. Install: pip install pyyaml")

    plan_path = Path(args.plan).expanduser()
    if not plan_path.exists():
        die(f"plan file not found: {plan_path}")
    plan = _yaml.safe_load(plan_path.read_text())

    if not plan.get("applied"):
        die("plan has not been applied yet — nothing to evaluate")

    applied_date = dt.date.fromisoformat(plan["applied_at"][:10])
    cal = applied_date.isocalendar()
    base_week, base_year = cal.week, cal.year

    # Find W+1 and W+2 processed campaign-network files
    w1_start, w1_end = iso_week_to_dates(base_week, base_year)
    w2_week = base_week + 1
    w2_year = base_year
    if w2_week > dt.date(base_year, 12, 28).isocalendar().week:
        w2_week = 1
        w2_year = base_year + 1
    w2_start, w2_end = iso_week_to_dates(w2_week, w2_year)

    profile = load_profile(required=False)
    retro_customer_id = profile.get("google_ads_customer_id")
    found = find_processed_files_for_period("campaign-network", [(w1_start, w1_end), (w2_start, w2_end)], retro_customer_id)
    w1_path, w2_path = found[0], found[1]

    if not w1_path:
        print(f"\nW+1 data not yet available (need {w1_start}–{w1_end})")
        print(f"Run: python3 lib/datapull.py fetch --query campaign_network_period --from {w1_start} --to {w1_end}")
        print("     python3 lib/datapull.py aggregate --grain campaign_network_period")
        print("\nToo early to evaluate — check back after W+1 data is available.")
        return

    primary_goal = profile.get("primary_goal") or "in_app_conversions"
    w1_rows = read_csv(w1_path)
    w2_rows = read_csv(w2_path) if w2_path else []

    def _cpi_from_rows(rows: list[dict], cid: str) -> float:
        for r in rows:
            if str(r.get("campaign_id", "")).replace("-", "") == cid:
                cost = number(r.get("cost", 0))
                inst = number(r.get("installs", 0))
                return cost / inst if inst > 0 else 0.0
        return 0.0

    verdicts: list[dict] = []
    for change in plan.get("changes", []):
        cid = str(change["campaign_id"])
        cname = change["campaign_name"]
        action = change["action"]
        baseline_cpi = float(change.get("w0_cpi", 0) or 0)
        expected = "lower" if "increase" in action else "higher"

        w1_cpi = _cpi_from_rows(w1_rows, cid)
        w2_cpi = _cpi_from_rows(w2_rows, cid) if w2_rows else 0.0

        w1_moved = (w1_cpi < baseline_cpi) if expected == "lower" else (w1_cpi > baseline_cpi)
        w2_moved = (w2_cpi < baseline_cpi) if expected == "lower" else (w2_cpi > baseline_cpi)

        if w2_cpi > 0 and w1_moved and w2_moved:
            verdict = "working"
        elif not w2_path or w2_cpi == 0:
            verdict = "too_early"
        else:
            verdict = "not_working"

        verdicts.append({
            "campaign": cname,
            "action": action,
            "baseline_cpi": baseline_cpi,
            "w1_cpi": w1_cpi,
            "w2_cpi": w2_cpi if w2_cpi > 0 else None,
            "expected": expected,
            "verdict": verdict,
        })

    sym = _currency_symbol(profile.get("currency", ""))
    total = len(verdicts)
    working = sum(1 for v in verdicts if v["verdict"] == "working")
    early = sum(1 for v in verdicts if v["verdict"] == "too_early")
    not_wk = sum(1 for v in verdicts if v["verdict"] == "not_working")

    print(f"\nBid/Budget Retrospective — changes applied {plan['applied_at'][:10]}")
    print(f"  {working}/{total} working  |  {early} too early  |  {not_wk} not working\n")

    hdr = f"  {'Campaign':<45}  {'Action':<26}  {'Baseline CPI':>12}  {'W+1 CPI':>10}  {'W+2 CPI':>10}  {'Verdict':<12}"
    print(hdr)
    print("  " + "─" * (len(hdr) - 2))
    for v in verdicts:
        w2_str = _fmt_display(v["w2_cpi"], "cost", sym) if v["w2_cpi"] else "—"
        print(
            f"  {v['campaign']:<45}  {v['action']:<26}  "
            f"{_fmt_display(v['baseline_cpi'], 'cost', sym):>12}  "
            f"{_fmt_display(v['w1_cpi'], 'cost', sym):>10}  "
            f"{w2_str:>10}  "
            f"{v['verdict']:<12}"
        )


def slice_creatives(args: argparse.Namespace) -> None:
    """Filter creative processed CSV to LOW-label assets, flag Low-Action, show patterns."""
    profile = load_profile(required=False)
    min_imp = float(getattr(args, "min_impressions", None) or profile.get("creative_min_impressions", 50000))
    primary_goal = profile.get("primary_goal", "in_app_conversions")
    currency = _currency_symbol(profile.get("currency", ""))
    customer_id = profile.get("google_ads_customer_id")

    creative_path = newest_processed("creative", customer_id)
    rows = read_csv(creative_path)
    if not rows:
        print(
            f"No creative data in {creative_path.name} (account {customer_id}). "
            f"Nothing to slice.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    # Step 1: filter to min impressions only
    eligible = [r for r in rows if number(r.get("impressions", 0)) >= min_imp]
    # Step 2: filter to LOW label only
    low_rows = [r for r in eligible if r.get("performance_label", "").upper() == "LOW"]

    if not low_rows:
        print(f"No LOW-label creatives above {min_imp:.0f} minimum impressions.")
        return

    # Build per-(campaign, asset_type) aggregates so text/video/image are compared fairly
    conv_col = "in_app_conversions" if primary_goal == "in_app_conversions" else "installs"
    camp_agg: dict[tuple, dict] = {}
    for r in eligible:
        key = (r.get("campaign_name", ""), r.get("asset_type", ""))
        if key not in camp_agg:
            camp_agg[key] = {"imp": 0.0, "clicks": 0.0, "installs": 0.0, "cost": 0.0}
        camp_agg[key]["imp"] += number(r.get("impressions", 0))
        camp_agg[key]["clicks"] += number(r.get("clicks", 0))
        camp_agg[key]["installs"] += number(r.get("installs", 0))
        camp_agg[key]["cost"] += number(r.get("cost", 0))

    for m in camp_agg.values():
        m["ctr"] = m["clicks"] / m["imp"] * 100 if m["imp"] > 0 else 0.0
        m["cti"] = m["installs"] / m["clicks"] * 100 if m["clicks"] > 0 else 0.0
        m["cpc"] = m["cost"] / m["clicks"] if m["clicks"] > 0 else 0.0

    # Count assets per (campaign, asset_type) so we know when comparison is meaningful
    type_counts_per_camp: dict[tuple, int] = {}
    for r in eligible:
        key = (r.get("campaign_name", ""), r.get("asset_type", ""))
        type_counts_per_camp[key] = type_counts_per_camp.get(key, 0) + 1

    # Flag each LOW creative: low-action = 2+ metrics worse than campaign+asset_type avg
    results = []
    for r in low_rows:
        cname = r.get("campaign_name", "")
        atype = r.get("asset_type", "")
        cm = camp_agg.get((cname, atype), {})

        asset_ctr = number(r.get("ctr_percent", 0))
        asset_cti = number(r.get("cti_percent", 0))
        asset_cpc = number(r.get("cpc", 0))

        worse_ctr = asset_ctr < cm.get("ctr", 0) * 0.90 if cm.get("ctr", 0) > 0 else False
        worse_cti = asset_cti < cm.get("cti", 0) * 0.90 if cm.get("cti", 0) > 0 else False
        worse_cpc = asset_cpc > cm.get("cpc", 0) * 1.10 if cm.get("cpc", 0) > 0 else False

        peers = type_counts_per_camp.get((cname, atype), 0)
        if peers <= 1:
            # Only asset of its type in this campaign — can't compare; trust the API LOW label
            flag = "low-action"
            worse_ctr = worse_cti = worse_cpc = False
        else:
            flag = "low-action" if sum([worse_ctr, worse_cti, worse_cpc]) >= 2 else "low-watch"
        results.append({
            "flag": flag,
            "campaign_name": cname,
            "ad_group_name": r.get("ad_group_name", ""),
            "asset_id": r.get("asset_id", ""),
            "asset_name": r.get("asset_name", ""),
            "asset_type": r.get("asset_type", ""),
            "field_type": r.get("field_type", ""),
            "impressions": r.get("impressions", ""),
            "cost": r.get("cost", ""),
            "ctr_percent": r.get("ctr_percent", ""),
            "type_avg_ctr": format_float(cm.get("ctr", 0)),
            "cti_percent": r.get("cti_percent", ""),
            "type_avg_cti": format_float(cm.get("cti", 0)),
            "cpc": r.get("cpc", ""),
            "type_avg_cpc": format_float(cm.get("cpc", 0)),
            "installs": r.get("installs", ""),
            "in_app_conversions": r.get("in_app_conversions", ""),
            "worse_ctr": str(worse_ctr),
            "worse_cti": str(worse_cti),
            "worse_cpc": str(worse_cpc),
        })

    text_low_action = [r for r in results if r["flag"] == "low-action" and r["asset_type"] == "TEXT"]
    text_low_watch = [r for r in results if r["flag"] == "low-watch" and r["asset_type"] == "TEXT"]
    media_low = [r for r in results if r["asset_type"] in ("YOUTUBE_VIDEO", "IMAGE", "MEDIA_BUNDLE")]

    print(f"\n[Creative Underperformance — LOW label, ≥{min_imp:.0f} impressions]\n")
    print(f"  {len(results)} LOW total | {len(text_low_action)} text low-action | {len(text_low_watch)} text low-watch | {len(media_low)} video/image LOW\n")

    # Section 1: Text low-action (2+ metrics worse than same-type campaign avg)
    if text_low_action:
        print(f"  TEXT LOW-ACTION ({len(text_low_action)} — CTR/CTI/CPC worse vs same-type campaign avg)")
        hdr = (f"  {'Asset/ID':<28}  {'Field':<14}  "
               f"{'CTR%':>6}  {'TypeAvg':>8}  {'CTI%':>6}  {'TypeAvg':>8}  "
               f"{'CPC':>8}  {'TypeAvg':>8}")
        print(hdr)
        print("  " + "─" * (len(hdr) - 2))
        for r in text_low_action:
            label = (r["asset_name"] or r["asset_id"] or "—")[:26]
            print(
                f"  {label:<28}  {r['field_type']:<14}  "
                f"{_fmt_display(r['ctr_percent'], 'percent', ''):>6}  "
                f"{_fmt_display(r['type_avg_ctr'], 'percent', ''):>8}  "
                f"{_fmt_display(r['cti_percent'], 'percent', ''):>6}  "
                f"{_fmt_display(r['type_avg_cti'], 'percent', ''):>8}  "
                f"{_fmt_display(r['cpc'], 'cost', currency):>8}  "
                f"{_fmt_display(r['type_avg_cpc'], 'cost', currency):>8}"
            )

    # Section 2: Video / Image LOW (always surfaced — production cost to replace)
    if media_low:
        print(f"\n  VIDEO / IMAGE LOW ({len(media_low)} — API signal; review for refresh)")
        hdr2 = (f"  {'Asset name/ID':<36}  {'Type':<14}  "
                f"{'CTR%':>6}  {'TypeAvg':>8}  {'CTI%':>6}  {'TypeAvg':>8}  "
                f"{'CPC':>8}  {'TypeAvg':>8}")
        print(hdr2)
        print("  " + "─" * (len(hdr2) - 2))
        for r in media_low:
            label = (r["asset_name"] or r["asset_id"] or "—")[:34]
            print(
                f"  {label:<36}  {r['asset_type']:<14}  "
                f"{_fmt_display(r['ctr_percent'], 'percent', ''):>6}  "
                f"{_fmt_display(r['type_avg_ctr'], 'percent', ''):>8}  "
                f"{_fmt_display(r['cti_percent'], 'percent', ''):>6}  "
                f"{_fmt_display(r['type_avg_cti'], 'percent', ''):>8}  "
                f"{_fmt_display(r['cpc'], 'cost', currency):>8}  "
                f"{_fmt_display(r['type_avg_cpc'], 'cost', currency):>8}"
            )

    if text_low_watch:
        print(f"\n  TEXT LOW-WATCH ({len(text_low_watch)} — only 1 metric worse; monitor):")
        for r in text_low_watch[:10]:  # cap at 10 to avoid wall of text
            label = (r["asset_name"] or r["asset_id"] or "—")[:40]
            print(f"    {r['field_type']:<14}  {label}")
        if len(text_low_watch) > 10:
            print(f"    … and {len(text_low_watch) - 10} more (use --output to save full list)")

    # Pattern analysis on all low-action assets (text + media)
    all_low_action = text_low_action + media_low
    if all_low_action:
        from collections import Counter
        type_counts: Counter = Counter(r["asset_type"] for r in all_low_action)
        field_counts: Counter = Counter(r["field_type"] for r in all_low_action)

        # Mine asset_name tokens (populated for images/videos)
        name_words: Counter = Counter()
        for r in all_low_action:
            for src in (r.get("asset_name") or "", r.get("ad_group_name") or ""):
                for tok in src.replace("-", " ").replace("_", " ").split():
                    if len(tok) >= 4:
                        name_words[tok.lower()] += 1

        # Ad-group patterns (always populated — describes creative theme)
        adgroup_counts: Counter = Counter(r.get("ad_group_name", "") for r in all_low_action if r.get("ad_group_name"))

        print("\n  [Patterns in Low-Action creatives]")
        print(f"  Asset types : {', '.join(f'{t}×{c}' for t, c in type_counts.most_common())}")
        print(f"  Field types : {', '.join(f'{f}×{c}' for f, c in field_counts.most_common())}")
        common_tokens = [(w, c) for w, c in name_words.most_common(8) if c >= 3]
        if common_tokens:
            print(f"  Common terms: {', '.join(f'{w}({c})' for w, c in common_tokens)}")
        top_adgroups = adgroup_counts.most_common(5)
        if top_adgroups:
            print(f"  Top ad groups with Low-Action creatives:")
            for ag, c in top_adgroups:
                print(f"    {c:>3}× {ag}")

    if getattr(args, "output", None):
        out = Path(args.output).expanduser()
        cols = ["flag", "campaign_name", "ad_group_name", "asset_id", "asset_name",
                "asset_type", "field_type", "impressions", "cost",
                "ctr_percent", "type_avg_ctr", "cti_percent", "type_avg_cti",
                "cpc", "type_avg_cpc", "installs", "in_app_conversions",
                "worse_ctr", "worse_cti", "worse_cpc"]
        write_csv(out, results, cols)
        print(f"\n  full CSV written: {out}")


_LANG_CANONICAL: dict = {
    'english': 'English', 'eng': 'English',
    'hindi': 'Hindi',
    'hinglish': 'Hinglish', 'nagpurihinglish': 'Hinglish',
    'bengali': 'Bengali',
    'telugu': 'Telugu', 'tenglish': 'Telugu',
    'tamil': 'Tamil', 'tanglish': 'Tamil',
    'gujarati': 'Gujarati', 'gujrati': 'Gujarati', 'gujlish': 'Gujarati',
    'marathi': 'Marathi',
    'malayalam': 'Malayalam', 'manglish': 'Malayalam',
    'odia': 'Odia',
    'kannada': 'Kannada',
}
_LANG_RE = re.compile(
    r'\b(' + '|'.join(_LANG_CANONICAL) + r')\b', re.IGNORECASE
)


def _lang_canonical(ag_name: str) -> str:
    """Extract canonical language from ad group name (e.g. 'Tenglish' → 'Telugu')."""
    m = _LANG_RE.search(ag_name)
    return _LANG_CANONICAL.get(m.group(1).lower(), 'Other') if m else 'Other'


def _ad_group_theme(ag_name: str) -> str:
    """First-two-segment theme from ad group name: 'UseCase-Party', 'Transit-Bus', etc."""
    name = re.sub(r'[-_][A-Z][a-z]{2,4}\d{2,4}_?$', '', ag_name).strip()
    parts = re.split(r'[-_]+', name)
    return '-'.join(parts[:2]) if len(parts) >= 2 else name


def _asset_dimension(row: dict[str, Any], axis: str) -> int | None:
    keys = (
        f"image_{axis}",
        f"asset_image_{axis}",
        f"full_size_{axis}",
        f"{axis}_pixels",
        f"image_{axis}_pixels",
        f"asset_image_{axis}_pixels",
        axis,
    )
    for key in keys:
        value = row.get(key)
        if value not in (None, "", "NA"):
            numeric = int(number(value))
            if numeric > 0:
                return numeric
    return None


def _asset_url(row: dict[str, Any]) -> str:
    for key in (
        "image_url",
        "asset_image_url",
        "full_size_url",
        "asset_image_full_size_url",
        "asset.image_asset.full_size.url",
        "url",
    ):
        value = str(row.get(key, "")).strip()
        if value:
            return value
    return ""


def _ratio_bucket_from_dimensions(width: int | None, height: int | None) -> str:
    if not width or not height:
        return "unknown"
    ratio_value = width / height
    if abs(ratio_value - (1200 / 628)) <= 0.08:
        return "horizontal"
    if abs(ratio_value - (4 / 5)) <= 0.05:
        return "vertical"
    if abs(ratio_value - 1.0) <= 0.05:
        return "square"
    return "unknown"


def _static_banner_ratio_bucket(row: dict[str, Any]) -> str:
    field_type = str(row.get("field_type", "")).upper()
    mapped = STATIC_IMAGE_FIELD_RATIOS.get(field_type)
    if mapped and mapped != "unknown":
        return mapped
    return _ratio_bucket_from_dimensions(
        _asset_dimension(row, "width"),
        _asset_dimension(row, "height"),
    )


def _is_static_image_asset(row: dict[str, Any]) -> bool:
    asset_type = str(row.get("asset_type", "")).upper()
    field_type = str(row.get("field_type", "")).upper()
    return asset_type == "IMAGE" or field_type in STATIC_IMAGE_FIELD_RATIOS


def _creative_file_period(path: Path) -> tuple[str, str]:
    parts = path.stem.split("_")
    if len(parts) >= 3:
        return parts[1], parts[2]
    return "unknown", "unknown"


def _fresh_static_banner_guide_date(path: Path, max_age_days: int) -> dt.date | None:
    if not path.exists():
        return None
    text = path.read_text(errors="ignore")
    if "Static Banner Diagnostic" in text or "data-only diagnostic" in text:
        return None
    match = re.search(r"^date:\s*'?([0-9]{4}-[0-9]{2}-[0-9]{2})'?\s*$", text, re.MULTILINE)
    if match:
        try:
            written = dt.date.fromisoformat(match.group(1))
        except ValueError:
            written = dt.date.fromtimestamp(path.stat().st_mtime)
    else:
        written = dt.date.fromtimestamp(path.stat().st_mtime)
    return written if (today() - written).days < max_age_days else None


def _static_banner_asset(row: dict[str, Any], ratio_bucket: str, source_label: str) -> dict[str, Any]:
    return {
        "source_label": source_label,
        "ratio_bucket": ratio_bucket,
        "campaign_id": row.get("campaign_id", ""),
        "campaign_name": row.get("campaign_name", ""),
        "ad_group_id": row.get("ad_group_id", ""),
        "ad_group_name": row.get("ad_group_name", ""),
        "asset_id": row.get("asset_id", ""),
        "asset_name": row.get("asset_name", ""),
        "asset_type": row.get("asset_type", ""),
        "field_type": row.get("field_type", ""),
        "performance_label": row.get("performance_label", ""),
        "width": _asset_dimension(row, "width"),
        "height": _asset_dimension(row, "height"),
        "mime_type": row.get("mime_type", "") or row.get("image_mime_type", ""),
        "file_size_bytes": row.get("file_size_bytes", "") or row.get("image_file_size_bytes", ""),
        "source_url": _asset_url(row),
        "impressions": row.get("impressions", ""),
        "clicks": row.get("clicks", ""),
        "ctr_percent": row.get("ctr_percent", ""),
        "installs": row.get("installs", ""),
        "in_app_conversions": row.get("in_app_conversions", ""),
        "cti_percent": row.get("cti_percent", ""),
        "cpc": row.get("cpc", ""),
    }


def _static_banner_identity_key(asset: dict[str, Any]) -> tuple[str, str]:
    asset_id = str(asset.get("asset_id", "")).strip()
    if asset_id:
        return ("asset_id", asset_id)
    source_url = str(asset.get("source_url", "")).strip()
    if source_url:
        return ("source_url", source_url)
    fallback = "|".join(
        str(asset.get(key, "") or "")
        for key in ("asset_name", "width", "height", "file_size_bytes")
    )
    return ("fallback", fallback)


def _static_banner_placement(asset: dict[str, Any]) -> dict[str, Any]:
    return {
        "campaign_id": asset.get("campaign_id", ""),
        "campaign_name": asset.get("campaign_name", ""),
        "ad_group_id": asset.get("ad_group_id", ""),
        "ad_group_name": asset.get("ad_group_name", ""),
        "field_type": asset.get("field_type", ""),
        "impressions": asset.get("impressions", ""),
        "clicks": asset.get("clicks", ""),
        "installs": asset.get("installs", ""),
        "in_app_conversions": asset.get("in_app_conversions", ""),
        "ctr_percent": asset.get("ctr_percent", ""),
        "cti_percent": asset.get("cti_percent", ""),
        "cpc": asset.get("cpc", ""),
        "source_url": asset.get("source_url", ""),
    }


def _merge_static_banner_asset_group(assets: list[dict[str, Any]]) -> dict[str, Any]:
    ranked_assets = sorted(
        assets,
        key=lambda asset: (
            number(asset.get("in_app_conversions")),
            number(asset.get("installs")),
            number(asset.get("impressions")),
        ),
        reverse=True,
    )
    merged = dict(ranked_assets[0])
    placements = [_static_banner_placement(asset) for asset in ranked_assets]
    merged["duplicate_placements"] = placements
    merged["duplicate_placement_count"] = len(placements)
    merged["top_placement_campaign_name"] = placements[0].get("campaign_name", "")
    merged["top_placement_ad_group_name"] = placements[0].get("ad_group_name", "")
    for metric in ("impressions", "clicks", "installs", "in_app_conversions"):
        merged[metric] = sum(number(asset.get(metric)) for asset in assets)
    impressions = number(merged.get("impressions"))
    clicks = number(merged.get("clicks"))
    installs = number(merged.get("installs"))
    conversions = number(merged.get("in_app_conversions"))
    merged["ctr_percent"] = (clicks / impressions * 100) if impressions else ""
    merged["cti_percent"] = (installs / clicks * 100) if clicks else ""
    cpc_values = [number(asset.get("cpc")) for asset in assets if number(asset.get("cpc")) > 0]
    merged["cpc"] = (sum(cpc_values) / len(cpc_values)) if cpc_values else ""
    return merged


def _dedupe_static_banner_assets(assets: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    ordered_keys: list[tuple[str, str]] = []
    for asset in assets:
        key = _static_banner_identity_key(asset)
        if key not in grouped:
            grouped[key] = []
            ordered_keys.append(key)
        grouped[key].append(asset)
    unique_assets = [_merge_static_banner_asset_group(grouped[key]) for key in ordered_keys]
    duplicate_groups = [
        {
            "asset_id": asset.get("asset_id", ""),
            "asset_name": asset.get("asset_name", ""),
            "source_url": asset.get("source_url", ""),
            "duplicate_placement_count": asset.get("duplicate_placement_count", 1),
            "placements": asset.get("duplicate_placements", []),
        }
        for asset in unique_assets
        if number(asset.get("duplicate_placement_count")) > 1
    ]
    return unique_assets, duplicate_groups


def _group_static_banner_assets(assets: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped = {key: [] for key in STATIC_BANNER_SPECS}
    grouped["unknown"] = []
    for asset in assets:
        grouped.setdefault(asset["ratio_bucket"], []).append(asset)
    for ratio, rows in grouped.items():
        grouped[ratio] = sorted(
            rows,
            key=lambda r: (
                number(r.get("in_app_conversions")),
                number(r.get("installs")),
                number(r.get("impressions")),
            ),
            reverse=True,
        )
    return grouped


def _build_default_static_banner_strategy(grouped_assets: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    themes: list[str] = []
    for ratio in ("horizontal", "vertical", "square"):
        for asset in grouped_assets.get(ratio, [])[:5]:
            theme = _ad_group_theme(asset.get("ad_group_name", ""))
            if theme and theme not in themes:
                themes.append(theme)
    theme_text = ", ".join(themes[:8]) if themes else "winning campaign/ad group contexts"
    return {
        "status": "data_only_pending_visual_review",
        "raw_asset_count": sum(len(grouped_assets.get(ratio, [])) for ratio in grouped_assets),
        "unique_image_count": sum(len(grouped_assets.get(ratio, [])) for ratio in grouped_assets),
        "winning_patterns": [
            f"Use the strongest observed campaign/ad group contexts as creative territories: {theme_text}.",
            "Keep each banner focused on one use case, one benefit, and one direct action.",
            "Prefer layouts that leave clear space for benefit copy and a short CTA.",
        ],
        "ratio_rules": {
            "horizontal": "Use a wide composition with the core message on one side and the product or context on the other.",
            "vertical": "Use stacked hierarchy: benefit first, product/context visual second, CTA last.",
            "square": "Keep the visual simple and centered; avoid dense text because the format has less horizontal room.",
        },
        "message_hierarchy": [
            "Primary use case, occasion, audience context, or need state.",
            "Specific benefit such as speed, savings, convenience, capacity, trust, quality, access, or a trial offer.",
            "Short CTA that works without surrounding copy.",
        ],
        "cta_rules": [
            "Use one CTA per banner.",
            "Keep CTA copy short enough to remain readable on mobile inventory.",
            "Do not let coupon text overpower the actual product or service benefit.",
        ],
        "brand_and_product_rules": [
            "Make the product or service signal visible without turning the banner into a logo-only ad.",
            "Use campaign/ad group context to choose the product or service focus and use context.",
        ],
        "visual_style": [
            "Prioritize legible contrast, simple foreground/background separation, and recognisable context.",
            "Avoid generic lifestyle imagery that does not communicate the use occasion.",
        ],
        "visual_language": [
            "Use one dominant reading path: claim first, proof second, action third.",
            "Keep the message inside a high-contrast block when the background is busy.",
            "Build separate compositions for horizontal, vertical, and square instead of resizing one master layout.",
        ],
        "brand_colors": {},
        "typography_signals": {},
        "component_patterns": [],
        "brand_signals": [],
        "token_confidence_notes": [],
        "avoid": [
            "Crowded text blocks.",
            "Multiple competing offers.",
            "Layouts that cannot adapt across horizontal, vertical, and square.",
            "Generic visual claims not supported by the campaign/ad group context.",
        ],
        "future_generation_contract_notes": [
            "Future generation must require campaign, ad group, and user brief before producing images.",
            "Start from the guide and brief, then say exactly which element cannot be faithfully generated if something is missing.",
            "Do not assume a fixed upload bundle; ask only for missing elements needed for fidelity or approval.",
        ],
    }


def _write_static_banner_index_entry(index_path: Path, entry: str, section: str = "Design") -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    if index_path.exists():
        text = index_path.read_text()
    else:
        text = "# Bob — Wiki Index\n\n## Analyses\n\n## Action Items\n\n## Design\n\n## Backlog\n"
    if f"## {section}" not in text:
        if "## Backlog" in text:
            text = text.replace("## Backlog", f"## {section}\n\n## Backlog", 1)
        else:
            text = text.rstrip() + f"\n\n## {section}\n"
    lines = text.splitlines()
    out: list[str] = []
    inserted = False
    in_target_section = False
    for line in lines:
        if line.startswith("## "):
            if in_target_section and not inserted:
                out.append(entry)
                inserted = True
            in_target_section = line.strip() == f"## {section}"
            out.append(line)
            continue
        if "Static Banner Design" in line:
            if not inserted:
                if in_target_section:
                    out.append(entry)
                    inserted = True
            continue
        out.append(line)
    if in_target_section and not inserted:
        out.append(entry)
    index_path.write_text("\n".join(out).rstrip() + "\n")


def _format_asset_metric_row(asset: dict[str, Any], currency: str) -> str:
    def _cell(value: Any) -> str:
        return str(value or "").replace("|", "\\|").replace("\n", " ").strip()

    label = asset.get("asset_name") or asset.get("asset_id") or "unknown"
    size = "unknown"
    if asset.get("width") and asset.get("height"):
        size = f"{asset['width']}x{asset['height']}"
    url = asset.get("source_url") or "unavailable"
    return (
        f"| {_cell(label)} | {_cell(asset.get('campaign_name', ''))} | {_cell(asset.get('ad_group_name', ''))} | "
        f"{_cell(asset.get('field_type', ''))} | {_cell(size)} | {_cell(asset.get('performance_label', ''))} | "
        f"{_fmt_display(asset.get('impressions'), 'count')} | "
        f"{_fmt_display(asset.get('clicks'), 'count')} | "
        f"{_fmt_display(asset.get('ctr_percent'), 'percent')} | "
        f"{_fmt_display(asset.get('installs'), 'count')} | "
        f"{_fmt_display(asset.get('in_app_conversions'), 'count')} | "
        f"{_fmt_display(asset.get('cti_percent'), 'percent')} | "
        f"{_fmt_display(asset.get('cpc'), 'cost', currency)} | {_cell(url)} |"
    )


def _format_repeated_placement_row(asset: dict[str, Any], placement: dict[str, Any], currency: str) -> str:
    asset_label = str(asset.get("asset_name") or asset.get("asset_id") or "unknown").replace("|", "\\|")
    campaign = str(placement.get("campaign_name", "") or "").replace("|", "\\|")
    ad_group = str(placement.get("ad_group_name", "") or "").replace("|", "\\|")
    return (
        f"| {asset_label} | {campaign} | {ad_group} | "
        f"{_fmt_display(placement.get('impressions'), 'count')} | "
        f"{_fmt_display(placement.get('clicks'), 'count')} | "
        f"{_fmt_display(placement.get('installs'), 'count')} | "
        f"{_fmt_display(placement.get('in_app_conversions'), 'count')} | "
        f"{_fmt_display(placement.get('cpc'), 'cost', currency)} |"
    )


def _static_banner_asset_filename(asset: dict[str, Any], index: int) -> str:
    source_url = asset.get("source_url") or ""
    suffix = Path(urllib.parse.urlparse(source_url).path).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png"}:
        mime = str(asset.get("mime_type") or "").lower()
        suffix = ".png" if "png" in mime else ".jpg"
    asset_id = re.sub(r"[^A-Za-z0-9_-]+", "-", str(asset.get("asset_id") or f"asset-{index}")).strip("-")
    return f"{index:03d}-{asset_id}{suffix}"


def _download_static_banner_assets(
    grouped_assets: dict[str, list[dict[str, Any]]],
    output_dir: Path,
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    downloaded_grouped: dict[str, list[dict[str, Any]]] = {key: [] for key in grouped_assets}
    manifest: list[dict[str, Any]] = []
    index = 1
    for ratio, assets in grouped_assets.items():
        for asset in assets:
            enriched = dict(asset)
            source_url = enriched.get("source_url") or ""
            local_path = ""
            status = "no_url"
            error = ""
            if source_url:
                filename = _static_banner_asset_filename(enriched, index)
                destination = output_dir / filename
                try:
                    urllib.request.urlretrieve(source_url, destination)
                    local_path = str(destination)
                    status = "downloaded"
                except Exception as exc:
                    status = "download_failed"
                    error = str(exc)
            enriched["local_path"] = local_path
            enriched["download_status"] = status
            enriched["download_error"] = error
            downloaded_grouped.setdefault(ratio, []).append(enriched)
            manifest.append(enriched)
            index += 1
    return downloaded_grouped, manifest


def _write_static_banner_manifest(run_dir: Path, payload: dict[str, Any]) -> Path:
    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    return manifest_path


def _strategy_has_visual_evidence(strategy: dict[str, Any]) -> bool:
    inspected = strategy.get("image_inspected_count")
    if number(inspected) > 0:
        return True
    inspected = strategy.get("unique_image_count")
    if number(inspected) > 0:
        return True
    observations = strategy.get("creative_observations") or strategy.get("per_creative_observations")
    return isinstance(observations, list) and len(observations) > 0


def _append_markdown_section(lines: list[str], title: str, values: Any, fallback: str = "- Not provided.") -> None:
    lines.extend(["", f"## {title}"])
    if isinstance(values, dict):
        if not values:
            lines.append(fallback)
            return
        for key, value in values.items():
            lines.append(f"- **{str(key).title()}:** {value}")
        return
    if isinstance(values, list):
        if not values:
            lines.append(fallback)
            return
        for value in values:
            lines.append(f"- {value}")
        return
    if values:
        lines.append(str(values))
        return
    lines.append(fallback)


def _strategy_visual_language_lines(strategy: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for value in strategy.get("visual_language") or []:
        if str(value).strip():
            lines.append(str(value).strip())
    return lines


def _strategy_list(strategy: dict[str, Any], key: str) -> list[str]:
    values = strategy.get(key) or []
    if not isinstance(values, list):
        return []
    out: list[str] = []
    for value in values:
        text = str(value or "").replace("\n", " ").strip()
        if text:
            out.append(text)
    return out


def _strategy_dict(strategy: dict[str, Any], key: str) -> dict[str, Any]:
    values = strategy.get(key) or {}
    return values if isinstance(values, dict) else {}


def _design_token_value(token: Any) -> str:
    if isinstance(token, dict):
        value = token.get("value") or token.get("hex") or token.get("token")
        return str(value or "").strip()
    return str(token or "").strip()


def _design_token_note(token: Any) -> str:
    if not isinstance(token, dict):
        return ""
    note = token.get("note") or token.get("role") or token.get("confidence")
    return str(note or "").strip()


def _infer_design_name(customer_id: str) -> str:
    safe_id = str(customer_id or "advertiser").replace(" ", "-")
    return f"{safe_id} Static Banner Design System"


def _generic_design_content_rules() -> list[str]:
    return [
        "Lead with one short problem, benefit, or use-case trigger that reads in under two seconds.",
        "Support the headline with one concrete proof element such as speed, offer, destination, or product mode.",
        "Keep the primary proof visible in the image, not only in the copy.",
        "Use no more than one headline, one proof cue, and one CTA in the same frame.",
    ]


def _write_static_banner_strategy_markdown(
    path: Path,
    customer_id: str,
    period_start: str,
    period_end: str,
    grouped_assets: dict[str, list[dict[str, Any]]],
    secondary_assets: list[dict[str, Any]],
    strategy: dict[str, Any],
    strategy_input_path: Path,
    design_path: Path,
    currency: str,
    diagnostic: bool = False,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    date_str = today().isoformat()
    refresh_after = today() + dt.timedelta(days=STATIC_BANNER_REFRESH_DAYS)
    unique_count = int(number(strategy.get("unique_image_count")) or sum(len(grouped_assets.get(r, [])) for r in ("horizontal", "vertical", "square")))
    lines: list[str] = [
        "---",
        f"date: {date_str}",
        "intent: static_banner_design",
        f"customer_id: {customer_id}",
        f"period: {period_start}–{period_end}",
        f"refresh_after: {refresh_after.isoformat()}",
        "---",
        "",
        "← [Wiki Index](../Index.md)",
        "",
        f"# {'Static Banner Diagnostic' if diagnostic else 'Static Banner Strategy'}: {date_str}",
        "",
        "## Summary",
        (
            "This is a data-only diagnostic, not a final strategy artifact. It is missing strategist visual analysis."
            if diagnostic
            else "This document captures the winning static-banner evidence for the current account. It keeps account-specific observations, duplicate-placement evidence, and strategist rationale separate from the reusable design spec."
        ),
        "",
        f"Unique visual families in scope: {unique_count}. Repeated placements are kept as evidence only.",
        "",
        f"Use [DESIGN.md]({design_path.name}) as the generation-oriented design spec. This strategy file is the audit trail and evidence base.",
        "",
        "## Image Specs",
        "| Format | Ratio | Recommended size | Minimum size | Max images | File rules |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for ratio, spec in STATIC_BANNER_SPECS.items():
        lines.append(
            f"| {ratio.title()} | {spec['ratio']} | {spec['recommended_size']} | "
            f"{spec['minimum_size']} | {spec['max_images']} | .jpg or .png, max 5MB |"
        )

    lines += [
        "",
        "## Winner References",
        "| Asset | Campaign | Ad group | Field | Size | Label | Impr. | Clicks | CTR | Installs | Conv. | CTI | CPC | Source |",
        "|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for ratio in ("horizontal", "vertical", "square"):
        for asset in grouped_assets.get(ratio, [])[:STATIC_BANNER_SPECS[ratio]["max_images"]]:
            lines.append(_format_asset_metric_row(asset, currency))
    if not any(grouped_assets.get(ratio) for ratio in ("horizontal", "vertical", "square")):
        lines.append("| No BEST static image assets found |  |  |  |  |  |  |  |  |  |  |  |  |  |")

    if secondary_assets:
        lines += [
            "",
            "## Secondary GOOD References",
            "No BEST static image assets were available for every slot, so these GOOD assets are reference-only.",
            "",
            "| Asset | Campaign | Ad group | Field | Size | Label | Impr. | Clicks | CTR | Installs | Conv. | CTI | CPC | Source |",
            "|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
        for asset in secondary_assets[:20]:
            lines.append(_format_asset_metric_row(asset, currency))

    repeated_assets = [
        asset
        for ratio in ("horizontal", "vertical", "square", "unknown")
        for asset in grouped_assets.get(ratio, [])
        if number(asset.get("duplicate_placement_count")) > 1
    ]
    if repeated_assets:
        lines += [
            "",
            "## Repeated Placement Evidence",
            "| Asset | Campaign | Ad group | Impr. | Clicks | Installs | Conv. | CPC |",
            "|---|---|---|---:|---:|---:|---:|---:|",
        ]
        for asset in repeated_assets:
            for placement in asset.get("duplicate_placements", []):
                lines.append(_format_repeated_placement_row(asset, placement, currency))

    observations = strategy.get("creative_observations") or strategy.get("per_creative_observations")
    if observations:
        lines += [
            "",
            "## Per-Creative Visual Observations",
            "| Asset | What it looks like | Layout | Message / CTA | Why it matters |",
            "|---|---|---|---|---|",
        ]
        for obs in observations:
            if not isinstance(obs, dict):
                continue
            asset = obs.get("asset") or obs.get("asset_id") or obs.get("asset_name") or "unknown"
            looks = obs.get("visual_description") or obs.get("what_it_looks_like") or ""
            layout = obs.get("layout_notes") or obs.get("layout") or ""
            message = obs.get("message_cta_notes") or obs.get("message") or obs.get("cta") or ""
            rationale = obs.get("why_it_matters") or obs.get("performance_read") or ""
            safe = [str(v).replace("|", "\\|").replace("\n", " ") for v in (asset, looks, layout, message, rationale)]
            lines.append(f"| {safe[0]} | {safe[1]} | {safe[2]} | {safe[3]} | {safe[4]} |")

    _append_markdown_section(lines, "Winning Patterns", strategy.get("winning_patterns"), "- Not provided by strategist.")
    _append_markdown_section(lines, "Visual Language", strategy.get("visual_language"), "- Not provided by strategist.")
    _append_markdown_section(lines, "Ratio-Specific Layout Rules", strategy.get("ratio_rules"), "- Not provided by strategist.")
    _append_markdown_section(lines, "Message Hierarchy", strategy.get("message_hierarchy"), "- Not provided by strategist.")
    _append_markdown_section(lines, "CTA Rules", strategy.get("cta_rules"), "- Not provided by strategist.")
    _append_markdown_section(lines, "Brand And Product Rules", strategy.get("brand_and_product_rules"), "- Not provided by strategist.")
    _append_markdown_section(lines, "Visual Style", strategy.get("visual_style"), "- Not provided by strategist.")
    _append_markdown_section(lines, "Avoid", strategy.get("avoid"), "- Not provided by strategist.")

    lines += [
        "",
        "## Future Generation Contract",
        "- Use `DESIGN.md` plus a campaign brief for future image generation. Do not use this strategy file as the primary prompt.",
        "- Future generation must require campaign, ad group, and user brief/objective.",
        "- The model should start from the guide and the brief, then say exactly which element it cannot faithfully generate if something is missing.",
        "- Do not assume a fixed upload bundle.",
        "- Ask only for the missing elements needed for fidelity or approval.",
        "- Optional future inputs: ratios, count per ratio, language or locale, offer or coupon, must-use text, and must-avoid text.",
        "- Future output expectations: exact Google dimensions, .jpg or .png, under 5MB, review files only.",
        f"- Strategist input: `{strategy_input_path}`",
    ]
    for note in strategy.get("future_generation_contract_notes", []):
        lines.append(f"- {note}")

    if diagnostic or strategy.get("status") == "data_only_pending_visual_review":
        lines += [
            "",
            "## Strategist Status",
            "Visual strategist JSON was not supplied, so this file is diagnostic only. Refetch creative_period if image URLs are missing, then run the `bob-static-banners` skill with the strategist packet.",
        ]

    path.write_text("\n".join(lines) + "\n")


def _write_static_banner_design_md(
    path: Path,
    strategy: dict[str, Any],
    strategy_path: Path,
    customer_id: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    visual_language = _strategy_visual_language_lines(strategy)
    ratio_rules = _strategy_dict(strategy, "ratio_rules")
    brand_colors = _strategy_dict(strategy, "brand_colors")
    typography_signals = _strategy_dict(strategy, "typography_signals")
    brand_signals = _strategy_list(strategy, "brand_signals")
    component_patterns = _strategy_list(strategy, "component_patterns")
    token_confidence_notes = _strategy_list(strategy, "token_confidence_notes")
    design_name = str(strategy.get("design_system_name") or _infer_design_name(customer_id))

    frontmatter: list[str] = [
        "---",
        f"name: {design_name}",
    ]
    if brand_colors:
        frontmatter.append("colors:")
        for key, token in brand_colors.items():
            value = _design_token_value(token)
            if value:
                frontmatter.append(f"  {key}: \"{value}\"")
    if typography_signals:
        frontmatter.append("typography:")
        for key, token in typography_signals.items():
            if isinstance(token, dict):
                frontmatter.append(f"  {key}:")
                for subkey in ("fontFamily", "fontWeight", "fontStyle", "fontSize"):
                    subvalue = token.get(subkey)
                    if subvalue:
                        frontmatter.append(f"    {subkey}: {subvalue}")
            else:
                frontmatter.append(f"  {key}: \"{str(token)}\"")
    frontmatter += [
        "layout:",
        "  readingPath: claim -> proof -> action",
        "  density: promotional",
        "  splitLayout: preferred for horizontal",
        "components:",
        "  primary:",
        "    - headline block",
        "    - proof container",
        "    - CTA container",
        "    - hero subject or product proof",
        "content:",
        "  maxClaims: 1",
        "  proofElements: 1",
        "  ctaElements: 1",
        "---",
        "",
    ]

    lines: list[str] = [
        *frontmatter,
        "# Design System",
        "",
        "## Overview",
        "An advertiser-specific static-banner design spec distilled from reviewed winning creatives. Use this file as the primary generation context; keep the strategy document for evidence and placement history.",
        "",
        f"Source strategy: [{strategy_path.name}]({strategy_path.name})",
        "",
        "## Brand Signals",
    ]
    if brand_signals:
        for item in brand_signals:
            lines.append(f"- {item}")
    else:
        lines.append("- Use the recurring logo lockup, hero product styling, and repeated shape language visible in the reviewed creatives as the advertiser brand anchor.")

    lines += [
        "",
        "## Visual Language",
    ]
    if visual_language:
        for item in visual_language:
            lines.append(f"- {item}")
    else:
        lines.append("- Build one dominant reading path: claim first, proof second, action third.")
        lines.append("- Prefer high-contrast message containers when the background carries scene detail.")
        lines.append("- Design each ratio intentionally instead of resizing one master layout.")

    lines += [
        "",
        "## Colors",
    ]
    if brand_colors:
        for key, token in brand_colors.items():
            value = _design_token_value(token)
            note = _design_token_note(token)
            label = str(key).replace("_", " ").title()
            line = f"- **{label}**"
            if value:
                line += f" ({value})"
            if note:
                line += f": {note}"
            lines.append(line)
    else:
        lines.append("- Brand color extraction was not provided by the strategist. Use the dominant advertiser colors visible in the reviewed creatives and document any uncertainty.")

    lines += [
        "",
        "## Token Confidence",
    ]
    if token_confidence_notes:
        for item in token_confidence_notes:
            lines.append(f"- {item}")
    else:
        lines.append("- Treat exact token values as visual inferences unless approved brand assets are supplied.")

    lines += [
        "",
        "## Typography",
    ]
    if typography_signals:
        for key, token in typography_signals.items():
            label = str(key).replace("_", " ").title()
            if isinstance(token, dict):
                details = []
                for subkey in ("fontFamily", "fontWeight", "fontStyle", "fontSize", "note"):
                    subvalue = token.get(subkey)
                    if subvalue:
                        details.append(f"{subkey}: {subvalue}")
                lines.append(f"- **{label}:** " + ", ".join(details))
            else:
                lines.append(f"- **{label}:** {token}")
    else:
        lines += [
            "- Headlines should read in under two seconds and carry the primary promise or friction point.",
            "- Supporting proof should be shorter and more concrete than the headline.",
            "- Use large, bold type for the main claim and simpler supporting type for badges, proof, or CTA labels.",
            "- Decorative or casual type can appear as a supporting accent, not as the only readable layer.",
        ]

    lines += [
        "",
        "## Composition",
        "- Protect one clear text zone rather than placing the main message across busy scene detail.",
        "- In wide formats, prefer a split between message space and product or lifestyle proof.",
        "- Use device frames, posters, signs, placards, or notification cards as optional message containers when they improve clarity.",
        "- Keep the eye path deliberate: primary claim, secondary proof, then action.",
        "",
        "## Components",
    ]
    if component_patterns:
        for item in component_patterns:
            lines.append(f"- {item}")
    else:
        lines += [
            "- **Headline block:** carries the single main promise or problem statement.",
            "- **Proof container:** badge, device screen, signboard, poster, or caption block that makes the benefit concrete.",
            "- **CTA container:** button, badge, or imperative label when the concept needs an explicit action cue.",
            "- **Hero proof:** product, person, scene trigger, or object that visually proves the use case.",
        ]

    lines += [
        "",
        "## Imagery",
        "- Use contextual scenes that clearly explain why the ad exists: purchase moment, use occasion, audience need, location, urgency, event, routine, or another advertiser-specific context repeated in the winning set.",
        "- Keep the foreground proof crisp and the supporting scene simpler or softer so the message remains dominant.",
        "- Use human expression only when it reinforces the promise rather than adding noise.",
        "- Avoid generic lifestyle imagery that does not create a reason to act.",
        "",
        "## Ratio Rules",
    ]
    if ratio_rules:
        for key in ("horizontal", "square", "vertical"):
            value = ratio_rules.get(key)
            if value:
                lines.append(f"- **{key.title()}:** {value}")
    else:
        lines.append("- **Horizontal:** Use a split layout with one clear message zone and one proof zone.")
        lines.append("- **Square:** Reduce the claim count and keep one promise plus one proof element.")
        lines.append("- **Vertical:** Stack the reading path instead of cropping from wide layouts.")

    lines += [
        "",
        "## Content Rules",
    ]
    for item in _generic_design_content_rules():
        lines.append(f"- {item}")

    lines += [
        "",
        "## Theme Grammar",
        "- Convert campaign, ad group, and source-image context into a broad creative theme before writing the prompt.",
        "- Treat close concepts as semantic neighbors rather than exact text matches; for example, coupon, sale, discount, and offer can map to value incentive; trial, sample, demo, and first use can map to first-experience proof.",
        "- Use the theme to choose the problem, benefit, proof cue, and scene role; do not copy a winning creative only because it shares a keyword.",
        "- Keep the advertiser's brand system and product proof consistent while adapting the use case to the LOW source asset.",
        "",
        "## Source Reference Rules",
        "- For LOW replacement variants, inspect the source image before prompt construction and use it as the visual reference.",
        "- Preserve source elements by role unless the user marks them as hard SLA: product or service category, scene context, proof container, offer cue, human or use-case cue, and brand treatment.",
        "- Do not generate extra ratios; create only a same-size replacement for the flagged source asset.",
        "- If the source and design guide conflict, keep user-approved hard SLA constraints first, then source role preservation, then design-guide preferences.",
        "",
        "## Prompt Assembly Contract",
        "- Build future variant prompts from source image, LOW campaign/ad group metadata, native dimensions, theme, user-approved hard SLAs, soft preservation rules, and this design system.",
        "- Ask the user for hard SLA constraints before every regeneration.",
        "- Attach the LOW source image to the generation call whenever the task is a replacement variant.",
        "- State that output is preview-only unless a separate upload or replacement workflow is explicitly approved.",
        "",
        "## Constraint Classes",
        "- **Hard SLA:** user-confirmed requirements that must be preserved or reported as failed.",
        "- **Soft Preserve:** source-image roles to keep similar without exact pixel preservation.",
        "- **Design Guide:** reusable composition, hierarchy, brand, CTA, and readability rules from reviewed winners.",
        "- **Inferred Tokens:** colors, typography, logo treatment, product styling, and component patterns inferred from reviewed creatives rather than approved source-of-truth brand files.",
    ]

    lines += [
        "",
        "## CTA Rules",
    ]
    cta_rules = _strategy_list(strategy, "cta_rules")
    if cta_rules:
        for item in cta_rules:
            lines.append(f"- {item}")
    else:
        lines.append("- Use an explicit CTA only when the concept benefits from a direct action prompt.")
        lines.append("- Keep the CTA secondary to the core benefit.")

    lines += [
        "",
        "## Do's and Don'ts",
    ]
    for item in _strategy_list(strategy, "avoid"):
        lines.append(f"- {item.rstrip('.')}.")
    if not _strategy_list(strategy, "avoid"):
        lines.append("- Don't crop one composition blindly across ratios.")
        lines.append("- Don't let scene detail overpower the message.")
    lines += [
        "- Do keep the composition readable at feed size.",
        "- Do adapt the same visual language across ratios without copying the exact placement of every element.",
        "",
        "## Fidelity Rules",
        "- Start from this design system and the current campaign brief.",
        "- If a required element cannot be faithfully generated, say exactly what is missing instead of guessing.",
        "- Ask only for missing elements tied to fidelity, approval, or exactness.",
        "- Do not assume a fixed upload checklist.",
        "- Use reviewed creative evidence first for brand tokens; merge explicit brand assets or brand docs only when they are available.",
    ]
    for item in _strategy_list(strategy, "future_generation_contract_notes"):
        lines.append(f"- {item}")

    path.write_text("\n".join(lines) + "\n")


def _write_static_banner_overview_markdown(
    path: Path,
    strategy_path: Path,
    design_path: Path,
    unique_count: int,
    diagnostic: bool = False,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    date_str = today().isoformat()
    lines = [
        "---",
        f"date: {date_str}",
        "intent: static_banner_design",
        "---",
        "",
        "← [Wiki Index](../Index.md)",
        "",
        f"# {'Static Banner Diagnostic' if diagnostic else 'Static Banner Design'}: {date_str}",
        "",
        "## Files",
        f"- [Strategy]({strategy_path.name}) — evidence, repeated-placement context, and per-creative observations for {unique_count} unique visual families.",
        f"- [DESIGN.md]({design_path.name}) — advertiser-specific thematic design-system spec for future source-guided generation.",
        "",
        "## How To Use",
        "- Read the strategy file when you need to understand what won and where it repeated.",
        "- Use `DESIGN.md` as the primary generation spec: theme grammar, source-reference rules, prompt assembly, constraint classes, and visual design rules.",
        "- For LOW static variants, start from the flagged source image and campaign/ad group metadata; do not generate from `DESIGN.md` alone.",
        "- Before each regeneration, ask the user for hard SLA constraints, then preserve source elements by role unless marked hard SLA.",
        "- If the strategist has not visually reviewed images yet, treat both files as incomplete.",
        "",
        "## Variant Generation Contract",
        "- Map metadata and source context into broad themes instead of exact keyword matches.",
        "- Generate only same-size replacement previews for flagged LOW static image assets.",
        "- Run spec-only QA on preview outputs; apply to Google Ads only through the separate approval-gated apply flow.",
    ]
    path.write_text("\n".join(lines) + "\n")


def suggest_static_banners(args: argparse.Namespace) -> None:
    """Prepare static banner image evidence or finalize the visual design guide."""
    explicit_customer = getattr(args, "customer", None)
    profile = load_profile(required=not bool(explicit_customer))
    if explicit_customer:
        customer_key = str(explicit_customer).replace("-", "")
        account_profile = ACCOUNTS_DIR / customer_key / "profile.json"
        if account_profile.exists():
            profile = json.loads(account_profile.read_text())
        else:
            profile = dict(profile)
            profile["google_ads_customer_id"] = explicit_customer
    customer_id = profile.get("google_ads_customer_id") or "unknown"
    currency = _currency_symbol(profile.get("currency", ""))
    wiki_base = account_wiki_dir(customer_id) if customer_id != "unknown" else ROOT / "wiki"
    design_dir = wiki_base / "design"
    strategy_guide_path = design_dir / "banner-design-strategy.md"
    design_md_path = design_dir / "DESIGN.md"
    guide_path = design_dir / "banner-design.md"
    strategy_input_path = design_dir / "banner-design-strategist-input.json"
    strategy_output_path = design_dir / "banner-design-strategy.json"
    strategy_json = getattr(args, "strategy_json", None)
    data_only_diagnostic = bool(getattr(args, "data_only_diagnostic", False))

    if not getattr(args, "force", False) and not strategy_json and not data_only_diagnostic:
        fresh_date = _fresh_static_banner_guide_date(strategy_guide_path if strategy_guide_path.exists() else guide_path, STATIC_BANNER_REFRESH_DAYS)
        if fresh_date:
            print(f"banner design guide is fresh from {fresh_date}: {strategy_guide_path if strategy_guide_path.exists() else guide_path}")
            print("use --force to regenerate before the 90-day refresh window")
            return

    min_imp = float(getattr(args, "min_impressions", None) or profile.get("creative_min_impressions", DEFAULT_CREATIVE_MIN_IMPRESSIONS))
    creative_path = Path(args.input).expanduser() if getattr(args, "input", None) else newest_processed("creative", customer_id)
    rows = read_csv(creative_path)
    period_start, period_end = _creative_file_period(creative_path)
    eligible = [
        r for r in rows
        if _is_static_image_asset(r) and number(r.get("impressions")) >= min_imp
    ]
    best_assets_raw = [
        _static_banner_asset(r, _static_banner_ratio_bucket(r), "primary")
        for r in eligible
        if str(r.get("performance_label", "")).upper() == "BEST"
    ]
    good_assets_raw = [
        _static_banner_asset(r, _static_banner_ratio_bucket(r), "secondary")
        for r in eligible
        if str(r.get("performance_label", "")).upper() == "GOOD"
    ]
    if not best_assets_raw and not good_assets_raw:
        die(f"no BEST or GOOD static image assets found above {min_imp:.0f} impressions in {creative_path}")

    best_assets, best_duplicate_groups = _dedupe_static_banner_assets(best_assets_raw)
    good_assets, good_duplicate_groups = _dedupe_static_banner_assets(good_assets_raw)
    primary_assets = best_assets or good_assets
    secondary_assets = [] if best_assets else good_assets
    duplicate_groups = best_duplicate_groups if best_assets else good_duplicate_groups
    grouped = _group_static_banner_assets(primary_assets)
    design_dir.mkdir(parents=True, exist_ok=True)

    run_dir = design_dir / "static-banner-assets" / today().isoformat()
    grouped_with_downloads, manifest_assets = _download_static_banner_assets(grouped, run_dir)
    manifest_payload = {
        "customer_id": customer_id,
        "source_file": str(creative_path),
        "period": {"start": period_start, "end": period_end},
        "min_impressions": min_imp,
        "raw_asset_count": len(best_assets_raw) if best_assets_raw else len(good_assets_raw),
        "unique_image_count": len(primary_assets),
        "image_specs": STATIC_BANNER_SPECS,
        "assets": manifest_assets,
        "duplicate_groups": duplicate_groups,
    }
    manifest_path = _write_static_banner_manifest(run_dir, manifest_payload)

    strategy_payload = {
        "customer_id": customer_id,
        "source_file": str(creative_path),
        "period": {"start": period_start, "end": period_end},
        "min_impressions": min_imp,
        "raw_asset_count": len(best_assets_raw) if best_assets_raw else len(good_assets_raw),
        "unique_image_count": len(primary_assets),
        "image_specs": STATIC_BANNER_SPECS,
        "asset_manifest": str(manifest_path),
        "assets_by_ratio": grouped_with_downloads,
        "duplicate_groups": duplicate_groups,
        "secondary_good_assets": secondary_assets,
        "required_output_schema": {
            "status": "str",
            "image_inspected_count": "int",
            "raw_asset_count": "int",
            "unique_image_count": "int",
            "creative_observations": "list[dict]",
            "duplicate_groups": "list[dict]",
            "winning_patterns": "list[str]",
            "visual_language": "list[str]",
            "brand_colors": "dict[str, dict | str]",
            "typography_signals": "dict[str, dict | str]",
            "component_patterns": "list[str]",
            "brand_signals": "list[str]",
            "token_confidence_notes": "list[str]",
            "ratio_rules": "dict[str, str]",
            "message_hierarchy": "list[str]",
            "cta_rules": "list[str]",
            "brand_and_product_rules": "list[str]",
            "visual_style": "list[str]",
            "avoid": "list[str]",
            "future_generation_contract_notes": "list[str]",
        },
    }
    strategy_input_path.write_text(json.dumps(strategy_payload, indent=2, ensure_ascii=False) + "\n")

    strategy: dict[str, Any]
    if strategy_json:
        strategy_path = Path(strategy_json).expanduser()
        strategy = json.loads(strategy_path.read_text())
        if strategy_path != strategy_output_path:
            strategy_output_path.write_text(json.dumps(strategy, indent=2, ensure_ascii=False) + "\n")
        if not _strategy_has_visual_evidence(strategy):
            die(
                f"strategy JSON has no visual evidence: {strategy_path}. "
                "Expected image_inspected_count > 0 or creative_observations."
            )
    elif data_only_diagnostic:
        strategy = _build_default_static_banner_strategy(grouped_with_downloads)
    else:
        downloaded = sum(1 for asset in manifest_assets if asset.get("download_status") == "downloaded")
        with_url = sum(1 for asset in manifest_assets if asset.get("source_url"))
        print(f"static banner strategist packet written: {strategy_input_path}")
        print(f"asset manifest written:                  {manifest_path}")
        print(f"unique images downloaded: {downloaded}/{len(manifest_assets)}")
        print(f"unique visuals: {len(primary_assets)} | raw placements: {len(best_assets_raw) if best_assets_raw else len(good_assets_raw)}")
        if with_url == 0:
            print(
                "\nNo image URLs are present in the selected creative data, so I did not write the final strategy or design docs. "
                "Refetch creative_period with the updated query, aggregate it, "
                "then rerun this command."
            )
        else:
            print(
                "\nRun the bob-static-banners skill with the strategist packet, save its JSON as "
                f"{design_dir / 'banner-design-strategy.json'}, then finalize with:\n"
                f"  ./bob suggest-static-banners --customer {customer_id} --force "
                f"--strategy-json {design_dir / 'banner-design-strategy.json'}"
            )
        return

    _write_static_banner_strategy_markdown(
        strategy_guide_path,
        customer_id,
        period_start,
        period_end,
        grouped_with_downloads,
        secondary_assets,
        strategy,
        strategy_input_path,
        design_md_path,
        currency,
        diagnostic=data_only_diagnostic,
    )
    _write_static_banner_design_md(
        design_md_path,
        strategy,
        strategy_guide_path,
        customer_id,
    )
    _write_static_banner_overview_markdown(
        guide_path,
        strategy_guide_path,
        design_md_path,
        len(primary_assets),
        diagnostic=data_only_diagnostic,
    )
    entry = (
        f"- [{'Static Banner Diagnostic' if data_only_diagnostic else 'Static Banner Design'} — {today().isoformat()}](design/banner-design.md) — "
        f"strategy + DESIGN.md from {len(primary_assets)} unique {'BEST' if best_assets else 'GOOD'} visual families"
        + ("; GOOD fallback used" if not best_assets else "")
    )
    _write_static_banner_index_entry(wiki_base / "Index.md", entry, section="Design")

    print(f"{'banner diagnostic overview' if data_only_diagnostic else 'banner design overview'} written: {guide_path}")
    print(f"banner strategy written:     {strategy_guide_path}")
    print(f"design spec written:         {design_md_path}")
    print(f"strategist input written:    {strategy_input_path}")


def suggest_static_variants(args: argparse.Namespace) -> None:
    """Prepare LOW static image candidates for source-guided same-size variants."""
    explicit_customer = getattr(args, "customer", None)
    profile = load_profile(required=not bool(explicit_customer))
    if explicit_customer:
        customer_key = str(explicit_customer).replace("-", "")
        account_profile = ACCOUNTS_DIR / customer_key / "profile.json"
        if account_profile.exists():
            profile = json.loads(account_profile.read_text())
        else:
            profile = dict(profile)
            profile["google_ads_customer_id"] = explicit_customer
    customer_id = profile.get("google_ads_customer_id") or "unknown"
    wiki_base = account_wiki_dir(customer_id) if customer_id != "unknown" else ROOT / "wiki"
    design_dir = wiki_base / "design"

    min_imp = float(getattr(args, "min_impressions", None) or profile.get("creative_min_impressions", DEFAULT_CREATIVE_MIN_IMPRESSIONS))
    creative_path = Path(args.input).expanduser() if getattr(args, "input", None) else newest_processed("creative", customer_id)
    rows = read_csv(creative_path)
    period_start, period_end = _creative_file_period(creative_path)

    low_static_assets_raw = [
        _static_banner_asset(r, _static_banner_ratio_bucket(r), "low_static_variant_candidate")
        for r in rows
        if _is_static_image_asset(r)
        and str(r.get("performance_label", "")).upper() == "LOW"
        and number(r.get("impressions")) >= min_imp
    ]
    if not low_static_assets_raw:
        print(f"no LOW static image assets found above {min_imp:.0f} impressions in {creative_path}")
        return

    low_static_assets = sorted(
        low_static_assets_raw,
        key=lambda asset: (
            number(asset.get("impressions")),
            number(asset.get("clicks")),
            str(asset.get("asset_id", "")),
        ),
        reverse=True,
    )
    grouped = _group_static_banner_assets(low_static_assets)
    run_dir = design_dir / "low-static-variants" / today().isoformat()
    grouped_with_downloads, manifest_assets = _download_static_banner_assets(grouped, run_dir)

    manifest_payload = {
        "customer_id": customer_id,
        "source_file": str(creative_path),
        "period": {"start": period_start, "end": period_end},
        "min_impressions": min_imp,
        "workflow": "low_static_variant_preview",
        "status": "prepared_candidates_only",
        "candidate_count": len(manifest_assets),
        "image_specs": STATIC_BANNER_SPECS,
        "design_references": {
            "landing": str(design_dir / "banner-design.md"),
            "design": str(design_dir / "DESIGN.md"),
        },
        "generation_contract": {
            "source_visual_step": "inspect each local_path with the runtime's visual-input capability before prompt construction",
            "hard_sla_step": "ask the user for hard SLA constraints before every regeneration",
            "output_size_rule": "generate exactly one replacement variant at the source asset native dimensions",
            "qa_scope": "spec-only: readable output, width match, height match, output path recorded, no Google Ads mutation",
            "upload_scope": "preview only; do not upload or replace Google Ads assets",
        },
        "assets_by_ratio": grouped_with_downloads,
        "assets": manifest_assets,
    }
    manifest_path = _write_static_banner_manifest(run_dir, manifest_payload)

    downloaded = sum(1 for asset in manifest_assets if asset.get("download_status") == "downloaded")
    with_url = sum(1 for asset in manifest_assets if asset.get("source_url"))
    print(f"LOW static variant candidates written: {manifest_path}")
    print(f"candidate images downloaded: {downloaded}/{len(manifest_assets)}")
    print(f"source URLs present: {with_url}/{len(manifest_assets)}")
    print("next: use the bob-static-banners LOW Static Variant Workflow with this manifest; ask for hard SLA constraints before each generation")


def _image_file_info(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        if len(data) < 24:
            die(f"invalid PNG image: {path}")
        width = int.from_bytes(data[16:20], "big")
        height = int.from_bytes(data[20:24], "big")
        return {"data": data, "width": width, "height": height, "mime": "IMAGE_PNG", "bytes": len(data)}
    if data.startswith(b"\xff\xd8"):
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            i += 2
            if marker in {0xD8, 0xD9, 0x01} or 0xD0 <= marker <= 0xD7:
                continue
            if i + 2 > len(data):
                break
            segment_len = int.from_bytes(data[i:i + 2], "big")
            if segment_len < 2 or i + segment_len > len(data):
                break
            if marker in {
                0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
            }:
                height = int.from_bytes(data[i + 3:i + 5], "big")
                width = int.from_bytes(data[i + 5:i + 7], "big")
                return {"data": data, "width": width, "height": height, "mime": "IMAGE_JPEG", "bytes": len(data)}
            i += segment_len
        die(f"could not read JPEG dimensions: {path}")
    die(f"unsupported image format for Google Ads upload: {path} (use PNG or JPEG)")


def _resolve_relative_path(path_text: str, base_dir: Path) -> Path:
    path = Path(str(path_text)).expanduser()
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    return path


def _load_static_variant_apply_changes(args: argparse.Namespace) -> tuple[dict[str, Any], list[dict[str, Any]], Path | None]:
    plan_path: Path | None = Path(args.plan).expanduser() if getattr(args, "plan", None) else None
    if plan_path:
        if not plan_path.exists():
            die(f"plan file not found: {plan_path}")
        try:
            import yaml as _yaml
        except ImportError:
            die("pyyaml is required for --plan. Install: pip install pyyaml")
        plan = _yaml.safe_load(plan_path.read_text()) or {}
        if plan.get("applied"):
            die(f"plan already applied on {plan.get('applied_at')}")
        changes = plan.get("changes") or plan.get("replacements") or []
        if not isinstance(changes, list):
            die("static variant apply plan must contain changes: [...]")
        return plan, changes, plan_path

    manifest_arg = getattr(args, "manifest", None)
    asset_id_arg = getattr(args, "asset_id", None)
    replacement_arg = getattr(args, "replacement", None)
    if not manifest_arg or not asset_id_arg or not replacement_arg:
        die("provide either --plan or all of --manifest, --asset-id, and --replacement")
    plan = {
        "customer_id": "",
        "manifest": manifest_arg,
        "changes": [
            {
                "asset_id": str(asset_id_arg),
                "replacement_image": replacement_arg,
                "action": "replace",
            }
        ],
        "applied": False,
    }
    return plan, plan["changes"], None


def _static_variant_manifest_assets(manifest_path: Path) -> dict[str, dict[str, Any]]:
    if not manifest_path.exists():
        die(f"manifest file not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text())
    assets = manifest.get("assets") or []
    if not isinstance(assets, list):
        die(f"manifest has no assets list: {manifest_path}")
    return {str(asset.get("asset_id", "")): asset for asset in assets if asset.get("asset_id")}


def static_variants_apply(args: argparse.Namespace) -> None:
    """Upload generated static variant images and swap them into matching app ads."""
    plan, changes, plan_path = _load_static_variant_apply_changes(args)
    if not changes:
        print("no static image replacements in plan — nothing to apply")
        return

    manifest_text = str(getattr(args, "manifest", None) or plan.get("manifest") or "")
    if not manifest_text:
        die("static variant apply requires a manifest path")
    manifest_path = Path(manifest_text).expanduser()
    if not manifest_path.is_absolute() and plan_path:
        manifest_path = (plan_path.parent / manifest_path).resolve()
    manifest_base = manifest_path.parent
    manifest_assets = _static_variant_manifest_assets(manifest_path)

    profile = load_profile(required=False)
    customer_id = str(plan.get("customer_id") or profile.get("google_ads_customer_id", "")).replace("-", "")
    if not customer_id:
        die("customer_id missing from plan and profile")

    prepared: list[dict[str, Any]] = []
    for idx, change in enumerate(changes, 1):
        if str(change.get("action", "replace")) != "replace":
            continue
        asset_id = str(change.get("asset_id", "")).strip()
        replacement_text = change.get("replacement_image") or change.get("replacement_path") or change.get("image")
        if not asset_id or not replacement_text:
            die(f"change #{idx} must include asset_id and replacement_image")
        source = manifest_assets.get(asset_id)
        if not source:
            die(f"asset_id {asset_id} not found in manifest {manifest_path}")
        replacement_path = _resolve_relative_path(str(replacement_text), manifest_base)
        if not replacement_path.exists():
            die(f"replacement image not found for asset {asset_id}: {replacement_path}")
        info = _image_file_info(replacement_path)
        source_width = int(number(source.get("width")) or 0)
        source_height = int(number(source.get("height")) or 0)
        if source_width and info["width"] != source_width:
            die(f"width mismatch for asset {asset_id}: source {source_width}, replacement {info['width']}")
        if source_height and info["height"] != source_height:
            die(f"height mismatch for asset {asset_id}: source {source_height}, replacement {info['height']}")
        if info["bytes"] > 5_000_000:
            die(f"replacement image exceeds 5MB Google image asset limit: {replacement_path}")
        prepared.append({
            "asset_id": asset_id,
            "old_asset_resource": f"customers/{customer_id}/assets/{asset_id}",
            "replacement_path": str(replacement_path),
            "image_info": info,
            "campaign_name": source.get("campaign_name", ""),
            "ad_group_id": str(source.get("ad_group_id", "")),
            "ad_group_name": source.get("ad_group_name", ""),
            "field_type": source.get("field_type", ""),
            "source_width": source_width,
            "source_height": source_height,
            "asset_name": source.get("asset_name", ""),
        })

    if not prepared:
        print("no replace actions in plan — nothing to apply")
        return

    print(f"\n{'#':<3}  {'Campaign':<28}  {'Ad group':<28}  {'Asset':<16}  {'Size':>11}  Replacement")
    print("─" * 120)
    for idx, item in enumerate(prepared, 1):
        size = f"{item['image_info']['width']}x{item['image_info']['height']}"
        print(
            f"{idx:<3}  {item['campaign_name'][:28]:<28}  {item['ad_group_name'][:28]:<28}  "
            f"{item['asset_id']:<16}  {size:>11}  {item['replacement_path']}"
        )

    if getattr(args, "dry_run", False):
        print("\n[dry-run] no Google Ads changes applied")
        return

    print("\nApprove upload + app-ad image replacement? [y/n]: ", end="", flush=True)
    try:
        answer = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\nAborted.")
        return
    if answer != "y":
        print("Aborted — no changes applied.")
        return

    try:
        import yaml as _yaml
        from google.ads.googleads.client import GoogleAdsClient  # type: ignore
        from google.ads.googleads.errors import GoogleAdsException  # type: ignore
        from google.protobuf.field_mask_pb2 import FieldMask  # type: ignore
    except ImportError:
        die("google-ads and pyyaml are required for static-variants-apply")

    config_path = str(_resolve_profile_config_path(profile, write=True))
    try:
        client = GoogleAdsClient.load_from_storage(config_path)
    except Exception as exc:
        die(f"failed to load Google Ads client: {exc}")

    ga_svc = client.get_service("GoogleAdsService")
    ad_svc = client.get_service("AdService")
    asset_svc = client.get_service("AssetService")
    results: list[dict[str, Any]] = []

    for item in prepared:
        asset_op = client.get_type("AssetOperation")
        created_asset = asset_op.create
        source_name = item.get("asset_name") or item["asset_id"]
        created_asset.name = f"Bob static variant {source_name} {today().isoformat()}"
        created_asset.image_asset.data = item["image_info"]["data"]
        created_asset.image_asset.mime_type = getattr(client.enums.MimeTypeEnum, item["image_info"]["mime"])
        try:
            asset_response = asset_svc.mutate_assets(customer_id=customer_id, operations=[asset_op])
            new_asset_resource = asset_response.results[0].resource_name
        except GoogleAdsException as exc:
            err_msg = "; ".join(e.message for e in exc.failure.errors)
            results.append({**item, "status": "error", "error": f"upload image asset: {err_msg}"})
            print(f"  ✗ {item['asset_id']} — image upload failed: {err_msg}")
            continue
        except Exception as exc:
            results.append({**item, "status": "error", "error": f"upload image asset: {exc}"})
            print(f"  ✗ {item['asset_id']} — image upload failed: {exc}")
            continue

        gaql = (
            "SELECT ad_group_ad.resource_name,"
            " ad_group_ad.ad.id,"
            " ad_group_ad.ad.app_ad.images"
            " FROM ad_group_ad"
            f" WHERE ad_group.id = {item['ad_group_id']}"
            " AND ad_group_ad.status != 'REMOVED'"
        )
        try:
            rows = list(ga_svc.search(customer_id=customer_id, query=gaql))
        except Exception as exc:
            results.append({**item, "status": "error", "new_asset_resource": new_asset_resource, "error": f"fetch app ad: {exc}"})
            print(f"  ✗ {item['asset_id']} — could not fetch app ad: {exc}")
            continue

        matched_ad = None
        matched_images: list[str] = []
        for row in rows:
            image_assets = [img.asset for img in row.ad_group_ad.ad.app_ad.images]
            if item["old_asset_resource"] in image_assets:
                matched_ad = row.ad_group_ad
                matched_images = image_assets
                break
        if not matched_ad:
            results.append({**item, "status": "error", "new_asset_resource": new_asset_resource, "error": "source image asset not found in app ad"})
            print(f"  ✗ {item['asset_id']} — source image asset not found in app ad")
            continue

        replaced_images = [
            new_asset_resource if asset == item["old_asset_resource"] else asset
            for asset in matched_images
        ]
        ad_id = matched_ad.ad.id
        ad_rn = ad_svc.ad_path(customer_id, str(ad_id))
        ad_op = client.get_type("AdOperation")
        ad_update = ad_op.update
        ad_update.resource_name = ad_rn
        for asset_resource in replaced_images:
            image_asset = client.get_type("AdImageAsset")
            image_asset.asset = asset_resource
            ad_update.app_ad.images.append(image_asset)
        mask = FieldMask()
        mask.paths.append("app_ad.images")
        ad_op.update_mask.CopyFrom(mask)

        try:
            ad_svc.mutate_ads(customer_id=customer_id, operations=[ad_op])
            results.append({
                **item,
                "status": "replaced",
                "ad_id": ad_id,
                "ad_resource": ad_rn,
                "new_asset_resource": new_asset_resource,
            })
            print(f"  ✓ {item['asset_id']} — uploaded {new_asset_resource} and replaced in ad {ad_id}")
        except GoogleAdsException as exc:
            err_msg = "; ".join(e.message for e in exc.failure.errors)
            results.append({**item, "status": "error", "new_asset_resource": new_asset_resource, "error": f"update app ad: {err_msg}"})
            print(f"  ✗ {item['asset_id']} — app ad update failed: {err_msg}")
        except Exception as exc:
            results.append({**item, "status": "error", "new_asset_resource": new_asset_resource, "error": f"update app ad: {exc}"})
            print(f"  ✗ {item['asset_id']} — app ad update failed: {exc}")

    errors = [r for r in results if r.get("status") == "error"]
    import datetime as _dt
    plan["applied"] = not errors
    plan["applied_at"] = _dt.datetime.now().isoformat(timespec="seconds")
    plan["applied_by"] = "static-variants-apply"
    plan["apply_results"] = [
        {k: v for k, v in r.items() if k != "image_info"}
        for r in results
    ]
    if plan_path:
        plan_path.write_text(_yaml.dump(plan, default_flow_style=False, allow_unicode=True, sort_keys=False))
        print(f"\nplan updated: {plan_path}")

    n_replaced = sum(1 for r in results if r.get("status") == "replaced")
    print(f"\n{n_replaced} static image replacement(s) live, {len(errors)} error(s)")
    if errors:
        raise SystemExit(2)


def _fetch_asset_texts(client, customer_id: str, asset_ids: list) -> dict:
    """Fetch text content from ad_group_ad_asset_view, TEXT assets only."""
    if not asset_ids:
        return {}
    ga_service = client.get_service("GoogleAdsService")
    id_list = ", ".join(str(i) for i in asset_ids[:500])
    query = (
        "SELECT asset.id, asset.text_asset.text "
        "FROM ad_group_ad_asset_view "
        "WHERE asset.type = 'TEXT' "
        f"AND asset.id IN ({id_list})"
    )
    result = {}
    try:
        response = ga_service.search(customer_id=customer_id, query=query)
        for row in response:
            result[str(row.asset.id)] = row.asset.text_asset.text or ""
    except Exception as exc:
        print(f"  warning: could not fetch asset text: {exc}")
    return result


def suggest_creative_copy(args: argparse.Namespace) -> None:
    """Generate a copy plan YAML + compact agent-agnostic prompt for LOW-action text assets."""
    import datetime as _dt
    try:
        import yaml as _yaml
    except ImportError:
        die("pyyaml is required: pip install pyyaml")

    profile = load_profile(required=False)
    min_imp = float(getattr(args, "min_impressions", None) or profile.get("creative_min_impressions", 50000))
    primary_goal = profile.get("primary_goal", "in_app_conversions")
    customer_id = profile.get("google_ads_customer_id", "unknown")

    creative_path = newest_processed("creative", customer_id)
    rows = read_csv(creative_path)
    eligible = [r for r in rows if number(r.get("impressions", 0)) >= min_imp]

    # Campaign-level averages per (campaign_id, asset_type)
    camp_agg: dict[tuple, dict] = {}
    for r in eligible:
        key = (r.get("campaign_id", ""), r.get("campaign_name", ""), r.get("asset_type", ""))
        if key not in camp_agg:
            camp_agg[key] = {"imp": 0.0, "clicks": 0.0, "installs": 0.0, "cost": 0.0}
        camp_agg[key]["imp"] += number(r.get("impressions", 0))
        camp_agg[key]["clicks"] += number(r.get("clicks", 0))
        camp_agg[key]["installs"] += number(r.get("installs", 0))
        camp_agg[key]["cost"] += number(r.get("cost", 0))
    for m in camp_agg.values():
        m["ctr"] = m["clicks"] / m["imp"] * 100 if m["imp"] > 0 else 0.0
        m["cti"] = m["installs"] / m["clicks"] * 100 if m["clicks"] > 0 else 0.0
        m["cpc"] = m["cost"] / m["clicks"] if m["clicks"] > 0 else 0.0

    # Peer counts per (campaign_id, asset_type) for meaningful comparison
    peer_counts: dict[tuple, int] = {}
    for r in eligible:
        key = (r.get("campaign_id", ""), r.get("campaign_name", ""), r.get("asset_type", ""))
        peer_counts[key] = peer_counts.get(key, 0) + 1

    # Current asset count per (ad_group_id, field_type) — used for limit check in apply
    ag_field_counts: dict[tuple, int] = {}
    for r in rows:  # full set, not just eligible
        key = (r.get("ad_group_id", ""), r.get("field_type", ""))
        ag_field_counts[key] = ag_field_counts.get(key, 0) + 1

    # LOW-action TEXT candidates (same 2-metric test as slice_creatives)
    low_rows = [r for r in eligible if r.get("performance_label", "").upper() == "LOW" and r.get("asset_type", "") == "TEXT"]
    changes = []
    for r in low_rows:
        cid = r.get("campaign_id", "")
        cname = r.get("campaign_name", "")
        ft = r.get("field_type", "")
        cm = camp_agg.get((cid, cname, "TEXT"), {})
        peers = peer_counts.get((cid, cname, "TEXT"), 0)

        asset_ctr = number(r.get("ctr_percent", 0))
        asset_cti = number(r.get("cti_percent", 0))
        asset_cpc = number(r.get("cpc", 0))
        worse_ctr = asset_ctr < cm.get("ctr", 0) * 0.90 if cm.get("ctr", 0) > 0 else False
        worse_cti = asset_cti < cm.get("cti", 0) * 0.90 if cm.get("cti", 0) > 0 else False
        worse_cpc = asset_cpc > cm.get("cpc", 0) * 1.10 if cm.get("cpc", 0) > 0 else False

        is_low_action = peers <= 1 or sum([worse_ctr, worse_cti, worse_cpc]) >= 2
        if not is_low_action:
            continue

        # Primary failing metric for prompt (most actionable signal)
        if worse_ctr:
            metric_note = f"CTR {asset_ctr:.1f}% vs avg {cm.get('ctr', 0):.1f}%"
        elif worse_cti:
            metric_note = f"CTI {asset_cti:.1f}% vs avg {cm.get('cti', 0):.1f}%"
        else:
            metric_note = f"CPC {asset_cpc:.2f} vs avg {cm.get('cpc', 0):.2f}"

        changes.append({
            "campaign_id": cid,
            "campaign_name": cname,
            "ad_group_id": r.get("ad_group_id", ""),
            "ad_group_name": r.get("ad_group_name", ""),
            "asset_id": r.get("asset_id", ""),
            "field_type": ft,
            "current_text": "",
            "current_asset_count": ag_field_counts.get((r.get("ad_group_id", ""), ft), 0),
            "ctr_percent": format_float(asset_ctr),
            "campaign_avg_ctr": format_float(cm.get("ctr", 0)),
            "cti_percent": format_float(asset_cti),
            "campaign_avg_cti": format_float(cm.get("cti", 0)),
            "cpc": format_float(asset_cpc),
            "campaign_avg_cpc": format_float(cm.get("cpc", 0)),
            "_metric_note": metric_note,  # used for prompt only, not written to YAML
            "suggested_text": None,
            "action": "replace",
        })

    # Fetch asset text content via a targeted TEXT-only query
    all_asset_ids = list({c["asset_id"] for c in changes})
    text_map: dict = {}
    try:
        from google.ads.googleads.client import GoogleAdsClient
        config_path = str(_resolve_profile_config_path(profile, write=True))
        _ga_client = GoogleAdsClient.load_from_storage(config_path)
        text_map = _fetch_asset_texts(_ga_client, customer_id.replace("-", ""), all_asset_ids)
    except ImportError:
        print("  warning: google-ads not installed — text content unavailable")
    except Exception as _exc:
        print(f"  warning: Google Ads client load failed — text content unavailable: {_exc}")
    for c in changes:
        c["current_text"] = text_map.get(str(c["asset_id"]), "")

    # Assign 1-based index to each change so the subagent can reference by number
    for i, c in enumerate(changes, 1):
        c["change_index"] = i

    today = _dt.date.today().isoformat()
    out_dir = Path(getattr(args, "output_dir", None) or "wiki/action-items")
    out_dir.mkdir(parents=True, exist_ok=True)
    yaml_path = out_dir / f"creative-copy-{today}.yaml"
    prompt_path = out_dir / f"creative-copy-{today}-prompt.txt"

    # Strip internal keys before writing YAML
    _strip = {"_metric_note"}
    yaml_changes = [{k: v for k, v in c.items() if k not in _strip} for c in changes]
    plan = {
        "date": today,
        "customer_id": customer_id,
        "changes": yaml_changes,
        "applied": False,
        "applied_at": None,
    }
    with open(yaml_path, "w") as f:
        _yaml.dump(plan, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    _rules_header = [
        "App campaign copy rules:",
        "- HEADLINE ≤ 30 chars, DESCRIPTION ≤ 90 chars",
        "- Lead with a specific app benefit — not a generic phrase",
        "- Each asset must work standalone AND in combination with other assets and images",
        "- Every DESCRIPTION must end with punctuation (. or !) — max 1 exclamation mark per asset",
        "- Do not copy text already GOOD or BEST in the same ad group",
        "- If the current text contains a proper noun (place name, landmark, neighbourhood — e.g. \"Dum Dum airport\", \"Kalighat\"), keep it in the replacement. Tweak the surrounding copy, never swap the proper noun for a generic term.",
        "",
        "For each numbered asset below write one replacement following the rules above.",
        "Do NOT reuse the current text. Stay within the character limit for the field type.",
        "",
    ]

    batch_size = getattr(args, "batch_size", 25)
    batches = [changes[i:i + batch_size] for i in range(0, len(changes), batch_size)]
    prompt_paths = []
    for b_idx, batch in enumerate(batches, 1):
        b_path = out_dir / f"creative-copy-{today}-batch-{b_idx:03d}.txt"
        b_lines = list(_rules_header)
        for c in batch:
            b_lines.append(
                f'{c["change_index"]}. [{c["campaign_name"]} / {c["field_type"]}]'
                f'  ad_group: {c["ad_group_name"]}'
            )
            if c.get("current_text"):
                b_lines.append(f'   Current: "{c["current_text"][:60]}" — {c["_metric_note"]}')
        first_id = batch[0]["change_index"]
        last_id = batch[-1]["change_index"]
        b_lines += ['', f'Output ONLY: [{{"id":{first_id},"text":"..."}},{{"id":{last_id},"text":"..."}}]']
        b_path.write_text("\n".join(b_lines))
        prompt_paths.append((b_path, first_id, last_id))

    print(f"\nPlan:    {yaml_path}")
    print(f"Batches: {len(batches)} prompt files ({batch_size} assets each, last may be smaller)")
    for b_path, fid, lid in prompt_paths:
        print(f"  {b_path}  (assets {fid}–{lid})")
    print(f"\n{len(changes)} assets across {len({c['campaign_id'] for c in changes})} campaigns.")
    print("Use the bob-creative-copy skill — spawn one Agent call per batch file, then run:")
    print(f'  python3 lib/datapull.py creative-copy-apply --plan {yaml_path} --suggestions \'[...json...]\' ')


def creative_copy_apply(args: argparse.Namespace) -> None:
    """Review suggested copy, get user approval, push to Google Ads."""
    import datetime as _dt
    try:
        import yaml as _yaml
    except ImportError:
        die("pyyaml is required: pip install pyyaml")

    plan_path = Path(args.plan).expanduser()
    if not plan_path.exists():
        die(f"plan file not found: {plan_path}")
    plan = _yaml.safe_load(plan_path.read_text())

    if plan.get("applied"):
        die(f"plan already applied on {plan.get('applied_at')}")
    if not plan.get("changes"):
        print("no changes in plan — nothing to apply")
        return

    changes = plan["changes"]
    groups = plan.get("groups", [])
    LIMITS = {"HEADLINE": 30, "DESCRIPTION": 90}

    # Merge --suggestions JSON
    sug_map: dict = {}
    if getattr(args, "suggestions", None):
        import json as _json
        try:
            suggestions = _json.loads(args.suggestions)
        except Exception as e:
            die(f"invalid --suggestions JSON: {e}")
        sug_map = {int(s["id"]): s["text"] for s in suggestions}

    def _broadcast_groups() -> None:
        """Apply sug_map group texts to all matching changes."""
        for c in changes:
            gid = c.get("group_id")
            if gid and sug_map.get(gid):
                c["suggested_text"] = sug_map[gid]

    def _broadcast_legacy() -> None:
        for i, c in enumerate(changes, 1):
            if i in sug_map:
                c["suggested_text"] = sug_map[i]

    if groups:
        _broadcast_groups()
    else:
        _broadcast_legacy()

    # Validate suggestion IDs before doing anything irreversible
    if not groups and sug_map:
        from collections import Counter as _Counter
        sug_ids = list(sug_map.keys())
        n = len(changes)
        out_of_range = [i for i in sug_ids if i < 1 or i > n]
        duplicates = [i for i, cnt in _Counter(sug_ids).items() if cnt > 1]
        missing = [i for i in range(1, n + 1)
                   if i not in sug_map and changes[i - 1].get("action") == "replace"]
        if out_of_range:
            print(f"  ERROR: {len(out_of_range)} suggestion IDs out of range (1–{n}): "
                  f"{out_of_range[:5]}{'...' if len(out_of_range) > 5 else ''}")
        if duplicates:
            print(f"  ERROR: duplicate suggestion IDs: "
                  f"{duplicates[:5]}{'...' if len(duplicates) > 5 else ''}")
        if missing:
            print(f"  WARNING: {len(missing)} assets have no suggestion and will be skipped")
        if out_of_range or duplicates:
            print("  Suggestion set looks corrupted (ID drift). "
                  "Re-run suggest-creative-copy and regenerate all batches.")
            return

    # Validate character limits and null out violators
    if groups:
        for g in groups:
            text = sug_map.get(g["group_id"], "")
            if text:
                limit = LIMITS.get(g["field_type"], 90)
                if len(text) > limit:
                    print(f"  WARNING: group {g['group_id']} [{g['field_type']}/{g['language']}] "
                          f"'{text}' is {len(text)} chars (limit {limit}) — will be skipped")
                    sug_map[g["group_id"]] = None
        _broadcast_groups()
    else:
        for i, c in enumerate(changes, 1):
            st = c.get("suggested_text")
            if st:
                limit = LIMITS.get(c.get("field_type", ""), 90)
                if len(st) > limit:
                    print(f"  WARNING: #{i} '{st}' is {len(st)} chars (limit {limit}) — will be skipped")
                    c["suggested_text"] = None

    # Approval table
    if groups:
        print(f"\n{'#':<3}  {'Theme':<28}  {'Field':<12}  {'Lang':<10}  {'N':<4}  Suggested")
        print("─" * 100)
        for g in groups:
            gid = g["group_id"]
            text = sug_map.get(gid) or "—"
            chars = len(text) if text != "—" else 0
            theme_col = g.get("theme", g.get("field_type", ""))[:27]
            print(f"{gid:<3}  {theme_col:<28}  {g['field_type']:<12}  {g['language']:<10}  "
                  f"{g['asset_count']:<4}  \"{text[:45]}\"({chars})")
    else:
        actionable = [c for c in changes if c.get("action") in ("replace", "pause")]
        if not actionable:
            print("No actionable changes (suggested_text missing or over limit).")
            return
        print(f"\n{'#':<3}  {'Campaign':<22}  {'Field':<12}  {'Current':<32}  {'Suggested':<32}  Metric vs avg")
        print("─" * 120)
        for i, c in enumerate(changes, 1):
            if c.get("action") not in ("replace", "pause"):
                continue
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
            for g in groups:
                gid = g["group_id"]
                text = sug_map.get(gid) or "—"
                theme_col = g.get("theme", g.get("field_type", ""))[:27]
                print(f"{gid:<3}  {theme_col:<28}  {g['field_type']:<12}  {g['language']:<10}  "
                      f"{g['asset_count']:<4}  \"{text[:45]}\"")
        else:
            print(f"\n{'#':<3}  {'Field':<12}  {'Suggested'}")
            for i, c in enumerate(changes, 1):
                print(f"{i:<3}  {c.get('field_type',''):<12}  {c.get('suggested_text') or '—'}")
        print("\nApprove all? [y/n/edit N]: ", end="", flush=True)
        try:
            answer = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            break

    if answer != "y":
        print("Aborted — no changes applied.")
        return

    try:
        from google.ads.googleads.client import GoogleAdsClient  # type: ignore
        from google.ads.googleads.errors import GoogleAdsException  # type: ignore
        from google.protobuf.field_mask_pb2 import FieldMask  # type: ignore
    except ImportError:
        die("google-ads library required: pip install google-ads")

    profile = load_profile(required=False)
    config_path = str(_resolve_profile_config_path(profile, write=True))
    customer_id = str(plan.get("customer_id", profile.get("google_ads_customer_id", ""))).replace("-", "")

    try:
        client = GoogleAdsClient.load_from_storage(config_path)
    except Exception as exc:
        die(f"failed to load Google Ads client: {exc}")

    ga_svc = client.get_service("GoogleAdsService")
    ad_svc = client.get_service("AdService")

    results = []
    today = _dt.date.today().isoformat()

    from collections import defaultdict as _defaultdict
    ag_to_changes: dict = _defaultdict(list)
    for i, c in enumerate(changes, 1):
        if c.get("action") in ("replace", "pause") and (
            c.get("action") == "pause" or c.get("suggested_text")
        ):
            ag_to_changes[str(c.get("ad_group_id", ""))].append((i, c))

    for ag_id, ag_changes in ag_to_changes.items():
        gaql = (
            "SELECT ad_group_ad.resource_name,"
            " ad_group_ad.ad.id,"
            " ad_group_ad.ad.app_ad.headlines,"
            " ad_group_ad.ad.app_ad.descriptions"
            f" FROM ad_group_ad"
            f" WHERE ad_group.id = {ag_id}"
            f" AND ad_group_ad.status != 'REMOVED'"
            f" LIMIT 1"
        )
        try:
            rows = list(ga_svc.search(customer_id=customer_id, query=gaql))
        except Exception as exc:
            for _, c in ag_changes:
                results.append({"campaign": c.get("campaign_name", ""), "asset_id": c.get("asset_id", ""),
                                 "field_type": c.get("field_type", ""), "status": "error",
                                 "error": f"fetch app ad: {exc}"})
                print(f"  ✗ {c.get('campaign_name','')} / {c.get('field_type','')} — fetch failed: {exc}")
            continue

        if not rows:
            for _, c in ag_changes:
                results.append({"campaign": c.get("campaign_name", ""), "asset_id": c.get("asset_id", ""),
                                 "field_type": c.get("field_type", ""), "status": "error",
                                 "error": "no app ad found for ad group"})
                print(f"  ✗ {c.get('campaign_name','')} / {c.get('field_type','')} — no app ad in ad group {ag_id}")
            continue

        row_ad = rows[0].ad_group_ad
        ad_id = row_ad.ad.id
        ad_rn = ad_svc.ad_path(customer_id, str(ad_id))
        headlines = [h.text for h in row_ad.ad.app_ad.headlines]
        descriptions = [d.text for d in row_ad.ad.app_ad.descriptions]
        updated_fields: set = set()
        pending_indices: list = []

        for _, c in ag_changes:
            ft = c.get("field_type", "HEADLINE")
            action = c.get("action", "replace")
            current_list = headlines if ft == "HEADLINE" else descriptions
            field_path = "app_ad.headlines" if ft == "HEADLINE" else "app_ad.descriptions"
            target_text = c.get("current_text", "")

            matched_i = next((li for li, t in enumerate(current_list) if t == target_text), None)
            if matched_i is None:
                results.append({"campaign": c.get("campaign_name", ""), "asset_id": c.get("asset_id", ""),
                                 "field_type": ft, "status": "error",
                                 "error": "asset not found in app ad"})
                print(f"  ✗ {c.get('campaign_name','')} / {ft} — asset text not found in app ad")
                continue

            if action == "replace":
                current_list[matched_i] = c.get("suggested_text")
                entry = {"campaign": c.get("campaign_name", ""), "asset_id": c.get("asset_id", ""),
                         "field_type": ft, "suggested_text": c.get("suggested_text"),
                         "status": "pending_commit"}
            else:
                current_list.pop(matched_i)
                entry = {"campaign": c.get("campaign_name", ""), "asset_id": c.get("asset_id", ""),
                         "field_type": ft, "status": "pending_commit"}

            results.append(entry)
            pending_indices.append(len(results) - 1)
            updated_fields.add(field_path)

        if not pending_indices:
            continue

        op = client.get_type("AdOperation")
        ad_upd = op.update
        ad_upd.resource_name = ad_rn
        for text in headlines:
            ad_upd.app_ad.headlines.add().text = text
        for text in descriptions:
            ad_upd.app_ad.descriptions.add().text = text
        mask = FieldMask()
        mask.paths.extend(sorted(updated_fields))
        op.update_mask.CopyFrom(mask)

        try:
            ad_svc.mutate_ads(customer_id=customer_id, operations=[op])
            for ri in pending_indices:
                r = results[ri]
                r["status"] = "replaced" if "suggested_text" in r else "paused"
                if r["status"] == "replaced":
                    print(f"  ✓ {r['campaign']} / {r['field_type']} — replaced: \"{r['suggested_text']}\"")
                else:
                    print(f"  ✓ {r['campaign']} / {r['field_type']} — removed from app ad")
        except GoogleAdsException as exc:
            err_msg = "; ".join(e.message for e in exc.failure.errors)
            for ri in pending_indices:
                results[ri]["status"] = "error"
                results[ri]["error"] = err_msg
                print(f"  ✗ {results[ri]['campaign']} / {results[ri]['field_type']} — failed: {err_msg}")
        except Exception as exc:
            for ri in pending_indices:
                results[ri]["status"] = "error"
                results[ri]["error"] = str(exc)
                print(f"  ✗ {results[ri].get('campaign','')} / {results[ri].get('field_type','')} — failed: {exc}")

    errors = [r for r in results if r.get("status") == "error"]
    plan["applied"] = not errors
    plan["applied_at"] = _dt.datetime.now().isoformat(timespec="seconds")
    plan["apply_results"] = results
    plan["changes"] = changes
    with open(plan_path, "w") as f:
        _yaml.dump(plan, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    n_replaced = sum(1 for r in results if r["status"] == "replaced")
    n_paused = sum(1 for r in results if r["status"] == "paused")
    print(f"\n{n_replaced} new assets live, {n_paused} paused, {len(errors)} errors — plan saved: {plan_path}")
    if errors:
        raise SystemExit(2)


def setup_write_credentials(args: argparse.Namespace) -> None:
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
    except ImportError:
        die("google_auth_oauthlib not installed — run: pip install google-auth-oauthlib")
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


def _profile_customer_id(profile: dict[str, Any]) -> str:
    return str(profile.get("google_ads_customer_id", "")).replace("-", "")


def _account_credentials_dir(customer_id: str) -> str:
    return str(ACCOUNTS_DIR / customer_id.replace("-", ""))


def _default_read_config_path(customer_id: str) -> str:
    return f"{_account_credentials_dir(customer_id)}/google-ads-garf.yaml"


def _default_write_config_path(customer_id: str) -> str:
    return f"{_account_credentials_dir(customer_id)}/google-ads-api.yaml"


def _resolve_profile_config_path(profile: dict[str, Any], *, write: bool = False) -> Path:
    customer_id = _profile_customer_id(profile)
    configured = (
        str(profile.get("google_ads_write_config_path", "") or "").strip()
        if write
        else _profile_read_config_value(profile)
    )
    defaults: list[str] = []
    if configured:
        defaults.append(configured)
    if customer_id:
        defaults.append(_default_write_config_path(customer_id) if write else _default_read_config_path(customer_id))

    seen: set[str] = set()
    for candidate in defaults:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        path = Path(candidate).expanduser()
        if path.exists():
            return path
    fallback = configured
    if not fallback:
        fallback = defaults[0]
    return Path(fallback).expanduser()


def _normalize_account_config_files(profile: dict[str, Any]) -> list[str]:
    customer_id = _profile_customer_id(profile)
    if not customer_id:
        return []

    migrated: list[str] = []
    read_default = Path(_default_read_config_path(customer_id)).expanduser()
    write_default = Path(_default_write_config_path(customer_id)).expanduser()

    read_path = _profile_read_config_value(profile)
    if read_path:
        current_read = Path(read_path).expanduser()
        if current_read != read_default and current_read.exists() and not read_default.exists():
            read_default.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(current_read, read_default)
            migrated.append(f"copied read config into account folder: {read_default}")
        _set_profile_read_config_value(profile, str(read_default))
    elif read_default.exists():
        _set_profile_read_config_value(profile, str(read_default))
        migrated.append("set active account profile to account-folder read config")

    write_path = str(profile.get("google_ads_write_config_path", "") or "").strip()
    if write_path:
        current_write = Path(write_path).expanduser()
        if current_write != write_default and current_write.exists() and not write_default.exists():
            write_default.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(current_write, write_default)
            migrated.append(f"copied write config into account folder: {write_default}")
        profile["google_ads_write_config_path"] = str(write_default)
    elif write_default.exists():
        profile["google_ads_write_config_path"] = str(write_default)
        migrated.append("set active account profile to account-folder write config")

    if migrated:
        _set_active_account(profile)
    return migrated


def _print_section(title: str) -> None:
    print(f"\n  ── {title} {'─' * max(0, 46 - len(title))}")


def onboard(args: argparse.Namespace) -> None:
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

    print("\n  ── Confirm ──────────────────────────────────────────────────────")
    print(f"  Account:       {account_name} ({cid})")
    if mcc_id:
        print(f"  MCC:           {mcc_name} ({mcc_id})" if mcc_name else f"  MCC:           {mcc_id}")
    print(f"  Campaign type: {ct_display.split('[')[0].strip()}")
    if campaign_type == "app":
        print(f"  Primary goal:  {primary_goal}")
    print(f"  Currency:      {currency}")
    print(f"  Read access:   {'ready' if google_ads_read_config_path else 'not set'}")
    print(f"  Write access:  {'ready' if google_ads_write_config_path else 'not set'}")
    print(f"  CAC ceiling:   {cac_ceiling}  |  Change %: {bid_budget_change_pct}  |  Cooldown: {bid_budget_cooldown_days}d")

    confirm = _ob_prompt_help(
        "\n  Save this? (y/n)",
        "Bob needs your confirmation before saving this account setup locally.",
        "Review the summary above. Type y to save or n to stop.",
        "y",
    )
    if confirm.lower() != "y":
        print("No worries. Nothing saved.")
        return

    # Write files
    _set_active_account(profile)
    # Update registry
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

    # ── DONE ──────────────────────────────────────────────────────────────────
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
    _install_with_log(ROOT / "logs" / "setup.log")
    issues = _onboarding_runtime_issues(require_read=True, require_write=False)
    if not issues:
        print("  Setup looks good.")
        return

    print("\n  Still not right:")
    for issue in issues:
        print(f"  - {issue}")
    print(f"\n  Full install log: {ROOT / 'logs' / 'setup.log'}")


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


def log_pull_cmd(args: argparse.Namespace) -> None:
    """Write a pull-log entry without hitting the API — used for cache-hit recording."""
    profile = load_profile(required=False)
    account = args.account or str(profile.get("google_ads_customer_id", "")).replace("-", "")
    log_pull(
        query=args.query,
        from_date=args.from_date or "",
        to_date=args.to or "",
        account=account,
        run_id_val="",
        output_file="",
        reason=args.reason,
        question=args.question,
        outcome=args.outcome,
    )
    print(f"logged: {args.outcome} — {args.query} {args.from_date or ''}..{args.to or ''}")


def log_signal_cmd(args: argparse.Namespace) -> None:
    """Append one self-improvement signal — a friction moment in this session.

    For an immediate, single critical (chiefly `failsafe`). Routine friction is batched
    into one `session-debrief` call at a success beat instead — see that command.
    """
    profile = load_profile(required=False)
    account = args.account or str(profile.get("google_ads_customer_id", "")).replace("-", "")
    entry = log_signal(
        event_type=args.type,
        note=args.note,
        account=account,
        user_text=args.user_text,
        intent=args.intent,
        artifact=args.artifact,
        severity=args.severity,
        source="inline",
    )
    print(f"signal logged: {entry['event_type']} — {entry['note']}")


def session_debrief(args: argparse.Namespace) -> None:
    """Record a batch of self-improvement signals captured at a session success beat.

    The consent-based, in-voice half of capture: Bob tracks where it got stuck during a
    session and, at a clear win (e.g. a wiki write), offers to note it. Only on the user's
    say-so does it call this — one batched write for the whole session, each entry tagged
    source="debrief". The agent-agnostic sibling of log-signal: same schema, same writer,
    so it depends on no runtime internals. An empty list is a clean no-op (no nagging), and
    a malformed batch is validated up front so nothing is half-written.
    """
    profile = load_profile(required=False)
    account = args.account or str(profile.get("google_ads_customer_id", "")).replace("-", "")
    try:
        signals = json.loads(args.signals)
    except json.JSONDecodeError as exc:
        die(f"--signals must be a JSON array of signal objects: {exc}")
    if not isinstance(signals, list):
        die("--signals must be a JSON array, e.g. '[{\"event_type\":\"friction\",\"note\":\"...\"}]'")
    if not signals:
        print("session-debrief: clean session — no signals to record.")
        return
    # Validate every entry before writing any, so a malformed batch appends nothing.
    cleaned = []
    for i, s in enumerate(signals):
        if not isinstance(s, dict):
            die(f"--signals[{i}] must be an object with at least 'event_type' and 'note'")
        event_type = s.get("event_type") or s.get("type")
        note = s.get("note")
        if not event_type or not note:
            die(f"--signals[{i}] needs both 'event_type' and 'note'")
        cleaned.append((event_type, note, s))
    for event_type, note, s in cleaned:
        log_signal(
            event_type=event_type,
            note=note,
            account=s.get("account") or account,
            user_text=s.get("user_text", ""),
            intent=s.get("intent", ""),
            artifact=s.get("artifact", ""),
            severity=s.get("severity", ""),
            source="debrief",
        )
    n = len(cleaned)
    print(f"session-debrief: recorded {n} signal{'s' if n != 1 else ''} from this session.")


def self_improve(args: argparse.Namespace) -> None:
    """Prep step for a self-improvement pass. Summarises logged signals and points the
    agent at the files to read. Does NOT call any model — clustering and the proposal
    are the agent's job (see the bob-self-improve skill). Manual, proposal-only."""
    signals = _read_signal_log()
    backlog = ROOT / "logs" / "backlog.md"
    if not signals:
        print("No signals logged yet (logs/session-signals.jsonl is empty or missing).")
        print("Nothing to synthesize. Signals accumulate as agents call `./bob log-signal`.")
        return
    by_type: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    by_source: dict[str, int] = {}
    for s in signals:
        et = s.get("event_type", "?")
        by_type[et] = by_type.get(et, 0) + 1
        sev = s.get("severity")
        if sev:
            by_severity[sev] = by_severity.get(sev, 0) + 1
        src = s.get("source")
        if src:
            by_source[src] = by_source.get(src, 0) + 1
    print(f"Self-improvement signals: {len(signals)} total\n")
    print("By event type:")
    for k in sorted(by_type, key=lambda x: -by_type[x]):
        print(f"  {by_type[k]:>4}  {k}")
    if by_severity:
        print("\nBy severity:")
        for k in sorted(by_severity, key=lambda x: -by_severity[x]):
            print(f"  {by_severity[k]:>4}  {k}")
    if by_source:
        print("\nBy source (cli=auto, inline=log-signal, debrief=session-debrief):")
        for k in sorted(by_source, key=lambda x: -by_source[x]):
            print(f"  {by_source[k]:>4}  {k}")
    print("\nRead these to cluster pitfalls and write the proposal:")
    print(f"  signals : {SIGNAL_LOG_PATH}")
    if backlog.exists():
        print(f"  backlog : {backlog}")
    plan_path = SELF_IMPROVE_DIR / f"action-plan-{today().isoformat()}.md"
    print(f"\nWrite the proposal-only action plan to: {plan_path}")
    print("Nothing is changed by this command. See the bob-self-improve skill for the synthesis steps.")


def _load_sync_config() -> dict:
    if not SYNC_CONFIG_PATH.exists():
        return {}
    with SYNC_CONFIG_PATH.open() as f:
        return json.load(f)


def _save_sync_config(cfg: dict) -> None:
    BOB_DIR.mkdir(parents=True, exist_ok=True)
    with SYNC_CONFIG_PATH.open("w") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")


def _resolve_shared_dir(create: bool = False) -> Path:
    """Return the configured shared-folder Path, or die with a setup hint."""
    raw = _load_sync_config().get("shared_dir", "")
    if not raw:
        die("sync not set up — run: ./bob sync --set-dir PATH   (PATH = your shared folder, e.g. a Dropbox folder)")
    shared = Path(raw).expanduser()
    if not shared.exists():
        if create and shared.parent.exists():
            shared.mkdir(parents=True, exist_ok=True)
        else:
            die(f"shared folder not found: {shared} — is it available / your cloud drive mounted?")
    return shared


def _read_jsonl_lines(path: Path) -> list[str]:
    """Return non-blank, valid-JSON lines of a JSONL file (tolerant), preserving raw text."""
    if not path.exists():
        return []
    out: list[str] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            json.loads(line)
        except json.JSONDecodeError:
            continue
        out.append(line)
    return out


def _jsonl_ts(line: str) -> str:
    try:
        return json.loads(line).get("timestamp", "")
    except Exception:
        return ""


def _union_jsonl(local_path: Path, shared_path: Path, to_local: bool, to_shared: bool,
                 dry_run: bool) -> dict:
    """Union an append-only JSONL across local + shared (+ any cloud 'conflicted copy' siblings).

    Exact-line dedup, sorted by timestamp. Append-only ⇒ no conflicts, no event ever lost.
    """
    local = _read_jsonl_lines(local_path)
    shared = _read_jsonl_lines(shared_path)
    local_set, shared_set = set(local), set(shared)
    conflicted: list[str] = []
    conflict_files: list[Path] = []
    if shared_path.parent.exists():
        for p in shared_path.parent.glob("*conflicted copy*.jsonl"):
            conflict_files.append(p)
            conflicted.extend(_read_jsonl_lines(p))

    seen: set[str] = set()
    merged: list[str] = []
    for line in [*local, *shared, *conflicted]:
        if line not in seen:
            seen.add(line)
            merged.append(line)
    merged.sort(key=_jsonl_ts)

    stats = {
        "total": len(merged),
        "added_local": sum(1 for l in merged if l not in local_set),
        "added_shared": sum(1 for l in merged if l not in shared_set),
        "conflicted_folded": len(conflict_files),
    }
    if not dry_run:
        text = "".join(l + "\n" for l in merged)
        # Write only when content actually changes — re-running with nothing new rewrites nothing.
        if to_local and (not local_path.exists() or local_path.read_text() != text):
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_text(text)
        if to_shared:
            if not shared_path.exists() or shared_path.read_text() != text:
                shared_path.parent.mkdir(parents=True, exist_ok=True)
                shared_path.write_text(text)
            for p in conflict_files:
                try:
                    p.unlink()
                except OSError:
                    pass
    return stats


_INDEX_TITLE_DEFAULT = "# Bob — Wiki Index"


def _parse_index_sections(text: str) -> tuple[str, dict[str, list[str]], list[str]]:
    """Split Index.md into (title_block, {'## Header': [lines]}, header_order). Unknown sections kept."""
    title: list[str] = []
    sections: dict[str, list[str]] = {}
    order: list[str] = []
    current: str | None = None
    for line in text.splitlines():
        if line.startswith("## "):
            current = line.strip()
            if current not in sections:
                sections[current] = []
                order.append(current)
        elif current is None:
            title.append(line)
        else:
            sections[current].append(line)
    return "\n".join(title).strip(), sections, order


def _union_index(local_text: str, shared_text: str) -> str:
    """Union two Index.md files per section: bullet/content lines deduped, order preserved."""
    l_title, l_sec, l_order = _parse_index_sections(local_text)
    s_title, s_sec, s_order = _parse_index_sections(shared_text)
    order: list[str] = []
    for h in [*l_order, *s_order]:
        if h not in order:
            order.append(h)
    parts: list[str] = [l_title or s_title or _INDEX_TITLE_DEFAULT]
    for h in order:
        seen: set[str] = set()
        bullets: list[str] = []
        for x in [*l_sec.get(h, []), *s_sec.get(h, [])]:
            key = x.strip()
            if not key or key in seen:
                continue
            seen.add(key)
            bullets.append(x.rstrip())
        parts.append((h + "\n\n" + "\n".join(bullets)).rstrip())
    return "\n\n".join(parts).rstrip() + "\n"


def _split_entry_blocks(lines: list[str]) -> list[str]:
    """Split a section's lines into '### ' entry blocks (text before the first '### ' is dropped)."""
    blocks: list[str] = []
    cur: list[str] = []
    for line in lines:
        if line.startswith("### "):
            if cur:
                blocks.append("\n".join(cur).strip())
            cur = [line]
        elif cur:
            cur.append(line)
    if cur:
        blocks.append("\n".join(cur).strip())
    return [b for b in blocks if b]


def _union_backlog(local_text: str, shared_text: str) -> str:
    """Union backlog.md per section by '### ' entry block (dedup exact blocks, order preserved).

    Like the Index union but entries are multi-line blocks rather than single bullets — so two
    people adding bug/feature entries both accumulate, nothing is lost, nothing conflicts.
    """
    l_title, l_sec, l_order = _parse_index_sections(local_text)
    s_title, s_sec, s_order = _parse_index_sections(shared_text)
    order: list[str] = []
    for h in [*l_order, *s_order]:
        if h not in order:
            order.append(h)
    parts: list[str] = [l_title or s_title]
    for h in order:
        seen: set[str] = set()
        blocks: list[str] = []
        for b in [*_split_entry_blocks(l_sec.get(h, [])), *_split_entry_blocks(s_sec.get(h, []))]:
            key = b.strip()
            if key and key not in seen:
                seen.add(key)
                blocks.append(b)
        parts.append((h + "\n\n" + "\n\n".join(blocks)).rstrip())
    return "\n\n".join(p for p in parts if p).rstrip() + "\n"


def _union_md_file(local_path: Path, shared_path: Path, union_fn, to_local: bool,
                   to_shared: bool, dry_run: bool) -> dict:
    """Reconcile a single markdown file via union_fn; write only the sides whose content changes."""
    l_text = local_path.read_text(errors="replace") if local_path.exists() else ""
    s_text = shared_path.read_text(errors="replace") if shared_path.exists() else ""
    if not l_text and not s_text:
        return {"present": False, "to_local": False, "to_shared": False}
    merged = union_fn(l_text, s_text)
    stats = {"present": True, "to_local": merged != l_text, "to_shared": merged != s_text}
    if not dry_run:
        if to_local and stats["to_local"]:
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_text(merged)
        if to_shared and stats["to_shared"]:
            shared_path.parent.mkdir(parents=True, exist_ok=True)
            shared_path.write_text(merged)
    return stats


def _iter_wiki_files(base: Path) -> dict[str, Path]:
    """Map relative-path → absolute Path under base (skips junk + local .bak safety copies)."""
    out: dict[str, Path] = {}
    if not base.exists():
        return out
    for p in base.rglob("*"):
        if p.is_dir() or p.name == ".DS_Store" or ".bak-" in p.name:
            continue
        out[str(p.relative_to(base))] = p
    return out


def _files_equal(a: Path, b: Path) -> bool:
    try:
        return a.read_bytes() == b.read_bytes()
    except OSError:
        return False


def _backup(path: Path) -> None:
    """Save a sibling .bak copy so a newer-wins overwrite never loses content."""
    if path.exists():
        bak = path.with_name(path.name + f".bak-{dt.datetime.now().strftime('%Y%m%d%H%M%S')}")
        try:
            shutil.copy2(path, bak)
        except OSError:
            pass


def _sync_wiki(local_base: Path, shared_base: Path, to_local: bool, to_shared: bool,
               dry_run: bool) -> dict:
    """Reconcile wiki files: copy where missing, union Index.md, newer-wins (with .bak) elsewhere."""
    local_files = _iter_wiki_files(local_base)
    shared_files = _iter_wiki_files(shared_base)
    stats = {"to_shared": 0, "to_local": 0, "index_unioned": 0, "baks": 0}
    for rel in sorted(set(local_files) | set(shared_files)):
        lp, sp = local_files.get(rel), shared_files.get(rel)
        ltarget, starget = local_base / rel, shared_base / rel
        if lp and not sp:
            if to_shared:
                if not dry_run:
                    starget.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(lp, starget)
                stats["to_shared"] += 1
        elif sp and not lp:
            if to_local:
                if not dry_run:
                    ltarget.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(sp, ltarget)
                stats["to_local"] += 1
        elif lp and sp and not _files_equal(lp, sp):
            if Path(rel).name == "Index.md":
                merged = _union_index(lp.read_text(errors="replace"), sp.read_text(errors="replace"))
                if not dry_run:
                    if to_local:
                        ltarget.write_text(merged)
                    if to_shared:
                        starget.write_text(merged)
                stats["index_unioned"] += 1
            elif sp.stat().st_mtime >= lp.stat().st_mtime:
                if to_local:
                    if not dry_run:
                        _backup(ltarget)
                        shutil.copy2(sp, ltarget)
                    stats["to_local"] += 1
                    stats["baks"] += 1
            else:
                if to_shared:
                    if not dry_run:
                        _backup(starget)
                        shutil.copy2(lp, starget)
                    stats["to_shared"] += 1
                    stats["baks"] += 1
    return stats


def sync(args: argparse.Namespace) -> None:
    """Share wiki/ + logs/session-signals.jsonl with teammates via a plain shared folder.

    No git: the append-only signal log and Index.md bullet lists are unioned, other wiki files are
    copied newer-wins (older kept as .bak). Both paths stay gitignored, so the public repo is never
    touched. Default reconciles both ways; --pull / --push limit the direction.
    """
    if args.set_dir:
        shared_set = Path(args.set_dir).expanduser()
        _save_sync_config({"shared_dir": str(shared_set)})
        print(f"shared folder set: {shared_set}")
        if not shared_set.exists() and not shared_set.parent.exists():
            print(f"warning: {shared_set.parent} not found — is your cloud drive mounted?")

    if args.pull and args.push:
        die("use at most one of --pull / --push")
    shared = _resolve_shared_dir(create=not args.dry_run)
    to_local = not args.push
    to_shared = not args.pull

    direction = "both ways" if (to_local and to_shared) else ("pull only" if to_local else "push only")
    print(f"{'DRY RUN — ' if args.dry_run else ''}sync ({direction}) with {shared}\n")

    sig = _union_jsonl(SIGNAL_LOG_PATH, shared / "session-signals.jsonl", to_local, to_shared, args.dry_run)
    wiki = _sync_wiki(ROOT / "wiki", shared / "wiki", to_local, to_shared, args.dry_run)
    bk = _union_md_file(ROOT / "logs" / "backlog.md", shared / "backlog.md",
                        _union_backlog, to_local, to_shared, args.dry_run)

    print(f"signals : {sig['total']} total  (+{sig['added_local']} local, +{sig['added_shared']} shared"
          + (f", {sig['conflicted_folded']} conflicted-copy folded in" if sig["conflicted_folded"] else "") + ")")
    print(f"wiki    : {wiki['to_local']} → local, {wiki['to_shared']} → shared, "
          f"{wiki['index_unioned']} Index.md unioned, {wiki['baks']} .bak saved")
    bk_state = ("not present yet" if not bk["present"]
                else "unioned " + ("→ local & shared" if bk["to_local"] and bk["to_shared"]
                                   else "→ local" if bk["to_local"]
                                   else "→ shared" if bk["to_shared"] else "(already in sync)"))
    print(f"backlog : {bk_state}")
    print("\nNothing written (dry run)." if args.dry_run else "\nsync complete.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bob-data", description="Bob Frm Mktg data pull tools")
    sub = parser.add_subparsers(dest="command", required=True)

    fetch_parser = sub.add_parser("fetch", help="run one GARF query")
    fetch_parser.add_argument("--query", required=True)
    fetch_parser.add_argument("--days", type=int)
    fetch_parser.add_argument("--from", dest="from_date")
    fetch_parser.add_argument("--to")
    fetch_parser.add_argument("--account")
    fetch_parser.add_argument("--config")
    fetch_parser.add_argument("--run-id")
    fetch_parser.add_argument("--dry-run", action="store_true")
    fetch_parser.add_argument("--reason", default="", help="why this data is being fetched — logged to logs/pull-log.jsonl")
    fetch_parser.add_argument("--question", default="", help="user's exact question — logged for audit trail")
    fetch_parser.add_argument("--force", action="store_true", help="re-fetch even if file already exists")
    fetch_parser.set_defaults(func=fetch)

    boot_parser = sub.add_parser("bootstrap", help="run first-pull query set")
    boot_parser.add_argument("--from", dest="from_date")
    boot_parser.add_argument("--to")
    boot_parser.add_argument("--account")
    boot_parser.add_argument("--config")
    boot_parser.add_argument("--run-id")
    boot_parser.add_argument("--dry-run", action="store_true")
    boot_parser.add_argument("--keep-going", action="store_true")
    boot_parser.add_argument("--reason", default="", help="why bootstrap is running — logged to logs/pull-log.jsonl")
    boot_parser.add_argument("--question", default="", help="user's exact question — logged for audit trail")
    boot_parser.add_argument("--force", action="store_true", help="re-fetch all windows even if files exist")
    boot_parser.set_defaults(func=bootstrap)

    lp_parser = sub.add_parser("log-pull", help="write a log entry without fetching (for cache hits)")
    lp_parser.add_argument("--query", required=True)
    lp_parser.add_argument("--from", dest="from_date", default="")
    lp_parser.add_argument("--to", default="")
    lp_parser.add_argument("--account", default="")
    lp_parser.add_argument("--reason", default="")
    lp_parser.add_argument("--question", default="")
    lp_parser.add_argument("--outcome", default="skipped_wiki", choices=["skipped_wiki", "skipped_raw", "fetched"])
    lp_parser.set_defaults(func=log_pull_cmd)

    sig_parser = sub.add_parser("log-signal", help="record a self-improvement signal (a friction moment) — agent-agnostic")
    sig_parser.add_argument("--type", required=True, help="event type: failsafe|tool_error|retry|user_correction|plan_rejection|redundant_fetch|friction (free-form allowed)")
    sig_parser.add_argument("--note", required=True, help="one-line description of the stumble")
    sig_parser.add_argument("--user-text", dest="user_text", default="", help="the triggering user input (truncated to 280)")
    sig_parser.add_argument("--intent", default="", help="intent/route involved, e.g. compare-weeks")
    sig_parser.add_argument("--artifact", default="", help="best guess at the responsible file/rule")
    sig_parser.add_argument("--severity", default="", help="blocked|wrong|friction|cosmetic — feeds ranking")
    sig_parser.add_argument("--account", default="", help="override active account (defaults to active profile)")
    sig_parser.set_defaults(func=log_signal_cmd)

    sd_parser = sub.add_parser("session-debrief", help="record a batch of friction signals captured at a session success beat (consent-based)")
    sd_parser.add_argument("--signals", required=True, help="JSON array of signal objects; each needs event_type + note, plus optional user_text/intent/artifact/severity")
    sd_parser.add_argument("--account", default="", help="override active account (defaults to active profile)")
    sd_parser.set_defaults(func=session_debrief)

    si_parser = sub.add_parser("self-improve", help="summarise logged signals + point to files for a self-improvement pass")
    si_parser.set_defaults(func=self_improve)

    agg_parser = sub.add_parser("aggregate", help="create processed aggregates")
    agg_parser.add_argument("--source")
    agg_parser.add_argument(
        "--grain",
        default="account_daily",
        choices=[
            "account_daily",
            "account_network_period",
            "campaign_network_period",
            "campaign_reach_period",
            "adgroup_network_period",
            "creative_period",
            "campaign_weekly_trend",
        ],
    )
    agg_parser.add_argument("--input")
    agg_parser.add_argument("--from", dest="from_date", help="select raw period start date (YYYY-MM-DD)")
    agg_parser.add_argument("--to", help="select raw period end date (YYYY-MM-DD)")
    agg_parser.add_argument("--output")
    agg_parser.add_argument("--customer")
    agg_parser.add_argument("--goal", choices=["installs", "in_app_conversions"])
    agg_parser.set_defaults(func=aggregate)

    val_parser = sub.add_parser("validate-manual", help="validate Bob aggregate against manual aggregate")
    val_parser.add_argument("--bob", required=True)
    val_parser.add_argument("--manual", required=True)
    val_parser.add_argument("--mapping")
    val_parser.add_argument("--grain", default="date")
    val_parser.add_argument("--output-prefix")
    val_parser.set_defaults(func=validate_manual)

    cfg_parser = sub.add_parser("check-config", help="check Google Ads config shape without printing secrets")
    cfg_parser.add_argument("--config")
    cfg_parser.add_argument("--account")
    cfg_parser.set_defaults(func=check_config)

    wk_parser = sub.add_parser("compare-weeks", help="compare performance across two ISO calendar weeks")
    wk_parser.add_argument("--week", type=int, help="current ISO week number (default: last complete week)")
    wk_parser.add_argument("--vs", type=int, help="baseline ISO week number (default: current - 1)")
    wk_parser.add_argument("--year", type=int, help="ISO year for current week (default: current year)")
    wk_parser.add_argument("--grain", default="both", choices=["account", "campaign", "both"])
    wk_parser.add_argument("--name-contains", help="filter campaigns by name substring")
    wk_parser.add_argument("--output", help="write campaign comparison CSV to this path")
    wk_parser.add_argument("--output-account", help="write account comparison CSV to this path")
    wk_parser.add_argument("--goal", choices=["installs", "in_app_conversions"])
    wk_parser.add_argument("--all-metrics", action="store_true", help="show full metric table (users, CPM, freq, CTR, CPC, CTI, conv%%, CPA)")
    wk_parser.set_defaults(func=compare_weeks)

    mo_parser = sub.add_parser("compare-months", help="compare MTD or full-month performance across two calendar months")
    mo_parser.add_argument("--month", type=int, help="current month 1–12 (default: current month)")
    mo_parser.add_argument("--vs", type=int, help="baseline month 1–12 (default: current - 1)")
    mo_parser.add_argument("--year", type=int, help="year for the current month (default: current year)")
    mo_parser.add_argument("--full", action="store_true", help="compare full calendar months instead of MTD")
    mo_parser.add_argument("--grain", default="both", choices=["account", "campaign", "both"])
    mo_parser.add_argument("--name-contains", help="filter campaigns by name substring")
    mo_parser.add_argument("--output", help="write campaign comparison CSV to this path")
    mo_parser.add_argument("--output-account", help="write account comparison CSV to this path")
    mo_parser.add_argument("--goal", choices=["installs", "in_app_conversions"])
    mo_parser.add_argument("--all-metrics", action="store_true", help="show full metric table (users, CPM, freq, CTR, CPC, CTI, conv%%, CPA)")
    mo_parser.set_defaults(func=compare_months)

    slice_parser = sub.add_parser("slice-campaigns", help="compare a name-filtered campaign segment across two periods")
    slice_parser.add_argument("--name-contains", required=True, help="case-insensitive substring filter on campaign_name")
    slice_parser.add_argument(
        "--period",
        default="yesterday_vs_sdlw",
        choices=["yesterday_vs_sdlw", "wow", "mom", "mtd"],
        help="period pair for auto-detecting processed campaign-network files",
    )
    slice_parser.add_argument("--current", help="explicit current-period processed campaign-network CSV")
    slice_parser.add_argument("--baseline", help="explicit baseline processed campaign-network CSV")
    slice_parser.add_argument("--output", help="write full comparison CSV to this path")
    slice_parser.add_argument("--goal", choices=["installs", "in_app_conversions"])
    slice_parser.add_argument("--all-metrics", action="store_true", help="show full metric table (users, CPM, freq, CTR, CPC, CTI, conv%%, CPA)")
    slice_parser.set_defaults(func=slice_campaigns)

    sc_parser = sub.add_parser("slice-creatives", help="flag LOW-label creatives vs campaign averages")
    sc_parser.add_argument("--min-impressions", type=float, help="minimum impressions threshold (default: profile.creative_min_impressions or 50000)")
    sc_parser.add_argument("--output", help="write full flagged CSV to this path")
    sc_parser.set_defaults(func=slice_creatives)

    scc_parser = sub.add_parser("suggest-creative-copy",
        help="generate copy plan + compact agent prompt for LOW-action vs BEST text assets")
    scc_parser.add_argument("--min-impressions", type=float, help="minimum impressions (default: profile or 50000)")
    scc_parser.add_argument("--output-dir", help="directory for plan + prompt files (default: wiki/action-items/)")
    scc_parser.add_argument("--batch-size", type=int, default=25,
        help="max assets per batch prompt file (default: 25)")
    scc_parser.set_defaults(func=suggest_creative_copy)

    ssb_parser = sub.add_parser("suggest-static-banners",
        help="create the quarterly static banner design guide from BEST image assets")
    ssb_parser.add_argument("--input", help="explicit processed creative CSV (default: newest account creative slice)")
    ssb_parser.add_argument("--customer", help="customer ID for selecting account-scoped wiki/data paths")
    ssb_parser.add_argument("--min-impressions", type=float, help="minimum impressions (default: profile or 50000)")
    ssb_parser.add_argument("--strategy-json", help="structured JSON returned by the static-banner-strategist subagent")
    ssb_parser.add_argument("--force", action="store_true", help="regenerate even if the static-banner strategy guide is younger than 90 days")
    ssb_parser.add_argument("--data-only-diagnostic", action="store_true",
        help="write a diagnostic markdown without strategist visual analysis")
    ssb_parser.set_defaults(func=suggest_static_banners)

    ssv_parser = sub.add_parser("suggest-static-variants",
        help="prepare LOW static image candidates for source-guided same-size variants")
    ssv_parser.add_argument("--input", help="explicit processed creative CSV (default: newest account creative slice)")
    ssv_parser.add_argument("--customer", help="customer ID for selecting account-scoped wiki/data paths")
    ssv_parser.add_argument("--min-impressions", type=float, help="minimum impressions (default: profile or 50000)")
    ssv_parser.set_defaults(func=suggest_static_variants)

    sva_parser = sub.add_parser("static-variants-apply",
        help="upload approved static image variants and replace matching app-ad image assets")
    sva_parser.add_argument("--plan", help="YAML plan with manifest and changes/replacements")
    sva_parser.add_argument("--manifest", help="LOW static variants manifest for direct single replacement")
    sva_parser.add_argument("--asset-id", help="source LOW image asset ID for direct single replacement")
    sva_parser.add_argument("--replacement", help="generated PNG/JPEG replacement path for direct single replacement")
    sva_parser.add_argument("--dry-run", action="store_true", help="validate and show approval table without mutating Google Ads")
    sva_parser.set_defaults(func=static_variants_apply)

    cca_parser = sub.add_parser("creative-copy-apply",
        help="review and apply an approved copy plan: creates new text assets, pauses old ones")
    cca_parser.add_argument("--plan", required=True, help="path to creative-copy YAML plan")
    cca_parser.add_argument("--suggestions", help='JSON from agent: [{"id":1,"text":"..."},...]')
    cca_parser.set_defaults(func=creative_copy_apply)

    bb_rec_parser = sub.add_parser("bid-budget-recommend", help="generate bid/budget recommendations from weekly trend")
    bb_rec_parser.add_argument("--trend", help="explicit campaign-trend processed CSV (default: newest in data/processed/campaign-trend/)")
    bb_rec_parser.add_argument("--bid-budget", help="explicit bid_budget_inputs raw CSV (default: newest in garf/outputs/raw/bid_budget_inputs/)")
    bb_rec_parser.add_argument("--output", help="write recommendation CSV to this path")
    bb_rec_parser.add_argument("--yaml-output", help="write mutation plan YAML to this path")
    bb_rec_parser.add_argument("--goal", choices=["installs", "in_app_conversions"], help="override primary goal from profile")
    bb_rec_parser.add_argument("--cac-ceiling", help="skip campaigns with CPA above this value (default: profile.cac_ceiling or 200)")
    bb_rec_parser.add_argument("--change-pct", help="bid/budget change magnitude in %% (default: profile.bid_budget_change_pct or 10, capped at 20)")
    bb_rec_parser.add_argument("--dry-run", action="store_true", help="print recommendation table without writing files")
    bb_rec_parser.set_defaults(func=bid_budget_recommend)

    bb_apply_parser = sub.add_parser("bid-budget-apply", help="apply a mutation plan YAML to Google Ads")
    bb_apply_parser.add_argument("--plan", required=True, help="path to bid-budget YAML plan generated by bid-budget-recommend")
    bb_apply_parser.set_defaults(func=bid_budget_apply)

    bb_retro_parser = sub.add_parser("bid-budget-retrospective", help="evaluate whether applied bid/budget changes are working")
    bb_retro_parser.add_argument("--plan", required=True, help="path to applied bid-budget YAML plan")
    bb_retro_parser.set_defaults(func=bid_budget_retrospective)

    rd_parser = sub.add_parser("resolve-dates", help="resolve a period expression to concrete date ranges")
    rd_parser.add_argument(
        "--period", required=True,
        help="period name: yesterday-vs-sdlw, wow, mom, mtd, 3week-rolling, partial-wow",
    )
    rd_parser.add_argument(
        "--n", type=int, default=3,
        help="number of days for partial-wow (default: 3)",
    )
    rd_parser.set_defaults(func=cmd_resolve_dates)

    sw_parser = sub.add_parser("setup-write-credentials",
        help="one-time OAuth2 flow to generate write credentials for bid-budget-apply")
    sw_parser.add_argument("--creds", help="path to google-ads-creds.json (default: ~/google-ads-creds.json)")
    sw_parser.add_argument("--output", help="where to save the write config yaml (default: from profile)")
    sw_parser.set_defaults(func=setup_write_credentials)

    ob_parser = sub.add_parser("onboard", help="interactive onboarding — set up a new account")
    ob_parser.add_argument("--account-id", help="pre-fill customer ID (skip prompt)")
    ob_parser.set_defaults(func=onboard)

    sa_parser = sub.add_parser("switch-account", help="switch the active Google Ads account")
    sa_parser.add_argument("target", nargs="?", help="customer ID (with or without hyphens) or unique account-name substring")
    sa_parser.add_argument("--account-id", help="customer ID to switch to (legacy flag; positional 'target' is preferred)")
    sa_parser.set_defaults(func=switch_account)

    la_parser = sub.add_parser("list-accounts", help="list all registered Google Ads accounts")
    la_parser.set_defaults(func=list_accounts)

    rs_parser = sub.add_parser("repair-setup", help="reinstall project dependencies and recheck readiness")
    rs_parser.set_defaults(func=repair_setup)

    sync_parser = sub.add_parser("sync",
        help="share wiki + self-improve signals with the team via a shared folder (no git needed)")
    sync_parser.add_argument("--set-dir", metavar="PATH",
        help="one-time: record the shared folder (e.g. a synced Dropbox folder) in .bob/sync.json")
    sync_parser.add_argument("--pull", action="store_true", help="pull teammates' changes only (no push)")
    sync_parser.add_argument("--push", action="store_true", help="push your changes only (no pull)")
    sync_parser.add_argument("--dry-run", action="store_true", help="show what would sync; change nothing")
    sync_parser.set_defaults(func=sync)

    return parser


_COMMAND_MAP = """Bob — Performance Marketing Analyst CLI

SETUP
  onboard                       First-run setup for a new Google Ads account
  switch-account                Change active account (positional ID or name supported)
  list-accounts                 Show registered accounts
  check-config                  Verify Google Ads credentials
  repair-setup                  Reinstall local dependencies if setup didn't take
  setup-write-credentials       One-time OAuth for bid/budget mutation credentials

DATA
  fetch                         Pull one GARF query from Google Ads
  bootstrap                     Pull the default set of period windows
  aggregate                     Build a processed grain from raw outputs

ANALYSIS
  compare-weeks                 Two ISO weeks (default: last complete vs prior)
  compare-months                Two calendar months (MTD or full)
  slice-campaigns               Compare a name-filtered campaign segment
  slice-creatives               Flag underperforming creative assets

ACTIONS
  bid-budget-recommend          Generate a bid/budget plan from weekly trend
  bid-budget-apply              Apply an approved plan to Google Ads
  bid-budget-retrospective      Evaluate W+1/W+2 outcomes of an applied plan
  suggest-creative-copy         Build copy plan + prompt for LOW text assets
  suggest-static-banners        Build the quarterly static-banner design guide
  suggest-static-variants       Prepare LOW static image variant candidates
  static-variants-apply         Upload approved static variants to Google Ads
  creative-copy-apply           Push approved copy changes to Google Ads

UTILITIES
  resolve-dates                 Resolve a period name to concrete date ranges
  validate-manual               Compare a Bob aggregate against a manual export
  log-pull                      Write a pull-log entry without fetching
  log-signal                    Record a self-improvement signal (a friction moment)
  session-debrief               Record a batch of friction signals at a session success beat
  self-improve                  Summarise signals for a self-improvement pass
  sync                          Share wiki + signals with the team (via a shared folder, no git)

For any subcommand: ./bob <name> --help
"""


def _auto_log_cli_failure(command: str, argv: list[str], detail: str) -> None:
    """Self-instrumentation: record a tool_error signal when a CLI command fails.

    Agent-agnostic — fires regardless of who invoked ./bob, with no agent cooperation,
    so the hard signals land even when an agent stays quiet. Best-effort: signal logging
    must never mask or replace the original error. Skips the self-improvement commands
    themselves to avoid noise/recursion.
    """
    if command in ("log-signal", "session-debrief", "self-improve"):
        return
    try:
        profile = load_profile(required=False)
        account = str(profile.get("google_ads_customer_id", "")).replace("-", "")
        log_signal(
            event_type="tool_error",
            note=f"bob {' '.join(argv)} failed: {detail}"[:280],
            account=account,
            intent=command,
            severity="friction",
            source="cli",
        )
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        sys.stdout.write(_COMMAND_MAP)
        return 0
    parser = build_parser()
    args = parser.parse_args(argv)
    command = getattr(args, "command", argv[0])
    try:
        args.func(args)
    except KeyboardInterrupt:
        raise
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
        if code != 0:
            _auto_log_cli_failure(command, argv, f"exited with code {code}")
        raise
    except Exception as e:
        _auto_log_cli_failure(command, argv, f"{type(e).__name__}: {e}")
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
