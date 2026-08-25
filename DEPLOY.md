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

The repository already contains the image and Compose setup in [Dockerfile](./Dockerfile) and [docker-compose.yml](./docker-compose.yml).

## First deployment

Provision an Ubuntu VM, install Docker and Git, then run:

```bash
git clone <repository-url>
cd bobFrmMktgCLI
docker compose build
docker compose up -d
```

The initial site will be available at `http://SERVER_IP:8000`. Point the production DNS record at the server and put Caddy or Nginx in front of Bob for HTTPS.

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

Codex is installed inside the Docker image by the [Dockerfile](./Dockerfile):

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
