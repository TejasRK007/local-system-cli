"""
Live Dynamic Attendance Tool with Time-Rotating QR Code.

Provides secure classroom attendance management:
- Live rotating dynamic QR code refreshed every N seconds (default 15s)
- Anti-proxy protection: forwarded screenshots expire within seconds
- Real-time roster tracking and verified student check-in
- CSV roster export
- Zero emojis, 100% offline local privacy
"""

import csv
import io
import secrets
import socket
import sqlite3
import time
from typing import Any, Dict, Optional

import qrcode
import qrcode.image.svg

import app.database as db


def get_local_ip() -> str:
    """Return the machine's primary LAN IP address on Wi-Fi or local Ethernet network."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.3)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass
    return "127.0.0.1"


def resolve_checkin_host_url(host_url: Optional[str] = None, port: int = 8000) -> str:
    """
    Ensure the check-in URL uses a reachable LAN IP address so student phones
    scanning the QR code can access the server instead of failing on loopback 127.0.0.1.
    """
    lan_ip = get_local_ip()
    if not host_url:
        return f"http://{lan_ip}:{port}" if lan_ip != "127.0.0.1" else f"http://127.0.0.1:{port}"

    cleaned = host_url.rstrip("/")
    if lan_ip != "127.0.0.1":
        if "://127.0.0.1" in cleaned:
            cleaned = cleaned.replace("://127.0.0.1", f"://{lan_ip}")
        elif "://localhost" in cleaned:
            cleaned = cleaned.replace("://localhost", f"://{lan_ip}")
        elif "://0.0.0.0" in cleaned:
            cleaned = cleaned.replace("://0.0.0.0", f"://{lan_ip}")

    return cleaned


def _get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(db.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_attendance_tables() -> None:
    """Ensure database schema for attendance sessions, tokens, and records."""
    conn = _get_db_connection()
    try:
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS attendance_sessions (
                    id TEXT PRIMARY KEY,
                    course_name TEXT NOT NULL,
                    section TEXT NOT NULL,
                    rotation_interval INTEGER NOT NULL DEFAULT 15,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    ended_at TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS attendance_tokens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    token TEXT NOT NULL,
                    expires_at REAL NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(session_id) REFERENCES attendance_sessions(id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS attendance_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    student_id TEXT NOT NULL,
                    student_name TEXT NOT NULL,
                    device_info TEXT,
                    checked_in_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(session_id, student_id),
                    FOREIGN KEY(session_id) REFERENCES attendance_sessions(id)
                )
                """
            )
    finally:
        conn.close()


def generate_qr_svg(url: str) -> str:
    """Generate high-contrast vector SVG string for a given check-in URL."""
    factory = qrcode.image.svg.SvgPathImage
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
        image_factory=factory,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(attrib={"class": "attendance-qr-svg"})
    stream = io.BytesIO()
    img.save(stream)
    return stream.getvalue().decode("utf-8")


def attendance_start_session(
    course_name: str,
    section: str = "Section A",
    rotation_interval_seconds: int = 15,
    host_url: str = "http://127.0.0.1:8000",
) -> Dict[str, Any]:
    """Start a new live attendance session with dynamic rotating QR code."""
    _ensure_attendance_tables()
    session_id = f"att-{int(time.time())}-{secrets.token_hex(3)}"
    initial_token = secrets.token_urlsafe(12)
    expires_at = time.time() + max(5, int(rotation_interval_seconds))

    conn = _get_db_connection()
    try:
        with conn:
            # End any previously active session
            conn.execute(
                "UPDATE attendance_sessions SET is_active = 0, ended_at = CURRENT_TIMESTAMP "
                "WHERE is_active = 1"
            )
            # Create new session
            conn.execute(
                """
                INSERT INTO attendance_sessions
                (id, course_name, section, rotation_interval, is_active)
                VALUES (?, ?, ?, ?, 1)
                """,
                (session_id, course_name.strip(), section.strip(), int(rotation_interval_seconds)),
            )
            # Save first token
            conn.execute(
                """
                INSERT INTO attendance_tokens (session_id, token, expires_at)
                VALUES (?, ?, ?)
                """,
                (session_id, initial_token, expires_at),
            )
    finally:
        conn.close()

    resolved_host = resolve_checkin_host_url(host_url)
    checkin_url = (
        f"{resolved_host}/attendance/checkin?session_id={session_id}&token={initial_token}"
    )
    qr_svg = generate_qr_svg(checkin_url)
    lan_ip = get_local_ip()

    return {
        "success": True,
        "session_id": session_id,
        "course_name": course_name,
        "section": section,
        "rotation_interval": int(rotation_interval_seconds),
        "current_token": initial_token,
        "expires_at": expires_at,
        "seconds_remaining": max(0, int(expires_at - time.time())),
        "checkin_url": checkin_url,
        "lan_ip": lan_ip,
        "network_url": f"http://{lan_ip}:8000" if lan_ip != "127.0.0.1" else None,
        "qr_svg": qr_svg,
        "present_count": 0,
        "roster": [],
    }


