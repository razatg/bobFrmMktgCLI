"""Partial execution keeps exact proposals and never resends a successful field."""
import argparse
import contextlib
import csv
import datetime as dt
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

import yaml

from lib.bob.bid_budget import bid_budget_apply, bid_budget_validate
from lib.bob.bid_budget.guards import CampaignState, plan_hash
from tests import test_core


class PartialBidApplyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fixture = test_core.TestCreativeCopyApply
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.account = '1234567890'
        self.wiki = self.root / 'wiki' / self.account
        self.wiki.mkdir(parents=True)
        self.path = self.wiki / 'T3.yaml'
        self.plan = {'customer_id': self.account, 'applied': False, 'changes': [
            {'campaign_id': str(cid), 'campaign_name': f'Campaign {cid}',
             'action': 'increase_bid_and_budget' if cid < 3 else 'increase_bid',
             'current_target_cpa': 100, 'proposed_target_cpa': 110,
             'campaign_budget_id': str(cid), 'proposed_daily_budget': 1100 if cid < 3 else None}
            for cid in range(1, 4)]}
        self.path.write_text(yaml.safe_dump(self.plan))
        self.approved_hash = plan_hash(self.plan)
        self.live = {str(cid): CampaignState(str(cid), True, 200 if cid == 2 else 100,
                    1000, None, None, None, str(cid)) for cid in range(1, 4)}
        self.reject_third = True
        self.bids = Mock(side_effect=self.mutate_bids)
        self.budgets = Mock(side_effect=lambda request: self.response(request))
        self.client = NS(get_service=self.service, get_type=self.protobuf)

    def response(self, request, reject=None):
        self.assertTrue(request['partial_failure'])
        errors = [] if reject is None else [NS(message='bid rejected by Google Ads',
            location=NS(field_path_elements=[NS(field_name='operations', index=reject)]))]
        return NS(results=[NS(resource_name='' if index == reject else op.update.resource_name)
                           for index, op in enumerate(request['operations'])],
                  partial_failure_error=NS(code=3 if errors else 0,
                    details=[NS(value=self.fixture.FakeGoogleAdsFailure(errors))] if errors else []))

    def mutate_bids(self, request):
        reject = next((i for i, op in enumerate(request['operations'])
                       if self.reject_third and op.update.resource_name.endswith('/3')), None)
        return self.response(request, reject)

    def service(self, name):
        if name == 'CampaignService':
            return NS(campaign_path=lambda account, cid: f'customers/{account}/campaigns/{cid}',
                      mutate_campaigns=self.bids)
        if name == 'CampaignBudgetService':
            return NS(campaign_budget_path=lambda account, bid: f'customers/{account}/campaignBudgets/{bid}',
                      mutate_campaign_budgets=self.budgets)
        raise AssertionError(name)

    def protobuf(self, name):
        if name == 'GoogleAdsFailure':
            return self.fixture.FakeGoogleAdsFailure()
        self.assertIn(name, {'CampaignOperation', 'CampaignBudgetOperation'})
        return NS(update=NS(resource_name='', target_cpa=NS(target_cpa_micros=0), amount_micros=0), update_mask=Mock())

    def apply(self):
        output = io.StringIO()
        with patch.dict(sys.modules, self.fixture()._modules(self.client)), \
             patch.dict('os.environ', {'BOB_ACCOUNT_PERMISSION': 'read_write'}), \
             patch('lib.bob.bid_budget._require_write_permission'), \
             patch('lib.bob.bid_budget._runtime_write_config_path', return_value=self.root / 'credentials.yaml'), \
             patch('lib.bob.bid_budget.load_profile', return_value={'google_ads_customer_id': self.account}), \
             patch('lib.bob.bid_budget.account_wiki_dir', return_value=self.wiki), \
             patch('lib.bob.bid_budget.guards.read_live_state', return_value=self.live), \
             contextlib.redirect_stdout(output):
            try:
                bid_budget_apply(argparse.Namespace(plan=str(self.path), approval_hash=self.approved_hash))
                code = 0
            except SystemExit as error:
                code = error.code
        return code, yaml.safe_load(self.path.read_text()), output.getvalue()

    def test_live_hold_and_api_failure_do_not_block_other_campaigns_and_retry_preserves_success(self):
        code, saved, output = self.apply()
        self.assertEqual(code, 2)
        results = {(r['campaign_id'], r['field']): r for r in saved['apply_results']}
        self.assertEqual(results['1', 'target_cpa']['status'], 'ok')
        self.assertEqual(results['1', 'daily_budget']['status'], 'ok')
        self.assertEqual(results['2', 'target_cpa']['status'], 'held')
        self.assertEqual(results['2', 'daily_budget']['status'], 'held')
        self.assertEqual(results['3', 'target_cpa']['status'], 'error')
        self.assertIn('saved=100, proposed=110, live=200', output)
        self.assertIn('bid rejected by Google Ads', output)
        self.assertFalse(saved['applied'])
        self.assertEqual(saved['changes'], self.plan['changes'])
        self.assertEqual(plan_hash(saved), self.approved_hash)
        review = self.path.with_suffix('.review.csv')
        with review.open() as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 3)
        self.assertIn('held', rows[1]['status'])
        self.assertIn('live=200', rows[1]['reason'])
        self.assertIn('[[artifact:wiki/1234567890/T3.review.csv|', output)
        self.live['2'] = CampaignState('2', True, 100, 1000, None, None, None, '2')
        self.reject_third = False
        code, retried, _ = self.apply()
        self.assertEqual(code, 0)
        self.assertTrue(retried['applied'])
        requested = [op.update.resource_name.rsplit('/', 1)[-1]
                     for op in self.bids.call_args.kwargs['request']['operations']]
        self.assertEqual(requested, ['2', '3'])
        requested_budgets = self.budgets.call_args.kwargs['request']['operations']
        self.assertEqual([op.update.resource_name.rsplit('/', 1)[-1] for op in requested_budgets], ['2'])
        self.assertEqual({r['status'] for r in retried['apply_results']}, {'ok'})

    def test_all_campaigns_held_sends_no_mutation(self):
        self.live = {}
        code, saved, _ = self.apply()
        self.assertEqual(code, 2)
        self.bids.assert_not_called()
        self.budgets.assert_not_called()
        self.assertFalse(saved['applied'])
        self.assertEqual({r['status'] for r in saved['apply_results']}, {'held'})

    def test_unmapped_provider_failure_stops_budget_and_cannot_be_retried_blindly(self):
        def ambiguous(request):
            response = self.response(request)
            response.partial_failure_error = NS(code=3, details=[])
            return response
        self.bids.side_effect = ambiguous
        code, saved, output = self.apply()
        self.assertEqual(code, 2)
        self.assertIn('unknown', {r['status'] for r in saved['apply_results']})
        self.assertIn('daily_budget: not sent;', output)
        self.budgets.assert_not_called()
        code, again, _ = self.apply()
        self.assertEqual(code, 1)
        self.assertEqual(again['apply_results'], saved['apply_results'])
        self.assertEqual(self.bids.call_count, 1)

    def test_changed_proposal_cannot_execute_with_earlier_approval(self):
        self.plan['changes'][0]['proposed_target_cpa'] = 120
        self.path.write_text(yaml.safe_dump(self.plan))
        before = self.path.read_bytes()
        code, _, _ = self.apply()
        self.assertEqual(code, 1)
        self.assertEqual(self.path.read_bytes(), before)
        self.bids.assert_not_called()
        self.budgets.assert_not_called()

    def test_offline_check_creates_review_without_changing_proposal_or_hash(self):
        before = self.path.read_bytes()
        output = io.StringIO()
        with patch('lib.bob.bid_budget.load_profile', return_value={'google_ads_customer_id': self.account}), \
             patch('lib.bob.bid_budget.account_wiki_dir', return_value=self.wiki), contextlib.redirect_stdout(output):
            bid_budget_validate(argparse.Namespace(plan=str(self.path)))
        result = json.loads(output.getvalue())
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(result['plan_hash'], self.approved_hash)
        self.assertFalse(result['live_checked'])
        self.assertTrue(Path(result['review']).is_file())

    def test_native_google_partial_failure_response_maps_to_exact_receipts(self):
        from google.ads.googleads.client import GoogleAdsClient
        from google.auth.credentials import AnonymousCredentials
        from google.protobuf.any_pb2 import Any
        from lib.bob.bid_budget import _mutate_checkpointed
        client = GoogleAdsClient(credentials=AnonymousCredentials(), developer_token='test', version='v23', use_proto_plus=True)
        operations = []
        response = client.get_type('MutateCampaignsResponse')
        for cid in ('1', '3'):
            operation = client.get_type('CampaignOperation')
            operation.update.resource_name = f'customers/{self.account}/campaigns/{cid}'
            operations.append((cid, cid, 'target_cpa', 110, operation))
            response.results.append({'resource_name': operation.update.resource_name if cid == '1' else ''})
        error = client.get_type('GoogleAdsError')
        error.message = 'Exact failed operation'
        error.location.field_path_elements.append({'field_name': 'operations', 'index': 1})
        failure = client.get_type('GoogleAdsFailure')
        failure.errors.append(error)
        response.partial_failure_error.code = 3
        response.partial_failure_error.details.append(Any(value=type(failure).serialize(failure)))
        results = _mutate_checkpointed(Mock(return_value=response), self.account, operations, [], {}, self.path, client)
        self.assertEqual([r['status'] for r in results], ['ok', 'error'])
        self.assertEqual(results[1]['error'], 'Exact failed operation')
