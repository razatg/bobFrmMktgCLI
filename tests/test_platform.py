"""Direct tests for extracted platform primitives and facade compatibility."""

from __future__ import annotations

import contextlib
import datetime as dt
import io
import os
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
import datapull as dp  # noqa: E402
from lib.bob.platform import dates, metrics  # noqa: E402
from lib.bob.platform.errors import die  # noqa: E402


class PlatformCompatibilityTests(unittest.TestCase):
    def test_facade_exports_extracted_primitives(self):
        self.assertIs(dp.resolve_period_dates, dates.resolve_period_dates)
        self.assertIs(dp._derive_metrics, metrics.derive_metrics)
        self.assertIs(dp.number, metrics.number)
        self.assertIs(dp.die, die)

    def test_direct_period_resolution_uses_runtime_date_override(self):
        previous = os.environ.get("BOB_TODAY")
        os.environ["BOB_TODAY"] = "2026-03-01"
        try:
            self.assertEqual(
                dates.resolve_period_dates("mtd"),
                [
                    (dt.date(2026, 2, 1), dt.date(2026, 2, 28)),
                    (dt.date(2026, 1, 1), dt.date(2026, 1, 28)),
                ],
            )
        finally:
            if previous is None:
                os.environ.pop("BOB_TODAY", None)
            else:
                os.environ["BOB_TODAY"] = previous

    def test_metric_derivation_preserves_reach_and_ratio_rules(self):
        result = metrics.derive_metrics(
            {
                "impressions": 1000.0,
                "clicks": 100.0,
                "cost": 200.0,
                "installs": 50.0,
                "in_app_conversions": 10.0,
            },
            "in_app_conversions",
        )
        self.assertEqual(result["cpa"], "20")
        self.assertEqual(result["ctr_percent"], "10")
        self.assertEqual(result["reach"], "NA")

    def test_error_code_and_exit_status_remain_machine_readable(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as raised:
            die("authorization required", code=4, error_code="GOOGLE_AUTH_REQUIRED")
        self.assertEqual(raised.exception.code, 4)
        self.assertEqual(
            stderr.getvalue().splitlines(),
            ["BOB_ERROR_CODE=GOOGLE_AUTH_REQUIRED", "error: authorization required"],
        )


if __name__ == "__main__":
    unittest.main()
