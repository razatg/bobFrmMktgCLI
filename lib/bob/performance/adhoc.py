"""Typed, bounded relational analysis over registered Bob datasets."""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass
from typing import TypeAlias

from lib.bob.platform.metrics import derive_metrics, number


Scalar: TypeAlias = str | float | int | None
Row: TypeAlias = dict[str, Scalar]

MAX_OPERATIONS = 20
MAX_SOURCE_ROWS = 100_000
MAX_RESULT_ROWS = 10_000
MAX_INTERMEDIATE_ROWS = 100_000
MAX_PREVIEW_ROWS = 50
MAX_SECONDS = 60.0

BASE_METRICS = ("impressions", "clicks", "cost", "installs", "in_app_conversions")
DERIVED_METRICS = (
    "goal_conversions", "cpm", "frequency", "ctr_percent", "cpc",
    "cti_percent", "conversion_rate_percent", "cpa", "cpi",
)
ALLOWED_JOIN_KEYS = {
    ("customer_id",),
    ("campaign_id",),
    ("campaign_id", "network"),
    ("ad_group_id",),
    ("ad_group_id", "network"),
    ("asset_id",),
}


@dataclass(frozen=True)
class DatasetSpec:
    name: str
    subdir: str
    dimensions: tuple[str, ...]
    additive_metrics: tuple[str, ...] = BASE_METRICS
    allows_reach: bool = False


@dataclass(frozen=True)
class PreparedDataset:
    handle: str
    spec: DatasetSpec
    start: str
    end: str
    primary_goal: str
    rows: tuple[Row, ...]


@dataclass(frozen=True)
class AnalysisResult:
    handle: str
    analysis_name: str
    method_summary: str
    columns: tuple[str, ...]
    rows: tuple[Row, ...]


DATASETS: dict[str, DatasetSpec] = {
    "account_network_period": DatasetSpec(
        "account_network_period", "account-network",
        ("customer_id", "customer_name", "network"),
    ),
    "campaign_network_period": DatasetSpec(
        "campaign_network_period", "campaign-network",
        ("customer_id", "campaign_id", "campaign_name", "campaign_status", "network"),
    ),
    "campaign_reach_period": DatasetSpec(
        "campaign_reach_period", "campaign-reach",
        ("customer_id", "campaign_id", "campaign_name", "campaign_status"),
        BASE_METRICS + ("reach",), True,
    ),
    "adgroup_network_period": DatasetSpec(
        "adgroup_network_period", "adgroup-network",
        (
            "customer_id", "campaign_id", "campaign_name", "ad_group_id",
            "ad_group_name", "ad_group_status", "network",
        ),
    ),
    "campaign_primary_conversion_period": DatasetSpec(
        "campaign_primary_conversion_period", "campaign-primary-conversion",
        ("customer_id", "campaign_id", "campaign_name", "campaign_status", "network"),
        ("impressions", "clicks", "cost", "primary_conversions"),
    ),
    "adgroup_primary_conversion_period": DatasetSpec(
        "adgroup_primary_conversion_period", "adgroup-primary-conversion",
        (
            "customer_id", "campaign_id", "campaign_name", "ad_group_id",
            "ad_group_name", "ad_group_status", "network",
        ),
        ("impressions", "clicks", "cost", "primary_conversions"),
    ),
    "creative_period": DatasetSpec(
        "creative_period", "creative",
        (
            "customer_id", "campaign_id", "campaign_name", "ad_group_id", "ad_group_name",
            "asset_id", "asset_name", "asset_type", "asset_text", "video_id", "field_type",
            "performance_label",
        ),
    ),
}


class AnalysisError(ValueError):
    """A safe validation error suitable for returning through MCP."""


def catalog() -> dict[str, object]:
    return {
        "datasets": [
            {
                "name": spec.name,
                "dimensions": list(spec.dimensions),
                "additive_metrics": list(spec.additive_metrics),
                "derived_metrics": [
                    metric for metric in DERIVED_METRICS if metric != "frequency" or spec.allows_reach
                ],
                "reach_restriction": (
                    "reach and frequency remain at campaign grain" if spec.allows_reach else "unavailable"
                ),
            }
            for spec in DATASETS.values() if spec.name != "adgroup_network_period"
        ],
        "operations": ["group_sum", "join", "derive_metric", "derive", "filter", "rank", "select"],
        "limits": {
            "operations": MAX_OPERATIONS,
            "source_rows": MAX_SOURCE_ROWS,
            "result_rows": MAX_RESULT_ROWS,
            "preview_rows": MAX_PREVIEW_ROWS,
            "seconds": int(MAX_SECONDS),
        },
    }


