#!/usr/bin/env python3
"""Generate one crawlable article page per story with static social metadata."""
from __future__ import annotations

import datetime as dt
import html
import json
import os
import re
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
NEWS_PATH = ROOT / "data" / "news.json"
TEMPLATE_PATH = ROOT / "article.html"
SITE_URL = os.environ.get("SITE_URL", "https://nusantaranewsidn.com").rstrip("/")
SITEMAP_PATH = ROOT / "sitemap.xml"

def attr(value: str) -> str:
    return html.escape(str(value or ""), quote=True)

def share_image(url: str) -> str:
    """Return a valid image URL for social previews, preserving uploaded/source photos."""
    if not url or not url.startswith("https://"):
        return SITE_URL + "/assets/nusantaranews-share.svg"
    try:
        parts = urlsplit(url)
        if "images.unsplash.com" in parts.netloc:
            query = parse_qs(parts.query)
            query.update({"fit": ["crop"], "w": ["1200"], "h": ["630"], "q": ["85"]})
            return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query, doseq=True), ""))
    except Exception:
        pass
    return url

def fetch_supabase_articles() -> list[dict]:
    """Fetch only rows allowed by Supabase public SELECT/RLS for published articles."""
    config_path = ROOT / "admin" / "config.js"
    if not config_path.exists():
        print("[info] Supabase config not found; generating static feed articles only.")
        return []

    config = config_path.read_text(encoding="utf-8")
    url_match = re.search(r'url\s*:\s*["\']([^"\']+)["\']', config)
    key_match = re.search(r'anonKey\s*:\s*["\']([^"\']+)["\']', config)
    if not url_match or not key_match:
        print("[info] Supabase public config incomplete; generating static feed articles only.")
        return []

    project_url = url_match.group(1).rstrip("/")
    publishable_key = key_match.group(1)
    endpoint = project_url + "/rest/v1/articles?select=*&status=eq.published&order=published_at.desc"
    request = Request(endpoint, headers={
        "apikey": publishable_key,
        "Authorization": "Bearer " + publishable_key,
        "Accept": "application/json",
        "User-Agent": "NusantaraNewsSocialPreviewBuilder/1.0",
    })
    try:
        with urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, list):
            raise ValueError("Supabase did not return a list")
    except Exception as exc:
        print(f"[warn] Supabase article fetch failed; static feed pages will still be generated: {exc}")
        return []

    articles = []
    for row in payload:
        slug = str(row.get("slug") or "").strip()
        if not slug or row.get("status") != "published":
            continue
        stamp = str(row.get("published_at") or row.get("created_at") or "")
        articles.append({
            "slug": slug,
            "title": row.get("title") or "NusantaraNews",
            "category": row.get("category") or "Nasional",
            "excerpt": row.get("excerpt") or row.get("summary") or row.get("description") or "",
            "body": row.get("body") or row.get("content") or row.get("summary") or "",
            "author": row.get("author_name") or row.get("author") or "Redaksi NusantaraNews",
            "date": stamp[:10],
            "time": "",
            "image": row.get("image_url") or row.get("image") or "",
            "caption": row.get("image_caption") or row.get("caption") or "",
            "sourceName": row.get("source_name") or row.get("sourceName") or "",
            "sourceUrl": row.get("source_url") or row.get("sourceUrl") or "",
            "status": "Published",
            "sourceSystem": "supabase",
        })
    print(f"Fetched {len(articles)} published Supabase articles for share previews.")
    return articles


