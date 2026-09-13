"""Shared runtime, configuration, data discovery, and logging infrastructure."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import importlib.metadata as importlib_metadata
import json
import math
import os
import re
import shutil
import shlex
import subprocess
import sys
import tempfile
import tarfile
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .dates import (
    bid_budget_week_windows,
    iso_week_to_dates,
    last_complete_iso_week,
    normalize_period_name,
    parse_date,
    resolve_period_dates,
    split_date_range,
    today,
)
from .errors import die
from .metrics import derive_metrics as _derive_metrics, format_float, number, ratio

_REPO_ROOT = Path(__file__).resolve().parents[3]

# `ROOT` is the immutable code/instructions root. Hosted deployments set
# `BOB_STATE_ROOT` to the persistent client volume so Bob's existing commands
# keep their layout while accounts, data, Wiki, and logs survive image updates.
ROOT = _REPO_ROOT
STATE_ROOT = Path(os.getenv("BOB_STATE_ROOT", str(ROOT))).expanduser().resolve()
BOB_DIR = STATE_ROOT / ".bob"
PROFILE_PATH = BOB_DIR / "profile.json"
ACCOUNTS_DIR = BOB_DIR / "accounts"
ACCOUNTS_REGISTRY = BOB_DIR / "accounts.json"
VENV_DIR = ROOT / ".venv"
UV_RUNTIME_DIR = ROOT / "runtime" / "uv"
UV_BINARY = UV_RUNTIME_DIR / ("uv.exe" if os.name == "nt" else "uv")
QUERIES_DIR = ROOT / "garf" / "queries"
RAW_DIR = STATE_ROOT / "garf" / "outputs" / "raw"
PROCESSED_DIR = STATE_ROOT / "data" / "processed"
REPORTS_DIR = STATE_ROOT / "validation" / "reports"
PULL_LOG_PATH = STATE_ROOT / "logs" / "pull-log.jsonl"
PULL_LOCKS_DIR = STATE_ROOT / "logs" / "pull-locks"
SIGNAL_LOG_PATH = STATE_ROOT / "logs" / "session-signals.jsonl"
SELF_IMPROVE_DIR = STATE_ROOT / "wiki" / "_self-improve"
SNAPSHOT_DEFAULT_DIR = ROOT / ".local" / "vm-snapshot"

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
    {"query": "campaign_network_period", "period": "bid_budget_weeks"},
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
    "creative_headline_period", "creative_description_period",
    "creative_image_period", "creative_video_period",
}

# Granular entity-level queries are intentionally capped so a single Codex job
# cannot create a large burst of rows/CPU on the hosted VM. Account-level period
# queries remain whole-period pulls because their result is already rolled up.
GRANULAR_QUERY_MAX_DAYS = 7
GRANULAR_DATE_QUERIES = {
    "campaign_daily",
    "campaign_reach_daily",
    "network_daily",
    "creative_asset_daily",
    "conversion_action_daily",
    "creative_conversion_action_daily",
    "campaign_network_period",
    "campaign_reach_period",
    "adgroup_network_period",
    "creative_period",
}

DEFAULT_CREATIVE_MIN_IMPRESSIONS = 50000
CREATIVE_ASSET_QUERIES = {
    "headline": "creative_headline_period",
    "description": "creative_description_period",
    "image": "creative_image_period",
    "video": "creative_video_period",
}
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
    "asset_id", "asset_name", "asset_type", "asset_text", "video_id", "field_type", "performance_label",
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

CAMPAIGN_SLICE_COMPARISON_COLUMNS = _comparison_cols(["customer_id", "campaign_id", "campaign_name", "campaign_status"])
CAMPAIGN_NETWORK_COMPARISON_COLUMNS = _comparison_cols(["customer_id", "campaign_id", "campaign_name", "campaign_status", "network"])
ACCOUNT_WEEK_COMPARISON_COLUMNS   = _comparison_cols(["customer_id", "customer_name", "network"])
CAMPAIGN_WEEK_COMPARISON_COLUMNS  = _comparison_cols(["customer_id", "campaign_id", "campaign_name", "campaign_status"])
ADGROUP_NETWORK_COMPARISON_COLUMNS = _comparison_cols([
    "customer_id", "campaign_id", "campaign_name",
    "ad_group_id", "ad_group_name", "ad_group_status", "network",
])

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
    return STATE_ROOT / "wiki" / customer_id.replace("-", "")


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
    runtime_config = os.getenv("BOB_GOOGLE_ADS_RUNTIME_CONFIG", "").strip()
    if runtime_config:
        return runtime_config
    return str(profile.get("google_ads_read_config_path", "") or "").strip()


def _resolve_state_path(value: str | Path) -> Path:
    """Resolve legacy relative account paths against the persistent state root."""
    path = Path(value).expanduser()
    return path if path.is_absolute() else STATE_ROOT / path


def _set_profile_read_config_value(profile: dict[str, Any], value: str) -> None:
    profile["google_ads_read_config_path"] = value


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


def cmd_resolve_dates(args: argparse.Namespace) -> None:
    """Print concrete date ranges for a named period so the agent can construct fetch commands."""
    import calendar as _cal
    period = normalize_period_name(args.period)
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


def render_query(query_name: str, start: dt.date, end: dt.date, substitutions: dict[str, Any] | None = None) -> str:
    query_file = QUERIES_DIR / f"{query_name}.sql"
    if not query_file.exists():
        die(f"query file not found: {query_file}")
    text = query_file.read_text()
    yesterday = today() - dt.timedelta(days=1)
    sdlw = yesterday - dt.timedelta(days=7)
    values = dict(
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        period_start=start.isoformat(),
        period_end=end.isoformat(),
        yesterday=yesterday.isoformat(),
        sdlw=sdlw.isoformat(),
    )
    values.update(substitutions or {})
    return text.format(**values)


def ensure_dirs() -> None:
    for path in [RAW_DIR, PROCESSED_DIR, REPORTS_DIR, ACCOUNTS_DIR]:
        path.mkdir(parents=True, exist_ok=True)


def _venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python3"


def _uv_executable() -> str | None:
    """Return uv from PATH or Bob's private runtime location."""
    found = shutil.which("uv")
    if found:
        return found
    if UV_BINARY.exists() and os.access(UV_BINARY, os.X_OK):
        return str(UV_BINARY)
    return None


