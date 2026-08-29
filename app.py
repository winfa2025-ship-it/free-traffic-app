import os, json, datetime, hashlib, secrets, hmac, base64, urllib.request, urllib.parse
from flask import Flask, request, Response, render_template_string, redirect
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)
DATA = os.path.join(os.path.dirname(__file__), 'data')
SITE_FILE = os.path.join(DATA, 'site.json')
ADMINS_FILE = os.path.join(DATA, 'admin.json')
ADMIN_KEY = os.getenv('ADMIN_KEY', '')
ADMIN_EMAIL = os.getenv('ADMIN_EMAIL', 'admin@local')
ADMIN_PW = os.getenv('ADMIN_PASSWORD', '')
REGISTER_CODE = os.getenv('REGISTER_CODE', '')
SECRET = os.getenv('TOKEN_SECRET', 'change-me')


# ---------- admin auth ----------
def hash_pw(pw, salt=None):
    salt = salt or secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    return salt.hex() + ':' + h.hex()


def load_admins():
    if not os.path.exists(ADMINS_FILE):
        pw = ADMIN_PW or secrets.token_urlsafe(10)
        with open(ADMINS_FILE, 'w') as f:
            json.dump({ADMIN_EMAIL.lower(): {'hash': hash_pw(pw)}}, f)
        if not ADMIN_PW:
            print(f'[admin] no ADMIN_PASSWORD set — generated login: {ADMIN_EMAIL} / {pw}')
    with open(ADMINS_FILE) as f:
        return json.load(f)


def verify_pw(email, pw):
    a = load_admins().get(email.lower())
    if not a:
        return False
    salt, h = a['hash'].split(':')
    test = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1, dklen=32).hex()
    return hmac.compare_digest(test, h)


def add_admin(email, pw):
    admins = load_admins()
    admins[email.lower()] = {'hash': hash_pw(pw)}
    with open(ADMINS_FILE, 'w') as f:
        json.dump(admins, f)


def hmac_token(data, action):
    return hmac.new(SECRET.encode(), f'{action}:{str(data).lower()}'.encode(), hashlib.sha256).hexdigest()


def sess_token(email):
    return base64.urlsafe_b64encode(email.lower().encode()).decode() + '.' + hmac_token(email, 'sess')


def verify_sess(cookie):
    if not cookie or '.' not in cookie:
        return None
    b64, sig = cookie.split('.', 1)
    try:
        e = base64.urlsafe_b64decode(b64).decode()
    except Exception:
        return None
    return e if hmac.compare_digest(hmac_token(e, 'sess'), sig) else None


def check_auth():
    if verify_sess(request.cookies.get('sess')):
        return True
    if ADMIN_KEY and request.headers.get('x-admin-key') == ADMIN_KEY:
        return True
    return False


# ---------- site data ----------
def load():
    with open(SITE_FILE, encoding='utf-8') as f:
        return json.load(f)


def save(d):
    with open(SITE_FILE, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=2)


PAGE = open(os.path.join(os.path.dirname(__file__), 'templates/page.html'), encoding='utf-8').read()
DASH = open(os.path.join(os.path.dirname(__file__), 'templates/dash.html'), encoding='utf-8').read()
LOGIN = open(os.path.join(os.path.dirname(__file__), 'templates/login.html'), encoding='utf-8').read()
REGISTER = open(os.path.join(os.path.dirname(__file__), 'templates/register.html'), encoding='utf-8').read()


# ---------- routes ----------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template_string(LOGIN)
    email = (request.form.get('email') or (request.json or {}).get('email', '')).strip()
    pw = (request.form.get('password') or (request.json or {}).get('password', ''))
    if verify_pw(email, pw):
        resp = redirect('/dashboard')
        resp.set_cookie('sess', sess_token(email), httponly=True, samesite='Lax', max_age=2592000)
        return resp
    return render_template_string(LOGIN, error='Invalid email or password')


@app.route('/logout')
def logout():
    resp = redirect('/login')
    resp.set_cookie('sess', '', max_age=0)
    return resp


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'GET':
        return render_template_string(REGISTER, reg_code=REGISTER_CODE)
    email = (request.form.get('email') or (request.json or {}).get('email', '')).strip().lower()
    pw = request.form.get('password') or (request.json or {}).get('password', '')
    code = request.form.get('code') or (request.json or {}).get('code', '') or ''
    rc = REGISTER_CODE
    if rc and code != rc:
        return render_template_string(REGISTER, error='Invalid invite code', reg_code=REGISTER_CODE)
    if not email or '@' not in email or len(pw) < 6:
        return render_template_string(REGISTER, error='Need a valid email and password (>=6 chars)', reg_code=REGISTER_CODE)
    if email in load_admins():
        return render_template_string(REGISTER, error='Account exists — please login', reg_code=REGISTER_CODE)
    add_admin(email, pw)
    resp = redirect('/dashboard')
    resp.set_cookie('sess', sess_token(email), httponly=True, samesite='Lax', max_age=2592000)
    return resp


