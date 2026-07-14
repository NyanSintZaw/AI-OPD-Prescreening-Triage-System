-- 019: patients can now answer by tapping a quick-reply chip; tag those
-- messages so the nurse transcript shows how each answer was given
-- (voice / text / button).
ALTER TYPE input_mode ADD VALUE IF NOT EXISTS 'button';
