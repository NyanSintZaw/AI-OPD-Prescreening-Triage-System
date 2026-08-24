from datetime import date, datetime, time
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.services.screening.rules.criteria_models import default_vital_bounds

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


# Plausibility bounds come from the criteria defaults so the API, the engine,
# the cuff parser and the kiosk all refuse the same values — see
# docs/vital-bounds.md. These are a 422 backstop; the friendly re-ask happens
# before a request ever gets here.
_BOUNDS = default_vital_bounds()


class SessionVitalsUpdate(BaseModel):
    systolic: int = Field(..., ge=_BOUNDS["sbp"].min, le=_BOUNDS["sbp"].max)
    diastolic: int = Field(..., ge=_BOUNDS["dbp"].min, le=_BOUNDS["dbp"].max)
    pulse_bpm: int | None = Field(
        default=None, ge=_BOUNDS["hr"].min, le=_BOUNDS["hr"].max
    )
    # Patient-typed vitals captured at the booth alongside the cuff reading.
    weight_kg: float | None = Field(
        default=None, ge=_BOUNDS["weight"].min, le=_BOUNDS["weight"].max
    )
    height_cm: float | None = Field(
        default=None, ge=_BOUNDS["height"].min, le=_BOUNDS["height"].max
    )
    temperature_c: float | None = Field(
        default=None, ge=_BOUNDS["temp"].min, le=_BOUNDS["temp"].max
    )
    measured_at: datetime | None = None
    source: Literal["device", "manual"] = "device"
    reading_id: UUID | None = None

    @model_validator(mode="after")
    def _check_cross_field(self) -> "SessionVitalsUpdate":
        if self.systolic <= self.diastolic:
            raise ValueError("systolic must be greater than diastolic")
        return self


class SessionMeasurementUpdate(BaseModel):
    """A single vital captured mid-interview when the engine requests it
    (temperature once a fever is reported; weight/height near the end of the
    interview). Merges into the session's stored vitals without disturbing
    the blood-pressure reading (BP has its own PUT with provenance)."""

    vital: Literal["temp", "weight", "height", "spo2"]
    value: float

    @model_validator(mode="after")
    def _check_range(self) -> "SessionMeasurementUpdate":
        bound = _BOUNDS[self.vital]
        if not bound.contains(self.value):
            raise ValueError(
                f"{self.vital} must be between {bound.min} and {bound.max}"
            )
        return self


class LinkPatientRequest(BaseModel):
    hn: str = Field(..., min_length=1, max_length=64)
    # Same kiosk walk-up, identity already spoken-confirmed (e.g. start over
    # relinks on a fresh session): carry the confirmation atomically so the
    # new call never re-asks "are you {name}?".
    preconfirmed: bool = False


class LinkPatientResponse(BaseModel):
    linked: bool
    # Echoing the HN the patient just typed leaks nothing — unlike the old
    # VN flow, the HN IS what they entered. Everything else stays minimal:
    # this endpoint is unauthenticated by design.
    hn: str
    patient_name: str | None = None
    age_years: int | None = None
    # None when the HIS knows no open visit for this HN — screening still
    # runs; the write-backs then go HN-only.
    appointment: bool | None = None
    is_first_time: bool = False


class PatientHistoryIntakeRequest(BaseModel):
    """First-time-patient structured history collected at the booth.

    Field names per Data Requirements V1 §1.3: smoking and alcohol are
    separate questions, surgery history is ``post_surgeries``."""

    smoking: str | None = Field(default=None, max_length=500)
    alcohol: str | None = Field(default=None, max_length=500)
    allergies: str | None = Field(default=None, max_length=500)
    chronic_conditions: str | None = Field(default=None, max_length=500)
    post_surgeries: str | None = Field(default=None, max_length=500)
    family_history: str | None = Field(default=None, max_length=500)


class PatientHistoryIntakeResponse(BaseModel):
    saved: bool
    pushed_to_his: bool
    is_first_time: bool = False
    # No `hn`: the kiosk never renders it, and a patient-facing response has no
    # reason to carry a hospital number back to the browser.


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
        # Records were returned but none were physiologically possible —
        # the patient is asked to measure again straight away (no rest window).
        "implausible",
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
    """Whether this patient (HN) must wait before another BP reading."""

    resting: bool
    rest_until: datetime | None = None
    seconds_remaining: int = 0
    reason: str | None = None
    hn: str | None = None


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


class TempFetchRequest(BaseModel):
    """Body for the thermometer fetch: waits for the device to push a
    measurement, links the stored reading to the kiosk session when given."""

    session_id: UUID | None = None
    timeout_seconds: float | None = Field(default=None, ge=5, le=180)


class TemperatureFetchResponse(BaseModel):
    """Result of a kiosk-side thermometer fetch. ``status`` is always set;
    the reading fields are only present when ``status == "ok"``."""

    status: Literal[
        "ok",
        "busy",
        "not_configured",
        "device_not_found",
        "wrong_device",
        "timeout",
        "error",
    ]
    temperature_c: float | None = None
    measured_at: datetime | None = None
    message: str | None = None
    reading_id: UUID | None = None


