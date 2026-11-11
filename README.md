## Updates — 12 November 2026

- Customer addresses: Region > Province > City/Municipality > Barangay selectors (PSGC Cloud; network connection needed only when adding an address). Street/house details remain typed by the customer.
- Admin: download financial PDF on Dashboard or Finance (choose report period and date).
- Merchandiser: download the branch inventory and expiry report as a PDF.
- Delivery: assigned riders can preview and save their order receipt as a PNG image. The receipt is generated from order data, not a customer-uploaded proof of payment.
- Admin: Integrations sidebar entry is hidden.
- Customer: branch cards have a **View location** link (Google Maps URL; no key). Order tracking shows the **ordered branch**, not rider GPS. Existing rider location submission remains untouched.
- Performance: static asset caching, parallel storefront initialization, less portal bootstrap work at sign-in, and throttled notification/badge refresh.

**Upgrade notes:** Install the new Python dependency with `INSTALL_DEPENDENCIES.bat` (or `pip install -r requirements.txt`). Copy your **existing local** `server/.env` into this folder; secret credentials are intentionally excluded from the distributable ZIP. Do not upload `.env` to a public repository. No SQL migrations are needed for these changes.

# 360 Pharmacy — Unified Supabase Auth Edition (v5)

**Actual source code**, using a single login interface for customers, administrators, pharmacists, merchandisers and delivery staff. The existing medicine storefront and role-specific operations workspace are preserved. Theme: dark pharmacy green, gold/yellow and yellow-green accents.

## What changed

- `GET /login`: **one login** (email + password), customer signup, email-code verification, and password recovery.
- `GET /workspace`: authenticated role-based operations interface; `GET /portal` redirects there for old bookmarks. There is no staff-login gateway or separate staff password form.
- **Supabase Auth (`auth.users`)** stores all identities/passwords/sessions. A protected `public.profiles` table stores role, full name and optional staff ID. User metadata cannot select a role.
- Admin creates staff accounts **directly with an initial password**. Supabase Auth stores the password; the backend assigns the selected Pharmacist, Merchandiser, or Delivery role. Staff sign in at `/login` without an invitation email. Admin can change permitted staff roles or disable access.
- Customer signup requires email verification via code. Forgot password sends a recovery link.
- Backend uses `httpx` to call Supabase Auth; privileged Auth keys are never placed in HTML or JavaScript. The frontend accesses all other pharmacy data through FastAPI.
- The prior stock-delivery workflow and inventory operations are preserved. Opt-in GPS updates are now available for an assigned delivery staff member while their mobile page remains active.

## 1 — Choose the correct SQL (do not run both)

### New, fully empty Supabase project

Open **Supabase > SQL Editor** and run the complete text of:

`supabase/CREATE_NEW_DATABASE.sql`

This creates **30 application tables** (Supabase itself already has `auth.users`), required profile trigger, indexes, existing role and data restrictions, and two Storage buckets.

### If you already ran the previous Pharmacy360 v4 33-table SQL

Your database is not empty in schema, even if the records are empty. **Do NOT run CREATE_NEW_DATABASE.sql again.** Instead run:

`supabase/UPGRADE_EMPTY_V4_TO_AUTH.sql`

This intentionally stops if the old `profiles`, `auth_accounts`, or Supabase `auth.users` contain identities. It modifies only the empty legacy auth schema and adds `deliveries.last_location_at`. If accounts exist, plan an identity migration first rather than forcing this script.

To verify, run `supabase/VERIFY_NEW_DATABASE.sql` in a new query. No demo accounts or products are inserted by either script.

## 2 — Configure Supabase Auth in the dashboard

1. **Authentication > Sign In / Providers > Email**: enable email/password signup and **Confirm email**.
2. **Authentication > URL Configuration**: set Site URL to your actual application origin (for local work, `http://127.0.0.1:8000`) and add the same origin plus `/login` to Redirect URLs. If using another port or domain, update both.
3. **Authentication > Email Templates > Confirm signup**: put the confirmation OTP in the email template. For example:

   ```html
   <h2>Verify your 360 Pharmacy email</h2>
   <p>Your verification code: <strong>{{ .Token }}</strong></p>
   <p>You can also <a href="{{ .ConfirmationURL }}">verify using this link</a>.</p>
   ```

   The interface accepts 6- or 8-digit verification codes, depending on your project configuration. If your template only contains the default confirmation link, users **won't receive a visible code**.
4. **No Invite User template is required for new staff accounts**: Admin creates them directly with an initial password. This operation does not send an invitation email.
5. **Reset password** template should include `{{ .ConfirmationURL }}`; password recovery redirects land on the unified `/login` page.
6. Configure **custom SMTP** for real users. Supabase's default mail sending has limits and restrictions. Check spam filters and rate limits during testing.

Docs: https://supabase.com/docs/guides/auth/auth-email-templates and https://supabase.com/docs/guides/auth/users

## 3 — Configure `server/.env`

Copy `server/.env.example` to `server/.env`, then enter your own Supabase project values. None are bundled here.

