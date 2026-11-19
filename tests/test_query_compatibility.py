"""Exercise registered CLI/data contracts without contacting Google Ads."""
import argparse
import contextlib
import csv
import datetime as dt
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lib.bob.cli import build_parser
from lib.bob.platform import core
from lib.bob.performance import aggregate as aggregation
from lib.bob.performance import fetch as fetching
from lib.bob.performance import adhoc_data
from lib.bob.performance.adhoc import (
    AnalysisError, DATASETS, PreparedDataset, catalog, run_analysis,
)


class QueryCompatibilityTests(unittest.TestCase):
    def test_literal_date_works_through_cli_and_registered_resolver(self):
        from lib.bob.platform.dates import resolve_period_dates
        from lib.bob.mcp.server import bob_resolve_dates
        day = dt.date(2026, 11, 18)
        self.assertEqual(resolve_period_dates('2026-11-18'), [(day, day)])
        args = build_parser().parse_args(['resolve-dates', '--period', '2026-11-18'])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            args.func(args)
        self.assertIn('2026-11-18', output.getvalue())
        self.assertEqual(bob_resolve_dates(period='2026-11-18')['windows'],
                         [{'from': '2026-11-18', 'to': '2026-11-18'}])
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            resolve_period_dates('2026-02-30')

    def test_cli_primary_conversion_handoff_preserves_metric_meaning(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, output = Path(tmp) / 'source.csv', Path(tmp) / 'output.csv'
            source.write_text('customer_id,campaign_id,ad_group_id,network,impressions,clicks,cost,primary_conversions\n'
                              '1234567890,1,2,SEARCH,1000,100,100,10\n')
            args = build_parser().parse_args([
                'aggregate', '--grain', 'adgroup_primary_conversion_period',
                '--input', str(source), '--output', str(output), '--customer', '1234567890',
                '--goal', 'installs', '--from', '2026-11-01', '--to', '2026-11-07',
            ])
            with patch.object(aggregation, 'load_profile', return_value={}), contextlib.redirect_stdout(io.StringIO()):
                args.func(args)
            with output.open() as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual(row['primary_conversions'], '10')
            self.assertEqual(row['primary_cpa'], '10')
            self.assertNotIn('installs', row)
            self.assertNotIn('in_app_conversions', row)
        for grain in ('campaign_primary_conversion_period', 'bid_budget_inputs', 'change_history'):
            self.assertEqual(build_parser().parse_args(['aggregate', '--grain', grain]).func, aggregation.aggregate)

    def test_catalog_metrics_work_without_unrelated_conversion_columns(self):
        row = dict(customer_id='123', impressions=1000., clicks=100., cost=100., primary_conversions=10.)
        source = PreparedDataset('s', DATASETS['adgroup_primary_conversion_period'],
                                 '2026-11-01', '2026-11-07', 'installs', (row,))
        metrics = next(item['derived_metrics'] for item in catalog()['datasets']
                       if item['name'] == source.spec.name)
        result = run_analysis('metrics', {'s': source}, [
            dict(type='derive_metric', input='s', output='d', metrics=metrics),
        ], 'd', 'result')
        self.assertEqual(result.rows[0]['cpm'], 100.)
        self.assertEqual(result.rows[0]['cpc'], 1.)
        self.assertEqual(result.rows[0]['primary_cpa'], 10.)
        self.assertNotIn('cpi', metrics)
        with self.assertRaisesRegex(AnalysisError, 'installs'):
            run_analysis('missing input', {'s': source}, [
                dict(type='derive_metric', input='s', output='d', metrics=['cpi']),
            ], 'd', 'result')

    def test_complete_legacy_raw_range_is_reused_without_chunk_fetches(self):
        start, end = dt.date(2026, 11, 1), dt.date(2026, 11, 14)
        with tempfile.TemporaryDirectory() as tmp, patch.object(core, 'RAW_DIR', Path(tmp)):
            directory = Path(tmp) / 'campaign_network_period'
            directory.mkdir()
            raw = directory / '1234567890_2026-11-01_2026-11-14_old.csv'
            raw.write_text('customer_id,cost\n1234567890,100\n')
            self.assertEqual(core.find_raw_files_for_range('campaign_network_period', start, end, '1234567890'), [raw])
            args = argparse.Namespace(query='campaign_network_period', account='1234567890',
                                      from_date=str(start), to=str(end), days=None, force=False)
            with patch.object(fetching, 'load_profile', return_value={}), patch.object(fetching, '_fetch_one') as fetch:
                fetching.fetch(args)
                fetch.assert_called_once_with(args)

    def test_reach_fetch_is_whole_period_and_chunk_aggregation_is_rejected(self):
        args = argparse.Namespace(query='campaign_reach_period')
        with patch.object(fetching, '_fetch_one') as fetch:
            fetching.fetch(args)
            fetch.assert_called_once_with(args)
        with tempfile.TemporaryDirectory() as tmp:
            paths = [Path(tmp) / f'chunk-{i}.csv' for i in range(2)]
            for path in paths:
                path.write_text('campaign_id,reach,impressions\n1,100,1000\n')
            args = argparse.Namespace(source=None, customer='123', from_date='2026-11-01',
                                      to='2026-11-14', input=None, input_paths=paths, output=str(Path(tmp) / 'out.csv'))
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                aggregation._agg_network_period(args, {}, 'campaign_reach_period', 'installs')
            self.assertFalse(Path(args.output).exists())

    def test_unsafe_legacy_reach_cache_is_not_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            cached = Path(tmp) / '123_2026-11-01_2026-11-14.csv'
            cached.write_text('campaign_id,reach\n1,200\n')
            with patch.object(aggregation, 'find_processed_files_for_period', return_value=[cached]), \
                 patch.object(aggregation, 'find_raw_files_for_range', return_value=None):
                self.assertIsNone(aggregation.ensure_processed_file_for_period(
                    'campaign_reach_period', 'campaign-reach', dt.date(2026,11,1), dt.date(2026,11,14), '123', 'installs'))
                self.assertEqual(aggregation.ensure_processed_file_for_period(
                    'campaign_network_period', 'campaign-network', dt.date(2026,11,1), dt.date(2026,11,14), '123', 'installs'), cached)

    def test_retired_query_never_contacts_provider_and_old_grain_stays_readable(self):
        with patch.object(fetching, '_fetch_one') as fetch, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                fetching.fetch(argparse.Namespace(query='adgroup_network_period'))
            fetch.assert_not_called()
        self.assertEqual(build_parser().parse_args(['aggregate', '--grain', 'adgroup_network_period']).func,
                         aggregation.aggregate)

    def test_complete_period_reach_stays_at_source_grain(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / '123_2026-11-01_2026-11-14_run.csv'
            output = Path(tmp) / 'out.csv'
            source.write_text('customer_id,campaign_id,reach,impressions,cost\n123,1,100,2000,100\n')
            args = build_parser().parse_args([
                'aggregate', '--grain', 'campaign_reach_period', '--input', str(source),
                '--output', str(output), '--customer', '123', '--from', '2026-11-01', '--to', '2026-11-14',
            ])
            with patch.object(aggregation, 'load_profile', return_value={}), contextlib.redirect_stdout(io.StringIO()):
                args.func(args)
            with output.open() as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual(row['reach'], '100')
            self.assertEqual(row['frequency'], '20')

    def test_preparation_cannot_bypass_reach_cache_provenance(self):
        with patch.object(adhoc_data, 'selected_account', return_value=('123', {})), \
             patch.object(adhoc_data, '_manifest_pull_status', return_value=[]), \
             patch.object(adhoc_data, 'find_processed_files_for_period', return_value=[Path('/tmp/legacy.csv')]), \
             patch.object(adhoc_data, 'ensure_processed_file_for_period', return_value=None), \
             patch.object(adhoc_data, '_fetch_registered') as fetch:
            with self.assertRaisesRegex(AnalysisError, 'fetching is disabled'):
                adhoc_data.prepare_dataset('campaign_reach_period', '2026-11-01', '2026-11-14',
                                           'question', 'question', 's', allow_fetch=False)
            fetch.assert_not_called()
