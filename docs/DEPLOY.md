# Bob Deployment Guide

This is the MVP deployment path for a Hetzner VPS or a GCP Compute Engine VM.

Recommended architecture:

```text
Hetzner VPS or GCP VM
└── Docker Compose
    └── Bob container
        ├── /app: server, skills, and CLI code
        └── persistent volumes
            ├── /data/client       client data, wiki, processed data
            ├── /data/metadata     users, clients, conversations, jobs
            ├── /data/secrets      Google OAuth secrets
            └── /data/codex        Codex authentication and sessions
```

Start with a VPS or Compute Engine VM rather than Cloud Run. Bob currently needs persistent volumes, Codex session history, and a long-running worker process.

The repository already contains the image and Compose setup in [Dockerfile](../Dockerfile) and [docker-compose.yml](../docker-compose.yml).

The image installs `bubblewrap` (`bwrap`) for Codex's hosted Linux sandbox. Desktop mode uses the
Docker boundary with Codex's sandbox bypass; hosted mode must retain Codex `workspace-write`.

## Docker parity retrospective

Docker makes the image reproducible; it does not make two deployments identical when the image,
environment, volumes, session history, or host architecture differ. The first hosted rollout
departed from local development in several concrete ways:

| Area | Local development | Fresh GCP deployment | Result |
| --- | --- | --- | --- |
| Source tree | Included the generated, gitignored `./bob` launcher | Fresh clone did not contain `./bob` | Codex could load `.agents` but could not run Bob's CLI |
| Runtime policy | `BOB_RUNTIME=desktop` bypassed Codex's nested Linux sandbox | `BOB_RUNTIME=hosted` used `workspace-write` | Hosted mode exposed path and sandbox assumptions hidden locally |
| State | Existing local files and permissions | New Docker named volumes | Secret-volume ownership initially blocked the unprivileged `bob` user |
| Sessions | Local/new Codex sessions | Persisted sessions created before runner fixes | `exec resume` retained stale session capabilities and context |
| Build state | Existing development image/cache | Repeated `--no-cache` VM builds | Old layers consumed the small VM disk until Docker cache was pruned |
| Networking | Localhost browser callbacks | Headless VM and public OAuth callback | Codex needed device auth; Google OAuth needed an HTTPS hostname |

The key lesson is to test the artifact built from a **fresh Git clone**, because gitignored generated
files can make a developer checkout appear complete while the production image is incomplete. Bob's
Dockerfile now generates `/app/bob` during the image build, and the entrypoint refuses to start if
that launcher is missing. Conversation workspaces now materialize small disposable snapshots of
image-owned instructions, `.agents`, and GARF query templates. They use a real local `./bob` wrapper
that executes `/app/bob`, while client state remains linked within `/data/client`. Linking `.agents`
from a writable workspace to read-only `/app/.agents` is not safe: Bubblewrap refuses to construct
the sandbox because the protected instruction path crosses a writable symlink. The launcher itself
resolves to `/app`, reuses `/app/.venv`, and never creates a per-conversation virtual environment.

For reliable parity, all of these must match:

```text
same Git commit
+ image rebuilt from that commit
+ same required environment variables
+ expected named-volume ownership and contents
+ compatible CPU architecture
+ fresh or compatible Codex session state
= comparable local and VM behaviour
```

### Local versus hosted contract

The two environments are intentionally not identical in every detail. They must share the same Bob
code, skills, CLI behavior, calculations, and account isolation, while using different operating
boundaries and authentication flows.

