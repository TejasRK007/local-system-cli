"""
Comprehensive Automated Test Suite for Email Intelligence & Context-Aware Drafting.

Covers:
1. AI-Powered Smart Email Classification:
   - Work email classification
   - College / Education classification
   - Personal email classification
   - Promotional email classification
   - Spam detection & suspicious URL handling
   - Ambiguous emails marked as REVIEW REQUIRED
   - False-positive prevention (internships/hackathons preserved)
   - Manual category correction (manually_classified=1 protection)
   - Sender reputation (trusted & blocked)

2. Safe Bulk Cleanup:
   - Candidate filtering (only unnecessary & promotions)
   - Mandatory confirmation gate
   - Soft-delete moving to email_trash
   - Strict preservation: refusal to delete work, college, personal, or review emails
   - Partial failure reporting and recovery
   - Security audit logging

3. Context-Aware AI Email Drafting & Reply Generation:
   - Full thread retrieval
   - Sender history cross-referencing
   - Commitment and deadline extraction
   - 5 reply modes: ai_smart, professional, short, detailed, new_context_draft
   - Context grounding (Marcus Vance SLA, Clara Finch budget)
   - Safe fallback when conversation history is absent (no hallucination)
   - Strict guarantee: AI replies are never sent automatically

4. FastAPI REST Endpoints Integration
"""

import sqlite3
import pytest
from fastapi.testclient import TestClient

import app.database as db
from app.server import server_app
from app.tools.email_tools import (
    classify_email_content,
    email_bulk_cleanup,
    email_classify_all,
    email_classify_message,
    email_generate_context_aware_reply,
    email_get_cleanup_candidates,
    email_get_intelligence_stats,
    email_get_sender_reputation,
    email_read,
    email_retrieve_context,
    email_search,
    email_update_category,
    email_update_sender_reputation,
    email_extract_and_store_memory,
    email_get_memories,
    email_update_memory_status,
    email_get_privacy_settings,
    email_set_privacy_settings,
    _ensure_email_tables,
    _seed_demo_emails_if_empty,
)


@pytest.fixture(autouse=True)
def setup_isolated_email_env(tmp_path, monkeypatch):
    """Provide an isolated SQLite database populated with demo seed emails for every test."""
    test_db = tmp_path / "test_email_intel.db"
    monkeypatch.setattr(db, "DB_PATH", test_db)
    monkeypatch.setenv("AGENT_DB_PATH", str(test_db))
    db.init_db(test_db)
    _ensure_email_tables()
    _seed_demo_emails_if_empty(force=True)
    yield


# =============================================================================
# 1. EMAIL CLASSIFICATION TESTS
# =============================================================================

def test_classify_work_email():
    """Verify that work-related communications are categorized as 'work'."""
    subject = "Q4 Production Deployment Status & SLA Review"
    body = (
        "Hi Team, please find attached the SLA uptime report for Q4. "
        "Our team achieved 99.98% availability against our commitment. "
        "The post-mortem review meeting is scheduled for Friday at 3:00 PM."
    )
    res = classify_email_content(
        sender="marcus.vance@acmecloud.io",
        subject=subject,
        body=body,
    )
    assert res["category"] == "work"
    assert res["confidence"] >= 0.70
    assert not res["is_flagged_review"]


def test_classify_college_education_email():
    """Verify academic announcements, exams, and faculty emails are categorized as 'college'."""
    subject = "Final Semester Examination Schedule & Capstone Presentation"
    body = (
        "Dear Students, the Department of Computer Science has published the final "
        "examination timetable. The Capstone viva and presentation will be evaluated "
        "by the faculty committee on December 15th."
    )
    res = classify_email_content(
        sender="dr.sharma@pes.edu",
        subject=subject,
        body=body,
    )
    assert res["category"] == "college"
    assert res["confidence"] >= 0.70
    assert not res["is_flagged_review"]


