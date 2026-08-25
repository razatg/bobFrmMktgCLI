from __future__ import annotations
import asyncio, base64, hashlib, json, os, secrets
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request as URLRequest, urlopen
from urllib.error import HTTPError, URLError
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from .auth import check_password, csrf, current_user, hash_code, hash_password, same_code
from .agent_runner import AgentRunner, ExecutionPolicy
from .models import SecretStore, Store, new_id, now

ROOT = Path(__file__).resolve().parent.parent
STATE_ROOT = Path(os.getenv('BOB_STATE_ROOT', str(ROOT / 'data' / 'client'))).expanduser().resolve()
OFF_SCOPE_SENTINEL = '[[BOB_OUT_OF_SCOPE]]'
OFF_SCOPE_REPLY = "That’s outside this Bob workspace, mate. I’m here for the ads accounts, reports, wiki, setup, and related project work."
class Credentials(BaseModel): identifier: str; password: str
class Bootstrap(BaseModel): secret: str; identifier: str; password: str; client_name: str = 'Bob Client'
class Invite(BaseModel): expires_hours: int = 72
class Redeem(BaseModel): code: str; identifier: str; password: str
class MessageIn(BaseModel): content: str
class AccountSelectIn(BaseModel): account_id: str
class PasswordIn(BaseModel): current_password: str; new_password: str
class AccountIn(BaseModel): customer_id: str; account_name: str | None = None; permission: str = 'read'
class ClientIn(BaseModel):
    name: str; slug: str | None = None; identifier: str; password: str
    mcc_name: str | None = None; mcc_id: str | None = None; codex_model: str | None = None
    accounts: list[AccountIn] = []
class GoogleConfigIn(BaseModel):
    client_instance_id: str | None = None
    developer_token: str
    oauth_client_json: dict | None = None
    client_id: str | None = None
    client_secret: str | None = None
    mcc_id: str | None = None
    mcc_name: str | None = None
    base_url: str | None = None
    redirect_uri: str | None = None
class AccountPermissionIn(BaseModel): permission: str
def default_codex_model(): return os.getenv('BOB_CODEX_MODEL', 'gpt-5.6-luna').strip() or 'gpt-5.6-luna'
def client_codex_model(store, client_instance_id):
    row=store.one('SELECT codex_model FROM client_instances WHERE id=?',(client_instance_id,))
    return (row['codex_model'] or '').strip() if row else ''

def provision_environment_admin(store):
    """Create the first super-admin from deployment secrets, never from the browser UI."""
    identifier=os.getenv('ADMIN_IDENTIFIER','superadmin').strip(); password=os.getenv('ADMIN_PASSWORD','BobAdmin-2026!')
    if not identifier or not password: return
    if store.one('SELECT id FROM users WHERE email_or_identifier=?',(identifier,)): return
    existing_client=store.one('SELECT id FROM client_instances ORDER BY created_at LIMIT 1')
    cid=existing_client['id'] if existing_client else new_id(); uid=new_id(); t=now(); client_name=os.getenv('ADMIN_CLIENT_NAME','Bob Client').strip() or 'Bob Client'
    store.run('INSERT INTO users VALUES (?,?,?,?,?,?,?,?)',(uid,identifier,hash_password(password),'admin','approved',0,t,None))
    if not existing_client: store.run('INSERT INTO client_instances (id,slug,display_name,worker_ref,status,created_at) VALUES (?,?,?,?,?,?)',(cid,client_name.lower().replace(' ','-'),client_name,cid,'active',t))
    store.run('INSERT INTO client_memberships VALUES (?,?,?,?,?,?)',(uid,cid,'admin','approved',uid,t))

@asynccontextmanager
async def lifespan(app):
    app.state.store = Store(os.getenv('BOB_METADATA_DB', str(ROOT/'data'/'metadata.sqlite3')))
    app.state.secrets = SecretStore()
    provision_environment_admin(app.state.store)
    # A container restart terminates subprocesses, so do not leave their
    # metadata looking permanently active in the chat client.
    app.state.store.run('UPDATE jobs SET status="failed",error="gateway restarted before job completed",completed_at=? WHERE status IN ("queued","running")',(now(),))
    for path in (STATE_ROOT / '.bob', STATE_ROOT / 'data', STATE_ROOT / 'garf' / 'outputs' / 'raw', STATE_ROOT / 'wiki', STATE_ROOT / 'logs', STATE_ROOT / 'validation' / 'reports'):
        path.mkdir(parents=True, exist_ok=True)
    app.state.runner = AgentRunner(); app.state.locks = {}; app.state.cancel = {}
    yield; app.state.store.close()

app = FastAPI(title='Bob Hosted Gateway', lifespan=lifespan)
app.mount('/static', StaticFiles(directory=str(Path(__file__).with_name('static'))), name='static')

def membership(store, user, client=None):
    q='SELECT * FROM client_memberships WHERE user_id=? AND status="approved"'; args=[user['id']]
    if client: q+=' AND client_instance_id=?'; args.append(client)
    return store.one(q,args)
def permitted_accounts(store, user, client_instance_id, active_only=True):
    filters = 'WHERE a.client_instance_id=?'
    args = [client_instance_id]
    if active_only:
        filters += ' AND a.is_active=1'
    if user['role'] != 'admin':
        filters += ' AND EXISTS (SELECT 1 FROM user_account_access ua WHERE ua.account_id=a.id AND ua.user_id=?)'
        args.append(user['id'])
    rows = store.all(f'''SELECT a.id,a.customer_id,a.account_name,a.is_active
      FROM client_accounts a {filters} ORDER BY a.account_name''', tuple(args))
    return [dict(row) for row in rows]
def learned_offscope_path():
    return STATE_ROOT / 'logs' / 'offscope-prompts.json'
def load_learned_offscope():
    path = learned_offscope_path()
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError, TypeError):
        return set()
    return {str(item).strip() for item in data if str(item).strip()} if isinstance(data, list) else set()
def save_learned_offscope(values):
    path = learned_offscope_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(values), indent=2) + '\n')
def normalize_scope_prompt(text):
    return ' '.join(text.lower().split())
def obvious_allow_terms():
    return {
        'bob','google ads','adwords','account','accounts','campaign','campaigns','mcc','wiki','report','reports',
        'analysis','analyze','compare','fetch','pull','budget','budgets','creative','creatives','keyword','keywords',
        'install','installs','conversion','conversions','cpa','cpi','ctr','cpc','cpm','roas','onboard','setup','set me up',
        'switch account','customer id','gaarf','ads','ad group','adgroup','search term','network','week on week','wow','mom','mtd',
    }
def obvious_deny_terms():
    return {
        'lambda in python','python lambda','what is docker','explain docker','what is django','django middleware',
        'what is react','write a poem','capital of france','what is javascript',
    }
def is_obviously_bob_scope(store, row, prompt):
    normalized = normalize_scope_prompt(prompt)
    if not normalized:
        return True
    if normalized in load_learned_offscope():
        return False, 'learned'
    accounts = [a['account_name'].lower() for a in store.all('SELECT account_name FROM client_accounts WHERE client_instance_id=?',(row['client_instance_id'],))]
    if any(name and name in normalized for name in accounts):
        return True, 'account'
    if any(term in normalized for term in obvious_allow_terms()):
        return True, 'allow'
    if normalized in obvious_deny_terms():
        return False, 'deny'
    generic_terms = {'python','docker','django','javascript','react','flask','kubernetes','java','golang','sql'}
    if any(term in normalized for term in generic_terms):
        return False, 'generic'
    recent = store.all('SELECT role,content FROM messages WHERE conversation_id=? ORDER BY created_at DESC LIMIT 3',(row['id'],))
    if len(normalized.split()) <= 6 and recent:
        return True, 'followup'
    return True, 'pass'