| Concern | Local desktop | Hosted VM | Required solution/status |
| --- | --- | --- | --- |
| Source | Developer checkout may contain generated/ignored files | Fresh Git clone contains tracked files only | Docker build generates every required runtime artifact, including `/app/bob` — fixed |
| Bob launcher | Usually invoked as a real file from the repo root | Real workspace wrapper executes image-owned `/app/bob` | Launcher resolves to `/app` and reuses the image environment — fixed |
| Python environment | Local project `.venv` | Image-built `/app/.venv` | Hosted launcher must reuse `/app/.venv`; no per-conversation environments — fixed, verify on VM |
| Codex sandbox | Desktop mode may use Docker as the outer boundary and bypass nested sandboxing | Hosted mode uses Codex `workspace-write` with `bubblewrap` | Runtime switch and `bwrap` installation — fixed, verify command execution on VM |
| Skills/code | Read from local checkout | Image-owned under `/app`; small runtime snapshots are copied into each writable conversation workspace | Avoids Bubblewrap's writable-symlink rejection while preserving image ownership — fixed |
| Shell environment | Local shell naturally sees developer environment | Codex filters custom variables before running tools | Runner explicitly passes only Bob state/config paths through `shell_environment_policy.set` — fixed |
| Client state | Local `data/` paths | Named volumes under `/data/*` | All code must use configured state roots; volume ownership must permit user `bob` — fixed, existing volumes may need one repair |
| Codex state | Local Codex home | Persistent `codex-data` volume at `/data/codex` | Use device auth on headless VM; rebuilds retain login — fixed |
| Conversation context | Local sessions | Persistent native Codex session IDs in metadata | Reset session IDs once after sandbox/runner migrations; normal resume afterward — operational step |
| Google OAuth | Localhost callback allowed for development | Public HTTPS callback required | `nip.io` + Caddy for MVP, real domain for production — configured operationally |
| Networking | Localhost | GCP firewall, static IP, reverse proxy | Permit 80/443; close direct 8000 after HTTPS is stable — remaining hardening |
| Secrets | Local ignored files | Protected secret volume | Keep out of Git; migrate to GCP Secret Manager for stronger production protection — later phase |
| Logs | Developer terminal | Controlled container diagnostics | `BOB_DEBUG_LOGGING`, redacted and disabled normally — fixed |
| Disk | Developer machine storage | Small VM boot disk and Docker layers | Monitor `df -h`/`docker system df`; avoid unnecessary `--no-cache` builds — operational requirement |

What must behave identically in both environments:

- the same Git commit and Bob version;
- the same skill routing and CLI command map;
- deterministic Google Ads pulls and calculations;
- per-user conversation context and per-account permissions;
- wiki and processed-data behavior;
- no fabricated metrics when a CLI command fails.

What may legitimately differ:

- desktop versus hosted Codex sandbox policy;
- localhost versus HTTPS OAuth callback;
- local directories versus Docker named volumes;
- interactive local login versus headless device authentication;
- CPU architecture, provided the image is built natively on the target VM or for `linux/amd64`.

Before declaring a VM release ready, test from a fresh clone and a fresh conversation—not from a
developer checkout or a pre-migration Codex session. The release gate is:

```bash
git rev-parse HEAD
docker-compose build
docker-compose up -d --force-recreate
docker-compose exec web ls -l /app/bob
docker-compose exec web /app/bob
docker-compose exec web which bwrap
docker-compose exec web codex login status
curl http://127.0.0.1:8000/api/health
```

Then verify through the browser that a newly created conversation can answer one account question
using verified CLI data, resume the same conversation for a follow-up, switch accounts, enforce a
`NONE` permission, and load the wiki.

## First deployment

Provision an Ubuntu VM, install Docker and Git, then run:

```bash
git clone <repository-url>
cd bobFrmMktgCLI
docker compose build
docker compose up -d
```

The initial site will be available at `http://SERVER_IP:8000`. Point the production DNS record at the server and put Caddy or Nginx in front of Bob for HTTPS.

## GCP quick-start guide (Debian VM)

This is the tested MVP path for a GCP Compute Engine VM using a temporary HTTP address. HTTPS and a domain can be added later.

### 1. Create and connect to the VM

Use an x86-64 VM with at least 2 vCPUs, 4 GB RAM, 40 GB disk, and a public IPv4 address. Debian is fine; Ubuntu is not required. Add your Mac's public SSH key (`~/.ssh/id_ed25519.pub`) to the VM if using direct SSH. Never paste the private key (`~/.ssh/id_ed25519`).

The simplest first connection is the **SSH** button beside the VM in the GCP console. From a local terminal, direct SSH uses:

