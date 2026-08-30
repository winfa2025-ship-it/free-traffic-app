import json, os, re
from jinja2 import Environment, FileSystemLoader

OUT = os.environ.get('STATIC_OUT', 'public')
env = Environment(loader=FileSystemLoader('templates'))
_EMOJI_RE = re.compile(r'[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u2190-\u21FF\u2300-\u23FF]')
env.filters['noemoji'] = lambda s: _EMOJI_RE.sub('', str(s)).strip()
t = env.from_string(open('templates/page_static.html', encoding='utf-8').read())

site = json.load(open('data/site.json', encoding='utf-8'))

# Domain override: allow building for a static host (e.g. GitHub Pages) without
# touching the live data. If unset, falls back to data/site.json's domain.
DOM = (os.environ.get('SITE_DOMAIN') or site['domain']).rstrip('/')
site = dict(site, domain=DOM)

def write(path, content):
    full = os.path.join(OUT, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, 'w', encoding='utf-8') as f:
        f.write(content)

def rel_prefix(parts):
    # parts: components below OUT root, e.g. [] -> '', ['en'] -> '../',
    # ['p','slug','en'] -> '../../../'
    return '../' * len(parts)

LANG_NAMES = {'en':'EN','zh':'中文','ja':'日本語','ko':'한국어','es':'ES','ar':'العربية',
              'ru':'RU','de':'DE','fr':'FR','pt':'PT','it':'IT','hi':'HI','vi':'VI',
              'id':'ID','th':'TH','tr':'TR'}

def build_page(p, lang, parts, alts, is_content=False, slug='', switcher=None):
    rel = rel_prefix(parts)
    if is_content:
        # content page lives at p/<slug>/<lang>/ ; sibling langs & other pages
        lang_prefix = '../'
        pages_prefix = '../../'
        base_path = f'/p/{slug}'
    else:
        # landing lang pages live at root level
        lang_prefix = rel
        pages_prefix = ''
        base_path = '/'
    html = t.render(site=site, p=p, alts=alts, lang=lang, base=base_path,
                    is_content=is_content, slug=slug, switcher=switcher, rel=rel,
                    lang_prefix=lang_prefix, pages_prefix=pages_prefix)
    write('/'.join(parts + ['index.html']), html)

# 1) Main landing pages (all languages) + default at root.
langs = list(site['pages'].keys())
for lang, p in site['pages'].items():
    alts = ''.join(f'<link rel="alternate" hreflang="{l}" href="{DOM}/{l}" />' for l in langs)
    if lang == site.get('default_lang', 'en'):
        build_page(p, lang, [], alts, switcher=langs)
    build_page(p, lang, [lang], alts, switcher=langs)

# 2) Content (SEO) pages under /p/<slug>/<lang>/ and /p/<slug>/ for default lang.
for slug, cp in site.get('content_pages', {}).items():
    cplangs = cp['langs']
    for l in cplangs:
        p = cp['pages'].get(l)
        if not p:
            continue
        alts = ''.join(f'<link rel="alternate" hreflang="{l2}" href="{DOM}/p/{slug}/{l2}" />' for l2 in cplangs)
        parts = ['p', slug, l]
        build_page(p, l, parts, alts, is_content=True, slug=slug, switcher=cplangs)

# 3) /topics hub.
TOPICS_TPL = open('templates/topics.html', encoding='utf-8').read()
items = []
for slug, cp in site.get('content_pages', {}).items():
    lg = cp['langs'][0]
    p = cp['pages'].get(lg, {})
    items.append({'slug': slug, 'langs': cp['langs'],
                  'title': p.get('title', slug), 'url': f'p/{slug}/{lg}/'})
write('topics/index.html', env.from_string(TOPICS_TPL).render(items=items, rel='../'))

# 4) sitemap.xml + robots.txt (at OUT root).
urls = [f'<url><loc>{DOM}/</loc></url>'] + [f'<url><loc>{DOM}/{l}</loc></url>' for l in langs]
urls.append(f'<url><loc>{DOM}/topics</loc></url>')
for slug, cp in site.get('content_pages', {}).items():
    for l in cp['langs']:
        urls.append(f'<url><loc>{DOM}/p/{slug}/{l}</loc></url>')
write('sitemap.xml',
      '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
      + '\n'.join(urls) + '\n</urlset>')
write('robots.txt', f"User-agent: *\nAllow: /\nSitemap: {DOM}/sitemap.xml\n")

# 5) Static assets (og image, uploads, etc) — preserve subfolders.
if os.path.isdir('static'):
    for root, _, files in os.walk('static'):
        rel = os.path.relpath(root, 'static')
        for fn in files:
            src = os.path.join(root, fn)
            dst = os.path.join(OUT, 'static', rel, fn)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            open(dst, 'wb').write(open(src, 'rb').read())

print(f'static site built -> {OUT}')
