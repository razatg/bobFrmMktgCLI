"""Typed STDIO MCP boundary for Bob analysis and hosted JTBD scheduling."""

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
from lib.bob.performance.exploration import materialize_sources, verify_exploration
from lib.bob.platform.dates import resolve_period_dates
from server.schedule_tools import with_schedule_tools


server = MCPServer(
    "bob",
    instructions=(
        "Use registered read-only analysis during normal investigations on Bob's selected account. "
        "Use the scheduling tools only for Bob JTBD jobs in the authenticated Chat. Never create an "
        "external Codex, ChatGPT, Page, Space, or operating-system automation."
    ),
)
PREPARED: dict[str, PreparedDataset] = {}
RESULTS: dict[str, AnalysisResult] = {}
METHODS: dict[str, dict] = {}
OBSOLETE_ADHOC_DATASETS = {"adgroup_network_period"}


def preparation_error(code: str, message: object) -> dict[str, object]:
    """Return a bounded, path-safe preparation failure as normal MCP content."""
    clean = re.sub(r"(?:/[^\s:]+)+", "[internal path]", str(message)).strip()
    return {"ok": False, "error": {"code": code, "message": clean[:600]}}


def _resolve_sources(sources: dict[str, str]) -> dict[str, PreparedDataset]:
    resolved: dict[str, PreparedDataset] = {}
    for alias, handle in sources.items():
        if not alias.strip() or handle not in PREPARED:
            raise AnalysisError("analysis references an unknown dataset handle")
        resolved[alias] = PREPARED[handle]
    return resolved


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
    result_handle = f"result-{uuid.uuid4().hex}"
    try:
        result = run_analysis(analysis_name, _resolve_sources(sources), operations, final_table, result_handle)
    except AnalysisError as exc:
        return preparation_error("ANALYSIS_VALIDATION_FAILED", exc)
    RESULTS[result_handle] = result
    METHODS[result_handle] = {"sources": sources, "operations": operations, "final_table": final_table}
    return {
        "analysis_marker": {"type": "custom_analysis", "analysis_name": result.analysis_name},
        "result_handle": result.handle,
        "method_summary": result.method_summary,
        "columns": list(result.columns),
        "row_count": len(result.rows),
        "preview": list(result.rows[:MAX_PREVIEW_ROWS]),
        "preview_truncated": len(result.rows) > MAX_PREVIEW_ROWS,
    }


@server.tool(name="bob_materialize_exploration", structured_output=True)
def bob_materialize_exploration(sources: dict[str, str]) -> dict[str, object]:
    """Materialize prepared selected-account tables for a Codex-sandboxed Pandas exploration."""
    try:
        return materialize_sources(_resolve_sources(sources))
    except AnalysisError as exc:
        return preparation_error("EXPLORATION_MATERIALIZATION_FAILED", exc)


@server.tool(name="bob_verify_exploration", structured_output=True)
def bob_verify_exploration(analysis_name: str, sources: dict[str, str], code_file: str,
                           result_file: str, method_summary: str) -> dict[str, object]:
    """Verify the saved result of a confirmed Codex-sandboxed Pandas exploration."""
    result_handle = f"result-{uuid.uuid4().hex}"
    try:
        result, sanity = verify_exploration(
            analysis_name, _resolve_sources(sources), code_file, result_file, method_summary, result_handle,
        )
    except AnalysisError as exc:
        return preparation_error("EXPLORATION_VALIDATION_FAILED", exc)
    RESULTS[result_handle] = result
    METHODS[result_handle] = {"sources": sources, "exploration_code": code_file,
                              "result_file": result_file, "method_summary": method_summary}
    return {
        "analysis_marker": {"type": "custom_analysis", "analysis_name": result.analysis_name},
        "result_handle": result_handle,
        "method_summary": result.method_summary,
        "columns": list(result.columns),
        "row_count": len(result.rows),
        "preview": list(result.rows[:MAX_PREVIEW_ROWS]),
        "preview_truncated": len(result.rows) > MAX_PREVIEW_ROWS,
        "sanity": sanity,
        "disclaimer": "Custom exploratory analysis over verified selected-account data; review its assumptions before acting.",
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


@server.tool(name="bob_record_decision", structured_output=True)
def bob_record_decision(decision: dict[str, object], result_handles: list[str]) -> dict[str, object]:
    """Persist a recommendation and immutable copies of cited analysis inputs/outputs."""
    import json
    from dataclasses import asdict
    from lib.bob.performance.adhoc_data import selected_account
    from lib.bob.platform.core import STATE_ROOT
    from lib.bob.decisions.records import record
    account, profile = selected_account()
    decision = dict(decision)
    decision.setdefault('goals', profile.get('goals', {}))
    decision.setdefault('primary_goal', profile.get('primary_goal', 'in_app_conversions'))
    evidence = list(decision.get("evidence", []))
    if any(handle not in RESULTS for handle in result_handles):
        raise AnalysisError("decision cites an unknown result")
    directory = STATE_ROOT / 'data' / 'processed' / account / 'analysis'
    directory.mkdir(parents=True, exist_ok=True)
    for handle in result_handles:
        method = METHODS.get(handle, {})
        target = directory / f'{handle}.json'
        sources = {alias: asdict(source) for alias, source in _resolve_sources(method.get('sources', {})).items()}
        target.write_text(json.dumps({"result": asdict(RESULTS[handle]), "inputs": sources,
                                      "method": method}, allow_nan=False))
        evidence.append({"source": str(target.relative_to(STATE_ROOT)), "operation": method})
    return record(STATE_ROOT, account, dict(decision, evidence=evidence))


@server.tool(name="bob_schedule_list", structured_output=True)
def bob_schedule_list() -> dict[str, object]:
    """List the current user's scheduled jobs in this Chat so references can be resolved safely."""
    return with_schedule_tools(lambda tools: tools.list())


@server.tool(name="bob_schedule_create", structured_output=True)
def bob_schedule_create(prompt: str, day_of_week: str, local_time: str) -> dict[str, object]:
    """Create one weekly Bob JTBD job using a full weekday and local wall-clock time."""
    return with_schedule_tools(lambda tools: tools.create(prompt, day_of_week, local_time))


@server.tool(name="bob_schedule_update", structured_output=True)
def bob_schedule_update(day_of_week: str, local_time: str, task_id: str = "") -> dict[str, object]:
    """Move one scheduled job to a new weekly weekday and local time."""
    return with_schedule_tools(lambda tools: tools.update(day_of_week, local_time, task_id))


@server.tool(name="bob_schedule_pause", structured_output=True)
def bob_schedule_pause(task_id: str = "") -> dict[str, object]:
    """Pause one scheduled job without deleting its history."""
    return with_schedule_tools(lambda tools: tools.pause(task_id))


@server.tool(name="bob_schedule_resume", structured_output=True)
def bob_schedule_resume(task_id: str = "") -> dict[str, object]:
    """Resume one paused job and calculate its next future occurrence."""
    return with_schedule_tools(lambda tools: tools.resume(task_id))


@server.tool(name="bob_schedule_run_now", structured_output=True)
def bob_schedule_run_now(task_id: str = "") -> dict[str, object]:
    """Queue one manual occurrence without moving the recurring deadline."""
    return with_schedule_tools(lambda tools: tools.run_now(task_id))


@server.tool(name="bob_schedule_delete", structured_output=True)
def bob_schedule_delete(task_id: str = "", confirm: bool = False) -> dict[str, object]:
    """Request deletion, or confirm a deletion the user explicitly approved within ten minutes."""
    return with_schedule_tools(lambda tools: tools.delete(task_id, confirm))


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
