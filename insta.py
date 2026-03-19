import io
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from urllib.parse import urljoin, urlparse

import requests
import telebot
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)

BUILD_TAG = "v2-rewrite-newtab-sequential-v15-video-compress-fallback"
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif")
VIDEO_EXTS = (".mp4", ".webm", ".m4v", ".mov")
MAX_IMAGES = int(os.getenv("MAX_IMAGES", "50"))
MAX_VIDEOS = int(os.getenv("MAX_VIDEOS", "10"))
MAX_VIDEO_MB = int(os.getenv("MAX_VIDEO_MB", "200"))
TELEGRAM_MAX_UPLOAD_MB = int(os.getenv("TELEGRAM_MAX_UPLOAD_MB", "49"))
VIDEO_FILE_ID_CACHE_PATH = os.getenv("VIDEO_FILE_ID_CACHE_PATH", "video_file_ids.json")
ENABLE_FFMPEG_FALLBACK = os.getenv("ENABLE_FFMPEG_FALLBACK", "1") == "1"

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("Set TELEGRAM_BOT_TOKEN environment variable")

bot = telebot.TeleBot(TOKEN)


def load_video_file_id_cache():
    try:
        if not os.path.exists(VIDEO_FILE_ID_CACHE_PATH):
            return {}
        with open(VIDEO_FILE_ID_CACHE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_video_file_id_cache(cache):
    try:
        with open(VIDEO_FILE_ID_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        logging.warning("Failed to save video file_id cache: %s", exc)


def ffmpeg_available():
    return shutil.which("ffmpeg") is not None


def compress_video_bytes_to_limit(video_bytes: bytes, target_mb: int):
    if not ENABLE_FFMPEG_FALLBACK:
        return None
    if not ffmpeg_available():
        logging.warning("ffmpeg not available; compression fallback disabled")
        return None

    max_bytes = target_mb * 1024 * 1024
    in_fd, in_path = tempfile.mkstemp(suffix=".mp4")
    out_fd, out_path = tempfile.mkstemp(suffix="_compressed.mp4")
    os.close(in_fd)
    os.close(out_fd)
    try:
        with open(in_path, "wb") as f:
            f.write(video_bytes)

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            in_path,
            "-vf",
            "scale='min(1280,iw)':-2",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "30",
            "-c:a",
            "aac",
            "-b:a",
            "96k",
            "-movflags",
            "+faststart",
            "-fs",
            str(max_bytes),
            out_path,
        ]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if proc.returncode != 0:
            logging.warning("ffmpeg compression failed")
            return None
        if not os.path.exists(out_path):
            return None
        out_size = os.path.getsize(out_path)
        if out_size <= 0 or out_size > max_bytes:
            return None
        with open(out_path, "rb") as f:
            return f.read()
    except Exception as exc:
        logging.warning("Compression fallback exception: %s", exc)
        return None
    finally:
        for p in (in_path, out_path):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass


def is_http_url(url: str) -> bool:
    try:
        p = urlparse(url)
        return p.scheme in ("http", "https") and bool(p.netloc)
    except Exception:
        return False


def dedupe_keep_order(items):
    seen = set()
    out = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def looks_like_image_url(url: str) -> bool:
    lower = (url or "").lower()
    return any(ext in lower for ext in IMAGE_EXTS)


def looks_like_video_url(url: str) -> bool:
    lower = (url or "").lower()
    return any(ext in lower for ext in VIDEO_EXTS) or ".m3u8" in lower


def looks_like_image_page_url(url: str) -> bool:
    lower = (url or "").lower()
    hints = ["/pin/", "/gallery/", "/photo/", "/image/", "/pic/", "/view/", "/p/"]
    return any(h in lower for h in hints)


def is_junk_image_url(url: str) -> bool:
    lower = (url or "").lower()
    bad = [
        "logo",
        "icon",
        "sprite",
        "favicon",
        "/contents/categories/",
        "last_category",
        "premium.png",
        "play_white.png",
        "/player/skin/",
        "/images/premium",
    ]
    return any(x in lower for x in bad)


def extract_page_tokens(page_url: str):
    parsed = urlparse(page_url)
    tokens = []
    for part in (parsed.path or "").lower().split("/"):
        if not part or len(part) < 3:
            continue
        if part.isdigit():
            continue
        if part in {"porn", "tag", "picture", "page", "albums"}:
            continue
        for token in re.split(r"[^a-z0-9]+", part):
            if len(token) >= 3 and not token.isdigit():
                tokens.append(token)
    return dedupe_keep_order(tokens)


def base_domain(host: str):
    host = (host or "").lower().strip(".")
    parts = host.split(".")
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return host


def is_relevant_to_page(url: str, page_host: str, tokens):
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    lower_url = url.lower()

    if host == page_host:
        return True
    page_base = base_domain(page_host)
    if page_base and (host == page_base or host.endswith("." + page_base)):
        return True
    # For off-domain CDNs, require stronger token overlap to avoid unrelated galleries.
    if tokens and sum(1 for t in tokens if t in lower_url) >= 2:
        return True
    return False


def variant_key(url: str):
    lower = url.lower()
    key = re.sub(r"_[0-9]{2,4}x_", "_X_", lower)
    key = re.sub(r"/[0-9]{2,4}x[0-9]{2,4}/", "/XxX/", key)
    return key


def variant_score(url: str):
    lower = url.lower()
    score = 0
    m = re.search(r"_(\\d{2,4})x_", lower)
    if m:
        score += int(m.group(1))
    m2 = re.search(r"/(\\d{2,4})x(\\d{2,4})/", lower)
    if m2:
        score += int(m2.group(1)) + int(m2.group(2))
    if "original" in lower or "sources" in lower:
        score += 5000
    if "thumb" in lower or "/gthumb/" in lower:
        score -= 500
    return score


def choose_best_variant_per_image(urls):
    best_by_key = {}
    for u in urls:
        key = variant_key(u)
        cur = best_by_key.get(key)
        if not cur or variant_score(u) > variant_score(cur):
            best_by_key[key] = u
    return dedupe_keep_order(best_by_key.values())


def expand_hq_variants(url: str):
    lower = url.lower()
    variants = [url]

    # Common gallery size path upgrades: /460/... -> /1280/... /1920/...
    m = re.search(r"/(180|240|320|460|640|720|800|960|1024)/", lower)
    if m:
        cur = m.group(1)
        for target in ("1280", "1920", "2048"):
            variants.append(re.sub(rf"/{cur}/", f"/{target}/", url, count=1))

    # Token upgrades like _180x_ / _320x_ / _640x_.
    variants.append(re.sub(r"_(180|240|320|460|640|720|800|960)x_", "_1280x_", url, flags=re.IGNORECASE))
    variants.append(re.sub(r"_(180|240|320|460|640|720|800|960)x_", "_1920x_", url, flags=re.IGNORECASE))

    # Megatube overview -> sources.
    variants.append(expand_megatube_source_candidate(url))

    # Generic filename upgrades: foo.jpg -> foobig.jpg / foo_big.jpg.
    variants.append(re.sub(r"(\.(?:jpg|jpeg|png|webp|avif|gif))$", r"big\1", url, flags=re.IGNORECASE))
    variants.append(re.sub(r"(\.(?:jpg|jpeg|png|webp|avif|gif))$", r"_big\1", url, flags=re.IGNORECASE))

    # Thumb path upgrades used by some galleries (including auntmia-like structures).
    if "/thumbs/" in lower:
        variants.append(url.replace("/thumbs/", "/full/"))
        variants.append(url.replace("/thumbs/", "/"))

    return dedupe_keep_order([v for v in variants if is_http_url(v)])


def choose_best_download_url(url: str, referer: str):
    headers = {
        "User-Agent": DEFAULT_UA,
        "Referer": referer,
    }
    candidates = expand_hq_variants(url)
    best_url = None
    best_size = -1

    for c in candidates:
        try:
            h = requests.head(c, headers=headers, timeout=15, allow_redirects=True)
            if h.status_code >= 400:
                continue
            ct = (h.headers.get("content-type") or "").lower()
            if ct and not ct.startswith("image/") and not looks_like_image_url(c):
                continue
            size = int(h.headers.get("content-length", "0") or 0)
            # Prefer actual larger objects; if unknown size, keep as fallback.
            if size > best_size:
                best_size = size
                best_url = c
        except Exception:
            continue

    return best_url or url


def apply_dominant_gallery_id_filter(urls):
    """
    Keep only URLs that belong to the dominant long numeric gallery id in path,
    reducing related-content bleed (common on gallery pages).
    """
    id_counts = {}
    url_ids = {}
    for u in urls:
        ids = re.findall(r"/(\d{5,10})/", u)
        if ids:
            url_ids[u] = ids
            for gid in ids:
                id_counts[gid] = id_counts.get(gid, 0) + 1

    if not id_counts:
        return urls

    dominant_id, dominant_count = sorted(id_counts.items(), key=lambda x: x[1], reverse=True)[0]
    if dominant_count < 4:
        return urls

    kept = [u for u in urls if dominant_id in (url_ids.get(u) or [])]
    return kept or urls


def extract_megatube_album_id(page_url: str):
    m = re.search(r"/albums/(\d+)/", page_url.lower())
    return m.group(1) if m else None


def extract_megatube_video_id(page_url: str):
    m = re.search(r"/videos/(\d+)/", page_url.lower())
    return m.group(1) if m else None


def expand_megatube_source_candidate(url: str):
    m = re.search(
        r"/contents/albums_overview/(\d+)/(\d+)/(?:\d+x\d+|originals|1200x)/(\d+)\.(jpg|jpeg|png|webp|avif|gif)",
        url,
        flags=re.IGNORECASE,
    )
    if not m:
        return url
    g1, g2, img_id, ext = m.groups()
    return f"https://st.megatube.xxx/contents/albums/sources/{g1}/{g2}/{img_id}.{ext.lower()}"


def extract_image_candidates_from_html(html: str, base_url: str):
    soup = BeautifulSoup(html, "html.parser")
    urls = []

    for img in soup.find_all("img"):
        for attr in ("src", "data-src", "data-original", "data-full", "data-lazy"):
            v = img.get(attr)
            if v:
                urls.append(urljoin(base_url, v))

        for srcset_attr in ("srcset", "data-srcset"):
            srcset = img.get(srcset_attr)
            if srcset:
                for part in srcset.split(","):
                    candidate = part.strip().split(" ")[0]
                    if candidate:
                        urls.append(urljoin(base_url, candidate))

    for a in soup.select("a[href]"):
        href = a.get("href")
        if href:
            abs_href = urljoin(base_url, href)
            if a.find("img") is not None or looks_like_image_url(abs_href):
                urls.append(abs_href)

    for meta in soup.select("meta[property='og:image'], meta[name='twitter:image']"):
        c = meta.get("content")
        if c:
            urls.append(urljoin(base_url, c))

    urls = [u for u in dedupe_keep_order(urls) if is_http_url(u)]
    return urls


def collect_dom_candidates(page):
    urls = []
    try:
        dom_urls = page.eval_on_selector_all(
            "img, a[href], source",
            """els => {
                const out = [];
                for (const e of els) {
                    const href = e.href || e.getAttribute('href');
                    const src = e.src || e.getAttribute('src');
                    const dsrc = e.getAttribute('data-src');
                    const dorg = e.getAttribute('data-original');
                    if (href) out.push(href);
                    if (src) out.push(src);
                    if (dsrc) out.push(dsrc);
                    if (dorg) out.push(dorg);
                }
                return out;
            }""",
        )
        urls.extend(urljoin(page.url, u) for u in dom_urls if u)
    except Exception:
        pass
    return [u for u in dedupe_keep_order(urls) if is_http_url(u)]


def fetch_candidates_via_requests(page_url: str):
    headers = {
        "User-Agent": DEFAULT_UA,
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.google.com/",
    }
    try:
        r = requests.get(page_url, headers=headers, timeout=25)
        if r.status_code == 200 and r.text:
            return extract_image_candidates_from_html(r.text, page_url)
    except Exception:
        pass
    return []


def fetch_video_candidates_via_requests(page_url: str):
    headers = {
        "User-Agent": DEFAULT_UA,
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.google.com/",
    }
    try:
        r = requests.get(page_url, headers=headers, timeout=25)
        if r.status_code == 200 and r.text:
            return extract_video_candidates_from_html(r.text, page_url)
    except Exception:
        pass
    return []


def extract_video_candidates_from_html(html: str, base_url: str):
    soup = BeautifulSoup(html, "html.parser")
    urls = []

    for v in soup.find_all("video"):
        src = v.get("src")
        if src:
            urls.append(urljoin(base_url, src))
        for s in v.find_all("source"):
            ssrc = s.get("src")
            if ssrc:
                urls.append(urljoin(base_url, ssrc))

    for s in soup.find_all("source"):
        ssrc = s.get("src")
        if ssrc:
            urls.append(urljoin(base_url, ssrc))

    for a in soup.select("a[href]"):
        href = a.get("href")
        if href:
            abs_href = urljoin(base_url, href)
            if looks_like_video_url(abs_href):
                urls.append(abs_href)

    for meta in soup.select(
        "meta[property='og:video'], meta[property='og:video:url'], meta[name='twitter:player:stream']"
    ):
        c = meta.get("content")
        if c:
            urls.append(urljoin(base_url, c))

    return [u for u in dedupe_keep_order(urls) if is_http_url(u)]


def filter_video_candidates_for_page(page_url: str, candidates):
    page_host = (urlparse(page_url).netloc or "").lower()
    tokens = extract_page_tokens(page_url)
    cleaned = []
    for u in candidates:
        if not is_http_url(u):
            continue
        if not looks_like_video_url(u):
            continue
        if not is_relevant_to_page(u, page_host, tokens):
            continue
        cleaned.append(u)

    cleaned = dedupe_keep_order(cleaned)
    cleaned = apply_dominant_gallery_id_filter(cleaned)
    return dedupe_keep_order(cleaned)


def filter_candidates_for_page(page_url: str, candidates):
    cleaned = []
    for u in candidates:
        if not is_http_url(u):
            continue
        if is_junk_image_url(u):
            continue
        # Keep direct images and also clickable image-page links that resolve after opening.
        if looks_like_image_url(u) or looks_like_image_page_url(u):
            cleaned.append(u)
    page_host = (urlparse(page_url).netloc or "").lower()
    tokens = extract_page_tokens(page_url)

    cleaned = [u for u in cleaned if is_relevant_to_page(u, page_host, tokens)]

    lower_page = page_url.lower()
    if "megatube.xxx" in lower_page and "/videos/" in lower_page:
        video_id = extract_megatube_video_id(page_url)
        if video_id:
            token = f"/{video_id}/"
            video_images = []
            for u in cleaned:
                lu = u.lower()
                if "/contents/videos_screenshots/" in lu and token in lu:
                    video_images.append(u)
            if video_images:
                return choose_best_variant_per_image(dedupe_keep_order(video_images))

    if "megatube.xxx" in lower_page:
        album_id = extract_megatube_album_id(page_url)
        if album_id:
            token = f"/{album_id}/"
            album_only = []
            for u in cleaned:
                lu = u.lower()
                if "/contents/albums_overview/" in lu and token in lu:
                    album_only.append(expand_megatube_source_candidate(u))
                elif "/contents/albums/sources/" in lu and token in lu:
                    album_only.append(u)
            if album_only:
                return choose_best_variant_per_image(dedupe_keep_order(album_only))

    cleaned = choose_best_variant_per_image(dedupe_keep_order(cleaned))
    cleaned = apply_dominant_gallery_id_filter(cleaned)
    return dedupe_keep_order(cleaned)


def resolve_image_in_new_tab(context, source_page_url: str, candidate_url: str):
    tab = None
    try:
        tab = context.new_page()
        response = tab.goto(candidate_url, timeout=30000, wait_until="domcontentloaded")
        final_url = tab.url

        try:
            content_type = (response.headers.get("content-type") or "").lower() if response else ""
        except Exception:
            content_type = ""

        if is_http_url(final_url) and content_type.startswith("image/"):
            return final_url

        dom_imgs = tab.eval_on_selector_all(
            "img",
            "els => els.map(e => e.src || e.getAttribute('src') || e.getAttribute('data-src'))",
        )
        dom_anchors = tab.eval_on_selector_all(
            "a[href]",
            "els => els.map(e => e.href || e.getAttribute('href'))",
        )
        candidates = [urljoin(tab.url, x) for x in dom_imgs if x]
        candidates.extend(urljoin(tab.url, x) for x in dom_anchors if x)
        if is_http_url(final_url):
            candidates.insert(0, final_url)

        for u in dedupe_keep_order(candidates):
            if not is_http_url(u) or is_junk_image_url(u):
                continue
            if looks_like_image_url(u):
                return u

        return None
    except Exception as exc:
        logging.warning("new-tab resolve failed for %s: %s", candidate_url, exc)
        return None
    finally:
        try:
            if tab is not None:
                tab.close()
        except Exception:
            pass


def resolve_video_in_new_tab(context, source_page_url: str, candidate_url: str):
    tab = None
    try:
        # Direct downloadable media URL: avoid page.goto because it may trigger browser download.
        if looks_like_video_url(candidate_url) or "/get_file/" in candidate_url.lower():
            try:
                h = requests.head(
                    candidate_url,
                    headers={"User-Agent": DEFAULT_UA, "Referer": source_page_url},
                    timeout=15,
                    allow_redirects=True,
                )
                ct = (h.headers.get("content-type") or "").lower()
                if h.status_code < 400 and (ct.startswith("video/") or "application/vnd.apple.mpegurl" in ct or looks_like_video_url(candidate_url)):
                    return candidate_url
            except Exception:
                if looks_like_video_url(candidate_url):
                    return candidate_url

        tab = context.new_page()
        response = tab.goto(candidate_url, timeout=30000, wait_until="domcontentloaded")
        final_url = tab.url

        try:
            content_type = (response.headers.get("content-type") or "").lower() if response else ""
        except Exception:
            content_type = ""

        if is_http_url(final_url) and (content_type.startswith("video/") or "application/vnd.apple.mpegurl" in content_type):
            return final_url
        if is_http_url(final_url) and looks_like_video_url(final_url):
            return final_url

        dom_videos = tab.eval_on_selector_all(
            "video, source, a[href]",
            """els => {
                const out = [];
                for (const e of els) {
                    const src = e.src || e.getAttribute('src');
                    const href = e.href || e.getAttribute('href');
                    if (src) out.push(src);
                    if (href) out.push(href);
                }
                return out;
            }""",
        )
        candidates = [urljoin(tab.url, x) for x in dom_videos if x]
        if is_http_url(final_url):
            candidates.insert(0, final_url)

        for u in dedupe_keep_order(candidates):
            if is_http_url(u) and looks_like_video_url(u):
                return u
        return None
    except Exception as exc:
        if "Download is starting" in str(exc) and looks_like_video_url(candidate_url):
            return candidate_url
        logging.warning("new-tab video resolve failed for %s: %s", candidate_url, exc)
        return None
    finally:
        try:
            if tab is not None:
                tab.close()
        except Exception:
            pass


def download_image_bytes(url: str, referer: str):
    headers = {
        "User-Agent": DEFAULT_UA,
        "Referer": referer,
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    }
    r = requests.get(url, headers=headers, timeout=30)
    if r.status_code != 200:
        return None, None

    ct = (r.headers.get("content-type") or "").lower()
    if not ct.startswith("image/") and not looks_like_image_url(url):
        return None, None

    ext = ".jpg"
    if "png" in ct:
        ext = ".png"
    elif "webp" in ct:
        ext = ".webp"
    elif "gif" in ct:
        ext = ".gif"
    elif "avif" in ct:
        ext = ".avif"

    return r.content, ext


def download_video_bytes(url: str, referer: str, max_mb: int = 40):
    # m3u8 cannot be downloaded directly as a single binary here.
    if ".m3u8" in url.lower():
        logging.info("Skip direct download for m3u8 video: %s", url)
        return None, None

    headers = {
        "User-Agent": DEFAULT_UA,
        "Referer": referer,
        "Accept": "*/*",
    }
    try:
        r = requests.get(url, headers=headers, timeout=40, stream=True)
        if r.status_code != 200:
            logging.warning("Video download status=%s for %s", r.status_code, url)
            return None, None

        ct = (r.headers.get("content-type") or "").lower()
        if ct and not ct.startswith("video/") and not looks_like_video_url(url):
            logging.warning("Video content-type rejected ct=%s url=%s", ct, url)
            return None, None

        max_bytes = max_mb * 1024 * 1024
        data = bytearray()
        for chunk in r.iter_content(chunk_size=512 * 1024):
            if not chunk:
                continue
            data.extend(chunk)
            if len(data) > max_bytes:
                logging.warning("Video exceeds MAX_VIDEO_MB=%s for %s", max_mb, url)
                return None, None

        ext = ".mp4"
        if "webm" in ct:
            ext = ".webm"
        elif "quicktime" in ct:
            ext = ".mov"
        elif "x-m4v" in ct:
            ext = ".m4v"
        return bytes(data), ext
    except Exception as exc:
        logging.warning("Video binary download failed for %s: %s", url, exc)
        return None, None


def scrape_and_send_images(chat_id: int, page_url: str):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=DEFAULT_UA,
            locale="en-US",
            viewport={"width": 1366, "height": 768},
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )

        try:
            page = context.new_page()
            response_image_urls = []
            response_video_urls = []

            def on_response(resp):
                try:
                    ct = (resp.headers.get("content-type") or "").lower()
                    if ct.startswith("image/") and is_http_url(resp.url):
                        response_image_urls.append(resp.url)
                    elif (ct.startswith("video/") or "application/vnd.apple.mpegurl" in ct) and is_http_url(resp.url):
                        response_video_urls.append(resp.url)
                except Exception:
                    pass

            page.on("response", on_response)
            page.goto(page_url, timeout=35000, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)

            # Trigger lazy-loaded images.
            for _ in range(4):
                page.mouse.wheel(0, 5000)
                page.wait_for_timeout(700)

            raw_candidates = []
            raw_candidates.extend(extract_image_candidates_from_html(page.content(), page.url))
            raw_candidates.extend(collect_dom_candidates(page))
            raw_candidates.extend(response_image_urls)
            if not raw_candidates:
                raw_candidates.extend(fetch_candidates_via_requests(page.url))
            candidates = filter_candidates_for_page(page.url, raw_candidates)[:MAX_IMAGES]
            total_found = len(candidates)

            raw_video_candidates = []
            raw_video_candidates.extend(extract_video_candidates_from_html(page.content(), page.url))
            raw_video_candidates.extend([u for u in collect_dom_candidates(page) if looks_like_video_url(u)])
            raw_video_candidates.extend(response_video_urls)
            if not raw_video_candidates:
                raw_video_candidates.extend(fetch_video_candidates_via_requests(page.url))
            video_candidates = filter_video_candidates_for_page(page.url, raw_video_candidates)[:MAX_VIDEOS]
            total_videos = len(video_candidates)

            bot.send_message(
                chat_id,
                f"Found {total_found} images and {total_videos} videos. Opening each in a new tab and downloading one by one.",
            )
            logging.info(
                "Media candidates images=%s(raw=%s) videos=%s(raw=%s) url=%s",
                total_found,
                len(raw_candidates),
                total_videos,
                len(raw_video_candidates),
                page_url,
            )
            if total_found == 0 and total_videos == 0:
                bot.send_message(chat_id, "No downloadable media found on this page (it may be protected or dynamically blocked).")
                return 0, 0

            sent = 0
            sent_urls = set()
            for idx, candidate in enumerate(candidates, start=1):
                resolved = resolve_image_in_new_tab(context, page.url, candidate)
                if not resolved:
                    continue

                best_url = choose_best_download_url(resolved, page.url)
                if best_url in sent_urls:
                    continue
                raw, ext = download_image_bytes(best_url, page.url)
                if not raw:
                    continue

                file_obj = io.BytesIO(raw)
                file_obj.name = f"image_{idx}{ext}"
                bot.send_document(chat_id, file_obj)
                sent += 1
                sent_urls.add(best_url)
                if sent <= 3 or sent % 5 == 0 or sent == total_found:
                    logging.info("Sent image %s/%s from %s", sent, total_found, best_url)

            sent_videos = 0
            sent_video_urls = set()
            failed_videos = 0
            video_file_id_cache = load_video_file_id_cache()
            cache_changed = False
            for vid_idx, v_candidate in enumerate(video_candidates, start=1):
                resolved_video = resolve_video_in_new_tab(context, page.url, v_candidate)
                if not resolved_video:
                    failed_videos += 1
                    logging.warning("Video resolve failed for candidate: %s", v_candidate)
                    continue
                if resolved_video in sent_video_urls:
                    continue

                cached_file_id = video_file_id_cache.get(resolved_video)
                if cached_file_id:
                    try:
                        bot.send_video(chat_id, cached_file_id)
                        sent_videos += 1
                        sent_video_urls.add(resolved_video)
                        if sent_videos <= 2 or sent_videos == total_videos:
                            logging.info("Sent video %s/%s via cached file_id for %s", sent_videos, total_videos, resolved_video)
                        continue
                    except Exception as exc:
                        logging.warning("Cached file_id send failed for %s: %s", resolved_video, exc)

                v_raw, v_ext = download_video_bytes(resolved_video, page.url, max_mb=MAX_VIDEO_MB)
                if not v_raw:
                    # fallback: try remote URL send
                    try:
                        msg = bot.send_video(chat_id, resolved_video)
                        sent_videos += 1
                        sent_video_urls.add(resolved_video)
                        if getattr(msg, "video", None) and getattr(msg.video, "file_id", None):
                            video_file_id_cache[resolved_video] = msg.video.file_id
                            cache_changed = True
                        if sent_videos <= 2 or sent_videos == total_videos:
                            logging.info("Sent video %s/%s via URL from %s", sent_videos, total_videos, resolved_video)
                    except Exception as exc:
                        logging.warning("send_video URL failed for %s: %s", resolved_video, exc)
                        try:
                            bot.send_document(chat_id, resolved_video)
                            sent_videos += 1
                            sent_video_urls.add(resolved_video)
                            logging.info("Sent video as document URL from %s", resolved_video)
                        except Exception as exc2:
                            failed_videos += 1
                            logging.warning("send_document URL failed for %s: %s", resolved_video, exc2)
                            bot.send_message(chat_id, f"Video URL (could not auto-send): {resolved_video}")
                    continue

                if len(v_raw) > TELEGRAM_MAX_UPLOAD_MB * 1024 * 1024:
                    logging.warning(
                        "Video too large for Telegram upload (%s MB > %s MB): %s",
                        round(len(v_raw) / (1024 * 1024), 2),
                        TELEGRAM_MAX_UPLOAD_MB,
                        resolved_video,
                    )
                    try:
                        msg = bot.send_video(chat_id, resolved_video)
                        sent_videos += 1
                        sent_video_urls.add(resolved_video)
                        if getattr(msg, "video", None) and getattr(msg.video, "file_id", None):
                            video_file_id_cache[resolved_video] = msg.video.file_id
                            cache_changed = True
                        if sent_videos <= 2 or sent_videos == total_videos:
                            logging.info("Sent large video %s/%s via URL from %s", sent_videos, total_videos, resolved_video)
                    except Exception as exc:
                        logging.warning("Large video URL send failed for %s: %s", resolved_video, exc)
                        compressed = compress_video_bytes_to_limit(v_raw, TELEGRAM_MAX_UPLOAD_MB)
                        if compressed:
                            c_file = io.BytesIO(compressed)
                            c_file.name = f"video_{vid_idx}_compressed.mp4"
                            try:
                                msg = bot.send_video(chat_id, c_file)
                                sent_videos += 1
                                sent_video_urls.add(resolved_video)
                                if getattr(msg, "video", None) and getattr(msg.video, "file_id", None):
                                    video_file_id_cache[resolved_video] = msg.video.file_id
                                    cache_changed = True
                                logging.info("Sent compressed large video for %s", resolved_video)
                            except Exception as excc:
                                failed_videos += 1
                                logging.warning("Compressed video send failed for %s: %s", resolved_video, excc)
                                bot.send_message(chat_id, f"Video URL (too large to upload): {resolved_video}")
                        else:
                            failed_videos += 1
                            bot.send_message(chat_id, f"Video URL (too large to upload): {resolved_video}")
                    continue

                v_file = io.BytesIO(v_raw)
                v_file.name = f"video_{vid_idx}{v_ext}"
                try:
                    msg = bot.send_video(chat_id, v_file)
                    if getattr(msg, "video", None) and getattr(msg.video, "file_id", None):
                        video_file_id_cache[resolved_video] = msg.video.file_id
                        cache_changed = True
                except Exception as exc:
                    logging.warning("send_video file failed for %s: %s", resolved_video, exc)
                    try:
                        v_file.seek(0)
                        bot.send_document(chat_id, v_file)
                    except Exception as exc2:
                        failed_videos += 1
                        logging.warning("send_document file failed for %s: %s", resolved_video, exc2)
                        try:
                            msg = bot.send_video(chat_id, resolved_video)
                            sent_videos += 1
                            sent_video_urls.add(resolved_video)
                            if getattr(msg, "video", None) and getattr(msg.video, "file_id", None):
                                video_file_id_cache[resolved_video] = msg.video.file_id
                                cache_changed = True
                            logging.info("Sent video via URL fallback after file failure: %s", resolved_video)
                        except Exception as exc3:
                            logging.warning("URL fallback failed for %s: %s", resolved_video, exc3)
                            compressed = compress_video_bytes_to_limit(v_raw, TELEGRAM_MAX_UPLOAD_MB)
                            if compressed:
                                c_file = io.BytesIO(compressed)
                                c_file.name = f"video_{vid_idx}_compressed.mp4"
                                try:
                                    msg = bot.send_video(chat_id, c_file)
                                    sent_videos += 1
                                    sent_video_urls.add(resolved_video)
                                    if getattr(msg, "video", None) and getattr(msg.video, "file_id", None):
                                        video_file_id_cache[resolved_video] = msg.video.file_id
                                        cache_changed = True
                                    logging.info("Sent compressed fallback video for %s", resolved_video)
                                except Exception as exc4:
                                    failed_videos += 1
                                    logging.warning("Compressed fallback send failed for %s: %s", resolved_video, exc4)
                                    bot.send_message(chat_id, f"Video URL (could not auto-send): {resolved_video}")
                            else:
                                bot.send_message(chat_id, f"Video URL (could not auto-send): {resolved_video}")
                        continue
                sent_videos += 1
                sent_video_urls.add(resolved_video)
                if sent_videos <= 2 or sent_videos == total_videos:
                    logging.info("Sent video %s/%s from %s", sent_videos, total_videos, resolved_video)

            if cache_changed:
                save_video_file_id_cache(video_file_id_cache)
            bot.send_message(chat_id, f"Done. Sent {sent} images and {sent_videos} videos. Failed videos: {failed_videos}.")
            return sent, sent_videos
        finally:
            try:
                context.close()
            except Exception:
                pass
            try:
                browser.close()
            except Exception:
                pass


@bot.message_handler(commands=["start"])
def on_start(msg):
    bot.reply_to(msg, "Send a webpage URL. I will count pictures/videos, open each in a new tab, and download/send one-by-one.")


@bot.message_handler(func=lambda m: True)
def on_message(msg):
    text = (msg.text or "").strip()
    logging.info("Received input: %s", text)

    if not text.startswith("http://") and not text.startswith("https://"):
        bot.reply_to(msg, "Send a valid URL starting with http/https.")
        return

    bot.reply_to(msg, "Processing URL...")
    try:
        scrape_and_send_images(msg.chat.id, text)
    except Exception as exc:
        logging.error("Handler error: %s", exc, exc_info=True)
        bot.send_message(msg.chat.id, "Error while scraping/downloading images.")


if __name__ == "__main__":
    logging.info("[BUILD %s] Bot starting", BUILD_TAG)
    bot.infinity_polling(skip_pending=True, timeout=30, long_polling_timeout=30)

