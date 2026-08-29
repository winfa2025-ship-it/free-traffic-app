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
- `/sitemap.xml`, `/robots.txt` — auto-generated for indexing
- `/dashboard` — edit SEO/content, SEO check, Search Console queries
- `/api/site` GET/POST — site config (data/site.json)
- `/api/seo-check?lang=en` — on-page SEO score + tips
- `/api/searchconsole` — top queries (28d) from Search Console

## Optional: Google Search Console read-only

1. In Google Cloud Console, enable **Search Console API**, create OAuth
   desktop credentials, download as `credentials.json` into this folder.
2. First call to `/api/searchconsole` uses those creds to read top queries.
   (The google-* libs are optional deps — install only if you want this.)

## Notes

- For global reach, add more languages in `data/site.json` (each becomes `/<lang>`).
- Host on any free/cheap host (Render, Railway, Fly, Cloudflare Pages + a small
  backend). The landing page itself can be static-exported.
