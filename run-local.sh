#!/usr/bin/env bash
# Start the full on-prem stack. Ports are defined ONCE, here.
#
#   ./run-local.sh          start everything on one machine
#   ./run-local.sh ai       start ONLY the AI node (LLM + speech), bound to
#                           0.0.0.0 so a separate backend machine can reach it
#   ./run-local.sh check    just health-check what is already running
#
# Why these ports: :8000, :8080 and :8081 — the defaults in the READMEs and
# .env.example — are all taken on this machine by unrelated containers
# (license-plate-detector, a Tomcat app, a Spring app).
set -uo pipefail

SPEECH_PORT=${SPEECH_PORT:-8090}   # local-speech sidecar: STT + TTS
OLLAMA_PORT=${OLLAMA_PORT:-11434}  # local LLM
API_PORT=${API_PORT:-8100}         # FastAPI backend (moved off 8000)
WEB_PORT=${WEB_PORT:-5173}         # Vite kiosk

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOGS="$ROOT/.run-logs"
mkdir -p "$LOGS"

# The backend and frontend read these from their own .env files; keep them in
# sync with the ports above so there is one place to change.
sync_env() {
  local api_env="$ROOT/hospital-hotline-assistant-api/.env"
  local web_env="$ROOT/hospital-hotline-assistant-web/.env"
  sed -i -E "s#^(STT_BASE_URL|TTS_BASE_URL)=.*#\1=http://localhost:$SPEECH_PORT/v1#" "$api_env"
  sed -i -E "s#^SCREENING_OPENAI_BASE_URL=.*#SCREENING_OPENAI_BASE_URL=http://localhost:${SPEECH_PORT}/v1#" "$api_env"
  sed -i -E "s#^VITE_API_BASE_URL=.*#VITE_API_BASE_URL=http://localhost:$API_PORT#" "$web_env"
  # The API must allow the kiosk's origin or every browser call fails CORS.
  grep -q "localhost:$WEB_PORT" "$api_env" || echo "  ! add http://localhost:$WEB_PORT to CORS_ORIGINS in $api_env"
}

wait_for() {  # wait_for <url> <name> <seconds>
  local i=0
  until curl -sf -m 2 "$1" >/dev/null 2>&1; do
    i=$((i + 1)); [ "$i" -ge "$3" ] && { echo "  ✗ $2 did not come up"; return 1; }
    sleep 1
  done
  echo "  ✓ $2"
}

check() {
  echo "Health:"
  curl -sf -m 2 "http://localhost:$OLLAMA_PORT/api/tags" >/dev/null && echo "  ✓ ollama      :$OLLAMA_PORT" || echo "  ✗ ollama      :$OLLAMA_PORT"
  curl -sf -m 2 "http://localhost:$SPEECH_PORT/health"   >/dev/null && echo "  ✓ speech      :$SPEECH_PORT" || echo "  ✗ speech      :$SPEECH_PORT"
  curl -sf -m 2 "http://localhost:$API_PORT/health"      >/dev/null && echo "  ✓ backend     :$API_PORT"    || echo "  ✗ backend     :$API_PORT"
  curl -sf -m 2 "http://localhost:$WEB_PORT/"            >/dev/null && echo "  ✓ kiosk       :$WEB_PORT"    || echo "  ✗ kiosk       :$WEB_PORT"
  # Postgres runs natively here (Postgres.app), not in Docker — probe the
  # port, not a container name, so the check is true either way.
  pg_isready -h localhost -p 5432 -q 2>/dev/null \
    && echo "  ✓ postgres    :5432" || echo "  ✗ postgres    :5432"
  curl -sf -m 2 -H "X-API-Key: ${HIS_API_KEY:-demo-his-key}" "http://localhost:8001/api/patients" >/dev/null \
    && echo "  ✓ his-mock    :8001" || echo "  ✗ his-mock    :8001"
}

[ "${1:-}" = "check" ] && { check; exit 0; }

PIDS=()
cleanup() { echo; echo "stopping…"; for p in "${PIDS[@]:-}"; do kill "$p" 2>/dev/null; done; wait 2>/dev/null; }
trap cleanup EXIT INT TERM

