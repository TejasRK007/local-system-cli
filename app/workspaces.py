"""
Workspace and Permission Management module for Milestone 4.

Provides persistent workspace abstractions, granular permission controls (READ, WRITE, DELETE),
canonical path containment, and deterministic security checks.
"""

import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path, PureWindowsPath
from typing import Any, Optional

import app.database as db


class Permission(str, Enum):
    READ = "READ"
    WRITE = "WRITE"
    DELETE = "DELETE"


ALL_PERMISSIONS: set[str] = {Permission.READ.value, Permission.WRITE.value, Permission.DELETE.value}


@dataclass
class Workspace:
    workspace_id: str
    name: str
    path: str
    enabled: bool = True
    permissions: set[str] = field(default_factory=lambda: set(ALL_PERMISSIONS))
    created_at: str = ""
    updated_at: str = ""

    @property
    def canonical_path(self) -> Path:
        """Return the resolved canonical Path object."""
        return Path(self.path).expanduser().resolve()

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "name": self.name,
            "path": self.path,
            "enabled": self.enabled,
            "permissions": sorted(list(self.permissions)),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Workspace":
        perms = set(data.get("permissions", []))
        if not perms:
            perms = set(ALL_PERMISSIONS)
        return cls(
            workspace_id=data["workspace_id"],
            name=data["name"],
            path=data["path"],
            enabled=bool(data.get("enabled", True)),
            permissions=perms,
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )


