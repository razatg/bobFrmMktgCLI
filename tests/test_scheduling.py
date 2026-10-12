import asyncio
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from server.models import Store
from server.schedule_tools import ScheduleToolContext, ScheduleTools
from server.scheduling import (
    ScheduleRepository,
    Scheduler,
    next_weekly_occurrence,
)


class ScheduleTimeTests(unittest.TestCase):
    def test_first_occurrence_uses_local_timezone_and_skips_a_passed_time(self):
        before = datetime(2026, 10, 13, 22, 29, tzinfo=timezone.utc)
        first = next_weekly_occurrence(2, '04:00', 'Asia/Kolkata', before)
        self.assertEqual(first, datetime(2026, 10, 13, 22, 30, tzinfo=timezone.utc))
        after = datetime(2026, 10, 13, 22, 31, tzinfo=timezone.utc)
        following = next_weekly_occurrence(2, '04:00', 'Asia/Kolkata', after)
        self.assertEqual(following, datetime(2026, 10, 20, 22, 30, tzinfo=timezone.utc))

    def test_nonexistent_dst_time_is_normalized_forward(self):
        reference = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)
        result = next_weekly_occurrence(6, '02:30', 'America/New_York', reference)
        self.assertEqual(result, datetime(2026, 3, 8, 7, 30, tzinfo=timezone.utc))


class SchedulePersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / 'metadata.sqlite3')
        timestamp = '2026-10-11T00:00:00+00:00'
        self.store.run('INSERT INTO users VALUES (?,?,?,?,?,?,?,?)',
                       ('owner','owner@example.com','hash','member','approved',0,timestamp,None))
        self.store.run('''INSERT INTO client_instances
          (id,slug,display_name,worker_ref,status,created_at) VALUES (?,?,?,?,?,?)''',
          ('client','client','Client','client','active',timestamp))
        self.store.run('''INSERT INTO client_memberships VALUES (?,?,?,?,?,?)''',
                       ('owner','client','member','approved','owner',timestamp))
        self.store.run('''INSERT INTO client_accounts
          (id,client_instance_id,customer_id,account_name,is_active,created_at)
          VALUES (?,?,?,?,?,?)''',('account','client','1112223333','Demand',1,timestamp))
        self.store.run('''INSERT INTO user_account_access
          (user_id,account_id,permission,can_schedule,granted_by,created_at)
          VALUES (?,?,?,?,?,?)''',('owner','account','read',1,'owner',timestamp))
        self.store.run('''INSERT INTO conversations
          (id,user_id,client_instance_id,account_id,agent_backend,workspace_id,title,created_at,last_activity_at)
          VALUES (?,?,?,?,?,?,?,?,?)''',
          ('conversation','owner','client','account','codex','conversation','Chat',timestamp,timestamp))
        self.store.run('''INSERT INTO google_ads_connections
          (id,user_id,client_instance_id,google_subject,google_email,refresh_token_ref,
           scopes,status,last_verified_at,last_error,created_at,updated_at)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
          ('connection','owner','client',None,None,'secret:refresh','scope','connected',None,
           None,timestamp,timestamp))
        self.repo = ScheduleRepository(self.store)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_store_adds_client_timezone_to_an_existing_database(self):
        self.store.close()
        legacy_path = Path(self.temp.name) / 'legacy.sqlite3'
        db = sqlite3.connect(legacy_path)
        db.execute('''CREATE TABLE client_instances (
          id TEXT PRIMARY KEY, slug TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL,
          worker_ref TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL,
          mcc_id TEXT, mcc_name TEXT, codex_model TEXT)''')
        db.execute('''INSERT INTO client_instances
          (id,slug,display_name,worker_ref,status,created_at) VALUES (?,?,?,?,?,?)''',
          ('legacy','legacy','Legacy','legacy','active','2026-10-11T00:00:00+00:00'))
        db.commit(); db.close()
        migrated = Store(legacy_path)
        self.assertEqual(migrated.one('SELECT scheduling_timezone FROM client_instances')['scheduling_timezone'],
                         'Asia/Kolkata')
        migrated.close()
        self.store = Store(Path(self.temp.name) / 'metadata.sqlite3')

    def create_task(self):
        return self.repo.create(
            client_instance_id='client', account_id='account', owner_user_id='owner',
            conversation_id='conversation', prompt='Which text ads need changes?',
            day_of_week=2, local_time='04:00', timezone_name='Asia/Kolkata',
        )

    def schedule_tools(self, host_job_id='host-job'):
        return ScheduleTools(ScheduleToolContext(
            metadata_db=self.store.path,
            client_id='client',
            account_id='account',
            user_id='owner',
            conversation_id='conversation',
            host_job_id=host_job_id,
        ))

    def test_typed_tools_create_and_manage_a_weekly_job(self):
        tools = self.schedule_tools()
        try:
            created = tools.create(
                'Which text ads need changes based on performance?', 'Monday', '3 am'
            )
            self.assertTrue(created['ok'])
            self.assertEqual(created['task']['prompt'],
                             'Which text ads need changes based on performance?')
            self.assertIn('Every Monday at 3:00 AM', created['task']['schedule'])
            paused = tools.pause()
            self.assertEqual(paused['action'], 'paused')
            moved = tools.update('Friday', '18:30')
            self.assertIn('Every Friday at 6:30 PM', moved['task']['schedule'])
            resumed = tools.resume()
            self.assertEqual(resumed['action'], 'resumed')
            requested = tools.delete(confirm=False)
            self.assertEqual(requested['action'], 'confirmation_required')
            deleted = tools.delete(confirm=True)
            self.assertEqual(deleted['action'], 'deleted')
            self.assertEqual(tools.list()['tasks'], [])
        finally:
            tools.close()

    def test_typed_tools_refuse_to_guess_when_multiple_jobs_exist(self):
        self.create_task()
        self.repo.create(
            client_instance_id='client', account_id='account', owner_user_id='owner',
            conversation_id='conversation', prompt='What happened last week?',
            day_of_week=1, local_time='04:00', timezone_name='Asia/Kolkata',
        )
        tools = self.schedule_tools()
        try:
            result = tools.pause()
            self.assertFalse(result['ok'])
            self.assertEqual(result['error']['code'], 'TASK_SELECTION_REQUIRED')
            self.assertEqual(len(result['tasks']), 2)
        finally:
            tools.close()

    def test_run_now_is_marked_for_host_dispatch_and_preserves_deadline(self):
        task = self.create_task()
        deadline = task['next_run_at']
        tools = self.schedule_tools('chat-job')
        try:
            result = tools.run_now(task['id'])
            self.assertTrue(result['ok'])
        finally:
            tools.close()
        run = self.store.one('SELECT * FROM scheduled_runs WHERE task_id=?', (task['id'],))
        self.assertEqual(run['request_job_id'], 'chat-job')
        self.assertEqual(self.repo.get(task['id'])['next_run_at'], deadline)

    def test_typed_tools_enforce_scheduling_permission(self):
        self.store.run('UPDATE user_account_access SET can_schedule=0 WHERE user_id=?', ('owner',))
        tools = self.schedule_tools()
        try:
            result = tools.create('What happened last week?', 'Tuesday', '04:00')
            self.assertFalse(result['ok'])
            self.assertEqual(result['error']['code'], 'SCHEDULING_PERMISSION_REQUIRED')
        finally:
            tools.close()

    def test_claim_is_atomic_and_advances_the_recurring_occurrence(self):
        task = self.create_task()
        due = '2026-10-06T22:30:00+00:00'
        self.store.run('UPDATE scheduled_tasks SET next_run_at=? WHERE id=?', (due, task['id']))

        async def dispatch(_task, _run):
            return None

        scheduler = Scheduler(self.store, dispatch)
        claimed = scheduler.claim_next_due(datetime(2026, 10, 6, 23, 30, tzinfo=timezone.utc))
        self.assertIsNotNone(claimed)
        claimed_task, run = claimed
        self.assertEqual(claimed_task['id'], task['id'])
        self.assertEqual(run['scheduled_for'], due)
        self.assertIsNone(scheduler.claim_next_due(datetime(2026, 10, 6, 23, 30, tzinfo=timezone.utc)))
        stored = self.repo.get(task['id'])
        self.assertEqual(stored['status'], 'running')
        self.assertEqual(stored['next_run_at'], '2026-10-13T22:30:00+00:00')

    def test_run_now_preserves_the_recurring_deadline_and_pause_state(self):
        task = self.create_task()
        deadline = task['next_run_at']
        self.repo.pause(task['id'])
        run = self.repo.create_manual_run(task['id'])
        self.assertEqual(run['trigger_type'], 'run_now')
        self.assertEqual(run['return_status'], 'paused')
        self.repo.finish(run['id'], 'completed', 'No action needed.')
        stored = self.repo.get(task['id'])
        self.assertEqual(stored['status'], 'paused')
        self.assertEqual(stored['next_run_at'], deadline)

    def test_occurrence_older_than_grace_period_is_recorded_and_not_dispatched(self):
        task = self.create_task()
        due = '2026-10-06T22:30:00+00:00'
        self.store.run('UPDATE scheduled_tasks SET next_run_at=? WHERE id=?', (due, task['id']))

        async def dispatch(_task, _run):
            return None

        scheduler = Scheduler(self.store, dispatch, grace_hours=6)
        self.assertIsNone(scheduler.claim_next_due(datetime(2026, 10, 8, 0, 0, tzinfo=timezone.utc)))
        skipped = self.store.one('SELECT * FROM scheduled_runs WHERE task_id=?', (task['id'],))
        self.assertEqual(skipped['status'], 'skipped')
        self.assertEqual(skipped['failure_category'], 'missed_grace_period')
        stored = self.repo.get(task['id'])
        self.assertEqual(stored['status'], 'active')
        self.assertEqual(stored['next_run_at'], '2026-10-13T22:30:00+00:00')

    def test_delete_requires_a_recent_confirmation(self):
        task = self.create_task()
        self.assertFalse(self.repo.confirm_delete(task['id']))
        self.repo.request_delete(task['id'])
        self.assertTrue(self.repo.confirm_delete(task['id']))
        self.assertEqual(self.repo.get(task['id'])['status'], 'deleted')

    def test_restart_marks_active_run_interrupted_and_restores_pause_state(self):
        task = self.create_task()
        self.repo.pause(task['id'])
        run = self.repo.create_manual_run(task['id'])

        async def dispatch(_task, _run):
            return None

        Scheduler(self.store, dispatch).recover_interrupted()
        self.assertEqual(self.store.one('SELECT status FROM scheduled_runs WHERE id=?',(run['id'],))['status'],
                         'interrupted')
        self.assertEqual(self.repo.get(task['id'])['status'], 'paused')


if __name__ == '__main__':
    unittest.main()