```bash
ssh YOUR_GCP_USERNAME@YOUR_EXTERNAL_IP
```

### 2. Install Git and Docker on Debian

```bash
sudo apt update
sudo apt install -y git docker.io docker-compose
sudo systemctl enable --now docker
docker --version
docker-compose --version
```

Debian may provide the standalone `docker-compose` command rather than the newer `docker compose` plugin. Use the hyphenated command consistently on that VM.

### 3. Reserve a static IP

In GCP, open **VPC network → IP addresses**, find the VM's ephemeral external IP, and choose **Promote to static IP**. Keep the static IP attached to the running VM. This avoids the address changing after a stop/start.

### 4. Allow Bob's test port

Add a network tag such as `bob-web` to the VM. Then create a VPC firewall rule:

```text
Name: allow-bob-8000
Network: default
Direction: Ingress
Action: Allow
Target tags: bob-web
Source IPv4 ranges: 0.0.0.0/0
Protocols and ports: TCP 8000
```

Port 8000 is for temporary MVP testing only. Production should expose HTTPS on ports 80 and 443 through Caddy or Nginx.

### 5. Clone Bob and create the server environment

```bash
git clone <repository-url>
cd bobFrmMktgCLI
nano .env
```

For the current static-IP test, use:

```env
ADMIN_IDENTIFIER=superadmin
ADMIN_PASSWORD=<strong-admin-password>
ADMIN_CLIENT_NAME=FRM MKTG
BOB_ENVIRONMENT=production
BOB_RUNTIME=hosted
BOB_PUBLIC_BASE_URL=http://YOUR_STATIC_IP:8000
GOOGLE_OAUTH_REDIRECT_URI=http://YOUR_STATIC_IP:8000/api/google-ads/oauth/callback
BOB_CODEX_MODEL=gpt-5.6-luna
```

Replace `YOUR_STATIC_IP` and `<strong-admin-password>`. Save the file, then protect it:

```bash
chmod 600 .env
```

Never commit this file. Google Ads developer tokens and OAuth secrets are entered through the Admin UI and stored in the protected Docker volumes.

### 6. Build and start Bob

```bash
docker-compose build
docker-compose up -d
docker-compose ps
curl http://127.0.0.1:8000/api/health
```

The health response should be:

```json
{"status":"ok"}
```

Open `http://YOUR_STATIC_IP:8000` in a browser.

### 7. Authenticate Codex inside the container

Codex must be logged in inside Bob's container, not only on the VM host. Because a GCP VM is headless, use device authentication:

```bash
docker-compose exec web codex login --device-auth
docker-compose exec web codex login status
docker-compose exec web codex --version
```

The command displays a URL and a short code. Open the URL on your local computer, enter the code, and complete authentication. No localhost callback tunnel is required.

Test the same execution path Bob uses:

```bash
docker-compose exec web codex exec \
  --sandbox workspace-write \
  --skip-git-repo-check \
  "Reply with the word READY"
```

Codex credentials and sessions are stored in the persistent `codex-data` volume mounted at `/data/codex`.

To change the Codex account later:

```bash
docker-compose exec web codex logout
docker-compose exec web codex login --device-auth
docker-compose exec web codex login status
```

This changes Codex authentication only; it does not remove Bob's client data, conversations, or wiki.

### 8. Troubleshoot secret-volume permissions

If the Admin UI shows **Internal Server Error** and the container log contains:

```text
PermissionError: [Errno 13] Permission denied: '/data/secrets/...'
```

the secret files are present but are owned by a different Linux user. Bob intentionally runs as the
unprivileged `bob` user, so it cannot read files owned by `root` or another user. Repair ownership
and permissions from the repository directory:

```bash
cd ~/bobFrmMktgCLI
docker-compose exec -u root web chown -R bob:bob /data/secrets
docker-compose exec -u root web chmod 700 /data/secrets
docker-compose exec -u root web sh -c "find /data/secrets -type f -exec chmod 600 {} +"
docker-compose restart web
```

