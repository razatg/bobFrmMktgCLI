"""Durable, event-driven weekly scheduling for the hosted Bob gateway."""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, time, timedelta, timezone
from typing import Awaitable, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .models import new_id, now

DAY_NAMES = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')
DAY_LOOKUP = {name.casefold(): index for index, name in enumerate(DAY_NAMES)}
TERMINAL_RUN_STATUSES = {'completed', 'failed', 'needs_attention', 'skipped', 'interrupted'}


def parse_clock(value: str) -> str | None:
    match = re.fullmatch(r'\s*(\d{1,2})(?::(\d{2}))?\s*([ap]m)?\s*', value, re.I)
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2) or 0)
    suffix = (match.group(3) or '').casefold()
    if minute > 59 or (suffix and not 1 <= hour <= 12) or (not suffix and hour > 23):
        return None
    if suffix == 'am':
        hour %= 12
    elif suffix == 'pm':
        hour = hour % 12 + 12
    return f'{hour:02d}:{minute:02d}'


def next_weekly_occurrence(day_of_week: int, local_time: str, timezone_name: str,
                           after: datetime | None = None) -> datetime:
    """Return the first weekly occurrence strictly after ``after`` in UTC."""
    if day_of_week not in range(7):
        raise ValueError('day of week must be between 0 and 6')
    parsed = parse_clock(local_time)
    if parsed is None:
        raise ValueError('invalid local time')
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError('invalid timezone') from exc
    reference = after or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    reference = reference.astimezone(timezone.utc)
    local_reference = reference.astimezone(zone)
    hour, minute = (int(part) for part in parsed.split(':'))
    days_ahead = (day_of_week - local_reference.weekday()) % 7
    candidate_date = local_reference.date() + timedelta(days=days_ahead)
    candidate = datetime.combine(candidate_date, time(hour, minute), zone)
    # A round trip normalizes a local time that falls inside a DST gap. Ambiguous times use fold=0.
    candidate = candidate.astimezone(timezone.utc).astimezone(zone)
    if candidate.astimezone(timezone.utc) <= reference:
        candidate = datetime.combine(candidate_date + timedelta(days=7), time(hour, minute), zone)
        candidate = candidate.astimezone(timezone.utc).astimezone(zone)
    return candidate.astimezone(timezone.utc)


def display_schedule(day_of_week: int, local_time: str, timezone_name: str) -> str:
    hour, minute = (int(part) for part in local_time.split(':'))
    suffix = 'AM' if hour < 12 else 'PM'
    display_hour = hour % 12 or 12
    return f'Every {DAY_NAMES[day_of_week]} at {display_hour}:{minute:02d} {suffix} · {timezone_name}'


def task_title(prompt: str) -> str:
    if 'text ad' in prompt.casefold():
        return 'Text ad performance review'
    cleaned = re.sub(r'[?.!]+$', '', prompt).strip()
    return cleaned[:72] + ('…' if len(cleaned) > 72 else '')


