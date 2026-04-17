#!/usr/bin/env python3
"""Show currently active users: valid JWT tokens + recent session activity."""

import os
import sys
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from trusted_data_agent.auth.database import get_db_session
from trusted_data_agent.auth.models import User, AuthToken

SESSIONS_DIR = Path(os.path.dirname(__file__)).parent / "tda_sessions"
RECENT_SESSION_HOURS = 24


def get_latest_session_activity(user_id: str) -> tuple[int, datetime | None]:
    """Return (session_count, latest_activity) for a user from tda_sessions."""
    if not SESSIONS_DIR.exists():
        return 0, None

    count = 0
    latest: datetime | None = None

    for session_dir in SESSIONS_DIR.iterdir():
        if not session_dir.is_dir():
            continue
        meta_file = session_dir / "session_metadata.json"
        if not meta_file.exists():
            continue
        try:
            meta = json.loads(meta_file.read_text())
            if meta.get("user_uuid") != user_id:
                continue
            count += 1
            updated = meta.get("updated_at") or meta.get("created_at")
            if updated:
                ts = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if latest is None or ts > latest:
                    latest = ts
        except Exception:
            continue

    return count, latest


def main():
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=RECENT_SESSION_HOURS)

    with get_db_session() as session:
        raw_users = session.query(User).filter_by(is_active=True).order_by(User.last_login_at.desc().nulls_last()).all()

        active_token_counts: dict[str, int] = {}
        tokens = (
            session.query(AuthToken)
            .filter(AuthToken.revoked == False, AuthToken.expires_at > now)
            .all()
        )
        for t in tokens:
            active_token_counts[t.user_id] = active_token_counts.get(t.user_id, 0) + 1

        # Detach-safe: snapshot all needed fields inside the session
        users = [
            {
                "id": u.id,
                "username": u.username,
                "profile_tier": u.profile_tier,
                "is_admin": u.is_admin,
                "last_login_at": u.last_login_at,
            }
            for u in raw_users
        ]

    # Collect rows
    rows = []
    for user in users:
        user_tokens = active_token_counts.get(user["id"], 0)
        session_count, last_session_at = get_latest_session_activity(user["id"])
        recent_session = last_session_at and last_session_at >= cutoff

        last_login = user["last_login_at"]
        if last_login and last_login.tzinfo is None:
            last_login = last_login.replace(tzinfo=timezone.utc)
        recent_login = last_login and last_login >= cutoff

        is_active = bool(user_tokens) or recent_session or recent_login

        rows.append({
            "user": user,
            "tokens": user_tokens,
            "session_count": session_count,
            "last_session_at": last_session_at,
            "recent_session": recent_session,
            "recent_login": recent_login,
            "is_active": is_active,
        })

    active_rows = [r for r in rows if r["is_active"]]
    inactive_rows = [r for r in rows if not r["is_active"]]

    def fmt_time(dt: datetime | None) -> str:
        if dt is None:
            return "never"
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = now - dt
        if delta.total_seconds() < 60:
            return "just now"
        if delta.total_seconds() < 3600:
            return f"{int(delta.total_seconds() // 60)}m ago"
        if delta.total_seconds() < 86400:
            return f"{int(delta.total_seconds() // 3600)}h ago"
        return f"{delta.days}d ago"

    def print_row(r: dict):
        u = r["user"]
        tier = u["profile_tier"].upper()
        tokens_str = f"{r['tokens']} token{'s' if r['tokens'] != 1 else ''}"
        sessions_str = f"{r['session_count']} session{'s' if r['session_count'] != 1 else ''}"
        last_login_str = fmt_time(u["last_login_at"])
        last_session_str = fmt_time(r["last_session_at"])
        admin_flag = " [admin]" if u["is_admin"] else ""
        print(
            f"  {u['username']:<20} {tier:<12}{admin_flag:<8}"
            f"  login: {last_login_str:<12}"
            f"  session: {last_session_str:<12}"
            f"  {tokens_str:<12}  {sessions_str}"
        )

    print(f"\n=== Uderia Active Users  (as of {now.strftime('%Y-%m-%d %H:%M UTC')}) ===\n")

    if active_rows:
        print(f"ACTIVE ({len(active_rows)})  — valid JWT token, or activity within last {RECENT_SESSION_HOURS}h\n")
        print(f"  {'Username':<20} {'Tier':<12} {'':8}  {'Last login':<18} {'Last session':<18} {'Tokens':<12} Sessions")
        print("  " + "-" * 95)
        for r in active_rows:
            print_row(r)
    else:
        print("No active users found.")

    if inactive_rows:
        print(f"\nINACTIVE ({len(inactive_rows)})  — no activity in last {RECENT_SESSION_HOURS}h\n")
        for r in inactive_rows:
            print_row(r)

    print()


if __name__ == "__main__":
    main()
