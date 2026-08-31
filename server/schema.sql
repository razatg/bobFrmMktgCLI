PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY, email_or_identifier TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'member',
  status TEXT NOT NULL DEFAULT 'waitlisted', password_must_change INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, last_login_at TEXT
);
CREATE TABLE IF NOT EXISTS client_instances (
  id TEXT PRIMARY KEY, slug TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL,
  worker_ref TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL,
  mcc_id TEXT, mcc_name TEXT, codex_model TEXT
);
CREATE TABLE IF NOT EXISTS client_memberships (
  user_id TEXT NOT NULL, client_instance_id TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'member',
  status TEXT NOT NULL DEFAULT 'approved', granted_by TEXT, created_at TEXT NOT NULL,
  PRIMARY KEY (user_id, client_instance_id), FOREIGN KEY(user_id) REFERENCES users(id),
  FOREIGN KEY(client_instance_id) REFERENCES client_instances(id)
);
CREATE TABLE IF NOT EXISTS invites (
  id TEXT PRIMARY KEY, client_instance_id TEXT NOT NULL, code_hash TEXT NOT NULL,
  created_by TEXT NOT NULL, expires_at TEXT NOT NULL, used_by TEXT, used_at TEXT,
  max_uses INTEGER NOT NULL DEFAULT 10, use_count INTEGER NOT NULL DEFAULT 0,
  FOREIGN KEY(client_instance_id) REFERENCES client_instances(id)
);
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL, csrf_token TEXT NOT NULL,
  expires_at TEXT NOT NULL, created_at TEXT NOT NULL, revoked_at TEXT,
  FOREIGN KEY(user_id) REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS client_accounts (
  id TEXT PRIMARY KEY, client_instance_id TEXT NOT NULL, customer_id TEXT NOT NULL,
  account_name TEXT, is_active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL,
  primary_goal TEXT NOT NULL DEFAULT 'in_app_conversions',
  currency TEXT NOT NULL DEFAULT '',
  campaign_goal_type TEXT NOT NULL DEFAULT 'app_in_app_conversions',
  creative_lookback_days INTEGER NOT NULL DEFAULT 15,
  creative_min_impressions INTEGER NOT NULL DEFAULT 50000,
  cac_ceiling REAL NOT NULL DEFAULT 200,
  bid_budget_change_pct REAL NOT NULL DEFAULT 10,
  bid_budget_cooldown_days INTEGER NOT NULL DEFAULT 14,
  FOREIGN KEY(client_instance_id) REFERENCES client_instances(id)
);
CREATE TABLE IF NOT EXISTS user_account_access (
  user_id TEXT NOT NULL, account_id TEXT NOT NULL, permission TEXT NOT NULL,
  granted_by TEXT, created_at TEXT NOT NULL, PRIMARY KEY(user_id, account_id),
  FOREIGN KEY(user_id) REFERENCES users(id), FOREIGN KEY(account_id) REFERENCES client_accounts(id)
);
CREATE TABLE IF NOT EXISTS client_google_configs (
  client_instance_id TEXT PRIMARY KEY, developer_token_ref TEXT NOT NULL,
  oauth_client_id TEXT NOT NULL, oauth_client_secret_ref TEXT NOT NULL,
  mcc_id TEXT, mcc_name TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  FOREIGN KEY(client_instance_id) REFERENCES client_instances(id)
);
CREATE TABLE IF NOT EXISTS global_google_configs (
  environment TEXT PRIMARY KEY, developer_token_ref TEXT NOT NULL,
  oauth_client_id TEXT NOT NULL, oauth_client_secret_ref TEXT NOT NULL,
  base_url TEXT NOT NULL, redirect_uri TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS google_ads_connections (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL, client_instance_id TEXT NOT NULL,
  google_subject TEXT, google_email TEXT, refresh_token_ref TEXT NOT NULL,
  scopes TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'connected',
  last_verified_at TEXT, last_error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  UNIQUE(user_id, client_instance_id),
  FOREIGN KEY(user_id) REFERENCES users(id), FOREIGN KEY(client_instance_id) REFERENCES client_instances(id)
);
CREATE TABLE IF NOT EXISTS oauth_transactions (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL, client_instance_id TEXT NOT NULL,
  state_hash TEXT NOT NULL UNIQUE, pkce_verifier_ref TEXT NOT NULL,
  return_path TEXT, expires_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT NOT NULL,
  FOREIGN KEY(user_id) REFERENCES users(id), FOREIGN KEY(client_instance_id) REFERENCES client_instances(id)
);
CREATE TABLE IF NOT EXISTS conversations (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL, client_instance_id TEXT NOT NULL, account_id TEXT,
  agent_backend TEXT NOT NULL DEFAULT 'codex', agent_session_id TEXT, workspace_id TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT 'New conversation', created_at TEXT NOT NULL, last_activity_at TEXT NOT NULL,
  FOREIGN KEY(user_id) REFERENCES users(id), FOREIGN KEY(client_instance_id) REFERENCES client_instances(id)
);
CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'completed', created_at TEXT NOT NULL,
  FOREIGN KEY(conversation_id) REFERENCES conversations(id)
);
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, message_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued', error TEXT, started_at TEXT, completed_at TEXT, created_at TEXT NOT NULL,
  FOREIGN KEY(conversation_id) REFERENCES conversations(id), FOREIGN KEY(message_id) REFERENCES messages(id)
);
CREATE TABLE IF NOT EXISTS job_events (
  job_id TEXT NOT NULL, event_id INTEGER NOT NULL, event_type TEXT NOT NULL, payload TEXT NOT NULL,
  created_at TEXT NOT NULL, PRIMARY KEY(job_id, event_id), FOREIGN KEY(job_id) REFERENCES jobs(id)
);
CREATE INDEX IF NOT EXISTS idx_job_events ON job_events(job_id, event_id);
