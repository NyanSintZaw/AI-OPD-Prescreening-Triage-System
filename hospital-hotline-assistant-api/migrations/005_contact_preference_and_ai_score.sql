ALTER TABLE assessment_reviews
ADD COLUMN IF NOT EXISTS ai_assessment_score SMALLINT
CHECK (ai_assessment_score IS NULL OR ai_assessment_score BETWEEN 1 AND 10);

ALTER TABLE assessment_reviews
ADD COLUMN IF NOT EXISTS ai_assessment_scale SMALLINT NOT NULL DEFAULT 10
CHECK (ai_assessment_scale IN (5, 10));