def scope_wrapped_prompt(prompt):
    return (
        "You are Bob for this workspace only. Answer only questions tied to this Bob project, Google Ads accounts, "
        "wiki, setup, reporting, analysis, budgets, creatives, or technical work clearly connected to this workspace. "
        f"If the user asks for unrelated general knowledge, reply with {OFF_SCOPE_SENTINEL} followed by one short sentence refusing as out of scope.\n\n"
        f"User message:\n{prompt}"
    )
def client_for_user(store, user, client_id=None):
    if user['role']=='admin' and client_id:
        if not store.one('SELECT id FROM client_instances WHERE id=?',(client_id,)): raise HTTPException(404,'client not found')
        return client_id
    row = membership(store, user, client_id)
    if not row: raise HTTPException(403, 'no access to client')
    return row['client_instance_id']
def oauth_client_values(payload):
    payload = payload or {}
    block = payload.get('web') or payload.get('installed') or payload
    return str(block.get('client_id','')).strip(), str(block.get('client_secret','')).strip()
def environment_name():
    return os.getenv('BOB_ENVIRONMENT', 'local').strip().lower() or 'local'
def default_base_url():
    return os.getenv('BOB_PUBLIC_BASE_URL', 'http://localhost:8000').rstrip('/')
def redirect_uri():
    return os.getenv('GOOGLE_OAUTH_REDIRECT_URI', f'{default_base_url()}/api/google-ads/oauth/callback')
def global_google_config(store):
    return store.one('SELECT * FROM global_google_configs WHERE environment=?',(environment_name(),))
def configured_redirect_uri(store):
    row=global_google_config(store)
    return row['redirect_uri'] if row and row['redirect_uri'] else redirect_uri()
def client_google_config(store, client_id):
    row=store.one('SELECT * FROM client_google_configs WHERE client_instance_id=?',(client_id,))
    if row: return row
    return global_google_config(store)
def pkce_challenge(verifier):
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip('=')
def exchange_google_code(code, client_id, client_secret, verifier, redirect_uri):
    body = urlencode({'code':code,'client_id':client_id,'client_secret':client_secret,
                      'redirect_uri':redirect_uri,'grant_type':'authorization_code',
                      'code_verifier':verifier}).encode()
    req = URLRequest(os.getenv('GOOGLE_OAUTH_TOKEN_URL','https://oauth2.googleapis.com/token'), data=body,
                     headers={'Content-Type':'application/x-www-form-urlencoded'}, method='POST')
    try:
        with urlopen(req, timeout=15) as response: return json.loads(response.read().decode())
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        raise HTTPException(502, f'Google authorization exchange failed: {exc}') from exc
def create_google_oauth_transaction(store, user, client_instance_id, return_path='/'):
    config=client_google_config(store, client_instance_id)
    if not config: raise HTTPException(409,'Google Ads has not been configured by an admin')
    state=secrets.token_urlsafe(32); verifier=secrets.token_urlsafe(48); created=now(); expires=datetime_plus(10/60)
    store.run('INSERT INTO oauth_transactions VALUES (?,?,?,?,?,?,?,?,?)',(new_id(),user['id'],client_instance_id,hash_code(state),app.state.secrets.put(verifier),return_path or '/',expires,'pending',created))
    query={'client_id':config['oauth_client_id'],'redirect_uri':configured_redirect_uri(store),'response_type':'code','scope':'https://www.googleapis.com/auth/adwords','access_type':'offline','prompt':'consent','state':state,'code_challenge':pkce_challenge(verifier),'code_challenge_method':'S256'}
    return os.getenv('GOOGLE_OAUTH_AUTH_URL','https://accounts.google.com/o/oauth2/v2/auth')+'?'+urlencode(query), expires
def _safe_link(link_path: Path, target_path: Path):
    link_path.parent.mkdir(parents=True, exist_ok=True)
    if link_path.is_symlink():
        if Path(os.readlink(link_path)).resolve() == target_path.resolve():
            return
        link_path.unlink()
    elif link_path.exists():
        return
    link_path.symlink_to(target_path, target_is_directory=target_path.is_dir())
def prepare_conversation_runtime(workspace_id: str):
    conv_root = STATE_ROOT / 'runtime' / 'conversations' / workspace_id
    workspace = conv_root / 'workspace'
    state_root = conv_root / 'state'
    workspace.mkdir(parents=True, exist_ok=True)
    state_root.mkdir(parents=True, exist_ok=True)
    for shared in ('data', 'wiki', 'logs', 'validation', 'garf'):
        target = STATE_ROOT / shared
        target.mkdir(parents=True, exist_ok=True)
        _safe_link(state_root / shared, target)
    (state_root / '.bob').mkdir(parents=True, exist_ok=True)
    for name in ('.bob', 'data', 'wiki', 'logs', 'validation'):
        _safe_link(workspace / name, state_root / name)
    for name in ('AGENTS.md', 'CLAUDE.md', 'SOUL.md', 'bob', 'pyproject.toml'):
        target = ROOT / name
        if target.exists():
            _safe_link(workspace / name, target)
    for name in ('.agents', 'bin', 'lib'):
        target = ROOT / name
        if target.exists():
            _safe_link(workspace / name, target)
    garf_workspace = workspace / 'garf'
    garf_workspace.mkdir(parents=True, exist_ok=True)
    _safe_link(garf_workspace / 'queries', ROOT / 'garf' / 'queries')
    _safe_link(garf_workspace / 'outputs', state_root / 'garf' / 'outputs')
    return workspace, state_root
def runtime_google_config(store, user_id, client_instance_id, state_root: Path, account_id=None):
    config=client_google_config(store, client_instance_id)
    connection=store.one('SELECT * FROM google_ads_connections WHERE user_id=? AND client_instance_id=? AND status="connected"',(user_id,client_instance_id))
    if not config or not connection: return None
    developer=app.state.secrets.get(config['developer_token_ref'])
    secret=app.state.secrets.get(config['oauth_client_secret_ref'])
    refresh=app.state.secrets.get(connection['refresh_token_ref'])
    path=state_root / '.bob' / 'runtime' / f'google-ads-{user_id}.yaml'; path.parent.mkdir(parents=True,exist_ok=True)
    lines=[f'developer_token: {json.dumps(developer)}',f'client_id: {json.dumps(config["oauth_client_id"])}',f'client_secret: {json.dumps(secret)}',f'refresh_token: {json.dumps(refresh)}','use_proto_plus: true']
    if config['mcc_id']: lines.append(f'login_customer_id: {json.dumps(config["mcc_id"])}')
    path.write_text('\n'.join(lines)+'\n')
    try: path.chmod(0o600)
    except OSError: pass
    # Rebuild the CLI-facing account registry in the conversation-local state
    # root so one web conversation's account choice never mutates another's.
    user=store.one('SELECT role FROM users WHERE id=?',(user_id,))
    account_sql='SELECT id,customer_id,account_name,is_active FROM client_accounts WHERE client_instance_id=? AND is_active=1'
    account_args=[client_instance_id]
    if not user or user['role']!='admin':
        account_sql+=' AND EXISTS (SELECT 1 FROM user_account_access ua WHERE ua.account_id=client_accounts.id AND ua.user_id=?)'
        account_args.append(user_id)
    account_sql+=' ORDER BY account_name'
    accounts = [dict(row) for row in store.all(account_sql,tuple(account_args))]
    registry = state_root / '.bob' / 'accounts.json'
    registry.parent.mkdir(parents=True, exist_ok=True)
    selected = account_id or (accounts[0]['id'] if accounts else None)
    registry.write_text(json.dumps([{
        'google_ads_customer_id': a['customer_id'],
        'account_name': a['account_name'],
        'active': bool(a['is_active']) and a['id'] == selected,
        'google_ads_read_config_path': str(path),
    } for i, a in enumerate(accounts)], indent=2) + '\n')
    try: registry.chmod(0o600)
    except OSError: pass
    for account in accounts:
        profile_path = state_root / '.bob' / 'accounts' / str(account['customer_id']) / 'profile.json'
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        profile_path.write_text(json.dumps({
            'google_ads_customer_id': account['customer_id'],
            'account_name': account['account_name'],
            'google_ads_read_config_path': str(path),
        }, indent=2) + '\n')
        try: profile_path.chmod(0o600)
        except OSError: pass
    return str(path)
