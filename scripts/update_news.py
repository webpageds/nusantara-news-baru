#!/usr/bin/env python3
"""Import recent public headlines from Google News RSS while keeping source links."""
from __future__ import annotations

import datetime as dt
import json
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
MAX_REPAIR_PER_RUN = 10
MAX_GOOGLE_URL_RESOLUTIONS_PER_RUN = 1
_GOOGLE_URL_RESOLUTION_COUNT = 0
_GOOGLE_URL_CACHE: dict[str, str] = {}

# Source-verified article media for the exact items visible in the homepage report.
PINNED_ARTICLE_MEDIA = {
    "podsi-prioritaskan-persiapan-atlet-demi-tiket-olimpiade-los-angeles-2028": {
        "sourceName": "ANTARA News",
        "sourceUrl": "https://www.antaranews.com/berita/5881443/podsi-akan-fokus-persiapkan-atlet-jelang-kualifikasi-olimpiade",
        "image": "https://cdn.antaranews.com/cache/1200x800/2026/11/24/Kejurnas-Dayung-di-Karawang-241126-ryl-5.jpg",
        "caption": "ANTARA FOTO/Darryl Ramadhan — atlet rowing pada Kejurnas Dayung 2026 di Situ Cipule, Karawang",
    },
    "serangan-drone-tewaskan-2-warga-italia-di-kuwait-iran-bantah-terlibat": {
        "sourceName": "Media Indonesia",
        "sourceUrl": "https://mediaindonesia.com/internasional/961031/2-warga-italia-tewas-dalam-serangan-drone-di-kuwait-iran-bantah-terlibat",
        "image": "https://asset.mediaindonesia.com/news/2026/11/27/1795728902_9a164fa17489909da3c9.jpg",
        "caption": "Foto AFP via Media Indonesia — dua teknisi Italia yang tewas dalam serangan drone di Kuwait",
    },
    "riset-budaya-warkop-siswi-mts-aceh-besar-sabet-dua-penghargaan-nasional": {
        "sourceName": "Kemenag Aceh",
        "sourceUrl": "https://aceh.kemenag.go.id/baca/riset-budaya-warkop-mtsn-1-aceh-besar-sabet-dua-penghargaan-nasional",
        "image": "",
        "caption": "Foto Humas Kemenag Aceh Besar — Kakankemenag bersama peserta OMI Riset dan Sains di Asrama Haji Pondok Gede, 26 November 2026",
    },
    "bisnis-antarnegara-makin-ramai-pembayaran-global-naik-40-pada-semester-i-2026-ini-pendorongn": {
        "sourceName": "KONTAN",
        "sourceUrl": "https://keuangan.kontan.co.id/news/citi-catat-transaksi-pembayaran-global-naik-40-asia-jadi-motor-pertumbuhan",
        "image": "https://foto.kontan.co.id/8uUTBeoogZGbwyeB1f_4MkHeOjA%3D/smart/filters%3Aformat%28webp%29/2026/11/20/644485448.jpg",
        "caption": "Ilustrasi logo Citi — Reuters/Dado Ruvic, via KONTAN",
    },
}
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
# Topic-specific editorial illustrations are used only when the publisher has
# no usable image. They are labelled as illustrations, not event photographs.
FALLBACK_IMAGES = {
    "Nasional": "https://images.unsplash.com/photo-1529107386315-e1a2ed48a620?auto=format&fit=crop&w=1200&h=675&q=82",
    "Daerah": "https://images.unsplash.com/photo-1519608487953-e999c86e7455?auto=format&fit=crop&w=1200&h=675&q=82",
    "Ekonomi": "https://images.unsplash.com/photo-1611974789855-9c2a0a7236a3?auto=format&fit=crop&w=1200&h=675&q=82",
    "Internasional": "https://images.unsplash.com/photo-1526778548025-fa2f459cd1b4?auto=format&fit=crop&w=1200&h=675&q=82",
    "Politik": "https://images.unsplash.com/photo-1529107386315-e1a2ed48a620?auto=format&fit=crop&w=1200&h=675&q=82",
    "Teknologi": "https://images.unsplash.com/photo-1518770660439-4636190af475?auto=format&fit=crop&w=1200&h=675&q=82",
    "Olahraga": "https://images.unsplash.com/photo-1461896836934-ffe607ba8211?auto=format&fit=crop&w=1200&h=675&q=82",
    "Pendidikan": "https://images.unsplash.com/photo-1503676260728-1c00da094a0b?auto=format&fit=crop&w=1200&h=675&q=82",
    "Sosial": "https://images.unsplash.com/photo-1531206715517-5c0ba140b2b8?auto=format&fit=crop&w=1200&h=675&q=82",
    "Lifestyle": "https://images.unsplash.com/photo-1490645935967-10de6ba17061?auto=format&fit=crop&w=1200&h=675&q=82",
}