These commands do not print, replace, or delete credentials. They make the directory accessible only
to Bob and each secret file readable/writable only by Bob. Verify the result with:

```bash
docker-compose exec web ls -la /data/secrets
```

Files should be owned by `bob` and have permissions similar to `-rw-------`. After the restart,
retry **TEST APPLICATION** in the Admin UI. If the `find` command is mangled by terminal quoting,
the simpler fallback is:

```bash
docker-compose exec -u root web sh -c "chmod 600 /data/secrets/*"
docker-compose restart web
```

### 9. Test the MVP flow

1. Sign in as `superadmin`.
2. Confirm the client, MCC, Google Ads accounts, users, and account permissions.
3. Sign out and sign in as a client user.
4. Ask `Which account am I on?`.
5. Ask `What happened last week?`.
6. Switch the account dropdown and repeat the question.
7. Confirm a user with `NONE` permission is blocked before Codex runs.
8. Ask `Set me up` and complete the Google authorization flow.

Keep the application logs visible while testing:

```bash
docker-compose logs -f web
```

### 10. Later: domain and HTTPS

After the IP-based MVP test works, point an `A` record at the static IP and use Caddy or Nginx for HTTPS. Then update `.env`:

```env
BOB_PUBLIC_BASE_URL=https://bob.example.com
GOOGLE_OAUTH_REDIRECT_URI=https://bob.example.com/api/google-ads/oauth/callback
```

Register the same HTTPS callback URL in Google Cloud Console, allow ports 80 and 443, and restart Bob with `docker-compose up -d`.

### Temporary HTTPS with nip.io

Before buying a domain, a static public IP can be used with `nip.io`. For example, if the VM's
static IP is `136.64.108.221`, the temporary hostname is:

```text
136.64.108.221.nip.io
```

`nip.io` resolves this hostname to the embedded IP address. It is suitable for MVP testing only;
use a real domain before production.

1. In GCP, create or confirm an ingress firewall rule for TCP ports `80` and `443`. The rule should
   target the VM's network tag, such as `bob-web`.
2. Install Caddy on the VM:

```bash
sudo apt update
sudo apt install -y caddy
```

3. Configure the reverse proxy:

```bash
sudo nano /etc/caddy/Caddyfile
```

Use:

```text
136.64.108.221.nip.io {
    reverse_proxy 127.0.0.1:8000
}
```

Replace the IP if the VM has a different static IP. Save with `Ctrl+O`, press Enter, then exit
with `Ctrl+X`. Start and reload Caddy:

```bash
sudo systemctl enable --now caddy
sudo systemctl reload caddy
sudo systemctl status caddy
```

Caddy obtains and renews the HTTPS certificate automatically. Update Bob's server-only `.env`:

```env
BOB_PUBLIC_BASE_URL=https://136.64.108.221.nip.io
GOOGLE_OAUTH_REDIRECT_URI=https://136.64.108.221.nip.io/api/google-ads/oauth/callback
```

Restart Bob:

```bash
cd ~/bobFrmMktgCLI
docker-compose up -d
```

Register this exact URI in the Google Cloud OAuth client:

```text
https://136.64.108.221.nip.io/api/google-ads/oauth/callback
```

Open Bob at `https://136.64.108.221.nip.io`. A public IP over plain HTTP is only for testing Bob
itself; Google OAuth for the hosted application should use the HTTPS hostname.

## Updating Bob on the VM

Run updates from the repository directory:

```bash
cd ~/bobFrmMktgCLI
git pull origin main
docker-compose build --no-cache
docker-compose up -d
docker-compose ps
```

What these commands do:

- `git pull origin main` downloads the latest committed code and documentation from GitHub.
- `docker-compose build --no-cache` rebuilds the image from the new source and reinstalls image
  dependencies, such as `bubblewrap`. `--no-cache` ensures an old image layer is not reused when a
  dependency or Dockerfile changes.
- `docker-compose up -d` starts the updated container in the background. Docker volumes are not
  deleted, so client data, metadata, secrets, and Codex sessions remain intact.
- `docker-compose ps` confirms whether the container is running.

