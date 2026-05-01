"""
Task Scheduler (Track B)

Autonomous scheduling engine integrated with APScheduler.
Scheduled tasks run through the identical execute_query() pipeline as
user-submitted queries — the only additions are persistence, delivery
channels, and concurrency governance.

Governance model:
  - Scheduler component must be admin-enabled (component_settings.disabled_components)
  - Profile must have scheduler component enabled (componentConfig.scheduler.enabled)
  - Per-task: overlap_policy (skip | queue | allow), max_tokens_per_run
"""

import asyncio
import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("quart.app")

_DB_PATH = Path(__file__).resolve().parents[3] / "tda_auth.db"

# Holds the APScheduler instance (set during app startup)
_scheduler = None


def _ensure_columns():
    """Auto-migrate: add new columns to scheduled_tasks if missing.

    Called at import time AND deferred via _ensure_columns_deferred() once the app
    has bootstrapped the schema. The import-time call may fail silently when the
    table does not exist yet (fresh DB); the deferred call runs after schema init
    and always succeeds on existing tables.
    """
    try:
        with _get_conn() as conn:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(scheduled_tasks)").fetchall()}
            if not cols:
                # Table doesn't exist yet — schema init hasn't run; skip silently.
                return
            if "session_id" not in cols:
                conn.execute("ALTER TABLE scheduled_tasks ADD COLUMN session_id TEXT")
                conn.commit()
                logger.info("Task Scheduler: migrated scheduled_tasks — added session_id column.")
    except Exception as e:
        logger.warning(f"Task Scheduler schema migration warning: {e}")


# Tracks running task fires: {task_id: asyncio.Task}
_running_tasks: dict[str, asyncio.Task] = {}

# ── DB helpers ────────────────────────────────────────────────────────────────

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


_ensure_columns()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row(row) -> dict:
    return dict(row) if row else None


# ── Scheduler component gate ──────────────────────────────────────────────────

def is_scheduler_globally_enabled() -> bool:
    """Return True if the scheduler component is not in admin's disabled_components list."""
    try:
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT setting_value FROM component_settings WHERE setting_key = 'disabled_components'"
            ).fetchone()
        if row:
            disabled = json.loads(row["setting_value"] or "[]")
            return "scheduler" not in disabled
    except Exception:
        pass
    return True  # default open


def is_scheduler_enabled_for_profile(profile_id: str, user_uuid: str) -> bool:
    """Return True if the profile has scheduler component enabled in componentConfig."""
    if not is_scheduler_globally_enabled():
        return False
    try:
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT config FROM user_profiles WHERE id = ? AND user_uuid = ?",
                (profile_id, user_uuid)
            ).fetchone()
        if row:
            config = json.loads(row["config"] or "{}")
            comp_cfg = config.get("componentConfig", {}).get("scheduler", {})
            return bool(comp_cfg.get("enabled", False))
    except Exception:
        pass
    return False


# ── CRUD ──────────────────────────────────────────────────────────────────────

def create_task(
    user_uuid: str,
    profile_id: str,
    name: str,
    prompt: str,
    schedule: str,
    output_channel: Optional[str] = None,
    output_config: Optional[dict] = None,
    max_tokens_per_run: Optional[int] = None,
    overlap_policy: str = "skip",
    session_id: Optional[str] = None,
) -> dict:
    task_id = f"sched-{uuid.uuid4().hex[:12]}"
    now = _now()
    with _get_conn() as conn:
        conn.execute(
            """INSERT INTO scheduled_tasks
               (id, user_uuid, profile_id, name, prompt, schedule, enabled,
                output_channel, output_config, max_tokens_per_run, overlap_policy,
                session_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?)""",
            (
                task_id, user_uuid, profile_id, name, prompt, schedule,
                output_channel,
                json.dumps(output_config) if output_config else None,
                max_tokens_per_run,
                overlap_policy,
                session_id,
                now, now,
            )
        )
        conn.commit()

    task = get_task(task_id, user_uuid)
    if task and _scheduler and _scheduler.running:
        _register_job(task)
    return task