def choose_fallback_image(category: str) -> str:
    return FALLBACK_IMAGES.get(str(category or "").strip(), FALLBACK_IMAGES["Nasional"])

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
        self._jsonld_buffer: list[str] | None = None

    def _add_image(self, candidate: str, priority: int):
        candidate = str(candidate or "").strip()
        if candidate and not candidate.lower().startswith(("data:", "javascript:")):
            self.images.append((priority, self._sequence, candidate))
            self._sequence += 1

    def _collect_jsonld_article_images(self, node):
        """Collect image fields only from Article/NewsArticle JSON-LD objects."""
        if isinstance(node, list):
            for item in node:
                self._collect_jsonld_article_images(item)
            return
        if not isinstance(node, dict):
            return

        raw_types = node.get("@type", [])
        types = [raw_types] if isinstance(raw_types, str) else raw_types
        types = [str(item).lower() for item in types] if isinstance(types, list) else []
        is_article = any(
            item.endswith(("article", "newsarticle", "reportagenewsarticle", "blogposting"))
            for item in types
        )

        if is_article:
            def add_image_value(value):
                if isinstance(value, str):
                    self._add_image(value, 5)
                elif isinstance(value, list):
                    for child in value:
                        add_image_value(child)
                elif isinstance(value, dict):
                    for key in ("url", "contentUrl"):
                        if value.get(key):
                            add_image_value(value[key])
            add_image_value(node.get("image"))

        for key, value in node.items():
            if key not in ("image", "logo"):
                self._collect_jsonld_article_images(value)

    def handle_starttag(self, tag, attrs):
        values = {str(k).lower(): str(v) for k, v in attrs if k and v}
        tag = tag.lower()
        if tag == "script" and "ld+json" in (values.get("type") or "").lower():
            self._jsonld_buffer = []
            return

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
        self._add_image(candidate, priority)

    def handle_data(self, data):
        if self._jsonld_buffer is not None:
            self._jsonld_buffer.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "script" and self._jsonld_buffer is not None:
            raw = "".join(self._jsonld_buffer).strip()
            self._jsonld_buffer = None
            if raw:
                try:
                    self._collect_jsonld_article_images(json.loads(raw))
                except (json.JSONDecodeError, TypeError, ValueError):
                    pass

    def ordered_images(self):
        seen = set()
        for _, _, candidate in sorted(self.images):
            if candidate not in seen:
                seen.add(candidate)
                yield candidate


class _PublisherLinkParser(HTMLParser):
    """Find canonical publisher article links inside Google News wrappers."""
    def __init__(self):
        super().__init__()
        self.candidates: list[tuple[int, str]] = []

    def handle_starttag(self, tag, attrs):
        values = {str(k).lower(): str(v) for k, v in attrs if k and v}
        tag = tag.lower()
        if tag == "meta":
            key = (values.get("property") or values.get("name") or "").lower()
            if key in ("og:url", "twitter:url"):
                value = values.get("content", "").strip()
                if value:
                    self.candidates.append((0, value))
        elif tag == "link":
            if "canonical" in (values.get("rel") or "").lower().split():
                value = values.get("href", "").strip()
                if value:
                    self.candidates.append((1, value))
        elif tag == "a":
            value = values.get("href", "").strip()
            if value.startswith(("https://", "http://")):
                self.candidates.append((2, value))


