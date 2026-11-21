"""
GitHub AI Repository Chat & Grounded Code Retrieval Module (Milestone 9 - Prompt 3).

Provides evidence-grounded, repository-isolated code retrieval and question answering:
1. SQLite FTS5 index of source code chunks with path and line range metadata.
2. Repository and snapshot isolation (never mixes chunks across repos or commits).
3. Secret redaction before indexing and before LLM context injection.
4. Grounded citation generation (exact file paths, line ranges, and short excerpts).
5. Privacy gating: local Ollama preferred; Groq only with explicit cloud consent;
   honest deterministic fallback when offline.
6. Repository-scoped chat history with stale commit SHA detection and warning.
7. Zero code execution guarantee.
"""

import json
import logging
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import app.database as db
from app.tools.github_analyzer import (
    BINARY_EXTENSIONS,
    EXCLUDED_DIRS,
    MAX_TEXT_INSPECT_SIZE,
    redact_secrets,
)

logger = logging.getLogger(__name__)

CHUNK_LINES_SIZE = 60
CHUNK_LINES_OVERLAP = 15


# -----------------------------------------------------------------------------
# Database Schema & Initialization
# -----------------------------------------------------------------------------
def _ensure_chat_tables() -> None:
    """Create chunks, FTS5 virtual table, and chat history tables if not existing."""
    conn = sqlite3.connect(str(db.DB_PATH))
    try:
        # 1. Base table for file chunks
        conn.execute("""
            CREATE TABLE IF NOT EXISTS github_repo_file_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                repo_id INTEGER,
                repo_name TEXT NOT NULL,
                commit_sha TEXT NOT NULL,
                file_path TEXT NOT NULL,
                start_line INTEGER NOT NULL,
                end_line INTEGER NOT NULL,
                content TEXT NOT NULL,
                language TEXT,
                created_at TEXT NOT NULL
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_repo_chunks_lookup ON github_repo_file_chunks(repo_name, commit_sha);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_repo_chunks_repo_id ON github_repo_file_chunks(repo_id);")

        # 2. FTS5 Virtual Table for full-text code search
        try:
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS github_repo_chunks_fts USING fts5(
                    content,
                    file_path,
                    content='github_repo_file_chunks',
                    content_rowid='id',
                    tokenize = 'unicode61'
                );
            """)
        except sqlite3.OperationalError as e:
            logger.warning("FTS5 creation note: %s", e)

        # 3. Chat sessions table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS github_repo_chat_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                repo_id INTEGER,
                repo_name TEXT NOT NULL,
                commit_sha TEXT NOT NULL,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_sessions_repo ON github_repo_chat_sessions(repo_name);")

        # 4. Chat messages table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS github_repo_chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                sources_json TEXT,
                commit_sha TEXT NOT NULL,
                is_stale INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES github_repo_chat_sessions(id) ON DELETE CASCADE
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON github_repo_chat_messages(session_id);")
        conn.commit()
    finally:
        conn.close()


# -----------------------------------------------------------------------------
# File Chunking & Indexing
# -----------------------------------------------------------------------------
def chunk_text_content(
    text: str, file_path: str, max_lines: int = CHUNK_LINES_SIZE, overlap: int = CHUNK_LINES_OVERLAP
) -> List[Dict[str, Any]]:
    """
    Split text into overlapping line ranges with 1-indexed start and end lines.
    All secrets are redacted before chunk creation.
    """
    redacted = redact_secrets(text)
    lines = redacted.splitlines()
    if not lines:
        return []

    chunks: List[Dict[str, Any]] = []
    total_lines = len(lines)
    step = max(1, max_lines - overlap)

    for i in range(0, total_lines, step):
        chunk_lines = lines[i:i + max_lines]
        start_line = i + 1
        end_line = i + len(chunk_lines)
        chunk_text = "\n".join(chunk_lines).strip()
        if chunk_text:
            chunks.append({
                "file_path": file_path,
                "start_line": start_line,
                "end_line": end_line,
                "content": chunk_text,
            })
        if i + max_lines >= total_lines:
            break

    return chunks


