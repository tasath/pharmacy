"""
Backend API Tests — Σάρωση SMS Συνταγών
pytest tests/test_api.py -v
"""
import pytest, json, time, copy, datetime, sys, os
import unittest.mock as mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

# Import once — we'll patch functions on the module directly
import app_clean

BASE_DATA = {
    'pharmacies': {
        'FARM-TEST0001': {'name': 'Φαρμακείο Δοκιμής', 'active': True, 'ocr_override': None, 'created': '2026-01-01T00:00:00'},
        'FARM-INACTIVE': {'name': 'Ανενεργό', 'active': False, 'ocr_override': None, 'created': '2026-01-01T00:00:00'}
    },
    'settings': {
        'ocr_default': 'google',
        'admin_password': 'ac9689e2272427085e35b9d3e3e8bed88cb3434828b43b86fc0596cad4c6e270',
        'retention_months': 6
    },
    'usage': {},
    'lists': {}
}

SAMPLE_RX = [
    {'number': '2603273623318101', 'ekdosi': '14/04/2026', 'lixis': '14/07/2026'},
    {'number': '2603273623318202', 'ekdosi': '14/07/2026', 'lixis': '14/10/2026'},
]

@pytest.fixture(autouse=True)
def mock_storage():
    """Patch load_data/save_data on the module before each test"""
    store = copy.deepcopy(BASE_DATA)

    def fake_load():
        return copy.deepcopy(store)

    def fake_save(data):
        store.clear()
        store.update(copy.deepcopy(data))

    with mock.patch.object(app_clean, 'load_data', side_effect=fake_load), \
         mock.patch.object(app_clean, 'save_data', side_effect=fake_save):
        yield store

@pytest.fixture
def client():
    app_clean.app.config['TESTING'] = True
    return app_clean.app.test_client()

@pytest.fixture
def client_with_data(mock_storage):
    """Client that also exposes the store for pre-population"""
    app_clean.app.config['TESTING'] = True
    return app_clean.app.test_client(), mock_storage

# ═══ 1. HEALTH ════════════════════════════════════════════════════
class TestHealth:
    def test_health_ok(self, client):
        r = client.get('/health')
        assert r.status_code == 200
        assert json.loads(r.data)['status'] == 'ok'

# ═══ 2. ADMIN LOGIN ═══════════════════════════════════════════════
class TestAdminLogin:
    def test_correct_password(self, client):
        r = client.post('/admin/login', json={'password': 'admin1234'}, content_type='application/json')
        assert r.status_code == 200
        assert json.loads(r.data)['ok'] is True

    def test_wrong_password(self, client):
        r = client.post('/admin/login', json={'password': 'wrong'}, content_type='application/json')
        assert r.status_code == 401

    def test_empty_password(self, client):
        r = client.post('/admin/login', json={'password': ''}, content_type='application/json')
        assert r.status_code == 401

# ═══ 3. OCR ═══════════════════════════════════════════════════════
class TestOCR:
    def test_missing_code_400(self, client):
        r = client.post('/api/ocr', json={'image': 'dGVzdA=='}, content_type='application/json')
        assert r.status_code == 400

    def test_missing_image_400(self, client):
        r = client.post('/api/ocr', json={'code': 'FARM-TEST0001'}, content_type='application/json')
        assert r.status_code == 400

    def test_invalid_code_403(self, client):
        r = client.post('/api/ocr', json={'code': 'FARM-INVALID', 'image': 'dGVzdA=='}, content_type='application/json')
        assert r.status_code == 403

    def test_inactive_pharmacy_403(self, client):
        r = client.post('/api/ocr', json={'code': 'FARM-INACTIVE', 'image': 'dGVzdA=='}, content_type='application/json')
        assert r.status_code == 403

    def test_valid_code_mocked_google(self, client):
        ocr_text = 'Έκδοση Συνταγής # 2603273623318101\n14/04/2026\n14/07/2026'
        with mock.patch.object(app_clean, 'ocr_google', return_value=ocr_text), \
             mock.patch.object(app_clean, 'log_usage'):
            r = client.post('/api/ocr', json={'code': 'FARM-TEST0001', 'image': 'dGVzdA=='}, content_type='application/json')
            assert r.status_code == 200
            data = json.loads(r.data)
            assert data['ok'] is True
            assert '2603273623318101' in data['text']