class TempDeviceStatusOut(BaseModel):
    """Current thermometer configuration shown in the admin portal."""

    device_name: str
    device_mac: str | None
    configured: bool
    busy: bool


class TempScanDeviceOut(BaseModel):
    mac: str
    name: str | None = None
    rssi: int | None = None
    is_thermometer: bool = False


class TempScanResponse(BaseModel):
    status: Literal["ok", "busy", "error"]
    devices: list[TempScanDeviceOut] = Field(default_factory=list)
    message: str | None = None


class TempPairRequest(BaseModel):
    mac: str = Field(..., min_length=1, max_length=64)
    # Advertised name from the scan list; shown in the portal after pairing.
    # Optional — the backend falls back to the device's GAP name.
    name: str | None = Field(default=None, max_length=64)


class TempPairResponse(BaseModel):
    status: Literal[
        "ok",
        "busy",
        "invalid",
        "device_not_found",
        "wrong_device",
        "timeout",
        "error",
    ]
    device_name: str | None = None
    device_mac: str | None = None


class Spo2FetchRequest(BaseModel):
    """Body for the pulse-oximeter fetch: waits for a settled fingertip
    reading, links the stored reading to the kiosk session when given."""

    session_id: UUID | None = None
    timeout_seconds: float | None = Field(default=None, ge=5, le=180)


class Spo2FetchResponse(BaseModel):
    """Result of a kiosk-side pulse-oximeter fetch. ``status`` is always
    set; the reading fields are only present when ``status == "ok"``.
    ``timeout`` = no finger was ever detected; ``unstable`` = a finger was
    seen but the values never held steady long enough to trust."""

    status: Literal[
        "ok",
        "busy",
        "not_configured",
        "device_not_found",
        "wrong_device",
        "timeout",
        "unstable",
        "error",
    ]
    spo2: int | None = None
    pulse_bpm: int | None = None
    measured_at: datetime | None = None
    message: str | None = None
    reading_id: UUID | None = None


class Spo2DeviceStatusOut(BaseModel):
    """Current pulse-oximeter configuration shown in the admin portal."""

    device_name: str
    device_mac: str | None
    configured: bool
    busy: bool


class Spo2ScanDeviceOut(BaseModel):
    mac: str
    name: str | None = None
    rssi: int | None = None
    is_oximeter: bool = False


class Spo2ScanResponse(BaseModel):
    status: Literal["ok", "busy", "error"]
    devices: list[Spo2ScanDeviceOut] = Field(default_factory=list)
    message: str | None = None


class Spo2PairRequest(BaseModel):
    mac: str = Field(..., min_length=1, max_length=64)
    # Advertised name from the scan list; shown in the portal after pairing.
    name: str | None = Field(default=None, max_length=64)


class Spo2PairResponse(BaseModel):
    status: Literal[
        "ok",
        "busy",
        "invalid",
        "device_not_found",
        "wrong_device",
        "timeout",
        "error",
    ]
    device_name: str | None = None
    device_mac: str | None = None
    message: str | None = None


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


class ConfirmPatientNameRequest(BaseModel):
    """Patient response to \"Is this you, {name}?\" after link-patient.

    Provide either ``confirmed`` (button) or ``text`` (typed/spoken natural
    language). When ``text`` is set, the shared yes/no classifier decides.
    """

    confirmed: bool | None = None
    text: str | None = Field(default=None, max_length=200)


class ConfirmPatientNameResponse(BaseModel):
    """Outcome of the HN name-confirm step."""

    decision: Literal["yes", "no", "uncertain", "other"]
    name_confirmed: bool
    unlinked: bool = False
    patient_name: str | None = None


class SessionByHnOut(BaseModel):
    """Result of looking up a recent session by patient HN.

    ``found=False`` when no recent-window session is linked to this HN — the
    client should create a new session and call ``link-patient``. When
    ``found=True``, ``status`` says what the kiosk should offer: ``active``
    → continue or start over; ``completed`` → start over / reprint slip.
    """

    found: bool
    hn: str
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
    role: Literal["super_admin", "nurse", "viewer"]


class AdminUserManageOut(AdminUserOut):
    """Row in the admin User Settings table (nurse accounts)."""

    is_active: bool
    last_login_at: datetime | None = None
    created_at: datetime


