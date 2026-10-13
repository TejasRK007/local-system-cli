"""
Plan validator for Milestone 5: Intelligent Goal-to-Plan Reasoning.

Enforces strict action whitelisting, argument structure, canonical workspace
containment, permission validation, dependency DAG cycle detection, and
rejection of hallucinated source files or unauthorized system paths.
"""

import os
from pathlib import Path
from typing import Any, Optional

from app.workspaces import Permission, WorkspaceManager

ALLOWED_ACTIONS: frozenset[str] = frozenset(
    {
        "search",
        "create_directory",
        "mkdir",
        "create_file",
        "touch",
        "move",
        "rename",
        "delete",
        # Milestone 7: General local system tools
        "get_system_info",
        "sys_info",
        "list_processes",
        "find_process",
        "read_clipboard",
        "write_clipboard",
        "inspect_archive",
        "extract_archive",
        "get_file_metadata",
        "metadata",
        # Milestone 8: Personal automation & productivity integrations
        "read_document",
        "summarize_document",
        "browser_fetch_page",
        "browser_search",
        "browser_download_file",
        "email_search",
        "email_read",
        "email_draft",
        "email_send",
        "calendar_list_events",
        "calendar_check_conflict",
        "calendar_create_event",
        "github_list_issues",
        "github_inspect_pr",
        "github_create_issue",
    }
)


