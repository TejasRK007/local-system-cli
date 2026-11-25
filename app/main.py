import os
import sys
from pathlib import Path
from typing import Any, Optional

if sys.platform == "win32":
    try:
        if sys.stdout and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        if sys.stderr and hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from app.agent import run_agent
from app.database import get_recent_logs, log_event
from app.policy import RISK_COLORS, get_action_risk, requires_approval
from app.recovery import FailureCategory, execute_action_with_recovery
from app.tasks.adaptive import AdaptiveFilesystemAgent
from app.tasks.executor import StepExecutor
from app.tasks.goal_planner import GoalPlanner
from app.tasks.manager import TaskManager
from app.tasks.models import StepStatus, TaskStatus
from app.tasks.planner import plan_task_steps
from app.tasks.validator import PlanValidator
from app.tools.archive_tools import extract_archive, inspect_archive
from app.tools.browser_tools import browser_fetch_page
from app.tools.calendar_tools import (
    calendar_list_events,
)
from app.tools.clipboard import read_clipboard, write_clipboard
from app.tools.document_tools import read_document, summarize_document
from app.tools.email_tools import email_draft
from app.tools.file_actions import (
    delete_file,
    move_file,
    rename_file,
)
from app.tools.github_tools import github_list_issues
from app.tools.metadata_tools import get_file_metadata
from app.tools.system_tools import get_system_info, list_processes
from app.workspaces import Permission, WorkspaceManager

console = Console()


def get_candidate_unauthorized_folders(text: str = "", summary: str = "") -> list[tuple[str, Path]]:
    """
    Identify potential local folders (Downloads, Documents, Desktop, or explicitly
    mentioned directories) that are not yet registered as enabled workspaces.
    """
    home = Path.home()
    existing_paths = {
        str(w.canonical_path).lower()
        for w in WorkspaceManager.list_workspaces()
        if w.enabled
    }
    candidates: list[tuple[str, Path]] = []
    seen_paths: set[str] = set()

    standard = [
        ("Downloads", home / "Downloads"),
        ("Documents", home / "Documents"),
        ("Desktop", home / "Desktop"),
    ]

    combined_text = f"{text} {summary}".lower()

    # Prioritize folders explicitly mentioned in user request or summary
    for name, path in standard:
        if path.exists():
            resolved_str = str(path.resolve()).lower()
            if resolved_str not in existing_paths and resolved_str not in seen_paths:
                alias = name.lower()
                singular = alias[:-1] if alias.endswith("s") else alias
                if alias in combined_text or singular in combined_text:
                    candidates.append((name, path.resolve()))
                    seen_paths.add(resolved_str)

    # Then include other standard folders that exist but are not yet registered
    for name, path in standard:
        if path.exists():
            resolved_str = str(path.resolve()).lower()
            if resolved_str not in existing_paths and resolved_str not in seen_paths:
                candidates.append((name, path.resolve()))
                seen_paths.add(resolved_str)

    return candidates


def check_workspace_requirement(operation_name: str = "tasks") -> bool:
    """
    Ensure at least one workspace is configured.
    Returns True if workspaces exist or legacy test mode is active.
    Returns False (and prints notification) if real CLI has no workspaces configured.
    """
    if WorkspaceManager.count_workspaces() > 0:
        return True

    # In real CLI, if no workspaces exist, prompt user with yes/no option to authorize standard folders
    if not os.getenv("PYTEST_CURRENT_TEST") and not os.getenv("AGENT_ENFORCE_WORKSPACES"):
        candidates = get_candidate_unauthorized_folders()
        if candidates:
            folder_names = ", ".join(f"[bold cyan]{c[0]}[/bold cyan]" for c in candidates)
            console.print(
                Panel(
                    f"[yellow]No workspaces are currently configured.[/yellow]\n\n"
                    f"To perform {operation_name}, access to your local folders is needed.\n\n"
                    f"Available standard folders: {folder_names}\n\n"
                    "[bold white]Would you like to grant access to these folders now?[/bold white]",
                    title="[bold yellow]Authorize Folder Access[/bold yellow]",
                    border_style="yellow",
                )
            )
            if typer.confirm("Grant access to standard folders now?", default=True):
                for name, path in candidates:
                    WorkspaceManager.add_workspace(
                        path,
                        name=name,
                        permissions=[
                            Permission.READ.value,
                            Permission.WRITE.value,
                            Permission.DELETE.value,
                        ],
                    )
                    console.print(f"[bold green]✓ Authorized '{name}' ({path})[/bold green]")
                return True

    # Real CLI or enforced mode: require explicit workspace
    if not os.getenv("PYTEST_CURRENT_TEST") or os.getenv("AGENT_ENFORCE_WORKSPACES"):
        console.print(
            Panel(
                "[yellow]No workspaces configured.[/yellow]\n\n"
                f"You must explicitly add at least one authorized workspace before executing "
                f"{operation_name}.\n\n"
                "[bold white]Add a workspace:[/bold white]\n"
                '  py -m app.main workspace-add "<path>" [--name "<label>"]\n\n'
                "[dim]Example:[/dim]\n"
                '  py -m app.main workspace-add "manual_test" --name "manual_test"',
                title="[bold yellow]Workspace Required[/bold yellow]",
                border_style="yellow",
            )
        )
        return False

    return True


app = typer.Typer(help="Local Agentic Automation System - AI-powered task automation.")


def show_header():
    """Display the application header."""

    provider = os.getenv("LLM_PROVIDER", "ollama").lower()
    from app.llm import is_ollama_online

    ollama_up = is_ollama_online()
    if provider == "ollama":
        if ollama_up:
            status_line = (
                f"\n[dim green]● Local AI (Ollama): Online ({os.getenv('OLLAMA_MODEL', 'qwen2.5:3b')})[/dim green]"
            )
        else:
            status_line = (
                "\n[dim yellow]○ Local AI (Ollama): Offline (Run 'ollama serve' for offline local model)[/dim yellow]"
            )
    else:
        status_line = f"\n[dim blue]● Cloud AI: Groq ({os.getenv('GROQ_MODEL', 'openai/gpt-oss-120b')})[/dim blue]"

    console.print()

    console.print(
        Panel(
            "[bold white]LOCAL AGENTIC AUTOMATION SYSTEM[/bold white]\n"
            f"[cyan]AI Task Automation CLI[/cyan]{status_line}",
            border_style="cyan",
            expand=False,
        )
    )

    console.print()


def show_user_request(request: str):
    """Display the user's request."""

    text = Text()

    text.append(
        "You: ",
        style="bold cyan",
    )

    text.append(
        request,
        style="white",
    )

    console.print(text)
    console.print()


def show_file_table(files):
    """Display matching files in a Rich table."""

    table = Table(
        title="Matching Files",
        title_style="bold cyan",
        border_style="blue",
        show_lines=False,
    )

    table.add_column(
        "#",
        style="bold cyan",
        justify="right",
    )

    table.add_column(
        "File",
        style="white",
    )

    table.add_column(
        "Created",
        style="green",
    )

    for index, item in enumerate(files, start=1):
        table.add_row(
            str(index),
            item["path"],
            item["created"],
        )

    console.print(table)


def show_action_summary(
    action: str,
    risk: str,
    details: dict[str, str],
) -> None:
    """
    Display an Action / Risk summary panel before approval.

    Args:
        action: human-readable action name ('Rename', 'Move', 'Delete').
        risk:   risk tier string ('low', 'medium', 'high').
        details: extra key-value lines to show (e.g. File, New name).
    """
    color = RISK_COLORS.get(risk, "white")
    risk_badge = f"[bold {color}]{risk.upper()}[/bold {color}]"

    lines = [
        f"[bold white]Action :[/bold white] {action}",
        f"[bold white]Risk   :[/bold white] {risk_badge}",
    ]

    for key, value in details.items():
        lines.append(f"[bold white]{key:<8}:[/bold white] {value}")

    console.print(
        Panel(
            "\n".join(lines),
            title="[bold yellow]Action Summary[/bold yellow]",
            border_style=color,
        )
    )
    console.print()


def show_capabilities():
    """Display the capabilities of the current agent."""

    capabilities = (
        "[bold cyan]📁 File Management[/bold cyan]\n"
        "  • Find files by extension\n"
        "  • Find specific files by name\n"
        "  • Search Downloads, Documents, and Desktop\n"
        "  • Search inside nested folders\n"
        "  • Filter files by creation date\n"
        "  • Understand natural date expressions\n"
        "  • Delete files with approval\n"
        "  • Move files with approval\n"
        "  • Rename files with approval\n"
        "  • Verify file operations\n\n"
        "[bold cyan]🤖 Natural Language[/bold cyan]\n"
        "  • Understand normal human instructions\n"
        "  • Convert requests into tool actions\n"
        "  • Understand different ways of asking for the same task\n\n"
        "[bold yellow]🔐 Safety[/bold yellow]\n"
        "  • Destructive actions require approval\n"
        "  • Move operations require approval\n"
        "  • Rename operations require approval\n"
        "  • Exact files are shown before deletion, moving, or renaming\n"
        "  • File paths are checked before operations\n"
        "  • Existing files are never overwritten during moves or renames\n\n"
        "[bold green]💡 Example requests[/bold green]\n"
        '  • "Show me PDFs from yesterday"\n'
        '  • "Find Word documents in Downloads"\n'
        '  • "Find Internship Offer Letter - Tejas RK.pdf"\n'
        '  • "Show me PDFs from September 20 to September 24"\n'
        '  • "Delete the PDFs I downloaded yesterday"\n'
        '  • "Move Internship Offer Letter - Tejas RK.pdf to Documents"\n'
        '  • "Rename agent_renamed_test.txt to final_test.txt"\n'
        '  • "Find text files on my Desktop"'
    )

    console.print(
        Panel(
            capabilities,
            title="[bold white]What I Can Do[/bold white]",
            border_style="cyan",
            padding=(1, 2),
        )
    )


def show_help_hint():
    """Show help when the request is unsupported or unclear."""

    console.print()

    console.print(
        Panel(
            "[yellow]I couldn't understand that request.[/yellow]\n\n"
            "[bold white]Try:[/bold white]\n\n"
            "[cyan]python -m app.main agent "
            '"Show me PDFs from yesterday"[/cyan]\n'
            "[cyan]python -m app.main agent "
            '"Find Word documents in Downloads"[/cyan]\n'
            "[cyan]python -m app.main agent "
            '"Find Internship Offer Letter - Tejas RK.pdf"[/cyan]\n'
            "[cyan]python -m app.main agent "
            '"Move agent_move_test.txt to Documents"[/cyan]\n'
            "[cyan]python -m app.main agent "
            '"Rename agent_renamed_test.txt to final_test.txt"[/cyan]\n\n'
            "[bold white]For more examples:[/bold white]\n"
            "[green]python -m app.main --help[/green]",
            title="[bold yellow]Need Help?[/bold yellow]",
            border_style="yellow",
        )
    )


