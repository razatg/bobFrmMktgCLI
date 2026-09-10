#!/usr/bin/env python3
"""Print a small, shareable diagnostic from one native Codex session."""

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path


ERROR = re.compile(
    r"(?i)(traceback|exception|\berror\b|\bfailed\b|\bfailure\b|unexpected keyword|"
    r"invalid argument|request[ _-]?id|googleadsfailure|no changes were applied|exit (code|status) [1-9])"
)
SECRET = re.compile(
    r"(?i)((?:\"|')?\b(access[_-]?token|refresh[_-]?token|developer[_-]?token|"
    r"client[_-]?secret|api[_-]?key|authorization|password)\b(?:\"|')?\s*[=:]\s*)"
    r"(\"[^\"]*\"|'[^']*'|[^\s,;}]+)"
)
BEARER = re.compile(r"(?i)(\bbearer\s+)[A-Za-z0-9._~+\-/=]+")


def redact(text):
    return BEARER.sub(r"\1[REDACTED]", SECRET.sub(r"\1[REDACTED]", text))


def collect_text(value):
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [part for item in value for part in collect_text(item)]
    if isinstance(value, dict):
        return [part for key in ("text", "output", "message", "error", "content")
                if key in value for part in collect_text(value[key])]
    return []


def event_text(event):
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    kind = str(payload.get("type") or event.get("type") or "event")
    if kind == "function_call_output":
        value = payload.get("output")
    elif kind in {"message", "agent_message", "error", "turn_aborted"}:
        value = payload
    else:
        return kind, ""
    return kind, "\n".join(collect_text(value)).strip()


def find_session(root, session_id):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{7,127}", session_id):
        raise ValueError("invalid session ID")
    if not root.is_dir():
        raise FileNotFoundError(f"session root not found: {root}")
    matches = [path for path in root.rglob("*.jsonl") if session_id in path.name]
    if not matches:
        raise FileNotFoundError(f"no JSONL filename contains session ID {session_id}")
    return max(matches, key=lambda path: path.stat().st_mtime)


def load_events(path):
    events = []
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                print(f"warning: skipped malformed line {line_number}", file=sys.stderr)
                continue
            if isinstance(event, dict):
                events.append(event)
    return events


def load_job(path, job_id):
    if not job_id or not path.is_file():
        return None
    with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        row = db.execute(
            """SELECT j.status,j.error,j.created_at,m.content AS user_prompt
                 FROM jobs j JOIN messages m ON m.id=j.message_id WHERE j.id=?""",
            (job_id,),
        ).fetchone()
    return dict(row) if row else None


def clip(text, limit):
    text = redact(str(text or "")).strip()
    return text if len(text) <= limit else text[:limit] + f"\n[truncated after {limit} characters]"


def main():
    parser = argparse.ArgumentParser(description="Extract sanitized errors from a Codex session JSONL.")
    parser.add_argument("session_id")
    parser.add_argument("--job-id")
    parser.add_argument("--sessions-root", type=Path, default=Path("/data/codex/sessions"))
    parser.add_argument("--metadata-db", type=Path, default=Path("/data/metadata/metadata.sqlite3"))
    parser.add_argument("--max-chars", type=int, default=12_000)
    args = parser.parse_args()
    if args.max_chars < 500:
        parser.error("--max-chars must be at least 500")

    try:
        session_file = find_session(args.sessions_root, args.session_id)
        events = load_events(session_file)
        job = load_job(args.metadata_db, args.job_id)
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"Session: {args.session_id}\nSession file: {session_file.name}")
    if args.job_id:
        print(f"Job: {args.job_id}")
        if job:
            print(f"Job status: {job['status']}\nJob created: {job['created_at']}")
            print(f"Job error: {clip(job['error'] or 'none', args.max_chars)}")
            print(f"User prompt: {clip(job['user_prompt'], args.max_chars)}")
        else:
            print("Job metadata: unavailable or job ID not found")

    matches = []
    assistants = []
    for event in events:
        kind, text = event_text(event)
        if text and ERROR.search(text):
            matches.append((event.get("timestamp", "unknown time"), kind, text))
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        if text and (payload.get("type") == "agent_message" or
                     (payload.get("type") == "message" and payload.get("role") == "assistant")):
            assistants.append((event.get("timestamp", "unknown time"), kind, text))

    print(f"\nDiagnostic events: {len(matches)}")
    for number, (timestamp, kind, text) in enumerate(matches, 1):
        print(f"\n--- Diagnostic {number}: {timestamp} | {kind} ---\n{clip(text, args.max_chars)}")
    if assistants:
        timestamp, kind, text = assistants[-1]
        print(f"\n--- Last assistant response: {timestamp} | {kind} ---\n{clip(text, args.max_chars)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