def attendance_rotate_token(
    session_id: str, host_url: str = "http://127.0.0.1:8000"
) -> Dict[str, Any]:
    """Generate a new time-limited token for the active session and refresh the QR code."""
    _ensure_attendance_tables()
    conn = _get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, course_name, section, rotation_interval, is_active
            FROM attendance_sessions WHERE id = ? AND is_active = 1
            """,
            (session_id,),
        )
        sess = cur.fetchone()
        if not sess:
            return {"success": False, "error": "No active session found with this ID."}

        interval = sess["rotation_interval"]
        new_token = secrets.token_urlsafe(12)
        expires_at = time.time() + max(5, int(interval))

        with conn:
            conn.execute(
                "INSERT INTO attendance_tokens (session_id, token, expires_at) VALUES (?, ?, ?)",
                (session_id, new_token, expires_at),
            )

        resolved_host = resolve_checkin_host_url(host_url)
        checkin_url = (
            f"{resolved_host}/attendance/checkin?session_id={session_id}&token={new_token}"
        )
        qr_svg = generate_qr_svg(checkin_url)
        lan_ip = get_local_ip()

        return {
            "success": True,
            "session_id": session_id,
            "new_token": new_token,
            "expires_at": expires_at,
            "seconds_remaining": max(0, int(expires_at - time.time())),
            "checkin_url": checkin_url,
            "lan_ip": lan_ip,
            "network_url": f"http://{lan_ip}:8000" if lan_ip != "127.0.0.1" else None,
            "qr_svg": qr_svg,
        }
    finally:
        conn.close()


def attendance_get_active_session(
    host_url: str = "http://127.0.0.1:8000",
) -> Dict[str, Any]:
    """Fetch current active session state, auto-refreshing expired tokens."""
    _ensure_attendance_tables()
    conn = _get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, course_name, section, rotation_interval, is_active, created_at
            FROM attendance_sessions
            WHERE is_active = 1
            ORDER BY created_at DESC LIMIT 1
            """
        )
        sess = cur.fetchone()
        if not sess:
            return {"success": True, "active": False, "message": "No active attendance session."}

        session_id = sess["id"]
        interval = sess["rotation_interval"]

        # Fetch latest token
        cur.execute(
            """
            SELECT token, expires_at FROM attendance_tokens
            WHERE session_id = ?
            ORDER BY id DESC LIMIT 1
            """,
            (session_id,),
        )
        token_row = cur.fetchone()
        now_ts = time.time()
        resolved_host = resolve_checkin_host_url(host_url)

        if not token_row or token_row["expires_at"] <= now_ts:
            # Token expired -> auto rotate
            rotate_res = attendance_rotate_token(session_id, host_url=resolved_host)
            current_token = rotate_res["new_token"]
            expires_at = rotate_res["expires_at"]
            qr_svg = rotate_res["qr_svg"]
            checkin_url = rotate_res["checkin_url"]
        else:
            current_token = token_row["token"]
            expires_at = token_row["expires_at"]
            checkin_url = (
                f"{resolved_host}/attendance/checkin?session_id={session_id}&token={current_token}"
            )
            qr_svg = generate_qr_svg(checkin_url)

        # Fetch checked in roster
        cur.execute(
            """
            SELECT student_id, student_name, device_info, checked_in_at
            FROM attendance_records
            WHERE session_id = ?
            ORDER BY checked_in_at DESC
            """,
            (session_id,),
        )
        records = [
            {
                "student_id": r["student_id"],
                "student_name": r["student_name"],
                "device_info": r["device_info"] or "Mobile Web Client",
                "checked_in_at": r["checked_in_at"],
            }
            for r in cur.fetchall()
        ]

        lan_ip = get_local_ip()
        return {
            "success": True,
            "active": True,
            "session_id": session_id,
            "course_name": sess["course_name"],
            "section": sess["section"],
            "rotation_interval": interval,
            "current_token": current_token,
            "expires_at": expires_at,
            "seconds_remaining": max(0, int(expires_at - now_ts)),
            "checkin_url": checkin_url,
            "lan_ip": lan_ip,
            "network_url": f"http://{lan_ip}:8000" if lan_ip != "127.0.0.1" else None,
            "qr_svg": qr_svg,
            "present_count": len(records),
            "roster": records,
        }
    finally:
        conn.close()


