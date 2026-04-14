from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os, json, base64, requests, datetime, uuid, hashlib

app = Flask(__name__)
CORS(app)

# ── Config ─────────────────────────────────────────────────────────
GOOGLE_KEY     = os.environ.get('GOOGLE_VISION_KEY', '')
GIST_ID        = os.environ.get('GIST_ID', '')
GITHUB_TOKEN   = os.environ.get('GITHUB_TOKEN', '')
GIST_FILENAME  = 'pharmacy_data.json'

def make_hash(pwd):
    return hashlib.sha256(pwd.encode()).hexdigest()

DEFAULT_HASH = make_hash('admin1234')

# ── Gist Storage ───────────────────────────────────────────────────
def load_data():
    try:
        res = requests.get(
            f'https://api.github.com/gists/{GIST_ID}',
            headers={'Authorization': f'token {GITHUB_TOKEN}', 'Accept': 'application/vnd.github.v3+json'})
        res.raise_for_status()
        return json.loads(res.json()['files'][GIST_FILENAME]['content'])
    except Exception as e:
        print(f'load_data error: {e}')
        return {'pharmacies': {}, 'settings': {'admin_password': DEFAULT_HASH, 'retention_months': 6}, 'usage': {}, 'lists': {}}

def save_data(data):
    try:
        res = requests.patch(
            f'https://api.github.com/gists/{GIST_ID}',
            headers={'Authorization': f'token {GITHUB_TOKEN}', 'Accept': 'application/vnd.github.v3+json'},
            json={'files': {GIST_FILENAME: {'content': json.dumps(data, indent=2, ensure_ascii=False)}}})
        res.raise_for_status()
    except Exception as e:
        print(f'save_data error: {e}')

def get_month():
    return datetime.datetime.now().strftime('%Y-%m')

def check_admin():
    pwd    = request.headers.get('X-Admin-Password', '')
    data   = load_data()
    stored = data['settings'].get('admin_password', DEFAULT_HASH)
    return make_hash(pwd) == stored

# ── OCR — Google Vision only ───────────────────────────────────────
def clean_b64(b64):
    if ',' in b64: b64 = b64.split(',')[1]
    return b64.strip()

def ocr_google(b64):
    b64 = clean_b64(b64)
    res = requests.post(
        f'https://vision.googleapis.com/v1/images:annotate?key={GOOGLE_KEY}',
        json={'requests': [{'image': {'content': b64}, 'features': [{'type': 'TEXT_DETECTION'}], 'imageContext': {'languageHints': ['el', 'en']}}]})
    res.raise_for_status()
    return res.json()['responses'][0].get('fullTextAnnotation', {}).get('text', '')

def log_usage(code, service):
    data = load_data()
    m    = get_month()
    data['usage'].setdefault(m, {}).setdefault(code, {'google': 0, 'total': 0})
    data['usage'][m][code][service] = data['usage'][m][code].get(service, 0) + 1
    data['usage'][m][code]['total'] += 1
    save_data(data)

def cleanup_lists(data):
    now = datetime.datetime.now()
    to_delete = [lid for lid, lst in data.get('lists', {}).items()
                 if datetime.datetime.fromisoformat(lst['expires']) < now]
    for lid in to_delete: del data['lists'][lid]
    return data, len(to_delete) > 0

# ── Routes ─────────────────────────────────────────────────────────
@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'time': datetime.datetime.now().isoformat()})

@app.route('/admin')
def admin_panel():
    return send_from_directory('.', 'admin.html')

@app.route('/admin/reset')
def admin_reset():
    data = load_data()
    data['settings']['admin_password'] = DEFAULT_HASH
    save_data(data)
    return jsonify({'ok': True, 'message': 'Password reset to admin1234'})

@app.route('/api/ocr', methods=['POST'])
def do_ocr():
    body  = request.get_json()
    code  = body.get('code', '').strip().upper()
    image = body.get('image', '')
    if not code or not image:
        return jsonify({'ok': False, 'error': 'Missing code or image'}), 400
    data     = load_data()
    pharmacy = data['pharmacies'].get(code)
    if not pharmacy or not pharmacy.get('active', True):
        return jsonify({'ok': False, 'error': 'Μη έγκυρος κωδικός πρόσβασης'}), 403
    try:
        text = ocr_google(image)
        log_usage(code, 'google')
        print(f'OCR ok: len={len(text)}')
        return jsonify({'ok': True, 'text': text, 'service': 'google', 'pharmacy': pharmacy.get('name', code)})
    except Exception as e:
        import traceback
        print(f'OCR error: {traceback.format_exc()}')
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/lists', methods=['POST'])
def save_list():
    body = request.get_json()
    code = body.get('code', '').strip().upper()
    data = load_data()
    if code not in data['pharmacies']:
        return jsonify({'ok': False, 'error': 'Invalid code'}), 403
    retention = data['settings'].get('retention_months', 6)
    list_id   = str(uuid.uuid4())[:8].upper()
    expires   = (datetime.datetime.now() + datetime.timedelta(days=30 * retention)).isoformat()
    data.setdefault('lists', {})[list_id] = {
        'pharmacy_code': code, 'created': datetime.datetime.now().isoformat(),
        'expires': expires, 'prescriptions': body.get('prescriptions', [])
    }
    save_data(data)
    return jsonify({'ok': True, 'list_id': list_id, 'expires': expires})

