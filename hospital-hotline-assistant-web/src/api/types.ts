export type LanguageCode = 'th' | 'en';
export type SessionStatus = 'active' | 'completed' | 'reset' | 'escalated';
export type MessageRole = 'user' | 'assistant' | 'system';
export type InputMode = 'voice' | 'text' | 'button';
export type SeverityLevel = 'emergency' | 'urgent' | 'general' | 'unknown';
export type DepartmentKind = 'emergency' | 'opd';
export type ReviewStatus = 'pending' | 'approved' | 'corrected';

export interface SessionCreate {
  language?: LanguageCode;
  user_agent?: string | null;
  ip_hash?: string | null;
  metadata?: Record<string, unknown>;
}

export interface SessionUpdate {
  status: SessionStatus;
}

export interface SessionOut {
  id: string;
  language: LanguageCode;
  status: SessionStatus;
  started_at: string;
  ended_at: string | null;
  user_agent: string | null;
  ip_hash: string | null;
  metadata: Record<string, unknown>;
}

export interface MessageCreate {
  role: MessageRole;
  input_mode?: InputMode | null;
  content: string;
  audio_url?: string | null;
  transcript_confidence?: number | null;
  model_name?: string | null;
  response_latency_ms?: number | null;
  metadata?: Record<string, unknown>;
}

export interface MessageOut extends MessageCreate {
  id: string;
  session_id: string;
  created_at: string;
}

export interface SymptomEntryCreate {
  message_id?: string | null;
  raw_text: string;
  normalized_symptoms?: unknown[];
  body_location?: string | null;
  duration_text?: string | null;
  pain_score?: number | null;
  pain_location?: string | null;
  distress_score?: number | null;
  distress_type?: string | null;
  red_flags?: string[];
}

export interface SeverityAssessmentCreate {
  source_message_id?: string | null;
  severity?: SeverityLevel;
  confidence?: number | null;
  explanation?: string | null;
  detected_triggers?: unknown[];
}

export interface DepartmentOut {
  id: string;
  code: string;
  kind: DepartmentKind;
  name_en: string;
  name_th: string | null;
  description_en: string | null;
  description_th: string | null;
  is_active: boolean;
  floor?: string | null;
  room?: string | null;
  nav_hint_en?: string | null;
  nav_hint_th?: string | null;
  nav_line_en?: string | null;
  nav_line_th?: string | null;
}

export interface RoutingRuleOut {
  id: string;
  department_id: string;
  rule_name: string;
  description: string | null;
  symptom_keywords: string[];
  condition_json: Record<string, unknown>;
  severity_override: SeverityLevel | null;
  priority: number;
  is_active: boolean;
}

export interface EmergencyTriggerOut {
  id: string;
  trigger_name: string;
  description: string | null;
  trigger_keywords: string[];
  condition_json: Record<string, unknown>;
  alert_message_en: string;
  alert_message_th: string | null;
  priority: number;
  is_active: boolean;
}

export interface DepartmentRecommendationCreate {
  assessment_id?: string | null;
  department_id: string;
  confidence?: number | null;
  reason?: string | null;
}

export interface EmergencyEventCreate {
  trigger_id?: string | null;
  source_message_id?: string | null;
  detected_symptoms?: unknown[];
  alert_message: string;
}

export interface ConversationSummaryOut {
  session_id: string;
  language: LanguageCode;
  status: SessionStatus;
  started_at: string;
  ended_at: string | null;
  severity: SeverityLevel | null;
  department_name_en: string | null;
  department_name_th: string | null;
  message_count: number;
  has_alert: boolean;
  escalation_reason: string | null;
}

export interface AdminUserOut {
  id: string;
  email: string;
  full_name: string | null;
  role: 'super_admin' | 'nurse' | 'viewer';
}

export interface AdminLoginRequest {
  email: string;
  password: string;
}

export interface AdminLoginResponse {
  access_token: string;
  token_type: 'bearer';
  expires_at: string;
  user: AdminUserOut;
}

