# TIM Migration Plan

## 1. Summary

Move Bob from a local, user-managed CLI project to a hosted, per-client Docker deployment while preserving the existing Bob harness.

The hosted layer is a thin authenticated gateway around the existing agent CLI. It does not recreate Bob's skills, deterministic reporting logic, or agent conversation history.

- Codex/Claude own model interaction, tool execution, and native session history.
- Bob owns Google Ads workflows, metric calculations, safety rules, and `./bob` commands.
- The gateway owns authentication, authorization, session mapping, process lifecycle, concurrency, and response delivery.
- The first surface is a web UI. Telegram uses the same API later.
- Each client gets one isolated deployment on Hetzner Cloud or GCP Compute Engine.

## 2. Target technical architecture

```text
Browser
  |
  v
FastAPI application
  |- Google Sign-In and authorization
  |- conversation/session metadata
  |- per-conversation locks
  |- process supervisor
  `- WebSocket or SSE job events
        |
        v
Codex CLI or Claude Code CLI
        |
        v
Per-client Bob workspace
  |- ./bob
  |- AGENTS.md / CLAUDE.md
  |- .agents/
  |- .bob/
  |- wiki/
  |- data/
  |- garf/
  `- logs/
```

The MVP runs the FastAPI application and process supervisor in one container. It does not introduce Redis, Celery, or another distributed queue initially.

Persistent volumes:

```text
/data/client    Client Bob state: .bob, processed data, raw pulls, wiki, logs, validation
/data/codex     Codex configuration, authentication, and session history
/data/claude    Claude configuration and session state, if required
/data/metadata  Lightweight application metadata and job state
```

The container image contains Bob's immutable code and instructions under `/app`:

```text
/app            bob, lib/, bin/, .agents/, garf/queries/, AGENTS.md, CLAUDE.md, pyproject.toml
```

At startup, the client volume is linked into the historical relative paths under `/app` so the
existing agent instructions and skills continue to see `.bob/`, `data/`, `wiki/`, `logs/`, and
`validation/`. `lib/datapull.py` uses `BOB_STATE_ROOT=/data/client` for all persistent state paths
while retaining `/app` as its code/project root. Existing onboarded accounts are migrated into the
client volume; new chat-driven onboarding and all future pulls/Wiki writes use the same volume.

The domain choice is intentionally deferred. The initial hosted deployment may use one main
domain for all clients (for example, `timfrmmktg.com`) or a client subdomain, but the
authenticated user's approved `client_memberships` determine which
client instance, workspace volume, accounts, Wiki, and conversations they can access. Client
isolation is enforced by `client_instance_id` in the gateway and by separate worker/volume
boundaries; it does not depend on the browser hostname.

The first deployment may still run one client worker for the initial client MCC. URL shape is a presentation
and deployment choice, not a separate deployment or data-isolation mechanism in the MVP.

For local and test hosting, use environment-configured URLs:

```env
BOB_PUBLIC_BASE_URL=http://localhost:8000
GOOGLE_OAUTH_REDIRECT_URI=http://localhost:8000/api/google-ads/oauth/callback
```

Production replaces these values through deployment environment variables. No code path should
hardcode a client subdomain or infer tenant access solely from the request hostname.

## 3. Harness boundary

The existing harness remains authoritative and is copied into the image or base workspace unchanged:

- `AGENTS.md`
- `CLAUDE.md`
- `.agents/skills/`
- `SOUL.md`
- `./bob`
- existing Bob data and account rules

The gateway invokes the agent CLI from a controlled Bob workspace. It does not duplicate the performance-analysis, account, bid/budget, or creative logic in server code.

Every answer containing numbers must still be based on Bob CLI output produced for that job.

## 4. Native agent sessions

Native agent sessions are the source of truth for conversation context. The application does not maintain a second full transcript database.

Codex supports persistent non-interactive sessions:

```bash
codex exec \
  --cd <workspace> \
  --dangerously-bypass-approvals-and-sandbox \
  --model <model> \
  --json \
  --skip-git-repo-check \
  "<initial request>"

# Returns JSON events including:
# {"type":"thread.started","thread_id":"01a005a1-742a-76d2-b6ee-45a4c44a7971"}
```