class ScheduleRepository:
    def __init__(self, store):
        self.store = store

    def create(self, *, client_instance_id: str, account_id: str, owner_user_id: str,
               conversation_id: str, prompt: str, day_of_week: int, local_time: str,
               timezone_name: str) -> dict:
        task_id, timestamp = new_id(), now()
        next_run = next_weekly_occurrence(day_of_week, local_time, timezone_name).isoformat()
        title = task_title(prompt)
        description = f'Runs “{prompt}” and saves the result in Chat and Artifacts.'
        self.store.run('''INSERT INTO scheduled_tasks
          (id,client_instance_id,account_id,owner_user_id,conversation_id,title,description,prompt,
           day_of_week,local_time,timezone,recurring,status,next_run_at,created_at,updated_at)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,1,'active',?,?,?)''',
          (task_id,client_instance_id,account_id,owner_user_id,conversation_id,title,description,
           prompt,day_of_week,local_time,timezone_name,next_run,timestamp,timestamp))
        return dict(self.store.one('SELECT * FROM scheduled_tasks WHERE id=?', (task_id,)))

    def latest_for_conversation(self, conversation_id: str) -> dict | None:
        row = self.store.one('''SELECT * FROM scheduled_tasks WHERE conversation_id=?
          ORDER BY updated_at DESC LIMIT 1''', (conversation_id,))
        return dict(row) if row else None

    def pause(self, task_id: str) -> dict:
        self.store.run("UPDATE scheduled_tasks SET status='paused',delete_confirmation_at=NULL,updated_at=? WHERE id=?",
                       (now(), task_id))
        return self.get(task_id)

    def resume(self, task_id: str) -> dict:
        task = self.get(task_id)
        next_run = next_weekly_occurrence(
            task['day_of_week'], task['local_time'], task['timezone']).isoformat()
        self.store.run("UPDATE scheduled_tasks SET status='active',next_run_at=?,delete_confirmation_at=NULL,updated_at=? WHERE id=?",
                       (next_run, now(), task_id))
        return self.get(task_id)

    def update(self, task_id: str, day_of_week: int, local_time: str) -> dict:
        task = self.get(task_id)
        next_run = next_weekly_occurrence(day_of_week, local_time, task['timezone']).isoformat()
        self.store.run('''UPDATE scheduled_tasks SET day_of_week=?,local_time=?,next_run_at=?,
          delete_confirmation_at=NULL,updated_at=? WHERE id=?''',
          (day_of_week,local_time,next_run,now(),task_id))
        return self.get(task_id)

    def request_delete(self, task_id: str) -> dict:
        self.store.run('UPDATE scheduled_tasks SET delete_confirmation_at=?,updated_at=? WHERE id=?',
                       (now(), now(), task_id))
        return self.get(task_id)

    def confirm_delete(self, task_id: str, within_minutes: int = 10) -> bool:
        task = self.get(task_id)
        requested = task.get('delete_confirmation_at')
        if not requested:
            return False
        if datetime.fromisoformat(requested) < datetime.now(timezone.utc) - timedelta(minutes=within_minutes):
            return False
        self.store.run("UPDATE scheduled_tasks SET status='deleted',next_run_at=NULL,delete_confirmation_at=NULL,updated_at=? WHERE id=?",
                       (now(), task_id))
        return True

    def create_manual_run(self, task_id: str, request_job_id: str | None = None) -> dict:
        task = self.get(task_id)
        timestamp, run_id = now(), new_id()
        return_status = task['status'] if task['status'] in {'active', 'paused'} else 'active'
        self.store.run('''INSERT INTO scheduled_runs
          (id,task_id,request_job_id,trigger_type,scheduled_for,claimed_at,status,return_status,created_at)
          VALUES (?,?,?,?,?,?,'claimed',?,?)''',
          (run_id,task_id,request_job_id,'run_now',timestamp,timestamp,return_status,timestamp))
        self.store.run("UPDATE scheduled_tasks SET status='running',last_run_at=?,updated_at=? WHERE id=?",
                       (timestamp,timestamp,task_id))
        return dict(self.store.one('SELECT * FROM scheduled_runs WHERE id=?', (run_id,)))

    def attach_job(self, run_id: str, job_id: str, message_id: str) -> None:
        self.store.run("UPDATE scheduled_runs SET job_id=?,message_id=?,status='queued' WHERE id=?",
                       (job_id,message_id,run_id))

    def mark_started(self, run_id: str) -> None:
        self.store.run("UPDATE scheduled_runs SET status='running',started_at=? WHERE id=?", (now(),run_id))

    def finish(self, run_id: str, status: str, summary: str, *, artifact_path: str | None = None,
               failure_category: str | None = None) -> None:
        if status not in TERMINAL_RUN_STATUSES:
            raise ValueError('invalid terminal run status')
        run = self.store.one('SELECT task_id,return_status FROM scheduled_runs WHERE id=?', (run_id,))
        if not run:
            return
        task_status = 'needs_attention' if status == 'needs_attention' else run['return_status']
        self.store.run('''UPDATE scheduled_runs SET status=?,summary=?,artifact_path=?,failure_category=?,completed_at=?
          WHERE id=?''', (status,summary,artifact_path,failure_category,now(),run_id))
        self.store.run('UPDATE scheduled_tasks SET status=?,updated_at=? WHERE id=?',
                       (task_status,now(),run['task_id']))

    def get(self, task_id: str) -> dict:
        row = self.store.one('SELECT * FROM scheduled_tasks WHERE id=?', (task_id,))
        if not row:
            raise LookupError('scheduled task not found')
        return dict(row)