def cookie(response, sid): response.set_cookie('bob_session',sid,httponly=True,secure=os.getenv('BOB_SECURE_COOKIES','0')=='1',samesite='lax',max_age=86400)

@app.get('/')
async def index(): return FileResponse(Path(__file__).with_name('static')/'index.html')
@app.get('/api/health')
async def health(): return {'status':'ok'}
@app.get('/auth/session')
async def session(request: Request):
    row = request.app.state.store.session_user(request.cookies.get('bob_session'))
    if not row: return {'authenticated':False}
    return {'authenticated':True,'user':{'id':row['id'],'identifier':row['email_or_identifier'],'role':row['role'],'status':row['status']},'csrf':row['csrf_token']}
@app.post('/auth/bootstrap')
async def bootstrap(body: Bootstrap, request: Request):
    s=request.app.state.store
    if s.one('SELECT id FROM users LIMIT 1'): raise HTTPException(409,'bootstrap already completed')
    expected=os.getenv('ADMIN_BOOTSTRAP_SECRET')
    if not expected or not secrets.compare_digest(body.secret,expected): raise HTTPException(403,'invalid bootstrap secret')
    uid,cid=new_id(),new_id(); t=now()
    s.run('INSERT INTO users VALUES (?,?,?,?,?,?,?,?)',(uid,body.identifier,hash_password(body.password),'admin','approved',1,t,None))
    s.run('INSERT INTO client_instances (id,slug,display_name,worker_ref,status,created_at) VALUES (?,?,?,?,?,?)',(cid,body.client_name.lower().replace(' ','-'),body.client_name,cid,'active',t))
    s.run('INSERT INTO client_memberships VALUES (?,?,?,?,?,?)',(uid,cid,'admin','approved',uid,t))
    sid,csrf_token=s.create_session(uid); out=JSONResponse({'ok':True,'csrf':csrf_token}); cookie(out,sid); return out
@app.post('/auth/login')
async def login(body: Credentials, request: Request):
    s=request.app.state.store; row=s.one('SELECT * FROM users WHERE email_or_identifier=?',(body.identifier,))
    if not row or not check_password(body.password,row['password_hash']): raise HTTPException(401,'invalid credentials')
    if row['status']=='suspended': raise HTTPException(403,'account suspended')
    s.run('UPDATE users SET last_login_at=? WHERE id=?',(now(),row['id'])); sid,token=s.create_session(row['id']); out=JSONResponse({'ok':True,'csrf':token,'must_change':bool(row['password_must_change'])}); cookie(out,sid); return out
@app.post('/auth/logout')
async def logout(request: Request, response: Response):
    await csrf(request); sid=request.cookies.get('bob_session'); request.app.state.store.run('UPDATE sessions SET revoked_at=? WHERE id=?',(now(),sid)); response.delete_cookie('bob_session'); return {'ok':True}
@app.post('/auth/invite')
async def invite(body: Invite, request: Request):
    user=await csrf(request)
    if user['role']!='admin': raise HTTPException(403,'admin required')
    client=membership(request.app.state.store,user); code=secrets.token_urlsafe(12); t=datetime_plus(body.expires_hours)
    request.app.state.store.run('INSERT INTO invites VALUES (?,?,?,?,?,?,?)',(new_id(),client['client_instance_id'],hash_code(code),user['id'],t,None,None)); return {'code':code,'expires_at':t}
app.add_api_route('/api/admin/invites', invite, methods=['POST'])
@app.post('/auth/invite/redeem')
async def redeem(body: Redeem, request: Request):
    s=request.app.state.store; inv=next((x for x in s.all('SELECT * FROM invites WHERE used_by IS NULL AND expires_at>?',(now(),)) if same_code(body.code,x['code_hash'])),None)
    if not inv: raise HTTPException(400,'invalid invite')
    uid=new_id(); t=now(); s.run('INSERT INTO users VALUES (?,?,?,?,?,?,?,?)',(uid,body.identifier,hash_password(body.password),'member','approved',0,t,None)); s.run('INSERT INTO client_memberships VALUES (?,?,?,?,?,?)',(uid,inv['client_instance_id'],'member','approved',inv['created_by'],t)); s.run('UPDATE invites SET used_by=?,used_at=? WHERE id=?',(uid,t,inv['id'])); sid,token=s.create_session(uid); out=JSONResponse({'ok':True,'csrf':token}); cookie(out,sid); return out

@app.post('/api/profile/password')
async def change_password(body: PasswordIn, request: Request):
    user=await csrf(request)
    if len(body.new_password)<12: raise HTTPException(400,'password must be at least 12 characters')
    if not check_password(body.current_password,user['password_hash']): raise HTTPException(403,'current password is incorrect')
    request.app.state.store.run('UPDATE users SET password_hash=?,password_must_change=0 WHERE id=?',(hash_password(body.new_password),user['id'])); return {'ok':True}

@app.get('/api/admin/users')
async def admin_users(request: Request):
    user=await csrf(request)
    if user['role']!='admin': raise HTTPException(403,'admin required')
    client_id=request.query_params.get('client_instance_id')
    if client_id: client_for_user(request.app.state.store,user,client_id)
    return [dict(x) for x in request.app.state.store.all('''SELECT u.id,u.email_or_identifier,u.role,u.status,u.password_must_change,
      u.created_at,u.last_login_at,COALESCE(g.status,'not_connected') google_status
      FROM users u JOIN client_memberships cm ON cm.user_id=u.id
      LEFT JOIN google_ads_connections g ON g.user_id=u.id AND g.client_instance_id=cm.client_instance_id
      WHERE (? IS NULL OR cm.client_instance_id=?) ORDER BY u.created_at''',(client_id,client_id))]
@app.get('/api/admin/clients')
async def admin_clients(request: Request):
    user=await csrf(request); s=request.app.state.store
    if user['role']!='admin': raise HTTPException(403,'admin required')
    if user['role']=='admin':
        return [dict(x) for x in s.all('''SELECT c.id,c.slug,c.display_name,c.status,c.created_at,'admin' role,
          COALESCE(c.mcc_id,gc.mcc_id,'') mcc_id,COALESCE(c.mcc_name,gc.mcc_name,'') mcc_name,
          (SELECT COUNT(*) FROM client_accounts a WHERE a.client_instance_id=c.id) account_count,
          (SELECT COUNT(*) FROM client_memberships m2 WHERE m2.client_instance_id=c.id AND m2.role='member') user_count
          FROM client_instances c LEFT JOIN client_google_configs gc ON gc.client_instance_id=c.id
          ORDER BY c.created_at''')]
    return [dict(x) for x in s.all('''SELECT c.id,c.slug,c.display_name,c.status,c.created_at,cm.role,
      COALESCE(c.mcc_id,gc.mcc_id,'') mcc_id,COALESCE(c.mcc_name,gc.mcc_name,'') mcc_name,
      (SELECT COUNT(*) FROM client_accounts a WHERE a.client_instance_id=c.id) account_count,
      (SELECT COUNT(*) FROM client_memberships m2 WHERE m2.client_instance_id=c.id AND m2.role='member') user_count
      FROM client_instances c JOIN client_memberships cm ON cm.client_instance_id=c.id
      LEFT JOIN client_google_configs gc ON gc.client_instance_id=c.id
      WHERE cm.user_id=? AND cm.status="approved" ORDER BY c.created_at''',(user['id'],))]
