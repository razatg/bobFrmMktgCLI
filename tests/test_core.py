#!/usr/bin/env python3
"""Smoke test for the deterministic core of lib/datapull.py.

Pins the highest-value invariants that must never drift silently:
metric formulas, the zero-denominator -> "NA" rule, period-date windows,
and period aggregation. Each assertion references the formula it locks
(see CLAUDE.md -> "Metric formulas" and "Key functions in lib/datapull.py").

Pure stdlib, no external deps, no live Google Ads / GARF calls. Run with:
    ./.venv/bin/python tests/test_core.py        # or
    python -m unittest -v tests.test_core

If one of these assertions fails, either a real regression slipped in, or a
formula/window was changed on purpose -- in which case update the expected
value here deliberately (that is the point of the failure).
"""
import datetime as dt
import os
import sys
import unittest
from pathlib import Path

# Import the module under test without packaging: lib/datapull.py.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import datapull as dp  # noqa: E402


class TestMetricFormulas(unittest.TestCase):
    """dp._derive_metrics — every formula returns a formatted string; CLAUDE.md "Metric formulas"."""

    def base(self):
        # impressions/clicks/cost/installs/in_app_conversions are the summed base metrics.
        return {
            "impressions": 1000.0,
            "clicks": 100.0,
            "cost": 200.0,
            "installs": 50.0,
            "in_app_conversions": 10.0,
        }

    def test_formulas_goal_installs(self):
        # primary_goal == "installs" -> goal_conversions = installs (50)
        m = dp._derive_metrics(self.base(), "installs")
        self.assertEqual(m["cpm"], "200")                       # cost/impr*1000 = 200
        self.assertEqual(m["ctr_percent"], "10")                # clicks/impr*100 = 10
        self.assertEqual(m["cpc"], "2")                         # cost/clicks = 2
        self.assertEqual(m["cti_percent"], "50")                # installs/clicks*100 = 50
        self.assertEqual(m["conversion_rate_percent"], "50")    # goal/clicks*100 = 50
        self.assertEqual(m["cpa"], "4")                         # cost/goal = 200/50 = 4
        self.assertEqual(m["cpi"], "4")                         # cost/installs = 200/50 = 4
        self.assertEqual(m["goal_conversions"], "50")

    def test_goal_switch_to_in_app(self):
        # primary_goal == "in_app_conversions" -> goal_conversions = in_app (10)
        m = dp._derive_metrics(self.base(), "in_app_conversions")
        self.assertEqual(m["goal_conversions"], "10")
        self.assertEqual(m["cpa"], "20")                        # cost/goal = 200/10 = 20
        self.assertEqual(m["conversion_rate_percent"], "10")    # 10/100*100 = 10
        # cpi is always cost/installs regardless of goal
        self.assertEqual(m["cpi"], "4")

    def test_zero_denominator_returns_NA_not_zero(self):
        # CLAUDE.md: "Zero denominators return 'NA', never NaN or 0."
        g = self.base()
        g["impressions"] = 0.0
        m = dp._derive_metrics(g, "installs")
        self.assertEqual(m["cpm"], "NA")
        self.assertEqual(m["ctr_percent"], "NA")

        g = self.base()
        g["clicks"] = 0.0
        m = dp._derive_metrics(g, "installs")
        self.assertEqual(m["cpc"], "NA")
        self.assertEqual(m["cti_percent"], "NA")
        self.assertEqual(m["conversion_rate_percent"], "NA")

        g = self.base()
        g["installs"] = 0.0
        m = dp._derive_metrics(g, "installs")
        self.assertEqual(m["cpi"], "NA")
        self.assertEqual(m["cpa"], "NA")            # goal == installs == 0

        g = self.base()
        g["in_app_conversions"] = 0.0
        m = dp._derive_metrics(g, "in_app_conversions")
        self.assertEqual(m["cpa"], "NA")            # goal == in_app == 0

    def test_reach_optionality(self):
        # CLAUDE.md: reach/frequency stay NA when reach is absent; computed when present.
        m = dp._derive_metrics(self.base(), "installs")
        self.assertEqual(m["reach"], "NA")
        self.assertEqual(m["frequency"], "NA")

        g = self.base()
        g["reach"] = 5000.0
        m = dp._derive_metrics(g, "installs")
        self.assertEqual(m["reach"], "5000")
        self.assertEqual(m["frequency"], "0.2")     # impr/reach = 1000/5000


