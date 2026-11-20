"""Exercise the evidence → decision → review boundary and unsafe proposals."""
import datetime as dt
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from lib.bob.bid_budget.guards import CampaignState, plan_hash, validate_plan
from lib.bob.creative_copy.rules import validate_copy
from lib.bob.decisions import records
from lib.bob.decisions.evidence import read
from lib.bob.decisions.review import review
from lib.bob.search import search


class EvidenceFlowTests(unittest.TestCase):
    def test_recommendation_stays_offline_and_does_not_skip_on_reference_or_wait(self):
        import argparse
        import contextlib
        import io
        import yaml
        from unittest.mock import patch
        from lib.bob.bid_budget import bid_budget_recommend
        trend = {'customer_id': self.account, 'campaign_id': '1', 'campaign_name': 'Campaign',
                 'campaign_status': 'ENABLED', 'current_iso_week': '47', 'prior1_iso_week': '46', 'prior2_iso_week': '45'}
        for week, cost in ((47, 330), (46, 400), (45, 400)):
            trend.update({f'w{week}_cost': cost, f'w{week}_installs': 1000,
                          f'w{week}_impressions': 1000, f'w{week}_in_app_conversions': 1})
        history = self.root / 'history.csv'
        history.touch()
        budget = self.root / 'budget.csv'
        inputs = [{'customer_id': self.account, 'campaign_id': '1', 'daily_budget': 100,
                   'target_cpa': 100, 'campaign_budget_id': '2', 'cost': 100}]
        def read(path):
            if Path(path) == self.path:
                return [trend]
            if Path(path) == budget:
                return inputs
            return [{'campaign_id': '1', 'change_resource_type': 'CAMPAIGN', 'operation': 'UPDATE', 'changed_at': '2026-11-16'}]
        final = self.root / 'recommendation.yaml'
        with patch('lib.bob.bid_budget.load_profile', return_value={'google_ads_customer_id': self.account}), \
             patch('lib.bob.bid_budget.bid_budget_trend_path', return_value=(self.path, [])), \
             patch('lib.bob.bid_budget.validate_bid_budget_trend_rows'), \
             patch('lib.bob.bid_budget.read_csv', side_effect=read), \
             patch('lib.bob.bid_budget.find_newest_raw_for_customer', return_value=history), \
             patch('lib.bob.bid_budget.today', return_value=dt.date(2026, 11, 19)), \
             patch('lib.bob.bid_budget.guards.read_live_state', side_effect=AssertionError('recommendation must not query live execution state')), \
             contextlib.redirect_stdout(io.StringIO()):
            bid_budget_recommend(argparse.Namespace(goal=None, cac_ceiling=None, change_pct=None,
                trend=str(self.path), bid_budget=str(budget), output=str(self.root/'recommendation.csv'),
                yaml_output=str(final), dry_run=False))
        saved = yaml.safe_load(final.read_text())
        self.assertEqual(len(saved['changes']), 1)
        self.assertEqual(saved['skipped'], [])
        self.assertIn('Review guidance:', saved['changes'][0]['rationale'])
        self.assertFalse(saved['changes'][0]['cooldown_ok'])
        self.assertFalse(saved['changes'][0]['cac_guard_passed'])

    def test_grouping_allows_blank_categories_but_join_requires_identity(self):
        from lib.bob.performance.adhoc import _group_sum, _join, AnalysisError
        rows = [{'network': '', 'cost': 10}, {'network': '', 'cost': 20}]
        grouped, _ = _group_sum({'source': rows}, {'input': 'source', 'group_by': ['network'], 'metrics': ['cost']}, {'cost'})
        self.assertEqual(grouped, [{'network': '', 'cost': 30}])
        with self.assertRaisesRegex(AnalysisError, 'join keys'):
            _join({'left': [{'campaign_id': ''}], 'right': [{'campaign_id': ''}]},
                  {'left': 'left', 'right': 'right', 'on': ['campaign_id']})

    def test_context_aggregation_accepts_explicit_input_with_no_input_paths(self):
        import argparse
        import contextlib
        import io
        from unittest.mock import patch
        from lib.bob.performance.aggregate import _agg_context
        source = self.root / 'events.csv'
        source.write_text('campaign_id,changed_at\n1,2026-11-19\n')
        with patch('lib.bob.performance.aggregate.account_processed_dir', return_value=self.root/'context'), \
             contextlib.redirect_stdout(io.StringIO()):
            _agg_context(argparse.Namespace(customer=self.account, grain='change_history', input=str(source),
                input_paths=None, from_date='2026-11-19', to='2026-11-19'), {})
        self.assertIn('2026-11-19', next((self.root/'context').glob('*.csv')).read_text())

    def test_generated_copy_accepts_agent_subset_and_complete_rows_through_mock_apply(self):
        import argparse
        import contextlib
        import io
        import yaml
        from unittest.mock import patch
        from lib.bob.creative_copy.suggest import suggest_creative_copy
        from lib.bob.creative_copy.apply import creative_copy_propose
        from tests.test_core import TestCreativeCopyApply
        wiki = self.root / 'wiki' / self.account
        rows = []
        for i in range(1, 34):
            rows.append({'customer_id': self.account, 'campaign_id': '1', 'campaign_name': 'Campaign',
                'ad_group_id': str(100 + i), 'ad_group_name': 'Group', 'asset_id': str(300 + i),
                'asset_view_resource_name': f'customers/{self.account}/adGroupAdAssetViews/{100+i}~{200+i}~{300+i}~HEADLINE',
                'asset_type': 'TEXT', 'field_type': 'HEADLINE', 'asset_text': f'Old copy {i}',
                'performance_label': 'LOW' if i <= 32 else 'GOOD', 'impressions': 100000,
                'clicks': 100 if i <= 32 else 10000, 'installs': 1 if i <= 32 else 1000,
                'cost': 10000, 'ctr_percent': .1 if i <= 32 else 10,
                'cti_percent': 1 if i <= 32 else 10, 'cpc': 100 if i <= 32 else 1})
        profile = {'google_ads_customer_id': self.account}
        with patch('lib.bob.creative_copy.suggest.load_profile', return_value=profile), \
             patch('lib.bob.creative_copy.suggest._creative_processed_paths', return_value=[self.path]), \
             patch('lib.bob.creative_copy.suggest.read_csv', return_value=rows), contextlib.redirect_stdout(io.StringIO()):
            suggest_creative_copy(argparse.Namespace(output_dir=str(wiki), batch_size=25, min_impressions=None))
        original = next(wiki.glob('*.yaml'))
        original_bytes = original.read_bytes()
        candidates = yaml.safe_load(original_bytes)['changes']
        self.assertEqual(len(candidates), 32)
        final = wiki / 'selected.yaml'
        for shape in ('agent', 'complete'):
            if shape == 'agent':
                choices = [{'id': i, 'text': f'New copy {i}'} for i in range(7, 33)]
            else:
                choices = [dict(row, suggested_text=f'New copy {i}') for i, row in enumerate(candidates, 1) if i >= 7]
            with patch('lib.bob.creative_copy.apply.load_profile', return_value=profile), \
                 patch('lib.bob.creative_copy.apply.account_wiki_dir', return_value=wiki), contextlib.redirect_stdout(io.StringIO()):
                creative_copy_propose(argparse.Namespace(plan=str(original), output=str(final), changes_json=json.dumps(choices)))
            saved = yaml.safe_load(final.read_text())
            self.assertEqual(len(saved['changes']), 26)
            self.assertEqual([row['asset_id'] for row in saved['changes']], [row['asset_id'] for row in candidates[6:]])
            self.assertEqual(saved['changes'][0]['ctr_percent'], candidates[6]['ctr_percent'])
            self.assertEqual(saved['changes'][0]['suggested_text'], 'New copy 7')
            self.assertEqual(original.read_bytes(), original_bytes)
        saved['decision_id'] = self.record()['decision_id']
        adapter = TestCreativeCopyApply()
        self.addCleanup(adapter.doCleanups)
        live = [adapter._row(100+i, 200+i, [f'Old copy {i}'], ['Existing description.']) for i in range(1, 34)]
        with patch('lib.bob.creative_copy.apply.STATE_ROOT', self.root):
            applied_path, _, client, error = adapter._run(saved, [], live)
        self.assertIsNone(error)
        self.assertTrue(yaml.safe_load(applied_path.read_text())['applied'])
        requests = client.google_ads_service.mutate_calls
        self.assertEqual(len(requests), 2)
        self.assertEqual(len(requests[-1].mutate_operations), 26)

    def test_writers_preserve_execution_receipts_and_accept_generated_bid_rows(self):
        import argparse
        import contextlib
        import io
        import yaml
        from unittest.mock import patch
        from lib.bob.bid_budget import bid_budget_propose
        from lib.bob.creative_copy.apply import creative_copy_propose
        wiki = self.root / 'wiki' / self.account
        wiki.mkdir(parents=True)
        source, target = wiki / 'baseline.yaml', wiki / 'final.yaml'
        bid = {'campaign_id': '1', 'campaign_name': 'Campaign', 'field': 'target_cpa',
               'current_target_cpa': 100, 'proposed_target_cpa': 110, 'proposed_daily_budget': None,
               'action': 'increase_bid', 'rationale': 'Evidence supports scale', 'forecast': 'Review volume in a week',
               'w0_cpi': 20, 'cooldown_ok': True}
        plan = {'customer_id': self.account, 'changes': [bid], 'applied': False}
        source.write_text(yaml.safe_dump(plan))
        args = argparse.Namespace(plan=str(source), output=str(target), changes_json=json.dumps([bid]))
        with patch('lib.bob.bid_budget.load_profile', return_value={'google_ads_customer_id': self.account}), \
             patch('lib.bob.bid_budget.account_wiki_dir', return_value=wiki), contextlib.redirect_stdout(io.StringIO()):
            bid_budget_propose(args)
        self.assertEqual(yaml.safe_load(target.read_text())['changes'][0]['w0_cpi'], 20)
        plan['apply_results'] = [{'campaign_id': '1', 'status': 'ok'}]
        source.write_text(yaml.safe_dump(plan))
        previous = target.read_bytes()
        for module, writer in [('lib.bob.bid_budget', bid_budget_propose), ('lib.bob.creative_copy.apply', creative_copy_propose)]:
            with patch(module + '.load_profile', return_value={'google_ads_customer_id': self.account}), \
                 patch(module + '.account_wiki_dir', return_value=wiki), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                writer(args)
            self.assertEqual(target.read_bytes(), previous)

    def test_offline_bid_hash_needs_no_credentials_and_live_state_reads_only_settings(self):
        import argparse
        import contextlib
        import io
        import yaml
        from types import SimpleNamespace as NS
        from unittest.mock import Mock, patch
        from lib.bob.bid_budget import bid_budget_validate
        from lib.bob.bid_budget.guards import read_live_state
        plan = {'customer_id': self.account, 'changes': [], 'applied': False}
        path = self.root / 'draft.yaml'
        path.write_text(yaml.safe_dump(plan))
        output = io.StringIO()
        with patch('lib.bob.bid_budget.load_profile', return_value={'google_ads_customer_id': self.account}), \
             patch('lib.bob.bid_budget._runtime_write_config_path', side_effect=AssertionError('must stay offline')), \
             contextlib.redirect_stdout(output):
            bid_budget_validate(argparse.Namespace(plan=str(path)))
        result = json.loads(output.getvalue())
        self.assertFalse(result['live_checked'])
        self.assertEqual(result['plan_hash'], plan_hash(plan))
        service = Mock()
        service.search.return_value = [NS(campaign=NS(id=1, status=NS(name='ENABLED'), target_cpa=NS(target_cpa_micros=100000000)),
                                          campaign_budget=NS(id=2, amount_micros=1000000000))]
        states = read_live_state(NS(get_service=lambda name: service), self.account, dt.date(2026, 11, 19), 14)
        self.assertEqual(states['1'].target_cpa, 100)
        self.assertIsNone(states['1'].installs)
        self.assertEqual(service.search.call_count, 1)
        query = service.search.call_args.kwargs['query']
        self.assertNotIn('metrics.', query)
        self.assertNotIn('change_event', query)
        self.assertNotIn('segments.date', query)

    def test_approved_bid_apply_stops_before_mutation_when_current_settings_time_out(self):
        import argparse
        import contextlib
        import io
        import sys
        import yaml
        from unittest.mock import Mock, patch
        from lib.bob.bid_budget import bid_budget_apply
        from tests.test_core import TestCreativeCopyApply
        plan = {'customer_id': self.account, 'changes': [{'campaign_id': '1', 'action': 'increase_bid',
                                                        'proposed_target_cpa': 110}], 'applied': False}
        path = self.root / 'approved.yaml'
        path.write_text(yaml.safe_dump(plan))
        before = path.read_bytes()
        client = Mock()
        with patch.dict(sys.modules, TestCreativeCopyApply()._modules(client)), \
             patch('lib.bob.bid_budget._require_write_permission'), \
             patch('lib.bob.bid_budget._runtime_write_config_path', return_value=self.root/'credentials.yaml'), \
             patch('lib.bob.bid_budget.load_profile', return_value={'google_ads_customer_id': self.account}), \
             patch('lib.bob.bid_budget.guards.read_live_state', side_effect=TimeoutError('current settings timed out')), \
             contextlib.redirect_stdout(io.StringIO()), self.assertRaises(TimeoutError):
            bid_budget_apply(argparse.Namespace(plan=str(path), approval_hash=plan_hash(plan)))
        client.get_service.assert_not_called()
        self.assertEqual(path.read_bytes(), before)

    def test_copy_save_returns_row_errors_then_accepts_corrected_draft(self):
        import argparse
        import contextlib
        import io
        import yaml
        from unittest.mock import patch
        from lib.bob.creative_copy.apply import creative_copy_propose
        wiki = self.root / 'wiki' / self.account
        wiki.mkdir(parents=True)
        original, target = wiki / 'baseline.yaml', wiki / 'draft.yaml'
        original.write_text(yaml.safe_dump({'customer_id': self.account, 'changes': [], 'applied': False}))
        target.write_text('previous draft')
        changes = [{'ad_group_id': '10', 'ad_id': '20', 'asset_id': str(asset),
                    'action': 'replace', 'field_type': 'HEADLINE', 'current_text': 'Old copy',
                    'suggested_text': text, 'rationale': 'Evidence supports replacing this asset'}
                   for asset, text in ((30, None), (31, 'x' * 31))]
        args = argparse.Namespace(plan=str(original), output=str(target), changes_json=json.dumps(changes))
        with patch('lib.bob.creative_copy.apply.load_profile', return_value={'google_ads_customer_id': self.account}), \
             patch('lib.bob.creative_copy.apply.account_wiki_dir', return_value=wiki):
            output = io.StringIO()
            with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as stopped:
                creative_copy_propose(args)
            self.assertEqual(stopped.exception.code, 2)
            feedback = json.loads(output.getvalue())
            self.assertFalse(feedback['saved'])
            self.assertEqual([item['row'] for item in feedback['errors']], [1, 2])
            self.assertEqual(feedback['errors'][1]['limit'], 30)
            self.assertEqual(target.read_text(), 'previous draft')
            for change in changes:
                change['suggested_text'] = 'New copy'
            args.changes_json = json.dumps(changes)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                creative_copy_propose(args)
            self.assertTrue(json.loads(output.getvalue())['saved'])
        saved = yaml.safe_load(target.read_text())
        self.assertEqual([item['suggested_text'] for item in saved['changes']], ['New copy', 'New copy'])
        self.assertTrue(saved['decision_required'])
        self.assertFalse(saved['applied'])
        self.assertNotIn('approved_hash', saved)

    def test_goals_carry_legacy_values_without_overriding_saved_preferences(self):
        from lib.bob.platform.goals import account_goals, with_goal_aliases
        profile = {'cac_ceiling': 75, 'bid_budget_change_pct': 5, 'bid_budget_cooldown_days': 3}
        goals = account_goals(profile)
        self.assertEqual(goals['usual_approach'], {'cac_reference': 75, 'typical_change_pct': 5, 'preferred_wait_days': 3})
        profile['goals'] = goals
        goals['usual_approach']['typical_change_pct'] = 15
        self.assertEqual(with_goal_aliases(profile)['bid_budget_change_pct'], 15)
        goals['usual_approach']['cac_reference'] = None
        self.assertIsNone(account_goals(profile)['usual_approach']['cac_reference'])


    def test_registered_proposals_preserve_baseline_and_require_decision_capture(self):
        import argparse
        import contextlib
        import io
        import yaml
        from unittest.mock import patch
        from lib.bob.bid_budget import bid_budget_propose
        from lib.bob.creative_copy.apply import creative_copy_propose
        wiki = self.root/'wiki'/self.account
        wiki.mkdir(parents=True)
        original = wiki/'baseline.yaml'
        original.write_text(yaml.safe_dump({'customer_id': self.account, 'changes': [], 'applied': False}))
        original_bytes = original.read_bytes()
        for module, propose, changes in (
            ('lib.bob.bid_budget', bid_budget_propose, [{'campaign_id': '1', 'action': 'increase_bid',
                'proposed_target_cpa': 110, 'rationale': 'Registered evidence supports this choice'}]),
            ('lib.bob.creative_copy.apply', creative_copy_propose, [{'ad_group_id': '10', 'ad_id': '20', 'asset_id': '30',
                'action': 'replace', 'field_type': 'HEADLINE', 'current_text': 'Old', 'suggested_text': 'New',
                'rationale': 'Registered evidence supports replacement'}]),
        ):
            target = wiki/(propose.__name__+'.yaml')
            args = argparse.Namespace(plan=str(original), output=str(target), changes_json=json.dumps(changes))
            with patch(module+'.load_profile', return_value={'google_ads_customer_id': self.account}), \
                 patch(module+'.account_wiki_dir', return_value=wiki), contextlib.redirect_stdout(io.StringIO()):
                propose(args)
            self.assertEqual(original.read_bytes(), original_bytes)
            saved = yaml.safe_load(target.read_text())
            self.assertTrue(saved['decision_required'])
            self.assertFalse(saved['applied'])
            self.assertEqual(saved['baseline_changes'], [])
            self.assertNotIn('approved_hash', saved)

    def test_brief_returns_available_evidence_when_other_sections_are_missing(self):
        from unittest.mock import patch
        from lib.bob.brief import build_brief
        from lib.bob.performance.adhoc import PreparedDataset, DATASETS, AnalysisError
        import csv
        with self.path.open() as handle:
            rows = list(csv.DictReader(handle))
        prepared = PreparedDataset('dataset', DATASETS['campaign_network_period'], '2026-09-02', '2026-09-08', 'installs', tuple(rows))
        def prepare(dataset, *args):
            if dataset == 'change_history':
                raise AnalysisError('missing events')
            return prepared, {'source': str(self.path)}
        kt = self.root / 'wiki' / self.account / 'KT.md'
        kt.parent.mkdir(parents=True)
        kt.write_text('Account guidance.\n' * 1100)
        with patch('lib.bob.brief.selected_account', return_value=(self.account, {'primary_goal': 'installs'})), \
             patch('lib.bob.brief._prepare', side_effect=prepare), \
             patch('lib.bob.platform.core.STATE_ROOT', self.root):
            result = build_brief(focus='performance', period='2026-09-02:2026-09-08', offline=True)
        self.assertEqual(result['sections']['campaign_network_period:current']['status'], 'available')
        self.assertEqual(result['sections']['change_history:current']['status'], 'unavailable')
        self.assertEqual(result['fetches'], 0)
        self.assertEqual(result['account_rules'], kt.read_text())
        self.assertEqual(float(result['sections']['campaign_network_period:current']['account_totals'][0]['cpi']), 20)

    def test_mcp_decision_persists_transformed_result_and_its_inputs(self):
        from unittest.mock import patch
        from lib.bob.mcp.server import PREPARED, RESULTS, METHODS, bob_analyze, bob_record_decision
        from lib.bob.performance.adhoc import PreparedDataset, DATASETS
        source = PreparedDataset('test-source', DATASETS['campaign_network_period'], '2026-09-02', '2026-09-08',
                                 'installs', ({'customer_id': self.account, 'campaign_id': '1', 'cost': 400, 'installs': 20},))
        PREPARED[source.handle] = source
        result = bob_analyze('Cited data', {'source': source.handle}, [], 'source')
        with patch('lib.bob.performance.adhoc_data.selected_account', return_value=(self.account, {})), \
             patch('lib.bob.platform.core.STATE_ROOT', self.root):
            decision = bob_record_decision({'situation': 'Review efficiency', 'recommendation': 'Hold',
                'prediction': {'metric': 'cpi', 'direction': 'lower', 'baseline': 25, 'days': 7}}, [result['result_handle']])
        PREPARED.clear(); RESULTS.clear(); METHODS.clear()
        snapshot = json.loads(read(self.root, self.account, decision['evidence'][0]['sha256']))
        self.assertEqual(snapshot['inputs']['source']['rows'][0]['cost'], 400)
        self.assertEqual(snapshot['result']['rows'][0]['installs'], 20)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.account = '1234567890'
        self.source = f'data/processed/{self.account}/campaign-network/{self.account}_2026-09-02_2026-09-08.csv'
        self.path = self.root / self.source
        self.path.parent.mkdir(parents=True)
        self.path.write_text('customer_id,campaign_id,network,cost,installs,impressions,clicks,in_app_conversions\n'
                             f'{self.account},1,Search,100,5,1000,10,2\n'
                             f'{self.account},1,Display,300,15,3000,30,6\n')

    def record(self):
        return records.record(self.root, self.account, {
            'situation': 'Efficiency deteriorated', 'recommendation': 'Hold and inspect lag',
            'prediction': {'metric': 'cpi', 'direction': 'lower', 'baseline': 25, 'days': 7,
                           'entity': {'campaign_id': '1'}, 'review_date': '2026-09-11'},
            'evidence': [{'source': self.source, 'operation': {'grain': 'campaign_network_period'}}]})

    def test_evidence_survives_restart_and_reaggregation_and_search_recalls_it(self):
        decision = self.record()
        original = self.path.read_bytes()
        self.path.write_text('replacement')
        recalled = records.get(self.root, self.account, decision['decision_id'])
        self.assertEqual(read(self.root, self.account, recalled['evidence'][0]['sha256']), original)
        found = search(self.root, self.account, 'Efficiency', kind='decision')
        self.assertEqual(found[0]['path'], 'decision:' + decision['decision_id'])
        with self.assertRaisesRegex(ValueError, 'not found'):
            records.get(self.root, '999', decision['decision_id'])

    def test_search_recovers_saved_proposal_and_recalculates_missing_hash_offline(self):
        import contextlib
        import io
        import yaml
        from unittest.mock import patch
        from lib.bob.cli import build_parser
        directory = self.root / 'wiki' / self.account / 'action-items'
        directory.mkdir(parents=True)
        plan = {'customer_id': self.account, 'decision_id': 'recorded-decision',
                'changes': [{'campaign_id': '19', 'action': 'increase_bid', 'proposed_target_cpa': 110}],
                'applied': False, 'apply_results': [{'campaign_id': '18', 'status': 'applied'}]}
        path = directory / 'T3-final.yaml'
        path.write_text(yaml.safe_dump(plan))
        original = path.read_bytes()
        expected = plan_hash(plan)
        found = search(self.root, self.account, '-T3-', kind='action')
        self.assertEqual([row['path'] for row in found], [str(path.relative_to(self.root))])
        args = build_parser().parse_args(['bid-budget-validate', '--plan', str(self.root / found[0]['path'])])
        output = io.StringIO()
        with patch('lib.bob.bid_budget.load_profile', return_value={'google_ads_customer_id': self.account}), \
             patch('lib.bob.bid_budget._runtime_write_config_path', side_effect=AssertionError('must stay offline')), \
             contextlib.redirect_stdout(output):
            args.func(args)
        self.assertEqual(json.loads(output.getvalue())['plan_hash'], expected)
        self.assertFalse(json.loads(output.getvalue())['live_checked'])
        self.assertEqual(path.read_bytes(), original)
        plan['changes'][0]['proposed_target_cpa'] = 120
        self.assertNotEqual(plan_hash(plan), expected)

    def test_search_handles_hosted_shared_wiki_links(self):
        shared = self.root / 'shared' / 'wiki' / self.account
        shared.mkdir(parents=True)
        (shared / 'report.md').write_text('Unique report evidence')
        (shared / 'T3-final.yml').write_text(f'customer_id: "{self.account}"\nchanges: []\n')
        state = self.root / 'conversation-state'
        state.mkdir()
        (state / 'wiki').symlink_to(shared.parent, target_is_directory=True)
        found = search(state, self.account, 'T3', kind='action')
        self.assertEqual(found[0]['path'], f'wiki/{self.account}/T3-final.yml')
        self.assertTrue((state / found[0]['path']).is_file())
        self.assertEqual(search(state, self.account, 'Unique')[0]['path'], f'wiki/{self.account}/report.md')

    def test_proposal_search_excludes_foreign_malformed_and_external_files(self):
        directory = self.root / 'wiki' / self.account / 'action-items'
        directory.mkdir(parents=True)
        (directory / 'T3-foreign.yaml').write_text('customer_id: "999"\nchanges: []\n')
        (directory / 'T3-invalid.yaml').write_text('changes: [')
        (directory / 'T3-not-a-plan.yaml').write_text('message: notes\n')
        foreign = self.root / 'wiki' / '999'
        foreign.mkdir()
        (foreign / 'T3.md').write_text('T3 foreign account')
        escaped = self.root / 'T3-outside.yaml'
        escaped.write_text(f'customer_id: "{self.account}"\nchanges: []\n')
        (directory / 'T3-external.yaml').symlink_to(escaped)
        self.assertEqual(search(self.root, self.account, 'T3'), [])

    def test_review_uses_recorded_direction_maturity_and_summed_inputs(self):
        decision = self.record()
        records.update(self.root, self.account, decision['decision_id'], 'execution',
                       {'executed_at': '2026-09-01T12:00:00', 'complete': True})
        early = review(self.root, self.account, decision['decision_id'], self.source,
                       on_date=dt.date(2026, 9, 9))
        self.assertEqual(early['verdict'], 'inconclusive')
        result = review(self.root, self.account, decision['decision_id'], self.source,
                        on_date=dt.date(2026, 9, 12))
        self.assertEqual((result['verdict'], result['observed']), ('supported', 20))
        confounded = review(self.root, self.account, decision['decision_id'], self.source,
                            on_date=dt.date(2026, 9, 12), confounders=['Tracking changed'])
        self.assertEqual(confounded['verdict'], 'inconclusive')

    def test_recall_filters_entities_before_applying_the_limit(self):
        first = self.record()
        second = self.record()
        with records.database(self.root, self.account) as connection:
            other = dict(second, entities=['2'])
            connection.execute('UPDATE decisions SET record=? WHERE id=?', (json.dumps(other), second['decision_id']))
        found = records.recent(self.root, self.account, limit=1, entities=('1',))
        self.assertEqual(found[0]['decision_id'], first['decision_id'])

    def test_review_rejects_pre_action_windows_and_preserves_intent(self):
        decision = self.record()
        records.update(self.root, self.account, decision['decision_id'], 'execution',
                       {'executed_at': '2026-09-03'})
        with self.assertRaisesRegex(ValueError, 'exact execution-relative'):
            review(self.root, self.account, decision['decision_id'], self.source,
                   on_date=dt.date(2026, 9, 20))
        with self.assertRaisesRegex(ValueError, 'immutable'):
            records.update(self.root, self.account, decision['decision_id'], 'prediction', {})


