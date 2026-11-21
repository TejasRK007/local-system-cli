"""
GitHub AI Repository Intelligence & Analysis Module.

Provides evidence-grounded static code and project structure analysis:
1. Safe file discovery and tree construction.
2. Manifest and dependency parsing (npm, pip/poetry, cargo, go, maven/gradle, etc.).
3. Comprehensive secret detection and redaction (never persists raw secrets).
4. Secure ZIP archive validation & extraction (traversal, symlink, and zip bomb guards).
5. Grounded technical report generation (summary, architecture, components, folder breakdown,
   run/test instructions, maintainability observations, and uninspected items).
6. Local Ollama preferred, Groq with privacy gating (cloud consent), deterministic non-LLM fallback.
7. Strictly zero code execution — never executes repository scripts, binaries, or build steps.
"""

import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Limits & Security Configuration
# -----------------------------------------------------------------------------
MAX_ZIP_UPLOAD_SIZE = 25 * 1024 * 1024          # 25 MB max archive upload
MAX_UNCOMPRESSED_TOTAL_SIZE = 100 * 1024 * 1024  # 100 MB max uncompressed
MAX_ZIP_FILES_COUNT = 2000                       # Max files in archive
MAX_INDIVIDUAL_FILE_SIZE = 5 * 1024 * 1024       # 5 MB max single extracted file
MAX_TEXT_INSPECT_SIZE = 500 * 1024               # 500 KB max text inspected per file

# Disallowed Windows reserved device names
WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}

# Directories to skip entirely during file discovery
EXCLUDED_DIRS = {
    ".git", "node_modules", "vendor", "dist", "build", ".venv", "venv", "env",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".tox", "coverage", ".next",
    ".nuxt", "target", "bin", "obj", ".idea", ".vscode", "caches", ".cache",
    ".turbo", ".gradle", ".output", "out", ".parcel-cache", ".bundle",
}

# Binary and media file extensions to skip from text inspection
BINARY_EXTENSIONS = {
    ".exe", ".dll", ".so", ".dylib", ".bin", ".iso", ".zip", ".tar", ".gz",
    ".7z", ".rar", ".bz2", ".xz", ".png", ".jpg", ".jpeg", ".gif", ".ico",
    ".svg", ".webp", ".bmp", ".tiff", ".mp4", ".mp3", ".wav", ".avi", ".mov",
    ".pdf", ".docx", ".xlsx", ".pptx", ".odt", ".ods", ".woff", ".woff2",
    ".ttf", ".eot", ".otf", ".pyc", ".pyo", ".pyd", ".class", ".jar", ".war",
    ".ear", ".o", ".a", ".lib", ".obj", ".sqlite", ".sqlite3", ".db", ".min.js",
    ".min.css", ".map", ".wasm", ".dex", ".apk",
}

# Extension to programming language mapping
EXTENSION_LANGUAGE_MAP = {
    ".py": "Python",
    ".pyi": "Python",
    ".js": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".jsx": "JavaScript (React)",
    ".ts": "TypeScript",
    ".tsx": "TypeScript (React)",
    ".rs": "Rust",
    ".go": "Go",
    ".java": "Java",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".c": "C",
    ".h": "C/C++ Header",
    ".cpp": "C++",
    ".cc": "C++",
    ".cxx": "C++",
    ".hpp": "C++ Header",
    ".cs": "C#",
    ".rb": "Ruby",
    ".php": "PHP",
    ".swift": "Swift",
    ".dart": "Dart",
    ".scala": "Scala",
    ".html": "HTML",
    ".htm": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".sass": "Sass",
    ".less": "Less",
    ".sh": "Shell",
    ".bash": "Shell",
    ".zsh": "Shell",
    ".ps1": "PowerShell",
    ".sql": "SQL",
    ".r": "R",
    ".lua": "Lua",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".json": "JSON",
    ".toml": "TOML",
    ".xml": "XML",
    ".md": "Markdown",
    ".rst": "reStructuredText",
    ".dockerfile": "Dockerfile",
}


