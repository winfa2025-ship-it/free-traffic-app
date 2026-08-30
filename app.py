import os, json, datetime, hashlib, secrets, hmac, base64, sqlite3, urllib.request, urllib.parse, re, time
from collections import defaultdict
from flask import Flask, request, Response, render_template_string, redirect
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)

_EMOJI_RE = re.compile(r'[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u2190-\u21FF\u2300-\u23FF]')
@app.template_filter('noemoji')
def noemoji(s):
    return _EMOJI_RE.sub('', str(s)).strip()
DATA = os.path.join(os.path.dirname(__file__), 'data')
SITE_FILE = os.path.join(DATA, 'site.json')
ADMINS_FILE = os.path.join(DATA, 'admin.json')
ADMIN_KEY = os.getenv('ADMIN_KEY', '')
ADMIN_EMAIL = os.getenv('ADMIN_EMAIL', 'admin@local')
ADMIN_PW = os.getenv('ADMIN_PASSWORD', '')
REGISTER_CODE = os.getenv('REGISTER_CODE', '')
SECRET_FILE = os.path.join(DATA, '.secret')
def _load_secret():
    val = (os.getenv('TOKEN_SECRET') or '').strip()
    if val and val != 'change-me':
        return val
    # Fall back to a persisted random secret so session tokens can't be forged
    # with the old default, and sessions survive restarts.
    try:
        if os.path.exists(SECRET_FILE):
            return open(SECRET_FILE, encoding='utf-8').read().strip()
    except Exception:
        pass
    new = secrets.token_urlsafe(32)
    try:
        with open(SECRET_FILE, 'w', encoding='utf-8') as f:
            f.write(new)
    except Exception:
        pass
    return new
SECRET = _load_secret()
def _cookie_secure():
    return os.getenv('SECURE_COOKIE', 'true').lower() != 'false'

_login_attempts = defaultdict(list)
def _rate_limited(key, limit=10, window=300):
    now = time.time()
    buf = _login_attempts[key]
    buf[:] = [t for t in buf if now - t < window]
    if len(buf) >= limit:
        return True
    buf.append(now)
    return False


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


def body():
    if request.form:
        return request.form.to_dict()
    return request.get_json(silent=True) or {}


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


# ---------- stats ----------
STATS_DB = os.path.join(DATA, 'stats.db')

SEARCH_ENGINES = {
    'google.': 'google', 'bing.com': 'bing', 'yahoo.com': 'yahoo', 'baidu.com': 'baidu',
    'yandex': 'yandex', 'duckduckgo.com': 'duckduckgo', 'ecosia.org': 'ecosia',
    'qwant.com': 'qwant', 'naver.com': 'naver', 'ask.com': 'ask', 'aol.com': 'aol',
    'brave.com': 'brave', 'startpage.com': 'startpage', 'sogou.com': 'sogou',
    'so.com': '360', 'mail.ru': 'mailru', 'seznam.cz': 'seznam',
}
QUERY_PARAMS = {
    'google': 'q', 'bing': 'q', 'yahoo': 'p', 'baidu': 'wd', 'yandex': 'text',
    'duckduckgo': 'q', 'ecosia': 'q', 'qwant': 'q', 'naver': 'query', 'ask': 'q',
    'aol': 'q', 'brave': 'q', 'startpage': 'query', 'sogou': 'query', 'so.com': 'q',
    'mail.ru': 'q', 'seznam.cz': 'q',
}


def classify_ref(ref):
    if not ref:
        return ('direct', '')
    try:
        u = urllib.parse.urlparse(ref)
        host = (u.netloc or '').lower()
        qs = urllib.parse.parse_qs(u.query)
        src = None
        for k, v in SEARCH_ENGINES.items():
            if k in host:
                src = v
                break
        if src:
            qp = QUERY_PARAMS.get(src)
            q = (qs.get(qp, [''])[0] if qp else '')
            if src == 'google' and not q:
                q = qs.get('q', [''])[0]
            return (src, (q or '').strip()[:100])
        return (host or 'referral', '')
    except Exception:
        return ('referral', '')