Follow-up messages resume the recorded session:

```bash
codex exec resume <thread_id> \
  --cd <workspace> \
  --dangerously-bypass-approvals-and-sandbox \
  --model <model> \
  --json \
  --skip-git-repo-check \
  "<next request>"

# Returns cached_input_tokens in usage, proving conversation history is preserved
```

**Verified:** The local validation confirmed that resume preserves conversation context via cached tokens. Keep the exact validation date in the implementation test record rather than hard-coding it in this architecture document.

`--ephemeral` is not used for normal conversations because it disables session-file persistence. It may be used for intentionally stateless health checks or one-off jobs.

**Required flags:**
- `--skip-git-repo-check` when workspace is not a git repo
- hosted Linux uses `--sandbox workspace-write`; local Docker Desktop uses `--dangerously-bypass-approvals-and-sandbox` only through the explicit `docker-compose.desktop.yml` override because Docker Desktop blocks Codex's nested bubblewrap namespace. The desktop worker still runs as an unprivileged `bob` user with `no-new-privileges`.
- `--json` for structured event streaming

The service stores only the metadata needed to reconnect a web conversation to a native agent session:

```text
conversation_id
user_id
client_instance_id
agent_backend
agent_session_id
workspace_id
created_at
last_activity_at
```

The initial implementation uses SQLite for this small metadata set and for job status. SQLite is not a replacement for Codex or Claude history; it allows the API to authorize conversations, resume sessions, recover status after restart, and prevent duplicate work.

Claude is implemented through the same adapter interface, but its authentication, persistence, and resume behavior must be verified separately rather than assumed to match Codex.

Desktop login directories must never be copied or mounted onto the VPS. Server-side agent credentials are injected through Docker secrets or the hosting provider's secret manager.

## 5. Requests, sessions, and concurrency

Each request has these identifiers:

```text
client_instance_id
organization_id
user_id
conversation_id
message_id
job_id
agent_session_id
workspace_id
```

Different conversations may run concurrently:

```text
Conversation A -> Codex session A -> process A
Conversation B -> Codex session B -> process B
```

Native CLI sessions provide independent contexts, but they are not themselves a queue and they do not replace Bob's execution/runtime contract. The gateway still provides a thin process supervisor that:

- starts one process per independent conversation/job;
- serializes messages within one conversation;
- limits total concurrent processes with an asyncio semaphore;
- captures JSON events, stdout, stderr, exit status, and duration;
- supports timeout and cancellation;
- cleans up terminated processes;
- marks interrupted jobs failed or retryable after restart;
- prevents duplicate mutation execution.

No external queue service is required for the single-client MVP. A durable worker service or Redis-backed queue can be introduced later if one instance needs multiple application replicas or substantially higher throughput.

Two requests must never concurrently resume the same native agent session. Read-only requests in different conversations may run concurrently.

For hosted web execution, `agent_session_id` is the conversation-memory handle only. It is not the source of truth for account selection, Google Ads credentials, or runtime filesystem state. Those are resolved explicitly per request from application state.

## 6. Workspace and account isolation

Each client has a persistent state volume. Each conversation/session receives a stable native agent
session identity that is reused for every resumed message. Hosted web execution must not depend on
the CLI's shared "active account" model.

The runtime split is:

- `CLI mode`: local `.bob/`, local active account, and local Codex/Claude session behavior.
- `Web mode`: DB-backed users, clients, accounts, permissions, OAuth connections, and explicit request-scoped account context.

In web mode, the gateway resolves account context from:

```text
client_instance_id
user_id
conversation_id
account_id
customer_id
mcc_id
google_ads_connection_ref
```

`agent_session_id` remains the conversation-memory handle for the agent CLI, but it is not used as a substitute for account/runtime isolation.

Jobs within one conversation remain serialized. Different conversations may run concurrently when they do not contend for the same mutation or duplicate fetch work.

The workspace contains:

```text
AGENTS.md
CLAUDE.md
.agents/
.bob/
wiki/
data/
garf/
logs/
./bob
```

