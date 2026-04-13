from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os, json, base64, requests, datetime, uuid, hashlib

app = Flask(__name__)
CORS(app)

ADMIN_PASSWORD_DEFAULT = 'ac9689e2272427085e35b9d3e3e8bed88cb3434828b43b86fc0596cad4c6e270'  # admin1234
AZURE_KEY      = os.environ.get('AZURE_VISION_KEY', 'AW6kWq4EcqCgZiXU2vKrDcyFeGOKMcPi7WwtYrlQ7oZ5xvEwXN9gJQQJ99CDAC5RqLJXJ3w3AAAFACOGsQqg')
AZURE_ENDPOINT = os.environ.get('AZURE_ENDPOINT',   'https://pharmacy-vision.cognitiveservices.azure.com/')
GOOGLE_KEY     = os.environ.get('GOOGLE_VISION_KEY', '')
DATA_FILE      = os.path.join(os.environ.get('HOME', '.'), 'data', 'pharmacy_data.json')

# ── Data ───────────────────────────────────────────────────────────
def load_data():
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    if not os.path.exists(DATA_FILE):
        d = {'pharmacies': {}, 'settings': {'ocr_default': 'azure', 'admin_password': ADMIN_PASSWORD_DEFAULT, 'retention_months': 6}, 'usage': {}, 'lists': {}}
        save_data(d); return d
    with open(DATA_FILE, encoding='utf-8') as f:
        return json.load(f)

def save_data(data):
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def get_month():
    return datetime.datetime.now().strftime('%Y-%m')

# ── OCR ────────────────────────────────────────────────────────────
def ocr_azure(b64):
    # Strip data URL prefix if present
    if ',' in b64:
        b64 = b64.split(',')[1]
    b64 = b64.strip()
    url = AZURE_ENDPOINT.rstrip('/') + '/vision/v3.2/ocr'
    # Try JSON first (more reliable)
    res = requests.post(url,
        headers={'Ocp-Apim-Subscription-Key': AZURE_KEY, 'Content-Type': 'application/json'},
        json={'base64Image': b64},
        params={'language': 'el', 'detectOrientation': 'true'})
    if res.status_code != 200:
        # Fallback to binary
        res = requests.post(url,
            headers={'Ocp-Apim-Subscription-Key': AZURE_KEY, 'Content-Type': 'application/octet-stream'},
            data=base64.b64decode(b64),
            params={'language': 'el', 'detectOrientation': 'true'})
    res.raise_for_status()
    lines = []
    for region in res.json().get('regions', []):
        for line in region.get('lines', []):
            lines.append(' '.join(w['text'] for w in line.get('words', [])))
    return '\n'.join(lines)

def ocr_google(b64):
    res = requests.post(f'https://vision.googleapis.com/v1/images:annotate?key={GOOGLE_KEY}',
        json={'requests': [{'image': {'content': b64}, 'features': [{'type': 'TEXT_DETECTION'}], 'imageContext': {'languageHints': ['el','en']}}]})
    res.raise_for_status()
    return res.json()['responses'][0].get('fullTextAnnotation', {}).get('text', '')

def run_ocr(b64, service):
    if service == 'azure':
        try: return ocr_azure(b64), 'azure'
        except:
            if GOOGLE_KEY: return ocr_google(b64), 'google_fallback'
            raise
    elif service == 'google':
        try: return ocr_google(b64), 'google'
        except: return ocr_azure(b64), 'azure_fallback'
    else:
        try: return ocr_azure(b64), 'azure'
        except:
            if GOOGLE_KEY: return ocr_google(b64), 'google_fallback'
            raise Exception('All OCR services failed')

def log_usage(code, service):
    data = load_data()
    m = get_month()
    data['usage'].setdefault(m, {}).setdefault(code, {'azure':0,'google':0,'google_fallback':0,'azure_fallback':0,'total':0})
    data['usage'][m][code][service] = data['usage'][m][code].get(service, 0) + 1
    data['usage'][m][code]['total'] += 1
    save_data(data)

# ── Auto-delete expired lists ──────────────────────────────────────
def cleanup_lists():
    data = load_data()
    now = datetime.datetime.now()
    to_delete = [lid for lid, lst in data.get('lists', {}).items()
                 if datetime.datetime.fromisoformat(lst['expires']) < now]
    for lid in to_delete:
        del data['lists'][lid]
    if to_delete:
        save_data(data)

def check_admin():
    auth = request.headers.get('X-Admin-Password', '')
    data = load_data()
    return hashlib.sha256(auth.encode()).hexdigest() == data['settings'].get('admin_password', ADMIN_PASSWORD_DEFAULT)

# ── Routes ─────────────────────────────────────────────────────────
@app.route('/admin/reset-password')
def reset_password():
    # Temporary endpoint - resets admin password to admin1234
    # DELETE this route after first login
    data = load_data()
    import hashlib
    data['settings']['admin_password'] = hashlib.sha256(b'admin1234').hexdigest()
    save_data(data)
    return jsonify({'ok': True, 'message': 'Password reset to admin1234'})

