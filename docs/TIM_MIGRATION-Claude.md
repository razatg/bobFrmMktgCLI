# TIM Migration - Claude Implementation (Simplified)

## Key Insights
- ✅ **No database needed** - Bob already stores creds in `.bob/accounts.json`
- ✅ **No conversation DB needed** - Codex/Claude have `/resume` built-in
- ✅ **Web UI only** - Simple chat interface
- ✅ **Test locally** - Deploy to cloud when ready

---

## Simplified Architecture

```
┌─────────────────────────────────────────────────────────┐
│ User Browser                                             │
└───────────┬──────────────────────────────────────────────┘
            │ HTTP/WebSocket
            ▼
┌─────────────────────────────────────────────────────────┐
│ FastAPI Server (localhost:8000 or VPS)                  │
│                                                          │
│  POST /api/chat                                          │
│    ├─ Receives user message                             │
│    ├─ Get/create user workspace                         │
│    ├─ Run: codex exec --cd /data/{user_id}/             │
│    │        --sandbox workspace-write                    │
│    │        "{message}"                                  │
│    └─ Return response                                    │
│                                                          │
│  Or use Codex sessions:                                 │
│    ├─ codex --bg --name user_{id}  (background session) │
│    ├─ Send messages via stdin                           │
│    └─ Read responses from stdout                        │
└─────────────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────┐
│ User Workspace: /data/{user_id}/                        │
│                                                          │
│  Bob context (copied once):                             │
│    ├─ CLAUDE.md, SOUL.md, .agents/                      │
│    ├─ lib/, bin/, garf/, ./bob                          │
│                                                          │
│  Bob data (persistent):                                 │
│    ├─ .bob/accounts.json (Google Ads creds)             │
│    ├─ data/ (GARF outputs, processed CSVs)              │
│    ├─ wiki/ (saved analyses)                            │
│    └─ logs/ (pull logs, session signals)                │
│                                                          │
│  Codex session state:                                   │
│    └─ .codex/ (conversation history via /resume)        │
└─────────────────────────────────────────────────────────┘
```

**Key simplification:**
- No PostgreSQL
- Codex/Claude manage conversation history
- Bob's existing `.bob/accounts.json` manages creds
- Per-user workspaces with isolated Codex sessions

---

## File Structure

```
bobFrmMktgCLI/
├── Dockerfile                    # NEW
├── docker-compose.yml            # NEW
├── .dockerignore                 # NEW
│
├── server/
│   ├── app.py                    # NEW - FastAPI server
│   └── static/
│       └── index.html            # NEW - Web UI
│
├── pyproject.toml                # EXISTING (no changes)
├── ./bob                         # EXISTING (no changes)
├── lib/, .agents/, etc.          # EXISTING (no changes)
```

Only 4 new files, 0 changes to Bob.

---

## Implementation

### **File 1: Dockerfile**

```dockerfile
FROM python:3.12-slim

# Install system deps
RUN apt-get update && apt-get install -y \
    git curl \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js + Codex CLI
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g codex

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

WORKDIR /app

# Copy Bob repo
COPY . .

# Install Bob's deps
RUN uv sync --frozen --all-extras

# Install server deps
RUN uv pip install fastapi uvicorn websockets

RUN mkdir -p /data

ENV BOB_DATA_DIR=/data
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

### **File 2: docker-compose.yml**

```yaml
version: '3.8'

services:
  web:
    build: .
    ports:
      - "8000:8000"
    volumes:
      # User workspaces (persistent)
      - bob_data:/data
      
      # Codex auth (mount your local login)
      - ~/.codex:/root/.codex:ro
      
      # Hot-reload for development
      - ./server:/app/server
      - ./lib:/app/lib
      - ./.agents:/app/.agents
      - ./CLAUDE.md:/app/CLAUDE.md
      - ./SOUL.md:/app/SOUL.md
      - ./AGENTS.md:/app/AGENTS.md
    
    environment:
      BOB_DATA_DIR: /data
    
    restart: unless-stopped

volumes:
  bob_data:
```

---

### **File 3: server/app.py**

```python
#!/usr/bin/env python3
"""
FastAPI server that provides web UI and chat API for Bob.
Uses Codex CLI exec for stateless execution.
"""

import os
import asyncio
import shutil
from pathlib import Path
from fastapi import FastAPI, WebSocket, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse

