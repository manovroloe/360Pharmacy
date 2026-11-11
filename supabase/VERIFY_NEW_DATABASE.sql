-- Verify Supabase Auth and Pharmacy360 role model (read-only)
SELECT count(*) AS pharmacy_tables
FROM information_schema.tables WHERE table_schema='public'
AND table_type='BASE TABLE';

SELECT tc.constraint_name, ccu.table_schema AS identity_schema, ccu.table_name AS identity_table
FROM information_schema.table_constraints tc
JOIN information_schema.constraint_column_usage ccu
  ON tc.constraint_name=ccu.constraint_name AND tc.constraint_schema=ccu.constraint_schema
WHERE tc.table_schema='public' AND tc.table_name='profiles' AND tc.constraint_type='FOREIGN KEY'
  AND ccu.table_schema='auth' AND ccu.table_name='users';

SELECT tgname AS profile_creation_trigger
FROM pg_trigger WHERE tgrelid='auth.users'::regclass
  AND tgname='pharmacy360_auth_user_created';

SELECT name, public FROM storage.buckets WHERE id IN ('product-images','prescriptions');
