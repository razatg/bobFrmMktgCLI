import argparse
import tempfile
import unittest
import datetime as dt
from pathlib import Path
from unittest.mock import patch

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from lib.bob.performance.adhoc import (
    DATASETS,
    AnalysisError,
    AnalysisResult,
    PreparedDataset,
    catalog,
    normalize_source_rows,
    run_analysis,
)
from lib.bob.performance.adhoc_data import _fetch_failure_detail, prepare_dataset, publish_result
from lib.bob.performance.aggregate import _agg_network_period
from lib.bob.mcp.server import PREPARED, RESULTS, bob_analyze, bob_prepare_data, bob_publish_result


def prepared(rows, dataset="adgroup_network_period"):
    return PreparedDataset(
        handle="dataset-1",
        spec=DATASETS[dataset],
        start="2026-09-01",
        end="2026-09-07",
        primary_goal="installs",
        rows=tuple(rows),
    )


class AdhocAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            {
                "customer_id": "123", "campaign_id": "c1", "campaign_name": "Campaign",
                "ad_group_id": "a1", "ad_group_name": "A1", "ad_group_status": "ENABLED",
                "network": "Search", "impressions": 1000.0, "clicks": 10.0, "cost": 20.0,
                "installs": 5.0, "in_app_conversions": 2.0,
            },
            {
                "customer_id": "123", "campaign_id": "c1", "campaign_name": "Campaign",
                "ad_group_id": "a2", "ad_group_name": "A2", "ad_group_status": "ENABLED",
                "network": "Search", "impressions": 3000.0, "clicks": 30.0, "cost": 30.0,
                "installs": 12.0, "in_app_conversions": 5.0,
            },
        ]

    def test_catalog_exposes_only_registered_data_and_bounded_operations(self):
        found = catalog()
        self.assertEqual(
            {item["name"] for item in found["datasets"]},
            set(DATASETS) - {"adgroup_network_period"},
        )
        self.assertNotIn("python", found["operations"])
        self.assertEqual(found["limits"]["operations"], 20)

    def test_source_normalization_rejects_another_account(self):
        source = [{**self.rows[0], "customer_id": "999"}]
        with self.assertRaisesRegex(AnalysisError, "outside the selected account"):
            normalize_source_rows(DATASETS["adgroup_network_period"], source, "123")

    def test_adgroup_anomaly_graph_aggregates_before_deriving(self):
        operations = [
            {"type": "group_sum", "input": "source", "output": "child",
             "group_by": ["campaign_id", "ad_group_id", "network"],
             "metrics": ["cost", "impressions"]},
            {"type": "group_sum", "input": "source", "output": "parent",
             "group_by": ["campaign_id", "network"], "metrics": ["cost", "impressions"]},
            {"type": "join", "left": "child", "right": "parent", "output": "joined",
             "on": ["campaign_id", "network"], "how": "inner"},
            {"type": "derive", "input": "joined", "output": "child_cpm", "column": "adgroup_cpm",
             "expression": {"op": "multiply", "left": {"op": "safe_divide",
                 "left": {"column": "cost"}, "right": {"column": "impressions"}},
                 "right": {"constant": 1000}}},
            {"type": "derive", "input": "child_cpm", "output": "both_cpm", "column": "campaign_cpm",
             "expression": {"op": "multiply", "left": {"op": "safe_divide",
                 "left": {"column": "cost_right"}, "right": {"column": "impressions_right"}},
                 "right": {"constant": 1000}}},
            {"type": "derive", "input": "both_cpm", "output": "deviation", "column": "deviation",
             "expression": {"op": "safe_divide", "left": {"op": "subtract",
                 "left": {"column": "adgroup_cpm"}, "right": {"column": "campaign_cpm"}},
                 "right": {"column": "campaign_cpm"}}},
        ]
        result = run_analysis("Ad-group CPM anomalies", {"source": prepared(self.rows)}, operations,
                              "deviation", "result-1")
        self.assertEqual([row["campaign_cpm"] for row in result.rows], [12.5, 12.5])
        self.assertEqual([row["deviation"] for row in result.rows], [0.6, -0.2])

    def test_standard_ratios_use_aggregated_totals_and_zero_is_na(self):
        operations = [
            {"type": "group_sum", "input": "source", "output": "totals", "group_by": ["campaign_id"],
             "metrics": ["impressions", "clicks", "cost", "installs", "in_app_conversions"]},
            {"type": "derive_metric", "input": "totals", "output": "metrics", "metrics": ["cpm", "cpc"]},
        ]
        result = run_analysis("Ratios", {"source": prepared(self.rows)}, operations, "metrics", "result-1")
        self.assertEqual(result.rows[0]["cpm"], 12.5)
        empty_clicks = [{**self.rows[0], "clicks": 0.0}]
        result = run_analysis("Zero", {"source": prepared(empty_clicks)}, operations, "metrics", "result-2")
        self.assertIsNone(result.rows[0]["cpc"])

    def test_rank_without_partition_by_is_a_global_ranking(self):
        result = run_analysis(
            "Top campaigns", {"source": prepared(self.rows)},
            [{"type": "rank", "input": "source", "output": "top", "by": "cost", "limit": 1}],
            "top", "result",
        )
        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.rows[0]["ad_group_id"], "a2")
        self.assertEqual(result.rows[0]["rank"], 1)

    def test_reach_cannot_roll_up_above_campaign(self):
        reach = prepared([{**self.rows[0], "reach": 700.0}], "campaign_reach_period")
        operation = [{"type": "group_sum", "input": "source", "output": "bad", "group_by": [],
                      "metrics": ["reach", "impressions"]}]
        with self.assertRaisesRegex(AnalysisError, "campaign grain"):
            run_analysis("Bad reach", {"source": reach}, operation, "bad", "result")

    def test_unknown_operations_columns_and_excess_operations_are_rejected(self):
        source = {"source": prepared(self.rows)}
        with self.assertRaisesRegex(AnalysisError, "unsupported operation"):
            run_analysis("Unsafe", source, [{"type": "python", "output": "x"}], "x", "result")
        with self.assertRaisesRegex(AnalysisError, "additive metrics only"):
            run_analysis("Bad sum", source, [{"type": "group_sum", "input": "source", "output": "x",
                "group_by": ["campaign_id"], "metrics": ["cpm"]}], "x", "result")
        with self.assertRaisesRegex(AnalysisError, "20-operation"):
            run_analysis("Long", source, [{} for _ in range(21)], "source", "result")
        with self.assertRaisesRegex(AnalysisError, "stable identifiers"):
            run_analysis("Bad join", source, [{"type":"join", "left":"source", "right":"source",
                "output":"x", "on":["campaign_name"], "how":"inner"}], "x", "result")

    def test_result_and_runtime_limits_are_enforced(self):
        too_many = prepared([self.rows[0]] * 10_001)
        with self.assertRaisesRegex(AnalysisError, "result exceeds"):
            run_analysis("Too many", {"source": too_many}, [], "source", "result")
        operation = [{"type": "select", "input": "source", "output": "selected",
                      "columns": ["campaign_id"]}]
        with patch("lib.bob.performance.adhoc.time.monotonic", side_effect=[0.0, 61.0]):
            with self.assertRaisesRegex(AnalysisError, "60-second"):
                run_analysis("Too slow", {"source": prepared(self.rows)}, operation,
                             "selected", "result")

    def test_mcp_preview_is_bounded_and_unknown_result_is_rejected(self):
        PREPARED.clear(); RESULTS.clear()
        source = prepared([self.rows[0]] * 60)
        PREPARED[source.handle] = source
        response = bob_analyze("Bounded preview", {"source": source.handle}, [], "source")
        self.assertEqual(response["row_count"], 60)
        self.assertEqual(len(response["preview"]), 50)
        self.assertTrue(response["preview_truncated"])
        with self.assertRaisesRegex(AnalysisError, "explicit user confirmation"):
            bob_publish_result(response["result_handle"], "Result", "csv", False)
        with self.assertRaisesRegex(AnalysisError, "unknown or expired"):
            bob_publish_result("not-a-result", "Result", "csv", True)


