"""Review recorded predictions; temporal association is not a causal verdict."""
from __future__ import annotations

import csv
import datetime as dt
import io
from pathlib import Path

from lib.bob.platform.metrics import derive_metrics, number
from .evidence import preserve, read
from .records import get, update


def verdict(prediction: dict, observed: float | None, *, mature: bool,
            complete: bool, confounders: list[str]) -> str:
    if observed is None or not mature or not complete or confounders:
        return "inconclusive"
    direction = prediction["direction"]
    if direction == "range":
        supported = float(prediction["minimum"]) <= observed <= float(prediction["maximum"])
    elif direction == "higher":
        supported = observed > float(prediction["baseline"])
    else:
        supported = observed < float(prediction["baseline"])
    return "supported" if supported else "contradicted"


def review(root: Path, account: str, decision_id: str, source: str, *,
           on_date: dt.date, maturity_days: int | None = None, confounders: list[str] | None = None) -> dict:
    decision = get(root, account, decision_id)
    execution = decision.get("execution")
    if not execution or not execution.get("executed_at"):
        raise ValueError("review requires the actual execution or recorded hold observation start")
    prediction = decision["prediction"]
    if maturity_days is None:
        maturity_days = int(prediction.get('maturity_days', 3))
    start = dt.date.fromisoformat(execution["executed_at"][:10]) + dt.timedelta(days=1)
    end = start + dt.timedelta(days=prediction["days"] - 1)
    if f"{account}_{start}_{end}" not in Path(source).name:
        raise ValueError("review evidence must cover the exact execution-relative observation window")
    item = preserve(root, account, source, {"review": decision_id, "from": str(start), "to": str(end)})
    rows = list(csv.DictReader(io.StringIO(read(root, account, item["sha256"]).decode())))
    if any(str(row.get("customer_id", account)).replace("-", "") != account for row in rows):
        raise ValueError("review evidence contains another account")
    entity = prediction.get("entity", {})
    selected = [row for row in rows if all(str(row.get(k, "")) == str(v) for k, v in entity.items())]
    keys = ("impressions", "clicks", "cost", "installs", "in_app_conversions")
    totals = {key: sum(number(row.get(key)) for row in selected) for key in keys}
    metric = prediction["metric"]
    value = totals.get(metric) if metric in totals else derive_metrics(totals, decision.get("primary_goal", "in_app_conversions")).get(metric)
    observed = float(value) if value not in (None, "NA", "") and selected else None
    mature = on_date >= end + dt.timedelta(days=max(0, maturity_days))
    notes = confounders or []
    result = {"verdict": verdict(prediction, observed, mature=mature, complete=bool(selected) and execution.get("complete", True), confounders=notes),
              "observed": observed, "from": str(start), "to": str(end), "mature": mature,
              "confounders": notes, "evidence": item,
              "interpretation": "Observation against a prediction; not a causal claim."}
    update(root, account, decision_id, "review", result)
    return result
