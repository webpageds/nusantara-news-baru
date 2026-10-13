#!/usr/bin/env python3
"""Import recent public headlines from Google News RSS while keeping source links."""
from __future__ import annotations

import datetime as dt
import email.utils
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
FALLBACK_IMAGES = [
    "https://images.unsplash.com/photo-1593113598332-cd288d649433?auto=format&fit=crop&w=1400&q=85",
    "https://images.unsplash.com/photo-1516280440614-37939bbacd81?auto=format&fit=crop&w=1400&q=85",
    "https://images.unsplash.com/photo-1517649763962-0c623066013b?auto=format&fit=crop&w=1400&q=85",
    "https://images.unsplash.com/photo-1611974789855-9c2a0a7236a3?auto=format&fit=crop&w=1400&q=85",
    "https://images.unsplash.com/photo-1509062522246-3755977927d7?auto=format&fit=crop&w=1400&q=85",
    "https://images.unsplash.com/photo-1529107386315-e1a2ed48a620?auto=format&fit=crop&w=1400&q=85",
    "https://images.unsplash.com/photo-1451187580459-43490279c0fa?auto=format&fit=crop&w=1400&q=85",
    "https://images.unsplash.com/photo-1511497584788-876760111969?auto=format&fit=crop&w=1400&q=85",
    "https://images.unsplash.com/photo-1529101091764-c3526daf38fe?auto=format&fit=crop&w=1400&q=85",
    "https://images.unsplash.com/photo-1436491865332-7a61a109cc05?auto=format&fit=crop&w=1400&q=85",
    "https://images.unsplash.com/photo-1510511459019-5dead6b5f1b9?auto=format&fit=crop&w=1400&q=85",
    "https://images.unsplash.com/photo-1556742049-0cfed4f6a45d?auto=format&fit=crop&w=1400&q=85",
    "https://images.unsplash.com/photo-1503676260728-1c00da094a0b?auto=format&fit=crop&w=1400&q=85",
    "https://images.unsplash.com/photo-1441974231531-c6227db76b6e?auto=format&fit=crop&w=1400&q=85",
    "https://images.unsplash.com/photo-1538805060514-97d9cc17730c?auto=format&fit=crop&w=1400&q=85",
    "https://images.unsplash.com/photo-1537996194471-e657df975ab4?auto=format&fit=crop&w=1400&q=85",
    "https://images.unsplash.com/photo-1529390079861-591de354faf5?auto=format&fit=crop&w=1400&q=85",
    "https://images.unsplash.com/photo-1427504494785-3a9ca7044f45?auto=format&fit=crop&w=1400&q=85",
    "https://images.unsplash.com/photo-1566127992631-137a642a90f4?auto=format&fit=crop&w=1400&q=85",
    "https://images.unsplash.com/photo-1464822759023-fed622ff2c3b?auto=format&fit=crop&w=1400&q=85",
    "https://images.unsplash.com/photo-1521791136064-7986c2920216?auto=format&fit=crop&w=1400&q=85",
    "https://images.unsplash.com/photo-1473448912268-2022ce9509d8?auto=format&fit=crop&w=1400&q=85",
    "https://images.unsplash.com/photo-1497366754035-f200968a6e72?auto=format&fit=crop&w=1400&q=85",
    "https://images.unsplash.com/photo-1473341304170-971dccb5ac1e?auto=format&fit=crop&w=1400&q=85",
    "https://images.unsplash.com/photo-1516467508483-a7212febe31a?auto=format&fit=crop&w=1400&q=85",
    "https://images.unsplash.com/photo-1460925895917-afdab827c52f?auto=format&fit=crop&w=1400&q=85",
    "https://images.unsplash.com/photo-1448375240586-882707db888b?auto=format&fit=crop&w=1400&q=85",
]

def choose_fallback_image(slug: str, used_images: set[str]) -> str:
    start = sum(slug.encode("utf-8")) % len(FALLBACK_IMAGES)
    for offset in range(len(FALLBACK_IMAGES)):
        candidate = FALLBACK_IMAGES[(start + offset) % len(FALLBACK_IMAGES)]
        if candidate not in used_images:
            return candidate
    return FALLBACK_IMAGES[start]

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

def item_image(item: ET.Element) -> str | None:
    for elem in item.iter():
        tag = elem.tag.lower()
        if tag.endswith("}content") or tag.endswith("}thumbnail") or tag.endswith("enclosure"):
            url = elem.attrib.get("url", "")
            if url.startswith("https://") and re.search(r"\.(jpg|jpeg|png|webp)(\?|$)", url, re.I):
                return url
    desc = item.findtext("description") or ""
    match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', html.unescape(desc), re.I)
    if match and match.group(1).startswith("https://"):
        return match.group(1)
    return None

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
    rows = json.loads(NEWS_PATH.read_text(encoding="utf-8"))
    known_titles = {re.sub(r"\W+", " ", str(a.get("title", "")).lower()).strip() for a in rows}
    known_slugs = {a.get("slug") for a in rows}
    candidates: list[dict] = []
    used_fallback_images: set[str] = set()
    now = dt.datetime.now(TZ)

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
            image = item_image(item)
            caption = f"Gambar ilustrasi kategori {category}; bukan foto langsung peristiwa." if not image else "Gambar dari feed sumber; periksa keterangan sumber untuk konteks foto."
            fallback_image = choose_fallback_image(slug, used_fallback_images) if image is None else None
            if fallback_image:
                used_fallback_images.add(fallback_image)
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
    if not additions:
        print("No new headlines found; leaving news.json unchanged.")
        return 0
    existing = {a.get("slug") for a in rows}
    additions = [a for a in additions if a.get("slug") not in existing]
    rows = additions + rows
    NEWS_PATH.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Imported {len(additions)} headline(s); total articles: {len(rows)}.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
