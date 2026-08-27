# Frontend (React 19 + Vite + TS)

- Run: `npm run dev` (:5173). Build: `npm run build` (tsc && vite). No lint, no tests.
- Routes in `src/App.tsx`: patient kiosk `/kiosk` (welcome), `/kiosk/attract` (the loop shown when nobody is at the booth), `/kiosk/session` (no auth; legacy `/patient` `/call` redirect there); staff `/nurse` `/admin` via `ProtectedRoute` + localStorage roles. State = hand-rolled hooks + localStorage (react-query installed but unused — don't start using it).
- API: single `api` fetch wrapper `src/api/index.ts` (bearer auto-injected); voice = `src/hooks/useVoiceCall.ts` (~1000 lines: AudioWorklet downsample → 16 kHz Int16 binary WS frames up, 24 kHz PCM gap-free playback down, JSON control frames). Text-chat UI/API was removed — kiosk voice is the only patient flow.
- i18n: inline resources in `src/i18n/resources.ts`, exactly `th` (default) + `en` — always update BOTH blocks.
- Styling: plain global CSS on the **MALI design system** (Brand v1.0), vendored from the repo-root `mali-design-system/` package into `src/design-system/` — edit the package, then `npm run sync:ds` (`-- --check` reports drift); never hand-edit the vendored copy. `src/styles/tokens.css` is the entry that imports it plus a few app layout constants. There is no `--mch-*` alias layer and no `ds-bundle/` — both were retired. Kiosk screens still use the `.kiosk-root` scope with `k-*` classes and their own `--k-*` tokens at the top of `src/styles/kiosk.css`. See `DESIGN.md`. No Tailwind/CSS Modules.
- Patient-safety: patient-facing components never show triage level/color/diagnosis — department + directions only. Patient-facing copy calls the assistant **MALI** (th: มะลิ), never "AI assistant"; nurse/admin copy keeps "AI" so staff know what produced a recommendation.
- Wayfinding map iframe: `public/hospital-map/` is a COPY of repo-root `viewer/` — edit `viewer/`, then copy over.
- Env: `.env` — `VITE_API_BASE_URL`, `VITE_ENABLE_VOICE`, `VITE_FRONTDESK_MODE`, `VITE_VOICE_DEBUG`.
