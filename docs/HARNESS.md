# Harness

This document describes the current hosted Codex plumbing for Bob Frm Mktg.

## Purpose

Codex is the agent runtime and conversation-memory layer.

It is not the source of truth for:

- users
- client/account permissions
- Google Ads auth
- pull dedupe
- Bob data storage

Those responsibilities belong to the Bob gateway, secret store, SQLite metadata, and Bob's shared client state.

## High-level flow

```text
Browser UI
  |
  v
FastAPI gateway
  |
  |- auth/session
  |- client + user permission checks
  |- conversation record
  |- selected account on conversation
  |- job record + SSE events
  |
  v
Conversation runtime builder
  |
  |- creates per-conversation workspace
  |- creates per-conversation BOB_STATE_ROOT
  |- generates temp Google Ads YAML
  |- generates conversation-local .bob/accounts.json
  |- generates conversation-local account profiles
  |
  v
Codex CLI
  |
  |- codex exec
  |- codex exec resume
  |- agent_session_id = Codex memory/thread handle
  |
  v
Bob repo in conversation workspace
  |
  |- AGENTS.md
  |- .agents/skills/
  |- ./bob
  |- lib/datapull.py
  |
  v
Shared client data roots
  |
  |- wiki/
  |- data/processed/
  |- garf/outputs/raw/
  |- logs/
```

## Three layers

```text
Codex session id
= conversation memory

Conversation workspace/state root
= execution context for Bob

Client shared state
= durable data cache, wiki, and logs
```

These are separate on purpose.

`agent_session_id` preserves the chat thread and Codex memory.
It does not safely isolate Bob's filesystem/runtime expectations on its own.

## Detailed request path

1. User sends a prompt in the web UI.
2. Gateway authenticates the user and loads:
   - `user_id`
   - `client_instance_id`
   - `conversation_id`
   - `account_id`
3. Gateway creates or reuses:
   - `agent_session_id` for Codex memory
   - `workspace_id` for that conversation
4. Gateway builds conversation-local runtime paths under:
   - `data/client/runtime/conversations/<workspace_id>/workspace`
   - `data/client/runtime/conversations/<workspace_id>/state`
5. Gateway generates temporary runtime files in that conversation-local state:
   - Google Ads YAML
   - `.bob/accounts.json`
   - `.bob/accounts/<customer_id>/profile.json`
6. Gateway launches:
   - `codex exec` for the first turn
   - `codex exec resume <session_id>` for later turns
7. Codex runs Bob in that conversation workspace.
8. Bob reads conversation-local runtime state, but shared durable client data.
9. SSE streams progress and terminal status back to the UI.
10. Final assistant output is saved to conversation messages.

## Data ownership

| Layer | Owns |
| --- | --- |
| SQLite / gateway DB | users, clients, memberships, account permissions, conversations, jobs |
| Secret store | refresh tokens, developer token refs, OAuth secrets |
| Codex session | prompt history, reasoning continuity |
| Conversation runtime | temp YAML, temp `.bob/accounts.json`, temp account context |
| Shared client state | raw pulls, processed data, wiki, logs |

## Current hosted paths

```text
data/client/
  logs/
    clients/
      <client_instance_id>/
        pull-log.jsonl
        pull-locks/
  runtime/
    conversations/
      <workspace_id>/
        workspace/
          AGENTS.md -> linked
          .agents/ -> linked
          lib/ -> linked
          garf/queries -> linked
          .bob -> linked to local state
          wiki -> linked to shared client wiki
          data -> linked to shared client data
          logs -> linked to shared client logs
        state/
          .bob/
            runtime/google-ads-<user>.yaml
            accounts.json
            accounts/<customer_id>/profile.json
          wiki/ -> shared
          data/ -> shared
          logs/ -> shared
          garf/outputs/ -> shared
```

## Pull dedupe

Pull dedupe is fetch-level, not Codex-session-level.

The current logic is:

```text
Prompt needs fetch
  |
  v
lib/datapull.py fetch()
  |
  |- check client-scoped pull-log first
  |- check exact raw file on disk
  |- claim client-scoped pull-lock fingerprint
  |- if another identical pull is already running, wait/reuse
  |- else do one actual GARF pull
  |- log fetched or skipped_inflight
```

The effective fingerprint is:

```text
client_instance_id + account + query + from_date + to_date
```

## Important clarification about `.bob/accounts.json`

We reduced dependence on shared `.bob/accounts.json`, but we did not eliminate temporary `.bob/accounts.json`.

What changed:

- the web gateway no longer mutates one shared client-level `.bob/accounts.json`
- each conversation gets its own temporary `.bob/accounts.json`
- one conversation's account switch no longer affects another conversation

What did not change:

- Bob CLI and `lib/datapull.py` still expect account/runtime context through `.bob` files
- so the hosted path still generates conversation-local `.bob/accounts.json` as a compatibility bridge

That means the current state is:

- shared active-account dependency: removed from hosted web execution
- temporary `.bob/accounts.json` generation: still present

## Why this is acceptable now

The main concurrency bug was shared mutable account state across conversations.

That bug is solved because:

- account/runtime state is now per conversation
- Codex memory is per conversation
- durable data stays shared

This lets two users in the same client run different accounts concurrently without stomping on each other.

## Likely next cleanup

The next architectural cleanup would be to reduce or remove the temporary `.bob/accounts.json` bridge by making more of Bob's runtime account context explicit.

That would mean:

- pass explicit account/customer/runtime inputs more directly
- rely less on generated `.bob` files
- keep Codex session memory and Bob runtime state even more clearly separated

That cleanup is optional for correctness now. The current hosted harness is already safe for concurrent multi-user account use.
