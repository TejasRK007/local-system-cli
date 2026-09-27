import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from app.agent import run_agent
from app.database import get_recent_logs, log_event
from app.policy import RISK_COLORS, get_action_risk, requires_approval
from app.tools.file_actions import (
    delete_file,
    move_file,
    rename_file,
)

console = Console()


app = typer.Typer(
    help="Local Agentic Automation System - AI-powered task automation."
)


def show_header():
    """Display the application header."""

    console.print()

    console.print(
        Panel(
            "[bold white]LOCAL AGENTIC AUTOMATION SYSTEM[/bold white]\n"
            "[cyan]AI Task Automation CLI[/cyan]",
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
            title="[bold yellow]⚠ Action Summary[/bold yellow]",
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
            '[cyan]python -m app.main agent '
            '"Show me PDFs from yesterday"[/cyan]\n'
            '[cyan]python -m app.main agent '
            '"Find Word documents in Downloads"[/cyan]\n'
            '[cyan]python -m app.main agent '
            '"Find Internship Offer Letter - Tejas RK.pdf"[/cyan]\n'
            '[cyan]python -m app.main agent '
            '"Move agent_move_test.txt to Documents"[/cyan]\n'
            '[cyan]python -m app.main agent '
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

    console.print(
        "[bold white]AI-powered local task automation.[/bold white]"
    )

    console.print()

    console.print(
        "[bold cyan]Commands[/bold cyan]"
    )

    console.print(
        "  [cyan]agent[/cyan]    "
        "Give the agent a natural-language task."
    )

    console.print(
        "  [cyan]delete[/cyan]   "
        "Delete one exact file after user approval."
    )

    console.print(
        "  [cyan]logs[/cyan]     "
        "Show recent persistent audit log entries."
    )

    console.print()

    show_capabilities()

    console.print()

    console.print(
        Panel(
            "[bold cyan]Natural language examples[/bold cyan]\n\n"

            '  python -m app.main agent '
            '"Show me PDFs from yesterday"\n\n'

            '  python -m app.main agent '
            '"Find Word documents in Downloads"\n\n'

            '  python -m app.main agent '
            '"Find Internship Offer Letter - Tejas RK.pdf"\n\n'

            '  python -m app.main agent '
            '"Show me PDFs from the day before yesterday"\n\n'

            '  python -m app.main agent '
            '"Delete the PDFs I downloaded yesterday"\n\n'

            '  python -m app.main agent '
            '"Move Internship Offer Letter - Tejas RK.pdf to Documents"\n\n'

            '  python -m app.main agent '
            '"Rename agent_renamed_test.txt to final_test.txt"\n\n'

            '  python -m app.main agent '
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

    if any(
        phrase in request_lower
        for phrase in capability_phrases
    ):

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

    # ---------------------------------------------------------
    # AGENT PROCESSING
    # ---------------------------------------------------------

    console.print(
        "[bold blue]● Understanding request...[/bold blue]"
    )

    result = run_agent(request)

    console.print(
        "[bold blue]● Processing tools...[/bold blue]"
    )

    console.print()

    # ---------------------------------------------------------
    # UNSUPPORTED / UNCLEAR REQUEST
    # ---------------------------------------------------------

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

        return

    # ---------------------------------------------------------
    # RENAME REQUEST
    # ---------------------------------------------------------

    if (
        isinstance(result, dict)
        and result.get("action") == "rename"
    ):

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
                "Example: \"Rename file.txt [bold]in Downloads[/bold] "
                "to new.txt\"[/dim]"
                if not directory_specified
                else "[dim]Multiple files with the same name exist in that directory.[/dim]"
            )

            console.print(
                Panel(
                    f"[bold yellow]Ambiguous request:[/bold yellow] "
                    f"{len(source_files)} matching files were found.\n\n"
                    "I will not rename multiple files automatically.\n\n"
                    + scope_hint,

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
            approval = typer.confirm(
                f"Do you want to rename this file to {new_name}?"
            )

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
        # EXECUTE RENAME
        # -----------------------------------------------------

        console.print()

        console.print(
            "[bold yellow]● Renaming approved file...[/bold yellow]"
        )

        console.print()

        rename_result = rename_file(
            source_file,
            new_name,
        )

        # -----------------------------------------------------
        # RENAME SUCCESS
        # -----------------------------------------------------

        if "Verified:" in rename_result:

            console.print(
                Panel(
                    f"[bold green]{rename_result}[/bold green]",

                    title="[bold green]✓ Task Completed[/bold green]",
                    border_style="green",
                )
            )

            log_event(
                user_request=request,
                action="rename",
                risk_level=risk,
                approval_required=True,
                approval_result="APPROVED",
                execution_status="SUCCESS",
                result_summary=rename_result,
            )

        # -----------------------------------------------------
        # RENAME FAILURE
        # -----------------------------------------------------

        else:

            console.print(
                Panel(
                    f"[bold red]{rename_result}[/bold red]",

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
                execution_status="FAILED",
                result_summary=rename_result,
            )

        return

    # ---------------------------------------------------------
    # MOVE REQUEST
    # ---------------------------------------------------------

    if (
        isinstance(result, dict)
        and result.get("action") == "move"
    ):

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
            approval = typer.confirm(
                f"Do you want to move this file to {destination_name}?"
            )

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
        # EXECUTE MOVE
        # -----------------------------------------------------

        console.print()

        console.print(
            "[bold yellow]● Moving approved file...[/bold yellow]"
        )

        console.print()

        move_result = move_file(
            source_file,
            destination,
        )

        # -----------------------------------------------------
        # MOVE SUCCESS
        # -----------------------------------------------------

        if "Verified:" in move_result:

            console.print(
                Panel(
                    f"[bold green]{move_result}[/bold green]",

                    title="[bold green]✓ Task Completed[/bold green]",
                    border_style="green",
                )
            )

            log_event(
                user_request=request,
                action="move",
                risk_level=risk,
                approval_required=True,
                approval_result="APPROVED",
                execution_status="SUCCESS",
                result_summary=move_result,
            )

        # -----------------------------------------------------
        # MOVE FAILURE
        # -----------------------------------------------------

        else:

            console.print(
                Panel(
                    f"[bold red]{move_result}[/bold red]",

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
                execution_status="FAILED",
                result_summary=move_result,
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
        delete_request
        and isinstance(result, dict)
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

        show_file_table(
            result["files"]
        )

        console.print()

        console.print(
            f"[bold white]Total files:[/bold white] "
            f"[cyan]{result['count']}[/cyan]"
        )

        console.print()

        # ------ APPROVAL ------
        if requires_approval(risk):
            approval = typer.confirm(
                "⚠ This action is permanent. "
                "Do you want to delete ALL of these files?"
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

        console.print(
            "[bold yellow]● Deleting approved files...[/bold yellow]"
        )

        console.print()

        all_verified = True
        for item in result["files"]:

            deletion_result = delete_file(
                item["path"]
            )

            if "Verified" in deletion_result:

                console.print(
                    f"[green]✓[/green] "
                    f"{deletion_result}"
                )

            else:
                all_verified = False
                console.print(
                    f"[red]✗[/red] "
                    f"{deletion_result}"
                )

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

    if (
        isinstance(result, dict)
        and "files" in result
    ):

        if not result["found"]:

            console.print(
                Panel(
                    "[yellow]No matching files were found.[/yellow]\n\n"

                    f"[dim]Searched:[/dim] "
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

        console.print(
            "[bold green]✓ Search completed[/bold green]"
        )

        console.print()

        console.print(
            f"[bold white]Found [/bold white]"
            f"[bold cyan]{result['count']}[/bold cyan]"
            f"[bold white] matching file(s)[/bold white]"
        )

        console.print()

        show_file_table(
            result["files"]
        )

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

    console.print(
        "[bold yellow]⚠ High-risk action[/bold yellow]"
    )

    console.print()

    console.print(
        "[bold white]File scheduled for deletion:[/bold white]"
    )

    console.print()

    console.print(
        Panel(
            file_path,
            border_style="yellow",
        )
    )

    console.print()

    approval = typer.confirm(
        "Do you want to permanently delete this file?"
    )

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

    console.print(
        "[bold yellow]● Deleting file...[/bold yellow]"
    )

    result = delete_file(
        file_path
    )

    console.print()

    if "Verified" in result:

        console.print(
            Panel(
                f"[bold green]{result}[/bold green]",

                title="[bold green]✓ Task Completed[/bold green]",
                border_style="green",
            )
        )

        log_event(
            user_request=f"delete {file_path}",
            action="delete",
            risk_level="high",
            approval_required=True,
            approval_result="APPROVED",
            execution_status="SUCCESS",
            result_summary=result,
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
            execution_status="FAILED",
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
    )
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


if __name__ == "__main__":
    app()
