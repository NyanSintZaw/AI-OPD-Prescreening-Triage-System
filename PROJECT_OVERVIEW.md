# Project Overview — AI Prescreening Booth

**What this is, in one sentence:** a self-service kiosk at the Mae Fah Luang University (MFU) Medical Center where patients *talk* about their symptoms, and an AI helps figure out how urgent their situation is and which department they should go to — with a nurse always reviewing the result.

This document explains the whole project in plain terms. For developer-focused details, see `CLAUDE.md` and the `docs/` folder.

---

## The problem it solves

When patients arrive at the outpatient department (OPD), someone has to ask them what's wrong, judge how urgent it is, and send them to the right clinic. That takes staff time, and queues build up. This project puts a **voice-based booth** at the entrance: the patient has a short spoken conversation (in Thai or English), and the system produces a triage result and a department recommendation before they ever reach a human. Nurses then review every result in an admin portal, so the AI never has the final word.

## What a patient experiences

1. They walk up to the kiosk and start a session — no login, no typing.
2. They **speak** their symptoms. The system listens, asks follow-up questions out loud, and can take real measurements from connected devices (a blood-pressure cuff and a thermometer).
3. When it has enough information, it tells them **which department to visit** and shows a map of how to get there.
4. If something sounds dangerous (severe chest pain, very high blood pressure, etc.), the system flags it as an emergency immediately — even on the very first answer.

Importantly, the patient is **never shown a severity score or anything that sounds like a diagnosis**. They just get a friendly, plain-language recommendation. The medical details are reserved for staff.

## What the staff experience

- **Nurse review portal** — every kiosk session lands here as a pending review. Nurses see the full picture: the conversation, the severity level the system assigned, the reasoning behind it (with citations to the hospital's own triage manual), any vital signs measured, and the recommended department. They confirm or correct it.
- **Admin portal** — for administrators: session traces (exactly what the AI saw and decided at each step), quality metrics, criteria management, and a disease-surveillance dashboard that tracks symptom trends.
- **Desktop widget** — a small always-on-top pill on a staff PC showing how many reviews are waiting; clicking it opens the portal.

## How the AI works — and why it's designed this way

The core design rule is a **separation of powers**:

- The **language model** (the "AI" part) only does language work: it turns what the patient said into structured facts ("chest pain, started 2 hours ago, radiating to the arm"), phrases follow-up questions naturally, and writes the friendly explanation at the end.
- The **decision** — how urgent this is (a standard 5-level scale used by Thai hospitals) and which department to route to — is made by **plain, deterministic rules**, hand-encoded from the hospital's official triage manual. Same inputs always give the same answer, and every decision can be traced back to a specific rule.

This means the AI can't "hallucinate" a triage decision. It can only misread what the patient said — and even then, the conversation, the extracted facts, and the rule that fired are all logged for the nurse to check.

A few other safety-minded details:

- **Danger signs come first.** Before any conversation logic runs, each turn is checked against a list of red-flag symptoms and vital-sign limits. Objective data (a real cuff reading, the patient's age from hospital records) is merged in *before* that check, so a dangerous blood-pressure reading ends the interview on turn one.
- **Every reply is screened** before the patient hears it, in both Thai and English, to make sure no severity level, color code, diagnosis, or prescription leaks through.
- **The rules are versioned.** The criteria live in a database with version numbers; each patient session records which version it used, so results are auditable even after the rules are updated.
- **Everything is audited.** Every AI call and every rules decision is written to an audit table that powers the per-session trace view and the quality metrics.
- **Explanations are grounded.** The closing explanation for the patient is backed by passages retrieved from the hospital's own uploaded triage manual, not just the model's general knowledge.

## Connecting to the hospital's systems

The booth doesn't live in a vacuum:

- It can **look up the patient in the hospital information system (HIS)** — for example to get their age and current visit — and **write the triage result back** so it appears in the hospital's own records.
- Since we can't develop against the real hospital system, the repo includes a **mock HIS**: a small stand-in service with fake patient data that behaves like the real one. A switch in configuration chooses mock vs. real.
- **Medical devices** are integrated at the booth: an Omron blood-pressure cuff (via the `omblepy` Bluetooth tool) and a Bluetooth thermometer feed real measurements straight into the session.

## The pieces of the repo

| Folder | What it is |
|---|---|
| `hospital-hotline-assistant-api/` | The backend server (Python/FastAPI). Hosts the AI engine, the voice pipeline, all the APIs, and the database logic. |
| `hospital-hotline-assistant-web/` | The web app (React). Contains both the patient kiosk screens and the nurse/admin portals. Thai by default, English available. |
| `hospital-hotline-assistant-desktop/` | The Windows desktop widget showing the pending-review count. |
| `hospital-his-mock/` | The fake hospital information system used for development and demos. |
| `viewer/` | The interactive wayfinding map shown to patients with their recommendation. |
| `omblepy/` | Tooling for reading the Omron blood-pressure cuff over Bluetooth. |
| `e2e/` | An end-to-end test harness that exercises the real voice flow. |
| `docs/` | Design documents, integration plans, demo runbooks, and API references. |

## How the technology fits together (light version)

- The browser captures microphone audio and streams it to the backend over a live connection; the backend converts speech to text, runs one "turn" of the screening conversation, and streams synthesized speech back. Each turn is saved as it happens.
- The conversation engine is a small, bounded pipeline per turn: *understand what was said → check for danger signs → decide whether enough is known → either ask the next question or deliver the result*. Questions about danger signs use the manual's exact wording, not AI paraphrase.
- Data lives in **PostgreSQL**: sessions, messages, symptoms, severity assessments, department recommendations, nurse reviews, surveillance entries, audit logs, and the searchable triage-manual passages.
- The language model currently used is Google's **Gemini** (via Vertex AI), behind an adapter so it can be swapped for a locally hosted model later. Speech-to-text and text-to-speech are Google Cloud services.

## What it deliberately does *not* do

- It does **not diagnose** or prescribe — it routes and prioritizes.
- It does **not show patients** their triage level; that's for clinical staff.
- It does **not act autonomously** — every session goes to a nurse for review.
- There is **no text-chat option** anymore; the voice kiosk is the only patient-facing flow.

## Running it locally (very short version)

1. `docker compose up -d` — starts the database and the mock hospital system.
2. In `hospital-hotline-assistant-api/`: `uv sync`, then `uv run python scripts/init_db.py` (sets up tables and seeds the triage rules), then `uv run uvicorn app.main:app --reload`.
3. In `hospital-hotline-assistant-web/`: `npm install`, then `npm run dev` and open http://localhost:5173.

Configuration for both comes from `.env` files (copy the provided `.env.example`). Tests: `uv run pytest -m "not integration"` runs the full offline suite — no cloud services or database needed.
