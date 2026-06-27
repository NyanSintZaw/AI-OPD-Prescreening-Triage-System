-- One surveillance record per session (UPSERT support).
-- Remove duplicate rows (keep the one with the latest reported_at), then add constraint.
DELETE FROM disease_surveillance
WHERE ctid NOT IN (
    SELECT DISTINCT ON (session_id) ctid
    FROM disease_surveillance
    ORDER BY session_id, reported_at DESC
);

ALTER TABLE disease_surveillance
    ADD CONSTRAINT uq_disease_surveillance_session
    UNIQUE (session_id);
