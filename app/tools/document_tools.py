"""
Document Reading & Summarization Tools (Milestone 8).

Provides safe, workspace-bounded reading and summarization of local
text, markdown, pdf, and docx files with secret redaction and zero file mutation.
"""

import re
from pathlib import Path
from typing import Any

from app.workspaces import Permission, WorkspaceManager


def _redact_secrets(text: str) -> str:
    """Mask common sensitive patterns such as API keys, tokens, and passwords."""
    # Mask JWTs
    text = re.sub(
        r"eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]+", "[REDACTED_JWT]", text
    )
    # Mask standard api keys
    text = re.sub(
        r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"]?([a-zA-Z0-9_\-]{8,})['\"]?",
        r"\1: [REDACTED]",
        text,
    )
    # Mask Groq / OpenAI keys
    text = re.sub(r"gsk_[a-zA-Z0-9]{20,}", "[REDACTED_GROQ_KEY]", text)
    text = re.sub(r"sk-[a-zA-Z0-9]{20,}", "[REDACTED_OPENAI_KEY]", text)
    return text


def _extract_text_from_file(file_path: Path, max_chars: int = 5000) -> str:
    """Extract plain text from supported document types."""
    suffix = file_path.suffix.lower()

    if suffix in (".txt", ".md", ".json", ".csv", ".log", ".py", ".yaml", ".yml"):
        content = file_path.read_text(encoding="utf-8", errors="replace")
        return content[:max_chars]

    if suffix == ".docx":
        try:
            import docx

            doc = docx.Document(str(file_path))
            full_text = [p.text for p in doc.paragraphs if p.text.strip()]
            return "\n".join(full_text)[:max_chars]
        except Exception as e:
            return f"[Error parsing DOCX: {e}]"

    if suffix == ".pdf":
        try:
            # Fallback text extraction for basic PDF if pypdf or PyPDF2 available
            try:
                import pypdf

                reader = pypdf.PdfReader(str(file_path))
                text = "\n".join([page.extract_text() or "" for page in reader.pages[:10]])
                return text[:max_chars]
            except ImportError:
                # Basic binary extraction of visible streams if no pdf library
                data = file_path.read_bytes()
                extracted = re.findall(rb"\(([^\(\)]+)\)\s*Tj", data)
                if extracted:
                    return b" ".join(extracted).decode("ascii", errors="ignore")[:max_chars]
                return "[PDF installed without pypdf; text stream extracted or empty]"
        except Exception as e:
            return f"[Error reading PDF: {e}]"

    # Default fallback
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
        return content[:max_chars]
    except Exception:
        return f"[Unsupported binary document type: {suffix}]"


def read_document(file_path: str, max_chars: int = 4000) -> dict[str, Any]:
    """
    Safely read the text content of a local document within an authorized workspace.
    Redacts sensitive credentials and bounds output length.
    """
    try:
        path = Path(file_path).resolve()
        if not path.exists():
            return {
                "success": False,
                "error": f"File does not exist: {file_path}",
                "status": "NOT_FOUND",
            }
        if path.is_dir():
            return {
                "success": False,
                "error": f"Path is a directory, not a document: {file_path}",
                "status": "NOT_A_FILE",
            }

        # Verify workspace containment & READ permission
        auth_ok, reason, ws = WorkspaceManager.check_workspace_authorization(
            path, Permission.READ.value
        )
        if not auth_ok or not ws:
            return {
                "success": False,
                "error": reason,
                "status": "PERMISSION_DENIED",
            }

        raw_text = _extract_text_from_file(path, max_chars=max_chars)
        sanitized_text = _redact_secrets(raw_text)

        return {
            "success": True,
            "path": str(path),
            "filename": path.name,
            "workspace": ws.name,
            "character_count": len(sanitized_text),
            "content": sanitized_text,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "status": "EXECUTION_FAILURE",
        }


def summarize_document(file_path: str, max_chars: int = 4000) -> dict[str, Any]:
    """
    Read and summarize a document's key themes and metrics without modifying the file.
    """
    read_res = read_document(file_path, max_chars=max_chars)
    if not read_res.get("success"):
        return read_res

    content = read_res.get("content", "")
    lines = [line.strip() for line in content.split("\n") if line.strip()]
    total_words = len(content.split())

    # Generate structural summary points
    key_points = []
    for line in lines[:10]:
        if len(line) > 10 and not line.startswith("["):
            key_points.append(line[:120])
        if len(key_points) >= 4:
            break

    summary_preview = (
        f"Document '{read_res['filename']}' ({total_words} words, {len(lines)} non-empty lines).\n"
        f"Key excerpt: {content[:300]}..."
        if len(content) > 300
        else content
    )

    return {
        "success": True,
        "path": read_res["path"],
        "filename": read_res["filename"],
        "workspace": read_res["workspace"],
        "word_count": total_words,
        "line_count": len(lines),
        "summary": summary_preview,
        "key_points": key_points,
    }
