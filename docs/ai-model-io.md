# What we send to the AI model, and what comes back

**Generated — do not edit by hand.** Every prompt below is built by the same
functions the engine runs (`scripts/api_docs/model_io.py`), so this file
cannot drift from what actually goes on the wire.

## The rule

The model reads what the patient said and phrases what the rules decided.
**It is never given anything that identifies the patient.** The session
holds all of this and sends none of it:

| Held in the session | Sent to the model |
|---|---|
| `patient_name` = `สมชาย ใจดี` | never |
| `hn` = `09900001` | never |
| `visit_id` = `990000000000000001` | never |
| `slip_code` = `MCH-A1B2-C3D4` | never |
| `session_id` = `1f0b8c2e-4a77-4d1e-9d3a-2b6e5c7f81aa` | never |
| `birthdate` = `1968-03-14` | never |

This is enforced by `tests/screening/test_no_pii_in_prompts.py`, which
rebuilds every prompt with a state full of identifiers and fails if one
appears. Two used to: the explanation prompt carried the patient's name so
the reply could greet them, and the identity gate asked *"You are <name>, is
that correct?"*. The greeting now uses a `[NAME]` placeholder substituted
after the reply comes back; the gate never needed the name at all.

### The one thing we cannot filter

The patient's own words are sent verbatim — they have to be, it is what the
extraction reads. A patient may say their own name, their HN, or anything
else out loud, and no filter catches that reliably in free Thai speech.

**That is the reason the model is hosted in the hospital.** With inference on
a workstation on the ward network, an utterance that happens to contain an
identifier never leaves the building, and there is no third party holding a
transcript. Redacting what we control is worth doing; it is not what makes
this safe.

## Where the AI side sits

```
kiosk ──audio──> booth backend ──HTTP──> AI workstation (hospital LAN)
                      │                  /v1/chat/completions   LLM (vLLM / Ollama)
                      │                  /v1/audio/transcriptions  STT (Whisper)
                      │                  /v1/audio/speech          TTS
                      ├── rules engine   ← decides the triage level + department
                      ├── pgvector       ← RAG embeddings, computed locally (no network)
                      └── Postgres       ← state, audit
```

Today the stack runs on Google (Gemini via Vertex, Cloud STT/TTS). The
deployment target is the workstation above, and it is reached through
config only — no code path changes:

### The endpoint contract (`.env`)

| Setting | Value on the workstation | Notes |
|---|---|---|
| `SCREENING_MODEL_PROVIDER` | `openai_compatible` | `vertexai` = Gemini (current) |
| `SCREENING_OPENAI_BASE_URL` | `http://<workstation>:8000/v1` | **required** for this provider — startup fails rather than falling back to api.openai.com |
| `SCREENING_OPENAI_API_KEY` | optional | sent as `Authorization: Bearer` if set |
| `SCREENING_MODEL_NAME` | the served model id (e.g. `Qwen2.5-7B-Instruct`, `typhoon2-8b`) | default is a Gemini id — must be overridden |
| `SCREENING_MODEL_TIMEOUT_S` | `30` | per call; every call is also wrapped in `ainvoke_with_timeout` |
| `STT_PROVIDER` / `STT_BASE_URL` / `STT_MODEL` | `openai_compatible` / `http://<workstation>:8000/v1` / `whisper-large-v3` | `POST /audio/transcriptions`, multipart |
| `TTS_PROVIDER` / `TTS_BASE_URL` / `TTS_MODEL` | `openai_compatible` / `http://<workstation>:8000/v1` / server's TTS model | `POST /audio/speech`, wants `wav` at 24 kHz |
| `TTS_LOCAL_VOICE_TH` / `TTS_LOCAL_VOICE_EN` | voice ids the TTS server exposes | |
| `SPEECH_HTTP_TIMEOUT_S` | `30` | |

**What the LLM server must support:** the four chat calls are structured
(`with_structured_output`), which on an OpenAI-compatible server means
`response_format: {type: json_schema}` or tool calling. vLLM supports both;
a bare Ollama `/v1` is less reliable — run the `AI Model (local inference)`
Postman collection against the server before go-live; it sends the exact
bodies below.

**Requests carry no session id, no auth identity, and no cookies** — each
call is a standalone completion. The server needs no state between turns and
keeps nothing that could be joined back to a patient.

## What leaves the backend, per call

| Call | What is sent | Identity class | Proven by |
|---|---|---|---|
| extraction | criteria catalog, pending question, chief complaint, **the utterance verbatim** | patient free text | `test_no_pii_in_prompts` |
| question | persona, last 2 exchanges (our lines with the name masked to `[NAME]`), chief complaint, known answers, the approved question | patient free text | `test_no_pii_in_prompts::test_recent_turns_mask…` |
| explain | persona, symptom summary, department, urgency, manual passages (RAG), `[NAME]` placeholder | patient free text | `test_no_pii_in_prompts` |
| gate:* | one short utterance + session language | patient free text | `test_no_pii_in_prompts` |
| surveillance | complaint category, present findings + values, slot answers — **not the transcript** | clinical findings only | `test_surveillance_extractor`, `test_no_pii_in_prompts` |
| STT | the turn's audio | **raw voice** | — (inherent) |
| TTS | the reply text, greeting includes the given name | **name** | — (inherent) |
| RAG embeddings | symptom summary → local HuggingFace model | never leaves the process | `rag_query.py` |

"Patient free text" means: whatever the patient chose to say. A name spoken
aloud goes through. That is the residual that only local hosting removes.

## What is stored

`ai_inference_audit` records the call site, model name, prompt version,
latency, whether it succeeded, the rules trace (finding ids, slot answers,
rule ids, RAG page hits) and any validator violations. **It does not store
prompts or completions.** The session state (`screening_sessions`) keeps the
findings with their evidence quotes and the symptom summary — at rest in the
hospital's own Postgres, shown to the nurse, never sent anywhere.

## The calls

One turn makes one extraction call, then either a question render or an
explanation. Gates fire only when the deterministic classifier is unsure;
surveillance runs once per completed session.
Every call is bounded by `ainvoke_with_timeout`; a timeout falls back to
deterministic behaviour rather than blocking the booth.


### Extraction — read one patient message into findings

**When:** Every turn, first. The only call whose output changes the triage: it reports what the patient said, and the rules engine decides what that means.

**Prompt language: bilingual.** The booth sends the Thai prompt to a Thai session and the English one to an English session — the model is instructed in the language it must reply in, because this reply reaches the patient.

**Prompt sent (Thai session):**