app = FastAPI(title="Bob - Performance Marketing AI")

BOB_DATA_DIR = Path(os.getenv("BOB_DATA_DIR", "/data"))
BOB_REPO_DIR = Path("/app")

# Session tracking (in-memory, ephemeral)
active_sessions = {}


def prepare_workspace(user_id: str) -> Path:
    """Prepare isolated workspace for user"""
    workspace = BOB_DATA_DIR / user_id
    workspace.mkdir(parents=True, exist_ok=True)
    
    # Copy Bob repo files (only once)
    for item in ["CLAUDE.md", "SOUL.md", "AGENTS.md", ".agents", "lib", "bin", "garf", "bob"]:
        src = BOB_REPO_DIR / item
        dst = workspace / item
        
        if not dst.exists() and src.exists():
            if src.is_file():
                shutil.copy2(src, dst)
            else:
                shutil.copytree(src, dst, dirs_exist_ok=True)
    
    # Ensure bob is executable
    bob_script = workspace / "bob"
    if bob_script.exists():
        bob_script.chmod(0o755)
    
    return workspace


async def run_codex_exec(workspace: Path, prompt: str) -> str:
    """Run Codex CLI in exec mode (stateless, no history)"""
    
    output_file = workspace / ".bob_response.txt"
    
    try:
        process = await asyncio.create_subprocess_exec(
            "codex", "exec",
            "--cd", str(workspace),
            "--sandbox", "workspace-write",
            "--ephemeral",
            "--output-last-message", str(output_file),
            prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=180  # 3 min timeout
        )
        
        if output_file.exists():
            response = output_file.read_text()
            output_file.unlink()
            return response
        else:
            error = stderr.decode() if stderr else "No response"
            return f"Error: {error}"
    
    except asyncio.TimeoutError:
        return "Request timed out (>3 min). Try a simpler query."
    
    except Exception as e:
        return f"Error: {str(e)}"


