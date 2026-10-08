"""
LLM Provider Abstraction Module.

Supports local open-weight models via Ollama (e.g. qwen2.5:3b) as well
as cloud providers (Groq) with lazy initialization and offline CI mocking.
"""

import os
from typing import Any, List, Optional

from dotenv import load_dotenv

load_dotenv()


class OllamaChatWrapper:
    """
    Lightweight LangChain-compatible chat model wrapper around the local Ollama client.
    Allows streaming and invoke() returning an object with .content attribute.
    """

    def __init__(
        self,
        model: str = "qwen2.5:3b",
        temperature: float = 0.0,
        host: Optional[str] = None,
    ):
        self.model = model
        self.temperature = temperature
        resolved_host = (
            host if host is not None else os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        )
        self.host = str(resolved_host or "http://localhost:11434").rstrip("/")

    def invoke(self, messages_or_prompt: Any) -> Any:
        """Invokes the Ollama model with messages or a prompt string via native REST API."""
        import json
        import urllib.request

        system_persona = (
            "You are a local, private AI Executive Assistant "
            "operating directly on the user's computer. "
            "You maintain complete offline privacy. Never use emojis. "
            "Be polite, professional, concise, and helpful."
        )

        if isinstance(messages_or_prompt, str):
            prompt_str = messages_or_prompt
            messages = [
                {"role": "system", "content": system_persona},
                {"role": "user", "content": prompt_str},
            ]
        elif isinstance(messages_or_prompt, list):
            messages = []
            has_system = False
            for m in messages_or_prompt:
                extracted_role = getattr(m, "type", None) or getattr(m, "role", "user") or "user"
                role_str = str(extracted_role)
                if role_str == "human":
                    role_str = "user"
                elif role_str == "system":
                    role_str = "system"
                    has_system = True
                elif role_str == "ai":
                    role_str = "assistant"
                content_str = str(getattr(m, "content", str(m)))
                messages.append({"role": role_str, "content": content_str})
            if not has_system:
                messages.insert(0, {"role": "system", "content": system_persona})
        else:
            messages = [
                {"role": "system", "content": system_persona},
                {"role": "user", "content": str(messages_or_prompt)},
            ]

        payload = {
            "model": self.model,
            "messages": messages,
            "options": {"temperature": self.temperature},
            "stream": False,
        }
        url = f"{self.host}/api/chat"
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        reply_content = data.get("message", {}).get("content", "")

        class ResponseContent:
            def __init__(self, content: str):
                self.content = content

            def __str__(self) -> str:
                return self.content

        return ResponseContent(reply_content)

    def bind_tools(self, tools: List[Any]) -> "OllamaChatWrapper":
        """Returns self for tool-calling compatibility."""
        return self


def get_configured_llm() -> Any:
    """
    Factory function returning the configured LLM instance based on LLM_PROVIDER.
    Supports 'ollama' (local qwen2.5:3b) and 'groq' (cloud).
    """
    provider = os.getenv("LLM_PROVIDER", "ollama").lower()
    if provider == "ollama":
        model_name = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
        return OllamaChatWrapper(model=model_name)

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY environment variable is missing or empty. "
            "Please set GROQ_API_KEY in your environment or .env file, "
            "or set LLM_PROVIDER=ollama to use your local Ollama model."
        )

    from langchain_groq import ChatGroq

    return ChatGroq(
        model=os.getenv("GROQ_MODEL", "openai/gpt-oss-20b"),
        api_key=api_key,  # type: ignore[arg-type]
        temperature=0,
    )


def is_ollama_online(host: Optional[str] = None) -> bool:
    """Checks whether the local Ollama daemon port is open and responsive."""
    import socket
    from urllib.parse import urlparse

    resolved_host = (
        host if host is not None else os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    )
    h = str(resolved_host or "http://localhost:11434").rstrip("/")
    try:
        parsed = urlparse(h)
        hostname = parsed.hostname or "127.0.0.1"
        port = parsed.port or 11434
        with socket.create_connection((hostname, port), timeout=0.25):
            return True
    except OSError:
        return False


get_chat_model = get_configured_llm
LLMClient = OllamaChatWrapper
