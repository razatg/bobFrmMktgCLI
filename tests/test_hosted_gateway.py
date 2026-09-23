"""Phase 1 gateway tests; the agent process is replaced with a deterministic fake."""
import os
import json
import subprocess
import sys
import tempfile
from urllib.parse import parse_qs, urlparse
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]

class FakeRunner:
    def __init__(self):
        self.calls = []
    async def run(self, backend, session_id, prompt, workspace, policy, emit, cancel_event=None):
        user_prompt = prompt.split('User message:\n', 1)[1] if 'User message:\n' in prompt else prompt
        self.calls.append({
            'backend': backend,
            'session_id': session_id,
            'prompt': prompt,
            'user_prompt': user_prompt,
            'workspace': str(workspace),
            'environment': dict(policy.environment or {}),
        })
        await emit({'type':'thread.started','thread_id':session_id or 'thread-one'})
        await emit({'type':'command','message':'fake bob command'})
        return (session_id or 'thread-one', f'Bob received: {user_prompt}')

class FetchRunner(FakeRunner):
    async def run(self, backend, session_id, prompt, workspace, policy, emit, cancel_event=None):
        await emit({'type':'bob.error','code':'GOOGLE_AUTH_REQUIRED'})
        raise RuntimeError('Google Ads authorization is required')

class UnrelatedFetchFailureRunner(FakeRunner):
    async def run(self, backend, session_id, prompt, workspace, policy, emit, cancel_event=None):
        await emit({'type':'item.completed','item':{'type':'command_execution','command':'./bob fetch --query account_daily && git push && printf write apply','status':'failed'}})
        raise RuntimeError('query file is invalid')

class OffScopeRunner(FakeRunner):
    async def run(self, backend, session_id, prompt, workspace, policy, emit, cancel_event=None):
        user_prompt = prompt.split('User message:\n', 1)[1] if 'User message:\n' in prompt else prompt
        self.calls.append({
            'backend': backend,
            'session_id': session_id,
            'prompt': prompt,
            'user_prompt': user_prompt,
            'workspace': str(workspace),
            'environment': dict(policy.environment or {}),
        })
        await emit({'type':'command','message':'fake bob command'})
        return (session_id or 'thread-one', '[[BOB_OUT_OF_SCOPE]] Outside Bob scope.')

class TimeoutRunner(FakeRunner):
    async def run(self, *args, **kwargs):
        raise RuntimeError('agent timed out after 600 seconds')

class SlowRunner(FakeRunner):
    async def run(self, *args, **kwargs):
        import asyncio
        await asyncio.sleep(.25)
        return await super().run(*args, **kwargs)

class UsageRunner(FakeRunner):
    async def run(self, backend, session_id, prompt, workspace, policy, emit, cancel_event=None):
        self.calls.append({'backend':backend,'session_id':session_id,'prompt':prompt,
                           'workspace':str(workspace),'environment':dict(policy.environment or {})})
        cumulative = 1100 if session_id else 600
        await emit({'type':'thread.started','thread_id':session_id or 'usage-thread'})
        await emit({'type':'turn.completed','usage':{
            'input_tokens':cumulative,'cached_input_tokens':cumulative // 2,'output_tokens':100,
        },'large_ignored_field':'x' * 100_000})
        return (session_id or 'usage-thread', 'Usage response')

class CustomAnalysisRunner(FakeRunner):
    async def run(self, backend, session_id, prompt, workspace, policy, emit, cancel_event=None):
        await emit({'type':'thread.started','thread_id':session_id or 'analysis-thread'})
        await emit({'type':'item.completed','item':{
            'type':'mcp_tool_call','server':'bob','tool':'bob_data_catalog','status':'completed',
            'arguments':{},
        }})
        await emit({'type':'item.completed','item':{
            'type':'mcp_tool_call','server':'bob','tool':'bob_analyze','status':'completed',
            'arguments':{'analysis_name':'Ad-group CPM anomalies','operations':['private']},
        }})
        return (session_id or 'analysis-thread', 'Two ad groups need review.')

