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

## Where the model sits

```
kiosk ──audio──> booth backend ──HTTP──> model server (hospital workstation)
                      │                  OpenAI-compatible /v1/chat/completions
                      │                  vLLM or Ollama, weights on local disk
                      ├── rules engine   ← decides the triage level + department
                      └── Postgres       ← state, audit
```

The model is reached through `model_adapter.py`, which is a config switch,
not a code path: `SCREENING_MODEL_PROVIDER=openai_compatible` plus
`SCREENING_OPENAI_BASE_URL=http://<workstation>:8000/v1`. Nothing in the
engine knows which backend answered.

**Requests carry no session id, no auth identity, and no cookies** — each
call is a standalone completion. The server needs no state between turns and
keeps nothing that could be joined back to a patient.

## What is audited

`ai_inference_audit` records the call site, model name, prompt version,
latency, whether it succeeded, the rules trace and any validator violations.
**It does not store prompts or completions** — so the audit trail can be read
by staff without exposing what a patient said.

## The calls

One turn makes one extraction call, then either a paraphrase or an
explanation. Gates fire only when the deterministic classifier is unsure.
Every call is bounded by `ainvoke_with_timeout`; a timeout falls back to
deterministic behaviour rather than blocking the booth.


### Extraction — read one patient message into findings

**When:** Every turn, first. The only call whose output changes the triage: it reports what the patient said, and the rules engine decides what that means.

**Prompt sent:**