# ═══ 4. LISTS ═════════════════════════════════════════════════════
class TestLists:
    def test_save_valid(self, client):
        r = client.post('/api/lists', json={'code': 'FARM-TEST0001', 'prescriptions': SAMPLE_RX}, content_type='application/json')
        assert r.status_code == 200
        data = json.loads(r.data)
        assert data['ok'] is True
        assert len(data['list_id']) == 8

    def test_save_invalid_code(self, client):
        r = client.post('/api/lists', json={'code': 'FARM-INVALID', 'prescriptions': SAMPLE_RX}, content_type='application/json')
        assert r.status_code == 403

    def test_save_and_retrieve(self, client):
        r1 = client.post('/api/lists', json={'code': 'FARM-TEST0001', 'prescriptions': SAMPLE_RX}, content_type='application/json')
        list_id = json.loads(r1.data)['list_id']
        r2 = client.get('/api/lists/FARM-TEST0001')
        assert r2.status_code == 200
        lists = json.loads(r2.data)['lists']
        assert any(l['list_id'] == list_id for l in lists)

    def test_public_list_access(self, client):
        r1 = client.post('/api/lists', json={'code': 'FARM-TEST0001', 'prescriptions': SAMPLE_RX}, content_type='application/json')
        list_id = json.loads(r1.data)['list_id']
        r2 = client.get(f'/api/public/{list_id}')
        assert r2.status_code == 200
        assert len(json.loads(r2.data)['prescriptions']) == 2

    def test_delete_list(self, client):
        r1 = client.post('/api/lists', json={'code': 'FARM-TEST0001', 'prescriptions': SAMPLE_RX}, content_type='application/json')
        list_id = json.loads(r1.data)['list_id']
        r2 = client.delete(f'/api/lists/{list_id}?code=FARM-TEST0001')
        assert r2.status_code == 200

    def test_delete_list_wrong_pharmacy(self, client, mock_storage):
        mock_storage['pharmacies']['FARM-TEST0002'] = {
            'name': 'Φαρμακείο Β', 'active': True, 'ocr_override': None, 'created': '2026-01-01T00:00:00'
        }
        r1 = client.post('/api/lists', json={'code': 'FARM-TEST0001', 'prescriptions': SAMPLE_RX}, content_type='application/json')
        list_id = json.loads(r1.data)['list_id']
        r2 = client.delete(f'/api/lists/{list_id}?code=FARM-TEST0002')
        assert r2.status_code == 403

    def test_nonexistent_list_404(self, client):
        r = client.get('/api/public/NOTEXIST')
        assert r.status_code == 404

    def test_save_empty_prescriptions(self, client):
        r = client.post('/api/lists', json={'code': 'FARM-TEST0001', 'prescriptions': []}, content_type='application/json')
        assert r.status_code == 200

    def test_expired_list_404(self, client, mock_storage):
        mock_storage['lists']['EXPIRED01'] = {
            'pharmacy_code': 'FARM-TEST0001',
            'created': '2025-01-01T00:00:00',
            'expires': '2025-07-01T00:00:00',
            'prescriptions': SAMPLE_RX
        }
        r = client.get('/api/public/EXPIRED01')
        assert r.status_code == 404

# ═══ 5. ADMIN ═════════════════════════════════════════════════════
H = {'X-Admin-Password': 'admin1234'}

class TestAdmin:
    def test_get_data(self, client):
        r = client.get('/admin/data', headers=H)
        assert r.status_code == 200
        assert 'FARM-TEST0001' in json.loads(r.data)['pharmacies']

    def test_unauthorized(self, client):
        r = client.get('/admin/data', headers={'X-Admin-Password': 'wrong'})
        assert r.status_code == 401

    def test_add_pharmacy(self, client):
        r = client.post('/admin/pharmacy', json={'name': 'Νέο Φαρμακείο'}, headers=H, content_type='application/json')
        assert r.status_code == 200
        data = json.loads(r.data)
        assert data['code'].startswith('FARM-')
        assert 'default_password' in data

    def test_add_pharmacy_no_name(self, client):
        r = client.post('/admin/pharmacy', json={'name': ''}, headers=H, content_type='application/json')
        assert r.status_code == 400

    def test_deactivate_pharmacy(self, client):
        r = client.put('/admin/pharmacy/FARM-TEST0001', json={'active': False}, headers=H, content_type='application/json')
        assert r.status_code == 200

    def test_delete_pharmacy(self, client):
        r = client.delete('/admin/pharmacy/FARM-TEST0001', headers=H)
        assert r.status_code == 200

    def test_change_retention(self, client):
        r = client.put('/admin/settings', json={'retention_months': 12}, headers=H, content_type='application/json')
        assert r.status_code == 200

    def test_change_admin_password(self, client):
        r1 = client.put('/admin/settings', json={'admin_password': 'newpwd123'}, headers=H, content_type='application/json')
        assert r1.status_code == 200
        r2 = client.post('/admin/login', json={'password': 'admin1234'}, content_type='application/json')
        assert r2.status_code == 401
        r3 = client.post('/admin/login', json={'password': 'newpwd123'}, content_type='application/json')
        assert r3.status_code == 200

    def test_admin_reset(self, client):
        client.put('/admin/settings', json={'admin_password': 'changed'}, headers=H, content_type='application/json')
        client.get('/admin/reset')
        r = client.post('/admin/login', json={'password': 'admin1234'}, content_type='application/json')
        assert r.status_code == 200

