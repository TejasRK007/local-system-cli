"""
Email & Communication Automation Tools (Milestone 8).

Provides isolated email search, message reading with secret redaction,
draft staging (MEDIUM risk), outbound dispatch (HIGH risk),
account connection, AI summarization, and smart reply generation.
"""

import base64
import email
import email.utils
import imaplib
import json
import os
import re
import smtplib
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from email.header import decode_header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Optional

import app.database as db


def _get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(db.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_email_tables() -> None:
    """Ensure tables for staging email drafts, inboxes, and account states exist."""
    conn = _get_db_connection()
    try:
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS email_drafts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    to_address TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    body TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'DRAFT',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    sent_at TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS email_inbox (
                    id TEXT PRIMARY KEY,
                    sender TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    body TEXT NOT NULL,
                    received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    category TEXT DEFAULT 'inbox',
                    priority TEXT DEFAULT 'normal',
                    is_read INTEGER DEFAULT 0,
                    summary TEXT,
                    raw_html TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS email_accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT NOT NULL,
                    account_type TEXT NOT NULL DEFAULT 'demo',
                    imap_host TEXT,
                    imap_port INTEGER,
                    smtp_host TEXT,
                    smtp_port INTEGER,
                    username TEXT,
                    password TEXT,
                    is_connected INTEGER DEFAULT 1,
                    last_synced TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            # Check and add columns if upgrading from older schema
            cur = conn.cursor()
            cur.execute("PRAGMA table_info(email_inbox)")
            existing_cols = [r["name"] for r in cur.fetchall()]
            if "category" not in existing_cols:
                conn.execute("ALTER TABLE email_inbox ADD COLUMN category TEXT DEFAULT 'inbox'")
            if "priority" not in existing_cols:
                conn.execute("ALTER TABLE email_inbox ADD COLUMN priority TEXT DEFAULT 'normal'")
            if "is_read" not in existing_cols:
                conn.execute("ALTER TABLE email_inbox ADD COLUMN is_read INTEGER DEFAULT 0")
            if "summary" not in existing_cols:
                conn.execute("ALTER TABLE email_inbox ADD COLUMN summary TEXT")
            if "raw_html" not in existing_cols:
                conn.execute("ALTER TABLE email_inbox ADD COLUMN raw_html TEXT")

            cur.execute("PRAGMA table_info(email_accounts)")
            account_cols = [r["name"] for r in cur.fetchall()]
            if "password" not in account_cols:
                conn.execute("ALTER TABLE email_accounts ADD COLUMN password TEXT")
            if "access_token" not in account_cols:
                conn.execute("ALTER TABLE email_accounts ADD COLUMN access_token TEXT")
            if "refresh_token" not in account_cols:
                conn.execute("ALTER TABLE email_accounts ADD COLUMN refresh_token TEXT")
            if "token_expiry" not in account_cols:
                conn.execute("ALTER TABLE email_accounts ADD COLUMN token_expiry TEXT")
    finally:
        conn.close()


def _seed_demo_emails_if_empty(force: bool = False) -> None:
    """Seed realistic business and technical communications if inbox is empty."""
    conn = _get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) as cnt FROM email_inbox")
        row = cur.fetchone()
        cnt = row["cnt"] if row else 0

        if cnt == 0 or force:
            samples = [
                (
                    "msg-urgent-01",
                    "marcus.vance@acme-enterprises.com",
                    "URGENT: Q4 SLA Review & Production Incident 409 Resolution",
                    "Hi Tejas,\n\nFollowing up on our sev-1 outage yesterday, our leadership "
                    "requires an executive post-mortem and SLA credit calculation by 4:00 PM.\n\n"
                    "Could your team summarize root cause and confirm if patches are deployed "
                    "in the staging sandbox? Let me know if you can hop on a sync at 2:30 PM.\n\n"
                    "Regards,\nMarcus Vance\nDirector of Operations, Acme Corp",
                    "urgent",
                    "high",
                    0,
                    "<div style='font-family:sans-serif;color:#1e293b;line-height:1.6;'>"
                    "<p>Hi Tejas,</p>"
                    "<p>Following up on sev-1 outage, leadership requires post-mortem "
                    "and SLA credit calculation by <strong>4:00 PM today</strong>.</p>"
                    "<p>Could your team confirm if engineering patches are deployed?</p>"
                    "<hr style='border:none;border-top:1px solid #e2e8f0;margin:20px 0;'>"
                    "<p style='color:#64748b;font-size:13px;'>Regards,<br>"
                    "<strong style='color:#0f172a;'>Marcus Vance</strong><br>"
                    "Director of Operations, Acme Corp</p></div>",
                ),
                (
                    "msg-budget-02",
                    "clara.finch@globalfinance.internal",
                    "Action Required: Sign-off for Cloud GPU Compute Budget ($4,200/mo)",
                    "Hello Team,\n\nThe revised cloud compute budget for local orchestration "
                    "is ready for formal sign-off. Monthly allocation increases to $4,200.\n\n"
                    "We need your department head approval to release purchase orders. "
                    "Please reply confirming approval by end of day Wednesday.\n\n"
                    "Thanks,\nClara Finch\nFinancial Controller",
                    "action",
                    "high",
                    0,
                    "<div style='font-family:sans-serif;color:#1e293b;line-height:1.6;'>"
                    "<p>Hello Team,</p>"
                    "<p>The revised cloud compute budget is ready for formal sign-off. "
                    "Monthly allocation increases to <strong>$4,200</strong>.</p>"
                    "<p>We need your department approval to release purchase orders.</p>"
                    "<hr style='border:none;border-top:1px solid #e2e8f0;margin:20px 0;'>"
                    "<p style='color:#64748b;font-size:13px;'>Thanks,<br>"
                    "<strong style='color:#0f172a;'>Clara Finch</strong><br>"
                    "Financial Controller</p></div>",
                ),
                (
                    "msg-product-03",
                    "elena.rostova@techinnovate.io",
                    "Follow-up: Qwen2.5:3b Local LLM Benchmark Results & Next Steps",
                    "Hi Tejas,\n\nWe completed latency benchmarking with the 3B model on "
                    "16GB non-GPU hardware. Execution speed averaged 32 tokens/second with "
                    "under 4GB RAM utilization. Everything looks great for offline deployment!\n\n"
                    "Could you send over the updated API endpoints to test the UI?\n\n"
                    "Best,\nElena Rostova",
                    "inbox",
                    "normal",
                    1,
                    "<div style='font-family:sans-serif;color:#1e293b;line-height:1.6;'>"
                    "<p>Hi Tejas,</p>"
                    "<p>We completed latency benchmarking on 16GB non-GPU hardware. "
                    "Speed averaged <strong>32 tokens/second</strong>.</p>"
                    "<p>Could you send over updated API endpoints?</p>"
                    "<hr style='border:none;border-top:1px solid #e2e8f0;margin:20px 0;'>"
                    "<p style='color:#64748b;font-size:13px;'>Best,<br>"
                    "<strong style='color:#0f172a;'>Elena Rostova</strong></p></div>",
                ),
                (
                    "msg-sec-04",
                    "security-alerts@infosec-hub.corp",
                    "Notice: Annual Sandboxed Directory Authorization Review",
                    "All engineering personnel are requested to review local sandbox workspace "
                    "permissions before Friday.\n\n"
                    "Verify that all CLI directories have strict read/write authorization gates "
                    "and credential masking enabled.\n\nInfosec Security Team",
                    "inbox",
                    "low",
                    1,
                    "<div style='font-family:sans-serif;color:#1e293b;line-height:1.6;'>"
                    "<p>All engineering personnel are requested to review sandbox workspace "
                    "permissions before Friday.</p>"
                    "<p>Verify that CLI directories have authorization gates enabled.</p>"
                    "<hr style='border:none;border-top:1px solid #e2e8f0;margin:20px 0;'>"
                    "<p style='color:#64748b;font-size:13px;'>Infosec Security Team</p></div>",
                ),
            ]
            with conn:
                if force:
                    conn.execute("DELETE FROM email_inbox WHERE id NOT LIKE 'msg-%'")
                for item in samples:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO email_inbox
                        (id, sender, subject, body, category, priority,
                         is_read, raw_html, received_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now', '-1 hours'))
                        """,
                        item,
                    )
    finally:
        conn.close()


def _sanitize_email_body(body: str) -> str:
    """Mask credentials and sensitive tokens from email contents."""
    body = re.sub(
        r"(?i)(password|secret|token)\s*[:=]\s*['\"]?(\S+)['\"]?", r"\1: [REDACTED]", body
    )
    body = re.sub(r"gsk_[a-zA-Z0-9]{20,}", "[REDACTED_GROQ_KEY]", body)
    body = re.sub(r"sk-[a-zA-Z0-9]{20,}", "[REDACTED_KEY]", body)
    return body


def _clean_email_disclaimers(text: str) -> str:
    """Strip legal boilerplate signatures, confidentiality notices, and disclaimers."""
    if not text:
        return ""
    patterns = [
        r"(?i)\n\s*--\s*\n.*",
        r"(?i)\n\s*_{3,}\s*\n.*",
        r"(?i)\*{3,}\s*disclaimer\s*\*{3,}.*",
        r"(?i)the information contained in this (?:electronic )?communication is intended solely.*",
        r"(?i)this (?:e-?mail|message|communication) (?:and any attachments )?is confidential.*",
        r"(?i)confidentiality notice:?.*",
    ]
    cleaned = text
    for pat in patterns:
        cleaned = re.split(pat, cleaned, maxsplit=1, flags=re.DOTALL)[0]
    return cleaned.strip()


def email_search(
    query: str = "", category: str = "all", max_results: int = 25, sender: str = ""
) -> dict[str, Any]:
    """Search emails by query, sender, and category filter (LOW risk)."""
    _ensure_email_tables()
    acc = email_get_account()
    if acc.get("account_type") == "demo":
        conn_check = _get_db_connection()
        try:
            cur_chk = conn_check.cursor()
            cur_chk.execute("SELECT COUNT(*) as cnt FROM email_inbox WHERE id NOT LIKE 'msg-%'")
            has_personal = cur_chk.fetchone()["cnt"] > 0
            cur_chk.execute("SELECT COUNT(*) as cnt FROM email_inbox WHERE id LIKE 'msg-%'")
            demo_cnt = cur_chk.fetchone()["cnt"]
            if has_personal or demo_cnt == 0:
                with conn_check:
                    conn_check.execute("DELETE FROM email_inbox WHERE id NOT LIKE 'msg-%'")
                _seed_demo_emails_if_empty(force=True)
        finally:
            conn_check.close()
    else:
        _seed_demo_emails_if_empty(force=False)
    conn = _get_db_connection()
    try:
        cur = conn.cursor()
        conditions = []
        params: list[Any] = []

        if sender.strip():
            sender_pattern = f"%{sender.strip()}%"
            conditions.append("sender LIKE ?")
            params.append(sender_pattern)

        if query.strip():
            search_pattern = f"%{query.strip()}%"
            conditions.append("(sender LIKE ? OR subject LIKE ? OR body LIKE ?)")
            params.extend([search_pattern, search_pattern, search_pattern])

        if category and category.lower() != "all":
            if category.lower() == "unread":
                conditions.append("is_read = 0")
            elif category.lower() == "urgent":
                conditions.append("(category = 'urgent' OR priority = 'high')")
            elif category.lower() == "action":
                conditions.append("(category = 'action' OR priority = 'high')")
            else:
                conditions.append("category = ?")
                params.append(category.lower())

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"""
            SELECT id, sender, subject, body, received_at, category, priority, is_read, raw_html
            FROM email_inbox
            {where_clause}
            ORDER BY received_at DESC LIMIT ?
        """
        params.append(max_results)

        cur.execute(sql, tuple(params))
        rows = []
        for r in cur.fetchall():
            d = dict(r)
            d["body_preview"] = (d.get("body") or "")[:110].replace("\n", " ").strip()
            rows.append(d)

        return {
            "success": True,
            "query": query,
            "category": category,
            "count": len(rows),
            "messages": rows,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "status": "EXECUTION_FAILURE",
        }
    finally:
        conn.close()


def email_read(message_id: str = "latest") -> dict[str, Any]:
    """Read full email message body with credential redaction (LOW risk)."""
    _ensure_email_tables()
    _seed_demo_emails_if_empty(force=False)
    conn = _get_db_connection()
    try:
        cur = conn.cursor()
        if not message_id or str(message_id).lower().strip() in ("latest", "recent"):
            cur.execute(
                """
                SELECT id, sender, subject, body, received_at, category,
                       priority, is_read, summary, raw_html
                FROM email_inbox ORDER BY received_at DESC LIMIT 1
                """
            )
        else:
            cur.execute(
                """
                SELECT id, sender, subject, body, received_at, category,
                       priority, is_read, summary, raw_html
                FROM email_inbox WHERE id = ?
                """,
                (message_id,),
            )
        row = cur.fetchone()
        if not row:
            return {
                "success": False,
                "error": f"Email message '{message_id}' not found.",
                "status": "NOT_FOUND",
            }

        data = dict(row)
        data["body"] = _sanitize_email_body(data["body"])
        if data.get("raw_html"):
            data["raw_html"] = _sanitize_email_body(data["raw_html"])

        # Mark read
        with conn:
            conn.execute("UPDATE email_inbox SET is_read = 1 WHERE id = ?", (data["id"],))
        data["is_read"] = 1

        return {
            "success": True,
            "message": data,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "status": "EXECUTION_FAILURE",
        }
    finally:
        conn.close()


def email_mark_all_read() -> dict[str, Any]:
    """Mark all inbox emails as read."""
    _ensure_email_tables()
    conn = _get_db_connection()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute("UPDATE email_inbox SET is_read = 1 WHERE is_read = 0")
            count = cur.rowcount
        return {"success": True, "marked_count": count}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        conn.close()


def email_summarize(message_id: str) -> dict[str, Any]:
    """Generate an AI executive summary and action items for an email."""
    _ensure_email_tables()
    conn = _get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, sender, subject, body, summary FROM email_inbox WHERE id = ?",
            (message_id,),
        )
        row = cur.fetchone()
        if not row:
            return {"success": False, "error": f"Email '{message_id}' not found."}

        # Cached summary check (ignore stale summaries corrupted by legal disclaimer boilerplate)
        if row["summary"] and len(row["summary"].strip()) > 10:
            cached_sum = row["summary"]
            if not any(
                bad in cached_sum.lower()
                for bad in ["privileged information", "dissemination", "retransmission", "bmsit"]
            ):
                return {
                    "success": True,
                    "message_id": message_id,
                    "summary": cached_sum,
                    "cached": True,
                }

        sender = row["sender"]
        subject = row["subject"]
        body = _sanitize_email_body(row["body"])
        clean_body = _clean_email_disclaimers(body) or body

        prompt = (
            "You are an AI Executive Email Assistant. Provide a concise summary of this email.\n"
            "Format your response cleanly with:\n"
            "- Executive Summary (1-2 sentences)\n"
            "- Key Takeaways (2 bullet points)\n"
            "- Action Items (explicit next steps or 'None')\n"
            "- Urgency Level: (High, Medium, or Low)\n\n"
            f"From: {sender}\nSubject: {subject}\nBody:\n{clean_body}"
        )

        summary_content = ""
        try:
            from app.llm import get_chat_model

            model = get_chat_model()
            res = model.invoke(prompt)
            summary_content = res.content.strip()
        except Exception:
            lines = [ln.strip() for ln in clean_body.split("\n") if ln.strip()]

            # Avoid single greeting words like "Hi" as the whole executive summary
            meaningful_lines = [
                ln
                for ln in lines
                if len(ln.split()) > 2
                and not ln.lower().startswith(("hi ", "hello ", "dear ", "hey "))
            ]
            first_line = (
                meaningful_lines[0]
                if meaningful_lines
                else (lines[0] if lines else f"Communication regarding {subject}.")
            )

            actions = [
                ln
                for ln in meaningful_lines
                if any(
                    w in ln.lower()
                    for w in [
                        "please",
                        "need",
                        "confirm",
                        "review",
                        "approve",
                        "call",
                        "urgent",
                        "test",
                        "check",
                    ]
                )
            ]
            action_desc = (
                actions[0] if actions else "None (Acknowledge receipt and follow up as needed)."
            )
            core_intent = (
                lines[1]
                if len(lines) > 1 and lines[1] != first_line
                else (meaningful_lines[0] if meaningful_lines else "Information update")
            )

            is_high = any(
                w in subject.lower()
                for w in ["urgent", "hacked", "security alert", "critical"]
            )
            summary_content = (
                f"Executive Summary: {first_line}\n\n"
                "Key Takeaways:\n"
                f"- Message from {sender} concerning {subject}.\n"
                f"- Core intent: {core_intent}.\n\n"
                f"Action Items: {action_desc}\n"
                f"Urgency Level: {'High' if is_high else 'Medium'}"
            )

        with conn:
            conn.execute(
                "UPDATE email_inbox SET summary = ? WHERE id = ?", (summary_content, message_id)
            )

        return {
            "success": True,
            "message_id": message_id,
            "summary": summary_content,
            "cached": False,
        }
    finally:
        conn.close()


def _extract_display_name_and_email(sender_raw: str) -> tuple[str, str]:
    """Extract display name and email address from an RFC header or raw email."""
    if not sender_raw:
        return ("there", "")

    sender_clean = sender_raw.strip()
    match = re.search(r"<([^>]+)>", sender_clean)
    email = match.group(1).strip() if match else ""

    if "<" in sender_clean:
        display = sender_clean.split("<")[0].strip().strip("\"'")
        display = re.sub(
            r"\b(CSE|ISE|ECE|EEE|MECH|CIVIL|AIML)-\d+\b", "", display, flags=re.IGNORECASE
        ).strip()
        display = re.sub(r"\s+", " ", display).strip()
        if display:
            return (display, email or sender_clean)

    if not email:
        email = sender_clean

    user_part = email.split("@")[0].strip()
    if re.search(r"^\d+[a-z0-9]+$", user_part, re.IGNORECASE):
        return ("there", email)

    cleaned_name = re.sub(r"[._\-]+", " ", user_part).strip().title()
    return (cleaned_name or "there", email)


def email_generate_reply(
    message_id: str, tone: str = "professional", user_notes: str = ""
) -> dict[str, Any]:
    """Generate an AI reply draft for an email with customized tone."""
    _ensure_email_tables()
    conn = _get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, sender, subject, body FROM email_inbox WHERE id = ?",
            (message_id,),
        )
        row = cur.fetchone()
        if not row:
            return {"success": False, "error": f"Email '{message_id}' not found."}

        sender = row["sender"]
        subject = row["subject"]
        reply_subject = subject if subject.lower().startswith("re:") else f"Re: {subject}"
        body = _sanitize_email_body(row["body"])
        sender_name, to_address = _extract_display_name_and_email(sender)

        prompt = (
            f"You are drafting an email reply as Tejas.\n"
            f"Original Sender: {sender_name} <{to_address}>\n"
            f"Original Subject: {subject}\n"
            f"Original Message:\n{body}\n\n"
            f"Desired Tone: {tone}\n"
            f"User Guidance / Intent: {user_notes or 'Draft a contextually appropriate reply.'}\n\n"
            "Guidelines:\n"
            f"- Open with a natural greeting: 'Hi {sender_name},'\n"
            "- Write a natural response addressing the message directly.\n"
            "- Do NOT repeat user prompt instructions verbatim.\n"
            "- Sign off with 'Best regards,\nTejas' (or 'Thanks,\nTejas' for concise tone).\n"
            "- Output plain text without markdown fences."
        )

        reply_body = ""
        try:
            from app.llm import get_chat_model

            model = get_chat_model()
            res = model.invoke(prompt)
            reply_body = res.content.strip()
        except Exception:
            instruction = (user_notes or "").strip()
            instruction_lower = instruction.lower()

            if "decline" in tone.lower() or "decline" in instruction_lower:
                body_message = (
                    f"Thank you for reaching out regarding {subject}.\n\n"
                    "At this moment, we are unable to proceed due to scheduling constraints. "
                    "We appreciate your understanding."
                )
            elif "concise" in tone.lower():
                if "acknowledge" in instruction_lower:
                    body_message = (
                        "Thank you for the update. I acknowledge receipt and will review it."
                    )
                elif "approve" in instruction_lower or "confirm" in instruction_lower:
                    body_message = (
                        "Thank you for the details. This is confirmed and approved to proceed."
                    )
                elif "detail" in instruction_lower or "ask" in instruction_lower:
                    body_message = (
                        "Thank you for reaching out. Could you please share more specific details?"
                    )
                elif instruction:
                    body_message = instruction
                else:
                    body_message = (
                        f"Thank you for the update regarding {subject}. Noted and acknowledged."
                    )
            else:
                if "acknowledge" in instruction_lower:
                    body_message = (
                        "Thank you for reaching out. I have acknowledged receipt of your message "
                        "and will review the details. I will keep you updated on next steps."
                    )
                elif "approve" in instruction_lower or "confirm" in instruction_lower:
                    body_message = (
                        "Thank you for the update. Everything looks good from my side, "
                        "and this is confirmed to proceed."
                    )
                elif "detail" in instruction_lower or "ask" in instruction_lower:
                    body_message = (
                        "Thank you for your message. Could you please provide additional "
                        "details and context so we can address this?"
                    )
                elif instruction:
                    body_message = f"Thank you for update regarding {subject}.\n\n{instruction}"
                else:
                    body_message = (
                        f"Thank you for the update regarding {subject}.\n\n"
                        "I have reviewed the information provided and am aligned with next steps. "
                        "Please let me know if you need anything further."
                    )

            closing = "Thanks,\nTejas" if "concise" in tone.lower() else "Best regards,\nTejas"
            reply_body = f"Hi {sender_name},\n\n{body_message}\n\n{closing}"

        return {
            "success": True,
            "to": to_address or sender,
            "subject": reply_subject,
            "body": reply_body,
            "tone": tone,
        }
    finally:
        conn.close()


def _decode_mime_header(header_value: Optional[str]) -> str:
    """Safely decode MIME encoded-word headers (RFC 2047) to unicode strings."""
    if not header_value:
        return ""
    try:
        decoded_parts = decode_header(header_value)
        result = []
        for content, encoding in decoded_parts:
            if isinstance(content, bytes):
                enc = encoding or "utf-8"
                try:
                    result.append(content.decode(enc, errors="replace"))
                except Exception:
                    result.append(content.decode("latin-1", errors="replace"))
            else:
                result.append(str(content))
        return "".join(result).strip()
    except Exception:
        return str(header_value).strip()


def _extract_body_and_html(msg: Any) -> tuple[str, str]:
    """Extract plain text and sanitized HTML body from an email Message."""
    plain_body = ""
    raw_html = ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            cdisp = str(part.get("Content-Disposition") or "")
            if "attachment" in cdisp:
                continue
            if ctype == "text/plain" and not plain_body:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    try:
                        plain_body = payload.decode(charset, errors="replace")
                    except Exception:
                        plain_body = payload.decode("latin-1", errors="replace")
            elif ctype == "text/html" and not raw_html:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    try:
                        raw_html = payload.decode(charset, errors="replace")
                    except Exception:
                        raw_html = payload.decode("latin-1", errors="replace")
    else:
        ctype = msg.get_content_type()
        payload = msg.get_payload(decode=True)
        text_content = ""
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            try:
                text_content = payload.decode(charset, errors="replace")
            except Exception:
                text_content = payload.decode("latin-1", errors="replace")
        else:
            text_content = str(msg.get_payload() or "")

        if ctype == "text/html":
            raw_html = text_content
        else:
            plain_body = text_content

    if not plain_body and raw_html:
        clean_html = re.sub(r"<!--[\s\S]*?-->", " ", raw_html)
        clean_html = re.sub(r"<!\[if[\s\S]*?<!\[endif\]>", " ", clean_html)
        clean_html = re.sub(r"<style[\s\S]*?</style>", " ", clean_html, flags=re.IGNORECASE)
        clean_html = re.sub(r"<script[\s\S]*?</script>", " ", clean_html, flags=re.IGNORECASE)
        plain_body = re.sub(r"<[^>]+>", " ", clean_html)
        plain_body = re.sub(r"\s+", " ", plain_body).strip()

    # Sanitize raw_html by removing script tags and dangerous inline JS
    if raw_html:
        raw_html = re.sub(r"<script[\s\S]*?</script>", "", raw_html, flags=re.IGNORECASE)
        raw_html = re.sub(r"on\w+\s*=\s*['\"].*?['\"]", "", raw_html, flags=re.IGNORECASE)

    return plain_body.strip(), raw_html.strip()


def _extract_body(msg: Any) -> str:
    """Extract plain text body from an email Message."""
    plain, _ = _extract_body_and_html(msg)
    return plain


def _sync_imap_emails(account: dict[str, Any]) -> dict[str, Any]:
    """Fetch recent messages via IMAP and populate the email_inbox table."""
    host = account.get("imap_host") or ""
    email_addr = account.get("email") or ""
    if not host and "@gmail.com" in email_addr:
        host = "imap.gmail.com"
    port = int(account.get("imap_port") or 993)
    username = account.get("username") or email_addr
    password = account.get("password") or ""

    if not password:
        return {
            "success": False,
            "error": (
                "No password provided for IMAP. Please re-link with your "
                "16-character Google App Password."
            ),
        }

    try:
        mail = imaplib.IMAP4_SSL(host, port, timeout=12)
        mail.login(username, password)
        status, _ = mail.select("INBOX", readonly=True)
        if status != "OK":
            mail.logout()
            return {"success": False, "error": f"Failed to select INBOX: {status}"}

        status, search_data = mail.search(None, "ALL")
        if status != "OK" or not search_data or not search_data[0]:
            mail.close()
            mail.logout()
            return {"success": True, "count": 0, "messages": []}

        msg_nums = search_data[0].split()
        # Fetch the latest 25 emails
        recent_nums = msg_nums[-25:]
        recent_nums.reverse()

        new_messages = []
        for num in recent_nums:
            status, fetch_data = mail.fetch(num, "(RFC822)")
            if status != "OK" or not fetch_data:
                continue

            raw_bytes = None
            for part in fetch_data:
                if isinstance(part, tuple):
                    raw_bytes = part[1]
                    break

            if not raw_bytes:
                continue

            parsed = email.message_from_bytes(raw_bytes)
            num_str = num.decode("utf-8", errors="ignore")
            raw_msg_id = parsed.get("Message-ID") or f"imap-{num_str}"
            clean_id = re.sub(r"[^a-zA-Z0-9_-]", "", raw_msg_id)[:64] or f"imap-{num_str}"

            sender = _decode_mime_header(parsed.get("From")) or "Unknown Sender"
            subject = _decode_mime_header(parsed.get("Subject")) or "(No Subject)"

            date_hdr = parsed.get("Date")
            date_str = datetime.now().isoformat()
            if date_hdr:
                try:
                    pdate = email.utils.parsedate_to_datetime(date_hdr)
                    date_str = pdate.isoformat()
                except Exception:
                    pass

            body, raw_html = _extract_body_and_html(parsed)
            sanitized_body = _sanitize_email_body(body)
            sanitized_html = _sanitize_email_body(raw_html) if raw_html else ""

            text_for_category = (subject + " " + body).lower()
            category = "inbox"
            priority = "normal"
            if any(
                k in text_for_category
                for k in ["urgent", "emergency", "critical", "incident", "asap"]
            ):
                category = "urgent"
                priority = "high"
            elif any(
                k in text_for_category
                for k in [
                    "action required",
                    "action needed",
                    "sign-off",
                    "approval",
                    "review required",
                ]
            ):
                category = "action"
                priority = "high"

            new_messages.append(
                (
                    clean_id,
                    sender,
                    subject,
                    sanitized_body,
                    date_str,
                    category,
                    priority,
                    0,
                    sanitized_html,
                )
            )

        mail.close()
        mail.logout()

        if new_messages:
            conn = _get_db_connection()
            try:
                with conn:
                    # Clear out dummy seed messages when real IMAP messages are successfully fetched
                    conn.execute("DELETE FROM email_inbox WHERE id LIKE 'msg-%'")
                    for msg in new_messages:
                        conn.execute(
                            """
                            INSERT OR REPLACE INTO email_inbox
                            (id, sender, subject, body, received_at,
                             category, priority, is_read, raw_html)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            msg,
                        )
            finally:
                conn.close()

        return {
            "success": True,
            "count": len(new_messages),
            "fetched": len(new_messages),
        }
    except imaplib.IMAP4.error as err:
        err_msg = str(err)
        if (
            "AUTHENTICATIONFAILED" in err_msg
            or "Invalid credentials" in err_msg
            or "Application-specific password" in err_msg
        ):
            return {
                "success": False,
                "error": (
                    "IMAP Authentication Failed. Google requires a 16-character App Password. "
                    "Enable 2-Step Verification, generate an App Password at "
                    "myaccount.google.com/apppasswords, and re-link."
                ),
            }
        return {"success": False, "error": f"IMAP Error: {err_msg}"}
    except Exception as exc:
        return {"success": False, "error": f"Connection Error: {str(exc)}"}


def _refresh_google_token_if_needed(account: dict[str, Any]) -> str:
    """Check if Google OAuth token needs refreshing and refresh it if needed."""
    access_token = account.get("access_token") or ""
    refresh_token = account.get("refresh_token") or ""

    if not refresh_token:
        return access_token

    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        return access_token

    expiry_str = account.get("token_expiry")
    needs_refresh = False
    if expiry_str:
        try:
            expiry_dt = datetime.fromisoformat(expiry_str)
            if datetime.now() >= (expiry_dt - timedelta(minutes=2)):
                needs_refresh = True
        except Exception:
            needs_refresh = False

    if not needs_refresh and access_token:
        return access_token

    try:
        data = urllib.parse.urlencode({
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://oauth2.googleapis.com/token",
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            token_res = json.loads(resp.read().decode("utf-8"))
            new_access_token = token_res.get("access_token")
            expires_in = int(token_res.get("expires_in", 3600))
            new_expiry = (datetime.now() + timedelta(seconds=expires_in)).isoformat()
            if new_access_token:
                conn = _get_db_connection()
                try:
                    with conn:
                        conn.execute(
                            "UPDATE email_accounts SET access_token = ?, token_expiry = ? WHERE id = ?",
                            (new_access_token, new_expiry, account.get("id")),
                        )
                finally:
                    conn.close()
                return new_access_token
    except Exception:
        pass

    return access_token


def _decode_gmail_body_part(part: dict[str, Any]) -> tuple[str, str]:
    """Recursively extract plain and html body from a Gmail payload part."""
    plain = ""
    html = ""
    mime_type = part.get("mimeType", "")
    body_data = part.get("body", {}).get("data", "")
    if body_data:
        try:
            padded = body_data + "=" * (-len(body_data) % 4)
            decoded = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8", errors="replace")
            if "text/html" in mime_type:
                html = decoded
            elif "text/plain" in mime_type:
                plain = decoded
        except Exception:
            pass

    for subpart in part.get("parts", []):
        p_sub, h_sub = _decode_gmail_body_part(subpart)
        if p_sub and not plain:
            plain = p_sub
        if h_sub and not html:
            html = h_sub

    return plain, html


def _sync_gmail_api_emails(account: dict[str, Any]) -> dict[str, Any]:
    """Fetch recent messages via the Google Gmail REST API using OAuth token."""
    access_token = _refresh_google_token_if_needed(account)
    if not access_token:
        return {
            "success": False,
            "error": "Google OAuth access token missing. Please sign in with Google again.",
        }

    try:
        list_url = "https://gmail.googleapis.com/gmail/v1/users/me/messages?maxResults=25"
        req = urllib.request.Request(
            list_url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            list_data = json.loads(resp.read().decode("utf-8"))

        msg_stubs = list_data.get("messages", [])
        if not msg_stubs:
            return {"success": True, "count": 0, "messages": []}

        new_messages = []
        for stub in msg_stubs:
            msg_id = stub.get("id")
            if not msg_id:
                continue

            detail_url = f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg_id}?format=full"
            detail_req = urllib.request.Request(
                detail_url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json",
                },
            )
            with urllib.request.urlopen(detail_req, timeout=12) as d_resp:
                msg_detail = json.loads(d_resp.read().decode("utf-8"))

            payload = msg_detail.get("payload", {})
            headers_list = payload.get("headers", [])
            header_map = {h.get("name", "").lower(): h.get("value", "") for h in headers_list}

            sender = header_map.get("from") or "Unknown Sender"
            subject = header_map.get("subject") or "(No Subject)"
            date_raw = header_map.get("date")

            date_str = datetime.now().isoformat()
            if date_raw:
                try:
                    pdate = email.utils.parsedate_to_datetime(date_raw)
                    date_str = pdate.isoformat()
                except Exception:
                    pass

            plain_body, raw_html = _decode_gmail_body_part(payload)
            if not plain_body and not raw_html:
                plain_body = msg_detail.get("snippet", "")

            sanitized_body = _sanitize_email_body(plain_body)
            sanitized_html = _sanitize_email_body(raw_html) if raw_html else ""

            text_for_category = (subject + " " + sanitized_body).lower()
            category = "inbox"
            priority = "normal"
            if any(k in text_for_category for k in ["urgent", "emergency", "critical", "incident", "asap"]):
                category = "urgent"
                priority = "high"
            elif any(k in text_for_category for k in ["action required", "action needed", "sign-off", "approval", "review required"]):
                category = "action"
                priority = "high"

            clean_id = f"gmail-{msg_id}"
            new_messages.append((
                clean_id,
                sender,
                subject,
                sanitized_body,
                date_str,
                category,
                priority,
                0,
                sanitized_html,
            ))

        if new_messages:
            conn = _get_db_connection()
            try:
                with conn:
                    conn.execute("DELETE FROM email_inbox WHERE id LIKE 'msg-%'")
                    for msg in new_messages:
                        conn.execute(
                            """
                            INSERT OR REPLACE INTO email_inbox
                            (id, sender, subject, body, received_at, category, priority, is_read, raw_html)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            msg,
                        )
            finally:
                conn.close()

        return {"success": True, "count": len(new_messages), "fetched": len(new_messages)}
    except urllib.error.HTTPError as err:
        if err.code == 401:
            return {
                "success": False,
                "error": "Google OAuth authorization expired. Please click 'Sign in with Google' again.",
            }
        return {"success": False, "error": f"Gmail API HTTP {err.code}: {err.reason}"}
    except Exception as exc:
        return {"success": False, "error": f"Gmail API Error: {str(exc)}"}


def _send_gmail_api_email(
    account: dict[str, Any], to_address: str, subject: str, body: str
) -> dict[str, Any]:
    """Send an outbound email via the Gmail REST API with an OAuth token."""
    access_token = _refresh_google_token_if_needed(account)
    if not access_token:
        raise ValueError("Google OAuth token missing. Please sign in with Google again.")

    sender_email = account.get("email") or "me"
    msg = MIMEMultipart()
    msg["From"] = sender_email
    msg["To"] = to_address
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    raw_bytes = msg.as_bytes()
    raw_b64 = base64.urlsafe_b64encode(raw_bytes).decode("ascii")

    url = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
    post_data = json.dumps({"raw": raw_b64}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=post_data,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=12) as resp:
        return json.loads(resp.read().decode("utf-8"))


def email_link_google_oauth(
    email_address: str,
    access_token: str,
    refresh_token: str = "",
    expires_in: int = 3600,
) -> dict[str, Any]:
    """Link a Google Account authenticated via Google OAuth 2.0."""
    _ensure_email_tables()
    conn = _get_db_connection()
    try:
        now_dt = datetime.now()
        now_str = now_dt.isoformat()
        expiry_str = (now_dt + timedelta(seconds=expires_in)).isoformat()

        # If refresh_token is omitted on re-login, keep previously saved refresh_token
        if not refresh_token:
            cur = conn.cursor()
            cur.execute(
                "SELECT refresh_token FROM email_accounts WHERE email = ? AND refresh_token IS NOT NULL ORDER BY id DESC LIMIT 1",
                (email_address,),
            )
            r = cur.fetchone()
            if r and r["refresh_token"]:
                refresh_token = r["refresh_token"]

        with conn:
            conn.execute(
                """
                INSERT INTO email_accounts
                (email, account_type, imap_host, is_connected, last_synced, access_token, refresh_token, token_expiry)
                VALUES (?, 'google_oauth', 'Google Cloud OAuth (Gmail API)', 1, ?, ?, ?, ?)
                """,
                (email_address, now_str, access_token, refresh_token, expiry_str),
            )
            conn.execute("DELETE FROM email_inbox WHERE id NOT LIKE 'gmail-%'")

        return {
            "success": True,
            "email": email_address,
            "account_type": "google_oauth",
            "connected": True,
            "message": "Google Account successfully linked via OAuth 2.0.",
        }
    finally:
        conn.close()


def email_get_account() -> dict[str, Any]:
    """Retrieve current connected email account details."""
    _ensure_email_tables()
    conn = _get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, email, account_type, imap_host, is_connected, last_synced, password, access_token, refresh_token, token_expiry
            FROM email_accounts ORDER BY id DESC LIMIT 1
            """
        )
        row = cur.fetchone()
        if row:
            is_oauth = row["account_type"] in ("google_oauth", "google")
            has_password = bool(row["password"] and len(str(row["password"]).strip()) > 0)
            return {
                "success": True,
                "connected": bool(row["is_connected"]),
                "email": row["email"],
                "account_type": row["account_type"],
                "imap_host": "Google Cloud OAuth (Gmail API)" if is_oauth else (row["imap_host"] or "Local Gateway"),
                "last_synced": row["last_synced"],
                "has_password": has_password or is_oauth,
                "is_oauth": is_oauth,
            }
        return {
            "success": True,
            "connected": True,
            "email": "demo.executive@local.ai",
            "account_type": "demo",
            "imap_host": "Sandbox Offline Gateway",
            "last_synced": datetime.now().isoformat(),
            "has_password": True,
            "is_oauth": False,
        }
    finally:
        conn.close()


def email_link_account(
    email_address: str,
    account_type: str = "demo",
    imap_host: str = "",
    imap_port: int = 993,
    smtp_host: str = "",
    smtp_port: int = 587,
    username: str = "",
    password: str = "",
) -> dict[str, Any]:
    """Link or update email account configuration."""
    if not email_address or "@" not in email_address:
        return {
            "success": False,
            "error": f"Invalid email address '{email_address}'.",
            "status": "VALIDATION_FAILURE",
        }

    # Auto-fill provider defaults
    domain = email_address.split("@")[-1].lower() if "@" in email_address else ""
    if not imap_host:
        if domain in ["gmail.com", "googlemail.com"]:
            imap_host = "imap.gmail.com"
        elif domain in ["outlook.com", "hotmail.com", "live.com"]:
            imap_host = "outlook.office365.com"
        elif domain in ["yahoo.com"]:
            imap_host = "imap.mail.yahoo.com"

    if not smtp_host:
        if domain in ["gmail.com", "googlemail.com"]:
            smtp_host = "smtp.gmail.com"
        elif domain in ["outlook.com", "hotmail.com", "live.com"]:
            smtp_host = "smtp.office365.com"
        elif domain in ["yahoo.com"]:
            smtp_host = "smtp.mail.yahoo.com"

    if not username:
        username = email_address

    _ensure_email_tables()
    conn = _get_db_connection()
    try:
        now_str = datetime.now().isoformat()
        with conn:
            conn.execute(
                """
                INSERT INTO email_accounts
                (email, account_type, imap_host, imap_port, smtp_host,
                 smtp_port, username, password, is_connected, last_synced)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    email_address,
                    account_type,
                    imap_host,
                    imap_port,
                    smtp_host,
                    smtp_port,
                    username,
                    password,
                    now_str,
                ),
            )
            if account_type == "demo":
                conn.execute("DELETE FROM email_inbox WHERE id NOT LIKE 'msg-%'")
        if account_type == "demo":
            _seed_demo_emails_if_empty(force=True)
        return {
            "success": True,
            "email": email_address,
            "account_type": account_type,
            "imap_host": imap_host,
            "connected": True,
            "message": "Account successfully linked and verified.",
        }
    finally:
        conn.close()


def email_sync() -> dict[str, Any]:
    """Sync emails and return updated message count."""
    _ensure_email_tables()
    conn = _get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, email, account_type, imap_host, imap_port, smtp_host,
                   smtp_port, username, password, is_connected, access_token, refresh_token, token_expiry
            FROM email_accounts WHERE is_connected = 1 ORDER BY id DESC LIMIT 1
            """
        )
        row = cur.fetchone()
        account = dict(row) if row else None

        now_str = datetime.now().isoformat()
        warning = None

        if account and account.get("account_type") in ("google_oauth", "google"):
            sync_res = _sync_gmail_api_emails(account)
            if not sync_res.get("success"):
                warning = sync_res.get("error")
                _seed_demo_emails_if_empty(force=False)
        elif account and account.get("account_type") == "imap":
            sync_res = _sync_imap_emails(account)
            if not sync_res.get("success"):
                warning = sync_res.get("error")
                _seed_demo_emails_if_empty(force=False)
        else:
            with conn:
                conn.execute("DELETE FROM email_inbox WHERE id NOT LIKE 'msg-%'")
            _seed_demo_emails_if_empty(force=True)

        cur.execute("SELECT COUNT(*) as cnt FROM email_inbox")
        count = cur.fetchone()["cnt"]

        with conn:
            conn.execute(
                "UPDATE email_accounts SET last_synced = ? "
                "WHERE id = (SELECT MAX(id) FROM email_accounts)",
                (now_str,),
            )

        resp: dict[str, Any] = {
            "success": True,
            "count": count,
            "synced_at": now_str,
        }
        if warning:
            resp["warning"] = warning
        return resp
    finally:
        conn.close()


def email_draft(to_address: str, subject: str, body: str) -> dict[str, Any]:
    """Create and stage a local email draft without sending (MEDIUM risk)."""
    if not to_address or "@" not in to_address:
        return {
            "success": False,
            "error": f"Invalid recipient email address: '{to_address}'",
            "status": "VALIDATION_FAILURE",
        }

    _ensure_email_tables()
    conn = _get_db_connection()
    try:
        cur = conn.cursor()
        with conn:
            cur.execute(
                """
                INSERT INTO email_drafts (to_address, subject, body, status)
                VALUES (?, ?, ?, 'DRAFT')
                """,
                (to_address, subject, body),
            )
            draft_id = cur.lastrowid

        return {
            "success": True,
            "draft_id": draft_id,
            "to": to_address,
            "subject": subject,
            "status": "DRAFT_SAVED",
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "status": "EXECUTION_FAILURE",
        }
    finally:
        conn.close()


def email_send(
    to_address: str, subject: str, body: str, draft_id: Optional[int] = None
) -> dict[str, Any]:
    """Dispatch an outbound email (HIGH risk; requires explicit confirmation)."""
    if not to_address or "@" not in to_address:
        return {
            "success": False,
            "error": f"Invalid recipient email address: '{to_address}'",
            "status": "VALIDATION_FAILURE",
        }

    _ensure_email_tables()
    conn = _get_db_connection()
    try:
        now_str = datetime.now().isoformat()

        # Check if connected account has SMTP configured
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, email, account_type, smtp_host, smtp_port, username, password, access_token, refresh_token, token_expiry
            FROM email_accounts WHERE is_connected = 1 ORDER BY id DESC LIMIT 1
            """
        )
        row = cur.fetchone()
        acc = dict(row) if row else None

        if acc and acc.get("account_type") in ("google_oauth", "google"):
            _send_gmail_api_email(acc, to_address, subject, body)
        elif acc and acc.get("account_type") == "imap" and acc.get("password"):
            smtp_host = acc.get("smtp_host") or (
                "smtp.gmail.com" if "@gmail.com" in acc.get("email", "") else ""
            )
            smtp_port = int(acc.get("smtp_port") or 587)
            username = acc.get("username") or acc.get("email")
            password = acc.get("password")

            if smtp_host and username and password:
                msg = MIMEMultipart()
                msg["From"] = username
                msg["To"] = to_address
                msg["Subject"] = subject
                msg.attach(MIMEText(body, "plain"))

                with smtplib.SMTP(smtp_host, smtp_port, timeout=12) as s:
                    s.ehlo()
                    s.starttls()
                    s.ehlo()
                    s.login(username, password)
                    s.send_message(msg)

        with conn:
            if draft_id:
                conn.execute(
                    "UPDATE email_drafts SET status = 'SENT', sent_at = ? WHERE id = ?",
                    (now_str, draft_id),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO email_drafts (to_address, subject, body, status, sent_at)
                    VALUES (?, ?, ?, 'SENT', ?)
                    """,
                    (to_address, subject, body, now_str),
                )

        return {
            "success": True,
            "to": to_address,
            "subject": subject,
            "dispatched_at": now_str,
            "status": "SENT",
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "status": "EXECUTION_FAILURE",
        }
    finally:
        conn.close()
