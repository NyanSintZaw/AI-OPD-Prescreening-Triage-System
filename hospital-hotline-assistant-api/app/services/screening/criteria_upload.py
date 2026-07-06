"""Criteria upload pipeline: document → text → LLM extraction → draft version.

The LLM output is a deliberately shallow schema (flat rule descriptions), which
is converted to the full condition AST in code and merged into the currently
active criteria so a draft is always a complete document. Head nurses review,
edit (the PUT endpoint is the pressure valve for imperfect extraction), and
approve before activation. Hand-encoded v1 remains the safety baseline.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from .rules.criteria_models import parse_criteria

logger = logging.getLogger(__name__)

CHUNK_CHARS = 7000
CHUNK_OVERLAP = 600
MAX_CHUNKS = 24


# --- shallow LLM extraction schema -------------------------------------------

class ExtractedVitalCondition(BaseModel):
    vital: Literal["hr", "rr", "sbp", "dbp", "map", "spo2", "temp", "pain_score", "distress_score"]
    op: Literal["lt", "le", "gt", "ge"]
    value: float


class ExtractedFinding(BaseModel):
    id: str = Field(description="snake_case canonical id, e.g. chest_pain")
    label_en: str
    label_th: str
    synonyms_en: list[str] = Field(default_factory=list)
    synonyms_th: list[str] = Field(default_factory=list)


class ExtractedRule(BaseModel):
    id: str = Field(description="snake_case rule id, e.g. l1_cardiac_arrest")
    section: Literal["level1", "danger_vitals", "department_rule", "fast_track", "triage_tuple"]
    label_en: str
    label_th: str
    citation: str = Field(default="", description="Section/heading of the source document")
    findings_all: list[str] = Field(default_factory=list, description="ALL of these finding ids present")
    findings_any: list[str] = Field(default_factory=list, description="ANY of these finding ids present")
    vitals_all: list[ExtractedVitalCondition] = Field(default_factory=list)
    vitals_any: list[ExtractedVitalCondition] = Field(default_factory=list)
    age_band: Literal[
        "infant_0_1m", "infant_1_12m", "child_1_3y", "child_3_5y",
        "child_5_10y", "child_10_15y", "child_any", "adult", None,
    ] = None
    level: int | None = Field(default=None, ge=1, le=5)
    department_code: str | None = Field(
        default=None, description="Destination department code for department_rule/fast_track"
    )


class ExtractedRouting(BaseModel):
    complaint_category: str
    department_code: str
    fallback_department_code: str = "opd_general"
    acceptance_findings_any: list[str] = Field(
        default_factory=list,
        description="Specialty acceptance criteria: any of these findings → direct to specialty",
    )
    citation: str = ""


class CriteriaExtraction(BaseModel):
    """What the model extracts from ONE chunk of a screening manual."""

    findings: list[ExtractedFinding] = Field(default_factory=list)
    rules: list[ExtractedRule] = Field(default_factory=list)
    routing: list[ExtractedRouting] = Field(default_factory=list)


_EXTRACTION_PROMPT = """You are converting a Thai hospital patient-screening manual into structured
screening rules. Read the document chunk below and extract:
- findings: symptoms/signs referenced by rules (bilingual labels; create Thai
  and English labels for each; snake_case ids; reuse an existing id when the
  meaning matches).
- rules: triage rules. section=level1 for immediate life threats, danger_vitals
  for vital-sign thresholds (include age_band for pediatric bands),
  department_rule for department-specific red flags (set department_code and
  level), fast_track for named fast tracks, triage_tuple for symptom
  combinations that force a level.
- routing: chief-complaint category → destination department entries, with
  specialty acceptance criteria when the manual gives them.

Known department codes: emergency, opd_general, opd_internal_medicine,
opd_pediatrics, opd_cardiology, opd_orthopedics, opd_ent, opd_surgery,
opd_ophthalmology, opd_psychiatry, opd_obgyn.

Existing finding ids you should reuse where applicable:
{known_findings}

Extract ONLY what this chunk actually states. Do not invent thresholds.