After an update, verify the image and application:

```bash
docker-compose exec web which bwrap
curl http://127.0.0.1:8000/api/health
docker-compose logs --tail=100 web
```

For a routine code-only update, `docker-compose build` is usually sufficient; use
`--no-cache` after Dockerfile, Python dependency, Codex, or system-package changes. Never run
`docker-compose down -v` during an update because `-v` deletes the named data volumes.

### Verify the hosted runtime after an image update

Run these checks before browser testing:

```bash
docker-compose exec web ls -l /app/bob
docker-compose exec web /app/bob
docker-compose exec web which bwrap
docker-compose exec web codex login status
curl http://127.0.0.1:8000/api/health
```

`/app/bob` must exist and be executable. The conversation runtime creates `./bob` as a symlink to
this image-owned launcher; if `/app/bob` is absent, performance questions can still receive a model
response but no verified CLI data can be fetched.

### Controlled Codex diagnostics

Codex process diagnostics are disabled by default:

```env
BOB_DEBUG_LOGGING=false
```

To investigate a hosted job, edit the VM's `.env` and temporarily set:

```env
BOB_DEBUG_LOGGING=true
```

Recreate the container so Compose passes the changed environment:

```bash
docker-compose up -d --force-recreate
docker-compose exec web printenv BOB_DEBUG_LOGGING
docker-compose logs -f web
```

The log records the runtime, new-versus-resumed session, working directory, safe Codex arguments,
exit code, duration, and stderr on process failure. It deliberately excludes the user prompt and
does not print developer tokens, OAuth secrets, refresh tokens, passwords, or authorization URLs.

Typical lines are:

```text
codex start runtime=hosted session=False cwd=... args=[...]
codex completed exit=0 duration=... session=...
codex failed exit=... duration=... stderr=...
```

Turn diagnostics off after the issue is resolved:

```env
BOB_DEBUG_LOGGING=false
```

Then recreate the container again with `docker-compose up -d --force-recreate`.

### New and resumed Codex sessions

A new hosted session receives `--sandbox workspace-write` and the required `--add-dir` paths. Codex
`exec resume` does not accept `--add-dir`; it reuses the permissions captured when the session was
created. After changing sandbox paths or runner capabilities, old sessions may therefore need to be
invalidated once. This preserves users, messages, wiki, credentials, and client data:

```bash
docker-compose exec web python -c 'import sqlite3;x=sqlite3.connect("/data/metadata/metadata.sqlite3");x.execute("UPDATE conversations SET agent_session_id=NULL");x.commit();print("sessions cleared")'
```

Use this only after a runner/sandbox migration, not as routine maintenance. The next request creates
a fresh native Codex session; later requests resume it normally.

### Disk space after repeated builds

Repeated `docker-compose build --no-cache` runs retain old layers and can fill a small VM disk. Check:

```bash
df -h
docker system df
```

Remove unused images and build cache without deleting named volumes:

```bash
docker system prune -af
docker builder prune -af
```

Never add `--volumes`, and never use `docker-compose down -v`, because Bob's persistent client data,
metadata, secrets, and Codex state live in named volumes.

### Which rollout steps were permanent versus temporary

Permanent, required fixes:

- install `bubblewrap` in the hosted image for Codex's Linux sandbox;
- allow the image-owned application root when creating a new hosted Codex session;
- pass `BOB_STATE_ROOT`, shared-state root, client scope, and the per-user Google Ads config path to
  Codex shell commands through an explicit allowlist; never inherit the full container environment;
- generate `/app/bob` during Docker build and fail startup if it is missing;
- execute image-owned `/app/bob` through a real workspace wrapper so jobs reuse `/app/.venv`
  instead of creating one virtual environment per conversation;
- materialize disposable conversation copies of `.agents`, instruction files, and GARF query
  templates instead of symlinking them across the writable workspace/read-only image boundary;
- run Bob as the unprivileged `bob` user and keep named-volume ownership compatible with that user;
- use Codex `--device-auth` on a headless VM;
- use HTTPS for the hosted Google OAuth callback;
- retain controlled, redacted job diagnostics for future incidents.