```env
DATABASE_URL=postgresql://YOUR_USER:YOUR_URL_ENCODED_PASSWORD@YOUR_DB_HOST:6543/postgres
SUPABASE_URL=https://YOUR_PROJECT_REF.supabase.co
SUPABASE_PUBLISHABLE_KEY=YOUR_PUBLISHABLE_OR_ANON_KEY
SUPABASE_SECRET_KEY=sb_secret_YOUR_SERVER_SIDE_KEY
# SUPABASE_SERVICE_ROLE_KEY=OPTIONAL_LEGACY_SERVICE_ROLE_JWT
PUBLIC_SITE_URL=http://127.0.0.1:8000
APP_SECRET=GENERATE_RANDOM_48_CHAR_VALUE
ADMIN_SETUP_TOKEN=GENERATE_DIFFERENT_RANDOM_48_CHAR_VALUE
```

- Use **Supabase Connect** to copy the database URL; use its pooler URI where required. Never copy the string above literally.
- The database password must be URL-encoded when necessary (e.g. `@`, `#`, `%`, `/`).
- `SUPABASE_PUBLISHABLE_KEY` is safe to use as an Auth API key but this backend holds it server-side for a single-host deployment.
- `SUPABASE_SECRET_KEY` is **server-only** and required for direct staff creation (or use a valid legacy `SUPABASE_SERVICE_ROLE_KEY`). Never paste it into frontend JS, source control, or client settings.
- `PUBLIC_SITE_URL` must exactly match the browser origin and be in your Supabase Auth redirect allow-list.
- Generate random setup secrets with `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
- When you deploy production behind HTTPS, set `PUBLIC_SITE_URL=https://your-domain` and update Auth settings accordingly.

## 4 — Start on Windows

1. Run `INSTALL_DEPENDENCIES.bat` to set up the Python virtual environment.
2. Run `START_SYSTEM.bat` to launch the FastAPI app.
3. Visit `http://127.0.0.1:8000/` to browse the public storefront.
4. Visit `http://127.0.0.1:8000/login` to sign in or create a customer account.
5. Create the **first Administrator privately** in Supabase Dashboard > Authentication > Users and assign `role = 'admin'` in the protected `public.profiles` table (with the matching `auth.users.id`). There is no public Head Admin setup form.
6. Sign in as Admin and select **Staff Accounts > Create pharmacy staff account**. Enter the staff role, ID, name, email, and initial password. Check the staff email address carefully: Supabase marks Admin-created users as email-confirmed. Give the initial password to the employee privately; they sign in at `/login` and reach the dashboard assigned to that role. No invitation email is sent.

## Auth and permission behavior

| User | Can sign up publicly? | Gets role from | After login |
|---|---|---|---|
| Customer | Yes (email confirmation required) | Server-triggered `customer` role | Public store + personal account |
| Head Admin | No; one-time private setup | Protected server-side Admin assignment | Admin workspace |
| Pharmacist | No; Admin-created account | `public.profiles.role` | Prescription and medicine workspace |
| Merchandiser | No; Admin-created account | `public.profiles.role` | Incoming stock and inventory workspace |
| Delivery Staff | No; Admin-created account | `public.profiles.role` | Assigned deliveries and opt-in GPS |

The backend validates the actual Supabase JWT remotely and reads the authorized role from PostgreSQL on every authenticated request. SQL tables are RLS-enabled and `anon` / `authenticated` have no direct access. **Staff IDs are identifiers, not login usernames.** Changing a role does not change the email/password.

## Limits / unfinished external integrations

- A live Supabase deployment and email service are still necessary; offline syntax tests do not mean email delivery was tested.
- Current **payments are not a live PayMongo gateway**. Do not treat unverified payment redirects or demo methods as paid. PayMongo webhooks and reconciliation remain a separate development task.
- The rider can share actual phone GPS only with permission, while the site is open under **HTTPS or localhost**. The customer map polls roughly every 15 seconds. This does **not** deliver uninterrupted background GPS tracking, road routing or accurate ETA; a native rider app and mapping API would be needed for those.
- Auth sessions are stored client-side to preserve the old vanilla-JS architecture. For hardened production security, migrate session refresh tokens to secure HttpOnly cookies with anti-CSRF measures, use MFA for privileged accounts, add audit monitoring and a strict Content Security Policy.
- Some legacy feature modules remain in `server/main.py` and `client/scripts/portal.js` pending a broader Clean Architecture refactor. Authentication is extracted into `server/infrastructure/supabase_auth.py` and storage remains in its own adapter.

## Structure

```
client/
  index.html                 Public storefront
  login.html                 Shared customer/admin/staff authentication
  portal.html                Staff workspace (no login gate)
  scripts/api.js             API and session refresh helper
  scripts/login.js           Shared login/signup/verify/password-reset flow
  scripts/app.js             Customer experience
  scripts/portal.js          Role-specific staff features
server/
  auth.py                    Verified JWT -> protected user role
  infrastructure/supabase_auth.py
  infrastructure/supabase_storage.py
  main.py                    Protected FastAPI routes
  database.py                PostgreSQL transaction adapter
  .env.example               Environment configuration template
supabase/
  CREATE_NEW_DATABASE.sql
  UPGRADE_EMPTY_V4_TO_AUTH.sql
  VERIFY_NEW_DATABASE.sql
```
