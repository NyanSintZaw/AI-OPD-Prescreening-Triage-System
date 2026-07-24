from datetime import date, datetime, time
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

LanguageCode = Literal["th", "en"]
SessionStatus = Literal["active", "completed", "reset", "escalated"]
MessageRole = Literal["user", "assistant", "system"]
InputMode = Literal["voice", "text", "button"]
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


class SessionVitalsUpdate(BaseModel):
    systolic: int = Field(..., ge=40, le=300)
    diastolic: int = Field(..., ge=20, le=200)
    pulse_bpm: int | None = Field(default=None, ge=20, le=250)
    # Patient-typed vitals captured at the booth alongside the cuff reading.
    weight_kg: float | None = Field(default=None, gt=0, le=400)
    height_cm: float | None = Field(default=None, gt=0, le=272)
    temperature_c: float | None = Field(default=None, ge=30, le=45)
    measured_at: datetime | None = None
    source: Literal["device", "manual"] = "device"
    reading_id: UUID | None = None


class SessionMeasurementUpdate(BaseModel):
    """A single vital captured mid-interview when the engine requests it
    (temperature once a fever is reported; weight/height near the end of the
    interview). Merges into the session's stored vitals without disturbing
    the blood-pressure reading (BP has its own PUT with provenance)."""

    vital: Literal["temp", "weight", "height"]
    value: float

    @model_validator(mode="after")
    def _check_range(self) -> "SessionMeasurementUpdate":
        low, high = {
            "temp": (25.0, 45.0),      # °C
            "weight": (1.0, 400.0),    # kg
            "height": (30.0, 272.0),   # cm
        }[self.vital]
        if not (low <= self.value <= high):
            raise ValueError(f"{self.vital} must be between {low} and {high}")
        return self


class LinkVisitRequest(BaseModel):
    visit_id: str = Field(..., min_length=1, max_length=64)


class LinkVisitResponse(BaseModel):
    linked: bool
    visit_id: str
    patient_name: str | None = None
    age_years: int | None = None
    appointment: bool = False
    has_his_vitals: bool = False
    is_first_time: bool = False
    hn: str | None = None


class PatientHistoryIntakeRequest(BaseModel):
    """First-time-patient structured history collected at the booth."""

    smoking_alcohol: str | None = Field(default=None, max_length=500)
    allergies: str | None = Field(default=None, max_length=500)
    chronic_conditions: str | None = Field(default=None, max_length=500)
    past_surgeries: str | None = Field(default=None, max_length=500)
    family_history: str | None = Field(default=None, max_length=500)


class PatientHistoryIntakeResponse(BaseModel):
    saved: bool
    pushed_to_his: bool
    is_first_time: bool = False
    hn: str | None = None


class BpFetchRequest(BaseModel):
    """Optional body for the cuff fetch: links the stored reading to the
    kiosk session as soon as it is captured."""

    session_id: UUID | None = None


class BpWatchRequest(BaseModel):
    """Body for the long-poll watch: wait up to ``timeout_seconds`` for the
    cuff's finished-measurement broadcast, then fetch immediately."""

    session_id: UUID | None = None
    timeout_seconds: float = Field(default=25, ge=5, le=45)


class BloodPressureFetchResponse(BaseModel):
    """Result of a kiosk-side omblepy fetch. ``status`` is always set;
    the reading fields are only present when ``status == "ok"``."""

    status: Literal[
        "ok",
        "busy",
        "not_configured",
        "device_not_found",
        "pairing_error",
        "wrong_device",
        "timeout",
        "no_records",
        "not_seen",
        "resting",
        "error",
    ]
    systolic: int | None = None
    diastolic: int | None = None
    pulse_bpm: int | None = None
    measured_at: datetime | None = None
    is_recent: bool | None = None
    irregular_heartbeat: bool | None = None
    body_movement: bool | None = None
    message: str | None = None
    reading_id: UUID | None = None
    rest_until: datetime | None = None
    seconds_remaining: int | None = None


class BpRestStatusOut(BaseModel):
    """Whether this patient/visit must wait before another BP reading."""

    resting: bool
    rest_until: datetime | None = None
    seconds_remaining: int = 0
    reason: str | None = None
    hn: str | None = None
    visit_id: str | None = None


class BpDeviceStatusOut(BaseModel):
    """Current cuff configuration shown in the admin portal."""

    device_name: str
    device_mac: str | None
    configured: bool
    busy: bool
    supported_models: list[str]


class BpScanDeviceOut(BaseModel):
    mac: str
    name: str | None = None
    rssi: int | None = None
    is_omron: bool = False


