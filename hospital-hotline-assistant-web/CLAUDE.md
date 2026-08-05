# Frontend (React 19 + Vite + TS)

- Run: `npm run dev` (:5173). Build: `npm run build` (tsc && vite). No lint, no tests.
- Routes in `src/App.tsx`: patient kiosk `/kiosk` `/kiosk/session` (no auth; legacy `/patient` `/call` redirect there); staff `/nurse` `/admin` via `ProtectedRoute` + localStorage roles. State = hand-rolled hooks + localStorage (react-query installed but unused — don't start using it).
- API: single `api` fetch wrapper `src/api/index.ts` (bearer auto-injected); voice = `src/hooks/useVoiceCall.ts` (~1000 lines: AudioWorklet downsample → 16 kHz Int16 binary WS frames up, 24 kHz PCM gap-free playback down, JSON control frames). Text-chat UI/API was removed — kiosk voice is the only patient flow.
- i18n: inline resources in `src/i18n/resources.ts`, exactly `th` (default) + `en` — always update BOTH blocks.
- Styling: plain global CSS, tokens in `src/styles/tokens.css` (`--mch-*` brand vars). Kiosk screens use the ds-bundle kiosk world (`.kiosk-root` scope, `k-*` classes) — see `ds-bundle/README.md` before writing kiosk markup. No Tailwind/CSS Modules.
- Patient-safety: patient-facing components never show triage level/color/diagnosis — department + directions only.
- Wayfinding map iframe: `public/hospital-map/` is a COPY of repo-root `viewer/` — edit `viewer/`, then copy over.
- Env: `.env` — `VITE_API_BASE_URL`, `VITE_ENABLE_VOICE`, `VITE_FRONTDESK_MODE`, `VITE_VOICE_DEBUG`.