The current CLI uses account state in `.bob/accounts.json`. Hosted execution must not allow one user's account switch to affect another user's request.

The hosted gateway therefore binds every conversation and job to an explicit client/account context and applies these rules:

- do not mutate shared `.bob/accounts.json` to drive normal web requests;
- treat `change account` in the web UI/chat as a conversation default only;
- allow explicit account mentions inside a prompt to override the conversation default for that request;
- generate any required Google Ads runtime YAML/config from stored DB/secret values at run time only;
- keep the YAML/config as a temporary runtime artifact, not a durable source of truth;
- reserve broad locks for mutation safety or true duplicate-work coordination, not for ordinary read-only account switches.

Downloaded and processed data may be shared within a client only when the pull key is identical:

```text
(client_instance_id, customer_id, query, from_date, to_date)
```

If a matching pull is already running, another job waits for or reuses that result instead of starting a second identical pull. This dedupe is separate from native agent session handling. Reach and frequency remain subject to Bob's existing aggregation rules and are never blindly summed.

## 7. Mutation safety

Read-only analysis jobs may run concurrently. Bid, budget, creative, account, or other mutation workflows require:

1. proposal generation;
2. explicit user approval;
3. current-state recheck;
4. client-level mutation lock;
5. execution and audit result.

No mutation job runs concurrently with another mutation job for the same client. A process timeout must not automatically retry a mutation after it may have started; the service must first inspect current state.

## 8. Agent adapter

The adapter is a process boundary, not a replacement harness:

```text
AgentRunner.run(
    backend,
    session_id,
    prompt,
    workspace,
    model,
    execution_policy,
) -> JobEvent stream + final response
```

Required behavior:

- start the configured CLI with an explicit working directory;
- create a native session for a new conversation;
- resume the mapped native session for follow-up messages;
- pass the selected model and sandbox policy explicitly;
- parse structured output where supported;
- stream progress and final events to the API;
- enforce timeout, cancellation, and output-size limits;
- redact credentials from logs and responses;
- restrict accessible paths to the client/job workspace.

Codex's first implementation uses `codex exec` and `codex exec resume`. The proposed long-lived background stdin/stdout session is not part of the MVP because it creates unnecessary protocol and lifecycle complexity.

## 9. Authentication and API

The Phase 1 web UI uses server-side sessions backed by an instance invite/admin flow. A browser-generated localStorage user ID is never treated as authentication. Google Sign-In is a later replaceable identity-provider option, not a Phase 1 dependency.

**Super-admin provisioning:** On first startup, if no users exist, the service may create the super-admin from deployment secrets (`ADMIN_IDENTIFIER`, `ADMIN_PASSWORD`, and optional `ADMIN_CLIENT_NAME`). These values are never displayed in the browser or stored in source. The browser exposes ordinary username/password sign-in only; there is no first-time admin setup form.

Initial API:

```text
GET  /auth/session
POST /auth/login
POST /auth/invite/redeem
POST /auth/logout
POST /api/profile/password
GET  /api/admin/users
POST /api/admin/invites
POST /api/admin/users/{user_id}/approve
POST /api/admin/users/{user_id}/reject
POST /api/admin/users/{user_id}/suspend
POST /api/admin/users/{user_id}/accounts/{account_id}/grant
POST /api/admin/users/{user_id}/accounts/{account_id}/revoke
GET  /api/admin/accounts
POST /api/admin/google-ads/config
GET  /api/admin/google-ads/config
POST /api/conversations
POST /api/conversations/{conversation_id}/messages
GET  /api/conversations/{conversation_id}
GET  /api/jobs/{job_id}
GET  /api/jobs/{job_id}/events
GET  /api/account-status
POST /api/google-ads/onboarding
POST /api/google-ads/oauth/start
GET  /api/google-ads/oauth/callback
GET  /api/health
```

Authorization verifies that the user has an approved membership for the client instance. An instance admin controls invites, waitlisted users, approvals, suspension, and client/account assignments. Telegram later links to the same user through a one-time pairing flow and uses the same message/job APIs. 