@app.post('/api/admin/clients')
async def create_client(body: ClientIn, request: Request):
    user=await csrf(request); s=request.app.state.store
    if user['role']!='admin': raise HTTPException(403,'admin required')
    name=body.name.strip(); slug=(body.slug or name).strip().lower().replace(' ','-')
    if not name or not slug or not body.identifier.strip() or len(body.password)<12: raise HTTPException(400,'client name, user identifier, and password (12+ characters) are required')
    if s.one('SELECT id FROM client_instances WHERE slug=?',(slug,)): raise HTTPException(409,'client slug already exists')
    if s.one('SELECT id FROM users WHERE email_or_identifier=?',(body.identifier.strip(),)): raise HTTPException(409,'user identifier already exists')
    normalized_accounts=[]; seen_accounts=set()
    for account in body.accounts:
        customer_id=''.join(ch for ch in account.customer_id if ch.isdigit())
        if len(customer_id)!=10: raise HTTPException(400,'customer ID must contain 10 digits')
        if customer_id in seen_accounts: raise HTTPException(409,'duplicate account customer ID')
        seen_accounts.add(customer_id); normalized_accounts.append((account,customer_id))
    cid,uid=new_id(),new_id(); t=now(); source_config=s.one('''SELECT g.developer_token_ref,g.oauth_client_id,g.oauth_client_secret_ref
      FROM client_google_configs g JOIN client_memberships m ON m.client_instance_id=g.client_instance_id
      WHERE m.user_id=? AND m.role="admin" AND m.status="approved" ORDER BY g.updated_at DESC LIMIT 1''',(user['id'],))
    s.run('INSERT INTO client_instances (id,slug,display_name,worker_ref,status,created_at,mcc_id,mcc_name,codex_model) VALUES (?,?,?,?,?,?,?,?,?)',(cid,slug,name,cid,'active',t,(body.mcc_id or '').replace('-',''),body.mcc_name or '',(body.codex_model or '').strip())); s.run('INSERT INTO client_memberships VALUES (?,?,?,?,?,?)',(user['id'],cid,'admin','approved',user['id'],t)); s.run('INSERT INTO users VALUES (?,?,?,?,?,?,?,?)',(uid,body.identifier.strip(),hash_password(body.password),'member','approved',0,t,None)); s.run('INSERT INTO client_memberships VALUES (?,?,?,?,?,?)',(uid,cid,'member','approved',user['id'],t))
    if source_config: s.run('INSERT INTO client_google_configs (client_instance_id,developer_token_ref,oauth_client_id,oauth_client_secret_ref,mcc_id,mcc_name,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)',(cid,source_config['developer_token_ref'],source_config['oauth_client_id'],source_config['oauth_client_secret_ref'],(body.mcc_id or '').replace('-',''),body.mcc_name or '',t,t))
    for account,customer_id in normalized_accounts:
        if s.one('SELECT id FROM client_accounts WHERE client_instance_id=? AND customer_id=?',(cid,customer_id)): raise HTTPException(409,'duplicate account customer ID')
        account_id=new_id(); s.run('INSERT INTO client_accounts VALUES (?,?,?,?,?,?)',(account_id,cid,customer_id,(account.account_name or customer_id).strip(),1,t))
        if account.permission in {'read','mutate'}:
            s.run('INSERT INTO user_account_access VALUES (?,?,?,?,?)',(uid,account_id,account.permission,user['id'],t))
    return {'ok':True,'client':{'id':cid,'slug':slug,'display_name':name},'user':{'id':uid,'identifier':body.identifier.strip()}}
@app.get('/api/admin/clients/{client_id}')
async def admin_client_detail(client_id: str, request: Request):
    user=await csrf(request); s=request.app.state.store; client_for_user(s,user,client_id)
    if user['role']!='admin': raise HTTPException(403,'admin required')
    client=s.one('SELECT * FROM client_instances WHERE id=?',(client_id,))
    if not client: raise HTTPException(404,'client not found')
    cfg=s.one('SELECT mcc_id,mcc_name FROM client_instances WHERE id=?',(client_id,))
    accounts=[dict(x) for x in s.all('SELECT id,customer_id,account_name,is_active FROM client_accounts WHERE client_instance_id=? ORDER BY account_name',(client_id,))]
    users=[dict(x) for x in s.all('''SELECT u.id,u.email_or_identifier,u.role,u.status,COALESCE(g.status,'not_connected') google_status
      FROM users u JOIN client_memberships m ON m.user_id=u.id LEFT JOIN google_ads_connections g ON g.user_id=u.id AND g.client_instance_id=m.client_instance_id
      WHERE m.client_instance_id=? AND m.role='member' ORDER BY u.email_or_identifier''',(client_id,))]
    permissions=[dict(x) for x in s.all('''SELECT ua.user_id,ua.account_id,ua.permission FROM user_account_access ua
      JOIN client_accounts a ON a.id=ua.account_id WHERE a.client_instance_id=?''',(client_id,))]
    return {'client':dict(client),'config':dict(cfg) if cfg else None,'accounts':accounts,'users':users,'permissions':permissions}
@app.post('/api/admin/clients/{client_id}/accounts')
async def add_client_account(client_id: str, body: AccountIn, request: Request):
    user=await csrf(request); s=request.app.state.store; client_for_user(s,user,client_id)
    if user['role']!='admin': raise HTTPException(403,'admin required')
    customer_id=''.join(ch for ch in body.customer_id if ch.isdigit())
    if len(customer_id)!=10: raise HTTPException(400,'customer ID must contain 10 digits')
    if s.one('SELECT id FROM client_accounts WHERE client_instance_id=? AND customer_id=?',(client_id,customer_id)): raise HTTPException(409,'account already exists')
    aid=new_id(); s.run('INSERT INTO client_accounts VALUES (?,?,?,?,?,?)',(aid,client_id,customer_id,(body.account_name or customer_id).strip(),1,now()))
    return {'ok':True,'account':{'id':aid,'customer_id':customer_id,'account_name':body.account_name or customer_id}}
class ClientUpdateIn(BaseModel):
    name: str; slug: str; mcc_name: str | None = None; mcc_id: str | None = None; codex_model: str | None = None
@app.patch('/api/admin/clients/{client_id}')
async def update_client(client_id: str, body: ClientUpdateIn, request: Request):
    user=await csrf(request); s=request.app.state.store; client_for_user(s,user,client_id)
    if user['role']!='admin': raise HTTPException(403,'admin required')
    name=body.name.strip(); slug=body.slug.strip().lower().replace(' ','-'); mcc_id=''.join(ch for ch in (body.mcc_id or '') if ch.isdigit())
    if not name or not slug: raise HTTPException(400,'client name and slug are required')
    if len(mcc_id) not in {0,9,10}: raise HTTPException(400,'MCC ID must contain 9 or 10 digits')
    if s.one('SELECT id FROM client_instances WHERE slug=? AND id<>?',(slug,client_id)): raise HTTPException(409,'client slug already exists')
    s.run('UPDATE client_instances SET display_name=?,slug=?,mcc_id=?,mcc_name=?,codex_model=? WHERE id=?',(name,slug,mcc_id,body.mcc_name or '',(body.codex_model or '').strip(),client_id))
    if s.one('SELECT client_instance_id FROM client_google_configs WHERE client_instance_id=?',(client_id,)):
        s.run('UPDATE client_google_configs SET mcc_id=?,mcc_name=?,updated_at=? WHERE client_instance_id=?',(mcc_id,body.mcc_name or '',now(),client_id))
    return {'ok':True,'client_id':client_id,'display_name':name,'slug':slug,'mcc_id':mcc_id,'mcc_name':body.mcc_name or ''}