def make_page(template: str, article: dict) -> str:
    slug = article.get("slug", "")
    title = article.get("title", "NusantaraNews")
    description = article.get("excerpt") or title
    image = share_image(article.get("image", ""))
    canonical = f"{SITE_URL}/artikel/{slug}/"
    slug_meta = f'<meta name="nn-article-slug" content="{attr(slug)}">\n<meta name="nn-site-root" content="{SITE_URL}/">\n<link rel="canonical" href="{attr(canonical)}">'
    # Generated article pages are nested two directories below the site root.
    template = template.replace('<script src="./admin/config.js"></script>', '<script src="../../admin/config.js"></script>')
    if '<meta name="nn-article-slug"' not in template:
        template = template.replace('<meta charset="utf-8">', '<meta charset="utf-8">\n' + slug_meta, 1)
    template = re.sub(r'<meta name="description" content="[^"]*">', f'<meta name="description" content="{attr(description)}">', template, count=1)
    template = re.sub(r'<meta property="og:title" content="[^"]*">', f'<meta property="og:title" content="{attr(title)}">', template, count=1)
    template = re.sub(r'<meta property="og:description" content="[^"]*">', f'<meta property="og:description" content="{attr(description)}">', template, count=1)
    template = re.sub(r'<meta property="og:url" content="[^"]*">', f'<meta property="og:url" content="{attr(canonical)}">', template, count=1)
    template = re.sub(r'<meta property="og:image" content="[^"]*">', f'<meta property="og:image" content="{attr(image)}">', template, count=1)
    template = re.sub(r'<meta property="og:image:alt" content="[^"]*">', f'<meta property="og:image:alt" content="{attr(title)}">', template, count=1)
    template = re.sub(r'<meta property="og:image:width" content="[^"]*">', '<meta property="og:image:width" content="1200">', template, count=1)
    template = re.sub(r'<meta property="og:image:height" content="[^"]*">', '<meta property="og:image:height" content="630">', template, count=1)
    template = re.sub(r'<meta name="twitter:title" content="[^"]*">', f'<meta name="twitter:title" content="{attr(title)}">', template, count=1)
    template = re.sub(r'<meta name="twitter:description" content="[^"]*">', f'<meta name="twitter:description" content="{attr(description)}">', template, count=1)
    template = re.sub(r'<meta name="twitter:image" content="[^"]*">', f'<meta name="twitter:image" content="{attr(image)}">', template, count=1)
    template = re.sub(r'<title>.*?</title>', f'<title>{html.escape(title)} | NusantaraNews</title>', template, count=1)
    template = template.replace('href="./?category=', 'href="../../?category=')
    template = template.replace('href="./"', 'href="../../"')
    template = template.replace('src="assets/', 'src="../../assets/')
    template = template.replace('href="assets/', 'href="../../assets/')
    template = template.replace('fetch("./data/news.json"', 'fetch("../../data/news.json"')
    return template

def main() -> int:
    feed_rows = json.loads(NEWS_PATH.read_text(encoding="utf-8"))
    supabase_rows = fetch_supabase_articles()
    # Prefer the live Supabase row when a slug appears in both sources.
    by_slug = {
        str(article.get("slug")): article
        for article in feed_rows
        if article.get("status") == "Published" and article.get("slug")
    }
    by_slug.update({str(article["slug"]): article for article in supabase_rows})
    rows = list(by_slug.values())
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    urls = [f"{SITE_URL}/"]
    generated = 0
    for article in rows:
        if article.get("status") != "Published" or not article.get("slug"):
            continue
        folder = ROOT / "artikel" / article["slug"]
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "index.html").write_text(make_page(template, article), encoding="utf-8")
        urls.append(f"{SITE_URL}/artikel/{article['slug']}/")
        generated += 1
    today = dt.date.today().isoformat()
    latest_date = max((str(a.get("date", "")) for a in rows if a.get("status") == "Published" and a.get("date")), default=today)
    url_entries = [(f"{SITE_URL}/", latest_date)]
    url_entries.extend(
        (f"{SITE_URL}/artikel/{a['slug']}/", str(a.get("date") or latest_date))
        for a in rows if a.get("status") == "Published" and a.get("slug")
    )
    url_xml = "\n".join(
        f"  <url><loc>{html.escape(url)}</loc><lastmod>{lastmod}</lastmod><changefreq>{'daily' if url == SITE_URL + '/' else 'weekly'}</changefreq><priority>{'1.0' if url == SITE_URL + '/' else '0.8'}</priority></url>"
        for url, lastmod in url_entries
    )
    SITEMAP_PATH.write_text('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + url_xml + '\n</urlset>\n', encoding="utf-8")
    print(f"Generated {generated} pages; refreshed sitemap.xml.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
