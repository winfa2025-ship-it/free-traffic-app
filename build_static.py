import json, os, re
from jinja2 import Environment, FileSystemLoader

DOM = "https://winfa2025-ship-it.github.io/free-traffic-app"
env = Environment(loader=FileSystemLoader('templates'))
_EMOJI_RE = re.compile(r'[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u2190-\u21FF\u2300-\u23FF]')
env.filters['noemoji'] = lambda s: _EMOJI_RE.sub('', str(s)).strip()
t = env.from_string(open('templates/page.html', encoding='utf-8').read())
site = json.load(open('data/site.json', encoding='utf-8'))
site['domain'] = DOM

for lang, p in site['pages'].items():
    alts = ''.join(f'<link rel="alternate" hreflang="{l}" href="{DOM}/{l}" />' for l in site['pages'])
    html = t.render(site=site, p=p, alts=alts, lang=lang)
    if lang == site['default_lang']:
        open('index.html', 'w', encoding='utf-8').write(html)
    else:
        os.makedirs(lang, exist_ok=True)
        open(f'{lang}/index.html', 'w', encoding='utf-8').write(html)

urls = [f'<url><loc>{DOM}/</loc></url>'] + [f'<url><loc>{DOM}/{l}</loc></url>' for l in site['pages']]
open('sitemap.xml', 'w', encoding='utf-8').write(
    '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    + '\n'.join(urls) + '\n</urlset>')
open('robots.txt', 'w', encoding='utf-8').write(f"User-agent: *\nAllow: /\nSitemap: {DOM}/sitemap.xml\n")
print('static site built')