class AdhocDataTests(unittest.TestCase):

    def test_primary_conversion_aggregate_writes_its_declared_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.csv"
            output = Path(directory) / "result.csv"
            source.write_text(
                "customer_id,campaign_id,campaign_name,campaign_status,network,impressions,clicks,cost,primary_conversions\n"
                "123,c1,Campaign,ENABLED,SEARCH,100,2,3,1\n"
            )
            args = argparse.Namespace(
                source=None, customer="123", from_date="2026-09-01", to="2026-09-07",
                input=str(source), input_paths=None, output=str(output),
            )
            _agg_network_period(args, {}, "campaign_primary_conversion_period", "installs")
            header = output.read_text().splitlines()[0].split(",")
        self.assertEqual(header, [
            "customer_id", "campaign_id", "campaign_name", "campaign_status", "network",
            "impressions", "clicks", "cost", "primary_conversions", "cpm", "cpc", "primary_cpa",
        ])

    def test_mcp_rejects_obsolete_adgroup_dataset_without_preparing_it(self):
        result = bob_prepare_data("adgroup_network_period", "2026-09-01", "2026-09-07", "reason", "question")
        self.assertEqual(result["error"]["code"], "DATASET_UNAVAILABLE")

    def test_mcp_returns_preparation_error_as_typed_content(self):
        with patch("lib.bob.mcp.server.prepare_dataset", side_effect=AnalysisError("Google Ads rejected field x")):
            result = bob_prepare_data("campaign_network_period", "2026-09-01", "2026-09-07", "reason", "question")
        self.assertEqual(result, {"ok": False, "error": {
            "code": "DATA_PREPARATION_FAILED", "message": "Google Ads rejected field x",
        }})

    def test_primary_conversion_queries_use_supported_generic_metric_at_both_grains(self):
        root = Path(__file__).resolve().parents[1]
        campaign = (root / "garf" / "queries" / "campaign_primary_conversion_period.sql").read_text()
        adgroup = (root / "garf" / "queries" / "adgroup_primary_conversion_period.sql").read_text()
        self.assertIn("FROM campaign", campaign)
        self.assertIn("FROM ad_group", adgroup)
        self.assertIn("metrics.conversions AS primary_conversions", campaign)
        self.assertIn("metrics.conversions AS primary_conversions", adgroup)

    def test_fetch_failure_detail_returns_bounded_google_error(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch("lib.bob.performance.adhoc_data.RAW_DIR", Path(directory)):
            query_dir = Path(directory) / "adgroup_network_period"
            query_dir.mkdir()
            (query_dir / "123_2026-09-14_2026-09-20_run.meta.json").write_text(
                '{"stderr": "GoogleAdsException: query_error: PROHIBITED_METRIC_IN_SELECT_OR_WHERE_CLAUSE"}'
            )
            detail = _fetch_failure_detail(
                "adgroup_network_period", dt.date(2026, 9, 14), dt.date(2026, 9, 20), "123"
            )
        self.assertIn("PROHIBITED_METRIC", detail or "")
        self.assertIn("Google Ads rejected", detail or "")

    def test_existing_processed_data_is_used_without_fetch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.csv"
            path.write_text("customer_id,campaign_id,campaign_name,campaign_status,network,impressions,clicks,cost,installs,in_app_conversions\n123,c1,C,ENABLED,Search,100,2,3,1,0\n")
            profile = {"google_ads_customer_id": "123", "primary_goal": "installs"}
            with patch("lib.bob.performance.adhoc_data.selected_account", return_value=("123", profile)), \
                 patch("lib.bob.performance.adhoc_data._manifest_pull_status", return_value=[]), \
                 patch("lib.bob.performance.adhoc_data.find_processed_files_for_period", return_value=[path]), \
                 patch("lib.bob.performance.adhoc_data.fetch") as fetch_mock:
                dataset, response = prepare_dataset("campaign_network_period", "2026-09-01", "2026-09-07",
                                                    "reason", "question", "handle")
            self.assertEqual(len(dataset.rows), 1)
            self.assertFalse(response["fetched"])
            fetch_mock.assert_not_called()

    def test_empty_processed_data_is_not_accepted_as_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "empty.csv"
            path.write_text("customer_id,campaign_id,campaign_name,campaign_status,network,impressions,clicks,cost,installs,in_app_conversions\n")
            profile = {"google_ads_customer_id": "123", "primary_goal": "installs"}
            with patch("lib.bob.performance.adhoc_data.selected_account", return_value=("123", profile)), \
                 patch("lib.bob.performance.adhoc_data._manifest_pull_status", return_value=[]), \
                 patch("lib.bob.performance.adhoc_data.find_processed_files_for_period", return_value=[path]), \
                 patch("lib.bob.performance.adhoc_data._fetch_registered"), \
                 patch("lib.bob.performance.adhoc_data.ensure_processed_file_for_period", return_value=path):
                with self.assertRaisesRegex(AnalysisError, "empty cached dataset"):
                    prepare_dataset("campaign_network_period", "2026-09-01", "2026-09-07",
                                    "reason", "question", "handle")

    def test_missing_registered_data_uses_existing_fetch_then_aggregate_path(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.csv"
            path.write_text("customer_id,campaign_id,campaign_name,campaign_status,network,impressions,clicks,cost,installs,in_app_conversions\n123,c1,C,ENABLED,Search,100,2,3,1,0\n")
            profile = {"google_ads_customer_id": "123", "primary_goal": "installs"}
            with patch("lib.bob.performance.adhoc_data.selected_account", return_value=("123", profile)), \
                 patch("lib.bob.performance.adhoc_data._manifest_pull_status", return_value=[]), \
                 patch("lib.bob.performance.adhoc_data.find_processed_files_for_period", return_value=[None]), \
                 patch("lib.bob.performance.adhoc_data.ensure_processed_file_for_period", side_effect=[None, path]), \
                 patch("lib.bob.performance.adhoc_data.fetch") as fetch_mock:
                _, response = prepare_dataset("campaign_network_period", "2026-09-01", "2026-09-07",
                                              "custom analysis", "find anomalies", "handle")
            self.assertTrue(response["fetched"])
            fetch_mock.assert_called_once()
            self.assertEqual(fetch_mock.call_args.args[0].account, "123")

    def test_missing_processed_path_is_prepared_instead_of_crashing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.csv"
            path.write_text("customer_id,campaign_id,campaign_name,campaign_status,network,impressions,clicks,cost,installs,in_app_conversions\n123,c1,C,ENABLED,Search,100,2,3,1,0\n")
            profile = {"google_ads_customer_id": "123", "primary_goal": "installs"}
            with patch("lib.bob.performance.adhoc_data.selected_account", return_value=("123", profile)), \
                 patch("lib.bob.performance.adhoc_data._manifest_pull_status", return_value=[]), \
                 patch("lib.bob.performance.adhoc_data.find_processed_files_for_period", return_value=[]), \
                 patch("lib.bob.performance.adhoc_data.ensure_processed_file_for_period", side_effect=[None, path]), \
                 patch("lib.bob.performance.adhoc_data.fetch"):
                dataset, response = prepare_dataset("campaign_network_period", "2026-09-01", "2026-09-07",
                                                    "custom analysis", "find anomalies", "handle")
            self.assertEqual(len(dataset.rows), 1)
            self.assertTrue(response["fetched"])

    def test_publish_writes_only_markdown_or_csv_under_selected_account(self):
        result = AnalysisResult("result", "Analysis", "summed values", ("campaign", "cost"),
                                ({"campaign": "A", "cost": 12.5},))
        with tempfile.TemporaryDirectory() as directory, \
             patch("lib.bob.performance.adhoc_data.selected_account",
                   return_value=("123", {"account_name": "Demo"})), \
             patch("lib.bob.performance.adhoc_data.account_wiki_dir", return_value=Path(directory)):
            published = publish_result(result, "Campaign anomalies", "csv")
            self.assertTrue((Path(directory) / "analyses" / Path(published["artifact"]).name).is_file())
            with self.assertRaisesRegex(AnalysisError, "markdown or csv"):
                publish_result(result, "Internal", "json")


class MCPHandshakeTests(unittest.TestCase):
    def test_stdio_server_lists_only_approved_tools(self):
        async def exercise():
            root = Path(__file__).resolve().parents[1]
            params = StdioServerParameters(
                command=str(root / ".venv" / "bin" / "python"),
                args=["-m", "lib.bob.mcp.server"],
                cwd=root,
            )
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    self.assertEqual({tool.name for tool in tools.tools}, {
                        "bob_resolve_dates", "bob_data_catalog", "bob_prepare_data",
                        "bob_analyze", "bob_publish_result",
                    })
        anyio.run(exercise)


if __name__ == "__main__":
    unittest.main()