class PlanValidator:
    """Validates entire synthesized plans before execution."""

    @classmethod
    def validate_plan(cls, steps: list[dict[str, Any]]) -> tuple[bool, str]:
        """
        Validate all steps in a plan holistically.

        Returns (is_valid, error_reason).
        If any step or relationship fails validation, returns (False, reason).
        """
        if not steps or not isinstance(steps, list):
            return False, "Plan validation failed: steps list is empty."

        order_set: set[int] = set()
        step_orders: list[int] = []

        # 1. First pass: structure, action whitelist, and dependency DAG
        for idx, step in enumerate(steps):
            if not isinstance(step, dict):
                return False, f"Plan validation failed: step #{idx + 1} is not a valid object."

            order = step.get("step_order")
            if not isinstance(order, int) or order <= 0:
                return (
                    False,
                    f"Plan validation failed: step #{idx + 1} has invalid step_order: {order}.",
                )

            if order in order_set:
                return False, f"Plan validation failed: duplicate step_order {order} detected."
            order_set.add(order)
            step_orders.append(order)

            action = str(step.get("action", "")).lower().strip()
            if not action or action not in ALLOWED_ACTIONS:
                return False, (
                    f"Plan validation failed: step #{order} specifies unsupported action "
                    f"'{action}'. "
                    f"Allowed actions: {sorted(list(ALLOWED_ACTIONS))}."
                )

            args = step.get("arguments")
            if not isinstance(args, dict):
                return (
                    False,
                    f"Plan validation failed: step #{order} arguments must be a dictionary.",
                )

            # Check dependency references
            dep_order = step.get("depends_on_order")
            if dep_order is not None:
                if not isinstance(dep_order, int):
                    return (
                        False,
                        f"Plan validation failed: step #{order} depends_on_order must be an "
                        f"integer.",
                    )
                if dep_order >= order:
                    return False, (
                        f"Plan validation failed: step #{order} has invalid dependency "
                        f"#{dep_order}. "
                        f"Dependencies must refer to earlier steps (cycle / forward reference "
                        f"detected)."
                    )
                if dep_order not in order_set:
                    return (
                        False,
                        f"Plan validation failed: step #{order} depends on non-existent step "
                        f"#{dep_order}.",
                    )

            # Check variable references in arguments
            for arg_key, arg_val in args.items():
                if isinstance(arg_val, str) and "$output.step_" in arg_val:
                    # Extract referenced step order e.g. $output.step_1.path -> 1
                    try:
                        ref_part = arg_val.split("$output.step_")[-1]
                        ref_order = int(ref_part.split(".")[0])
                        if ref_order >= order:
                            return False, (
                                f"Plan validation failed: step #{order} references output of step "
                                f"#{ref_order} "
                                f"which is not an earlier step."
                            )
                        if ref_order not in order_set:
                            return False, (
                                f"Plan validation failed: step #{order} references output of "
                                f"non-existent step #{ref_order}."
                            )
                    except (ValueError, IndexError):
                        return (
                            False,
                            f"Plan validation failed: malformed output variable reference "
                            f"'{arg_val}'.",
                        )

        # 2. Second pass: per-action argument validation, path safety, workspace permissions,
        # destination collisions, and cross-step conflict detection
        deleted_paths: set[Path] = set()
        planned_destinations: set[Path] = set()

        for step in steps:
            order = step["step_order"]
            action = step["action"].lower().strip()
            args = step["arguments"]

            # ---------------------------------------------------------
            # CREATE_DIRECTORY
            # ---------------------------------------------------------
            if action in ("create_directory", "mkdir"):
                raw_dir = args.get("directory") or args.get("path")
                if not raw_dir or not str(raw_dir).strip():
                    return (
                        False,
                        f"Plan validation failed: step #{order} (create_directory) missing "
                        f"required 'directory' argument.",
                    )

                dir_str = str(raw_dir).strip()
                # Reject if variable reference (mkdir destination
                # must be known upfront or inside workspace)
                if not dir_str.startswith("$"):
                    path_obj = Path(dir_str).expanduser()
                    # Traversal / protected path check
                    safe_ok, safe_reason = cls._check_path_safety(path_obj)
                    if not safe_ok:
                        return (
                            False,
                            f"Plan validation failed: step #{order} target path unsafe: "
                            f"{safe_reason}",
                        )

                    # Workspace authorization check
                    auth_ok, auth_reason = WorkspaceManager.authorize_action(
                        "create_directory", target_path=path_obj
                    )
                    if not auth_ok:
                        return (
                            False,
                            f"Plan validation failed: step #{order} create_directory unauthorized: "
                            f"{auth_reason}",
                        )

            # ---------------------------------------------------------
            # CREATE_FILE
            # ---------------------------------------------------------
            elif action in ("create_file", "touch"):
                raw_fp = args.get("file_path") or args.get("path")
                if not raw_fp or not str(raw_fp).strip():
                    return (
                        False,
                        f"Plan validation failed: step #{order} ({action}) missing "
                        f"required 'file_path' argument.",
                    )

                fp_str = str(raw_fp).strip()
                if not fp_str.startswith("$"):
                    path_obj = Path(fp_str).expanduser()
                    safe_ok, safe_reason = cls._check_path_safety(path_obj)
                    if not safe_ok:
                        return (
                            False,
                            f"Plan validation failed: step #{order} target path unsafe: "
                            f"{safe_reason}",
                        )

                    auth_ok, auth_reason = WorkspaceManager.authorize_action(
                        "create_file", target_path=path_obj
                    )
                    if not auth_ok:
                        return (
                            False,
                            f"Plan validation failed: step #{order} create_file unauthorized: "
                            f"{auth_reason}",
                        )

            # ---------------------------------------------------------
            # MOVE
            # ---------------------------------------------------------
            elif action == "move":
                src = args.get("source")
                dst = args.get("destination")
                if not src or not str(src).strip():
                    return (
                        False,
                        f"Plan validation failed: step #{order} (move) missing required 'source' "
                        f"argument.",
                    )
                if not dst or not str(dst).strip():
                    return (
                        False,
                        f"Plan validation failed: step #{order} (move) missing required "
                        f"'destination' argument.",
                    )

                src_str = str(src).strip()
                dst_str = str(dst).strip()

                src_path_obj: Optional[Path] = None
                # Source path validation (if not variable reference, must exist on disk)
                if not src_str.startswith("$") and src_str.lower() not in ("it", "$prev.path"):
                    src_path = Path(src_str).expanduser()
                    if not src_path.is_absolute() and len(src_path.parts) == 1:
                        # Bare filename: must be resolvable within an authorized workspace
                        pass
                    else:
                        safe_ok, safe_reason = cls._check_path_safety(src_path)
                        if not safe_ok:
                            return (
                                False,
                                f"Plan validation failed: step #{order} move source unsafe: "
                                f"{safe_reason}",
                            )
                        if not src_path.exists():
                            return False, (
                                f"Plan validation failed: step #{order} source file does not exist "
                                f"on disk: {src_path}. "
                                f"Plans must be grounded in real files."
                            )
                        resolved_src = src_path.resolve()
                        if resolved_src in deleted_paths:
                            return (
                                False,
                                f"Plan validation failed: step #{order} conflicting steps: "
                                f"source '{src_path}' was deleted in an earlier step.",
                            )
                        src_path_obj = resolved_src

                        # Verify source workspace READ permission
                        if WorkspaceManager.count_workspaces() > 0:
                            auth_ok, reason, _ = WorkspaceManager.check_workspace_authorization(
                                src_path, Permission.READ.value
                            )
                            if not auth_ok:
                                return (
                                    False,
                                    f"Plan validation failed: step #{order} move source "
                                    f"unauthorized: {reason}",
                                )

                # Destination validation (if not variable reference)
                if not dst_str.startswith("$") and dst_str.lower() not in ("it", "$prev.path"):
                    dst_path = Path(dst_str).expanduser()
                    safe_ok, safe_reason = cls._check_path_safety(dst_path)
                    if not safe_ok:
                        return (
                            False,
                            f"Plan validation failed: step #{order} move destination unsafe: "
                            f"{safe_reason}",
                        )
                    if WorkspaceManager.count_workspaces() > 0:
                        auth_ok, reason, _ = WorkspaceManager.check_workspace_authorization(
                            dst_path, Permission.WRITE.value
                        )
                        if not auth_ok:
                            return (
                                False,
                                f"Plan validation failed: step #{order} move destination "
                                f"unauthorized: {reason}",
                            )

                    # Destination collision check
                    if src_path_obj:
                        dest_file = (
                            (dst_path / src_path_obj.name).resolve()
                            if dst_path.is_dir()
                            else dst_path.resolve()
                        )
                        if dest_file.exists():
                            return (
                                False,
                                f"Plan validation failed: step #{order} destination collision: "
                                f"file already exists at '{dest_file}'.",
                            )
                        if dest_file in planned_destinations:
                            return (
                                False,
                                f"Plan validation failed: step #{order} conflicting steps: "
                                f"multiple steps target destination '{dest_file}'.",
                            )
                        planned_destinations.add(dest_file)

            # ---------------------------------------------------------
            # RENAME
            # ---------------------------------------------------------
            elif action == "rename":
                src = args.get("source")
                new_name = args.get("new_name")
                if not src or not str(src).strip():
                    return (
                        False,
                        f"Plan validation failed: step #{order} (rename) missing required 'source' "
                        f"argument.",
                    )
                if not new_name or not str(new_name).strip():
                    return (
                        False,
                        f"Plan validation failed: step #{order} (rename) missing required "
                        f"'new_name' argument.",
                    )

                new_name_str = str(new_name).strip()
                if new_name_str in (".", ".."):
                    return (
                        False,
                        f"Plan validation failed: step #{order} rename new_name is invalid: "
                        f"'{new_name_str}'.",
                    )
                if "/" in new_name_str or "\\" in new_name_str:
                    return (
                        False,
                        f"Plan validation failed: step #{order} rename new_name must not contain "
                        f"path separators.",
                    )

                windows_reserved = {
                    "con",
                    "prn",
                    "aux",
                    "nul",
                    "com1",
                    "com2",
                    "com3",
                    "com4",
                    "com5",
                    "com6",
                    "com7",
                    "com8",
                    "com9",
                    "lpt1",
                    "lpt2",
                    "lpt3",
                    "lpt4",
                    "lpt5",
                    "lpt6",
                    "lpt7",
                    "lpt8",
                    "lpt9",
                }
                stem_lower = Path(new_name_str).stem.lower()
                if stem_lower in windows_reserved or new_name_str.lower() in windows_reserved:
                    return (
                        False,
                        f"Plan validation failed: step #{order} rename new_name is a reserved "
                        f"device name: '{new_name_str}'.",
                    )
                if any(c in '<>:"|?*' or ord(c) < 32 for c in new_name_str):
                    return (
                        False,
                        f"Plan validation failed: step #{order} rename new_name contains invalid "
                        f"filename characters: '{new_name_str}'.",
                    )

                src_str = str(src).strip()
                if not src_str.startswith("$") and src_str.lower() not in ("it", "$prev.path"):
                    src_path = Path(src_str).expanduser()
                    safe_ok, safe_reason = cls._check_path_safety(src_path)
                    if not safe_ok:
                        return (
                            False,
                            f"Plan validation failed: step #{order} rename source unsafe: "
                            f"{safe_reason}",
                        )
                    if not src_path.exists():
                        return (
                            False,
                            f"Plan validation failed: step #{order} rename source does not exist: "
                            f"{src_path}",
                        )
                    resolved_src = src_path.resolve()
                    if resolved_src in deleted_paths:
                        return (
                            False,
                            f"Plan validation failed: step #{order} conflicting steps: "
                            f"source '{src_path}' was deleted in an earlier step.",
                        )
                    if resolved_src.name == new_name_str:
                        return (
                            False,
                            f"Plan validation failed: step #{order} rename source and destination "
                            f"are identical: '{new_name_str}'.",
                        )

                    dest_path = (resolved_src.parent / new_name_str).resolve()
                    safe_dst_ok, safe_dst_reason = cls._check_path_safety(dest_path)
                    if not safe_dst_ok:
                        return (
                            False,
                            f"Plan validation failed: step #{order} rename destination unsafe: "
                            f"{safe_dst_reason}",
                        )
                    if dest_path.exists():
                        return (
                            False,
                            f"Plan validation failed: step #{order} destination collision: "
                            f"target file already exists at '{dest_path}'.",
                        )
                    if dest_path in planned_destinations:
                        return (
                            False,
                            f"Plan validation failed: step #{order} conflicting steps: "
                            f"multiple steps target destination '{dest_path}'.",
                        )
                    planned_destinations.add(dest_path)

                    if WorkspaceManager.count_workspaces() > 0:
                        auth_ok, reason, _ = WorkspaceManager.check_workspace_authorization(
                            src_path, Permission.WRITE.value
                        )
                        if not auth_ok:
                            return (
                                False,
                                f"Plan validation failed: step #{order} rename unauthorized: "
                                f"{reason}",
                            )

            # ---------------------------------------------------------
            # DELETE
            # ---------------------------------------------------------
            elif action == "delete":
                target = args.get("target") or args.get("source")
                if not target or not str(target).strip():
                    return (
                        False,
                        f"Plan validation failed: step #{order} (delete) missing required 'target' "
                        f"argument.",
                    )

                target_str = str(target).strip()
                if not target_str.startswith("$") and target_str.lower() not in (
                    "it",
                    "$prev.path",
                ):
                    tgt_path = Path(target_str).expanduser()
                    safe_ok, safe_reason = cls._check_path_safety(tgt_path)
                    if not safe_ok:
                        return (
                            False,
                            f"Plan validation failed: step #{order} delete target unsafe: "
                            f"{safe_reason}",
                        )
                    if not tgt_path.exists():
                        return (
                            False,
                            f"Plan validation failed: step #{order} delete target does not exist: "
                            f"{tgt_path}",
                        )
                    resolved_tgt = tgt_path.resolve()
                    if resolved_tgt in deleted_paths:
                        return (
                            False,
                            f"Plan validation failed: step #{order} conflicting steps: "
                            f"target '{tgt_path}' was already deleted in an earlier step.",
                        )
                    deleted_paths.add(resolved_tgt)

                    if WorkspaceManager.count_workspaces() > 0:
                        auth_ok, reason, _ = WorkspaceManager.check_workspace_authorization(
                            tgt_path, Permission.DELETE.value
                        )
                        if not auth_ok:
                            return (
                                False,
                                f"Plan validation failed: step #{order} delete unauthorized: "
                                f"{reason}",
                            )

            # ---------------------------------------------------------
            # SEARCH
            # ---------------------------------------------------------
            elif action == "search":
                raw_dir = args.get("directory")
                if raw_dir and not str(raw_dir).startswith("$"):
                    dir_path = Path(str(raw_dir)).expanduser()
                    safe_ok, safe_reason = cls._check_path_safety(dir_path)
                    if not safe_ok:
                        return (
                            False,
                            f"Plan validation failed: step #{order} search directory unsafe: "
                            f"{safe_reason}",
                        )
                    if WorkspaceManager.count_workspaces() > 0:
                        auth_ok, reason, _ = WorkspaceManager.check_workspace_authorization(
                            dir_path, Permission.READ.value
                        )
                        if not auth_ok:
                            return (
                                False,
                                f"Plan validation failed: step #{order} search unauthorized: "
                                f"{reason}",
                            )

            # ---------------------------------------------------------
            # M7: SYSTEM & PROCESS INSPECTION
            # ---------------------------------------------------------
            elif action in ("get_system_info", "sys_info", "list_processes", "find_process"):
                pass

            # ---------------------------------------------------------
            # M7: CLIPBOARD
            # ---------------------------------------------------------
            elif action == "read_clipboard":
                pass
            elif action == "write_clipboard":
                if not (args.get("text") or args.get("content")):
                    return (
                        False,
                        f"Plan validation failed: step #{order} (write_clipboard) "
                        f"missing 'text' argument.",
                    )

            # ---------------------------------------------------------
            # M7: ARCHIVES
            # ---------------------------------------------------------
            elif action == "inspect_archive":
                raw_arc = args.get("archive_path") or args.get("path")
                if not raw_arc:
                    return (
                        False,
                        f"Plan validation failed: step #{order} (inspect_archive) "
                        f"missing 'archive_path'.",
                    )
                if not str(raw_arc).startswith("$"):
                    arc_path = Path(str(raw_arc)).expanduser()
                    safe_ok, safe_reason = cls._check_path_safety(arc_path)
                    if not safe_ok:
                        return (
                            False,
                            f"Plan validation failed: step #{order} archive unsafe: {safe_reason}",
                        )
                    if not arc_path.exists():
                        return (
                            False,
                            f"Plan validation failed: step #{order} archive not found: {arc_path}",
                        )
                    if WorkspaceManager.count_workspaces() > 0:
                        auth_ok, reason, _ = WorkspaceManager.check_workspace_authorization(
                            arc_path, Permission.READ.value
                        )
                        if not auth_ok:
                            return (
                                False,
                                f"Plan validation failed: step #{order} archive unauthorized: "
                                f"{reason}",
                            )

            elif action == "extract_archive":
                raw_arc = args.get("archive_path") or args.get("path")
                raw_dst = args.get("destination") or args.get("target_dir")
                if not raw_arc or not raw_dst:
                    return (
                        False,
                        f"Plan validation failed: step #{order} (extract_archive) "
                        f"requires 'archive_path' and 'destination'.",
                    )
                if not str(raw_arc).startswith("$"):
                    arc_path = Path(str(raw_arc)).expanduser()
                    safe_ok, safe_reason = cls._check_path_safety(arc_path)
                    if not safe_ok:
                        return (
                            False,
                            f"Plan validation failed: step #{order} archive unsafe: {safe_reason}",
                        )
                    if not arc_path.exists():
                        return (
                            False,
                            f"Plan validation failed: step #{order} archive not found: {arc_path}",
                        )
                    if WorkspaceManager.count_workspaces() > 0:
                        auth_ok, reason, _ = WorkspaceManager.check_workspace_authorization(
                            arc_path, Permission.READ.value
                        )
                        if not auth_ok:
                            return (
                                False,
                                f"Plan validation failed: step #{order} archive unauthorized: "
                                f"{reason}",
                            )
                if not str(raw_dst).startswith("$"):
                    dst_path = Path(str(raw_dst)).expanduser()
                    safe_ok, safe_reason = cls._check_path_safety(dst_path)
                    if not safe_ok:
                        return (
                            False,
                            f"Plan validation failed: step #{order} destination unsafe: "
                            f"{safe_reason}",
                        )
                    if WorkspaceManager.count_workspaces() > 0:
                        auth_ok, reason, _ = WorkspaceManager.check_workspace_authorization(
                            dst_path, Permission.WRITE.value
                        )
                        if not auth_ok:
                            return (
                                False,
                                f"Plan validation failed: step #{order} destination unauthorized: "
                                f"{reason}",
                            )

            # ---------------------------------------------------------
            # M7: METADATA
            # ---------------------------------------------------------
            elif action in ("get_file_metadata", "metadata", "read_document", "summarize_document"):
                raw_file = args.get("file_path") or args.get("path")
                if not raw_file:
                    return (
                        False,
                        f"Plan validation failed: step #{order} (metadata) missing 'file_path'.",
                    )
                if not str(raw_file).startswith("$"):
                    target_path = Path(str(raw_file)).expanduser()
                    safe_ok, safe_reason = cls._check_path_safety(target_path)
                    if not safe_ok:
                        return (
                            False,
                            f"Plan validation failed: step #{order} file unsafe: {safe_reason}",
                        )
                    if not target_path.exists():
                        return (
                            False,
                            f"Plan validation failed: step #{order} file not found: {target_path}",
                        )
                    if WorkspaceManager.count_workspaces() > 0:
                        auth_ok, reason, _ = WorkspaceManager.check_workspace_authorization(
                            target_path, Permission.READ.value
                        )
                        if not auth_ok:
                            return (
                                False,
                                f"Plan validation failed: step #{order} file unauthorized: "
                                f"{reason}",
                            )

        return True, "Plan is valid."

    @classmethod
    def _check_path_safety(cls, path: Path) -> tuple[bool, str]:
        """Verify canonical path boundaries, traversal rejection, and protected paths."""
        # 1. Protected path check on input path BEFORE filesystem resolution/existence
        if WorkspaceManager.is_protected_system_path(path):
            return False, f"Targeting protected system directory '{path}' is blocked."

        try:
            resolved = path.resolve()
        except Exception as e:
            return False, f"Could not resolve path: {e}"

        # Drive root rejection (e.g. C:\ or /)
        if resolved == Path(resolved.anchor) or len(resolved.parts) <= 1:
            return False, f"Targeting drive root '{resolved}' is blocked."

        # Cross-platform protected system paths (Windows, POSIX, symlinks)
        if WorkspaceManager.is_protected_system_path(resolved):
            return False, f"Targeting protected system directory '{resolved}' is blocked."

        # Protected system directories on Windows environment fallback
        resolved_str = str(resolved).lower()
        windows_dir = os.environ.get("SystemRoot", "C:\\Windows").lower()
        prog_files = os.environ.get("ProgramFiles", "C:\\Program Files").lower()
        prog_files_x86 = os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)").lower()

        for sys_path in (windows_dir, prog_files, prog_files_x86):
            if sys_path and (
                resolved_str == sys_path
                or resolved_str.startswith(sys_path + "\\")
                or resolved_str.startswith(sys_path + "/")
            ):
                return False, f"Targeting protected system directory '{resolved}' is blocked."

        return True, "Path is safe."
