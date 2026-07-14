# Triage Manual vs Screening Criteria — why both admin tabs exist

Both admin uploads originate from the same source document (the MFU manual,
คู่มือเกณฑ์การคัดกรองผู้ป่วย), but they feed two different parts of the system.
This is the **decision-separation** principle: the rules decide, the LLM only
phrases.

## The one-liner

> **Screening Criteria change what the system *decides*. The Triage Manual
> changes how it *explains* that decision.**

## Side by side

| | **Screening Criteria** (🧾 tab) | **Triage Manual** (📋 tab) |
|---|---|---|
| What it is | Structured, machine-readable rules (red flags, danger vitals, chief-complaint → department routing, age bands) | The raw manual PDF, chunked + embedded for semantic search (RAG) |
| Role | **Decides** the MOPH level + department | **Grounds the wording** of the patient explanation |
| Consumed by | The pure rules engine (`rules/`), every turn | Only the `explain` node, and only on **non-emergency** turns |
| Backed by | `screening_criteria_versions` table + `screening_criteria_v1.json` | `triage_knowledge` pgvector table (`rag_query.py` / `rag_ingest.py`) |
| Governance | Versioned: upload → draft → review → approve → **activate** | Plain upload → re-index (no versioning/approval) |
| Required? | **Yes** — this is the triage. A seeded v1 is always active. | **No** — optional. |
| If absent / not uploaded | (never absent — bundled v1 falls back automatically) | Explanations fall back to a clean bilingual template |
| Needs pgvector? | No | **Yes** — the RAG index needs the `vector` extension (`pgvector/pgvector:pg16`) |

## Do you need both?

- **Screening Criteria: required.** It *is* the triage. Nurses upload/approve
  new versions here; the engine reads the active version to decide.
- **Triage Manual: optional.** It only makes non-emergency explanations echo
  the real manual's phrasing. Decisions are identical with or without it.

Since the ADK and pydantic-ai stacks were removed, the indexed manual has
exactly **one** remaining consumer — the screening engine's `explain` node
(`nodes/explain.py`), which retrieves the top passages
(`response_mode="no_text"`) and hands them to Gemini as *"approved hospital
guidance you may draw phrasing from"*, with a 1.5 s timeout and a graceful
fallback to the deterministic template. Emergency explanations never use it.

## Recommendation

**Keep both for the demo.** Upload the manual to the 📋 tab so explanations can
draw on real hospital phrasing (a good transparency story), and keep the
hand-encoded **v1** active in the 🧾 tab for decisions. But treat the manual as
an *explanation-quality* feature, not part of the decision path — if the
grounded explanations don't visibly improve on the templates, the Triage
Manual upload (and its pgvector dependency) can be dropped with **no impact on
triage decisions**.

Never activate an LLM-extracted **criteria** draft over the hand-encoded v1
for a real demo without a nurse review — the hand-encoding is more reliable
than auto-extraction.
