"""Offline Supabase Auth contract checks: no keys or network needed."""
from pathlib import Path
import sys
import json

import pytest
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import infrastructure.supabase_auth as module


@pytest.fixture
def auth_mock(monkeypatch):
    monkeypatch.setattr(module, 'SUPABASE_URL', 'https://example.supabase.co')
    monkeypatch.setattr(module, 'SUPABASE_PUBLISHABLE_KEY', 'test_public_key')
    monkeypatch.setattr(module, 'SUPABASE_SERVICE_ROLE_KEY', 'test_server_secret')
    monkeypatch.setattr(module, 'SUPABASE_SECRET_KEY', 'sb_secret_mock_server_key')
    monkeypatch.setattr(module, 'PUBLIC_SITE_URL', 'http://127.0.0.1:8000')
    calls=[]
    def respond(request):
        calls.append(request)
        path=request.url.path
        if path.endswith('/token') and body(request).get('email') == 'bad@example.com':
            return httpx.Response(401, json={'msg': 'Invalid login credentials'})
        if path.endswith('/token'):
            return httpx.Response(200, json={'access_token':'testjwt','refresh_token':'testrefresh','user':{'id':'U1'},'expires_in':3600})
        if path.endswith('/verify'):
            return httpx.Response(200, json={'access_token':'testjwt','refresh_token':'testrefresh','user':{'id':'U1'},'expires_in':3600})
        if path.endswith('/invite') or path.endswith('/admin/users'):
            return httpx.Response(200,json={'id':'staff-id'})
        if path.endswith('/user'):
            return httpx.Response(200,json={'id':'U1','email':'test@example.com'})
        return httpx.Response(200, json={'ok':True})
    original_client=httpx.Client
    def client_factory(**kwargs):
        kwargs['transport']=httpx.MockTransport(respond)
        return original_client(**kwargs)
    monkeypatch.setattr(module.httpx,'Client',client_factory)
    return module.SupabaseAuthGateway(),calls


def body(request):
    return json.loads(request.content)


def test_signup_requires_customer_metadata_only(auth_mock):
    auth,calls=auth_mock
    auth.signup('new@example.com','not-a-real-password','New Customer')
    assert calls[-1].url.path.endswith('/signup')
    assert body(calls[-1])['data']=={'full_name':'New Customer'}
    assert 'role' not in body(calls[-1])['data']
    assert calls[-1].headers['apikey']=='test_public_key'
    assert 'redirect_to' in calls[-1].url.query.decode()


def test_signup_verification_uses_email_otp(auth_mock):
    auth,calls=auth_mock
    result=auth.verify_signup('new@example.com','123456')
    assert result['access_token']=='testjwt'
    assert body(calls[-1])=={'type':'email','email':'new@example.com','token':'123456'}


def test_every_role_uses_same_password_login(auth_mock):
    auth,calls=auth_mock
    auth.password_login('staff@example.com','secret')
    assert calls[-1].url.path.endswith('/token')
    assert 'grant_type=password' in calls[-1].url.query.decode()
    assert 'role' not in body(calls[-1])


def test_direct_staff_creation_uses_server_secret_no_invite(auth_mock):
    auth,calls=auth_mock
    auth.create_staff_account('staff@example.com', 'InitialPass123!', 'My Staff')
    request=calls[-1]
    assert request.url.path.endswith('/admin/users')
    assert request.headers['apikey']=='sb_secret_mock_server_key'
    # Opaque sb_secret keys are not JWTs, so never send Bearer sb_secret.
    assert 'authorization' not in request.headers
    assert body(request)=={
        'email':'staff@example.com', 'password':'InitialPass123!',
        'email_confirm':True,'user_metadata':{'full_name':'My Staff'},
    }
    auth.delete_staff_identity('staff-id')
    assert calls[-1].method=='DELETE'
    assert calls[-1].url.path.endswith('/admin/users/staff-id')
    assert 'authorization' not in calls[-1].headers
    auth.create_head_admin('head@example.com','secret','Owner')
    assert calls[-1].url.path.endswith('/admin/users')
    assert body(calls[-1])['email_confirm'] is True
    assert 'authorization' not in calls[-1].headers


def test_admin_auth_falls_back_to_legacy_service_role_when_new_secret_missing(auth_mock, monkeypatch):
    auth, calls = auth_mock
    monkeypatch.setattr(module, 'SUPABASE_SECRET_KEY', '')
    auth.create_staff_account('staff@example.com', 'InitialPass123!', 'My Staff')
    assert calls[-1].headers['apikey'] == 'test_server_secret'
    assert calls[-1].headers['authorization'] == 'Bearer test_server_secret'


def test_new_secret_key_is_used_even_if_legacy_key_is_invalid(auth_mock, monkeypatch):
    auth, calls = auth_mock
    monkeypatch.setattr(module, 'SUPABASE_SERVICE_ROLE_KEY', 'invalid_old_key')
    auth.create_staff_account('staff@example.com', 'InitialPass123!', 'My Staff')
    assert calls[-1].headers['apikey'] == 'sb_secret_mock_server_key'
    assert 'authorization' not in calls[-1].headers


def test_password_recovery_and_refresh(auth_mock):
    auth,calls=auth_mock
    auth.request_recovery('staff@example.com')
    assert calls[-1].url.path.endswith('/recover')
    auth.refresh('old_refresh')
    assert body(calls[-1])['refresh_token']=='old_refresh'
    auth.set_password('testjwt','new-password')
    assert calls[-1].headers['authorization']=='Bearer testjwt'
    assert body(calls[-1])=={'password':'new-password'}


def test_auth_error_does_not_expose_keys(auth_mock):
    auth,calls=auth_mock
    with pytest.raises(module.AuthServiceError) as error:
        auth.password_login('bad@example.com','bad')
    assert error.value.status==401
    assert 'test_server_secret' not in str(error.value)
