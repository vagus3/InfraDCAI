import json
from typing import AsyncGenerator

import httpx

from app.config import settings


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


async def _stream_ollama(messages: list[dict]) -> AsyncGenerator[str, None]:
    url = f"{settings.ollama_base_url}/api/chat"
    payload = {"model": settings.ollama_model, "messages": messages, "stream": True}

    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("POST", url, json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line:
                    continue
                data = json.loads(line)
                content = data.get("message", {}).get("content", "")
                if content:
                    yield content
                if data.get("done"):
                    break


async def _stream_openai(messages: list[dict]) -> AsyncGenerator[str, None]:
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {settings.openai_api_key}"}
    payload = {"model": settings.openai_model, "messages": messages, "stream": True}

    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("POST", url, headers=headers, json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue
                data_str = line.removeprefix("data: ")
                if data_str.strip() == "[DONE]":
                    break
                data = json.loads(data_str)
                delta = data["choices"][0]["delta"]
                content = delta.get("content", "")
                if content:
                    yield content