class AccountUpdateIn(BaseModel): account_name: str; customer_id: str; is_active: bool = True
@app.patch('/api/admin/clients/{client_id}/accounts/{account_id}')
async def update_client_account(client_id: str, account_id: str, body: AccountUpdateIn, request: Request):
    user=await csrf(request); s=request.app.state.store; client_for_user(s,user,client_id)
    if user['role']!='admin': raise HTTPException(403,'admin required')
    customer_id=''.join(ch for ch in body.customer_id if ch.isdigit())
    account=s.one('SELECT * FROM client_accounts WHERE id=? AND client_instance_id=?',(account_id,client_id))
    if not account: raise HTTPException(404,'account not found')
    if len(customer_id)!=10: raise HTTPException(400,'customer ID must contain 10 digits')
    if s.one('SELECT id FROM client_accounts WHERE client_instance_id=? AND customer_id=? AND id<>?',(client_id,customer_id,account_id)): raise HTTPException(409,'account customer ID already exists')
    name=body.account_name.strip() or customer_id
    s.run('UPDATE client_accounts SET account_name=?,customer_id=?,is_active=? WHERE id=?',(name,customer_id,int(body.is_active),account_id))
    return {'ok':True,'account_id':account_id,'account_name':name,'customer_id':customer_id,'is_active':body.is_active}
class UserCreateIn(BaseModel): identifier: str; password: str; status: str = 'approved'
@app.post('/api/admin/clients/{client_id}/users')
async def add_client_user(client_id: str, body: UserCreateIn, request: Request):
    admin=await csrf(request); s=request.app.state.store; client_for_user(s,admin,client_id)
    if admin['role']!='admin': raise HTTPException(403,'admin required')
    identifier=body.identifier.strip()
    if not identifier or len(body.password)<12: raise HTTPException(400,'identifier and password (12+ characters) are required')
    if body.status not in {'approved','waitlisted'}: raise HTTPException(400,'invalid user status')
    if s.one('SELECT id FROM users WHERE email_or_identifier=?',(identifier,)): raise HTTPException(409,'user identifier already exists')
    uid=new_id(); t=now(); s.run('INSERT INTO users VALUES (?,?,?,?,?,?,?,?)',(uid,identifier,hash_password(body.password),'member',body.status,0,t,None)); s.run('INSERT INTO client_memberships VALUES (?,?,?,?,?,?)',(uid,client_id,'member',body.status,admin['id'],t))
    return {'ok':True,'user':{'id':uid,'identifier':identifier,'status':body.status}}
class UserUpdateIn(BaseModel): status: str | None = None; password: str | None = None
@app.patch('/api/admin/clients/{client_id}/users/{uid}')
async def update_client_user(client_id: str, uid: str, body: UserUpdateIn, request: Request):
    admin=await csrf(request); s=request.app.state.store; client_for_user(s,admin,client_id)
    if admin['role']!='admin': raise HTTPException(403,'admin required')
    member=s.one('SELECT * FROM client_memberships WHERE user_id=? AND client_instance_id=?',(uid,client_id))
    target=s.one('SELECT * FROM users WHERE id=?',(uid,))
    if not member or not target or target['role']=='admin': raise HTTPException(404,'client user not found')
    if body.status is not None and body.status not in {'approved','waitlisted','suspended'}: raise HTTPException(400,'invalid user status')
    if body.password is not None and len(body.password)<12: raise HTTPException(400,'password must be at least 12 characters')
    if body.status is not None:
        s.run('UPDATE client_memberships SET status=? WHERE user_id=? AND client_instance_id=?',(body.status,uid,client_id))
        # The current user model has one global approval state. Keep it in
        # sync with the client membership so approving a client user actually
        # unlocks the protected chat APIs on the next login.
        s.run('UPDATE users SET status=? WHERE id=?',(body.status,uid))
    if body.password is not None: s.run('UPDATE users SET password_hash=? WHERE id=?',(hash_password(body.password),uid))
    return {'ok':True,'user_id':uid}
@app.delete('/api/admin/clients/{client_id}/users/{uid}')
async def remove_client_user(client_id: str, uid: str, request: Request):
    admin=await csrf(request); s=request.app.state.store; client_for_user(s,admin,client_id)
    if admin['role']!='admin': raise HTTPException(403,'admin required')
    target=s.one('SELECT * FROM users WHERE id=?',(uid,)); member=s.one('SELECT * FROM client_memberships WHERE user_id=? AND client_instance_id=?',(uid,client_id))
    if not target or target['role']=='admin' or not member: raise HTTPException(404,'client user not found')
    s.run('DELETE FROM user_account_access WHERE user_id=? AND account_id IN (SELECT id FROM client_accounts WHERE client_instance_id=?)',(uid,client_id))
    s.run('DELETE FROM client_memberships WHERE user_id=? AND client_instance_id=?',(uid,client_id))
    if not s.one('SELECT 1 FROM client_memberships WHERE user_id=?',(uid,)): s.run('DELETE FROM users WHERE id=?',(uid,))
    return {'ok':True,'user_id':uid,'client_id':client_id}
async def set_user_status(uid: str, status: str, request: Request):
    user=await csrf(request)
    if user['role']!='admin': raise HTTPException(403,'admin required')
    if not request.app.state.store.one('SELECT id FROM users WHERE id=?',(uid,)): raise HTTPException(404,'user not found')
    request.app.state.store.run('UPDATE users SET status=? WHERE id=?',(status,uid)); return {'ok':True,'status':status}
@app.post('/api/admin/users/{uid}/approve')
async def approve(uid: str, request: Request): return await set_user_status(uid,'approved',request)
@app.post('/api/admin/users/{uid}/reject')
async def reject(uid: str, request: Request): return await set_user_status(uid,'suspended',request)
@app.post('/api/admin/users/{uid}/suspend')
async def suspend(uid: str, request: Request): return await set_user_status(uid,'suspended',request)

@app.post('/api/admin/google-ads/config')
async def save_google_config(body: GoogleConfigIn, request: Request):
    user=await csrf(request); s=request.app.state.store
    client_id=body.client_instance_id or client_for_user(s,user)
    if user['role']!='admin':
        raise HTTPException(403,'admin required')
    oauth_id, oauth_secret = oauth_client_values(body.oauth_client_json)
    oauth_id = body.client_id or oauth_id; oauth_secret = body.client_secret or oauth_secret
    if not body.developer_token.strip() or not oauth_id or not oauth_secret:
        raise HTTPException(400,'developer token and OAuth client credentials are required')
    t=now(); env=environment_name(); existing_global=global_google_config(s)
    dev_ref=app.state.secrets.put(body.developer_token.strip())
    secret_ref=app.state.secrets.put(oauth_secret)
    saved_base_url=(body.base_url or default_base_url()).rstrip('/')
    saved_redirect=body.redirect_uri or f'{saved_base_url}/api/google-ads/oauth/callback'
    if existing_global:
        s.run('UPDATE global_google_configs SET developer_token_ref=?,oauth_client_id=?,oauth_client_secret_ref=?,base_url=?,redirect_uri=?,updated_at=? WHERE environment=?',(dev_ref,oauth_id,secret_ref,saved_base_url,saved_redirect,t,env))
    else:
        s.run('INSERT INTO global_google_configs (environment,developer_token_ref,oauth_client_id,oauth_client_secret_ref,base_url,redirect_uri,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)',(env,dev_ref,oauth_id,secret_ref,body.base_url or default_base_url(),body.redirect_uri or redirect_uri(),t,t))
    existing=s.one('SELECT * FROM client_google_configs WHERE client_instance_id=?',(client_id,))
    mcc_id=(body.mcc_id or '').replace('-',''); mcc_name=body.mcc_name or ''
    if existing:
        s.run('UPDATE client_google_configs SET developer_token_ref=?,oauth_client_id=?,oauth_client_secret_ref=?,mcc_id=?,mcc_name=?,updated_at=? WHERE client_instance_id=?',(dev_ref,oauth_id,secret_ref,mcc_id,mcc_name,t,client_id))
    else:
        s.run('INSERT INTO client_google_configs (client_instance_id,developer_token_ref,oauth_client_id,oauth_client_secret_ref,mcc_id,mcc_name,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)',(client_id,dev_ref,oauth_id,secret_ref,mcc_id,mcc_name,t,t))
    return {'ok':True,'client_instance_id':client_id,'environment':env,'oauth_client_id':oauth_id,'base_url':saved_base_url,'redirect_uri':saved_redirect,'mcc_id':mcc_id or None}

