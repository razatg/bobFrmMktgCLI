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
import argparse
import contextlib
import datetime as dt
import io
import json
import os
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest import mock
from pathlib import Path

# Import the module under test without packaging: lib/datapull.py.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import datapull as dp  # noqa: E402
from lib.bob.performance import fetch as performance_fetch  # noqa: E402


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

    def test_date_aliases_are_normalized(self):
        yesterday = [(self.d("2026-06-14"), self.d("2026-06-14"))]
        last_week = [(self.d("2026-06-08"), self.d("2026-06-14"))]
        self.assertEqual(dp.resolve_period_dates("yesterday"), yesterday)
        self.assertEqual(dp.resolve_period_dates("last-week"), last_week)
        self.assertEqual(dp.resolve_period_dates("last_week"), last_week)
        self.assertEqual(dp.resolve_period_dates("last complete week"), last_week)

    def test_bid_budget_windows_use_partial_current_iso_week(self):
        os.environ["BOB_TODAY"] = "2026-06-18"
        self.assertEqual(
            dp.resolve_period_dates("bid-budget-weeks"),
            [
                (self.d("2026-06-15"), self.d("2026-06-17")),
                (self.d("2026-06-08"), self.d("2026-06-14")),
                (self.d("2026-06-01"), self.d("2026-06-07")),
            ],
        )

    def test_bid_budget_windows_use_last_full_week_on_monday(self):
        self.assertEqual(
            dp.resolve_period_dates("bid_budget_weeks"),
            [
                (self.d("2026-06-08"), self.d("2026-06-14")),
                (self.d("2026-06-01"), self.d("2026-06-07")),
                (self.d("2026-05-25"), self.d("2026-05-31")),
            ],
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


class TestBidBudgetInputSelection(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self._processed_dir = dp.PROCESSED_DIR
        self._raw_dir = dp.RAW_DIR
        self._today = os.environ.get("BOB_TODAY")
        root = Path(self.temp.name)
        dp.PROCESSED_DIR = root / "processed"
        dp.RAW_DIR = root / "raw"
        os.environ["BOB_TODAY"] = "2026-09-10"
        self.addCleanup(self._restore)

    def _restore(self):
        dp.PROCESSED_DIR = self._processed_dir
        dp.RAW_DIR = self._raw_dir
        if self._today is None:
            os.environ.pop("BOB_TODAY", None)
        else:
            os.environ["BOB_TODAY"] = self._today

    def test_exact_partial_week_wins_over_later_starting_stale_file(self):
        trend_dir = dp.account_processed_dir("123-456-7890", "campaign-trend")
        trend_dir.mkdir(parents=True)
        expected = trend_dir / "1234567890_2026-09-07_2026-09-09.csv"
        stale = trend_dir / "1234567890_2026-09-08_2026-09-08.csv"
        expected.write_text("customer_id\n1234567890\n")
        stale.write_text("customer_id\n1234567890\n")

        selected, windows = dp.bid_budget_trend_path("123-456-7890")

        self.assertEqual(selected, expected)
        self.assertEqual(windows[0], (dt.date(2026, 9, 7), dt.date(2026, 9, 9)))

    def test_explicit_stale_trend_is_rejected(self):
        trend_dir = dp.account_processed_dir("1234567890", "campaign-trend")
        trend_dir.mkdir(parents=True)
        stale = trend_dir / "1234567890_2026-09-08_2026-09-08.csv"
        stale.write_text("customer_id\n1234567890\n")

        with self.assertRaises(SystemExit):
            dp.bid_budget_trend_path("1234567890", str(stale))

    def test_trend_rows_require_exact_account_and_week_dates(self):
        windows = dp.bid_budget_week_windows()
        valid = {
            "customer_id": "1234567890",
            "current_iso_week": "37", "prior1_iso_week": "36", "prior2_iso_week": "35",
            "w37_start": "2026-09-07", "w37_end": "2026-09-09",
            "w36_start": "2026-08-31", "w36_end": "2026-09-06",
            "w35_start": "2026-08-24", "w35_end": "2026-08-30",
        }
        dp.validate_bid_budget_trend_rows([valid], "1234567890", windows)
        with self.assertRaises(SystemExit):
            dp.validate_bid_budget_trend_rows([{**valid, "customer_id": "9999999999"}], "1234567890", windows)
        with self.assertRaises(SystemExit):
            dp.validate_bid_budget_trend_rows([{**valid, "w36_end": "2026-09-05"}], "1234567890", windows)

    def test_raw_selection_is_account_scoped(self):
        raw_dir = dp.RAW_DIR / "bid_budget_inputs"
        raw_dir.mkdir(parents=True)
        wanted = raw_dir / "1234567890_2026-09-09_2026-09-09_a.csv"
        foreign = raw_dir / "9999999999_2026-09-09_2026-09-09_z.csv"
        wanted.write_text("customer_id\n1234567890\n")
        foreign.write_text("customer_id\n9999999999\n")
        os.utime(foreign, (wanted.stat().st_mtime + 10, wanted.stat().st_mtime + 10))

        self.assertEqual(dp.newest_raw_for_customer("bid_budget_inputs", "1234567890"), wanted)


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

    def test_creative_content_fields_survive_aggregation(self):
        rows = [{"asset_id": "1", "asset_text": "Ride faster", "video_id": "vid-1",
                 "impressions": "100", "clicks": "10", "cost": "20", "installs": "5",
                 "in_app_conversions": "2"}]
        out = dp._aggregate_period_rows(rows, ["asset_id", "asset_text", "video_id"], "installs")
        self.assertEqual(out[0]["asset_text"], "Ride faster")
        self.assertEqual(out[0]["video_id"], "vid-1")

    def test_creative_queries_select_asset_content(self):
        query_root = Path(__file__).resolve().parent.parent / "garf" / "queries"
        headline = (query_root / "creative_headline_period.sql").read_text()
        description = (query_root / "creative_description_period.sql").read_text()
        video = (query_root / "creative_video_period.sql").read_text()
        self.assertIn("asset.text_asset.text AS asset_text", headline)
        self.assertIn("asset.text_asset.text AS asset_text", description)
        self.assertIn("asset.youtube_video_asset.youtube_video_id AS video_id", video)

    def test_creative_rows_prefer_text_over_stale_blank_duplicate(self):
        rows = [
            {"campaign_id": "c", "ad_group_id": "g", "asset_id": "1", "asset_type": "TEXT", "field_type": "HEADLINE", "asset_text": "", "impressions": "100"},
            {"campaign_id": "c", "ad_group_id": "g", "asset_id": "1", "asset_type": "TEXT", "field_type": "HEADLINE", "asset_text": "Ride faster", "impressions": "100"},
        ]
        out = dp._dedupe_creative_rows(rows)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["asset_text"], "Ride faster")

    def test_compact_comparison_prints_drivers_not_full_rows(self):
        rows = [
            {"campaign_name": "A", "current_goal_conversions": "100", "baseline_goal_conversions": "50",
             "current_cost": "200", "baseline_cost": "100"},
            {"campaign_name": "B", "current_goal_conversions": "10", "baseline_goal_conversions": "9",
             "current_cost": "20", "baseline_cost": "18"},
        ]
        with contextlib.redirect_stdout(io.StringIO()) as output:
            dp._print_compact_comparison(
                "campaign_network_period", ["campaign_name"], rows,
                {"goal_conversions": "110", "cost": "220"},
                {"goal_conversions": "59", "cost": "118"},
                "goal_conversions", "₹", "current", "baseline", "", 1, None, None,
            )
        text = output.getvalue()
        self.assertIn("Top 1 drivers:", text)
        self.assertIn("A", text)
        self.assertNotIn("B", text)

    def test_parser_exposes_compact_output_controls(self):
        parser = dp.build_parser()
        args = parser.parse_args(["compare-weeks", "--summary", "--top", "3"])
        self.assertTrue(args.summary)
        self.assertEqual(args.top, 3)
        args = parser.parse_args(["fetch", "--query", "campaign_daily", "--quiet"])
        self.assertTrue(args.quiet)
        args = parser.parse_args(["data-manifest", "--account", "123-456-7890"])
        self.assertEqual(args.account, "123-456-7890")


class TestCampaignWeeklyTrendSelection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._raw_dir = dp.RAW_DIR
        self._processed_dir = dp.PROCESSED_DIR
        self._today = os.environ.get("BOB_TODAY")
        root = Path(self.tmp.name)
        dp.RAW_DIR = root / "raw"
        dp.PROCESSED_DIR = root / "processed"
        os.environ["BOB_TODAY"] = "2026-06-18"
        self.addCleanup(self._restore)

    def _restore(self):
        dp.RAW_DIR = self._raw_dir
        dp.PROCESSED_DIR = self._processed_dir
        if self._today is None:
            os.environ.pop("BOB_TODAY", None)
        else:
            os.environ["BOB_TODAY"] = self._today

    def _write_period(self, customer, start, end, run_id, impressions, row_customer=None):
        path = dp.RAW_DIR / "campaign_network_period" / f"{customer}_{start}_{end}_{run_id}.csv"
        dp.write_csv(path, [{
            "customer_id": row_customer or customer,
            "campaign_id": "campaign-1",
            "campaign_name": "Campaign One",
            "campaign_status": "ENABLED",
            "network": "DISPLAY",
            "impressions": str(impressions),
            "clicks": "20",
            "cost": "100",
            "installs": "20",
            "in_app_conversions": "4",
        }], [
            "customer_id", "campaign_id", "campaign_name", "campaign_status", "network",
        ] + dp.SUM_METRICS)
        return path

    def _args(self, customer, output):
        return argparse.Namespace(source=None, customer=customer, output=str(output))

    def test_uses_exact_customer_windows_and_newest_duplicate(self):
        customer = "1234567890"
        self._write_period(customer, "2026-06-15", "2026-06-17", "a-old", 111)
        self._write_period(customer, "2026-06-15", "2026-06-17", "z-new", 222)
        self._write_period(customer, "2026-06-08", "2026-06-14", "run", 100)
        self._write_period(customer, "2026-06-01", "2026-06-07", "run", 90)
        self._write_period(customer, "2026-06-14", "2026-06-17", "newer-overlap", 999)
        self._write_period("9998887777", "2026-06-15", "2026-06-17", "foreign", 999)

        output = Path(self.tmp.name) / "trend.csv"
        dp._agg_campaign_weekly_trend(
            self._args("123-456-7890", output),
            {"google_ads_customer_id": customer},
            "installs",
        )

        row = dp.read_csv(output)[0]
        self.assertEqual(row["customer_id"], customer)
        self.assertEqual(row["current_iso_week"], "25")
        self.assertEqual(row["w25_start"], "2026-06-15")
        self.assertEqual(row["w25_end"], "2026-06-17")
        self.assertEqual(row["w25_impressions"], "222")
        self.assertEqual(row["w24_impressions"], "100")
        self.assertEqual(row["w23_impressions"], "90")

    def test_missing_exact_window_is_not_replaced_by_overlap(self):
        customer = "1234567890"
        self._write_period(customer, "2026-06-15", "2026-06-17", "run", 100)
        self._write_period(customer, "2026-06-07", "2026-06-14", "overlap", 100)
        self._write_period(customer, "2026-06-01", "2026-06-07", "run", 100)

        with self.assertRaises(SystemExit):
            dp._agg_campaign_weekly_trend(
                self._args(customer, Path(self.tmp.name) / "trend.csv"),
                {"google_ads_customer_id": customer},
                "installs",
            )

    def test_matching_file_rejects_foreign_account_rows(self):
        customer = "1234567890"
        self._write_period(customer, "2026-06-15", "2026-06-17", "run", 100)
        self._write_period(
            customer, "2026-06-08", "2026-06-14", "run", 100,
            row_customer="9998887777",
        )
        self._write_period(customer, "2026-06-01", "2026-06-07", "run", 100)

        with self.assertRaises(SystemExit):
            dp._agg_campaign_weekly_trend(
                self._args(customer, Path(self.tmp.name) / "trend.csv"),
                {"google_ads_customer_id": customer},
                "installs",
            )


class TestProcessedPeriodMaterialization(unittest.TestCase):
    """Exact period slices should be materialized from raw files before comparisons fail."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._raw_dir = dp.RAW_DIR
        self._processed_dir = dp.PROCESSED_DIR
        root = Path(self.tmp.name)
        dp.RAW_DIR = root / "raw"
        dp.PROCESSED_DIR = root / "processed"
        self.addCleanup(self._restore_dirs)

    def _restore_dirs(self):
        dp.RAW_DIR = self._raw_dir
        dp.PROCESSED_DIR = self._processed_dir

    def d(self, s):
        return dt.date.fromisoformat(s)

    def test_exact_raw_window_is_aggregated_when_processed_file_is_missing(self):
        customer = "9998887777"
        raw_dir = dp.RAW_DIR / "account_network_period"
        raw_path = raw_dir / f"{customer}_2026-05-01_2026-05-24_test.csv"
        dp.write_csv(raw_path, [{
            "customer_id": customer,
            "customer_name": "Test Account",
            "network": "SEARCH",
            "impressions": "1000",
            "clicks": "100",
            "cost": "200",
            "installs": "50",
            "in_app_conversions": "10",
        }], ["customer_id", "customer_name", "network"] + dp.SUM_METRICS)

        processed = dp.ensure_processed_file_for_period(
            "account_network_period",
            "account-network",
            self.d("2026-05-01"),
            self.d("2026-05-24"),
            customer,
            "installs",
        )

        self.assertIsNotNone(processed)
        self.assertEqual(processed.name, f"{customer}_2026-05-01_2026-05-24.csv")
        rows = dp.read_csv(processed)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["network"], "Google Search")
        self.assertEqual(rows[0]["cost"], "200")

    def test_granular_chunks_are_combined_before_aggregation(self):
        customer = "9998887777"
        raw_dir = dp.RAW_DIR / "campaign_network_period"
        columns = [
            "customer_id", "campaign_id", "campaign_name", "campaign_status", "network",
        ] + dp.SUM_METRICS
        for start, end, impressions in (
            ("2026-05-01", "2026-05-07", "100"),
            ("2026-05-08", "2026-05-14", "250"),
        ):
            dp.write_csv(raw_dir / f"{customer}_{start}_{end}_test.csv", [{
                "customer_id": customer, "campaign_id": "camp-1", "campaign_name": "Campaign",
                "campaign_status": "ENABLED", "network": "SEARCH", "impressions": impressions,
                "clicks": "10", "cost": "20", "installs": "5", "in_app_conversions": "1",
            }], columns)

        processed = dp.ensure_processed_file_for_period(
            "campaign_network_period", "campaign-network", self.d("2026-05-01"),
            self.d("2026-05-14"), customer, "installs",
        )

        self.assertIsNotNone(processed)
        rows = dp.read_csv(processed)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["impressions"], "350")
        self.assertEqual(rows[0]["clicks"], "20")
        self.assertEqual(rows[0]["cpi"], "4")

    def test_compare_months_missing_guidance_uses_exact_mtd_windows(self):
        saved_today = os.environ.get("BOB_TODAY")
        saved_load_profile = dp.load_profile
        os.environ["BOB_TODAY"] = "2026-06-25"
        dp.load_profile = lambda required=False: {
            "google_ads_customer_id": "9998887777",
            "primary_goal": "installs",
            "currency": "INR",
        }
        self.addCleanup(lambda: setattr(dp, "load_profile", saved_load_profile))
        if saved_today is None:
            self.addCleanup(lambda: os.environ.pop("BOB_TODAY", None))
        else:
            self.addCleanup(lambda: os.environ.__setitem__("BOB_TODAY", saved_today))

        args = argparse.Namespace(
            month=6,
            vs=5,
            year=2026,
            full=False,
            grain="account",
            name_contains=None,
            output=None,
            output_account=None,
            goal=None,
            all_metrics=False,
        )
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            dp.compare_months(args)
        text = out.getvalue()
        self.assertIn("Jun (2026-06-01–2026-06-24)", text)
        self.assertIn("May (2026-05-01–2026-05-24)", text)
        self.assertIn("aggregate --grain account_network_period --from 2026-06-01 --to 2026-06-24", text)
        self.assertIn("aggregate --grain account_network_period --from 2026-05-01 --to 2026-05-24", text)

    def _campaign_network_rows(self, customer):
        return (
            [{
                "customer_id": customer,
                "campaign_id": "1",
                "campaign_name": "Brand Stable",
                "campaign_status": "ENABLED",
                "network": "SEARCH",
                "impressions": "1000",
                "clicks": "100",
                "cost": "200",
                "installs": "50",
                "in_app_conversions": "10",
            }, {
                "customer_id": customer,
                "campaign_id": "1",
                "campaign_name": "Brand Stable",
                "campaign_status": "ENABLED",
                "network": "CONTENT",
                "impressions": "500",
                "clicks": "50",
                "cost": "100",
                "installs": "25",
                "in_app_conversions": "5",
            }],
            [{
                "customer_id": customer,
                "campaign_id": "1",
                "campaign_name": "Brand Stable",
                "campaign_status": "ENABLED",
                "network": "SEARCH",
                "impressions": "800",
                "clicks": "80",
                "cost": "160",
                "installs": "40",
                "in_app_conversions": "8",
            }, {
                "customer_id": customer,
                "campaign_id": "1",
                "campaign_name": "Brand Stable",
                "campaign_status": "ENABLED",
                "network": "CONTENT",
                "impressions": "250",
                "clicks": "25",
                "cost": "50",
                "installs": "10",
                "in_app_conversions": "2",
            }],
        )

    def _write_campaign_network_pair(self):
        customer = "9998887777"
        proc_dir = dp.PROCESSED_DIR / customer / "campaign-network"
        cur_path = proc_dir / f"{customer}_2026-06-01_2026-06-07.csv"
        base_path = proc_dir / f"{customer}_2026-05-25_2026-05-31.csv"
        cur_rows, base_rows = self._campaign_network_rows(customer)
        dp.write_csv(cur_path, cur_rows, dp.CAMPAIGN_NETWORK_PERIOD_COLUMNS)
        dp.write_csv(base_path, base_rows, dp.CAMPAIGN_NETWORK_PERIOD_COLUMNS)
        return customer, cur_path, base_path

    def _write_campaign_reach_pair(self, customer):
        proc_dir = dp.PROCESSED_DIR / customer / "campaign-reach"
        cur_path = proc_dir / f"{customer}_2026-06-01_2026-06-07.csv"
        base_path = proc_dir / f"{customer}_2026-05-25_2026-05-31.csv"
        cur_rows = [{
            "customer_id": customer,
            "campaign_id": "1",
            "campaign_name": "Brand Stable",
            "campaign_status": "ENABLED",
            "reach": "500",
            "impressions": "1500",
            "clicks": "150",
            "cost": "300",
            "installs": "75",
            "in_app_conversions": "15",
        }]
        base_rows = [{
            "customer_id": customer,
            "campaign_id": "1",
            "campaign_name": "Brand Stable",
            "campaign_status": "ENABLED",
            "reach": "420",
            "impressions": "1050",
            "clicks": "105",
            "cost": "210",
            "installs": "50",
            "in_app_conversions": "10",
        }]
        dp.write_csv(cur_path, cur_rows, dp.CAMPAIGN_REACH_PERIOD_COLUMNS)
        dp.write_csv(base_path, base_rows, dp.CAMPAIGN_REACH_PERIOD_COLUMNS)
        return cur_path, base_path

    def _write_adgroup_network_pair(self):
        customer = "9998887777"
        proc_dir = dp.PROCESSED_DIR / customer / "adgroup-network"
        cur_path = proc_dir / f"{customer}_2026-06-01_2026-06-07.csv"
        base_path = proc_dir / f"{customer}_2026-05-25_2026-05-31.csv"
        cur_rows = [{
            "customer_id": customer,
            "campaign_id": "1",
            "campaign_name": "Brand Stable",
            "ad_group_id": "11",
            "ad_group_name": "Brand Stable AG",
            "ad_group_status": "ENABLED",
            "network": "SEARCH",
            "impressions": "100",
            "clicks": "10",
            "cost": "20",
            "installs": "5",
            "in_app_conversions": "1",
        }]
        base_rows = [{
            "customer_id": customer,
            "campaign_id": "1",
            "campaign_name": "Brand Stable",
            "ad_group_id": "11",
            "ad_group_name": "Brand Stable AG",
            "ad_group_status": "ENABLED",
            "network": "SEARCH",
            "impressions": "80",
            "clicks": "8",
            "cost": "16",
            "installs": "4",
            "in_app_conversions": "1",
        }]
        dp.write_csv(cur_path, cur_rows, dp.ADGROUP_NETWORK_PERIOD_COLUMNS)
        dp.write_csv(base_path, base_rows, dp.ADGROUP_NETWORK_PERIOD_COLUMNS)
        return customer, cur_path, base_path

    def _slice_args(self, cur_path, base_path, **overrides):
        args = {
            "name_contains": "Brand",
            "period": "yesterday_vs_sdlw",
            "current": str(cur_path),
            "baseline": str(base_path),
            "output": None,
            "output_network": None,
            "goal": "installs",
            "all_metrics": False,
            "reach_metrics": False,
            "network_split": False,
        }
        args.update(overrides)
        return argparse.Namespace(**args)

    def test_slice_campaigns_can_show_named_segment_network_split(self):
        customer, cur_path, base_path = self._write_campaign_network_pair()
        saved_load_profile = dp.load_profile
        dp.load_profile = lambda required=False: {
            "google_ads_customer_id": customer,
            "primary_goal": "installs",
            "currency": "INR",
        }
        self.addCleanup(lambda: setattr(dp, "load_profile", saved_load_profile))

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            dp.slice_campaigns(self._slice_args(cur_path, base_path, network_split=True))
        text = out.getvalue()
        self.assertIn("Campaign × Network", text)
        self.assertIn("Segment × Network", text)
        self.assertIn("Brand Stable", text)
        self.assertIn("Google Search", text)
        self.assertIn("Google Display Network", text)

    def test_slice_campaigns_network_split_all_metrics_shows_additive_metrics(self):
        customer, cur_path, base_path = self._write_campaign_network_pair()
        saved_load_profile = dp.load_profile
        dp.load_profile = lambda required=False: {
            "google_ads_customer_id": customer,
            "primary_goal": "installs",
            "currency": "INR",
        }
        self.addCleanup(lambda: setattr(dp, "load_profile", saved_load_profile))

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            dp.slice_campaigns(self._slice_args(
                cur_path,
                base_path,
                all_metrics=True,
                network_split=True,
            ))
        text = out.getvalue()
        self.assertIn("Campaign × Network — all metrics", text)
        self.assertIn("Campaign: Brand Stable | Network: Google Search", text)
        self.assertIn("CTR %", text)
        self.assertNotIn("Users", text)
        self.assertNotIn("Frequency", text)

    def test_all_metrics_does_not_warn_or_show_reach_without_opt_in(self):
        customer, cur_path, base_path = self._write_campaign_network_pair()
        saved_load_profile = dp.load_profile
        dp.load_profile = lambda required=False: {
            "google_ads_customer_id": customer,
            "primary_goal": "installs",
            "currency": "INR",
        }
        self.addCleanup(lambda: setattr(dp, "load_profile", saved_load_profile))

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            dp.slice_campaigns(self._slice_args(cur_path, base_path, all_metrics=True))
        text = out.getvalue()
        self.assertIn("Campaign Segment Summary", text)
        self.assertIn("Campaign: Brand Stable", text)
        self.assertIn("Impressions", text)
        self.assertIn("CTR %", text)
        self.assertNotIn("campaign_reach_period", text)



    def test_reach_metrics_only_show_on_individual_campaign_tables(self):
        customer, cur_path, base_path = self._write_campaign_network_pair()
        self._write_campaign_reach_pair(customer)
        saved_load_profile = dp.load_profile
        dp.load_profile = lambda required=False: {
            "google_ads_customer_id": customer,
            "primary_goal": "installs",
            "currency": "INR",
        }
        self.addCleanup(lambda: setattr(dp, "load_profile", saved_load_profile))

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            dp.slice_campaigns(self._slice_args(
                cur_path,
                base_path,
                all_metrics=True,
                reach_metrics=True,
            ))
        text = out.getvalue()
        summary = text.split("Campaign: Brand Stable", 1)[0]
        campaign = text.split("Campaign: Brand Stable", 1)[1]
        self.assertNotIn("Users", summary)
        self.assertNotIn("Frequency", summary)
        self.assertIn("Users", campaign)
        self.assertIn("Frequency", campaign)
        self.assertIn("500", campaign)

    def test_slice_campaigns_output_csv_accepts_customer_id_rows(self):
        customer, cur_path, base_path = self._write_campaign_network_pair()
        saved_load_profile = dp.load_profile
        dp.load_profile = lambda required=False: {
            "google_ads_customer_id": customer,
            "primary_goal": "installs",
            "currency": "INR",
        }
        self.addCleanup(lambda: setattr(dp, "load_profile", saved_load_profile))

        output_path = Path(self.tmp.name) / "segment.csv"
        with contextlib.redirect_stdout(io.StringIO()):
            dp.slice_campaigns(self._slice_args(cur_path, base_path, output=str(output_path)))
        rows = dp.read_csv(output_path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["customer_id"], customer)
        self.assertEqual(rows[0]["campaign_name"], "Brand Stable")
        self.assertEqual(rows[0]["current_cost"], "300")

    def test_slice_campaigns_output_csv_includes_campaign_reach_only_when_available(self):
        customer, cur_path, base_path = self._write_campaign_network_pair()
        self._write_campaign_reach_pair(customer)
        saved_load_profile = dp.load_profile
        dp.load_profile = lambda required=False: {
            "google_ads_customer_id": customer,
            "primary_goal": "installs",
            "currency": "INR",
        }
        self.addCleanup(lambda: setattr(dp, "load_profile", saved_load_profile))

        output_path = Path(self.tmp.name) / "segment-reach.csv"
        with contextlib.redirect_stdout(io.StringIO()):
            dp.slice_campaigns(self._slice_args(
                cur_path,
                base_path,
                all_metrics=True,
                reach_metrics=True,
                output=str(output_path),
            ))
        rows = dp.read_csv(output_path)
        self.assertEqual(rows[0]["current_reach"], "500")
        self.assertEqual(rows[0]["baseline_reach"], "420")
        self.assertEqual(rows[0]["current_frequency"], "3")

    def test_slice_campaigns_output_network_preserves_campaign_by_network_rows(self):
        customer, cur_path, base_path = self._write_campaign_network_pair()
        saved_load_profile = dp.load_profile
        dp.load_profile = lambda required=False: {
            "google_ads_customer_id": customer,
            "primary_goal": "installs",
            "currency": "INR",
        }
        self.addCleanup(lambda: setattr(dp, "load_profile", saved_load_profile))

        output_path = Path(self.tmp.name) / "segment-network.csv"
        with contextlib.redirect_stdout(io.StringIO()):
            dp.slice_campaigns(self._slice_args(
                cur_path,
                base_path,
                network_split=True,
                output_network=str(output_path),
            ))
        rows = dp.read_csv(output_path)
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["campaign_name"] for r in rows}, {"Brand Stable"})
        self.assertEqual({r["network"] for r in rows}, {"Google Search", "Google Display Network"})
        search = next(r for r in rows if r["network"] == "Google Search")
        self.assertEqual(search["current_installs"], "50")
        self.assertEqual(search["baseline_installs"], "40")

    def test_compare_weeks_campaign_network_split_output_preserves_network_rows(self):
        customer, _, _ = self._write_campaign_network_pair()
        saved_load_profile = dp.load_profile
        dp.load_profile = lambda required=False: {
            "google_ads_customer_id": customer,
            "primary_goal": "installs",
            "currency": "INR",
        }
        self.addCleanup(lambda: setattr(dp, "load_profile", saved_load_profile))

        output_path = Path(self.tmp.name) / "compare-week-campaign-network.csv"
        args = argparse.Namespace(
            week=23,
            vs=22,
            year=2026,
            grain="campaign",
            name_contains="Brand",
            output=str(output_path),
            output_account=None,
            goal="installs",
            all_metrics=False,
            reach_metrics=False,
            network_split=True,
        )
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            dp.compare_weeks(args)
        text = out.getvalue()
        self.assertIn("Campaigns (2 campaign-network rows across 1 campaigns matching 'brand')", text)
        self.assertIn("Google Search", text)
        rows = dp.read_csv(output_path)
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["network"] for r in rows}, {"Google Search", "Google Display Network"})

    def test_compare_weeks_adgroup_grain_outputs_adgroup_network_rows(self):
        customer, _, _ = self._write_adgroup_network_pair()
        saved_load_profile = dp.load_profile
        dp.load_profile = lambda required=False: {
            "google_ads_customer_id": customer,
            "primary_goal": "installs",
            "currency": "INR",
        }
        self.addCleanup(lambda: setattr(dp, "load_profile", saved_load_profile))

        output_path = Path(self.tmp.name) / "compare-week-adgroup-network.csv"
        args = argparse.Namespace(
            week=23,
            vs=22,
            year=2026,
            grain="adgroup",
            name_contains="Brand",
            output=str(output_path),
            output_account=None,
            goal="installs",
            all_metrics=True,
            reach_metrics=False,
            network_split=False,
        )
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            dp.compare_weeks(args)
        text = out.getvalue()
        self.assertIn("Ad Group × Network", text)
        self.assertIn("Brand Stable AG", text)
        rows = dp.read_csv(output_path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ad_group_name"], "Brand Stable AG")
        self.assertEqual(rows[0]["network"], "Google Search")


class TestNormalizeCustomerId(unittest.TestCase):
    """dp._normalize_customer_id — 10 digits reformat to DDD-DDD-DDDD; else stripped passthrough."""

    def test_reformats_ten_digits(self):
        self.assertEqual(dp._normalize_customer_id("9998887777"), "999-888-7777")
        self.assertEqual(dp._normalize_customer_id("999 888 7777"), "999-888-7777")
        self.assertEqual(dp._normalize_customer_id("999-888-7777"), "999-888-7777")

    def test_passthrough_when_not_ten_digits(self):
        self.assertEqual(dp._normalize_customer_id("  abc  "), "abc")
        self.assertEqual(dp._normalize_customer_id("12345"), "12345")


class TestOnboardAnswers(unittest.TestCase):
    """dp._onboard_from_answers — non-interactive onboarding validation (dry-run, no writes).

    Called with explicit `existing` so it never touches the real account registry, and
    dry_run=True so it only validates + prints (no files written, no setup run).
    """

    def _complete_answers(self, **overrides):
        answers = {
            "customer_id": "999-888-7777",
            "account_name": "Test App",
            "campaign_type": "app",
            "primary_goal": "installs",
            "currency": "INR",
            "mcc_id": "skip",
            "developer_token": "test-token",
            "oauth_client_json_path": "skip",
            "cac_ceiling": 200,
            "bid_budget_change_pct": 10,
            "bid_budget_cooldown_days": 14,
        }
        answers.update(overrides)
        return answers

    def _dry_run(self, answers_dict, existing=None):
        args = argparse.Namespace(answers=json.dumps(answers_dict), dry_run=True)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            dp._onboard_from_answers(args, existing or [])
        return out.getvalue()

    def _expect_die(self, answers, existing=None):
        # answers may be a dict or a raw (possibly malformed) string
        raw = answers if isinstance(answers, str) else json.dumps(answers)
        args = argparse.Namespace(answers=raw, dry_run=True)
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit):
            dp._onboard_from_answers(args, existing or [])
        return err.getvalue()

    def test_valid_dry_run_normalizes_input(self):
        # fuzzy input ("999 888 7777", "App", "inr") is normalized in the summary
        out = self._dry_run(self._complete_answers(
            customer_id="999 888 7777",
            campaign_type="App",
            currency="inr",
        ))
        self.assertIn("999-888-7777", out)   # reformatted
        self.assertIn("INR", out)            # upper-cased
        self.assertIn("App Campaigns", out)  # enum resolved to display label
        self.assertIn("dry run", out.lower())

    def test_incomplete_agent_answers_are_rejected(self):
        msg = self._expect_die({
            "customer_id": "999-888-7777",
            "account_name": "Test App",
            "campaign_type": "app",
            "primary_goal": "installs",
            "currency": "INR",
            "developer_token": "test-token",
        })
        self.assertIn("incomplete", msg)
        self.assertIn("mcc_id", msg)
        self.assertIn("cac_ceiling", msg)
        self.assertIn("bid_budget_change_pct", msg)
        self.assertIn("bid_budget_cooldown_days", msg)

    def test_mcc_name_required_when_mcc_id_is_supplied(self):
        msg = self._expect_die(self._complete_answers(mcc_id="111-222-3333"))
        self.assertIn("mcc_name", msg)

    def test_invalid_reports_all_problems_at_once(self):
        msg = self._expect_die(self._complete_answers(
            customer_id="",
            campaign_type="banana",
            currency="rupees",
        ))
        self.assertIn("customer_id", msg)    # missing required field
        self.assertIn("campaign_type", msg)  # bad enum
        self.assertIn("currency", msg)       # bad currency — all three in one message

    def test_malformed_json_raises(self):
        self._expect_die("{not valid json")

    def test_already_registered_rejected(self):
        msg = self._expect_die(
            self._complete_answers(),
            existing=[{"google_ads_customer_id": "999-888-7777"}],
        )
        self.assertIn("already registered", msg)

    # --- developer-token completeness gate ---

    def test_dry_run_warns_when_token_missing(self):
        out = self._dry_run(self._complete_answers(developer_token=""))
        self.assertIn("No developer token", out)  # loud warning, but dry-run still passes

    def test_bare_onboard_prints_guidance_and_does_nothing(self):
        # No --answers and no --interactive → guidance only, no prompts, no setup side effects.
        args = argparse.Namespace(answers=None, interactive=False)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            dp.onboard(args)
        text = out.getvalue()
        self.assertIn("--answers", text)
        self.assertIn("--interactive", text)

    def test_real_save_without_token_is_blocked(self):
        # dry_run=False + no token + no skip → die BEFORE _finalize_onboard, so nothing is written.
        args = argparse.Namespace(
            answers=json.dumps({
                "customer_id": "999-888-7777",
                "account_name": "Test App",
                "campaign_type": "app",
                "primary_goal": "installs",
                "currency": "INR",
                "mcc_id": "skip",
                "developer_token": "",
                "oauth_client_json_path": "skip",
                "cac_ceiling": 200,
                "bid_budget_change_pct": 10,
                "bid_budget_cooldown_days": 14,
            }),
            dry_run=False,
        )
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit):
                dp._onboard_from_answers(args, [])
        self.assertIn("developer token", err.getvalue().lower())


class TestHostedWritePermissions(unittest.TestCase):
    def test_missing_runtime_credentials_emit_machine_readable_auth_code(self):
        err = io.StringIO()
        with mock.patch.dict(os.environ, {}, clear=True), contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit):
                dp._runtime_write_config_path()
        self.assertIn("BOB_ERROR_CODE=GOOGLE_AUTH_REQUIRED", err.getvalue())

    def test_read_users_are_blocked_from_mutations(self):
        err = io.StringIO()
        with mock.patch.dict(os.environ, {"BOB_ACCOUNT_PERMISSION": "read"}, clear=False), contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit):
                dp._require_write_permission()
        self.assertNotIn("GOOGLE_AUTH_REQUIRED", err.getvalue())

    def test_read_write_users_can_reach_mutation_gate(self):
        with mock.patch.dict(os.environ, {"BOB_ACCOUNT_PERMISSION": "read_write"}, clear=False):
            dp._require_write_permission()


class TestCreativeCopyApply(unittest.TestCase):
    class RepeatedAssets(list):
        """A protobuf-like repeated field that intentionally has no add()."""

    class MaskTarget:
        def __init__(self):
            self.paths = []

        def CopyFrom(self, mask):
            self.paths = list(mask.paths)

    class FakeGoogleAdsFailure:
        def __init__(self, errors=None):
            self.errors = errors or []

        @classmethod
        def deserialize(cls, value):
            return value

    class FakeGoogleAdsService:
        def __init__(self, rows, fail_validation=False, fail_actual=False,
                     validation_error_indexes=None, actual_error_indexes=None):
            self.rows = rows
            self.queries = []
            self.mutate_calls = []
            self.fail_validation = fail_validation
            self.fail_actual = fail_actual
            self.validation_error_indexes = set(validation_error_indexes or [])
            self.actual_error_indexes = set(actual_error_indexes or [])

        def search(self, customer_id, query):
            self.queries.append(query)
            return self.rows

        def mutate(self, *, request):
            self.mutate_calls.append(request)
            if self.fail_validation and request.validate_only:
                raise RuntimeError("validation rejected")
            if self.fail_actual and not request.validate_only:
                raise RuntimeError("mutation response unavailable")
            indexes = self.validation_error_indexes if request.validate_only else self.actual_error_indexes
            errors = [types.SimpleNamespace(
                message=f"operation {index} rejected",
                error_code="test_error: REJECTED",
                location=types.SimpleNamespace(field_path_elements=[
                    types.SimpleNamespace(field_name="mutate_operations", index=index)
                ]),
            ) for index in sorted(indexes)]
            failure = TestCreativeCopyApply.FakeGoogleAdsFailure(errors)
            status = types.SimpleNamespace(
                code=3 if errors else 0,
                details=[types.SimpleNamespace(value=failure)] if errors else [],
            )
            return types.SimpleNamespace(mutate_operation_responses=[], partial_failure_error=status)

    class FakeClient:
        def __init__(self, rows, fail_validation=False, fail_actual=False,
                     validation_error_indexes=None, actual_error_indexes=None):
            self.google_ads_service = TestCreativeCopyApply.FakeGoogleAdsService(
                rows, fail_validation=fail_validation, fail_actual=fail_actual,
                validation_error_indexes=validation_error_indexes,
                actual_error_indexes=actual_error_indexes,
            )

        def get_service(self, name):
            if name == "GoogleAdsService":
                return self.google_ads_service
            if name == "AdService":
                return types.SimpleNamespace(
                    ad_path=lambda customer_id, ad_id: f"customers/{customer_id}/ads/{ad_id}"
                )
            raise AssertionError(f"unexpected service {name}")

        def get_type(self, name):
            if name == "AdTextAsset":
                return types.SimpleNamespace(text="")
            if name == "AdOperation":
                app_ad = types.SimpleNamespace(
                    headlines=TestCreativeCopyApply.RepeatedAssets(),
                    descriptions=TestCreativeCopyApply.RepeatedAssets(),
                )
                update = types.SimpleNamespace(resource_name="", app_ad=app_ad)
                return types.SimpleNamespace(update=update, update_mask=TestCreativeCopyApply.MaskTarget())
            if name == "MutateOperation":
                return types.SimpleNamespace(ad_operation=None)
            if name == "MutateGoogleAdsRequest":
                return types.SimpleNamespace(
                    customer_id="", mutate_operations=TestCreativeCopyApply.RepeatedAssets(),
                    partial_failure=None, validate_only=None,
                )
            if name == "GoogleAdsFailure":
                return TestCreativeCopyApply.FakeGoogleAdsFailure()
            raise AssertionError(f"unexpected protobuf type {name}")

    @staticmethod
    def _row(ad_group_id, ad_id, headlines, descriptions):
        app_ad = types.SimpleNamespace(
            headlines=[types.SimpleNamespace(text=text) for text in headlines],
            descriptions=[types.SimpleNamespace(text=text) for text in descriptions],
        )
        ad_group_ad = types.SimpleNamespace(
            resource_name=f"customers/1234567890/adGroupAds/{ad_group_id}~{ad_id}",
            ad=types.SimpleNamespace(id=ad_id, app_ad=app_ad),
        )
        return types.SimpleNamespace(
            ad_group=types.SimpleNamespace(id=ad_group_id),
            ad_group_ad=ad_group_ad,
        )

    @staticmethod
    def _change(index, ad_group_id, ad_id, asset_id, field, current, proposed):
        return {
            "change_index": index,
            "campaign_name": "Generic App Campaign",
            "ad_group_id": str(ad_group_id),
            "ad_id": str(ad_id),
            "asset_id": str(asset_id),
            "field_type": field,
            "current_text": current,
            "suggested_text": None,
            "action": "replace",
        }

    def _modules(self, client):
        client_module = types.ModuleType("google.ads.googleads.client")
        client_module.GoogleAdsClient = types.SimpleNamespace(load_from_storage=lambda _: client)
        errors_module = types.ModuleType("google.ads.googleads.errors")
        errors_module.GoogleAdsException = type("FakeGoogleAdsException", (Exception,), {})
        ads_module = types.ModuleType("google.ads")
        ads_module.__path__ = []
        googleads_module = types.ModuleType("google.ads.googleads")
        googleads_module.__path__ = []
        return {
            "google.ads": ads_module,
            "google.ads.googleads": googleads_module,
            "google.ads.googleads.client": client_module,
            "google.ads.googleads.errors": errors_module,
        }

    def _run(self, plan, suggestions, rows, fail_validation=False, fail_actual=False,
             validation_error_indexes=None, actual_error_indexes=None):
        import yaml

        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        plan_path = Path(temp.name) / "creative-plan.yaml"
        plan_path.write_text(yaml.safe_dump(plan, sort_keys=False))
        original = plan_path.read_bytes()
        client = self.FakeClient(
            rows, fail_validation=fail_validation, fail_actual=fail_actual,
            validation_error_indexes=validation_error_indexes,
            actual_error_indexes=actual_error_indexes,
        )
        args = argparse.Namespace(plan=str(plan_path), suggestions=json.dumps(suggestions))
        error = None
        try:
            with mock.patch.object(dp, "_require_write_permission"), \
                 mock.patch.object(dp, "_runtime_write_config_path", return_value=Path(temp.name) / "google.yaml"), \
                 mock.patch.object(dp, "load_profile", return_value={}), \
                 mock.patch.dict(sys.modules, self._modules(client)), \
                 mock.patch("builtins.input", return_value="y"), \
                 contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                dp.creative_copy_apply(args)
        except SystemExit as exc:
            error = exc
        return plan_path, original, client, error

    def test_asset_view_resource_extracts_exact_ad_id(self):
        resource = "customers/1234567890/adGroupAdAssetViews/10~200~300~HEADLINE"
        self.assertEqual(dp._creative_ad_id(resource), "200")
        self.assertEqual(dp._creative_ad_id("malformed"), "")

    def test_creative_dedupe_preserves_same_asset_in_different_ads(self):
        base = {
            "campaign_id": "1", "ad_group_id": "10", "asset_id": "300",
            "asset_type": "TEXT", "field_type": "HEADLINE", "asset_text": "Shared headline",
        }
        rows = [
            {**base, "asset_view_resource_name": "customers/123/adGroupAdAssetViews/10~200~300~HEADLINE"},
            {**base, "asset_view_resource_name": "customers/123/adGroupAdAssetViews/10~201~300~HEADLINE"},
        ]
        self.assertEqual(len(dp._dedupe_creative_rows(rows)), 2)

    def test_real_google_ads_types_support_atomic_validate_request(self):
        try:
            from google.ads.googleads.client import GoogleAdsClient
            from google.auth.credentials import AnonymousCredentials
        except ImportError:
            self.skipTest("google-ads write dependency is not installed")

        client = GoogleAdsClient(
            credentials=AnonymousCredentials(), developer_token="test", use_proto_plus=True
        )
        ad_service = client.get_service("AdService")
        ad_operation = client.get_type("AdOperation")
        ad_operation.update.resource_name = ad_service.ad_path("1234567890", "200")
        mutate_operation = client.get_type("MutateOperation")
        mutate_operation.ad_operation = ad_operation
        request = client.get_type("MutateGoogleAdsRequest")
        request.customer_id = "1234567890"
        request.mutate_operations.append(mutate_operation)
        request.partial_failure = True
        request.validate_only = True

        self.assertEqual(request.customer_id, "1234567890")
        self.assertTrue(request.validate_only)
        self.assertTrue(request.partial_failure)
        self.assertEqual(len(request.mutate_operations), 1)
        self.assertEqual(
            request.mutate_operations[0].ad_operation.update.resource_name,
            "customers/1234567890/ads/200",
        )

    def test_multiple_ads_are_updated_once_each_in_one_partial_failure_batch(self):
        import yaml

        changes = [
            self._change(1, 10, 200, 501, "HEADLINE", "Old headline", "New headline"),
            self._change(2, 10, 200, 502, "DESCRIPTION", "Old description", "New description"),
            self._change(3, 20, 300, 503, "HEADLINE", "Other headline", "Better headline"),
        ]
        plan = {"customer_id": "1234567890", "changes": changes, "applied": False, "applied_at": None}
        rows = [
            self._row(10, 100, ["Old headline", "Distractor"], ["Old description"]),
            self._row(10, 200, ["Old headline", "Keep headline"], ["Old description"]),
            self._row(20, 300, ["Other headline"], ["Keep description"]),
        ]
        suggestions = [
            {"id": 1, "text": "New headline"},
            {"id": 2, "text": "New description"},
            {"id": 3, "text": "Better headline"},
        ]
        plan_path, _, client, error = self._run(plan, suggestions, rows)

        self.assertIsNone(error)
        self.assertIn("ad_group_ad.ad.id IN (200, 300)", client.google_ads_service.queries[0])
        self.assertEqual(len(client.google_ads_service.mutate_calls), 2)
        validation, mutation = client.google_ads_service.mutate_calls
        self.assertTrue(validation.validate_only)
        self.assertTrue(validation.partial_failure)
        self.assertFalse(mutation.validate_only)
        self.assertTrue(mutation.partial_failure)
        self.assertEqual(len(mutation.mutate_operations), 2)
        by_resource = {
            operation.ad_operation.update.resource_name: operation.ad_operation
            for operation in mutation.mutate_operations
        }
        target = by_resource["customers/1234567890/ads/200"]
        self.assertEqual([asset.text for asset in target.update.app_ad.headlines], ["New headline", "Keep headline"])
        self.assertEqual([asset.text for asset in target.update.app_ad.descriptions], ["New description"])
        saved = yaml.safe_load(plan_path.read_text())
        self.assertTrue(saved["applied"])
        self.assertEqual(saved["apply_status"], "applied")
        self.assertEqual(len(saved["apply_results"]), 3)

    def test_google_validation_failure_holds_back_only_affected_ad(self):
        import yaml

        changes = [
            self._change(1, 10, 200, 501, "HEADLINE", "Old one", "New one"),
            self._change(2, 20, 300, 502, "HEADLINE", "Old two", "New two"),
            self._change(3, 30, 400, 503, "HEADLINE", "Old three", "New three"),
        ]
        rows = [
            self._row(10, 200, ["Old one"], ["Description one"]),
            self._row(20, 300, ["Old two"], ["Description two"]),
            self._row(30, 400, ["Old three"], ["Description three"]),
        ]
        suggestions = [{"id": index, "text": change["suggested_text"]}
                       for index, change in enumerate(changes, 1)]
        plan = {"customer_id":"1234567890","changes":changes,"applied":False,"applied_at":None}
        plan_path, _, client, error = self._run(
            plan, suggestions, rows, validation_error_indexes={1}
        )

        self.assertIsNone(error)
        self.assertEqual(len(client.google_ads_service.mutate_calls[1].mutate_operations), 2)
        saved = yaml.safe_load(plan_path.read_text())
        self.assertFalse(saved["applied"])
        self.assertEqual(saved["apply_status"], "partial")
        self.assertEqual([change["apply_status"] for change in saved["changes"]],
                         ["applied", "failed", "applied"])
        self.assertIn("operation 1 rejected", saved["changes"][1]["apply_error"])

    def test_google_apply_failure_marks_only_failed_operation(self):
        import yaml

        changes = [
            self._change(1,10,200,501,"HEADLINE","Old one","New one"),
            self._change(2,20,300,502,"HEADLINE","Old two","New two"),
        ]
        rows = [
            self._row(10,200,["Old one"],["Description one"]),
            self._row(20,300,["Old two"],["Description two"]),
        ]
        plan = {"customer_id":"1234567890","changes":changes,"applied":False}
        plan_path, _, _, error = self._run(
            plan, [{"id":1,"text":"New one"},{"id":2,"text":"New two"}], rows,
            actual_error_indexes={0},
        )

        self.assertIsNone(error)
        saved = yaml.safe_load(plan_path.read_text())
        self.assertEqual([change["apply_status"] for change in saved["changes"]],
                         ["failed", "applied"])
        self.assertIn("operation 0 rejected", saved["changes"][0]["apply_error"])

    def test_retry_accepts_only_failed_change_and_keeps_prior_successes(self):
        import yaml

        changes = [
            {**self._change(1,10,200,501,"HEADLINE","Old one","New one"),
             "apply_status":"applied","applied_at":"2026-09-10T00:00:00"},
            {**self._change(2,20,300,502,"HEADLINE","Old two","New two"),
             "apply_status":"failed","apply_error":"policy"},
        ]
        prior = {"change_index":1,"campaign":"Generic App Campaign","asset_id":"501",
                 "field_type":"HEADLINE","ad_id":"200","status":"replaced","suggested_text":"New one"}
        plan = {"customer_id":"1234567890","changes":changes,"applied":False,
                "apply_status":"partial","apply_results":[prior]}
        rows = [self._row(20,300,["Old two"],["Description two"])]
        plan_path, _, client, error = self._run(
            plan, [{"id":2,"text":"Revised two"}], rows
        )

        self.assertIsNone(error)
        self.assertEqual(len(client.google_ads_service.mutate_calls[1].mutate_operations), 1)
        saved = yaml.safe_load(plan_path.read_text())
        self.assertTrue(saved["applied"])
        self.assertEqual([change["apply_status"] for change in saved["changes"]],
                         ["applied", "applied"])
        self.assertEqual([result["change_index"] for result in saved["apply_results"]], [1, 2])

    def test_duplicate_text_holds_back_one_ad_while_another_applies(self):
        import yaml

        changes = [
            self._change(1,10,200,501,"HEADLINE","Old one","Keep"),
            self._change(2,20,300,502,"HEADLINE","Old two","New two"),
        ]
        rows = [
            self._row(10,200,["Old one","Keep"],["Description one"]),
            self._row(20,300,["Old two"],["Description two"]),
        ]
        plan = {"customer_id":"1234567890","changes":changes,"applied":False}
        plan_path, _, client, error = self._run(
            plan, [{"id":1,"text":"Keep"},{"id":2,"text":"New two"}], rows
        )

        self.assertIsNone(error)
        self.assertEqual(len(client.google_ads_service.mutate_calls[0].mutate_operations), 1)
        saved = yaml.safe_load(plan_path.read_text())
        self.assertEqual([change["apply_status"] for change in saved["changes"]],
                         ["failed", "applied"])
        self.assertIn("duplicate text", saved["changes"][0]["apply_error"])

    def test_local_validation_failure_preserves_plan_and_sends_nothing(self):
        change = self._change(1, 10, 200, 501, "HEADLINE", "Missing headline", "New headline")
        plan = {"customer_id": "1234567890", "changes": [change], "applied": False, "applied_at": None}
        rows = [self._row(10, 200, ["Different headline"], ["Description"])]
        plan_path, original, client, error = self._run(plan, [{"id": 1, "text": "New headline"}], rows)
        self.assertIsNotNone(error)
        self.assertEqual(plan_path.read_bytes(), original)
        self.assertEqual(client.google_ads_service.mutate_calls, [])

    def test_missing_mutation_response_preserves_plan(self):
        change = self._change(1, 10, 200, 501, "HEADLINE", "Old headline", "New headline")
        plan = {"customer_id": "1234567890", "changes": [change], "applied": False, "applied_at": None}
        rows = [self._row(10, 200, ["Old headline"], ["Description"])]
        plan_path, original, client, error = self._run(
            plan, [{"id": 1, "text": "New headline"}], rows, fail_actual=True
        )
        self.assertIsNotNone(error)
        self.assertEqual(plan_path.read_bytes(), original)
        self.assertEqual(len(client.google_ads_service.mutate_calls), 2)
        self.assertTrue(client.google_ads_service.mutate_calls[0].validate_only)

    def test_google_validation_failure_preserves_plan(self):
        change = self._change(1, 10, 200, 501, "HEADLINE", "Old headline", "New headline")
        plan = {"customer_id": "1234567890", "changes": [change], "applied": False, "applied_at": None}
        rows = [self._row(10, 200, ["Old headline"], ["Description"])]
        plan_path, original, client, error = self._run(
            plan, [{"id": 1, "text": "New headline"}], rows, fail_validation=True
        )
        self.assertIsNotNone(error)
        self.assertEqual(plan_path.read_bytes(), original)
        self.assertEqual(len(client.google_ads_service.mutate_calls), 1)
        self.assertTrue(client.google_ads_service.mutate_calls[0].validate_only)


class TestUvRuntime(unittest.TestCase):
    """The launcher and setup path use uv as the runtime authority."""

    def test_uv_run_command_defaults_to_no_sync(self):
        with mock.patch.object(dp, "_uv_executable", return_value="/tmp/uv"):
            self.assertEqual(
                dp._uv_run_command("python", "-c", "pass"),
                ["/tmp/uv", "run", "--project", str(dp.ROOT), "--python", "3.12", "--no-sync", "python", "-c", "pass"],
            )

    def test_uv_run_command_can_request_sync(self):
        with mock.patch.object(dp, "_uv_executable", return_value="/tmp/uv"):
            self.assertNotIn("--no-sync", dp._uv_run_command("python", "-V", sync=True))

    def test_uv_sync_command_supports_optional_capability(self):
        with mock.patch.object(dp, "_uv_executable", return_value="/tmp/uv"):
            self.assertEqual(
                dp._uv_sync_command(extra="write"),
                ["/tmp/uv", "sync", "--project", str(dp.ROOT), "--python", "3.12", "--extra", "write"],
            )

    def test_missing_uv_reports_recovery_action(self):
        with mock.patch.object(dp, "_uv_executable", return_value=None):
            err = io.StringIO()
            with contextlib.redirect_stderr(err), self.assertRaises(SystemExit):
                dp._uv_sync_command()
            self.assertIn("runtime manager", err.getvalue())
            self.assertIn("network access", err.getvalue())

    def test_launcher_delegates_to_uv(self):
        launcher = Path(dp.ROOT / "bob").read_text()
        self.assertIn("run --project", launcher)
        self.assertIn("UV_INSTALL_DIR", launcher)
        self.assertNotIn("installer -pkg", launcher)

    def test_project_declares_capability_extras(self):
        project = (Path(dp.ROOT) / "pyproject.toml").read_text()
        self.assertIn("[project.optional-dependencies]", project)
        self.assertIn("write =", project)
        self.assertIn("video =", project)


class TestFetchDedupe(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._raw_dir = dp.RAW_DIR
        self._pull_log = dp.PULL_LOG_PATH
        self._pull_locks = dp.PULL_LOCKS_DIR
        self._queries_dir = dp.QUERIES_DIR
        self._saved_env = os.environ.copy()
        root = Path(self.tmp.name)
        dp.RAW_DIR = root / "raw"
        dp.PULL_LOG_PATH = root / "logs" / "pull-log.jsonl"
        dp.PULL_LOCKS_DIR = root / "logs" / "pull-locks"
        dp.QUERIES_DIR = root / "queries"
        dp.QUERIES_DIR.mkdir(parents=True, exist_ok=True)
        (dp.QUERIES_DIR / "campaign_daily.sql").write_text("SELECT 1\n")
        os.environ["BOB_CLIENT_INSTANCE_ID"] = "alpha-client"
        self.addCleanup(self._restore_paths)

    def _restore_paths(self):
        dp.RAW_DIR = self._raw_dir
        dp.PULL_LOG_PATH = self._pull_log
        dp.PULL_LOCKS_DIR = self._pull_locks
        dp.QUERIES_DIR = self._queries_dir
        os.environ.clear()
        os.environ.update(self._saved_env)

    def _fetch_args(self):
        return argparse.Namespace(
            query="campaign_daily",
            days=None,
            from_date="2026-08-18",
            to="2026-08-24",
            account="1234567890",
            config="fake-google-ads.yaml",
            dry_run=False,
            run_id="test-run",
            reason="thin dedupe test",
            question="",
            force=False,
        )

    def test_identical_inflight_fetch_is_reused(self):
        call_count = 0
        call_lock = threading.Lock()

        def fake_garf_command(rendered_query_path, tmp_dir, account, config):
            return [str(tmp_dir)]

        def fake_run(cmd, cwd=None, text=None, capture_output=None, check=None):
            nonlocal call_count
            with call_lock:
                call_count += 1
            time.sleep(0.3)
            Path(cmd[0], "out.csv").write_text("date,impressions\n2026-08-24,1\n")
            return mock.Mock(returncode=0, stdout="ok", stderr="")

        with mock.patch.object(dp, "garf_command", side_effect=fake_garf_command), \
             mock.patch.object(dp, "render_query", return_value="SELECT 1"), \
             mock.patch.object(dp.subprocess, "run", side_effect=fake_run):
            first = threading.Thread(target=dp.fetch, args=(self._fetch_args(),))
            second = threading.Thread(target=dp.fetch, args=(self._fetch_args(),))
            first.start()
            time.sleep(0.05)
            second.start()
            first.join()
            second.join()

        self.assertEqual(call_count, 1)
        lines = [json.loads(line) for line in dp._pull_log_path().read_text().splitlines() if line.strip()]
        self.assertEqual(sorted(line["outcome"] for line in lines), ["fetched", "skipped_inflight"])
        self.assertTrue(all(line.get("client_instance_id") == "alpha-client" for line in lines))

    def test_granular_month_is_split_into_seven_day_pulls(self):
        args = self._fetch_args()
        args.from_date = "2026-08-01"
        args.to = "2026-08-30"
        calls = []
        with mock.patch.object(performance_fetch, "_fetch_one", side_effect=lambda child: calls.append(child)):
            dp.fetch(args)
        self.assertEqual(len(calls), 5)
        self.assertEqual(
            [(c.from_date, c.to) for c in calls],
            [
                ("2026-08-01", "2026-08-07"),
                ("2026-08-08", "2026-08-14"),
                ("2026-08-15", "2026-08-21"),
                ("2026-08-22", "2026-08-28"),
                ("2026-08-29", "2026-08-30"),
            ],
        )

    def test_account_period_month_is_not_split(self):
        args = self._fetch_args()
        args.query = "account_network_period"
        args.from_date = "2026-08-01"
        args.to = "2026-08-30"
        calls = []
        with mock.patch.object(performance_fetch, "_fetch_one", side_effect=lambda child: calls.append(child)):
            dp.fetch(args)
        self.assertEqual(len(calls), 1)
        self.assertIs(calls[0], args)


if __name__ == "__main__":
    unittest.main()