def show_help_screen():
    """Display beginner-friendly help."""

    show_header()

    console.print("[bold white]AI-powered local task automation.[/bold white]")

    console.print()

    console.print("[bold cyan]Commands[/bold cyan]")

    console.print("  [cyan]agent[/cyan]    Give the agent a natural-language task.")

    console.print("  [cyan]delete[/cyan]   Delete one exact file after user approval.")

    console.print("  [cyan]logs[/cyan]                 Show recent persistent audit log entries.")

    console.print(
        "  [cyan]goal[/cyan]                 "
        "Plan and execute a high-level goal using intelligent reasoning."
    )

    console.print("  [cyan]task[/cyan]                 Execute a stateful multi-step task.")

    console.print(
        "  [cyan]task-resume[/cyan]          "
        "Safely resume an incomplete task from first failed step."
    )

    console.print("  [cyan]tasks[/cyan]                List recent multi-step tasks.")

    console.print(
        "  [cyan]task-status[/cyan]          View detailed status of a task and its steps."
    )

    console.print("  [cyan]workspace[/cyan]            List configured workspaces and permissions.")

    console.print(
        "  [cyan]workspace-add[/cyan]        "
        "Add and authorize a new local directory as a workspace."
    )

    console.print("  [cyan]workspace-remove[/cyan]     Remove a workspace configuration.")

    console.print("  [cyan]workspace-enable[/cyan]     Enable an existing workspace.")

    console.print("  [cyan]workspace-disable[/cyan]    Disable an existing workspace.")

    console.print(
        "  [cyan]workspace-permissions[/cyan]Update permissions for an existing workspace."
    )

    console.print()

    show_capabilities()

    console.print()

    console.print(
        Panel(
            "[bold cyan]Natural language examples[/bold cyan]\n\n"
            "  python -m app.main agent "
            '"Show me PDFs from yesterday"\n\n'
            "  python -m app.main agent "
            '"Find Word documents in Downloads"\n\n'
            "  python -m app.main agent "
            '"Find Internship Offer Letter - Tejas RK.pdf"\n\n'
            "  python -m app.main agent "
            '"Show me PDFs from the day before yesterday"\n\n'
            "  python -m app.main agent "
            '"Delete the PDFs I downloaded yesterday"\n\n'
            "  python -m app.main agent "
            '"Move Internship Offer Letter - Tejas RK.pdf to Documents"\n\n'
            "  python -m app.main agent "
            '"Rename agent_renamed_test.txt to final_test.txt"\n\n'
            "  python -m app.main agent "
            '"What can you do for me?"',
            title="[bold white]Examples[/bold white]",
            border_style="blue",
            padding=(1, 2),
        )
    )

    console.print()

    console.print(
        "[dim]Tip: You can describe what you want in normal language. "
        "You don't need to memorize special commands.[/dim]"
    )

    console.print()


# -------------------------------------------------------------
# FRIENDLY HELP COMMAND
# -------------------------------------------------------------


@app.command(
    name="help",
    help="Show examples and learn what the agent can do.",
)
def help_command():
    show_help_screen()


# -------------------------------------------------------------
# AGENT COMMAND
# -------------------------------------------------------------