@app.get('/api/admin/google-ads/config')
async def get_google_config(request: Request):
    user=await csrf(request); s=request.app.state.store; client_id=request.query_params.get('client_instance_id')
    if user['role']!='admin': raise HTTPException(403,'admin required')
    if client_id: client_for_user(s,user,client_id)
    row=global_google_config(s); client=s.one('SELECT client_instance_id,mcc_id,mcc_name,created_at,updated_at FROM client_google_configs WHERE client_instance_id=?',(client_id,)) if client_id else None
    return {'configured':bool(row),'environment':environment_name(),'oauth_client_id':row['oauth_client_id'] if row else None,'base_url':row['base_url'] if row else default_base_url(),'redirect_uri':row['redirect_uri'] if row else redirect_uri(),'client':dict(client) if client else None}
@app.post('/api/admin/google-ads/test')
async def test_google_config(request: Request):
    user=await csrf(request); s=request.app.state.store
    if user['role']!='admin': raise HTTPException(403,'admin required')
    config=global_google_config(s)
    if not config: return {'status':'not_configured','checks':[],'message':'Configure the Bob Google Ads application first.'}
    checks=[{'name':'OAuth client configured','ok':bool(config['oauth_client_id'] and config['oauth_client_secret_ref'])},{'name':'Redirect URI configured','ok':bool(config['redirect_uri'])},{'name':'Authorization URL ready','ok':True},{'name':'Developer token present','ok':bool(config['developer_token_ref'])}]
    return {'status':'ready_for_user_authorization','checks':checks,'message':'Ready for a client user to authorize Google Ads.'}

@app.post('/api/admin/users/{uid}/accounts/{account_id}/grant')
async def grant_account(uid: str, account_id: str, body: AccountPermissionIn, request: Request):
    admin=await csrf(request); s=request.app.state.store
    if admin['role']!='admin': raise HTTPException(403,'admin required')
    account=s.one('SELECT * FROM client_accounts WHERE id=?',(account_id,)); target=s.one('SELECT * FROM users WHERE id=?',(uid,))
    if not account or not target: raise HTTPException(404,'user or account not found')
    if not membership(s,admin,account['client_instance_id']) or not membership(s,target,account['client_instance_id']): raise HTTPException(403,'client membership required')
    if body.permission not in {'read','mutate'}: raise HTTPException(400,'permission must be read or mutate')
    s.run('INSERT INTO user_account_access VALUES (?,?,?,?,?) ON CONFLICT(user_id,account_id) DO UPDATE SET permission=excluded.permission,granted_by=excluded.granted_by,created_at=excluded.created_at',(uid,account_id,body.permission,admin['id'],now()))
    return {'ok':True,'user_id':uid,'account_id':account_id,'permission':body.permission}

@app.post('/api/admin/users/{uid}/accounts/{account_id}/revoke')
async def revoke_account(uid: str, account_id: str, request: Request):
    admin=await csrf(request); s=request.app.state.store
    if admin['role']!='admin': raise HTTPException(403,'admin required')
    account=s.one('SELECT * FROM client_accounts WHERE id=?',(account_id,))
    if not account or not membership(s,admin,account['client_instance_id']): raise HTTPException(404,'account not found')
    s.run('DELETE FROM user_account_access WHERE user_id=? AND account_id=?',(uid,account_id)); return {'ok':True}

@app.get('/api/admin/accounts')
async def admin_accounts(request: Request):
    user=await csrf(request); s=request.app.state.store
    if user['role']!='admin': raise HTTPException(403,'admin required')
    client_id=client_for_user(s,user)
    accounts=s.all('SELECT id,customer_id,account_name,is_active FROM client_accounts WHERE client_instance_id=? ORDER BY customer_id',(client_id,))
    result=[]
    for account in accounts:
        grants=s.all('''SELECT u.id user_id,u.email_or_identifier,ua.permission FROM user_account_access ua
          JOIN users u ON u.id=ua.user_id WHERE ua.account_id=? ORDER BY u.email_or_identifier''',(account['id'],))
        item=dict(account); item['grants']=[dict(g) for g in grants]; result.append(item)
    return result

@app.post('/api/google-ads/oauth/start')
async def google_oauth_start(request: Request):
    user=await csrf(request); s=request.app.state.store
    client_id=client_for_user(s,user,request.query_params.get('client_instance_id'))
    authorization_url,expires=create_google_oauth_transaction(s,user,client_id,request.query_params.get('return_path','/'))
    return {'authorization_url':authorization_url,'expires_at':expires}

@app.get('/api/google-ads/oauth/callback')
async def google_oauth_callback(code: str | None = None, state: str | None = None, error: str | None = None, request: Request = None):
    if not state: raise HTTPException(400,'missing OAuth state')
    s=request.app.state.store; tx=s.one('SELECT * FROM oauth_transactions WHERE state_hash=? AND status="pending"',(hash_code(state),))
    if not tx or tx['expires_at'] < now(): raise HTTPException(400,'invalid or expired OAuth state')
    if error: s.run('UPDATE oauth_transactions SET status="failed" WHERE id=?',(tx['id'],)); return {'ok':False,'error':error}
    if not code: raise HTTPException(400,'missing OAuth code')
    config=s.one('SELECT * FROM client_google_configs WHERE client_instance_id=?',(tx['client_instance_id'],))
    try:
        token=exchange_google_code(code,config['oauth_client_id'],app.state.secrets.get(config['oauth_client_secret_ref']),app.state.secrets.get(tx['pkce_verifier_ref']),configured_redirect_uri(s))
    except HTTPException as exc:
        s.run('UPDATE oauth_transactions SET status="failed" WHERE id=?',(tx['id'],)); raise exc
    refresh=token.get('refresh_token')
    if not refresh: raise HTTPException(502,'Google did not return a refresh token; reconnect with consent')
    existing=s.one('SELECT id FROM google_ads_connections WHERE user_id=? AND client_instance_id=?',(tx['user_id'],tx['client_instance_id']))
    ref=app.state.secrets.put(refresh); t=now()
    if existing: s.run('UPDATE google_ads_connections SET refresh_token_ref=?,scopes=?,status="connected",last_error=NULL,last_verified_at=?,updated_at=? WHERE id=?',(ref,token.get('scope','https://www.googleapis.com/auth/adwords'),t,t,existing['id']))
    else: s.run('INSERT INTO google_ads_connections VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',(new_id(),tx['user_id'],tx['client_instance_id'],None,None,ref,token.get('scope','https://www.googleapis.com/auth/adwords'),'connected',t,None,t,t))
    s.run('UPDATE oauth_transactions SET status="consumed" WHERE id=?',(tx['id'],))
    return RedirectResponse(url=tx['return_path'] or '/', status_code=303)

def datetime_plus(hours):
    from datetime import datetime,timedelta,timezone
    return (datetime.now(timezone.utc)+timedelta(hours=hours)).isoformat()