```text
You are a clinical intake scribe for a Thai hospital. Read ONE patient message
(Thai or English) and extract ONLY what the patient actually said into the
structured schema. Never guess, never diagnose, never infer findings that were
not stated. If the message answers the assistant's pending question, record
that answer (as finding updates with state "absent" when the patient denies,
or slot/score updates).

Allowed complaint categories (copy ONE id verbatim — never invent or combine ids): generic, chest_pain, dyspnea_cough, abdominal_pain, headache, fever, ear, nose_throat, eye, injury, pregnancy, mental_health, musculoskeletal, urinary, wound_skin, gynecology, breast, palpitations, limb_vascular, forensic, gi, skin_rash, chronic_followup, administrative
Pick the category from what the patient HAS, never from what they deny: "I have
a fever but no headache" / "มีไข้ แต่ไม่ปวดหัว" is fever, not headache.

Finding catalog (use ONLY these ids):
- abdominal_mass: คลำก้อนได้ที่ท้อง (also: ก้อนที่ท้อง)
- abdominal_pain: ปวดท้อง (also: ปวดท้องน้อย, จุกท้อง)
- abnormal_breath_sounds: เสียงหายใจผิดปกติ (หวีด/ครืดคราด) ได้ยินโดยไม่ใช้เครื่องฟัง (also: หายใจมีเสียงหวีด, หายใจครืดคราด)
- active_bleeding: เลือดออกมากไม่หยุด (active bleeding) (also: เลือดไหลไม่หยุด, เลือดออกเยอะมาก, ห้ามเลือดไม่อยู่, เลือดไหลออกมาก)
- agitation_violent: คลุ้มคลั่ง อาละวาด (also: คลุ้มคลั่ง)
- airway_obstruction: ทางเดินหายใจอุดกั้น สำลักติดคอ (also: สำลัก, ติดคอหายใจไม่ได้)
- allergy_history: มีประวัติแพ้ (ยา อาหาร หรืออื่น ๆ) (also: แพ้ยา, แพ้อาหาร, ประวัติแพ้)
- allergy_symptoms: อาการภูมิแพ้ (จามบ่อย คันจมูก น้ำมูกใส) (also: ภูมิแพ้, แพ้อากาศ)
- amniotic_fluid_leak: น้ำเดิน น้ำคร่ำไหล (also: น้ำเดิน, น้ำไหลออกทางช่องคลอด)
- animal_insect_bite_24h: แมลงสัตว์กัดต่อย ภายใน 24 ชั่วโมง (also: หมากัด, งูกัด, แมลงต่อย)
- anosmia: จมูกไม่ได้กลิ่น (also: ไม่ได้กลิ่น)
- apnea: หยุดหายใจ (also: หยุดหายใจเป็นพัก)
- assault_24h: ถูกทำร้ายร่างกายภายใน 24 ชั่วโมง (also: ถูกทำร้าย, โดนซ้อม)
- auditory_hallucinations: หูแว่วเสียงคน จับใจความได้ (also: หูแว่ว, ได้ยินเสียงคนพูด)
- back_pain_radiating_leg: ปวดหลังร้าวลงขา (also: ปวดหลังร้าวลงขา, ปวดหลังร้าวลงไปที่ขา)
- balance_loss: เสียการทรงตัว เดินเซ เวียนศีรษะรุนแรงฉับพลัน (also: เดินเซ, ทรงตัวไม่ได้)
- bloody_stool: ถ่ายเป็นเลือดสด (also: อุจจาระมีเลือด, ถ่ายมีเลือดสด)
- blue_lips: ริมฝีปากเขียว ตัวเขียว (also: เขียวคล้ำ, ปากเขียว)
- blurred_vision_sudden: ตามัว ตาพร่าฉับพลัน (also: ตามัวฉับพลัน)
- breast_discharge: มีสารคัดหลั่งจากหัวนม (also: น้ำไหลจากหัวนม)
- breast_infection_signs: เต้านมแดง ร้อน หรือบวม (อาจติดเชื้อหรือเป็นฝีหนอง) (also: เต้านมอักเสบ, เต้านมบวมแดง)
- breast_lump: คลำก้อนได้ที่เต้านม (also: ก้อนที่เต้านม)
- breast_pain: เจ็บเต้านม (also: ปวดเต้านม)
- burn_scald_24h: ไฟไหม้ น้ำร้อนลวก ภายใน 24 ชั่วโมง (also: น้ำร้อนลวก, ไฟลวก)
- cardiac_arrest: หัวใจหยุดเต้น ไม่หายใจ ไม่มีชีพจร (also: หัวใจหยุด, ไม่หายใจ, คลำชีพจรไม่ได้)
- chest_pain: เจ็บแน่นหน้าอก (also: แน่นหน้าอก, เจ็บหน้าอก, จุกแน่นใต้ลิ้นปี่)
- chest_pain_radiating: เจ็บหน้าอกร้าวไปคอ กราม ไหล่ หรือแขน (also: เจ็บร้าวไปกราม, เจ็บร้าวไปไหล่)
- chronic_cough_2w: ไอเรื้อรังมากกว่า 2 สัปดาห์ (also: ไอเรื้อรัง)
- chronic_wound: แผลเรื้อรัง (แผลเท้าเบาหวาน แผลกดทับ แผลไม่หาย) (also: แผลเบาหวาน, แผลกดทับ, แผลเรื้อรัง)
- confusion: ซึม สับสน เรียกแล้วตอบช้า ภายใน 72 ชั่วโมง (also: สับสน, ซึมลง, พูดจาสับสน)
- copd_history: มีโรคปอดอุดกั้นเรื้อรัง (COPD) (also: ถุงลมโป่งพอง)
- cough: ไอ (also: ไอแห้ง, ไอมีเสมหะ)
- crowning: ทารกกำลังคลอด มีส่วนของทารกโผล่ออกมา (also: เด็กกำลังจะคลอด, อยากเบ่ง)
- decreased_fetal_movement: ลูกดิ้นน้อยลง (also: ทารกดิ้นน้อยลง)
- dehydration_signs: อาการขาดน้ำ (ดื่มน้ำแล้วอาเจียน ปัสสาวะน้อย ลุกแล้วหน้ามืด) (also: ขาดน้ำ, กินน้ำไม่ได้)
- depression_symptoms: ซึมเศร้า เบื่อหน่าย ท้อแท้ (also: เศร้า, หดหู่)
- diabetes_history: มีโรคเบาหวาน (also: เบาหวาน)
- dialysis_access_needed: ทำเส้นฟอกไต เตรียมฟอกไตหน้าท้อง (also: ทำเส้นฟอกไต)
- diaphoresis: เหงื่อออกมาก เหงื่อแตก (also: เหงื่อแตกท่วมตัว)
- diarrhea: ถ่ายเหลว ท้องเสีย (also: ท้องร่วง)
- dyspnea: หายใจเหนื่อย หายใจหอบ (also: เหนื่อยหอบ, หายใจไม่อิ่ม, หายใจลำบาก)
- dysuria: ปัสสาวะแสบขัด (also: ฉี่แสบ, ปัสสาวะขัด)
- ear_discharge: น้ำไหลจากหู (also: หูน้ำหนวก)
- ear_pain: ปวดหู (also: เจ็บหู)
- edema: บวมที่ขาหรือตามตัว (also: ขาบวม, ตัวบวม)
- electric_shock_24h: ไฟดูด ภายใน 24 ชั่วโมง (also: ไฟดูด, ไฟช็อต)
- epistaxis_uncontrolled: เลือดกำเดาไหลไม่หยุด (also: เลือดกำเดาไม่หยุด)
- evening_fever: มีไข้ตอนเย็น ไข้ต่ำ ๆ ช่วงเย็น (also: ไข้ตอนเย็น)
- eye_active_bleeding: เลือดออกที่ตาไม่หยุด (also: เลือดออกในตา)
- eye_chemical_exposure: สารเคมีหรือพิษสัตว์กระเด็นเข้าตา (also: สารเคมีเข้าตา)
- eye_lump_swelling: ก้อนบวมแดงที่ตา (also: ตากุ้งยิง, ก้อนที่เปลือกตา)
- eye_pain_severe: ปวดตามาก (also: ปวดตารุนแรง)
- eye_redness_severe: ตาแดงมาก (also: ตาแดงจัด)
- eye_trauma: อุบัติเหตุทางตา (also: ตาโดนกระแทก)
- facial_droop: ปากเบี้ยว หน้าเบี้ยวฉับพลัน (also: หน้าเบี้ยว, มุมปากตก)
- fatigue_weight_loss: อ่อนเพลีย น้ำหนักลด (also: น้ำหนักลด, เพลีย)
- fever: มีไข้ (also: ตัวร้อน, ไข้ขึ้น)
- floppy_infant: เด็กตัวอ่อนปวกเปียก ไม่ตอบสนอง (also: ตัวอ่อน, ไม่ตอบสนอง)
- foreign_body_ent_24h: สิ่งแปลกปลอมติดในหู จมูก หรือคอ ภายใน 24 ชั่วโมง (also: ของติดในหู, ก้างติดคอ, มีของติดในหู, แมลงเข้าหู)
- fracture_suspected: สงสัยกระดูกหักหรือข้อหลุด (also: กระดูกหัก, ข้อเคลื่อน, ข้อหลุด)
- ga_24w_or_more: อายุครรภ์ 24 สัปดาห์ขึ้นไป (also: ครรภ์ 6 เดือนขึ้นไป)
- gasping: หายใจเฮือก (also: หายใจเฮือก ๆ)
- hallucination_paranoia: ภาพหลอน หวาดระแวง (also: เห็นภาพหลอน, ระแวง)
- head_injury: ศีรษะกระแทก บาดเจ็บที่ศีรษะ (also: หัวกระแทก, หัวฟาดพื้น)
- headache: ปวดศีรษะ (also: ปวดหัว)
- headache_sudden_severe: ปวดศีรษะรุนแรงฉับพลัน (ปวดที่สุดในชีวิต) (also: ปวดหัวรุนแรงที่สุด)
- hearing_loss: การได้ยินลดลง หูอื้อ (also: หูอื้อ, หูตึง, ได้ยินไม่ชัด)
- heart_disease_history: มีประวัติโรคหัวใจ เส้นเลือดหัวใจตีบ (also: โรคหัวใจ, เส้นเลือดหัวใจตีบ)
- heavy_vaginal_bleeding: เลือดออกมากทางช่องคลอด (เปียกชุ่มผ้าอนามัยทุก 1 ชั่วโมง) (also: เลือดชุ่มผ้าอนามัย)
- hematemesis: อาเจียนเป็นเลือด (also: อ้วกเป็นเลือด)
- hemoptysis: ไอเป็นเลือด เสมหะปนเลือด (also: ไอมีเลือดปน)
- high_fever: ไข้สูง (เกิน 38.5 องศา) (also: ไข้สูงมาก)
- hoarseness_over_2w: เสียงแหบนานเกิน 2 สัปดาห์ (also: เสียงแหบเรื้อรัง)
- home_oxygen: ใช้ออกซิเจนที่บ้าน (also: ให้ออกซิเจนที่บ้าน)
- hypertension_history: มีโรคความดันโลหิตสูง (also: ความดันสูง)
- hypoglycemia_symptoms: อาการน้ำตาลต่ำ (มือสั่น เหงื่อแตก มึนงง หิวมาก) (also: น้ำตาลตก, น้ำตาลต่ำ)
- immediate_danger: ยังอยู่ในอันตราย / ผู้ก่อเหตุอยู่ใกล้ (also: ไม่ปลอดภัย)
- injury_within_24h: บาดเจ็บภายใน 24 ชั่วโมงที่ผ่านมา
- irregular_pulse: หัวใจเต้นผิดจังหวะ ชีพจรไม่สม่ำเสมอ (also: หัวใจเต้นไม่เป็นจังหวะ)
- limb_ischemia: มือเท้าเย็น ปวดเวลาใช้แขนขา แผลเรื้อรัง/ซีดดำ (also: เท้าดำ, แขนขาขาดเลือด)
- limb_weakness: แขนขาอ่อนแรงหรือชาครึ่งซีกฉับพลัน (also: อ่อนแรงครึ่งซีก, ยกแขนไม่ขึ้น, ชาครึ่งซีก)
- lip_swelling: ปากบวม หน้าบวม (also: ริมฝีปากบวม, หน้าบวม)
- loc_transient: หมดสติหรือสลบชั่วครู่หลังศีรษะกระแทก/บาดเจ็บ (เฉพาะเมื่อเกิดจากการบาดเจ็บ) (also: สลบหลังหัวฟาด, หมดสติหลังล้ม, สลบไปหลังกระแทก)
- major_trauma_mechanism: อุบัติเหตุรถยนต์/จักรยานยนต์ ตกจากที่สูงเกิน 5 เมตร หรือคนเดินถนนถูกรถชน (also: รถชน, รถล้ม, ตกจากที่สูง)
- medication_run_out: ยาประจำหมด (also: ยาหมด, มารับยา)
- melena: ถ่ายดำ (also: อุจจาระสีดำ)
- missed_period: ประจำเดือนขาด (also: เมนส์ไม่มา, ประจำเดือนไม่มา)
- nasal_congestion: คัดจมูก (also: จมูกตัน)
- nasal_flaring: หายใจปีกจมูกบาน (also: ปีกจมูกบาน)
- neck_mass: ก้อนที่คอ (also: ก้อนที่ลำคอ)
- neck_swelling_dysphagia: คอบวมโต กลืนลำบาก หายใจลำบาก (also: กลืนลำบาก, คอบวม)
- oral_ulcer_chronic: แผลในช่องปากเรื้อรังไม่หาย (also: แผลในปากไม่หาย)
- orthopnea: นอนราบไม่ได้ ต้องนั่งหายใจ (also: นอนราบแล้วเหนื่อย)
- overdose_or_poison: ได้รับยาเกินขนาด หรือสัมผัสสารพิษ/สารเคมี (also: กินยาเกินขนาด, โดนสารพิษ)
- pale_cold_sweaty: ผิวหนังซีดและตัวเย็นชื้นพร้อมกัน (สัญญาณช็อก) (also: ตัวเย็นหน้าซีด, หน้าซีดตัวเย็น)
- palm_sole_rash: ผื่นแดงตามฝ่ามือ ฝ่าเท้า รอบปาก (also: ผื่นฝ่ามือฝ่าเท้า)
- palpitations: ใจสั่น หัวใจเต้นเร็วผิดปกติ (also: ใจเต้นแรง, ใจสั่นรัว)
- penetrating_injury_torso: ถูกแทงที่คอ หน้าอก หรือช่องท้อง (also: ถูกแทง, ถูกยิง)
- police_case: มีใบรายงานชันสูตรหรือใบนำส่งตรวจจากตำรวจ (also: มีใบนำส่งจากตำรวจ, คดีความ)
- pregnancy: กำลังตั้งครรภ์ (also: ท้อง, มีครรภ์)
- problem_scar: แผลเป็นมีปัญหา (คีลอยด์ แผลเป็นหดรั้ง เจ็บหรือคันเรื้อรัง) (also: คีลอยด์, แผลเป็นนูน)
- rash_itching: ผื่นคัน ลมพิษ (also: ผื่นลมพิษ, ผื่นคันทั้งตัว)
- rash_rapidly_spreading: ผื่นลามเร็วภายในไม่กี่ชั่วโมง (also: ผื่นลามเร็ว, ผื่นขึ้นทั้งตัว)
- rash_vesicles: ผื่นแดงหรือตุ่มน้ำตามร่างกาย (also: ตุ่มน้ำใส, ผื่นขึ้นตามตัว)
- recent_chemotherapy: ได้รับยาเคมีบำบัดอยู่ (also: ให้คีโม, รับยาเคมี)
- retraction: หายใจมีอกบุ๋ม (retraction) (also: อกบุ๋ม, ซี่โครงบุ๋ม)
- runny_nose: น้ำมูกไหล (also: มีน้ำมูก)
- seizure_now: กำลังชักเกร็ง เรียกไม่รู้สึกตัว (also: ชัก, ชักเกร็ง)
- self_harm_risk: เสี่ยงทำร้ายตนเองหรือผู้อื่น หรือเพิ่งทำร้ายตนเอง (also: ทำร้ายตัวเอง)
- severe_morning_sickness: แพ้ท้องรุนแรงจนกินไม่ได้ (also: แพ้ท้องหนัก, แพ้ท้องรุนแรง)
- severe_respiratory_distress: หายใจลำบากรุนแรง พูดเป็นประโยคไม่ได้ ต้องลุกนั่งหายใจ (also: หายใจไม่ทัน, พูดไม่เป็นประโยค, หอบมาก)
- severe_stress: เครียดมาก (also: เครียดหนัก)
- severe_uncontrolled_pain: ปวดรุนแรงมากจนทนไม่ไหว (also: ปวดมากทนไม่ไหว, ปวดที่สุดในชีวิต)
- sexual_assault_72h: ถูกกระทำชำเราภายใน 72 ชั่วโมง (also: ถูกล่วงละเมิดทางเพศ)
- slurred_speech: พูดไม่ชัด ลิ้นแข็ง พูดไม่ออกทันที (also: พูดอ้อแอ้, พูดไม่รู้เรื่องฉับพลัน)
- smoking: สูบบุหรี่ (also: สูบบุหรี่)
- snoring: นอนกรน (also: กรน)
- sore_throat: เจ็บคอ (also: เจ็บคอ)
- stiff_neck: คอแข็ง ก้มคอไม่ได้ ร่วมกับไข้ (also: คอแข็ง)
- sudden_vision_loss: ตามองไม่เห็นเฉียบพลัน เห็นภาพซ้อน (also: ตามืดฉับพลัน, เห็นภาพซ้อน)
- suicidal_ideation: มีความคิดอยากตาย อยากฆ่าตัวตาย (also: อยากตาย, คิดสั้น)
- syncope_24h: วูบ หน้ามืด เป็นลม ภายใน 24 ชั่วโมง (ไม่ได้เกิดจากอุบัติเหตุ) (also: เป็นลม, วูบหมดสติ, วูบ, หน้ามืด, หมดสติไปแป๊บนึง, เป็นลมล้ม)
- tinnitus: เสียงดังในหู (วิ้ง เสียงแมลง) (also: หูมีเสียงวิ้ง, เสียงดังในหู)
- unilateral_leg_swelling: ขาบวมและปวดข้างเดียว (also: ขาบวมข้างเดียว, น่องบวม)
- unresponsive: ซึมลงปลุกไม่ตื่น ไม่รู้สึกตัว (also: หมดสติ, ปลุกไม่ตื่น, ไม่ตอบสนอง)
- uterine_contractions_frequent: ท้องแข็ง เจ็บครรภ์ถี่ (ทุก ๆ 2 นาที) (also: เจ็บท้องคลอดถี่, ท้องแข็งถี่)
- vaginal_bleeding: เลือดออกทางช่องคลอดผิดปกติ (also: เลือดออกช่องคลอด)
- varicose_veins: เส้นเลือดขอด (also: เส้นเลือดขอด)
- vertigo: เวียนศีรษะ บ้านหมุน (also: บ้านหมุน, เวียนหัว)
- vertigo_positional: บ้านหมุนสัมพันธ์กับท่าทาง (also: บ้านหมุนเวลาเปลี่ยนท่า)
- vomiting: อาเจียน คลื่นไส้ (also: คลื่นไส้, อ้วก)
- wound_infection_signs: แผลมีอาการติดเชื้อ (แดงลาม มีหนอง ร้อน) (also: มีหนอง, แผลบวมแดง)

Rules:
- A denial ("no", "ไม่มีค่ะ", "none of these", "ไม่มีอาการเหล่านี้") of the pending
  question -> ALL of that question's finding ids with state "absent". A bare
  denial applies ONLY to the pending question's finding ids — never to other
  findings the question wording mentioned in passing.
- Explicit negations the patient volunteers anywhere in the message ("no fever
  though", "no trouble breathing", "แต่ไม่มีไข้", "หายใจปกติดี") -> those findings
  with state "absent" — including in the very first message. This applies to
  "X but no Y" sentences too: "I've had a fever since yesterday but no cough"
  -> fever "present" AND cough "absent"; "มีไข้ แต่ไม่ไอ ไม่เจ็บคอ" -> fever
  "present", cough "absent", sore_throat "absent". Never drop the negated
  finding just because the sentence also reports a positive one.
- A correction: when the patient says an earlier symptom was a mistake, has gone
  away, or was about someone else ("พูดผิด ไม่ได้ปวดท้อง", "หายแล้ว", "ไม่ได้เป็นแล้ว",
  "that was my mother, not me", "I was wrong about the sweating") -> that finding
  with state "absent", evidence = those words. If they replace their main problem
  ("จริงๆ แล้วมาเรื่องผื่น", "I'm actually here for a sore throat") -> also fill
  chief_complaint with the new problem and complaint_category with its category.
  Do NOT fill chief_complaint when they only add a symptom to the one they have.
- A bare affirmation ("yes", "ใช่", "มี") of a pending question that checks exactly
  ONE finding -> that finding id with state "present".
- A bare affirmation of a pending question that checks SEVERAL findings:
  if they are severity grades of the SAME symptom (e.g. dyspnea vs
  severe_respiratory_distress) -> record only the mildest as "present";
  if they are DISTINCT symptoms (e.g. confusion vs stiff_neck) -> record NO
  finding updates (the assistant will ask which one). When the patient names
  specific symptoms, record exactly those as "present".
- For EVERY finding update, fill evidence with the exact words from the
  patient's message that state it — copied verbatim, never paraphrased or
  translated. If you cannot quote supporting words, do not record the finding.
- Numbers 0-10 answering a pain/breathing question -> pain_score or distress_score.
- A timeframe answering when it started or how long it has lasted (e.g.
  "2-3 days", "since yesterday") -> fill BOTH slot_updates.onset and
  slot_updates.duration when the phrasing covers both, so neither is re-asked.
- Ages like "6 เดือน" -> age_years 0.5.
- complaint_category: whenever the patient states any symptom, pick the SINGLE
  closest category from the allowed list. If more than one could fit (e.g.
  sore throat + cough), pick the one matching the symptom they said first.
  Use null only when no category fits at all (e.g. a greeting or a question).
- wants_human=true only when they explicitly ask for a person/nurse/staff.

Context:
Chief complaint so far: แน่นหน้าอกมา 2 ชั่วโมง
The assistant just asked: คุณมีอาการเจ็บหน้าอกหรือไม่

Patient message:
เจ็บแน่นหน้าอกมาสองชั่วโมง ร้าวไปแขนซ้าย ไม่มีไข้
```