Temporary or one-time recovery actions:

- resetting `agent_session_id` was needed only to discard sessions created before runner fixes;
- changing ownership of `/data/secrets` repaired an existing volume and should not be a recurring task;
- pruning Docker build cache repaired disk exhaustion caused by repeated diagnostic rebuilds;
- `nip.io` is a temporary HTTPS hostname until a real domain is configured.

Redundant or superseded steps:

- the SSH tunnel and port `1455` mapping are unnecessary because Codex supports `--device-auth`;
- repeatedly refreshing the browser could not repair a persisted native Codex session;
- repeatedly rebuilding before adding diagnostics obscured the actual failure and consumed disk;
- broad Docker privileges such as `SYS_ADMIN` or `seccomp:unconfined` were not shown to fix the
  missing-launcher problem and should not be added unless a reproducible namespace error proves they
  are required. They weaken the container boundary.

## Complete deployment steps

### 1. Create the server

Use either a Hetzner Cloud VPS or a GCP Compute Engine Ubuntu VM. For the MVP, use at least 2 vCPUs, 4 GB RAM, 40 GB disk, and a static public IP.

### CPU architecture: Apple Silicon Mac to Intel GCP

The GCP E2 machine family is x86-64/Intel-compatible. Bob’s Dockerfile uses Python, Node.js, npm, and the Codex CLI and does not need a separate Intel Dockerfile. The simplest deployment is to clone the repository and run `docker compose build` on the GCP VM itself; Docker then builds the native `linux/amd64` image.

Your development Mac uses Apple Silicon (`arm64`). If you build the image on the Mac and transfer it to GCP, build for the GCP architecture explicitly:

```bash
docker buildx build --platform linux/amd64 -t bob:latest --load .
```

If you use a container registry:

```bash
docker buildx build --platform linux/amd64 -t REGISTRY/bob:latest --push .
```

If you only run `docker compose build` on the Mac, Docker normally creates an `arm64` image, which should not be used as the production image on the Intel VM. No Compose or application change is required when the image is built directly on GCP.

Install Docker and Git:

```bash
sudo apt update
sudo apt install -y git docker.io docker-compose-plugin
sudo systemctl enable --now docker
docker --version
docker compose version
```

### 2. Configure DNS

Create an `A` record such as:

```text
bob.example.com -> SERVER_PUBLIC_IP
```

For a temporary test, use `http://SERVER_PUBLIC_IP:8000`. For production, use a domain with HTTPS.

### 3. Clone and configure Bob

```bash
git clone <repository-url>
cd bobFrmMktgCLI
```

Create a server-only `.env` file and run `chmod 600 .env`. Never commit it.

Local development values are:

```env
ADMIN_IDENTIFIER=superadmin
ADMIN_PASSWORD=<local-password>
ADMIN_CLIENT_NAME=FRM MKTG
BOB_ENVIRONMENT=local
BOB_RUNTIME=desktop
BOB_PUBLIC_BASE_URL=http://127.0.0.1:8000
GOOGLE_OAUTH_REDIRECT_URI=http://127.0.0.1:8000/api/google-ads/oauth/callback
BOB_CODEX_MODEL=gpt-5.6-luna
```

The local Base URL must be exactly `http://127.0.0.1:8000`; do not add another `/:8000` suffix.

Production values are:

```env
ADMIN_IDENTIFIER=superadmin
ADMIN_PASSWORD=<strong-production-password>
ADMIN_CLIENT_NAME=FRM MKTG
BOB_ENVIRONMENT=production
BOB_RUNTIME=hosted
BOB_PUBLIC_BASE_URL=https://bob.example.com
GOOGLE_OAUTH_REDIRECT_URI=https://bob.example.com/api/google-ads/oauth/callback
BOB_CODEX_MODEL=gpt-5.6-luna
```

Local and production are separate deployments. Do not use the local callback URL in production.

### 4. Build and start the container

```bash
docker compose build
docker compose up -d
docker compose ps
docker compose logs --tail=100 web
curl http://127.0.0.1:8000/api/health
```

