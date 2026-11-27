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
# Never use generic stock photos as if they documented an individual article.
FALLBACK_IMAGES = {}

def choose_fallback_image(category: str) -> str:
    return ""

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
    """Collect publisher-declared article images in preferred metadata order."""
    PRIORITY = {
        "og:image": 0,
        "og:image:url": 1,
        "og:image:secure_url": 2,
        "twitter:image": 3,
        "twitter:image:src": 4,
        "image": 5,
    }

    def __init__(self):
        super().__init__()
        self.images: list[tuple[int, int, str]] = []
        self._sequence = 0

    def handle_starttag(self, tag, attrs):
        values = {str(k).lower(): str(v) for k, v in attrs if k and v}
        tag = tag.lower()
        candidate = ""

        if tag == "meta":
            key = (values.get("property") or values.get("name") or values.get("itemprop") or "").lower()
            if key in self.PRIORITY:
                candidate = values.get("content", "").strip()
                priority = self.PRIORITY[key]
            else:
                return
        elif tag == "link" and "image_src" in (values.get("rel") or "").lower().split():
            candidate = values.get("href", "").strip()
            priority = 6
        else:
            return

        if candidate and not candidate.lower().startswith(("data:", "javascript:")):
            self.images.append((priority, self._sequence, candidate))
            self._sequence += 1

    def ordered_images(self):
        seen = set()
        for _, _, candidate in sorted(self.images):
            if candidate not in seen:
                seen.add(candidate)
                yield candidate


def resolve_publisher_url(url: str) -> str:
    """Resolve Google News RSS links to the publisher article URL."""
    if not url.startswith(("https://", "http://")):
        return ""
    try:
        parts = urllib.parse.urlsplit(url)
        if parts.netloc.lower().endswith("news.google.com"):
            # Google News article links sometimes encode the publisher URL in
            # the RSS wrapper; otherwise, follow the redirect normally.
            query = urllib.parse.parse_qs(parts.query)
            for key in ("url", "u", "q"):
                value = (query.get(key) or [""])[0]
                if value.startswith(("https://", "http://")) and "google." not in urllib.parse.urlsplit(value).netloc.lower():
                    return value
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; NusantaraNewsBot/1.0)"})
        with urllib.request.urlopen(req, timeout=15) as response:
            final_url = response.geturl()
            html_bytes = response.read(500000)
        host = urllib.parse.urlsplit(final_url).netloc.lower()
        if not host.endswith(("news.google.com", "google.com")):
            return final_url
        # Some Google News wrappers expose the original article link in HTML.
        text = html_bytes.decode("utf-8", errors="replace")
        patterns = [
            r'https?://[^"\\\\ ]+',
            r'url=([^&"\\\\ ]+)',
        ]
        for pattern in patterns:
            for match in re.findall(pattern, text):
                candidate = urllib.parse.unquote(html.unescape(match)).replace("\\\\u003d", "=")
                if candidate.startswith(("https://", "http://")):
                    c_host = urllib.parse.urlsplit(candidate).netloc.lower()
                    if c_host and not c_host.endswith(("google.com", "googleusercontent.com", "gstatic.com")):
                        return candidate
    except Exception as exc:
        print(f"[warn] cannot resolve publisher URL {url}: {exc}")
    return ""


def valid_article_image(url: str) -> bool:
    """Accept direct publisher images, including extensionless Blogger CDN URLs.

    Do not accept Google's generic search/news thumbnails: those can be shared
    across unrelated stories. Blogger's dedicated image host is an exception
    because it serves the original uploaded image bytes.
    """
    try:
        raw = html.unescape(str(url or "")).strip()
        if raw.startswith("//"):
            raw = "https:" + raw
        elif raw.lower().startswith("http://"):
            raw = "https://" + raw[7:]
        parts = urllib.parse.urlsplit(raw)
        host, path = (parts.hostname or "").lower(), parts.path.lower()
        if parts.scheme != "https" or not host or not path:
            return False

        blogger_host = (
            host == "blogger.googleusercontent.com"
            or host == "blogspot.com"
            or host.endswith(".blogspot.com")
        )
        # Do not broadly allow googleusercontent.com: only Blogger's dedicated
        # CDN is considered a trustworthy original-image host.
        if (host.endswith(("google.com", "gstatic.com", "googleusercontent.com")) and not blogger_host):
            return False
        if host.endswith(("news.google.com", "google.co", "googleusercontent.com")) and not blogger_host:
            return False
        if any(token in path for token in (
            "logo", "favicon", "avatar", "placeholder", "no-image",
            "no_image", "default-image", "default_image", "sprite"
        )):
            return False
        # Reject clearly tiny thumbnail variants, but preserve full-size Blogger
        # paths such as /s1600/ and publisher URLs with w=1200.
        size_match = re.search(r"(?:[?&](?:w|width|sz)=|[=/]w)(\d{1,4})(?:[&#/]|$)", raw.lower())
        if size_match and int(size_match.group(1)) < 200:
            return False
        if re.search(r"/(?:s|w|h)\d{1,3}(?:-[a-z]+)?/", path) and not blogger_host:
            return False
        return True
    except Exception:
        return False

