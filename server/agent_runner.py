"""Process-boundary Codex adapter with cancellation, timeout, and JSONL events."""
from __future__ import annotations
import asyncio, json, os, shutil
from dataclasses import dataclass
from pathlib import Path

@dataclass
class ExecutionPolicy:
    model: str | None = None
    timeout_seconds: int = 240
    max_output_bytes: int = 2_000_000
    environment: dict[str, str] | None = None

class AgentRunner:
    def __init__(self, executable=None): self.executable = executable or shutil.which('codex') or 'codex'
    @staticmethod
    def _hosted_sandbox_available():
        return bool(shutil.which('bwrap'))

    async def run(self, backend, session_id, prompt, workspace, policy, emit, cancel_event=None):
        if backend != 'codex': raise ValueError('only the Codex backend is enabled in Phase 1')
        runtime = os.getenv('BOB_RUNTIME', 'hosted').strip().lower()
        environment = os.environ.copy()
        if policy.environment: environment.update(policy.environment)
        if session_id:
            # Resume options must precede the session ID. The native session
            # retains its original working directory, so resume does not take
            # --cd in this Codex CLI version.
            args = [self.executable, 'exec', 'resume']
        else:
            args = [self.executable, 'exec']
        if runtime == 'desktop':
            # Docker Desktop's Linux VM does not permit Codex's nested
            # bubblewrap user namespace. Docker remains the outer boundary
            # and this worker runs as the unprivileged `bob` user.
            args += ['--dangerously-bypass-approvals-and-sandbox']
        elif not session_id:
            # Hosted Linux uses Codex's normal inner sandbox.
            if not self._hosted_sandbox_available():
                raise RuntimeError('Hosted Codex sandbox is unavailable: bubblewrap (bwrap) is not installed in the container')
            args += ['--sandbox', 'workspace-write']
        if not session_id: args += ['--cd', str(workspace)]
        args += ['--json', '--skip-git-repo-check']
        # Conversation workspaces contain symlinks to image-owned skills and
        # CLI code under the application root. Hosted Codex must be told that
        # this root is an allowed sandbox directory, otherwise `.agents` is
        # rejected when the skill is loaded through the symlink.
        add_dirs = [str(Path(__file__).resolve().parents[1])]
        for key in ('BOB_STATE_ROOT', 'BOB_SHARED_STATE_ROOT'):
            root = environment.get(key)
            if root:
                resolved = str(Path(root).expanduser().resolve())
                if resolved not in add_dirs:
                    add_dirs.append(resolved)
        for root in add_dirs:
            args += ['--add-dir', root]
        if policy.model: args += ['--model', policy.model]
        if session_id: args.append(session_id)
        args.append(prompt)
        if not Path(workspace).exists(): Path(workspace).mkdir(parents=True, exist_ok=True)
        proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=str(workspace), env=environment)
        output = 0; thread_id = session_id; final = ''
        async def read():
            nonlocal output, thread_id, final
            async for raw in proc.stdout:
                output += len(raw)
                if output > policy.max_output_bytes: proc.kill(); raise RuntimeError('agent output limit exceeded')
                line = raw.decode(errors='replace').strip()
                if not line: continue
                try: event = json.loads(line)
                except json.JSONDecodeError: event = {'type':'stdout','text':line}
                if event.get('type') == 'thread.started': thread_id = event.get('thread_id', thread_id)
                item = event.get('item') or {}
                if event.get('type') in {'assistant.final','result','final'}:
                    final = event.get('text') or event.get('message') or event.get('result') or final
                elif event.get('type') == 'item.completed' and item.get('type') == 'agent_message':
                    final = item.get('text') or final
                await emit(event)
            return final
        task = None
        try:
            task = asyncio.create_task(read())
            deadline = asyncio.get_running_loop().time() + policy.timeout_seconds
            while not task.done():
                if cancel_event and cancel_event.is_set():
                    proc.terminate()
                    raise asyncio.CancelledError
                if asyncio.get_running_loop().time() >= deadline:
                    proc.kill()
                    raise asyncio.TimeoutError
                await asyncio.sleep(.05)
            final = await task
            remaining = max(0.1, deadline - asyncio.get_running_loop().time())
            await asyncio.wait_for(proc.wait(), remaining)
        except asyncio.TimeoutError:
            proc.kill(); await proc.wait(); raise
        finally:
            if proc.returncode is None: proc.kill(); await proc.wait()
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        if proc.returncode != 0:
            err = (await proc.stderr.read()).decode(errors='replace')[-4000:]
            raise RuntimeError(err or f'agent exited {proc.returncode}')
        return thread_id, final