def index_repository_text_files(
    repo_root: Path,
    repo_name: str,
    commit_sha: str,
    repo_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Traverse repo_root, chunk eligible text files, and index into SQLite & FTS5.
    Isolates index by repo_name and commit_sha.
    """
    _ensure_chat_tables()
    repo_root = repo_root.resolve()

    # Identify wrapper root directory if present
    top_entries = [p for p in repo_root.iterdir() if not p.name.startswith(".")]
    effective_root = top_entries[0] if (len(top_entries) == 1 and top_entries[0].is_dir()) else repo_root

    conn = sqlite3.connect(str(db.DB_PATH))
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        # Clear any prior chunks for this exact snapshot to ensure idempotency
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM github_repo_file_chunks WHERE repo_name = ? AND commit_sha = ?",
            (repo_name, commit_sha),
        )
        old_ids = [r[0] for r in cur.fetchall()]
        if old_ids:
            cur.execute(
                "DELETE FROM github_repo_file_chunks WHERE repo_name = ? AND commit_sha = ?",
                (repo_name, commit_sha),
            )
            try:
                for oid in old_ids:
                    cur.execute("DELETE FROM github_repo_chunks_fts WHERE rowid = ?", (oid,))
            except Exception:
                pass

        indexed_files_count = 0
        total_chunks_count = 0

        for path in effective_root.rglob("*"):
            if not path.is_file():
                continue

            rel_parts = path.relative_to(effective_root).parts
            if any(p in EXCLUDED_DIRS or p.startswith(".") for p in rel_parts[:-1]):
                continue

            name = path.name
            suffix = path.suffix.lower()

            if suffix in BINARY_EXTENSIONS or name.startswith(".git"):
                continue

            try:
                size = path.stat().st_size
                if size > MAX_TEXT_INSPECT_SIZE:
                    continue
                content = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            rel_path = path.relative_to(effective_root).as_posix()
            chunks = chunk_text_content(content, rel_path)
            if not chunks:
                continue

            indexed_files_count += 1
            for ch in chunks:
                cur.execute(
                    """INSERT INTO github_repo_file_chunks
                       (repo_id, repo_name, commit_sha, file_path, start_line, end_line, content, language, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        repo_id,
                        repo_name,
                        commit_sha,
                        ch["file_path"],
                        ch["start_line"],
                        ch["end_line"],
                        ch["content"],
                        suffix,
                        now,
                    ),
                )
                chunk_id = cur.lastrowid
                try:
                    cur.execute(
                        "INSERT INTO github_repo_chunks_fts(rowid, content, file_path) VALUES (?, ?, ?)",
                        (chunk_id, ch["content"], ch["file_path"]),
                    )
                except Exception as fts_err:
                    logger.debug("FTS insert warning: %s", fts_err)
                total_chunks_count += 1

        conn.commit()
        return {
            "success": True,
            "repo_name": repo_name,
            "commit_sha": commit_sha,
            "indexed_files": indexed_files_count,
            "total_chunks": total_chunks_count,
        }
    finally:
        conn.close()


# -----------------------------------------------------------------------------
# Chunk Retrieval (FTS5 + Lexical + Path Mention Heuristics)
# -----------------------------------------------------------------------------
def build_fts_query(user_query: str) -> str:
    """Extract clean keywords and format an FTS5 MATCH query with OR disjunction."""
    raw_words = re.findall(r"[A-Za-z0-9_]+", user_query)
    stopwords = {
        "a", "an", "the", "and", "or", "to", "in", "is", "of", "for", "with",
        "this", "that", "how", "what", "where", "why", "when", "who", "does",
        "do", "can", "should", "i", "my", "app", "project", "repo", "repository",
        "file", "files", "function", "method", "code", "explain", "tell", "show",
    }
    terms = [w for w in raw_words if len(w) > 1 and w.lower() not in stopwords]
    if not terms:
        terms = [w for w in raw_words if len(w) > 1]
    if not terms:
        return ""
    # Enclose tokens in double quotes for safe FTS5 evaluation
    return " OR ".join(f'"{t}"' for t in terms[:8])