def normalize_source_rows(spec: DatasetSpec, rows: list[dict[str, str]], customer_id: str) -> tuple[Row, ...]:
    normalized_customer = customer_id.replace("-", "")
    if len(rows) > MAX_SOURCE_ROWS:
        raise AnalysisError(f"dataset exceeds the {MAX_SOURCE_ROWS:,}-row analysis limit")
    output: list[Row] = []
    for source in rows:
        row_customer = str(source.get("customer_id", "")).replace("-", "")
        if row_customer and row_customer != normalized_customer:
            raise AnalysisError("dataset contains rows outside the selected account")
        row: Row = {dimension: str(source.get(dimension, "")) for dimension in spec.dimensions}
        for metric in spec.additive_metrics:
            row[metric] = number(source.get(metric))
        output.append(row)
    return tuple(output)


def run_analysis(
    analysis_name: str,
    sources: dict[str, PreparedDataset],
    operations: list[dict[str, object]],
    final_table: str,
    result_handle: str,
) -> AnalysisResult:
    name = analysis_name.strip()
    if not name or len(name) > 120:
        raise AnalysisError("analysis_name must contain 1 to 120 characters")
    if not sources:
        raise AnalysisError("at least one prepared source is required")
    if len(operations) > MAX_OPERATIONS:
        raise AnalysisError(f"analysis exceeds the {MAX_OPERATIONS}-operation limit")
    source_rows = sum(len(source.rows) for source in sources.values())
    if source_rows > MAX_SOURCE_ROWS:
        raise AnalysisError(f"sources exceed the {MAX_SOURCE_ROWS:,}-row analysis limit")
    goals = {source.primary_goal for source in sources.values()}
    if len(goals) != 1:
        raise AnalysisError("all sources must use the same selected-account goal")
    tables = {alias: [dict(row) for row in source.rows] for alias, source in sources.items()}
    additive = set().union(*(source.spec.additive_metrics for source in sources.values()))
    started = time.monotonic()
    summaries: list[str] = []
    for operation in operations:
        if time.monotonic() - started > MAX_SECONDS:
            raise AnalysisError("analysis exceeded the 60-second execution limit")
        summary = _execute_operation(tables, operation, additive, next(iter(goals)))
        summaries.append(summary)
        output_name = _required_text(operation, "output")
        if len(tables[output_name]) > MAX_INTERMEDIATE_ROWS:
            raise AnalysisError("an intermediate table exceeded the row limit")
    if final_table not in tables:
        raise AnalysisError(f"unknown final table: {final_table}")
    final_rows = tables[final_table]
    if len(final_rows) > MAX_RESULT_ROWS:
        raise AnalysisError(f"result exceeds the {MAX_RESULT_ROWS:,}-row limit; add a filter or rank limit")
    columns = tuple(final_rows[0].keys()) if final_rows else ()
    return AnalysisResult(
        handle=result_handle,
        analysis_name=name,
        method_summary="; ".join(summaries) or "selected prepared data without transformations",
        columns=columns,
        rows=tuple(final_rows),
    )


def _execute_operation(
    tables: dict[str, list[Row]],
    operation: dict[str, object],
    additive: set[str],
    primary_goal: str,
) -> str:
    kind = _required_text(operation, "type")
    output = _required_text(operation, "output")
    if output in tables:
        raise AnalysisError(f"output table already exists: {output}")
    if kind == "group_sum":
        rows, summary = _group_sum(tables, operation, additive)
    elif kind == "join":
        rows, summary = _join(tables, operation)
    elif kind == "derive_metric":
        rows, summary = _derive_standard_metric(tables, operation, primary_goal)
    elif kind == "derive":
        rows, summary = _derive_expression(tables, operation)
    elif kind == "filter":
        rows, summary = _filter(tables, operation)
    elif kind == "rank":
        rows, summary = _rank(tables, operation)
    elif kind == "select":
        rows, summary = _select(tables, operation)
    else:
        raise AnalysisError(f"unsupported operation: {kind}")
    tables[output] = rows
    return summary


def _input_rows(tables: dict[str, list[Row]], operation: dict[str, object]) -> tuple[str, list[Row]]:
    name = _required_text(operation, "input")
    if name not in tables:
        raise AnalysisError(f"unknown input table: {name}")
    return name, tables[name]


def _group_sum(
    tables: dict[str, list[Row]], operation: dict[str, object], additive: set[str]
) -> tuple[list[Row], str]:
    source_name, rows = _input_rows(tables, operation)
    keys = _text_list(operation, "group_by", allow_empty=True)
    metrics = _text_list(operation, "metrics")
    invalid = [metric for metric in metrics if metric not in additive]
    if invalid:
        raise AnalysisError(f"group_sum accepts additive metrics only: {', '.join(invalid)}")
    if "reach" in metrics and "campaign_id" not in keys:
        raise AnalysisError("reach cannot be summed above campaign grain")
    _require_columns(rows, keys + metrics)
    grouped: dict[tuple[Scalar, ...], Row] = {}
    for row in rows:
        key = tuple(row[column] for column in keys)
        target = grouped.setdefault(key, {column: row[column] for column in keys})
        for metric in metrics:
            target[metric] = number(target.get(metric)) + number(row.get(metric))
    return list(grouped.values()), f"summed {', '.join(metrics)} from {source_name} by {', '.join(keys) or 'all rows'}"


