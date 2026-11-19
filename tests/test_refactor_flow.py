"""Exercise the evidence → decision → review boundary and unsafe proposals."""
import datetime as dt
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from lib.bob.answer_check import check_answer
from lib.bob.bid_budget.guards import CampaignState, plan_hash, validate_plan
from lib.bob.creative_copy.rules import validate_copy
from lib.bob.decisions import records
from lib.bob.decisions.evidence import read
from lib.bob.decisions.review import review
from lib.bob.search import search


class EvidenceFlowTests(unittest.TestCase):
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

    def test_departure_warnings_are_visible_in_the_review_answer(self):
        checked = check_answer(self.answer(answer='Review this proposal.', plans=[{'path': 'plan.yaml'}]),
                               self.root, self.account, proposal_validator=lambda plan: [
                                   {'allowed': True, 'warnings': ['change exceeds the usual adjustment']}])
        self.assertIn('change exceeds the usual adjustment', checked.answer)

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
        with patch('lib.bob.brief.selected_account', return_value=(self.account, {'primary_goal': 'installs'})), \
             patch('lib.bob.brief._prepare', side_effect=prepare), \
             patch('lib.bob.platform.core.STATE_ROOT', self.root):
            result = build_brief(focus='performance', period='2026-09-02:2026-09-08', offline=True)
        self.assertEqual(result['sections']['campaign_network_period:current']['status'], 'available')
        self.assertEqual(result['sections']['change_history:current']['status'], 'unavailable')
        self.assertEqual(result['fetches'], 0)
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

    def answer(self, **changes):
        claim = {'entity': {'campaign_id': '1'}, 'metric': 'cpi',
                 'period': ['2026-09-02', '2026-09-08'], 'value': 20, 'source': self.source}
        envelope = {'account': self.account, 'answer': 'Campaign CPI is 20.', 'claims': [claim]}
        envelope.update(changes)
        return json.dumps(envelope)

    def test_claim_recomputes_cpi_across_networks(self):
        checked = check_answer(self.answer(), self.root, self.account)
        self.assertFalse(checked.blocked)
        self.assertEqual(checked.warnings, ())
        self.assertEqual(checked.answer, 'Campaign CPI is 20.')

    def test_wrong_unclaimed_and_wrong_period_figures_are_flagged(self):
        for envelope in (self.answer(answer='Campaign CPI is 80.'),
                         self.answer(claims=[]),
                         self.answer(claims=[{'entity': {}, 'metric': 'cost', 'value': 400,
                                              'source': self.source, 'period': ['2026-09-01', '2026-09-08']}])):
            self.assertTrue(check_answer(envelope, self.root, self.account).warnings)

    def test_foreign_account_and_foreign_rows_are_held(self):
        self.assertTrue(check_answer(self.answer(account='999'), self.root, self.account).blocked)
        self.path.write_text(self.path.read_text().replace(self.account, '999'))
        self.assertTrue(check_answer(self.answer(), self.root, self.account).blocked)

    def test_plain_text_is_compatible_but_not_falsely_verified(self):
        self.assertEqual(check_answer('I recommend waiting.', self.root, self.account).warnings, ())
        self.assertTrue(check_answer('CPI is 20.', self.root, self.account).warnings)

    def test_source_escape_is_not_accepted(self):
        envelope = json.loads(self.answer())
        envelope['claims'][0]['source'] = '/etc/passwd'
        self.assertTrue(check_answer(json.dumps(envelope), self.root, self.account).warnings)

    def test_denied_proposal_is_not_shown_as_an_approval_table(self):
        raw = self.answer(answer='Increase this budget.', plans=[{'path': 'plan.yaml', 'kind': 'bid_budget'}])
        checked = check_answer(raw, self.root, self.account,
                               proposal_validator=lambda plan: [{'allowed': False, 'reasons': ['step cap']}])
        self.assertNotIn('Increase this budget.', checked.answer)
        self.assertIn('did not pass validation', checked.answer)

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

    def test_copy_names_punctuation_and_peer_duplicates(self):
        self.assertTrue(validate_copy('Try the app', 'DESCRIPTION'))
        self.assertTrue(validate_copy('Try it!!', 'HEADLINE'))
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
        with self.assertRaisesRegex(ValueError, 'excluded campaign'):
            self.check()

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