def _uv_sync_command(extra: str | None = None) -> list[str]:
    uv = _uv_executable()
    if not uv:
        die(
            "Bob needs its local runtime manager (uv), but it is not available. "
            "Run ./bob again with network access enabled so Bob can install it."
        )
    command = [uv, "sync", "--project", str(ROOT), "--python", "3.12"]
    if extra:
        command.extend(["--extra", extra])
    return command


def _uv_run_command(*command: str, sync: bool = False) -> list[str]:
    uv = _uv_executable()
    if not uv:
        die(
            "Bob needs its local runtime manager (uv), but it is not available. "
            "Run ./bob again with network access enabled so Bob can install it."
        )
    args = [uv, "run", "--project", str(ROOT), "--python", "3.12"]
    if not sync:
        args.append("--no-sync")
    return args + list(command)


def _write_bob_launcher() -> None:
    launcher = ROOT / "bob"
    launcher.write_text(
        "#!/bin/bash\n"
        "# bob - launcher backed by uv-managed, self-healing Python dependencies.\n"
        "set -e\n"
        "\n"
        'SOURCE="${BASH_SOURCE[0]}"\n'
        'while [ -h "$SOURCE" ]; do\n'
        '    SOURCE_DIR="$(cd "$(dirname "$SOURCE")" && pwd)"\n'
        '    SOURCE_TARGET="$(readlink "$SOURCE")"\n'
        '    if [[ "$SOURCE_TARGET" = /* ]]; then SOURCE="$SOURCE_TARGET"; else SOURCE="$SOURCE_DIR/$SOURCE_TARGET"; fi\n'
        'done\n'
        'DIR="$(cd "$(dirname "$SOURCE")" && pwd)"\n'
        "\n"
        'UV_DIR="$DIR/runtime/uv"\n'
        'UV_BIN="$UV_DIR/uv"\n'
        "\n"
        'if command -v uv >/dev/null 2>&1; then\n'
        '    UV_BIN="$(command -v uv)"\n'
        'elif [ ! -x "$UV_BIN" ]; then\n'
        '    if ! command -v curl >/dev/null 2>&1; then\n'
        '        echo "Bob needs uv to manage its local runtime, and curl to install uv automatically." >&2\n'
        '        exit 1\n'
        '    fi\n'
        '    mkdir -p "$UV_DIR"\n'
        '    UV_INSTALLER="$(mktemp "${TMPDIR:-/tmp}/bob-uv.XXXXXX.sh")"\n'
        '    trap "rm -f \\\"$UV_INSTALLER\\\"" EXIT\n'
        '    echo "Bob is installing its local runtime manager..."\n'
        '    if ! curl --fail --location --silent --show-error https://astral.sh/uv/install.sh --output "$UV_INSTALLER"; then\n'
        '        echo "Bob could not download its runtime manager. Check network access and try again." >&2\n'
        '        exit 1\n'
        '    fi\n'
        '    UV_INSTALL_DIR="$UV_DIR" UV_NO_MODIFY_PATH=1 sh "$UV_INSTALLER" >/dev/null\n'
        'fi\n'
        '\n'
        'if [ ! -x "$UV_BIN" ] && ! command -v uv >/dev/null 2>&1; then\n'
        '    echo "Bob could not find a usable uv runtime manager." >&2\n'
        '    exit 1\n'
        'fi\n'
        'if [ ! -x "$UV_BIN" ]; then UV_BIN="$(command -v uv)"; fi\n'
        'exec "$UV_BIN" run --project "$DIR" --python 3.12 python "$DIR/lib/datapull.py" "$@"\n'
    )
    launcher.chmod(0o755)