_TRACKING_HOSTS = (
    "google-analytics.com", "googletagmanager.com", "googlesyndication.com",
    "doubleclick.net", "adservice.google.com", "hotjar.com",
    "fonts.googleapis.com", "fonts.gstatic.com", "w3.org",
)


def _is_tracking_or_google_host(host: str, path: str = "") -> bool:
    host = (host or "").lower().split(":", 1)[0]
    path = (path or "").lower()
    if any(host == item or host.endswith("." + item) for item in _TRACKING_HOSTS):
        return True
    if host in ("news.google.com", "google.com", "www.google.com", "gstatic.com"):
        return True
    if host.endswith((".google.com", ".gstatic.com", ".googleusercontent.com")):
        return True
    if path.endswith(("/analytics.js", "/gtag/js", "/gtm.js", "/collect", "/g/collect")):
        return True
    if any(token in path for token in ("/pagead/", "/doubleclick/", "/pixel.", "/beacon")):
        return True
    return False


def _publisher_candidate(value: str, base_url: str = "") -> str:
    """Normalize a candidate and reject trackers, Google wrappers, and static assets."""
    try:
        candidate = urllib.parse.urljoin(base_url, html.unescape(str(value or "")).strip())
        parts = urllib.parse.urlsplit(candidate)
        host, path = (parts.hostname or "").lower(), parts.path.lower()
        if parts.scheme not in ("http", "https") or not host:
            return ""
        if _is_tracking_or_google_host(host, path):
            return ""
        if path.endswith((".js", ".css", ".json", ".xml", ".svg", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".woff", ".woff2")):
            return ""
        if not path or path == "/":
            return ""
        return urllib.parse.urlunsplit(("https", parts.netloc, parts.path, parts.query, ""))
    except Exception:
        return ""