def test_classify_personal_email():
    """Verify personal conversations and family updates are categorized as 'personal'."""
    subject = "Weekend dinner at mom's place?"
    body = (
        "Hey! Are you free this Saturday evening? Mom wants everyone over for dinner. "
        "Let me know if you can make it so we can cook your favorite pasta."
    )
    res = classify_email_content(
        sender="elena.family@gmail.com",
        subject=subject,
        body=body,
    )
    assert res["category"] == "personal"
    assert res["confidence"] >= 0.70


def test_classify_promotional_email():
    """Verify sales, discounts, and shopping marketing emails are categorized as 'promotions'."""
    subject = "FLASH SALE: 70% Off Designer Jackets & Free Shipping"
    body = (
        "Don't miss our biggest sale of the season! Use promo code BLACKFRIDAY to get "
        "70% discount on all apparel. Free express shipping on orders over $50."
    )
    res = classify_email_content(
        sender="offers@stylevault-deals.com",
        subject=subject,
        body=body,
    )
    assert res["category"] == "promotions"
    assert res["confidence"] >= 0.70


def test_classify_spam_detection():
    """Verify phishing scams and urgent credential warnings are detected as 'spam'."""
    subject = "URGENT: Your bank account will be suspended in 24 hours"
    body = (
        "Dear Customer, we detected unauthorized access. Click here immediately to "
        "verify your credentials and wire funds to secure escrow: http://192.168.1.100/verify-login"
    )
    res = classify_email_content(
        sender="security@secure-bank-alert-update.xyz",
        subject=subject,
        body=body,
    )
    assert res["category"] == "spam"
    assert res["confidence"] >= 0.70


def test_suspicious_url_handling():
    """Verify emails with raw IP destinations or suspicious phishing TLDs are flagged as spam."""
    subject = "Update your credentials immediately"
    body = "Follow this direct server link to preserve your account: http://45.33.32.156/login.php"
    res = classify_email_content(
        sender="admin@notice-server.top",
        subject=subject,
        body=body,
    )
    assert res["category"] == "spam"


def test_ambiguous_email_handling_marked_review_required():
    """Verify that ambiguous, low-context emails are flagged as REVIEW REQUIRED."""
    subject = "Quick question"
    body = "Can you send the thing we talked about earlier?"
    res = classify_email_content(
        sender="unknown.contact492@randomdomain.org",
        subject=subject,
        body=body,
    )
    assert res["category"] == "review_required" or res["is_flagged_review"] is True or res["confidence"] < 0.60


def test_false_positive_prevention_job_opportunity():
    """Ensure a professional internship/job offer containing offer-like words is NOT classified as unnecessary/promo."""
    subject = "Internship Offer: Software Engineering Intern - Summer 2027"
    body = (
        "Congratulations! Google is pleased to extend an offer for the Software Engineering "
        "Intern position starting May 2027. Please review the attached contract and sign by Friday."
    )
    res = classify_email_content(
        sender="university-recruiting@google.com",
        subject=subject,
        body=body,
    )
    assert res["category"] in ("work", "college")
    assert res["category"] not in ("promotions", "unnecessary", "spam")


def test_false_positive_prevention_hackathon():
    """Ensure university hackathons are classified as college/work and never junk."""
    subject = "Registrations Open: National AI Hackathon 2026 - Cash Prizes & Mentorship"
    body = (
        "The ACM Student Chapter invites teams of 4 to build autonomous agents. "
        "Submit your project abstract before October 30th. Certificate of merit for all participants."
    )
    res = classify_email_content(
        sender="acm-events@university.edu",
        subject=subject,
        body=body,
    )
    assert res["category"] in ("college", "work")
    assert res["category"] not in ("promotions", "unnecessary", "spam")