# --- AI node only: this machine serves the LLM + speech over the network ----
if [ "${1:-}" = "ai" ]; then
  ip=$(hostname -I | awk '{print $1}')
  echo "AI node — reachable at $ip (speech :$SPEECH_PORT, llm :$OLLAMA_PORT)"

  # Ollama deliberately stays on 127.0.0.1: the gateway inside local-speech
  # proxies /v1/chat/completions to it, so only :SPEECH_PORT is exposed and
  # there is no unauthenticated LLM endpoint on the network.
  if curl -sf -m 2 "http://localhost:$OLLAMA_PORT/api/tags" >/dev/null; then
    echo "  ✓ ollama (private on localhost, proxied via :$SPEECH_PORT)"
  else
    echo "  ✗ ollama is not running — start it with: ollama serve"
  fi

  if ! curl -sf -m 2 "http://localhost:$SPEECH_PORT/health" >/dev/null; then
    ( cd "$ROOT/local-speech" && ./venv/bin/uvicorn server:app --host 0.0.0.0 --port "$SPEECH_PORT" \
      >"$LOGS/speech.log" 2>&1 ) & PIDS+=($!)
    wait_for "http://localhost:$SPEECH_PORT/health" "local-speech" 60
  else echo "  ✓ local-speech (already running)"; fi

  echo
  echo "On the backend machine, set in hospital-hotline-assistant-api/.env:"
  echo "  SCREENING_OPENAI_BASE_URL=http://$ip:$SPEECH_PORT/v1"
  echo "  STT_BASE_URL=http://$ip:$SPEECH_PORT/v1"
  echo "  TTS_BASE_URL=http://$ip:$SPEECH_PORT/v1"
  echo
  # Only follow logs for services this script actually started; when they were
  # already up, their output is going wherever they were launched from.
  if [ -f "$LOGS/speech.log" ] && [ ${#PIDS[@]} -gt 0 ]; then
    tail -f "$LOGS/speech.log"
  else
    echo "Services already running — logs are in their own terminals."
    [ ${#PIDS[@]} -gt 0 ] && wait
  fi
  exit 0
fi

echo "Ports: speech=$SPEECH_PORT ollama=$OLLAMA_PORT api=$API_PORT web=$WEB_PORT"
sync_env

echo "[1/5] databases"
# Only his-mock runs in Docker. Postgres is the native Postgres.app install on
# :5432 (see DATABASE_URL in the api .env); starting the compose postgres too
# would collide on that port and abort the whole `up`.
docker compose -f "$ROOT/docker-compose.yml" up -d his-mock >/dev/null 2>&1 \
  && echo "  ✓ his-mock (docker)" || echo "  ✗ his-mock failed to start"
pg_isready -h localhost -p 5432 -q 2>/dev/null \
  && echo "  ✓ postgres (native, :5432)" \
  || echo "  ✗ postgres is not running — start Postgres.app"

echo "[2/5] ollama"
if ! curl -sf -m 2 "http://localhost:$OLLAMA_PORT/api/tags" >/dev/null; then
  ollama serve >"$LOGS/ollama.log" 2>&1 & PIDS+=($!)
  wait_for "http://localhost:$OLLAMA_PORT/api/tags" "ollama" 30
else echo "  ✓ ollama (already running)"; fi

echo "[3/5] local-speech"
if ! curl -sf -m 2 "http://localhost:$SPEECH_PORT/health" >/dev/null; then
  ( cd "$ROOT/local-speech" && ./venv/bin/uvicorn server:app --host 0.0.0.0 --port "$SPEECH_PORT" \
    >"$LOGS/speech.log" 2>&1 ) & PIDS+=($!)
  wait_for "http://localhost:$SPEECH_PORT/health" "local-speech" 60
else echo "  ✓ local-speech (already running)"; fi

echo "[4/5] backend"
( cd "$ROOT/hospital-hotline-assistant-api" && uv run uvicorn app.main:app --port "$API_PORT" --reload \
  >"$LOGS/api.log" 2>&1 ) & PIDS+=($!)
wait_for "http://localhost:$API_PORT/health" "backend" 90 || echo "    see $LOGS/api.log"

echo "[5/5] kiosk"
( cd "$ROOT/hospital-hotline-assistant-web" && npm run dev -- --port "$WEB_PORT" \
  >"$LOGS/web.log" 2>&1 ) & PIDS+=($!)
wait_for "http://localhost:$WEB_PORT/" "kiosk" 60 || echo "    see $LOGS/web.log"

echo
check
echo
echo "Kiosk:  http://localhost:$WEB_PORT/kiosk"
echo "Logs:   $LOGS/{ollama,speech,api,web}.log"
echo "Ctrl-C to stop everything started here."
tail -f "$LOGS/api.log" "$LOGS/speech.log"
