-- PHARMACY 360 v4 EMPTY DATABASE -> v5 SUPABASE AUTH
-- RUN ONLY IF you already ran the old 33-table schema on a NEW, EMPTY project.
-- Stops instead of deleting real account/profile records. Does not drop business tables.
BEGIN;
SET LOCAL search_path TO public;

DO $upgrade_check$
BEGIN
  IF to_regclass('public.profiles') IS NULL THEN
    RAISE EXCEPTION 'The Pharmacy360 v4 profiles table is missing. Use CREATE_NEW_DATABASE.sql on a brand-new project.';
  END IF;
  IF EXISTS(SELECT 1 FROM public.profiles LIMIT 1) THEN
    RAISE EXCEPTION 'Existing profiles found. This automatic schema-only Auth upgrade is unsafe; migrate users individually.';
  END IF;
  IF EXISTS(SELECT 1 FROM auth.users LIMIT 1) THEN
    RAISE EXCEPTION 'Supabase auth.users is not empty. Stop and review identities before upgrading.';
  END IF;
  IF to_regclass('public.auth_accounts') IS NOT NULL THEN
    IF EXISTS(SELECT 1 FROM public.auth_accounts LIMIT 1) THEN
      RAISE EXCEPTION 'Legacy auth_accounts contains data. Stop for a manual identity migration.';
    END IF;
  END IF;
END;
$upgrade_check$;

-- The v4 files used more than one possible name for the profile-to-account
-- foreign key. Drop whichever constraint ACTUALLY references auth_accounts.
DO $drop_legacy_fk$
DECLARE
  legacy_fk RECORD;
BEGIN
  IF to_regclass('public.auth_accounts') IS NOT NULL THEN
    FOR legacy_fk IN
      SELECT con.conname
      FROM pg_constraint con
      WHERE con.conrelid = 'public.profiles'::regclass
        AND con.confrelid = 'public.auth_accounts'::regclass
        AND con.contype = 'f'
    LOOP
      EXECUTE format('ALTER TABLE public.profiles DROP CONSTRAINT %I', legacy_fk.conname);
    END LOOP;
  END IF;
END;
$drop_legacy_fk$;

ALTER TABLE public.profiles DROP CONSTRAINT IF EXISTS fk_profile_identity;
ALTER TABLE public.profiles
  ADD CONSTRAINT fk_profile_identity FOREIGN KEY(id) REFERENCES auth.users(id) ON DELETE CASCADE;

DROP TABLE IF EXISTS public.auth_sessions;
DROP TABLE IF EXISTS public.email_otps;
DROP TABLE IF EXISTS public.auth_accounts;
-- Add an optional timestamp for GPS updates from the active rider browser.
ALTER TABLE public.deliveries ADD COLUMN IF NOT EXISTS last_location_at TIMESTAMPTZ NULL;

CREATE OR REPLACE FUNCTION public.pharmacy360_new_auth_profile()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
BEGIN
  INSERT INTO public.profiles(id,email,full_name,role,is_active)
  VALUES (NEW.id, NEW.email,
    LEFT(COALESCE(NEW.raw_user_meta_data ->> 'full_name', ''),160),
    'customer', TRUE)
  ON CONFLICT (id) DO NOTHING;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS pharmacy360_auth_user_created ON auth.users;
CREATE TRIGGER pharmacy360_auth_user_created
AFTER INSERT ON auth.users
FOR EACH ROW EXECUTE FUNCTION public.pharmacy360_new_auth_profile();

COMMIT;