@app.command(
    help="Give the agent a natural-language task.",
)
def agent(request: str):

    show_header()

    show_user_request(request)

    request_lower = request.lower()

    # ---------------------------------------------------------
    # CAPABILITY QUESTIONS
    # ---------------------------------------------------------

    capability_phrases = [
        "what can you do",
        "what can you do for me",
        "how can you help",
        "how can you help me",
        "what can you help me with",
        "what tasks can you perform",
        "what are your capabilities",
    ]

    if any(phrase in request_lower for phrase in capability_phrases):
        show_capabilities()

        log_event(
            user_request=request,
            action="search",
            risk_level="low",
            approval_required=False,
            approval_result="NOT_REQUIRED",
            execution_status="SUCCESS",
            result_summary="Displayed capabilities",
        )

        return

    if not check_workspace_requirement("agent operations"):
        log_event(
            user_request=request,
            action="workspace",
            risk_level="low",
            approval_required=False,
            approval_result="NOT_APPLICABLE",
            execution_status="BLOCKED",
            result_summary="Operation blocked: No workspaces configured",
        )
        return

    # ---------------------------------------------------------
    # AGENT PROCESSING
    # ---------------------------------------------------------

    # Auto-bridge compound requests that involve multi-step goals
    compound_action_words = [
        "if found",
        "and move",
        "then move",
        "and delete",
        "then delete",
        "organize",
        "archive",
        "clean up",
        "sort all",
    ]
    if any(w in request_lower for w in compound_action_words):
        console.print("[dim]Delegating compound task to Goal Planner...[/dim]")
        goal_command(request)
        return

    console.print("[bold blue]● Understanding request...[/bold blue]")

    result = run_agent(request)

    console.print("[bold blue]● Processing tools...[/bold blue]")

    console.print()

    # ---------------------------------------------------------
    # UNSUPPORTED / STRING RESULT HANDLING
    # ---------------------------------------------------------

    if isinstance(result, str):
        if result == "UNSUPPORTED_REQUEST":
            show_help_hint()

            log_event(
                user_request=request,
                action="unsupported",
                risk_level="low",
                approval_required=False,
                approval_result="NOT_APPLICABLE",
                execution_status="NOT_SUPPORTED",
                result_summary="Unsupported or unrecognized request",
            )
        else:
            console.print(Panel(result, border_style="cyan"))
        return

        return

    # ---------------------------------------------------------
    # RENAME REQUEST
    # ---------------------------------------------------------

    if isinstance(result, dict) and result.get("action") == "rename":
        source_files = result.get(
            "source_files",
            [],
        )

        new_name = result.get(
            "new_name",
            "",
        )

        directory_specified = result.get("directory_specified", False)

        # -----------------------------------------------------
        # NO MATCH
        # -----------------------------------------------------

        if not source_files:
            scope = "the specified directory" if directory_specified else "all allowed directories"

            console.print(
                Panel(
                    "[yellow]The requested file could "
                    "not be found.[/yellow]\n\n"
                    f"[bold white]Searched:[/bold white] {scope}\n"
                    "[bold white]New name:[/bold white] "
                    f"{new_name}",
                    title="[bold yellow]File Not Found[/bold yellow]",
                    border_style="yellow",
                )
            )

            log_event(
                user_request=request,
                action="rename",
                risk_level="medium",
                approval_required=True,
                approval_result="NOT_APPLICABLE",
                execution_status="FAILED",
                result_summary=f"File not found for rename: {new_name}",
            )

            return

        # -----------------------------------------------------
        # MULTIPLE MATCHES — ambiguous, refuse safely
        # -----------------------------------------------------

        if len(source_files) > 1:
            scope_hint = (
                "[dim]Please specify the exact directory.\n"
                'Example: "Rename file.txt [bold]in Downloads[/bold] '
                'to new.txt"[/dim]'
                if not directory_specified
                else "[dim]Multiple files with the same name exist in that directory.[/dim]"
            )

            console.print(
                Panel(
                    f"[bold yellow]Ambiguous request:[/bold yellow] "
                    f"{len(source_files)} matching files were found.\n\n"
                    "I will not rename multiple files automatically.\n\n" + scope_hint,
                    title="[bold yellow]⚠ Ambiguous Request[/bold yellow]",
                    border_style="yellow",
                )
            )

            console.print()

            show_file_table(source_files)

            log_event(
                user_request=request,
                action="ambiguous",
                risk_level="medium",
                approval_required=True,
                approval_result="NOT_APPLICABLE",
                execution_status="AMBIGUOUS",
                result_summary=f"Ambiguous: {len(source_files)} matching files found",
            )

            return

        # -----------------------------------------------------
        # EXACT SOURCE FILE
        # -----------------------------------------------------

        source_file = source_files[0]["path"]

        # ------ POLICY: risk classification ------
        risk = get_action_risk("rename")

        show_action_summary(
            action="Rename",
            risk=risk,
            details={
                "File   ": source_file,
                "New name": new_name,
            },
        )

        # ------ APPROVAL ------
        if requires_approval(risk):
            approval = typer.confirm(f"Do you want to rename this file to {new_name}?")

            if not approval:
                console.print()

                console.print(
                    Panel(
                        "[bold red]The file was not renamed.[/bold red]",
                        title="[bold red]✗ Action Cancelled[/bold red]",
                        border_style="red",
                    )
                )

                log_event(
                    user_request=request,
                    action="rename",
                    risk_level=risk,
                    approval_required=True,
                    approval_result="DENIED",
                    execution_status="CANCELLED",
                    result_summary=f"Cancelled rename of {source_file} to {new_name}",
                )

                return

        # -----------------------------------------------------
        # EXECUTE RENAME WITH RECOVERY & OBSERVATION
        # -----------------------------------------------------

        console.print()

        console.print("[bold yellow]● Renaming approved file...[/bold yellow]")

        console.print()

        target_path = Path(source_file).parent / new_name

        exec_res = execute_action_with_recovery(
            action="rename",
            action_func=rename_file,
            func_args=(source_file, new_name),
            source_path=source_file,
            destination_path=target_path,
            on_retry=lambda attempt, desc: console.print(
                f"[bold yellow]● Retrying rename (Attempt {attempt + 1})... "
                f"Reason: {desc}[/bold yellow]"
            ),
        )

        status = exec_res["status"]
        summary = exec_res["result_summary"]

        if status == "SUCCESS":
            console.print(
                Panel(
                    f"[bold green]{summary}[/bold green]",
                    title="[bold green]✓ Task Completed[/bold green]",
                    border_style="green",
                )
            )
        elif status == FailureCategory.CONFLICT.value:
            console.print(
                Panel(
                    f"[bold yellow]Conflict Detected:[/bold yellow] Destination already contains a "
                    f"file named '{new_name}'.\n\n"
                    f"[dim]Existing file at {target_path} was NOT overwritten. Original file "
                    f"remains intact at {source_file}.[/dim]",
                    title="[bold yellow]⚠ Destination Conflict[/bold yellow]",
                    border_style="yellow",
                )
            )
        else:
            console.print(
                Panel(
                    f"[bold red]{summary}[/bold red]",
                    title="[bold red]✗ Rename Failed[/bold red]",
                    border_style="red",
                )
            )

        log_event(
            user_request=request,
            action="rename",
            risk_level=risk,
            approval_required=True,
            approval_result="APPROVED",
            execution_status=status,
            result_summary=summary,
        )

        return

    # ---------------------------------------------------------
    # MOVE REQUEST
    # ---------------------------------------------------------

    if isinstance(result, dict) and result.get("action") == "move":
        source_files = result.get(
            "source_files",
            [],
        )

        destination = result.get(
            "destination",
            "",
        )

        destination_name = result.get(
            "destination_name",
            "destination",
        )

        # -----------------------------------------------------
        # NO MATCH
        # -----------------------------------------------------

        if not source_files:
            console.print(
                Panel(
                    "[yellow]The requested file could not "
                    "be found.[/yellow]\n\n"
                    "[bold white]Need help?[/bold white]\n"
                    "[green]python -m app.main --help[/green]",
                    title="[bold yellow]File Not Found[/bold yellow]",
                    border_style="yellow",
                )
            )

            log_event(
                user_request=request,
                action="move",
                risk_level="medium",
                approval_required=True,
                approval_result="NOT_APPLICABLE",
                execution_status="FAILED",
                result_summary="File not found for move",
            )

            return

        # -----------------------------------------------------
        # MULTIPLE MATCHES
        # -----------------------------------------------------

        if len(source_files) > 1:
            console.print(
                Panel(
                    "[yellow]Multiple files matched "
                    "the request.[/yellow]\n\n"
                    "I will not move multiple files automatically.\n\n"
                    "[dim]Please specify the exact file or "
                    "directory.[/dim]",
                    title="[bold yellow]Multiple Matches[/bold yellow]",
                    border_style="yellow",
                )
            )

            console.print()

            show_file_table(source_files)

            log_event(
                user_request=request,
                action="ambiguous",
                risk_level="medium",
                approval_required=True,
                approval_result="NOT_APPLICABLE",
                execution_status="AMBIGUOUS",
                result_summary=f"Ambiguous: {len(source_files)} matching files found",
            )

            return

        # -----------------------------------------------------
        # EXACT SOURCE FILE
        # -----------------------------------------------------

        source_file = source_files[0]["path"]

        # ------ POLICY: risk classification ------
        risk = get_action_risk("move")

        show_action_summary(
            action="Move",
            risk=risk,
            details={
                "File   ": source_file,
                "To     ": destination,
            },
        )

        # ------ APPROVAL ------
        if requires_approval(risk):
            approval = typer.confirm(f"Do you want to move this file to {destination_name}?")

            if not approval:
                console.print()

                console.print(
                    Panel(
                        "[bold red]No file was moved.[/bold red]",
                        title="[bold red]✗ Action Cancelled[/bold red]",
                        border_style="red",
                    )
                )

                log_event(
                    user_request=request,
                    action="move",
                    risk_level=risk,
                    approval_required=True,
                    approval_result="DENIED",
                    execution_status="CANCELLED",
                    result_summary=f"Cancelled move of {source_file} to {destination_name}",
                )

                return

        # -----------------------------------------------------
        # EXECUTE MOVE WITH RECOVERY & OBSERVATION
        # -----------------------------------------------------

        console.print()

        console.print("[bold yellow]● Moving approved file...[/bold yellow]")

        console.print()

        target_file = Path(destination) / Path(source_file).name

        exec_res = execute_action_with_recovery(
            action="move",
            action_func=move_file,
            func_args=(source_file, destination),
            source_path=source_file,
            destination_path=target_file,
            on_retry=lambda attempt, desc: console.print(
                f"[bold yellow]● Retrying move (Attempt {attempt + 1})... "
                f"Reason: {desc}[/bold yellow]"
            ),
        )

        status = exec_res["status"]
        summary = exec_res["result_summary"]

        if status == "SUCCESS":
            console.print(
                Panel(
                    f"[bold green]{summary}[/bold green]",
                    title="[bold green]✓ Task Completed[/bold green]",
                    border_style="green",
                )
            )
        elif status == FailureCategory.CONFLICT.value:
            console.print(
                Panel(
                    f"[bold yellow]Conflict Detected:[/bold yellow] Destination directory already "
                    f"contains a file named '{Path(source_file).name}'.\n\n"
                    f"[dim]The existing file at {target_file} was NOT overwritten. Source file "
                    f"remains intact at {source_file}.[/dim]",
                    title="[bold yellow]⚠ Destination Conflict[/bold yellow]",
                    border_style="yellow",
                )
            )
        else:
            console.print(
                Panel(
                    f"[bold red]{summary}[/bold red]",
                    title="[bold red]✗ Move Failed[/bold red]",
                    border_style="red",
                )
            )

        log_event(
            user_request=request,
            action="move",
            risk_level=risk,
            approval_required=True,
            approval_result="APPROVED",
            execution_status=status,
            result_summary=summary,
        )

        return

    # ---------------------------------------------------------
    # DELETE REQUEST
    # ---------------------------------------------------------

    delete_request = any(
        word in request_lower
        for word in [
            "delete",
            "remove",
            "erase",
        ]
    )

    if (
        isinstance(result, dict)
        and (result.get("action") == "delete" or (delete_request and "files" in result))
        and "files" in result
    ):
        if not result["found"]:
            console.print(
                Panel(
                    "[yellow]No files matched the deletion request."
                    "[/yellow]\n\n"
                    "[dim]Try describing the files differently, "
                    "or use another date.[/dim]\n\n"
                    "[bold white]Need help?[/bold white]\n"
                    "[green]python -m app.main --help[/green]",
                    title="[bold yellow]No Matches[/bold yellow]",
                    border_style="yellow",
                )
            )

            log_event(
                user_request=request,
                action="delete",
                risk_level="high",
                approval_required=True,
                approval_result="NOT_APPLICABLE",
                execution_status="FAILED",
                result_summary="No files matched deletion request",
            )

            return

        # ------ POLICY: risk classification ------
        risk = get_action_risk("delete")

        show_action_summary(
            action="Delete",
            risk=risk,
            details={
                "Files  ": f"{result['count']} file(s) matched",
            },
        )

        show_file_table(result["files"])

        console.print()

        console.print(f"[bold white]Total files:[/bold white] [cyan]{result['count']}[/cyan]")

        console.print()

        # ------ APPROVAL ------
        if requires_approval(risk):
            approval = typer.confirm(
                "⚠ This action is permanent. Do you want to delete ALL of these files?"
            )

            if not approval:
                console.print()

                console.print(
                    Panel(
                        "[bold red]No files were deleted.[/bold red]",
                        title="[bold red]✗ Action Cancelled[/bold red]",
                        border_style="red",
                    )
                )

                log_event(
                    user_request=request,
                    action="delete",
                    risk_level=risk,
                    approval_required=True,
                    approval_result="DENIED",
                    execution_status="CANCELLED",
                    result_summary=f"Cancelled deletion of {result['count']} file(s)",
                )

                return

        console.print()

        console.print("[bold yellow]● Deleting approved files...[/bold yellow]")

        console.print()

        all_verified = True
        for item in result["files"]:
            exec_res = execute_action_with_recovery(
                action="delete",
                action_func=delete_file,
                func_args=(item["path"],),
                source_path=item["path"],
                on_retry=lambda attempt, desc: console.print(
                    f"[bold yellow]● Retrying deletion of {item['path']} "
                    f"(Attempt {attempt + 1})... Reason: {desc}[/bold yellow]"
                ),
            )

            if exec_res["status"] == "SUCCESS":
                console.print(f"[green]✓[/green] {exec_res['result_summary']}")
            else:
                all_verified = False
                console.print(f"[red]✗[/red] {exec_res['result_summary']}")

        console.print()

        console.print(
            Panel(
                "[bold green]Deletion process completed.[/bold green]",
                title="[bold green]✓ Task Completed[/bold green]",
                border_style="green",
            )
        )

        exec_status = "SUCCESS" if all_verified else "FAILED"
        log_event(
            user_request=request,
            action="delete",
            risk_level=risk,
            approval_required=True,
            approval_result="APPROVED",
            execution_status=exec_status,
            result_summary=f"Deleted {result['count']} file(s)",
        )

        return

    # ---------------------------------------------------------
    # NORMAL FILE SEARCH
    # ---------------------------------------------------------

    if isinstance(result, dict) and "files" in result:
        if not result["found"]:
            _search_msg = result.get("message", "")
            _search_body = (
                f"[bold red]{_search_msg}[/bold red]\n\n"
                if _search_msg
                else "[yellow]No matching files were found.[/yellow]\n\n"
            )

            console.print(
                Panel(
                    _search_body + f"[dim]Searched:[/dim] "
                    f"{result.get('directory')}\n"
                    f"[dim]Filename:[/dim] "
                    f"{result.get('filename') or 'any'}\n"
                    f"[dim]Extension:[/dim] "
                    f"{result.get('extension') or 'any'}\n"
                    f"[dim]Date:[/dim] "
                    f"{result.get('start_date') or 'any'}"
                    f" to "
                    f"{result.get('end_date') or 'any'}\n\n"
                    "[bold white]Need help?[/bold white]\n"
                    "[green]python -m app.main --help[/green]",
                    title="[bold yellow]No Matches[/bold yellow]",
                    border_style="yellow",
                )
            )

            log_event(
                user_request=request,
                action="search",
                risk_level="low",
                approval_required=False,
                approval_result="NOT_REQUIRED",
                execution_status="SUCCESS",
                result_summary="Search completed: 0 files found",
            )

            return

        console.print("[bold green]✓ Search completed[/bold green]")

        console.print()

        console.print(
            f"[bold white]Found [/bold white]"
            f"[bold cyan]{result['count']}[/bold cyan]"
            f"[bold white] matching file(s)[/bold white]"
        )

        console.print()

        show_file_table(result["files"])

        console.print()

        console.print(
            Panel(
                "[bold green]Task completed successfully.[/bold green]",
                border_style="green",
            )
        )

        log_event(
            user_request=request,
            action="search",
            risk_level="low",
            approval_required=False,
            approval_result="NOT_REQUIRED",
            execution_status="SUCCESS",
            result_summary=f"Found {result['count']} matching file(s)",
        )

        return

    # ---------------------------------------------------------
    # NORMAL LLM RESPONSE
    # ---------------------------------------------------------

    if isinstance(result, str):
        console.print(
            Panel(
                result,
                title="[bold cyan]Agent Response[/bold cyan]",
                border_style="cyan",
            )
        )

        log_event(
            user_request=request,
            action="search",
            risk_level="low",
            approval_required=False,
            approval_result="NOT_REQUIRED",
            execution_status="SUCCESS",
            result_summary=result[:80],
        )

        return

    # ---------------------------------------------------------
    # UNKNOWN RESULT
    # ---------------------------------------------------------

    show_help_hint()

    log_event(
        user_request=request,
        action="unsupported",
        risk_level="low",
        approval_required=False,
        approval_result="NOT_APPLICABLE",
        execution_status="NOT_SUPPORTED",
        result_summary="Unknown agent response format",
    )


# -------------------------------------------------------------
# DIRECT FILE DELETION COMMAND
# -------------------------------------------------------------


@app.command(
    help="Delete one exact file after user approval.",
)
def delete(file_path: str):
    """Safely delete one exact file after user approval."""

    show_header()

    if not check_workspace_requirement("file deletion"):
        log_event(
            user_request=f"delete {file_path}",
            action="delete",
            risk_level="high",
            approval_required=False,
            approval_result="NOT_APPLICABLE",
            execution_status="BLOCKED",
            result_summary="Operation blocked: No workspaces configured",
        )
        return

    console.print("[bold yellow]⚠ High-risk action[/bold yellow]")

    console.print()

    console.print("[bold white]File scheduled for deletion:[/bold white]")

    console.print()

    console.print(
        Panel(
            file_path,
            border_style="yellow",
        )
    )

    console.print()

    approval = typer.confirm("Do you want to permanently delete this file?")

    if not approval:
        console.print()

        console.print(
            Panel(
                "[bold red]No file was deleted.[/bold red]",
                title="[bold red]✗ Action Cancelled[/bold red]",
                border_style="red",
            )
        )

        log_event(
            user_request=f"delete {file_path}",
            action="delete",
            risk_level="high",
            approval_required=True,
            approval_result="DENIED",
            execution_status="CANCELLED",
            result_summary=f"Cancelled direct deletion of {file_path}",
        )

        return

    console.print()

    console.print("[bold yellow]● Deleting file...[/bold yellow]")

    exec_res = execute_action_with_recovery(
        action="delete",
        action_func=delete_file,
        func_args=(file_path,),
        source_path=file_path,
        on_retry=lambda attempt, desc: console.print(
            f"[bold yellow]● Retrying deletion (Attempt {attempt + 1})... "
            f"Reason: {desc}[/bold yellow]"
        ),
    )

    result = exec_res["result_summary"]
    status = exec_res["status"]

    console.print()

    if status == "SUCCESS":
        console.print(
            Panel(
                f"[bold green]{result}[/bold green]",
                title="[bold green]✓ Task Completed[/bold green]",
                border_style="green",
            )
        )
    else:
        console.print(
            Panel(
                f"[bold red]{result}[/bold red]",
                title="[bold red]✗ Operation Failed[/bold red]",
                border_style="red",
            )
        )

    log_event(
        user_request=f"delete {file_path}",
        action="delete",
        risk_level="high",
        approval_required=True,
        approval_result="APPROVED",
        execution_status=status,
        result_summary=result,
    )


