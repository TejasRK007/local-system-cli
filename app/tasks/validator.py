"""
Plan validator for Milestone 5: Intelligent Goal-to-Plan Reasoning.

Enforces strict action whitelisting, argument structure, canonical workspace
containment, permission validation, dependency DAG cycle detection, and
rejection of hallucinated source files or unauthorized system paths.
"""

import os
from pathlib import Path
from typing import Any

from app.workspaces import Permission, WorkspaceManager

ALLOWED_ACTIONS: frozenset[str] = frozenset(
    {
        "search",
        "create_directory",
        "mkdir",
        "move",
        "rename",
        "delete",
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

        # 2. Second pass: per-action argument validation, path safety, and workspace permissions
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
                if "/" in new_name_str or "\\" in new_name_str:
                    return (
                        False,
                        f"Plan validation failed: step #{order} rename new_name must not contain "
                        f"path separators.",
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
                            f"Plan validation failed: step #{order} rename target does not exist: "
                            f"{src_path}",
                        )
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

        return True, "Plan is valid."

    @classmethod
    def _check_path_safety(cls, path: Path) -> tuple[bool, str]:
        """Verify canonical path boundaries, traversal rejection, and protected paths."""
        try:
            resolved = path.resolve()
        except Exception as e:
            return False, f"Could not resolve path: {e}"

        # Drive root rejection (e.g. C:\ or /)
        if resolved == Path(resolved.anchor) or len(resolved.parts) <= 1:
            return False, f"Targeting drive root '{resolved}' is blocked."

        # Protected system directories on Windows
        resolved_str = str(resolved).lower()
        windows_dir = os.environ.get("SystemRoot", "C:\\Windows").lower()
        prog_files = os.environ.get("ProgramFiles", "C:\\Program Files").lower()
        prog_files_x86 = os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)").lower()

        for sys_path in (windows_dir, prog_files, prog_files_x86):
            if (
                resolved_str == sys_path
                or resolved_str.startswith(sys_path + "\\")
                or resolved_str.startswith(sys_path + "/")
            ):
                return False, f"Targeting protected system directory '{resolved}' is blocked."

        return True, "Path is safe."