The health check should return `{"status":"ok"}`.

### 5. Configure HTTPS

Do not expose port `8000` publicly in production. Put Caddy or Nginx in front of Bob and proxy HTTPS to `127.0.0.1:8000`. With Caddy:

```text
bob.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

Allow only SSH, HTTP, and HTTPS through the firewall. Use HTTP only for redirecting to HTTPS.

### 6. Register Google OAuth

In Google Cloud Console, add this exact production callback to the OAuth client:

```text
https://bob.example.com/api/google-ads/oauth/callback
```

For local development, register the separate callback:

```text
http://127.0.0.1:8000/api/google-ads/oauth/callback
```

### 7. Log in to Codex

Codex is installed in the image. Authenticate it once inside the running container:

```bash
docker compose exec web codex login
docker compose exec web codex login status
docker compose exec web codex --version
```

Test the same execution style Bob uses:

```bash
docker compose exec web codex exec \
  --sandbox workspace-write \
  --skip-git-repo-check \
  "Reply with the word READY"
```

### 8. Configure the Admin UI

Open the local or production Bob URL and sign in as the super-admin. Open `Google Ads App` and enter the matching Base URL, Redirect URI, OAuth client ID, OAuth client secret, and Google Ads developer token. Save and test the application.

Then add clients, MCCs, Google Ads accounts, users, and account permissions. Approve the users. Each client user signs in and tells Bob `Set me up`; Bob then presents the Google authorization URL.

### 9. Client model defaults

The global default is configured by:

```env
BOB_CODEX_MODEL=gpt-5.6-luna
```

An administrator can override it per client in `Clients -> Edit Client`. Leave the client field blank to inherit the global default. The cost-first setting is model `gpt-5.6-luna` with reasoning effort `low`; the current MVP model field stores the model identifier, not the word `low`.

## Storage and credential protection

Compose creates four persistent volumes:

```text
bob-data       -> /data/client
metadata-data  -> /data/metadata
secret-data    -> /data/secrets
codex-data     -> /data/codex
```

`/data/client` contains client wiki and processed data. `/data/metadata` contains users, clients, conversations, jobs, and permissions. `/data/codex` contains Codex authentication and sessions. `/data/secrets` contains the actual OAuth secrets; SQLite stores references to them rather than raw secret values.

For the MVP, `/data/secrets` is protected at the application and container-filesystem level:

- the image runs Bob as the unprivileged `bob` user;
- the Dockerfile gives ownership of `/data` to `bob`;
- the secret directory is created with `0700` permissions;
- individual secret files are created with `0600` permissions;
- the named volume is not published as a host directory or served by the web app.

This is not the same as encryption at rest. A host administrator, Docker daemon administrator, or anyone who obtains the volume backup can still read the secrets. For production hardening, use GCP Secret Manager on GCP, or Vault/Docker secrets backed by a protected host secret store on Hetzner. Keep Codex authentication in its protected persistent `CODEX_HOME` volume because the CLI expects local files.

Back up `/data/client`, `/data/metadata`, `/data/secrets`, and `/data/codex` using encrypted backups.

## Deployment backlog: Google identity confirmation

Bob login identity and Google OAuth identity are separate. For example, a Bob user signed in as
`x@x.com` may complete Google Ads authorization using `y@x.com`, provided that the Google account
has access to the relevant MCC or accounts and the OAuth application permits it. The resulting
credential is stored against the Bob user who initiated the flow, not matched solely by email.

Before production rollout, display and record both identities after the OAuth callback:

```text
Bob user: x@x.com
Google account authorized: y@x.com
Google Ads accounts granted: <account list>
```

The implementation must treat OAuth `state` only as a flow-correlation value. It must not use the
email in `state` as proof of the Google identity. Add an Admin UI confirmation and audit trail for
the Google account returned by Google, so an administrator can detect an unintended account being
connected.

## Updating Bob

```bash
cd bobFrmMktgCLI
git pull origin main
docker compose build
docker compose up -d
```

Docker volumes remain intact during image updates. Verify with `docker compose ps`, `docker compose logs --tail=100 web`, and `curl http://127.0.0.1:8000/api/health`.

