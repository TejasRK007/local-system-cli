import json
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq

from app.tools.filesystem import search_files

load_dotenv()


llm = ChatGroq(
    model="openai/gpt-oss-20b",
    api_key=os.getenv("GROQ_API_KEY"),  # type: ignore[arg-type]
    temperature=0,
)


tools = [search_files]

llm_with_tools = llm.bind_tools(tools)


KNOWN_DIRECTORIES = {
    "downloads": Path.home() / "Downloads",
    "documents": Path.home() / "Documents",
    "desktop": Path.home() / "Desktop",
}


def extract_move_request(request: str):
    """
    Understand a natural-language file move request.

    This function only extracts information.
    It does not move any files.
    """

    prompt = f"""
You are an intent extraction component for a local file automation system.

Determine whether the user's request is a file MOVE request.

User request:
{request}

Supported directories:

- Downloads
- Documents
- Desktop

If this is a move request, return ONLY valid JSON:

{{
    "action": "move",
    "filename": "exact filename",
    "source_directory": "Downloads or Documents or Desktop or null",
    "destination_directory": "Downloads or Documents or Desktop"
}}

Rules:

1. Preserve the filename exactly as provided.
2. Do not invent a filename.
3. If the source directory is not specified, use null.
4. The destination directory must be Downloads, Documents, or Desktop.
5. Do not perform the move.
6. Return JSON only.

If this is NOT a move request, return:

{{
    "action": "none"
}}
"""

    response = llm.invoke(prompt)

    content = str(response.content).strip()

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {"action": "none"}


def extract_rename_request(request: str):
    """
    Understand a natural-language file rename request.

    This function only extracts information.
    It does not rename any files.
    """

    prompt = f"""
You are an intent extraction component for a local file automation system.

Determine whether the user's request is a file RENAME request.

User request:
{request}

Supported directories:

- Downloads
- Documents
- Desktop

If this is a rename request, return ONLY valid JSON:

{{
    "action": "rename",
    "filename": "exact current filename",
    "new_name": "exact new filename",
    "directory": "Downloads or Documents or Desktop or null"
}}

Rules:

1. Preserve the current filename exactly as provided.
2. Preserve the new filename exactly as provided.
3. Do not invent filenames.
4. If the directory is not specified, use null.
5. The directory, if provided, must be Downloads, Documents, or Desktop.
6. Do not perform the rename.
7. Return JSON only.

Example:

User:
Rename agent_renamed_test.txt to final_test.txt

Return:

{{
    "action": "rename",
    "filename": "agent_renamed_test.txt",
    "new_name": "final_test.txt",
    "directory": null
}}

If this is NOT a rename request, return:

{{
    "action": "none"
}}
"""

    response = llm.invoke(prompt)

    content = str(response.content).strip()

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {"action": "none"}


