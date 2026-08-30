# Continuous Deployment to the Debian GCP VM

This guide automates deployment whenever code is pushed to `main`.

```text
Push to GitHub main
        ↓
GitHub runs a syntax check
        ↓
GitHub SSHs into the Debian VM
        ↓
The VM pulls the latest code and rebuilds Bob
        ↓
The VM health check confirms the site is running
```

The `ubuntu-latest` runner below is GitHub's temporary machine. It is not the production VM. The
actual deployment commands run on the GCP VM, which is Debian.

## 1. Prepare the Debian VM

Connect to the VM:

```bash
gcloud compute ssh bob-frm-mktg \
  --zone us-central1-b \
  --project performance-marketing-351117
```

Go to Bob and protect the environment file:

```bash
cd /home/rajat_girdhar/bobFrmMktgCLI
chmod 600 .env
ls -l .env
```

The permissions should look like:

```text
-rw------- 1 rajat_girdhar rajat_girdhar .env
```

The `.env` file contains sensitive configuration, so only the VM user should be able to read it.

Allow the VM user to run Docker without `sudo`:

```bash
sudo usermod -aG docker $USER
newgrp docker
docker ps
```

## 2. Create a GitHub deployment key

Run this on your Mac, not on the VM:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/bob_deploy -C "github-actions-bob-deploy"
```

Display the public key:

```bash
cat ~/.ssh/bob_deploy.pub
```

Copy the complete line. On the Debian VM, add it to:

```bash
nano ~/.ssh/authorized_keys
```

Save with `Ctrl + O`, press `Enter`, then press `Ctrl + X`.

The private key remains on your Mac and is added only to GitHub Actions Secrets.

## 3. Add GitHub repository secrets

Open:

```text
GitHub repository → Settings → Secrets and variables → Actions → New repository secret
```

Create these three repository secrets:

### `VM_HOST`

```text
136.64.108.221
```

Use the VM's reserved static external IP.

### `VM_USER`

```text
rajat_girdhar
```

Confirm it on the VM with:

```bash
whoami
```

### `VM_SSH_PRIVATE_KEY`

On your Mac, run:

```bash
cat ~/.ssh/bob_deploy
```

Copy the entire output, including:

```text
-----BEGIN OPENSSH PRIVATE KEY-----
...
-----END OPENSSH PRIVATE KEY-----
```

Do not add `.env`, Google Ads credentials, OAuth secrets, or Codex credentials to GitHub.

## 4. Add the GitHub Actions workflow

On your Mac:

```bash
cd ~/Projects/bobFrmMktgCLI
mkdir -p .github/workflows
nano .github/workflows/deploy.yml
```

Paste:

```yaml
name: Deploy Bob

on:
  push:
    branches:
      - main

jobs:
  test-and-deploy:
    # GitHub's temporary runner, not the Debian production VM.
    runs-on: ubuntu-latest

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Check frontend JavaScript
        run: node --check server/static/app.js

      - name: Deploy to Debian GCP VM
        uses: appleboy/ssh-action@v1.2.2
        with:
          host: ${{ secrets.VM_HOST }}
          username: ${{ secrets.VM_USER }}
          key: ${{ secrets.VM_SSH_PRIVATE_KEY }}
          script: |
            set -e

            cd /home/rajat_girdhar/bobFrmMktgCLI

            chmod 600 .env

            git pull --ff-only origin main

            docker-compose up -d --build --force-recreate web

            sleep 5

            curl --fail http://127.0.0.1:8000/api/health

            docker-compose ps
```

Save nano with `Ctrl + O`, `Enter`, and `Ctrl + X`.

`runs-on: ubuntu-latest` is correct because it describes the GitHub runner. The remote script uses
the Debian VM's `docker-compose` command.

The workflow reapplies `chmod 600 .env` on every deployment, pulls only fast-forward changes, rebuilds
the web image, restarts Bob, and fails if the health endpoint does not respond successfully.

## 5. Commit and activate deployment

```bash
git add .github/workflows/deploy.yml
git commit -m "Add automatic VM deployment"
git push origin main
```

View the result in:

```text
GitHub repository → Actions → Deploy Bob
```

The deployment updates application code and the Docker image. The VM's `.env`, named Docker volumes,
Google credentials, users, wiki, and Codex login remain on the VM.
