import json
from typing import AsyncGenerator

import httpx

from app.config import settings


# read=None (the previous setting) means "no gap between reads may exceed
# this" -- httpx's read timeout is per socket read, not a bound on total
# response time (https://www.python-httpx.org/advanced/timeouts/), so a
# generous read timeout does not cut off a long-but-actively-streaming
# answer. connect/write/pool stay short: those cover setup, not generation.
_UPSTREAM_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)


class UpstreamIncompleteError(RuntimeError):
    """The upstream connection ended before it signaled completion (no
    `done: true` from Ollama, no `data: [DONE]` from OpenAI).

    Without this, the async generator simply stops -- which looks identical
    to a clean finish to a caller that only checks whether iteration ended,
    such as `async for chunk in stream_llm_response(...): ...` followed by
    persisting the reply as complete. A dropped connection or a provider
    closing early would otherwise be saved as a normal, finished answer.
    """


async def stream_llm_response(messages: list[dict]) -> AsyncGenerator[str, None]:
    """Yields text chunks from whichever provider LLM_PROVIDER selects.

    Local dev uses Ollama so there is no per-token cost while iterating.
    The deployed environment uses OpenAI because a t3.micro cannot run a
    local model -- see DECISIONS.md.
    """
    if settings.llm_provider == "ollama":
        async for chunk in _stream_ollama(messages):
            yield chunk
    elif settings.llm_provider == "openai":
        async for chunk in _stream_openai(messages):
            yield chunk
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {settings.llm_provider}")


async def _stream_ollama(
    messages: list[dict], client: httpx.AsyncClient | None = None
) -> AsyncGenerator[str, None]:
    """`client` is normally created and closed here for the one request. A
    caller (a test, or code composing several calls) may pass its own
    instead, in which case this function uses it without closing it --
    the passed-in client's lifecycle stays the caller's to manage."""
    url = f"{settings.ollama_base_url}/api/chat"
    payload = {"model": settings.ollama_model, "messages": messages, "stream": True}

    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=_UPSTREAM_TIMEOUT)
    try:
        async with client.stream("POST", url, json=payload) as response:
            response.raise_for_status()
            saw_done = False
            async for line in response.aiter_lines():
                if not line:
                    continue
                data = json.loads(line)
                content = data.get("message", {}).get("content", "")
                if content:
                    yield content
                if data.get("done"):
                    saw_done = True
                    break
            if not saw_done:
                raise UpstreamIncompleteError("ollama stream ended without done: true")
    finally:
        if owns_client:
            await client.aclose()


async def _stream_openai(
    messages: list[dict], client: httpx.AsyncClient | None = None
) -> AsyncGenerator[str, None]:
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {settings.openai_api_key}"}
    payload = {"model": settings.openai_model, "messages": messages, "stream": True}

    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=_UPSTREAM_TIMEOUT)
    try:
        async with client.stream("POST", url, headers=headers, json=payload) as response:
            response.raise_for_status()
            saw_done = False
            async for line in response.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue
                data_str = line.removeprefix("data: ")
                if data_str.strip() == "[DONE]":
                    saw_done = True
                    break
                data = json.loads(data_str)
                delta = data["choices"][0]["delta"]
                content = delta.get("content", "")
                if content:
                    yield content
            if not saw_done:
                raise UpstreamIncompleteError("openai stream ended without [DONE]")
    finally:
        if owns_client:
            await client.aclose()
