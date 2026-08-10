# Hospital HIS Integration — Security Discussion (for the hospital IT team)

Status: **draft for discussion** · Owner: AI-OPD booth team · Last updated: 2026-07-15

This document frames the security conversation for connecting the AI-OPD
pre-screening booth to the hospital's information system (HIS) in production.
It describes what we connect to today (demo), what we propose for production,
what we commit to on our side, and the decisions we need from the hospital.

---

## 1. What the integration is (and is not)

**We never connect to the hospital database.** The booth talks to a small
integration **API** that the hospital exposes and controls. The hospital's DB
stays inside its network; the hospital decides exactly which fields cross the
boundary and can revoke our access at any time without touching the DB.

The booth uses exactly three operations:

| Operation | Direction | Data |
|---|---|---|
| `GET /api/visits/{visit_id}` | read | visit id, patient name, birthdate, appointment flag, any vitals already recorded |
| `POST /api/visits/{id}/prescreen` | write (Stage 1) | booth measurements (BP/pulse/temp/weight/height), booth station id, held triage narrative |
| `POST /api/v1/patient-assignments` | write (Stage 2) | nurse-confirmed destination + SBAR handover — **only after a nurse signs off**; returns the queue number |

Plus one optional write: the patient's own follow-up note
(`PUT /api/visits/{id}/follow-up`).

A visit is only ever looked up when **the patient themselves** enters/scans
their visit ID at the booth — we never enumerate or browse visits from the
patient flow. (The staff-side "Hospital DB" view is a read-only proxy for
authorized admins, and can be disabled in production if the hospital prefers.)

In the demo, the endpoint is a mock service (`hospital-his-mock`) on
localhost over plain HTTP. That is acceptable *only* because it never leaves
the machine. Production requirements are below.

## 2. Proposed production security

### 2.1 Encryption in transit
- **TLS 1.2 minimum, TLS 1.3 preferred**, valid certificates — the endpoint
  must be `https://`. There is no additional payload-level encryption scheme
  to invent; TLS is the standard and sufficient transport protection.
- **Mutual TLS (mTLS) proposed**: both sides present certificates, so the
  hospital's API cryptographically verifies the caller is our booth server —
  not just any client holding a leaked key. Our HTTP client (httpx) supports
  client certificates natively; we can enable this as soon as the hospital
  issues a client cert.

### 2.2 Network placement
Preferred (simplest and strongest): the **booth server lives inside the
hospital LAN** — kiosk hardware is on-premises anyway — so integration
traffic never crosses the internet. Alternatives if hosting off-site:
site-to-site **VPN/IPsec tunnel**, or a private link with **IP allowlisting**
on the hospital side. The integration API should not be reachable from the
public internet in any arrangement.

### 2.3 Authentication & credentials
- Today: a static `X-API-Key` header (fine for the mock; weak alone in
  production — static keys leak, don't expire, don't identify the caller).
