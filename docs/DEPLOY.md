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

## First deployment

Provision an Ubuntu VM, install Docker and Git, then run:

```bash
git clone <repository-url>
cd bobFrmMktgCLI
docker compose build
docker compose up -d
```

The initial site will be available at `http://SERVER_IP:8000`. Point the production DNS record at the server and put Caddy or Nginx in front of Bob for HTTPS.

## Complete deployment steps

### 1. Create the server

Use either a Hetzner Cloud VPS or a GCP Compute Engine Ubuntu VM. For the MVP, use at least 2 vCPUs, 4 GB RAM, 40 GB disk, and a static public IP.

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

Back up these Docker volumes before major upgrades:

- `/data/client`
- `/data/metadata`
- `/data/secrets`
- `/data/codex`
