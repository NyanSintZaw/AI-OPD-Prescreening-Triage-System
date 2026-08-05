-- Rename the confusingly-named 'admin' role to 'nurse'.
-- The role gates the nurse review portal; the actual admin portal is
-- super_admin-only. Roles become: super_admin | nurse | viewer.
-- Existing rows (e.g. the seeded opd.nurse@mfu.local) follow the rename.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_enum e
        JOIN pg_type t ON t.oid = e.enumtypid
        WHERE t.typname = 'admin_role' AND e.enumlabel = 'admin'
    ) THEN
        ALTER TYPE admin_role RENAME VALUE 'admin' TO 'nurse';
    END IF;
END
$$;
