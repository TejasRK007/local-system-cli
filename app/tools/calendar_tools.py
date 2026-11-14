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
        "january": 1,
        "february": 2,
        "march": 3,
        "april": 4,
        "may": 5,
        "june": 6,
        "july": 7,
        "august": 8,
        "september": 9,
        "october": 10,
        "november": 11,
        "december": 12,
        "jan": 1,
        "feb": 2,
        "mar": 3,
        "apr": 4,
        "jun": 6,
        "jul": 7,
        "aug": 8,
        "sep": 9,
        "sept": 9,
        "oct": 10,
        "nov": 11,
        "dec": 12,
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
        pattern = (
            r"\b(?:meeting|event)\s+(?:with|for|about)\s+"
            r"([a-zA-Z0-9_\s]+?)(?:\s+(?:on|at|tomorrow|today|\d)|$)"
        )
        m_title = re.search(pattern, text, re.IGNORECASE)
    if not m_title:
        m_title = re.search(
            r"\b(?:schedule|add|create)\s+([a-zA-Z0-9_\s]+?)(?:\s+(?:on|at|tomorrow|today|\d)|$)",
            text,
            re.IGNORECASE,
        )

    if m_title and len(m_title.group(1).strip()) > 2:
        extracted = m_title.group(1).strip()
        cleaned_cand = re.sub(
            r"^(?:one\s+more\s+|an?\s+|new\s+)", "", extracted, flags=re.I
        ).strip()
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


def calendar_sync_google(
    calendar_id_or_url: str,
    api_key: Optional[str] = None,
    access_token: Optional[str] = None,
) -> dict[str, Any]:
    """
    Sync events from Google Calendar into local SQLite storage.
    Supports:
    1. Google Calendar REST API v3 via API key or OAuth Bearer token
    2. Google Calendar iCal / .ics private or public feed URLs
    """
    import json
    import os
    import re
    import urllib.parse
    import urllib.request
    from datetime import datetime

    _ensure_calendar_table()
    raw_source = calendar_id_or_url.strip()
    if not raw_source:
        return {
            "success": False,
            "error": "Google Calendar ID or Feed URL cannot be empty.",
            "status": "VALIDATION_FAILURE",
        }

    resolved_api_key = api_key or os.getenv("GOOGLE_CALENDAR_API_KEY")
    resolved_token = access_token or os.getenv("GOOGLE_ACCESS_TOKEN")

    parsed_events: list[dict[str, str]] = []

    # Case 1: Direct iCal / ICS Feed (Public or Secret iCal Address from Google Calendar Settings)
    if "calendar.google.com" in raw_source.lower() and (
        raw_source.lower().endswith(".ics") or "/ical/" in raw_source.lower()
    ) or (raw_source.lower().startswith("http") and raw_source.lower().endswith(".ics")):
        try:
            req = urllib.request.Request(
                raw_source,
                headers={"User-Agent": "LocalAgenticCalendarSync/1.0"},
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                raw_ics = resp.read().decode("utf-8", errors="replace")

            vevent_matches = re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", raw_ics, re.DOTALL)
            for block in vevent_matches:
                summary_m = re.search(r"SUMMARY(?::|;[^:]*:)(.*)", block)
                dtstart_m = re.search(r"DTSTART(?::|;[^:]*:)(.*)", block)
                dtend_m = re.search(r"DTEND(?::|;[^:]*:)(.*)", block)
                desc_m = re.search(r"DESCRIPTION(?::|;[^:]*:)(.*)", block)

                title = summary_m.group(1).strip() if summary_m else "Google Calendar Event"
                desc = desc_m.group(1).strip().replace("\\n", "\n") if desc_m else ""

                def _parse_ics_date(d_str: str) -> str:
                    s = d_str.strip().replace("Z", "")
                    if len(s) == 8:
                        return f"{s[:4]}-{s[4:6]}-{s[6:8]}T09:00:00"
                    if len(s) >= 15:
                        return f"{s[:4]}-{s[4:6]}-{s[6:8]}T{s[9:11]}:{s[11:13]}:{s[13:15]}"
                    return datetime.now().strftime("%Y-%m-%dT%H:00:00")

                if dtstart_m:
                    start_iso = _parse_ics_date(dtstart_m.group(1))
                else:
                    start_iso = datetime.now().strftime("%Y-%m-%dT%H:00:00")
                end_iso = _parse_ics_date(dtend_m.group(1)) if dtend_m else start_iso

                parsed_events.append({
                    "title": title,
                    "start_time": start_iso,
                    "end_time": end_iso,
                    "description": desc,
                })
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to retrieve Google Calendar iCal feed: {e}",
                "status": "NETWORK_FAILURE",
            }

    # Case 2: Google Calendar REST API v3
    else:
        cal_id = raw_source
        encoded_id = urllib.parse.quote(cal_id)

        now_iso = datetime.now().strftime("%Y-%m-%dT00:00:00Z")
        url = (
            f"https://www.googleapis.com/calendar/v3/calendars/{encoded_id}/events"
            f"?timeMin={now_iso}&singleEvents=true&orderBy=startTime&maxResults=50"
        )
        if resolved_api_key:
            url += f"&key={resolved_api_key}"

        headers = {"Accept": "application/json", "User-Agent": "LocalAgenticCalendarSync/1.0"}
        if resolved_token:
            headers["Authorization"] = f"Bearer {resolved_token}"

        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            for item in data.get("items", []):
                title = item.get("summary") or "Untitled Event"
                start_obj = item.get("start", {})
                end_obj = item.get("end", {})
                start_raw = start_obj.get("dateTime") or start_obj.get("date") or ""
                end_raw = end_obj.get("dateTime") or end_obj.get("date") or ""

                start_clean = re.sub(r"[+-]\d{2}:\d{2}$|Z$", "", start_raw)
                end_clean = re.sub(r"[+-]\d{2}:\d{2}$|Z$", "", end_raw)
                if len(start_clean) == 10:
                    start_clean += "T09:00:00"
                if len(end_clean) == 10:
                    end_clean += "T10:00:00"

                parsed_events.append({
                    "title": title,
                    "start_time": start_clean,
                    "end_time": end_clean or start_clean,
                    "description": item.get("description") or "",
                })
        except Exception as e:
            return {
                "success": False,
                "error": (
                    f"Google Calendar API request failed: {e}. "
                    "Ensure your Google Calendar ID is valid and an API Key or OAuth Token "
                    "is provided, or provide your Google Calendar Secret iCal Address URL directly."
                ),
                "status": "API_FAILURE",
            }

    # Save idempotently into local SQLite database
    conn = _get_db_connection()
    inserted_count = 0
    try:
        cur = conn.cursor()
        with conn:
            for ev in parsed_events:
                cur.execute(
                    "SELECT id FROM calendar_events WHERE title = ? AND start_time = ?",
                    (ev["title"], ev["start_time"]),
                )
                if not cur.fetchone():
                    cur.execute(
                        """
                        INSERT INTO calendar_events (title, start_time, end_time, description)
                        VALUES (?, ?, ?, ?)
                        """,
                        (ev["title"], ev["start_time"], ev["end_time"], ev["description"]),
                    )
                    inserted_count += 1
        return {
            "success": True,
            "synced_count": len(parsed_events),
            "newly_added": inserted_count,
            "source": raw_source,
            "events": parsed_events,
        }
    except Exception as e:
        return {"success": False, "error": str(e), "status": "DATABASE_ERROR"}
    finally:
        conn.close()