export interface AssessmentReviewOut {
  id: string;
  session_id: string;
  assessment_id: string;
  status: ReviewStatus;
  reviewer_id: string | null;
  reviewer_name: string | null;
  proposed_department_id: string | null;
  proposed_department_name_en: string | null;
  proposed_department_name_th: string | null;
  confirmed_department_id: string | null;
  confirmed_department_name_en: string | null;
  confirmed_department_name_th: string | null;
  ai_assessment_score: number | null;
  ai_assessment_scale: number;
  patient_contact_requested: boolean | null;
  patient_contact_phone: string | null;
  patient_contact_preferred_time: string | null;
  patient_contact_relation: string | null;
  /** Screening engine v2: fired rule ids + manual citations behind the routing. */
  disposition_reasons?: Array<{
    rule_id: string;
    text_en: string;
    text_th: string;
    citation?: string;
  }> | null;
  notes: string | null;
  /** Booth context: linked HIS visit + measurements taken at the kiosk. */
  visit_id?: string | null;
  patient_name?: string | null;
  patient_hn?: string | null;
  /** HN-level history snapshot — the same record the admin Patient (HN) view
   *  shows: copied from the HIS at visit link (returning patients) or written
   *  by the first-time booth intake. Null for anonymous sessions. */
  patient_history?: {
    is_first_time?: boolean | null;
    smoking_alcohol?: string | null;
    allergies?: string | null;
    chronic_conditions?: string | null;
    past_surgeries?: string | null;
    family_history?: string | null;
    recorded_at?: string | null;
    last_weight_kg?: number | null;
    last_height_cm?: number | null;
    vitals_measured_at?: string | null;
  } | null;
  vitals?: {
    systolic?: number | null;
    diastolic?: number | null;
    pulse_bpm?: number | null;
    weight_kg?: number | null;
    height_cm?: number | null;
    temperature?: number | null;
    source?: string | null;
  } | null;
  /** Core vitals (hr/rr/spo2/temp/sbp) never instrument-measured this
   *  session — shown as an undertriage caution. Null for non-disposed rows. */
  missing_vitals?: string[] | null;
  /** Values the patient or cuff reported that were refused as
   *  physiologically impossible, keyed by canonical vital. Shown flagged with
   *  the reported number — a blank would read as "never measured", which is a
   *  different and much less alarming thing. Never published to the HIS. */
  rejected_vitals?: Record<string, RejectedVital> | null;
  /** AI narrative (read-only originals the nurse can edit before publishing). */
  ai_chief_complaint?: string | null;
  ai_illness_note?: string | null;
  /** Patient note captured after disposition for the doctor. */
  patient_follow_up?: string | null;
  /** Nurse-signed narrative, set on confirm. */
  chief_complaint?: string | null;
  illness_note?: string | null;
  /**
   * Stage-2 hospital outcome:
   * pushed | denied | unavailable | invalid | unknown | skipped.
   * `unknown` means we never learned whether the queue row was created —
   * deliberately not "failed", because a retry is safe and re-queueing is not.
   */
  his_routing_status?: string | null;
  /** What the nurse reads out to the patient. */
  his_queue_number?: string | null;
  /** The hospital's own Thai wording; show this, never the English enum. */
  his_routing_message_th?: string | null;
  his_request_id?: string | null;
  reviewed_at: string | null;
  created_at: string;
  updated_at: string;
}

/** Clinical handover sent to the hospital. All seven fields are
 *  nurse-editable; omitting `sbar` entirely makes the server rebuild it. */
export interface SbarFields {
  situation?: string | null;
  background?: string | null;
  assessment?: string | null;
  assessment_problem?: string | null;
  assessment_equipment?: string | null;
  recommend?: string | null;
  documentation?: string | null;
}

export interface SbarPreviewRequest {
  department_id?: string | null;
  chief_complaint?: string | null;
  illness_note?: string | null;
}

export interface AssessmentReviewApproveRequest {
  notes?: string | null;
  ai_assessment_score?: number | null;
  chief_complaint?: string | null;
  illness_note?: string | null;
  sbar?: SbarFields | null;
}

export interface AssessmentReviewCorrectRequest {
  confirmed_department_id: string;
  reason?: string | null;
  ai_assessment_score?: number | null;
  chief_complaint?: string | null;
  illness_note?: string | null;
  sbar?: SbarFields | null;
}