def retrieve_relevant_chunks(
    repo_name: str,
    commit_sha: str,
    user_query: str,
    max_chunks: int = 6,
) -> List[Dict[str, Any]]:
    """
    Retrieve top matching code chunks for repo_name and commit_sha.
    Enforces strict repository and snapshot isolation.
    """
    _ensure_chat_tables()
    conn = sqlite3.connect(str(db.DB_PATH))
    conn.row_factory = sqlite3.Row
    retrieved: List[Dict[str, Any]] = []
    seen_chunk_ids = set()

    try:
        # 1. If query directly names a specific file (e.g. 'main.py' or 'server.py'), pull its chunks first
        file_mentions = re.findall(r"[A-Za-z0-9_./\-]+\.[A-Za-z0-9]+", user_query)
        for fm in file_mentions:
            cur = conn.execute(
                """SELECT id, file_path, start_line, end_line, content
                   FROM github_repo_file_chunks
                   WHERE repo_name = ? AND commit_sha = ? AND file_path LIKE ?
                   ORDER BY start_line ASC LIMIT 3""",
                (repo_name, commit_sha, f"%{fm}"),
            )
            for row in cur.fetchall():
                if row["id"] not in seen_chunk_ids:
                    seen_chunk_ids.add(row["id"])
                    retrieved.append({
                        "id": row["id"],
                        "file_path": row["file_path"],
                        "start_line": row["start_line"],
                        "end_line": row["end_line"],
                        "content": row["content"],
                        "source": "exact_file_match",
                    })

        # 2. FTS5 Full-Text Search
        fts_query = build_fts_query(user_query)
        if fts_query:
            try:
                cur = conn.execute(
                    """SELECT c.id, c.file_path, c.start_line, c.end_line, c.content, f.rank
                       FROM github_repo_file_chunks c
                       JOIN github_repo_chunks_fts f ON c.id = f.rowid
                       WHERE github_repo_chunks_fts MATCH ? AND c.repo_name = ? AND c.commit_sha = ?
                       ORDER BY f.rank ASC
                       LIMIT ?""",
                    (fts_query, repo_name, commit_sha, max_chunks),
                )
                for row in cur.fetchall():
                    if row["id"] not in seen_chunk_ids:
                        seen_chunk_ids.add(row["id"])
                        retrieved.append({
                            "id": row["id"],
                            "file_path": row["file_path"],
                            "start_line": row["start_line"],
                            "end_line": row["end_line"],
                            "content": row["content"],
                            "source": "fts5_match",
                        })
            except Exception as fts_err:
                logger.debug("FTS query failed (%s); using LIKE fallback", fts_err)

        # 3. Fallback LIKE search if FTS returned nothing
        if len(retrieved) < max_chunks:
            keywords = [w for w in re.findall(r"[A-Za-z0-9_]{3,}", user_query) if w.lower() not in {"how", "what", "where", "explain", "does"}]
            for kw in keywords[:3]:
                cur = conn.execute(
                    """SELECT id, file_path, start_line, end_line, content
                       FROM github_repo_file_chunks
                       WHERE repo_name = ? AND commit_sha = ? AND content LIKE ?
                       LIMIT ?""",
                    (repo_name, commit_sha, f"%{kw}%", max_chunks - len(retrieved)),
                )
                for row in cur.fetchall():
                    if row["id"] not in seen_chunk_ids:
                        seen_chunk_ids.add(row["id"])
                        retrieved.append({
                            "id": row["id"],
                            "file_path": row["file_path"],
                            "start_line": row["start_line"],
                            "end_line": row["end_line"],
                            "content": row["content"],
                            "source": "like_match",
                        })
                if len(retrieved) >= max_chunks:
                    break

        return retrieved[:max_chunks]
    finally:
        conn.close()


# -----------------------------------------------------------------------------
# Stale Index Detection
# -----------------------------------------------------------------------------
def check_repository_stale(
    repo_id: Any, indexed_commit: str, repo_name: Optional[str] = None
) -> Tuple[bool, Optional[str]]:
    """
    Check if the repository has newer commits on GitHub than the indexed commit SHA.
    Supports repo_id (int), repo_name (str), or both.
    Returns (is_stale, latest_commit_sha).
    """
    if str(indexed_commit).startswith("snapshot"):
        return False, indexed_commit

    full_name = None
    if isinstance(repo_id, str) and "/" in repo_id:
        full_name = repo_id
    elif repo_name and "/" in repo_name:
        full_name = repo_name

    if not full_name and isinstance(repo_id, int):
        conn = sqlite3.connect(str(db.DB_PATH))
        try:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                "SELECT full_name FROM github_repositories WHERE id = ? AND is_active = 1", (repo_id,)
            )
            row = cur.fetchone()
            if row:
                full_name = row["full_name"]
        finally:
            conn.close()

    if not full_name:
        return False, indexed_commit

    from app.tools.github_tools import _get_authed_headers
    headers = _get_authed_headers() or {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "LocalAgenticAutomation/1.0",
    }
    url = f"https://api.github.com/repos/{full_name}/commits?per_page=1"
    try:
        import urllib.request
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data and isinstance(data, list) and len(data) > 0:
                live_sha = data[0].get("sha", "")
                if live_sha and live_sha != indexed_commit:
                    return True, live_sha
    except Exception:
        pass

    return False, indexed_commit