def get_task(task_id: str, user_uuid: str) -> Optional[dict]:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM scheduled_tasks WHERE id = ? AND user_uuid = ?",
            (task_id, user_uuid)
        ).fetchone()
    return _row(row)


def list_tasks(user_uuid: str, profile_id: Optional[str] = None) -> list[dict]:
    with _get_conn() as conn:
        if profile_id:
            # Include tasks with empty profile_id (created before profile scoping was enforced)
            rows = conn.execute(
                "SELECT * FROM scheduled_tasks WHERE user_uuid = ? AND (profile_id = ? OR profile_id = '') ORDER BY created_at DESC",
                (user_uuid, profile_id)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM scheduled_tasks WHERE user_uuid = ? ORDER BY created_at DESC",
                (user_uuid,)
            ).fetchall()
    return [dict(r) for r in rows]


def update_task(task_id: str, user_uuid: str, updates: dict) -> Optional[dict]:
    allowed = {
        "name", "prompt", "schedule", "enabled",
        "output_channel", "output_config", "max_tokens_per_run", "overlap_policy",
        "session_id",
    }
    fields = {k: v for k, v in updates.items() if k in allowed}
    if not fields:
        return get_task(task_id, user_uuid)

    if "output_config" in fields and isinstance(fields["output_config"], dict):
        fields["output_config"] = json.dumps(fields["output_config"])

    fields["updated_at"] = _now()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [task_id, user_uuid]
    with _get_conn() as conn:
        conn.execute(
            f"UPDATE scheduled_tasks SET {set_clause} WHERE id = ? AND user_uuid = ?",
            values
        )
        conn.commit()

    task = get_task(task_id, user_uuid)
    if task and _scheduler and _scheduler.running:
        _unregister_job(task_id)
        if task.get("enabled"):
            _register_job(task)
    return task


def delete_task(task_id: str, user_uuid: str) -> bool:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM scheduled_tasks WHERE id = ? AND user_uuid = ?",
            (task_id, user_uuid)
        ).fetchone()
        if not row:
            return False
        conn.execute("DELETE FROM scheduled_tasks WHERE id = ?", (task_id,))
        conn.commit()
    _unregister_job(task_id)
    return True


# ── Run history ───────────────────────────────────────────────────────────────

def list_runs(task_id: str, user_uuid: str, limit: int = 20) -> list[dict]:
    """Return recent run records for a task (validates ownership)."""
    with _get_conn() as conn:
        owner = conn.execute(
            "SELECT id FROM scheduled_tasks WHERE id = ? AND user_uuid = ?",
            (task_id, user_uuid)
        ).fetchone()
        if not owner:
            return []
        rows = conn.execute(
            """SELECT * FROM scheduled_task_runs WHERE task_id = ?
               ORDER BY started_at DESC LIMIT ?""",
            (task_id, limit)
        ).fetchall()
    return [dict(r) for r in rows]


def _record_run_start(task_id: str, bg_task_id: Optional[str] = None) -> str:
    run_id = f"run-{uuid.uuid4().hex[:12]}"
    with _get_conn() as conn:
        conn.execute(
            """INSERT INTO scheduled_task_runs (id, task_id, bg_task_id, started_at, status)
               VALUES (?, ?, ?, ?, 'running')""",
            (run_id, task_id, bg_task_id, _now())
        )
        conn.commit()
    return run_id


