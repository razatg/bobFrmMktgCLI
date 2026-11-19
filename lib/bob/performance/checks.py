"""Evidence metadata is explicit about what the data can and cannot establish."""
from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path


def evidence_status(path: Path, start: dt.date, end: dt.date, *, on_date: dt.date,
                    maturity_days: int = 3) -> dict:
    return {"from": str(start), "to": str(end), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "extracted_at": dt.datetime.fromtimestamp(path.stat().st_mtime, dt.timezone.utc).isoformat(),
            "conversion_mature": end <= on_date - dt.timedelta(days=maturity_days),
            "maturity_days": maturity_days, "maturity_is_estimate": True,
            "coverage": "exact_period_file"}