# -------------------------------------------------------------
# AUDIT LOGS COMMAND
# -------------------------------------------------------------


@app.command(
    help="Show recent persistent audit log entries.",
)
def logs(
    limit: int = typer.Option(
        10,
        "--limit",
        help="Number of recent audit entries to display.",
    ),
):
    """Display recent audit entries in a clean Rich table."""

    show_header()

    entries = get_recent_logs(limit=limit)

    if not entries:
        console.print(
            Panel(
                "[yellow]No audit log entries found.[/yellow]\n\n"
                "[dim]Run agent tasks to record persistent audit logs.[/dim]",
                title="[bold cyan]Audit Log[/bold cyan]",
                border_style="cyan",
            )
        )
        return

    table = Table(
        title=f"Audit Logs (Showing latest {len(entries)})",
        title_style="bold cyan",
        border_style="blue",
        show_lines=False,
    )

    table.add_column("ID", style="bold cyan", justify="right")
    table.add_column("Timestamp", style="green")
    table.add_column("Action", style="white")
    table.add_column("Risk", justify="center")
    table.add_column("Approval", justify="center")
    table.add_column("Status", justify="center")
    table.add_column("Request", style="white")

    approval_styles = {
        "APPROVED": "bold green",
        "DENIED": "bold red",
        "NOT_REQUIRED": "dim",
        "NOT_APPLICABLE": "dim",
    }

    status_styles = {
        "SUCCESS": "bold green",
        "CANCELLED": "bold yellow",
        "BLOCKED": "bold red",
        "FAILED": "bold red",
        "AMBIGUOUS": "bold yellow",
        "NOT_SUPPORTED": "dim red",
        "CONFLICT": "bold yellow",
        "POLICY_VIOLATION": "bold red",
        "VERIFICATION_FAILURE": "bold red",
        "EXECUTION_FAILURE": "bold red",
        "RETRY_EXHAUSTED": "bold red",
        "NEEDS_USER_INPUT": "bold yellow",
    }

    for row in entries:
        risk_val = row.get("risk_level", "low").lower()
        risk_color = RISK_COLORS.get(risk_val, "white")
        risk_text = f"[{risk_color}]{risk_val.upper()}[/{risk_color}]"

        appr_val = row.get("approval_result", "NOT_REQUIRED")
        appr_color = approval_styles.get(appr_val, "white")
        appr_text = f"[{appr_color}]{appr_val}[/{appr_color}]"

        status_val = row.get("execution_status", "SUCCESS")
        status_color = status_styles.get(status_val, "white")
        status_text = f"[{status_color}]{status_val}[/{status_color}]"

        req_text = row.get("user_request", "")
        if len(req_text) > 40:
            req_text = req_text[:37] + "..."

        table.add_row(
            str(row.get("id", "")),
            str(row.get("timestamp", "")),
            str(row.get("action", "")),
            risk_text,
            appr_text,
            status_text,
            req_text,
        )

    console.print(table)
    console.print()


# -------------------------------------------------------------
# TASK COMMANDS (MILESTONE 3)
# -------------------------------------------------------------


@app.command(
    name="task",
    help="Execute a stateful multi-step task.",
)
def task_command(
    request: str,
    compensate: bool = typer.Option(
        False,
        "--compensate",
        help="Enable safe rollback / compensation on step failure.",
    ),
):
    """Execute a multi-step task with dependency enforcement and per-step approval."""
    show_header()
    show_user_request(request)

    if not check_workspace_requirement("multi-step tasks"):
        log_event(
            user_request=request,
            action="task",
            risk_level="low",
            approval_required=False,
            approval_result="NOT_APPLICABLE",
            execution_status="BLOCKED",
            result_summary="Operation blocked: No workspaces configured",
        )
        return

    console.print("[bold blue]* Planning task steps...[/bold blue]")
    steps_spec = plan_task_steps(request)

    if not steps_spec:
        console.print(
            Panel(
                "[yellow]Could not determine steps for this task request.[/yellow]\n\n"
                "[dim]Try describing the task with clear actions (e.g. 'Move file.pdf to Documents "
                "and then rename it to final.pdf').[/dim]",
                title="[bold yellow]Task Planning Failed[/bold yellow]",
                border_style="yellow",
            )
        )
        return

    task = TaskManager.create_task(request, steps_spec)

    console.print()
    console.print(f"[bold cyan]Task Created:[/bold cyan] [white]{task.task_id}[/white]")
    console.print()

    plan_table = Table(
        title="Planned Steps",
        title_style="bold cyan",
        border_style="blue",
        show_lines=False,
    )
    plan_table.add_column("#", style="bold cyan", justify="right")
    plan_table.add_column("Action", style="white")
    plan_table.add_column("Arguments", style="dim")
    plan_table.add_column("Depends On", style="yellow", justify="center")

    for s in task.steps:
        dep_label = s.depends_on_step_id or "None"
        args_str = ", ".join(f"{k}={v}" for k, v in s.arguments.items())
        plan_table.add_row(str(s.step_order), s.action.upper(), args_str, dep_label)

    console.print(plan_table)
    console.print()

    def confirm_step(action: str, prompt_text: str, details: dict[str, Any]) -> bool:
        show_action_summary(
            action=action.capitalize(),
            risk=get_action_risk(action),
            details={k: str(v) for k, v in details.items()},
        )
        return typer.confirm(prompt_text)

    executed_task = StepExecutor.execute_task(
        task=task,
        confirm_callback=confirm_step,
        compensate_on_failure=compensate,
    )

    console.print()
    summary_table = Table(
        title=f"Task Execution Summary ({executed_task.task_id})",
        title_style="bold cyan",
        border_style="blue",
        show_lines=False,
    )
    summary_table.add_column("#", style="bold cyan", justify="right")
    summary_table.add_column("Action", style="white")
    summary_table.add_column("Status", justify="center")
    summary_table.add_column("Output / Result", style="white")

    step_status_colors = {
        StepStatus.SUCCESS: "bold green",
        StepStatus.FAILED: "bold red",
        StepStatus.SKIPPED: "dim yellow",
        StepStatus.WAITING_FOR_APPROVAL: "bold yellow",
        StepStatus.RUNNING: "bold cyan",
        StepStatus.PENDING: "white",
    }

    for s in executed_task.steps:
        st_color = step_status_colors.get(s.status, "white")
        st_text = f"[{st_color}]{s.status.value}[/{st_color}]"
        out_text = str(s.output) if s.output else (s.error_info or "")
        if len(out_text) > 50:
            out_text = out_text[:47] + "..."
        summary_table.add_row(str(s.step_order), s.action.upper(), st_text, out_text)

    console.print(summary_table)
    console.print()

    if executed_task.status == TaskStatus.COMPLETED:
        console.print(
            Panel(
                f"[bold green]Task {executed_task.task_id} completed successfully.[/bold green]",
                title="[bold green]Task Completed[/bold green]",
                border_style="green",
            )
        )
    elif executed_task.status == TaskStatus.PARTIAL_FAILURE:
        console.print(
            Panel(
                f"[bold yellow]Task {executed_task.task_id} partially failed.[/bold yellow]\n\n"
                f"[dim]{executed_task.error_summary or 'Some steps failed or were skipped.'}[/dim]",
                title="[bold yellow]Partial Failure[/bold yellow]",
                border_style="yellow",
            )
        )
    elif executed_task.status == TaskStatus.CANCELLED:
        console.print(
            Panel(
                f"[bold red]Task {executed_task.task_id} was cancelled by user.[/bold red]",
                title="[bold red]Task Cancelled[/bold red]",
                border_style="red",
            )
        )
    else:
        console.print(
            Panel(
                f"[bold red]Task {executed_task.task_id} failed.[/bold red]\n\n"
                f"[dim]{executed_task.error_summary or 'Execution failed.'}[/dim]",
                title="[bold red]Task Failed[/bold red]",
                border_style="red",
            )
        )


# -------------------------------------------------------------
# GOAL COMMAND (MILESTONE 5)
# -------------------------------------------------------------


