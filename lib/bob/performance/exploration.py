"""Materialization and deterministic verification for Codex-sandboxed Wings It analyses."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

from lib.bob.performance.adhoc import AnalysisError, AnalysisResult, PreparedDataset, Row


MAX_CODE_CHARS = 8_000
MAX_RESULT_ROWS = 10_000
MAX_RESULT_COLUMNS = 100


def materialize_sources(sources: dict[str, PreparedDataset]) -> dict[str, object]:
    """Write prepared account-scoped rows into the disposable Codex workspace."""
    root = _exploration_root()
    inputs = root / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}
    for alias, source in sources.items():
        target = inputs / f"{alias}.json"
        target.write_text(json.dumps(list(source.rows)), encoding="utf-8")
        files[alias] = str(Path(root.name) / target.relative_to(root))
    return {"inputs": files, "rows": {alias: len(source.rows) for alias, source in sources.items()}}


def verify_exploration(analysis_name: str, sources: dict[str, PreparedDataset], code_file: str,
                       result_file: str, method_summary: str, result_handle: str) -> tuple[AnalysisResult, dict[str, object]]:
    """Verify a Codex-sandboxed result before it can be presented or published."""
    name = analysis_name.strip()
    if not name or len(name) > 120:
        raise AnalysisError("analysis_name must contain 1 to 120 characters")
    summary = " ".join(method_summary.split())
    if not summary or len(summary) > 600:
        raise AnalysisError("method_summary must contain 1 to 600 characters")
    root = _exploration_root()
    code = _workspace_file(root, code_file, ".py").read_text(encoding="utf-8")
    if not code.strip() or len(code) > MAX_CODE_CHARS:
        raise AnalysisError(f"exploration code must contain 1 to {MAX_CODE_CHARS:,} characters")
    rows = _read_result(_workspace_file(root, result_file, ".json"))
    sanity = _sanity_check(rows, sources)
    columns = tuple(rows[0]) if rows else ()
    return AnalysisResult(result_handle, name, summary, columns, tuple(rows)), sanity


def _exploration_root() -> Path:
    raw = os.environ.get("BOB_EXPLORATION_DIR", "")
    if not raw:
        raise AnalysisError("exploration workspace is unavailable")
    root = Path(raw).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _workspace_file(root: Path, relative: str, suffix: str) -> Path:
    candidate = (root / relative).resolve()
    if candidate.parent != root or candidate.suffix != suffix or not candidate.is_file():
        raise AnalysisError("exploration files must be direct files in the disposable workspace")
    return candidate


def _read_result(path: Path) -> list[Row]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AnalysisError("exploration result must be valid JSON records") from exc
    if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
        raise AnalysisError("exploration result must be a table of records")
    return [{str(column): value for column, value in row.items()} for row in payload]


def _sanity_check(rows: list[Row], sources: dict[str, PreparedDataset]) -> dict[str, object]:
    if len(rows) > MAX_RESULT_ROWS:
        raise AnalysisError(f"exploration result exceeds the {MAX_RESULT_ROWS:,}-row limit")
    columns = set().union(*(row.keys() for row in rows)) if rows else set()
    if len(columns) > MAX_RESULT_COLUMNS:
        raise AnalysisError(f"exploration result exceeds the {MAX_RESULT_COLUMNS}-column limit")
    customer_ids = {str(row.get("customer_id", "")).replace("-", "") for source in sources.values() for row in source.rows}
    customer_ids.discard("")
    warnings: list[str] = []
    for row in rows:
        if "customer_id" in row and str(row["customer_id"]).replace("-", "") not in customer_ids:
            raise AnalysisError("exploration result contains a customer outside the prepared sources")
        for column, value in row.items():
            if isinstance(value, float) and not math.isfinite(value):
                raise AnalysisError(f"exploration result contains a non-finite value in {column}")
    _ratio_warnings(rows, warnings)
    _additive_warnings(rows, sources, warnings)
    return {"status": "passed_with_warnings" if warnings else "passed", "input_rows": {alias: len(source.rows) for alias, source in sources.items()}, "output_rows": len(rows), "output_columns": len(columns), "checks": ["selected-account inputs", "finite numbers", "result bounds", "ratio reconciliation"], "warnings": warnings}


def _ratio_warnings(rows: list[Row], warnings: list[str]) -> None:
    for row in rows:
        for ratio_name, numerator, denominator, multiplier in (("cpm", "cost", "impressions", 1000.0), ("primary_cpa", "cost", "primary_conversions", 1.0)):
            for suffix in ("", "_left", "_right"):
                key = ratio_name + suffix
                if key not in row or numerator + suffix not in row or denominator + suffix not in row:
                    continue
                divisor, actual = _number(row[denominator + suffix]), _number(row[key])
                numerator_value = _number(row[numerator + suffix])
                expected = None if not divisor or numerator_value is None else numerator_value / divisor * multiplier
                if expected is not None and actual is not None and not math.isclose(actual, expected, rel_tol=1e-5, abs_tol=1e-5):
                    warnings.append(f"{key} does not reconcile to its displayed numerator and denominator")
                    return


def _additive_warnings(rows: list[Row], sources: dict[str, PreparedDataset], warnings: list[str]) -> None:
    for metric in ("impressions", "clicks", "cost", "installs", "in_app_conversions", "primary_conversions"):
        if not rows or metric not in rows[0]:
            continue
        total = sum(_number(row.get(metric)) or 0.0 for row in rows)
        source_totals = [sum(_number(row.get(metric)) or 0.0 for row in source.rows) for source in sources.values()]
        if source_totals and total > max(source_totals) * 1.000001:
            warnings.append(f"{metric} total exceeds every prepared source total; review grouping or joins")


def _number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None
