# Software Requirements Specification (SRS)

## AI Voice-Based Hospital Hotline Assistant (Web-Based MVP)

---

## 1. Introduction

### 1.1 Project Title

AI Voice-Based Hospital Hotline Assistant

### 1.2 Purpose

The purpose of this system is to provide a web-based AI hospital hotline assistant that communicates with patients using voice and text in real time. The system helps patients describe symptoms, determines urgency levels, and recommends the appropriate hospital department before human staff interaction.

The system is designed to:

- Reduce frontline workload
- Improve patient guidance
- Support multilingual communication
- Provide preliminary emergency instructions when necessary

This MVP focuses on demonstration and pilot evaluation for hospital usage.

### 1.3 Scope

The first version of the system will:

- Operate as a web application
- Support Thai and English
- Allow voice and text communication
- Classify symptom urgency
- Recommend hospital departments
- Provide preliminary emergency guidance
- Log conversations for evaluation purposes

The system will **NOT**:

- Diagnose diseases
- Prescribe medication
- Replace medical professionals
- Provide final medical decisions

### 1.4 Target Users

- General patients
- Elderly users
- Non-technical users
- Hospital visitors
- Hospital administrative staff

---

## 2. Overall Description

### 2.1 Product Perspective

The system acts as an AI-powered hospital hotline assistant accessible through a web browser. Patients interact with the system using voice or text. The AI processes patient input and provides guidance based on predefined symptom-routing logic and AI classification.

### 2.2 Product Objectives

The system aims to:

- Improve hospital navigation
- Reduce patient confusion
- Assist emergency recognition
- Reduce unnecessary waiting
- Improve accessibility through voice interaction

### 2.3 Assumptions and Dependencies

- Users have internet access
- Users have microphone permission enabled
- Hospital routing information is predefined
- AI services for speech recognition and text-to-speech are available

---

## 3. Functional Requirements

### 3.1 User Access Module

#### FR-1: Access Web Hotline

The system shall allow users to access the hotline assistant through a web browser without account registration.

| | |
|---|---|
| **Inputs** | User opens website URL |
| **Outputs** | Homepage and assistant interface displayed |

---

### 3.2 Voice Communication Module

#### FR-2: Speech-to-Text Input

The system shall allow users to speak through a microphone and convert speech into text in real time.

| | |
|---|---|
| **Inputs** | User voice input |
| **Outputs** | Transcribed text displayed on screen |

#### FR-3: Text-to-Speech Response

The system shall convert AI responses into spoken audio.

| | |
|---|---|
| **Inputs** | AI-generated response text |
| **Outputs** | Audio playback to user |

#### FR-4: Multilingual Voice Support

The system shall support voice interaction in Thai and English.

| | |
|---|---|
| **Inputs** | User selected language |
| **Outputs** | Responses generated in selected language |

---

### 3.3 Patient Symptom Collection Module

#### FR-5: Symptom Description Input

The system shall allow users to describe symptoms using voice, text, or both.

| | |
|---|---|
| **Inputs** | User symptom descriptions |
| **Outputs** | Stored symptom text |

#### FR-6: Follow-Up Question Generation

The system shall generate follow-up questions when symptom information is incomplete.

**Example:**
> User: "I have pain."
> System: "Where is the pain located?"

---

### 3.4 Severity Assessment Module

#### FR-7: Preliminary Severity Classification

The system shall classify patient urgency into one of three levels:

| Level | Description |
|---|---|
| **Emergency** | Immediate life-threatening situation |
| **Urgent** | Requires prompt attention |
| **General** | Non-urgent care needed |

| | |
|---|---|
| **Inputs** | Patient symptoms |
| **Outputs** | Severity category |

#### FR-8: Emergency Escalation Detection

The system shall detect predefined emergency symptom combinations.

**Example Triggers:**
- Chest pain + breathing difficulty
- Loss of consciousness
- Severe bleeding

| | |
|---|---|
| **Outputs** | Emergency alert message + recommendation to seek immediate medical care |

---

### 3.5 Department Recommendation Module

#### FR-9: Department Recommendation

The system shall recommend the most appropriate hospital department based on symptoms.

**Example Outputs:**
- Emergency Department
- Pediatrics
- Cardiology
- Orthopedics
- ENT

#### FR-10: Department Explanation

The system shall explain why a department is recommended.

**Example:**
> "Based on your breathing symptoms, the Emergency Department is recommended."

---

### 3.6 Conversation Management Module

#### FR-11: Real-Time AI Conversation

The system shall maintain continuous conversational interaction with users, including:

- Multiple exchanges
- Contextual understanding
- Real-time response generation

#### FR-12: Conversation Reset

The system shall allow users to restart the conversation.

---

### 3.7 Data Logging Module

#### FR-13: Conversation Logging

The system shall store:

- User symptoms
- AI responses
- Timestamps
- Severity classifications
- Department recommendations

**Purpose:** Evaluation, testing, and system improvement.

#### FR-14: Session ID Generation

The system shall generate unique session IDs for each interaction.

---

### 3.8 Administrative Module

#### FR-15: View Interaction Records

The system shall allow authorized administrators to view conversation logs.

#### FR-16: Manage Department Routing Rules

The system shall allow administrators to:

- Edit symptom-routing mappings
- Update department rules
- Configure emergency triggers

---

## 4. Non-Functional Requirements

### 4.1 Performance Requirements

#### NFR-1: Response Time

| Response Type | Target |
|---|---|
| Text responses | ≤ 3 seconds |
| Voice responses | ≤ 5 seconds |

### 4.2 Reliability Requirements

#### NFR-2: System Availability

The system should maintain at least **95% uptime** during testing.

### 4.3 Security Requirements

#### NFR-3: Data Protection

The system shall encrypt all communication using **HTTPS**.

#### NFR-4: Limited Personal Data Collection

The system shall avoid collecting unnecessary personal information.

### 4.4 Usability Requirements

#### NFR-5: Simple User Interface

The interface shall:

- Support elderly users
- Use large buttons
- Provide clear voice interaction controls

### 4.5 Scalability Requirements

#### NFR-6: Future Language Expansion

The system architecture should support future multilingual expansion.

---

## 5. System Architecture (High-Level)

### Frontend

- Web application
- Voice interaction UI
- Real-time chat interface

**Suggested:** React.js / Next.js

### Backend

- API server
- AI orchestration
- Session management

**Suggested:** FastAPI / Node.js

### AI Services

- Speech-to-Text
- Text-to-Speech
- Symptom classification
- Severity assessment

### Database

Stores conversation logs, routing rules, and emergency rules.

**Suggested:** PostgreSQL / Firebase

---

## 6. Constraints

- The system is **not** a licensed medical diagnostic tool
- Recommendations are **preliminary only**
- Minority language datasets may be limited
- AI outputs may require hospital validation

---

## 7. Future Enhancements

- Mobile application version
- Avatar-based interaction
- Additional language support
- Hospital appointment integration
- Queue management integration
- Emergency hotline integration
- Electronic Medical Record (EMR) integration

---

## 8. Suggested MVP Features for Demo

For hospital presentation, prioritize the following:

### Essential MVP

- Voice conversation
- Thai + English support
- Symptom intake
- Severity classification
- Department recommendation
- Emergency detection
- Text-to-speech responses

### Optional MVP

- Admin dashboard
- Conversation analytics
- Avatar UI
