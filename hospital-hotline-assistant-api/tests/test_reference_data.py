import json


def test_triage_reference_loader_uses_minimal_fallback_for_missing_file(
    monkeypatch,
    tmp_path,
    caplog,
):
    from app.services.ai import reference_data

    monkeypatch.setattr(reference_data, "_TRIAGE_FILE", tmp_path / "missing.json")

    data = reference_data._load_triage_reference()

    assert data["source"] == "built-in minimal fallback"
    assert data["decision_tree"]
    assert "using minimal fallback" in caplog.text


def test_triage_reference_loader_reads_valid_json(monkeypatch, tmp_path):
    from app.services.ai import reference_data

    path = tmp_path / "triage.json"
    path.write_text(
        json.dumps({"knowledge_base": "custom", "decision_tree": [{"step": 1}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(reference_data, "_TRIAGE_FILE", path)

    data = reference_data._load_triage_reference()

    assert data["knowledge_base"] == "custom"
