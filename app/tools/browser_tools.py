"""
Controlled Browser Automation & Web Inspection Tools (Milestone 8).

Provides safe web page text extraction, web query simulation, and
secure file downloading confined strictly into authorized workspaces.
"""

import html
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from app.workspaces import WorkspaceManager


def _clean_html_to_text(html_content: str) -> str:
    """Extract plain readable text from HTML markup without executing scripts."""
    # Remove script and style tags
    cleaned = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html_content)
    # Replace standard break/paragraph tags with newlines
    cleaned = re.sub(r"(?i)<(br|p|div|h[1-6]|li)[\s/>]", "\n", cleaned)
    # Strip remaining HTML tags
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    # Decode HTML entities
    cleaned = html.unescape(cleaned)
    # Normalize multiple whitespace
    lines = [re.sub(r"\s+", " ", line).strip() for line in cleaned.split("\n")]
    return "\n".join([line for line in lines if line])


def browser_fetch_page(url: str, max_chars: int = 4000) -> dict[str, Any]:
    """
    Safely fetch and extract readable text content from a web page URL.
    Zero JavaScript execution or raw shell invocation.
    """
    try:
        parsed = urllib.parse.urlparse(url)
        if not parsed.scheme or parsed.scheme not in ("http", "https"):
            err_msg = f"Invalid URL scheme '{parsed.scheme}'. Only http and https are permitted."
            return {
                "success": False,
                "error": err_msg,
                "status": "POLICY_VIOLATION",
            }

        headers = {"User-Agent": "LocalAgenticAutomation/1.0 (Python; Desktop Automation Agent)"}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            content_type = resp.headers.get_content_type()
            raw_data = resp.read(1024 * 512)  # Limit 512 KB
            charset = resp.headers.get_content_charset() or "utf-8"
            decoded = raw_data.decode(charset, errors="replace")

        # Extract title
        title_match = re.search(r"(?i)<title>(.*?)</title>", decoded)
        title = title_match.group(1).strip() if title_match else url

        cleaned_text = _clean_html_to_text(decoded)[:max_chars]

        return {
            "success": True,
            "url": url,
            "title": title,
            "content_type": content_type,
            "length": len(cleaned_text),
            "content": cleaned_text,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "status": "EXECUTION_FAILURE",
        }


def browser_search(query: str, max_results: int = 5) -> dict[str, Any]:
    """
    Structured web search endpoint returning query results for agent reasoning.
    """
    if not query or not query.strip():
        return {
            "success": False,
            "error": "Query cannot be empty",
            "status": "VALIDATION_FAILURE",
        }

    # Structured search representation
    simulated_results = [
        {
            "title": f"Search result for '{query}'",
            "url": f"https://duckduckgo.com/html/?q={urllib.parse.quote_plus(query)}",
            "snippet": f"Web query regarding {query}. Grounded search parameter.",
        }
    ]
    return {
        "success": True,
        "query": query,
        "results_count": len(simulated_results),
        "results": simulated_results[:max_results],
    }


def browser_download_file(url: str, dest_workspace: str, filename: str) -> dict[str, Any]:
    """
    Download a remote resource strictly into an authorized, writable workspace.
    Verifies destination workspace permissions and physically confirms written file.
    """
    try:
        ws = WorkspaceManager.get_workspace_by_name(dest_workspace)
        if not ws:
            return {
                "success": False,
                "error": f"Workspace not found: '{dest_workspace}'",
                "status": "WORKSPACE_NOT_FOUND",
            }
        if not ws.enabled:
            return {
                "success": False,
                "error": f"Workspace '{dest_workspace}' is disabled",
                "status": "PERMISSION_DENIED",
            }
        if "WRITE" not in ws.permissions:
            return {
                "success": False,
                "error": f"Workspace '{dest_workspace}' lacks WRITE permission",
                "status": "PERMISSION_DENIED",
            }

        # Validate filename safety (no path traversal in filename)
        clean_name = Path(filename).name
        target_path = (ws.canonical_path / clean_name).resolve()

        # Workspace containment
        try:
            target_path.relative_to(ws.canonical_path)
        except ValueError:
            err_msg = (
                f"Destination path '{target_path}' escapes workspace boundary '{ws.canonical_path}'"
            )
            return {
                "success": False,
                "error": err_msg,
                "status": "SECURITY_VIOLATION",
            }

        # Prevent overwrite
        if target_path.exists():
            return {
                "success": False,
                "error": f"Destination file already exists: {target_path}",
                "status": "CONFLICT",
            }

        headers = {"User-Agent": "LocalAgenticAutomation/1.0 (File Download)"}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read(1024 * 1024 * 10)  # 10 MB max cap

        target_path.write_bytes(data)

        # Physical verification
        if not target_path.exists() or target_path.stat().st_size != len(data):
            return {
                "success": False,
                "error": f"Physical verification failed for {target_path}",
                "status": "VERIFICATION_FAILURE",
            }

        return {
            "success": True,
            "url": url,
            "workspace": ws.name,
            "path": str(target_path),
            "bytes_downloaded": len(data),
            "status": "SUCCESS",
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "status": "EXECUTION_FAILURE",
        }