export interface RoutingFeedbackOut {
  id: string;
  session_id: string;
  assessment_id: string;
  original_department_id: string | null;
  corrected_department_id: string;
  corrected_department_name_en: string | null;
  corrected_department_name_th: string | null;
  reported_by: string | null;
  reporter_name: string | null;
  reason: string | null;
  created_at: string;
}

/** Final assessment payload — the terminal `complete` stream event and the
 *  voice WS `assessment_complete` frame both carry this shape. */
export interface ChatResponsePayload {
  reply: string;
  severity: {
    level: SeverityLevel;
    explanation?: string;
    confidence?: number;
  };
  /** Screening engine v2: patients never see the level; gate UI on this. */
  assessment_status?: 'complete' | 'in_progress' | null;
  /** Set to a vital key (e.g. 'temp') when the engine asks the booth to take
   *  a reading mid-interview; the UI pops a numeric input for it. */
  awaiting_measurement?: string | null;
  /** Localized quick-reply chips under the assistant bubble. */
  reply_options?: Array<{ id: string; label: string }>;
  /** True when the patient-facing flow (incl. follow-up) is finished. */
  flow_complete?: boolean;
  department?: {
    department_id?: string;
    reason?: string;
    confidence?: number;
  } | null;
  emergency?: {
    trigger_id?: string;
    alert_message: string;
    detected_symptoms?: string[];
  } | null;
  symptoms?: {
    raw_text: string;
    body_location?: string | null;
    duration_text?: string | null;
    pain_score?: number | null;
    pain_location?: string | null;
    distress_score?: number | null;
    distress_type?: string | null;
    red_flags?: string[];
  } | null;
  contact?: Record<string, unknown> | null;
  follow_up_question?: string | null;
  follow_up_reason?: string | null;
  model_name?: string | null;
  latency_ms?: number | null;
  alert_sent?: boolean;
  assistant_message_id?: string | null;
}

export interface FollowUpQuestionOut {
  id: string;
  session_id: string;
  question_text: string;
  reason: string | null;
  asked_at: string;
  answer_message_id: string | null;
  answered_at: string | null;
}

export interface EmergencyEventOut {
  id: string;
  session_id: string;
  trigger_id?: string | null;
  source_message_id?: string | null;
  detected_symptoms: unknown[];
  alert_message: string;
  created_at: string;
}

export interface SttResponsePayload {
  transcript: string;
  confidence: number | null;
  language_code: string;
}

export interface ApiError {
  detail: string;
}

// ── Doctor schedules ─────────────────────────────────────────────────────────

export interface DoctorScheduleCreate {
  schedule_date: string;
  start_time: string;
  end_time: string;
  break_start?: string | null;
  break_end?: string | null;
  room?: string | null;
  slot_label?: string | null;
  is_available: boolean;
  notes?: string | null;
}

export interface DoctorScheduleOut extends DoctorScheduleCreate {
  id: string;
  doctor_id: string;
  created_at: string;
  updated_at: string;
}

export interface DoctorCreate {
  full_name: string;
  title?: string;
  specialization?: string | null;
  department_id?: string | null;
  phone_ext?: string | null;
  notes?: string | null;
  is_active?: boolean;
}

export interface DoctorUpdate {
  full_name?: string;
  title?: string;
  specialization?: string | null;
  department_id?: string | null;
  phone_ext?: string | null;
  notes?: string | null;
  is_active?: boolean;
}

