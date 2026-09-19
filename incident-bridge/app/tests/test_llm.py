"""app/ has no other tests today (see AGENTS.md). This exercises the
real streaming/parsing logic against httpx.MockTransport -- no real
network, no real Ollama/OpenAI -- using the injectable `client` parameter
so these do not need to monkeypatch httpx.AsyncClient globally.
"""

import json

import httpx
import pytest

from app.llm import UpstreamIncompleteError, _stream_ollama, _stream_openai


async def _collect(agen):
    return [chunk async for chunk in agen]


def _client_with(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.anyio
async def test_ollama_stream_yields_chunks_in_order():
    body = "\n".join(
        [
            json.dumps({"message": {"content": "안녕"}, "done": False}),
            json.dumps({"message": {"content": "!"}, "done": True}),
        ]
    )
    client = _client_with(lambda request: httpx.Response(200, text=body + "\n"))

    chunks = await _collect(_stream_ollama([{"role": "user", "content": "hi"}], client=client))

    assert chunks == ["안녕", "!"]
    await client.aclose()


@pytest.mark.anyio
async def test_ollama_stream_without_done_raises_incomplete():
    # The connection just ends -- no line ever sets done: true. Before this
    # was fixed, the generator would simply stop and the caller (chat.py)
    # would treat the partial reply as a finished answer.
    body = json.dumps({"message": {"content": "절반만"}, "done": False}) + "\n"
    client = _client_with(lambda request: httpx.Response(200, text=body))

    with pytest.raises(UpstreamIncompleteError):
        await _collect(_stream_ollama([{"role": "user", "content": "hi"}], client=client))
    await client.aclose()


@pytest.mark.anyio
async def test_ollama_stream_propagates_http_errors():
    client = _client_with(lambda request: httpx.Response(404, json={"error": "model not found"}))

    with pytest.raises(httpx.HTTPStatusError):
        await _collect(_stream_ollama([{"role": "user", "content": "hi"}], client=client))
    await client.aclose()


@pytest.mark.anyio
async def test_openai_stream_yields_chunks_and_stops_at_done_sentinel():
    def chunk(text):
        return "data: " + json.dumps({"choices": [{"delta": {"content": text}}]}) + "\n\n"

    body = chunk("안녕") + chunk("하세요") + "data: [DONE]\n\n"
    client = _client_with(lambda request: httpx.Response(200, text=body))

    chunks = await _collect(_stream_openai([{"role": "user", "content": "hi"}], client=client))

    assert chunks == ["안녕", "하세요"]
    await client.aclose()


@pytest.mark.anyio
async def test_openai_stream_without_done_sentinel_raises_incomplete():
    def chunk(text):
        return "data: " + json.dumps({"choices": [{"delta": {"content": text}}]}) + "\n\n"

    body = chunk("절반만")  # connection ends before "data: [DONE]"
    client = _client_with(lambda request: httpx.Response(200, text=body))

    with pytest.raises(UpstreamIncompleteError):
        await _collect(_stream_openai([{"role": "user", "content": "hi"}], client=client))
    await client.aclose()