The gateway resolves the active client from the user's approved membership and carries the
resolved `client_instance_id` through every
conversation, job, account, Wiki, and credential lookup. If a user belongs to multiple clients,
the UI/chat flow must require an explicit active-client selection before creating a conversation;
the selected client is never accepted from an untrusted browser parameter without membership
validation.

Google Sign-In, when added later, will authenticate the user but will not replace the Google Ads developer token or Google Ads OAuth credentials required by Bob.

Authentication requirements for Phase 1:

- Passwords use Argon2id or bcrypt; plaintext passwords are never stored.
- Sessions are server-side, expire, can be revoked, and use Secure, HttpOnly, SameSite cookies.
- State-changing browser requests use CSRF protection.
- User status is one of `waitlisted`, `approved`, or `suspended`.
- Only approved users can create conversations or access Wiki, account, and job data.
- Admin endpoints require an approved admin role.

## 9B. Phase 1 data model

SQLite stores access control, job state, and a small UI message projection. It does not replace native Codex/Claude session history.

Required tables:

```text
users
  id, email_or_identifier, password_hash, role, status,
  password_must_change, created_at, last_login_at

client_instances
  id, slug, display_name, worker_ref, status, created_at

client_memberships
  user_id, client_instance_id, role, status, granted_by, created_at

invites
  id, client_instance_id, code_hash, created_by, expires_at,
  used_by, used_at

sessions
  id, user_id, expires_at, created_at, revoked_at

client_accounts
  id, client_instance_id, customer_id, account_name, is_active, created_at

user_account_access
  user_id, account_id, permission, granted_by, created_at

google_ads_connections
  id, user_id, client_instance_id, google_subject, google_email,
  refresh_token_secret_ref, scopes, status, last_verified_at, last_error,
  created_at, updated_at

oauth_transactions
  id, user_id, client_instance_id, state_hash, pkce_verifier_secret_ref,
  return_path, expires_at, status, created_at

conversations
  id, user_id, client_instance_id, account_id, agent_backend, agent_session_id,
  workspace_id, title, created_at, last_activity_at

messages
  id, conversation_id, role, content, status, created_at

jobs
  id, conversation_id, message_id, status, error,
  started_at, completed_at, created_at

approvals
  id, conversation_id, approval_type, plan_ref, status,
  approved_by, approved_at, applied_at, created_at
```

The developer token and OAuth client credentials belong to the organization/application. Each user
connects Google Ads with their own Google account, producing a separate Google Ads connection and
refresh-token reference. `client_memberships` controls client access and `user_account_access`
controls the user's Bob permission (`read` or `mutate`) for each account. Google authorization and
Bob permission are separate gates: authorizing Google does not automatically grant mutation access.

At job start, the worker materializes a protected runtime configuration from the organization
developer token/OAuth client credentials and the current user's Google connection. The gateway
never places tokens in prompts, UI projections, ordinary logs, or shared account metadata. A
Google token failure marks only that user's connection as requiring reauthorization.

The SQLite file is encrypted at rest with SQLCipher when credential references or other sensitive metadata are stored locally. The encryption key is supplied through the secret store, never committed or logged. Database connections must configure the key before reading or writing and must use safe parameterized queries.

## 9A. Web chat client UI

The web client follows the retro chat-console direction of the reference design. It deliberately has no permanent left navigation menu. The active conversation remains the visual focus, while Bob's agent information is persistently visible on the right.

```text
┌──────────────────────────────────────────────────────────────┐
│ BOB // FRM MKTG          HISTORY     WIKI       ● ONLINE      │
├──────────────────────────────────────────────┬───────────────┤
│                                              │               │
│                 CURRENT CHAT                 │  BOB          │
│                                              │  AGENT INFO   │
│  User question                               │               │
│                                              │  ● Connected  │
│  Bob response                                │  Model        │
│                                              │  Account      │
│  > running Bob command                       │  Workspace    │
│                                              │               │
│  Ask Bob anything...                  SEND   │               │
└──────────────────────────────────────────────┴───────────────┘
```