def _join(tables: dict[str, list[Row]], operation: dict[str, object]) -> tuple[list[Row], str]:
    left_name = _required_text(operation, "left")
    right_name = _required_text(operation, "right")
    if left_name not in tables or right_name not in tables:
        raise AnalysisError("join references an unknown input table")
    keys = _text_list(operation, "on")
    if tuple(keys) not in ALLOWED_JOIN_KEYS:
        raise AnalysisError("join keys must use registered stable identifiers and compatible grains")
    how = str(operation.get("how", "inner"))
    if how not in {"inner", "left"}:
        raise AnalysisError("join how must be inner or left")
    left, right = tables[left_name], tables[right_name]
    _require_columns(left, keys)
    _require_columns(right, keys)
    right_index: dict[tuple[Scalar, ...], Row] = {}
    for row in right:
        key = tuple(row[column] for column in keys)
        if key in right_index:
            raise AnalysisError("join keys are not unique on the right table")
        right_index[key] = row
    right_columns = list(right[0]) if right else []
    output: list[Row] = []
    for left_row in left:
        right_row = right_index.get(tuple(left_row[column] for column in keys))
        if right_row is None and how == "inner":
            continue
        merged = dict(left_row)
        for column in right_columns:
            if column in keys:
                continue
            value = right_row.get(column) if right_row else None
            target = column if column not in merged else f"{column}_right"
            if target in merged:
                raise AnalysisError(f"join column collision: {target}")
            merged[target] = value
        output.append(merged)
    return output, f"{how}-joined {left_name} to {right_name} on {', '.join(keys)}"


def _derive_standard_metric(
    tables: dict[str, list[Row]], operation: dict[str, object], primary_goal: str
) -> tuple[list[Row], str]:
    source_name, rows = _input_rows(tables, operation)
    metrics = _text_list(operation, "metrics")
    invalid = [metric for metric in metrics if metric not in DERIVED_METRICS]
    if invalid:
        raise AnalysisError(f"unknown derived metrics: {', '.join(invalid)}")
    if "frequency" in metrics and rows and "reach" not in rows[0]:
        raise AnalysisError("frequency is unavailable without campaign-grain reach")
    _require_columns(rows, list(BASE_METRICS))
    output: list[Row] = []
    for row in rows:
        values = {metric: number(row.get(metric)) for metric in BASE_METRICS}
        if "reach" in row:
            values["reach"] = number(row.get("reach"))
        derived = derive_metrics(values, primary_goal)
        updated = dict(row)
        for metric in metrics:
            value = derived[metric]
            updated[metric] = None if value == "NA" else number(value)
        output.append(updated)
    return output, f"derived {', '.join(metrics)} on {source_name} from additive totals"


def _derive_expression(tables: dict[str, list[Row]], operation: dict[str, object]) -> tuple[list[Row], str]:
    source_name, rows = _input_rows(tables, operation)
    column = _required_text(operation, "column")
    expression = operation.get("expression")
    if not isinstance(expression, dict):
        raise AnalysisError("derive expression must be an object")
    output: list[Row] = []
    for row in rows:
        updated = dict(row)
        updated[column] = _evaluate(expression, row, 0)
        output.append(updated)
    return output, f"derived {column} on {source_name} with safe numeric arithmetic"


def _evaluate(expression: dict[str, object], row: Row, depth: int) -> float | None:
    if depth > 8:
        raise AnalysisError("expression nesting exceeds eight levels")
    if set(expression) == {"column"}:
        column = _required_text(expression, "column")
        if column not in row:
            raise AnalysisError(f"unknown expression column: {column}")
        value = row[column]
        return None if value is None or str(value).upper() == "NA" else number(value)
    if set(expression) == {"constant"}:
        value = expression["constant"]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise AnalysisError("expression constants must be numeric")
        return float(value)
    if set(expression) != {"op", "left", "right"}:
        raise AnalysisError("invalid expression node")
    op = _required_text(expression, "op")
    left_node, right_node = expression["left"], expression["right"]
    if not isinstance(left_node, dict) or not isinstance(right_node, dict):
        raise AnalysisError("expression operands must be objects")
    left, right = _evaluate(left_node, row, depth + 1), _evaluate(right_node, row, depth + 1)
    if left is None or right is None:
        return None
    if op == "add":
        return left + right
    if op == "subtract":
        return left - right
    if op == "multiply":
        return left * right
    if op == "safe_divide":
        return None if right == 0 else left / right
    raise AnalysisError(f"unsupported expression operator: {op}")


