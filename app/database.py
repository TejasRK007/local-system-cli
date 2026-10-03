"""
Audit database module for the Local Agentic Automation System.

Provides persistent SQLite-based audit logging for every agent execution,
recording action, risk classification, approval decisions, execution status,
and result summaries while ensuring no sensitive credentials or file contents
are persisted.
"""

import json
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# Default to project_root / "data" / "agent.db"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_DB_PATH = DEFAULT_DATA_DIR / "agent.db"

# Module-level DB_PATH (can be patched or overridden via AGENT_DB_PATH env var)
DB_PATH = Path(os.getenv("AGENT_DB_PATH", str(DEFAULT_DB_PATH)))


def get_db_path() -> Path:
    """Return the active SQLite database path."""
    return DB_PATH


def sanitize_text(text: Optional[str]) -> str:
    """
    Remove secrets, tokens, API keys, and credentials from text.

    Ensures that user requests and result summaries never persist sensitive
    credentials into the audit database or display them in logs.
    """
    if not text:
        return ""

    sanitized = str(text)

    # 1. Mask exact values of known secret environment variables if set
    for env_var in ("GROQ_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        val = os.getenv(env_var)
        if val and len(val.strip()) > 5:
            sanitized = sanitized.replace(val.strip(), "[REDACTED]")

    # 2. Mask common API key prefixes (Groq gsk_, OpenAI sk-, bearer tokens)
    sanitized = re.sub(r"gsk_[A-Za-z0-9_-]{16,}", "[REDACTED]", sanitized)
    sanitized = re.sub(r"sk-[A-Za-z0-9_-]{16,}", "[REDACTED]", sanitized)
    sanitized = re.sub(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{16,}", "Bearer [REDACTED]", sanitized)

    # 3. Mask key-value credentials: password=xyz, token=xyz, api_key=xyz, secret=xyz
    sanitized = re.sub(
        r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key)\s*[:=]\s*['\"]?(\S+?)['\"]?(?=\s|$)",
        r"\1=[REDACTED]",
        sanitized,
    )

    return sanitized


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """
    Establish a connection to the SQLite database.

    Automatically ensures the parent directory exists.
    """
    target_path = Path(db_path) if db_path else get_db_path()
    target_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(target_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Optional[Path] = None) -> None:
    """Initialize the database schema if not already created."""
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    user_request TEXT NOT NULL,
                    action TEXT NOT NULL,
                    risk_level TEXT NOT NULL,
                    approval_required INTEGER NOT NULL,
                    approval_result TEXT NOT NULL,
                    execution_status TEXT NOT NULL,
                    result_summary TEXT
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    user_request TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    error_summary TEXT
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS task_steps (
                    step_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    step_order INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    arguments TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    output TEXT,
                    error_info TEXT,
                    depends_on_step_id TEXT,
                    FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS workspaces (
                    workspace_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    path TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS workspace_permissions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workspace_id TEXT NOT NULL,
                    permission TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (workspace_id) REFERENCES workspaces(workspace_id) ON DELETE CASCADE
                );
                """
            )
    finally:
        conn.close()


def log_event(
    user_request: str,
    action: str,
    risk_level: str,
    approval_required: bool | int,
    approval_result: str,
    execution_status: str,
    result_summary: str = "",
    timestamp: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> int:
    """
    Record an agent execution event into the SQLite audit log.

    Args:
        user_request: Original user prompt / instruction.
        action: Action type ('search', 'rename', 'move', 'delete', 'unsupported', 'ambiguous').
        risk_level: Risk tier ('low', 'medium', 'high').
        approval_required: Whether user approval was required (0 or 1 / bool).
        approval_result: 'NOT_REQUIRED', 'APPROVED', 'DENIED', or 'NOT_APPLICABLE'.
        execution_status: 'SUCCESS', 'CANCELLED', 'BLOCKED', 'FAILED', 'AMBIGUOUS', 'NOT_SUPPORTED'.
        result_summary: Concise non-sensitive summary of the outcome.
        timestamp: Optional timestamp string (defaults to current local time).
        db_path: Optional path to SQLite file (defaults to active DB_PATH).

    Returns:
        The integer ID of the newly created audit row.
    """
    init_db(db_path)

    ts = timestamp or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    clean_request = sanitize_text(user_request)
    clean_summary = sanitize_text(result_summary)
    appr_req_int = 1 if approval_required else 0

    conn = get_connection(db_path)
    try:
        with conn:
            cursor = conn.execute(
                """
                INSERT INTO audit_log (
                    timestamp,
                    user_request,
                    action,
                    risk_level,
                    approval_required,
                    approval_result,
                    execution_status,
                    result_summary
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    ts,
                    clean_request,
                    action,
                    risk_level,
                    appr_req_int,
                    approval_result,
                    execution_status,
                    clean_summary,
                ),
            )
            return int(cursor.lastrowid or 0)
    finally:
        conn.close()


def get_recent_logs(
    limit: int = 10,
    db_path: Optional[Path] = None,
) -> list[dict[str, Any]]:
    """
    Retrieve the most recent audit log entries ordered from newest to oldest.

    Args:
        limit: Maximum number of rows to return (default: 10).
        db_path: Optional path to SQLite file (defaults to active DB_PATH).

    Returns:
        List of dictionaries corresponding to audit_log rows.
    """
    init_db(db_path)

    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            """
            SELECT
                id,
                timestamp,
                user_request,
                action,
                risk_level,
                approval_required,
                approval_result,
                execution_status,
                result_summary
            FROM audit_log
            ORDER BY id DESC
            LIMIT ?;
            """,
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def create_task_record(
    task_id: str,
    user_request: str,
    status: str = "PENDING",
    created_at: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> None:
    """Record a new task in the tasks table."""
    init_db(db_path)
    ts = created_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    clean_request = sanitize_text(user_request)
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO tasks (
                    task_id,
                    user_request,
                    status,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?);
                """,
                (task_id, clean_request, status, ts, ts),
            )
    finally:
        conn.close()


def create_step_record(
    step_id: str,
    task_id: str,
    step_order: int,
    action: str,
    arguments: dict[str, Any] | str,
    status: str = "PENDING",
    depends_on_step_id: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> None:
    """Record a new step in the task_steps table."""
    init_db(db_path)
    args_json = json.dumps(arguments) if isinstance(arguments, dict) else str(arguments)
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO task_steps (
                    step_id,
                    task_id,
                    step_order,
                    action,
                    arguments,
                    status,
                    attempts,
                    depends_on_step_id
                ) VALUES (?, ?, ?, ?, ?, ?, 0, ?);
                """,
                (
                    step_id,
                    task_id,
                    step_order,
                    action,
                    args_json,
                    status,
                    depends_on_step_id,
                ),
            )
    finally:
        conn.close()


def update_task_record(
    task_id: str,
    status: str,
    error_summary: Optional[str] = None,
    updated_at: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> None:
    """Update task status and error summary."""
    init_db(db_path)
    ts = updated_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    clean_err = sanitize_text(error_summary) if error_summary else None
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                UPDATE tasks
                SET status = ?, error_summary = ?, updated_at = ?
                WHERE task_id = ?;
                """,
                (status, clean_err, ts, task_id),
            )
    finally:
        conn.close()


def update_step_record(
    step_id: str,
    status: str,
    attempts: int,
    output: Optional[dict[str, Any] | str] = None,
    error_info: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> None:
    """Update step status, attempt count, output, and error info."""
    init_db(db_path)
    output_json = (
        json.dumps(output)
        if isinstance(output, dict)
        else (str(output) if output is not None else None)
    )
    clean_err = sanitize_text(error_info) if error_info else None
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                UPDATE task_steps
                SET status = ?, attempts = ?, output = ?, error_info = ?
                WHERE step_id = ?;
                """,
                (status, attempts, output_json, clean_err, step_id),
            )
    finally:
        conn.close()


def get_task_record(
    task_id: str,
    db_path: Optional[Path] = None,
) -> Optional[dict[str, Any]]:
    """Retrieve a single task by its task_id."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            """
            SELECT task_id, user_request, status, created_at, updated_at, error_summary
            FROM tasks
            WHERE task_id = ?;
            """,
            (task_id,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_task_steps_records(
    task_id: str,
    db_path: Optional[Path] = None,
) -> list[dict[str, Any]]:
    """Retrieve all steps for a given task ordered by step_order."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            """
            SELECT step_id, task_id, step_order, action, arguments, status, attempts, output,
                error_info, depends_on_step_id
            FROM task_steps
            WHERE task_id = ?
            ORDER BY step_order ASC;
            """,
            (task_id,),
        )
        results = []
        for row in cursor.fetchall():
            d = dict(row)
            try:
                d["arguments"] = json.loads(d["arguments"])
            except Exception:
                pass
            if d.get("output"):
                try:
                    d["output"] = json.loads(d["output"])
                except Exception:
                    pass
            results.append(d)
        return results
    finally:
        conn.close()


def list_task_records(
    limit: int = 10,
    db_path: Optional[Path] = None,
) -> list[dict[str, Any]]:
    """List recent tasks ordered from newest to oldest."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            """
            SELECT task_id, user_request, status, created_at, updated_at, error_summary
            FROM tasks
            ORDER BY created_at DESC
            LIMIT ?;
            """,
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def create_workspace_record(
    workspace_id: str,
    name: str,
    path: str,
    enabled: bool | int = 1,
    permissions: Optional[list[str] | set[str]] = None,
    created_at: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> None:
    """Record a new workspace and its permissions."""
    init_db(db_path)
    ts = created_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    is_enabled = 1 if enabled else 0
    perms = list(permissions) if permissions is not None else ["READ", "WRITE", "DELETE"]

    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO workspaces (
                    workspace_id,
                    name,
                    path,
                    enabled,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?);
                """,
                (workspace_id, name, path, is_enabled, ts, ts),
            )
            for p in perms:
                conn.execute(
                    """
                    INSERT INTO workspace_permissions (
                        workspace_id,
                        permission,
                        created_at
                    ) VALUES (?, ?, ?);
                    """,
                    (workspace_id, p.upper().strip(), ts),
                )
    finally:
        conn.close()


def update_workspace_record(
    workspace_id: str,
    name: Optional[str] = None,
    path: Optional[str] = None,
    enabled: Optional[bool | int] = None,
    permissions: Optional[list[str] | set[str]] = None,
    updated_at: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> bool:
    """Update workspace attributes and permissions."""
    init_db(db_path)
    ts = updated_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection(db_path)
    try:
        with conn:
            # Check existence
            cur = conn.execute(
                "SELECT workspace_id FROM workspaces WHERE workspace_id = ?;", (workspace_id,)
            )
            if not cur.fetchone():
                return False

            updates = ["updated_at = ?"]
            params: list[Any] = [ts]

            if name is not None:
                updates.append("name = ?")
                params.append(name)
            if path is not None:
                updates.append("path = ?")
                params.append(path)
            if enabled is not None:
                updates.append("enabled = ?")
                params.append(1 if enabled else 0)

            params.append(workspace_id)
            conn.execute(
                f"UPDATE workspaces SET {', '.join(updates)} WHERE workspace_id = ?;",
                params,
            )

            if permissions is not None:
                conn.execute(
                    "DELETE FROM workspace_permissions WHERE workspace_id = ?;",
                    (workspace_id,),
                )
                for p in permissions:
                    conn.execute(
                        """
                        INSERT INTO workspace_permissions (
                            workspace_id,
                            permission,
                            created_at
                        ) VALUES (?, ?, ?);
                        """,
                        (workspace_id, p.upper().strip(), ts),
                    )
            return True
    finally:
        conn.close()


def delete_workspace_record(
    workspace_id: str,
    db_path: Optional[Path] = None,
) -> bool:
    """Delete a workspace and its permissions."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        with conn:
            cur = conn.execute(
                "DELETE FROM workspaces WHERE workspace_id = ?;",
                (workspace_id,),
            )
            return cur.rowcount > 0
    finally:
        conn.close()


def get_workspace_record(
    workspace_id: str,
    db_path: Optional[Path] = None,
) -> Optional[dict[str, Any]]:
    """Retrieve workspace record with permissions list."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        cur = conn.execute(
            """
            SELECT workspace_id, name, path, enabled, created_at, updated_at
            FROM workspaces
            WHERE workspace_id = ?;
            """,
            (workspace_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        d = dict(row)
        p_cur = conn.execute(
            """
            SELECT permission FROM workspace_permissions
            WHERE workspace_id = ?;
            """,
            (workspace_id,),
        )
        d["permissions"] = [r["permission"] for r in p_cur.fetchall()]
        return d
    finally:
        conn.close()


def get_workspace_by_name_record(
    name: str,
    db_path: Optional[Path] = None,
) -> Optional[dict[str, Any]]:
    """Retrieve workspace record by name (case-insensitive)."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        cur = conn.execute(
            """
            SELECT workspace_id, name, path, enabled, created_at, updated_at
            FROM workspaces
            WHERE LOWER(name) = LOWER(?);
            """,
            (name.strip(),),
        )
        row = cur.fetchone()
        if not row:
            return None
        d = dict(row)
        p_cur = conn.execute(
            """
            SELECT permission FROM workspace_permissions
            WHERE workspace_id = ?;
            """,
            (d["workspace_id"],),
        )
        d["permissions"] = [r["permission"] for r in p_cur.fetchall()]
        return d
    finally:
        conn.close()


def list_workspace_records(
    db_path: Optional[Path] = None,
) -> list[dict[str, Any]]:
    """Retrieve all workspaces with their permissions."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        cur = conn.execute(
            """
            SELECT workspace_id, name, path, enabled, created_at, updated_at
            FROM workspaces
            ORDER BY created_at ASC;
            """
        )
        workspaces = [dict(row) for row in cur.fetchall()]
        for ws in workspaces:
            p_cur = conn.execute(
                """
                SELECT permission FROM workspace_permissions
                WHERE workspace_id = ?;
                """,
                (ws["workspace_id"],),
            )
            ws["permissions"] = [r["permission"] for r in p_cur.fetchall()]
        return workspaces
    finally:
        conn.close()


def count_workspaces(
    db_path: Optional[Path] = None,
) -> int:
    """Return the total number of configured workspaces."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        cur = conn.execute("SELECT COUNT(*) AS total FROM workspaces;")
        row = cur.fetchone()
        return row["total"] if row else 0
    finally:
        conn.close()
