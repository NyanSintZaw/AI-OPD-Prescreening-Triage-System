/**
 * The deployment-prep slide's copy, split out like `business.ts` because three
 * columns of it inlined would make `slides.ts` hard to scan.
 *
 * This slide used to be three, and its hardware half used to be four [FILL]
 * chips. It is not any more: the GPU budget below is measured against a real
 * card, and the application server line is a real allocation. That is the whole
 * point of the slide — the on-prem claim is engineered, not aspirational.
 */
import type { Slide } from './types';

type Checklist = Extract<Slide, { layout: 'checklist' }>;

export const PREP_COLUMNS: Checklist['columns'] = [
  {
    title: 'TECHNICAL',
    items: [
      {
        title: 'Signing in with hospital accounts',
        /* The badge came off at the user's request. The honesty has to live in
           the copy instead: "Today: bearer tokens" says plainly that single
           sign-on is not in place, and the speaker note still asks for it to be
           said aloud. Do not let this sentence drift into implying it ships. */
        body: 'Today: bearer tokens and three roles. Four answers move us onto your directory.',
        terms: [
          { term: 'SAML or OIDC', gloss: 'the protocol we use to talk to your directory' },
          { term: 'AD FS or Azure AD', gloss: 'whichever identity provider you run' },
          { term: 'Group-to-role mapping', gloss: 'which staff groups become admin, nurse or viewer' },
          { term: 'Session lifetime', gloss: 'how long a signed-in session stays valid' },
        ],
      },
      {
        title: 'On your LAN, no public internet',
        terms: [
          { term: 'mTLS', gloss: 'certificates on both ends of the booth-to-HIS link' },
          { term: 'Domain allowlist', gloss: 'booth to your HIS API, staff browsers to the portal' },
          { term: 'Cloud egress', gloss: 'only while running cloud inference — the on-prem build removes it' },
        ],
      },
      {
        title: 'A HIS test endpoint and test records',
        body: 'The one dependency that gates the pilot start date.',
        terms: [
          { term: 'Test endpoint', gloss: 'a non-production copy of your integration API' },
          { term: 'Test records', gloss: 'synthetic patients we can screen safely' },
        ],
      },
      {
        title: 'Staging, then production',
        terms: [
          { term: 'Staging', gloss: 'two weeks of dry-run screening against your test API' },
          { term: 'Production', gloss: 'the first live patient, once staging is signed off' },
        ],
      },
    ],
  },
  {
    title: 'DATA AND INTEGRATION',
    items: [
      {
        kind: 'endpoint',
        /* HN, not VN: identity moved on 2026-08-20 — see docs/his-integration.md.
           The old VN path still exists but nothing in the booth flow calls it. */
        title: 'GET /api/v1/patients/{hn}',
        body: 'Read: name, birthdate, current visit, appointment flag, existing vitals',
      },
      {
        kind: 'endpoint',
        title: 'POST /visits/{id}/prescreen',
        body: 'Write, Stage 1: booth measurements, held narrative',
      },
      {
        kind: 'endpoint',
        title: 'POST /v1/patient-assignments',
        body: 'Write, Stage 2: nurse-confirmed destination and SBAR',
      },
      {
        title: 'The triage manual, as a PDF',
        body: 'Every criterion and every cited explanation is built from it.',
      },
      {
        title: 'Your department list, verbatim in Thai',
        body: '11 routable today, about 64% of routed encounters — plus a named clinical owner to sign off criteria versions.',
      },
      {
        title: 'A sample prescreen export',
        body: 'What we benchmark against. A synthetic sample already ships with our mock HIS.',
      },
    ],
  },
  {
    title: 'HARDWARE',
    items: [
      {
        title: 'Inference server, GPU',
        body: 'One RTX 4000 SFF Ada, 20 GB. The whole local voice stack fits with room to spare:',
        rows: [
          { label: 'LLM', name: 'scb10x/llama3.1-typhoon2-8b-instruct', value: '9.2 GB' },
          { label: 'STT', name: 'faster-whisper large-v3-turbo (fp16)', value: '~2.5 GB' },
          { label: 'TTS', name: 'F5-TTS-THAI v1', value: '~1.5–2.5 GB' },
          { label: 'total', name: '', value: '~14 of 20 GB', total: true },
        ],
      },
      {
        title: 'Application server',
        body: '2 vCPU, 8 GB RAM, 100 GB disk. FastAPI backend, PostgreSQL with pgvector, both staff portals. Modest and CPU-bound.',
      },
      {
        title: 'Storage',
        body: 'That same 100 GB covers sessions, transcripts, the audit trail and the manual embeddings. The retention window is your call.',
      },
      {
        title: 'Booth, per kiosk',
        body: 'Touch screen, mic and speaker, Bluetooth BP cuff, thermometer, slip printer.',
      },
    ],
  },
];

export const PREP_FOOTER =
  'We never connect to your database. You expose a small API, you choose the fields, and you can revoke us without touching it.';
