"""Supabase Auth (GoTrue) HTTP adapter.

All privileged calls stay on the FastAPI server. Browser clients receive a Supabase
user access token, never DATABASE_URL or a project secret key.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

import httpx

from settings import SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, SUPABASE_SERVICE_ROLE_KEY, SUPABASE_SECRET_KEY, PUBLIC_SITE_URL


class AuthServiceError(RuntimeError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class SupabaseAuthGateway:
    @property
    def configured(self) -> bool:
        return bool(SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY and (SUPABASE_SECRET_KEY or SUPABASE_SERVICE_ROLE_KEY))

    @property
    def redirect_url(self) -> str:
        return PUBLIC_SITE_URL.rstrip('/') + '/login'

    def _call(self, method: str, route: str, *, body: dict[str, Any] | None = None,
              user_token: str | None = None, privileged: bool = False,
              query: dict[str, str] | None = None) -> dict[str, Any]:
        if not self.configured:
            raise AuthServiceError(
                'Supabase Auth is not configured. Set SUPABASE_URL, '
                'SUPABASE_PUBLISHABLE_KEY and SUPABASE_SECRET_KEY in server/.env.', 503
            )
        # Auth API keys identify our app; only Supabase user access tokens and
        # legacy JWT keys belong in Authorization. sb_secret_ is NOT a JWT.
        key = (SUPABASE_SECRET_KEY or SUPABASE_SERVICE_ROLE_KEY) if privileged else SUPABASE_PUBLISHABLE_KEY
        headers = {'apikey': key, 'Content-Type': 'application/json'}
        if user_token:
            headers['Authorization'] = f'Bearer {user_token}'
        elif not key.startswith(('sb_secret_', 'sb_publishable_')):
            headers['Authorization'] = f'Bearer {key}'
        target = f'{SUPABASE_URL}/auth/v1{route}'
        if query:
            target += ('&' if '?' in target else '?') + urlencode(query)
        try:
            with httpx.Client(timeout=15, follow_redirects=False) as client:
                res = client.request(method, target, headers=headers, json=body)
        except httpx.RequestError as exc:
            raise AuthServiceError('Cannot reach Supabase Auth. Check your project URL and connection.', 503) from exc
        try:
            response: dict[str, Any] = res.json() if res.content else {}
        except ValueError:
            response = {}
        if res.is_error:
            # Do not expose internal project URLs, headers, or provider stack traces.
            message = str(response.get('msg') or response.get('error_description')
                          or response.get('message') or response.get('error') or 'Authentication request failed.')
            if res.status_code >= 500:
                raise AuthServiceError('Supabase Auth is temporarily unavailable. Please retry.', 502)
            if res.status_code == 429:
                raise AuthServiceError('Too many attempts. Please try again later.', 429)
            if res.status_code in (401, 403):
                raise AuthServiceError(message, res.status_code)
            raise AuthServiceError(message, 400 if res.status_code == 422 else res.status_code)
        return response

    def signup(self, email: str, password: str, full_name: str) -> dict[str, Any]:
        return self._call('POST', '/signup', body={
            'email': email, 'password': password, 'data': {'full_name': full_name},
        }, query={'redirect_to': self.redirect_url})

    def verify_signup(self, email: str, token: str) -> dict[str, Any]:
        return self._call('POST', '/verify', body={'type': 'email', 'email': email, 'token': token})

    def resend_signup(self, email: str) -> dict[str, Any]:
        return self._call('POST', '/resend', body={
            'type': 'signup', 'email': email,
        }, query={'redirect_to': self.redirect_url})

    def password_login(self, email: str, password: str) -> dict[str, Any]:
        return self._call('POST', '/token?grant_type=password', body={'email': email, 'password': password})

    def refresh(self, refresh_token: str) -> dict[str, Any]:
        return self._call('POST', '/token?grant_type=refresh_token', body={'refresh_token': refresh_token})

    def get_user(self, token: str) -> dict[str, Any]:
        response = self._call('GET', '/user', user_token=token)
        # /user normally returns the user directly, not a nested object.
        return response.get('user') if isinstance(response.get('user'), dict) else response

    def request_recovery(self, email: str) -> None:
        self._call('POST', '/recover', body={'email': email}, query={'redirect_to': self.redirect_url})

    def set_password(self, access_token: str, password: str) -> None:
        self._call('PUT', '/user', body={'password': password}, user_token=access_token)

    def revoke_session(self, access_token: str) -> None:
        self._call('POST', '/logout', body={}, user_token=access_token, query={'scope': 'local'})

    def create_staff_account(self, email: str, password: str, full_name: str) -> dict[str, Any]:
        # Direct staff creation. No invite or confirmation email is sent.
        # Admin is responsible for checking the staff member's email address.
        return self._call('POST', '/admin/users', privileged=True, body={
            'email': email, 'password': password, 'email_confirm': True,
            'user_metadata': {'full_name': full_name},
        })

    def delete_staff_identity(self, user_id: str) -> None:
        # Compensation if the later PostgreSQL profile assignment fails.
        # Never call this for an existing identity: only a newly created ID.
        self._call('DELETE', '/admin/users/' + user_id, privileged=True)

    def create_head_admin(self, email: str, password: str, full_name: str) -> dict[str, Any]:
        # Only used with the one-time server-side ADMIN_SETUP_TOKEN.
        return self._call('POST', '/admin/users', privileged=True, body={
            'email': email, 'password': password, 'email_confirm': True,
            'user_metadata': {'full_name': full_name},
        })


auth_gateway = SupabaseAuthGateway()
