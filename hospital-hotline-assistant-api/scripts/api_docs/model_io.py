"""The model I/O contract, built from the real prompt builders.

Every example here is produced by the same code the engine runs, so the
document and the Postman collection cannot drift from what actually goes on
the wire — the mistake this repo has made before with hand-typed samples.

One synthetic patient throughout: a 58-year-old with chest pain, level 3.
The name is deliberately present in the *state* so the examples prove the
identifiers do not reach the model.
"""

from __future__ import annotations

import json
from typing import Any

from app.services.screening.extraction import ExtractionResult, build_extraction_prompt
from app.services.screening.nlu_backstop import _PROMPTS as GATE_PROMPTS
from app.services.screening.nlu_backstop import _SCHEMAS as GATE_SCHEMAS
from app.services.screening.nodes.explain import _EXPLAIN_PROMPT, _NAME_LINE
from app.services.screening.nodes.question import (
    PhrasedQuestion,
    _PARAPHRASE_PROMPT,
    _REPHRASE_INSTRUCTION,
    recent_exchange_lines,
)
from app.services.screening.persona import persona_block
from app.services.screening.state import ScreeningState
from app.services.surveillance_extractor import (
    _EXTRACTION_PROMPT as SURVEILLANCE_PROMPT,
    SurveillanceKeywords,
    screening_summary_text,
)

# What the session holds and the model must never see.
WITHHELD = {
    "patient_name": "สมชาย ใจดี",
    "hn": "09900001",
    "visit_id": "990000000000000001",
    "slip_code": "MCH-A1B2-C3D4",
    "session_id": "1f0b8c2e-4a77-4d1e-9d3a-2b6e5c7f81aa",
    "birthdate": "1968-03-14",
}


# Render the bundled criteria (app/data/screening_criteria.json) — the same
# document a fresh database seeds as version 1 active, so the hospital-facing
# prompt examples match what the booth runs.
def _criteria():
    from app.services.screening.rules.criteria_store import load_seed_criteria

    return load_seed_criteria()


def _state(language: str = "th") -> ScreeningState:
    state = ScreeningState(session_id=WITHHELD["session_id"], language=language)
    state.patient_name = WITHHELD["patient_name"]
    th = language == "th"
    state.chief_complaint = "แน่นหน้าอกมา 2 ชั่วโมง" if th else "chest tightness for 2 hours"
    state.age_years = 58
    state.vitals = {"systolic": 158, "diastolic": 94, "pulse_bpm": 96}
    # The last exchange goes back into the question prompt. The assistant
    # line is stored already masked by engine._remember — this is what a
    # stored line looks like, name and all, after masking.
    state.recent_turns = [
        {"role": "user", "text": "เจ็บแน่นหน้าอกมาสองชั่วโมง ร้าวไปแขนซ้าย"},
        {"role": "assistant", "text": "[NAME] คะ เข้าใจค่ะ ตอนนี้เหนื่อยหรือหายใจลำบากไหมคะ"},
    ] if th else [
        {"role": "user", "text": "My chest has been tight for two hours, it goes into my left arm"},
        {"role": "assistant", "text": "[NAME], I understand. Are you short of breath right now?"},
    ]
    return state


def _schema(model: Any) -> dict:
    """The JSON Schema a local server is given to constrain the reply."""
    return model.model_json_schema()


# Which call sites have a genuinely different prompt per language, versus an
# English instruction scaffold that is identical whatever the patient speaks.
# Verified against the source, not assumed:
#   extraction  — English scaffold (extraction.py), but the finding catalog
#                 lists labels/synonyms in the session language only, so the
#                 th and en prompts differ
#   question    — bilingual (_PARAPHRASE_PROMPT has "en" and "th")
#   explain     — bilingual (_EXPLAIN_PROMPT has "en" and "th")
#   gate:*      — English only (_PROMPTS), carrying "Session language: th"
BILINGUAL_CALLS = {"extraction", "question", "explain"}


