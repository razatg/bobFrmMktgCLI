"""Read-only STDIO MCP server for bounded ad-hoc Bob analysis."""

from __future__ import annotations

import datetime as dt
import re
import uuid

from mcp.server.mcpserver import MCPServer

from lib.bob.performance.adhoc import (
    MAX_PREVIEW_ROWS,
    AnalysisError,
    AnalysisResult,
    PreparedDataset,
    catalog,
    run_analysis,
)
from lib.bob.performance.adhoc_data import prepare_dataset, publish_result
from lib.bob.platform.dates import resolve_period_dates


server = MCPServer(
    "bob",
    instructions=(
        "Use these tools only for confirmed, read-only custom analyses on Bob's selected account. "
        "Never invent unavailable dimensions or silently choose business thresholds."
    ),
)
PREPARED: dict[str, PreparedDataset] = {}
RESULTS: dict[str, AnalysisResult] = {}
OBSOLETE_ADHOC_DATASETS = {"adgroup_network_period"}


def preparation_error(code: str, message: object) -> dict[str, object]:
    """Return a bounded, path-safe preparation failure as normal MCP content."""
    clean = re.sub(r"(?:/[^\s:]+)+", "[internal path]", str(message)).strip()
    return {"ok": False, "error": {"code": code, "message": clean[:600]}}


@server.tool(name="bob_resolve_dates", structured_output=True)
def bob_resolve_dates(period: str = "", from_date: str = "", to_date: str = "") -> dict[str, object]:
    """Resolve a Bob date alias or validate one explicit inclusive date window."""
    if from_date or to_date:
        if not from_date or not to_date:
            raise AnalysisError("both from_date and to_date are required for a custom period")
        try:
            start, end = dt.date.fromisoformat(from_date), dt.date.fromisoformat(to_date)
        except ValueError as exc:
            raise AnalysisError("dates must use YYYY-MM-DD") from exc
        if start > end:
            raise AnalysisError("from_date must not be after to_date")
        windows = [(start, end)]
    elif period.strip():
        windows = resolve_period_dates(period)
    else:
        raise AnalysisError("provide a period alias or an explicit date window")
    return {"windows": [{"from": start.isoformat(), "to": end.isoformat()} for start, end in windows]}


@server.tool(name="bob_data_catalog", structured_output=True)
def bob_data_catalog() -> dict[str, object]:
    """List the registered datasets, dimensions, metrics, operations, and limits."""
    return catalog()


@server.tool(name="bob_prepare_data", structured_output=True)
def bob_prepare_data(
    dataset: str,
    from_date: str,
    to_date: str,
    reason: str,
    question: str,
) -> dict[str, object]:
    """Prepare one registered dataset for the selected account, fetching only when absent."""
    if dataset in OBSOLETE_ADHOC_DATASETS:
        return preparation_error(
            "DATASET_UNAVAILABLE",
            "This ad-group dataset is unavailable for ad-hoc analysis; use the registered primary-conversion dataset.",
        )
    handle = f"dataset-{uuid.uuid4().hex}"
    try:
        prepared, response = prepare_dataset(dataset, from_date, to_date, reason, question, handle)
    except AnalysisError as exc:
        return preparation_error("DATA_PREPARATION_FAILED", exc)
    PREPARED[handle] = prepared
    return response


@server.tool(name="bob_analyze", structured_output=True)
def bob_analyze(
    analysis_name: str,
    sources: dict[str, str],
    operations: list[dict[str, object]],
    final_table: str,
) -> dict[str, object]:
    """Run a validated operation graph over prepared selected-account datasets."""
    resolved: dict[str, PreparedDataset] = {}
    for alias, handle in sources.items():
        if not alias.strip() or handle not in PREPARED:
            raise AnalysisError("analysis references an unknown dataset handle")
        resolved[alias] = PREPARED[handle]
    result_handle = f"result-{uuid.uuid4().hex}"
    result = run_analysis(analysis_name, resolved, operations, final_table, result_handle)
    RESULTS[result_handle] = result
    return {
        "analysis_marker": {"type": "custom_analysis", "analysis_name": result.analysis_name},
        "result_handle": result.handle,
        "method_summary": result.method_summary,
        "columns": list(result.columns),
        "row_count": len(result.rows),
        "preview": list(result.rows[:MAX_PREVIEW_ROWS]),
        "preview_truncated": len(result.rows) > MAX_PREVIEW_ROWS,
    }


@server.tool(name="bob_publish_result", structured_output=True)
def bob_publish_result(
    result_handle: str,
    title: str,
    output_format: str,
    user_confirmed: bool,
) -> dict[str, object]:
    """Publish a confirmed result as selected-account Markdown or CSV."""
    if not user_confirmed:
        raise AnalysisError("explicit user confirmation is required before publishing")
    result = RESULTS.get(result_handle)
    if result is None:
        raise AnalysisError("unknown or expired result handle")
    return publish_result(result, title, output_format)


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