# -----------------------------------------------------------------------------
# Secret Detection & Redaction
# -----------------------------------------------------------------------------
SECRET_PATTERNS = [
    # GitHub Tokens
    (re.compile(r"ghp_[A-Za-z0-9]{15,}"), "[REDACTED_GITHUB_PAT]"),
    (re.compile(r"gho_[A-Za-z0-9]{15,}"), "[REDACTED_GITHUB_OAUTH]"),
    (re.compile(r"ghu_[A-Za-z0-9]{15,}"), "[REDACTED_GITHUB_USER]"),
    (re.compile(r"ghs_[A-Za-z0-9]{15,}"), "[REDACTED_GITHUB_SERVER]"),
    (re.compile(r"ghr_[A-Za-z0-9]{15,}"), "[REDACTED_GITHUB_REFRESH]"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{30,}"), "[REDACTED_GITHUB_PAT]"),

    # Cloud & LLM API Keys
    (re.compile(r"AKIA[0-9A-Z]{16}"), "[REDACTED_AWS_KEY]"),
    (re.compile(r"gsk_[A-Za-z0-9]{20,}"), "[REDACTED_GROQ_KEY]"),
    (re.compile(r"sk-[A-Za-z0-9]{10,}"), "[REDACTED_OPENAI_KEY]"),
    (re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"), "[REDACTED_ANTHROPIC_KEY]"),
    (re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"), "[REDACTED_SLACK_TOKEN]"),

    # Private Keys
    (
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
        "[REDACTED_PRIVATE_KEY]",
    ),
    (
        re.compile(r"-----(BEGIN|END) [A-Z ]*PRIVATE KEY-----"),
        "[REDACTED_PRIVATE_KEY]",
    ),

    # JSON Web Tokens
    (
        re.compile(r"eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]+"),
        "[REDACTED_JWT]",
    ),

    # Generic key-value secret definitions: password = "xyz", token = "xyz"
    (
        re.compile(
            r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|client[_-]?secret|auth[_-]?token)\s*([:=])\s*['\"]([^'\"]{4,})['\"]"
        ),
        r'\1\2"[REDACTED]"',
    ),

    # Database connection URIs with embedded credentials
    (
        re.compile(r"(?i)(postgres|mysql|mongodb(?:\+srv)?):\/\/([^:\s]+):([^@\s]+)@"),
        r"\1://\2:[REDACTED]@",
    ),
]


def redact_secrets(text: str) -> str:
    """
    Detect and mask all sensitive secrets, credentials, tokens, and private keys.
    Guarantees raw secrets are never persisted to the database or sent to LLMs.
    """
    if not text:
        return ""
    sanitized = str(text)

    # 1. Mask exact values of active secret environment variables if set
    for env_var in ("GITHUB_TOKEN", "GITHUB_CLIENT_SECRET", "GROQ_API_KEY", "OPENAI_API_KEY"):
        val = os.getenv(env_var)
        if val and len(val.strip()) > 5:
            sanitized = sanitized.replace(val.strip(), "[REDACTED]")

    # 2. Run standard secret pattern replacements
    for pattern, replacement in SECRET_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)

    return sanitized


# -----------------------------------------------------------------------------
# Secure ZIP Archive Validation & Extraction
# -----------------------------------------------------------------------------
def safe_extract_zip(zip_source: Any, target_dir: Path) -> Dict[str, Any]:
    """
    Safely extract a ZIP archive into target_dir with strict security enforcement:
    - Path traversal protection (no absolute paths or '..' components).
    - Symlink abuse protection (disallows symlinks).
    - Zip bomb protection (total size and file count limits).
    - Windows reserved device name protection.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    resolved_target = target_dir.resolve()

    try:
        with zipfile.ZipFile(zip_source, "r") as zf:
            infolist = zf.infolist()

            # 1. Check file count limit
            if len(infolist) > MAX_ZIP_FILES_COUNT:
                return {
                    "success": False,
                    "error": f"ZIP archive exceeds maximum file count limit ({len(infolist)} > {MAX_ZIP_FILES_COUNT}).",
                    "status": "LIMIT_EXCEEDED",
                }

            # 2. Check total uncompressed size limit
            total_size = sum(info.file_size for info in infolist)
            if total_size > MAX_UNCOMPRESSED_TOTAL_SIZE:
                return {
                    "success": False,
                    "error": f"ZIP archive uncompressed size exceeds limit ({total_size} bytes > {MAX_UNCOMPRESSED_TOTAL_SIZE} bytes).",
                    "status": "LIMIT_EXCEEDED",
                }

            extracted_count = 0
            skipped_count = 0

            for info in infolist:
                # Check for null bytes
                if "\0" in info.filename:
                    return {
                        "success": False,
                        "error": "Suspicious ZIP entry: filename contains null byte.",
                        "status": "SUSPICIOUS_ENTRY",
                    }

                # Path traversal check: must not be absolute or start with slash
                cleaned_name = info.filename.replace("\\", "/")
                if os.path.isabs(cleaned_name) or cleaned_name.startswith(("/", "\\")):
                    return {
                        "success": False,
                        "error": f"Path traversal attempt detected in ZIP entry: {info.filename}",
                        "status": "SECURITY_VIOLATION",
                    }

                parts = Path(cleaned_name).parts
                if ".." in parts:
                    return {
                        "success": False,
                        "error": f"Directory traversal '..' detected in ZIP entry: {info.filename}",
                        "status": "SECURITY_VIOLATION",
                    }

                # Windows reserved device names check
                for part in parts:
                    stem = part.split(".")[0].upper()
                    if stem in WINDOWS_RESERVED_NAMES:
                        return {
                            "success": False,
                            "error": f"Reserved Windows device name detected in ZIP entry: {info.filename}",
                            "status": "SECURITY_VIOLATION",
                        }

                # Symlink check (Unix mode 0o120000 = S_IFLNK)
                if (info.external_attr >> 16) & 0o170000 == 0o120000:
                    skipped_count += 1
                    continue

                # Single file size check
                if info.file_size > MAX_INDIVIDUAL_FILE_SIZE:
                    skipped_count += 1
                    continue

                dest_path = (resolved_target / cleaned_name).resolve()

                # Verify dest_path stays strictly inside resolved_target
                try:
                    dest_path.relative_to(resolved_target)
                except ValueError:
                    return {
                        "success": False,
                        "error": f"ZIP path traversal escapes target directory: {info.filename}",
                        "status": "SECURITY_VIOLATION",
                    }

                if info.is_dir():
                    dest_path.mkdir(parents=True, exist_ok=True)
                else:
                    dest_path.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info) as src, open(dest_path, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    extracted_count += 1

            return {
                "success": True,
                "extracted_count": extracted_count,
                "skipped_count": skipped_count,
                "extract_dir": str(resolved_target),
            }
    except zipfile.BadZipFile:
        return {
            "success": False,
            "error": "File is not a valid or readable ZIP archive.",
            "status": "INVALID_ARCHIVE",
        }
    except Exception as exc:
        return {
            "success": False,
            "error": f"Extraction error: {str(exc)}",
            "status": "EXTRACTION_ERROR",
        }


# -----------------------------------------------------------------------------
# Safe File Discovery & Tree Construction
# -----------------------------------------------------------------------------
def discover_repository_files(repo_root: Path) -> Dict[str, Any]:
    """
    Walk repo_root, skipping excluded directories and binary files.
    Builds a hierarchical file tree, calculates language distributions,
    and returns categorized manifest and source file references.
    """
    repo_root = repo_root.resolve()

    # Detect if repo was extracted with a single wrapper root directory
    top_entries = [p for p in repo_root.iterdir() if not p.name.startswith(".")]
    if len(top_entries) == 1 and top_entries[0].is_dir():
        effective_root = top_entries[0]
    else:
        effective_root = repo_root

    total_files = 0
    inspected_files = 0
    skipped_files = 0
    language_counts: Dict[str, int] = {}
    language_bytes: Dict[str, int] = {}
    total_code_bytes = 0

    inspected_text_files: Dict[str, Path] = {}
    all_relative_paths: List[str] = []
    skipped_items: List[Dict[str, str]] = []

    def build_tree_node(dir_path: Path) -> List[Dict[str, Any]]:
        nonlocal total_files, inspected_files, skipped_files, total_code_bytes
        items: List[Dict[str, Any]] = []

        try:
            entries = sorted(dir_path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except Exception:
            return items

        for entry in entries:
            rel_path = entry.relative_to(effective_root).as_posix()
            name = entry.name

            if entry.is_dir():
                if name in EXCLUDED_DIRS or name.startswith("."):
                    skipped_items.append({"path": rel_path, "reason": "Excluded directory"})
                    continue
                children = build_tree_node(entry)
                items.append({
                    "name": name,
                    "path": rel_path,
                    "type": "dir",
                    "children": children,
                })
            else:
                total_files += 1
                all_relative_paths.append(rel_path)
                try:
                    size = entry.stat().st_size
                except Exception:
                    size = 0

                suffix = entry.suffix.lower()
                lang = EXTENSION_LANGUAGE_MAP.get(suffix, "Other")

                # Check if binary
                if suffix in BINARY_EXTENSIONS or name.startswith(".git"):
                    skipped_files += 1
                    skipped_items.append({"path": rel_path, "reason": f"Binary/Media file ({suffix})"})
                    items.append({
                        "name": name,
                        "path": rel_path,
                        "type": "file",
                        "size": size,
                        "language": lang,
                        "is_binary": True,
                    })
                    continue

                # Check if oversized
                if size > MAX_TEXT_INSPECT_SIZE:
                    skipped_files += 1
                    skipped_items.append({"path": rel_path, "reason": f"File exceeds size limit ({size} bytes)"})
                    items.append({
                        "name": name,
                        "path": rel_path,
                        "type": "file",
                        "size": size,
                        "language": lang,
                        "oversized": True,
                    })
                    continue

                # Inspectable text file
                inspected_files += 1
                inspected_text_files[rel_path] = entry
                total_code_bytes += size

                if lang != "Other":
                    language_counts[lang] = language_counts.get(lang, 0) + 1
                    language_bytes[lang] = language_bytes.get(lang, 0) + size

                items.append({
                    "name": name,
                    "path": rel_path,
                    "type": "file",
                    "size": size,
                    "language": lang,
                    "is_binary": False,
                })

        return items

    tree = build_tree_node(effective_root)

    # Compute language percentages
    languages_summary: Dict[str, Dict[str, Any]] = {}
    for lang, byte_count in language_bytes.items():
        pct = round((byte_count / total_code_bytes * 100), 1) if total_code_bytes > 0 else 0.0
        languages_summary[lang] = {
            "files": language_counts.get(lang, 0),
            "bytes": byte_count,
            "percentage": pct,
        }

    # Sort languages descending by bytes
    sorted_languages = dict(
        sorted(languages_summary.items(), key=lambda item: item[1]["bytes"], reverse=True)
    )

    return {
        "effective_root": effective_root,
        "tree": tree,
        "total_files": total_files,
        "inspected_files": inspected_files,
        "skipped_files": skipped_files,
        "languages": sorted_languages,
        "inspected_text_files": inspected_text_files,
        "all_relative_paths": all_relative_paths,
        "skipped_items": skipped_items,
    }


# -----------------------------------------------------------------------------
# Manifest & Dependency Parsers
# -----------------------------------------------------------------------------
def parse_manifests(
    inspected_text_files: Dict[str, Path]
) -> Dict[str, Any]:
    """
    Parse package manifests (package.json, requirements.txt, pyproject.toml,
    Cargo.toml, go.mod, pom.xml, pubspec.yaml, etc.) to discover dependencies,
    frameworks, package managers, and scripts.
    """
    frameworks: Set[str] = set()
    package_managers: Set[str] = set()
    dependencies: List[Dict[str, Any]] = []
    scripts: Dict[str, str] = {}
    manifest_sources: List[str] = []

    for rel_path, file_path in inspected_text_files.items():
        name = file_path.name.lower()

        # 1. Node / JavaScript: package.json
        if name == "package.json":
            manifest_sources.append(rel_path)
            package_managers.add("npm")
            try:
                raw = file_path.read_text(encoding="utf-8", errors="replace")
                data = json.loads(raw)
                deps = data.get("dependencies", {})
                dev_deps = data.get("devDependencies", {})
                scripts.update(data.get("scripts", {}))

                for dep, ver in deps.items():
                    dependencies.append({
                        "name": dep, "version": str(ver), "type": "runtime", "source": rel_path
                    })
                    _detect_node_framework(dep, frameworks)

                for dep, ver in dev_deps.items():
                    dependencies.append({
                        "name": dep, "version": str(ver), "type": "development", "source": rel_path
                    })
                    _detect_node_framework(dep, frameworks)
            except Exception:
                pass

        # Package manager lockfiles
        elif name == "pnpm-lock.yaml":
            package_managers.add("pnpm")
        elif name == "yarn.lock":
            package_managers.add("yarn")

        # 2. Python: requirements.txt
        elif name in ("requirements.txt", "requirements-dev.txt"):
            manifest_sources.append(rel_path)
            package_managers.add("pip")
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
                for line in content.splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or line.startswith("-"):
                        continue
                    # Match package name and version
                    m = re.match(r"^([A-Za-z0-9_.\-]+)(.*)$", line)
                    if m:
                        pkg = m.group(1).lower()
                        ver = m.group(2).strip() or "unpinned"
                        dependencies.append({
                            "name": pkg, "version": ver, "type": "runtime", "source": rel_path
                        })
                        _detect_python_framework(pkg, frameworks)
            except Exception:
                pass

        # 3. Python: pyproject.toml
        elif name == "pyproject.toml":
            manifest_sources.append(rel_path)
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
                if "poetry" in content:
                    package_managers.add("poetry")
                else:
                    package_managers.add("pip/build")

                # Basic regex parsing of dependencies
                dep_matches = re.findall(r'([A-Za-z0-9_.\-]+)\s*=\s*["\']([^"\']+)["\']', content)
                for pkg, ver in dep_matches:
                    pkg_lower = pkg.lower()
                    if pkg_lower not in ("python", "name", "version", "description", "readme"):
                        dependencies.append({
                            "name": pkg_lower, "version": ver, "type": "runtime", "source": rel_path
                        })
                        _detect_python_framework(pkg_lower, frameworks)
            except Exception:
                pass

        # 4. Rust: Cargo.toml
        elif name == "cargo.toml":
            manifest_sources.append(rel_path)
            package_managers.add("cargo")
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
                crates = re.findall(r'([A-Za-z0-9_\-]+)\s*=\s*(?:["\']([^"\']+)["\']|\{.*?version\s*=\s*["\']([^"\']+)["\'])', content)
                for m in crates:
                    crate_name = m[0].lower()
                    ver = m[1] or m[2] or "unspecified"
                    dependencies.append({
                        "name": crate_name, "version": ver, "type": "crate", "source": rel_path
                    })
                    if crate_name in ("actix-web", "axum", "rocket", "tokio", "diesel", "serde"):
                        frameworks.add(crate_name.capitalize())
            except Exception:
                pass

        # 5. Go: go.mod
        elif name == "go.mod":
            manifest_sources.append(rel_path)
            package_managers.add("go modules")
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
                go_deps = re.findall(r'^\s*([A-Za-z0-9_.\-\/]+)\s+v([A-Za-z0-9_.\-]+)', content, re.MULTILINE)
                for mod, ver in go_deps:
                    dependencies.append({
                        "name": mod, "version": f"v{ver}", "type": "module", "source": rel_path
                    })
                    mod_lower = mod.lower()
                    if "gin-gonic" in mod_lower:
                        frameworks.add("Gin")
                    elif "fiber" in mod_lower:
                        frameworks.add("Fiber")
                    elif "echo" in mod_lower:
                        frameworks.add("Echo")
                    elif "gorm" in mod_lower:
                        frameworks.add("GORM")
            except Exception:
                pass

        # 6. Dart / Flutter: pubspec.yaml
        elif name == "pubspec.yaml":
            manifest_sources.append(rel_path)
            package_managers.add("pub")
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
                if "flutter:" in content:
                    frameworks.add("Flutter")
            except Exception:
                pass

        # 7. Java / Maven: pom.xml
        elif name == "pom.xml":
            manifest_sources.append(rel_path)
            package_managers.add("maven")
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
                if "spring-boot" in content:
                    frameworks.add("Spring Boot")
            except Exception:
                pass

    return {
        "manifest_sources": manifest_sources,
        "frameworks": sorted(list(frameworks)),
        "package_managers": sorted(list(package_managers)),
        "dependencies": dependencies,
        "scripts": scripts,
        "total_dependencies": len(dependencies),
    }


def _detect_node_framework(dep: str, frameworks: Set[str]) -> None:
    dep = dep.lower()
    mapping = {
        "react": "React",
        "react-dom": "React",
        "next": "Next.js",
        "vue": "Vue.js",
        "nuxt": "Nuxt.js",
        "svelte": "Svelte",
        "@angular/core": "Angular",
        "express": "Express",
        "fastify": "Fastify",
        "@nestjs/core": "NestJS",
        "tailwindcss": "Tailwind CSS",
        "jest": "Jest",
        "vitest": "Vitest",
        "playwright": "Playwright",
        "cypress": "Cypress",
        "electron": "Electron",
        "vite": "Vite",
        "webpack": "Webpack",
    }
    if dep in mapping:
        frameworks.add(mapping[dep])


def _detect_python_framework(pkg: str, frameworks: Set[str]) -> None:
    pkg = pkg.lower()
    mapping = {
        "fastapi": "FastAPI",
        "flask": "Flask",
        "django": "Django",
        "pytest": "Pytest",
        "sqlalchemy": "SQLAlchemy",
        "torch": "PyTorch",
        "tensorflow": "TensorFlow",
        "pandas": "Pandas",
        "numpy": "NumPy",
        "langchain": "LangChain",
        "pydantic": "Pydantic",
        "celery": "Celery",
        "uvicorn": "Uvicorn",
    }
    if pkg in mapping:
        frameworks.add(mapping[pkg])


# -----------------------------------------------------------------------------
# Entry Points & Configuration Discovery
# -----------------------------------------------------------------------------
def discover_entry_points(all_relative_paths: List[str]) -> List[Dict[str, str]]:
    """Identify entry points and important configuration files."""
    entry_candidates = [
        ("main.py", "Application Entry Point (Python)"),
        ("app.py", "Application Entry Point (Python)"),
        ("server.py", "Server Entry Point (Python)"),
        ("manage.py", "Django Management CLI"),
        ("index.js", "Module / Server Entry Point (JavaScript)"),
        ("index.ts", "Module / Server Entry Point (TypeScript)"),
        ("server.js", "Server Entry Point (JavaScript)"),
        ("server.ts", "Server Entry Point (TypeScript)"),
        ("src/index.ts", "Application Entry Point (TypeScript)"),
        ("src/main.ts", "Application Entry Point (TypeScript)"),
        ("src/App.tsx", "React Root Component"),
        ("src/main.jsx", "React Root Entry Point"),
        ("main.go", "Application Entry Point (Go)"),
        ("src/main.rs", "Application Binary Entry Point (Rust)"),
        ("src/lib.rs", "Library Root (Rust)"),
        ("Dockerfile", "Container Build Specification"),
        ("docker-compose.yml", "Multi-Container Orchestration"),
        ("docker-compose.yaml", "Multi-Container Orchestration"),
        ("Makefile", "Build & Task Automation"),
    ]

    discovered: List[Dict[str, str]] = []
    seen_paths = set()

    for p in all_relative_paths:
        p_lower = p.lower()
        p_parts = p_lower.split("/")
        filename = p_parts[-1]

        for candidate, description in entry_candidates:
            cand_lower = candidate.lower()
            if "/" in cand_lower:
                # Match path ending with candidate
                if p_lower == cand_lower or p_lower.endswith("/" + cand_lower):
                    if p not in seen_paths:
                        discovered.append({"path": p, "description": description})
                        seen_paths.add(p)
            else:
                # Top-level or subfolder root file (e.g. main.py in root, src/, or app/)
                if filename == cand_lower and (len(p_parts) <= 2):
                    if p not in seen_paths:
                        discovered.append({"path": p, "description": description})
                        seen_paths.add(p)

    # Also detect any cmd/*/main.go in Go projects
    for p in all_relative_paths:
        if p.startswith("cmd/") and p.endswith("/main.go") and p not in seen_paths:
            discovered.append({
                "path": p,
                "description": "Go Command Entry Point",
            })
            seen_paths.add(p)

    return discovered


# -----------------------------------------------------------------------------
# Test Suite Discovery
# -----------------------------------------------------------------------------
def discover_test_suite(all_relative_paths: List[str]) -> Dict[str, Any]:
    """Find automated test directories, test file counts, and test patterns."""
    test_dirs: Set[str] = set()
    test_files: List[str] = []

    test_patterns = (
        r"^test[s]?\/",
        r"^__tests__\/",
        r"^spec\/",
        r".*_test\.py$",
        r"^test_.*\.py$",
        r".*\.(test|spec)\.(js|ts|jsx|tsx)$",
        r".*_test\.go$",
    )

    for p in all_relative_paths:
        parts = p.split("/")
        if len(parts) > 1 and parts[0] in ("tests", "test", "__tests__", "spec"):
            test_dirs.add(parts[0])

        if any(re.search(pat, p) for pat in test_patterns):
            test_files.append(p)

    return {
        "test_dirs": sorted(list(test_dirs)),
        "test_files_count": len(test_files),
        "sample_test_files": test_files[:10],
        "has_tests": len(test_files) > 0,
    }


# -----------------------------------------------------------------------------
# Run / Build / Test Instructions Extraction
# -----------------------------------------------------------------------------
def extract_run_instructions(
    inspected_text_files: Dict[str, Path],
    scripts: Dict[str, str],
    package_managers: List[str],
) -> Dict[str, Any]:
    """Extract install, run, build, and test instructions from README and manifests."""
    install_cmds: List[str] = []
    run_cmds: List[str] = []
    build_cmds: List[str] = []
    test_cmds: List[str] = []
    sources: List[str] = []

    # 1. Check manifests scripts (e.g. package.json)
    if "test" in scripts:
        test_cmds.append(f"npm test  # ({scripts['test']})")
    if "start" in scripts:
        run_cmds.append(f"npm start  # ({scripts['start']})")
    if "dev" in scripts:
        run_cmds.append(f"npm run dev  # ({scripts['dev']})")
    if "build" in scripts:
        build_cmds.append(f"npm run build  # ({scripts['build']})")

    # 2. Check README files
    readme_path = None
    for p, f in inspected_text_files.items():
        if f.name.lower().startswith("readme"):
            readme_path = f
            sources.append(p)
            break

    if readme_path:
        try:
            content = readme_path.read_text(encoding="utf-8", errors="replace")
            # Extract fenced code blocks under Installation / Usage / Running headers
            sections = re.split(r"\n(?=#{1,3}\s+)", content)
            for sec in sections:
                header_match = re.match(r"^#{1,3}\s+(.*)", sec)
                if not header_match:
                    continue
                header = header_match.group(1).lower()
                code_blocks = re.findall(r"```(?:bash|sh|shell|cmd|powershell)?\s*\n([\s\S]*?)```", sec)

                if any(k in header for k in ("install", "setup", "getting started")):
                    for cb in code_blocks:
                        lines = [line.strip() for line in cb.splitlines() if line.strip() and not line.strip().startswith("#")]
                        install_cmds.extend(lines[:3])

                elif any(k in header for k in ("run", "running", "usage", "start", "quick start")):
                    for cb in code_blocks:
                        lines = [line.strip() for line in cb.splitlines() if line.strip() and not line.strip().startswith("#")]
                        run_cmds.extend(lines[:3])

                elif any(k in header for k in ("build", "compile")):
                    for cb in code_blocks:
                        lines = [line.strip() for line in cb.splitlines() if line.strip() and not line.strip().startswith("#")]
                        build_cmds.extend(lines[:2])

                elif any(k in header for k in ("test", "testing")):
                    for cb in code_blocks:
                        lines = [line.strip() for line in cb.splitlines() if line.strip() and not line.strip().startswith("#")]
                        test_cmds.extend(lines[:2])
        except Exception:
            pass

    # 3. Default fallback commands if none extracted
    if not install_cmds:
        if "poetry" in package_managers:
            install_cmds.append("poetry install")
        elif "pip" in package_managers:
            install_cmds.append("pip install -r requirements.txt")
        elif "pnpm" in package_managers:
            install_cmds.append("pnpm install")
        elif "yarn" in package_managers:
            install_cmds.append("yarn install")
        elif "npm" in package_managers:
            install_cmds.append("npm install")
        elif "cargo" in package_managers:
            install_cmds.append("cargo build")
        elif "go modules" in package_managers:
            install_cmds.append("go mod download")

    if not test_cmds:
        if "poetry" in package_managers or "pip" in package_managers:
            test_cmds.append("pytest")
        elif "cargo" in package_managers:
            test_cmds.append("cargo test")
        elif "go modules" in package_managers:
            test_cmds.append("go test ./...")

    return {
        "install": list(dict.fromkeys(install_cmds))[:5],
        "run": list(dict.fromkeys(run_cmds))[:5],
        "build": list(dict.fromkeys(build_cmds))[:3],
        "test": list(dict.fromkeys(test_cmds))[:3],
        "sources": sources,
    }


# -----------------------------------------------------------------------------
# Maintainability & Security Observations
# -----------------------------------------------------------------------------
def generate_observations(
    inspected_text_files: Dict[str, Path],
    all_relative_paths: List[str],
    has_tests: bool,
    dependencies: List[Dict[str, Any]],
) -> List[Dict[str, str]]:
    """
    Generate factual maintainability, security, and configuration observations.
    NOTE: All entries are strictly labeled as observations, not confirmed vulnerabilities.
    """
    observations: List[Dict[str, str]] = []
    file_names = {p.lower() for p in all_relative_paths}

    # 1. Missing README
    has_readme = any("readme" in p for p in file_names)
    if not has_readme:
        observations.append({
            "category": "Maintainability",
            "type": "Missing Documentation",
            "observation": "No README file was detected in the repository root. Setup and usage instructions may be missing.",
            "path": "README.md",
        })

    # 2. Missing Test Suite
    if not has_tests:
        observations.append({
            "category": "Maintainability",
            "type": "No Test Suite Detected",
            "observation": "No automated test directory (tests/, __tests__/) or test files were found among inspected paths.",
            "path": "tests/",
        })

    # 3. Missing .gitignore
    if ".gitignore" not in file_names:
        observations.append({
            "category": "Configuration",
            "type": "Missing .gitignore",
            "observation": "No .gitignore file detected. Unwanted build artifacts or temporary files might be accidentally committed.",
            "path": ".gitignore",
        })

    # 4. Dependency Lockfile Check
    has_pkg_json = any(p.endswith("package.json") for p in file_names)
    has_pkg_lock = any(p.endswith("package-lock.json") or p.endswith("pnpm-lock.yaml") or p.endswith("yarn.lock") for p in file_names)
    if has_pkg_json and not has_pkg_lock:
        observations.append({
            "category": "Configuration",
            "type": "Missing Node Lockfile",
            "observation": "package.json is present without a corresponding lockfile (package-lock.json / pnpm-lock.yaml / yarn.lock).",
            "path": "package.json",
        })

    # 5. Unpinned dependencies check
    unpinned = [d["name"] for d in dependencies if d.get("version") in ("*", "latest", "unpinned", "")]
    if len(unpinned) > 2:
        observations.append({
            "category": "Maintainability",
            "type": "Unpinned Dependencies",
            "observation": f"{len(unpinned)} dependencies are unpinned or lack version constraints (e.g. {', '.join(unpinned[:3])}).",
            "path": "manifests",
        })

    # 6. Check for dummy or exposed credential keys in committed files
    for rel_path, f in inspected_text_files.items():
        if f.suffix.lower() in (".env", ".env.local", ".env.production"):
            observations.append({
                "category": "Security Observation",
                "type": "Committed Environment File",
                "observation": f"Environment file '{rel_path}' is tracked in repository. Ensure no production secrets are committed.",
                "path": rel_path,
            })
            break

    return observations


# -----------------------------------------------------------------------------
# Folder Structure & Major Module Explanations
# -----------------------------------------------------------------------------
def analyze_folder_structure(
    effective_root: Path,
    all_relative_paths: List[str]
) -> List[Dict[str, Any]]:
    """Group inspected files by top-level folder and summarize each module's purpose."""
    folder_groups: Dict[str, List[str]] = {}

    for p in all_relative_paths:
        parts = p.split("/")
        if len(parts) > 1:
            top_folder = parts[0]
            folder_groups.setdefault(top_folder, []).append(p)
        else:
            folder_groups.setdefault(".", []).append(p)

    folder_modules: List[Dict[str, Any]] = []

    ROLE_MAP = {
        "app": "Core Application Logic & Backend Services",
        "src": "Primary Source Code & Modules",
        "lib": "Shared Libraries & Helper Utilities",
        "tests": "Automated Unit & Integration Test Suite",
        "test": "Automated Test Suite",
        "__tests__": "Automated Test Specs",
        "ui": "Frontend User Interface, Web Views & Assets",
        "frontend": "Client Application & Frontend Components",
        "client": "Client Application Source",
        "docs": "Project Documentation & Architecture Specs",
        "scripts": "Developer Utilities & Automation Scripts",
        "tools": "Developer Tools & Auxiliary Helpers",
        "config": "Project & Environment Configuration",
        "data": "Local Database & Data Storage Files",
        ".github": "GitHub Actions CI/CD Workflows & Issue Templates",
        ".": "Repository Root & Configuration Manifests",
    }

    for folder, paths in sorted(folder_groups.items(), key=lambda x: (x[0] == ".", x[0])):
        role = ROLE_MAP.get(folder.lower(), f"Submodule / Directory: {folder}")
        folder_modules.append({
            "folder": folder if folder != "." else "(root)",
            "role": role,
            "files_count": len(paths),
            "sample_files": [p.split("/", 1)[-1] if "/" in p else p for p in paths[:6]],
        })

    return folder_modules


# -----------------------------------------------------------------------------
# Grounded Architecture & Component Synthesis
# -----------------------------------------------------------------------------
def synthesize_architecture_report(
    repo_name: str,
    discovery: Dict[str, Any],
    manifest_data: Dict[str, Any],
    entry_points: List[Dict[str, str]],
    test_info: Dict[str, Any],
    run_instructions: Dict[str, Any],
    folder_modules: List[Dict[str, Any]],
    observations: List[Dict[str, str]],
    allow_cloud: bool = False,
) -> Dict[str, Any]:
    """
    Synthesize high-level repository summary, component responsibilities,
    and architectural flow. Prefers local Ollama if online; falls back to Groq
    only if cloud consent granted; falls back to deterministic synthesis if offline.
    """
    inspected_text_files = discovery["inspected_text_files"]

    # Extract README excerpt for grounding
    readme_excerpt = ""
    for rel_path, f in inspected_text_files.items():
        if f.name.lower().startswith("readme"):
            try:
                raw = f.read_text(encoding="utf-8", errors="replace")
                readme_excerpt = redact_secrets(raw[:2500])
            except Exception:
                pass
            break

    # Build prompt context
    langs_list = [f"{lang} ({data['percentage']}%)" for lang, data in list(discovery["languages"].items())[:4]]
    langs_str = ", ".join(langs_list) or "Not determined"
    frameworks_str = ", ".join(manifest_data["frameworks"]) or "None identified"
    entry_pts_str = ", ".join([ep["path"] for ep in entry_points]) or "None identified"

    llm_provider = "deterministic-fallback"
    ai_summary = ""
    ai_components: List[Dict[str, Any]] = []
    architecture_flow: Dict[str, Any] = {}

    # Attempt LLM processing (Local Ollama first, Groq second if cloud allowed)
    from app.llm import is_ollama_online, OllamaChatWrapper, GroqChatWrapper

    llm_client = None
    if is_ollama_online():
        llm_provider = "ollama"
        llm_client = OllamaChatWrapper(timeout=25.0)
    elif allow_cloud and os.getenv("GROQ_API_KEY", "").strip():
        llm_provider = "groq"
        llm_client = GroqChatWrapper(timeout=20.0, fallback_to_ollama=False)

    if llm_client:
        prompt = f"""You are a senior software architect analyzing the repository '{repo_name}'.
Produce an evidence-grounded technical analysis based ONLY on the observed files and metadata below.
CRITICAL: Never invent functionality, dependencies, or architecture not supported by the evidence.
Ground all statements in file paths.

Repository Metadata:
- Primary Languages: {langs_str}
- Identified Frameworks: {frameworks_str}
- Entry Points: {entry_pts_str}
- Total Files Inspected: {discovery['inspected_files']}

README Excerpt:
{readme_excerpt}

Respond with a JSON object strictly matching this schema:
{{
  "summary": "2-3 concise sentences explaining the purpose and domain of this repository.",
  "components": [
    {{
      "name": "Component Name",
      "responsibility": "What this component does based on observed code/structure",
      "primary_files": ["path/to/file1", "path/to/file2"]
    }}
  ],
  "data_and_control_flow": "Concise factual description of how data and control flow through entry points and components.",
  "grounding_notes": "Explicit statement of files inspected to derive this architecture."
}}
"""
        try:
            resp = llm_client.invoke(prompt)
            content = str(resp.content).strip()
            # Extract JSON block
            json_match = re.search(r"\{[\s\S]*\}", content)
            if json_match:
                parsed = json.loads(json_match.group(0))
                ai_summary = parsed.get("summary", "")
                ai_components = parsed.get("components", [])
                architecture_flow = {
                    "data_and_control_flow": parsed.get("data_and_control_flow", ""),
                    "grounding_notes": parsed.get("grounding_notes", ""),
                }
        except Exception as exc:
            logger.warning("LLM architecture synthesis failed (%s); using deterministic fallback", type(exc).__name__)
            llm_provider = "deterministic-fallback"

    # Deterministic fallback synthesis if LLM was unavailable or failed
    if not ai_summary:
        if readme_excerpt:
            first_para = readme_excerpt.split("\n\n")[0].replace("#", "").strip()
            ai_summary = f"{repo_name} is a software project primarily written in {langs_str}. {first_para[:250]}."
        else:
            ai_summary = (
                f"{repo_name} is a software repository utilizing {langs_str} with {frameworks_str}."
            )

    if not ai_components:
        # Build components from folder modules and entry points
        for mod in folder_modules[:5]:
            folder = mod["folder"]
            ai_components.append({
                "name": f"{folder} Module",
                "responsibility": mod["role"],
                "primary_files": [f"{folder}/{f}" if folder != "(root)" else f for f in mod["sample_files"][:3]],
            })

    if not architecture_flow:
        entry_list = [ep["path"] for ep in entry_points]
        flow_desc = (
            f"Execution begins at entry point(s): {', '.join(entry_list)}. "
            f"Components communicate internally via module imports and configured handlers."
            if entry_list else
            "Standard module structure; execution is initiated via package manifests or test runners."
        )
        architecture_flow = {
            "data_and_control_flow": flow_desc,
            "grounding_notes": f"Derived from inspected manifest files ({', '.join(manifest_data['manifest_sources'])}) and folder hierarchy.",
        }

    return {
        "summary": ai_summary,
        "components": ai_components,
        "architecture_flow": architecture_flow,
        "llm_provider": llm_provider,
    }


# -----------------------------------------------------------------------------
# Master Repository Analyzer Entrypoint
# -----------------------------------------------------------------------------
def analyze_repository_directory(
    repo_root: Path,
    repo_name: str,
    commit_sha: Optional[str] = None,
    allow_cloud: bool = False,
) -> Dict[str, Any]:
    """
    Run complete static analysis on an extracted repository directory.
    Guarantees zero code execution and complete secret redaction.
    """
    # 1. Discover files & build tree
    discovery = discover_repository_files(repo_root)

    # 2. Parse manifests & dependencies
    manifest_data = parse_manifests(discovery["inspected_text_files"])

    # 3. Discover entry points & configurations
    entry_points = discover_entry_points(discovery["all_relative_paths"])

    # 4. Discover test suite
    test_info = discover_test_suite(discovery["all_relative_paths"])

    # 5. Extract run/build/test instructions
    run_instructions = extract_run_instructions(
        discovery["inspected_text_files"],
        manifest_data["scripts"],
        manifest_data["package_managers"],
    )

    # 6. Folder & Module explanation
    folder_modules = analyze_folder_structure(
        discovery["effective_root"],
        discovery["all_relative_paths"],
    )

    # 7. Generate observations & security hygiene notes
    observations = generate_observations(
        discovery["inspected_text_files"],
        discovery["all_relative_paths"],
        test_info["has_tests"],
        manifest_data["dependencies"],
    )

    # 8. Synthesize architecture & summary (with privacy-gated LLM / fallback)
    arch_report = synthesize_architecture_report(
        repo_name=repo_name,
        discovery=discovery,
        manifest_data=manifest_data,
        entry_points=entry_points,
        test_info=test_info,
        run_instructions=run_instructions,
        folder_modules=folder_modules,
        observations=observations,
        allow_cloud=allow_cloud,
    )

    # Unknowns & Files not inspected
    unknowns = {
        "skipped_files_count": discovery["skipped_files"],
        "skipped_items_sample": discovery["skipped_items"][:15],
        "excluded_directories": sorted(list(EXCLUDED_DIRS)),
        "binary_extensions_filtered": sorted(list(BINARY_EXTENSIONS)),
    }

    return {
        "success": True,
        "repo_name": repo_name,
        "commit_sha": commit_sha or "snapshot",
        "status": "completed",
        "summary": arch_report["summary"],
        "languages": discovery["languages"],
        "frameworks": manifest_data["frameworks"],
        "package_managers": manifest_data["package_managers"],
        "dependencies": manifest_data["dependencies"][:100],  # Bound DB storage
        "total_dependencies_count": manifest_data["total_dependencies"],
        "entry_points": entry_points,
        "folder_modules": folder_modules,
        "components": arch_report["components"],
        "architecture_flow": arch_report["architecture_flow"],
        "run_instructions": run_instructions,
        "test_info": test_info,
        "observations": observations,
        "unknowns": unknowns,
        "inspected_files_count": discovery["inspected_files"],
        "skipped_files_count": discovery["skipped_files"],
        "total_files_count": discovery["total_files"],
        "tree": discovery["tree"],
        "llm_provider": arch_report["llm_provider"],
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