async def conversation(request, cid):
    user=await current_user(request); row=request.app.state.store.one('SELECT * FROM conversations WHERE id=?',(cid,))
    if not row or row['user_id']!=user['id'] or not membership(request.app.state.store,user,row['client_instance_id']): raise HTTPException(404,'conversation not found')
    return user,row
@app.get('/api/conversations')
async def conversations(request: Request):
    user=await current_user(request); rows=request.app.state.store.all('SELECT * FROM conversations WHERE user_id=? ORDER BY last_activity_at DESC',(user['id'],)); return [dict(x) for x in rows]
@app.post('/api/conversations')
async def create_conversation(request: Request):
    user=await csrf(request); s=request.app.state.store; m=membership(s,user)
    if not m: raise HTTPException(403,'no client access')
    accounts = permitted_accounts(s, user, m['client_instance_id'])
    account_id = accounts[0]['id'] if accounts else None
    cid=new_id(); t=now(); s.run('INSERT INTO conversations VALUES (?,?,?,?,?,?,?,?,?,?)',(cid,user['id'],m['client_instance_id'],account_id,'codex',None,cid,'New conversation',t,t)); return {'id':cid,'account_id':account_id}

@app.get('/api/accounts')
async def user_accounts(request: Request):
    user=await current_user(request); s=request.app.state.store; client=membership(s,user)
    if not client: raise HTTPException(403,'no client access')
    return permitted_accounts(s, user, client['client_instance_id'])

@app.post('/api/conversations/{cid}/account')
async def select_conversation_account(cid: str, body: AccountSelectIn, request: Request):
    user,row=await conversation(request,cid); s=request.app.state.store
    account=next((account for account in permitted_accounts(s, user, row['client_instance_id']) if account['id']==body.account_id), None)
    if not account: raise HTTPException(404,'account not found')
    s.run('UPDATE conversations SET account_id=?,last_activity_at=? WHERE id=?',(body.account_id,now(),cid))
    return {'ok':True,'account_id':body.account_id}
@app.get('/api/conversations/{cid}')
async def get_conversation(cid: str, request: Request):
    _,row=await conversation(request,cid); msgs=request.app.state.store.all('SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at',(cid,)); return {'conversation':dict(row),'messages':[dict(x) for x in msgs]}
@app.post('/api/conversations/{cid}/messages')
async def message(cid: str, body: MessageIn, request: Request):
    user,row=await conversation(request,cid); s=request.app.state.store; row=dict(row)
    # Persist an unambiguous account mention on the conversation so the
    # dropdown, agent panel, runtime config, and Codex prompt share context.
    prompt_lower=body.content.lower()
    permitted=permitted_accounts(s,user,row['client_instance_id'])
    all_accounts=[dict(a) for a in s.all('SELECT id,account_name FROM client_accounts WHERE client_instance_id=? AND is_active=1',(row['client_instance_id'],))]
    permitted_ids={a['id'] for a in permitted}
    unauthorized=[a for a in all_accounts if a['id'] not in permitted_ids and a['account_name'] and a['account_name'].lower() in prompt_lower]
    if len(unauthorized)==1:
        mid=new_id(); t=now(); s.run('INSERT INTO messages VALUES (?,?,?,?,?,?)',(mid,cid,'user',body.content,'completed',t))
        reply=f"You don’t have access to {unauthorized[0]['account_name']}. Ask an admin to grant you READ access first."
        s.run('INSERT INTO messages VALUES (?,?,?,?,?,?)',(new_id(),cid,'assistant',reply,'completed',now()))
        return {'job_id':None,'message_id':mid,'immediate_response':reply}
    mentioned=[a for a in permitted if a['account_name'] and a['account_name'].lower() in prompt_lower]
    if len(mentioned)==1 and mentioned[0]['id']!=row.get('account_id'):
        s.run('UPDATE conversations SET account_id=?,last_activity_at=? WHERE id=?',(mentioned[0]['id'],now(),cid))
        row['account_id']=mentioned[0]['id']
    setup_request=body.content.strip().lower()
    if 'set me up' in setup_request or setup_request in {'setup','onboard me','onboard me bob'}:
        mid=new_id(); t=now(); s.run('INSERT INTO messages VALUES (?,?,?,?,?,?)',(mid,cid,'user',body.content,'completed',t))
        connection=s.one('SELECT status FROM google_ads_connections WHERE user_id=? AND client_instance_id=?',(user['id'],row['client_instance_id']))
        if connection and connection['status']=='connected':
            reply="You’re already connected to Google Ads with your own Google account. Ask me what you’d like to check."
        else:
            try:
                url,_=create_google_oauth_transaction(s,user,row['client_instance_id'],f'/?conversation={cid}')
                reply="Righto — open this Google Ads authorization link and sign in with your own Google account:\n\n"+url+"\n\nOnce Google sends you back, tell me you’re ready and I’ll verify the connection."
            except HTTPException as exc:
                reply=f"I can start that setup once the admin configures Google Ads for this workspace. ({exc.detail})"
        s.run('INSERT INTO messages VALUES (?,?,?,?,?,?)',(new_id(),cid,'assistant',reply,'completed',now()))
        return {'job_id':None,'message_id':mid,'immediate_response':reply}
    allowed,_reason = is_obviously_bob_scope(s, row, body.content)
    if not allowed:
        mid=new_id(); t=now()
        s.run('INSERT INTO messages VALUES (?,?,?,?,?,?)',(mid,cid,'user',body.content,'completed',t))
        s.run('INSERT INTO messages VALUES (?,?,?,?,?,?)',(new_id(),cid,'assistant',OFF_SCOPE_REPLY,'completed',now()))
        return {'job_id':None,'message_id':mid,'immediate_response':OFF_SCOPE_REPLY}
    # Serialize only within one conversation. Different conversations get
    # isolated runtime state and may run concurrently.
    lock=app.state.locks.setdefault(cid,asyncio.Lock())
    if lock.locked(): raise HTTPException(409,'conversation is busy')
    mid,jid=new_id(),new_id(); t=now(); s.run('INSERT INTO messages VALUES (?,?,?,?,?,?)',(mid,cid,'user',body.content,'completed',t)); s.run('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?)',(jid,cid,mid,'queued',None,None,None,t)); asyncio.create_task(run_job(request,jid,cid,body.content,row,lock)); return {'job_id':jid,'message_id':mid}
async def run_job(request,jid,cid,prompt,row,lock):
    s=request.app.state.store
    async with lock:
        s.run('UPDATE jobs SET status="running",started_at=? WHERE id=?',(now(),jid)); s.event(jid,'status',{'status':'THINKING'})
        try:
            async def emit(event): s.event(jid,'agent',event)
            workspace, state_root = prepare_conversation_runtime(row['workspace_id'])
            runtime_config=runtime_google_config(s,row['user_id'],row['client_instance_id'],state_root,row['account_id'])
            environment = {
                'BOB_STATE_ROOT': str(state_root),
                'BOB_SHARED_STATE_ROOT': str(STATE_ROOT),
                'BOB_CLIENT_INSTANCE_ID': row['client_instance_id'],
            }
            if runtime_config:
                environment['BOB_GOOGLE_ADS_RUNTIME_CONFIG'] = runtime_config
            policy=ExecutionPolicy(model=client_codex_model(s,row['client_instance_id']) or default_codex_model(),environment=environment)
            sid,final=await app.state.runner.run(row['agent_backend'],row['agent_session_id'],scope_wrapped_prompt(prompt),workspace,policy,emit,app.state.cancel.get(jid))
            final = final or 'No final response returned.'
            if final.startswith(OFF_SCOPE_SENTINEL):
                learned = load_learned_offscope()
                learned.add(normalize_scope_prompt(prompt))
                save_learned_offscope(learned)
                final = final[len(OFF_SCOPE_SENTINEL):].strip() or OFF_SCOPE_REPLY
            s.run('UPDATE conversations SET agent_session_id=?,last_activity_at=? WHERE id=?',(sid,now(),cid)); s.run('INSERT INTO messages VALUES (?,?,?,?,?,?)',(new_id(),cid,'assistant',final,'completed',now())); s.run('UPDATE jobs SET status="completed",completed_at=? WHERE id=?',(now(),jid)); s.event(jid,'terminal',{'status':'COMPLETED','response':final})
        except asyncio.CancelledError: s.run('UPDATE jobs SET status="cancelled",completed_at=? WHERE id=?',(now(),jid)); s.event(jid,'terminal',{'status':'CANCELLED'})
        except Exception as exc: s.run('UPDATE jobs SET status="failed",error=?,completed_at=? WHERE id=?',(str(exc)[-1000:],now(),jid)); s.event(jid,'terminal',{'status':'FAILED','error':str(exc)[-1000:]})
