"""
Calendar & Scheduling Automation Tools (Milestone 8).

Provides calendar event inspection (LOW risk), overlap/conflict checking (LOW risk),
and event creation (MEDIUM risk requiring human approval).
"""

import sqlite3
from typing import Any, Optional

import app.database as db


def _get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(db.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_calendar_table() -> None:
    """Ensure calendar events table exists."""
    conn = _get_db_connection()
    try:
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS calendar_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    start_time TEXT NOT NULL,
                    end_time TEXT NOT NULL,
                    description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
    finally:
        conn.close()


def calendar_list_events(
    start_date: Optional[str] = None, end_date: Optional[str] = None
) -> dict[str, Any]:
    """
    List calendar events within an optional time range (LOW risk).
    """
    _ensure_calendar_table()
    conn = _get_db_connection()
    try:
        cur = conn.cursor()
        if start_date and end_date:
            cur.execute(
                "SELECT id, title, start_time, end_time, description FROM calendar_events "
                "WHERE start_time >= ? AND start_time <= ? ORDER BY start_time ASC",
                (start_date, end_date),
            )
        elif start_date:
            cur.execute(
                "SELECT id, title, start_time, end_time, description FROM calendar_events "
                "WHERE start_time >= ? ORDER BY start_time ASC",
                (start_date,),
            )
        else:
            cur.execute(
                "SELECT id, title, start_time, end_time, description "
                "FROM calendar_events ORDER BY start_time ASC"
            )
        rows = [dict(r) for r in cur.fetchall()]
        return {
            "success": True,
            "count": len(rows),
            "events": rows,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "status": "EXECUTION_FAILURE",
        }
    finally:
        conn.close()


def calendar_check_conflict(start_time: str, end_time: str) -> dict[str, Any]:
    """
    Check if a proposed timeslot conflicts with existing events (LOW risk).
    """
    _ensure_calendar_table()
    conn = _get_db_connection()
    try:
        cur = conn.cursor()
        # Overlap condition: start < existing.end AND end > existing.start
        cur.execute(
            """
            SELECT id, title, start_time, end_time FROM calendar_events
            WHERE start_time < ? AND end_time > ?
            """,
            (end_time, start_time),
        )
        conflicts = [dict(r) for r in cur.fetchall()]
        has_conflict = len(conflicts) > 0
        return {
            "success": True,
            "has_conflict": has_conflict,
            "conflicts_count": len(conflicts),
            "conflicts": conflicts,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "status": "EXECUTION_FAILURE",
        }
    finally:
        conn.close()


def calendar_create_event(
    title: str, start_time: str, end_time: str, description: str = ""
) -> dict[str, Any]:
    """
    Create a new calendar appointment (MEDIUM risk; requires human approval).
    """
    if not title or not title.strip():
        return {
            "success": False,
            "error": "Event title cannot be empty",
            "status": "VALIDATION_FAILURE",
        }

    _ensure_calendar_table()
    conn = _get_db_connection()
    try:
        cur = conn.cursor()
        with conn:
            cur.execute(
                """
                INSERT INTO calendar_events (title, start_time, end_time, description)
                VALUES (?, ?, ?, ?)
                """,
                (title.strip(), start_time.strip(), end_time.strip(), description.strip()),
            )
            event_id = cur.lastrowid

        return {
            "success": True,
            "event_id": event_id,
            "title": title,
            "start_time": start_time,
            "end_time": end_time,
            "status": "EVENT_CREATED",
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "status": "EXECUTION_FAILURE",
        }
    finally:
        conn.close()


def calendar_delete_event(event_id: int) -> dict[str, Any]:
    """Deletes a calendar event by ID."""
    _ensure_calendar_table()
    conn = _get_db_connection()
    try:
        cur = conn.cursor()
        with conn:
            cur.execute("DELETE FROM calendar_events WHERE id = ?", (event_id,))
        return {"success": True, "event_id": event_id}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        conn.close()


def parse_calendar_event_request(text: str) -> dict[str, str]:
    """
    Extracts title, start_time, and end_time ISO strings from natural language prompts
    such as 'add one more event on 10:20 AM on 9th october' or 'schedule meeting tomorrow at 3 PM'.
    """
    import re
    from datetime import datetime, timedelta

    now = datetime.now()
    text_lower = text.lower()

    # 1. Date parsing
    target_date = now.date()
    months = {
        "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
        "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8,
        "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
    }

    month_keys = "|".join(sorted(months.keys(), key=len, reverse=True))
    m_date1 = re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({month_keys})\b", text_lower)
    m_date2 = re.search(rf"\b({month_keys})\s+(\d{{1,2}})(?:st|nd|rd|th)?\b", text_lower)

    if m_date1:
        day = int(m_date1.group(1))
        month = months[m_date1.group(2)]
        try:
            target_date = target_date.replace(month=month, day=day)
        except ValueError:
            pass
    elif m_date2:
        month = months[m_date2.group(1)]
        day = int(m_date2.group(2))
        try:
            target_date = target_date.replace(month=month, day=day)
        except ValueError:
            pass
    elif "tomorrow" in text_lower:
        target_date = target_date + timedelta(days=1)

    # 2. Time parsing
    hour = 10
    minute = 0
    m_time = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", text_lower)
    if not m_time:
        m_time = re.search(r"\b(?:at|on)\s+(\d{1,2}):(\d{2})\b", text_lower)

    if m_time:
        hour = int(m_time.group(1))
        minute = int(m_time.group(2)) if m_time.group(2) else 0
        ampm = m_time.group(3).lower() if len(m_time.groups()) >= 3 and m_time.group(3) else None
        if ampm == "pm" and hour < 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0

    dt_start = datetime(target_date.year, target_date.month, target_date.day, hour, minute)
    dt_end = dt_start + timedelta(hours=1)

    # 3. Title parsing
    title = "Scheduled Event"
    m_title = re.search(r"\b(?:called|named|titled)\s+[\"']?([^\"'\n]+)[\"']?", text, re.IGNORECASE)
    if not m_title:
        m_title = re.search(r"\b(?:meeting|event)\s+(?:with|for|about)\s+([a-zA-Z0-9_\s]+?)(?:\s+(?:on|at|tomorrow|today|\d)|$)", text, re.IGNORECASE)
    if not m_title:
        m_title = re.search(r"\b(?:schedule|add|create)\s+([a-zA-Z0-9_\s]+?)(?:\s+(?:on|at|tomorrow|today|\d)|$)", text, re.IGNORECASE)

    if m_title and len(m_title.group(1).strip()) > 2:
        extracted = m_title.group(1).strip()
        cleaned_cand = re.sub(r"^(?:one\s+more\s+|an?\s+|new\s+)", "", extracted, flags=re.I).strip()
        if cleaned_cand.lower() not in ["event", "meeting", "reminder", "appointment"]:
            title = cleaned_cand.title()
        elif "on" in text_lower:
            title = f"Event on {target_date.strftime('%B %d')}"
    elif "on" in text_lower:
        title = f"Event on {target_date.strftime('%B %d')}"

    return {
        "title": title,
        "start_time": dt_start.strftime("%Y-%m-%dT%H:%M:00"),
        "end_time": dt_end.strftime("%Y-%m-%dT%H:%M:00"),
    }
