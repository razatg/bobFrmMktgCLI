"""Process-boundary Codex adapter with cancellation, timeout, and JSONL events."""
from __future__ import annotations
import asyncio, json, logging, os, shutil, signal, time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger('bob.agent_runner')

@dataclass
class ExecutionPolicy:
    model: str | None = None
    timeout_seconds: int = 240
    max_output_bytes: int = 2_000_000
    environment: dict[str, str] | None = None
    job_id: str | None = None

class AgentRunner:
    SHELL_ENV_KEYS = (
        'BOB_STATE_ROOT',
        'BOB_SHARED_STATE_ROOT',
        'BOB_CLIENT_INSTANCE_ID',
        'BOB_GOOGLE_ADS_RUNTIME_CONFIG',
    )

    def __init__(self, executable=None):
        self.executable = executable or shutil.which('codex') or 'codex'
        self.process_registry = {}
    @staticmethod
    def _hosted_sandbox_available():
        return bool(shutil.which('bwrap'))

    @staticmethod
    def _debug_enabled():
        return os.getenv('BOB_DEBUG_LOGGING', '').strip().lower() in {'1', 'true', 'yes', 'on'}

    def _debug(self, message, *args):
        if self._debug_enabled():
            logger.warning(message, *args)

    @staticmethod
    def _kill_process_group(proc, force=False):
        """Stop Codex and every shell/tool child it started."""
        if proc.returncode is not None:
            return
        try:
            os.killpg(proc.pid, signal.SIGKILL if force else signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            try:
                proc.kill() if force else proc.terminate()
            except ProcessLookupError:
                pass

    @staticmethod
    async def _read_stderr(stream, max_bytes=4000):
        data = bytearray()
        while True:
            chunk = await stream.read(64 * 1024)
            if not chunk:
                break
            data.extend(chunk)
            if len(data) > max_bytes:
                del data[:-max_bytes]
        return bytes(data)

    @staticmethod
    async def _read_jsonl(stream, max_output_bytes, emit, session_id=None):
        """Read Codex JSONL without asyncio's default 64 KiB line limit."""
        output = 0
        pending = bytearray()
        thread_id = session_id
        final = ''

        async def handle(raw):
            nonlocal thread_id, final
            line = raw.decode(errors='replace').strip()
            if not line:
                return
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                event = {'type':'stdout','text':line}
            if event.get('type') == 'thread.started':
                thread_id = event.get('thread_id', thread_id)
            item = event.get('item') or {}
            if event.get('type') in {'assistant.final','result','final'}:
                final = event.get('text') or event.get('message') or event.get('result') or final
            elif event.get('type') == 'item.completed' and item.get('type') == 'agent_message':
                final = item.get('text') or final
            await emit(event)

        while True:
            chunk = await stream.read(64 * 1024)
            if not chunk:
                break
            output += len(chunk)
            if output > max_output_bytes:
                raise RuntimeError('agent output limit exceeded')
            pending.extend(chunk)
            while True:
                newline = pending.find(b'\n')
                if newline < 0:
                    break
                raw = bytes(pending[:newline])
                del pending[:newline + 1]
                await handle(raw)
        if pending:
            await handle(bytes(pending))
        return thread_id, final

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
        # Codex intentionally filters the environment inherited by shell
        # commands. Pass only Bob's non-secret state paths and client scope;
        # never inherit the container environment wholesale because it also
        # contains admin credentials and deployment secrets.
        for key in self.SHELL_ENV_KEYS:
            value = environment.get(key)
            if value:
                args += ['-c', f'shell_environment_policy.set.{key}={json.dumps(str(value))}']
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
        # `exec resume` does not accept --add-dir; a resumed session reuses
        # the permissions captured when the session was created. New hosted
        # sessions need the application root so symlinked `.agents` loads.
        if not session_id:
            for root in add_dirs:
                args += ['--add-dir', root]
        if policy.model: args += ['--model', policy.model]
        if session_id: args.append(session_id)
        args.append(prompt)
        if not Path(workspace).exists(): Path(workspace).mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        self._debug('codex start runtime=%s session=%s cwd=%s args=%r', runtime, bool(session_id), workspace, args[:-1])
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(workspace),
            env=environment,
            start_new_session=True,
        )
        job_id = getattr(policy, 'job_id', None)
        if job_id:
            self.process_registry[job_id] = {
                'pid': proc.pid,
                'process_group_id': proc.pid,
                'started_monotonic': started,
            }
        thread_id = session_id; final = ''
        async def read():
            return await self._read_jsonl(proc.stdout, policy.max_output_bytes, emit, session_id)
        task = None; stderr_task = asyncio.create_task(self._read_stderr(proc.stderr))
        try:
            task = asyncio.create_task(read())
            deadline = asyncio.get_running_loop().time() + policy.timeout_seconds
            while not task.done():
                if cancel_event and cancel_event.is_set():
                    self._kill_process_group(proc)
                    raise asyncio.CancelledError
                if asyncio.get_running_loop().time() >= deadline:
                    self._kill_process_group(proc, force=True)
                    raise RuntimeError(f'agent timed out after {policy.timeout_seconds} seconds')
                await asyncio.sleep(.05)
            thread_id, final = await task
            remaining = max(0.1, deadline - asyncio.get_running_loop().time())
            await asyncio.wait_for(proc.wait(), remaining)
            if cancel_event and cancel_event.is_set():
                raise asyncio.CancelledError
        except asyncio.TimeoutError:
            self._kill_process_group(proc, force=True); await proc.wait()
            raise RuntimeError(f'agent timed out after {policy.timeout_seconds} seconds') from None
        finally:
            if job_id:
                self.process_registry.pop(job_id, None)
            if proc.returncode is None:
                self._kill_process_group(proc, force=True); await proc.wait()
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            if not stderr_task.done():
                await asyncio.gather(stderr_task, return_exceptions=True)
        if proc.returncode != 0:
            err = (await stderr_task).decode(errors='replace')[-4000:]
            self._debug('codex failed exit=%s duration=%.2fs stderr=%s', proc.returncode, time.monotonic() - started, err)
            raise RuntimeError(err or f'agent exited {proc.returncode}')
        self._debug('codex completed exit=0 duration=%.2fs session=%s', time.monotonic() - started, thread_id)
        return thread_id, final