**Prompt sent (English session):**

```text
You are a clinical intake scribe for a Thai hospital. Read ONE patient message
(Thai or English) and extract ONLY what the patient actually said into the
structured schema. Never guess, never diagnose, never infer findings that were
not stated. If the message answers the assistant's pending question, record
that answer (as finding updates with state "absent" when the patient denies,
or slot/score updates).

Allowed complaint categories (copy ONE id verbatim — never invent or combine ids): generic, chest_pain, dyspnea_cough, abdominal_pain, headache, fever, ear, nose_throat, eye, injury, pregnancy, mental_health, musculoskeletal, urinary, wound_skin, gynecology, breast, palpitations, limb_vascular, forensic, gi, skin_rash, chronic_followup, administrative
Pick the category from what the patient HAS, never from what they deny: "I have
a fever but no headache" / "มีไข้ แต่ไม่ปวดหัว" is fever, not headache.

Finding catalog (use ONLY these ids):
- abdominal_mass: Lump felt in the abdomen (also: lump in belly)
- abdominal_pain: Abdominal pain (also: stomach ache, belly pain)
- abnormal_breath_sounds: Audible abnormal breathing (wheeze/stridor) (also: wheezing, noisy breathing)
- active_bleeding: Heavy bleeding that won't stop (also: bleeding a lot, can't stop the bleeding)
- agitation_violent: Severe agitation / violent behavior (also: out of control)
- airway_obstruction: Airway obstruction / choking (also: choking, something stuck in throat blocking breathing)
- allergy_history: Known allergy (medication, food, or other) (also: allergic to, drug allergy, food allergy)
- allergy_symptoms: Allergy symptoms (sneezing, itchy runny nose) (also: hay fever)
- amniotic_fluid_leak: Water broke / amniotic fluid leaking (also: water broke)
- animal_insect_bite_24h: Animal or insect bite/sting within 24 hours (also: dog bite, snake bite, stung)
- anosmia: Loss of smell (also: can't smell)
- apnea: Stopped breathing (apnea) (also: stops breathing)
- assault_24h: Physically assaulted within 24 hours (also: was attacked)
- auditory_hallucinations: Hearing voices (understandable speech) (also: hearing voices)
- back_pain_radiating_leg: Back pain radiating down the leg (also: sciatica-like pain)
- balance_loss: Sudden loss of balance / severe dizziness with unsteady walking (also: staggering, can't walk straight)
- bloody_stool: Fresh blood in stool (recent) (also: blood in stool)
- blue_lips: Blue lips / cyanosis (also: turning blue)
- blurred_vision_sudden: Sudden blurred vision (also: vision suddenly blurry)
- breast_discharge: Discharge from nipple
- breast_infection_signs: Breast redness, warmth, or swelling (possible infection/abscess) (also: breast abscess, mastitis)
- breast_lump: Breast lump (also: lump in breast)
- breast_pain: Breast pain
- burn_scald_24h: Burn or scald within 24 hours (also: scalded)
- cardiac_arrest: Cardiac arrest / not breathing, no pulse (also: no pulse, not breathing, collapsed and unresponsive)
- chest_pain: Chest pain / tightness (also: chest tightness, pressure on chest, chest discomfort)
- chest_pain_radiating: Chest pain radiating to neck, jaw, shoulder, or arm (also: pain spreading to jaw, pain going down the arm)
- chronic_cough_2w: Cough lasting more than 2 weeks
- chronic_wound: Chronic wound (diabetic foot, pressure sore, non-healing ulcer) (also: wound that won't heal)
- confusion: New confusion / drowsiness / disorientation (within 72 hours) (also: disoriented, not making sense, very drowsy)
- copd_history: History of COPD / chronic lung disease (also: emphysema)
- cough: Cough (also: coughing)
- crowning: Baby is coming / part of baby visible (also: baby's head is coming out)
- decreased_fetal_movement: Baby moving less than usual (also: baby not moving much)
- dehydration_signs: Signs of dehydration (cannot keep fluids down, little urine, dizzy on standing) (also: can't keep fluids down, dehydrated)
- depression_symptoms: Depressed mood / loss of interest (also: feeling depressed)
- diabetes_history: History of diabetes (also: diabetic)
- dialysis_access_needed: Needs dialysis access creation (fistula / PD catheter)
- diaphoresis: Sweating heavily / cold sweat with symptoms (also: cold sweat, drenched in sweat)
- diarrhea: Diarrhea (also: loose stools)
- dyspnea: Difficulty breathing / shortness of breath (also: short of breath, breathless, hard to breathe)
- dysuria: Painful or burning urination (also: burning when peeing)
- ear_discharge: Fluid draining from the ear
- ear_pain: Ear pain (also: earache)
- edema: Swelling of legs or body (also: swollen legs, puffy ankles)
- electric_shock_24h: Electric shock within 24 hours (also: electrocuted)
- epistaxis_uncontrolled: Nosebleed that will not stop
- evening_fever: Low-grade fever in the evenings
- eye_active_bleeding: Eye bleeding that won't stop
- eye_chemical_exposure: Chemical or animal venom splashed into eye (also: chemical in eye)
- eye_lump_swelling: Red swollen lump at the eye (also: stye)
- eye_pain_severe: Severe eye pain
- eye_redness_severe: Very red eye
- eye_trauma: Eye injury / accident involving the eye (also: hit in the eye, hurt my eye)
- facial_droop: Facial droop / crooked mouth (sudden) (also: face drooping on one side)
- fatigue_weight_loss: Fatigue with unexplained weight loss (also: losing weight)
- fever: Fever (also: feverish, high temperature)
- floppy_infant: Child limp / floppy / not responding (also: limp child)
- foreign_body_ent_24h: Foreign object stuck in ear, nose, or throat (within 24 hours) (also: something stuck in my ear)
- fracture_suspected: Suspected broken bone or dislocated joint (also: bone might be broken, joint popped out)
- ga_24w_or_more: Pregnancy at 24 weeks or more (also: 6 months pregnant or more)
- gasping: Gasping breaths
- hallucination_paranoia: Hallucinations or paranoia (also: seeing things, paranoid)
- head_injury: Head injury / hit head (also: hit my head)
- headache: Headache (also: head hurts)
- headache_sudden_severe: Sudden very severe headache (worst ever) (also: thunderclap headache)
- hearing_loss: Hearing loss / reduced hearing (also: can't hear well)
- heart_disease_history: History of heart disease / coronary artery disease (also: heart problems before)
- heavy_vaginal_bleeding: Heavy vaginal bleeding (soaking a pad every hour) (also: soaking pads)
- hematemesis: Vomiting blood (recent) (also: threw up blood, throwing up blood)
- hemoptysis: Coughing up blood / blood-streaked sputum (also: blood in sputum)
- high_fever: High fever (over 38.5°C) (also: burning up)
- hoarseness_over_2w: Hoarse voice for more than 2 weeks (also: voice hoarse for weeks)
- home_oxygen: Uses home oxygen
- hypertension_history: History of high blood pressure (also: hypertension)
- hypoglycemia_symptoms: Low blood sugar symptoms (shaky, sweaty, confused, very hungry) (also: hypoglycemia, sugar crash)
- immediate_danger: Still in immediate danger / attacker nearby (also: not safe)
- injury_within_24h: Injury happened within the last 24 hours
- irregular_pulse: Irregular heartbeat / pulse (also: skipping beats)
- limb_ischemia: Cold, painful, or discolored hands/feet; chronic non-healing limb wounds (also: foot turning black)
- limb_weakness: Sudden weakness or numbness of arm/leg (one side) (also: one side weak, arm won't lift)
- lip_swelling: Swelling of lips, mouth, or face (also: swollen lips, face swelling up)
- loc_transient: Brief loss of consciousness after a head injury / blow (only when an injury caused it) (also: knocked out, passed out after hitting my head, blacked out after the fall)
- major_trauma_mechanism: Car/motorcycle accident, fall from over 5 metres, or pedestrian hit by vehicle (also: motorbike crash, hit by a car)
- medication_run_out: Regular medication has run out (also: out of medication, refill)
- melena: Black tarry stool (recent) (also: black stools)
- missed_period: Missed period (also: late period)
- nasal_congestion: Nasal congestion / blocked nose (also: stuffy nose)
- nasal_flaring: Nostrils flaring when breathing (child)
- neck_mass: Lump in the neck (also: neck lump)
- neck_swelling_dysphagia: Neck swelling with trouble swallowing or breathing (also: can't swallow)
- oral_ulcer_chronic: Chronic mouth ulcer that won't heal
- orthopnea: Cannot lie flat to breathe (also: needs to sit up to breathe at night)
- overdose_or_poison: Drug overdose or exposure to poison/chemicals (also: took too many pills, swallowed chemicals)
- pale_cold_sweaty: Pale AND cold AND clammy skin together (shock signs) (also: cold and clammy, pale and cold to the touch)
- palm_sole_rash: Red rash on palms, soles, or around the mouth
- palpitations: Palpitations / racing heart (also: heart racing, heart pounding)
- penetrating_injury_torso: Stab or penetrating wound to neck, chest, or abdomen (also: stabbed)
- police_case: Has police report / forensic referral document (also: police sent me for examination)
- pregnancy: Currently pregnant (also: expecting)
- problem_scar: Problem scar (keloid, contracture, chronic painful/itchy scar) (also: keloid)
- rash_itching: Itchy rash / hives (also: hives)
- rash_rapidly_spreading: Rash spreading rapidly (within hours) (also: spreading rash)
- rash_vesicles: Red rash or fluid-filled blisters on the body (also: blisters)
- recent_chemotherapy: Currently receiving chemotherapy (also: on chemo)
- retraction: Chest retractions when breathing (also: ribs pulling in when breathing)
- runny_nose: Runny nose
- seizure_now: Seizure now / convulsing and unresponsive (also: convulsions, fitting)
- self_harm_risk: Risk of harming self or others / recent self-harm (also: hurt myself)
- severe_morning_sickness: Severe pregnancy vomiting, cannot eat or drink
- severe_respiratory_distress: Severe breathing difficulty (cannot speak full sentences / must sit up to breathe) (also: can't speak full sentences, gasping for air, struggling to breathe)
- severe_stress: Severe stress / overwhelming distress (also: extremely stressed)
- severe_uncontrolled_pain: Very severe pain that cannot be controlled (also: worst pain, unbearable pain)
- sexual_assault_72h: Sexual assault within 72 hours
- slurred_speech: Slurred or garbled speech (sudden) (also: can't get words out, speech suddenly unclear)
- smoking: Smoker
- snoring: Snoring / suspected sleep apnea
- sore_throat: Sore throat
- stiff_neck: Stiff neck with fever
- sudden_vision_loss: Sudden loss of vision / double vision (also: suddenly can't see, double vision)
- suicidal_ideation: Thoughts of suicide or wanting to die (also: want to end my life)
- syncope_24h: Fainting / near-fainting within 24 hours (no injury as the cause) (also: blacked out, passed out today, fainted, nearly fainted, collapsed, lost consciousness for a moment)
- tinnitus: Ringing or buzzing in the ear (also: ringing in ears)
- unilateral_leg_swelling: One leg swollen and painful (also: swollen calf)
- unresponsive: Unresponsive / cannot be woken (also: unconscious, won't wake up, passed out and not waking)
- uterine_contractions_frequent: Frequent strong contractions (about every 2 minutes) (also: contractions every few minutes)
- vaginal_bleeding: Vaginal bleeding (abnormal) (also: bleeding down there)
- varicose_veins: Varicose veins
- vertigo: Dizziness / spinning sensation (also: room spinning)
- vertigo_positional: Spinning dizziness related to head position (also: dizzy when turning head)
- vomiting: Vomiting (also: throwing up, nausea)
- wound_infection_signs: Wound infection signs (spreading redness, pus, warmth) (also: pus, infected wound)

Rules:
- A denial ("no", "ไม่มีค่ะ", "none of these", "ไม่มีอาการเหล่านี้") of the pending
  question -> ALL of that question's finding ids with state "absent". A bare
  denial applies ONLY to the pending question's finding ids — never to other
  findings the question wording mentioned in passing.
- Explicit negations the patient volunteers anywhere in the message ("no fever
  though", "no trouble breathing", "แต่ไม่มีไข้", "หายใจปกติดี") -> those findings
  with state "absent" — including in the very first message. This applies to
  "X but no Y" sentences too: "I've had a fever since yesterday but no cough"
  -> fever "present" AND cough "absent"; "มีไข้ แต่ไม่ไอ ไม่เจ็บคอ" -> fever
  "present", cough "absent", sore_throat "absent". Never drop the negated
  finding just because the sentence also reports a positive one.
- A correction: when the patient says an earlier symptom was a mistake, has gone
  away, or was about someone else ("พูดผิด ไม่ได้ปวดท้อง", "หายแล้ว", "ไม่ได้เป็นแล้ว",
  "that was my mother, not me", "I was wrong about the sweating") -> that finding
  with state "absent", evidence = those words. If they replace their main problem
  ("จริงๆ แล้วมาเรื่องผื่น", "I'm actually here for a sore throat") -> also fill
  chief_complaint with the new problem and complaint_category with its category.
  Do NOT fill chief_complaint when they only add a symptom to the one they have.
- A bare affirmation ("yes", "ใช่", "มี") of a pending question that checks exactly
  ONE finding -> that finding id with state "present".
- A bare affirmation of a pending question that checks SEVERAL findings:
  if they are severity grades of the SAME symptom (e.g. dyspnea vs
  severe_respiratory_distress) -> record only the mildest as "present";
  if they are DISTINCT symptoms (e.g. confusion vs stiff_neck) -> record NO
  finding updates (the assistant will ask which one). When the patient names
  specific symptoms, record exactly those as "present".
- For EVERY finding update, fill evidence with the exact words from the
  patient's message that state it — copied verbatim, never paraphrased or
  translated. If you cannot quote supporting words, do not record the finding.
- Numbers 0-10 answering a pain/breathing question -> pain_score or distress_score.
- A timeframe answering when it started or how long it has lasted (e.g.
  "2-3 days", "since yesterday") -> fill BOTH slot_updates.onset and
  slot_updates.duration when the phrasing covers both, so neither is re-asked.
- Ages like "6 เดือน" -> age_years 0.5.
- complaint_category: whenever the patient states any symptom, pick the SINGLE
  closest category from the allowed list. If more than one could fit (e.g.
  sore throat + cough), pick the one matching the symptom they said first.
  Use null only when no category fits at all (e.g. a greeting or a question).
- wants_human=true only when they explicitly ask for a person/nurse/staff.

Context:
Chief complaint so far: chest tightness for 2 hours
The assistant just asked: Do you have chest pain?

Patient message:
My chest has been tight for two hours, it goes into my left arm, no fever
```