@app.route('/api/public/<list_id>', methods=['GET'])
def public_list(list_id):
    data = load_data()
    lst  = data.get('lists', {}).get(list_id)
    if not lst:
        return jsonify({'ok': False, 'error': 'Η λίστα δεν βρέθηκε ή έχει λήξει'}), 404
    if datetime.datetime.fromisoformat(lst['expires']) < datetime.datetime.now():
        return jsonify({'ok': False, 'error': 'Η λίστα έχει λήξει'}), 404
    return jsonify({'ok': True, 'prescriptions': lst['prescriptions'], 'created': lst['created'], 'expires': lst['expires']})

@app.route('/api/lists/<code>', methods=['GET'])
def get_lists(code):
    code = code.strip().upper()
    data = load_data()
    if code not in data['pharmacies']:
        return jsonify({'ok': False, 'error': 'Invalid code'}), 403
    data, changed = cleanup_lists(data)
    if changed: save_data(data)
    pharmacy_lists = [
        {'list_id': lid, 'created': lst['created'], 'expires': lst['expires'], 'prescriptions': lst['prescriptions']}
        for lid, lst in data.get('lists', {}).items() if lst['pharmacy_code'] == code
    ]
    pharmacy_lists.sort(key=lambda x: x['created'], reverse=True)
    return jsonify({'ok': True, 'lists': pharmacy_lists})

@app.route('/api/lists/<list_id>', methods=['DELETE'])
def delete_list(list_id):
    code = request.args.get('code', '').strip().upper()
    data = load_data()
    lst  = data.get('lists', {}).get(list_id)
    if not lst: return jsonify({'ok': False, 'error': 'Not found'}), 404
    if lst['pharmacy_code'] != code: return jsonify({'ok': False, 'error': 'Unauthorized'}), 403
    del data['lists'][list_id]
    save_data(data)
    return jsonify({'ok': True})

# ── Pharmacy password (stored in Gist) ────────────────────────────
@app.route('/api/pharmacy/login', methods=['POST'])
def pharmacy_login():
    body = request.get_json()
    code = body.get('code', '').strip().upper()
    pwd  = body.get('password', '')
    data = load_data()
    pharmacy = data['pharmacies'].get(code)
    if not pharmacy or not pharmacy.get('active', True):
        return jsonify({'ok': False, 'error': 'Μη έγκυρος κωδικός'}), 403
    stored = pharmacy.get('password_hash')
    if stored and make_hash(pwd) != stored:
        return jsonify({'ok': False, 'error': 'Λάθος κωδικός'}), 401
    return jsonify({'ok': True, 'pharmacy': pharmacy.get('name', code)})

# ── Admin routes ───────────────────────────────────────────────────
@app.route('/admin/login', methods=['POST'])
def admin_login():
    pwd    = request.get_json().get('password', '')
    data   = load_data()
    stored = data['settings'].get('admin_password', DEFAULT_HASH)
    if make_hash(pwd) == stored:
        return jsonify({'ok': True})
    return jsonify({'ok': False, 'error': 'Λάθος κωδικός'}), 401

@app.route('/admin/data')
def admin_data():
    if not check_admin(): return jsonify({'error': 'Unauthorized'}), 401
    data        = load_data()
    list_counts = {}
    for lst in data.get('lists', {}).values():
        c = lst['pharmacy_code']
        list_counts[c] = list_counts.get(c, 0) + 1
    return jsonify({
        'pharmacies':  data['pharmacies'],
        'settings':    data['settings'],
        'usage':       data['usage'].get(get_month(), {}),
        'list_counts': list_counts,
        'month':       get_month()
    })

@app.route('/admin/pharmacy', methods=['POST'])
def add_pharmacy():
    if not check_admin(): return jsonify({'error': 'Unauthorized'}), 401
    name = request.get_json().get('name', '').strip()
    if not name: return jsonify({'ok': False, 'error': 'Name required'}), 400
    code = 'FARM-' + str(uuid.uuid4())[:8].upper()
    # Generate simple default password
    default_pwd = str(uuid.uuid4())[:6].upper()
    data = load_data()
    data['pharmacies'][code] = {
        'name': name, 'active': True,
        'password_hash': make_hash(default_pwd),
        'created': datetime.datetime.now().isoformat()
    }
    save_data(data)
    return jsonify({'ok': True, 'code': code, 'name': name, 'default_password': default_pwd})

@app.route('/admin/pharmacy/<code>', methods=['PUT'])
def update_pharmacy(code):
    if not check_admin(): return jsonify({'error': 'Unauthorized'}), 401
    body = request.get_json()
    data = load_data()
    if code not in data['pharmacies']: return jsonify({'ok': False, 'error': 'Not found'}), 404
    for f in ['name', 'active']:
        if f in body: data['pharmacies'][code][f] = body[f]
    if 'pharmacy_password' in body:
        data['pharmacies'][code]['password_hash'] = make_hash(body['pharmacy_password'])
    save_data(data)
    return jsonify({'ok': True})

@app.route('/admin/pharmacy/<code>', methods=['DELETE'])
def delete_pharmacy(code):
    if not check_admin(): return jsonify({'error': 'Unauthorized'}), 401
    data = load_data()
    if code in data['pharmacies']: del data['pharmacies'][code]
    save_data(data)
    return jsonify({'ok': True})

@app.route('/admin/settings', methods=['PUT'])
def update_settings():
    if not check_admin(): return jsonify({'error': 'Unauthorized'}), 401
    body = request.get_json()
    data = load_data()
    if 'retention_months' in body: data['settings']['retention_months'] = int(body['retention_months'])
    if 'admin_password'   in body: data['settings']['admin_password']   = make_hash(body['admin_password'])
    save_data(data)
    return jsonify({'ok': True})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8000)))
