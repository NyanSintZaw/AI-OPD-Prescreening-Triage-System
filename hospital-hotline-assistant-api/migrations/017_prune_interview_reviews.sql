-- Remove interview-turn review noise: every turn used to enqueue a pending
-- assessment_review even while severity was still 'unknown', so a session
-- stayed "reviewable" after the nurse confirmed the real assessment.
-- The service now only creates reviews for terminal dispositions and
-- escalations; this prunes the historical pending noise rows.
DELETE FROM assessment_reviews ar
USING severity_assessments sa
WHERE sa.id = ar.assessment_id
  AND ar.status = 'pending'
  AND sa.severity = 'unknown';