**Reply is schema-constrained** — the server is given this JSON Schema, so a local model cannot answer with prose:

```json
{
  "$defs": {
    "FindingUpdate": {
      "description": "One finding the patient's message resolves.",
      "properties": {
        "id": {
          "description": "Canonical finding id from the provided catalog",
          "title": "Id",
          "type": "string"
        },
        "state": {
          "description": "present if the patient confirms it, absent if they deny it",
          "enum": [
            "present",
            "absent"
          ],
          "title": "State",
          "type": "string"
        },
        "value": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "Optional detail, e.g. '3 days' or 'left side'",
          "title": "Value"
        },
        "evidence": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "The exact words from the patient's message that state this finding, copied verbatim (same language, no paraphrase)",
          "title": "Evidence"
        }
      },
      "required": [
        "id",
        "state"
      ],
      "title": "FindingUpdate",
      "type": "object"
    }
  },
  "description": "Structured reading of a single patient message.",
  "properties": {
    "chief_complaint": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Patient's main problem in their own words, only when newly stated",
      "title": "Chief Complaint"
    },
    "complaint_category": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Best matching complaint category from the provided list, or null",
      "title": "Complaint Category"
    },
    "finding_updates": {
      "items": {
        "$ref": "#/$defs/FindingUpdate"
      },
      "title": "Finding Updates",
      "type": "array"
    },
    "slot_updates": {
      "additionalProperties": {
        "type": "string"
      },
      "description": "OLDCARTS slots this message answers (onset, location, duration, character, aggravating, relieving, timing, severity) mapped to the answer text",
      "title": "Slot Updates",
      "type": "object"
    },
    "age_years": {
      "anyOf": [
        {
          "type": "number"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Patient age in years when stated (0.5 = 6 months)",
      "title": "Age Years"
    },
    "gender": {
      "anyOf": [
        {
          "enum": [
            "male",
            "female"
          ],
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "The patient's sex ONLY when they explicitly state it (e.g. 'male', 'female', 'ชาย', 'หญิง', typically answering the gender question). Never guess it from the name, symptoms, or wording; null when unstated or declined",
      "title": "Gender"
    },
    "pain_score": {
      "anyOf": [
        {
          "maximum": 10,
          "minimum": 0,
          "type": "integer"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "0-10 pain score when stated",
      "title": "Pain Score"
    },
    "distress_score": {
      "anyOf": [
        {
          "maximum": 10,
          "minimum": 0,
          "type": "integer"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "0-10 breathing difficulty score when stated",
      "title": "Distress Score"
    },
    "temperature_c": {
      "anyOf": [
        {
          "type": "number"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Body temperature in Celsius when stated",
      "title": "Temperature C"
    },
    "spo2_percent": {
      "anyOf": [
        {
          "type": "number"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Blood oxygen saturation percentage when the patient states a reading they measured themselves (e.g. a home pulse oximeter)",
      "title": "Spo2 Percent"
    },
    "is_question_to_assistant": {
      "default": false,
      "description": "True when the message is a question to the assistant rather than an answer about symptoms",
      "title": "Is Question To Assistant",
      "type": "boolean"
    },
    "wants_human": {
      "default": false,
      "description": "True when the patient asks for a human/nurse",
      "title": "Wants Human",
      "type": "boolean"
    }
  },
  "title": "ExtractionResult",
  "type": "object"
}
```

