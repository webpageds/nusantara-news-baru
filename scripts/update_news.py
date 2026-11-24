#!/usr/bin/env python3
"""Import recent public headlines from Google News RSS while keeping source links."""
from __future__ import annotations

import datetime as dt
import email.utils
from html.parser import HTMLParser
import html
import json
import re
import time
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
NEWS_PATH = ROOT / "data" / "news.json"
TZ = ZoneInfo("Asia/Jakarta")
MAX_NEW_PER_RUN = 5
MAX_REPAIR_PER_RUN = 25
FEEDS = {
    "Nasional": "berita nasional Indonesia when:1d",
    "Daerah": "berita daerah Indonesia when:1d",
    "Ekonomi": "ekonomi bisnis saham Indonesia when:1d",
    "Internasional": "berita internasional dunia when:1d",
    "Politik": "politik pemerintahan Indonesia when:1d",
    "Teknologi": "teknologi digital Indonesia when:1d",
    "Olahraga": "olahraga Indonesia when:1d",
    "Pendidikan": "pendidikan sekolah kampus Indonesia when:1d",
    "Sosial": "sosial masyarakat bantuan Indonesia when:1d",
    "Lifestyle": "gaya hidup budaya kesehatan Indonesia when:1d",
}
# Editorial fallback illustrations by category; never rotate unrelated images.
FALLBACK_IMAGES = {
    "Nasional": "https://images.unsplash.com/photo-1529107386315-e1a2ed48a620?auto=format&fit=crop&w=1400&q=85",
    "Daerah": "https://images.unsplash.com/photo-1519501025264-65ba15a82390?auto=format&fit=crop&w=1400&q=85",
    "Ekonomi": "https://images.unsplash.com/photo-1611974789855-9c2a0a7236a3?auto=format&fit=crop&w=1400&q=85",
    "Internasional": "https://images.unsplash.com/photo-1451187580459-43490279c0fa?auto=format&fit=crop&w=1400&q=85",
    "Politik": "https://images.unsplash.com/photo-1529107386315-e1a2ed48a620?auto=format&fit=crop&w=1400&q=85",
    "Teknologi": "https://images.unsplash.com/photo-1518770660439-4636190af475?auto=format&fit=crop&w=1400&q=85",
    "Olahraga": "https://images.unsplash.com/photo-1464359982907-8f8fb5a8a1e1?auto=format&fit=crop&w=1400&q=85",
    "Pendidikan": "https://images.unsplash.com/photo-1509062522246-3755977927d7?auto=format&fit=crop&w=1400&q=85",
    "Sosial": "https://images.unsplash.com/photo-1593113598332-cd288d649433?auto=format&fit=crop&w=1400&q=85",
    "Lifestyle": "https://images.unsplash.com/photo-1499209974431-9dddcece7f88?auto=format&fit=crop&w=1400&q=85",
}

def choose_fallback_image(category: str) -> str:
    return FALLBACK_IMAGES.get(category, FALLBACK_IMAGES["Nasional"])

def clean_text(value: str) -> str:
    value = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", value or "", flags=re.I | re.S)
    value = re.sub(r"<img\b[^>]*>", " ", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()

def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return value[:92].strip("-") or "berita-terbaru"

def parse_date(value: str) -> dt.datetime:
    try:
        parsed = email.utils.parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(TZ)
    except Exception:
        return dt.datetime.now(TZ)

class _MetaImageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.image = None

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "meta":
            return
        values = {str(k).lower(): str(v) for k, v in attrs if k and v}
        key = (values.get("property") or values.get("name") or "").lower()
        if key in ("og:image", "og:image:url", "twitter:image", "twitter:image:src"):
            candidate = values.get("content", "").strip()
            if candidate.startswith(("https://", "http://")):
                self.image = candidate


def publisher_page_image(url: str) -> str | None:
    """Resolve a news link and read its publisher-provided Open Graph image."""
    if not url.startswith(("https://", "http://")):
        return None
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; NusantaraNewsBot/1.0)",
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        with urllib.request.urlopen(req, timeout=12) as response:
            final_url = response.geturl()
            content_type = response.headers.get("Content-Type", "")
            if "html" not in content_type.lower():
                return None
            html_bytes = response.read(1_500_000)
        parser = _MetaImageParser()
        parser.feed(html_bytes.decode("utf-8", errors="replace"))
        if parser.image:
            image_url = urllib.parse.urljoin(final_url, parser.image)
            if image_url.startswith(("https://", "http://")):
                return image_url
    except Exception as exc:
        print(f"[warn] cannot read publisher image from {url}: {exc}")
    return None


def item_image(item: ET.Element, article_url: str = "") -> str | None:
    """Prefer publisher RSS image metadata, then publisher page og:image."""
    for elem in item.iter():
        tag = elem.tag.lower()
        if tag.endswith("}content") or tag.endswith("}thumbnail") or tag.endswith("enclosure"):
            candidate = (elem.attrib.get("url") or elem.attrib.get("href") or "").strip()
            if candidate.startswith(("https://", "http://")):
                return candidate
    desc = html.unescape(item.findtext("description") or "")
    match = re.search(r"""<img\b[^>]+(?:src|data-src)=["']([^"']+)["']""", desc, re.I)
    if match:
        candidate = html.unescape(match.group(1)).strip()
        if candidate.startswith(("https://", "http://")):
            return candidate
    return publisher_page_image(article_url) if article_url else None