def _record_run_end(
    run_id: str,
    status: str,
    result_summary: Optional[str] = None,
    tokens_used: Optional[int] = None,
    cost_usd: Optional[float] = None,
    skip_reason: Optional[str] = None,
):
    now = _now()
    with _get_conn() as conn:
        conn.execute(
            """UPDATE scheduled_task_runs
               SET completed_at = ?, status = ?, result_summary = ?,
                   tokens_used = ?, cost_usd = ?, skip_reason = ?
               WHERE id = ?""",
            (now, status, result_summary, tokens_used, cost_usd, skip_reason, run_id)
        )
        # Update parent task last_run fields
        run_row = conn.execute(
            "SELECT task_id FROM scheduled_task_runs WHERE id = ?", (run_id,)
        ).fetchone()
        if run_row:
            conn.execute(
                "UPDATE scheduled_tasks SET last_run_at = ?, last_run_status = ?, updated_at = ? WHERE id = ?",
                (now, status, now, run_row["task_id"])
            )
        conn.commit()


# ── APScheduler integration ───────────────────────────────────────────────────

def get_scheduler():
    """Return the global APScheduler instance (may be None before startup)."""
    return _scheduler


async def start_scheduler():
    """Start APScheduler and register all enabled tasks. Called at app startup."""
    global _scheduler
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
    except ImportError:
        logger.warning("APScheduler not installed — Task Scheduler component disabled. Run: pip install apscheduler>=3.10")
        return

    _scheduler = AsyncIOScheduler()
    _scheduler.start()
    logger.info("Task Scheduler started.")

    # Register all currently enabled tasks
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM scheduled_tasks WHERE enabled = 1"
        ).fetchall()
    tasks = [dict(r) for r in rows]
    for task in tasks:
        try:
            _register_job(task)
        except Exception as e:
            logger.error(f"Failed to register scheduled task '{task['id']}': {e}")

    logger.info(f"Task Scheduler: registered {len(tasks)} task(s).")