class TestNumericHelpers(unittest.TestCase):
    def test_number(self):
        self.assertEqual(dp.number(None), 0.0)
        self.assertEqual(dp.number(""), 0.0)
        self.assertEqual(dp.number("NA"), 0.0)
        self.assertEqual(dp.number("NULL"), 0.0)
        self.assertEqual(dp.number("NAN"), 0.0)
        self.assertEqual(dp.number("abc"), 0.0)     # unparseable -> 0.0
        self.assertEqual(dp.number("1,234.5"), 1234.5)  # commas stripped
        self.assertEqual(dp.number("12"), 12.0)

    def test_ratio(self):
        self.assertEqual(dp.ratio(10, 0), "NA")     # zero denominator
        self.assertEqual(dp.ratio(1, 4), "0.25")
        self.assertEqual(dp.ratio(1, 4, 100), "25")  # scale applied

    def test_format_float(self):
        self.assertEqual(dp.format_float(0), "0")
        self.assertEqual(dp.format_float(2.0), "2")          # trailing zeros stripped
        self.assertEqual(dp.format_float(0.2), "0.2")
        self.assertEqual(dp.format_float(100), "100")
        self.assertEqual(dp.format_float(123.456), "123.46")  # abs >= 100 -> 2 dp
        self.assertEqual(dp.format_float(1.23450), "1.2345")  # abs < 100 -> up to 4 dp


class TestPeriodDates(unittest.TestCase):
    """Date windows are frozen via the BOB_TODAY env var that today() honors."""

    def setUp(self):
        self._saved = os.environ.get("BOB_TODAY")
        os.environ["BOB_TODAY"] = "2026-06-15"   # -> yesterday = 2026-06-14

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("BOB_TODAY", None)
        else:
            os.environ["BOB_TODAY"] = self._saved

    def d(self, s):
        return dt.date.fromisoformat(s)

    def test_resolve_period_dates(self):
        self.assertEqual(
            dp.resolve_period_dates("wow"),
            [(self.d("2026-06-08"), self.d("2026-06-14")),
             (self.d("2026-06-01"), self.d("2026-06-07"))],
        )
        self.assertEqual(
            dp.resolve_period_dates("mom"),
            [(self.d("2026-05-16"), self.d("2026-06-14")),
             (self.d("2026-04-16"), self.d("2026-05-15"))],
        )
        self.assertEqual(
            dp.resolve_period_dates("mtd"),
            [(self.d("2026-06-01"), self.d("2026-06-14")),
             (self.d("2026-05-01"), self.d("2026-05-14"))],
        )
        self.assertEqual(
            dp.resolve_period_dates("yesterday_vs_sdlw"),
            [(self.d("2026-06-14"), self.d("2026-06-14")),
             (self.d("2026-06-07"), self.d("2026-06-07"))],
        )

    def test_unknown_period_raises(self):
        with self.assertRaises(SystemExit):
            dp.resolve_period_dates("not_a_period")

    def test_iso_week_to_dates(self):
        # ISO week 24 of 2026 runs Mon 2026-06-08 .. Sun 2026-06-14.
        self.assertEqual(
            dp.iso_week_to_dates(24, 2026),
            (self.d("2026-06-08"), self.d("2026-06-14")),
        )
        # round-trip: a known Monday -> its (year, week) -> same Monday/Sunday
        monday = self.d("2026-06-08")
        cal = monday.isocalendar()
        self.assertEqual(
            dp.iso_week_to_dates(cal.week, cal.year),
            (monday, monday + dt.timedelta(days=6)),
        )

    def test_last_complete_iso_week(self):
        # The week ending Sun 2026-06-14, before reference Mon 2026-06-15.
        self.assertEqual(dp.last_complete_iso_week(self.d("2026-06-15")), (24, 2026))


class TestAggregation(unittest.TestCase):
    """dp._aggregate_period_rows — sum SUM_METRICS by key, recompute derived metrics."""

    def test_rows_with_same_key_are_summed(self):
        rows = [
            {"network": "g", "impressions": "600", "clicks": "60",
             "cost": "120", "installs": "30", "in_app_conversions": "6"},
            {"network": "g", "impressions": "400", "clicks": "40",
             "cost": "80", "installs": "20", "in_app_conversions": "4"},
        ]
        out = dp._aggregate_period_rows(rows, ["network"], "installs")
        self.assertEqual(len(out), 1)
        row = out[0]
        self.assertEqual(row["network"], "g")
        # sums: impr 1000, clicks 100, cost 200, installs 50 -> same as TestMetricFormulas base
        self.assertEqual(row["impressions"], "1000")
        self.assertEqual(row["cost"], "200")
        self.assertEqual(row["cpm"], "200")    # derived from the SUMS, not averaged
        self.assertEqual(row["cpi"], "4")

    def test_distinct_keys_preserved_and_sorted(self):
        rows = [
            {"network": "z", "impressions": "100", "clicks": "10",
             "cost": "10", "installs": "5", "in_app_conversions": "1"},
            {"network": "a", "impressions": "100", "clicks": "10",
             "cost": "10", "installs": "5", "in_app_conversions": "1"},
        ]
        out = dp._aggregate_period_rows(rows, ["network"], "installs")
        self.assertEqual([r["network"] for r in out], ["a", "z"])  # sorted by key


if __name__ == "__main__":
    unittest.main()