def _install_project_requirements() -> None:
    print("  Syncing Bob's local runtime...")
    subprocess.check_call(_uv_sync_command(), cwd=ROOT)
    _write_bob_launcher()


def _install_capability(capability: str) -> None:
    """Install an optional capability into Bob's uv-managed environment."""
    print(f"  Adding Bob's {capability} tools...")
    subprocess.check_call(_uv_sync_command(extra=capability), cwd=ROOT)


def ensure_local_setup_for_onboarding() -> None:
    """Prepare the local Python environment before asking account questions."""
    if os.environ.get("BOB_ONBOARD_SETUP_DONE") == "1":
        return

    print("\nGetting Bob ready on this machine...")
    _install_project_requirements()
    print("  Bob is ready.\n")

    # A human may start onboarding with system Python before the launcher exists.
    # Re-enter through uv so optional imports used later in onboarding resolve from
    # the managed environment, while avoiding a loop when already running under uv.
    if os.environ.get("BOB_ONBOARD_SETUP_DONE") != "1" and sys.prefix == sys.base_prefix:
        command = _uv_run_command("python", str(Path(__file__).resolve()), *sys.argv[1:])
        env = os.environ.copy()
        env["BOB_ONBOARD_SETUP_DONE"] = "1"
        os.execvpe(command[0], command, env)



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
    sync_cmd = _uv_sync_command() + ["-v"]
    try:
        with open(log_path, "w") as logf:
            subprocess.check_call(sync_cmd, cwd=ROOT, stdout=logf, stderr=subprocess.STDOUT)
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
    _install_with_log(STATE_ROOT / "logs" / "setup.log")
    return _onboarding_runtime_issues(require_read, require_write)


