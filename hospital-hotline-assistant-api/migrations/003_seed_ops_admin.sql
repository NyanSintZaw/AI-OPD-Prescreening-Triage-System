-- Seed operations admin for the staff dashboard (separate from OPD nurse account).
INSERT INTO admin_users (email, password_hash, full_name, role, is_active)
VALUES (
    'ops.admin@mfu.local',
    'sha256$' || encode(digest('admin1234', 'sha256'), 'hex'),
    'Operations Admin (Seed)',
    'super_admin',
    TRUE
)
ON CONFLICT (email) DO NOTHING;
