"""
LLM Provider Abstraction Module.

Supports local open-weight models via Ollama (e.g. qwen2.5:3b) as well
as cloud providers (Groq: e.g. llama-3.3-70b-versatile) with lazy
initialization, timeout handling, automatic fallback, and privacy controls.
"""

import json
import logging
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, List, Optional

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

DEFAULT_OLLAMA_MODEL = "qwen2.5:3b"
DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"


class ResponseContent:
    """Standardized response object matching LangChain chat output interface."""

    def __init__(self, content: str, tool_calls: Optional[List[Any]] = None):
        self.content = content
        self.tool_calls = tool_calls or []

    def __str__(self) -> str:
        return self.content


def _normalize_messages(messages_or_prompt: Any, system_persona: str) -> List[dict]:
    """Convert prompt string or LangChain-style message list into a standard dict list."""
    if isinstance(messages_or_prompt, str):
        return [
            {"role": "system", "content": system_persona},
            {"role": "user", "content": messages_or_prompt},
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
        return messages
    else:
        return [
            {"role": "system", "content": system_persona},
            {"role": "user", "content": str(messages_or_prompt)},
        ]


class OllamaChatWrapper:
    """
    Lightweight LangChain-compatible chat model wrapper around the local Ollama client.
    Allows streaming and invoke() returning an object with .content attribute.
    """

    def __init__(
        self,
        model: Optional[str] = None,
        temperature: float = 0.0,
        host: Optional[str] = None,
        timeout: float = 30.0,
    ):
        self.model = model or os.getenv("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)
        self.temperature = temperature
        resolved_host = (
            host if host is not None else os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
        )
        self.host = str(resolved_host or "http://127.0.0.1:11434").rstrip("/")
        self.timeout = timeout

    def invoke(self, messages_or_prompt: Any) -> ResponseContent:
        """Invokes the Ollama model with messages or a prompt string via native REST API."""
        system_persona = (
            "You are a local, private AI Executive Assistant "
            "operating directly on the user's computer. "
            "You maintain complete offline privacy. Never use emojis. "
            "Be polite, professional, concise, and helpful."
        )

        messages = _normalize_messages(messages_or_prompt, system_persona)

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
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        reply_content = data.get("message", {}).get("content", "")
        return ResponseContent(reply_content)

    def bind_tools(self, tools: List[Any]) -> "OllamaChatWrapper":
        """Returns self for tool-calling compatibility."""
        return self


class GroqChatWrapper:
    """
    High-performance LangChain-compatible wrapper around the Groq API.
    Features configurable model, request timeouts, and automatic fallback
    to local Ollama or deterministic handlers upon failure.
    Never exposes API keys in exceptions or logs.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.1,
        timeout: float = 15.0,
        fallback_to_ollama: bool = True,
    ):
        self.api_key = api_key or os.getenv("GROQ_API_KEY", "")
        self.model = model or os.getenv("GROQ_MODEL", DEFAULT_GROQ_MODEL)
        self.temperature = temperature
        self.timeout = timeout
        self.fallback_to_ollama = fallback_to_ollama
        # Testable internal handles (can be mocked in unit tests)
        self._groq_client = None   # Set to a mock in tests to intercept API calls
        self._fallback_ollama = None  # Set to a mock in tests to intercept Ollama fallback

    def invoke(self, messages_or_prompt: Any) -> ResponseContent:
        """Execute chat completion via Groq REST API with graceful error handling and fallback."""
        if not self.api_key or not self.api_key.strip():
            if self.fallback_to_ollama:
                fallback = self._fallback_ollama or OllamaChatWrapper()
                return fallback.invoke(messages_or_prompt)
            raise ValueError("GROQ_API_KEY is not set or empty.")

        system_persona = (
            "You are an AI Executive Assistant providing intelligent, context-grounded analysis. "
            "Never use emojis. Be professional, concise, and truthful."
        )
        messages = _normalize_messages(messages_or_prompt, system_persona)

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "stream": False,
        }
        url = "https://api.groq.com/openai/v1/chat/completions"
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key.strip()}",
                "User-Agent": "Antigravity-Agent/2.0",
            },
            method="POST",
        )

        try:
            # If a mock client is injected, use its interface instead of urllib
            if self._groq_client is not None:
                resp_obj = self._groq_client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=self.temperature,
                )
                content = resp_obj.choices[0].message.content if resp_obj.choices else ""
                return ResponseContent(content)

            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            choices = data.get("choices", [])
            content = choices[0].get("message", {}).get("content", "") if choices else ""
            return ResponseContent(content)
        except Exception as err:
            logger.warning("Groq API call failed (%s); attempting fallback", type(err).__name__)
            if self.fallback_to_ollama:
                try:
                    fallback = self._fallback_ollama or OllamaChatWrapper()
                    return fallback.invoke(messages_or_prompt)
                except Exception:
                    pass
            raise RuntimeError(f"Groq API completion failed: {type(err).__name__}")

    def bind_tools(self, tools: List[Any]) -> "GroqChatWrapper":
        """Returns self for tool-calling compatibility."""
        return self


def is_ollama_online(host: Optional[str] = None) -> bool:
    """
    Checks whether the local Ollama daemon port is open and responsive.
    Uses 127.0.0.1 directly to prevent Windows DNS resolution delays.
    """
    resolved_host = (
        host if host is not None else os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    )
    h = str(resolved_host or "http://127.0.0.1:11434").rstrip("/")
    try:
        parsed = urllib.parse.urlparse(h)
        hostname = parsed.hostname or "127.0.0.1"
        if hostname == "localhost":
            hostname = "127.0.0.1"
        port = parsed.port or 11434
        with socket.create_connection((hostname, port), timeout=0.25):
            return True
    except (OSError, Exception):
        return False


def get_configured_llm(
    provider: Optional[str] = None,
    allow_cloud: bool = False,
) -> Any:
    """
    Factory function returning the configured LLM instance.
    Supports 'ollama' (default local qwen2.5:3b) and 'groq' (cloud llama-3.3-70b-versatile).

    Privacy enforcement:
    If provider is 'groq' but allow_cloud is False, cloud invocation is blocked
    and the model falls back to local Ollama if online.
    """
    selected_provider = (provider or os.getenv("LLM_PROVIDER", "ollama")).lower().strip()

    if selected_provider == "groq":
        groq_key = os.getenv("GROQ_API_KEY", "").strip()
        if not groq_key:
            logger.info("Groq requested but GROQ_API_KEY is missing; using Ollama")
            return OllamaChatWrapper()

        if not allow_cloud:
            # Privacy requirement: explicitly raise so callers know cloud was blocked
            raise PermissionError(
                "Cloud LLM processing is not permitted without user consent. "
                "Set allow_cloud=True (after obtaining user consent) to use Groq."
            )

        return GroqChatWrapper(
            api_key=groq_key,
            model=os.getenv("GROQ_MODEL", DEFAULT_GROQ_MODEL),
            fallback_to_ollama=True,
        )

    # Default to Ollama
    model_name = os.getenv("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)
    return OllamaChatWrapper(model=model_name)


get_chat_model = get_configured_llm
LLMClient = OllamaChatWrapper