def resolve_publisher_url(url: str) -> str:
    """Resolve current Google News RSS article URLs with Google's signed URL RPC."""
    global _GOOGLE_URL_RESOLUTION_COUNT
    raw = html.unescape(str(url or "")).strip()
    if not raw.startswith(("https://", "http://")):
        return ""
    try:
        parts = urllib.parse.urlsplit(raw)
        host = (parts.hostname or "").lower()
        if not host.endswith("news.google.com"):
            return _publisher_candidate(raw)
        if raw in _GOOGLE_URL_CACHE:
            return _GOOGLE_URL_CACHE[raw]
        if _GOOGLE_URL_RESOLUTION_COUNT >= MAX_GOOGLE_URL_RESOLUTIONS_PER_RUN:
            return ""

        match = re.search(r"/(?:rss/)?articles/([^/?#]+)", parts.path)
        if not match:
            return ""
        article_id = match.group(1)
        _GOOGLE_URL_RESOLUTION_COUNT += 1

        cookie = "CONSENT=YES+cb; SOCS=CAI"
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Cookie": cookie,
        }
        page_request = urllib.request.Request(
            "https://news.google.com/rss/articles/" + urllib.parse.quote(article_id, safe=""),
            headers=headers,
        )
        with urllib.request.urlopen(page_request, timeout=12) as response:
            final_url = response.geturl()
            final_host = (urllib.parse.urlsplit(final_url).hostname or "").lower()
            if final_host and not final_host.endswith("google.com"):
                resolved = _publisher_candidate(final_url)
                _GOOGLE_URL_CACHE[raw] = resolved
                return resolved
            page = response.read(1800000).decode("utf-8", errors="replace")

        signature_match = re.search(r'data-n-a-sg="([^"]+)"', page)
        timestamp_match = re.search(r'data-n-a-ts="([^"]+)"', page)
        if not signature_match or not timestamp_match:
            print(f"[warn] Google News signature/timestamp missing for {article_id[:18]}.")
            _GOOGLE_URL_CACHE[raw] = ""
            return ""

        signature = signature_match.group(1)
        timestamp = timestamp_match.group(1)
        # This is the current garturlreq payload observed in Google's own page.
        inner = (
            '["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,'
            'null,null,null,null,null,0,1],"X","X",1,[1,1,1],1,1,null,0,0,null,0],'
            + json.dumps(article_id) + "," + timestamp + "," + json.dumps(signature) + "]"
        )
        body = urllib.parse.urlencode({
            "f.req": json.dumps([[["Fbv4je", inner, None, "generic"]]], separators=(",", ":"))
        }).encode("utf-8")
        post_headers = {
            "User-Agent": "Mozilla/5.0",
            "Cookie": cookie,
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        }
        post_request = urllib.request.Request(
            "https://news.google.com/_/DotsSplashUi/data/batchexecute",
            data=body,
            headers=post_headers,
        )
        with urllib.request.urlopen(post_request, timeout=12) as response:
            raw_response = response.read(1000000).decode("utf-8", errors="replace")

        # Google sometimes returns an XSSI-prefixed frame without a blank-line
        # separator. Accept both the blank-line and direct JSON-array formats.
        clean_response = raw_response.lstrip()
        if clean_response.startswith(")]}'"):
            clean_response = clean_response[4:].lstrip()
        try:
            frames = json.loads(clean_response)
        except json.JSONDecodeError:
            first_array = clean_response.find("[")
            if first_array < 0:
                raise ValueError("Google News batchexecute response contained no JSON array: " + clean_response[:220])
            frames, _ = json.JSONDecoder().raw_decode(clean_response[first_array:])
        row = frames[0][2] if isinstance(frames, list) and frames and isinstance(frames[0], list) and len(frames[0]) > 2 else None
        if not row:
            print(f"[warn] Google News returned an empty publisher URL for {article_id[:18]}.")
            _GOOGLE_URL_CACHE[raw] = ""
            return ""
        payload = json.loads(row)
        resolved = _publisher_candidate(str(payload[1])) if isinstance(payload, list) and len(payload) > 1 else ""
        _GOOGLE_URL_CACHE[raw] = resolved
        if not resolved:
            print(f"[warn] Google News publisher URL did not pass validation for {article_id[:18]}.")
        return resolved
    except Exception as exc:
        print(f"[warn] cannot decode Google News URL {raw[:100]}: {exc}")
        _GOOGLE_URL_CACHE[raw] = ""
        return ""



def valid_article_image(url: str) -> bool:
    """Accept plausible direct publisher images; reject generic/thumbnail assets."""
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
        if host in ("www.w3.org", "w3.org", "fonts.googleapis.com", "fonts.gstatic.com"):
            return False

        blogger_host = (
            host == "blogger.googleusercontent.com"
            or host == "blogspot.com"
            or host.endswith(".blogspot.com")
        )
        # Google-hosted search thumbnails are not publisher images. Only the
        # dedicated Blogger CDN is allowed as a direct Google-hosted image.
        if host.endswith(("google.com", "gstatic.com", "googleusercontent.com")) and not blogger_host:
            return False
        if host == "images.unsplash.com":
            # The old feed used these as repeated category fallbacks, not article photos.
            return False
        if any(token in path for token in (
            "logo", "favicon", "avatar", "placeholder", "no-image",
            "no_image", "default-image", "default_image", "sprite", "analytics.js"
        )):
            return False
        if re.search(r"(?:[?&](?:w|width|sz)=|[=/]w)(\d{1,4})(?:[&#/]|$)", raw.lower()):
            match = re.search(r"(?:[?&](?:w|width|sz)=|[=/]w)(\d{1,4})(?:[&#/]|$)", raw.lower())
            if match and int(match.group(1)) < 200:
                return False
        if re.search(r"/(?:s|w|h)\d{1,3}(?:-[a-z]+)?/", path) and not blogger_host:
            return False
        return True
    except Exception:
        return False