class Scheduler:
    """One timer that sleeps until SQLite's earliest active task is due."""

    def __init__(self, store, dispatch: Callable[[dict, dict], Awaitable[None]], *, grace_hours: int = 6):
        self.store = store
        self.dispatch = dispatch
        self.grace_period = timedelta(hours=max(0, grace_hours))
        self.changed = asyncio.Event()
        self._runner: asyncio.Task | None = None
        self.next_wake_at: str | None = None

    def start(self) -> None:
        self.recover_interrupted()
        self._runner = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if not self._runner:
            return
        self._runner.cancel()
        try:
            await self._runner
        except asyncio.CancelledError:
            pass
        self._runner = None

    def wake(self) -> None:
        self.changed.set()

    def dispatch_claimed(self, task: dict, run: dict) -> None:
        asyncio.create_task(self._dispatch_claimed(task,run))

    def recover_interrupted(self) -> None:
        timestamp = now()
        self.store.run('''UPDATE scheduled_runs SET status='interrupted',completed_at=?,
          summary=COALESCE(summary,'The service restarted while this run was active.')
          WHERE status IN ('claimed','queued','running')''', (timestamp,))
        for task in self.store.all("SELECT id FROM scheduled_tasks WHERE status='running'"):
            run = self.store.one('''SELECT return_status FROM scheduled_runs
              WHERE task_id=? AND status='interrupted' ORDER BY created_at DESC LIMIT 1''', (task['id'],))
            return_status = run['return_status'] if run and run['return_status'] in {'active','paused'} else 'active'
            self.store.run('UPDATE scheduled_tasks SET status=?,updated_at=? WHERE id=?',
                           (return_status,timestamp,task['id']))

    async def _run(self) -> None:
        while True:
            row = self.store.one('''SELECT next_run_at FROM scheduled_tasks
              WHERE status='active' AND next_run_at IS NOT NULL
              ORDER BY next_run_at LIMIT 1''')
            self.next_wake_at = row['next_run_at'] if row else None
            self.changed.clear()
            if not row:
                await self.changed.wait()
                continue
            due = datetime.fromisoformat(row['next_run_at'])
            seconds = max(0.0, (due - datetime.now(timezone.utc)).total_seconds())
            try:
                await asyncio.wait_for(self.changed.wait(), timeout=seconds)
                continue
            except asyncio.TimeoutError:
                pass
            claimed = self.claim_next_due()
            if claimed:
                task, run = claimed
                self.dispatch_claimed(task,run)

    async def _dispatch_claimed(self, task: dict, run: dict) -> None:
        try:
            await self.dispatch(task, run)
        except Exception:
            ScheduleRepository(self.store).finish(
                run['id'], 'failed',
                'The scheduler could not start this run. Nothing was changed in Google Ads.',
                failure_category='dispatch_failure',
            )
            self.wake()

    def claim_next_due(self, at: datetime | None = None) -> tuple[dict, dict] | None:
        timestamp = (at or datetime.now(timezone.utc)).astimezone(timezone.utc)
        db = self.store.db
        try:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('''SELECT * FROM scheduled_tasks
              WHERE status='active' AND next_run_at IS NOT NULL AND next_run_at<=?
              ORDER BY next_run_at LIMIT 1''', (timestamp.isoformat(),)).fetchone()
            if not row:
                db.commit()
                return None
            task = dict(row)
            run_id = new_id()
            scheduled_for = datetime.fromisoformat(task['next_run_at']).astimezone(timezone.utc)
            upcoming = next_weekly_occurrence(
                task['day_of_week'], task['local_time'], task['timezone'], scheduled_for,
            ).isoformat() if task['recurring'] else None
            if timestamp - scheduled_for > self.grace_period:
                db.execute('''INSERT INTO scheduled_runs
                  (id,task_id,trigger_type,scheduled_for,claimed_at,completed_at,status,summary,
                   failure_category,return_status,created_at)
                  VALUES (?,?,?,?,?,?,'skipped',?,'missed_grace_period','active',?)''',
                  (run_id,task['id'],'scheduled',task['next_run_at'],timestamp.isoformat(),
                   timestamp.isoformat(),'Missed while the service was unavailable; advanced to the next run.',
                   timestamp.isoformat()))
                db.execute("UPDATE scheduled_tasks SET status='active',last_run_at=?,next_run_at=?,updated_at=? WHERE id=?",
                           (task['next_run_at'],upcoming,timestamp.isoformat(),task['id']))
                db.commit()
                return None
            db.execute('''INSERT INTO scheduled_runs
              (id,task_id,trigger_type,scheduled_for,claimed_at,status,return_status,created_at)
              VALUES (?,?,?,?,?,'claimed','active',?)''',
              (run_id, task['id'], 'scheduled', task['next_run_at'], timestamp.isoformat(), timestamp.isoformat()))
            db.execute('''UPDATE scheduled_tasks SET status='running',last_run_at=?,next_run_at=?,updated_at=?
              WHERE id=?''', (task['next_run_at'], upcoming, timestamp.isoformat(), task['id']))
            db.commit()
        except Exception:
            db.rollback()
            raise
        run = dict(self.store.one('SELECT * FROM scheduled_runs WHERE id=?', (run_id,)))
        return task, run

    def health(self) -> dict:
        return {
            'alive': bool(self._runner and not self._runner.done()),
            'next_wake_at': self.next_wake_at,
        }
