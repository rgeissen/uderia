"""
Scheduler Component Handler.

Processes TDA_Scheduler tool calls into scheduling canvas render payloads.
Delegates CRUD to task_scheduler.py; enriches tasks with next-run previews.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from trusted_data_agent.components.base import (
    BaseComponentHandler,
    ComponentRenderPayload,
    RenderTarget,
)

logger = logging.getLogger("quart.app")


# ---------------------------------------------------------------------------
# Next-run computation (cron + interval, no heavy deps)
# ---------------------------------------------------------------------------

def _next_runs(schedule: str, n: int = 6) -> List[str]:
    """Return the next n ISO timestamps for a cron or interval schedule."""
    now = datetime.now(timezone.utc)
    try:
        if schedule.startswith("interval:"):
            return _next_runs_interval(schedule[len("interval:"):], now, n)
        else:
            return _next_runs_cron(schedule, now, n)
    except Exception as exc:
        logger.debug(f"next_runs failed for '{schedule}': {exc}")
        return []


def _parse_interval_seconds(spec: str) -> int:
    spec = spec.strip().lower()
    if spec.endswith("d"):
        return int(spec[:-1]) * 86400
    if spec.endswith("h"):
        return int(spec[:-1]) * 3600
    if spec.endswith("m"):
        return int(spec[:-1]) * 60
    if spec.endswith("s"):
        return int(spec[:-1])
    return int(spec)


def _next_runs_interval(spec: str, base: datetime, n: int) -> List[str]:
    from datetime import timedelta
    secs = _parse_interval_seconds(spec)
    runs = []
    t = base
    for _ in range(n):
        t = t + timedelta(seconds=secs)
        runs.append(t.isoformat())
    return runs


def _next_runs_cron(expression: str, base: datetime, n: int) -> List[str]:
    try:
        from apscheduler.triggers.cron import CronTrigger
        parts = expression.split()
        if len(parts) != 5:
            return []
        # Standard unix cron: min hour dom month dow
        trigger = CronTrigger(
            minute=parts[0],
            hour=parts[1],
            day=parts[2],
            month=parts[3],
            day_of_week=parts[4],
        )
    except Exception:
        return _next_runs_cron_manual(expression, base, n)

    runs = []
    t = base
    for _ in range(n):
        nxt = trigger.get_next_fire_time(t, t)
        if nxt is None:
            break
        runs.append(nxt.isoformat())
        t = nxt
    return runs


def _next_runs_cron_manual(expression: str, base: datetime, n: int) -> List[str]:
    """Very small cron evaluator covering the common cases (no APScheduler needed)."""
    from datetime import timedelta

    parts = expression.split()
    if len(parts) != 5:
        return []

    def _matches(val, expr):
        if expr == "*":
            return True
        if "/" in expr:
            step_parts = expr.split("/")
            step = int(step_parts[1])
            return val % step == 0
        if "-" in expr:
            lo, hi = expr.split("-")
            return int(lo) <= val <= int(hi)
        if "," in expr:
            return val in [int(x) for x in expr.split(",")]
        return val == int(expr)

    # Standard unix cron: min hour dom month dow (0=Sunday)
    minute_e, hour_e, day_e, month_e, dow_e = parts
    runs = []
    t = base.replace(second=0, microsecond=0) + timedelta(minutes=1)
    # Scan forward up to 366 * 24 * 60 minutes (cap at reasonable limit)
    limit = 366 * 24 * 60
    checked = 0
    while len(runs) < n and checked < limit:
        checked += 1
        if (_matches(t.month, month_e) and
                _matches(t.day, day_e) and
                _matches(t.weekday(), dow_e) and
                _matches(t.hour, hour_e) and
                _matches(t.minute, minute_e)):
            runs.append(t.isoformat())
        t += timedelta(minutes=1)
    return runs


def _human_schedule(schedule: str) -> str:
    """Return a human-readable description of a schedule."""
    if schedule.startswith("interval:"):
        spec = schedule[len("interval:"):].strip().lower()
        if spec.endswith("d"):
            n = spec[:-1]
            return f"Every {n} day{'s' if int(n) > 1 else ''}"
        if spec.endswith("h"):
            n = spec[:-1]
            return f"Every {n} hour{'s' if int(n) > 1 else ''}"
        if spec.endswith("m"):
            n = spec[:-1]
            return f"Every {n} minute{'s' if int(n) > 1 else ''}"
        return f"Every {spec}"

    parts = schedule.split()
    if len(parts) != 5:
        return schedule

    minute, hour, dom, month, dow = parts

    # Hourly
    if hour == "*" and dom == "*" and month == "*":
        if minute == "0":
            return "Every hour (on the hour)"
        return f"Every hour at :{minute.zfill(2)}"

    # Daily fixed time
    if dom == "*" and month == "*" and dow == "*":
        if hour.isdigit() and minute.isdigit():
            h, m = int(hour), int(minute)
            period = "AM" if h < 12 else "PM"
            h12 = h % 12 or 12
            return f"Daily at {h12}:{str(m).zfill(2)} {period}"

    # Weekdays
    if dom == "*" and month == "*" and dow == "1-5":
        if hour.isdigit() and minute.isdigit():
            h, m = int(hour), int(minute)
            period = "AM" if h < 12 else "PM"
            h12 = h % 12 or 12
            return f"Weekdays at {h12}:{str(m).zfill(2)} {period}"

    # Weekly on specific day
    dow_names = {0: "Sun", 1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat"}
    if dom == "*" and month == "*" and dow.isdigit():
        day_name = dow_names.get(int(dow), dow)
        if hour.isdigit() and minute.isdigit():
            h, m = int(hour), int(minute)
            period = "AM" if h < 12 else "PM"
            h12 = h % 12 or 12
            return f"Weekly on {day_name} at {h12}:{str(m).zfill(2)} {period}"

    return schedule


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

class SchedulerComponentHandler(BaseComponentHandler):

    @property
    def component_id(self) -> str:
        return "scheduler"

    @property
    def tool_name(self) -> str:
        return "TDA_Scheduler"

    @property
    def is_deterministic(self) -> bool:
        return True

    def validate_arguments(self, arguments: Dict[str, Any]) -> Tuple[bool, str]:
        action = arguments.get("action", "")
        valid_actions = {"create", "list", "update", "delete", "enable", "disable", "run_now", "history"}
        if action not in valid_actions:
            return False, f"Unknown action '{action}'. Must be one of: {', '.join(sorted(valid_actions))}."
        if action == "create":
            for field in ("name", "prompt", "schedule"):
                if not arguments.get(field):
                    return False, f"'{field}' is required for action 'create'."
        if action in {"update", "delete", "enable", "disable", "run_now", "history"}:
            if not arguments.get("task_id"):
                return False, f"'task_id' is required for action '{action}'."
        return True, ""

    async def process(
        self,
        arguments: Dict[str, Any],
        context: Dict[str, Any],
    ) -> ComponentRenderPayload:
        from trusted_data_agent.core.task_scheduler import (
            create_task, get_task, list_tasks, update_task, delete_task,
            list_runs, run_task_now,
        )

        action = arguments.get("action") or ""
        # If the LLM omitted action but supplied create fields, infer create intent
        if not action:
            if all(k in arguments for k in ("name", "prompt", "schedule")):
                action = "create"
            else:
                action = "list"
        user_uuid = context.get("user_uuid", "")
        profile_id = context.get("profile_id", "")

        message = ""
        affected_task: Optional[Dict] = None
        runs: List[Dict] = []
        error: Optional[str] = None

        try:
            if action == "create":
                # session_context="current" pins the task to the invoking session
                pinned_session_id: Optional[str] = None
                if arguments.get("session_context") == "current":
                    pinned_session_id = context.get("session_id") or None

                task = create_task(
                    user_uuid=user_uuid,
                    profile_id=profile_id,
                    name=arguments["name"],
                    prompt=arguments["prompt"],
                    schedule=arguments["schedule"],
                    output_channel=arguments.get("output_channel"),
                    output_config=arguments.get("output_config"),
                    overlap_policy=arguments.get("overlap_policy", "skip"),
                    max_tokens_per_run=arguments.get("max_tokens_per_run"),
                    session_id=pinned_session_id,
                )
                affected_task = task
                ctx_label = "current session" if pinned_session_id else "new session"
                message = f"Task \"{task['name']}\" scheduled — {_human_schedule(task['schedule'])} · runs in {ctx_label}"

            elif action == "update":
                updates = {k: arguments[k] for k in (
                    "name", "prompt", "schedule", "output_channel",
                    "output_config", "overlap_policy", "max_tokens_per_run", "enabled"
                ) if k in arguments}
                # Allow toggling session context via update
                if "session_context" in arguments:
                    if arguments["session_context"] == "current":
                        updates["session_id"] = context.get("session_id") or None
                    else:
                        updates["session_id"] = None
                task = update_task(arguments["task_id"], user_uuid, updates)
                affected_task = task
                message = f"Task \"{task['name']}\" updated"

            elif action in ("enable", "disable"):
                enabled_val = 1 if action == "enable" else 0
                task = update_task(arguments["task_id"], user_uuid, {"enabled": enabled_val})
                affected_task = task
                verb = "enabled" if enabled_val else "paused"
                message = f"Task \"{task['name']}\" {verb}"

            elif action == "delete":
                task = get_task(arguments["task_id"], user_uuid)
                task_name = task["name"] if task else arguments["task_id"]
                delete_task(arguments["task_id"], user_uuid)
                message = f"Task \"{task_name}\" deleted"

            elif action == "run_now":
                task = get_task(arguments["task_id"], user_uuid)
                run_id = await run_task_now(arguments["task_id"], user_uuid)
                affected_task = task
                message = f"Task \"{task['name'] if task else ''}\" triggered — run ID {run_id[:8]}…"

            elif action == "history":
                task = get_task(arguments["task_id"], user_uuid)
                affected_task = task
                runs = list_runs(arguments["task_id"], user_uuid, limit=20)
                message = f"Run history for \"{task['name'] if task else arguments['task_id']}\""

            else:  # list
                message = "Scheduled tasks"

        except Exception as exc:
            logger.error(f"TDA_Scheduler action='{action}' failed: {exc}", exc_info=True)
            error = str(exc)
            message = f"Scheduler error: {error}"

        # Load tasks scoped to this profile (consistent with profile-per-user model)
        tasks = list_tasks(user_uuid, profile_id) if action != "history" else (
            list_tasks(user_uuid, profile_id) if not error else []
        )

        # Enrich each task with derived display fields
        for t in tasks:
            t["_human_schedule"] = _human_schedule(t.get("schedule", ""))
            t["_next_runs"] = _next_runs(t.get("schedule", ""), n=5) if t.get("schedule") else []
            t["_session_context"] = "current" if t.get("session_id") else "new"

        if affected_task and affected_task.get("schedule"):
            affected_task["_human_schedule"] = _human_schedule(affected_task["schedule"])
            affected_task["_next_runs"] = _next_runs(affected_task["schedule"], n=5)
            affected_task["_session_context"] = "current" if affected_task.get("session_id") else "new"

        spec = {
            "action": action,
            "message": message,
            "tasks": tasks,
            "affected_task_id": affected_task["id"] if affected_task else None,
            "runs": runs,
            "error": error,
        }

        return ComponentRenderPayload(
            component_id="scheduler",
            render_target=RenderTarget.INLINE,
            spec=spec,
            title="Task Scheduler",
            metadata={"action": action, "task_count": len(tasks)},
            tts_text=message,
        )