# ═══ 6. PERFORMANCE ═══════════════════════════════════════════════
class TestPerformance:
    RX_6 = [
        {'number': f'260327362331810{i}', 'ekdosi': '14/04/2026', 'lixis': '14/07/2026'}
        for i in range(1, 7)
    ]

    def _populate_lists(self, store, n, pharmacy='FARM-TEST0001'):
        now = datetime.datetime.now()
        for i in range(n):
            store['lists'][f'LST{i:05d}'] = {
                'pharmacy_code': pharmacy,
                'created': (now - datetime.timedelta(days=i)).isoformat(),
                'expires': (now + datetime.timedelta(days=180)).isoformat(),
                'prescriptions': copy.deepcopy(SAMPLE_RX)
            }

    def test_retrieve_100_lists_under_1s(self, client, mock_storage):
        self._populate_lists(mock_storage, 100)
        start = time.time()
        r = client.get('/api/lists/FARM-TEST0001')
        elapsed = time.time() - start
        assert r.status_code == 200
        assert len(json.loads(r.data)['lists']) == 100
        assert elapsed < 1.0, f'Too slow: {elapsed:.3f}s (limit 1.0s)'
        print(f'\n  ✅ 100 lists retrieved in {elapsed*1000:.1f}ms')

    def test_admin_panel_100_lists_3_pharmacies(self, client, mock_storage):
        for i in range(2, 4):
            mock_storage['pharmacies'][f'FARM-TEST000{i}'] = {
                'name': f'Φαρμακείο {i}', 'active': True,
                'ocr_override': None, 'created': '2026-01-01T00:00:00'
            }
        now = datetime.datetime.now()
        codes = ['FARM-TEST0001', 'FARM-TEST0002', 'FARM-TEST0003']
        for i in range(100):
            mock_storage['lists'][f'LST{i:05d}'] = {
                'pharmacy_code': codes[i % 3],
                'created': (now - datetime.timedelta(days=i)).isoformat(),
                'expires': (now + datetime.timedelta(days=180)).isoformat(),
                'prescriptions': copy.deepcopy(SAMPLE_RX)
            }
        start = time.time()
        r = client.get('/admin/data', headers=H)
        elapsed = time.time() - start
        assert r.status_code == 200
        result = json.loads(r.data)
        assert sum(result['list_counts'].values()) == 100
        assert elapsed < 1.0, f'Too slow: {elapsed:.3f}s'
        print(f'\n  ✅ Admin data 100 lists / 3 pharmacies in {elapsed*1000:.1f}ms')

    def test_public_list_6_prescriptions(self, client):
        r1 = client.post('/api/lists', json={'code': 'FARM-TEST0001', 'prescriptions': self.RX_6}, content_type='application/json')
        list_id = json.loads(r1.data)['list_id']
        start = time.time()
        r2 = client.get(f'/api/public/{list_id}')
        elapsed = time.time() - start
        assert r2.status_code == 200
        assert len(json.loads(r2.data)['prescriptions']) == 6
        assert elapsed < 0.5
        print(f'\n  ✅ Public list (6 rx) in {elapsed*1000:.1f}ms')

    def test_lists_sorted_newest_first(self, client, mock_storage):
        self._populate_lists(mock_storage, 10)
        r = client.get('/api/lists/FARM-TEST0001')
        lists = json.loads(r.data)['lists']
        dates = [l['created'] for l in lists]
        assert dates == sorted(dates, reverse=True)
        print(f'\n  ✅ Lists correctly sorted newest first')