def calendar_create_google_event(
    title: str,
    start_time: str,
    end_time: str,
    description: str = "",
    calendar_id: str = "primary",
    access_token: Optional[str] = None,
) -> dict[str, Any]:
    """
    Create an event in Google Calendar via REST API v3 and mirror it in local SQLite calendar.
    Requires an OAuth access token (provided or via GOOGLE_ACCESS_TOKEN env var).
    """
    import json
    import os
    import urllib.parse
    import urllib.request

    resolved_token = access_token or os.getenv("GOOGLE_ACCESS_TOKEN")
    google_event_id = None
    api_synced = False

    if resolved_token:
        try:
            encoded_id = urllib.parse.quote(calendar_id.strip() or "primary")
            url = f"https://www.googleapis.com/calendar/v3/calendars/{encoded_id}/events"
            s_time = start_time.strip()
            e_time = end_time.strip()

            s_payload = (
                {"dateTime": s_time}
                if ("+" in s_time or "Z" in s_time or "-" in s_time[10:])
                else {
                    "dateTime": f"{s_time}:00" if len(s_time) == 16 else s_time,
                    "timeZone": "UTC",
                }
            )
            e_payload = (
                {"dateTime": e_time}
                if ("+" in e_time or "Z" in e_time or "-" in e_time[10:])
                else {
                    "dateTime": f"{e_time}:00" if len(e_time) == 16 else e_time,
                    "timeZone": "UTC",
                }
            )

            body = json.dumps({
                "summary": title.strip(),
                "description": description.strip(),
                "start": s_payload,
                "end": e_payload,
            }).encode("utf-8")

            req = urllib.request.Request(
                url,
                data=body,
                headers={
                    "Authorization": f"Bearer {resolved_token}",
                    "Content-Type": "application/json",
                    "User-Agent": "LocalAgenticCalendarSync/1.0",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))
                google_event_id = res_data.get("id")
                api_synced = True
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to create Google Calendar event: {e}",
                "status": "GOOGLE_API_ERROR",
            }

    local_res = calendar_create_event(title, start_time, end_time, description)
    if not local_res.get("success"):
        return local_res

    local_res["google_synced"] = api_synced
    if google_event_id:
        local_res["google_event_id"] = google_event_id
    if not resolved_token:
        local_res["note"] = (
            "Saved to local calendar. To sync directly to remote Google Calendar, "
            "provide a Google OAuth access token."
        )
    return local_res
