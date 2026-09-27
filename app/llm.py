import json
import os

from dotenv import load_dotenv
from groq import Groq

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))


def choose_tool(request: str) -> dict:
    prompt = f"""
You are the reasoning component of a local automation agent.

Available tool:
- filesystem.search: searches for files inside a directory.
  Arguments:
  - directory: directory to search
  - extension: file extension such as .pdf or .txt

User request:
{request}

Decide whether the filesystem.search tool should be used.

Return ONLY valid JSON in this format:

{{
    "tool": "filesystem.search",
    "directory": "~/Downloads",
    "extension": ".pdf"
}}

If the request does not require the filesystem tool, return:

{{
    "tool": "none"
}}
"""

    response = client.chat.completions.create(
        model="openai/gpt-oss-20b",
        messages=[
            {
                "role": "user",
                "content": prompt,
            }
        ],
    )

    content = response.choices[0].message.content or "{}"

    return json.loads(content)