def init_stats():
    conn = sqlite3.connect(STATS_DB)
    conn.execute('CREATE TABLE IF NOT EXISTS hits(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, lang TEXT, path TEXT, ip_hash TEXT, ref TEXT)')
    conn.execute('CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, lang TEXT, type TEXT)')
    for col, typ in (('source', 'TEXT'), ('query', 'TEXT')):
        try:
            conn.execute(f'ALTER TABLE hits ADD COLUMN {col} {typ}')
        except Exception:
            pass
    conn.commit(); conn.close()

def record_hit(lang, path):
    try:
        if 'dashboard' in (request.headers.get('Referer') or ''):
            return  # skip the admin preview iframe
        ip = (request.headers.get('X-Forwarded-For') or request.remote_addr or '').split(',')[0].strip()
        iph = hashlib.sha256((ip + SECRET).encode()).hexdigest()[:16]
        ref = (request.headers.get('Referer') or '')[:500]
        source, query = classify_ref(ref)
        conn = sqlite3.connect(STATS_DB)
        conn.execute('INSERT INTO hits(ts,lang,path,ip_hash,ref,source,query) VALUES(?,?,?,?,?,?,?)',
                     (datetime.datetime.now().isoformat(), lang, path, iph, ref, source, query))
        conn.commit(); conn.close()
    except Exception as e:
        print('[hit]', e)

# ---------- content pages (SEO landing pages from keywords) ----------
def slugify(s):
    s = (s or '').lower().strip()
    ascii_part = re.sub(r'[^a-z0-9]+', '-', s).strip('-')
    if ascii_part:
        return ascii_part[:60]
    return 'kw-' + hashlib.md5(s.encode()).hexdigest()[:8]


def template_generate(keyword, lang, cta_url, cta_label, n=5):
    kw = keyword.strip()
    if lang == 'zh':
        title = f"{kw} 完整指南 2026：推薦、評測與購買建議"
        desc = f"深入解析 {kw}：從挑選要點、常見問題到購買建議，一篇看懂 {kw} 的一切，幫你做出最好選擇。"
        hero = f"{kw} 完整指南"
        lead = f"正在尋找最適合你的 {kw}？本指南彙整 2026 年最新資訊，帶你快速了解 {kw} 的優點、用法與選購重點。"
        sections = [
            {"h2": f"為什麼 {kw} 值得關注", "body": f"隨著需求成長，{kw} 成為熱門話題。本文整理關鍵資訊，協助你在眾多選擇中快速找到合適方案。"},
            {"h2": f"{kw} 的選購重點", "body": f"挑選 {kw} 時，建議從品質、來源、口碑與價格四個面向評估，才能買得安心、用得開心。"},
            {"h2": f"{kw} 常見問題 FAQ", "body": f"Q：{kw} 適合所有人嗎？A：多數人皆可，但仍建議依自身需求選擇。Q：哪裡買最划算？A：可比較官方與授權通路。"},
            {"h2": f"2026 年 {kw} 趨勢", "body": f"今年 {kw} 朝向更高品質與多元方向發展，早鳥與限量方案尤其受到關注。"},
            {"h2": f"立即行動：入手 {kw}", "body": f"心動不如行動，現在就透過下方按鈕了解並支持 {kw} 的最新方案。"},
        ]
    else:
        title = f"Best {kw} in 2026 — Complete Guide, Tips & Where to Buy"
        desc = f"Everything you need to know about {kw}: how to choose, FAQ, trends and where to get the best {kw} in 2026."
        hero = f"The Complete {kw} Guide"
        lead = f"Looking for the best {kw}? This 2026 guide covers how to choose, common questions, and where to buy {kw} with confidence."
        sections = [
            {"h2": f"Why {kw} matters in 2026", "body": f"{kw.title()} has become a hot topic as demand grows. This guide gathers the key facts so you can decide quickly."},
            {"h2": f"How to choose the right {kw}", "body": f"When picking {kw}, weigh quality, source, reputation and price to get the best fit for your needs."},
            {"h2": f"Frequently asked questions about {kw}", "body": f"Q: Is {kw} right for everyone? A: Most people, but choose based on your own needs. Q: Where is it cheapest? A: Compare official and authorized channels."},
            {"h2": f"2026 trends for {kw}", "body": f"This year {kw} is moving toward higher quality and more variety; early-bird and limited editions draw the most attention."},
            {"h2": f"Get your {kw} now", "body": f"Ready to act? Use the button below to explore and support the latest {kw} offer."},
        ]
    return {"title": title, "description": desc, "keywords": kw, "hero_title": hero,
            "hero_lead": lead, "cta_label": cta_label, "cta_url": cta_url,
            "sections": sections[:max(3, n)]}