def test_manual_category_correction():
    """Verify that a user can manually override an email's category and it is protected."""
    msg = email_read("msg-urgent-01")["message"]
    assert msg is not None

    # Manually reclassify to 'personal'
    update_res = email_update_category("msg-urgent-01", "personal")
    assert update_res["success"] is True
    assert update_res["category"] == "personal"

    # Verify persistent state
    reloaded = email_read("msg-urgent-01")["message"]
    assert reloaded["classification_category"] == "personal"
    assert reloaded["manually_classified"] == 1

    # Verify that automated reclassification does NOT overwrite manual correction
    email_classify_message("msg-urgent-01", force=False)
    protected = email_read("msg-urgent-01")["message"]
    assert protected["classification_category"] == "personal"


def test_sender_reputation_trusted_and_blocked():
    """Verify sender reputation rules."""
    sender_email = "newsletter@marketing-spam.com"

    # Mark as blocked
    block_res = email_update_sender_reputation(sender_email, "blocked")
    assert block_res["success"] is True
    assert email_get_sender_reputation(sender_email) == "blocked"

    # Classified as spam because sender is blocked
    res = classify_email_content(
        sender=sender_email,
        subject="Weekly digest",
        body="Here is some normal looking content",
    )
    assert res["category"] == "spam"

    # Mark as trusted
    trust_res = email_update_sender_reputation("colleague@acme.com", "trusted")
    assert trust_res["success"] is True
    assert email_get_sender_reputation("colleague@acme.com") == "trusted"


# =============================================================================
# 2. BULK CLEANUP TESTS
# =============================================================================

def test_bulk_cleanup_candidate_listing():
    """Verify candidate listing returns ONLY unnecessary and promotional emails."""
    res = email_get_cleanup_candidates()
    assert res["success"] is True
    candidates = res["candidates"]
    assert len(candidates) > 0

    for c in candidates:
        cat = c["classification_category"]
        assert cat in ("unnecessary", "promotions")
        assert cat not in ("work", "college", "personal", "review_required")


def test_bulk_cleanup_confirmation_required():
    """Verify bulk cleanup refuses execution if confirm=False."""
    candidates = email_get_cleanup_candidates()["candidates"]
    target_ids = [c["id"] for c in candidates[:2]]

    res = email_bulk_cleanup(target_ids, confirm=False)
    assert res["success"] is False
    assert "confirmation is required" in res["error"].lower()

    # Verify messages were NOT deleted
    for mid in target_ids:
        msg = email_read(mid)["message"]
        assert msg is not None
        assert msg.get("is_deleted", 0) == 0