@app.route('/')
@app.route('/<lang>')
def page(lang=None):
    site = load()
    lang = lang or site.get('default_lang', 'en')
    p = site['pages'].get(lang, site['pages'][site['default_lang']])
    alts = ''.join(f'<link rel="alternate" hreflang="{l}" href="{site["domain"]}/{l}" />' for l in site['pages'])
    return render_template_string(PAGE, site=site, p=p, alts=alts, lang=lang)


@app.route('/sitemap.xml')
def sitemap():
    site = load()
    urls = [f'<url><loc>{site["domain"]}/</loc></url>'] + \
           [f'<url><loc>{site["domain"]}/{l}</loc></url>' for l in site['pages']]
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + '\n'.join(urls) + '\n</urlset>'
    return Response(xml, mimetype='application/xml')


@app.route('/robots.txt')
def robots():
    site = load()
    return Response(f"User-agent: *\nAllow: /\nSitemap: {site['domain']}/sitemap.xml\n", mimetype='text/plain')


@app.route('/api/seo-check')
def seo_check():
    if not check_auth():
        return {'error': 'unauthorized'}, 401
    site = load()
    lang = request.args.get('lang') or site['default_lang']
    p = site['pages'].get(lang, {})
    tips = []
    t = p.get('title', '')
    if len(t) < 30 or len(t) > 60:
        tips.append(f'title length {len(t)} — aim 30-60 chars')
    d = p.get('description', '')
    if len(d) < 70 or len(d) > 160:
        tips.append(f'description length {len(d)} — aim 70-160 chars')
    if not p.get('keywords'):
        tips.append('add keywords')
    if len(p.get('sections', [])) < 2:
        tips.append('add more content sections (>=2) for richer indexing')
    return {'lang': lang, 'score': max(0, 100 - len(tips) * 15), 'tips': tips}


@app.route('/dashboard', methods=['GET', 'OPTIONS'])
def dashboard():
    if request.method == 'OPTIONS':
        return '', 200
    if not check_auth():
        return redirect('/login')
    return render_template_string(DASH)


@app.route('/api/site', methods=['GET', 'POST'])
def site_api():
    if not check_auth():
        return {'error': 'unauthorized'}, 401
    if request.method == 'GET':
        return load()
    save(request.json)
    return {'ok': True}


@app.route('/api/searchconsole')
def searchconsole():
    if not check_auth():
        return {'error': 'unauthorized'}, 401
    creds = os.path.join(os.path.dirname(__file__), 'credentials.json')
    if not os.path.exists(creds):
        return {'setup': 'missing credentials.json — see README', 'queries': []}
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        svc = build('searchconsole', 'v1', credentials=Credentials.from_authorized_user_file(creds))
        site_url = load()['domain'].rstrip('/')
        body = {'startDate': (datetime.date.today() - datetime.timedelta(days=28)).isoformat(),
                'endDate': datetime.date.today().isoformat(), 'dimensions': ['query'], 'rowLimit': 20}
        r = svc.searchanalytics().query(siteUrl=site_url, body=body).execute()
        rows = [{'query': x['keys'][0], 'clicks': x['clicks'], 'impressions': x['impressions']}
                for x in r.get('rows', [])]
        return {'queries': rows}
    except Exception as e:
        return {'error': str(e), 'queries': []}


@app.route('/api/submit', methods=['POST'])
def submit_sitemap():
    if not check_auth():
        return {'error': 'unauthorized'}, 401
    site = load()
    url = f"{site['domain'].rstrip('/')}/sitemap.xml"
    creds = os.path.join(os.path.dirname(__file__), 'credentials.json')
    if os.path.exists(creds):
        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
            svc = build('searchconsole', 'v1', credentials=Credentials.from_authorized_user_file(creds))
            svc.sitemaps().submit(siteUrl=site['domain'].rstrip('/'), feedUrl=url).execute()
            return {'google': 'submitted via Search Console API', 'sitemap': url,
                    'note': 'Bing: add the sitemap URL in Bing Webmaster Tools.'}
        except Exception as e:
            return {'error': str(e), 'sitemap': url}
    return {'sitemap': url, 'results': {'google': 'ping deprecated', 'bing': 'ping deprecated'},
            'note': 'Legacy sitemap ping was discontinued by Google/Bing. Add the sitemap URL manually in Google Search '
                    'Console (Sitemaps section) and Bing Webmaster Tools, or drop credentials.json here to submit via API.'}


if __name__ == '__main__':
    load_admins()
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', '3000')))