async def stop_scheduler():
    """Stop APScheduler gracefully. Called at app shutdown."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Task Scheduler stopped.")
    _scheduler = None


def _register_job(task: dict):
    """Add or replace an APScheduler job for a task."""
    if not _scheduler:
        return
    schedule = task.get("schedule", "")
    task_id = task["id"]

    # Remove existing job if present
    _unregister_job(task_id)

    try:
        if schedule.startswith("interval:"):
            # interval:300s  or  interval:10m  or  interval:1h
            interval_str = schedule[len("interval:"):]
            seconds = _parse_interval(interval_str)
            _scheduler.add_job(
                _fire_task,
                "interval",
                seconds=seconds,
                id=task_id,
                args=[task_id],
                misfire_grace_time=60,
                coalesce=True,
                replace_existing=True,
            )
        else:
            # Cron expression: "0 9 * * 1-5"
            parts = schedule.split()
            if len(parts) != 5:
                raise ValueError(f"Invalid cron expression '{schedule}' — expected 5 fields")
            _scheduler.add_job(
                _fire_task,
                "cron",
                minute=parts[0], hour=parts[1],
                day=parts[2], month=parts[3], day_of_week=parts[4],
                id=task_id,
                args=[task_id],
                misfire_grace_time=60,
                coalesce=True,
                replace_existing=True,
            )
        logger.info(f"Scheduled task '{task.get('name', task_id)}' registered ({schedule})")
    except Exception as e:
        logger.error(f"Failed to register job for task '{task_id}': {e}")


def _unregister_job(task_id: str):
    if _scheduler:
        try:
            _scheduler.remove_job(task_id)
        except Exception:
            pass


def _parse_interval(s: str) -> int:
    """Convert '300s', '10m', '2h' to seconds."""
    s = s.strip().lower()
    if s.endswith("h"):
        return int(s[:-1]) * 3600
    if s.endswith("m"):
        return int(s[:-1]) * 60
    if s.endswith("s"):
        return int(s[:-1])
    return int(s)  # bare number = seconds


# ── Task execution ────────────────────────────────────────────────────────────

def _fire_task(task_id: str):
    """Synchronous wrapper called by APScheduler — schedules the async execution."""
    loop = asyncio.get_event_loop()
    loop.create_task(_execute_task_async(task_id))


async def _emit_notification(user_uuid: str, notification: dict):
    """Push a notification to all active queues for a user (fire-and-forget)."""
    from trusted_data_agent.core.config import APP_STATE
    queues = APP_STATE.get("notification_queues", {}).get(user_uuid, set())
    for q in queues:
        asyncio.create_task(q.put(notification))


async def _execute_task_async(task_id: str, preflight_run_id: Optional[str] = None):
    """Execute a scheduled task through the standard execution pipeline.

    Emits the same new_session_created / rest_task_update / rest_task_complete
    notification events as the REST query pipeline so the frontend's existing
    buffer/replay/live-rendering path works identically to genie slave sessions.
    """
    import copy as _copy

    # Load task from DB
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM scheduled_tasks WHERE id = ? AND enabled = 1", (task_id,)
        ).fetchone()
    if not row:
        return

    task = dict(row)
    user_uuid = task["user_uuid"]
    profile_id = task["profile_id"]
    overlap_policy = task.get("overlap_policy", "skip")

    # Overlap policy check
    if task_id in _running_tasks and not _running_tasks[task_id].done():
        if overlap_policy == "skip":
            run_id = _record_run_start(task_id)
            _record_run_end(run_id, "skipped", skip_reason="Previous run still active (overlap_policy=skip)")
            logger.info(f"Task '{task.get('name', task_id)}' skipped — previous run still active.")
            return
        elif overlap_policy == "queue":
            try:
                await asyncio.wait_for(_running_tasks[task_id], timeout=300)
            except asyncio.TimeoutError:
                pass

    run_id = preflight_run_id or _record_run_start(task_id)
    asyncio_task = asyncio.current_task()
    if asyncio_task:
        _running_tasks[task_id] = asyncio_task

    try:
        from trusted_data_agent.core import session_manager
        from trusted_data_agent.agent.execution_service import run_agent_execution
        from trusted_data_agent.core.config import APP_STATE, APP_CONFIG
        from trusted_data_agent.core.config_manager import get_config_manager

        # Unique ID used for rest_task_update / rest_task_complete payloads
        bg_task_id = f"sched-bg-{uuid.uuid4().hex[:12]}"

        # Determine session: use pinned session if set and still valid, else create new
        pinned_session_id = task.get("session_id")
        session_id = None
        is_pinned_session = False
        if pinned_session_id:
            try:
                existing = await session_manager.get_session(user_uuid, pinned_session_id)
                if existing and not existing.get("archived"):
                    session_id = pinned_session_id
                    is_pinned_session = True
                    logger.info(
                        f"Scheduled task '{task.get('name', task_id)}' running in "
                        f"pinned session {pinned_session_id[:12]}…"
                    )
            except Exception:
                pass
            if not session_id:
                logger.warning(
                    f"Scheduled task '{task.get('name', task_id)}': pinned session "
                    f"'{pinned_session_id}' unavailable — falling back to new session."
                )

        if not session_id:
            session_id = await session_manager.create_session(
                user_uuid=user_uuid,
                provider=APP_CONFIG.CURRENT_PROVIDER,
                llm_instance=APP_STATE.get("llm"),
                charting_intensity="medium",
                profile_id=profile_id,
                is_temporary=True,
                temporary_purpose=f"Scheduled task: {task.get('name', task_id)}",
            )

        # --- Emit new_session_created so the session appears in the sidebar immediately ---
        # Only emit for freshly-created ephemeral sessions (not for reused pinned sessions).
        if not is_pinned_session:
            try:
                session_data = await session_manager.get_session(user_uuid, session_id)
                if session_data:
                    profile_type = None
                    try:
                        cm = get_config_manager()
                        profile_obj = cm.get_profile(profile_id, user_uuid) or {}
                        profile_type = profile_obj.get("profile_type")
                    except Exception:
                        pass
                    await _emit_notification(user_uuid, {
                        "type": "new_session_created",
                        "payload": {
                            "id": session_id,
                            "name": session_data.get("name", f"Scheduled: {task.get('name', task_id)}"),
                            "created_at": session_data.get("created_at"),
                            "profile_id": session_data.get("profile_id"),
                            "profile_tag": session_data.get("profile_tag"),
                            "profile_type": profile_type,
                            "genie_metadata": {},
                            "is_temporary": True,
                            "temporary_purpose": f"Scheduled task: {task.get('name', task_id)}",
                        }
                    })
            except Exception as e:
                logger.debug(f"Task scheduler: new_session_created emit failed: {e}")

        total_input_tokens = 0
        total_output_tokens = 0
        final_answer = None

        async def _event_handler(event_data, event_type):
            nonlocal total_input_tokens, total_output_tokens, final_answer
            if isinstance(event_data, dict):
                if event_type == "token_update":
                    total_input_tokens = event_data.get("total_input", total_input_tokens)
                    total_output_tokens = event_data.get("total_output", total_output_tokens)
                if event_data.get("type") == "conversation_agent_complete":
                    payload = event_data.get("payload", {})
                    final_answer = payload.get("final_answer_text") or payload.get("answer", "")

            # --- Mirror the REST pipeline: push every event to notification queues ---
            try:
                canonical_event = _copy.deepcopy(event_data) if isinstance(event_data, dict) else {"data": str(event_data)}
                if "type" not in canonical_event:
                    canonical_event["type"] = event_type or "notification"

                if event_type == "status_indicator_update":
                    notification = {"type": "status_indicator_update", "payload": canonical_event}
                elif event_type == "session_name_update":
                    notification = {"type": "session_name_update", "payload": canonical_event}
                else:
                    notification = {
                        "type": "rest_task_update",
                        "payload": {
                            "task_id": bg_task_id,
                            "session_id": session_id,
                            "event": canonical_event,
                        },
                    }
                await _emit_notification(user_uuid, notification)
            except Exception as e:
                logger.debug(f"Task scheduler: rest_task_update emit failed: {e}")

        final_result_payload = await run_agent_execution(
            user_uuid=user_uuid,
            session_id=session_id,
            user_input=task["prompt"],
            event_handler=_event_handler,
            profile_override_id=profile_id,
            source="scheduler",
        )

        # Extract final_answer from result payload if event handler didn't capture it
        if not final_answer and isinstance(final_result_payload, dict):
            final_answer = final_result_payload.get("final_answer") or final_result_payload.get("final_answer_text")

        result_summary = (final_answer or "")[:500]
        tokens_used = total_input_tokens + total_output_tokens

        # Post-run token budget check (mid-run cancellation not yet supported)
        max_tokens = task.get("max_tokens_per_run")
        if max_tokens and tokens_used > max_tokens:
            logger.warning(
                f"Task '{task.get('name', task_id)}' exceeded token budget: "
                f"{tokens_used} used > {max_tokens} limit."
            )
            _record_run_end(run_id, "error", result_summary=f"Token budget exceeded ({tokens_used} > {max_tokens})", tokens_used=tokens_used)
            _running_tasks.pop(task_id, None)
            return

        # --- Emit rest_task_complete so the frontend renders the Q&A and cleans up state ---
        try:
            session_data = await session_manager.get_session(user_uuid, session_id)
            profile_tag = session_data.get("profile_tag") if session_data else None
            await _emit_notification(user_uuid, {
                "type": "rest_task_complete",
                "payload": {
                    "task_id": bg_task_id,
                    "session_id": session_id,
                    "turn_id": final_result_payload.get("turn_id") if isinstance(final_result_payload, dict) else None,
                    "user_input": task["prompt"],
                    "final_answer": final_answer or result_summary,
                    "profile_tag": profile_tag,
                    "extension_specs": None,
                    "skill_specs": None,
                    "source": "scheduler",
                }
            })
        except Exception as e:
            logger.debug(f"Task scheduler: rest_task_complete emit failed: {e}")

        # Deliver result via output channel
        output_channel = task.get("output_channel")
        if output_channel and result_summary:
            await _deliver_result(task, result_summary, session_id)

        _record_run_end(run_id, "success", result_summary=result_summary, tokens_used=tokens_used)
        logger.info(f"Scheduled task '{task.get('name', task_id)}' completed ({tokens_used} tokens).")

    except Exception as e:
        logger.error(f"Scheduled task '{task_id}' failed: {e}", exc_info=True)
        _record_run_end(run_id, "error", result_summary=str(e)[:500])
    finally:
        _running_tasks.pop(task_id, None)


async def _deliver_result(task: dict, result: str, session_id: str):
    """Deliver task result via the configured output channel."""
    channel = task.get("output_channel")
    cfg_raw = task.get("output_config")
    cfg = json.loads(cfg_raw) if cfg_raw else {}
    task_name = task.get("name", task["id"])
    subject = f"[Uderia] Scheduled task: {task_name}"

    try:
        if channel == "email":
            to_addr = cfg.get("to_address")
            if not to_addr:
                logger.warning(f"Task '{task_name}': email channel configured but no to_address.")
                return
            from trusted_data_agent.auth.email_service import EmailService
            await EmailService.send_email(to_addr, subject, result)

        elif channel == "webhook":
            import httpx
            url = cfg.get("webhook_url")
            if not url:
                return
            headers = {"Content-Type": "application/json"}
            bearer = cfg.get("bearer_token")
            if bearer:
                headers["Authorization"] = f"Bearer {bearer}"
            payload = {
                "task_id": task["id"],
                "task_name": task_name,
                "session_id": session_id,
                "result": result,
                "completed_at": _now(),
            }
            async with httpx.AsyncClient(timeout=15.0) as client:
                await client.post(url, json=payload, headers=headers)

        elif channel == "google_mail":
            user_uuid = task.get("user_uuid")
            if not user_uuid:
                logger.warning(f"Task '{task_name}': google_mail channel — no user_uuid on task, cannot send.")
                return
            from trusted_data_agent.connectors.google_connector import get_tokens
            tokens = await get_tokens(user_uuid)
            if not tokens or not tokens.get("access_token"):
                logger.warning(f"Task '{task_name}': google_mail — no Google account connected for user {user_uuid}.")
                return
            from trusted_data_agent.core.platform_connector_registry import get_server_credentials
            creds = get_server_credentials("uderia-google")
            to_addr = cfg.get("to_address") or tokens.get("email") or ""
            if not to_addr:
                logger.warning(f"Task '{task_name}': google_mail — no recipient address configured.")
                return
            import base64
            from email.mime.text import MIMEText
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build as _gapi_build
            google_creds = Credentials(
                token=tokens["access_token"],
                refresh_token=tokens.get("refresh_token"),
                token_uri="https://oauth2.googleapis.com/token",
                client_id=creds.get("GOOGLE_CLIENT_ID", ""),
                client_secret=creds.get("GOOGLE_CLIENT_SECRET", ""),
            )
            msg = MIMEText(result)
            msg["to"] = to_addr
            msg["subject"] = subject
            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
            service = _gapi_build("gmail", "v1", credentials=google_creds, cache_discovery=False)
            service.users().messages().send(userId="me", body={"raw": raw}).execute()
            logger.info(f"Task '{task_name}': google_mail delivered to {to_addr}.")

    except Exception as e:
        logger.warning(f"Failed to deliver result for task '{task_name}' via {channel}: {e}")


# ── Manual trigger ────────────────────────────────────────────────────────────

async def run_task_now(task_id: str, user_uuid: str) -> str:
    """Manually trigger a task immediately. Returns run_id."""
    task = get_task(task_id, user_uuid)
    if not task:
        raise ValueError(f"Task '{task_id}' not found.")
    run_id = _record_run_start(task_id)
    asyncio.create_task(_execute_task_async(task_id, preflight_run_id=run_id))
    return run_id