- Proposed: **OAuth2 client-credentials** (short-lived tokens from the
  hospital's identity provider) **or mTLS client certificates** — whichever
  the hospital's integration team already operates.
- Regardless of mechanism: per-environment credentials, an agreed **rotation
  schedule**, immediate revocation path, and secrets held in a secrets
  manager on our side (not in config files).

### 2.4 Least privilege & data minimization (PDPA)
Health data is **sensitive personal data under Thailand's PDPA**; the design
principle is to receive and store the minimum needed for triage:
- Service account scoped to the three operations above and to the specific
  fields listed — nothing else readable.
- Lookups happen only for a patient-supplied visit ID; write-backs contain
  only what the patient/nurse produced at the booth.
- Clinical narrative is **never published without human (nurse) sign-off**
  (the two-stage write-back).
- We will align retention with the hospital's policy — see open question 5.

### 2.5 Our side of the fence
- Booth data (Postgres) on an encrypted volume; OS-level hardening on the
  kiosk machine.
- Role-separated staff access (nurse vs super-admin), individual accounts,
  audit trail of every AI decision (`ai_inference_audit`) and every nurse
  action (reviews, reroutes) — reconcilable against the hospital's API logs.
- Only the super-admin can change the HIS connection, from an authenticated
  admin UI; changes are logged and take effect without downtime.
- Patients never see clinical classifications (triage level/color) — only
  the destination department.

### 2.6 Standards
If the HIS (or its gateway) speaks **HL7 FHIR**, we propose using it: our
integration is adapter-based, so a FHIR adapter can replace the custom REST
one without changing the screening engine. FHIR also lets us ride the
hospital's existing authorization infrastructure (e.g. SMART-style scopes).

## 3. Decisions we need from the hospital IT team

| # | Question | Options / notes |
|---|---|---|
| 1 | Where does the booth server live? | On hospital LAN (preferred) · VPN tunnel · IP-allowlisted private link |
| 2 | Transport security level? | HTTPS (server TLS only) · **mTLS** (we support both) |
| 3 | Authentication mechanism? | OAuth2 client-credentials · mTLS certs · (static API key only if paired with network isolation) |
| 4 | Interface contract? | Keep the 3-operation custom REST API · or a FHIR interface (which resources/profiles?) |
| 5 | Data retention on our side? | How long may booth data (name, vitals, complaint, transcript) be kept after the visit closes; deletion/anonymization procedure |
| 6 | Which fields exactly are exposed on visit lookup? | We need: name, birthdate, appointment flag; prior vitals optional |
| 7 | Staff "Hospital DB" read-only view | Keep for hospital staff (behind our admin auth) or disable in production? |
| 8 | Incident contacts + audit reconciliation | Who to notify, log formats, clock sync |
| 9 | Credential lifecycle | Issuer, rotation period, revocation path, test vs prod credentials |

## 4. Hardening work on our side before production

Tracked as the follow-up implementation list (not yet built — demo runs on
the mock):

1. Enforce `https://` endpoints in the admin connection UI outside dev mode.
2. Optional mTLS client-certificate support in `HttpHisAdapter`.
3. Move the API credential out of `.env` into managed secret storage; mask it
   in any UI.
4. Outbound-request audit log (timestamp, operation, visit id hash, result)
   for reconciliation with the hospital's gateway logs.
5. Retention job implementing whatever is agreed in question 5.

## 5. Production runs local inference (decided 2026-08-06)

**The cloud dependency is a demo artifact, not the production design.** In
deployment the booth runs a **local LLM, local STT and local TTS** on
hospital hardware, so patient audio and symptom narratives never leave the
building. This removes what would otherwise be the largest privacy question
in the system — see 5.2.

### 5.0 What we send the model (added 2026-08-10)

`docs/ai-model-io.md` is the generated contract: every prompt, every schema,
every reply, built from the engine's own prompt builders so it cannot drift.
The rule it records is that **no patient identifier reaches the model** — not
the name, HN, VN, slip code, session id or birthdate. Two calls used to send
the name and no longer do; `tests/screening/test_no_pii_in_prompts.py` fails
the build if any of them come back.

What we cannot redact is the patient's own speech: they may say their name
out loud, and no filter catches that reliably in free Thai. **That, not the
redaction, is what local inference buys** — an utterance carrying an
identifier never leaves the hospital, and no third party holds a transcript.
The `AI Model (local inference)` Postman collection runs every call against a
workstation endpoint.

### 5.1 Readiness — one seam exists, one does not

| Component | Today (demo) | Production | Seam status |
|---|---|---|---|
| LLM | Vertex AI Gemini | local (vLLM / Ollama) | ✅ **ready** — `model_adapter.py` selects on `screening_model_provider`; `openai_compatible` already implemented |
| STT | `GoogleSttClient` | local (e.g. Whisper) | ❌ **no seam** — concrete class, constructed directly in `main.py` lifespan, no provider setting |
| TTS | `GoogleTtsClient` | local | ❌ **no seam** — same |

So the speech path needs the same treatment the LLM already has: a protocol
plus a provider setting, so `app.state.stt_client` / `tts_client` can be
swapped by configuration rather than by editing code. **Scope this before
committing to a deployment date** — it is not a config change today.

Two further things that ride on the switch:

- **Triage quality must be re-validated.** A local model is not a drop-in for
  Gemini on extraction quality. Re-run the `evals/` harness against the local
  model and compare before it goes anywhere near patients — the engine's
  determinism protects the *decision*, but extraction feeds it.
- **Model licensing** for whatever local model is chosen (commercial use in a
  clinical setting).

### 5.2 What this does and does not resolve

**Resolved at deployment:** cross-border transfer of sensitive health data.
Health data is sensitive personal data under the PDPA, and sending it to an
overseas cloud is a transfer under Sections 28–29 — with no PDPC adequacy
list published, that route needs contractual safeguards. Running locally
removes the question rather than answering it.

**Still applies during the demo.** If any demo session involves a real
patient, PDPA applies to that session. Demo runs should use synthetic
patients, or carry explicit consent. Note the model currently uses Vertex's
**global** endpoint (chosen for latency/quota), so the processing region is
not pinned — worth stating plainly to the hospital rather than leaving them
to infer that "deployed on-site" means "data stays on-site".

**Unaffected either way** — everything in section 6 below is our own code and
has nothing to do with where the model runs.

## 6. Findings from the 2026-08-06 review (our code, not the integration)

Ordered by severity. None of these are fixed by local inference.

1. **`GET /sessions/by-visit/{visit_id}` is unauthenticated and returns
   `patient_name`.** Unlike our session UUIDs a VN is short and likely
   sequential, so it is enumerable — anyone able to reach the API can harvest
   patient names and session state. Being on the hospital LAN narrows the
   attacker population; it does not fix the hole.
2. **Passwords are unsalted SHA-256** (`hash_password_sha256`) — no salt, no
   work factor, so rainbow-table and GPU-crackable. These accounts guard
   patient records; move to bcrypt or argon2.
3. **No rate limiting anywhere**, so `/admin/login` can be brute-forced —
   which compounds finding 2.
4. `GET /sessions/{id}/messages` returns a full transcript with no auth.
   Much less severe (the UUID is unguessable) but an unguessable URL is
   secrecy, not access control.
5. **No read-access logging.** We audit AI inferences and nurse actions, but
   not who *viewed* which patient's record — commonly required at
   accreditation.
6. **Retention still unspecified** (open question 5, since 2026-07-15) and
   **encryption at rest** on the hospital VM is a deployment-level item.

Confirmed *not* a problem, for the record: we never touch their database;
`ai_inference_audit` stores rules traces and validator results, **not** raw
prompts or responses, so PHI is not duplicated there; the HIS token is never
echoed back to any UI; and voice audio is converted in memory and streamed,
never written to disk.

**Open question for the booth flow:** does the kiosk obtain **explicit
consent** before recording? Sensitive data generally requires it under the
PDPA. Not yet verified.

## 7. Our side of the HIS call — checklist

Everything above is about the boundary itself. This is what **we** are
responsible for on every outbound call to the hospital API. Ordered by how
much it would hurt to get wrong.

### 7.1 Credentials

- The token lives in `.env` in plaintext (hardening item 3 above). It is
  written there by the admin UI via `persist_env_keys`, so it also lands in
  any backup of that file. `.env` is gitignored.
- **We currently send the token twice** — `his_auth_headers()` sets both
  `Authorization: Bearer` *and* `X-API-Key`, so one config works against the
  mock and a real API. Against real iMed that puts the credential in a header
  they never asked for, where it can end up in their logs or a proxy trace.
  **Send Bearer only once we are on the real API.**
- Ask the hospital for a token that is **scoped to the operations we need**
  and **independently revocable**, with **separate credentials for UAT and
  production**. A single general-purpose token turns any leak on our side
  into a much larger incident.
- Changing the token is a live admin action (no downtime), so rotation costs
  nothing operationally — agree a rotation interval with them.

### 7.2 Transport

- `http://` endpoints are still accepted today — see §7.6. Until that is
  fixed, an operator can configure a cleartext endpoint and we will send the
  bearer token in the clear.
- **No CA-bundle or client-certificate setting exists.** `his_*` settings are
  only mode / base_url / api_key / timeout / display_name. Hospital internal
  APIs very often use a private CA; when they do, httpx will reject the
  connection and the tempting "fix" under UAT time pressure is `verify=False`,
  which silently destroys the TLS guarantee. **Add a CA-bundle path setting
  before UAT**; the same shape carries the client cert when they are ready for
  mTLS (§2.1).

### 7.3 Request construction

- `_his_proxy_get(f"/api/visits/{visit_id}")` (`app/routers/deps.py`)
  interpolates an operator-supplied value straight into a URL path with no
  encoding. Low severity, trivially fixed, and exactly what a pentest writes
  up.

### 7.4 What we put on the wire

- **Never** send transcripts, raw audio, or LLM prompts to the HIS — only the
  structured result. Worth stating explicitly because SBAR is free text and
  invites "just include everything".
- SBAR can carry **third-party personal data**: patients describe other people
  ("my mother had a stroke") and that lands in the hospital record. Not
  necessarily wrong clinically, but it should be a deliberate decision.

### 7.5 Logging and audit

- The token never appears in logs today — keep it that way.
- Failure logs embed the request path, which contains `visit_id` and `hn`.
  **Hash identifiers** in the outbound audit log (hardening item 4), which
  should land together with the audit log itself.
- Never log HIS error bodies verbatim; they may contain patient data.

### 7.6 Failure behaviour

- Retries must **never** resend an assignment without the stored `request_id`
  — that is the double-booking path (see `docs/imed-integration-plan.md`).
- Bound retries. A hospital-side outage must not turn our booth into a load
  generator against their API.
- A timeout is **`unknown`, not `failed`** — the queue row may exist.

### 7.7 Treat their responses as untrusted input

- Validate shape and size before persisting.
- Render `message_th` as text in the nurse portal. React escapes by default,
  so this only breaks if someone reaches for `dangerouslySetInnerHTML`.

## 8. Meeting notes

> Fill in during/after the discussion.

- Date / attendees:
- Decisions (by question number):
- Action items (ours):
- Action items (hospital):