def image_url_is_reachable(url: str) -> bool:
    """Check recognizable image bytes, including CDNs serving application/octet-stream."""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; NusantaraNewsBot/1.0)",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*;q=0.8,*/*;q=0.5",
        })
        with urllib.request.urlopen(req, timeout=8) as response:
            content_type = str(response.headers.get("Content-Type", "")).lower()
            sample = response.read(64)
            signature = (
                sample.startswith(b"\xff\xd8\xff")
                or sample.startswith(b"\x89PNG\r\n\x1a\n")
                or sample.startswith((b"GIF87a", b"GIF89a"))
                or (sample.startswith(b"RIFF") and sample[8:12] == b"WEBP")
                or (len(sample) >= 12 and sample[4:8] == b"ftyp" and sample[8:12] in (b"avif", b"avis"))
            )
            return bool(sample) and (content_type.startswith("image/") or signature)
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
        with urllib.request.urlopen(req, timeout=8) as response:
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
            if valid_article_image(candidate) and image_url_is_reachable(candidate):
                return candidate
    except Exception as exc:
        print(f"[warn] cannot read publisher image from {publisher_url}: {exc}")
    return None

def item_image(item: ET.Element, article_url: str = "") -> str | None:
    """Use a reachable publisher-declared image, never a Google proxy thumbnail."""
    publisher_url = resolve_publisher_url(article_url) if article_url else ""
    if publisher_url:
        image = publisher_page_image(publisher_url)
        if image:
            return image

    # RSS enclosures from the publisher/CDN are acceptable; Google-hosted
    # News thumbnails are excluded because they can be generic or repetitive.
    for elem in item.iter():
        tag = elem.tag.lower()
        if tag.endswith("}content") or tag.endswith("enclosure"):
            candidate = (elem.attrib.get("url") or elem.attrib.get("href") or "").strip()
            if valid_article_image(candidate) and image_url_is_reachable(candidate):
                return candidate
    return None