# -----------------------------------------------------------------------------
# Grounded Q&A Execution
# -----------------------------------------------------------------------------
def execute_repository_chat(
    repo_name: str,
    commit_sha: str,
    question: str,
    session_id: Optional[int] = None,
    repo_id: Optional[int] = None,
    allow_cloud: bool = False,
) -> Dict[str, Any]:
    """
    Execute grounded repository question answering:
    - Verifies index presence.
    - Retrieves top relevant chunks.
    - Pulls high-level repository analysis for architectural context.
    - Synthesizes grounded answer citing file paths and line ranges.
    - Persists user and assistant messages in chat history.
    """
    _ensure_chat_tables()

    # 1. Retrieve analysis metadata
    from app.tools.github_tools import github_get_latest_analysis, github_get_analysis_by_commit
    analysis = None
    if repo_id:
        analysis = github_get_analysis_by_commit(repo_id, commit_sha) or github_get_latest_analysis(repo_id)

    # 2. Retrieve relevant chunks
    chunks = retrieve_relevant_chunks(repo_name, commit_sha, question, max_chunks=6)

    # 3. Format citations list
    citations: List[Dict[str, Any]] = []
    for c in chunks:
        # First 6 lines as excerpt preview
        lines = c["content"].splitlines()[:6]
        excerpt_preview = "\n".join(lines)
        citations.append({
            "path": c["file_path"],
            "file_path": c["file_path"],
            "start_line": c["start_line"],
            "end_line": c["end_line"],
            "excerpt": excerpt_preview,
            "code_snippet": excerpt_preview,
        })

    # 4. Check for stale index
    is_stale, live_sha = check_repository_stale(repo_id, commit_sha)
    stale_warning = (
        f"Repository has newer commits on GitHub ({live_sha[:8]}) than this index ({commit_sha[:8]}). "
        f"Consider re-analyzing the repository for the latest code changes."
        if is_stale else None
    )

    # 5. Build prompt with retrieved evidence
    context_blocks = []
    for c in chunks:
        context_blocks.append(
            f"--- File: {c['file_path']} (Lines {c['start_line']}-{c['end_line']}) ---\n{c['content']}"
        )
    retrieved_context_str = "\n\n".join(context_blocks)

    repo_summary = analysis.get("summary", "") if analysis else ""
    frameworks_str = ", ".join(analysis.get("frameworks", [])) if analysis else ""

    system_persona = f"""You are an expert repository code assistant answering questions about the source code of repository '{repo_name}'.
You MUST strictly ground all answers in the provided file excerpts and repository metadata.

CRITICAL RULES:
1. Cite specific file paths and line ranges for every technical claim (e.g. `app/server.py:L150-L175`).
2. Provide short, exact code excerpts to support your findings where practical.
3. If the retrieved code excerpts do NOT provide sufficient evidence to answer the question, clearly state: "Insufficient evidence in indexed files to answer [question]. The indexed excerpts do not contain [missing detail]."
4. NEVER fabricate or hallucinate file names, functions, endpoints, classes, dependencies, or behavior.
5. Clearly distinguish confirmed code-level facts from inferences or assumptions.
6. Never claim or imply that you executed any repository code or tests. All statements are based purely on static source analysis.
7. Maintain privacy: never repeat any sensitive secrets, passwords, or tokens.
"""

    user_prompt = f"""Repository Overview:
- Summary: {repo_summary}
- Identified Frameworks: {frameworks_str}
- Indexed Commit: {commit_sha}

Retrieved Code Excerpts:
{retrieved_context_str if retrieved_context_str else "[No matching code excerpts found for this query]"}

User Question:
{question}
"""

    # 6. LLM Invocation with Privacy Gating & Deterministic Fallback
    from app.llm import is_ollama_online, OllamaChatWrapper, GroqChatWrapper

    llm_provider = "deterministic-fallback"
    ai_answer = ""

    llm_client = None
    if is_ollama_online():
        llm_provider = "ollama"
        llm_client = OllamaChatWrapper(timeout=25.0)
    elif allow_cloud and os.getenv("GROQ_API_KEY", "").strip():
        llm_provider = "groq"
        llm_client = GroqChatWrapper(timeout=20.0, fallback_to_ollama=False)

    if llm_client:
        try:
            messages = [
                {"role": "system", "content": system_persona},
                {"role": "user", "content": user_prompt},
            ]
            resp = llm_client.invoke(messages)
            ai_answer = str(resp.content).strip()
        except Exception as exc:
            logger.warning("LLM chat invocation failed (%s); using deterministic fallback", type(exc).__name__)
            llm_provider = "deterministic-fallback"

    # Deterministic fallback when LLM is unavailable, offline, or cloud consent denied
    if not ai_answer:
        if not chunks:
            # Check if this is an overview/architecture/run question that can be answered from analysis metadata
            q_lower = question.lower()
            if any(k in q_lower for k in ("architecture", "overview", "summary", "purpose", "what is this")):
                ai_answer = (
                    f"**Repository Overview ({repo_name})**:\n\n"
                    f"{repo_summary or 'No summary recorded.'}\n\n"
                    f"- **Frameworks**: {frameworks_str or 'None detected'}\n"
                    f"- **Indexed Commit**: `{commit_sha[:8]}`"
                )
            elif any(k in q_lower for k in ("run", "install", "how to run", "how do i run", "setup")):
                rinfo = analysis.get("run_instructions", {}) if analysis else {}
                installs = "\n".join(rinfo.get("install", [])) or "None extracted"
                runs = "\n".join(rinfo.get("run", [])) or "None extracted"
                ai_answer = (
                    f"**Run & Installation Instructions**:\n\n"
                    f"**Install**:\n```bash\n{installs}\n```\n\n"
                    f"**Run**:\n```bash\n{runs}\n```\n"
                )
            else:
                ai_answer = (
                    f"Insufficient evidence in indexed files to answer your question regarding '{question}'. "
                    f"No matching functions, classes, or code excerpts were found in the indexed files for commit `{commit_sha[:8]}`."
                )
        else:
            findings = []
            for c in chunks:
                findings.append(
                    f"- Found in [`{c['file_path']}:L{c['start_line']}-L{c['end_line']}`]:\n"
                    f"```\n{c['content'][:300]}\n```"
                )
            ai_answer = (
                f"Based on static analysis of indexed files in `{repo_name}` (commit `{commit_sha[:8]}`):\n\n"
                + "\n\n".join(findings)
                + "\n\n*Note: Derived from static indexed text without code execution.*"
            )

    # 7. Record session & messages in SQLite
    conn = sqlite3.connect(str(db.DB_PATH))
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        cur = conn.cursor()
        if not session_id:
            # Create session
            session_title = question[:40] + ("..." if len(question) > 40 else "")
            cur.execute(
                """INSERT INTO github_repo_chat_sessions
                   (repo_id, repo_name, commit_sha, title, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (repo_id, repo_name, commit_sha, session_title, now, now),
            )
            session_id = cur.lastrowid
        else:
            cur.execute(
                "UPDATE github_repo_chat_sessions SET updated_at = ? WHERE id = ?", (now, session_id)
            )

        # Insert user message
        cur.execute(
            """INSERT INTO github_repo_chat_messages
               (session_id, role, content, sources_json, commit_sha, is_stale, created_at)
               VALUES (?, 'user', ?, '[]', ?, ?, ?)""",
            (session_id, question, commit_sha, 1 if is_stale else 0, now),
        )

        # Insert assistant message
        cur.execute(
            """INSERT INTO github_repo_chat_messages
               (session_id, role, content, sources_json, commit_sha, is_stale, created_at)
               VALUES (?, 'assistant', ?, ?, ?, ?, ?)""",
            (session_id, ai_answer, json.dumps(citations), commit_sha, 1 if is_stale else 0, now),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "success": True,
        "session_id": session_id,
        "repo_name": repo_name,
        "commit_sha": commit_sha,
        "answer": ai_answer,
        "sources": citations,
        "warning": stale_warning,
        "is_stale": is_stale,
        "llm_provider": llm_provider,
        "timestamp": now,
    }


# -----------------------------------------------------------------------------
# Chat History Management (List, Clear, New Session)
# -----------------------------------------------------------------------------
def get_chat_history(
    repo_name: str, session_id: Optional[int] = None, limit: int = 50
) -> Dict[str, Any]:
    """Retrieve chat history messages scoped strictly to repo_name."""
    _ensure_chat_tables()
    conn = sqlite3.connect(str(db.DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        if session_id:
            cur.execute(
                """SELECT m.id, m.session_id, m.role, m.content, m.sources_json, m.commit_sha, m.is_stale, m.created_at
                   FROM github_repo_chat_messages m
                   JOIN github_repo_chat_sessions s ON m.session_id = s.id
                   WHERE s.repo_name = ? AND m.session_id = ?
                   ORDER BY m.id ASC LIMIT ?""",
                (repo_name, session_id, limit),
            )
        else:
            cur.execute(
                """SELECT m.id, m.session_id, m.role, m.content, m.sources_json, m.commit_sha, m.is_stale, m.created_at
                   FROM github_repo_chat_messages m
                   JOIN github_repo_chat_sessions s ON m.session_id = s.id
                   WHERE s.repo_name = ?
                   ORDER BY m.id ASC LIMIT ?""",
                (repo_name, limit),
            )

        messages = []
        for r in cur.fetchall():
            d = dict(r)
            try:
                d["sources"] = json.loads(d["sources_json"]) if d.get("sources_json") else []
            except Exception:
                d["sources"] = []
            d.pop("sources_json", None)
            d["is_stale"] = bool(d["is_stale"])
            messages.append(d)

        return {"success": True, "repo_name": repo_name, "count": len(messages), "messages": messages}
    finally:
        conn.close()


def clear_chat_history(repo_name: str, session_id: Optional[int] = None) -> Dict[str, Any]:
    """Delete chat history scoped to repository or specific session."""
    _ensure_chat_tables()
    conn = sqlite3.connect(str(db.DB_PATH))
    try:
        with conn:
            if session_id:
                conn.execute(
                    """DELETE FROM github_repo_chat_messages
                       WHERE session_id IN (
                           SELECT id FROM github_repo_chat_sessions
                           WHERE id = ? AND repo_name = ?
                       )""",
                    (session_id, repo_name),
                )
                conn.execute(
                    "DELETE FROM github_repo_chat_sessions WHERE id = ? AND repo_name = ?",
                    (session_id, repo_name),
                )
            else:
                conn.execute(
                    """DELETE FROM github_repo_chat_messages
                       WHERE session_id IN (
                           SELECT id FROM github_repo_chat_sessions
                           WHERE repo_name = ?
                       )""",
                    (repo_name,),
                )
                conn.execute(
                    "DELETE FROM github_repo_chat_sessions WHERE repo_name = ?", (repo_name,)
                )
        return {"success": True, "message": f"Chat history cleared for {repo_name}."}
    finally:
        conn.close()


def create_chat_session(
    repo_name: str,
    commit_sha: str,
    title: str = "New Chat",
    repo_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Start a new chat session for a repository."""
    _ensure_chat_tables()
    conn = sqlite3.connect(str(db.DB_PATH))
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with conn:
            cur = conn.execute(
                """INSERT INTO github_repo_chat_sessions
                   (repo_id, repo_name, commit_sha, title, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (repo_id, repo_name, commit_sha, title, now, now),
            )
            session_id = cur.lastrowid
        return {
            "success": True,
            "session_id": session_id,
            "repo_name": repo_name,
            "commit_sha": commit_sha,
            "title": title,
        }
    finally:
        conn.close()


def list_analyzed_repos_for_chat() -> Dict[str, Any]:
    """List all repositories that have been analyzed and are eligible for chat."""
    _ensure_chat_tables()
    conn = sqlite3.connect(str(db.DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            """SELECT a.id as analysis_id, a.repo_id, a.repo_name, a.commit_sha,
                      a.summary, a.frameworks_json, a.created_at,
                      (SELECT COUNT(*) FROM github_repo_file_chunks c
                       WHERE c.repo_name = a.repo_name AND c.commit_sha = a.commit_sha) as chunks_count
               FROM github_repo_analyses a
               WHERE a.status = 'completed'
               ORDER BY a.id DESC"""
        )
        repos = []
        seen = set()
        for r in cur.fetchall():
            rn = r["repo_name"]
            if rn in seen:
                continue
            seen.add(rn)
            d = dict(r)
            try:
                d["frameworks"] = json.loads(d["frameworks_json"]) if d.get("frameworks_json") else []
            except Exception:
                d["frameworks"] = []
            d.pop("frameworks_json", None)
            d["is_indexed"] = d["chunks_count"] > 0
            repos.append(d)
        return {"success": True, "count": len(repos), "repositories": repos}
    finally:
        conn.close()
