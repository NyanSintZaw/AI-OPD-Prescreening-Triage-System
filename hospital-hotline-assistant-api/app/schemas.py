from datetime import date, datetime, time
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

LanguageCode = Literal["th", "en"]
SessionStatus = Literal["active", "completed", "reset", "escalated"]
MessageRole = Literal["user", "assistant", "system"]
InputMode = Literal["voice", "text"]
SeverityLevel = Literal["emergency", "urgent", "general", "unknown"]
DepartmentKind = Literal["emergency", "opd"]
ReviewStatus = Literal["pending", "approved", "corrected"]


class TtsRequest(BaseModel):
    text: str
    language: LanguageCode = "en"


class SttResponse(BaseModel):
    transcript: str
    confidence: float | None = None
    language_code: str


class SessionCreate(BaseModel):
    language: LanguageCode = "th"
    user_agent: str | None = None
    ip_hash: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionUpdate(BaseModel):
    status: SessionStatus


class SessionLocationUpdate(BaseModel):
    location_area: str = Field(..., min_length=1, max_length=100)


class SessionOut(BaseModel):
    id: UUID
    language: LanguageCode
    status: SessionStatus
    started_at: datetime
    ended_at: datetime | None = None
    user_agent: str | None = None
    ip_hash: str | None = None
    metadata: dict[str, Any]


class MessageCreate(BaseModel):
    role: MessageRole
    input_mode: InputMode | None = None
    content: str
    audio_url: str | None = None
    transcript_confidence: float | None = Field(default=None, ge=0, le=1)
    model_name: str | None = None
    response_latency_ms: int | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MessageOut(MessageCreate):
    id: UUID
    session_id: UUID
    created_at: datetime


class SymptomEntryCreate(BaseModel):
    message_id: UUID | None = None
    raw_text: str
    normalized_symptoms: list[Any] = Field(default_factory=list)
    body_location: str | None = None
    duration_text: str | None = None
    pain_score: int | None = Field(default=None, ge=0, le=10)
    pain_location: str | None = None
    distress_score: int | None = Field(default=None, ge=0, le=10)
    distress_type: str | None = None
    red_flags: list[str] = Field(default_factory=list)


class SeverityAssessmentCreate(BaseModel):
    source_message_id: UUID | None = None
    severity: SeverityLevel = "unknown"
    confidence: float | None = Field(default=None, ge=0, le=1)
    explanation: str | None = None
    detected_triggers: list[Any] = Field(default_factory=list)


class DepartmentOut(BaseModel):
    id: UUID
    code: str
    kind: DepartmentKind
    name_en: str
    name_th: str | None = None
    description_en: str | None = None
    description_th: str | None = None
    is_active: bool


class RoutingRuleOut(BaseModel):
    id: UUID
    department_id: UUID
    rule_name: str
    description: str | None = None
    symptom_keywords: list[str]
    condition_json: dict[str, Any]
    severity_override: SeverityLevel | None = None
    priority: int
    is_active: bool


class EmergencyTriggerOut(BaseModel):
    id: UUID
    trigger_name: str
    description: str | None = None
    trigger_keywords: list[str]
    condition_json: dict[str, Any]
    alert_message_en: str
    alert_message_th: str | None = None
    priority: int
    is_active: bool


class DepartmentRecommendationCreate(BaseModel):
    assessment_id: UUID | None = None
    department_id: UUID
    confidence: float | None = Field(default=None, ge=0, le=1)
    reason: str | None = None


class EmergencyEventCreate(BaseModel):
    trigger_id: UUID | None = None
    source_message_id: UUID | None = None
    detected_symptoms: list[Any] = Field(default_factory=list)
    alert_message: str


class EmergencyEventOut(EmergencyEventCreate):
    id: UUID
    session_id: UUID
    created_at: datetime


class FollowUpQuestionCreate(BaseModel):
    question_text: str
    reason: str | None = None


class FollowUpQuestionOut(BaseModel):
    id: UUID
    session_id: UUID
    question_text: str
    reason: str | None = None
    asked_at: datetime
    answer_message_id: UUID | None = None
    answered_at: datetime | None = None


class FollowUpQuestionAnswerUpdate(BaseModel):
    answer_message_id: UUID


class ChatRequest(BaseModel):
    content: str
    input_mode: InputMode = "text"
    language: LanguageCode = "en"
    history: list[Any] = Field(default_factory=list)


class ChatSeverityOut(BaseModel):
    level: SeverityLevel
    explanation: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class ChatDepartmentOut(BaseModel):
    department_id: UUID | None = None
    reason: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class ChatEmergencyOut(BaseModel):
    trigger_id: UUID | None = None
    alert_message: str | None = None
    detected_symptoms: list[str] = Field(default_factory=list)


class ChatSymptomsOut(BaseModel):
    raw_text: str
    body_location: str | None = None
    duration_text: str | None = None
    pain_score: int | None = Field(default=None, ge=0, le=10)
    pain_location: str | None = None
    distress_score: int | None = Field(default=None, ge=0, le=10)
    distress_type: str | None = None
    red_flags: list[str] = Field(default_factory=list)