class AdminUserCreate(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    full_name: str = Field(..., min_length=1, max_length=150)
    password: str = Field(..., min_length=8, max_length=128)
    # Only nurse accounts are manageable from the UI for now.
    role: Literal["nurse"] = "nurse"


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
    # Whether an access token is saved — the token itself is never echoed.
    has_api_key: bool = False


class HisConnectionUpdate(BaseModel):
    endpoint: str = Field(..., min_length=8, max_length=500)  # http(s)://…
    name: str = Field(..., min_length=1, max_length=120)
    # Optional bearer token; blank/omitted keeps the currently saved one.
    api_key: str | None = Field(None, max_length=500)


class AdminLoginRequest(BaseModel):
    email: str
    password: str


class AdminLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: AdminUserOut


class SbarPayload(BaseModel):
    """Clinical handover sent to the hospital with a patient assignment.

    All seven fields are nurse-editable in the review dialog. When a request
    omits ``sbar`` entirely the server rebuilds it from the engine, so
    non-UI callers (Postman, scripts) need not construct one. When it IS
    present it is authoritative **in full** — a field the nurse deliberately
    blanked must stay blank, so there is no per-field merge.
    """

    situation: str | None = None
    background: str | None = None
    assessment: str | None = None
    assessment_problem: str | None = None
    assessment_equipment: str | None = None
    recommend: str | None = None
    documentation: str | None = None


class SbarPreviewRequest(BaseModel):
    """The nurse's current draft, since SBAR depends on all three."""

    department_id: UUID | None = None
    chief_complaint: str | None = None
    illness_note: str | None = None


class AssessmentReviewApproveRequest(BaseModel):
    notes: str | None = None
    # Nurse-entered VN when the HIS gave us no current_visit at link time —
    # written to metadata.patient.visit_id before the Stage-2 push.
    visit_id: str | None = Field(default=None, max_length=64)
    ai_assessment_score: int | None = Field(default=None, ge=1, le=10)
    # Nurse-confirmed clinical narrative (edited or accepted as-is); published
    # to the HIS at Stage 2. None keeps the AI's values.
    chief_complaint: str | None = None
    illness_note: str | None = None
    sbar: SbarPayload | None = None


class AssessmentReviewCorrectRequest(BaseModel):
    confirmed_department_id: UUID
    reason: str | None = None
    visit_id: str | None = Field(default=None, max_length=64)
    ai_assessment_score: int | None = Field(default=None, ge=1, le=10)
    chief_complaint: str | None = None
    illness_note: str | None = None
    sbar: SbarPayload | None = None


class TriageStatsOut(BaseModel):
    """Operational triage numbers for the nurse and admin dashboards.

    One round trip for every panel: queue pressure, acuity mix, arrival
    rhythm, department load, and how often a nurse rerouted what the engine
    proposed. Staff-only — nothing here is ever shown to a patient.
    """

    days: int
    pending_reviews: int
    # Wait of the longest-pending confirmation. None when the queue is empty.
    oldest_pending_minutes: int | None = None
    # [{level: 1..5 | None, count}] over the window.
    acuity: list[dict[str, Any]] = []
    # [{hour: 0..23, count}] for today, dense — a gap must read as zero, not
    # as "no bar drawn here".
    hourly_today: list[dict[str, Any]] = []
    # [{code, name_en, name_th, count}] by the department the patient actually
    # went to (nurse-confirmed when present, else engine-proposed).
    departments: list[dict[str, Any]] = []
    # {reviewed, confirmed, rerouted, agreement_rate, avg_review_minutes}
    agreement: dict[str, Any] = {}
    # [{date, sessions, screened}] dense across the whole window.
    daily: list[dict[str, Any]] = []


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
    # The engine's MOPH 5-level decision, so the nurse queue can be sorted and
    # coloured by acuity. Nurse/admin surfaces only — never sent to a patient.
    # Null until the engine disposed (interview turns stay unclassified).
    triage_level: int | None = None
    triage_label: str | None = None
    triage_response_time: str | None = None
    notes: str | None = None
    # Booth context for the review screen: measurements taken at the kiosk,
    # the linked patient (HN-first; visit_id is the VN passthrough when the
    # HIS knew an open visit), and the AI narrative the nurse can edit before
    # it is published to the HIS at Stage 2.
    visit_id: str | None = None
    patient_name: str | None = None
    patient_hn: str | None = None
    # HN-level history snapshot from session metadata: written at visit link
    # (returning patients, copied from the HIS master record) or by the
    # first-time intake — the same record the admin Patient (HN) view shows.
    patient_history: dict[str, Any] | None = None
    vitals: dict[str, Any] | None = None
    # Undertriage caution: core vitals (hr/rr/spo2/temp/sbp) never
    # instrument-measured this session. Null until the engine disposed.
    missing_vitals: list[str] | None = None
    # Values reported but refused as physiologically impossible, keyed by
    # canonical vital: {value, reason, source, attempts, ...}. Shown flagged in
    # nurse review — never blank — and never published to the HIS.
    rejected_vitals: dict[str, Any] | None = None
    ai_chief_complaint: str | None = None
    ai_illness_note: str | None = None
    patient_follow_up: str | None = None
    chief_complaint: str | None = None
    illness_note: str | None = None
    # Stage-2 outcome. status: pushed | denied | unavailable | invalid |
    # unknown | skipped (see AssignmentResult). queue_number is what the nurse
    # reads out to the patient; message_th is the hospital's own Thai wording.
    his_routing_status: str | None = None
    his_queue_number: str | None = None
    his_routing_message_th: str | None = None
    his_request_id: str | None = None
    # Whether the patient-facing explanation drew on the uploaded triage
    # manual: {used, reason, hits[{title,page,chars}], chars, latency_ms}.
    # Null for sessions that never reached the explain step.
    rag_grounding: dict[str, Any] | None = None
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
