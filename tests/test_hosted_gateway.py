"""Phase 1 gateway tests; the agent process is replaced with a deterministic fake."""
import os
import json
import tempfile
from urllib.parse import parse_qs, urlparse
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

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
        await emit({'type':'command','message':'fake bob command'})
        return (session_id or 'thread-one', f'Bob received: {user_prompt}')

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
    def test_health_and_bootstrap_login(self):
        self.assertEqual(self.client.get('/api/health').json(),{'status':'ok'})
        csrf=self.bootstrap(); self.assertTrue(csrf)
        self.assertTrue(self.client.get('/auth/session').json()['authenticated'])
        self.client.post('/auth/logout',headers={'X-CSRF-Token':csrf})
        self.assertFalse(self.client.get('/auth/session').json()['authenticated'])

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
        member_csrf=redeemed.json()['csrf']; conversation=self.client.post('/api/conversations',headers={'X-CSRF-Token':member_csrf}).json()['id']
        job=self.client.post(f'/api/conversations/{conversation}/messages',headers={'X-CSRF-Token':member_csrf},json={'content':'hello'}).json()['job_id']
        import time; time.sleep(.05)
        events=self.client.get(f'/api/jobs/{job}/events').text
        self.assertIn('COMPLETED',events); self.assertIn('Bob received: hello',events)
        data=self.client.get(f'/api/conversations/{conversation}').json()
        self.assertEqual(data['conversation']['agent_session_id'],'thread-one')
        self.assertIn('You are Bob for this workspace only.', self.app.state.runner.calls[0]['prompt'])
    def test_csrf_and_workspace_isolation(self):
        self.bootstrap(); self.assertEqual(self.client.post('/api/conversations').status_code,403)
        # A path traversal cannot escape the configured wiki root.
        from server.app import safe_wiki_path
        with self.assertRaises(Exception): safe_wiki_path('../outside')

    def test_bob_state_paths_follow_persistent_client_root(self):
        import lib.datapull as datapull
        self.assertEqual(datapull.STATE_ROOT, Path(self.workspace).resolve())
        self.assertEqual(datapull.ACCOUNTS_DIR, Path(self.workspace).resolve() / '.bob' / 'accounts')
        self.assertEqual(datapull.PROCESSED_DIR, Path(self.workspace).resolve() / 'data' / 'processed')
        self.assertEqual(datapull.account_wiki_dir('123-456-7890'), Path(self.workspace).resolve() / 'wiki' / '1234567890')

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
        start=self.client.post('/api/google-ads/oauth/start',headers={'X-CSRF-Token':member_csrf})
        self.assertEqual(start.status_code,200,start.text)
        query=parse_qs(urlparse(start.json()['authorization_url']).query)
        self.assertEqual(query['scope'],['https://www.googleapis.com/auth/adwords'])
        self.assertEqual(query['access_type'],['offline'])
        from server import app as app_module
        with patch.object(app_module,'exchange_google_code',return_value={'refresh_token':'user-refresh','scope':'https://www.googleapis.com/auth/adwords'}):
            callback=self.client.get('/api/google-ads/oauth/callback',params={'code':'auth-code','state':query['state'][0]})
        self.assertEqual(callback.status_code,200,callback.text)
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
        account_id='account-one'; s.run('INSERT INTO client_accounts VALUES (?,?,?,?,?,?)',(account_id,client_id,'1112223333','Demo Demand',1,'2026-08-24T00:00:00+00:00'))
        invite=self.client.post('/api/admin/invites',headers={'X-CSRF-Token':admin_csrf},json={}).json()['code']
        member=self.client.post('/auth/invite/redeem',json={'code':invite,'identifier':'member','password':'another-secure-password'})
        uid=s.one('SELECT id FROM users WHERE email_or_identifier=?',('member',))['id']
        admin_login=self.client.post('/auth/login',json={'identifier':'admin','password':'a-secure-password'})
        admin_csrf=admin_login.json()['csrf']
        grant=self.client.post(f'/api/admin/users/{uid}/accounts/{account_id}/grant',headers={'X-CSRF-Token':admin_csrf},json={'permission':'mutate'})
        self.assertEqual(grant.status_code,200,grant.text)
        self.assertEqual(s.one('SELECT permission FROM user_account_access WHERE user_id=? AND account_id=?',(uid,account_id))['permission'],'mutate')
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
        for screen in ('admin-dashboard','admin-clients','admin-google-app'):
            self.assertIn(screen,html)
        for section in ('OVERVIEW','ACCOUNTS','USERS & ACCESS','GOOGLE ADS'):
            self.assertIn(section,js)
        self.assertIn('TEST APPLICATION',html)
        self.assertIn("$('#admin').classList.add('active')",js)
        self.assertIn("document.querySelector('aside').hidden=true",js)
        self.assertIn('global_google_configs',Path('server/schema.sql').read_text())

    def test_client_edit_accepts_dashed_nine_digit_mcc(self):
        csrf=self.bootstrap()
        clients=self.client.get('/api/admin/clients',headers={'X-CSRF-Token':csrf}).json()
        client_id=clients[0]['id']
        response=self.client.patch(f'/api/admin/clients/{client_id}',headers={'X-CSRF-Token':csrf},json={
            'name':'Demo Client','slug':'demo-client','mcc_name':'Demo MCC','mcc_id':'12-345-6789'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['mcc_id'],'123456789')

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
        two=self.client.post('/api/conversations',headers={'X-CSRF-Token':csrf}).json()
        client_id=created.json()['client']['id']
        demand=self.app.state.store.one('SELECT id FROM client_accounts WHERE client_instance_id=? AND account_name=?',(client_id,'Demand'))['id']
        supply=self.app.state.store.one('SELECT id FROM client_accounts WHERE client_instance_id=? AND account_name=?',(client_id,'Supply'))['id']
        self.client.post(f"/api/conversations/{one['id']}/account",headers={'X-CSRF-Token':csrf},json={'account_id':demand})
        self.client.post(f"/api/conversations/{two['id']}/account",headers={'X-CSRF-Token':csrf},json={'account_id':supply})
        job1=self.client.post(f"/api/conversations/{one['id']}/messages",headers={'X-CSRF-Token':csrf},json={'content':'hello demand'}).json()['job_id']
        job2=self.client.post(f"/api/conversations/{two['id']}/messages",headers={'X-CSRF-Token':csrf},json={'content':'hello supply'}).json()['job_id']
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

    def test_obvious_generic_prompt_is_blocked_before_codex(self):
        csrf=self.bootstrap()
        invite=self.client.post('/api/admin/invites',headers={'X-CSRF-Token':csrf},json={}).json()['code']
        redeemed=self.client.post('/auth/invite/redeem',json={'code':invite,'identifier':'member','password':'another-secure-password'})
        member_csrf=redeemed.json()['csrf']
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
