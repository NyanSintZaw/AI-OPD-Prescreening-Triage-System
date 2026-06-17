ALTER TABLE symptom_entries
ADD COLUMN IF NOT EXISTS pain_location TEXT;

ALTER TABLE symptom_entries
ADD COLUMN IF NOT EXISTS distress_score SMALLINT
CHECK (distress_score IS NULL OR distress_score BETWEEN 0 AND 10);

ALTER TABLE symptom_entries
ADD COLUMN IF NOT EXISTS distress_type TEXT;

ALTER TABLE symptom_entries
ADD COLUMN IF NOT EXISTS red_flags JSONB NOT NULL DEFAULT '[]'::jsonb;
