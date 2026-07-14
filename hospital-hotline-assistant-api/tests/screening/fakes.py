"""Fake chat model for graph/engine tests — canned structured outputs."""

from __future__ import annotations

from collections import deque
from types import SimpleNamespace

from app.services.screening.extraction import ExtractionResult
from app.services.screening.nodes.question import PhrasedQuestion


class FakeChatModel:
    """Duck-types the BaseChatModel surface the nodes use.

    Queue canned ``ExtractionResult`` objects; an empty queue raises, which
    the nodes treat as an extraction failure. Question paraphrases consume
    queued ``PhrasedQuestion``s — or, for convenience, queued strings from
    ``text_replies`` (options empty → node falls back to deterministic chips).
    An empty queue raises, so the node degrades to the verbatim template.
    Free-text calls (explain node) return queued strings or "".
    """

    def __init__(self) -> None:
        self.extractions: deque[ExtractionResult] = deque()
        self.phrasings: deque[PhrasedQuestion] = deque()
        self.text_replies: deque[str] = deque()
        self.prompts: list[str] = []

    def with_structured_output(self, schema):
        return _Structured(self, schema)

    async def ainvoke(self, messages):
        self.prompts.append(str(messages))
        content = self.text_replies.popleft() if self.text_replies else ""
        # Real messages expose .text (flattens content blocks); mirror it.
        return SimpleNamespace(content=content, text=content)


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
        if self._schema is PhrasedQuestion:
            if self._owner.phrasings:
                return self._owner.phrasings.popleft()
            if self._owner.text_replies:
                return PhrasedQuestion(
                    question=self._owner.text_replies.popleft(), options=[]
                )
            raise RuntimeError("no canned phrasing")
        raise AssertionError(f"unexpected schema {self._schema}")
