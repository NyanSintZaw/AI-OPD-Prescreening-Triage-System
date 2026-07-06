from app.services.ai.agent_factory import build_triage_agent
from app.services.ai.prompts import _TRIAGE_INSTRUCTION


def test_triage_agent_includes_indexed_manual_and_static_fallback_tools():
    agent = build_triage_agent(model_name="gemini-test")

    tool_names = [tool.name for tool in agent.tools]

    assert "search_indexed_triage_manual" in tool_names
    assert "get_triage_reference" in tool_names
    assert "get_department_list" in tool_names
    assert "classify_triage_level" in tool_names
    assert tool_names.index("search_indexed_triage_manual") < tool_names.index(
        "get_triage_reference"
    )


def test_triage_prompt_requires_index_first_and_static_fallback():
    assert "search_indexed_triage_manual" in _TRIAGE_INSTRUCTION
    assert "preferred clinical reference" in _TRIAGE_INSTRUCTION
    assert "available=false" in _TRIAGE_INSTRUCTION
    assert "get_triage_reference" in _TRIAGE_INSTRUCTION
    assert "get_department_list" in _TRIAGE_INSTRUCTION