**Reply we act on:**

```json
{
  "chief_complaint": "แน่นหน้าอกมา 2 ชั่วโมง ร้าวไปแขนซ้าย",
  "complaint_category": "chest_pain",
  "finding_updates": [
    {
      "id": "chest_pain_radiating",
      "state": "present",
      "evidence": "ร้าวไปแขนซ้าย"
    },
    {
      "id": "fever",
      "state": "absent",
      "evidence": "ไม่มีไข้"
    }
  ],
  "slot_updates": {
    "onset": "2 ชั่วโมง",
    "location": "หน้าอก"
  },
  "age_years": null,
  "pain_score": null,
  "distress_score": null
}
```

### Question — acknowledge, then ask the approved question

**When:** Every interview turn, once the rules engine has picked the next question. The model returns a short acknowledgement and (only for history/associated-symptom questions) a rewording. Red-flag, scale, measurement and confirm questions are sent with a 'return it unchanged' instruction and the engine uses the criteria text regardless of what comes back.

**Prompt language: bilingual.** The booth sends the Thai prompt to a Thai session and the English one to an English session — the model is instructed in the language it must reply in, because this reply reaches the patient.

**Prompt sent (Thai session):**

```text
คุณเป็นผู้ช่วยคัดกรองของโรงพยาบาล พูดภาษาไทยอย่างอบอุ่นและใจเย็น พูดภาษาไทยเท่านั้น พูดง่าย ๆ เหมือนพยาบาลใจดีหน้าเคาน์เตอร์ ห้ามใช้ศัพท์แพทย์ ครั้งละหนึ่งถึงสองประโยคสั้น ๆ ห้ามเป็นรายการ รับรู้สิ่งที่ผู้ป่วยเพิ่งบอกสั้น ๆ ก่อนถามต่อ โดยไม่ทวนซ้ำยาวเกินไป ข้อห้ามเด็ดขาด: ห้ามพูดถึงระดับการคัดกรอง สี คะแนน หรือการจัดประเภท ห้ามวินิจฉัยหรือระบุชื่อโรคที่สงสัย ห้ามแนะนำยา
คุณกำลังอยู่ระหว่างการสนทนาคัดกรอง บทสนทนาล่าสุด:
user: เจ็บแน่นหน้าอกมาสองชั่วโมง ร้าวไปแขนซ้าย
คุณ: [NAME] คะ เข้าใจค่ะ ตอนนี้เหนื่อยหรือหายใจลำบากไหมคะ
บริบทผู้ป่วย: แน่นหน้าอกมา 2 ชั่วโมง
ข้อมูลที่ผู้ป่วยตอบแล้ว ห้ามถามซ้ำ: อายุ 58 ปี | ความดัน 158/94
ขั้นแรก เขียน `ack`: วลีสั้น ๆ หนึ่งวลี (ไม่เกิน 15 คำ) ที่รับรู้สิ่งที่ผู้ป่วยเพิ่งบอกอย่างอบอุ่น โดยไม่ทวนซ้ำยาว ห้ามมีคำถาม คำแนะนำ หรือคำปลอบใจเรื่องผลลัพธ์ เปลี่ยนถ้อยคำทุกครั้ง ห้ามใช้คำเดิมกับประโยคก่อนหน้าของคุณ บ่อยครั้งคำเดียว (เช่น ค่ะ เข้าใจค่ะ) หรือไม่ต้องมีเลยจะดีที่สุด เว้นว่างไว้หากไม่มีอะไรต้องรับรู้
จากนั้นเขียน `question`: เรียบเรียงคำถามด้านล่างให้เป็นธรรมชาติ โดยคงความหมายทางคลินิกเดิมทุกประการ ถามเพียงหนึ่งคำถาม ความยาวหนึ่งถึงสองประโยคสั้น ๆ ห้ามใช้ศัพท์แพทย์ ห้ามถามซ้ำสิ่งที่ตอบแล้ว
พร้อมกันนี้ให้เสนอตัวเลือกคำตอบสั้น ๆ 3 หรือ 4 ตัวเลือก (ไม่เกิน 30 ตัวอักษรต่อตัวเลือก) เป็นภาษาไทย แตกต่างกันชัดเจน ครอบคลุมคำตอบที่เป็นไปได้ ห้ามมีการวินิจฉัย ระดับการคัดกรอง หรือชื่อยา
คำถาม: อาการเจ็บหน้าอกร้าวไปที่แขน คอ หรือกรามหรือไม่
```

