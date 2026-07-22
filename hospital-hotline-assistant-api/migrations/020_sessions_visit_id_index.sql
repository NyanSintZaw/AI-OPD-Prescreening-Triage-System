-- Lookup index for session resume: re-entering the same VN finds the most
-- recent active session linked to that visit (metadata.visit.visit_id).
CREATE INDEX IF NOT EXISTS idx_sessions_visit_id
    ON sessions ((metadata->'visit'->>'visit_id'))
    WHERE metadata->'visit'->>'visit_id' IS NOT NULL;