@app.get('/api/jobs/{jid}')
async def job(jid: str, request: Request):
    user=await current_user(request); row=request.app.state.store.one('SELECT j.*,c.user_id FROM jobs j JOIN conversations c ON c.id=j.conversation_id WHERE j.id=? AND c.user_id=?',(jid,user['id']));
    if not row: raise HTTPException(404,'job not found')
    return dict(row)
def wiki_root(): return STATE_ROOT / 'wiki'

def bob_ascii():
    """Return Bob's canonical face from SOUL.md, keeping the UI in sync."""
    try:
        section = (ROOT / 'SOUL.md').read_text(errors='replace').split("## Bob's Face (ASCII)", 1)[1]
        face = section.split('```', 2)[1].strip('\n')
        # The speech bubble belongs in Bob's conversational output. In the
        # narrow Agent Info rail it makes the ASCII art overflow horizontally.
        return '\n'.join(line.split('      "', 1)[0].rstrip() for line in face.splitlines())
    except (OSError, IndexError):
        return ''

def active_account(store, client_instance_id, account_id=None):
    if account_id:
        row = store.one('SELECT account_name,customer_id FROM client_accounts WHERE client_instance_id=? AND id=? LIMIT 1',(client_instance_id,account_id))
    else:
        row = store.one('SELECT account_name,customer_id FROM client_accounts WHERE client_instance_id=? AND is_active=1 ORDER BY account_name LIMIT 1',(client_instance_id,))
    if row: return dict(row)
    # Compatibility fallback for existing desktop profiles during migration.
    state_root = Path(os.getenv('BOB_STATE_ROOT', str(STATE_ROOT))).expanduser().resolve()
    try:
        accounts = json.loads((state_root / '.bob' / 'accounts.json').read_text())
    except (OSError, ValueError, TypeError):
        return None
    return next((account for account in accounts if isinstance(account, dict) and account.get('active')), None) if isinstance(accounts, list) else None
def sync_state_accounts(store, client_instance_id):
    state_root=Path(os.getenv('BOB_STATE_ROOT',str(STATE_ROOT))).expanduser().resolve()
    registry=state_root/'.bob'/'accounts.json'
    if not registry.exists():
        registry=ROOT/'.bob'/'accounts.json'
    try: accounts=json.loads(registry.read_text())
    except (OSError,ValueError,TypeError): return
    if not isinstance(accounts,list): return
    for account in accounts:
        if not isinstance(account,dict): continue
        customer=str(account.get('google_ads_customer_id','')).replace('-','').strip()
        if not customer or store.one('SELECT id FROM client_accounts WHERE client_instance_id=? AND customer_id=?',(client_instance_id,customer)): continue
        store.run('INSERT INTO client_accounts VALUES (?,?,?,?,?,?)',(new_id(),client_instance_id,customer,account.get('account_name') or customer,1,now()))

@app.get('/api/agent-info')
async def agent_info(request: Request):
    user = await current_user(request)
    client = membership(request.app.state.store, user)
    client_row = request.app.state.store.one('SELECT display_name FROM client_instances WHERE id=?', (client['client_instance_id'],)) if client else None
    conversation_id=request.query_params.get('conversation_id')
    conversation_row=request.app.state.store.one('SELECT account_id FROM conversations WHERE id=? AND user_id=?',(conversation_id,user['id'])) if conversation_id else None
    account = active_account(request.app.state.store, client['client_instance_id'], conversation_row['account_id'] if conversation_row else None) if client else None
    configured_model = client_codex_model(request.app.state.store, client['client_instance_id']) if client else ''
    configured_model = configured_model or default_codex_model()
    return {
        'ascii': bob_ascii(),
        'photo_url': '/static/assets/bob-agent-card.png',
        'name': 'BOB',
        'role': 'SENIOR PERFORMANCE MARKETING LEAD',
        'specialty': 'GOOGLE ADS / APP CAMPAIGNS',
        'style': 'DIRECT / DATA-BACKED / AUSSIE',
        'description': 'Bob calls the signal, cuts the noise, and gives you the next move. Direct, opinionated, and backed by the numbers.',
        'client_name': client_row['display_name'] if client_row else 'Unknown client',
        'account_name': account.get('account_name', 'Unnamed account') if account else 'No active account',
        'model': f'CODEX / {configured_model}' if configured_model else 'CODEX / DEFAULT',
    }

def safe_wiki_path(path: str):
    root=wiki_root().resolve(); target=(root/path).resolve()
    if target!=root and root not in target.parents: raise HTTPException(400,'invalid wiki path')
    return target
@app.get('/api/wiki')
async def wiki_index(request: Request):
    await current_user(request); root=wiki_root()
    if not root.exists(): return []
    return [{'path':str(p.relative_to(root)),'updated_at':p.stat().st_mtime} for p in root.rglob('*.md') if p.is_file()]
@app.get('/api/wiki/{path:path}')
async def wiki_page(path: str, request: Request):
    await current_user(request); target=safe_wiki_path(path)
    if not target.is_file(): raise HTTPException(404,'wiki page not found')
    return {'path':path,'content':target.read_text(errors='replace'),'updated_at':target.stat().st_mtime}
@app.get('/api/jobs/{jid}/events')
async def events(jid: str, request: Request):
    user=await current_user(request); row=request.app.state.store.one('SELECT j.*,c.user_id FROM jobs j JOIN conversations c ON c.id=j.conversation_id WHERE j.id=? AND c.user_id=?',(jid,user['id']));
    if not row: raise HTTPException(404,'job not found')
    try: last=int(request.headers.get('Last-Event-ID','0'))
    except ValueError: last=0
    async def stream():
        cursor=last
        while True:
            rows=request.app.state.store.all('SELECT * FROM job_events WHERE job_id=? AND event_id>? ORDER BY event_id',(jid,cursor))
            for e in rows:
                cursor=e['event_id']; yield f"id: {cursor}\nevent: {e['event_type']}\ndata: {e['payload']}\n\n"
                if e['event_type']=='terminal': return
            state=request.app.state.store.one('SELECT status FROM jobs WHERE id=?',(jid,))['status']
            if state in {'completed','failed','cancelled'}: return
            yield ': keep-alive\n\n'; await asyncio.sleep(1)
    return StreamingResponse(stream(),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})
@app.post('/api/jobs/{jid}/cancel')
async def cancel(jid: str, request: Request):
    user=await csrf(request); row=request.app.state.store.one('SELECT j.* FROM jobs j JOIN conversations c ON c.id=j.conversation_id WHERE j.id=? AND c.user_id=?',(jid,user['id']));
    if not row: raise HTTPException(404,'job not found')
    app.state.cancel[jid]=asyncio.Event(); app.state.cancel[jid].set(); return {'ok':True}
