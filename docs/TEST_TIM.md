# TIM Hosted Gateway — Local End-to-End Test

This document tests the Phase 1 hosted gateway on your own computer. It uses a temporary database and workspace so it does not touch Bob's existing account data.

## 1. One-time prerequisites

From the Bob repository, confirm these commands exist:

```bash
uv --version
codex --version
```

Codex must already be authenticated on this computer. The gateway launches `codex exec` on your behalf; you do not run Codex separately for each question.

## 2. Start a fresh local server

Open Terminal and run:

```bash
cd /Users/rajatgirdhar/Projects/bobFrmMktgCLI

export ADMIN_BOOTSTRAP_SECRET=local-test-secret
export BOB_METADATA_DB=/tmp/bob-tim-test.sqlite3
export BOB_WORKSPACE_ROOT=/tmp/bob-tim-workspace

UV_CACHE_DIR=/tmp/bob-uv-cache uv run uvicorn server.app:app \
  --host 127.0.0.1 \
  --port 8000
```

Keep this Terminal window open. The server is now available at:

```text
http://localhost:8000
```

To reset the test completely, stop the server with `Ctrl+C`, choose new `/tmp` paths, and start it again.

## 3. First browser test: sign in as the provisioned admin

1. Open [http://localhost:8000](http://localhost:8000) in Chrome.
2. You should see the Bob landing screen.
3. Click **SIGN IN**.
4. Sign in with the configured `ADMIN_IDENTIFIER` and `ADMIN_PASSWORD`.
5. The workspace should open and the header should show `● ONLINE`.

The sign-in modal should close and the Bob workspace should appear. The header should show `● ONLINE`.

## 4. Send a test question

In the chat box, send:

```text
Reply with exactly: browser E2E passed
```

Expected result:

- Your message appears in the timeline.
- Bob's status changes from `READY` to `THINKING`.
- A response appears saying `browser E2E passed`.
- The status ends at `COMPLETED`.

Then refresh the page. The conversation and response should still be visible, and the status should return to `READY`.

## 5. Test the workspace UI

- Click **WIKI** and confirm the Wiki view opens.
- Click **HISTORY** and confirm the chat returns.
- Confirm the right-side **BOB AGENT INFO** panel shows connection, status, model, workspace, and capabilities.
- Resize Chrome to a narrow/mobile width and confirm the Agent Info panel becomes a collapsible drawer.

## 6. Add another user

The current Phase 1 UI supports invite redemption, but the admin invite-generation screen is not implemented yet. Generate a temporary invite through the authenticated API.

Use the browser's authenticated session and CSRF token. For a quick local test, open Chrome DevTools Console on the Bob page and run:

```js
fetch('/auth/session').then(r => r.json())
```

Copy the returned `csrf` value. Then run:

```js
fetch('/api/admin/invites', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'X-CSRF-Token': 'PASTE_CSRF_VALUE_HERE'
  },
  body: JSON.stringify({expires_hours: 72})
}).then(r => r.json())
```

Copy the returned `code`. In a new browser incognito window:

1. Open `http://localhost:8000`.
2. Click **SIGN IN**.
3. Expand **Have an invite code?**.
4. Enter the invite code, a new identifier, and a password.
5. Click **JOIN WORKSPACE**.

The second user should enter the workspace without seeing the admin setup screen.

## 7. Expected failure checks

- Wrong bootstrap secret: the modal shows an error and no admin is created.
- Wrong login password: the modal remains open and shows an authentication error.
- Reusing a bootstrap database: setup reports that bootstrap is already complete. Use a fresh `/tmp` database for another clean test.
- Missing Codex authentication: the user can sign in, but the job ends in `FAILED`; fix Codex authentication and retry.

## 8. Stop the test server

Return to the Terminal running uvicorn and press:

```text
Ctrl+C
```

The temporary database and workspace are under `/tmp` and are safe to discard after testing.
