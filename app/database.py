"""
Audit database module for the Local Agentic Automation System.

Provides persistent SQLite-based audit logging for every agent execution,
recording action, risk classification, approval decisions, execution status,
and result summaries while ensuring no sensitive credentials or file contents
are persisted.
"""

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
    """Initialize the audit database schema if not already created."""
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
