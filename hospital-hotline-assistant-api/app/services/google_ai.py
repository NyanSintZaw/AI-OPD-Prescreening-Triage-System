from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from app.config import settings


SYSTEM_PROMPT = """
You are a hospital triage assistant.
Return STRICT JSON only with these fields:
{
  "reply": "string",
  "severity": {"level":"emergency|urgent|general|unknown","explanation":"string","confidence":0.0},
  "department": {"code":"string|null","reason":"string","confidence":0.0},
  "symptoms": {"rawText":"string","bodyLocation":"string|null","durationText":"string|null"},
  "needsFollowUp": true|false,
  "followUpQuestion": "string|null",
  "followUpReason": "string|null"
}
Keep responses short and safe. If emergency signs exist, prioritize emergency guidance.
"""


def _extract_json_block(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


class GoogleTriageClient:
    def __init__(self) -> None:
        self.enabled = settings.google_ai_enabled
        self.project = settings.google_cloud_project
        self.location = settings.google_cloud_location
        self.model_name = settings.google_model_name
        self.credentials = settings.google_application_credentials

    async def generate_triage(
        self,
        *,
        language: str,
        user_message: str,
        history: list[dict[str, Any]],
        emergency_context: list[str],
        routing_context: list[str],
    ) -> dict[str, Any]:
        if not self.enabled:
            return self._fallback_triage(language, user_message, emergency_context, routing_context)

        try:
            result = await asyncio.to_thread(
                self._generate_with_google,
                language,
                user_message,
                history,
                emergency_context,
                routing_context,
            )
            if result:
                return result
        except Exception:
            # Safety fallback when external AI fails.
            pass

        return self._fallback_triage(language, user_message, emergency_context, routing_context)

    def _generate_with_google(
        self,
        language: str,
        user_message: str,
        history: list[dict[str, Any]],
        emergency_context: list[str],
        routing_context: list[str],
    ) -> dict[str, Any] | None:
        if self.credentials:
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = self.credentials

        try:
            from google import genai
        except Exception:
            return None

        context_lines = [
            f"Language: {language}",
            f"Emergency context: {', '.join(emergency_context) if emergency_context else 'none'}",
            f"Routing context: {', '.join(routing_context) if routing_context else 'none'}",
            f"Conversation history: {json.dumps(history[-8:], ensure_ascii=False)}",
            f"Latest user message: {user_message}",
        ]
        prompt = SYSTEM_PROMPT + "\n\n" + "\n".join(context_lines)

        client = genai.Client(
            vertexai=bool(self.project),
            project=self.project,
            location=self.location,
        )

        response = client.models.generate_content(
            model=self.model_name,
            contents=prompt,
        )

        text_output = getattr(response, "text", "") or ""
        parsed = _extract_json_block(text_output)
        return parsed

    def _fallback_triage(
        self,
        language: str,
        user_message: str,
        emergency_context: list[str],
        routing_context: list[str],
    ) -> dict[str, Any]:
        is_th = language == "th"
        emergency_detected = bool(emergency_context)

        if emergency_detected:
            return {
                "reply": (
                    "อาการที่แจ้งมีความเสี่ยงฉุกเฉิน กรุณาติดต่อเจ้าหน้าที่ทันที"
                    if is_th
                    else "Your symptoms may indicate an emergency. Please contact hospital staff immediately."
                ),
                "severity": {
                    "level": "emergency",
                    "explanation": "Rule-based emergency match fallback",
                    "confidence": 0.9,
                },
                "department": {
                    "code": "emergency",
                    "reason": "Emergency trigger matched",
                    "confidence": 0.9,
                },
                "symptoms": {
                    "rawText": user_message,
                    "bodyLocation": None,
                    "durationText": None,
                },
                "needsFollowUp": False,
                "followUpQuestion": None,
                "followUpReason": None,
            }

        needs_follow_up = len(user_message.split()) < 5
        return {
            "reply": (
                "ขอบคุณสำหรับข้อมูล กรุณาบอกตำแหน่งอาการและระยะเวลาที่เป็น"
                if is_th
                else "Thank you. Please share symptom location and how long you have had it."
            ),
            "severity": {
                "level": "urgent" if routing_context else "unknown",
                "explanation": "AI fallback response",
                "confidence": 0.55,
            },
            "department": {
                "code": None,
                "reason": "Need more information",
                "confidence": 0.4,
            },
            "symptoms": {
                "rawText": user_message,
                "bodyLocation": None,
                "durationText": None,
            },
            "needsFollowUp": needs_follow_up,
            "followUpQuestion": (
                "อาการอยู่บริเวณไหน และเป็นมานานเท่าไร?"
                if is_th
                else "Where is the symptom located and how long has it lasted?"
            )
            if needs_follow_up
            else None,
            "followUpReason": "Incomplete symptom details" if needs_follow_up else None,
        }