The visual language uses a near-black background, dark green surfaces, phosphor-green highlights, thin framed panels, restrained square corners, and a monospace system chrome. It is inspired by the reference direction without copying its artwork or proprietary assets.

**Design system:** Use CSS custom properties for the retro terminal design: near-black base, dark-green surfaces, phosphor-green primary text, muted-green secondary text, red errors, amber warnings, sharp framed panels, monospace system chrome, and visible green focus rings. Use responsive breakpoints for desktop, tablet, and mobile. There is no permanent sidebar; do not add a sidebar layout token.

### History tab

`HISTORY` is the default tab and contains the current chat timeline, streamed Bob progress, Markdown answers, retry/stop controls, and mutation approval cards.

Older conversations are accessed through a compact history switcher or modal opened from the top bar. There is no permanent left-side conversation list. The switcher reads the SQLite presentation index, and selecting an item loads that conversation's visible message projection while future messages resume its mapped native agent session.

### Wiki tab

`WIKI` replaces the chat content area with a two-pane wiki browser: a compact document/category picker and the selected Markdown page. It supports safe Markdown rendering, search, last-updated information, and an `Ask Bob about this page` action. Wiki writes still require the existing explicit approval rules.

### Bob Agent Info panel

The right panel remains visible on desktop and becomes a collapsible drawer on smaller screens. It displays Bob's status, active client/account, workspace, selected model profile, current job state, available capabilities, and connection state. It never displays credentials, tokens, raw session files, or sensitive prompts. Mobile must provide an accessible control to open and close the drawer; it must not remove the panel entirely.

### UI states

The client visibly distinguishes `READY`, `THINKING`, `RUNNING BOB COMMAND`, `WAITING FOR APPROVAL`, `COMPLETED`, `FAILED`, and `CANCELLED`. Technical command progress is collapsed by default so the normal experience remains a clean conversation.

The first implementation serves a responsive static frontend from `server/static/` using semantic HTML, CSS, and a small JavaScript module. Server-Sent Events stream job progress and final responses. React or another frontend build system is deferred until the interaction model stabilizes.

**SSE implementation:** Use the job-scoped endpoint `GET /api/jobs/{job_id}/events`. Events have monotonically increasing IDs and clients reconnect with `Last-Event-ID`. The server sends keep-alive comments, replays only missed events, emits one terminal event, and closes the stream after completion, failure, or cancellation. The client uses bounded exponential backoff and must not duplicate a final response after reconnecting.

Additional UI endpoints:

```text
GET  /api/conversations
GET  /api/conversations/{conversation_id}
GET  /api/wiki
GET  /api/wiki/{path}
POST /api/wiki/{path}/ask
POST /api/jobs/{job_id}/cancel
POST /api/approvals/{approval_id}/approve
POST /api/approvals/{approval_id}/reject
```

## 10. Capability-based model routing

Routing occurs before creating or resuming the agent process:

```text
fast      account/configuration help and simple status questions
standard  one standard comparison or straightforward data question
strong    diagnosis, recommendations, Target, video, or mutation planning
```

Example configuration:

```yaml
agent:
  backend: codex
  profiles:
    fast:
      model: <fast-model>
      timeout_seconds: 90
    standard:
      model: <standard-model>
      timeout_seconds: 240
    strong:
      model: <strong-model>
      timeout_seconds: 600
  routing:
    account_setup: fast
    standard_comparison: standard
    diagnosis: strong
    target: strong
    video: strong
    mutation: strong
```

Fallback rules:

- Retry once with the next stronger profile on timeout, invalid output, or inability to select a valid Bob command.
- Preserve the same native session and job workspace during escalation when safe.
- Never automatically retry a mutation after execution may have started.
- Re-check Google Ads state before any mutation retry.
- Record selected profile, fallback reason, duration, and cost metadata.

## 11. Deployment model

Use a provider-neutral Docker image and Docker Compose first.

The target shape is one shared gateway with an isolated Bob worker per client:

```text
timfrmmktg.com
        |
        v
  Gateway/API container
        |
        +-- client-primary worker + Bob/data volume
        +-- client-other worker  + Bob/data volume
        `-- client-third worker  + Bob/data volume