def calls(language: str = "th") -> list[dict[str, Any]]:
    """Every model call the engine can make, in the order a turn runs them."""
    state = _state(language)
    criteria = _criteria()

    return [
        {
            "id": "extraction",
            "title": "Extraction — read one patient message into findings",
            "when": (
                "Every turn, first. The only call whose output changes the "
                "triage: it reports what the patient said, and the rules "
                "engine decides what that means."
            ),
            "prompt": build_extraction_prompt(
                criteria, state,
                *(
                    ("เจ็บแน่นหน้าอกมาสองชั่วโมง ร้าวไปแขนซ้าย ไม่มีไข้", "คุณมีอาการเจ็บหน้าอกหรือไม่")
                    if language == "th"
                    else ("My chest has been tight for two hours, it goes into my left arm, no fever", "Do you have chest pain?")
                ),
            ),
            "structured": True,
            "schema": _schema(ExtractionResult),
            "response": {
                "chief_complaint": "แน่นหน้าอกมา 2 ชั่วโมง ร้าวไปแขนซ้าย",
                "complaint_category": "chest_pain",
                "finding_updates": [
                    {
                        "id": "chest_pain_radiating",
                        "state": "present",
                        "evidence": "ร้าวไปแขนซ้าย",
                    },
                    {"id": "fever", "state": "absent", "evidence": "ไม่มีไข้"},
                ],
                "slot_updates": {"onset": "2 ชั่วโมง", "location": "หน้าอก"},
                "age_years": None,
                "pain_score": None,
                "distress_score": None,
            },
        },
        {
            "id": "question",
            "title": "Question — acknowledge, then ask the approved question",
            "when": (
                "Every interview turn, once the rules engine has picked the "
                "next question. The model returns a short acknowledgement and "
                "(only for history/associated-symptom questions) a rewording. "
                "Red-flag, scale, measurement and confirm questions are sent "
                "with a 'return it unchanged' instruction and the engine uses "
                "the criteria text regardless of what comes back."
            ),
            "prompt": _PARAPHRASE_PROMPT[language].format(
                persona=persona_block(language),
                recent=recent_exchange_lines(state, language),
                context=state.chief_complaint,
                known="อายุ 58 ปี | ความดัน 158/94",
                instruction=_REPHRASE_INSTRUCTION[language],
                question="อาการเจ็บหน้าอกร้าวไปที่แขน คอ หรือกรามหรือไม่",
            ),
            "structured": True,
            "schema": _schema(PhrasedQuestion),
            "response": {
                "ack": "เข้าใจค่ะ",
                "question": "อาการเจ็บที่หน้าอก มีร้าวไปที่แขน คอ หรือกรามด้วยไหมคะ",
                "options": ["ร้าวไปแขน", "ร้าวไปคอหรือกราม", "ไม่ร้าวไปไหน", "ไม่แน่ใจ"],
            },
        },
        {
            "id": "explain",
            "title": "Explain — phrase the decision the rules already made",
            "when": (
                "Once, at disposition. The department and urgency are inputs, "
                "not something the model chooses."
            ),
            "prompt": _EXPLAIN_PROMPT[language].format(
                persona=persona_block(language),
                summary="แน่นหน้าอกมา 2 ชั่วโมง ร้าวไปแขนซ้าย",
                department="แผนก OPD MED (อายุรกรรม)",
                name_line=_NAME_LINE[language],
                urgency_line="",
                reference="",
                closing_line="",
            ),
            "structured": False,
            "schema": None,
            "response": (
                "[NAME] คะ จากอาการที่เล่ามา ทางเราขอให้ไปที่แผนก OPD MED "
                "(อายุรกรรม) เพื่อให้แพทย์ตรวจดูอย่างละเอียดนะคะ "
                "เดี๋ยวเจ้าหน้าที่จะช่วยแนะนำทางให้ค่ะ"
            ),
            "post": (
                "`[NAME]` is replaced with the patient's name **after** the "
                "reply comes back, so the greeting reads naturally without the "
                "name ever being sent. The reply is then checked by "
                "`validator.py` for triage-level, colour, diagnosis and "
                "medication leaks, in Thai and English, before the patient "
                "hears it."
            ),
        },
        *[
            {
                "id": f"gate:{kind}",
                "title": f"Gate ({kind}) — classify one yes/no-ish reply",
                "when": (
                    "Only when the deterministic regex classifier is unsure. "
                    "The model returns one enum value and never generates "
                    "anything the patient hears."
                ),
                "prompt": GATE_PROMPTS[kind].format(
                    utterance="ไม่มีแล้วค่ะ ขอบคุณค่ะ",
                    language=language,
                    context="in_progress" if kind == "resume_choice" else "-",
                ),
                "structured": True,
                "schema": _schema(GATE_SCHEMAS[kind]),
                "response": {
                    "verdict": {
                        "followup_decline": "decline",
                        "identity_yesno": "yes",
                        "resume_choice": "continue",
                    }[kind]
                },
            }
            for kind in sorted(GATE_PROMPTS)
        ],
        {
            "id": "surveillance",
            "title": "Surveillance — disease keywords for the outbreak dashboard",
            "when": (
                "Once, when the session is marked completed, in the background. "
                "Input is the engine's own screening state (complaint, present "
                "findings, slot answers) — never the transcript, never the "
                "identity. Output feeds disease_surveillance only; nothing the "
                "patient hears."
            ),
            "prompt": SURVEILLANCE_PROMPT.format(messages=screening_summary_text(_surv_state(language))),
            "structured": True,
            "schema": _schema(SurveillanceKeywords),
            "response": {"keywords": ["chest pain", "arm pain"]},
        },
    ]


