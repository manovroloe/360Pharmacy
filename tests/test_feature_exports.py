"""Offline regressions for the new PDF and receipt routes (no live credentials)."""
import sys
import types
import importlib.util
from pathlib import Path

if importlib.util.find_spec('psycopg') is None:
    pg = types.ModuleType('psycopg')
    pg.__spec__ = importlib.util.spec_from_loader('psycopg', loader=None)
    pg.Error = OSError
    pg.connect = lambda *a, **kw: None
    pg.__path__ = []
    rows = types.ModuleType('psycopg.rows'); rows.dict_row = object()
    typesmod = types.ModuleType('psycopg.types'); typesmod.__path__ = []
    jsonmod = types.ModuleType('psycopg.types.json'); jsonmod.Jsonb = lambda x: x
    sys.modules.update({'psycopg':pg,'psycopg.rows':rows,'psycopg.types':typesmod,'psycopg.types.json':jsonmod})

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
from fastapi.testclient import TestClient
from auth import current_user
import main as m

client = TestClient(m.app)


def as_role(role, identifier='u1'):
    m.app.dependency_overrides[current_user] = lambda: {'profile': {'id': identifier, 'role': role}}


def test_pdf_permissions(monkeypatch):
    as_role('customer')
    try:
        assert client.get('/api/admin/financial-report.pdf').status_code == 403
        assert client.get('/api/inventory/report.pdf').status_code == 403
    finally:
        m.app.dependency_overrides.clear()


def test_admin_financial_pdf(monkeypatch):
    as_role('admin')
    monkeypatch.setattr(m, 'dashboard', lambda period,date,user: {'period':period,'referenceDate':'2026-11-12','orders':[]})
    try:
        response=client.get('/api/admin/financial-report.pdf?period=month&date=2026-11-12')
        assert response.status_code == 200
        assert response.headers['content-type'].startswith('application/pdf')
        assert response.content.startswith(b'%PDF-')
    finally:
        m.app.dependency_overrides.clear()


def test_merch_inventory_pdf(monkeypatch):
    as_role('merchandiser')
    monkeypatch.setattr(m, 'inventory', lambda user: {'inventory': [], 'batches': []})
    try:
        response=client.get('/api/inventory/report.pdf')
        assert response.status_code == 200
        assert response.content.startswith(b'%PDF-')
    finally:
        m.app.dependency_overrides.clear()


def test_receipt_protected_and_contains_items(monkeypatch):
    as_role('delivery','rider-1')
    def select(table, filters):
        if table == 'deliveries':
            return [{'id':'delivery-1','order_id':'order-1','assigned_to':'rider-1'}]
        if table == 'order_items':
            return [{'product_name_snapshot':'Paracetamol','quantity':2,'final_unit_price':5.0,'line_total':10.0}]
        return []
    monkeypatch.setattr(m.db,'select',select)
    monkeypatch.setattr(m,'record',lambda table, uid: {'id':'order-1','fulfillment':'delivery','order_number':'ORD-1','payment_status':'unpaid','total_amount':10.0})
    try:
        r=client.get('/api/delivery/packages/delivery-1/receipt')
        assert r.status_code==200 and r.json()['items'][0]['quantity']==2
        m.app.dependency_overrides[current_user] = lambda: {'profile': {'id':'different-rider','role':'delivery'}}
        assert client.get('/api/delivery/packages/delivery-1/receipt').status_code == 403
    finally:
        m.app.dependency_overrides.clear()
