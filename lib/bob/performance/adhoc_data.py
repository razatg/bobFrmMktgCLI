"""Selected-account data preparation and artifact publishing for ad-hoc analysis."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import uuid
from pathlib import Path

from lib.bob.performance.adhoc import (
    DATASETS,
    AnalysisError,
    AnalysisResult,
    PreparedDataset,
    normalize_source_rows,
)
from lib.bob.performance.aggregate import ensure_processed_file_for_period
from lib.bob.performance.fetch import fetch
from lib.bob.performance.manifest import _manifest_pull_status
from lib.bob.platform.core import RAW_DIR, account_wiki_dir, find_processed_files_for_period, load_profile
from lib.bob.platform.presentation import read_csv


MAX_PERIOD_DAYS = 366


def selected_account() -> tuple[str, dict[str, object]]:
    expected = re.sub(r"\D", "", os.environ.get("BOB_SELECTED_CUSTOMER_ID", ""))
    if not expected:
        raise AnalysisError("selected-account scope is unavailable")
    profile = load_profile(required=True)
    actual = re.sub(r"\D", "", str(profile.get("google_ads_customer_id", "")))
    if not actual or actual != expected:
        raise AnalysisError("selected-account scope does not match the active runtime profile")
    return expected, profile


def prepare_dataset(
    dataset: str,
    from_date: str,
    to_date: str,
    reason: str,
    question: str,
    handle: str,
) -> tuple[PreparedDataset, dict[str, object]]:
    spec = DATASETS.get(dataset)
    if spec is None:
        raise AnalysisError(f"unknown registered dataset: {dataset}")
    start, end = _date_window(from_date, to_date)
    customer_id, profile = selected_account()
    manifest_pulls = _manifest_pull_status(customer_id, dataset, start, end)
    processed_paths = find_processed_files_for_period(spec.subdir, [(start, end)], customer_id)
    path = processed_paths[0] if processed_paths else None
    fetched = False
    if path is None:
        path = ensure_processed_file_for_period(
            dataset, spec.subdir, start, end, customer_id,
            str(profile.get("primary_goal") or "in_app_conversions"),
        )
    if path is None:
        if not reason.strip() or not question.strip():
            raise AnalysisError("reason and question are required before fetching missing data")
        _fetch_registered(dataset, start, end, customer_id, reason, question)
        fetched = True
        path = ensure_processed_file_for_period(
            dataset, spec.subdir, start, end, customer_id,
            str(profile.get("primary_goal") or "in_app_conversions"),
        )
    if path is None:
        raise AnalysisError("registered data could not be prepared for the requested period")
    source_rows = read_csv(path)
    if not source_rows:
        if not reason.strip() or not question.strip():
            raise AnalysisError("reason and question are required before rebuilding empty data")
        _fetch_registered(dataset, start, end, customer_id, reason, question, force=True)
        fetched = True
        path = ensure_processed_file_for_period(
            dataset, spec.subdir, start, end, customer_id,
            str(profile.get("primary_goal") or "in_app_conversions"), force=True,
        )
        source_rows = read_csv(path) if path else []
    if not source_rows:
        raise AnalysisError(
            "registered data preparation returned no rows for the requested period; "
            "an empty cached dataset is not usable for analysis"
        )
    rows = normalize_source_rows(spec, source_rows, customer_id)
    prepared = PreparedDataset(
        handle=handle,
        spec=spec,
        start=start.isoformat(),
        end=end.isoformat(),
        primary_goal=str(profile.get("primary_goal") or "in_app_conversions"),
        rows=rows,
    )
    return prepared, {
        "dataset_handle": handle,
        "dataset": dataset,
        "from": prepared.start,
        "to": prepared.end,
        "rows": len(rows),
        "fetched": fetched,
        "prior_manifest_matches": len(manifest_pulls),
    }


def publish_result(result: AnalysisResult, title: str, output_format: str) -> dict[str, object]:
    customer_id, profile = selected_account()
    clean_title = " ".join(title.split()).strip()
    if not clean_title or len(clean_title) > 120:
        raise AnalysisError("title must contain 1 to 120 characters")
    normalized_format = output_format.strip().lower()
    suffix = {"markdown": ".md", "md": ".md", "csv": ".csv"}.get(normalized_format)
    if suffix is None:
        raise AnalysisError("format must be markdown or csv")
    slug = re.sub(r"[^a-z0-9]+", "-", clean_title.lower()).strip("-")[:60] or "analysis"
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    filename = f"{slug}-{stamp}-{uuid.uuid4().hex[:6]}{suffix}"
    wiki_root = account_wiki_dir(customer_id)
    target = wiki_root / "analyses" / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    if suffix == ".csv":
        _write_csv(target, result)
    else:
        target.write_text(_markdown(result, clean_title), encoding="utf-8")
    _append_index(wiki_root, clean_title, filename, str(profile.get("account_name") or "Account"))
    return {
        "artifact": f"wiki/{customer_id}/analyses/{filename}",
        "title": clean_title,
        "format": "csv" if suffix == ".csv" else "markdown",
        "rows": len(result.rows),
    }


def _date_window(from_date: str, to_date: str) -> tuple[dt.date, dt.date]:
    try:
        start, end = dt.date.fromisoformat(from_date), dt.date.fromisoformat(to_date)
    except ValueError as exc:
        raise AnalysisError("dates must use YYYY-MM-DD") from exc
    if start > end:
        raise AnalysisError("from_date must not be after to_date")
    if (end - start).days + 1 > MAX_PERIOD_DAYS:
        raise AnalysisError(f"period cannot exceed {MAX_PERIOD_DAYS} days")
    return start, end


def _fetch_registered(
    dataset: str, start: dt.date, end: dt.date, customer_id: str, reason: str, question: str,
    force: bool = False,
) -> None:
    args = argparse.Namespace(
        query=dataset,
        days=None,
        from_date=start.isoformat(),
        to=end.isoformat(),
        account=customer_id,
        config=None,
        dry_run=False,
        run_id=None,
        reason=reason.strip(),
        question=question.strip(),
        force=force,
        quiet=True,
    )
    try:
        fetch(args)
    except SystemExit as exc:
        detail = _fetch_failure_detail(dataset, start, end, customer_id)
        message = detail or f"data preparation failed (exit {exc.code})"
        raise AnalysisError(message) from exc


def _fetch_failure_detail(dataset: str, start: dt.date, end: dt.date, customer_id: str) -> str | None:
    """Return one bounded Google Ads error from the fetch metadata, if recorded."""
    pattern = f"{customer_id}_{start.isoformat()}_{end.isoformat()}_*.meta.json"
    metadata_files = sorted((RAW_DIR / dataset).glob(pattern), key=lambda path: path.stat().st_mtime)
    if not metadata_files:
        return None
    try:
        metadata = json.loads(metadata_files[-1].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    output = "\n".join(str(metadata.get(key, "")) for key in ("stderr", "stdout"))
    lines = [" ".join(line.split()) for line in output.splitlines()]
    relevant = [line for line in lines if any(marker in line.lower() for marker in (
        "googleads", "google ads", "query_error", "field_error", "prohibited_",
    ))]
    if not relevant:
        return None
    detail = " ".join(relevant)
    detail = re.sub(r"(?:/[^\s:]+)+", "[internal path]", detail)
    return f"Google Ads rejected the registered data query: {detail[:600]}"


def _write_csv(path: Path, result: AnalysisResult) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(result.columns))
        writer.writeheader()
        writer.writerows(result.rows)


def _markdown(result: AnalysisResult, title: str) -> str:
    lines = ["← [Wiki Index](../Index.md)", "", f"# {title}", "", result.method_summary, ""]
    if not result.rows:
        return "\n".join(lines + ["No matching rows.", ""])
    widths = {
        column: max(len(column), *(len(_display(row.get(column))) for row in result.rows))
        for column in result.columns
    }
    numeric = {
        column: any(isinstance(row.get(column), (int, float)) for row in result.rows)
        for column in result.columns
    }
    def align(value: str, column: str) -> str:
        return value.rjust(widths[column]) if numeric[column] else value.ljust(widths[column])
    lines.append("| " + " | ".join(align(column, column) for column in result.columns) + " |")
    lines.append("| " + " | ".join(
        ("-" * max(1, widths[column] - 1) + ":") if numeric[column] else "-" * widths[column]
        for column in result.columns
    ) + " |")
    for row in result.rows:
        lines.append("| " + " | ".join(align(_display(row.get(column)), column) for column in result.columns) + " |")
    return "\n".join(lines) + "\n"


def _display(value: object) -> str:
    if value is None:
        return "NA"
    if isinstance(value, float):
        return f"{value:.6f}".rstrip("0").rstrip(".")
    return str(value).replace("|", "\\|").replace("\n", " ")


def _append_index(wiki_root: Path, title: str, filename: str, account_name: str) -> None:
    index = wiki_root / "Index.md"
    if index.exists():
        content = index.read_text(encoding="utf-8", errors="replace").rstrip()
    else:
        wiki_root.mkdir(parents=True, exist_ok=True)
        content = f"# {account_name} Wiki\n\n## Analyses"
    if "## Analyses" not in content:
        content += "\n\n## Analyses"
    entry = f"- {dt.date.today().isoformat()} — [{title}](analyses/{filename})"
    if entry not in content:
        content += "\n" + entry
    index.write_text(content + "\n", encoding="utf-8")