**Prompt sent (English session):**

```text
You are a warm, calm hospital screening assistant speaking English. Speak plainly, like a kind nurse at a front desk — no medical jargon. One or two short sentences at a time; never lists. Acknowledge what the patient just said before moving on, briefly and without repeating it back at length. STRICT RULES: never mention triage levels, colors, scores, or classifications; never diagnose or name a suspected disease; never recommend medication.
You are in the middle of a screening conversation. Recent exchange:
user: My chest has been tight for two hours, it goes into my left arm
You: [NAME], I understand. Are you short of breath right now?
Patient context: chest tightness for 2 hours
Already answered — do not re-ask: อายุ 58 ปี | ความดัน 158/94
First, write `ack`: one short clause (under 12 words) that acknowledges what the patient just said, warmly and without repeating it back at length. It must not contain a question, advice, or reassurance about the outcome. Vary it — never reuse the wording of your previous line; a single word or nothing at all is often best. Leave it empty if there is nothing to acknowledge.
Then write `question`: rephrase the question below conversationally, preserving its exact clinical meaning. Exactly ONE question, one or two short sentences, no lists, no medical jargon. Do NOT re-ask anything already answered.
Also provide 3 or 4 short answer choices (max 30 characters each) the patient could tap to answer, in English, mutually distinct, covering the most likely answers; never include diagnoses, levels, or medication.
Question: อาการเจ็บหน้าอกร้าวไปที่แขน คอ หรือกรามหรือไม่
```

