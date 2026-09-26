import typer

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from app.agent import run_agent
from app.tools.file_actions import delete_file


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
    text.append("You: ", style="bold cyan")
    text.append(request, style="white")

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

    table.add_column("#", style="bold cyan", justify="right")
    table.add_column("File", style="white")
    table.add_column("Created", style="green")

    for index, item in enumerate(files, start=1):
        table.add_row(
            str(index),
            item["path"],
            item["created"],
        )

    console.print(table)


def show_capabilities():
    """Display the capabilities of the current agent."""

    capabilities = (
        "[bold cyan]📁 File Management[/bold cyan]\n"
        "  • Find files by extension\n"
        "  • Search Downloads, Documents, and Desktop\n"
        "  • Filter files by creation date\n"
        "  • Understand natural date expressions\n"
        "  • Delete files with approval\n"
        "  • Verify deletion\n\n"

        "[bold cyan]🤖 Natural Language[/bold cyan]\n"
        "  • Understand normal human instructions\n"
        "  • Convert requests into tool actions\n"
        "  • Understand different ways of asking for the same task\n\n"

        "[bold yellow]🔐 Safety[/bold yellow]\n"
        "  • Destructive actions require approval\n"
        "  • Exact files are shown before deletion\n"
        "  • File paths are checked before deletion\n\n"

        "[bold green]💡 Example requests[/bold green]\n"
        '  • "Show me PDFs from yesterday"\n'
        '  • "Find Word documents in Downloads"\n'
        '  • "Show me PDFs from September 20 to September 24"\n'
        '  • "Delete the PDFs I downloaded yesterday"\n'
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
            '"What can you do for me?"[/cyan]\n\n'
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

    console.print("[bold cyan]Commands[/bold cyan]")

    console.print(
        "  [cyan]agent[/cyan]    "
        "Give the agent a natural-language task."
    )

    console.print(
        "  [cyan]delete[/cyan]   "
        "Delete one exact file after user approval."
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
            '"Show me PDFs from the day before yesterday"\n\n'
            '  python -m app.main agent '
            '"Delete the PDFs I downloaded yesterday"\n\n'
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
        return

    # ---------------------------------------------------------
    # DELETE REQUEST
    # ---------------------------------------------------------

    delete_request = any(
        word in request_lower
        for word in ["delete", "remove", "erase"]
    )

    if delete_request and isinstance(result, dict) and "files" in result:

        if not result["found"]:
            console.print(
                Panel(
                    "[yellow]No files matched the deletion request.[/yellow]\n\n"
                    "[dim]Try describing the files differently, "
                    "or use another date.[/dim]\n\n"
                    "[bold white]Need help?[/bold white]\n"
                    "[green]python -m app.main --help[/green]",
                    title="[bold yellow]No Matches[/bold yellow]",
                    border_style="yellow",
                )
            )
            return

        console.print(
            Panel(
                "[bold yellow]"
                "Approval is required before deletion."
                "[/bold yellow]",
                title="[bold yellow]⚠ High-Risk Action[/bold yellow]",
                border_style="yellow",
            )
        )

        console.print()

        show_file_table(result["files"])

        console.print()

        console.print(
            f"[bold white]Total files:[/bold white] "
            f"[cyan]{result['count']}[/cyan]"
        )

        console.print()

        approval = typer.confirm(
            "Do you want to permanently delete ALL of these files?"
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

            return

        console.print()

        console.print(
            "[bold yellow]● Deleting approved files...[/bold yellow]"
        )

        console.print()

        for item in result["files"]:
            deletion_result = delete_file(item["path"])

            if "Verified" in deletion_result:
                console.print(
                    f"[green]✓[/green] {deletion_result}"
                )
            else:
                console.print(
                    f"[red]✗[/red] {deletion_result}"
                )

        console.print()

        console.print(
            Panel(
                "[bold green]Deletion process completed.[/bold green]",
                title="[bold green]✓ Task Completed[/bold green]",
                border_style="green",
            )
        )

        return

    # ---------------------------------------------------------
    # NORMAL FILE SEARCH
    # ---------------------------------------------------------

    if isinstance(result, dict) and "files" in result:

        if not result["found"]:
            console.print(
                Panel(
                    "[yellow]No matching files were found.[/yellow]\n\n"
                    f"[dim]Searched:[/dim] "
                    f"{result.get('directory')}\n"
                    f"[dim]Extension:[/dim] "
                    f"{result.get('extension')}\n"
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

        show_file_table(result["files"])

        console.print()

        console.print(
            Panel(
                "[bold green]Task completed successfully.[/bold green]",
                border_style="green",
            )
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

        return

    # ---------------------------------------------------------
    # UNKNOWN RESULT
    # ---------------------------------------------------------

    show_help_hint()


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

        return

    console.print()

    console.print(
        "[bold yellow]● Deleting file...[/bold yellow]"
    )

    result = delete_file(file_path)

    console.print()

    if "Verified" in result:
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


if __name__ == "__main__":
    app()