Document chunk:
{chunk}"""


def extract_text(path: str | Path, filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        import fitz  # PyMuPDF, already a project dependency

        doc = fitz.open(str(path))
        try:
            return "\n\n".join(page.get_text() for page in doc)
        finally:
            doc.close()
    if suffix in (".txt", ".md", ".csv"):
        return Path(path).read_text(encoding="utf-8", errors="replace")
    if suffix == ".docx":
        import subprocess

        result = subprocess.run(
            ["pandoc", str(path), "-t", "plain"],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0:
            return result.stdout
        raise ValueError(f"docx conversion failed: {result.stderr[:200]}")
    raise ValueError(f"Unsupported file type: {suffix}")


def _chunk(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text) and len(chunks) < MAX_CHUNKS:
        end = min(start + CHUNK_CHARS, len(text))
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end - CHUNK_OVERLAP
    return chunks


def _vital_leaf(cond: ExtractedVitalCondition) -> dict[str, Any]:
    return {"vital": cond.vital, "op": cond.op, "value": cond.value}


def _rule_condition(rule: ExtractedRule) -> dict[str, Any]:
    all_of: list[dict[str, Any]] = [{"finding_id": fid} for fid in rule.findings_all]
    all_of += [_vital_leaf(v) for v in rule.vitals_all]
    any_of: list[dict[str, Any]] = [{"finding_id": fid} for fid in rule.findings_any]
    any_of += [_vital_leaf(v) for v in rule.vitals_any]
    condition: dict[str, Any] = {}
    if all_of:
        condition["all_of"] = all_of
    if any_of:
        if all_of:
            condition["all_of"].append({"any_of": any_of})
        else:
            condition["any_of"] = any_of
    if not condition:
        # rule without any condition content is unusable; mark impossible
        condition = {"all_of": [{"finding_id": "__unextractable__"}]}
    if rule.age_band:
        condition["age_band"] = rule.age_band
    return condition


def _upsert(items: list[dict[str, Any]], entry: dict[str, Any], key: str = "id") -> None:
    for i, existing in enumerate(items):
        if existing.get(key) == entry.get(key):
            items[i] = entry
            return
    items.append(entry)


def merge_extraction(base: dict[str, Any], extraction: CriteriaExtraction) -> dict[str, Any]:
    """Merge one chunk's extraction into a full criteria payload (in place)."""

    catalog = base.setdefault("finding_catalog", {})
    for finding in extraction.findings:
        fid = finding.id.strip()
        if not fid:
            continue
        existing = catalog.get(fid, {})
        catalog[fid] = {
            "label_en": finding.label_en or existing.get("label_en", fid),
            "label_th": finding.label_th or existing.get("label_th", fid),
            "synonyms_en": sorted({*existing.get("synonyms_en", []), *finding.synonyms_en}),
            "synonyms_th": sorted({*existing.get("synonyms_th", []), *finding.synonyms_th}),
            "is_risk_factor": existing.get("is_risk_factor", False),
        }

    for rule in extraction.rules:
        referenced = set(rule.findings_all) | set(rule.findings_any)
        if not referenced and not rule.vitals_all and not rule.vitals_any:
            referenced = {"__unextractable__"}  # keeps document valid, flags review
        missing = [fid for fid in referenced if fid not in catalog]
        for fid in missing:
            # placeholder entries keep the document valid; flagged for review
            catalog[fid] = {
                "label_en": fid.replace("_", " "),
                "label_th": fid,
                "synonyms_en": [],
                "synonyms_th": [],
                "is_risk_factor": False,
            }
        condition = _rule_condition(rule)
        entry: dict[str, Any] = {
            "id": rule.id,
            "label_en": rule.label_en,
            "label_th": rule.label_th,
            "citation": rule.citation,
            "condition": condition,
        }
        if rule.section == "level1":
            _upsert(base.setdefault("level1_criteria", []), entry)
        elif rule.section == "danger_vitals":
            entry["level"] = rule.level or 2
            _upsert(base.setdefault("danger_vitals", []), entry)
        elif rule.section == "department_rule":
            entry["department_code"] = rule.department_code or "emergency"
            entry["min_level"] = rule.level or 2
            _upsert(base.setdefault("department_rules", []), entry)
        elif rule.section == "fast_track":
            entry["department_code"] = rule.department_code or "emergency"
            entry["level"] = rule.level or 2
            _upsert(base.setdefault("fast_tracks", []), entry)
        elif rule.section == "triage_tuple":
            tuple_entry = {
                "id": rule.id,
                "label_en": rule.label_en,
                "label_th": rule.label_th,
                "findings_all": rule.findings_all,
                "risk_factors_any": rule.findings_any,
                "force_min_level": rule.level or 2,
                "citation": rule.citation,
            }
            _upsert(base.setdefault("triage_tuples", []), tuple_entry)

    for route in extraction.routing:
        entry = {
            "complaint_category": route.complaint_category,
            "department_code": route.department_code,
            "fallback_department_code": route.fallback_department_code,
            "specialty_conditions": (
                [{"any_of": [{"finding_id": fid} for fid in route.acceptance_findings_any
                             if fid in catalog]}]
                if [fid for fid in route.acceptance_findings_any if fid in catalog]
                else []
            ),
            "citation": route.citation,
        }
        _upsert(
            base.setdefault("routing_table", []), entry, key="complaint_category",
        )

    return base