**Reply is schema-constrained** — the server is given this JSON Schema, so a local model cannot answer with prose:

```json
{
  "description": "Structured render: acknowledgement + question + tappable answers.",
  "properties": {
    "ack": {
      "default": "",
      "description": "One short clause acknowledging what the patient just said, with no question in it; empty when there is nothing to acknowledge",
      "title": "Ack",
      "type": "string"
    },
    "question": {
      "description": "The screening question to ask next",
      "title": "Question",
      "type": "string"
    },
    "options": {
      "description": "3 or 4 short, mutually distinct answer choices the patient could tap, in the same language as the question",
      "items": {
        "type": "string"
      },
      "title": "Options",
      "type": "array"
    }
  },
  "required": [
    "question"
  ],
  "title": "PhrasedQuestion",
  "type": "object"
}
```

**Reply we act on:**

```json
{
  "ack": "เข้าใจค่ะ",
  "question": "อาการเจ็บที่หน้าอก มีร้าวไปที่แขน คอ หรือกรามด้วยไหมคะ",
  "options": [
    "ร้าวไปแขน",
    "ร้าวไปคอหรือกราม",
    "ไม่ร้าวไปไหน",
    "ไม่แน่ใจ"
  ]
}
```

### Explain — phrase the decision the rules already made

**When:** Once, at disposition. The department and urgency are inputs, not something the model chooses.

**Prompt language: bilingual.** The booth sends the Thai prompt to a Thai session and the English one to an English session — the model is instructed in the language it must reply in, because this reply reaches the patient.

**Prompt sent (Thai session):**

```text
คุณเป็นผู้ช่วยคัดกรองของโรงพยาบาล พูดภาษาไทยอย่างอบอุ่นและใจเย็น พูดภาษาไทยเท่านั้น พูดง่าย ๆ เหมือนพยาบาลใจดีหน้าเคาน์เตอร์ ห้ามใช้ศัพท์แพทย์ ครั้งละหนึ่งถึงสองประโยคสั้น ๆ ห้ามเป็นรายการ รับรู้สิ่งที่ผู้ป่วยเพิ่งบอกสั้น ๆ ก่อนถามต่อ โดยไม่ทวนซ้ำยาวเกินไป ข้อห้ามเด็ดขาด: ห้ามพูดถึงระดับการคัดกรอง สี คะแนน หรือการจัดประเภท ห้ามวินิจฉัยหรือระบุชื่อโรคที่สงสัย ห้ามแนะนำยา
ระบบเกณฑ์ทางคลินิกได้ตัดสินใจแล้วว่าผู้ป่วยควรไปที่แผนกใด หน้าที่ของคุณคืออธิบายอย่างสุภาพใน 2-4 ประโยคสั้น ๆ เท่านั้น ห้ามพูดถึงแผนกอื่น
อาการที่ผู้ป่วยเล่า: แน่นหน้าอกมา 2 ชั่วโมง ร้าวไปแขนซ้าย
ให้ผู้ป่วยไปที่: แผนก OPD MED (อายุรกรรม)
เรียกผู้ป่วยหนึ่งครั้งอย่างเป็นธรรมชาติ โดยเขียนโทเคน [NAME] ตรงตำแหน่งที่ควรเป็นชื่อ (โทเคนนี้มีคำว่า 'คุณ' อยู่แล้ว อย่าเขียน 'คุณ' นำหน้าซ้ำ ห้ามแต่งชื่อขึ้นเอง และห้ามแปลโทเคนนี้)

```

**Prompt sent (English session):**