async def run_codex_session(workspace: Path, user_id: str, message: str) -> str:
    """Run Codex in background session mode (with history via /resume)"""
    
    # Check if session exists
    if user_id not in active_sessions:
        # Start new background session
        session_name = f"bob_{user_id}"
        
        process = await asyncio.create_subprocess_exec(
            "codex",
            "--bg",
            "--name", session_name,
            "--cd", str(workspace),
            "--sandbox", "workspace-write",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        active_sessions[user_id] = {
            "name": session_name,
            "process": process
        }
    
    session = active_sessions[user_id]
    
    # Send message to session
    session["process"].stdin.write((message + "\n").encode())
    await session["process"].stdin.drain()
    
    # Read response (wait for prompt)
    response_lines = []
    while True:
        line = await session["process"].stdout.readline()
        if not line:
            break
        
        text = line.decode().strip()
        if text == ">":  # Prompt returned
            break
        
        response_lines.append(text)
    
    return "\n".join(response_lines)


@app.get("/")
async def index():
    """Serve web UI"""
    html = """
<!DOCTYPE html>
<html>
<head>
    <title>Bob - Performance Marketing AI</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: #f5f5f5;
            height: 100vh;
            display: flex;
            flex-direction: column;
        }
        
        header {
            background: #2563eb;
            color: white;
            padding: 1rem 2rem;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        
        header h1 {
            font-size: 1.5rem;
            font-weight: 600;
        }
        
        #chat-container {
            flex: 1;
            overflow-y: auto;
            padding: 2rem;
            display: flex;
            flex-direction: column;
            gap: 1rem;
        }
        
        .message {
            max-width: 70%;
            padding: 1rem;
            border-radius: 0.5rem;
            line-height: 1.5;
            white-space: pre-wrap;
        }
        
        .message.user {
            align-self: flex-end;
            background: #2563eb;
            color: white;
        }
        
        .message.assistant {
            align-self: flex-start;
            background: white;
            border: 1px solid #e5e7eb;
        }
        
        .message.assistant pre {
            background: #f3f4f6;
            padding: 0.5rem;
            border-radius: 0.25rem;
            overflow-x: auto;
            margin: 0.5rem 0;
        }
        
        footer {
            background: white;
            padding: 1rem 2rem;
            border-top: 1px solid #e5e7eb;
            display: flex;
            gap: 0.5rem;
        }
        
        #message-input {
            flex: 1;
            padding: 0.75rem;
            border: 1px solid #d1d5db;
            border-radius: 0.5rem;
            font-size: 1rem;
        }
        
        #send-button {
            padding: 0.75rem 2rem;
            background: #2563eb;
            color: white;
            border: none;
            border-radius: 0.5rem;
            font-size: 1rem;
            cursor: pointer;
            font-weight: 500;
        }
        
        #send-button:hover {
            background: #1d4ed8;
        }
        
        #send-button:disabled {
            background: #9ca3af;
            cursor: not-allowed;
        }
        
        .typing {
            align-self: flex-start;
            background: white;
            border: 1px solid #e5e7eb;
            padding: 1rem;
            border-radius: 0.5rem;
            font-style: italic;
            color: #6b7280;
        }
    </style>
</head>
<body>
    <header>
        <h1>Bob — Performance Marketing AI</h1>
    </header>
    
    <div id="chat-container">
        <div class="message assistant">
            👋 Hi! I'm Bob, your performance marketing AI.
            
            Ask me anything about your Google Ads campaigns:
            • What happened yesterday?
            • Compare this week vs last week
            • Which campaigns are underperforming?
            
            First time? Say "set me up" to add your Google Ads account.
        </div>
    </div>
    
    <footer>
        <input 
            type="text" 
            id="message-input" 
            placeholder="Ask me anything..."
            autocomplete="off"
        />
        <button id="send-button">Send</button>
    </footer>
    
    <script>
        const chatContainer = document.getElementById('chat-container');
        const messageInput = document.getElementById('message-input');
        const sendButton = document.getElementById('send-button');
        
        // Generate simple user ID (in production, use proper auth)
        const userId = localStorage.getItem('bob_user_id') || 
                       'user_' + Math.random().toString(36).substr(2, 9);
        localStorage.setItem('bob_user_id', userId);
        
        function addMessage(role, content) {
            const div = document.createElement('div');
            div.className = `message ${role}`;
            div.textContent = content;
            chatContainer.appendChild(div);
            chatContainer.scrollTop = chatContainer.scrollHeight;
        }
        
        function addTypingIndicator() {
            const div = document.createElement('div');
            div.className = 'typing';
            div.id = 'typing-indicator';
            div.textContent = 'Bob is thinking...';
            chatContainer.appendChild(div);
            chatContainer.scrollTop = chatContainer.scrollHeight;
            return div;
        }
        
        function removeTypingIndicator() {
            const indicator = document.getElementById('typing-indicator');
            if (indicator) indicator.remove();
        }
        
        async function sendMessage() {
            const message = messageInput.value.trim();
            if (!message) return;
            
            // Add user message
            addMessage('user', message);
            messageInput.value = '';
            sendButton.disabled = true;
            
            // Show typing indicator
            const typing = addTypingIndicator();
            
            try {
                // Send to server
                const response = await fetch('/api/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ user_id: userId, message })
                });
                
                const data = await response.json();
                
                // Remove typing, add response
                removeTypingIndicator();
                addMessage('assistant', data.response);
            
            } catch (error) {
                removeTypingIndicator();
                addMessage('assistant', `Error: ${error.message}`);
            
            } finally {
                sendButton.disabled = false;
                messageInput.focus();
            }
        }
        
        sendButton.addEventListener('click', sendMessage);
        messageInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });
        
        messageInput.focus();
    </script>
</body>
</html>
    """
    return HTMLResponse(content=html)


@app.post("/api/chat")
async def chat(request: dict):
    """Handle chat messages"""
    user_id = request.get("user_id", "default")
    message = request.get("message", "")
    
    if not message:
        raise HTTPException(status_code=400, detail="Message required")
    
    # Prepare workspace
    workspace = prepare_workspace(user_id)
    
    # Run Codex (use exec mode for now, switch to session mode later for history)
    response = await run_codex_exec(workspace, message)
    
    return {"response": response}


@app.get("/health")
async def health():
    """Health check endpoint"""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

---

### **File 4: .dockerignore**

```
data/
logs/
wiki/
.venv*
__pycache__/
*.pyc
.git/
.DS_Store
*.log
tmp/
.claude/
.codex/
runtime/uv/
```

---

## Build & Run

### **Local Testing**

```bash
# Build
docker-compose build

# Run
docker-compose up

# Open browser
open http://localhost:8000

# Test in chat:
# "hi" -> Codex responds
# "list files" -> Codex runs ls
# "run ./bob --help" -> Shows Bob commands
# "set me up" -> Bob onboarding
```

### **Production Deploy**

```bash
# On VPS
git clone https://github.com/YOUR_USERNAME/bobFrmMktgCLI.git
cd bobFrmMktgCLI

# Run
docker compose up -d

# View logs
docker compose logs -f
```

---

## Git/Version Control

### **Feature Branch Workflow**

```bash
# Create branch
git checkout -b feature/web-server

# Add files
git add Dockerfile docker-compose.yml server/ .dockerignore
git commit -m "Add web server with Codex integration

- Dockerfile: Python 3.12 + uv + Codex CLI  
- server/app.py: FastAPI with chat API + web UI
- No database - uses Codex /resume for history
- Per-user workspaces with Bob context
"

# Push
git push -u origin feature/web-server

# Merge to main when ready
git checkout main
git merge feature/web-server
git push
```

### **Update .gitignore**

Add to existing `.gitignore`:
```
# Server
server/__pycache__/
*.pyc

# Runtime
runtime/uv/
```

---

## CI/CD Implementation

### **Phase 1: Automated Testing**

**File:** `.github/workflows/test.yml`

```yaml
name: Test

on:
  push:
    branches: [main, feature/*]
  pull_request:
    branches: [main]

jobs:
  test-bob-cli:
    name: Test Bob CLI
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      
      - name: Install uv
        run: curl -LsSf https://astral.sh/uv/install.sh | sh
      
      - name: Install dependencies
        run: |
          export PATH="$HOME/.local/bin:$PATH"
          uv sync --frozen --all-extras
      
      - name: Test Bob launcher
        run: |
          export PATH="$HOME/.local/bin:$PATH"
          ./bob --help
      
      - name: Run Python tests
        run: |
          export PATH="$HOME/.local/bin:$PATH"
          uv pip install pytest
          uv run pytest tests/ -v
  
  test-docker-build:
    name: Test Docker Build
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v4
      
      - name: Build Docker image
        run: docker build -t bob-server:test .
      
      - name: Test image can run
        run: |
          docker run --rm bob-server:test uv run python -c "print('OK')"
```

**What this does:**
- Runs on every push/PR
- Tests Bob CLI still works
- Tests Docker image builds
- Blocks merge if fails

---

### **Phase 2: Build & Push Docker Image**

**File:** `.github/workflows/build.yml`

```yaml
name: Build and Push

on:
  push:
    branches: [main]
    tags: ['v*']

jobs:
  build:
    name: Build Docker Image
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3
      
      - name: Login to Docker Hub
        uses: docker/login-action@v3
        with:
          username: ${{ secrets.DOCKERHUB_USERNAME }}
          password: ${{ secrets.DOCKERHUB_TOKEN }}
      
      - name: Extract metadata
        id: meta
        uses: docker/metadata-action@v5
        with:
          images: yourname/bob-server
          tags: |
            type=ref,event=branch
            type=semver,pattern={{version}}
            type=semver,pattern={{major}}.{{minor}}
            type=sha,prefix={{branch}}-
      
      - name: Build and push
        uses: docker/build-push-action@v5
        with:
          context: .
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=registry,ref=yourname/bob-server:buildcache
          cache-to: type=registry,ref=yourname/bob-server:buildcache,mode=max
```

**What this does:**
- Pushes to `main` → builds Docker image
- Pushes to Docker Hub
- Creates tags: `main`, `v1.0.0`, `main-abc123`
- Uses layer caching for faster builds

**Setup:**
1. Create Docker Hub account
2. Create access token
3. Add to GitHub Secrets:
   - `DOCKERHUB_USERNAME`
   - `DOCKERHUB_TOKEN`

---

### **Phase 3: Auto-Deploy to VPS**

**Option A: Watchtower (Simplest)**

On VPS:
```bash
# One-time setup
docker run -d \
  --name watchtower \
  -v /var/run/docker.sock:/var/run/docker.sock \
  containrrr/watchtower \
  --interval 300 \
  --cleanup
```

How it works:
- Push to `main` → GitHub builds image → Pushes to Docker Hub
- Watchtower checks every 5 minutes
- Sees new image → pulls → restarts container
- Old image removed automatically

**Option B: SSH Deploy (More Control)**

**File:** `.github/workflows/deploy.yml`

```yaml
name: Deploy to VPS

on:
  push:
    branches: [main]
  workflow_dispatch:  # Manual trigger

jobs:
  deploy:
    name: Deploy
    runs-on: ubuntu-latest
    
    steps:
      - name: Deploy via SSH
        uses: appleboy/ssh-action@v1.0.3
        with:
          host: ${{ secrets.VPS_HOST }}
          username: ${{ secrets.VPS_USER }}
          key: ${{ secrets.SSH_PRIVATE_KEY }}
          script: |
            cd /root/bobFrmMktgCLI
            git pull origin main
            docker compose pull
            docker compose up -d --force-recreate
            docker system prune -f
```

**Setup:**
1. Generate SSH key:
   ```bash
   ssh-keygen -t ed25519 -C "github-actions"
   ```
2. Add public key to VPS: `~/.ssh/authorized_keys`
3. Add to GitHub Secrets:
   - `VPS_HOST` (IP address)
   - `VPS_USER` (root or bob)
   - `SSH_PRIVATE_KEY` (private key content)

How it works:
- Push to `main` → GitHub SSHs to VPS
- Pulls latest code + image
- Recreates containers
- Cleans up old images

---

### **Phase 4: Rollback Strategy**

**Tag releases:**
```bash
# Before deploying a major change
git tag -a v1.0.0 -m "Release 1.0.0"
git push origin v1.0.0
```

**Rollback:**
```bash
# On VPS
cd /root/bobFrmMktgCLI

# Rollback code
git checkout v1.0.0

# Rollback image
docker compose pull
docker compose up -d --force-recreate
```

**Or use specific image tag:**
```yaml
# docker-compose.yml
services:
  web:
    image: yourname/bob-server:v1.0.0  # Pin to specific version
```

---

### **Phase 5: Monitoring & Alerts**

**Health Check Endpoint:**

Already in `server/app.py`:
```python
@app.get("/health")
async def health():
    return {"status": "ok"}
```

**External Monitoring:**

Use UptimeRobot (free):
1. Sign up at uptimerobot.com
2. Add monitor: `https://bob.yourdomain.com/health`
3. Check every 5 minutes
4. Alert via email/Slack if down

**Or GitHub Actions:**

**File:** `.github/workflows/healthcheck.yml`

```yaml
name: Health Check

on:
  schedule:
    - cron: '*/30 * * * *'  # Every 30 minutes
  workflow_dispatch:

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - name: Check health endpoint
        run: |
          curl -f https://bob.yourdomain.com/health || exit 1
      
      - name: Notify on failure
        if: failure()
        uses: 8398a7/action-slack@v3
        with:
          status: ${{ job.status }}
          text: '🚨 Bob server is down!'
          webhook_url: ${{ secrets.SLACK_WEBHOOK }}
```

---

## Complete CI/CD Flow

```
┌────────────────────────────────────────────────────────┐
│ Developer                                              │
│   git commit -m "Add feature"                          │
│   git push origin main                                 │
└───────────┬────────────────────────────────────────────┘
            │
            ▼
┌────────────────────────────────────────────────────────┐
│ GitHub Actions                                         │
│                                                         │
│  [1] Run Tests (.github/workflows/test.yml)            │
│      ├─ Test Bob CLI                                   │
│      ├─ Test Docker build                              │
│      └─ Block if fails                                 │
│                                                         │
│  [2] Build Image (.github/workflows/build.yml)         │
│      ├─ Build Docker image                             │
│      ├─ Push to Docker Hub                             │
│      └─ Tag: main, sha, version                        │
│                                                         │
│  [3] Deploy (.github/workflows/deploy.yml)             │
│      ├─ SSH to VPS                                     │
│      ├─ git pull                                       │
│      ├─ docker compose pull                            │
│      └─ docker compose up -d                           │
└───────────┬────────────────────────────────────────────┘
            │
            ▼
┌────────────────────────────────────────────────────────┐
│ Production VPS                                         │
│   New image deployed                                   │
│   Zero-downtime restart                                │
│   Old image cleaned up                                 │
└───────────┬────────────────────────────────────────────┘
            │
            ▼
┌────────────────────────────────────────────────────────┐
│ Monitoring                                             │
│   UptimeRobot checks /health every 5 min               │
│   Alerts if down                                       │
└────────────────────────────────────────────────────────┘
```

**Time from commit to deployed:** ~5-10 minutes

---

## Concurrency (Simple Approach - No Queue)

**User's insight:** Can open multiple CLI instances, same can happen in server.

**Simple approach:** One Codex process per concurrent user.

```python
# In server/app.py - already handles this

async def run_codex_exec(workspace: Path, prompt: str) -> str:
    """Each call spawns new Codex process - naturally concurrent"""
    
    process = await asyncio.create_subprocess_exec(
        "codex", "exec",
        "--cd", str(workspace),
        # ... runs in parallel with other users' processes
    )
```

**How concurrency works:**

```
User A sends message
    ↓
FastAPI spawns: asyncio.create_subprocess_exec (Codex process A)
    ↓ (non-blocking, returns immediately)
FastAPI continues...

User B sends message (while A is running)
    ↓
FastAPI spawns: asyncio.create_subprocess_exec (Codex process B)
    ↓
Both processes run in parallel

User C sends message
    ↓
FastAPI spawns: Codex process C
    ↓
All 3 run concurrently
```

**No queue needed:**
- asyncio handles async execution
- OS handles process scheduling
- Docker handles resource limits
- Each user gets isolated workspace
- Each workspace has own Bob data

**Resource limits (if needed):**

**File:** `docker-compose.yml`
```yaml
services:
  web:
    deploy:
      resources:
        limits:
          cpus: '4.0'      # Max 4 CPUs
          memory: 4G        # Max 4GB RAM
```

**Or limit concurrent processes:**

```python
# In server/app.py
import asyncio

# Semaphore limits concurrent Codex processes
MAX_CONCURRENT = 10
codex_semaphore = asyncio.Semaphore(MAX_CONCURRENT)

async def run_codex_exec(workspace: Path, prompt: str) -> str:
    async with codex_semaphore:  # Wait if 10 already running
        process = await asyncio.create_subprocess_exec(...)
```

**Verdict:** No job queue, no Redis, no Celery. Just spawn processes. Simple.

---

## Phase 2 / Later: Add Telegram Bot

After web UI is working, optionally add Telegram interface.

**Why Telegram:**
- Users chat via mobile app (no browser needed)
- Built-in auth (Telegram user ID)
- Push notifications
- File sharing (for wiki exports)

**Changes needed:**

1. **Install python-telegram-bot:**
   ```bash
   uv pip install python-telegram-bot
   ```

2. **Add telegram bot script:**
   ```python
   # server/telegram_bot.py
   from telegram import Update
   from telegram.ext import Application, MessageHandler, filters
   
   async def handle_message(update: Update, context):
       user_id = str(update.effective_user.id)
       message = update.message.text
       
       # Reuse same logic as web API
       workspace = prepare_workspace(user_id)
       response = await run_codex_exec(workspace, message)
       
       await update.message.reply_text(response)
   
   app = Application.builder().token(BOT_TOKEN).build()
   app.add_handler(MessageHandler(filters.TEXT, handle_message))
   app.run_polling()
   ```

3. **Update docker-compose.yml:**
   ```yaml
   services:
     web:
       # ... existing
     
     telegram-bot:
       build: .
       command: ["uv", "run", "python", "server/telegram_bot.py"]
       environment:
         TELEGRAM_BOT_TOKEN: ${TELEGRAM_BOT_TOKEN}
       volumes:
         - bob_data:/data
   ```

**Setup:**
- Message @BotFather on Telegram
- `/newbot` → get token
- Add to `.env`
- `docker-compose up` → bot works

**Not needed now** - Focus on web UI first.

---

## Summary

**Files to create:** 4
1. `Dockerfile`
2. `docker-compose.yml`
3. `server/app.py`
4. `.dockerignore`

**Modified files:** 1
- `.gitignore` (add server/__pycache__, runtime/uv/)

**No database** - Codex/Claude handle conversation history  
**No timelines** - Work at your own pace  
**Web UI first** - Telegram later  
**CI/CD ready** - GitHub Actions for test/build/deploy
