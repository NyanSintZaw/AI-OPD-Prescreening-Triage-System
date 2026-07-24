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
| `PUT /api/visits/{id}/routing` | write (Stage 2) | nurse-confirmed department + narrative — **only after a nurse signs off** |

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

## 5. Meeting notes

> Fill in during/after the discussion.

- Date / attendees:
- Decisions (by question number):
- Action items (ours):
- Action items (hospital):