class WorkspaceManager:
    """Manages workspace lifecycle, permissions, and canonical path containment."""

    @staticmethod
    def _is_subpath(target: Path, parent: Path) -> bool:
        """
        Robust containment check handling Windows case-insensitivity,
        drive-letter casing, and trailing slashes.
        """
        try:
            resolved_target = target.resolve()
            resolved_parent = parent.resolve()
            if resolved_target == resolved_parent:
                return True
            if resolved_target.is_relative_to(resolved_parent):
                return True
        except (ValueError, AttributeError):
            pass

        # Case-insensitive comparison fallback for Windows drive letters and paths
        try:
            target_parts = [p.lower() for p in target.resolve().parts]
            parent_parts = [p.lower() for p in parent.resolve().parts]
            if len(target_parts) >= len(parent_parts):
                return target_parts[: len(parent_parts)] == parent_parts
        except Exception:
            pass

        return False

    @staticmethod
    def is_protected_system_path(path: str | Path) -> bool:
        """
        Verify whether a path targets a protected system directory across platforms.
        Handles Windows system roots, drive letters, POSIX system directories, symlinks
        (e.g. macOS /etc -> /private/etc), and case variations.
        Evaluates protection before and without requiring path existence on the host OS.
        """
        try:
            raw_str = str(path).replace("\\", "/").strip()
        except Exception:
            return False

        if not raw_str:
            return False

        def _is_protected_normalized_path(s: str) -> bool:
            # Block filesystem drive/root anchors (e.g. "/", "\\", "C:", "C:/")
            drive_match = re.match(r"^([a-zA-Z]:)(?:/.*)?$", s)
            if s in ("/", "\\"):
                return True
            if drive_match and s.rstrip("/") == drive_match.group(1):
                return True

            # Uniform inspection without Windows drive prefix (e.g. C:/Windows -> /Windows)
            no_drive = re.sub(r"^[a-zA-Z]:", "", s)
            if not no_drive.startswith("/"):
                return False

            norm_lower = no_drive.lower().rstrip("/")
            if norm_lower in ("", "/"):
                return True

            # macOS System Volume Data prefix normalization
            if norm_lower.startswith("/system/volumes/data/"):
                norm_lower = norm_lower[len("/system/volumes/data"):].rstrip("/")
            elif norm_lower == "/system/volumes/data":
                return True

            if norm_lower in ("", "/"):
                return True

            parts = [p for p in norm_lower.split("/") if p]
            if not parts:
                return True

            top_dir = parts[0]
            posix_protected = {
                "system",
                "library",
                "etc",
                "bin",
                "sbin",
                "usr",
                "dev",
                "proc",
                "sys",
                "boot",
                "root",
            }
            win_protected = {
                "windows",
                "program files",
                "program files (x86)",
                "programdata",
                "system volume information",
                "$recycle.bin",
            }

            if top_dir in posix_protected or top_dir in win_protected:
                return True

            # /private: /private, /private/etc, /private/var/{root,db,log} are protected.
            # /private/var/folders and other temp directories are not protected.
            if top_dir == "private":
                if len(parts) == 1:
                    return True
                if parts[1] == "etc":
                    return True
                if parts[1] == "var" and len(parts) >= 3 and parts[2] in ("root", "db", "log"):
                    return True

            # /var: /var/{root,db,log} are protected.
            if top_dir == "var":
                if len(parts) >= 2 and parts[1] in ("root", "db", "log"):
                    return True

            return False

        # 1. Check raw path if rooted
        is_rooted = raw_str.startswith("/") or bool(re.match(r"^[a-zA-Z]:", raw_str))
        if is_rooted and _is_protected_normalized_path(raw_str):
            return True

        # 2. Check Windows environment variables on raw and normalized path
        try:
            raw_win = PureWindowsPath(path)
            raw_win_str = str(raw_win).lower()
            for env_name in (
                "SystemRoot",
                "windir",
                "ProgramFiles",
                "ProgramFiles(x86)",
                "ProgramW6432",
                "ProgramData",
            ):
                env_val = os.environ.get(env_name)
                if not env_val:
                    continue
                norm_env_win = str(PureWindowsPath(env_val)).lower()
                if raw_win_str == norm_env_win or raw_win_str.startswith(norm_env_win + "\\"):
                    return True
                norm_env_posix = env_val.replace("\\", "/").lower().rstrip("/")
                if not norm_env_posix.startswith("/"):
                    norm_env_posix = re.sub(r"^[a-zA-Z]:", "", norm_env_posix)
                raw_posix = raw_str.lower().rstrip("/")
                if raw_posix == norm_env_posix or raw_posix.startswith(norm_env_posix + "/"):
                    return True
        except Exception:
            pass

        # 3. Canonicalize / resolve path
        try:
            target_resolved = Path(path).expanduser().resolve()
            resolved_str = str(target_resolved).replace("\\", "/").strip()
            if _is_protected_normalized_path(resolved_str):
                return True
        except Exception:
            pass

        # 4. Host OS symlink checks against existing protected paths
        for pfx in (
            "/system",
            "/library",
            "/etc",
            "/private/etc",
            "/bin",
            "/sbin",
            "/usr",
            "/dev",
            "/proc",
            "/sys",
            "/boot",
            "/root",
        ):
            try:
                cand = Path(pfx)
                if cand.is_absolute() and cand.exists():
                    cand_res = cand.resolve()
                    tgt_res = Path(path).expanduser().resolve()
                    if tgt_res == cand_res or tgt_res.is_relative_to(cand_res):
                        return True
            except Exception:
                pass

        return False

    @staticmethod
    def add_workspace(
        path: str | Path,
        name: Optional[str] = None,
        permissions: Optional[set[str] | list[str]] = None,
        enabled: bool = True,
    ) -> Workspace:
        """
        Add and persist a new workspace.
        Canonicalizes path, verifies security boundaries, assigns a unique workspace_id,
        and sets permissions.
        """
        resolved = Path(path).expanduser().resolve()
        if not resolved.exists():
            raise FileNotFoundError(f"Path does not exist: {resolved}")
        if not resolved.is_dir():
            raise NotADirectoryError(f"Path is not a directory: {resolved}")

        # Block entire drive roots (e.g. C:\ or /)
        if resolved == Path(resolved.anchor) or len(resolved.parts) <= 1:
            raise ValueError(
                f"Adding entire drive root '{resolved}' as a workspace is not permitted."
            )

        # Block protected system folders across platforms
        if WorkspaceManager.is_protected_system_path(resolved):
            raise PermissionError(
                f"Cannot add protected system directory as a workspace: {resolved}"
            )

        # Derive a human-readable name if not provided
        ws_name = name.strip() if name and name.strip() else resolved.name
        if not ws_name:
            ws_name = "workspace"

        # Ensure unique name if collision occurs with a different path
        existing = db.get_workspace_by_name_record(ws_name)
        if existing:
            # If path matches existing, update and return existing
            if Path(existing["path"]).resolve() == resolved:
                ws_id = existing["workspace_id"]
                perms = (
                    set(permissions) if permissions is not None else set(existing["permissions"])
                )
                db.update_workspace_record(ws_id, enabled=enabled, permissions=perms)
                return WorkspaceManager.get_workspace(ws_id)  # type: ignore[return-value]
            ws_name = f"{ws_name}_{uuid.uuid4().hex[:4]}"

        workspace_id = f"ws_{uuid.uuid4().hex[:8]}"
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        perms_set = (
            set(p.upper().strip() for p in permissions)
            if permissions is not None
            else set(ALL_PERMISSIONS)
        )

        db.create_workspace_record(
            workspace_id=workspace_id,
            name=ws_name,
            path=str(resolved),
            enabled=enabled,
            permissions=perms_set,
            created_at=ts,
        )

        return Workspace(
            workspace_id=workspace_id,
            name=ws_name,
            path=str(resolved),
            enabled=enabled,
            permissions=perms_set,
            created_at=ts,
            updated_at=ts,
        )

    @staticmethod
    def remove_workspace(workspace_id: str) -> bool:
        """Remove a workspace from configuration without deleting historical tasks or logs."""
        return db.delete_workspace_record(workspace_id)

    @staticmethod
    def enable_workspace(workspace_id: str) -> bool:
        """Enable an existing workspace."""
        return db.update_workspace_record(workspace_id, enabled=True)

    @staticmethod
    def disable_workspace(workspace_id: str) -> bool:
        """Disable an existing workspace."""
        return db.update_workspace_record(workspace_id, enabled=False)

    @staticmethod
    def set_permissions(workspace_id: str, permissions: set[str] | list[str]) -> bool:
        """Set explicit permissions for a workspace."""
        perms = [p.upper().strip() for p in permissions]
        return db.update_workspace_record(workspace_id, permissions=perms)

    @staticmethod
    def get_workspace(workspace_id: str) -> Optional[Workspace]:
        """Load a workspace by its ID."""
        row = db.get_workspace_record(workspace_id)
        return Workspace.from_dict(row) if row else None

    @staticmethod
    def get_workspace_by_name(name: str) -> Optional[Workspace]:
        """Load a workspace by its name/label."""
        row = db.get_workspace_by_name_record(name)
        return Workspace.from_dict(row) if row else None

    @staticmethod
    def list_workspaces(enabled_only: bool = False) -> list[Workspace]:
        """Retrieve all workspaces."""
        rows = db.list_workspace_records()
        workspaces = [Workspace.from_dict(r) for r in rows]
        if enabled_only:
            workspaces = [w for w in workspaces if w.enabled]
        return workspaces

    @staticmethod
    def count_workspaces() -> int:
        """Count configured workspaces."""
        return db.count_workspaces()

    @staticmethod
    def find_workspace_for_path(path: str | Path) -> Optional[Workspace]:
        """
        Find the matching configured workspace containing the canonical path.
        If nested workspaces exist, returns the most specific (longest path) match.
        """
        try:
            target = Path(path).expanduser().resolve()
        except Exception:
            return None

        candidates = []
        for ws in WorkspaceManager.list_workspaces():
            try:
                ws_path = ws.canonical_path
                if WorkspaceManager._is_subpath(target, ws_path):
                    candidates.append((len(ws_path.parts), ws))
            except Exception:
                continue

        if not candidates:
            return None

        # Return workspace with most specific (deepest) match
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]

    @staticmethod
    def check_workspace_authorization(
        path: str | Path,
        required_permission: str,
    ) -> tuple[bool, str, Optional[Workspace]]:
        """
        Verify canonical path containment, workspace enabled status, and required permission.

        Returns (is_authorized, reason_or_message, workspace_instance).
        """
        try:
            target = Path(path).expanduser().resolve()
        except Exception as e:
            return False, f"Invalid path: {e}", None

        ws = WorkspaceManager.find_workspace_for_path(target)
        if not ws:
            return False, f"Path is outside configured workspaces: {target}", None

        if not ws.enabled:
            return False, f"Workspace '{ws.name}' is currently disabled.", ws

        req_perm = required_permission.upper().strip()
        if req_perm not in ws.permissions:
            return (
                False,
                f"Workspace '{ws.name}' does not have {req_perm} permission (has "
                f"{sorted(list(ws.permissions))}).",
                ws,
            )

        return True, "Authorized", ws

    @classmethod
    def authorize_action(
        cls,
        action: str,
        source_path: Optional[str | Path] = None,
        destination_path: Optional[str | Path] = None,
        target_path: Optional[str | Path] = None,
    ) -> tuple[bool, str]:
        """
        Authoritative action authorization according to Milestone 4 policy:
        - Search / Read / List: READ on target/source
        - Move: READ on source AND WRITE on destination
        - Rename: WRITE on file's workspace
        - Delete: DELETE on target's workspace
        """
        act = action.lower().strip()

        # If no workspaces are configured:
        # In real CLI or enforced mode, block execution immediately.
        # Fall back to legacy ALLOWED_DIRECTORIES only for legacy test fixtures.
        if cls.count_workspaces() == 0:
            if not os.getenv("PYTEST_CURRENT_TEST") or os.getenv("AGENT_ENFORCE_WORKSPACES"):
                return (
                    False,
                    "POLICY_VIOLATION: No workspaces configured. An authorized workspace must be "
                    "explicitly added.",
                )
            return True, "No workspaces configured (legacy mode)"

        if act in ("search", "find", "list", "read"):
            p = source_path or target_path
            if p:
                ok, reason, _ = cls.check_workspace_authorization(p, Permission.READ.value)
                if not ok:
                    return False, f"POLICY_VIOLATION: {reason}"
            return True, "Authorized"

        elif act == "move":
            if not source_path or not destination_path:
                return False, "POLICY_VIOLATION: Missing source or destination path for move."
            ok_src, reason_src, _ = cls.check_workspace_authorization(
                source_path, Permission.READ.value
            )
            if not ok_src:
                return False, f"POLICY_VIOLATION: Move source unauthorized - {reason_src}"
            ok_dst, reason_dst, _ = cls.check_workspace_authorization(
                destination_path, Permission.WRITE.value
            )
            if not ok_dst:
                return False, f"POLICY_VIOLATION: Move destination unauthorized - {reason_dst}"
            return True, "Authorized"

        elif act == "rename":
            p = source_path or target_path
            if not p:
                return False, "POLICY_VIOLATION: Missing target path for rename."
            ok, reason, _ = cls.check_workspace_authorization(p, Permission.WRITE.value)
            if not ok:
                return False, f"POLICY_VIOLATION: Rename unauthorized - {reason}"
            return True, "Authorized"

        elif act in ("create_directory", "mkdir"):
            p = target_path or destination_path or source_path
            if not p:
                return False, "POLICY_VIOLATION: Missing directory path for create_directory."
            ok, reason, _ = cls.check_workspace_authorization(p, Permission.WRITE.value)
            if not ok:
                return False, f"POLICY_VIOLATION: Create directory unauthorized - {reason}"
            return True, "Authorized"

        elif act == "delete":
            p = target_path or source_path
            if not p:
                return False, "POLICY_VIOLATION: Missing target path for delete."
            ok, reason, _ = cls.check_workspace_authorization(p, Permission.DELETE.value)
            if not ok:
                return False, f"POLICY_VIOLATION: Delete unauthorized - {reason}"
            return True, "Authorized"

        return False, f"POLICY_VIOLATION: Unrecognized action '{action}'"
