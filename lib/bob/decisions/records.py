"""One small durable journal, scoped to the selected account."""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import hashlib
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path

from .evidence import account_dir, preserve


@contextmanager
def database(root: Path, account: str):
    directory = account_dir(root, account)
    directory.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(directory / "decisions.sqlite", timeout=20)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute('''CREATE TABLE IF NOT EXISTS decisions (
          id TEXT PRIMARY KEY, created_at TEXT NOT NULL, record TEXT NOT NULL)''')
        with connection:
            yield connection
    finally:
        connection.close()


def _prediction(prediction: dict) -> None:
    if prediction.get("direction") not in {"higher", "lower", "range"}:
        raise ValueError("prediction needs higher, lower or range")
    if prediction.get("metric") not in {"cost", "installs", "in_app_conversions", "cpi", "cpa", "ctr_percent", "cpc"}:
        raise ValueError("unsupported prediction metric")
    days = prediction.get("days")
    if not isinstance(days, int) or not 1 <= days <= 90:
        raise ValueError("prediction observation days must be between 1 and 90")
    fields = ("minimum", "maximum") if prediction["direction"] == "range" else ("baseline",)
    if any(not math.isfinite(float(prediction[field])) for field in fields):
        raise ValueError("prediction values must be finite")
    if len(fields) == 2 and float(prediction["minimum"]) > float(prediction["maximum"]):
        raise ValueError("prediction range is reversed")


def record(root: Path, account: str, payload: dict) -> dict:
    if str(payload.get("account", account)).replace("-", "") != account:
        raise ValueError("decision is outside the selected account")
    for field in ("situation", "recommendation", "prediction", "evidence"):
        if not payload.get(field):
            raise ValueError(f"decision requires {field}")
    _prediction(payload["prediction"])
    if not isinstance(payload["evidence"], list):
        raise ValueError("evidence must be a list")
    sources = [preserve(root, account, item["source"], item["operation"])
               for item in payload["evidence"]]
    entities = payload.get("entities") or [str(value) for key, value in payload["prediction"].get("entity", {}).items()
                                           if key in {"campaign_id", "ad_group_id", "asset_id"}]
    instructions = hashlib.sha256()
    repo = Path(__file__).resolve().parents[3]
    for path in [repo/'AGENTS.md', repo/'SOUL.md', *sorted((repo/'.agents/skills').rglob('*.md'))]:
        instructions.update(str(path.relative_to(repo)).encode())
        instructions.update(path.read_bytes())
    decision = dict(payload, account=account, decision_id=uuid.uuid4().hex,
                    created_at=dt.datetime.now(dt.timezone.utc).isoformat(), evidence=sources,
                    entities=entities, execution=None, review=None,
                    model=os.getenv('BOB_AGENT_MODEL') or payload.get('model', 'unspecified'),
                    code_version=sources[0]['code_version'], instructions_version=instructions.hexdigest())
    with database(root, account) as connection:
        connection.execute("INSERT INTO decisions VALUES (?,?,?)",
                           (decision["decision_id"], decision["created_at"], json.dumps(decision, allow_nan=False)))
    return decision


def get(root: Path, account: str, decision_id: str) -> dict:
    with database(root, account) as connection:
        row = connection.execute("SELECT record FROM decisions WHERE id=?", (decision_id,)).fetchone()
    if row is None:
        raise ValueError("decision not found for selected account")
    return json.loads(row[0])


def update(root: Path, account: str, decision_id: str, field: str, value: dict) -> dict:
    if field not in {"execution", "human", "review"}:
        raise ValueError("decision intent and evidence are immutable")
    with database(root, account) as connection:
        row = connection.execute("SELECT record FROM decisions WHERE id=?", (decision_id,)).fetchone()
        if row is None:
            raise ValueError("decision not found for selected account")
        decision = json.loads(row[0])
        if field in {'human', 'review'} and decision.get(field) is not None:
            decision.setdefault(field+'_history', []).append(decision[field])
        decision[field] = value
        if field == 'execution' and value.get('executed_at'):
            executed = dt.date.fromisoformat(value['executed_at'][:10])
            decision['review_due'] = str(executed + dt.timedelta(
                days=decision['prediction']['days'] + max(0, int(decision['prediction'].get('maturity_days', 3)))))
        connection.execute("UPDATE decisions SET record=? WHERE id=?",
                           (json.dumps(decision, allow_nan=False), decision_id))
    return decision


def recent(root: Path, account: str, limit: int = 10, entities: tuple[str, ...] = ()) -> list[dict]:
    with database(root, account) as connection:
        if entities:
            placeholders = ','.join('?' for _ in entities)
            rows = connection.execute(f'''SELECT record FROM decisions WHERE EXISTS (
              SELECT 1 FROM json_each(decisions.record, '$.entities') WHERE value IN ({placeholders}))
              ORDER BY created_at DESC LIMIT ?''', (*entities, max(1, min(limit, 100)))).fetchall()
        else:
            rows = connection.execute("SELECT record FROM decisions ORDER BY created_at DESC LIMIT ?",
                                      (max(1, min(limit, 100)),)).fetchall()
    return [json.loads(row[0]) for row in rows]