def validation_errors(payload: dict[str, Any]) -> list[str]:
    try:
        parse_criteria(payload)
        return []
    except ValidationError as exc:
        return [
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
            for err in exc.errors()[:50]
        ]
    except Exception as exc:  # noqa: BLE001
        return [str(exc)]


async def extract_criteria_draft(
    *,
    file_path: str | Path,
    filename: str,
    model,
    base_payload: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Run the full pipeline; returns (draft_payload, warnings)."""

    text = extract_text(file_path, filename)
    chunks = _chunk(text)
    if not chunks:
        raise ValueError("Document contains no extractable text")

    known = ", ".join(sorted(base_payload.get("finding_catalog", {}).keys()))
    structured = model.with_structured_output(CriteriaExtraction)
    warnings: list[str] = []
    draft = base_payload
    for index, chunk in enumerate(chunks):
        prompt = _EXTRACTION_PROMPT.format(known_findings=known, chunk=chunk)
        try:
            extraction: CriteriaExtraction = await structured.ainvoke(prompt)
        except Exception as exc:  # noqa: BLE001
            logger.exception("criteria extraction failed on chunk %d", index + 1)
            warnings.append(f"chunk {index + 1}/{len(chunks)} failed: {exc}")
            continue
        draft = merge_extraction(draft, extraction)

    warnings.extend(validation_errors(draft))
    return draft, warnings


def diff_criteria(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """Field-level diff between two criteria payloads, keyed by rule ids."""

    sections = [
        ("level1_criteria", "id"), ("danger_vitals", "id"),
        ("department_rules", "id"), ("fast_tracks", "id"),
        ("triage_tuples", "id"), ("routing_table", "complaint_category"),
        ("complaint_templates", "category"),
    ]
    result: dict[str, Any] = {}
    for section, key in sections:
        old_items = {item.get(key): item for item in old.get(section, [])}
        new_items = {item.get(key): item for item in new.get(section, [])}
        added = sorted(k for k in new_items if k not in old_items)
        removed = sorted(k for k in old_items if k not in new_items)
        changed = sorted(
            k for k in new_items
            if k in old_items and new_items[k] != old_items[k]
        )
        if added or removed or changed:
            result[section] = {"added": added, "removed": removed, "changed": changed}

    old_findings = old.get("finding_catalog", {})
    new_findings = new.get("finding_catalog", {})
    f_added = sorted(k for k in new_findings if k not in old_findings)
    f_removed = sorted(k for k in old_findings if k not in new_findings)
    f_changed = sorted(
        k for k in new_findings if k in old_findings and new_findings[k] != old_findings[k]
    )
    if f_added or f_removed or f_changed:
        result["finding_catalog"] = {
            "added": f_added, "removed": f_removed, "changed": f_changed,
        }
    return result