@app.command(
    name="goal",
    help="Plan and execute a high-level goal using intelligent reasoning.",
)
def goal_command(
    goal: str,
    compensate: bool = typer.Option(
        True,
        "--compensate",
        help="Enable safe rollback / compensation on step failure.",
    ),
    auto_approve: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Automatically approve the synthesized plan.",
    ),
):
    """
    Intelligent Goal-to-Plan execution:
    1. Inspects authorized workspaces for real matching files.
    2. Synthesizes a structured TaskStep sequence.
    3. Validates the plan with PlanValidator (actions, paths, permissions, DAG).
    4. Shows a plan preview with cumulative risk.
    5. Asks for user approval before modifying files.
    6. Executes through the existing StepExecutor.
    """
    show_header()
    show_user_request(goal)

    if not check_workspace_requirement("goal planning"):
        log_event(
            user_request=goal,
            action="goal",
            risk_level="low",
            approval_required=False,
            approval_result="NOT_APPLICABLE",
            execution_status="BLOCKED",
            result_summary="Operation blocked: No workspaces configured",
        )
        return

    console.print("[bold blue]* Analyzing goal and inspecting authorized workspaces...[/bold blue]")
    plan = GoalPlanner.plan_goal(goal)

    # If zero files discovered or planning stopped safely, offer yes/no option to grant access to candidate folders
    if not plan.steps:
        if not os.getenv("PYTEST_CURRENT_TEST"):
            candidates = get_candidate_unauthorized_folders(goal, plan.summary)
            if candidates:
                folder_list_str = "\n".join(
                    f"  • [bold cyan]{name}[/bold cyan] ([dim]{path}[/dim])"
                    for name, path in candidates
                )
                console.print(
                    Panel(
                        f"[yellow]No matching files found in currently authorized workspaces.[/yellow]\n\n"
                        f"The following folder(s) were detected on your system but are not yet authorized:\n\n"
                        f"{folder_list_str}\n\n"
                        "[bold white]Would you like to grant access to these folders to locate and process your files?[/bold white]",
                        title="[bold yellow]Authorize Folder Access[/bold yellow]",
                        border_style="yellow",
                    )
                )
                if auto_approve or typer.confirm("Grant access to these folders and re-run?", default=True):
                    for name, path in candidates:
                        WorkspaceManager.add_workspace(
                            path,
                            name=name,
                            permissions=[
                                Permission.READ.value,
                                Permission.WRITE.value,
                                Permission.DELETE.value,
                            ],
                        )
                        console.print(f"[bold green]✓ Authorized '{name}' ({path})[/bold green]")

                    console.print()
                    console.print("[bold blue]* Re-analyzing goal with newly authorized workspace(s)...[/bold blue]")
                    plan = GoalPlanner.plan_goal(goal)

    if not plan.steps:
        console.print(
            Panel(
                f"[yellow]{plan.summary}[/yellow]\n\n"
                "[dim]Ensure files exist inside enabled workspaces with READ permission.[/dim]",
                title="[bold yellow]Goal Planning[/bold yellow]",
                border_style="yellow",
            )
        )
        log_event(
            user_request=goal,
            action="goal",
            risk_level="low",
            approval_required=False,
            approval_result="NOT_APPLICABLE",
            execution_status="NO_MATCH",
            result_summary=plan.summary,
        )
        return

    # Validate plan before showing preview
    valid, val_reason = PlanValidator.validate_plan(plan.steps)
    if not valid:
        console.print(
            Panel(
                f"[bold red]Plan rejected by policy validation:[/bold red]\n\n"
                f"[white]{val_reason}[/white]",
                title="[bold red]Policy Violation[/bold red]",
                border_style="red",
            )
        )
        log_event(
            user_request=goal,
            action="goal",
            risk_level=plan.cumulative_risk,
            approval_required=True,
            approval_result="NOT_APPLICABLE",
            execution_status="POLICY_VIOLATION",
            result_summary=val_reason,
        )
        return

    # Display Plan Preview
    console.print()
    if plan.target_workspace:
        console.print(
            f"[bold cyan]Target Workspace:[/bold cyan] [white]{plan.target_workspace.name}[/white] "
            f"([dim]{plan.target_workspace.canonical_path}[/dim])"
        )

    if plan.discovered_files:
        files_table = Table(
            title=f"Discovered Files ({len(plan.discovered_files)})",
            title_style="bold cyan",
            border_style="blue",
            show_lines=False,
        )
        files_table.add_column("#", style="bold cyan", justify="right")
        files_table.add_column("File Name", style="white")
        files_table.add_column("Path", style="dim")
        for idx, f in enumerate(plan.discovered_files, start=1):
            f_path = Path(f["path"])
            files_table.add_row(str(idx), f_path.name, str(f_path))
        console.print(files_table)
        console.print()

    # Steps preview table
    plan_table = Table(
        title="Proposed Execution Plan",
        title_style="bold cyan",
        border_style="blue",
        show_lines=False,
    )
    plan_table.add_column("#", style="bold cyan", justify="right")
    plan_table.add_column("Action", style="white")
    plan_table.add_column("Arguments", style="dim")
    plan_table.add_column("Depends On", style="yellow", justify="center")

    for s in plan.steps:
        dep_label = str(s.get("depends_on_order")) if s.get("depends_on_order") else "None"
        args_str = ", ".join(f"{k}={v}" for k, v in s.get("arguments", {}).items())
        plan_table.add_row(str(s["step_order"]), s["action"].upper(), args_str, dep_label)

    console.print(plan_table)
    console.print()

    # Risk badge
    risk_color = RISK_COLORS.get(plan.cumulative_risk, "white")
    console.print(
        f"[bold white]Cumulative Plan Risk:[/bold white] "
        f"[{risk_color}]{plan.cumulative_risk.upper()}[/{risk_color}]"
    )
    console.print()

    # Plan-level approval gate
    if plan.requires_approval and not auto_approve:
        approved = typer.confirm(f"Execute this plan? ({len(plan.steps)} steps)")
        if not approved:
            console.print(
                Panel(
                    "[bold yellow]Plan execution cancelled by user.[/bold yellow]\n\n"
                    "[dim]No directories were created, and no files were moved or deleted.[/dim]",
                    title="[bold yellow]Cancelled[/bold yellow]",
                    border_style="yellow",
                )
            )
            log_event(
                user_request=goal,
                action="goal",
                risk_level=plan.cumulative_risk,
                approval_required=True,
                approval_result="DENIED",
                execution_status="CANCELLED",
                result_summary="Plan approval denied by user",
            )
            return

    # Task instantiation & persistence
    task = TaskManager.create_task(goal, plan.steps)
    log_event(
        user_request=goal,
        action="goal",
        risk_level=plan.cumulative_risk,
        approval_required=plan.requires_approval,
        approval_result="APPROVED" if plan.requires_approval else "NOT_REQUIRED",
        execution_status="RUNNING",
        result_summary=f"Task {task.task_id} instantiated with {len(plan.steps)} steps",
    )

    console.print(f"[bold cyan]Task Created:[/bold cyan] [white]{task.task_id}[/white]")
    console.print()

    # Execute through existing StepExecutor
    def confirm_step(action: str, prompt_text: str, details: dict[str, Any]) -> bool:
        return True

    executed_task = StepExecutor.execute_task(
        task=task,
        confirm_callback=confirm_step,
        compensate_on_failure=compensate,
    )

    console.print()
    summary_table = Table(
        title=f"Task Execution Summary ({executed_task.task_id})",
        title_style="bold cyan",
        border_style="blue",
        show_lines=False,
    )
    summary_table.add_column("#", style="bold cyan", justify="right")
    summary_table.add_column("Action", style="white")
    summary_table.add_column("Status", justify="center")
    summary_table.add_column("Output / Result", style="white")

    step_status_colors = {
        StepStatus.SUCCESS: "bold green",
        StepStatus.FAILED: "bold red",
        StepStatus.SKIPPED: "dim yellow",
        StepStatus.WAITING_FOR_APPROVAL: "bold yellow",
        StepStatus.RUNNING: "bold cyan",
        StepStatus.PENDING: "white",
    }

    for step_item in executed_task.steps:
        st_color = step_status_colors.get(step_item.status, "white")
        st_text = f"[{st_color}]{step_item.status.value}[/{st_color}]"
        out_text = str(step_item.output) if step_item.output else (step_item.error_info or "")
        if len(out_text) > 50:
            out_text = out_text[:47] + "..."
        summary_table.add_row(
            str(step_item.step_order), step_item.action.upper(), st_text, out_text
        )

    console.print(summary_table)
    console.print()

    if executed_task.status == TaskStatus.COMPLETED:
        console.print(
            Panel(
                f"[bold green]Task {executed_task.task_id} completed successfully.[/bold green]",
                title="[bold green]Goal Completed[/bold green]",
                border_style="green",
            )
        )
    elif executed_task.status == TaskStatus.PARTIAL_FAILURE:
        console.print(
            Panel(
                f"[bold yellow]Task {executed_task.task_id} partially failed.[/bold yellow]\n\n"
                f"[dim]{executed_task.error_summary or 'Some steps failed or were skipped.'}[/dim]",
                title="[bold yellow]Partial Failure[/bold yellow]",
                border_style="yellow",
            )
        )
    elif executed_task.status == TaskStatus.CANCELLED:
        console.print(
            Panel(
                f"[bold red]Task {executed_task.task_id} was cancelled by user.[/bold red]",
                title="[bold red]Task Cancelled[/bold red]",
                border_style="red",
            )
        )
    else:
        console.print(
            Panel(
                f"[bold red]Task {executed_task.task_id} failed.[/bold red]\n\n"
                f"[dim]{executed_task.error_summary or 'Execution failed.'}[/dim]",
                title="[bold red]Task Failed[/bold red]",
                border_style="red",
            )
        )


@app.command(
    name="adaptive",
    help="Run an adaptive filesystem goal with observation and safe replanning (M6).",
)
def adaptive_command(
    goal: str,
    max_cycles: int = typer.Option(
        3,
        "--max-cycles",
        min=1,
        max=10,
        help="Maximum observe/plan/execute/replan cycles.",
    ),
    compensate: bool = typer.Option(
        True,
        "--compensate/--no-compensate",
        help="Compensate completed steps when a cycle partially fails.",
    ),
    auto_approve: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Automatically approve modifying plans.",
    ),
):
    """Execute a high-level goal using the M6 adaptive filesystem loop."""
    show_header()
    show_user_request(goal)

    if not check_workspace_requirement("adaptive goal execution"):
        return

    def render_cycle(cycle_no, plan, observation):
        total_files = sum(ws.file_count for ws in observation.workspaces)
        console.print(
            f"\n[bold blue]M6 Cycle {cycle_no}/{max_cycles}[/bold blue] — "
            f"observed {total_files} file(s) across {len(observation.workspaces)} workspace(s)."
        )

        if plan.discovered_files:
            table = Table(
                title=f"Observed Goal Inputs ({len(plan.discovered_files)})",
                title_style="bold cyan",
                border_style="blue",
            )
            table.add_column("#", justify="right")
            table.add_column("File")
            table.add_column("Path", style="dim")
            for idx, item in enumerate(plan.discovered_files, 1):
                path = Path(item["path"])
                table.add_row(str(idx), path.name, str(path))
            console.print(table)

        if plan.steps:
            table = Table(
                title="Validated Adaptive Plan",
                title_style="bold cyan",
                border_style="blue",
            )
            table.add_column("#", justify="right")
            table.add_column("Action")
            table.add_column("Arguments", style="dim")
            for step in plan.steps:
                args = ", ".join(
                    f"{key}={value}" for key, value in step.get("arguments", {}).items()
                )
                table.add_row(str(step["step_order"]), step["action"].upper(), args)
            console.print(table)
            risk_color = RISK_COLORS.get(plan.cumulative_risk, "white")
            console.print(
                f"Risk: [{risk_color}]{plan.cumulative_risk.upper()}[/{risk_color}] — "
                f"{plan.summary}"
            )
        else:
            console.print(f"[yellow]{plan.summary}[/yellow]")

    def approve(plan):
        if auto_approve or not plan.requires_approval:
            return True
        return typer.confirm(f"Execute this adaptive plan? ({len(plan.steps)} steps)")

    result = AdaptiveFilesystemAgent.run(
        goal,
        confirm_callback=approve,
        compensate_on_failure=compensate,
        max_cycles=max_cycles,
        on_cycle=render_cycle,
        on_retry=lambda attempt, reason: console.print(
            f"[yellow]Retry {attempt + 1}: {reason}[/yellow]"
        ),
    )

    status_style = {
        "COMPLETE": "bold green",
        "PARTIAL": "bold yellow",
        "BLOCKED": "bold red",
    }.get(result.status, "bold white")
    console.print()
    console.print(
        Panel(
            f"[{status_style}]{result.summary}[/{status_style}]\n\n"
            f"Cycles: {len(result.cycles)}\n"
            f"Observed filesystem changes: {len(result.observed_changes)}",
            title=f"[bold white]M6 Result: {result.status}[/bold white]",
            border_style=status_style.split()[-1],
        )
    )

    log_event(
        user_request=goal,
        action="adaptive_goal",
        risk_level=(result.cycles[-1].plan.cumulative_risk if result.cycles else "low"),
        approval_required=any(c.plan.requires_approval for c in result.cycles),
        approval_result="APPROVED" if result.status == "COMPLETE" else "NOT_APPLICABLE",
        execution_status=result.status,
        result_summary=result.summary,
    )


@app.command(
    name="tasks",
    help="List recent multi-step tasks.",
)
def tasks_command(
    limit: int = typer.Option(
        10,
        "--limit",
        help="Number of recent tasks to display.",
    ),
):
    """Display recent multi-step tasks in a clean Rich table."""
    show_header()
    tasks = TaskManager.list_tasks(limit=limit)

    if not tasks:
        console.print(
            Panel(
                "[yellow]No tasks found.[/yellow]\n\n"
                '[dim]Run multi-step tasks with: python -m app.main task "..."[/dim]',
                title="[bold cyan]Task History[/bold cyan]",
                border_style="cyan",
            )
        )
        return

    table = Table(
        title=f"Task History (Showing latest {len(tasks)})",
        title_style="bold cyan",
        border_style="blue",
        show_lines=False,
    )
    table.add_column("Task ID", style="bold cyan")
    table.add_column("Status", justify="center")
    table.add_column("Steps", justify="center")
    table.add_column("Created", style="green")
    table.add_column("Request", style="white")

    status_styles = {
        TaskStatus.COMPLETED: "bold green",
        TaskStatus.PARTIAL_FAILURE: "bold yellow",
        TaskStatus.FAILED: "bold red",
        TaskStatus.CANCELLED: "bold red",
        TaskStatus.RUNNING: "bold cyan",
        TaskStatus.PENDING: "white",
        TaskStatus.WAITING_FOR_APPROVAL: "bold yellow",
    }

    for t in tasks:
        st_color = status_styles.get(t.status, "white")
        st_text = f"[{st_color}]{t.status.value}[/{st_color}]"
        req = t.user_request
        if len(req) > 40:
            req = req[:37] + "..."
        table.add_row(t.task_id, st_text, str(len(t.steps)), t.created_at, req)

    console.print(table)
    console.print()