```text
You are a clinical intake scribe for a Thai hospital. Read ONE patient message
(Thai or English) and extract ONLY what the patient actually said into the
structured schema. Never guess, never diagnose, never infer findings that were
not stated. If the message answers the assistant's pending question, record
that answer (as finding updates with state "absent" when the patient denies,
or slot/score updates).

Context:
Chief complaint so far: แน่นหน้าอกมา 2 ชั่วโมง
The assistant just asked: คุณมีอาการเจ็บหน้าอกหรือไม่

Allowed complaint categories (copy ONE id verbatim — never invent or combine ids): generic, chest_pain, dyspnea_cough, abdominal_pain, headache, fever, ear, nose_throat, eye, injury, pregnancy, mental_health, musculoskeletal, urinary
Pick the category from what the patient HAS, never from what they deny: "I have
a fever but no headache" / "มีไข้ แต่ไม่ปวดหัว" is fever, not headache.

Finding catalog (use ONLY these ids):
- abdominal_pain: Abdominal pain / ปวดท้อง (also: stomach ache, belly pain, ปวดท้องน้อย, จุกท้อง)
- abnormal_breath_sounds: Audible abnormal breathing (wheeze/stridor) / เสียงหายใจผิดปกติ (หวีด/ครืดคราด) ได้ยินโดยไม่ใช้เครื่องฟัง (also: wheezing, noisy breathing, หายใจมีเสียงหวีด, หายใจครืดคราด)
- active_bleeding: Heavy bleeding that won't stop / เลือดออกมากไม่หยุด (active bleeding) (also: bleeding a lot, can't stop the bleeding, เลือดไหลไม่หยุด, เลือดออกเยอะมาก)
- agitation_violent: Severe agitation / violent behavior / คลุ้มคลั่ง อาละวาด (also: out of control, คลุ้มคลั่ง)
- airway_obstruction: Airway obstruction / choking / ทางเดินหายใจอุดกั้น สำลักติดคอ (also: choking, something stuck in throat blocking breathing, สำลัก, ติดคอหายใจไม่ได้)
- amniotic_fluid_leak: Water broke / amniotic fluid leaking / น้ำเดิน น้ำคร่ำไหล (also: water broke, น้ำเดิน)
- animal_insect_bite_24h: Animal or insect bite/sting within 24 hours / แมลงสัตว์กัดต่อย ภายใน 24 ชั่วโมง (also: dog bite, snake bite, stung, หมากัด, งูกัด, แมลงต่อย)
- apnea: Stopped breathing (apnea) / หยุดหายใจ (also: stops breathing, หยุดหายใจเป็นพัก)
- assault_24h: Physically assaulted within 24 hours / ถูกทำร้ายร่างกายภายใน 24 ชั่วโมง (also: was attacked, ถูกทำร้าย, โดนซ้อม)
- balance_loss: Sudden loss of balance / severe dizziness with unsteady walking / เสียการทรงตัว เดินเซ เวียนศีรษะรุนแรงฉับพลัน (also: staggering, can't walk straight, เดินเซ, ทรงตัวไม่ได้)
- bloody_stool: Fresh blood in stool (recent) / ถ่ายเป็นเลือดสด (also: blood in stool, อุจจาระมีเลือด)
- blue_lips: Blue lips / cyanosis / ริมฝีปากเขียว ตัวเขียว (also: turning blue, เขียวคล้ำ, ปากเขียว)
- burn_scald_24h: Burn or scald within 24 hours / ไฟไหม้ น้ำร้อนลวก ภายใน 24 ชั่วโมง (also: scalded, น้ำร้อนลวก, ไฟลวก)
- cardiac_arrest: Cardiac arrest / not breathing, no pulse / หัวใจหยุดเต้น ไม่หายใจ ไม่มีชีพจร (also: no pulse, not breathing, collapsed and unresponsive, หัวใจหยุด, ไม่หายใจ, คลำชีพจรไม่ได้)
- chest_pain: Chest pain / tightness / เจ็บแน่นหน้าอก (also: chest tightness, pressure on chest, chest discomfort, แน่นหน้าอก, เจ็บหน้าอก, จุกแน่นใต้ลิ้นปี่)
- chest_pain_radiating: Chest pain radiating to neck, jaw, shoulder, or arm / เจ็บหน้าอกร้าวไปคอ กราม ไหล่ หรือแขน (also: pain spreading to jaw, pain going down the arm, เจ็บร้าวไปกราม, เจ็บร้าวไปไหล่)
- chronic_cough_2w: Cough lasting more than 2 weeks / ไอเรื้อรังมากกว่า 2 สัปดาห์ (also: ไอเรื้อรัง)
- confusion: New confusion / drowsiness / disorientation (within 72 hours) / ซึม สับสน เรียกแล้วตอบช้า ภายใน 72 ชั่วโมง (also: disoriented, not making sense, very drowsy, สับสน, ซึมลง, พูดจาสับสน)
- cough: Cough / ไอ (also: coughing, ไอแห้ง, ไอมีเสมหะ)
- crowning: Baby is coming / part of baby visible / ทารกกำลังคลอด มีส่วนของทารกโผล่ออกมา (also: baby's head is coming out, เด็กกำลังจะคลอด, อยากเบ่ง)
- decreased_fetal_movement: Baby moving less than usual / ลูกดิ้นน้อยลง (also: baby not moving much, ทารกดิ้นน้อยลง)
- diaphoresis: Sweating heavily / cold sweat with symptoms / เหงื่อออกมาก เหงื่อแตก (also: cold sweat, drenched in sweat, เหงื่อแตกท่วมตัว)
- diarrhea: Diarrhea / ถ่ายเหลว ท้องเสีย (also: loose stools, ท้องร่วง)
- dyspnea: Difficulty breathing / shortness of breath / หายใจเหนื่อย หายใจหอบ (also: short of breath, breathless, hard to breathe, เหนื่อยหอบ, หายใจไม่อิ่ม, หายใจลำบาก)
- dysuria: Painful or burning urination / ปัสสาวะแสบขัด (also: burning when peeing, ฉี่แสบ, ปัสสาวะขัด)
- ear_pain: Ear pain / ปวดหู (also: earache, เจ็บหู)
- electric_shock_24h: Electric shock within 24 hours / ไฟดูด ภายใน 24 ชั่วโมง (also: electrocuted, ไฟดูด, ไฟช็อต)
- epistaxis_uncontrolled: Nosebleed that will not stop / เลือดกำเดาไหลไม่หยุด (also: เลือดกำเดาไม่หยุด)
- evening_fever: Low-grade fever in the evenings / มีไข้ตอนเย็น ไข้ต่ำ ๆ ช่วงเย็น (also: ไข้ตอนเย็น)
- eye_active_bleeding: Eye bleeding that won't stop / เลือดออกที่ตาไม่หยุด (also: เลือดออกในตา)
- eye_chemical_exposure: Chemical or animal venom splashed into eye / สารเคมีหรือพิษสัตว์กระเด็นเข้าตา (also: chemical in eye, สารเคมีเข้าตา)
- eye_trauma: Eye injury / accident involving the eye / อุบัติเหตุทางตา (also: hit in the eye, ตาโดนกระแทก)
- facial_droop: Facial droop / crooked mouth (sudden) / ปากเบี้ยว หน้าเบี้ยวฉับพลัน (also: face drooping on one side, หน้าเบี้ยว, มุมปากตก)
- fatigue_weight_loss: Fatigue with unexplained weight loss / อ่อนเพลีย น้ำหนักลด (also: losing weight, น้ำหนักลด, เพลีย)
- fever: Fever / มีไข้ (also: feverish, high temperature, ตัวร้อน, ไข้ขึ้น)
- floppy_infant: Child limp / floppy / not responding / เด็กตัวอ่อนปวกเปียก ไม่ตอบสนอง (also: limp child, ตัวอ่อน, ไม่ตอบสนอง)
- foreign_body_ent_24h: Foreign object stuck in ear, nose, or throat (within 24 hours) / สิ่งแปลกปลอมติดในหู จมูก หรือคอ ภายใน 24 ชั่วโมง (also: something stuck in my ear, ของติดในหู, ก้างติดคอ)
- fracture_suspected: Suspected broken bone or dislocated joint / สงสัยกระดูกหักหรือข้อหลุด (also: bone might be broken, joint popped out, กระดูกหัก, ข้อเคลื่อน, ข้อหลุด)
- ga_24w_or_more: Pregnancy at 24 weeks or more / อายุครรภ์ 24 สัปดาห์ขึ้นไป (also: 6 months pregnant or more, ครรภ์ 6 เดือนขึ้นไป)
- gasping: Gasping breaths / หายใจเฮือก (also: หายใจเฮือก ๆ)
- headache: Headache / ปวดศีรษะ (also: head hurts, ปวดหัว)
- headache_sudden_severe: Sudden very severe headache (worst ever) / ปวดศีรษะรุนแรงฉับพลัน (ปวดที่สุดในชีวิต) (also: thunderclap headache, ปวดหัวรุนแรงที่สุด)
- heavy_vaginal_bleeding: Heavy vaginal bleeding (soaking a pad every hour) / เลือดออกมากทางช่องคลอด (เปียกชุ่มผ้าอนามัยทุก 1 ชั่วโมง) (also: soaking pads, เลือดชุ่มผ้าอนามัย)
- hematemesis: Vomiting blood (recent) / อาเจียนเป็นเลือด (also: threw up blood, อ้วกเป็นเลือด)
- hemoptysis: Coughing up blood / blood-streaked sputum / ไอเป็นเลือด เสมหะปนเลือด (also: blood in sputum, ไอมีเลือดปน)
- hypertension_history: History of high blood pressure / มีโรคความดันโลหิตสูง (also: hypertension, ความดันสูง)
- injury_within_24h: Injury happened within the last 24 hours / บาดเจ็บภายใน 24 ชั่วโมงที่ผ่านมา
- limb_weakness: Sudden weakness or numbness of arm/leg (one side) / แขนขาอ่อนแรงหรือชาครึ่งซีกฉับพลัน (also: one side weak, arm won't lift, อ่อนแรงครึ่งซีก, ยกแขนไม่ขึ้น, ชาครึ่งซีก)
- lip_swelling: Swelling of lips, mouth, or face / ปากบวม หน้าบวม (also: swollen lips, face swelling up, ริมฝีปากบวม, หน้าบวม)
- major_trauma_mechanism: Car/motorcycle accident, fall from over 5 metres, or pedestrian hit by vehicle / อุบัติเหตุรถยนต์/จักรยานยนต์ ตกจากที่สูงเกิน 5 เมตร หรือคนเดินถนนถูกรถชน (also: motorbike crash, hit by a car, รถชน, รถล้ม, ตกจากที่สูง)
- melena: Black tarry stool (recent) / ถ่ายดำ (also: black stools, อุจจาระสีดำ)
- missed_period: Missed period / ประจำเดือนขาด (also: late period, เมนส์ไม่มา, ประจำเดือนไม่มา)
- nasal_flaring: Nostrils flaring when breathing (child) / หายใจปีกจมูกบาน (also: ปีกจมูกบาน)
- overdose_or_poison: Drug overdose or exposure to poison/chemicals / ได้รับยาเกินขนาด หรือสัมผัสสารพิษ/สารเคมี (also: took too many pills, swallowed chemicals, กินยาเกินขนาด, โดนสารพิษ)
- pale_cold_sweaty: Pale AND cold AND clammy skin together (shock signs) / ผิวหนังซีดและตัวเย็นชื้นพร้อมกัน (สัญญาณช็อก) (also: cold and clammy, pale and cold to the touch, ตัวเย็นหน้าซีด, หน้าซีดตัวเย็น)
- palm_sole_rash: Red rash on palms, soles, or around the mouth / ผื่นแดงตามฝ่ามือ ฝ่าเท้า รอบปาก (also: ผื่นฝ่ามือฝ่าเท้า)
- penetrating_injury_torso: Stab or penetrating wound to neck, chest, or abdomen / ถูกแทงที่คอ หน้าอก หรือช่องท้อง (also: stabbed, ถูกแทง, ถูกยิง)
- pregnancy: Currently pregnant / กำลังตั้งครรภ์ (also: expecting, ท้อง, มีครรภ์)
- rash_itching: Itchy rash / hives / ผื่นคัน ลมพิษ (also: hives, ผื่นลมพิษ, ผื่นคันทั้งตัว)
- recent_chemotherapy: Currently receiving chemotherapy / ได้รับยาเคมีบำบัดอยู่ (also: on chemo, ให้คีโม, รับยาเคมี)
- retraction: Chest retractions when breathing / หายใจมีอกบุ๋ม (retraction) (also: ribs pulling in when breathing, อกบุ๋ม, ซี่โครงบุ๋ม)
- runny_nose: Runny nose / น้ำมูกไหล (also: มีน้ำมูก)
- seizure_now: Seizure now / convulsing and unresponsive / กำลังชักเกร็ง เรียกไม่รู้สึกตัว (also: convulsions, fitting, ชัก, ชักเกร็ง)
- self_harm_risk: Risk of harming self or others / recent self-harm / เสี่ยงทำร้ายตนเองหรือผู้อื่น หรือเพิ่งทำร้ายตนเอง (also: hurt myself, ทำร้ายตัวเอง)
- severe_morning_sickness: Severe pregnancy vomiting, cannot eat or drink / แพ้ท้องรุนแรงจนกินไม่ได้ (also: แพ้ท้องหนัก)
- severe_respiratory_distress: Severe breathing difficulty (cannot speak full sentences / must sit up to breathe) / หายใจลำบากรุนแรง พูดเป็นประโยคไม่ได้ ต้องลุกนั่งหายใจ (also: can't speak full sentences, gasping for air, struggling to breathe, หายใจไม่ทัน, พูดไม่เป็นประโยค, หอบมาก)
- sexual_assault_72h: Sexual assault within 72 hours / ถูกกระทำชำเราภายใน 72 ชั่วโมง (also: ถูกล่วงละเมิดทางเพศ)
- slurred_speech: Slurred or garbled speech (sudden) / พูดไม่ชัด ลิ้นแข็ง พูดไม่ออกทันที (also: can't get words out, speech suddenly unclear, พูดอ้อแอ้, พูดไม่รู้เรื่องฉับพลัน)
- sore_throat: Sore throat / เจ็บคอ (also: เจ็บคอ)
- stiff_neck: Stiff neck with fever / คอแข็ง ก้มคอไม่ได้ ร่วมกับไข้ (also: คอแข็ง)
- sudden_vision_loss: Sudden loss of vision / double vision / ตามองไม่เห็นเฉียบพลัน เห็นภาพซ้อน (also: suddenly can't see, double vision, ตามืดฉับพลัน, เห็นภาพซ้อน)
- suicidal_ideation: Thoughts of suicide or wanting to die / มีความคิดอยากตาย อยากฆ่าตัวตาย (also: want to end my life, อยากตาย, คิดสั้น)
- syncope_24h: Fainting / near-fainting within 24 hours / วูบ หน้ามืด เป็นลม ภายใน 24 ชั่วโมง (also: blacked out, passed out today, เป็นลม, วูบหมดสติ)
- unresponsive: Unresponsive / cannot be woken / ซึมลงปลุกไม่ตื่น ไม่รู้สึกตัว (also: unconscious, won't wake up, passed out and not waking, หมดสติ, ปลุกไม่ตื่น, ไม่ตอบสนอง)
- uterine_contractions_frequent: Frequent strong contractions (about every 2 minutes) / ท้องแข็ง เจ็บครรภ์ถี่ (ทุก ๆ 2 นาที) (also: contractions every few minutes, เจ็บท้องคลอดถี่, ท้องแข็งถี่)
- vaginal_bleeding: Vaginal bleeding (abnormal) / เลือดออกทางช่องคลอดผิดปกติ (also: bleeding down there, เลือดออกช่องคลอด)
- vomiting: Vomiting / อาเจียน คลื่นไส้ (also: throwing up, nausea, คลื่นไส้, อ้วก)

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

Patient message:
เจ็บแน่นหน้าอกมาสองชั่วโมง ร้าวไปแขนซ้าย ไม่มีไข้
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

### Paraphrase — reword one approved question

**When:** When the rules engine has picked the next question and it is safe to reword. Red-flag and measurement questions are asked verbatim from the criteria and never go near the model.

**Prompt sent:**

```text
คุณเป็นผู้ช่วยคัดกรองของโรงพยาบาลที่พูดจาอบอุ่นและใจเย็น พูดภาษาไทยเท่านั้น ช่วยเรียบเรียงคำถามคัดกรองต่อไปนี้ให้เป็นธรรมชาติ โดยคงความหมายทางคลินิกเดิมทุกประการ ถามเพียงหนึ่งคำถาม ความยาวหนึ่งถึงสองประโยคสั้น ๆ ห้ามใช้ศัพท์แพทย์ และห้ามพูดถึงระดับการคัดกรองหรือการวินิจฉัย
ห้ามถามซ้ำสิ่งที่ผู้ป่วยตอบไปแล้ว
พร้อมกันนี้ให้เสนอตัวเลือกคำตอบสั้น ๆ 3 หรือ 4 ตัวเลือก (ไม่เกิน 30 ตัวอักษรต่อตัวเลือก) เป็นภาษาไทย แตกต่างกันชัดเจน ครอบคลุมคำตอบที่เป็นไปได้ ห้ามมีการวินิจฉัย ระดับการคัดกรอง หรือชื่อยา
บริบทผู้ป่วย: แน่นหน้าอกมา 2 ชั่วโมง
ข้อมูลที่ผู้ป่วยตอบแล้ว ห้ามถามซ้ำ: อายุ 58 ปี | ความดัน 158/94
คำถามที่ต้องเรียบเรียง: อาการเจ็บหน้าอกร้าวไปที่แขน คอ หรือกรามหรือไม่
```

**Reply is schema-constrained** — the server is given this JSON Schema, so a local model cannot answer with prose:

```json
{
  "description": "Structured paraphrase: the reworded question + tappable answers.",
  "properties": {
    "question": {
      "description": "The rephrased screening question",
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

**Prompt sent:**

```text
คุณเป็นผู้ช่วยคัดกรองของโรงพยาบาล พูดภาษาไทยอย่างอบอุ่นและใจเย็น ระบบเกณฑ์ทางคลินิกได้ตัดสินใจแล้วว่าผู้ป่วยควรไปที่แผนกใด หน้าที่ของคุณคืออธิบายอย่างสุภาพใน 2-4 ประโยคสั้น ๆ เท่านั้น
ข้อห้ามเด็ดขาด: ห้ามพูดถึงระดับการคัดกรอง สี คะแนน หรือการจัดประเภท ห้ามวินิจฉัยหรือระบุชื่อโรคที่สงสัย ห้ามแนะนำยา และห้ามพูดถึงแผนกอื่น
อาการที่ผู้ป่วยเล่า: แน่นหน้าอกมา 2 ชั่วโมง ร้าวไปแขนซ้าย
ให้ผู้ป่วยไปที่: แผนก OPD MED (อายุรกรรม)
เรียกผู้ป่วยหนึ่งครั้งอย่างเป็นธรรมชาติ โดยเขียนโทเคน [NAME] ตรงตำแหน่งที่ควรเป็นชื่อ (ห้ามแต่งชื่อขึ้นเอง และห้ามแปลโทเคนนี้)

```

**Reply we act on:**

```text
[NAME] คะ จากอาการที่เล่ามา ทางเราขอให้ไปที่แผนก OPD MED (อายุรกรรม) เพื่อให้แพทย์ตรวจดูอย่างละเอียดนะคะ เดี๋ยวเจ้าหน้าที่จะช่วยแนะนำทางให้ค่ะ
```

`[NAME]` is replaced with the patient's name **after** the reply comes back, so the greeting reads naturally without the name ever being sent. The reply is then checked by `validator.py` for triage-level, colour, diagnosis and medication leaks, in Thai and English, before the patient hears it.


### Gate (followup_decline) — classify one yes/no-ish reply

**When:** Only when the deterministic regex classifier is unsure. The model returns one enum value and never generates anything the patient hears.

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

## Running it against a workstation

The `AI Model (local inference)` Postman collection carries every call above as a real `POST /v1/chat/completions`. Point `aiModelBaseUrl` at the workstation and they run as-is — the same bytes the booth sends.