## Environment configuration

Create a server-only `.env` file. Never commit it:

```env
ADMIN_IDENTIFIER=superadmin
ADMIN_PASSWORD=<strong-password>
ADMIN_CLIENT_NAME=FRM MKTG
BOB_RUNTIME=hosted
BOB_PUBLIC_BASE_URL=https://your-domain.com
GOOGLE_OAUTH_REDIRECT_URI=https://your-domain.com/api/google-ads/oauth/callback
```

Add the exact production callback URL to the Google Cloud OAuth client:

```text
https://your-domain.com/api/google-ads/oauth/callback
```

The localhost callback is only for development.

## Codex CLI setup

Codex is installed inside the Docker image by the [Dockerfile](../Dockerfile):

```dockerfile
npm install --global "@openai/codex@0.147.0"
```

Authenticate it once from the VPS:

```bash
docker compose exec web codex login
```

Codex authentication is stored in `CODEX_HOME=/data/codex`, a persistent Docker volume. Rebuilding or restarting the container therefore does not require logging in again.

Verify the installation:

```bash
docker compose exec web codex login status
docker compose exec web codex --version
```

Test the same execution style Bob uses:

```bash
docker compose exec web codex exec \
  --sandbox workspace-write \
  --skip-git-repo-check \
  "Reply with the word READY"
```

Codex `exec` reuses saved CLI authentication by default. Treat the Codex authentication file like a password and never commit or share it. See the [official Codex non-interactive mode guidance](https://learn.chatgpt.com/docs/non-interactive-mode).

Hosted mode uses `--sandbox workspace-write`. Desktop mode may use the Docker outer boundary with the bypass setting, but that should not be enabled on the hosted VPS unless the security trade-off is explicitly accepted.

## Admin setup after deployment

1. Open `https://your-domain.com`.
2. Sign in as the super-admin.
3. Open `Google Ads App`.
4. Set the production base URL and redirect URL.
5. Add each client, MCC, and Google Ads account.
6. Add client users.
7. Approve the users.
8. Have each client user sign in and say `Set me up`.
9. Bob presents the Google authorization URL.
10. The user authorizes Google Ads.

Bob then stores the user’s Google connection securely and uses it for future jobs.

## Updating the server

For a manual update:

```bash
cd bobFrmMktgCLI
git pull origin main
docker compose build
docker compose up -d
```

The Docker volumes remain intact. Updating the image does not delete users, conversations, Codex sessions, client wiki data, Google connections, or processed data.

The next deployment improvement should be a GitHub Actions workflow that SSHes into the VPS, pulls `main`, rebuilds the image, and restarts Compose. Codex authentication and application data should remain on persistent volumes, never in Git.

## Operational checks

```bash
docker compose ps
docker compose logs --tail=100 web
curl http://127.0.0.1:8000/api/health
```

Hosted job protection and diagnostics are configured in the server-only `.env`:

```env
BOB_JOB_TIMEOUT_SECONDS=600
BOB_MAX_CONCURRENT_JOBS=1
BOB_DEBUG_LOGGING=false
```

The single-worker limit keeps the only VM from running multiple heavy Codex/data-pull processes at
once. A second request remains queued. A timed-out job terminates its full Codex child process
group, including shell, Bob, Python, and GARF children. Job diagnostics are written to the
persistent metadata volume:

```bash
docker compose exec web tail -f /data/metadata/logs/bob-runtime.jsonl
docker compose exec web grep -E 'job_failed|job_cancelled|timed out' /data/metadata/logs/bob-runtime.jsonl
```

The runtime log rotates at 5 MB and does not contain prompts, OAuth tokens, or developer tokens.
Set `BOB_DEBUG_LOGGING=true` only while diagnosing a problem, then recreate the web container and
set it back to `false`.

Back up these Docker volumes before major upgrades:

- `/data/client`
- `/data/metadata`
- `/data/secrets`
- `/data/codex`