class FinalPlanTests(unittest.TestCase):
    def test_undefined_budget_utilisation_is_not_reported_as_zero(self):
        from lib.bob.performance.adhoc import DATASETS, normalize_source_rows
        rows = normalize_source_rows(DATASETS['bid_budget_inputs'], [
            {'customer_id': '123', 'campaign_id': '1', 'daily_budget': '0', 'budget_utilization_pct': 'NA'}], '123')
        self.assertIsNone(rows[0]['budget_utilization_pct'])
    def test_mutation_checkpoint_preserves_success_and_marks_ambiguous_request(self):
        from types import SimpleNamespace
        import yaml
        from lib.bob.bid_budget import _mutate_checkpointed
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'plan.yaml'
            operation = SimpleNamespace(update=SimpleNamespace(resource_name='customers/123/campaigns/1'))
            operations = [('Campaign', '1', 'target_cpa', 110, operation)]
            prior = [{'campaign_id': '2', 'field': 'target_cpa', 'status': 'ok'},
                     {'campaign_id': '1', 'field': 'daily_budget', 'status': 'not_sent'}]
            def timeout(**kwargs):
                saved = yaml.safe_load(path.read_text())
                self.assertEqual(saved['apply_results'][-1]['status'], 'unknown')
                raise TimeoutError('response unavailable')
            results = _mutate_checkpointed(timeout, '123', operations, prior, {}, path)
            self.assertEqual([receipt['status'] for receipt in results], ['ok', 'not_sent', 'unknown'])
            self.assertEqual(yaml.safe_load(path.read_text())['apply_results'], results)

    def setUp(self):
        self.profile = {'google_ads_customer_id': '123', 'cac_ceiling': 200,
                        'bid_budget_change_pct': 10, 'bid_budget_cooldown_days': 14}
        self.live = {'1': CampaignState('1', True, 100, 1000, 50, 80, None, '2')}
        self.plan = {'customer_id': '123', 'changes': [{'campaign_id': '1', 'action': 'increase_bid',
                                                     'proposed_target_cpa': 110}]}

    def check(self):
        return validate_plan(self.plan, self.profile, self.live, on_date=dt.date(2026, 9, 20), permission='read_write')

    def test_changed_plan_is_checked_against_live_value_not_embedded_flags(self):
        self.assertTrue(self.check()[0].allowed)
        self.plan['changes'][0]['proposed_target_cpa'] = 150
        self.plan['changes'][0]['cac_guard_passed'] = True
        self.assertFalse(self.check()[0].allowed)
        self.plan['changes'][0].update(rationale='Evidence supports testing a larger step; risk is higher cost.',
                                       forecast='Review CPA after seven mature days.')
        self.assertTrue(self.check()[0].allowed)
        self.assertTrue(self.check()[0].warnings)
        self.plan['changes'][0]['proposed_target_cpa'] = float('nan')
        self.assertFalse(self.check()[0].allowed)

    def test_marketing_departures_need_explanation_but_disabled_targets_still_fail(self):
        for fields in ({'last_change': dt.date(2026, 9, 19)}, {'installs': 0},
                       {'actual_cpa': 300}):
            self.live['1'] = replace(CampaignState('1', True, 100, 1000, 50, 80, None, '2'), **fields)
            self.plan['changes'][0].pop('rationale', None)
            self.assertFalse(self.check()[0].allowed)
            self.plan['changes'][0].update(rationale='Cited evidence supports this experiment; risk discussed.',
                                           forecast='Review against prediction after seven days.')
            self.assertTrue(self.check()[0].allowed)
            self.assertTrue(self.check()[0].warnings)
        self.live['1'] = replace(self.live['1'], enabled=False)
        self.assertFalse(self.check()[0].allowed)

    def test_account_permission_duplicate_and_daily_cap_fail_closed(self):
        with self.assertRaises(PermissionError):
            validate_plan(self.plan, self.profile, self.live, on_date=dt.date(2026, 9, 20))
        self.plan['customer_id'] = '999'
        with self.assertRaises(ValueError):
            self.check()
        self.plan['customer_id'] = '123'
        self.plan['changes'] *= 2
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            self.check()
        self.plan['changes'] = self.plan['changes'][:1]
        self.profile['daily_change_cap'] = 0
        self.assertTrue(self.check()[0].allowed)

    def test_approval_hash_binds_values_but_not_execution_receipts(self):
        approved = plan_hash(self.plan)
        self.plan['apply_results'] = []
        self.assertEqual(plan_hash(self.plan), approved)
        self.plan['changes'][0]['proposed_target_cpa'] = 105
        self.assertNotEqual(plan_hash(self.plan), approved)

    def test_copy_names_and_duplicates_are_checked_but_style_is_advisory(self):
        self.assertEqual(validate_copy('Try the app', 'DESCRIPTION'), ())
        self.assertEqual(validate_copy('Try it!!', 'HEADLINE'), ())
        self.assertTrue(validate_copy('Explore a new place.', 'DESCRIPTION', protected_terms=('Landmark',)))
        self.assertTrue(validate_copy(' TRY IT ', 'HEADLINE', existing_good=('Try it',)))
        self.assertEqual(validate_copy('Try the app.', 'DESCRIPTION'), ())

    def test_creative_final_plan_rejects_changed_or_disabled_live_text(self):
        from lib.bob.creative_copy.rules import validate_plan as validate_copy_plan
        plan = {'customer_id': '123', 'changes': [{'ad_group_id': '10', 'ad_id': '20',
            'field_type': 'HEADLINE', 'action': 'replace', 'current_text': 'Old text', 'suggested_text': 'New text'}]}
        live = [{'ad_group_id': '10', 'ad_id': '20', 'enabled': True,
                 'headlines': ['Old text'], 'descriptions': []}]
        self.assertTrue(validate_copy_plan(plan, '123', live)[0]['allowed'])
        live[0]['headlines'] = ['Changed text']
        self.assertFalse(validate_copy_plan(plan, '123', live)[0]['allowed'])
        live[0].update(headlines=['Old text'], enabled=False)
        self.assertFalse(validate_copy_plan(plan, '123', live)[0]['allowed'])

    def test_excluded_campaign_and_shared_budget_are_protected(self):
        self.profile['goals'] = {'excluded_entities': ['1']}
        self.assertFalse(self.check()[0].allowed)
        self.profile['goals'] = {'excluded_entities': ['2']}
        self.live['2'] = CampaignState('2', True, 100, 1000, 50, 80, None, '2')
        self.plan['changes'][0].update(action='increase_bid_and_budget', campaign_budget_id='2', proposed_daily_budget=1100)
        verdict = self.check()[0]
        self.assertFalse(verdict.allowed)
        self.assertIn('budget change would affect an excluded campaign', verdict.reasons)

    def test_nonfinite_business_limits_fail_closed(self):
        self.profile['bid_budget_change_pct'] = float('nan')
        with self.assertRaisesRegex(ValueError, 'finite'):
            self.check()

    def test_live_copy_peers_and_protected_names_override_plan_assertions(self):
        from types import SimpleNamespace
        from lib.bob.creative_copy.rules import refresh_copy_evidence
        row = SimpleNamespace(ad_group=SimpleNamespace(id=10), asset=SimpleNamespace(text_asset=SimpleNamespace(text='Existing winner')),
            ad_group_ad_asset_view=SimpleNamespace(field_type=SimpleNamespace(name='HEADLINE'),
                                                   performance_label=SimpleNamespace(name='BEST')))
        service = SimpleNamespace(search=lambda **kwargs: [row])
        client = SimpleNamespace(get_service=lambda name: service)
        plan = {'changes': [{'ad_group_id': '10', 'field_type': 'HEADLINE', 'current_text': 'Visit Landmark', 'existing_good': []}]}
        refresh_copy_evidence(client, '123', plan, {'goals': {'protected_names': ['Landmark']}})
        self.assertEqual(plan['changes'][0]['existing_good'], ['Existing winner'])
        self.assertEqual(plan['changes'][0]['protected_terms'], ['Landmark'])
