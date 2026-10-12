---
name: bob-scheduling
description: Use only when a hosted Bob message starts with /sch, /sch-run, /sch-pause, or /sch-resume. Handles the explicit JTBD scheduling command through Bob's typed tools. Not for ordinary performance questions or execution when a stored task triggers.
---

# Bob Scheduling

Use this skill only in the managed hosted workspace and only after the backend has identified an
explicit `/sch` command. Ordinary language without that prefix is never a scheduling request.

## Boundary

- Use only the scheduling tools made available for the command: create for `/sch`; list plus Run
  Now for `/sch-run`; list plus pause for `/sch-pause`; list plus resume for `/sch-resume`.
- Never use native Codex, ChatGPT, Page, Space, OS cron, or another automation system.
- Never access or modify the scheduling database directly. The tools recheck the authenticated user, selected account, scheduling permission, ownership, Google authorization, and client timezone.
- `/sch` creates a prompt and never runs the underlying analysis immediately. `/sch-run` is the only
  command that requests an immediate run.
- Scheduled runs are read-only. They may recommend changes but never apply Google Ads mutations automatically.

## Interpret and act

For `/sch`, extract three meanings from the remainder of the message:

1. The prompt Bob should run, preserving the user's intended question without the scheduling instruction.
2. A full weekday.
3. A local wall-clock time.

Normalize obvious language before the tool call, such as `Mon` to `Monday`, `3 am` to `03:00`, and `everyweek` to weekly recurrence. If any required meaning is genuinely missing or ambiguous, ask one focused question and do not call create.

Examples:

- `/sch Every Tuesday at 4 AM, what happened last week?`
- `/sch What happened last week? every Tuesday at 4am`
- `/sch Which text ads need changes? every Tuesday at 4 in the morning`

For management commands:

- `/sch-run <natural-language task reference>` calls Run Now; `/sch-pause <reference>` pauses;
  `/sch-resume <reference>` resumes.
- If the user clearly refers to the only job in this Chat, call the requested tool without a task ID; the server resolves it safely.
- If there may be more than one job, call `bob_schedule_list`. Use a returned task ID only when the user's reference uniquely matches. Otherwise show the short choices and ask which one they mean.
- Do not create, move, or delete a task through the four public commands. Pausing is the safe way to
  stop a task. Do not suggest an unprefixed natural-language scheduling fallback.

## Respond

Use the tool result as the source of truth. On success, confirm the interpreted prompt, plain-language schedule, timezone, status, and first run when returned. Keep the response short and mention that scheduled analysis does not change Google Ads. On a tool error, relay its safe next action plainly; do not claim a task changed.

At trigger time, this skill is not used. Bob submits the stored prompt through normal routing—for example, text-ad performance routes to `bob-creative-copy`—then saves the Chat result and Artifact in JTBD run history.