@app.route('/admin/debug-password')
def debug_password():
    import hashlib
    data = load_data()
    stored = data['settings'].get('admin_password', 'NOT SET')
    test = hashlib.sha256(b'admin1234').hexdigest()
    return jsonify({
        'stored': stored,
        'expected': test,
        'match': stored == test
    })

@app.route('/health')
def health():
    cleanup_lists()
    return jsonify({'status': 'ok', 'time': datetime.datetime.now().isoformat()})

@app.route('/admin')
def admin_panel():
    return send_from_directory('.', 'admin.html')

@app.route('/api/ocr', methods=['POST'])
def do_ocr():
    body  = request.get_json()
    code  = body.get('code', '').strip().upper()
    image = body.get('image', '')
    if not code or not image:
        return jsonify({'ok': False, 'error': 'Missing code or image'}), 400
    data = load_data()
    pharmacy = data['pharmacies'].get(code)
    if not pharmacy or not pharmacy.get('active', True):
        return jsonify({'ok': False, 'error': 'Μη έγκυρος κωδικός πρόσβασης'}), 403
    service = pharmacy.get('ocr_override') or data['settings'].get('ocr_default', 'azure')
    try:
        if ',' in image: image = image.split(',')[1]
        text, used = run_ocr(image, service)
        log_usage(code, used)
        return jsonify({'ok': True, 'text': text, 'service': used, 'pharmacy': pharmacy.get('name', code)})
    except Exception as e:
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
    expires   = (datetime.datetime.now() + datetime.timedelta(days=30*retention)).isoformat()
    data.setdefault('lists', {})[list_id] = {
        'pharmacy_code': code,
        'created': datetime.datetime.now().isoformat(),
        'expires': expires,
        'prescriptions': body.get('prescriptions', [])
    }
    save_data(data)
    return jsonify({'ok': True, 'list_id': list_id, 'expires': expires})

@app.route('/api/lists/<code>', methods=['GET'])
def get_lists(code):
    code = code.strip().upper()
    data = load_data()
    if code not in data['pharmacies']:
        return jsonify({'ok': False, 'error': 'Invalid code'}), 403
    cleanup_lists()
    data = load_data()
    pharmacy_lists = [
        {'list_id': lid, 'created': lst['created'], 'expires': lst['expires'], 'prescriptions': lst['prescriptions']}
        for lid, lst in data.get('lists', {}).items()
        if lst['pharmacy_code'] == code
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

# ── Admin ──────────────────────────────────────────────────────────
@app.route('/admin/login', methods=['POST'])
def admin_login():
    pwd  = request.get_json().get('password', '')
    data = load_data()
    if hashlib.sha256(pwd.encode()).hexdigest() == data['settings'].get('admin_password', ADMIN_PASSWORD_DEFAULT):
        return jsonify({'ok': True})
    return jsonify({'ok': False, 'error': 'Λάθος κωδικός'}), 401

@app.route('/admin/data')
def admin_data():
    if not check_admin(): return jsonify({'error': 'Unauthorized'}), 401
    data     = load_data()
    month    = get_month()
    lists    = data.get('lists', {})
    list_counts = {}
    for lst in lists.values():
        c = lst['pharmacy_code']
        list_counts[c] = list_counts.get(c, 0) + 1
    return jsonify({'pharmacies': data['pharmacies'], 'settings': data['settings'],
                    'usage': data['usage'].get(month, {}), 'list_counts': list_counts, 'month': month})

@app.route('/admin/pharmacy', methods=['POST'])
def add_pharmacy():
    if not check_admin(): return jsonify({'error': 'Unauthorized'}), 401
    name = request.get_json().get('name', '').strip()
    if not name: return jsonify({'ok': False, 'error': 'Name required'}), 400
    code = 'FARM-' + str(uuid.uuid4())[:8].upper()
    data = load_data()
    data['pharmacies'][code] = {'name': name, 'active': True, 'ocr_override': None, 'created': datetime.datetime.now().isoformat()}
    save_data(data)
    return jsonify({'ok': True, 'code': code, 'name': name})

@app.route('/admin/pharmacy/<code>', methods=['PUT'])
def update_pharmacy(code):
    if not check_admin(): return jsonify({'error': 'Unauthorized'}), 401
    body = request.get_json()
    data = load_data()
    if code not in data['pharmacies']: return jsonify({'ok': False}), 404
    for f in ['name', 'active', 'ocr_override']:
        if f in body: data['pharmacies'][code][f] = body[f]
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
    if 'ocr_default'       in body: data['settings']['ocr_default']       = body['ocr_default']
    if 'retention_months'  in body: data['settings']['retention_months']   = int(body['retention_months'])
    if 'admin_password'    in body: data['settings']['admin_password']     = hashlib.sha256(body['admin_password'].encode()).hexdigest()
    save_data(data)
    return jsonify({'ok': True})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8000)))
