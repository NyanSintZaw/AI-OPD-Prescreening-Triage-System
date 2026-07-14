-- Nurse-editable clinical narrative on reviews.
-- The AI's symptoms_summary / key_reason live in session metadata; these
-- columns hold what the nurse actually signs off (edited or as-is), which is
-- what gets published to the HIS at Stage 2.
ALTER TABLE assessment_reviews
    ADD COLUMN IF NOT EXISTS chief_complaint text,
    ADD COLUMN IF NOT EXISTS illness_note text;