def request_feed(query: str) -> list[ET.Element]:
    params = urllib.parse.urlencode({"q": query, "hl": "id", "gl": "ID", "ceid": "ID:id"})
    url = "https://news.google.com/rss/search?" + params
    req = urllib.request.Request(url, headers={"User-Agent": "NusantaraNewsFeedBot/1.0"})
    with urllib.request.urlopen(req, timeout=12) as response:
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

    # Apply source-verified media for the exact stories from the reported homepage.
    # Warkop image is fetched from the official Kemenag Aceh page; no substitute
    # image is invented if the publisher page does not expose a direct photo.
    pinned_repaired = 0
    for article in rows:
        media = PINNED_ARTICLE_MEDIA.get(str(article.get("slug") or ""))
        if not media:
            continue
        article["sourceName"] = media["sourceName"]
        article["sourceUrl"] = media["sourceUrl"]
        article["caption"] = media["caption"]
        image = str(media.get("image") or "").strip()
        if not image:
            image = publisher_page_image(media["sourceUrl"]) or ""
        # Explicitly curated, source-page image URLs are already checked
        # against the publisher page and its visible image. For these exact
        # allow-listed URLs, do not reject a CDN solely because it serves the
        # image with application/octet-stream or rewrites the file format.
        curated_direct_image = bool(str(media.get("image") or "").strip())
        image_ok = valid_article_image(image) and (curated_direct_image or image_url_is_reachable(image))
        if image and image_ok:
            if article.get("image") != image:
                article["image"] = image
                pinned_repaired += 1
        else:
            article["image"] = ""
    if pinned_repaired:
        print(f"Applied {pinned_repaired} source-verified article photo(s).")

    # Delete the old category-based stock photos and Google News proxy thumbnails.
    # These assets were reused across hundreds of unrelated stories.
    repaired = 0
    for article in rows:
        if not article.get("autoImported"):
            continue
        image = str(article.get("image") or "").strip()
        image_host = (urllib.parse.urlsplit(image).hostname or "").lower() if image else ""
        if image_host in ("images.unsplash.com", "lh3.googleusercontent.com", "www.w3.org", "w3.org"):
            article["image"] = ""
            article["caption"] = "Foto utama penerbit sedang dicari ulang; foto generik tidak digunakan."
            repaired += 1
        source_url = str(article.get("sourceUrl") or "").strip()
        if source_url:
            parts = urllib.parse.urlsplit(source_url)
            if _is_tracking_or_google_host(parts.hostname or "", parts.path) and not (parts.hostname or "").lower().endswith("news.google.com"):
                article["sourceUrl"] = ""
                repaired += 1

    repair_cursor = next((int(article.get("_imageRepairCursor", 0)) for article in rows if article.get("_imageRepairCursor") is not None), 0)
    imported_indexes = [i for i, article in enumerate(rows) if article.get("autoImported")]
    next_cursor = repair_cursor
    if imported_indexes:
        batch = imported_indexes[repair_cursor:repair_cursor + MAX_REPAIR_PER_RUN]
        if not batch:
            batch = imported_indexes[:MAX_REPAIR_PER_RUN]
            repair_cursor = 0
        for index in batch:
            article = rows[index]
            source_url = str(article.get("sourceUrl") or "").strip()
            if not source_url:
                continue
            source_host = (urllib.parse.urlsplit(source_url).hostname or "").lower()
            # Leave Google News redirects to the live-feed matcher below so
            # the limited decoder budget prioritizes currently visible stories.
            if source_host.endswith("news.google.com"):
                continue
            actual_image = publisher_page_image(source_url)
            existing_image = str(article.get("image") or "").strip()
            if actual_image and existing_image != actual_image:
                article["image"] = actual_image
                article["caption"] = f"Foto utama dari penerbit {article.get('sourceName', 'sumber berita')}; kredit mengikuti sumber asli."
                repaired += 1
        next_cursor = (repair_cursor + len(batch)) % max(1, len(imported_indexes))
    if repaired:
        print(f"Cleaned/repaired {repaired} imported article image/source field(s).")

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
            rss_link = (item.findtext("link") or "").strip()
            if not raw_title or not rss_link.startswith(("https://", "http://")):
                continue
            normalized = re.sub(r"\W+", " ", raw_title.lower()).strip()
            published = parse_date(item.findtext("pubDate") or "")
            if published > now + dt.timedelta(minutes=10) or published < now - dt.timedelta(hours=30):
                continue

            publisher_link = resolve_publisher_url(rss_link)
            link = publisher_link or rss_link

            # Re-match already imported titles to current RSS entries. This
            # restores publisher URLs and hero images for records whose sourceUrl
            # was previously corrupted to google-analytics.js.
            if normalized in known_titles:
                existing = next((a for a in rows if re.sub(r"\W+", " ", str(a.get("title", "")).lower()).strip() == normalized and a.get("autoImported")), None)
                if existing:
                    if publisher_link and existing.get("sourceUrl") != publisher_link:
                        existing["sourceUrl"] = publisher_link
                        repaired += 1
                    actual_image = item_image(item, publisher_link or rss_link)
                    if actual_image and existing.get("image") != actual_image:
                        existing["image"] = actual_image
                        existing["caption"] = f"Foto utama dari penerbit {source_name}; kredit mengikuti sumber asli."
                        repaired += 1
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
            image = item_image(item, publisher_link or rss_link)
            caption = f"Foto dari penerbit {source_name}; periksa kredit pada artikel asli." if image else "Foto asli dari penerbit belum dapat diverifikasi; gambar tidak ditampilkan."
            is_illustration = not bool(image)
            if not image:
                image = choose_fallback_image(category)
                caption = "Ilustrasi editorial kategori " + category + "; bukan dokumentasi langsung peristiwa. Foto utama penerbit tidak tersedia."
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
                "imageIsIllustration": is_illustration,
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