@app.command(
    name="task-status",
    help="View detailed status of a task and its steps.",
)
def task_status_command(task_id: str):
    """Display detailed execution state and steps for a specific task."""
    show_header()
    task = TaskManager.get_task(task_id)

    if not task:
        console.print(
            Panel(
                f"[yellow]Task not found: {task_id}[/yellow]",
                title="[bold yellow]Not Found[/bold yellow]",
                border_style="yellow",
            )
        )
        return

    status_styles = {
        TaskStatus.COMPLETED: "bold green",
        TaskStatus.PARTIAL_FAILURE: "bold yellow",
        TaskStatus.FAILED: "bold red",
        TaskStatus.CANCELLED: "bold red",
        TaskStatus.RUNNING: "bold cyan",
        TaskStatus.PENDING: "white",
        TaskStatus.WAITING_FOR_APPROVAL: "bold yellow",
    }
    st_color = status_styles.get(task.status, "white")
    st_text = f"[{st_color}]{task.status.value}[/{st_color}]"

    info_lines = [
        f"[bold white]Task ID :[/bold white] {task.task_id}",
        f"[bold white]Status  :[/bold white] {st_text}",
        f"[bold white]Created :[/bold white] {task.created_at}",
        f"[bold white]Updated :[/bold white] {task.updated_at}",
        f"[bold white]Request :[/bold white] {task.user_request}",
    ]
    if task.error_summary:
        info_lines.append(f"[bold red]Error   :[/bold red] {task.error_summary}")

    console.print(
        Panel(
            "\n".join(info_lines),
            title="[bold cyan]Task Details[/bold cyan]",
            border_style="cyan",
        )
    )
    console.print()

    table = Table(
        title=f"Steps ({len(task.steps)})",
        title_style="bold cyan",
        border_style="blue",
        show_lines=False,
    )
    table.add_column("#", style="bold cyan", justify="right")
    table.add_column("Step ID", style="white")
    table.add_column("Action", style="white")
    table.add_column("Status", justify="center")
    table.add_column("Attempts", justify="center")
    table.add_column("Output / Details", style="white")

    step_status_colors = {
        StepStatus.SUCCESS: "bold green",
        StepStatus.FAILED: "bold red",
        StepStatus.SKIPPED: "dim yellow",
        StepStatus.WAITING_FOR_APPROVAL: "bold yellow",
        StepStatus.RUNNING: "bold cyan",
        StepStatus.PENDING: "white",
    }

    for s in task.steps:
        st_c = step_status_colors.get(s.status, "white")
        st_badge = f"[{st_c}]{s.status.value}[/{st_c}]"
        detail = str(s.output) if s.output else (s.error_info or "")
        table.add_row(
            str(s.step_order), s.step_id, s.action.upper(), st_badge, str(s.attempts), detail
        )

    console.print(table)
    console.print()


# -------------------------------------------------------------
# TASK RESUME COMMAND (MILESTONE 4)
# -------------------------------------------------------------


@app.command(
    name="task-resume",
    help="Safely resume an interrupted or failed task from the first incomplete step.",
)
def task_resume_command(
    task_id: str = typer.Argument(..., help="Task ID to resume."),
    compensate: bool = typer.Option(
        False,
        "--compensate",
        help="Enable safe rollback / compensation on step failure.",
    ),
):
    """Safely resume an incomplete persistent task."""
    show_header()

    if not check_workspace_requirement("task resumption"):
        return

    task = TaskManager.get_task(task_id)
    if not task:
        console.print(
            Panel(
                f"[yellow]Task not found: {task_id}[/yellow]",
                title="[bold yellow]Not Found[/bold yellow]",
                border_style="yellow",
            )
        )
        return

    if task.status == TaskStatus.COMPLETED:
        console.print(
            Panel(
                f"[bold green]Task {task.task_id} is already completed.[/bold green]\n\n"
                "[dim]All steps were previously verified successfully. No resumption needed.[/dim]",
                title="[bold green]Already Completed[/bold green]",
                border_style="green",
            )
        )
        return

    completed_steps = [s for s in task.steps if s.status == StepStatus.SUCCESS]
    incomplete_steps = [s for s in task.steps if s.status != StepStatus.SUCCESS]

    if not incomplete_steps:
        console.print(
            Panel(
                f"[bold green]All steps in task {task.task_id} are already successful."
                f"[/bold green]",
                title="[bold green]Nothing to Resume[/bold green]",
                border_style="green",
            )
        )
        return

    first_incomplete = incomplete_steps[0]

    console.print(
        Panel(
            f"[bold white]Task ID            :[/bold white] {task.task_id}\n"
            f"[bold white]Current Status     :[/bold white] {task.status.value}\n"
            f"[bold white]Completed Steps    :[/bold white] {len(completed_steps)} of "
            f"{len(task.steps)}\n"
            f"[bold white]Resuming From Step :[/bold white] #{first_incomplete.step_order} "
            f"({first_incomplete.action.upper()})\n"
            f"[bold white]Original Request   :[/bold white] {task.user_request}",
            title="[bold cyan]Task Resume Details[/bold cyan]",
            border_style="cyan",
        )
    )
    console.print()

    # Reset incomplete steps to PENDING for fresh evaluation
    for s in incomplete_steps:
        TaskManager.update_step_state(s, StepStatus.PENDING, attempts=0, error_info=None)

    def confirm_step(action: str, prompt_text: str, details: dict[str, Any]) -> bool:
        show_action_summary(
            action=action.capitalize(),
            risk=get_action_risk(action),
            details={k: str(v) for k, v in details.items()},
        )
        return typer.confirm(prompt_text)

    executed_task = StepExecutor.execute_task(
        task=task,
        confirm_callback=confirm_step,
        compensate_on_failure=compensate,
    )

    console.print()
    summary_table = Table(
        title=f"Task Execution Summary ({executed_task.task_id})",
        title_style="bold cyan",
        border_style="blue",
        show_lines=False,
    )
    summary_table.add_column("#", style="bold cyan", justify="right")
    summary_table.add_column("Action", style="white")
    summary_table.add_column("Status", justify="center")
    summary_table.add_column("Output / Result", style="white")

    step_status_colors = {
        StepStatus.SUCCESS: "bold green",
        StepStatus.FAILED: "bold red",
        StepStatus.SKIPPED: "dim yellow",
        StepStatus.WAITING_FOR_APPROVAL: "bold yellow",
        StepStatus.RUNNING: "bold cyan",
        StepStatus.PENDING: "white",
    }

    for s in executed_task.steps:
        st_color = step_status_colors.get(s.status, "white")
        st_text = f"[{st_color}]{s.status.value}[/{st_color}]"
        out_text = str(s.output) if s.output else (s.error_info or "")
        if len(out_text) > 50:
            out_text = out_text[:47] + "..."
        summary_table.add_row(str(s.step_order), s.action.upper(), st_text, out_text)

    console.print(summary_table)
    console.print()

    if executed_task.status == TaskStatus.COMPLETED:
        console.print(
            Panel(
                f"[bold green]Task {executed_task.task_id} resumed and completed "
                f"successfully.[/bold green]",
                title="[bold green]Task Completed[/bold green]",
                border_style="green",
            )
        )
    elif executed_task.status == TaskStatus.PARTIAL_FAILURE:
        console.print(
            Panel(
                f"[bold yellow]Task {executed_task.task_id} partially failed on resumption."
                f"[/bold yellow]\n\n"
                f"[dim]{executed_task.error_summary or 'Some steps failed or were skipped.'}[/dim]",
                title="[bold yellow]Partial Failure[/bold yellow]",
                border_style="yellow",
            )
        )
    elif executed_task.status == TaskStatus.CANCELLED:
        console.print(
            Panel(
                f"[bold red]Task {executed_task.task_id} was cancelled by user on "
                f"resumption.[/bold red]",
                title="[bold red]Task Cancelled[/bold red]",
                border_style="red",
            )
        )
    else:
        console.print(
            Panel(
                f"[bold red]Task {executed_task.task_id} failed on resumption.[/bold red]\n\n"
                f"[dim]{executed_task.error_summary or 'Execution failed.'}[/dim]",
                title="[bold red]Task Failed[/bold red]",
                border_style="red",
            )
        )


# -------------------------------------------------------------
# WORKSPACE COMMANDS (MILESTONE 4)
# -------------------------------------------------------------


@app.command(
    name="workspace",
    help="Display configured workspaces and their permissions.",
)
def workspace_command():
    """Display configured workspaces and their permissions."""
    show_header()
    workspaces = WorkspaceManager.list_workspaces()

    if not workspaces:
        console.print(
            Panel(
                "[yellow]No workspaces configured.[/yellow]\n\n"
                "The agent requires at least one explicitly configured workspace to operate "
                "safely.\n\n"
                "[bold white]To add a workspace:[/bold white]\n"
                '  py -m app.main workspace-add "<path>" [--name "<label>"]\n\n'
                "[dim]Example:[/dim]\n"
                '  py -m app.main workspace-add "manual_test" --name "manual_test"',
                title="[bold yellow]No Configured Workspaces[/bold yellow]",
                border_style="yellow",
            )
        )
        return

    table = Table(
        title=f"Configured Workspaces ({len(workspaces)})",
        title_style="bold cyan",
        border_style="blue",
        show_lines=False,
    )
    table.add_column("Workspace ID", style="bold cyan")
    table.add_column("Name", style="white")
    table.add_column("Canonical Path", style="dim")
    table.add_column("Status", justify="center")
    table.add_column("Permissions", style="green")

    for ws in workspaces:
        status_text = (
            "[bold green]ENABLED[/bold green]" if ws.enabled else "[bold red]DISABLED[/bold red]"
        )
        perms_text = ", ".join(sorted(list(ws.permissions)))
        table.add_row(ws.workspace_id, ws.name, str(ws.canonical_path), status_text, perms_text)

    console.print(table)
    console.print()


@app.command(
    name="workspace-add",
    help="Add and authorize a new local directory as a persistent workspace.",
)
def workspace_add_command(
    path: str = typer.Argument(..., help="Path to local directory to authorize as workspace."),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Optional human-readable label."),
    permissions: str = typer.Option(
        "READ,WRITE,DELETE",
        "--permissions",
        "-p",
        help="Comma-separated permissions (READ, WRITE, DELETE).",
    ),
):
    """Add and persist a new workspace."""
    show_header()
    perm_list = [p.strip().upper() for p in permissions.split(",") if p.strip()]
    invalid_perms = [p for p in perm_list if p not in ("READ", "WRITE", "DELETE")]
    if invalid_perms:
        console.print(
            Panel(
                f"[bold red]Invalid permission(s): {', '.join(invalid_perms)}[/bold red]\n\n"
                "Allowed permissions are: READ, WRITE, DELETE",
                title="[bold red]Error[/bold red]",
                border_style="red",
            )
        )
        return

    try:
        ws = WorkspaceManager.add_workspace(
            path=path,
            name=name,
            permissions=perm_list,
        )
        perms_str = ", ".join(sorted(list(ws.permissions)))
        console.print(
            Panel(
                f"[bold green]Workspace authorized successfully![/bold green]\n\n"
                f"[bold white]ID          :[/bold white] {ws.workspace_id}\n"
                f"[bold white]Name        :[/bold white] {ws.name}\n"
                f"[bold white]Canonical   :[/bold white] {ws.canonical_path}\n"
                f"[bold white]Status      :[/bold white] ENABLED\n"
                f"[bold white]Permissions :[/bold white] {perms_str}",
                title="[bold green]Workspace Added[/bold green]",
                border_style="green",
            )
        )
    except Exception as e:
        console.print(
            Panel(
                f"[bold red]Failed to add workspace:[/bold red] {e}",
                title="[bold red]Error[/bold red]",
                border_style="red",
            )
        )


