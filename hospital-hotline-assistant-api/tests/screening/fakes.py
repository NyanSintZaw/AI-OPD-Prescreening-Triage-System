"""Fake chat model for graph/engine tests — canned structured outputs."""

from __future__ import annotations

from collections import deque
from types import SimpleNamespace

from app.services.screening.extraction import ExtractionResult


class FakeChatModel:
    """Duck-types the BaseChatModel surface the nodes use.

    Queue canned ``ExtractionResult`` objects; an empty queue raises, which
    the nodes treat as an extraction failure. Free-text calls return queued
    strings or "" (nodes then fall back to templates).
    """

    def __init__(self) -> None:
        self.extractions: deque[ExtractionResult] = deque()
        self.text_replies: deque[str] = deque()
        self.prompts: list[str] = []

    def with_structured_output(self, schema):
        return _Structured(self, schema)

    async def ainvoke(self, messages):
        self.prompts.append(str(messages))
        content = self.text_replies.popleft() if self.text_replies else ""
        return SimpleNamespace(content=content)


class _Structured:
    def __init__(self, owner: FakeChatModel, schema) -> None:
        self._owner = owner
        self._schema = schema

    async def ainvoke(self, prompt):
        self._owner.prompts.append(str(prompt))
        if self._schema is ExtractionResult:
            if not self._owner.extractions:
                raise RuntimeError("no canned extraction")
            return self._owner.extractions.popleft()
        raise AssertionError(f"unexpected schema {self._schema}")
