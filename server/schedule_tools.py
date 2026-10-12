"""Validated scheduling operations exposed to Bob's hosted agent."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from .models import Store
from .scheduling import DAY_LOOKUP, ScheduleRepository, display_schedule, parse_clock


@dataclass(frozen=True)
class ScheduleToolContext:
    metadata_db: str
    client_id: str
    account_id: str
    user_id: str
    conversation_id: str
    host_job_id: str

    @classmethod
    def from_environment(cls) -> "ScheduleToolContext":
        values = {
            "metadata_db": os.getenv("BOB_METADATA_DB", ""),
            "client_id": os.getenv("BOB_CLIENT_INSTANCE_ID", ""),
            "account_id": os.getenv("BOB_SCHEDULE_ACCOUNT_ID", ""),
            "user_id": os.getenv("BOB_SCHEDULE_USER_ID", ""),
            "conversation_id": os.getenv("BOB_SCHEDULE_CONVERSATION_ID", ""),
            "host_job_id": os.getenv("BOB_HOST_JOB_ID", ""),
        }
        if not all(values.values()):
            raise ValueError("Scheduling is available only inside an authenticated Bob Chat.")
        return cls(**values)


def _error(code: str, message: str, **details) -> dict[str, object]:
    return {"ok": False, "error": {"code": code, "message": message}, **details}


def _task_view(task: dict) -> dict[str, object]:
    return {
        "task_id": task["id"],
        "title": task["title"],
        "prompt": task["prompt"],
        "status": task["status"],
        "schedule": display_schedule(task["day_of_week"], task["local_time"], task["timezone"]),
        "timezone": task["timezone"],
        "next_run_at": task["next_run_at"],
    }


class ScheduleTools:
    """Open a short-lived DB connection and enforce the authenticated Chat scope."""

    def __init__(self, context: ScheduleToolContext):
        self.context = context
        self.store = Store(context.metadata_db)
        self.repo = ScheduleRepository(self.store)

    def close(self) -> None:
        self.store.close()

    def _access_error(self) -> dict[str, object] | None:
        c = self.context
        user = self.store.one(
            "SELECT id,role,status FROM users WHERE id=?", (c.user_id,)
        )
        conversation = self.store.one(
            "SELECT id FROM conversations WHERE id=? AND user_id=? AND client_instance_id=? AND account_id=?",
            (c.conversation_id, c.user_id, c.client_id, c.account_id),
        )
        account = self.store.one(
            "SELECT id FROM client_accounts WHERE id=? AND client_instance_id=? AND is_active=1",
            (c.account_id, c.client_id),
        )
        membership = self.store.one(
            "SELECT 1 FROM client_memberships WHERE user_id=? AND client_instance_id=?",
            (c.user_id, c.client_id),
        )
        grant = self.store.one(
            "SELECT permission,can_schedule FROM user_account_access WHERE user_id=? AND account_id=?",
            (c.user_id, c.account_id),
        )
        if not user or user["status"] != "approved" or not conversation or not account or not membership:
            return _error("ACCESS_DENIED", "This Chat no longer has access to the selected account.")
        if user["role"] != "admin" and (not grant or grant["permission"] == "none"):
            return _error("ACCESS_DENIED", "This Chat no longer has access to the selected account.")
        if user["role"] != "admin" and not grant["can_schedule"]:
            return _error(
                "SCHEDULING_PERMISSION_REQUIRED",
                "Your Admin needs to give you scheduling permission for this account first.",
            )
        return None

    def _connected(self) -> bool:
        row = self.store.one(
            "SELECT 1 FROM google_ads_connections WHERE user_id=? AND client_instance_id=? AND status='connected'",
            (self.context.user_id, self.context.client_id),
        )
        return bool(row)

    def _tasks(self) -> list[dict]:
        rows = self.store.all(
            """SELECT * FROM scheduled_tasks
               WHERE client_instance_id=? AND account_id=? AND owner_user_id=?
                 AND conversation_id=? AND status!='deleted'
               ORDER BY updated_at DESC""",
            (
                self.context.client_id,
                self.context.account_id,
                self.context.user_id,
                self.context.conversation_id,
            ),
        )
        return [dict(row) for row in rows]

    def _resolve(self, task_id: str = "") -> tuple[dict | None, dict[str, object] | None]:
        tasks = self._tasks()
        if task_id:
            matches = [task for task in tasks if task["id"] == task_id]
            if len(matches) == 1:
                return matches[0], None
            return None, _error("TASK_NOT_FOUND", "I can’t find that scheduled job in this Chat.")
        if len(tasks) == 1:
            return tasks[0], None
        if not tasks:
            return None, _error("TASK_NOT_FOUND", "I can’t find a scheduled job in this Chat yet.")
        return None, _error(
            "TASK_SELECTION_REQUIRED",
            "More than one scheduled job matches this Chat. Ask the user which one they mean.",
            tasks=[_task_view(task) for task in tasks],
        )

    def list(self) -> dict[str, object]:
        if error := self._access_error():
            return error
        return {"ok": True, "tasks": [_task_view(task) for task in self._tasks()]}

    def create(self, prompt: str, day_of_week: str, local_time: str) -> dict[str, object]:
        if error := self._access_error():
            return error
        if not self._connected():
            return _error(
                "GOOGLE_AUTH_REQUIRED",
                "Google Ads authorization is required. Ask the user to say ‘Set me up again’.",
            )
        clean_prompt = str(prompt).strip()
        day = DAY_LOOKUP.get(str(day_of_week).strip().casefold())
        clock = parse_clock(local_time)
        if not clean_prompt:
            return _error("PROMPT_REQUIRED", "Ask what Bob should run on the schedule.")
        if day is None:
            return _error("DAY_REQUIRED", "Ask which day of the week Bob should run it.")
        if clock is None:
            return _error("TIME_REQUIRED", "Ask what local time Bob should run it.")
        timezone_row = self.store.one(
            "SELECT scheduling_timezone FROM client_instances WHERE id=?", (self.context.client_id,)
        )
        if not timezone_row:
            return _error("CLIENT_NOT_FOUND", "The client workspace is no longer available.")
        try:
            task = self.repo.create(
                client_instance_id=self.context.client_id,
                account_id=self.context.account_id,
                owner_user_id=self.context.user_id,
                conversation_id=self.context.conversation_id,
                prompt=clean_prompt,
                day_of_week=day,
                local_time=clock,
                timezone_name=timezone_row["scheduling_timezone"],
            )
        except ValueError as exc:
            return _error("INVALID_SCHEDULE", str(exc))
        first = datetime.fromisoformat(task["next_run_at"]).astimezone(ZoneInfo(task["timezone"]))
        return {
            "ok": True,
            "action": "created",
            "task": _task_view(task),
            "first_run": first.strftime("%A, %d %B at %-I:%M %p"),
            "message": "The job was scheduled. Nothing will be changed in Google Ads.",
        }

    def update(self, day_of_week: str, local_time: str, task_id: str = "") -> dict[str, object]:
        if error := self._access_error():
            return error
        task, error = self._resolve(task_id)
        if error:
            return error
        day = DAY_LOOKUP.get(str(day_of_week).strip().casefold())
        clock = parse_clock(local_time)
        if day is None or clock is None:
            return _error("DAY_AND_TIME_REQUIRED", "Ask for both a weekday and a local time.")
        task = self.repo.update(task["id"], day, clock)
        return {"ok": True, "action": "updated", "task": _task_view(task)}

    def pause(self, task_id: str = "") -> dict[str, object]:
        return self._change("paused", task_id)

    def resume(self, task_id: str = "") -> dict[str, object]:
        return self._change("resumed", task_id)

    def _change(self, action: str, task_id: str) -> dict[str, object]:
        if error := self._access_error():
            return error
        task, error = self._resolve(task_id)
        if error:
            return error
        task = self.repo.pause(task["id"]) if action == "paused" else self.repo.resume(task["id"])
        return {"ok": True, "action": action, "task": _task_view(task)}

    def run_now(self, task_id: str = "") -> dict[str, object]:
        if error := self._access_error():
            return error
        if not self._connected():
            return _error(
                "GOOGLE_AUTH_REQUIRED",
                "Google Ads authorization is required. Ask the user to say ‘Set me up again’.",
            )
        task, error = self._resolve(task_id)
        if error:
            return error
        if task["status"] == "running":
            return _error("ALREADY_RUNNING", f"{task['title']} is already running.")
        run = self.repo.create_manual_run(task["id"], self.context.host_job_id)
        return {
            "ok": True,
            "action": "run_now_requested",
            "task": _task_view(self.repo.get(task["id"])),
            "message": "The job is queued now. Its next recurring time did not move.",
        }

    def delete(self, task_id: str = "", confirm: bool = False) -> dict[str, object]:
        if error := self._access_error():
            return error
        task, error = self._resolve(task_id)
        if error:
            return error
        if not confirm:
            task = self.repo.request_delete(task["id"])
            return {
                "ok": True,
                "action": "confirmation_required",
                "task": _task_view(task),
                "message": "Ask the user to confirm deletion within 10 minutes.",
            }
        if not self.repo.confirm_delete(task["id"]):
            return _error(
                "CONFIRMATION_EXPIRED",
                "Deletion was not requested or its confirmation expired. Ask to delete again first.",
            )
        return {"ok": True, "action": "deleted", "task_id": task["id"]}


def with_schedule_tools(operation):
    """Run one operation and always close its SQLite connection."""
    try:
        tools = ScheduleTools(ScheduleToolContext.from_environment())
    except ValueError as exc:
        return _error("SCHEDULING_UNAVAILABLE", str(exc))
    try:
        return operation(tools)
    finally:
        tools.close()