def _surv_state(language: str) -> ScreeningState:
    from app.services.screening.state import Finding

    state = _state(language)
    state.complaint_category = "chest_pain"
    state.findings["chest_pain_radiating"] = Finding(state="present", value="ร้าวไปแขนซ้าย")
    state.slots = {"onset": "2 ชั่วโมง", "location": "หน้าอก"}
    return state


# Speech: same workstation, OpenAI audio routes (speech_adapter.HttpSttClient /
# HttpTtsClient). These are the two calls that unavoidably carry patient data
# the LLM path withholds — raw voice and, in TTS input, the patient's name in
# the greeting — which is why they are local too.
def speech_calls() -> list[dict[str, Any]]:
    return [
        {
            "id": "stt",
            "title": "STT — POST {LLM_BASE_URL}/audio/transcriptions",
            "when": "Every patient turn: the 16 kHz PCM of that turn, multipart.",
            "carries": "raw patient audio (whatever they say, including a name)",
            "request": {
                "multipart": {
                    "model": "{STT_MODEL}",
                    "language": "th",
                    "response_format": "json",
                    "file": "<turn audio, audio/wav>",
                }
            },
            "response": {"text": "เจ็บแน่นหน้าอกมาสองชั่วโมง"},
        },
        {
            "id": "tts",
            "title": "TTS — POST {LLM_BASE_URL}/audio/speech",
            "when": "Every assistant line the patient hears.",
            "carries": "the finished reply text — the greeting includes the patient's given name",
            "request": {
                "json": {
                    "model": "{TTS_MODEL}",
                    "input": "สวัสดีค่ะ คุณสมชาย วันนี้มีอาการอะไรให้ช่วยคะ",
                    "voice": "{TTS_LOCAL_VOICE_TH}",
                    "response_format": "wav",
                    "sample_rate": 24000,
                }
            },
            "response": "<audio/wav, LINEAR16 24 kHz>",
        },
    ]


def openai_body(call: dict[str, Any], model_name: str) -> dict[str, Any]:
    """The call as an OpenAI-compatible request — what a workstation running
    vLLM or Ollama would receive."""
    body: dict[str, Any] = {
        "model": model_name,
        "messages": [{"role": "user", "content": call["prompt"]}],
        "temperature": 0.1,
        "stream": False,
    }
    if call["structured"]:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": call["id"].replace(":", "_"),
                "strict": True,
                "schema": call["schema"],
            },
        }
    return body


def openai_response(call: dict[str, Any], model_name: str) -> dict[str, Any]:
    content = call["response"]
    return {
        "id": "chatcmpl-mfu-0001",
        "object": "chat.completion",
        "model": model_name,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": (
                        json.dumps(content, ensure_ascii=False)
                        if isinstance(content, dict)
                        else content
                    ),
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