@app.command(
    name="workspace-remove",
    help="Remove a workspace from configuration without affecting task history.",
)
def workspace_remove_command(
    workspace_id: str = typer.Argument(..., help="Workspace ID to remove."),
):
    """Remove a workspace."""
    show_header()
    ws = WorkspaceManager.get_workspace(workspace_id)
    if not ws:
        console.print(
            Panel(
                f"[yellow]Workspace not found: {workspace_id}[/yellow]",
                title="[bold yellow]Not Found[/bold yellow]",
                border_style="yellow",
            )
        )
        return

    success = WorkspaceManager.remove_workspace(workspace_id)
    if success:
        console.print(
            Panel(
                f"[bold green]Workspace '{ws.name}' ({workspace_id}) removed "
                f"successfully.[/bold green]\n\n"
                "[dim]Historical tasks and audit logs remain preserved.[/dim]",
                title="[bold green]Workspace Removed[/bold green]",
                border_style="green",
            )
        )
    else:
        console.print(
            Panel(
                f"[bold red]Failed to remove workspace: {workspace_id}[/bold red]",
                title="[bold red]Error[/bold red]",
                border_style="red",
            )
        )


@app.command(
    name="workspace-enable",
    help="Enable an existing workspace.",
)
def workspace_enable_command(
    workspace_id: str = typer.Argument(..., help="Workspace ID to enable."),
):
    """Enable a workspace."""
    show_header()
    ws = WorkspaceManager.get_workspace(workspace_id)
    if not ws:
        console.print(
            Panel(
                f"[yellow]Workspace not found: {workspace_id}[/yellow]",
                title="[bold yellow]Not Found[/bold yellow]",
                border_style="yellow",
            )
        )
        return

    WorkspaceManager.enable_workspace(workspace_id)
    console.print(
        Panel(
            f"[bold green]Workspace '{ws.name}' ({workspace_id}) is now ENABLED.[/bold green]",
            title="[bold green]Workspace Enabled[/bold green]",
            border_style="green",
        )
    )


@app.command(
    name="workspace-disable",
    help="Disable an existing workspace.",
)
def workspace_disable_command(
    workspace_id: str = typer.Argument(..., help="Workspace ID to disable."),
):
    """Disable a workspace."""
    show_header()
    ws = WorkspaceManager.get_workspace(workspace_id)
    if not ws:
        console.print(
            Panel(
                f"[yellow]Workspace not found: {workspace_id}[/yellow]",
                title="[bold yellow]Not Found[/bold yellow]",
                border_style="yellow",
            )
        )
        return

    WorkspaceManager.disable_workspace(workspace_id)
    console.print(
        Panel(
            f"[bold yellow]Workspace '{ws.name}' ({workspace_id}) is now "
            f"DISABLED.[/bold yellow]\n\n"
            "[dim]Agent operations inside this workspace will be blocked until re-enabled.[/dim]",
            title="[bold yellow]Workspace Disabled[/bold yellow]",
            border_style="yellow",
        )
    )


@app.command(
    name="workspace-permissions",
    help="Update permissions for an existing workspace (e.g. READ or READ,WRITE).",
)
def workspace_permissions_command(
    workspace_id: str = typer.Argument(..., help="Workspace ID to modify."),
    permissions: str = typer.Argument(
        ..., help="Comma-separated permissions (READ, WRITE, DELETE)."
    ),
):
    """Update permissions for a workspace."""
    show_header()
    ws = WorkspaceManager.get_workspace(workspace_id)
    if not ws:
        console.print(
            Panel(
                f"[yellow]Workspace not found: {workspace_id}[/yellow]",
                title="[bold yellow]Not Found[/bold yellow]",
                border_style="yellow",
            )
        )
        return

    perm_list = [p.strip().upper() for p in permissions.split(",") if p.strip()]
    invalid_perms = [p for p in perm_list if p not in ("READ", "WRITE", "DELETE")]
    if invalid_perms:
        console.print(
            Panel(
                f"[bold red]Invalid permission(s): {', '.join(invalid_perms)}[/bold red]\n\n"
                "Allowed permissions are: READ, WRITE, DELETE",
                title="[bold red]Error[/bold red]",
                border_style="red",
            )
        )
        return

    WorkspaceManager.set_permissions(workspace_id, perm_list)
    perms_str = ", ".join(sorted(perm_list))
    console.print(
        Panel(
            f"[bold green]Updated permissions for '{ws.name}' ({workspace_id}):[/bold green]\n\n"
            f"[bold white]New Permissions:[/bold white] {perms_str}",
            title="[bold green]Permissions Updated[/bold green]",
            border_style="green",
        )
    )


# ==============================================================================
# MILESTONE 7: GENERAL LOCAL SYSTEM TOOLS
# ==============================================================================


@app.command(
    name="sys-info",
    help="Inspect system hardware, OS specifications, and resource utilization (M7).",
)
def sys_info_command():
    """Display structured hardware and operating system statistics."""
    show_header()
    info = get_system_info()

    table = Table(
        title="System & Resource Information",
        title_style="bold cyan",
        border_style="blue",
    )
    table.add_column("Property", style="bold white", width=25)
    table.add_column("Value", style="cyan")

    table.add_row("Operating System", f"{info['os']} ({info['release']})")
    table.add_row("OS Version", info["version"])
    table.add_row("Architecture", info["architecture"])
    table.add_row("Processor / CPUs", f"{info['processor']} ({info['cpu_count']} cores)")
    table.add_row("Total RAM", f"{info['ram_total_gb']} GB")
    ram_free_pct = 100 - info["ram_percent"]
    table.add_row("Available RAM", f"{info['ram_available_gb']} GB ({ram_free_pct:.1f}% free)")
    table.add_row("Disk Total", f"{info['disk_total_gb']} GB")
    table.add_row("Disk Used", f"{info['disk_used_gb']} GB ({info['disk_percent']}% used)")
    table.add_row("Disk Free", f"{info['disk_free_gb']} GB")

    console.print(table)


@app.command(
    name="ps",
    help="List or search running system processes safely (M7).",
)
def ps_command(
    limit: int = typer.Option(15, "--limit", "-n", help="Maximum processes to display."),
    sort_by: str = typer.Option("memory", "--sort-by", "-s", help="Sort order: 'memory' or 'cpu'."),
    filter_name: Optional[str] = typer.Option(
        None, "--filter", "-f", help="Filter by process name."
    ),
):
    """List running processes with memory and CPU usage."""
    show_header()
    processes = list_processes(limit=limit, sort_by=sort_by, name_filter=filter_name)

    title = f"Top {len(processes)} Processes (Sorted by {sort_by.upper()})"
    if filter_name:
        title += f" [Filter: '{filter_name}']"

    table = Table(title=title, title_style="bold cyan", border_style="blue")
    table.add_column("PID", justify="right", style="cyan", width=8)
    table.add_column("Process Name", style="bold white", width=30)
    table.add_column("Memory (MB)", justify="right", style="green", width=14)
    table.add_column("Memory %", justify="right", style="yellow", width=10)
    table.add_column("CPU %", justify="right", style="magenta", width=10)
    table.add_column("Status", style="dim white", width=10)

    for p in processes:
        table.add_row(
            str(p["pid"]),
            p["name"],
            f"{p['memory_mb']:.2f}",
            f"{p['memory_percent']:.1f}%",
            f"{p['cpu_percent']:.1f}%",
            p["status"],
        )

    console.print(table)


@app.command(
    name="clipboard",
    help="Inspect or write to system clipboard safely (M7).",
)
def clipboard_command(
    write: Optional[str] = typer.Option(None, "--write", "-w", help="Text to copy to clipboard."),
):
    """Read from or write to the system clipboard."""
    show_header()
    if write is not None:
        risk = get_action_risk("write_clipboard")
        snippet = write[:80] + ("..." if len(write) > 80 else "")
        r_color = RISK_COLORS[risk]
        console.print(
            Panel(
                f"[bold yellow]Action:[/bold yellow] Write to Clipboard\n"
                f"[bold yellow]Content:[/bold yellow] {snippet}\n"
                f"[bold yellow]Risk:[/bold yellow] [{r_color}]{risk.upper()}[/{r_color}]",
                title="Clipboard Write Request",
                border_style="yellow",
            )
        )
        if not typer.confirm("Copy this text to clipboard?"):
            console.print("[yellow]Clipboard write cancelled by user.[/yellow]")
            return

        success = write_clipboard(write)
        if success:
            console.print(f"[bold green]Copied {len(write)} characters to clipboard![/bold green]")
        else:
            console.print("[bold red]Failed to write to clipboard.[/bold red]")
    else:
        content = read_clipboard()
        console.print(
            Panel(
                content if content else "[dim italic](Clipboard is currently empty)[/dim italic]",
                title=f"Clipboard Content ({len(content)} chars)",
                border_style="cyan",
            )
        )


@app.command(
    name="archive",
    help="Inspect or safely extract archive files (.zip, .tar) (M7).",
)
def archive_command(
    archive_path: str = typer.Argument(..., help="Path to archive file."),
    extract_to: Optional[str] = typer.Option(
        None, "--extract-to", "-x", help="Destination folder for extraction."
    ),
):
    """Inspect archive contents or safely extract with Zip Slip protection."""
    show_header()
    path_obj = Path(archive_path).expanduser().resolve()
    if not path_obj.exists():
        console.print(f"[bold red]Archive file not found: {path_obj}[/bold red]")
        return

    if extract_to:
        dest_obj = Path(extract_to).expanduser().resolve()
        risk = get_action_risk("extract_archive")
        r_color = RISK_COLORS[risk]
        console.print(
            Panel(
                f"[bold yellow]Archive:[/bold yellow] {path_obj.name}\n"
                f"[bold yellow]Destination:[/bold yellow] {dest_obj}\n"
                f"[bold yellow]Risk:[/bold yellow] [{r_color}]{risk.upper()}[/{r_color}]",
                title="Archive Extraction Request",
                border_style="yellow",
            )
        )
        if not typer.confirm("Extract archive?"):
            console.print("[yellow]Extraction cancelled by user.[/yellow]")
            return

        try:
            res = extract_archive(path_obj, dest_obj)
            console.print(
                Panel(
                    f"[bold green]Extracted {res['extracted_count']} files "
                    f"to {dest_obj}[/bold green]",
                    title="Extraction Complete",
                    border_style="green",
                )
            )
        except Exception as e:
            console.print(f"[bold red]Extraction failed: {e}[/bold red]")
    else:
        try:
            report = inspect_archive(path_obj)
            title = (
                f"Archive: {path_obj.name} "
                f"({report['total_files']} files, {report['total_uncompressed_bytes']} bytes)"
            )
            table = Table(
                title=title,
                title_style="bold cyan",
                border_style="blue",
            )
            table.add_column("#", justify="right", width=5)
            table.add_column("Filename", style="bold white")
            table.add_column("Size (Bytes)", justify="right", style="green", width=14)
            table.add_column("Type", style="cyan", width=10)

            for i, m in enumerate(report["members"][:25], 1):
                table.add_row(
                    str(i),
                    m["filename"],
                    str(m["size_bytes"]),
                    "DIR" if m["is_dir"] else "FILE",
                )

            if len(report["members"]) > 25:
                extra = len(report["members"]) - 25
                table.add_row("...", f"... and {extra} more items", "...", "...")

            console.print(table)
        except Exception as e:
            console.print(f"[bold red]Failed to inspect archive: {e}[/bold red]")


