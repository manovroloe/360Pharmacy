-- Fresh Supabase Storage buckets. Run ONLY AFTER 0001_initial_schema.sql.
-- No source code or SQL file stores Supabase keys or user uploads.
-- Requires storage schema (created by Supabase on hosted projects).
-- Run after 0001_initial_schema.sql.
INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES
  ('product-images','product-images',TRUE,5242880,ARRAY['image/jpeg','image/png','image/webp']),
  ('prescriptions','prescriptions',FALSE,10485760,ARRAY['application/pdf','image/jpeg','image/png','image/webp'])
ON CONFLICT (id) DO NOTHING;
-- Files are uploaded/signed only by the server with a service_role key.
-- Do not grant direct insert/select permissions to anon or authenticated.