```text
You are a warm, calm hospital screening assistant speaking English. Speak plainly, like a kind nurse at a front desk — no medical jargon. One or two short sentences at a time; never lists. Acknowledge what the patient just said before moving on, briefly and without repeating it back at length. STRICT RULES: never mention triage levels, colors, scores, or classifications; never diagnose or name a suspected disease; never recommend medication.
The clinical rules engine has decided where this patient should go — your ONLY job is to explain it kindly in 2–4 short sentences. Do not name any other department.
Patient's reported symptoms: แน่นหน้าอกมา 2 ชั่วโมง ร้าวไปแขนซ้าย
Send the patient to: แผนก OPD MED (อายุรกรรม)
Address the patient once, naturally, writing the literal token [NAME] exactly where their name belongs (do not invent a name, do not translate the token).

```

**Reply we act on:**

```text
[NAME] คะ จากอาการที่เล่ามา ทางเราขอให้ไปที่แผนก OPD MED (อายุรกรรม) เพื่อให้แพทย์ตรวจดูอย่างละเอียดนะคะ เดี๋ยวเจ้าหน้าที่จะช่วยแนะนำทางให้ค่ะ
```

`[NAME]` is replaced with the patient's name **after** the reply comes back, so the greeting reads naturally without the name ever being sent. The reply is then checked by `validator.py` for triage-level, colour, diagnosis and medication leaks, in Thai and English, before the patient hears it.


### Gate (followup_decline) — classify one yes/no-ish reply

**When:** Only when the deterministic regex classifier is unsure. The model returns one enum value and never generates anything the patient hears.

**Prompt language: English**, whatever the patient speaks — this call produces structured data, not patient-facing text, so the instructions do not need translating. The patient's own words pass through verbatim in whatever language they spoke, and the finding catalog carries both languages.

**Prompt sent:**

```text
A hospital kiosk assistant just asked the patient (in Thai or English): 'Is there anything else you would like to ask, or anything to note for the doctor?'
Classify the patient's reply below. Answer with exactly one verdict:
- decline: the reply only declines or politely closes the conversation (e.g. 'No, nothing else', 'I'm done, thanks', 'no worries, I'm all set', 'ไม่มีแล้วค่ะ ขอบคุณค่ะ')
- content: the reply contains an actual question, symptom, or note the doctor should see
- unclear: cannot tell
Session language: th. Context: -
Patient reply: 'ไม่มีแล้วค่ะ ขอบคุณค่ะ'
```

**Reply is schema-constrained** — the server is given this JSON Schema, so a local model cannot answer with prose:

```json
{
  "properties": {
    "verdict": {
      "enum": [
        "decline",
        "content",
        "unclear"
      ],
      "title": "Verdict",
      "type": "string"
    }
  },
  "required": [
    "verdict"
  ],
  "title": "_FollowupVerdict",
  "type": "object"
}
```

**Reply we act on:**

```json
{
  "verdict": "decline"
}
```

### Gate (identity_yesno) — classify one yes/no-ish reply

**When:** Only when the deterministic regex classifier is unsure. The model returns one enum value and never generates anything the patient hears.

**Prompt language: English**, whatever the patient speaks — this call produces structured data, not patient-facing text, so the instructions do not need translating. The patient's own words pass through verbatim in whatever language they spoke, and the finding catalog carries both languages.

**Prompt sent:**

```text
A hospital kiosk showed the patient the name on their record and asked 'is this you?'
Classify the patient's reply below (Thai or English). Answer with exactly one verdict:
- yes: the reply confirms it is them
- no: the reply says it is not them / wrong name / wrong person
- unclear: cannot tell (off-topic, ambiguous)
Session language: th.
Patient reply: 'ไม่มีแล้วค่ะ ขอบคุณค่ะ'
```

**Reply is schema-constrained** — the server is given this JSON Schema, so a local model cannot answer with prose:

```json
{
  "properties": {
    "verdict": {
      "enum": [
        "yes",
        "no",
        "unclear"
      ],
      "title": "Verdict",
      "type": "string"
    }
  },
  "required": [
    "verdict"
  ],
  "title": "_IdentityVerdict",
  "type": "object"
}
```

**Reply we act on:**

```json
{
  "verdict": "yes"
}
```

### Gate (resume_choice) — classify one yes/no-ish reply

**When:** Only when the deterministic regex classifier is unsure. The model returns one enum value and never generates anything the patient hears.

**Prompt language: English**, whatever the patient speaks — this call produces structured data, not patient-facing text, so the instructions do not need translating. The patient's own words pass through verbatim in whatever language they spoke, and the finding catalog carries both languages.

**Prompt sent:**

```text
A hospital kiosk found the patient's earlier assessment (status: in_progress) and asked whether they want to CONTINUE it or START OVER with a new one.
Classify the patient's reply below (Thai or English). Answer with exactly one verdict:
- continue: they want to pick up the earlier assessment
- start_over: they want a fresh assessment from the beginning
- unclear: cannot tell
Session language: th.
Patient reply: 'ไม่มีแล้วค่ะ ขอบคุณค่ะ'
```

**Reply is schema-constrained** — the server is given this JSON Schema, so a local model cannot answer with prose:

```json
{
  "properties": {
    "verdict": {
      "enum": [
        "continue",
        "start_over",
        "unclear"
      ],
      "title": "Verdict",
      "type": "string"
    }
  },
  "required": [
    "verdict"
  ],
  "title": "_ResumeVerdict",
  "type": "object"
}
```

**Reply we act on:**

```json
{
  "verdict": "continue"
}
```

### Surveillance — disease keywords for the outbreak dashboard

**When:** Once, when the session is marked completed, in the background. Input is the engine's own screening state (complaint, present findings, slot answers) — never the transcript, never the identity. Output feeds disease_surveillance only; nothing the patient hears.

**Prompt language: English**, whatever the patient speaks — this call produces structured data, not patient-facing text, so the instructions do not need translating. The patient's own words pass through verbatim in whatever language they spoke, and the finding catalog carries both languages.

**Prompt sent:**

```text
You are a medical keyword extractor for a hospital triage system.

Given the structured summary of a screening conversation below, extract a
concise list of disease names, symptoms, and body-part complaints that the
patient reported.

Rules:
- Return short keyword strings (1–3 words each).
- Use lowercase English.
- Include diseases (e.g. "covid", "dengue", "influenza"), symptoms
  (e.g. "fever", "sore throat", "muscle pain"), and body parts with problems
  (e.g. "ear pain", "chest pain").
- Do NOT include greetings, question phrases, or doctor/schedule queries.
- If no health keywords are found, return an empty list.

Screening summary:
- complaint category: chest_pain
- chief complaint: แน่นหน้าอกมา 2 ชั่วโมง
- chest_pain_radiating: ร้าวไปแขนซ้าย
- onset: 2 ชั่วโมง
- location: หน้าอก

```

**Reply is schema-constrained** — the server is given this JSON Schema, so a local model cannot answer with prose:

```json
{
  "properties": {
    "keywords": {
      "items": {
        "type": "string"
      },
      "title": "Keywords",
      "type": "array"
    }
  },
  "title": "SurveillanceKeywords",
  "type": "object"
}
```

**Reply we act on:**

```json
{
  "keywords": [
    "chest pain",
    "arm pain"
  ]
}
```

## The speech calls

### STT — POST {LLM_BASE_URL}/audio/transcriptions

**When:** Every patient turn: the 16 kHz PCM of that turn, multipart.  
**Carries:** raw patient audio (whatever they say, including a name)

```json
{
  "multipart": {
    "model": "{STT_MODEL}",
    "language": "th",
    "response_format": "json",
    "file": "<turn audio, audio/wav>"
  }
}
```

**Reply:**

```json
{
  "text": "เจ็บแน่นหน้าอกมาสองชั่วโมง"
}
```

### TTS — POST {LLM_BASE_URL}/audio/speech

**When:** Every assistant line the patient hears.  
**Carries:** the finished reply text — the greeting includes the patient's given name

```json
{
  "json": {
    "model": "{TTS_MODEL}",
    "input": "สวัสดีค่ะ คุณสมชาย วันนี้มีอาการอะไรให้ช่วยคะ",
    "voice": "{TTS_LOCAL_VOICE_TH}",
    "response_format": "wav",
    "sample_rate": 24000
  }
}
```

**Reply:**

```text
<audio/wav, LINEAR16 24 kHz>
```

## Running it against a workstation

The `AI Model (local inference)` Postman collection carries every call above as real requests. Set `LLM_BASE_URL` in the environment to the workstation and they run as-is — the same bytes the booth sends.