def request_feed(query: str) -> list[ET.Element]:
    params = urllib.parse.urlencode({"q": query, "hl": "id", "gl": "ID", "ceid": "ID:id"})
    url = "https://news.google.com/rss/search?" + params
    req = urllib.request.Request(url, headers={"User-Agent": "NusantaraNewsFeedBot/1.0"})
    with urllib.request.urlopen(req, timeout=20) as response:
        xml_bytes = response.read()
    root = ET.fromstring(xml_bytes)
    channel = root.find("channel")
    return list(channel.findall("item")) if channel is not None else []

def main() -> int:
    try:
        raw = NEWS_PATH.read_text(encoding="utf-8").strip()
        rows = json.loads(raw) if raw else []
        if not isinstance(rows, list):
            raise ValueError("news.json must contain a JSON array")
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"[error] Cannot safely read existing news.json: {exc}")
        return 1
    known_titles = {re.sub(r"\W+", " ", str(a.get("title", "")).lower()).strip() for a in rows}
    known_slugs = {a.get("slug") for a in rows}
    candidates: list[dict] = []
    now = dt.datetime.now(TZ)

    # Repair old automatically imported cards that still use generic stock photos.
    repaired = 0
    for article in rows:
        if repaired >= MAX_REPAIR_PER_RUN:
            break
        if not article.get("autoImported"):
            continue
        current_image = str(article.get("image") or "")
        if "images.unsplash.com" not in current_image and current_image:
            continue
        source_url = str(article.get("sourceUrl") or "")
        if not source_url:
            continue
        actual_image = publisher_page_image(source_url)
        if actual_image:
            article["image"] = actual_image
            article["caption"] = f"Foto utama dari penerbit {article.get('sourceName', 'sumber berita')}; periksa kredit pada artikel asli."
            repaired += 1
    if repaired:
        print(f"Repaired {repaired} existing article image(s).")

    for category, query in FEEDS.items():
        try:
            items = request_feed(query)
        except Exception as exc:
            print(f"[warn] feed {category} unavailable: {exc}")
            continue
        for item in items[:5]:
            raw_title = clean_text(item.findtext("title") or "")
            source_elem = item.find("source")
            source_name = clean_text(source_elem.text or "") if source_elem is not None else "Google News RSS"
            if source_name and raw_title.endswith(" - " + source_name):
                raw_title = raw_title[:-(len(source_name) + 3)].strip()
            link = (item.findtext("link") or "").strip()
            if not raw_title or not link.startswith("https://"):
                continue
            normalized = re.sub(r"\W+", " ", raw_title.lower()).strip()
            if normalized in known_titles:
                continue
            published = parse_date(item.findtext("pubDate") or "")
            if published > now + dt.timedelta(minutes=10) or published < now - dt.timedelta(hours=30):
                continue
            description = clean_text(item.findtext("description") or "")
            if description.lower().startswith(raw_title.lower()):
                description = description[len(raw_title):].strip(" -:|")
            if len(description) < 45:
                excerpt = f"Berita terbaru kategori {category} dari {source_name}. Buka tautan sumber untuk membaca laporan lengkap dan konteksnya."
            else:
                excerpt = description[:270].rsplit(" ", 1)[0] + ("…" if len(description) > 270 else "")
            slug_base = slugify(raw_title)
            slug = slug_base
            suffix = 2
            while slug in known_slugs:
                slug = f"{slug_base}-{suffix}"
                suffix += 1
            known_titles.add(normalized)
            known_slugs.add(slug)
            image = item_image(item, link)
            caption = f"Ilustrasi kategori {category}; foto utama dari penerbit tidak tersedia." if not image else f"Foto dari penerbit {source_name}; periksa kredit pada artikel asli."
            fallback_image = choose_fallback_image(category) if image is None else None
            candidates.append({
                "slug": slug,
                "title": raw_title[:140],
                "category": category,
                "excerpt": excerpt,
                "author": "Feed Redaksi",
                "date": published.strftime("%Y-%m-%d"),
                "time": published.strftime("%H.%M WIB"),
                "image": image or fallback_image,
                "caption": caption,
                "body": (description if len(description) >= 45 else excerpt) + "\n\nSorotan ini diimpor otomatis dari feed berita publik dan belum melalui verifikasi redaksional manual. Buka tautan sumber untuk laporan lengkap, konteks, dan pembaruan terbaru.",
                "sourceName": source_name or "Google News RSS",
                "sourceUrl": link,
                "status": "Published",
                "autoImported": True
            })
        time.sleep(0.12)

    candidates.sort(key=lambda a: (a["date"], a["time"]), reverse=True)
    additions = candidates[:MAX_NEW_PER_RUN]
    if not additions and not repaired:
        print("No new headlines or image repairs found; leaving news.json unchanged.")
        return 0
    existing = {a.get("slug") for a in rows}
    additions = [a for a in additions if a.get("slug") not in existing]
    rows = additions + rows
    NEWS_PATH.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Imported {len(additions)} headline(s), repaired {repaired} image(s); total articles: {len(rows)}.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