def llm_generate(keyword, lang, cta_url, cta_label):
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        return None
    model = os.getenv('OPENAI_MODEL', 'gpt-4o-mini')
    lang_name = {'zh': 'Traditional Chinese', 'ja': 'Japanese', 'ko': 'Korean',
                 'es': 'Spanish', 'ar': 'Arabic', 'ru': 'Russian', 'de': 'German',
                 'fr': 'French', 'pt': 'Portuguese', 'it': 'Italian', 'hi': 'Hindi',
                 'vi': 'Vietnamese', 'id': 'Indonesian', 'th': 'Thai', 'tr': 'Turkish'}.get(lang, 'English')
    sys = ("You are an SEO copywriter. Return ONLY valid JSON (no markdown) with exactly these keys: "
           "title (30-60 chars), description (70-160 chars), keywords (comma list), hero_title, "
           "hero_lead (1-2 sentences), and sections (array of 5 objects each with h2 and body (2-3 sentences)). "
           "Naturally include the keyword. Make content original, helpful, and written for humans.")
    user = (f"Write an SEO-optimized landing page about the keyword \"{keyword}\" in {lang_name}. "
            f"The page should drive readers to this call-to-action: \"{cta_label}\" -> {cta_url}. "
            f"Include the keyword in the title, first heading and first paragraph. Add an FAQ section. "
            f"Respond with JSON only.")
    try:
        req = urllib.request.Request(
            'https://api.openai.com/v1/chat/completions',
            data=json.dumps({"model": model, "messages": [
                {"role": "system", "content": sys}, {"role": "user", "content": user}],
                "response_format": {"type": "json_object"}, "temperature": 0.7}).encode(),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read())
        c = json.loads(data['choices'][0]['message']['content'])
        out = template_generate(keyword, lang, cta_url, cta_label)
        for k in ('title', 'description', 'keywords', 'hero_title', 'hero_lead'):
            if c.get(k):
                out[k] = c[k]
        if isinstance(c.get('sections'), list) and len(c['sections']) >= 3:
            out['sections'] = [{"h2": s.get('h2', ''), "body": s.get('body', '')}
                                for s in c['sections'] if s.get('h2')]
        return out
    except Exception as e:
        print('[llm]', e)
        return None


def generate_content(keyword, lang, cta_url, cta_label):
    if os.getenv('OPENAI_API_KEY'):
        r = llm_generate(keyword, lang, cta_url, cta_label)
        if r:
            return r
    return template_generate(keyword, lang, cta_url, cta_label)


# ---------- routes ----------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template_string(LOGIN)
    ip = (request.headers.get('X-Forwarded-For') or request.remote_addr or '').split(',')[0].strip()
    if _rate_limited('login:' + ip):
        return render_template_string(LOGIN, error='Too many attempts. Try again later.'), 429
    b = body()
    email = (b.get('email') or '').strip()
    pw = b.get('password') or ''
    if verify_pw(email, pw):
        resp = redirect('/dashboard')
        resp.set_cookie('sess', sess_token(email), httponly=True, samesite='Lax', secure=_cookie_secure(), max_age=2592000)
        return resp
    return render_template_string(LOGIN, error='Invalid email or password')


@app.route('/logout')
def logout():
    resp = redirect('/login')
    resp.set_cookie('sess', '', httponly=True, secure=_cookie_secure(), max_age=0)
    return resp