export interface DoctorOut {
  id: string;
  full_name: string;
  title: string;
  specialization: string | null;
  department_id: string | null;
  department_name_en: string | null;
  department_name_th: string | null;
  phone_ext: string | null;
  notes: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface DoctorWithSchedulesOut extends DoctorOut {
  schedules: DoctorScheduleOut[];
}

// ── Vitals (blood pressure kiosk) ─────────────────────────────────────────────

export type BloodPressureFetchStatus =
  | 'ok'
  | 'busy'
  | 'not_configured'
  | 'device_not_found'
  | 'pairing_error'
  | 'wrong_device'
  | 'timeout'
  | 'no_records'
  /** Records came back but none were physiologically possible — re-measure
   *  immediately (this is not a crisis reading, so no rest window). */
  | 'implausible'
  | 'not_seen'
  | 'resting'
  | 'error';

export interface BloodPressureFetchResponse {
  status: BloodPressureFetchStatus;
  systolic: number | null;
  diastolic: number | null;
  pulse_bpm: number | null;
  measured_at: string | null;
  is_recent: boolean | null;
  irregular_heartbeat: boolean | null;
  body_movement: boolean | null;
  message: string | null;
  reading_id?: string | null;
  rest_until?: string | null;
  seconds_remaining?: number | null;
}

export interface BpRestStatusOut {
  resting: boolean;
  rest_until: string | null;
  seconds_remaining: number;
  reason: string | null;
  hn: string | null;
  visit_id: string | null;
}

/** One value refused as physiologically impossible. `value` is what was
 *  actually reported, kept so nurse review can show it flagged. */
export interface RejectedVital {
  vital: string;
  value: number;
  /** 'out_of_range' | 'sbp_le_dbp' | 'bmi_implausible' */
  reason: string;
  /** 'reported' (patient said it) | 'measured' (cuff/HIS sent it) */
  source?: string;
  attempts?: number;
  turn?: number;
  text_en?: string;
  text_th?: string;
}

/** Physiologically possible range for one vital, from the active criteria. */
export interface VitalBound {
  min: number;
  max: number;
  unit: string;
  retry_text_en: string;
  retry_text_th: string;
}

export interface VitalBoundsOut {
  bounds: Record<string, VitalBound>;
  cross_checks: Record<string, { text_en: string; text_th: string }>;
}

export interface SessionVitalsUpdate {
  systolic: number;
  diastolic: number;
  pulse_bpm?: number | null;
  weight_kg?: number | null;
  height_cm?: number | null;
  temperature_c?: number | null;
  measured_at?: string | null;
  source?: 'device' | 'manual';
  reading_id?: string | null;
}

export interface LinkVisitRequest {
  visit_id: string;
  /** Identity already spoken-confirmed in this kiosk run (start-over relink)
   *  — the fresh session must not re-ask "are you {name}?". */
  preconfirmed?: boolean;
}

export type HisScreeningStatus = 'registered' | 'screened' | 'routed';

export interface HisVisitSummary {
  visit_id: string;
  hnx: string | null;
  patient_name?: string | null;
  appointment: boolean;
  birthdate: string | null;
  screening_status: HisScreeningStatus;
  modify_time: string | null;
}

export interface HisVisitDetail {
  visit_id: string;
  hnx: string | null;
  patient_name?: string | null;
  appointment: boolean;
  birthdate: string | null;
  screening_status: HisScreeningStatus;
  vitals: {
    weight: number | null;
    height: number | null;
    bmi: number | null;
    waist_width: number | null;
    pressure: string | null;
    systolic: number | null;
    diastolic: number | null;
    temperature: number | null;
    pulse: number | null;
  };
  measure: { spid: string | null; name: string | null; department: string | null };
  nurse_chief_complaint: string | null;
  nurse_patient_illness: string | null;
  /** Patient note captured at the booth after disposition (Stage 1). */
  follow_up?: string | null;
  first_location: { id: string | null; name: string | null; department: string | null };
  second_location: { id: string | null; name: string | null; department: string | null };
  modify_time: string | null;
}

export interface HisVisitsResponse {
  available: boolean;
  visits: HisVisitSummary[];
}

export interface HisVisitDetailResponse {
  available: boolean;
  visit: HisVisitDetail | null;
}

/** HN master record row from the hospital DB (admin Database → HN tab). */
export interface HisPatientSummary {
  hn: string;
  patient_name: string | null;
  birthdate: string | null;
  is_first_time: boolean;
  history: {
    smoking_alcohol: string | null;
    allergies: string | null;
    chronic_conditions: string | null;
    past_surgeries: string | null;
    family_history: string | null;
    recorded_at: string | null;
  };
  last_vitals: {
    weight: number | null;
    height: number | null;
    measured_at: string | null;
  };
  visit_count: number;
}

export interface HisPatientsResponse {
  available: boolean;
  patients: HisPatientSummary[];
}

export interface HisConnection {
  mode: 'mock' | 'http';
  endpoint: string | null;
  /** Display name shown as the Hospital Database panel title. */
  name: string;
  connected: boolean;
  visit_count?: number | null;
  message?: string | null;
  /** A token is saved server-side; the token itself is never sent back. */
  has_api_key?: boolean;
}

export interface HisConnectionUpdate {
  endpoint: string;
  name: string;
  /** Optional bearer token; omit/blank keeps the saved one. */
  api_key?: string;
}

export interface AdminManagedUser {
  id: string;
  email: string;
  full_name: string | null;
  role: 'super_admin' | 'nurse' | 'viewer';
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
}

export interface AdminUserCreateRequest {
  email: string;
  full_name: string;
  password: string;
}

export interface AdminUserUpdateRequest {
  full_name?: string;
  password?: string;
  is_active?: boolean;
}

export interface LinkVisitResponse {
  linked: boolean;
  visit_id: string;
  patient_name?: string | null;
  age_years?: number | null;
  appointment?: boolean;
  has_his_vitals?: boolean;
  is_first_time?: boolean;
}

/** Lookup an in-progress session already linked to this hospital visit (VN). */
export interface SessionByVisitOut {
  found: boolean;
  visit_id: string;
  session?: SessionOut | null;
  /** 'active' → offer continue/start-over; 'completed' → start-over/reprint. */
  status?: string | null;
  patient_name?: string | null;
  name_confirmed?: boolean;
  needs_history_intake?: boolean;
}

export interface ConfirmVisitNameRequest {
  confirmed?: boolean | null;
  text?: string | null;
}

export interface ConfirmVisitNameResponse {
  decision: 'yes' | 'no' | 'uncertain' | 'other';
  name_confirmed: boolean;
  unlinked: boolean;
  patient_name?: string | null;
}

export interface PatientHistoryIntakeRequest {
  smoking_alcohol?: string | null;
  allergies?: string | null;
  chronic_conditions?: string | null;
  past_surgeries?: string | null;
  family_history?: string | null;
}

export interface PatientHistoryIntakeResponse {
  saved: boolean;
  pushed_to_his: boolean;
  is_first_time: boolean;
  hn?: string | null;
}

// ── Kiosk home / attract-screen stats ─────────────────────────────────────────

export interface KioskStats {
  /** ISO date the counts are for (server local date). */
  date: string;
  /** Hospital visits registered in the HIS today. */
  booth_patients_today: number;
  /** Nurse-approved/corrected assessments today. */
  navigated_today: number;
  /** Triage sessions started at the booth today. */
  sessions_today: number;
}

export interface BpDeviceStatusOut {
  device_name: string;
  device_mac: string | null;
  configured: boolean;
  busy: boolean;
  supported_models: string[];
}

export interface BpScanDeviceOut {
  mac: string;
  name: string | null;
  rssi: number | null;
  is_omron: boolean;
}

export interface BpScanResponse {
  status: 'ok' | 'busy' | 'error';
  devices: BpScanDeviceOut[];
  message: string | null;
}

export interface BpPairRequest {
  mac: string;
  device_name: string;
}

export interface BpPairResponse {
  status:
    | 'ok'
    | 'busy'
    | 'invalid'
    | 'device_not_found'
    | 'pairing_error'
    | 'wrong_device'
    | 'timeout'
    | 'not_configured'
    | 'error';
  device_name: string | null;
  device_mac: string | null;
  message: string | null;
}

// ── Disease Surveillance ──────────────────────────────────────────────────────

export interface SymptomCount {
  keyword: string;
  count: number;
}

export interface AreaSymptomCount {
  area: string;
  keyword: string;
  count: number;
}

export interface DailyCount {
  date: string;
  count: number;
}

export interface SeverityCount {
  severity_level: string | null;
  count: number;
}

export interface OutbreakAlert {
  keyword: string;
  area: string | null;
  recent_count: number;
  previous_count: number;
  increase_pct: number;
}

export interface SurveillanceSummaryOut {
  days: number;
  total_reports: number;
  top_symptoms: SymptomCount[];
  by_area: AreaSymptomCount[];
  daily_trend: DailyCount[];
  severity_distribution: SeverityCount[];
  outbreak_alerts: OutbreakAlert[];
}

// ── Triage manual uploads ─────────────────────────────────────────────────────

export type TriageManualStatus = 'processing' | 'ready' | 'failed';

export interface TriageManualUploadOut {
  id: string;
  original_filename: string;
  file_size_bytes: number | null;
  chunks_count: number | null;
  status: TriageManualStatus;
  error_message: string | null;
  uploaded_by: string | null;
  uploaded_at: string | null;
  completed_at: string | null;
  /** Only present immediately after upload (202 response) */
  message?: string;
}

// ── Screening criteria governance (engine v2) ─────────────────────────────────

export type CriteriaVersionStatus =
  | 'draft'
  | 'pending_review'
  | 'approved'
  | 'active'
  | 'retired';

export interface CriteriaVersionSummary {
  id: string;
  version_no: number;
  status: CriteriaVersionStatus;
  change_summary: string;
  /** true while background rule extraction is still running */
  processing: boolean;
  uploaded_by: string | null;
  reviewed_by: string | null;
  created_at: string | null;
  reviewed_at: string | null;
  activated_at: string | null;
}

export interface CriteriaVersionDetail extends CriteriaVersionSummary {
  criteria: Record<string, unknown>;
  validation_errors: string[];
}

// ── Read-only nurse view of the ACTIVE criteria (GET /admin/criteria/active) ──
// The server renders every condition AST to text, so nothing here is an AST.

export interface CriteriaViewQuestion {
  id: string | null;
  kind: string | null;
  slot: string | null;
  vital: string | null;
  min_age_years: number | null;
  finding_ids: string[];
  text_en: string;
  text_th: string;
  options: Array<{ id: string | null; text_en: string; text_th: string }>;
  citation: string;
  placeholder: boolean;
}

export interface CriteriaViewRule {
  id: string | null;
  group: 'level1' | 'danger_vital' | 'fast_track' | 'department_rule' | 'triage_tuple';
  label_en: string;
  label_th: string;
  condition_en: string;
  condition_th: string;
  level: number | null;
  min_level: number | null;
  department_code: string | null;
  department_name_en: string | null;
  department_name_th: string | null;
  citation: string;
  placeholder: boolean;
}

export interface CriteriaViewFinding {
  id: string;
  label_en: string;
  label_th: string;
  synonyms_en: string[];
  synonyms_th: string[];
  is_risk_factor: boolean;
}

export interface CriteriaViewTemplate {
  category: string;
  label_en: string;
  label_th: string;
  keywords_en: string[];
  keywords_th: string[];
  questions: CriteriaViewQuestion[];
}

export interface CriteriaViewRouting {
  complaint_category: string;
  department_code: string;
  fallback_department_code: string | null;
  department_name_en: string | null;
  department_name_th: string | null;
  condition_en: string;
  condition_th: string;
  citation: string;
  placeholder: boolean;
}

export interface CriteriaActiveView {
  id: string | null;
  version_no: number | null;
  status: CriteriaVersionStatus | 'seed';
  change_summary: string;
  activated_at: string | null;
  source_standards: Array<{ name?: string; edition?: string; url?: string }>;
  complaint_templates: CriteriaViewTemplate[];
  universal_questions: CriteriaViewQuestion[];
  pre_disposition_questions: CriteriaViewQuestion[];
  findings: CriteriaViewFinding[];
  rules: CriteriaViewRule[];
  routing: CriteriaViewRouting[];
}

export interface CriteriaSectionDiff {
  added: string[];
  removed: string[];
  changed: string[];
}

export interface CriteriaDiffOut {
  version_id: string;
  against: string;
  diff: Record<string, CriteriaSectionDiff>;
}

export interface CriteriaEditResponse {
  id: string;
  saved: boolean;
  validation_errors: string[];
}

export interface AiMetricsCallSite {
  call_site: string;
  calls: number;
  ok_calls: number;
  ok_rate: number | null;
  avg_latency_ms: number | null;
}

export interface AiMetricsDisposition {
  level: number | null;
  department_code: string | null;
  count: number;
}

export interface AiMetricsOut {
  from: string | null;
  to: string | null;
  totals: {
    sessions?: number;
    escalations?: number;
    extraction_failures?: number;
    dispositions?: number;
  };
  call_sites: AiMetricsCallSite[];
  dispositions: AiMetricsDisposition[];
  validator_violations: Array<{ violation: string; count: number }>;
}