def attendance_end_session(session_id: Optional[str] = None) -> Dict[str, Any]:
    """End the current or specified attendance session."""
    _ensure_attendance_tables()
    conn = _get_db_connection()
    try:
        cur = conn.cursor()
        target_id = session_id
        if not target_id:
            cur.execute(
                "SELECT id FROM attendance_sessions WHERE is_active = 1 "
                "ORDER BY created_at DESC LIMIT 1"
            )
            row = cur.fetchone()
            if row:
                target_id = row["id"]

        with conn:
            if target_id:
                conn.execute(
                    "UPDATE attendance_sessions SET is_active = 0, ended_at = CURRENT_TIMESTAMP "
                    "WHERE id = ?",
                    (target_id,),
                )
            else:
                conn.execute(
                    "UPDATE attendance_sessions SET is_active = 0, ended_at = CURRENT_TIMESTAMP "
                    "WHERE is_active = 1"
                )

        total_present = 0
        if target_id:
            cur.execute(
                "SELECT COUNT(*) as cnt FROM attendance_records WHERE session_id = ?", (target_id,)
            )
            cnt_row = cur.fetchone()
            if cnt_row:
                total_present = cnt_row["cnt"]

        return {
            "success": True,
            "message": (
                f"Attendance session closed successfully ({total_present} students recorded)."
            ),
            "session_id": target_id,
            "total_present": total_present,
            "export_url": f"/api/attendance/export?session_id={target_id}" if target_id else None,
        }
    finally:
        conn.close()


def attendance_checkin(
    session_id: str,
    token: str,
    student_id: str,
    student_name: str,
    device_info: str = "Mobile Client",
) -> Dict[str, Any]:
    """
    Student check-in handler with anti-proxy verification:
    - Verifies session is currently active
    - Token must match current or immediately preceding token (grace period)
    - Rejects expired or forwarded tokens
    - Prevents duplicate check-ins for the same student
    """
    _ensure_attendance_tables()
    s_id = student_id.strip().upper()
    s_name = student_name.strip()

    if not s_id or not s_name:
        return {"success": False, "error": "Both Student ID and Student Name are required."}

    conn = _get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, course_name, is_active, rotation_interval
            FROM attendance_sessions WHERE id = ?
            """,
            (session_id,),
        )
        sess = cur.fetchone()
        if not sess:
            return {"success": False, "error": "Invalid session ID."}
        if not sess["is_active"]:
            return {"success": False, "error": "This attendance session has ended."}

        interval = sess["rotation_interval"]
        grace_period = interval + 8.0  # Allow scan + network latency window
        now_ts = time.time()

        # Check token validity in database
        cur.execute(
            """
            SELECT id, token, expires_at FROM attendance_tokens
            WHERE session_id = ? AND token = ?
            ORDER BY id DESC LIMIT 1
            """,
            (session_id, token.strip()),
        )
        tok_row = cur.fetchone()
        if not tok_row:
            return {
                "success": False,
                "error": "Invalid QR code token. Please scan the live QR code on the screen.",
            }

        # Check if token is older than the allowed grace window
        if now_ts > (tok_row["expires_at"] + grace_period):
            return {
                "success": False,
                "error": "QR code token expired. Screenshots cannot be used. Scan the live screen.",
            }

        # Check for duplicate student check-in
        cur.execute(
            """
            SELECT id, checked_in_at FROM attendance_records
            WHERE session_id = ? AND student_id = ?
            """,
            (session_id, s_id),
        )
        existing = cur.fetchone()
        if existing:
            return {
                "success": False,
                "error": f"Student '{s_id}' has already checked in for this session.",
                "already_checked_in": True,
            }

        with conn:
            conn.execute(
                """
                INSERT INTO attendance_records (session_id, student_id, student_name, device_info)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, s_id, s_name, device_info.strip()),
            )

        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        return {
            "success": True,
            "message": f"Attendance verified for {s_name} ({s_id}).",
            "student_id": s_id,
            "student_name": s_name,
            "course_name": sess["course_name"],
            "timestamp": ts,
            "record": {
                "student_id": s_id,
                "student_name": s_name,
                "device_info": device_info.strip(),
                "checked_in_at": ts,
            },
        }
    finally:
        conn.close()


def attendance_export_csv(session_id: str) -> str:
    """Export attendance roster for a session as CSV."""
    _ensure_attendance_tables()
    conn = _get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT course_name, section FROM attendance_sessions WHERE id = ?", (session_id,)
        )
        sess = cur.fetchone()
        course = sess["course_name"] if sess else "Course"
        section = sess["section"] if sess else "A"

        cur.execute(
            """
            SELECT student_id, student_name, device_info, checked_in_at
            FROM attendance_records
            WHERE session_id = ?
            ORDER BY checked_in_at ASC
            """,
            (session_id,),
        )
        rows = cur.fetchall()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["# Attendance Roster", f"Course: {course}", f"Section: {section}"])
        writer.writerow(
            ["Student ID", "Student Name", "Check-in Timestamp", "Status", "Device Info"]
        )
        for r in rows:
            writer.writerow(
                [
                    r["student_id"],
                    r["student_name"],
                    r["checked_in_at"],
                    "Verified Present",
                    r["device_info"],
                ]
            )

        return output.getvalue()
    finally:
        conn.close()