@app.route('/register', methods=['GET', 'POST'])
def register():
    rc = REGISTER_CODE
    if not rc:
        return render_template_string(REGISTER, error='Registration is disabled. Set REGISTER_CODE to enable.', reg_code='')
    if request.method == 'GET':
        return render_template_string(REGISTER, reg_code=rc)
    ip = (request.headers.get('X-Forwarded-For') or request.remote_addr or '').split(',')[0].strip()
    if _rate_limited('register:' + ip):
        return render_template_string(REGISTER, error='Too many attempts. Try again later.', reg_code=rc), 429
    b = body()
    email = (b.get('email') or '').strip().lower()
    pw = b.get('password') or ''
    code = b.get('code') or ''
    if code != rc:
        return render_template_string(REGISTER, error='Invalid invite code', reg_code=rc)
    if not email or '@' not in email or len(pw) < 6:
        return render_template_string(REGISTER, error='Need a valid email and password (>=6 chars)', reg_code=rc)
    if email in load_admins():
        return render_template_string(REGISTER, error='Account exists — please login', reg_code=rc)
    add_admin(email, pw)
    resp = redirect('/dashboard')
    resp.set_cookie('sess', sess_token(email), httponly=True, samesite='Lax', secure=_cookie_secure(), max_age=2592000)
    return resp


@app.route('/')
@app.route('/<lang>')
def page(lang=None):
    site = load()
    lang = lang or site.get('default_lang', 'en')
    p = site['pages'].get(lang, site['pages'][site['default_lang']])
    alts = ''.join(f'<link rel="alternate" hreflang="{l}" href="{site["domain"]}/{l}" />' for l in site['pages'])
    if request.endpoint == 'page':
        record_hit(lang, request.path)
    return render_template_string(PAGE, site=site, p=p, alts=alts, lang=lang,
                                  base='/', is_content=False, switcher=list(site['pages'].keys()))

@app.route('/api/event', methods=['POST'])
def event():
    lang = request.args.get('lang', '')
    etype = request.args.get('type', '')
    try:
        conn = sqlite3.connect(STATS_DB)
        conn.execute('INSERT INTO events(ts,lang,type) VALUES(?,?,?)',
                     (datetime.datetime.now().isoformat(), lang, etype))
        conn.commit(); conn.close()
    except Exception as e:
        print('[event]', e)
    return ('', 204)

@app.route('/api/stats-view')
def stats_view():
    if not check_auth():
        return {'error': 'unauthorized'}, 401
    conn = sqlite3.connect(STATS_DB)
    total = conn.execute('SELECT COUNT(*) FROM hits').fetchone()[0]
    cta = conn.execute("SELECT COUNT(*) FROM events WHERE type='cta'").fetchone()[0]
    by_lang = dict(conn.execute('SELECT lang,COUNT(*) FROM hits GROUP BY lang').fetchall())
    days = []
    for i in range(6, -1, -1):
        d = (datetime.date.today() - datetime.timedelta(days=i)).isoformat()
        n = conn.execute("SELECT COUNT(*) FROM hits WHERE ts LIKE ?", (d + '%',)).fetchone()[0]
        days.append({'date': d, 'n': n})
    top_ref = [r[0] for r in conn.execute(
        "SELECT ref,COUNT(*) c FROM hits WHERE ref<>'' GROUP BY ref ORDER BY c DESC LIMIT 8").fetchall()]
    by_source = dict(conn.execute('SELECT COALESCE(source,\'unknown\'),COUNT(*) FROM hits GROUP BY COALESCE(source,\'unknown\')').fetchall())
    search_total = sum(v for k, v in by_source.items() if k in SEARCH_ENGINES.values())
    top_paths = [{'path': r[0], 'n': r[1]} for r in conn.execute(
        "SELECT path,COUNT(*) c FROM hits GROUP BY path ORDER BY c DESC LIMIT 10").fetchall()]
    top_queries = [{'query': r[0], 'n': r[1]} for r in conn.execute(
        "SELECT query,COUNT(*) c FROM hits WHERE query<>'' GROUP BY query ORDER BY c DESC LIMIT 15").fetchall()]
    conn.close()
    return {'total': total, 'cta': cta, 'by_lang': by_lang, 'last7': days, 'top_ref': top_ref,
            'by_source': by_source, 'search_total': search_total,
            'top_paths': top_paths, 'top_queries': top_queries}


