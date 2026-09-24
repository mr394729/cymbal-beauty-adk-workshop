"""Authenticated Agent Runtime streaming using the public REST contract.

The installed SDK counts braces inside JSON strings when framing some streamed
responses. Decode JSON values instead, preserving trace previews and tool results.
REST reference: https://docs.cloud.google.com/gemini-enterprise-agent-platform/reference/rest/v1beta1/projects.locations.reasoningEngines/streamQuery
"""
from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator
from typing import Any

import google.auth
import httpx
from google.auth.transport.requests import Request

_RESOURCE = re.compile(r"projects/[a-zA-Z0-9_-]+/locations/([a-z0-9-]+)/reasoningEngines/[a-zA-Z0-9_-]+(?:/runtimeRevisions/[a-zA-Z0-9_-]+)?")
_MAX_FRAME_CHARS = 8 * 1024 * 1024


class StreamQueryError(RuntimeError):
    """A transport/framing failure, without response bodies or credential values."""


class _JSONFrames:
    def __init__(self):
        self.buffer = ""
        self.decoder = json.JSONDecoder()

    def feed(self, text: str, *, final: bool = False) -> list[dict]:
        self.buffer += text
        results = []
        while self.buffer.strip():
            self.buffer = self.buffer.lstrip()
            if len(self.buffer) > _MAX_FRAME_CHARS:
                raise StreamQueryError("Agent Runtime response frame exceeded the size limit.")
            try:
                value, end = self.decoder.raw_decode(self.buffer)
            except json.JSONDecodeError:
                if final:
                    raise StreamQueryError("Agent Runtime returned malformed or truncated JSON.") from None
                break
            if not isinstance(value, dict):
                raise StreamQueryError("Agent Runtime returned a non-object event.")
            if "error" in value and "content" not in value and "actions" not in value:
                raise StreamQueryError("Agent Runtime reported an upstream error.")
            results.append(value)
            self.buffer = self.buffer[end:]
        return results


async def _events(response: httpx.Response) -> AsyncIterator[dict]:
    """Handle SSE data fields or raw JSON/NDJSON, independent of TCP chunk splits."""
    frames = _JSONFrames()
    mode = None
    data: list[str] = []
    data_size = 0
    # aiter_lines handles split UTF-8 characters and CRLF boundaries incrementally.
    async for line in response.aiter_lines():
        if mode is None and line.strip():
            mode = "sse" if line.startswith((":", "data:", "event:", "id:", "retry:")) else "json"
        if mode != "sse":
            for value in frames.feed(line + "\n"):
                yield value
            continue
        if not line:
            if data:
                for value in frames.feed("\n".join(data), final=True):
                    yield value
                data, data_size = [], 0
            continue
        if line.startswith(":"):
            continue
        field, separator, value = line.partition(":")
        if field == "data":
            value = value[1:] if value.startswith(" ") else value
            data.append(value if separator else "")
            data_size += len(value)
            if data_size > _MAX_FRAME_CHARS:
                raise StreamQueryError("Agent Runtime response frame exceeded the size limit.")
        # SSE event/id/retry fields describe delivery and are not agent payloads.
    if data:
        for value in frames.feed("\n".join(data), final=True):
            yield value
    for value in frames.feed("", final=True):
        yield value


def _authorize(credentials, url: str) -> dict[str, str]:
    if credentials is None:
        credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
    request = Request()
    try:
        credentials.before_request(request, "POST", url, headers)
    finally:
        request.session.close()
    return headers


async def stream_query(*, name: str, user_id: str, session_id: str, message: Any,
                       invocation_id: str | None = None, credentials=None,
                       http_client: httpx.AsyncClient | None = None) -> AsyncIterator[dict]:
    """Stream one request; never retry a turn that may already have executed tools.

    Uses ADC unless explicit google.auth credentials are supplied. A provided
    http_client remains caller-owned; the default client closes on completion,
    failure, cancellation, or early generator closure.
    """
    match = _RESOURCE.fullmatch(name)
    if not match:
        raise ValueError("Expected an Agent Runtime engine or runtime revision resource name.")
    location = match.group(1)
    host = "aiplatform.googleapis.com" if location == "global" else f"{location}-aiplatform.googleapis.com"
    url = f"https://{host}/v1beta1/{name}:streamQuery?alt=sse"
    inputs = {"user_id": user_id, "session_id": session_id, "message": message}
    if invocation_id is not None:
        inputs["invocation_id"] = invocation_id
    try:
        headers = await asyncio.to_thread(_authorize, credentials, url)
    except Exception:
        raise StreamQueryError("Unable to authenticate the Agent Runtime request.") from None
    owned = http_client is None
    client = http_client or httpx.AsyncClient(timeout=httpx.Timeout(600, connect=30, write=30, pool=30))
    try:
        async with client.stream("POST", url, headers=headers,
                                 json={"classMethod": "async_stream_query", "input": inputs}) as response:
            if not response.is_success:
                raise StreamQueryError(f"Agent Runtime request failed with HTTP {response.status_code}.")
            async for event in _events(response):
                yield event
    except httpx.HTTPError:
        raise StreamQueryError("Agent Runtime stream failed during transport; the request was not retried.") from None
    finally:
        if owned:
            await client.aclose()
