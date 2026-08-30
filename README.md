# Free Traffic Control Center

A white-hat tool to earn **free organic traffic** from Google / Yahoo for your
crowdfunding campaign. It manages an SEO-optimized landing page, auto-generates
`sitemap.xml` + `robots.txt`, runs on-page SEO checks, and (optionally) reads
real search queries from Google Search Console.

It does NOT buy traffic, run bots, scrape, or spam. Traffic comes from search
engines indexing quality content — for free.

## Run

```bash
pip install -r requirements.txt
cp .env.example .env
python app.py        # / = landing, /zh = Chinese, /dashboard = control center
```

## How free traffic works (the honest version)

1. Edit your page SEO/content in `/dashboard` (title 30–60, description 70–160,
   real keywords people search).
2. Submit `/sitemap.xml` in **Google Search Console** and **Bing Webmaster Tools**.
3. Search engines index the page; people searching your keywords find it → free
   visitors. No per-click cost.
4. Connect Search Console (see below) to see which queries bring impressions &
   clicks, then improve those pages.

## Endpoints

- `/` and `/<lang>` — localized landing pages (hreflang alternates)
- `/p/<slug>` and `/p/<slug>/<lang>` — auto-generated SEO **content pages** (one per keyword)
- `/topics` — internal hub linking every content page (helps crawl & internal linking)
- `/sitemap.xml`, `/robots.txt` — auto-generated, now including all content pages
- `/dashboard` — edit SEO/content, **generate content pages from keywords**, SEO check, Search Console queries, **search-traffic analytics**
- `/api/site` GET/POST — site config (data/site.json)
- `/api/pages` GET/POST/DELETE — list / create / delete content pages
- `/api/generate` POST — bulk-create SEO pages from a list of keywords
- `/api/seo-check?lang=en` — on-page SEO score + tips
- `/api/searchconsole` — top queries (28d) from Search Console
- `/api/stats-view` — traffic + **search-engine source breakdown, top landing pages, captured queries**

## Auto-generating SEO pages (the 推流 engine)

1. Open `/dashboard` → **Content Pages** card.
2. Paste one keyword/topic per line, pick languages (en/zh default), optional CTA.
3. Click **Generate** — the app writes an SEO-optimized landing page per language, links
   them together and into `/topics`, and adds them to `/sitemap.xml`. More indexed pages =
   more ways for search engines to send free traffic.
4. Connect Google Search Console (below) to see which queries bring impressions/clicks.

Generation uses an LLM when `OPENAI_API_KEY` is set (set `OPENAI_MODEL`, default
`gpt-4o-mini`); otherwise it falls back to a built-in SEO template so it always works offline.

## Optional: Google Search Console read-only

1. In Google Cloud Console, enable **Search Console API**, create OAuth
   desktop credentials, download as `credentials.json` into this folder.
2. First call to `/api/searchconsole` uses those creds to read top queries.
   (The google-* libs are optional deps — install only if you want this.)

## Notes

- For global reach, add more languages in `data/site.json` (each becomes `/<lang>`).
- Host on any free/cheap host (Render, Railway, Fly, Cloudflare Pages + a small
  backend). The landing page itself can be static-exported.
