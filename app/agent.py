import os
from datetime import datetime

from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage

from app.tools.filesystem import search_files

load_dotenv()

llm = ChatGroq(
    model="openai/gpt-oss-20b",
    api_key=os.getenv("GROQ_API_KEY"),
    temperature=0,
)

tools = [search_files]
llm_with_tools = llm.bind_tools(tools)


def run_agent(request: str):
    current_date = datetime.now().strftime("%Y-%m-%d")
    current_day = datetime.now().strftime("%A")

    system_prompt = f"""
You are the reasoning component of a local computer automation agent.

Today's date is {current_date}.
Today is {current_day}.

Your available tool is:

search_files(
    directory,
    extension,
    start_date,
    end_date
)

The tool searches files by extension and creation date.

Supported tasks currently include:

1. Finding files by extension.
2. Finding files in Downloads, Documents, or Desktop.
3. Filtering files by creation date.
4. Understanding natural-language date expressions such as:
   - today
   - yesterday
   - the day before yesterday
   - last week
   - specific dates
   - date ranges
5. Finding files that the user wants to delete.
   The application, not you, handles the actual deletion and approval.

Important rules:

- Understand normal natural-language requests.
- Convert the user's request into appropriate tool arguments.
- If the user does not specify a directory for a file-search request,
  use "Downloads".
- For PDF requests, use ".pdf".
- For Word documents, use ".docx".
- For text files, use ".txt".
- Convert relative dates into concrete YYYY-MM-DD dates.
- Never invent file paths.
- Never claim that you deleted a file.
- Never execute deletion yourself.

Very important:

If the user's request is unrelated to the supported file-management
capabilities, or the request is meaningless, random text, or cannot
reasonably be understood as a supported task, DO NOT answer normally.

Instead, respond with exactly:

UNSUPPORTED_REQUEST

Examples of unsupported requests:

"pichsdbvcbdh"
"asdfghjkl"
"play a song"
"send an email"
"book me a flight"
"tell me a joke"

Examples of supported requests:

"Show me PDFs from yesterday"
"Find Word documents in Downloads"
"Show me files created today"
"Find PDFs from September 20 to September 24"
"Delete the PDFs I downloaded yesterday"

If the request is supported and requires searching files,
use the search_files tool.

If the request is unsupported, return exactly:
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

        # If the model refuses/doesn't understand a request,
        # normalize that into the application's unsupported state.
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
            result = search_files.invoke(tool_call["args"])
            results.append(result)

    if len(results) == 1:
        return results[0]

    return results