def publisher_page_image(url: str) -> str | None:
    """Read the publisher article's image metadata, rejecting generic graphics."""
    publisher_url = resolve_publisher_url(url)
    if not publisher_url:
        return None
    try:
        req = urllib.request.Request(publisher_url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; NusantaraNewsBot/1.0)",
            "Accept": "text/html,application/xhtml+xml",
        })
        with urllib.request.urlopen(req, timeout=12) as response:
            final_url = response.geturl()
            if "html" not in response.headers.get("Content-Type", "").lower():
                return None
            html_bytes = response.read(1800000)
        parser = _MetaImageParser()
        parser.feed(html_bytes.decode("utf-8", errors="replace"))
        # Prefer the publisher's OG hero image, then its Twitter/itemprop image.
        # Resolve relative and protocol-relative URLs against the final article URL.
        for raw_candidate in parser.ordered_images():
            candidate = urllib.parse.urljoin(final_url, raw_candidate)
            if valid_article_image(candidate):
                return candidate
    except Exception as exc:
        print(f"[warn] cannot read publisher image from {publisher_url}: {exc}")
    return None

def item_image(item: ET.Element, article_url: str = "") -> str | None:
    """Use only a verified image from the original publisher article."""
    publisher_url = resolve_publisher_url(article_url) if article_url else ""
    if publisher_url:
        image = publisher_page_image(publisher_url)
        if image:
            return image
    # RSS media metadata is accepted only when hosted by a publisher/CDN,
    # never Google News, generic Google thumbnail services or stock providers.
    for elem in item.iter():
        tag = elem.tag.lower()
        if tag.endswith("}content") or tag.endswith("}thumbnail") or tag.endswith("enclosure"):
            candidate = (elem.attrib.get("url") or elem.attrib.get("href") or "").strip()
            if valid_article_image(candidate):
                return candidate
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

    # Repair imported cards in batches; re-check every feed photo because some
    # old entries point to Google News proxy thumbnails shared across stories.
    repaired = 0
    repair_cursor = next((int(article.get("_imageRepairCursor", 0)) for article in rows if article.get("_imageRepairCursor") is not None), 0)
    imported_indexes = [i for i, article in enumerate(rows) if article.get("autoImported")]
    if imported_indexes:
        batch = imported_indexes[repair_cursor:repair_cursor + MAX_REPAIR_PER_RUN]
        if not batch:
            batch = imported_indexes[:MAX_REPAIR_PER_RUN]
            repair_cursor = 0
        for index in batch:
            article = rows[index]
            source_url = str(article.get("sourceUrl") or "")
            if not source_url:
                continue
            actual_image = publisher_page_image(source_url)
            existing_image = str(article.get("image") or "").strip()
            if actual_image and existing_image != actual_image:
                article["image"] = actual_image
                article["caption"] = f"Foto artikel dari penerbit {article.get('sourceName', 'sumber berita')}; kredit mengikuti sumber asli."
                repaired += 1
            elif not actual_image and existing_image and not valid_article_image(existing_image):
                # Remove known proxy thumbnails or broken placeholders only.
                # Keep existing direct publisher images when the source temporarily
                # blocks our metadata fetch, so a transient network issue cannot erase a good photo.
                article["image"] = ""
                article["caption"] = "Foto asli belum dapat diverifikasi dari penerbit; gambar tidak ditampilkan sementara."
                repaired += 1
        next_cursor = (repair_cursor + len(batch)) % max(1, len(imported_indexes))
            rows[0]["_imageRepairLastBatch"] = len(batch)
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
            publisher_link = resolve_publisher_url(link)
            if publisher_link:
                link = publisher_link
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
            caption = f"Foto dari penerbit {source_name}; periksa kredit pada artikel asli." if image else "Foto asli dari penerbit belum dapat diverifikasi; gambar tidak ditampilkan."
            fallback_image = None
            candidates.append({
                "slug": slug,
                "title": raw_title[:140],
                "category": category,
                "excerpt": excerpt,
                "author": "Feed Redaksi",
                "date": published.strftime("%Y-%m-%d"),
                "time": published.strftime("%H.%M WIB"),
                "image": image or "",
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
    if not additions and not repaired and not imported_indexes:
        print("No new headlines or image repairs found; leaving news.json unchanged.")
        return 0
    existing = {a.get("slug") for a in rows}
    additions = [a for a in additions if a.get("slug") not in existing]
    rows = additions + rows

    # Keep the repair cursor attached to the first feed row after new headlines
    # are prepended. Otherwise every new import shifts the cursor out of row 0
    # and old image repairs can restart from the beginning indefinitely.
    if imported_indexes:
        next_cursor = (next_cursor + len(additions)) % max(1, len(imported_indexes) + len(additions))
        for article in rows:
            article.pop("_imageRepairCursor", None)
        if rows:
            rows[0]["_imageRepairCursor"] = next_cursor

    NEWS_PATH.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Imported {len(additions)} headline(s), repaired {repaired} image(s); total articles: {len(rows)}.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