class BpScanResponse(BaseModel):
    status: Literal["ok", "busy", "error"]
    devices: list[BpScanDeviceOut] = Field(default_factory=list)
    message: str | None = None


class BpPairRequest(BaseModel):
    mac: str = Field(..., min_length=1, max_length=64)
    device_name: str = Field(..., min_length=1, max_length=32)


class BpPairResponse(BaseModel):
    status: Literal[
        "ok",
        "busy",
        "invalid",
        "device_not_found",
        "pairing_error",
        "wrong_device",
        "timeout",
        "not_configured",
        "error",
    ]
    device_name: str | None = None
    device_mac: str | None = None
    message: str | None = None


class SessionOut(BaseModel):
    id: UUID
    language: LanguageCode
    status: SessionStatus
    started_at: datetime
    ended_at: datetime | None = None
    user_agent: str | None = None
    ip_hash: str | None = None
    metadata: dict[str, Any]


class ConfirmVisitNameRequest(BaseModel):
    """Patient response to \"Is this you, {name}?\" after link-visit.

    Provide either ``confirmed`` (button) or ``text`` (typed/spoken natural
    language). When ``text`` is set, the shared yes/no classifier decides.
    """

    confirmed: bool | None = None
    text: str | None = Field(default=None, max_length=200)


class ConfirmVisitNameResponse(BaseModel):
    """Outcome of the VN name-confirm step."""

    decision: Literal["yes", "no", "uncertain", "other"]
    name_confirmed: bool
    unlinked: bool = False
    patient_name: str | None = None


class SessionByVisitOut(BaseModel):
    """Result of looking up a recent session by hospital visit ID (VN).

    ``found=False`` when no same-day session is linked to this VN — the
    client should create a new session and call ``link-visit``. When
    ``found=True``, ``status`` says what the kiosk should offer: ``active``
    → continue or start over; ``completed`` → start over / reprint slip.
    """

    found: bool
    visit_id: str
    session: SessionOut | None = None
    status: str | None = None
    patient_name: str | None = None
    name_confirmed: bool = False
    needs_history_intake: bool = False


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
    floor: str | None = None
    room: str | None = None
    nav_hint_en: str | None = None
    nav_hint_th: str | None = None
    nav_line_en: str | None = None
    nav_line_th: str | None = None


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
    assessment_status: str | None = None  # "complete" | "in_progress"
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
    awaiting_measurement: str | None = None
    reply_options: list[dict[str, str]] = Field(default_factory=list)
    flow_complete: bool = False


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


class AdminUserManageOut(AdminUserOut):
    """Row in the admin User Settings table (nurse accounts)."""

    is_active: bool
    last_login_at: datetime | None = None
    created_at: datetime


class AdminUserCreate(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    full_name: str = Field(..., min_length=1, max_length=150)
    password: str = Field(..., min_length=8, max_length=128)
    # Only nurse accounts (role "admin") are manageable from the UI for now.
    role: Literal["admin"] = "admin"


class AdminUserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=150)
    password: str | None = Field(default=None, min_length=8, max_length=128)
    is_active: bool | None = None


class HisConnectionOut(BaseModel):
    """Hospital-DB connection state shown in admin Database Settings."""

    mode: Literal["mock", "http"]
    endpoint: str | None = None
    name: str
    connected: bool
    visit_count: int | None = None
    message: str | None = None


class HisConnectionUpdate(BaseModel):
    endpoint: str = Field(..., min_length=8, max_length=500)  # http(s)://…
    name: str = Field(..., min_length=1, max_length=120)


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
    # Nurse-confirmed clinical narrative (edited or accepted as-is); published
    # to the HIS at Stage 2. None keeps the AI's values.
    chief_complaint: str | None = None
    illness_note: str | None = None


class AssessmentReviewCorrectRequest(BaseModel):
    confirmed_department_id: UUID
    reason: str | None = None
    ai_assessment_score: int | None = Field(default=None, ge=1, le=10)
    chief_complaint: str | None = None
    illness_note: str | None = None


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
    # AI reasoning trace: fired rule ids + manual citations (screening engine v2)
    disposition_reasons: list[dict[str, Any]] | None = None
    notes: str | None = None
    # Booth context for the review screen: measurements taken at the kiosk,
    # the linked HIS visit, and the AI narrative the nurse can edit before it
    # is published to the HIS at Stage 2.
    visit_id: str | None = None
    patient_name: str | None = None
    vitals: dict[str, Any] | None = None
    ai_chief_complaint: str | None = None
    ai_illness_note: str | None = None
    patient_follow_up: str | None = None
    chief_complaint: str | None = None
    illness_note: str | None = None
    his_routing_status: str | None = None
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