```

Phase 1 uses one client worker on one VPS. Additional clients are added as separate worker containers with separate volumes, credentials, Codex session state, and resource limits. Bob's existing repository-wide path assumptions remain safe because each worker has its own filesystem root.

The initial deployment contains:

- FastAPI web/API and process supervisor container;
- one isolated Bob worker container;
- persistent Bob workspace volume for that client;
- persistent Codex/Claude runtime volume for that client;
- SQLite metadata volume for users, access, conversations, and jobs;
- optional reverse proxy with HTTPS.

The image must:

- use the existing `uv.lock` and `pyproject.toml`;
- pin the agent CLI versions;
- install only hosted-runtime dependencies required by the selected capabilities;
- run as a non-root user;
- include a healthcheck;
- apply CPU, memory, process, timeout, and disk limits;
- keep application logs separate from secret-bearing process output;
- receive credentials through secrets rather than image layers or source files.

CI/CD for the first client must:

1. run the existing test suite;
2. validate the lockfile and build the Docker image;
3. scan and publish a versioned image;
4. deploy a pinned image tag or digest to the VPS;
5. run a healthcheck and read-only smoke test;
6. retain the previous image for rollback.

The VPS must not deploy by running `git pull` in place. Client data and native agent sessions live in volumes and must survive image replacement.

## 12. Migration phases

### Phase 0 — Runner spike ✅ VERIFIED

**Completed during local runner validation:**

- ✅ Codex `exec` runs in non-interactive mode with `--json` output
- ✅ `exec resume <thread_id>` persists and resumes sessions (confirmed via cached_input_tokens)
- ✅ Bob instructions and `./bob` commands work from non-interactive process
- ✅ Structured JSONL event streaming works
- ✅ Thread ID returned in `{"type":"thread.started","thread_id":"..."}`

**Verified commands:**
```bash
# Create session
codex exec --cd /tmp --skip-git-repo-check --json "first message"
# → thread_id: 01a005a1-742a-76d2-b6ee-45a4c44a7971

