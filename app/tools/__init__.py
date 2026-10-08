from .archive_tools import extract_archive, inspect_archive
from .browser_tools import browser_download_file, browser_fetch_page, browser_search
from .calendar_tools import calendar_check_conflict, calendar_create_event, calendar_list_events
from .clipboard import read_clipboard, write_clipboard
from .document_tools import read_document, summarize_document
from .email_tools import (
    email_draft,
    email_generate_reply,
    email_get_account,
    email_link_account,
    email_mark_all_read,
    email_read,
    email_search,
    email_send,
    email_summarize,
    email_sync,
)
from .file_actions import create_directory, delete_file, move_file, rename_file
from .filesystem import search_files
from .github_tools import github_create_issue, github_inspect_pr, github_list_issues
from .metadata_tools import get_file_metadata
from .system_tools import find_process, get_system_info, list_processes

__all__ = [
    "search_files",
    "create_directory",
    "delete_file",
    "move_file",
    "rename_file",
    "get_system_info",
    "list_processes",
    "find_process",
    "read_clipboard",
    "write_clipboard",
    "inspect_archive",
    "extract_archive",
    "get_file_metadata",
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
    "email_summarize",
    "email_generate_reply",
    "email_get_account",
    "email_link_account",
    "email_mark_all_read",
    "email_sync",
    "calendar_list_events",
    "calendar_check_conflict",
    "calendar_create_event",
    "github_list_issues",
    "github_inspect_pr",
    "github_create_issue",
]