def _filter(tables: dict[str, list[Row]], operation: dict[str, object]) -> tuple[list[Row], str]:
    source_name, rows = _input_rows(tables, operation)
    raw_conditions = operation.get("conditions")
    if not isinstance(raw_conditions, list) or not raw_conditions:
        raise AnalysisError("filter conditions must be a non-empty list")
    conditions: list[dict[str, object]] = []
    for condition in raw_conditions:
        if not isinstance(condition, dict):
            raise AnalysisError("each filter condition must be an object")
        conditions.append(condition)
    output = [row for row in rows if all(_matches(row, condition) for condition in conditions)]
    return output, f"filtered {source_name} with {len(conditions)} confirmed condition(s)"


def _matches(row: Row, condition: dict[str, object]) -> bool:
    column = _required_text(condition, "column")
    operator = _required_text(condition, "operator")
    if column not in row:
        raise AnalysisError(f"unknown filter column: {column}")
    actual, expected = row[column], condition.get("value")
    if operator == "in":
        if not isinstance(expected, list):
            raise AnalysisError("the in operator requires a list value")
        return actual in expected
    if operator in {"eq", "ne"}:
        matched = actual == expected or str(actual) == str(expected)
        return matched if operator == "eq" else not matched
    if isinstance(expected, bool) or not isinstance(expected, (int, float)):
        raise AnalysisError(f"{operator} requires a numeric value")
    if actual is None or str(actual).upper() == "NA":
        return False
    left, right = number(actual), float(expected)
    return {
        "gt": left > right,
        "gte": left >= right,
        "lt": left < right,
        "lte": left <= right,
    }.get(operator, False) if operator in {"gt", "gte", "lt", "lte"} else _bad_operator(operator)


def _bad_operator(operator: str) -> bool:
    raise AnalysisError(f"unsupported filter operator: {operator}")


def _rank(tables: dict[str, list[Row]], operation: dict[str, object]) -> tuple[list[Row], str]:
    source_name, rows = _input_rows(tables, operation)
    by = _required_text(operation, "by")
    direction = str(operation.get("direction", "desc"))
    if direction not in {"asc", "desc"}:
        raise AnalysisError("rank direction must be asc or desc")
    partitions = _text_list(operation, "partition_by", allow_empty=True) if "partition_by" in operation else []
    limit = operation.get("limit")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_RESULT_ROWS:
        raise AnalysisError(f"rank limit must be between 1 and {MAX_RESULT_ROWS}")
    _require_columns(rows, [by] + partitions)
    grouped: dict[tuple[Scalar, ...], list[Row]] = defaultdict(list)
    for row in rows:
        grouped[tuple(row[column] for column in partitions)].append(row)
    output: list[Row] = []
    for partition_rows in grouped.values():
        valid = [row for row in partition_rows if row[by] is not None and str(row[by]).upper() != "NA"]
        missing = [row for row in partition_rows if row[by] is None or str(row[by]).upper() == "NA"]
        ordered = sorted(valid, key=lambda row: number(row[by]), reverse=direction == "desc") + missing
        for index, row in enumerate(ordered[:limit], start=1):
            ranked = dict(row)
            ranked["rank"] = index
            output.append(ranked)
    return output, f"ranked {source_name} by {by} {direction} with limit {limit}"


def _select(tables: dict[str, list[Row]], operation: dict[str, object]) -> tuple[list[Row], str]:
    source_name, rows = _input_rows(tables, operation)
    columns = _text_list(operation, "columns")
    _require_columns(rows, columns)
    return [{column: row.get(column) for column in columns} for row in rows], f"selected {len(columns)} columns from {source_name}"


def _required_text(mapping: dict[str, object], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise AnalysisError(f"{key} must be a non-empty string")
    return value.strip()


def _text_list(mapping: dict[str, object], key: str, allow_empty: bool = False) -> list[str]:
    value = mapping.get(key)
    if not isinstance(value, list) or (not value and not allow_empty):
        qualifier = "a list" if allow_empty else "a non-empty list"
        raise AnalysisError(f"{key} must be {qualifier}")
    output: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise AnalysisError(f"{key} entries must be non-empty strings")
        output.append(item.strip())
    if len(output) != len(set(output)):
        raise AnalysisError(f"{key} contains duplicate columns")
    return output


def _require_columns(rows: list[Row], columns: list[str]) -> None:
    if not rows:
        return
    missing = [column for column in columns if column not in rows[0]]
    if missing:
        raise AnalysisError(f"unknown columns: {', '.join(missing)}")
