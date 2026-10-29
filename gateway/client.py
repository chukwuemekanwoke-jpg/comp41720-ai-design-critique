"""Bounded REST orchestration with exact evidence membership checks."""
import asyncio
import json
from collections import Counter

import httpx
from pydantic import ValidationError

from .models import AnswerOut, RetrievalOut, timestamp

MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class UpstreamFailure(Exception):
    def __init__(self, timed_out=False):
        self.timed_out = timed_out


async def post_json(client, path, body, request_id, deadline):
    try:
        async with asyncio.timeout(deadline):
            async with client.stream("POST", path, json=body, headers={"X-Request-ID": request_id}) as response:
                if response.status_code != 200 or response.headers.get("x-request-id") != request_id:
                    raise UpstreamFailure()
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > MAX_RESPONSE_BYTES:
                        raise UpstreamFailure()
                return json.loads(content)
    except (httpx.TimeoutException, TimeoutError):
        raise UpstreamFailure(timed_out=True) from None
    except (httpx.HTTPError, ValueError, UnicodeError):
        raise UpstreamFailure() from None


def source_key(source):
    return (source.source_id, source.snapshot_id, source.source_version, source.url, source.passage)


async def retrieve(client, request_id, question, deadline):
    raw = await post_json(client, "/v1/retrieve", {
        "request_id": request_id, "question": question, "top_k": 5, "index_version": None,
    }, request_id, deadline)
    try:
        evidence = RetrievalOut.model_validate(raw)
        if evidence.request_id != request_id:
            raise ValueError("Request ID mismatch")
        # Validate Answer's stricter evidence bounds without truncation.
        sources = [p.as_source() for p in evidence.passages]
        return evidence, sources
    except (ValidationError, ValueError):
        raise UpstreamFailure() from None


async def orchestrate(retrieval_client, answer_client, settings, request_id, question):
    try:
        async with asyncio.timeout(settings.total_timeout):
            evidence, sources = await retrieve(retrieval_client, request_id, question, settings.retrieval_timeout)
            body = {"question": question, "sources": [s.model_dump() for s in sources],
                    "index_version": evidence.index_version, "last_success_at": evidence.last_success_at}
            raw = await post_json(answer_client, "/v1/answers", body, request_id, settings.answer_timeout)
            try:
                answer = AnswerOut.model_validate(raw)
                if (answer.request_id != request_id or answer.index_version != evidence.index_version
                        or answer.last_success_at is None
                        or timestamp(answer.last_success_at) != timestamp(evidence.last_success_at)):
                    raise ValueError("Evidence generation mismatch")
                supplied = Counter(source_key(source) for source in sources)
                cited = Counter(source_key(source) for source in answer.sources)
                if cited - supplied:
                    raise ValueError("Invented or duplicated citations")
                if answer.status == "degraded" and answer.sources != sources:
                    raise ValueError("Fallback did not retain original evidence")
                return answer
            except (ValidationError, ValueError):
                raise UpstreamFailure() from None
    except TimeoutError:
        raise UpstreamFailure(timed_out=True) from None