# Resume session
codex exec resume 01a005a1-742a-76d2-b6ee-45a4c44a7971 "second message" --json
# → cached_input_tokens: 9984 (conversation preserved)
```

**Still needed:**
- Process timeout and cancellation testing
- Claude `-p` authentication and session behavior (if Claude backend selected)
- Process cleanup on interrupt/timeout

### Phase 1 — One-client hosted MVP

Goal: prove the complete hosted experience for one client while establishing the main-domain,
membership-based tenant boundary that will support additional clients later.

**Implementation files needed:**

1. **`Dockerfile`** - Python 3.12 + uv + Node.js + Codex CLI
2. **`docker-compose.yml`** - Web service + volumes
3. **`server/app.py`** - FastAPI application + routes
4. **`server/auth.py`** - instance access, invite, and waitlist flow; Google Sign-In is deferred
5. **`server/agent_runner.py`** - Process supervisor + Codex adapter
6. **`server/models.py`** - SQLite schemas (conversation metadata, job state)
7. **`server/schema.sql`** - Database schema with encryption setup
8. **`server/static/index.html`** - Retro chat shell with History/Wiki tabs and right Agent Info panel
9. **`server/static/styles.css`** - Responsive retro visual system
10. **`server/static/app.js`** - Conversation switcher, SSE events, chat, Wiki, and approval interactions
11. **`.dockerignore`** - Exclude data/, logs/, .venv*, and local credentials/state
12. **`docker/entrypoint.sh`** - Initialize the client volume and preserve Bob's historical state paths
13. **`scripts/migrate-client-state.sh`** - One-time copy of an existing client's `.bob`, data, Wiki, logs, and validation state

**Runtime-refactor files to touch after the hosted MVP is stable:**

1. **`server/app.py`** - Remove shared web writes to `.bob/accounts.json`, build explicit web runtime context, and replace broad client read locks with duplicate-work coordination.
2. **`server/agent_runner.py`** - Pass explicit request-scoped runtime inputs into Codex/Claude execution instead of relying on ambient shared account state.
3. **`lib/datapull.py`** - Prefer explicit account/customer/runtime context for hosted web requests; keep "active account" only as the CLI fallback.
4. **`.agents/skills/bob-performance-analysis/SKILL.md`** - Remove instructions that assume hosted runs use shared active-account state.
5. **`.agents/skills/bob-accounts/SKILL.md`** - Distinguish local CLI account switching from web conversation/account selection.
6. **`server/schema.sql`** - Extend job/fingerprint storage if durable duplicate-pull dedupe metadata is added.

**Capabilities:**

- Add instance admin, invite codes, waitlisted users, approved members, and client authorization.
- Add password/session security, bootstrap-secret invalidation, and CSRF protection.
- Add conversation, message, job, status, and event APIs.
- Add the SQLite tables and encrypted metadata model defined in Section 9B.
- Add SQLite session/job metadata (conversation_id → thread_id mapping) and the UI message projection.
- Add the Codex adapter using native persistent sessions (exec + exec resume).
- Add one client workspace volume.
- Migrate the existing client state into that volume before first startup; code, skills, query templates, and the launcher remain image-owned.
- Support read-only Bob questions.
- Add process limits (asyncio.Semaphore), timeout, cancellation, and audit logging.
- Add job-scoped SSE with event IDs, keep-alives, bounded reconnect, and terminal-event idempotency.
- Run one gateway and one isolated client worker through Docker Compose on one VPS.
- Use manual image deployment and one read-only smoke test after deployment.

Out of scope for this phase:

- Google Sign-In callback configuration;
- multiple client workers;
- automated fleet rollout or canary deployment;
- shared multi-tenant Bob filesystem;
- final domain/subdomain strategy;
- Telegram;
- production mutation write-back.

### Phase 2 — Thin-client onboarding and Google Ads setup

- Move account onboarding into the web UI.
- Store developer tokens and OAuth credentials through server-side secrets.
- Keep organization/application credentials separate from each user's Google Ads connection.
- Let each user start Google Ads OAuth from chat and authorize with their own Google account.
- Keep the existing chat onboarding phrase (`set me up` / `onboard me`) as the client-facing
  trigger. Bob responds with a short-lived Google authorization URL in the conversation; there is
  no separate client-facing setup form or Connect button.
- Store one protected Google connection per user and client instance; never store Google passwords.
- Discover multiple accounts under an MCC, then apply Bob's per-user account permission (`read` or
  `mutate`) configured by the admin.
- Use an environment-configured callback in local/test environments and production; do not bake
  a client domain into application code.
- Add explicit account-scoped web job context (`client_instance_id`, `user_id`, `conversation_id`,
  `account_id`, `customer_id`, `mcc_id`, and Google connection reference).
- Generate Google Ads runtime YAML/config from stored values only for the duration of a request if
  the Ads toolchain still requires a file. The refresh token remains stored as a protected user
  connection, not inside a durable runtime YAML file.
- Remove the need for users to install Python, `uv`, or agent CLIs locally.
- Let an approved user say `onboard me` in the thin client and complete the guided Bob onboarding flow.
- Keep credential entry in a secure form or secret-handling flow rather than ordinary chat history.
- Keep Google Sign-In deferred; the invite/session identity remains the MVP authentication mechanism.

### Phase 3 — Concurrent sessions, approvals, and second client

- Remove the web bridge that mutates shared active-account files for normal reads.
- Keep CLI active-account behavior as a local-only concern.
- Add lightweight request-scoped runtime artifacts where the Ads toolchain requires a file on disk.
- Add duplicate-pull dedupe keyed by `(client_instance_id, customer_id, query, from_date, to_date)`.
- Keep per-conversation serialization and client mutation locks.
- Add explicit approval UI and mutation audit records.
- Add model profiles and safe fallback behavior.
- Add a second client as a separate worker container and separate persistent volumes on the same VPS.
- Verify that users route only to their approved client worker.
- Verify that both clients are reachable through the selected host strategy and that membership
  checks prevent cross-client conversation, account, Wiki, and credential access.
- Continue updating the shared Docker image manually; do not refactor Bob into a shared filesystem yet.

### Phase 4 — Centralized code rollout

- Build one versioned Bob image in CI and publish it to a container registry.
- Update client worker containers from the same image while preserving their volumes.
- Add a simple deployment script that updates all configured workers and checks health after each restart.
- Support rollback to the previous image version.
- A canary is optional: if used later, it means updating one client worker first, checking it, and then updating the remaining workers.

### Phase 5 — Provider and client expansion

- Add Claude adapter after server authentication and session behavior are verified.
- Add Telegram through the existing API.
- Add automated client-instance provisioning for Hetzner and GCP.
- Add backups, monitoring, and restore drills.
- Add Google Sign-In as a replaceable authentication provider after the invite/admin flow is stable.
- Move an individual client worker to its own VPS if resource usage or isolation requires it.

## 13. Test and acceptance criteria

- A new web conversation creates one persistent Codex session.
- A follow-up resumes the same Codex session.
- Two different conversations run concurrently without sharing session memory or mutable account state.
- Two messages in one conversation are serialized.
- API restart preserves the native session mapping and reports interrupted jobs correctly.
- Normal conversations never use `--ephemeral`.
- Desktop credentials are never required by the deployment.
- Unauthorized users cannot access another client instance.
- Read-only jobs can run concurrently.
- Two users in the same client can ask read-only questions against different accounts concurrently.
- Two identical read-only pulls for the same client/account/query/window reuse one underlying pull instead of launching two.
- Mutation jobs require approval and acquire an exclusive client lock.
- A timed-out process is terminated and reported cleanly.
- Secrets never appear in API responses, prompts, logs, or Git.
- The container runs as non-root and passes its healthcheck.
- Existing Bob CLI tests pass inside the container.
- A fresh instance can be provisioned without local Python, `uv`, Node, or agent CLI installation.

### UI and end-to-end verification

- The desktop layout has no permanent left-side navigation menu.
- The `HISTORY` and `WIKI` top-level tabs switch content without losing the active conversation.
- The History switcher/modal loads older conversations from the SQLite presentation index.
- Selecting an older conversation displays its saved UI projection and resumes the mapped native agent session for the next message.
- The right-side Bob Agent Info panel displays connection, account, workspace, model profile, capability, and job status without exposing credentials or raw session files.
- The Agent Info panel collapses into an accessible drawer on mobile-sized viewports.
- The UI renders `READY`, `THINKING`, `RUNNING BOB COMMAND`, `WAITING FOR APPROVAL`, `COMPLETED`, `FAILED`, and `CANCELLED` states distinctly.
- Server-Sent Events stream progress and the final response; reconnecting does not duplicate the final message.
- Stop, retry, timeout, and process-failure flows update the conversation and job state correctly.
- Wiki navigation renders Markdown safely, supports the document picker/search flow, and sends `Ask Bob about this page` through the normal conversation API.
- Wiki writes and Google Ads mutations show approval controls and cannot execute without explicit approval.
- Browser refresh and API restart preserve the conversation mapping and recover or clearly report interrupted jobs.
- Unauthenticated users cannot load conversations, Wiki content, or Agent Info for another client instance.
- Browser responses, rendered messages, SSE events, and client-side state contain no developer tokens, OAuth credentials, agent credentials, or sensitive prompts.
- The UI is keyboard navigable and readable at desktop and mobile breakpoints, including focus states, labels, and error messages.

The UI checks should run as browser-level end-to-end tests against a fake agent runner and seeded SQLite/wiki fixtures. They must not invoke Google Ads or real mutation commands. A separate deployment smoke test verifies the same flows against a real Codex runner in a disposable client instance.

## 14. Risks to verify before production

- Headless authentication, licensing, and account limits for each selected agent CLI.
- Stable streaming, resume, and cancellation behavior for each adapter.
- Whether per-job workspace copies are necessary for the data volume and startup time.
- Exact Google Ads OAuth redirect and secret-storage flow.
- Cost controls for concurrent users and strong-model fallback.
- Backup and restore behavior for Bob state and native agent session files.
- Operational behavior when an agent process exits after a Google Ads mutation may have started.