def garf_command(query_path: Path, output_dir: Path, account: str, config: str | None) -> list[str]:
    uv = _uv_executable()
    garf_exe = shutil.which("garf")
    prefix: list[str] = []
    if uv:
        prefix = [uv, "run", "--project", str(ROOT), "--python", "3.12", "--no-sync"]
    if not garf_exe:
        candidate = Path(sys.executable).parent / "garf"
        if candidate.exists():
            garf_exe = str(candidate)
    if not garf_exe:
        garf_exe = "garf"
    cmd = prefix + [
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


def find_newest_raw_for_customer(query_name: str, customer_id: str) -> Path | None:
    """Return the newest raw CSV whose filename belongs to one account, if present."""
    normalized_customer = str(customer_id).replace("-", "")
    query_dir = RAW_DIR / query_name
    files = [
        path for path in query_dir.glob("*.csv")
        if path.stem.split("_", 1)[0].replace("-", "") == normalized_customer
    ]
    files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return files[0] if files else None


def newest_raw_for_customer(query_name: str, customer_id: str) -> Path:
    """Return the newest raw CSV whose filename belongs to one account."""
    path = find_newest_raw_for_customer(query_name, customer_id)
    if path is None:
        normalized_customer = str(customer_id).replace("-", "")
        query_dir = RAW_DIR / query_name
        die(f"no raw CSV found for {query_name} and account {normalized_customer} in {query_dir}")
    return path


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


def find_raw_files_for_range(
    query_name: str,
    start: dt.date,
    end: dt.date,
    customer_id: str | None = None,
) -> list[Path] | None:
    """Return every exact contiguous chunk needed to cover an inclusive range."""
    files: list[Path] = []
    windows = (
        split_date_range(start, end)
        if query_name in GRANULAR_DATE_QUERIES
        else [(start, end)]
    )
    for chunk_start, chunk_end in windows:
        path = find_raw_file_for_period(query_name, chunk_start, chunk_end, customer_id)
        if not path:
            return None
        files.append(path)
    return files


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
    'skipped_wiki' (wiki cache hit — agent writes via log-pull subcommand),
    'skipped_inflight' (another identical pull finished while we waited).
    """
    path = _pull_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
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
    client_instance_id = os.getenv("BOB_CLIENT_INSTANCE_ID", "").strip()
    if client_instance_id:
        entry["client_instance_id"] = client_instance_id
    with path.open("a") as f:
        json.dump(entry, f)
        f.write("\n")


def _pull_client_scope() -> str:
    return os.getenv("BOB_CLIENT_INSTANCE_ID", "").strip() or "default"


def _pull_log_path() -> Path:
    client_instance_id = os.getenv("BOB_CLIENT_INSTANCE_ID", "").strip()
    if client_instance_id:
        return PULL_LOG_PATH.parent / "clients" / client_instance_id / PULL_LOG_PATH.name
    return PULL_LOG_PATH


def _pull_log_candidates() -> list[Path]:
    primary = _pull_log_path()
    if primary == PULL_LOG_PATH:
        return [primary]
    return [primary, PULL_LOG_PATH]


def _pull_locks_dir() -> Path:
    client_instance_id = os.getenv("BOB_CLIENT_INSTANCE_ID", "").strip()
    if client_instance_id:
        return PULL_LOCKS_DIR.parent / "clients" / client_instance_id / PULL_LOCKS_DIR.name
    return PULL_LOCKS_DIR


def _pull_fingerprint(query: str, from_date: str, to_date: str, account: str) -> str:
    raw = "|".join((_pull_client_scope(), query, from_date, to_date, account))
    return hashlib.sha256(raw.encode()).hexdigest()


def _matching_pull_entry(entry: dict[str, Any], query: str, from_date: str, to_date: str, account: str) -> bool:
    if entry.get("query") != query:
        return False
    if entry.get("from_date") != from_date or entry.get("to_date") != to_date:
        return False
    if str(entry.get("account", "")).replace("-", "") != account:
        return False
    entry_scope = str(entry.get("client_instance_id", "")).strip()
    current_scope = os.getenv("BOB_CLIENT_INSTANCE_ID", "").strip()
    if current_scope:
        return entry_scope == current_scope
    return not entry_scope


def _latest_matching_pull(query: str, from_date: str, to_date: str, account: str) -> dict[str, Any] | None:
    latest: dict[str, Any] | None = None
    for path in _pull_log_candidates():
        if not path.exists():
            continue
        with path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if _matching_pull_entry(entry, query, from_date, to_date, account):
                    latest = entry
    return latest


def _claim_pull_lock(query: str, start: dt.date, end: dt.date, account: str) -> Path:
    locks_dir = _pull_locks_dir()
    locks_dir.mkdir(parents=True, exist_ok=True)
    lock_dir = locks_dir / _pull_fingerprint(query, start.isoformat(), end.isoformat(), account)
    deadline = time.monotonic() + float(os.getenv("BOB_PULL_WAIT_SECONDS", "300"))
    stale_seconds = float(os.getenv("BOB_PULL_STALE_SECONDS", "1800"))
    while True:
        exact = sorted((RAW_DIR / query).glob(f"{account}_{start}_{end}_*.csv"))
        if exact:
            raise FileExistsError(str(exact[-1]))
        recent = _latest_matching_pull(query, start.isoformat(), end.isoformat(), account)
        if recent and recent.get("output_file") and Path(str(recent["output_file"])).exists():
            raise FileExistsError(str(recent["output_file"]))
        try:
            lock_dir.mkdir()
            payload = {
                "client_instance_id": os.getenv("BOB_CLIENT_INSTANCE_ID", "").strip(),
                "query": query,
                "from_date": start.isoformat(),
                "to_date": end.isoformat(),
                "account": account,
                "pid": os.getpid(),
                "created_at": dt.datetime.now().isoformat(timespec="seconds"),
            }
            (lock_dir / "owner.json").write_text(json.dumps(payload, indent=2) + "\n")
            return lock_dir
        except FileExistsError:
            try:
                age = time.time() - lock_dir.stat().st_mtime
            except FileNotFoundError:
                continue
            if age > stale_seconds:
                shutil.rmtree(lock_dir, ignore_errors=True)
                continue
            if time.monotonic() >= deadline:
                die(
                    f"Another identical pull is still running for {account} / {query} / "
                    f"{start.isoformat()}..{end.isoformat()}. Try again in a bit."
                )
            time.sleep(1.0)


def _release_pull_lock(lock_dir: Path | None) -> None:
    if not lock_dir:
        return
    shutil.rmtree(lock_dir, ignore_errors=True)


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

# This is the platform compatibility surface while skill modules are extracted.
# It includes private legacy names deliberately; the final facade narrows exports.
__all__ = [name for name in globals() if not name.startswith("__")]
