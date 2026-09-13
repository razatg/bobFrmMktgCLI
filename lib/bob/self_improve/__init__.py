"""Signal capture and self-improvement preparation commands."""

from __future__ import annotations

import argparse
import json
from typing import Any

from lib.bob.platform.core import *
def log_pull_cmd(args: argparse.Namespace) -> None:
    """Write a pull-log entry without hitting the API — used for cache-hit recording."""
    profile = load_profile(required=False)
    account = args.account or str(profile.get("google_ads_customer_id", "")).replace("-", "")
    log_pull(
        query=args.query,
        from_date=args.from_date or "",
        to_date=args.to or "",
        account=account,
        run_id_val="",
        output_file="",
        reason=args.reason,
        question=args.question,
        outcome=args.outcome,
    )
    print(f"logged: {args.outcome} — {args.query} {args.from_date or ''}..{args.to or ''}")


def log_signal_cmd(args: argparse.Namespace) -> None:
    """Append one self-improvement signal — a friction moment in this session.

    For an immediate, single critical (chiefly `failsafe`). Routine friction is batched
    into one `session-debrief` call at a success beat instead — see that command.
    """
    profile = load_profile(required=False)
    account = args.account or str(profile.get("google_ads_customer_id", "")).replace("-", "")
    entry = log_signal(
        event_type=args.type,
        note=args.note,
        account=account,
        user_text=args.user_text,
        intent=args.intent,
        artifact=args.artifact,
        severity=args.severity,
        source="inline",
    )
    print(f"signal logged: {entry['event_type']} — {entry['note']}")


def session_debrief(args: argparse.Namespace) -> None:
    """Record a batch of self-improvement signals captured at a session success beat.

    The consent-based, in-voice half of capture: Bob tracks where it got stuck during a
    session and, at a clear win (e.g. a wiki write), offers to note it. Only on the user's
    say-so does it call this — one batched write for the whole session, each entry tagged
    source="debrief". The agent-agnostic sibling of log-signal: same schema, same writer,
    so it depends on no runtime internals. An empty list is a clean no-op (no nagging), and
    a malformed batch is validated up front so nothing is half-written.
    """
    profile = load_profile(required=False)
    account = args.account or str(profile.get("google_ads_customer_id", "")).replace("-", "")
    try:
        signals = json.loads(args.signals)
    except json.JSONDecodeError as exc:
        die(f"--signals must be a JSON array of signal objects: {exc}")
    if not isinstance(signals, list):
        die("--signals must be a JSON array, e.g. '[{\"event_type\":\"friction\",\"note\":\"...\"}]'")
    if not signals:
        print("session-debrief: clean session — no signals to record.")
        return
    # Validate every entry before writing any, so a malformed batch appends nothing.
    cleaned = []
    for i, s in enumerate(signals):
        if not isinstance(s, dict):
            die(f"--signals[{i}] must be an object with at least 'event_type' and 'note'")
        event_type = s.get("event_type") or s.get("type")
        note = s.get("note")
        if not event_type or not note:
            die(f"--signals[{i}] needs both 'event_type' and 'note'")
        cleaned.append((event_type, note, s))
    for event_type, note, s in cleaned:
        log_signal(
            event_type=event_type,
            note=note,
            account=s.get("account") or account,
            user_text=s.get("user_text", ""),
            intent=s.get("intent", ""),
            artifact=s.get("artifact", ""),
            severity=s.get("severity", ""),
            source="debrief",
        )
    n = len(cleaned)
    print(f"session-debrief: recorded {n} signal{'s' if n != 1 else ''} from this session.")


def self_improve(args: argparse.Namespace) -> None:
    """Prep step for a self-improvement pass. Summarises logged signals and points the
    agent at the files to read. Does NOT call any model — clustering and the proposal
    are the agent's job (see the bob-self-improve skill). Manual, proposal-only."""
    signals = _read_signal_log()
    backlog = STATE_ROOT / "logs" / "backlog.md"
    if not signals:
        print("No signals logged yet (logs/session-signals.jsonl is empty or missing).")
        print("Nothing to synthesize. Signals accumulate as agents call `./bob log-signal`.")
        return
    by_type: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    by_source: dict[str, int] = {}
    for s in signals:
        et = s.get("event_type", "?")
        by_type[et] = by_type.get(et, 0) + 1
        sev = s.get("severity")
        if sev:
            by_severity[sev] = by_severity.get(sev, 0) + 1
        src = s.get("source")
        if src:
            by_source[src] = by_source.get(src, 0) + 1
    print(f"Self-improvement signals: {len(signals)} total\n")
    print("By event type:")
    for k in sorted(by_type, key=lambda x: -by_type[x]):
        print(f"  {by_type[k]:>4}  {k}")
    if by_severity:
        print("\nBy severity:")
        for k in sorted(by_severity, key=lambda x: -by_severity[x]):
            print(f"  {by_severity[k]:>4}  {k}")
    if by_source:
        print("\nBy source (cli=auto, inline=log-signal, debrief=session-debrief):")
        for k in sorted(by_source, key=lambda x: -by_source[x]):
            print(f"  {by_source[k]:>4}  {k}")
    print("\nRead these to cluster pitfalls and write the proposal:")
    print(f"  signals : {SIGNAL_LOG_PATH}")
    if backlog.exists():
        print(f"  backlog : {backlog}")
    plan_path = SELF_IMPROVE_DIR / f"action-plan-{today().isoformat()}.md"
    print(f"\nWrite the proposal-only action plan to: {plan_path}")
    print("Nothing is changed by this command. See the bob-self-improve skill for the synthesis steps.")

__all__ = [name for name in globals() if not name.startswith("__")]
