"""Stable Bob command-line parser and dispatcher."""

from __future__ import annotations

import argparse
import sys

from lib.bob.platform.core import *
from lib.bob.performance.fetch import fetch, bootstrap
from lib.bob.performance.aggregate import *
from lib.bob.performance.compare import *
from lib.bob.performance.validation import *
from lib.bob.performance.creatives import *
from lib.bob.performance.manifest import *
from lib.bob.bid_budget import *
from lib.bob.static_banners import *
from lib.bob.creative_copy import *
from lib.bob.accounts import *
from lib.bob.self_improve import *
from lib.bob.sync import *
from lib.bob.snapshot import *
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
    fetch_parser.add_argument("--quiet", action="store_true", help="print only a compact pull result")
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
    boot_parser.add_argument("--quiet", action="store_true", help="print only compact pull results")
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
    wk_parser.add_argument("--grain", default="both", choices=["account", "campaign", "adgroup", "both"])
    wk_parser.add_argument("--name-contains", help="filter campaigns by name substring")
    wk_parser.add_argument("--output", help="write campaign comparison CSV to this path")
    wk_parser.add_argument("--output-account", help="write account comparison CSV to this path")
    wk_parser.add_argument("--goal", choices=["installs", "in_app_conversions"])
    wk_parser.add_argument("--all-metrics", action="store_true", help="show full metric table; use --reach-metrics to include Users/Frequency")
    wk_parser.add_argument("--reach-metrics", action="store_true", help="include opt-in Users/Frequency for individual campaign rows")
    wk_parser.add_argument("--network-split", action="store_true", help="keep campaign comparisons split by network")
    wk_parser.add_argument("--summary", action="store_true", help="print a compact driver summary; keep full rows in --output")
    wk_parser.add_argument("--top", type=int, default=10, help="number of summary drivers to print (default: 10)")
    wk_parser.set_defaults(func=compare_weeks)

    mo_parser = sub.add_parser("compare-months", help="compare MTD or full-month performance across two calendar months")
    mo_parser.add_argument("--month", type=int, help="current month 1–12 (default: current month)")
    mo_parser.add_argument("--vs", type=int, help="baseline month 1–12 (default: current - 1)")
    mo_parser.add_argument("--year", type=int, help="year for the current month (default: current year)")
    mo_parser.add_argument("--full", action="store_true", help="compare full calendar months instead of MTD")
    mo_parser.add_argument("--grain", default="both", choices=["account", "campaign", "adgroup", "both"])
    mo_parser.add_argument("--name-contains", help="filter campaigns by name substring")
    mo_parser.add_argument("--output", help="write campaign comparison CSV to this path")
    mo_parser.add_argument("--output-account", help="write account comparison CSV to this path")
    mo_parser.add_argument("--goal", choices=["installs", "in_app_conversions"])
    mo_parser.add_argument("--all-metrics", action="store_true", help="show full metric table; use --reach-metrics to include Users/Frequency")
    mo_parser.add_argument("--reach-metrics", action="store_true", help="include opt-in Users/Frequency for individual campaign rows")
    mo_parser.add_argument("--network-split", action="store_true", help="keep campaign comparisons split by network")
    mo_parser.add_argument("--summary", action="store_true", help="print a compact driver summary; keep full rows in --output")
    mo_parser.add_argument("--top", type=int, default=10, help="number of summary drivers to print (default: 10)")
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
    slice_parser.add_argument("--output-network", help="write campaign × network comparison CSV to this path")
    slice_parser.add_argument("--goal", choices=["installs", "in_app_conversions"])
    slice_parser.add_argument("--all-metrics", action="store_true", help="show full metric table; use --reach-metrics to include Users/Frequency")
    slice_parser.add_argument("--reach-metrics", action="store_true", help="include opt-in Users/Frequency for individual campaign rows")
    slice_parser.add_argument("--network-split", action="store_true", help="show campaign × network rows plus segment network rollup")
    slice_parser.add_argument("--summary", action="store_true", help="print a compact driver summary; keep full rows in --output")
    slice_parser.add_argument("--top", type=int, default=10, help="number of summary drivers to print (default: 10)")
    slice_parser.set_defaults(func=slice_campaigns)

    manifest_parser = sub.add_parser("data-manifest", help="summarise available raw and processed data for one account")
    manifest_parser.add_argument("--account", help="customer ID (default: active account)")
    manifest_parser.add_argument("--query", help="filter by query or processed grain")
    manifest_parser.add_argument("--from", dest="from_date", help="include windows ending on or after this date")
    manifest_parser.add_argument("--to", help="include windows starting on or before this date")
    manifest_parser.set_defaults(func=data_manifest)

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
    bb_rec_parser.add_argument("--trend", help="explicit campaign-trend CSV (must match the selected account's exact current W0 window)")
    bb_rec_parser.add_argument("--bid-budget", help="explicit bid_budget_inputs raw CSV (default: newest for the selected account)")
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
        help="period name: yesterday, yesterday-vs-sdlw, last-week, last-complete-week, wow, mom, mtd, 3week-rolling, bid-budget-weeks, partial-wow",
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

    ob_parser = sub.add_parser("onboard", help="onboarding — set up a new account (interactive, or --answers for agents)")
    ob_parser.add_argument("--account-id", help="pre-fill customer ID (skip prompt)")
    ob_parser.add_argument(
        "--answers",
        help="non-interactive: a JSON object of onboarding answers gathered in chat "
        "(keys: customer_id, account_name, campaign_type, primary_goal, currency, "
        "mcc_id, mcc_name, developer_token, skip_read_access, oauth_client_json_path, "
        "cac_ceiling, bid_budget_change_pct, bid_budget_cooldown_days). A real save requires "
        "developer_token unless skip_read_access is true. Skips all interactive prompts.",
    )
    ob_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="with --answers: validate and print the confirm summary, write nothing",
    )
    ob_parser.add_argument(
        "--interactive",
        action="store_true",
        help="run the hands-on terminal prompt flow (for a human in a real terminal). "
        "Without this and without --answers, onboard just prints usage guidance.",
    )
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

    snapshot_parser = sub.add_parser("snapshot-pull", help="pull a safe VM data snapshot for local inspection")
    snapshot_parser.add_argument("--ssh-host", help="SSH target, e.g. user@vm-host")
    snapshot_parser.add_argument("--gcloud-instance", help="Google Compute Engine instance, e.g. bob-frm-mktg")
    snapshot_parser.add_argument("--gcloud-zone", help="Google Cloud zone, e.g. us-central1-b")
    snapshot_parser.add_argument("--gcloud-project", help="Google Cloud project ID")
    snapshot_parser.add_argument("--remote-dir", default="", help="remote Bob repository directory")
    snapshot_parser.add_argument("--local-dir", default="", help="local snapshot directory")
    snapshot_parser.set_defaults(func=snapshot_pull)

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
  data-manifest                 Summarise available data for the active account

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
  snapshot-pull                 Pull a safe VM data snapshot for local inspection (on demand)

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
    if argv[0].startswith("video-"):
        _install_capability("video")
    elif argv[0] in {
        "bid-budget-apply",
        "static-variants-apply",
        "creative-copy-apply",
    }:
        _install_capability("write")
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

__all__ = ["build_parser", "main", "_COMMAND_MAP"]