class ChatResponse(BaseModel):
    reply: str
    severity: ChatSeverityOut
    department: ChatDepartmentOut | None = None
    emergency: ChatEmergencyOut | None = None
    symptoms: ChatSymptomsOut | None = None
    contact: dict[str, Any] | None = None
    follow_up_question: str | None = None
    follow_up_reason: str | None = None
    model_name: str | None = None
    latency_ms: int | None = None
    alert_sent: bool = False
    assistant_message_id: UUID | None = None


class ConversationSummaryOut(BaseModel):
    session_id: UUID
    language: LanguageCode
    status: SessionStatus
    started_at: datetime
    ended_at: datetime | None = None
    severity: SeverityLevel | None = None
    department_name_en: str | None = None
    department_name_th: str | None = None
    message_count: int
    has_alert: bool = False
    escalation_reason: str | None = None


class AdminUserOut(BaseModel):
    id: UUID
    email: str
    full_name: str | None = None
    role: Literal["super_admin", "admin", "viewer"]


class AdminLoginRequest(BaseModel):
    email: str
    password: str


class AdminLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: AdminUserOut


class AssessmentReviewApproveRequest(BaseModel):
    notes: str | None = None
    ai_assessment_score: int | None = Field(default=None, ge=1, le=10)


class AssessmentReviewCorrectRequest(BaseModel):
    confirmed_department_id: UUID
    reason: str | None = None
    ai_assessment_score: int | None = Field(default=None, ge=1, le=10)


class AssessmentReviewOut(BaseModel):
    id: UUID
    session_id: UUID
    assessment_id: UUID
    status: ReviewStatus
    reviewer_id: UUID | None = None
    reviewer_name: str | None = None
    proposed_department_id: UUID | None = None
    proposed_department_name_en: str | None = None
    proposed_department_name_th: str | None = None
    confirmed_department_id: UUID | None = None
    confirmed_department_name_en: str | None = None
    confirmed_department_name_th: str | None = None
    ai_assessment_score: int | None = None
    ai_assessment_scale: int = 10
    patient_contact_requested: bool | None = None
    patient_contact_phone: str | None = None
    patient_contact_preferred_time: str | None = None
    patient_contact_relation: str | None = None
    notes: str | None = None
    reviewed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class RoutingFeedbackOut(BaseModel):
    id: UUID
    session_id: UUID
    assessment_id: UUID
    original_department_id: UUID | None = None
    corrected_department_id: UUID
    corrected_department_name_en: str | None = None
    corrected_department_name_th: str | None = None
    reported_by: UUID | None = None
    reporter_name: str | None = None
    reason: str | None = None
    created_at: datetime


# ── Doctor schedules ─────────────────────────────────────────────────────────

class DoctorScheduleCreate(BaseModel):
    schedule_date: date
    start_time: time
    end_time: time
    break_start: time | None = None
    break_end: time | None = None
    room: str | None = None
    slot_label: str | None = None
    is_available: bool = True
    notes: str | None = None


class DoctorScheduleOut(DoctorScheduleCreate):
    id: UUID
    doctor_id: UUID
    created_at: datetime
    updated_at: datetime


class DoctorCreate(BaseModel):
    full_name: str
    title: str = "Dr."
    specialization: str | None = None
    department_id: UUID | None = None
    phone_ext: str | None = None
    notes: str | None = None
    is_active: bool = True


class DoctorUpdate(BaseModel):
    full_name: str | None = None
    title: str | None = None
    specialization: str | None = None
    department_id: UUID | None = None
    phone_ext: str | None = None
    notes: str | None = None
    is_active: bool | None = None


class DoctorOut(BaseModel):
    id: UUID
    full_name: str
    title: str
    specialization: str | None = None
    department_id: UUID | None = None
    department_name_en: str | None = None
    department_name_th: str | None = None
    phone_ext: str | None = None
    notes: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class DoctorWithSchedulesOut(DoctorOut):
    schedules: list[DoctorScheduleOut] = Field(default_factory=list)


# ── Disease Surveillance ─────────────────────────────────────────────────────

class SymptomCount(BaseModel):
    keyword: str
    count: int


class AreaSymptomCount(BaseModel):
    area: str
    keyword: str
    count: int


class DailyCount(BaseModel):
    date: str
    count: int


class SeverityCount(BaseModel):
    severity_level: str | None
    count: int


class OutbreakAlert(BaseModel):
    keyword: str
    area: str | None
    recent_count: int
    previous_count: int
    increase_pct: float


class SurveillanceSummaryOut(BaseModel):
    days: int
    total_reports: int
    top_symptoms: list[SymptomCount]
    by_area: list[AreaSymptomCount]
    daily_trend: list[DailyCount]
    severity_distribution: list[SeverityCount]
    outbreak_alerts: list[OutbreakAlert]
