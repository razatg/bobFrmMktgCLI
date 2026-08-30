"""Small SQLite metadata store; native agent history remains outside this database."""
from __future__ import annotations
import json, os, secrets, sqlite3, uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

def now() -> str: return datetime.now(timezone.utc).isoformat()
def new_id() -> str: return uuid.uuid4().hex

class Store:
    def __init__(self, path: str | Path):
        self.path = str(path); Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript((Path(__file__).with_name('schema.sql')).read_text())
        # Keep local development databases created by earlier gateway builds usable.
        self._ensure_column('client_google_configs', 'mcc_name', 'TEXT')
        self._ensure_column('client_instances', 'mcc_id', 'TEXT')
        self._ensure_column('client_instances', 'mcc_name', 'TEXT')
        self._ensure_column('client_instances', 'codex_model', 'TEXT')
        self._ensure_column('client_accounts', 'primary_goal', "TEXT NOT NULL DEFAULT 'in_app_conversions'")
        self._ensure_column('client_accounts', 'currency', "TEXT NOT NULL DEFAULT ''")
        self._ensure_column('client_accounts', 'campaign_goal_type', "TEXT NOT NULL DEFAULT 'app_in_app_conversions'")
        self._ensure_column('client_accounts', 'creative_lookback_days', 'INTEGER NOT NULL DEFAULT 15')
        self._ensure_column('client_accounts', 'creative_min_impressions', 'INTEGER NOT NULL DEFAULT 50000')
        self._ensure_column('client_accounts', 'cac_ceiling', 'REAL NOT NULL DEFAULT 200')
        self._ensure_column('client_accounts', 'bid_budget_change_pct', 'REAL NOT NULL DEFAULT 10')
        self._ensure_column('client_accounts', 'bid_budget_cooldown_days', 'INTEGER NOT NULL DEFAULT 14')
        # One-time rename from the old user-facing permission term.
        self.db.execute("UPDATE user_account_access SET permission='read_write' WHERE permission='mutate'")
        self.db.commit()
        self._ensure_column('global_google_configs', 'base_url', 'TEXT')
        self.db.execute("UPDATE global_google_configs SET base_url=? WHERE base_url IS NULL OR base_url=''", (os.getenv('BOB_PUBLIC_BASE_URL','http://localhost:8000'),))
        self.db.commit()
    def _ensure_column(self, table, column, definition):
        columns = {row['name'] for row in self.db.execute(f'PRAGMA table_info({table})')}
        if column not in columns:
            self.db.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')
    def close(self): self.db.close()
    def one(self, sql, args=()): return self.db.execute(sql, args).fetchone()
    def all(self, sql, args=()): return self.db.execute(sql, args).fetchall()
    def run(self, sql, args=()):
        cur = self.db.execute(sql, args); self.db.commit(); return cur
    def create_session(self, user_id, hours=24):
        sid, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
        self.run('INSERT INTO sessions VALUES (?,?,?,?,?,NULL)', (sid,user_id,csrf,(datetime.now(timezone.utc)+timedelta(hours=hours)).isoformat(),now()))
        return sid, csrf
    def session_user(self, sid):
        if not sid: return None
        row = self.one('SELECT s.id AS session_id,s.user_id AS id,s.csrf_token,s.expires_at,s.created_at,s.revoked_at,u.email_or_identifier,u.password_hash,u.role,u.status,u.password_must_change,u.created_at AS user_created_at,u.last_login_at FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.id=? AND s.revoked_at IS NULL AND s.expires_at>?',(sid,now()))
        return row
    def event(self, job_id, event_type, payload):
        n = self.one('SELECT COALESCE(MAX(event_id),0)+1 n FROM job_events WHERE job_id=?',(job_id,))['n']
        self.run('INSERT INTO job_events VALUES (?,?,?,?,?)',(job_id,n,event_type,json.dumps(payload),now())); return n

class SecretStore:
    """Small local-dev secret store; production should point this at a real secret manager."""
    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or os.getenv('BOB_SECRET_ROOT', 'data/secrets')).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        try: self.root.chmod(0o700)
        except OSError: pass

    def put(self, value: str) -> str:
        ref = f'secret:{new_id()}'
        path = self.root / ref.split(':', 1)[1]
        path.write_text(value)
        try: path.chmod(0o600)
        except OSError: pass
        return ref

    def get(self, ref: str) -> str:
        if not ref.startswith('secret:'): raise ValueError('invalid secret reference')
        return (self.root / ref.split(':', 1)[1]).read_text()
