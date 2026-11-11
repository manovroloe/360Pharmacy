"""Offline route checks; database and Supabase Auth calls are patched, no external credentials."""
import sys
import types
from pathlib import Path
import importlib.util
import pytest

# CI containers with a full dependency install will use the real psycopg. The
# fallback modules below allow validating route/auth separation without it.
if importlib.util.find_spec('psycopg') is None:
    pg = types.ModuleType('psycopg')
    pg.Error = OSError
    pg.connect = lambda *a,**k: None
    pg.__path__ = []
    rows = types.ModuleType('psycopg.rows')
    rows.dict_row = object()
    typesmod = types.ModuleType('psycopg.types')
    typesmod.__path__ = []
    jsonmod = types.ModuleType('psycopg.types.json')
    jsonmod.Jsonb = lambda value: value
    sys.modules.update({'psycopg':pg,'psycopg.rows':rows,'psycopg.types':typesmod,'psycopg.types.json':jsonmod})

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
from fastapi.testclient import TestClient
import main as appmodule
from auth import current_user

client = TestClient(appmodule.app)


def test_single_login_route_and_no_old_staff_login_gateway():
    assert client.get('/login').status_code == 200
    assert 'signinForm' in client.get('/login').text
    assert 'portalLoginTabs' not in client.get('/workspace').text
    assert client.get('/portal', follow_redirects=False).headers['location'] == '/workspace'


def test_customer_registration_cannot_claim_admin(monkeypatch):
    captured=[]
    monkeypatch.setattr(appmodule.auth_gateway, 'signup', lambda email, passwd, name: captured.append((email,passwd,name)) or {'id':'new'})
    r=client.post('/api/auth/register',json={'email':'customer@example.com','full_name':'New Customer','password':'password123','role':'admin'})
    assert r.status_code == 200
    assert r.json()['emailVerificationRequired'] is True
    assert captured == [('customer@example.com','password123','New Customer')]


def test_unified_password_login_reads_backend_role(monkeypatch):
    monkeypatch.setattr(appmodule.auth_gateway, 'password_login', lambda email,passw: {'access_token':'test-access','refresh_token':'test-refresh','expires_in':3600,'user':{'id':'u1'}})
    monkeypatch.setattr(appmodule, 'profile_for_user', lambda uid: {'id':uid,'role':'pharmacist','is_active':True})
    result=client.post('/api/auth/login',json={'email':'user@example.com','password':'testpass','role':'admin'})
    assert result.status_code == 200
    assert result.json()['profile']['role'] == 'pharmacist'


def test_staff_creation_rejects_public_customer(monkeypatch):
    appmodule.app.dependency_overrides[current_user] = lambda: {'profile':{'id':'customer-1','role':'customer'}}
    try:
        result=client.post('/api/admin/staff',json={'email':'staff@example.com','role':'admin','staff_id':'STAFF-01','full_name':'Staff Member'})
        assert result.status_code == 403
    finally:
        appmodule.app.dependency_overrides.clear()


def test_staff_creation_cannot_assign_admin_role(monkeypatch):
    appmodule.app.dependency_overrides[current_user] = lambda: {'profile':{'id':'admin-1','role':'admin'}}
    try:
        result=client.post('/api/admin/staff',json={'email':'staff@example.com','role':'admin','staff_id':'STAFF-01','full_name':'Staff Member'})
        assert result.status_code == 400
    finally:
        appmodule.app.dependency_overrides.clear()


STAFF_PAYLOAD = {
    'email': 'pharm@example.com', 'role': 'pharmacist', 'staff_id': 'PHARM-001',
    'full_name': 'Pharmacy Staff', 'password': 'InitialPass123!', 'phone': '',
}


def test_admin_directly_creates_staff_with_password_and_role(monkeypatch):
    account_calls = []
    profile_calls = []
    event_calls = []
    appmodule.app.dependency_overrides[current_user] = lambda: {'profile': {'id': 'admin-1', 'role': 'admin'}}
    monkeypatch.setattr(appmodule.db, 'select', lambda table, filters: [])
    monkeypatch.setattr(appmodule.auth_gateway, 'create_staff_account',
                        lambda email, password, name: account_calls.append((email, password, name)) or {'id': 'staff-uuid'})
    def record_profile(table, payload, conflict):
        profile_calls.append((table, dict(payload), conflict))
        return [dict(payload)]
    monkeypatch.setattr(appmodule.db, 'upsert', record_profile)
    monkeypatch.setattr(appmodule, 'log_activity', lambda *args: event_calls.append(args))
    try:
        result=client.post('/api/admin/staff', json=STAFF_PAYLOAD)
        assert result.status_code == 200, result.text
        assert result.json()['role'] == 'pharmacist'
        assert result.json()['created'] is True
        assert 'password' not in result.text.lower()
        assert 'invitation_sent' not in result.text
        assert account_calls == [('pharm@example.com', 'InitialPass123!', 'Pharmacy Staff')]
        assert profile_calls[0][1]['role'] == 'pharmacist'
        assert 'password' not in profile_calls[0][1]
        assert event_calls[0][2] == 'created_staff_account'
        assert 'InitialPass123!' not in repr(event_calls)
    finally:
        appmodule.app.dependency_overrides.clear()


def test_staff_creation_requires_initial_password(monkeypatch):
    appmodule.app.dependency_overrides[current_user] = lambda: {'profile': {'id': 'admin-1', 'role': 'admin'}}
    try:
        payload = dict(STAFF_PAYLOAD, password='abc')
        result = client.post('/api/admin/staff', json=payload)
        assert result.status_code == 400
        assert 'at least 8' in result.json()['detail']
    finally:
        appmodule.app.dependency_overrides.clear()


def test_staff_creation_removes_new_auth_user_if_profile_insert_fails(monkeypatch):
    from database import DatabaseError
    removed=[]
    appmodule.app.dependency_overrides[current_user] = lambda: {'profile': {'id': 'admin-1', 'role': 'admin'}}
    monkeypatch.setattr(appmodule.db, 'select', lambda table, filters: [])
    monkeypatch.setattr(appmodule.auth_gateway, 'create_staff_account', lambda email, password, name: {'id': 'new-staff'})
    monkeypatch.setattr(appmodule.auth_gateway, 'delete_staff_identity', lambda uid: removed.append(uid))
    def fail(*args, **kwargs):
        raise DatabaseError('Simulated profile constraint failure')
    monkeypatch.setattr(appmodule.db, 'upsert', fail)
    try:
        result = client.post('/api/admin/staff', json=STAFF_PAYLOAD)
        assert result.status_code == 503
        assert removed == ['new-staff']
        assert 'InitialPass123!' not in result.text
    finally:
        appmodule.app.dependency_overrides.clear()