class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=str(Path(self.tmp.name)/'metadata.sqlite3')
        self.workspace=str(Path(self.tmp.name)/'workspace')
        self.env=patch.dict(os.environ, {'BOB_METADATA_DB':self.db,'BOB_STATE_ROOT':self.workspace,'BOB_SECRET_ROOT':str(Path(self.tmp.name)/'secrets'),'ADMIN_BOOTSTRAP_SECRET':'test-bootstrap','ADMIN_IDENTIFIER':'','ADMIN_PASSWORD':''}, clear=False)
        self.env.start()
        from server.app import app
        self.app=app; self.client=TestClient(app); self.client.__enter__(); self.app.state.runner=FakeRunner()
    def tearDown(self):
        self.client.__exit__(None,None,None); self.env.stop(); self.tmp.cleanup()
    def bootstrap(self):
        r=self.client.post('/auth/bootstrap',json={'secret':'test-bootstrap','identifier':'admin','password':'a-secure-password','client_name':'Test Client'})
        self.assertEqual(r.status_code,200,r.text); return r.json()['csrf']

    def test_user_response_hides_internal_steps_but_allows_explicit_technical_help(self):
        from server.app import sanitize_user_response
        internal='''I will retrieve the spend.\n```sh\n./bob fetch --query campaign_daily\n```\n[Ownly W35 Analysis](/data/client/runtime/conversations/demo/workspace/wiki/1112223333/analyses/ownly-w35.md)\nCSV: wiki/1112223333/action-items/plan.csv\nInternal: wiki/1112223333/action-items/plan.yaml\nSee /data/client/logs/pull-log.jsonl.'''
        shown=sanitize_user_response(internal,customer_id='111-222-3333')
        self.assertNotIn('./bob',shown)
        self.assertNotIn('/data/client',shown)
        self.assertIn('I will retrieve the spend.',shown)
        self.assertIn('[[artifact:wiki/1112223333/analyses/ownly-w35.md|Ownly W35 Analysis]]',shown)
        self.assertIn('[[artifact:wiki/1112223333/action-items/plan.csv|Plan]]',shown)
        self.assertNotIn('plan.yaml',shown)
        blocked=sanitize_user_response('wiki/9998887777/secret.md',customer_id='1112223333')
        self.assertEqual(blocked,'[artifact unavailable]')
        technical=sanitize_user_response(internal,technical=True)
        self.assertNotIn('/data/client',technical)
        self.assertIn('./bob fetch',technical)
    def test_health_and_bootstrap_login(self):
        self.assertEqual(self.client.get('/api/health').json(),{'status':'ok'})
        csrf=self.bootstrap(); self.assertTrue(csrf)
        self.assertTrue(self.client.get('/auth/session').json()['authenticated'])
        self.client.post('/auth/logout',headers={'X-CSRF-Token':csrf})
        self.assertFalse(self.client.get('/auth/session').json()['authenticated'])

    def test_admin_data_explorer_is_read_only_and_blocks_sensitive_paths(self):
        csrf=self.bootstrap()
        raw=Path(self.workspace)/'runtime'/'conversations'/'demo'/'state'/'garf'/'outputs'/'raw'/'demo.csv'
        raw.parent.mkdir(parents=True,exist_ok=True); raw.write_text('asset_id,asset_name\n1,Headline\n')
        listed=self.client.get('/api/admin/data-explorer?kind=raw',headers={'X-CSRF-Token':csrf})
        self.assertEqual(listed.status_code,200,listed.text); self.assertTrue(any(x['path'].endswith('demo.csv') for x in listed.json()['files']))
        shown=self.client.get('/api/admin/data-explorer/file?path='+str(raw.relative_to(self.workspace)),headers={'X-CSRF-Token':csrf})
        self.assertEqual(shown.json()['content'],'asset_id,asset_name\n1,Headline\n')
        secret=Path(self.workspace)/'secrets'/'x.txt'; secret.parent.mkdir(); secret.write_text('nope')
        self.assertEqual(self.client.get('/api/admin/data-explorer/file?path=secrets/x.txt',headers={'X-CSRF-Token':csrf}).status_code,404)

    def test_account_knowledge_is_separate_and_editable(self):
        csrf=self.bootstrap(); s=self.app.state.store
        client_id=s.one('SELECT id FROM client_instances')['id']
        s.run('INSERT INTO client_accounts (id,client_instance_id,customer_id,account_name,is_active,created_at) VALUES (?,?,?,?,?,?)',('account-kt','%s'%client_id,'1234567890','Demand account',1,'2026-08-31T00:00:00+00:00'))
        shown=self.client.get('/api/account-knowledge?customer_id=123-456-7890')
        self.assertEqual(shown.status_code,200,shown.text)
        self.assertIn('specific to this Google Ads account',shown.json()['content'])
        updated='# Account Knowledge\n\n- FTU means first-time user for this account.\n'
        saved=self.client.put('/api/account-knowledge',headers={'X-CSRF-Token':csrf},json={'customer_id':'1234567890','content':updated})
        self.assertEqual(saved.status_code,200,saved.text)
        self.assertEqual(self.client.get('/api/account-knowledge?customer_id=1234567890').json()['content'],updated)

    def test_admin_can_readd_orphaned_user(self):
        csrf=self.bootstrap(); s=self.app.state.store
        client_id=s.one('SELECT id FROM client_instances')['id']; orphan='orphan@example.com'
        s.run('INSERT INTO users VALUES (?,?,?,?,?,?,?,?)',('orphan-id',orphan,'old-hash','member','approved',0,'2026-01-01T00:00:00+00:00',None))
        response=self.client.post(f'/api/admin/clients/{client_id}/users',headers={'X-CSRF-Token':csrf},json={'identifier':orphan,'password':'a-new-secure-password'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertTrue(response.json()['reused_orphan'])
        self.assertIsNotNone(s.one('SELECT 1 FROM client_memberships WHERE user_id=? AND client_instance_id=?',('orphan-id',client_id)))

    def test_selected_account_prompt_has_compact_knowledge_rule(self):
        from server.app import scope_wrapped_prompt
        prompt=scope_wrapped_prompt('What does GSR2Net mean?',client_instance_id='client-one',account_customer_id='1234567890')
        self.assertIn('account KT is at wiki/1234567890/KT.md',prompt)
        self.assertNotIn('client KT',prompt)
        self.assertIn('AUTHORITATIVE CURRENT ACCOUNT:',prompt)
        self.assertNotIn('MANAGEMENT',prompt)
        self.assertIn('Ask one focused clarification',prompt)
        self.assertIn('KT campaign exclusions are authoritative',prompt)
        self.assertIn('Do not repeat a prior failure solely from native-thread context',prompt)

    def test_admin_observability_is_lightweight_and_reads_history(self):
        csrf=self.bootstrap()
        with patch.dict(os.environ, {'BOB_THREAD_HANDOFF_INPUT_TOKENS':'5000000'}):
            live=self.client.get('/api/admin/observability',headers={'X-CSRF-Token':csrf})
        self.assertEqual(live.status_code,200,live.text)
        self.assertEqual(live.json()['active_job'],None)
        self.assertEqual(live.json()['thread_handoff'],{'input_tokens':5000000,'source':'environment'})
        updated=self.client.patch('/api/admin/runtime-settings',headers={'X-CSRF-Token':csrf},json={'thread_handoff_input_tokens':7500000})
        self.assertEqual(updated.status_code,200,updated.text)
        self.assertEqual(updated.json(),{'input_tokens':7500000,'source':'admin'})
        self.assertEqual(self.app.state.store.thread_handoff_override(),7500000)
        rejected=self.client.patch('/api/admin/runtime-settings',headers={'X-CSRF-Token':csrf},json={'thread_handoff_input_tokens':-1})
        self.assertEqual(rejected.status_code,400,rejected.text)
        from server import app as app_module
        with patch.object(app_module,'runtime_log_path',return_value=Path(self.workspace)/'logs'/'bob-runtime.jsonl'):
            log=Path(self.workspace)/'logs'/'bob-runtime.jsonl'; log.parent.mkdir(parents=True,exist_ok=True)
            log.write_text(json.dumps({'ts':'2026-08-29T10:00:00+00:00','event':'job_resource_summary','job_id':'job-a','status':'failed','peak_bytes':123,'oom_kill_count':1})+'\n')
            history=self.client.get('/api/admin/observability/history?from=2026-08-29&to=2026-08-29',headers={'X-CSRF-Token':csrf})
        self.assertEqual(history.status_code,200,history.text); self.assertEqual(history.json()[0]['job_id'],'job-a')

    def test_agent_info_is_dynamic(self):
        self.bootstrap()
        accounts = [{'account_name': 'Demo Account', 'google_ads_customer_id': '123-456-7890', 'active': True}]
        state = Path(self.workspace) / '.bob'
        state.mkdir(parents=True, exist_ok=True)
        (state / 'accounts.json').write_text(json.dumps(accounts))
        info = self.client.get('/api/agent-info')
        self.assertEqual(info.status_code, 200, info.text)
        self.assertEqual(info.json()['client_name'], 'Test Client')
        self.assertEqual(info.json()['account_name'], 'Demo Account')
        self.assertEqual(info.json()['model'], 'CODEX / gpt-5.6-luna')
        self.assertEqual(info.json()['name'], 'BOB')
        self.assertEqual(info.json()['role'], 'SENIOR PERFORMANCE MARKETING LEAD')
        self.assertEqual(info.json()['photo_url'], '/static/assets/bob-agent-card.png')
        self.assertIn('.-""""""""-.', info.json()['ascii'])
    def test_invite_authorization_and_conversation_resume(self):
        csrf=self.bootstrap()
        invite=self.client.post('/api/admin/invites',headers={'X-CSRF-Token':csrf},json={}).json()['code']
        redeemed=self.client.post('/auth/invite/redeem',json={'code':invite,'identifier':'member','password':'another-secure-password'})
        self.assertEqual(redeemed.status_code,200,redeemed.text)
        member_csrf=redeemed.json()['csrf']; member_id=self.app.state.store.one('SELECT id FROM users WHERE email_or_identifier=?',('member',))['id']
        client_id=self.app.state.store.one('SELECT id FROM client_instances')['id']; stamp='2026-08-31T00:00:00+00:00'
        self.app.state.store.run('INSERT INTO google_ads_connections VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',('connection',member_id,client_id,None,None,'secret:refresh','scope','connected',stamp,None,stamp,stamp))
        conversation=self.client.post('/api/conversations',headers={'X-CSRF-Token':member_csrf}).json()['id']
        job=self.client.post(f'/api/conversations/{conversation}/messages',headers={'X-CSRF-Token':member_csrf},json={'content':'hello'}).json()['job_id']
        import time; time.sleep(.05)
        events=self.client.get(f'/api/jobs/{job}/events').text
        self.assertIn('COMPLETED',events); self.assertNotIn('Bob received: hello',events)
        data=self.client.get(f'/api/conversations/{conversation}').json()
        self.assertEqual(data['conversation']['agent_session_id'],'thread-one')
        self.assertIn('Bob received: hello',data['messages'][-1]['content'])
        self.assertIn('You are Bob for this workspace only.', self.app.state.runner.calls[0]['prompt'])
        self.assertIn('Google Ads connection: connected',self.app.state.runner.calls[0]['prompt'])

    def test_token_threshold_retires_thread_and_next_job_gets_bounded_handoff(self):
        csrf=self.bootstrap(); self.app.state.runner=UsageRunner()
        self.app.state.store.set_thread_handoff_override(1000)
        with patch.dict(os.environ, {'BOB_THREAD_HANDOFF_INPUT_TOKENS':'999999999'}):
            conversation=self.client.post('/api/conversations',headers={'X-CSRF-Token':csrf}).json()['id']
            first=self.client.post(f'/api/conversations/{conversation}/messages',headers={'X-CSRF-Token':csrf},json={'content':'first report'}).json()['job_id']
            import time; time.sleep(.05)
            first_job=self.client.get(f'/api/jobs/{first}').json()
            first_conversation=self.client.get(f'/api/conversations/{conversation}').json()['conversation']
            self.assertEqual(first_job['input_tokens_estimate'],600)
            self.assertEqual(first_conversation['agent_session_id'],'usage-thread')
            self.assertEqual(first_conversation['thread_input_tokens_estimate'],600)

            second=self.client.post(f'/api/conversations/{conversation}/messages',headers={'X-CSRF-Token':csrf},json={'content':'second report'}).json()['job_id']
            time.sleep(.05)
            second_job=self.client.get(f'/api/jobs/{second}').json()
            retired=self.client.get(f'/api/conversations/{conversation}').json()['conversation']
            self.assertEqual(second_job['input_tokens_estimate'],500)
            self.assertIsNone(retired['agent_session_id'])
            self.assertEqual(retired['thread_input_tokens_estimate'],0)
            sessions=self.client.get('/api/admin/codex-sessions',headers={'X-CSRF-Token':csrf}).json()
            second_session=next(item for item in sessions if item['job_id']==second)
            self.assertEqual(second_session['agent_session_id'],'usage-thread')

            third=self.client.post(f'/api/conversations/{conversation}/messages',headers={'X-CSRF-Token':csrf},json={'content':'third report'}).json()['job_id']
            time.sleep(.05)
            third_job=self.client.get(f'/api/jobs/{third}').json()
            self.assertEqual(third_job['input_tokens_estimate'],600)
            call=self.app.state.runner.calls[-1]
            self.assertIsNone(call['session_id'])
            self.assertIn('CONTINUITY FROM THE PREVIOUS CODEX THREAD',call['prompt'])
            self.assertIn('User: first report',call['prompt'])
            self.assertIn('Assistant: Usage response',call['prompt'])
            self.assertLessEqual(len(call['prompt'].split('User message:\n',1)[0].encode()),15 * 1024)

            stored_events=self.client.get(f'/api/admin/codex-sessions/{third}/events',headers={'X-CSRF-Token':csrf}).json()
            usage_event=next(event for event in stored_events if event['payload'].get('type')=='turn.completed')
            self.assertEqual(usage_event['payload']['usage']['input_tokens'],600)
            self.assertNotIn('large_ignored_field',usage_event['payload'])
            terminal=stored_events[-1]['payload']
            self.assertNotIn('response',terminal)
            self.assertIn('message_id',terminal)

    def test_invite_redeem_grants_all_active_client_accounts_as_read(self):
        admin_csrf=self.bootstrap(); s=self.app.state.store
        client_id=s.one('SELECT id FROM client_instances')['id']
        created='2026-08-31T00:00:00+00:00'
        s.run('INSERT INTO client_accounts (id,client_instance_id,customer_id,account_name,is_active,created_at) VALUES (?,?,?,?,?,?)',('one',client_id,'1111111111','First account',1,created))
        s.run('INSERT INTO client_accounts (id,client_instance_id,customer_id,account_name,is_active,created_at) VALUES (?,?,?,?,?,?)',('two',client_id,'2222222222','Second account',1,created))
        s.run('INSERT INTO client_accounts (id,client_instance_id,customer_id,account_name,is_active,created_at) VALUES (?,?,?,?,?,?)',('off',client_id,'3333333333','Inactive account',0,created))
        invite=self.client.post('/api/admin/invites',headers={'X-CSRF-Token':admin_csrf},json={'max_uses':2}).json()['code']
        redeemed=self.client.post('/auth/invite/redeem',json={'code':invite,'identifier':'member@example.com','password':'another-secure-password'})
        self.assertEqual(redeemed.status_code,200,redeemed.text)
        self.assertEqual(redeemed.json()['redirect'],'chat')
        uid=s.one('SELECT id FROM users WHERE email_or_identifier=?',('member@example.com',))['id']
        access=s.all('SELECT account_id,permission FROM user_account_access WHERE user_id=? ORDER BY account_id',(uid,))
        self.assertEqual([(x['account_id'],x['permission']) for x in access],[('one','read'),('two','read')])
        self.assertEqual([x['account_name'] for x in self.client.get('/api/accounts').json()],['First account','Second account'])
        second=self.client.post('/auth/invite/redeem',json={'code':invite,'identifier':'second@example.com','password':'another-secure-password'})
        self.assertEqual(second.status_code,200,second.text)
        third=self.client.post('/auth/invite/redeem',json={'code':invite,'identifier':'third@example.com','password':'another-secure-password'})
        self.assertEqual(third.status_code,400)

    def test_failed_job_has_explicit_error_and_central_runtime_log(self):
        csrf=self.bootstrap(); self.app.state.runner=TimeoutRunner()
        conversation=self.client.post('/api/conversations',headers={'X-CSRF-Token':csrf}).json()['id']
        job=self.client.post(f'/api/conversations/{conversation}/messages',headers={'X-CSRF-Token':csrf},json={'content':'run a report'}).json()['job_id']
        import time; time.sleep(.05)
        events=self.client.get(f'/api/jobs/{job}/events').text
        self.assertIn('FAILED',events); self.assertIn('agent timed out after 600 seconds',events)
        stored=self.client.get(f'/api/jobs/{job}').json()
        self.assertEqual(stored['error'],'agent timed out after 600 seconds')
        log=(Path(self.db).parent/'logs'/'bob-runtime.jsonl').read_text()
        self.assertIn('job_failed',log); self.assertIn(job,log)
    def test_csrf_and_workspace_isolation(self):
        self.bootstrap(); self.assertEqual(self.client.post('/api/conversations').status_code,403)
        # A path traversal cannot escape the configured wiki root.
        from server.app import safe_wiki_path
        with self.assertRaises(Exception): safe_wiki_path('../outside')

    def test_bob_state_paths_follow_persistent_client_root(self):
        script = (
            "from lib.bob.platform.core import STATE_ROOT, ACCOUNTS_DIR, PROCESSED_DIR, account_wiki_dir; "
            "print(STATE_ROOT); print(ACCOUNTS_DIR); print(PROCESSED_DIR); "
            "print(account_wiki_dir('123-456-7890'))"
        )
        env = dict(os.environ, BOB_STATE_ROOT=self.workspace)
        paths = subprocess.check_output(
            [sys.executable, "-c", script], cwd=ROOT, env=env, text=True
        ).splitlines()
        workspace = Path(self.workspace).resolve()
        self.assertEqual(paths, [
            str(workspace),
            str(workspace / '.bob' / 'accounts'),
            str(workspace / 'data' / 'processed'),
            str(workspace / 'wiki' / '1234567890'),
        ])

    def test_codex_prompt_uses_conversation_account_not_typed_account(self):
        from server.app import prompt_for_selected_account
        s=self.app.state.store; admin_csrf=self.bootstrap(); client_id=s.one('SELECT id FROM client_instances')['id']
        s.run('INSERT INTO client_accounts (id,client_instance_id,customer_id,account_name,is_active,created_at) VALUES (?,?,?,?,?,?)',('primary',client_id,'1112223333','Primary Account',1,'2026-08-24T00:00:00+00:00'))
        s.run('INSERT INTO client_accounts (id,client_instance_id,customer_id,account_name,is_active,created_at) VALUES (?,?,?,?,?,?)',('secondary',client_id,'4445556666','Secondary Account',1,'2026-08-24T00:00:00+00:00'))
        row={'account_id':'primary','client_instance_id':client_id}
        internal=prompt_for_selected_account(s,row,'What happened in Secondary Account?')
        self.assertEqual(internal,'What happened in another account?')

    def test_admin_google_config_and_user_oauth_connection(self):
        admin_csrf=self.bootstrap()
        configured=self.client.post('/api/admin/google-ads/config',headers={'X-CSRF-Token':admin_csrf},json={
            'developer_token':'dev-token','mcc_id':'123-456-7890',
            'oauth_client_json':{'web':{'client_id':'client-id','client_secret':'client-secret'}}})
        self.assertEqual(configured.status_code,200,configured.text)
        self.assertEqual(configured.json()['mcc_id'],'1234567890')
        self.assertNotIn('dev-token',configured.text)
        invite=self.client.post('/api/admin/invites',headers={'X-CSRF-Token':admin_csrf},json={}).json()['code']
        member=self.client.post('/auth/invite/redeem',json={'code':invite,'identifier':'member@example.com','password':'another-secure-password'})
        member_csrf=member.json()['csrf']
        self.assertFalse(self.client.get('/auth/session').json()['google_connected'])
        start=self.client.post('/api/google-ads/oauth/start',headers={'X-CSRF-Token':member_csrf})
        self.assertEqual(start.status_code,200,start.text)
        query=parse_qs(urlparse(start.json()['authorization_url']).query)
        self.assertEqual(query['scope'],['https://www.googleapis.com/auth/adwords'])
        self.assertEqual(query['access_type'],['offline'])
        from server import app as app_module
        with patch.object(app_module,'exchange_google_code',return_value={'refresh_token':'user-refresh','scope':'https://www.googleapis.com/auth/adwords'}):
            callback=self.client.get('/api/google-ads/oauth/callback',params={'code':'auth-code','state':query['state'][0]})
        self.assertEqual(callback.status_code,200,callback.text)
        self.assertTrue(self.client.get('/auth/session').json()['google_connected'])
        connection=self.app.state.store.one('SELECT * FROM google_ads_connections')
        self.assertEqual(connection['status'],'connected')
        self.assertEqual(self.app.state.secrets.get(connection['refresh_token_ref']),'user-refresh')
        from server.app import prepare_conversation_runtime, runtime_google_config
        client_id=self.app.state.store.one('SELECT id FROM client_instances')['id']
        _, runtime_state = prepare_conversation_runtime('test-conversation')
        runtime_path=runtime_google_config(self.app.state.store,connection['user_id'],client_id,runtime_state)
        runtime_text=Path(runtime_path).read_text()
        self.assertIn('refresh_token: "user-refresh"',runtime_text)
        self.assertIn('use_proto_plus: true',runtime_text)
        self.assertNotIn('dev-token',configured.text)
        registry=(runtime_state / '.bob' / 'accounts.json')
        self.assertTrue(registry.exists())
        self.assertFalse((Path(self.workspace) / '.bob' / 'accounts.json').exists())

    def test_admin_account_permission_grant_and_revoke(self):
        admin_csrf=self.bootstrap(); s=self.app.state.store
        client_id=s.one('SELECT id FROM client_instances')['id']
        account_id='account-one'; s.run('INSERT INTO client_accounts (id,client_instance_id,customer_id,account_name,is_active,created_at) VALUES (?,?,?,?,?,?)',(account_id,client_id,'1112223333','Demo Demand',1,'2026-08-24T00:00:00+00:00'))
        invite=self.client.post('/api/admin/invites',headers={'X-CSRF-Token':admin_csrf},json={}).json()['code']
        member=self.client.post('/auth/invite/redeem',json={'code':invite,'identifier':'member','password':'another-secure-password'})
        uid=s.one('SELECT id FROM users WHERE email_or_identifier=?',('member',))['id']
        admin_login=self.client.post('/auth/login',json={'identifier':'admin','password':'a-secure-password'})
        admin_csrf=admin_login.json()['csrf']
        grant=self.client.post(f'/api/admin/users/{uid}/accounts/{account_id}/grant',headers={'X-CSRF-Token':admin_csrf},json={'permission':'read_write'})
        self.assertEqual(grant.status_code,200,grant.text)
        self.assertEqual(s.one('SELECT permission FROM user_account_access WHERE user_id=? AND account_id=?',(uid,account_id))['permission'],'read_write')
        rejected=self.client.post(f'/api/admin/users/{uid}/accounts/{account_id}/grant',headers={'X-CSRF-Token':admin_csrf},json={'permission':'mutate'})
        self.assertEqual(rejected.status_code,400)
        revoke=self.client.post(f'/api/admin/users/{uid}/accounts/{account_id}/revoke',headers={'X-CSRF-Token':admin_csrf})
        self.assertEqual(revoke.status_code,200,revoke.text)
        self.assertIsNone(s.one('SELECT 1 FROM user_account_access WHERE user_id=? AND account_id=?',(uid,account_id)))

    def test_conversation_runtime_materializes_image_files_without_code_symlinks(self):
        from server import app as app_module

        runtime_root = Path(self.workspace)
        workspace = runtime_root / 'runtime' / 'conversations' / 'sandbox-safe' / 'workspace'
        (workspace / 'garf').mkdir(parents=True, exist_ok=True)
        # Reproduce the layout created by earlier releases so upgrades also
        # prove that stale writable-to-read-only symlinks are replaced.
        (workspace / '.agents').symlink_to(app_module.ROOT / '.agents', target_is_directory=True)
        (workspace / 'bob').symlink_to(app_module.ROOT / 'bob')
        (workspace / 'garf' / 'queries').symlink_to(app_module.ROOT / 'garf' / 'queries', target_is_directory=True)

        with patch.object(app_module, 'STATE_ROOT', runtime_root):
            prepared, state_root = app_module.prepare_conversation_runtime('sandbox-safe')

        self.assertEqual(prepared, workspace)
        self.assertFalse((prepared / '.agents').is_symlink())
        self.assertTrue((prepared / '.agents' / 'skills').is_dir())
        self.assertFalse((prepared / 'AGENTS.md').is_symlink())
        self.assertFalse((prepared / 'garf' / 'queries').is_symlink())
        self.assertFalse((prepared / 'bob').is_symlink())
        self.assertTrue(os.access(prepared / 'bob', os.X_OK))
        self.assertIn(str(app_module.ROOT / 'bob'), (prepared / 'bob').read_text())
        self.assertTrue((prepared / '.bob').is_symlink())
        self.assertEqual((prepared / '.bob').resolve(), (state_root / '.bob').resolve())
        self.assertFalse((prepared / 'logs').exists())
        self.assertTrue((state_root / 'logs').is_symlink())

    def test_customer_artifacts_only_expose_markdown_and_csv(self):
        admin_csrf = self.bootstrap()
        store = self.app.state.store
        client_id = store.one('SELECT id FROM client_instances')['id']
        demand_id = 'artifact-demand'
        supply_id = 'artifact-supply'
        store.run('INSERT INTO client_accounts (id,client_instance_id,customer_id,account_name,is_active,created_at) VALUES (?,?,?,?,?,?)',
                  (demand_id, client_id, '1112223333', 'Demo Demand', 1, '2026-08-28T00:00:00+00:00'))
        store.run('INSERT INTO client_accounts (id,client_instance_id,customer_id,account_name,is_active,created_at) VALUES (?,?,?,?,?,?)',
                  (supply_id, client_id, '9998887777', 'Demo Supply', 1, '2026-08-28T00:00:00+00:00'))
        invite = self.client.post('/api/admin/invites', headers={'X-CSRF-Token':admin_csrf}, json={}).json()['code']
        redeemed = self.client.post('/auth/invite/redeem', json={
            'code': invite, 'identifier': 'artifact-user', 'password': 'artifact-password-123'
        })
        member_csrf = redeemed.json()['csrf']
        user_id = store.one('SELECT id FROM users WHERE email_or_identifier=?', ('artifact-user',))['id']
        from server import app as app_module
        runtime_root = Path(self.workspace)
        demand_root = runtime_root / 'wiki' / '1112223333'
        supply_root = runtime_root / 'wiki' / '9998887777'
        (demand_root / 'action-items').mkdir(parents=True)
        supply_root.mkdir(parents=True)
        (demand_root / 'Index.md').write_text(
            '# Demo Demand Wiki\n\n[Bid/Budget Plan](action-items/bid-budget.csv)\n'
        )
        (demand_root / 'action-items' / 'bid-budget.csv').write_text('campaign_id,action\n1,increase_bid\n')
        (demand_root / 'action-items' / 'bid-budget.yaml').write_text('status: proposed\n')
        (demand_root / 'action-items' / 'suggestions.json').write_text('[{"id":1}]\n')
        (demand_root / 'action-items' / 'batch.txt').write_text('internal prompt\n')
        (supply_root / 'secret.md').write_text('# Supply only\n')

        with patch.object(app_module, 'STATE_ROOT', runtime_root):
            conversation = self.client.post('/api/conversations', headers={'X-CSRF-Token':member_csrf}).json()
            index = self.client.get('/api/artifacts', params={'conversation_id':conversation['id']})
            self.assertEqual(index.status_code, 200, index.text)
            paths = [artifact['path'] for artifact in index.json()]
            self.assertEqual(paths, [
                '1112223333/Index.md',
                '1112223333/action-items/bid-budget.csv',
            ])
            csv_page = self.client.get('/api/artifacts/1112223333/action-items/bid-budget.csv')
            self.assertEqual(csv_page.status_code, 200, csv_page.text)
            self.assertEqual(csv_page.json()['type'], 'csv')
            self.assertIn('increase_bid', csv_page.json()['content'])
            download = self.client.get('/api/artifacts/1112223333/action-items/bid-budget.csv?download=1')
            self.assertEqual(download.status_code, 200, download.text)
            self.assertIn('attachment', download.headers['content-disposition'])
            for internal_name in ('bid-budget.yaml', 'suggestions.json', 'batch.txt'):
                hidden = self.client.get(f'/api/artifacts/1112223333/action-items/{internal_name}')
                self.assertEqual(hidden.status_code, 404, hidden.text)
            supply = self.client.get('/api/artifacts/9998887777/secret.md')
            self.assertEqual(supply.status_code, 200, supply.text)
            self.assertIn('# Supply only', supply.json()['content'])
            legacy = self.client.get('/api/wiki')
            self.assertIn('9998887777/secret.md', [page['path'] for page in legacy.json()])

    def test_set_me_up_is_a_chat_response_with_google_url(self):
        admin_csrf=self.bootstrap()
        self.client.post('/api/admin/google-ads/config',headers={'X-CSRF-Token':admin_csrf},json={
            'developer_token':'dev-token','client_id':'client-id','client_secret':'client-secret','mcc_id':'1234567890'})
        invite=self.client.post('/api/admin/invites',headers={'X-CSRF-Token':admin_csrf},json={}).json()['code']
        member=self.client.post('/auth/invite/redeem',json={'code':invite,'identifier':'setup-user','password':'another-secure-password'})
        member_csrf=member.json()['csrf']; conversation=self.client.post('/api/conversations',headers={'X-CSRF-Token':member_csrf}).json()['id']
        response=self.client.post(f'/api/conversations/{conversation}/messages',headers={'X-CSRF-Token':member_csrf},json={'content':'set me up'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertIsNone(response.json()['job_id'])
        self.assertIn('https://accounts.google.com/o/oauth2/v2/auth',response.json()['immediate_response'])
        self.assertEqual(self.app.state.store.one('SELECT COUNT(*) n FROM oauth_transactions')['n'],1)

    def test_queries_without_google_auth_can_use_saved_context(self):
        admin_csrf=self.bootstrap(); invite=self.client.post('/api/admin/invites',headers={'X-CSRF-Token':admin_csrf},json={}).json()['code']
        member=self.client.post('/auth/invite/redeem',json={'code':invite,'identifier':'no-auth-user','password':'another-secure-password'})
        member_csrf=member.json()['csrf']; conversation=self.client.post('/api/conversations',headers={'X-CSRF-Token':member_csrf}).json()['id']
        response=self.client.post(f'/api/conversations/{conversation}/messages',headers={'X-CSRF-Token':member_csrf},json={'content':'What happened last week?'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertIsNotNone(response.json()['job_id'])
        import time; time.sleep(.05)
        messages=self.client.get(f'/api/conversations/{conversation}').json()['messages']
        self.assertEqual(messages[-1]['role'],'assistant')
        self.assertEqual(self.app.state.runner.calls[-1]['environment'].get('BOB_ACCOUNT_PERMISSION'),'read')

    def test_environment_provisions_super_admin_without_browser_setup(self):
        from server.app import provision_environment_admin
        from server.models import Store
        path=Path(self.tmp.name)/'provision.sqlite3'
        with patch.dict(os.environ, {'ADMIN_IDENTIFIER':'superadmin','ADMIN_PASSWORD':'BobAdmin-2026!','ADMIN_CLIENT_NAME':'Demo MCC'}):
            store=Store(path)
            provision_environment_admin(store)
            user=store.one('SELECT * FROM users')
            self.assertEqual(user['email_or_identifier'],'superadmin')
            self.assertEqual(user['role'],'admin')
        self.assertEqual(store.one('SELECT display_name FROM client_instances')['display_name'],'Demo MCC')
        store.close()

    def test_admin_can_create_an_additional_client(self):
        csrf=self.bootstrap()
        response=self.client.post('/api/admin/clients',headers={'X-CSRF-Token':csrf},json={'name':'Alpha','slug':'alpha','identifier':'owner@alpha.com','password':'alpha-owner-password'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['client']['slug'],'alpha')
        clients=self.client.get('/api/admin/clients')
        self.assertEqual(clients.status_code,200,clients.text)
        self.assertIn('Alpha',[client['display_name'] for client in clients.json()])

    def test_super_admin_creates_client_and_client_sets_up_in_chat(self):
        admin_csrf=self.bootstrap()
        config=self.client.post('/api/admin/google-ads/config',headers={'X-CSRF-Token':admin_csrf},json={
            'developer_token':'dev-token','client_id':'client-id','client_secret':'client-secret','mcc_id':'1234567890'})
        self.assertEqual(config.status_code,200,config.text)
        created=self.client.post('/api/admin/clients',headers={'X-CSRF-Token':admin_csrf},json={
            'name':'Beta','slug':'beta','identifier':'owner@beta.com','password':'beta-owner-password'})
        self.assertEqual(created.status_code,200,created.text)
        client_login=self.client.post('/auth/login',json={'identifier':'owner@beta.com','password':'beta-owner-password'})
        self.assertEqual(client_login.status_code,200,client_login.text)
        client_csrf=client_login.json()['csrf']
        conversation=self.client.post('/api/conversations',headers={'X-CSRF-Token':client_csrf}).json()['id']
        response=self.client.post(f'/api/conversations/{conversation}/messages',headers={'X-CSRF-Token':client_csrf},json={'content':'hey set me up'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertIsNone(response.json()['job_id'])
        self.assertIn('https://accounts.google.com/o/oauth2/v2/auth',response.json()['immediate_response'])

    def test_multi_client_admin_console_is_client_scoped(self):
        admin_csrf=self.bootstrap()
        configured=self.client.post('/api/admin/google-ads/config',headers={'X-CSRF-Token':admin_csrf},json={
            'developer_token':'global-dev-token','client_id':'bob-client-id','client_secret':'bob-client-secret'})
        self.assertEqual(configured.status_code,200,configured.text)
        created=self.client.post('/api/admin/clients',headers={'X-CSRF-Token':admin_csrf},json={
            'name':'Alpha','slug':'alpha','mcc_name':'Alpha MCC','mcc_id':'222-222-2222',
            'identifier':'owner@alpha.com','password':'alpha-owner-password',
            'accounts':[{'account_name':'Demo Demand','customer_id':'123-456-7890'},
                        {'account_name':'Demo Brand','customer_id':'987-654-3210'}]})
        self.assertEqual(created.status_code,200,created.text)
        client_id=created.json()['client']['id']
        detail=self.client.get(f'/api/admin/clients/{client_id}',headers={'X-CSRF-Token':admin_csrf})
        self.assertEqual(detail.status_code,200,detail.text)
        payload=detail.json()
        self.assertEqual(payload['config']['mcc_name'],'Alpha MCC')
        self.assertEqual(sorted(a['customer_id'] for a in payload['accounts']),['1234567890','9876543210'])
        owner_id=next(u['id'] for u in payload['users'] if u['email_or_identifier']=='owner@alpha.com')
        permissions=self.app.state.store.all('''SELECT a.customer_id,ua.permission FROM user_account_access ua
          JOIN client_accounts a ON a.id=ua.account_id WHERE ua.user_id=? ORDER BY a.customer_id''',(owner_id,))
        self.assertEqual([(x['customer_id'],x['permission']) for x in permissions],[('1234567890','read'),('9876543210','read')])
        users=self.client.get(f'/api/admin/users?client_instance_id={client_id}',headers={'X-CSRF-Token':admin_csrf})
        self.assertEqual([u['email_or_identifier'] for u in users.json()],['admin','owner@alpha.com'])
        app_test=self.client.post('/api/admin/google-ads/test',headers={'X-CSRF-Token':admin_csrf})
        self.assertEqual(app_test.status_code,200,app_test.text)
        self.assertEqual(app_test.json()['status'],'ready_for_user_authorization')

    def test_admin_ui_contains_main_navigation_and_client_screens(self):
        html=(Path('server/static/index.html')).read_text()
        js=(Path('server/static/app.js')).read_text()
        for label in ('DASHBOARD','CLIENTS','GOOGLE ADS APP'):
            self.assertIn(label,html)
        self.assertIn('CODEX SESSIONS', html)
        self.assertIn('admin-codex-sessions', html)
        for screen in ('admin-dashboard','admin-clients','admin-google-app'):
            self.assertIn(screen,html)
        for section in ('OVERVIEW','ACCOUNTS','USERS & ACCESS','GOOGLE ADS'):
            self.assertIn(section,js)
        self.assertIn('GENERATE INVITE CODE',js)
        self.assertIn('MAXIMUM PEOPLE',js)
        self.assertIn("client_instance_id:selectedClientId",js)
        self.assertIn('read-only access to all active accounts',js)
        self.assertIn('TEST APPLICATION',html)
        self.assertIn("$('#admin').classList.add('active')",js)
        self.assertIn("document.querySelector('aside').hidden=true",js)
        self.assertIn('global_google_configs',Path('server/schema.sql').read_text())
        self.assertIn('ARTIFACTS', html)
        self.assertIn('/api/artifacts', js)
        self.assertIn('/static/app.js?v=31', html)
        self.assertIn('/api/admin/runtime-settings', js)
        self.assertIn('Aggregate processed input tokens', js)
        self.assertIn('cached_input_tokens_estimate', js)
        self.assertIn('runtime_settings',Path('server/schema.sql').read_text())
        self.assertIn('artifact:wiki\\/', js)
        self.assertNotIn('originalAddWithRelativeWiki', js)
        self.assertNotIn('originalAddWithArtifactPaths', js)
        self.assertNotIn('renderClientSectionWithoutManagement', js)
        self.assertNotIn('renderClientSectionWithInvite', js)
        self.assertNotIn('client_role', js)
        self.assertNotIn('refreshQuestionBank', js)
        self.assertNotIn('HEY BOB, SET ME UP', js)
        self.assertEqual(js.count('function renderQuestionBank('),1)
        self.assertEqual(js.count('function renderClientSection('),1)
        self.assertIn('/api/admin/users/${userId}/password',js)
        self.assertIn('artifact-chat-link', js)
        self.assertNotIn('loadWiki()', js)
        self.assertIn('watchJob', js)
        self.assertIn('USER QUESTION', js)
        self.assertIn('user_prompt', js)
        self.assertIn('/api/jobs/${jid}', js)
        self.assertIn('RECONNECTING', js)
        self.assertIn('/api/conversations/${conversation}/active-job', js)
        self.assertNotIn('STOP JOB', html)
        self.assertIn('press Esc to stop', js)
        self.assertIn('cancelActiveJob', js)
        self.assertIn('safeActivityText', js)
        self.assertIn('job-activity', js)
        self.assertIn('state.retries<=5', js)
        self.assertIn('appendActivity', js)
        self.assertIn('pagehide', js)
        self.assertIn("'conversation_id':target['id']",Path('server/app.py').read_text())
        self.assertIn('create_account_conversation',Path('server/app.py').read_text())
        self.assertIn('await load(result.conversation_id)',js)
        self.assertIn('await setupAgentPanel();await loadArtifacts()',js)
        self.assertEqual(js.count('function setupAgentPanel('),1)

    def test_browser_shell_and_app_bundle_always_revalidate(self):
        shell=self.client.get('/')
        bundle=self.client.get('/static/app.js?v=31')
        self.assertEqual(shell.status_code,200,shell.text)
        self.assertEqual(bundle.status_code,200,bundle.text)
        self.assertIn('/static/app.js?v=31',shell.text)
        self.assertEqual(shell.headers.get('cache-control'),'no-cache, must-revalidate')
        self.assertEqual(bundle.headers.get('cache-control'),'no-cache, must-revalidate')

    def test_user_cancel_terminates_job_and_records_terminal_state(self):
        csrf=self.bootstrap(); self.app.state.runner=SlowRunner()
        conversation=self.client.post('/api/conversations',headers={'X-CSRF-Token':csrf}).json()['id']
        job=self.client.post(f'/api/conversations/{conversation}/messages',headers={'X-CSRF-Token':csrf},json={'content':'long report'}).json()['job_id']
        import time; time.sleep(.05)
        cancelled=self.client.post(f'/api/jobs/{job}/cancel',headers={'X-CSRF-Token':csrf})
        self.assertEqual(cancelled.status_code,200,cancelled.text)
        deadline=time.time()+1
        stored=self.client.get(f'/api/jobs/{job}').json()
        while stored['status'] not in {'cancelled','failed','completed'} and time.time()<deadline:
            time.sleep(.02)
            stored=self.client.get(f'/api/jobs/{job}').json()
        self.assertEqual(stored['status'],'cancelled')
        self.assertIn('CANCELLED',self.client.get(f'/api/jobs/{job}/events').text)
        # Let the deliberately slow fake runner unwind before TestClient closes
        # the SQLite connection during teardown.
        time.sleep(.4)

    def test_admin_can_inspect_each_jobs_native_session(self):
        csrf=self.bootstrap()
        conversation=self.client.post('/api/conversations',headers={'X-CSRF-Token':csrf}).json()['id']
        job=self.client.post(f'/api/conversations/{conversation}/messages',headers={'X-CSRF-Token':csrf},json={'content':'hello'}).json()['job_id']
        import time; time.sleep(.05)
        sessions=self.client.get('/api/admin/codex-sessions',headers={'X-CSRF-Token':csrf})
        self.assertEqual(sessions.status_code,200,sessions.text)
        self.assertEqual(sessions.json()[0]['job_id'],job)
        self.assertEqual(sessions.json()[0]['agent_session_id'],'thread-one')
        self.assertEqual(sessions.json()[0]['user_prompt'],'hello')
        events=self.client.get(f'/api/admin/codex-sessions/{job}/events',headers={'X-CSRF-Token':csrf})
        self.assertEqual(events.status_code,200,events.text)
        self.assertEqual(events.json()[0]['event_type'],'status')
        self.assertEqual(events.json()[1]['event_type'],'agent')
        self.assertEqual(events.json()[1]['payload']['type'],'thread.started')
        self.assertEqual(events.json()[1]['payload']['thread_id'],'thread-one')

    def test_admin_can_reset_a_completed_native_session_without_deleting_chat(self):
        csrf=self.bootstrap()
        conversation=self.client.post('/api/conversations',headers={'X-CSRF-Token':csrf}).json()['id']
        job=self.client.post(f'/api/conversations/{conversation}/messages',headers={'X-CSRF-Token':csrf},json={'content':'hello'}).json()['job_id']
        import time; time.sleep(.05)
        reset=self.client.post(f'/api/admin/codex-sessions/{job}/reset',headers={'X-CSRF-Token':csrf})
        self.assertEqual(reset.status_code,200,reset.text)
        self.assertEqual(reset.json(),{'ok':True,'conversation_id':conversation})
        stored=self.client.get(f'/api/conversations/{conversation}').json()
        self.assertIsNone(stored['conversation']['agent_session_id'])
        self.assertEqual(stored['conversation']['thread_input_tokens_estimate'],0)
        self.assertEqual(len(stored['messages']),2)

    def test_admin_can_filter_custom_analysis_and_view_user_facing_conversation(self):
        csrf=self.bootstrap(); self.app.state.runner=CustomAnalysisRunner()
        conversation=self.client.post('/api/conversations',headers={'X-CSRF-Token':csrf}).json()['id']
        job=self.client.post(f'/api/conversations/{conversation}/messages',headers={'X-CSRF-Token':csrf},
                             json={'content':'Find unusual ad groups'}).json()['job_id']
        import time; time.sleep(.05)
        sessions=self.client.get('/api/admin/codex-sessions',headers={'X-CSRF-Token':csrf})
        self.assertEqual(sessions.status_code,200,sessions.text)
        item=next(row for row in sessions.json() if row['job_id']==job)
        self.assertEqual(item['analysis_name'],'Ad-hoc analysis')
        events=self.client.get(f'/api/admin/codex-sessions/{job}/events',headers={'X-CSRF-Token':csrf}).json()
        marker=next(event for event in events if event['event_type']=='custom_analysis')
        self.assertEqual(marker['payload'],{'analysis_name':'Ad-hoc analysis','phase':'identified'})
        self.app.state.store.run(
            'INSERT INTO messages VALUES (?,?,?,?,?,?)',
            ('earlier-message',conversation,'user','Earlier unrelated chat','completed','2000-01-01T00:00:00+00:00'),
        )
        shown=self.client.get(f'/api/admin/codex-sessions/{job}/conversation',headers={'X-CSRF-Token':csrf})
        self.assertEqual(shown.status_code,200,shown.text)
        self.assertEqual([message['role'] for message in shown.json()['messages']],['user','assistant'])
        self.assertNotIn('Earlier unrelated chat',shown.text)
        self.assertNotIn('operations',shown.text)
        self.client.post('/auth/logout',headers={'X-CSRF-Token':csrf})
        self.assertEqual(self.client.get(f'/api/admin/codex-sessions/{job}/conversation').status_code,401)

    def test_active_job_blocks_duplicate_prompt_and_is_discoverable(self):
        csrf=self.bootstrap(); self.app.state.runner=SlowRunner()
        conversation=self.client.post('/api/conversations',headers={'X-CSRF-Token':csrf}).json()['id']
        first=self.client.post(f'/api/conversations/{conversation}/messages',headers={'X-CSRF-Token':csrf},json={'content':'slow report'})
        self.assertEqual(first.status_code,200,first.text)
        job_id=first.json()['job_id']
        active=self.client.get(f'/api/conversations/{conversation}/active-job')
        self.assertEqual(active.status_code,200,active.text)
        self.assertEqual(active.json()['id'],job_id)
        duplicate=self.client.post(f'/api/conversations/{conversation}/messages',headers={'X-CSRF-Token':csrf},json={'content':'duplicate report'})
        self.assertEqual(duplicate.status_code,409,duplicate.text)
        import time; time.sleep(.35)
        self.assertEqual(self.client.get(f'/api/conversations/{conversation}/active-job').json(),None)

    def test_client_edit_accepts_dashed_nine_digit_mcc(self):
        csrf=self.bootstrap()
        clients=self.client.get('/api/admin/clients',headers={'X-CSRF-Token':csrf}).json()
        client_id=clients[0]['id']
        response=self.client.patch(f'/api/admin/clients/{client_id}',headers={'X-CSRF-Token':csrf},json={
            'name':'Demo Client','slug':'demo-client','mcc_name':'Demo MCC','mcc_id':'12-345-6789'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['mcc_id'],'123456789')

    def test_account_switch_opens_a_durable_account_conversation_without_mutating_the_source(self):
        admin_csrf=self.bootstrap()
        created=self.client.post('/api/admin/clients',headers={'X-CSRF-Token':admin_csrf},json={
            'name':'Alpha','slug':'alpha','identifier':'owner@alpha.com','password':'alpha-owner-password',
            'accounts':[{'account_name':'Demand','customer_id':'111-111-1111'},
                        {'account_name':'Supply','customer_id':'222-222-2222'}]})
        self.assertEqual(created.status_code,200,created.text)
        login=self.client.post('/auth/login',json={'identifier':'owner@alpha.com','password':'alpha-owner-password'})
        csrf=login.json()['csrf']
        accounts={row['account_name']:row['id'] for row in self.client.get('/api/accounts').json()}
        source=self.client.post('/api/conversations',headers={'X-CSRF-Token':csrf}).json()['id']
        self.app.state.store.run('''UPDATE conversations SET agent_session_id=?,workspace_id=?,title=? WHERE id=?''',
                                 ('demand-thread','demand-workspace','Demand history',source))
        self.app.state.store.run('INSERT INTO messages VALUES (?,?,?,?,?,?)',
                                 ('demand-message',source,'user','Keep this demand context','completed','2026-09-13T00:00:00+00:00'))

        switched=self.client.post(f'/api/conversations/{source}/account',headers={'X-CSRF-Token':csrf},
                                  json={'account_id':accounts['Supply']})
        self.assertEqual(switched.status_code,200,switched.text)
        target=switched.json()
        self.assertTrue(target['created'])
        self.assertNotEqual(target['conversation_id'],source)
        self.assertEqual(target['account_id'],accounts['Supply'])
        source_row=self.app.state.store.one('SELECT account_id,agent_session_id,workspace_id,title FROM conversations WHERE id=?',(source,))
        self.assertEqual(tuple(source_row),(accounts['Demand'],'demand-thread','demand-workspace','Demand history'))
        self.assertEqual(self.client.get(f'/api/conversations/{source}').json()['messages'][0]['content'],'Keep this demand context')
        info=self.client.get('/api/agent-info',params={'conversation_id':target['conversation_id']})
        self.assertEqual(info.status_code,200,info.text)
        self.assertEqual(info.json()['account_name'],'Supply')
        resumed=self.client.post(f"/api/conversations/{target['conversation_id']}/account",headers={'X-CSRF-Token':csrf},
                                 json={'account_id':accounts['Demand']})
        self.assertEqual(resumed.status_code,200,resumed.text)
        self.assertEqual(resumed.json()['conversation_id'],source)
        self.assertFalse(resumed.json()['created'])

    def test_account_switch_is_rejected_while_the_loaded_conversation_has_a_running_job(self):
        admin_csrf=self.bootstrap(); self.app.state.runner=SlowRunner()
        created=self.client.post('/api/admin/clients',headers={'X-CSRF-Token':admin_csrf},json={
            'name':'Alpha','slug':'alpha','identifier':'owner@alpha.com','password':'alpha-owner-password',
            'accounts':[{'account_name':'Demand','customer_id':'111-111-1111'},
                        {'account_name':'Supply','customer_id':'222-222-2222'}]})
        login=self.client.post('/auth/login',json={'identifier':'owner@alpha.com','password':'alpha-owner-password'})
        csrf=login.json()['csrf']
        accounts={row['account_name']:row['id'] for row in self.client.get('/api/accounts').json()}
        source=self.client.post('/api/conversations',headers={'X-CSRF-Token':csrf}).json()['id']
        job=self.client.post(f'/api/conversations/{source}/messages',headers={'X-CSRF-Token':csrf},json={'content':'slow report'})
        self.assertEqual(job.status_code,200,job.text)
        blocked=self.client.post(f'/api/conversations/{source}/account',headers={'X-CSRF-Token':csrf},json={'account_id':accounts['Supply']})
        self.assertEqual(blocked.status_code,409,blocked.text)
        import time; time.sleep(.4)

    def test_different_conversations_get_isolated_account_runtime(self):
        admin_csrf=self.bootstrap()
        configured=self.client.post('/api/admin/google-ads/config',headers={'X-CSRF-Token':admin_csrf},json={
            'developer_token':'dev-token','client_id':'client-id','client_secret':'client-secret','mcc_id':'1234567890'})
        self.assertEqual(configured.status_code,200,configured.text)
        created=self.client.post('/api/admin/clients',headers={'X-CSRF-Token':admin_csrf},json={
            'name':'Alpha','slug':'alpha','identifier':'owner@alpha.com','password':'alpha-owner-password',
            'accounts':[{'account_name':'Demand','customer_id':'111-111-1111'},
                        {'account_name':'Supply','customer_id':'222-222-2222'}]})
        self.assertEqual(created.status_code,200,created.text)
        login=self.client.post('/auth/login',json={'identifier':'owner@alpha.com','password':'alpha-owner-password'})
        csrf=login.json()['csrf']
        from server import app as app_module
        with patch.object(app_module,'exchange_google_code',return_value={'refresh_token':'user-refresh','scope':'https://www.googleapis.com/auth/adwords'}):
            start=self.client.post('/api/google-ads/oauth/start',headers={'X-CSRF-Token':csrf})
            state=parse_qs(urlparse(start.json()['authorization_url']).query)['state'][0]
            callback=self.client.get('/api/google-ads/oauth/callback',params={'code':'auth-code','state':state})
        self.assertEqual(callback.status_code,200,callback.text)
        one=self.client.post('/api/conversations',headers={'X-CSRF-Token':csrf}).json()
        client_id=created.json()['client']['id']
        demand=self.app.state.store.one('SELECT id FROM client_accounts WHERE client_instance_id=? AND account_name=?',(client_id,'Demand'))['id']
        supply=self.app.state.store.one('SELECT id FROM client_accounts WHERE client_instance_id=? AND account_name=?',(client_id,'Supply'))['id']
        demand_conversation=self.client.post(f"/api/conversations/{one['id']}/account",headers={'X-CSRF-Token':csrf},json={'account_id':demand}).json()['conversation_id']
        two=self.client.post('/api/conversations',headers={'X-CSRF-Token':csrf}).json()
        supply_conversation=self.client.post(f"/api/conversations/{two['id']}/account",headers={'X-CSRF-Token':csrf},json={'account_id':supply}).json()['conversation_id']
        job1=self.client.post(f"/api/conversations/{demand_conversation}/messages",headers={'X-CSRF-Token':csrf},json={'content':'hello demand'}).json()['job_id']
        job2=self.client.post(f"/api/conversations/{supply_conversation}/messages",headers={'X-CSRF-Token':csrf},json={'content':'hello supply'}).json()['job_id']
        import time; time.sleep(.05)
        self.client.get(f'/api/jobs/{job1}/events')
        self.client.get(f'/api/jobs/{job2}/events')
        self.assertEqual(len(self.app.state.runner.calls),2)
        envs=[call['environment'] for call in self.app.state.runner.calls[-2:]]
        workspaces=[call['workspace'] for call in self.app.state.runner.calls[-2:]]
        self.assertNotEqual(workspaces[0], workspaces[1])
        registries=[]
        for env in envs:
            state_root=Path(env['BOB_STATE_ROOT'])
            registry=json.loads((state_root / '.bob' / 'accounts.json').read_text())
            registries.append(next(a['google_ads_customer_id'] for a in registry if a.get('active')))
        self.assertEqual(sorted(registries),['1111111111','2222222222'])

    def test_client_users_only_see_and_select_permitted_accounts(self):
        admin_csrf=self.bootstrap()
        created=self.client.post('/api/admin/clients',headers={'X-CSRF-Token':admin_csrf},json={
            'name':'Alpha','slug':'alpha','identifier':'owner@alpha.com','password':'alpha-owner-password',
            'accounts':[{'account_name':'Demo Demand','customer_id':'123-456-7890'},
                        {'account_name':'Demo Brand','customer_id':'987-654-3210'}]})
        self.assertEqual(created.status_code,200,created.text)
        client_id=created.json()['client']['id']
        added=self.client.post(f'/api/admin/clients/{client_id}/users',headers={'X-CSRF-Token':admin_csrf},json={
            'identifier':'analyst@alpha.com','password':'analyst-password-123'})
        self.assertEqual(added.status_code,200,added.text)
        detail=self.client.get(f'/api/admin/clients/{client_id}',headers={'X-CSRF-Token':admin_csrf}).json()
        owner_id=next(u['id'] for u in detail['users'] if u['email_or_identifier']=='owner@alpha.com')
        analyst_id=next(u['id'] for u in detail['users'] if u['email_or_identifier']=='analyst@alpha.com')
        demand_id=next(a['id'] for a in detail['accounts'] if a['account_name']=='Demo Demand')
        brand_id=next(a['id'] for a in detail['accounts'] if a['account_name']=='Demo Brand')
        self.client.post(f'/api/admin/users/{owner_id}/accounts/{brand_id}/revoke',headers={'X-CSRF-Token':admin_csrf})
        self.client.post(f'/api/admin/users/{analyst_id}/accounts/{brand_id}/grant',headers={'X-CSRF-Token':admin_csrf},json={'permission':'read'})
        owner=self.client.post('/auth/login',json={'identifier':'owner@alpha.com','password':'alpha-owner-password'})
        owner_csrf=owner.json()['csrf']
        owner_accounts=self.client.get('/api/accounts').json()
        self.assertEqual([a['account_name'] for a in owner_accounts],['Demo Demand'])
        self.client.post('/auth/logout',headers={'X-CSRF-Token':owner_csrf})
        analyst_login=self.client.post('/auth/login',json={'identifier':'analyst@alpha.com','password':'analyst-password-123'})
        analyst_csrf=analyst_login.json()['csrf']
        analyst_accounts=self.client.get('/api/accounts').json()
        self.assertEqual([a['account_name'] for a in analyst_accounts],['Demo Brand'])
        conversation=self.client.post('/api/conversations',headers={'X-CSRF-Token':analyst_csrf}).json()
        self.assertEqual(conversation['account_id'],brand_id)
        blocked=self.client.post(f"/api/conversations/{conversation['id']}/account",headers={'X-CSRF-Token':analyst_csrf},json={'account_id':demand_id})
        self.assertEqual(blocked.status_code,404,blocked.text)
        self.client.post('/auth/logout',headers={'X-CSRF-Token':analyst_csrf})
        owner_login=self.client.post('/auth/login',json={'identifier':'owner@alpha.com','password':'alpha-owner-password'})
        owner_csrf=owner_login.json()['csrf']
        owner_conversation=self.client.post('/api/conversations',headers={'X-CSRF-Token':owner_csrf}).json()
        selected=self.client.get('/api/conversations/'+owner_conversation['id']).json()['conversation']['account_id']
        self.assertEqual(selected,demand_id)

    def test_read_user_can_use_saved_context_without_google_auth(self):
        admin_csrf=self.bootstrap(); s=self.app.state.store
        client_id=s.one('SELECT id FROM client_instances')['id']; stamp='2026-08-31T00:00:00+00:00'
        s.run('INSERT INTO client_accounts (id,client_instance_id,customer_id,account_name,is_active,created_at) VALUES (?,?,?,?,?,?)',('saved-account',client_id,'1234567890','Saved account',1,stamp))
        added=self.client.post(f'/api/admin/clients/{client_id}/users',headers={'X-CSRF-Token':admin_csrf},json={
            'identifier':'reader@example.com','password':'reader-password'})
        self.assertEqual(added.status_code,200,added.text)
        user_id=s.one('SELECT id FROM users WHERE email_or_identifier=?',('reader@example.com',))['id']
        grant=self.client.post(f'/api/admin/users/{user_id}/accounts/saved-account/grant',headers={'X-CSRF-Token':admin_csrf},json={'permission':'read'})
        self.assertEqual(grant.status_code,200,grant.text)
        login=self.client.post('/auth/login',json={'identifier':'reader@example.com','password':'reader-password'})
        self.assertEqual(login.status_code,200,login.text); csrf=login.json()['csrf']
        self.assertEqual([a['account_name'] for a in self.client.get('/api/accounts').json()],['Saved account'])
        conversation=self.client.post('/api/conversations',headers={'X-CSRF-Token':csrf}).json()
        job=self.client.post(f"/api/conversations/{conversation['id']}/messages",headers={'X-CSRF-Token':csrf},json={'content':'What is in the saved wiki?'})
        self.assertEqual(job.status_code,200,job.text); self.assertIsNotNone(job.json()['job_id'])
        import time; time.sleep(.05)
        events=self.client.get(f"/api/jobs/{job.json()['job_id']}/events").text
        self.assertIn('COMPLETED',events)
        call=self.app.state.runner.calls[-1]
        self.assertEqual(call['environment'].get('BOB_ACCOUNT_PERMISSION'),'read')
        self.assertNotIn('BOB_GOOGLE_ADS_RUNTIME_CONFIG',call['environment'])
        self.assertIn('Account permission: read',call['prompt'])
        self.assertIn('Google Ads connection: not connected',call['prompt'])

    def test_live_fetch_without_google_auth_gets_setup_handoff(self):
        admin_csrf=self.bootstrap(); s=self.app.state.store
        client_id=s.one('SELECT id FROM client_instances')['id']; stamp='2026-08-31T00:00:00+00:00'
        s.run('INSERT INTO client_accounts (id,client_instance_id,customer_id,account_name,is_active,created_at) VALUES (?,?,?,?,?,?)',('fetch-account',client_id,'1234567890','Fetch account',1,stamp))
        added=self.client.post(f'/api/admin/clients/{client_id}/users',headers={'X-CSRF-Token':admin_csrf},json={'identifier':'fetch-reader@example.com','password':'reader-password'})
        self.assertEqual(added.status_code,200,added.text)
        user_id=s.one('SELECT id FROM users WHERE email_or_identifier=?',('fetch-reader@example.com',))['id']
        grant=self.client.post(f'/api/admin/users/{user_id}/accounts/fetch-account/grant',headers={'X-CSRF-Token':admin_csrf},json={'permission':'read'})
        self.assertEqual(grant.status_code,200,grant.text)
        login=self.client.post('/auth/login',json={'identifier':'fetch-reader@example.com','password':'reader-password'})
        csrf=login.json()['csrf']; self.app.state.runner=FetchRunner()
        conversation=self.client.post('/api/conversations',headers={'X-CSRF-Token':csrf}).json()
        response=self.client.post(f"/api/conversations/{conversation['id']}/messages",headers={'X-CSRF-Token':csrf},json={'content':'What happened last week?'})
        self.assertIsNotNone(response.json()['job_id'])
        import time; time.sleep(.1)
        messages=self.client.get(f"/api/conversations/{conversation['id']}").json()['messages']
        self.assertIn('Say ‘Hey Bob, set me up’',messages[-1]['content'])
        job=self.client.get(f"/api/jobs/{response.json()['job_id']}").json()
        self.assertEqual(job['status'],'completed')
        events=s.all('SELECT payload FROM job_events WHERE job_id=?',(response.json()['job_id'],))
        self.assertTrue(any(json.loads(event['payload'])=={'type':'bob.error','code':'GOOGLE_AUTH_REQUIRED'} for event in events))

    def test_command_name_does_not_turn_unrelated_failure_into_google_setup(self):
        csrf=self.bootstrap(); self.app.state.runner=UnrelatedFetchFailureRunner()
        conversation=self.client.post('/api/conversations',headers={'X-CSRF-Token':csrf}).json()['id']
        response=self.client.post(f'/api/conversations/{conversation}/messages',headers={'X-CSRF-Token':csrf},json={'content':'check saved performance'})
        import time; time.sleep(.05)
        job=self.client.get(f"/api/jobs/{response.json()['job_id']}").json()
        self.assertEqual(job['status'],'failed')
        self.assertEqual(job['error'],'query file is invalid')

    def test_membership_status_password_and_removed_role_have_separate_apis(self):
        admin_csrf=self.bootstrap(); s=self.app.state.store
        client_id=s.one('SELECT id FROM client_instances')['id']
        rejected=self.client.post(f'/api/admin/clients/{client_id}/users',headers={'X-CSRF-Token':admin_csrf},json={
            'identifier':'reader@example.com','password':'reader-password','client_role':'management'})
        self.assertEqual(rejected.status_code,422,rejected.text)
        added=self.client.post(f'/api/admin/clients/{client_id}/users',headers={'X-CSRF-Token':admin_csrf},json={
            'identifier':'reader@example.com','password':'reader-password'})
        self.assertEqual(added.status_code,200,added.text); uid=added.json()['user']['id']
        mixed=self.client.patch(f'/api/admin/clients/{client_id}/users/{uid}',headers={'X-CSRF-Token':admin_csrf},json={
            'status':'approved','password':'changed-reader-password'})
        self.assertEqual(mixed.status_code,422,mixed.text)
        suspended=self.client.patch(f'/api/admin/clients/{client_id}/users/{uid}',headers={'X-CSRF-Token':admin_csrf},json={'status':'suspended'})
        self.assertEqual(suspended.status_code,200,suspended.text)
        self.assertEqual(s.one('SELECT status FROM client_memberships WHERE user_id=? AND client_instance_id=?',(uid,client_id))['status'],'suspended')
        self.assertEqual(s.one('SELECT status FROM users WHERE id=?',(uid,))['status'],'approved')
        reset=self.client.post(f'/api/admin/users/{uid}/password',headers={'X-CSRF-Token':admin_csrf},json={'password':'changed-reader-password'})
        self.assertEqual(reset.status_code,200,reset.text)
        login=self.client.post('/auth/login',json={'identifier':'reader@example.com','password':'changed-reader-password'})
        self.assertEqual(login.status_code,200,login.text)

    def test_obvious_generic_prompt_is_blocked_before_codex(self):
        csrf=self.bootstrap()
        invite=self.client.post('/api/admin/invites',headers={'X-CSRF-Token':csrf},json={}).json()['code']
        redeemed=self.client.post('/auth/invite/redeem',json={'code':invite,'identifier':'member','password':'another-secure-password'})
        member_csrf=redeemed.json()['csrf']
        member_id=self.app.state.store.one('SELECT id FROM users WHERE email_or_identifier=?',('member',))['id']; client_id=self.app.state.store.one('SELECT id FROM client_instances')['id']; stamp='2026-08-31T00:00:00+00:00'
        self.app.state.store.run('INSERT INTO google_ads_connections VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',('connection',member_id,client_id,None,None,'secret:refresh','scope','connected',stamp,None,stamp,stamp))
        conversation=self.client.post('/api/conversations',headers={'X-CSRF-Token':member_csrf}).json()['id']
        response=self.client.post(f'/api/conversations/{conversation}/messages',headers={'X-CSRF-Token':member_csrf},json={'content':'explain lambda in python'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertIsNone(response.json()['job_id'])
        self.assertIn('outside this Bob workspace', response.json()['immediate_response'])
        self.assertEqual(self.app.state.runner.calls, [])

    def test_admin_can_change_own_password(self):
        csrf=self.bootstrap()
        wrong=self.client.post('/api/profile/password',headers={'X-CSRF-Token':csrf},json={'current_password':'wrong-password','new_password':'new-admin-password-123'})
        self.assertEqual(wrong.status_code,403)
        changed=self.client.post('/api/profile/password',headers={'X-CSRF-Token':csrf},json={'current_password':'a-secure-password','new_password':'new-admin-password-123'})
        self.assertEqual(changed.status_code,200,changed.text)
        self.client.post('/auth/logout',headers={'X-CSRF-Token':csrf})
        login=self.client.post('/auth/login',json={'identifier':'admin','password':'new-admin-password-123'})
        self.assertEqual(login.status_code,200,login.text)

    def test_codex_out_of_scope_reply_teaches_exact_prompt_cache(self):
        self.app.state.runner = OffScopeRunner()
        csrf=self.bootstrap()
        invite=self.client.post('/api/admin/invites',headers={'X-CSRF-Token':csrf},json={}).json()['code']
        redeemed=self.client.post('/auth/invite/redeem',json={'code':invite,'identifier':'member','password':'another-secure-password'})
        member_csrf=redeemed.json()['csrf']
        member_id=self.app.state.store.one('SELECT id FROM users WHERE email_or_identifier=?',('member',))['id']; client_id=self.app.state.store.one('SELECT id FROM client_instances')['id']; stamp='2026-08-31T00:00:00+00:00'
        self.app.state.store.run('INSERT INTO google_ads_connections VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',('connection',member_id,client_id,None,None,'secret:refresh','scope','connected',stamp,None,stamp,stamp))
        conversation=self.client.post('/api/conversations',headers={'X-CSRF-Token':member_csrf}).json()['id']
        prompt = 'tell me about middleware layers'
        first=self.client.post(f'/api/conversations/{conversation}/messages',headers={'X-CSRF-Token':member_csrf},json={'content':prompt})
        self.assertEqual(first.status_code,200,first.text)
        import time; time.sleep(.05)
        self.client.get(f"/api/jobs/{first.json()['job_id']}/events")
        from server.app import learned_offscope_path
        learned = json.loads(learned_offscope_path().read_text())
        self.assertIn(prompt, learned)
        second=self.client.post(f'/api/conversations/{conversation}/messages',headers={'X-CSRF-Token':member_csrf},json={'content':prompt})
        self.assertEqual(second.status_code,200,second.text)
        self.assertIsNone(second.json()['job_id'])
        self.assertIn('outside this Bob workspace', second.json()['immediate_response'])
        self.assertEqual(len(self.app.state.runner.calls), 1)

if __name__=='__main__': unittest.main()