def run_agent(request: str):
    current_date = datetime.now().strftime("%Y-%m-%d")
    current_day = datetime.now().strftime("%A")

    # ---------------------------------------------------------
    # FIRST: CHECK FOR MOVE INTENT
    # ---------------------------------------------------------

    move_intent = extract_move_request(request)

    if move_intent.get("action") == "move":

        filename = move_intent.get("filename")
        source_directory = move_intent.get("source_directory")
        destination_directory = move_intent.get(
            "destination_directory"
        )

        if not filename or not destination_directory:
            return "UNSUPPORTED_REQUEST"

        if source_directory:
            # User explicitly named a directory — search only there.
            search_result = search_files.invoke(
                {
                    "directory": source_directory,
                    "extension": "",
                    "filename": filename,
                    "start_date": "",
                    "end_date": "",
                }
            )
            matched_files = search_result.get("files", [])
        else:
            # No directory specified — search ALL allowed directories
            # so ambiguous filenames are always detected.
            matched_files = []
            for dir_name in KNOWN_DIRECTORIES:
                search_result = search_files.invoke(
                    {
                        "directory": dir_name,
                        "extension": "",
                        "filename": filename,
                        "start_date": "",
                        "end_date": "",
                    }
                )
                matched_files.extend(search_result.get("files", []))

        return {
            "action": "move",
            "source_files": matched_files,
            "count": len(matched_files),
            "destination": str(
                KNOWN_DIRECTORIES[
                    destination_directory.lower()
                ]
            ),
            "destination_name": destination_directory,
            "directory_specified": bool(source_directory),
        }

    # ---------------------------------------------------------
    # SECOND: CHECK FOR RENAME INTENT
    # ---------------------------------------------------------

    rename_intent = extract_rename_request(request)

    if rename_intent.get("action") == "rename":

        filename = rename_intent.get("filename")
        new_name = rename_intent.get("new_name")
        directory = rename_intent.get("directory")

        if not filename or not new_name:
            return "UNSUPPORTED_REQUEST"

        if directory:
            # User explicitly named a directory — search only there.
            search_result = search_files.invoke(
                {
                    "directory": directory,
                    "extension": "",
                    "filename": filename,
                    "start_date": "",
                    "end_date": "",
                }
            )
            matched_files = search_result.get("files", [])
        else:
            # No directory specified — search ALL allowed directories
            # so ambiguous filenames are always detected.
            matched_files = []
            for dir_name in KNOWN_DIRECTORIES:
                search_result = search_files.invoke(
                    {
                        "directory": dir_name,
                        "extension": "",
                        "filename": filename,
                        "start_date": "",
                        "end_date": "",
                    }
                )
                matched_files.extend(search_result.get("files", []))

        return {
            "action": "rename",
            "source_files": matched_files,
            "count": len(matched_files),
            "new_name": new_name,
            "directory_specified": bool(directory),
        }

    # ---------------------------------------------------------
    # NORMAL SEARCH / DELETE AGENT
    # ---------------------------------------------------------

    system_prompt = f"""
You are the reasoning component of a local computer automation agent.

Today's date is {current_date}.
Today is {current_day}.

Your available tool is:

search_files(
    directory,
    extension,
    filename,
    start_date,
    end_date
)

The tool searches files by:

- filename
- extension
- directory
- creation date

Supported tasks:

1. Find files by extension.
2. Find a specific file by filename.
3. Search Downloads, Documents, or Desktop.
4. Filter files by creation date.
5. Understand natural-language dates.
6. Find files for deletion.

DIRECTORIES:

The allowed top-level directories are:

- Downloads
- Documents
- Desktop

These are separate directories.

For normal searches with no directory specified,
use Downloads.

For specific filename searches with no directory specified,
use Downloads.

FILENAME SEARCH:

If the user gives a specific filename, put it in
the filename argument.

DELETE REQUESTS:

If the user asks to delete files,
first use search_files to identify the exact files.

Do NOT delete anything yourself.

The application handles:

- approval
- deletion
- path validation
- verification

DATE SEARCH:

Convert relative dates such as:

- today
- yesterday
- the day before yesterday
- last week

into concrete YYYY-MM-DD dates.

EXTENSION SEARCH:

PDF = .pdf
Word = .docx
Text = .txt

UNSUPPORTED REQUESTS:

If the request is unrelated to the supported
file-management capabilities or is meaningless,
return exactly:

UNSUPPORTED_REQUEST
"""

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=request),
    ]

    response = llm_with_tools.invoke(messages)

    if not response.tool_calls:

        response_text = str(response.content).strip()

        if response_text == "UNSUPPORTED_REQUEST":
            return "UNSUPPORTED_REQUEST"

        unsupported_phrases = [
            "i'm not sure what you're asking",
            "i’m not sure what you’re asking",
            "could you please clarify",
            "i don't understand",
            "i don’t understand",
            "i cannot help",
            "i can't help",
            "i can’t help",
        ]

        response_lower = response_text.lower()

        if any(
            phrase in response_lower
            for phrase in unsupported_phrases
        ):
            return "UNSUPPORTED_REQUEST"

        return response.content

    results = []

    for tool_call in response.tool_calls:

        if tool_call["name"] == "search_files":

            result = search_files.invoke(
                tool_call["args"]
            )

            results.append(result)

    if len(results) == 1:
        return results[0]

    return results
