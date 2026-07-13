"""A stalled LLM call must not hang the turn — it is bounded and degrades.

Regression for the live-call freeze: a Vertex/Gemini gRPC call with no client
deadline hung a voice turn forever. Every screening LLM call is now wrapped in
``ainvoke_with_timeout``; a stall raises ``TimeoutError`` which the nodes catch
and fall back from.
"""

import asyncio
import time

import pytest

from app.services.screening.engine import ScreeningTriageEngine
from app.services.screening.nodes.base import ainvoke_with_timeout
from app.services.screening.persistence import InMemoryStateStore


class _HangingRunnable:
    async def ainvoke(self, _payload):
        await asyncio.sleep(3600)  # never returns within the test


class _HangingModel:
    """Duck-types the BaseChatModel surface the nodes use; every call hangs."""

    def with_structured_output(self, _schema):
        return _HangingRunnable()

    async def ainvoke(self, _messages):
        await asyncio.sleep(3600)


async def test_ainvoke_with_timeout_raises_fast_on_stall():
    started = time.perf_counter()
    with pytest.raises((asyncio.TimeoutError, TimeoutError)):
        await ainvoke_with_timeout(_HangingRunnable(), "x", timeout_s=0.2)
    # It returns promptly at the deadline, not after the 3600s sleep.
    assert time.perf_counter() - started < 5


async def test_ainvoke_with_timeout_returns_value_when_fast():
    class _Fast:
        async def ainvoke(self, payload):
            return f"ok:{payload}"

    assert await ainvoke_with_timeout(_Fast(), "hi", timeout_s=5) == "ok:hi"


async def test_hanging_extraction_escalates_instead_of_hanging(criteria):
    # A model whose extraction never returns must not freeze the turn: the
    # per-call timeout fires, both attempts "fail", and the engine escalates.
    engine = ScreeningTriageEngine(
        model=_HangingModel(),
        store=InMemoryStateStore(criteria),
        question_budget=8,
        model_label="screening:test",
        model_timeout_s=0.2,
    )
    started = time.perf_counter()
    r1 = await engine.run_turn(
        session_id="hang1", language="en", input_mode="voice", content="I have a cough",
    )
    r2 = await engine.run_turn(
        session_id="hang1", language="en", input_mode="voice", content="still coughing",
    )
    elapsed = time.perf_counter() - started
    # Two turns, two extraction attempts each at 0.2s — nowhere near a hang.
    assert elapsed < 10
    assert r2["escalated"] is True
    assert "nurse" in r2["reply"].lower()