@app.command(
    name="metadata",
    help="Inspect detailed file metadata, MIME type, and cryptographic hashes (M7).",
)
def metadata_command(
    file_path: str = typer.Argument(..., help="Path to target file."),
):
    """Inspect structured file metadata and checksums."""
    show_header()
    path_obj = Path(file_path).expanduser().resolve()
    if not path_obj.exists():
        console.print(f"[bold red]File not found: {path_obj}[/bold red]")
        return

    try:
        meta = get_file_metadata(path_obj)
        table = Table(
            title=f"Metadata: {path_obj.name}",
            title_style="bold cyan",
            border_style="blue",
        )
        table.add_column("Attribute", style="bold white", width=20)
        table.add_column("Value", style="cyan")

        table.add_row("Full Path", meta["path"])
        table.add_row("File Size", f"{meta['human_size']} ({meta['size_bytes']} bytes)")
        table.add_row("MIME Type", meta["mime_type"])
        table.add_row("Created", meta["created_at"])
        table.add_row("Modified", meta["modified_at"])
        table.add_row("Permissions", meta["permissions_octal"])
        if meta.get("line_count") is not None:
            table.add_row("Line Count", str(meta["line_count"]))
        if meta.get("sha256"):
            table.add_row("SHA-256", meta["sha256"])
        if meta.get("md5"):
            table.add_row("MD5", meta["md5"])

        console.print(table)
    except Exception as e:
        console.print(f"[bold red]Failed to read metadata: {e}[/bold red]")


# =============================================================================
# MILESTONE 8: PRODUCTIVITY & INTEGRATION CLI COMMANDS
# =============================================================================


@app.command(
    name="read-doc",
    help="Safely read document content within authorized workspaces (M8).",
)
def read_doc_command(
    file_path: str = typer.Argument(..., help="Path to document (.txt, .md, .pdf, .docx)."),
    max_chars: int = typer.Option(3000, help="Maximum characters to display."),
):
    """Read a document within authorized workspaces."""
    show_header()
    res = read_document(file_path, max_chars=max_chars)
    if not res.get("success"):
        console.print(f"[bold red]Error: {res.get('error')}[/bold red]")
        return

    doc_title = (
        f"[bold cyan]Document: {res['filename']} "
        f"({res['character_count']} chars, {res['workspace']})[/bold cyan]"
    )
    console.print(
        Panel(
            res["content"],
            title=doc_title,
            border_style="green",
        )
    )


@app.command(
    name="summarize-doc",
    help="Summarize a document's key points without modifying the file (M8).",
)
def summarize_doc_command(
    file_path: str = typer.Argument(..., help="Path to document to summarize."),
):
    """Summarize document content within authorized workspaces."""
    show_header()
    res = summarize_document(file_path)
    if not res.get("success"):
        console.print(f"[bold red]Error: {res.get('error')}[/bold red]")
        return

    body = f"[bold]Summary:[/bold]\n{res['summary']}\n\n[bold]Key Points:[/bold]\n"
    for pt in res.get("key_points", []):
        body += f"• {pt}\n"

    console.print(
        Panel(
            body.strip(),
            title=f"[bold cyan]Summary: {res['filename']} ({res['word_count']} words)[/bold cyan]",
            border_style="blue",
        )
    )


@app.command(
    name="browser-fetch",
    help="Safely extract readable text from a URL without script execution (M8).",
)
def browser_fetch_command(
    url: str = typer.Argument(..., help="Target HTTP/HTTPS URL."),
    max_chars: int = typer.Option(2000, help="Maximum characters to preview."),
):
    """Fetch clean readable web page content."""
    show_header()
    res = browser_fetch_page(url, max_chars=max_chars)
    if not res.get("success"):
        console.print(f"[bold red]Error: {res.get('error')}[/bold red]")
        return

    console.print(
        Panel(
            res["content"],
            title=f"[bold cyan]{res['title']} ({res['length']} chars)[/bold cyan]",
            border_style="cyan",
        )
    )


@app.command(
    name="email-draft",
    help="Stage a local email draft without sending (M8).",
)
def email_draft_command(
    to: str = typer.Argument(..., help="Recipient email address."),
    subject: str = typer.Argument(..., help="Email subject line."),
    body: str = typer.Option(
        "Automated message staged via Local Agentic Automation.", help="Draft body text."
    ),
):
    """Stage a local email draft."""
    show_header()
    res = email_draft(to, subject, body)
    if not res.get("success"):
        console.print(f"[bold red]Error: {res.get('error')}[/bold red]")
        return

    console.print(
        Panel(
            f"[bold green]Draft #{res['draft_id']} staged successfully.[/bold green]\n"
            f"[cyan]To:[/cyan] {to}\n[cyan]Subject:[/cyan] {subject}\n[cyan]Body:[/cyan] {body}",
            title="[bold blue]Email Draft Saved[/bold blue]",
        )
    )


@app.command(
    name="calendar-events",
    help="List scheduled calendar events (M8).",
)
def calendar_events_command():
    """List calendar appointments."""
    show_header()
    res = calendar_list_events()
    events = res.get("events", [])
    if not events:
        console.print("[yellow]No calendar events found.[/yellow]")
        return

    table = Table(title="Calendar Events", title_style="bold cyan")
    table.add_column("ID", width=6)
    table.add_column("Title", style="bold white")
    table.add_column("Start Time", style="green")
    table.add_column("End Time", style="green")
    table.add_column("Description", style="cyan")

    for ev in events:
        table.add_row(
            str(ev["id"]), ev["title"], ev["start_time"], ev["end_time"], ev.get("description", "")
        )

    console.print(table)


@app.command(
    name="github-issues",
    help="List issues in a GitHub repository (M8).",
)
def github_issues_command(
    repo: str = typer.Argument(..., help="Repository in 'owner/repo' format."),
    state: str = typer.Option("open", help="Issue state (open/closed/all)."),
):
    """Query GitHub repository issues."""
    show_header()
    res = github_list_issues(repo, state=state)
    if not res.get("success"):
        console.print(f"[bold red]Error querying GitHub: {res.get('error')}[/bold red]")
        return

    issues = res.get("issues", [])
    if not issues:
        console.print(f"[yellow]No {state} issues found in {repo}.[/yellow]")
        return

    table = Table(title=f"GitHub Issues: {repo}", title_style="bold cyan")
    table.add_column("#", width=6)
    table.add_column("Title", style="bold white")
    table.add_column("Author", style="cyan")
    table.add_column("State", style="green")

    for iss in issues:
        table.add_row(
            str(iss.get("number")),
            iss.get("title", ""),
            iss.get("author", ""),
            iss.get("state", ""),
        )

    console.print(table)


@app.command(
    name="ui",
    help="Launch the local interactive web dashboard (FastAPI + Modern Web UI).",
)
def ui_command(
    host: str = typer.Option(
        "0.0.0.0", help="Host interface to bind (0.0.0.0 allows phone/LAN access)."
    ),
    port: int = typer.Option(8000, help="Port to run the dashboard web server on."),
    open_browser: bool = typer.Option(True, help="Automatically open browser."),
    reload: bool = typer.Option(False, help="Enable auto-reload on code change."),
):
    """Launch the Web Dashboard."""
    import webbrowser

    import uvicorn

    from app.tools.attendance_tools import get_local_ip

    show_header()
    lan_ip = get_local_ip()
    local_url = f"http://127.0.0.1:{port}"
    network_url = f"http://{lan_ip}:{port}" if lan_ip != "127.0.0.1" else None

    panel_text = (
        f"[bold green]Local Agentic Dashboard starting:[/bold green]\n"
        f"  Local Access:   [bold cyan]{local_url}[/bold cyan]\n"
    )
    if network_url:
        panel_text += (
            f"  Network Access: [bold cyan]{network_url}[/bold cyan] (Scan or visit on mobile)\n"
        )
    panel_text += (
        "[dim]Powered by FastAPI, Uvicorn, and Ollama (qwen2.5:3b).\nPress Ctrl+C to stop.[/dim]"
    )

    console.print(
        Panel(
            panel_text,
            title="[bold blue]Web Dashboard[/bold blue]",
            border_style="cyan",
        )
    )

    if open_browser:
        try:
            webbrowser.open(local_url)
        except Exception:
            pass

    uvicorn.run("app.server:server_app", host=host, port=port, reload=reload, log_level="info")


@app.command(
    name="https-ui",
    help="Launch dashboard over HTTPS (required for camera access on mobile/LAN).",
)
def https_ui_command(
    host: str = typer.Option("0.0.0.0", help="Host interface to bind."),
    port: int = typer.Option(8443, help="HTTPS port (default 8443)."),
    open_browser: bool = typer.Option(True, help="Automatically open browser."),
):
    """Launch the Web Dashboard with HTTPS so phone cameras work on LAN."""
    import webbrowser

    import uvicorn

    from app.ssl_cert import ensure_ssl_cert
    from app.tools.attendance_tools import get_local_ip

    show_header()
    console.print("[bold cyan]Setting up HTTPS for LAN camera access...[/bold cyan]")

    try:
        cert_file, key_file = ensure_ssl_cert()
    except Exception as e:
        console.print(f"[bold red]Failed to generate SSL certificate: {e}[/bold red]")
        console.print("[yellow]Install cryptography:  pip install cryptography[/yellow]")
        raise typer.Exit(1)

    lan_ip = get_local_ip()
    local_url = f"https://127.0.0.1:{port}"
    network_url = f"https://{lan_ip}:{port}" if lan_ip != "127.0.0.1" else None

    panel_text = (
        f"[bold green]Local Agentic Dashboard (HTTPS):[/bold green]\n"
        f"  Local Access:   [bold cyan]{local_url}[/bold cyan]\n"
    )
    if network_url:
        panel_text += (
            f"  Network Access: [bold cyan]{network_url}[/bold cyan]\n"
            "  [bold yellow]→ Open on phone, tap 'Advanced' → 'Proceed' "
            "to trust the cert.[/bold yellow]\n"
        )
    panel_text += (
        f"\n[dim]Camera access (QR scan) requires HTTPS — this is why we need the cert.\n"
        f"Certificate: {cert_file}\n"
        f"Press Ctrl+C to stop.[/dim]"
    )

    console.print(
        Panel(
            panel_text,
            title="[bold blue]Web Dashboard — HTTPS Mode[/bold blue]",
            border_style="green",
        )
    )

    if open_browser:
        try:
            webbrowser.open(local_url)
        except Exception:
            pass

    uvicorn.run(
        "app.server:server_app",
        host=host,
        port=port,
        ssl_certfile=cert_file,
        ssl_keyfile=key_file,
        log_level="info",
    )


if __name__ == "__main__":
    app()
