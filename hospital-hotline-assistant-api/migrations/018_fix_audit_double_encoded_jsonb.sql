-- 018: repair double-JSON-encoded jsonb in ai_inference_audit.
--
-- persistence.write_audit pre-dumped rules_trace/validator_result with
-- json.dumps while the asyncpg pool codec (app/database.py) also encodes,
-- so the columns stored JSONB *string scalars* containing JSON text, e.g.
--   validator_result = '"[\"diagnosis\"]"'   (string, not array)
--   rules_trace      = '"{\"question_id\": \"dc_onset\"}"'
-- jsonb_array_elements_text() on such a scalar made GET /admin/ai-metrics
-- fail with "cannot extract elements from a scalar", and the dispositions
-- breakdown (rules_trace->>'level') silently read NULLs.
--
-- Unwrap one encoding level: the scalar's text (#>> '{}') IS the intended
-- JSON document. Idempotent — repaired rows are no longer of type 'string'.

UPDATE ai_inference_audit
SET rules_trace = (rules_trace #>> '{}')::jsonb
WHERE jsonb_typeof(rules_trace) = 'string';

UPDATE ai_inference_audit
SET validator_result = (validator_result #>> '{}')::jsonb
WHERE jsonb_typeof(validator_result) = 'string';
