"""GARF fetch execution for the performance-analysis skill."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from lib.bob.platform.core import *  # noqa: F403
from lib.bob.performance.aggregate import aggregate

def _fetch_one(args: argparse.Namespace) -> None:
    ensure_dirs()
    profile = load_profile(required=not bool(args.account))
    query_name = args.query
    account = args.account or profile.get("google_ads_customer_id")
    if not account:
        die("google_ads_customer_id missing from profile and --account not provided")
    account = str(account).replace("-", "")
    config = args.config or _profile_read_config_value(profile)
    if not config and not args.dry_run:
        die("I need the Google Ads developer token from Google Ads > Admin > API Center before I can fetch data from Google Ads.", error_code="GOOGLE_AUTH_REQUIRED")
    if config:
        config = str(_resolve_state_path(config))

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
    lock_dir: Path | None = None
    if not getattr(args, "force", False) and not args.dry_run:
        recent = _latest_matching_pull(query_name, start.isoformat(), end.isoformat(), account)
        if recent and recent.get("output_file") and Path(str(recent["output_file"])).exists():
            existing_output = Path(str(recent["output_file"]))
            print(f"skipping {query_name} {start}..{end} — already logged {existing_output.name}")
            log_pull(query_name, start.isoformat(), end.isoformat(), account, rid, str(existing_output), reason, question, outcome="skipped_raw")
            try:
                log_signal(
                    event_type="redundant_fetch",
                    note=f"fetch {query_name} {start}..{end} but pull log already pointed to {existing_output.name}",
                    account=account,
                    intent="fetch",
                    severity="friction",
                    source="cli",
                )
            except Exception:
                pass
            return
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
        try:
            lock_dir = _claim_pull_lock(query_name, start, end, account)
        except FileExistsError as exc:
            reused = Path(str(exc))
            print(f"reusing in-flight {query_name} {start}..{end} — {reused.name}")
            log_pull(query_name, start.isoformat(), end.isoformat(), account, rid, str(reused), reason, question, outcome="skipped_inflight")
            return

    substitutions = {}
    if query_name in CREATIVE_ASSET_QUERIES.values():
        substitutions['min_impressions'] = int(profile.get('creative_min_impressions', DEFAULT_CREATIVE_MIN_IMPRESSIONS))
    rendered_query = render_query(query_name, start, end, substitutions)
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

    try:
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
    finally:
        _release_pull_lock(lock_dir)

    write_metadata(meta_file, metadata)
    log_pull(query_name, start.isoformat(), end.isoformat(), account, rid, str(output_file), reason, question, outcome="fetched")
    if not getattr(args, "quiet", False):
        print(f"raw output written: {output_file}")
        print(f"metadata written: {meta_file}")
    try:
        with open(output_file, newline="") as _f:
            _row_count = sum(1 for _ in csv.reader(_f)) - 1
    except Exception:
        _row_count = -1
    if getattr(args, "quiet", False):
        print(f"pull complete: {query_name} {start.isoformat()}..{end.isoformat()} ({_row_count} rows)")
    if _row_count == 0:
        if not getattr(args, "quiet", False):
            print(
                f"WARNING: 0 rows for {account} / {query_name} / {start.isoformat()}..{end.isoformat()}. "
                f"The account may have no activity in this window.",
                file=sys.stderr,
            )


def fetch(args: argparse.Namespace) -> None:
    """Fetch one query, chunking ordinary granular ranges into sequential seven-day pulls.

    Asset-specific creative queries intentionally use the configured total lookback
    window as one server-filtered request; they are not daily-segmented or split.
    """
    if args.query in CREATIVE_ASSET_QUERIES.values():
        profile = load_profile(required=not bool(args.account))
        if not args.from_date and not args.to and not args.days:
            args.days = int(profile.get('creative_lookback_days', 15))
        _fetch_one(args)
        return
    if args.query not in GRANULAR_DATE_QUERIES:
        _fetch_one(args)
        return

    start, end = resolve_range(args)
    windows = split_date_range(start, end)
    if len(windows) == 1:
        _fetch_one(args)
        return

    if not getattr(args, "quiet", False):
        print(
            f"{args.query}: {start}..{end} -> {len(windows)} sequential pulls "
            f"(maximum {GRANULAR_QUERY_MAX_DAYS} days each)"
        )
    failures: list[str] = []
    for index, (chunk_start, chunk_end) in enumerate(windows, start=1):
        if not getattr(args, "quiet", False):
            print(f"\n==> granular pull {index}/{len(windows)}: {chunk_start}..{chunk_end}")
        child = argparse.Namespace(
            query=args.query,
            days=None,
            from_date=chunk_start.isoformat(),
            to=chunk_end.isoformat(),
            account=args.account,
            config=args.config,
            dry_run=args.dry_run,
            run_id=(f"{args.run_id}-{index:03d}" if args.run_id else None),
            reason=args.reason,
            question=args.question,
            force=args.force,
            quiet=getattr(args, "quiet", False),
        )
        try:
            _fetch_one(child)
        except SystemExit as exc:
            failures.append(f"{chunk_start}..{chunk_end}: exit {exc.code}")
            break
    if failures:
        print("\ncompleted with failures:")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)

def bootstrap(args: argparse.Namespace) -> None:
    failures: list[str] = []
    aggregate_ranges: dict[str, tuple[dt.date, dt.date]] = {}
    for entry in DEFAULT_BOOTSTRAP:
        query_name = entry["query"]
        if "period" in entry:
            windows = resolve_period_dates(entry["period"])
            label = f"{query_name} ({entry['period']}, {len(windows)} windows)"
        else:
            windows = [None]
            label = f"{query_name} ({entry['days']} days)"
            if query_name in GRANULAR_DATE_QUERIES:
                end = parse_date(args.to) or (today() - dt.timedelta(days=1))
                start = parse_date(args.from_date) or (end - dt.timedelta(days=entry["days"] - 1))
                aggregate_ranges[query_name] = (start, end)
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
                    quiet=getattr(args, "quiet", False),
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
                    quiet=getattr(args, "quiet", False),
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
                date_range = aggregate_ranges.get(grain)
                agg_args = argparse.Namespace(
                    grain=grain, source=None, goal=None, input=None, customer=None, output=None,
                    from_date=date_range[0].isoformat() if date_range else None,
                    to=date_range[1].isoformat() if date_range else None,
                )
                aggregate(agg_args)
            except SystemExit:
                print(f"  aggregate {grain}: skipped (no data yet)")
        print("\nbootstrap complete")

__all__ = ["fetch", "bootstrap"]