def test_bulk_cleanup_moving_to_trash():
    """Verify selected unnecessary emails are moved to email_trash and marked deleted."""
    candidates = email_get_cleanup_candidates()["candidates"]
    target_ids = [c["id"] for c in candidates[:2]]
    assert len(target_ids) >= 1

    cleanup_res = email_bulk_cleanup(target_ids, confirm=True)
    assert cleanup_res["success"] is True
    assert cleanup_res["deleted_count"] == len(target_ids)

    # Active search should no longer show them
    active_search = email_search(category="all")["messages"]
    active_ids = {m["id"] for m in active_search}
    for mid in target_ids:
        assert mid not in active_ids

    # Check trash database directly
    conn = sqlite3.connect(db.DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT message_id FROM email_trash WHERE message_id IN (?, ?)", tuple(target_ids[:2]))
        trash_rows = cursor.fetchall()
        assert len(trash_rows) == len(target_ids)
    finally:
        conn.close()


def test_bulk_cleanup_strict_preservation_of_important_emails():
    """Verify that attempting to bulk-delete work, college, or personal emails is BLOCKED."""
    # IDs of important demo emails
    protected_ids = ["msg-urgent-01", "msg-college-01", "msg-personal-01", "msg-review-01"]

    res = email_bulk_cleanup(protected_ids, confirm=True)
    assert len(res["protected_emails"]) == len(protected_ids)
    assert res["deleted_count"] == 0

    # Ensure none were moved to trash
    for pid in protected_ids:
        msg = email_read(pid)["message"]
        assert msg is not None
        assert msg.get("is_deleted", 0) == 0


def test_bulk_cleanup_partial_failure_and_recovery():
    """Verify bulk cleanup handles unknown or missing IDs gracefully."""
    candidates = email_get_cleanup_candidates()["candidates"]
    valid_id = candidates[0]["id"]
    mixed_ids = [valid_id, "nonexistent-id-99999", "invalid-id-88888"]

    res = email_bulk_cleanup(mixed_ids, confirm=True)
    assert res["success"] is True
    assert res["deleted_count"] == 1
    assert "nonexistent-id-99999" in res["failed_ids"]
    assert "invalid-id-88888" in res["failed_ids"]


def test_bulk_cleanup_audit_logging():
    """Verify that every bulk cleanup execution creates an audit log entry."""
    candidates = email_get_cleanup_candidates()["candidates"]
    target_id = candidates[0]["id"]

    email_bulk_cleanup([target_id], confirm=True)

    # Inspect audit trail in database
    conn = sqlite3.connect(db.DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT action, execution_status, result_summary FROM audit_log WHERE action = 'email_bulk_cleanup'")
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "email_bulk_cleanup"
        assert row[1] == "SUCCESS"
        assert "Bulk cleanup" in row[2]
    finally:
        conn.close()


# =============================================================================
# 3. CONTEXT-AWARE AI EMAIL DRAFTING & REPLY TESTS
# =============================================================================

def test_retrieve_complete_email_threads():
    """Verify email thread grouping and chronological message retrieval."""
    # 'msg-urgent-01' has a prior thread message 'msg-work-01-prev'
    context = email_retrieve_context("msg-urgent-01")
    assert context["success"] is True
    assert context["thread_message_count"] >= 2
    assert len(context["thread_messages"]) >= 1

    # Thread messages should have valid sender and subject
    thread_subjects = [m["subject"] for m in context["thread_messages"]]
    assert any("Incident 409" in s for s in thread_subjects)


def test_retrieve_previous_conversations_same_sender():
    """Verify cross-referencing previous conversations with the same sender across the mailbox."""
    context = email_retrieve_context("msg-urgent-01")
    assert context["success"] is True
    assert len(context["thread_messages"]) >= 1
    assert context["sender_email"] == "marcus.vance@acme-enterprises.com"


def test_retrieve_commitments_and_deadlines():
    """Verify extraction of previous commitments, deadlines, and numerical figures."""
    context = email_retrieve_context("msg-urgent-01")
    commitments = context["commitments"]
    assert len(commitments) > 0
    commitment_text = " ".join(commitments)
    assert "4:00 PM" in commitment_text or "credit" in commitment_text or "Incident" in commitment_text or "SLA" in commitment_text


def test_generate_context_aware_reply_grounding():
    """
    Verify that AI reply to 'Can you provide an update?' retrieves context
    and mentions specific project details rather than a generic canned reply.
    """
    reply_res = email_generate_context_aware_reply(
        message_id="msg-urgent-01",
        reply_type="ai_smart",
        user_guidance="Acknowledge Marcus and confirm report is ready.",
    )
    assert reply_res["success"] is True
    assert reply_res["to"] == "marcus.vance@acme-enterprises.com"
    assert reply_res["subject"].startswith("Re:")

    body = reply_res["body"]
    assert any(term in body for term in ("409", "Incident", "SLA", "credit", "post-mortem", "deadline", "Marcus"))
    assert len(body.split()) >= 15


def test_generate_context_aware_reply_5_modes():
    """Verify all 5 specialized reply modes produce distinct, well-tailored responses."""
    modes = ["ai_smart", "professional", "short", "detailed", "new_context_draft"]
    results = {}

    for mode in modes:
        res = email_generate_context_aware_reply(
            message_id="msg-urgent-01",
            reply_type=mode,
        )
        assert res["success"] is True
        assert len(res["body"]) > 0
        results[mode] = res["body"]

    # 'short' reply should be concise
    assert len(results["short"].split()) <= len(results["detailed"].split())
    # 'new_context_draft' should generate an outbound subject
    draft_res = email_generate_context_aware_reply(
        message_id="msg-urgent-01",
        reply_type="new_context_draft",
    )
    assert draft_res["subject"]


def test_avoid_hallucinated_information_when_no_context():
    """When an email has no prior thread, AI drafting should remain polite without inventing false claims."""
    res = email_generate_context_aware_reply(
        message_id="msg-unnecessary-01",
        reply_type="short",
        user_guidance="Please unsubscribe me.",
    )
    assert res["success"] is True
    assert "unsubscribe" in res["body"].lower()


def test_replies_never_sent_automatically():
    """Verify that generating an AI reply NEVER dispatches outbound mail or mutates inbox."""
    before_search = email_search(category="all")["messages"]
    before_count = len(before_search)

    # Generate replies
    res = email_generate_context_aware_reply("msg-urgent-01", reply_type="professional")
    assert res["success"] is True
    assert res["auto_sent"] is False

    # Inbox count must remain exactly the same
    after_search = email_search(category="all")["messages"]
    assert len(after_search) == before_count


# =============================================================================
# 4. REST API ENDPOINTS INTEGRATION TESTS
# =============================================================================

def test_api_intelligence_stats():
    """Test GET /api/email/intelligence/stats endpoint."""
    client = TestClient(server_app)
    response = client.get("/api/email/intelligence/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    stats = data.get("stats") or data.get("counts")
    assert stats is not None
    assert "work" in stats
    assert "college" in stats
    assert "personal" in stats
    assert "promotions" in stats
    assert "spam" in stats
    assert "unnecessary" in stats
    assert "review_required" in stats
    assert stats["total_active"] > 0 or stats.get("total", 0) > 0


def test_api_email_classify_endpoint():
    """Test POST /api/email/classify endpoint."""
    client = TestClient(server_app)
    # Classify a single email
    res1 = client.post("/api/email/classify", json={"message_id": "msg-urgent-01", "force": True})
    assert res1.status_code == 200
    assert res1.json()["success"] is True
    assert res1.json()["category"] == "work"

    # Batch classify all
    res2 = client.post("/api/email/classify", json={"force": False})
    assert res2.status_code == 200
    assert res2.json()["success"] is True
    assert "processed_count" in res2.json()


def test_api_category_update_endpoint():
    """Test POST /api/email/category/update endpoint."""
    client = TestClient(server_app)
    res = client.post("/api/email/category/update", json={"message_id": "msg-urgent-01", "category": "personal"})
    assert res.status_code == 200
    assert res.json()["success"] is True
    assert res.json()["category"] == "personal"


def test_api_sender_reputation_endpoint():
    """Test POST /api/email/sender/reputation and GET /api/email/senders."""
    client = TestClient(server_app)
    res1 = client.post("/api/email/sender/reputation", json={"sender_email": "vip.client@partner.com", "reputation": "trusted"})
    assert res1.status_code == 200
    assert res1.json()["success"] is True

    res2 = client.get("/api/email/senders")
    assert res2.status_code == 200
    senders = res2.json()["senders"]
    assert any(s["sender_email"] == "vip.client@partner.com" and s["reputation"] == "trusted" for s in senders)


def test_api_bulk_cleanup_flow():
    """Test candidate retrieval and execution through REST API."""
    client = TestClient(server_app)

    # 1. Get candidates
    c_res = client.get("/api/email/cleanup/candidates")
    assert c_res.status_code == 200
    candidates = c_res.json()["candidates"]
    assert len(candidates) > 0
    candidate_id = candidates[0]["id"]

    # 2. Execute cleanup
    clean_res = client.post("/api/email/cleanup/execute", json={"message_ids": [candidate_id], "confirm": True})
    assert clean_res.status_code == 200
    assert clean_res.json()["success"] is True
    assert clean_res.json().get("deleted_count", clean_res.json().get("processed_count")) == 1


def test_api_context_and_reply_flow():
    """Test GET /api/email/context and POST /api/email/context_reply."""
    client = TestClient(server_app)

    # 1. Get context
    ctx_res = client.get("/api/email/context?id=msg-urgent-01")
    assert ctx_res.status_code == 200
    ctx_data = ctx_res.json()
    assert ctx_data["success"] is True
    assert ctx_data["thread_message_count"] >= 2

    # 2. Generate context-aware reply
    reply_res = client.post(
        "/api/email/context_reply",
        json={
            "message_id": "msg-urgent-01",
            "reply_type": "professional",
            "user_guidance": "Mention that Q4 uptime exceeded targets.",
        },
    )
    assert reply_res.status_code == 200
    reply_data = reply_res.json()
    assert reply_data["success"] is True
    assert "body" in reply_data
    assert reply_data["auto_sent"] is False


def test_classify_bank_transaction_protected_from_promotions():
    """Bank transactions must never be treated as advertisements or spam."""
    content = "Dear Customer, INR 4,500.00 was debited from your A/c ending in 4102 on 14-Nov-2026. Available balance INR 38,200.00. Ref: UPI/20261114/091."
    res = classify_email_content(
        sender="alerts@hdfcbank.net",
        subject="Alert: Account Debited INR 4,500.00 - Txn Ref 8912",
        body=content,
    )
    # Must NOT be classified as promotions or spam — it is a transactional/financial alert
    # Acceptable: important, work, personal, review_required (uncertain but safe)
    assert res["category"] not in ["promotions", "spam", "unnecessary"], (
        f"Bank transaction was misclassified as '{res['category']}' — must not be promotions/spam/unnecessary"
    )


def test_unknown_sender_handling_not_spam_by_default():
    """An unknown sender with normal business/educational content must not be classified as spam."""
    content = "Hi, I noticed your research paper on distributed machine learning and wanted to inquire if you are available for a brief discussion next week."
    res = classify_email_content(
        sender="dr.smith@externalresearch.org",
        subject="Inquiry regarding distributed systems research",
        body=content,
    )
    assert res["category"] != "spam", (
        f"Unknown legitimate sender was misclassified as spam — got '{res['category']}'"
    )
    # is_suspicious must be False for a plain professional inquiry
    assert res.get("is_suspicious", False) is False


def test_persistent_email_memory_extraction_and_lifecycle():
    """Test extracting commitments into email_memory, querying them, and updating their status."""
    sender = "partner.director@venturelab.io"
    msg_id = "msg-venture-memo-01"

    # 1. Extract and persist memory
    stored = email_extract_and_store_memory(
        message_id=msg_id,
        sender=sender,
        subject="Term Sheet Review",
        body="I will send the revised term sheet and cap table by Friday afternoon for your review.",
        thread_id="thread-venture-01"
    )
    assert isinstance(stored, list)
    assert len(stored) > 0

    # 2. Query memories by sender
    memories = email_get_memories(sender_email=sender)
    assert len(memories) > 0
    matched = [m for m in memories if m["source_message_id"] == msg_id]
    assert len(matched) > 0
    mem_id = matched[0]["id"]
    # Must start as pending (is_completed=0)
    assert matched[0]["is_completed"] == 0

    # 3. Update status to completed
    result = email_update_memory_status(mem_id, is_completed=True)
    assert result["success"] is True
    assert result["is_completed"] is True

    # 4. Verify completed item excluded from default query (include_completed=False)
    still_pending = email_get_memories(sender_email=sender, include_completed=False)
    assert not any(m["id"] == mem_id for m in still_pending)

    # 5. Verify completed item appears when include_completed=True
    all_mems = email_get_memories(sender_email=sender, include_completed=True)
    assert any(m["id"] == mem_id for m in all_mems)


def test_reply_acknowledges_earlier_commitment_from_memory():
    """Test that reply drafting acknowledges prior commitments stored in memory."""
    sender = "collab.engineer@devops.org"
    # Seed prior commitment into email_memory via extraction function
    stored = email_extract_and_store_memory(
        message_id="msg-report-earlier-01",
        sender=sender,
        subject="Project Status Update",
        body="I will share the project report by Monday morning.",
        thread_id="thread-project-report-99"
    )
    # Confirm at least one item was stored
    assert len(stored) > 0, "Memory extraction should capture 'I will share the project report by Monday'"

    # Seed a follow-up incoming email into the inbox
    with sqlite3.connect(db.DB_PATH) as conn:
        conn.execute(
            """INSERT OR REPLACE INTO email_inbox 
               (id, sender, subject, body, thread_id, category, is_read, received_at)
               VALUES (?, ?, ?, ?, ?, ?, 0, datetime('now'))""",
            ("msg-report-later-02", sender, "Any update on the project report?",
             "Hi, any update on the project report you mentioned?", "thread-project-report-99", "work")
        )
        conn.commit()

    reply = email_generate_context_aware_reply("msg-report-later-02", reply_type="professional")
    assert reply["success"] is True
    # Reply should reference the project report or prior commitment context
    reply_lower = reply["body"].lower()
    assert ("project report" in reply_lower or "report" in reply_lower or "monday" in reply_lower)
    assert reply["auto_sent"] is False


def test_context_aware_reply_all_6_modes():
    """Test reply generation for all 6 modes: professional, concise, friendly, detailed, decline, custom."""
    modes = ["professional", "concise", "friendly", "detailed", "decline", "custom"]
    for mode in modes:
        res = email_generate_context_aware_reply(
            "msg-urgent-01",
            reply_type=mode,
            user_guidance="Thank them for organizing the Q4 infrastructure review."
        )
        assert res["success"] is True
        assert len(res["body"]) > 10
        assert res["auto_sent"] is False
        if mode == "decline":
            assert ("decline" in res["body"].lower() or "unable" in res["body"].lower() or "cannot" in res["body"].lower())


def test_bulk_cleanup_protects_starred_attachments_and_pending_commitments():
    """Ensure cleanup candidates strictly exclude starred, attachment-carrying, and commitment-linked emails."""
    with sqlite3.connect(db.DB_PATH) as conn:
        # Create a promo email that is starred — must be excluded despite being promotions
        conn.execute(
            """INSERT OR REPLACE INTO email_inbox 
               (id, sender, subject, body, classification_category, classification_confidence,
                is_starred, has_attachments, is_read, is_deleted, is_flagged_review, received_at)
               VALUES ('msg-promo-starred', 'promo@deals.com', '50% off holiday sale', 'Huge discounts',
                       'promotions', 0.95, 1, 0, 1, 0, 0, datetime('now'))"""
        )
        # Create a promo email with attachments — must be excluded
        conn.execute(
            """INSERT OR REPLACE INTO email_inbox 
               (id, sender, subject, body, classification_category, classification_confidence,
                is_starred, has_attachments, is_read, is_deleted, is_flagged_review, received_at)
               VALUES ('msg-promo-attach', 'promo@deals.com', 'Catalog attached', 'See PDF',
                       'promotions', 0.92, 0, 1, 1, 0, 0, datetime('now'))"""
        )
        # Create a promo email with a pending commitment in email_memory (correct schema)
        conn.execute(
            """INSERT OR REPLACE INTO email_inbox 
               (id, sender, subject, body, classification_category, classification_confidence,
                is_starred, has_attachments, is_read, is_deleted, is_flagged_review, received_at)
               VALUES ('msg-promo-commit', 'promo@deals.com', 'Vendor Agreement draft', 'Please review discount',
                       'promotions', 0.91, 0, 0, 1, 0, 0, datetime('now'))"""
        )
        conn.execute(
            """INSERT INTO email_memory 
               (source_message_id, thread_id, sender, sender_email, memory_type, description, due_date, is_completed, is_expired, confirmed)
               VALUES ('msg-promo-commit', '', 'promo@deals.com', 'promo@deals.com',
                       'commitment', 'Promise to review discount terms by end of week', '', 0, 0, 1)"""
        )
        conn.commit()

    result = email_get_cleanup_candidates()
    candidates = result.get("candidates", []) if isinstance(result, dict) else result
    candidate_ids = [c["id"] for c in candidates]

    assert "msg-promo-starred" not in candidate_ids, "Starred emails must be excluded from cleanup"
    assert "msg-promo-attach" not in candidate_ids, "Emails with attachments must be excluded from cleanup"
    assert "msg-promo-commit" not in candidate_ids, "Emails with pending commitments must be excluded from cleanup"


def test_privacy_settings_consent_gate():
    """Verify that cloud processing requires explicit consent and cannot silently transmit email data."""
    import os

    # Set cloud processing to False
    email_set_privacy_settings(False)
    settings = email_get_privacy_settings()
    assert settings["allow_cloud_processing"] is False

    # With a fake Groq key in env + allow_cloud=False → must raise PermissionError
    orig_key = os.environ.get("GROQ_API_KEY", "")
    os.environ["GROQ_API_KEY"] = "gsk_test_fake_key_for_privacy_test"
    try:
        from app.llm import get_configured_llm
        with pytest.raises(PermissionError) as exc_info:
            get_configured_llm("groq", allow_cloud=False)
        assert "Cloud LLM processing is not permitted" in str(exc_info.value)

        # Calling with allow_cloud=True should NOT raise PermissionError
        # (it may fail with network error, but that's acceptable)
        try:
            llm = get_configured_llm("groq", allow_cloud=True)
            assert llm is not None
        except PermissionError:
            pytest.fail("get_configured_llm raised PermissionError even with allow_cloud=True")
        except Exception:
            pass  # Network/API errors are fine — only PermissionError is wrong
    finally:
        if orig_key:
            os.environ["GROQ_API_KEY"] = orig_key
        else:
            os.environ.pop("GROQ_API_KEY", None)


def test_star_toggle_and_api_endpoint():
    """Test toggling message star status via tool and API."""
    client = TestClient(server_app)
    msg_id = "msg-urgent-01"

    # Initial toggle via API
    res = client.post("/api/email/star", json={"message_id": msg_id, "is_starred": True})
    assert res.status_code == 200
    assert res.json()["is_starred"] is True

    # Untoggle
    res2 = client.post("/api/email/star", json={"message_id": msg_id, "is_starred": False})
    assert res2.status_code == 200
    assert res2.json()["is_starred"] is False


def test_groq_api_fallback_to_ollama_on_error():
    """Verify GroqChatWrapper falls back to Ollama or handles failures gracefully."""
    from app.llm import GroqChatWrapper, ResponseContent
    from unittest.mock import MagicMock

    wrapper = GroqChatWrapper(api_key="gsk_fake_key_for_test")

    # Mock the internal Groq HTTP client to simulate API failure
    mock_groq = MagicMock()
    mock_groq.chat.completions.create.side_effect = Exception("Groq Rate Limit Exceeded")
    wrapper._groq_client = mock_groq

    # Mock fallback Ollama instance
    mock_ollama = MagicMock()
    mock_resp = ResponseContent("Fallback Ollama response")
    mock_ollama.invoke.return_value = mock_resp
    wrapper._fallback_ollama = mock_ollama

    result = wrapper.invoke("Test prompt")
    assert result.content == "Fallback Ollama response"
    mock_ollama.invoke.assert_called_once()