@app.route('/p/<slug>')
@app.route('/p/<slug>/<lang>')
def content_page(slug, lang=None):
    site = load()
    cps = site.get('content_pages', {})
    cp = cps.get(slug)
    if not cp:
        return 'Not found', 404
    lang = lang or site.get('default_lang', 'en')
    if lang not in cp.get('langs', []):
        lang = cp['langs'][0]
    p = cp['pages'].get(lang)
    if not p:
        return 'Not found', 404
    base = f'/p/{slug}'
    alts = ''.join(f'<link rel="alternate" hreflang="{l}" href="{site["domain"]}{base}/{l}" />' for l in cp['langs'])
    record_hit(lang, request.path)
    return render_template_string(PAGE, site=site, p=p, alts=alts, lang=lang,
                                  base=base, is_content=True, switcher=cp['langs'], slug=slug)


TOPICS_TPL = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Topics — Free Traffic Control Center</title>
<meta name="robots" content="index,follow"/>
<meta name="description" content="Browse all topic guides."/>
<style>
:root{--bg:#0e0b07;--gold:#d9b25f;--cream:#f6efe2;--card:#1a140c}
*{box-sizing:border-box}body{margin:0;font-family:system-ui,sans-serif;background:var(--bg);color:var(--cream);line-height:1.6}
a{color:var(--gold)}.wrap{max-width:880px;margin:0 auto;padding:20px}
h1{color:var(--gold)}.grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fill,minmax(240px,1fr))}
.card{background:var(--card);border:1px solid #2a2114;border-radius:12px;padding:16px}
.card a{font-weight:700;text-decoration:none;font-size:1.05rem}
.tag{display:inline-block;font-size:.75rem;color:#b9a98a;border:1px solid #2a2114;border-radius:999px;padding:2px 8px;margin:4px 4px 0 0}
footer{padding:24px 0;color:#b9a98a;font-size:.85rem;text-align:center}
</style></head>
<body><div class="wrap">
<h1>📚 All Topic Guides</h1>
<p class="muted" style="color:#b9a98a">Free, SEO-optimized guides. Internal hub to help search engines crawl every page.</p>
<div class="grid">
{% for it in items %}<div class="card"><a href="{{ it.url }}">{{ it.title }}</a>
<div style="margin-top:8px">{% for l in it.langs %}<span class="tag">{{ l }}</span>{% endfor %}</div></div>{% endfor %}
</div>
<footer>© 2026 Kungfu Express · <a href="/">Home</a></footer>
</div></body></html>"""


@app.route('/topics')
def topics():
    site = load()
    cps = site.get('content_pages', {})
    items = []
    for slug, cp in cps.items():
        lg = cp['langs'][0]
        p = cp['pages'].get(lg, {})
        items.append({'slug': slug, 'langs': cp['langs'],
                      'title': p.get('title', slug), 'url': f'/p/{slug}/{lg}'})
    return render_template_string(TOPICS_TPL, site=site, items=items)


@app.route('/api/pages', methods=['GET', 'POST', 'DELETE'])
def api_pages():
    if not check_auth():
        return {'error': 'unauthorized'}, 401
    site = load()
    cps = site.setdefault('content_pages', {})
    if request.method == 'GET':
        return {'pages': [{'slug': s, 'langs': c['langs'],
                           'title': c['pages'].get(c['langs'][0], {}).get('title', s),
                           'url': f'/p/{s}/{c["langs"][0]}'} for s, c in cps.items()]}
    if request.method == 'DELETE':
        slug = request.args.get('slug', '')
        if slug in cps:
            del cps[slug]
            save(site)
            return {'ok': True, 'deleted': slug}
        return {'ok': False, 'error': 'not found'}, 404
    # POST: create/update a single page
    b = body()
    slug = (b.get('slug') or '').strip()
    if not slug:
        return {'error': 'slug required'}, 400
    langs = b.get('langs') or ['en']
    if isinstance(langs, str):
        langs = [langs]
    pages = b.get('pages', {})
    site['content_pages'][slug] = {'langs': langs, 'pages': pages}
    save(site)
    return {'ok': True, 'slug': slug, 'url': f'/p/{slug}/{langs[0]}'}


@app.route('/api/generate', methods=['POST'])
def api_generate():
    if not check_auth():
        return {'error': 'unauthorized'}, 401
    b = body()
    keywords = [k.strip() for k in (b.get('keywords') or '').split('\n') if k.strip()]
    if not keywords:
        return {'error': 'no keywords provided'}, 400
    langs = b.get('langs') or ['en', 'zh']
    if isinstance(langs, str):
        langs = [langs]
    site = load()
    main = site['pages'].get(site.get('default_lang', 'en'), {})
    cta_url = (b.get('cta_url') or main.get('cta_url') or '').strip()
    cta_label = (b.get('cta_label') or main.get('cta_label') or 'Learn more').strip()
    cps = site.setdefault('content_pages', {})
    created = []
    for kw in keywords[:50]:
        slug = slugify(kw)
        base_slug, i = slug, 2
        while slug in cps:
            slug = f'{base_slug}-{i}'; i += 1
        pages = {}
        for lg in langs:
            try:
                pages[lg] = generate_content(kw, lg, cta_url, cta_label)
            except Exception:
                pages[lg] = template_generate(kw, lg, cta_url, cta_label)
        cps[slug] = {'langs': langs, 'pages': pages}
        created.append({'slug': slug, 'keyword': kw, 'url': f'/p/{slug}/{langs[0]}'})
    save(site)
    return {'ok': True, 'created': created}


@app.route('/sitemap.xml')
def sitemap():
    site = load()
    dom = site['domain'].rstrip('/')
    langs = list(site['pages'].keys())

    def alts(base):
        b = (base or '').rstrip('/')
        out = f'    <xhtml:link rel="alternate" hreflang="x-default" href="{dom}{b}" />\n'
        for l in langs:
            out += f'    <xhtml:link rel="alternate" hreflang="{l}" href="{dom}{b}/{l}" />\n'
        return out

    today = datetime.date.today().isoformat()
    urls = [f'  <url>\n    <loc>{dom}/</loc>\n    <lastmod>{today}</lastmod>\n{alts("/")}  </url>']
    for l in langs:
        urls.append(f'  <url>\n    <loc>{dom}/{l}</loc>\n    <lastmod>{today}</lastmod>\n{alts("/")}  </url>')
    urls.append(f'  <url>\n    <loc>{dom}/topics</loc>\n    <lastmod>{today}</lastmod>\n  </url>')
    for slug, cp in site.get('content_pages', {}).items():
        base = f'/p/{slug}'
        cavg = '    <xhtml:link rel="alternate" hreflang="x-default" href="{dom}{base}/{cp["langs"][0]}" />\n'
        for l in cp['langs']:
            cavg += f'    <xhtml:link rel="alternate" hreflang="{l}" href="{dom}{base}/{l}" />\n'
        for l in cp['langs']:
            urls.append(f'  <url>\n    <loc>{dom}{base}/{l}</loc>\n    <lastmod>{today}</lastmod>\n{cavg}  </url>')
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n' \
          '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" ' \
          'xmlns:xhtml="http://www.w3.org/1999/xhtml">\n' + '\n'.join(urls) + '\n</urlset>'
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
    tips = []
    dom = site.get('domain', '').rstrip('/')
    if 'your-domain.com' in dom or dom in ('', 'https://your-domain.com'):
        tips.append('Set your real domain in the dashboard — canonical/hreflang/sitemap currently point to the placeholder.')
    for l, p in site['pages'].items():
        t = p.get('title', '')
        if len(t) < 30 or len(t) > 60:
            tips.append(f'[{l}] title length {len(t)} — aim 30-60 chars')
        d = p.get('description', '')
        if len(d) < 70 or len(d) > 160:
            tips.append(f'[{l}] description length {len(d)} — aim 70-160 chars')
        if not p.get('keywords'):
            tips.append(f'[{l}] add keywords')
        if len(p.get('sections', [])) < 3:
            tips.append(f'[{l}] add more content sections (>=3) for richer indexing')
    p = site['pages'].get(lang, {})
    return {'lang': lang, 'score': max(0, 100 - len(tips) * 12), 'tips': tips}


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
    save(body())
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
    init_stats()
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', '3000')))
