import io
import logging
import os
import re
import time
from urllib.parse import urljoin, urlparse

import requests
import telebot
import yt_dlp
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

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("Set TELEGRAM_BOT_TOKEN environment variable")

bot = telebot.TeleBot(TOKEN)

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif")
VIDEO_EXTS = (".mp4", ".webm")
MEDIA_EXTS = IMAGE_EXTS + VIDEO_EXTS
DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
VERBOSE_MEDIA_LOGS = os.getenv("VERBOSE_MEDIA_LOGS", "1") == "1"
TRACE_URLS = os.getenv("TRACE_URLS", "1") == "1"


def handle_popups(page):
    selectors = [
        "button:has-text('Accept')",
        "button:has-text('I Agree')",
        "button:has-text('Enter')",
        "button:has-text('Yes')",
        "button:has-text('Continue')",
        "button:has-text('I am 18')",
        "text=I am 18",
        "text=Enter",
    ]

    for selector in selectors:
        try:
            btn = page.query_selector(selector)
            if btn:
                btn.click()
                logging.info("Popup handled with: %s", selector)
                page.wait_for_timeout(1500)
                return
        except Exception:
            continue

    try:
        page.evaluate(
            """
            document.querySelectorAll('div,section').forEach(el => {
                const txt = (el.innerText || '').toLowerCase();
                if (txt.includes('18') && txt.includes('enter')) {
                    el.remove();
                }
            });
            """
        )
    except Exception as exc:
        logging.warning("Popup fallback remove failed: %s", exc)


def analyze_page(page):
    result = {
        "has_images": bool(page.query_selector_all("img")),
        "has_videos": bool(page.query_selector_all("video")),
        "has_lazy": bool(page.query_selector_all("[data-src], [data-lazy], [data-original]")),
        "scroll_needed": False,
        "pagination": False,
    }

    for b in page.query_selector_all("button"):
        text = (b.inner_text() or "").lower()
        if "load more" in text or "show more" in text:
            result["scroll_needed"] = True
            break

    for a in page.query_selector_all("a"):
        href = (a.get_attribute("href") or "").lower()
        if "/page/" in href or "?page=" in href:
            result["pagination"] = True
            break

    return result


def is_protection_page(page):
    try:
        title = (page.title() or "").lower()
    except Exception:
        title = ""

    markers = [
        "just a moment",
        "attention required",
        "cloudflare",
        "access denied",
        "forbidden",
    ]
    if any(m in title for m in markers):
        return True

    try:
        html = (page.content() or "").lower()
    except Exception:
        return False

    html_markers = [
        "cf-challenge",
        "cloudflare",
        "access denied",
        "error 403",
        "forbidden",
    ]
    return any(m in html for m in html_markers)


def decide_strategy(analysis):
    if analysis["has_lazy"]:
        return "lazy_load"
    if analysis["scroll_needed"]:
        return "scroll"
    if analysis["pagination"]:
        return "pagination"
    if analysis["has_images"]:
        return "static"
    return "unknown"


def get_base_url(url):
    match = re.search(r"(.*?/p/)\d+/?$", url)
    return match.group(1) if match else None


def score_url(url) :
    score = 0
    lower = url.lower()
    if "large" in lower or "original" in lower:
        score += 3
    if "media" in lower:
        score += 2
    if len(url) > 100:
        score += 1
    if any(k in lower for k in ["75x75", "150x", "236x", "320x", "474x", "thumb", "preview", "small"]):
        score -= 5
    if "/contents/categories/" in lower:
        score -= 12
    if "st.megatube.xxx" in lower and "/contents/albums/sources/" in lower:
        score += 14
    m = re.search(r"(\d{2,4})x(\d{2,4})", lower)
    if m:
        w = int(m.group(1))
        h = int(m.group(2))
        if w * h >= 1000 * 1000:
            score += 3
        elif w * h <= 320 * 320:
            score -= 3
    return score


def has_any_ext(url, exts):
    lower = (url or "").lower()
    return any(ext in lower for ext in exts)


def looks_like_direct_media_url(url):
    lower = (url or "").lower()
    return has_any_ext(lower, MEDIA_EXTS) or ".m3u8" in lower


def is_http_url(url):
    if not url:
        return False
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def is_blocked_or_junk_url(url):
    lower = (url or "").lower()
    bad_keywords = [
        "logo",
        "icon",
        "avatar",
        "favicon",
        "emoji",
    ]
    if any(k in lower for k in bad_keywords):
        return True
    return False


def is_valid_media(url):
    if not url:
        return False

    if not is_http_url(url):
        return False

    lower = url.lower()
    if is_blocked_or_junk_url(lower):
        return False

    if "hr_" in lower:
        return True

    if ".m3u8" in lower:
        return True

    return has_any_ext(lower, MEDIA_EXTS)


def dedupe_keep_order(items):
    seen = set()
    output = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            output.append(item)
    return output


def probe_url(url, headers=None, timeout=8):
    info = {"url": url, "ok": False, "size": 0, "content_type": "", "status_code": 0}
    try:
        res = requests.head(url, headers=headers, timeout=timeout, allow_redirects=True)
        info["status_code"] = res.status_code
        info["content_type"] = (res.headers.get("content-type") or "").lower()
        info["size"] = int(res.headers.get("content-length", 0) or 0)
        info["ok"] = 200 <= res.status_code < 400
        return info
    except Exception:
        return info


def is_probe_image_ok(meta, url):
    content_type = (meta.get("content_type") or "").lower()
    status_ok = bool(meta.get("ok"))
    looks_like_image = has_any_ext(url, IMAGE_EXTS)

    if not status_ok:
        return False
    if content_type.startswith("text/html") or "application/json" in content_type:
        return False
    if content_type:
        return content_type.startswith("image/")
    return looks_like_image


def scrape_direct_media_url(url):
    headers = {
        "User-Agent": DEFAULT_UA,
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": url,
    }

    info = probe_url(url, headers=headers, timeout=10)
    content_type = (info.get("content_type") or "").lower()

    if (content_type.startswith("image/") and info.get("ok")) or (has_any_ext(url, IMAGE_EXTS) and info.get("ok")):
        logging.info("Direct media URL detected as image: %s (ct=%s)", url, content_type)
        return {"title": "Direct Image", "images": [url], "videos": [], "blocked": False}

    if (content_type.startswith("video/") and info.get("ok")) or ".m3u8" in url.lower() or (
        has_any_ext(url, VIDEO_EXTS) and info.get("ok")
    ):
        logging.info("Direct media URL detected as video: %s (ct=%s)", url, content_type)
        return {"title": "Direct Video", "images": [], "videos": [url], "blocked": False}

    # Fallback: try a lightweight GET for servers that do not return HEAD metadata.
    try:
        res = requests.get(url, headers=headers, timeout=10, stream=True)
        get_ct = (res.headers.get("content-type") or "").lower()
        if get_ct.startswith("image/"):
            logging.info("Direct media GET detected image: %s (ct=%s)", url, get_ct)
            return {"title": "Direct Image", "images": [url], "videos": [], "blocked": False}
        if get_ct.startswith("video/") or "application/vnd.apple.mpegurl" in get_ct:
            logging.info("Direct media GET detected video: %s (ct=%s)", url, get_ct)
            return {"title": "Direct Video", "images": [], "videos": [url], "blocked": False}
    except Exception as exc:
        logging.warning("Direct media probe GET failed for %s: %s", url, exc)

    return None


def select_best_image_candidate(img_url, headers):
    candidates = dedupe_keep_order(expand_image_candidates(img_url) + [img_url])
    probed = []

    for candidate in candidates:
        if not is_http_url(candidate):
            continue
        meta = probe_url(candidate, headers=headers, timeout=8)
        if is_probe_image_ok(meta, candidate):
            is_image_type = (meta["content_type"] or "").startswith("image/")
            bonus = 1_000_000 if is_image_type else 0
            meta["rank"] = bonus + meta["size"] + (score_url(candidate) * 1024)
            probed.append(meta)
        elif VERBOSE_MEDIA_LOGS:
            logging.info("Probe reject non-image: %s (ct=%s status=%s)", candidate, meta["content_type"], meta["status_code"])

    if not probed:
        if VERBOSE_MEDIA_LOGS:
            logging.info("No better candidate found, using original: %s", img_url)
        return img_url

    best = sorted(probed, key=lambda x: x["rank"], reverse=True)[0]
    if VERBOSE_MEDIA_LOGS:
        summary = ", ".join(
            f"{m['url']} [ct={m['content_type'] or '-'} size={m['size']}]"
            for m in sorted(probed, key=lambda x: x["rank"], reverse=True)[:4]
        )
        logging.info("Image candidate selection: base=%s | chosen=%s | options=%s", img_url, best["url"], summary)
    return best["url"]


def expand_image_candidates(url):
    if not url:
        return []

    candidates = [url]
    lower_url = url.lower()
    is_megatube = "megatube.xxx" in lower_url or "mt-static.com" in lower_url

    # Common size tokens in image CDNs: /236x/... or /960x540/... etc.
    sized_path = re.search(r"/\d{2,4}x\d{2,4}(?:_[a-z]+)?/", url, flags=re.IGNORECASE)
    if sized_path and not is_megatube:
        candidates.append(re.sub(r"/\d{2,4}x\d{2,4}(?:_[a-z]+)?/", "/originals/", url, flags=re.IGNORECASE))
        candidates.append(re.sub(r"/\d{2,4}x\d{2,4}(?:_[a-z]+)?/", "/1200x/", url, flags=re.IGNORECASE))

    # Megatube/mt-static: prefer st.megatube.xxx source URLs (usually valid high-res).
    m_overview = re.search(
        r"/contents/albums_overview/(\d+)/(\d+)/(?:\d+x\d+|originals|1200x)/(\d+)\.(jpg|jpeg|png|webp|avif|gif)",
        url,
        flags=re.IGNORECASE,
    )
    if m_overview:
        g1, g2, img_id, ext = m_overview.groups()
        src_base = f"https://st.megatube.xxx/contents/albums/sources/{g1}/{g2}/{img_id}.{ext.lower()}"
        candidates.append(src_base)
        candidates.append(f"{src_base}?rnd={int(time.time())}")

    m_sources = re.search(
        r"/contents/albums/sources/(\d+)/(\d+)/(\d+)\.(jpg|jpeg|png|webp|avif|gif)",
        url,
        flags=re.IGNORECASE,
    )
    if m_sources:
        g1, g2, img_id, ext = m_sources.groups()
        src_base = f"https://st.megatube.xxx/contents/albums/sources/{g1}/{g2}/{img_id}.{ext.lower()}"
        candidates.append(src_base)
        candidates.append(f"{src_base}?rnd={int(time.time())}")

    # WordPress and similar: image-800x525.jpg -> image.jpg
    candidates.append(
        re.sub(
            r"-\d{2,4}x\d{2,4}(?=\.(?:jpg|jpeg|png|webp|avif|gif)(?:\?|$))",
            "",
            url,
            flags=re.IGNORECASE,
        )
    )
    candidates.append(re.sub(r"-scaled(?=\.(?:jpg|jpeg|png|webp|avif|gif)(?:\?|$))", "", url, flags=re.IGNORECASE))

    # Remove width/height quality params that often force thumbnails.
    stripped = re.sub(r"([?&])(w|h|width|height|quality|q|resize)=[^&]+", "", url, flags=re.IGNORECASE)
    stripped = re.sub(r"\?&", "?", stripped).rstrip("?&")
    if stripped and stripped != url:
        candidates.append(stripped)

    return dedupe_keep_order(candidates)


def choose_best_images_for_send(images, headers, limit, probe_pool=40):
    pool = images[:probe_pool]
    ranked = []

    for base in pool:
        chosen = select_best_image_candidate(base, headers)
        meta = probe_url(chosen, headers=headers, timeout=8)
        if not is_probe_image_ok(meta, chosen):
            if VERBOSE_MEDIA_LOGS:
                logging.info(
                    "Pre-send ranking skip invalid image: base=%s chosen=%s status=%s ct=%s",
                    base,
                    chosen,
                    meta.get("status_code", 0),
                    meta.get("content_type", ""),
                )
            continue
        rank = (meta.get("size", 0), score_url(chosen))
        ranked.append((rank, chosen, base, meta))

    ranked.sort(key=lambda x: x[0], reverse=True)
    ordered = []
    for _, chosen, base, meta in ranked:
        ordered.append(chosen)
        if VERBOSE_MEDIA_LOGS:
            logging.info(
                "Pre-send ranking: base=%s chosen=%s size=%s ct=%s",
                base,
                chosen,
                meta.get("size", 0),
                meta.get("content_type", ""),
            )

    # Include leftovers not in the probed pool, preserving existing order.
    for img in images:
        if img not in ordered:
            ordered.append(img)

    return dedupe_keep_order(ordered)[:limit] if limit is not None else dedupe_keep_order(ordered)


def filter_media_by_source_context(source_url, images, videos):
    source_lower = (source_url or "").lower()
    album_match = re.search(r"/albums/(\d+)/", source_lower)

    # Site-specific: megatube album pages often expose unrelated category thumbs.
    if "megatube.xxx" in source_lower and album_match:
        album_id = album_match.group(1)
        album_token = f"/{album_id}/"
        album_images = [
            u for u in images
            if "/contents/albums_" in u.lower() and album_token in u.lower()
        ]
        if album_images:
            if VERBOSE_MEDIA_LOGS:
                logging.info(
                    "Context filter applied: source album_id=%s kept_album_images=%s dropped=%s",
                    album_id,
                    len(album_images),
                    max(0, len(images) - len(album_images)),
                )
            images = album_images
        else:
            # If no album-specific images were found, at least de-prioritize categories.
            images = [u for u in images if "/contents/categories/" not in u.lower()] or images

    return images, videos


def filter_relevant_images(source_url, images):
    source_host = (urlparse(source_url).netloc or "").lower()
    if not source_host:
        return images

    def domain_match(target_host):
        target_host = (target_host or "").lower()
        return target_host == source_host or target_host.endswith("." + source_host)

    allowed_extra = (
        "uuu.cam",
        "st.megatube.xxx",
        "mt-static.com",
    )

    kept = []
    for img in images:
        host = (urlparse(img).netloc or "").lower()
        if domain_match(host):
            kept.append(img)
            continue
        if any(host == d or host.endswith("." + d) for d in allowed_extra):
            kept.append(img)
            continue

    if VERBOSE_MEDIA_LOGS:
        logging.info(
            "Relevant image filter: source=%s kept=%s dropped=%s",
            source_host,
            len(kept),
            max(0, len(images) - len(kept)),
        )
    return kept or images


def extract_images_from_soup(soup, base_url):
    urls = []
    img_attrs = ["src", "data-src", "data-original", "data-full", "data-zoom-image", "data-large-file"]

    for img in soup.find_all("img"):
        for attr in img_attrs:
            val = img.get(attr)
            if val:
                urls.append(urljoin(base_url, val))

        for set_attr in ["srcset", "data-srcset"]:
            srcset = img.get(set_attr)
            if srcset:
                for part in srcset.split(","):
                    candidate = part.strip().split(" ")[0]
                    if candidate:
                        urls.append(urljoin(base_url, candidate))

    for meta in soup.select(
        "meta[property='og:image'], meta[name='twitter:image'], meta[property='og:image:url']"
    ):
        content = meta.get("content")
        if content:
            urls.append(urljoin(base_url, content))

    cleaned = []
    for u in urls:
        if is_http_url(u) and not is_blocked_or_junk_url(u):
            if has_any_ext(u, IMAGE_EXTS) or "image" in u.lower():
                cleaned.extend(expand_image_candidates(u))

    cleaned = dedupe_keep_order(cleaned)
    cleaned = [u for u in cleaned if is_valid_media(u)]
    return sorted(cleaned, key=score_url, reverse=True)


def collect_detail_page_links_from_soup(soup, base_url, max_links=20):
    base_host = (urlparse(base_url).netloc or "").lower()
    links = []

    for a in soup.select("a[href]"):
        href = a.get("href")
        if not href:
            continue
        normalized = urljoin(base_url, href)
        if not is_http_url(normalized):
            continue
        parsed = urlparse(normalized)
        if parsed.netloc.lower() != base_host:
            continue
        lower = normalized.lower()
        if has_any_ext(lower, IMAGE_EXTS) or has_any_ext(lower, VIDEO_EXTS):
            continue
        if any(k in lower for k in ["#comment", "#reply", "tag=", "sort=", "page="]):
            continue
        if any(k in lower for k in ["/photo", "/image", "/pic", "/gallery", "/view", "/p/"]):
            links.append(normalized)

    return dedupe_keep_order(links)[:max_links]


def crawl_detail_pages_for_images(detail_urls, referer_url, max_pages=20):
    if not detail_urls:
        return []

    parsed = urlparse(referer_url)
    domain = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else referer_url
    headers = {
        "User-Agent": DEFAULT_UA,
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": domain,
    }

    collected = []
    for idx, detail_url in enumerate(detail_urls[:max_pages], start=1):
        try:
            res = requests.get(detail_url, headers=headers, timeout=15)
            if res.status_code != 200:
                continue
            soup = BeautifulSoup(res.text, "html.parser")
            images = extract_images_from_soup(soup, detail_url)
            if images:
                collected.append(images[0])  # take best/full-size candidate per detail page
                logging.info("Detail page %s/%s -> image found", idx, min(len(detail_urls), max_pages))
        except Exception as exc:
            logging.warning("Detail page crawl failed for %s: %s", detail_url, exc)

    return dedupe_keep_order(collected)


def collect_detail_page_links_from_dom(page, max_links=20):
    try:
        hrefs = page.eval_on_selector_all("a[href]", "els => els.map(e => e.href || e.getAttribute('href'))")
    except Exception:
        return []

    base_url = page.url
    base_host = (urlparse(base_url).netloc or "").lower()
    links = []
    for raw in hrefs:
        if not raw:
            continue
        normalized = urljoin(base_url, raw)
        if not is_http_url(normalized):
            continue
        parsed = urlparse(normalized)
        if parsed.netloc.lower() != base_host:
            continue
        lower = normalized.lower()
        if has_any_ext(lower, IMAGE_EXTS) or has_any_ext(lower, VIDEO_EXTS):
            continue
        if any(k in lower for k in ["#comment", "#reply", "tag=", "sort=", "page="]):
            continue
        if any(k in lower for k in ["/photo", "/image", "/pic", "/gallery", "/view", "/p/"]):
            links.append(normalized)

    return dedupe_keep_order(links)[:max_links]


def crawl_detail_pages_with_tabs(page, detail_links, max_pages=12):
    collected = []
    context = page.context
    total = min(len(detail_links), max_pages)

    for idx, detail_url in enumerate(detail_links[:max_pages], start=1):
        tab = None
        try:
            logging.info("Detail tab %s/%s opening: %s", idx, total, detail_url)
            tab = context.new_page()
            tab.goto(detail_url, timeout=25000, wait_until="domcontentloaded")
            tab.wait_for_timeout(1200)
            logging.info("Detail tab %s/%s loaded: final_url=%s title=%s", idx, total, tab.url, tab.title())
            handle_popups(tab)
            tab.wait_for_timeout(800)

            # Priority 1: if page exposes a download button, use that media URL.
            download_url = extract_download_url_from_tab(tab)
            if download_url:
                collected.append(download_url)
                logging.info("Detail tab %s/%s using download button media: %s", idx, total, download_url)
                continue

            # Priority 2: fallback to direct image candidates from page DOM/network.
            tab_media = collect_dom_media(tab)
            tab_media = dedupe_keep_order([u for u in tab_media if is_http_url(u)])
            if TRACE_URLS and tab_media:
                for media_idx, media_url in enumerate(tab_media[:12], start=1):
                    logging.info("Detail tab %s media url [%s]: %s", idx, media_idx, media_url)
            tab_images = [u for u in tab_media if has_any_ext(u, IMAGE_EXTS)]

            if tab_images:
                tab_images = sorted(tab_images, key=score_url, reverse=True)
                best = tab_images[0]
                collected.append(best)
                logging.info("Detail tab %s/%s picked image: %s", idx, total, best)
            elif VERBOSE_MEDIA_LOGS:
                logging.info("Detail tab %s/%s found no image: %s", idx, total, detail_url)
        except Exception as exc:
            logging.warning("Detail tab crawl failed (%s): %s", detail_url, exc)
        finally:
            try:
                if tab is not None:
                    logging.info("Detail tab %s/%s closing: %s", idx, total, detail_url)
                    tab.close()
            except Exception:
                pass

    return dedupe_keep_order(collected)


def extract_download_url_from_tab(tab):
    selectors = [
        "a[download]",
        "a[href*='download']",
        "a:has-text('Download')",
        "button:has-text('Download')",
        "[class*='download'] a",
        "[id*='download'] a",
        "[class*='download']",
        "[id*='download']",
    ]

    for sel in selectors:
        try:
            elements = tab.query_selector_all(sel)
        except Exception:
            elements = []

        for el in elements:
            try:
                raw = (
                    el.get_attribute("href")
                    or el.get_attribute("data-href")
                    or el.get_attribute("data-url")
                    or el.get_attribute("data-download")
                )
                if raw:
                    candidate = urljoin(tab.url, raw)
                    if is_http_url(candidate):
                        meta = probe_url(candidate, headers={"User-Agent": DEFAULT_UA, "Referer": tab.url}, timeout=8)
                        ct = (meta.get("content_type") or "").lower()
                        if meta.get("ok") and (ct.startswith("image/") or has_any_ext(candidate, IMAGE_EXTS)):
                            logging.info("Download button URL selected: %s", candidate)
                            return candidate
                onclick = el.get_attribute("onclick") or ""
                match = re.search(r"https?://[^'\"\\s]+", onclick)
                if match:
                    candidate = match.group(0)
                    meta = probe_url(candidate, headers={"User-Agent": DEFAULT_UA, "Referer": tab.url}, timeout=8)
                    ct = (meta.get("content_type") or "").lower()
                    if meta.get("ok") and (ct.startswith("image/") or has_any_ext(candidate, IMAGE_EXTS)):
                        logging.info("Download button onclick URL selected: %s", candidate)
                        return candidate
            except Exception:
                continue

    return None


def send_images(bot_client, chat_id, images, page_url, limit=10, send_as_document=True, min_size_kb=0):
    parsed = urlparse(page_url)
    domain = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else page_url

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": domain,
    }

    sent = 0
    max_to_send = limit if limit is not None else len(images)
    candidate_images = choose_best_images_for_send(images, headers, limit=max_to_send, probe_pool=40)

    for original_img_url in candidate_images:
        if sent >= max_to_send:
            break

        img_url = select_best_image_candidate(original_img_url, headers)
        if TRACE_URLS:
            logging.info("Send image candidate: original=%s selected=%s", original_img_url, img_url)

        probe = probe_url(img_url, headers=headers, timeout=8)
        if not is_probe_image_ok(probe, img_url):
            if VERBOSE_MEDIA_LOGS:
                logging.info(
                    "Skip send non-image/bad URL: %s (status=%s ct=%s)",
                    img_url,
                    probe.get("status_code", 0),
                    probe.get("content_type", ""),
                )
            continue

        try:
            head = requests.head(img_url, timeout=7, allow_redirects=True)
            size = int(head.headers.get("content-length", 0))
            if min_size_kb and size and size < (min_size_kb * 1024):
                logging.info("Skipped small image (<%sKB): %s", min_size_kb, img_url)
                continue
        except Exception:
            pass

        try:
            if send_as_document:
                bot_client.send_document(chat_id, img_url)
            else:
                bot_client.send_photo(chat_id, img_url)
            sent += 1
            logging.info("Sent image via URL (%s/%s)", sent, max_to_send)
            continue
        except Exception as exc:
            logging.warning("Direct photo send failed, downloading: %s", exc)

        try:
            res = requests.get(img_url, headers=headers, timeout=15)
            if res.status_code == 200:
                if send_as_document:
                    file_obj = io.BytesIO(res.content)
                    file_obj.name = "image.jpg"
                    bot_client.send_document(chat_id, file_obj)
                else:
                    bot_client.send_photo(chat_id, res.content)
                sent += 1
                logging.info("Sent image via download (%s/%s)", sent, max_to_send)
            elif VERBOSE_MEDIA_LOGS:
                logging.info("Image download not OK: %s status=%s", img_url, res.status_code)
        except Exception as exc:
            logging.warning("Final image send failed: %s", exc)

    return sent


def send_videos(bot_client, chat_id, videos, page_url, limit=2):
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": page_url,
    }

    sent = 0
    for vid_url in videos[:limit]:
        if not is_http_url(vid_url):
            logging.info("Skipping non-http video URL: %s", vid_url)
            continue

        try:
            if ".m3u8" in vid_url.lower():
                ydl_opts = {
                    "quiet": True,
                    "format": "best",
                    "noplaylist": True,
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(vid_url, download=False)
                    direct = info.get("url")
                if direct:
                    bot_client.send_video(chat_id, direct)
                    sent += 1
                    continue

            res = requests.get(vid_url, headers=headers, timeout=15, stream=True)
            if res.status_code == 200:
                bot_client.send_video(chat_id, vid_url)
                sent += 1
                continue

            logging.warning("Video GET check failed: %s", vid_url)
        except Exception as exc:
            logging.warning("Primary video send error: %s", exc)

        try:
            ydl_opts = {"quiet": True, "format": "best", "noplaylist": True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(vid_url, download=False)
                direct = info.get("url")
            if direct:
                bot_client.send_video(chat_id, direct)
                sent += 1
        except Exception as exc:
            logging.warning("Video fallback extraction failed: %s", exc)

    return sent


def detect_site(url):
    lower = url.lower()
    if "instagram.com" in lower:
        return "instagram"
    if "x.com" in lower or "twitter.com" in lower:
        return "twitter"
    if "pixabay.com" in lower:
        return "pixabay"
    if "youtube.com" in lower or "youtu.be" in lower:
        return "youtube"
    if "sharechat.com" in lower:
        return "sharechat"
    return "generic"


def is_dynamic(url):
    return any(k in url.lower() for k in ["instagram", "youtube", "twitter", "x.com"])


def static_scrape(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.google.com/",
    }

    res = requests.get(url, headers=headers, timeout=20)
    if res.status_code == 403:
        logging.warning("403 detected (blocked)")
        return {"title": "Blocked", "images": [], "videos": [], "blocked": True}

    soup = BeautifulSoup(res.text, "html.parser")
    title = soup.title.string.strip() if soup.title and soup.title.string else "No title"

    images = []
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src")
        if src:
            abs_url = urljoin(url, src)
            if is_valid_media(abs_url):
                images.append(abs_url)
                images.extend(expand_image_candidates(abs_url))

    videos = []
    for v in soup.find_all("video"):
        src = v.get("src")
        if src:
            abs_url = urljoin(url, src)
            if is_valid_media(abs_url):
                videos.append(abs_url)

    # Crawl likely detail pages to collect full-size images even when thumbnails exist.
    detail_links = collect_detail_page_links_from_soup(soup, url, max_links=30)
    if VERBOSE_MEDIA_LOGS:
        logging.info("Static detail links discovered=%s for %s", len(detail_links), url)
    detail_images = crawl_detail_pages_for_images(detail_links, url, max_pages=25)
    if detail_images:
        # Prefer detail-page images by placing them first before dedupe/sort.
        images = detail_images + images
    if VERBOSE_MEDIA_LOGS:
        logging.info("Static detail images added=%s", len(detail_images))

    images = dedupe_keep_order(images)
    videos = dedupe_keep_order(videos)
    images = sorted(images, key=score_url, reverse=True)
    images, videos = filter_media_by_source_context(url, images, videos)
    images = filter_relevant_images(url, images)
    if VERBOSE_MEDIA_LOGS:
        logging.info("Static final media count images=%s videos=%s", len(images), len(videos))

    return {
        "title": title,
        "images": images,
        "videos": videos,
        "blocked": False,
    }


def run_page_strategy(page, strategy):
    if strategy == "scroll":
        logging.info("Using scroll strategy")
        for _ in range(6):
            page.mouse.wheel(0, 6000)
            page.wait_for_timeout(1800)
    elif strategy == "lazy_load":
        logging.info("Using lazy-load strategy")
        page.wait_for_timeout(6000)
    elif strategy == "static":
        logging.info("Using static DOM strategy")
    else:
        logging.info("Unknown strategy, fallback short scroll")
        for _ in range(3):
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(1500)


def collect_dom_media(page):
    media_urls = []

    def normalize(urls, expect_media=False):
        out = []
        for raw in urls:
            if not raw:
                continue
            normalized = urljoin(page.url, raw)
            if not is_http_url(normalized):
                continue
            if is_blocked_or_junk_url(normalized):
                continue
            if expect_media or is_valid_media(normalized):
                out.append(normalized)
        return out

    dom_images = page.eval_on_selector_all(
        "img",
        """els => els.map(e =>
            e.src ||
            e.getAttribute('data-src') ||
            e.getAttribute('data-original') ||
            e.getAttribute('data-lazy')
        )""",
    )
    media_urls.extend(normalize(dom_images, expect_media=True))

    highres_attr_images = page.eval_on_selector_all(
        "img",
        """els => {
            const attrs = ['data-full','data-original','data-zoom-image','data-large-file','data-image','data-url'];
            const out = [];
            for (const e of els) {
                for (const a of attrs) {
                    const v = e.getAttribute(a);
                    if (v) out.push(v);
                }
            }
            return out;
        }""",
    )
    media_urls.extend(normalize(highres_attr_images, expect_media=True))

    srcset_urls = page.eval_on_selector_all(
        "img",
        """els => {
            const out = [];
            for (const e of els) {
                const sets = [e.getAttribute('srcset'), e.getAttribute('data-srcset')].filter(Boolean);
                for (const set of sets) {
                    for (const part of set.split(',')) {
                        const url = part.trim().split(' ')[0];
                        if (url) out.push(url);
                    }
                }
            }
            return out;
        }""",
    )
    media_urls.extend(normalize(srcset_urls, expect_media=True))

    anchor_urls = page.eval_on_selector_all(
        "a[href]",
        "els => els.map(e => e.href || e.getAttribute('href'))",
    )
    media_urls.extend(normalize(anchor_urls, expect_media=True))

    dom_videos = page.eval_on_selector_all(
        "video, source",
        "els => els.map(e => e.src || e.getAttribute('src'))",
    )
    media_urls.extend(normalize(dom_videos, expect_media=True))

    meta_media = page.eval_on_selector_all(
        "meta[property='og:image'], meta[property='og:video'], meta[property='og:video:url'], meta[name='twitter:image'], meta[name='twitter:player:stream']",
        "els => els.map(e => e.getAttribute('content'))",
    )
    media_urls.extend(normalize(meta_media, expect_media=True))

    if VERBOSE_MEDIA_LOGS:
        logging.info("DOM media collected raw count=%s on %s", len(media_urls), page.url)
        if TRACE_URLS and media_urls:
            for idx, media_url in enumerate(media_urls[:20], start=1):
                logging.info("DOM media url [%s]: %s", idx, media_url)
    return media_urls


def click_open_images_for_hd(page, media_urls, max_clicks=6):
    try:
        clickable_images = page.query_selector_all("img")
        if not clickable_images:
            return 0

        # Prioritize likely content images over tiny UI assets.
        def image_score(img):
            src = (img.get_attribute("src") or img.get_attribute("data-src") or "").lower()
            score = len(src)
            if any(x in src for x in ["thumb", "icon", "logo", "avatar", "sprite"]):
                score -= 1000
            return score

        clickable_images = sorted(clickable_images, key=image_score, reverse=True)[: max_clicks * 3]
        clicked = 0

        for i, img in enumerate(clickable_images):
            if clicked >= max_clicks:
                break

            try:
                src_preview = img.get_attribute("src") or img.get_attribute("data-src") or ""
                if not src_preview:
                    continue
                low = src_preview.lower()
                if any(x in low for x in ["icon", "logo", "avatar", "thumb", "sprite"]):
                    continue

                current_url = page.url
                logging.info("[CLICK] Trying image %s src=%s", i, src_preview)

                parent_link = None
                try:
                    parent_link = img.evaluate_handle("el => el.closest('a')")
                except Exception:
                    parent_link = None

                new_page = None
                try:
                    with page.context.expect_page(timeout=2500) as new_page_info:
                        img.scroll_into_view_if_needed()
                        if parent_link:
                            parent_link.click()
                        else:
                            img.click()
                    new_page = new_page_info.value
                except Exception:
                    new_page = None

                if new_page is not None:
                    clicked += 1
                    logging.info("[CLICK] New tab opened for image %s", i)
                    try:
                        new_page.wait_for_load_state("domcontentloaded", timeout=12000)
                    except Exception:
                        pass
                    handle_popups(new_page)
                    new_page.wait_for_timeout(1000)

                    dl = extract_download_url_from_tab(new_page)
                    if dl:
                        media_urls.append(dl)
                        logging.info("[HD-DOWNLOAD-BTN] %s", dl)

                    tab_media = collect_dom_media(new_page)
                    media_urls.extend(tab_media)
                    if TRACE_URLS and tab_media:
                        for j, u in enumerate(tab_media[:10], start=1):
                            logging.info("[HD-NEWTAB-%s] %s", j, u)

                    try:
                        new_page.close()
                    except Exception:
                        pass
                    continue

                # Same-tab navigation case
                page.wait_for_timeout(1200)
                if page.url != current_url:
                    clicked += 1
                    logging.info("[CLICK] Same-tab navigation for image %s -> %s", i, page.url)

                    dl = extract_download_url_from_tab(page)
                    if dl:
                        media_urls.append(dl)
                        logging.info("[HD-DOWNLOAD-BTN] %s", dl)

                    nav_media = collect_dom_media(page)
                    media_urls.extend(nav_media)
                    if TRACE_URLS and nav_media:
                        for j, u in enumerate(nav_media[:10], start=1):
                            logging.info("[HD-NAV-%s] %s", j, u)

                    try:
                        page.go_back(timeout=12000)
                        page.wait_for_timeout(800)
                    except Exception:
                        pass
                    continue

                # Modal/lightbox case
                modal_media = collect_dom_media(page)
                if modal_media:
                    clicked += 1
                    media_urls.extend(modal_media)
                    logging.info("[CLICK] Modal/media capture for image %s count=%s", i, len(modal_media))
                    if TRACE_URLS:
                        for j, u in enumerate(modal_media[:10], start=1):
                            logging.info("[HD-MODAL-%s] %s", j, u)

                try:
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(600)
                except Exception:
                    pass

            except Exception as exc:
                logging.warning("Click failed: %s", exc)
                continue

        return clicked
    except Exception as exc:
        logging.warning("Click system failed: %s", exc)
        return 0


def _dynamic_scrape_on_page(page, url):
    media_urls = []
    response_image_urls = set()
    response_video_urls = set()
    title = "No title"
    handle_response = None

    try:
        def handle_response(response):
            try:
                candidate = response.url
                content_type = (response.headers.get("content-type") or "").lower()
                is_video_type = content_type.startswith("video/") or "application/vnd.apple.mpegurl" in content_type
                is_image_type = content_type.startswith("image/")
                if is_blocked_or_junk_url(candidate):
                    return
                if is_image_type and is_http_url(candidate):
                    cand_lower = candidate.lower()
                    if any(x in cand_lower for x in ["orig", "large", "1080", "1920", "sources", "full", "download"]):
                        media_urls.append(candidate)
                        response_image_urls.add(candidate)
                    elif has_any_ext(candidate, IMAGE_EXTS):
                        media_urls.append(candidate)
                        response_image_urls.add(candidate)
                elif is_video_type and is_http_url(candidate):
                    media_urls.append(candidate)
                    response_video_urls.add(candidate)
                elif has_any_ext(candidate, MEDIA_EXTS) and is_valid_media(candidate):
                    media_urls.append(candidate)
            except Exception as exc:
                logging.warning("Response hook error: %s", exc)

        page.on("response", handle_response)

        try:
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(2500)
        except Exception as exc:
            logging.warning("Timeout/loading error for %s: %s", url, exc)
            return {"title": "Timeout", "images": [], "videos": []}

        if is_protection_page(page):
            logging.warning("Protection page detected for %s", url)
            return {"title": "Blocked by site protection", "images": [], "videos": [], "blocked": True}

        handle_popups(page)
        page.wait_for_timeout(2000)

        analysis = analyze_page(page)
        strategy = decide_strategy(analysis)
        logging.info("Analysis: %s", analysis)
        logging.info("Strategy: %s", strategy)

        run_page_strategy(page, strategy)
        clicked_count = click_open_images_for_hd(page, media_urls, max_clicks=10)
        logging.info("Click extraction interacted with %s images", clicked_count)
        dom_urls = collect_dom_media(page)
        media_urls.extend(dom_urls)
        if VERBOSE_MEDIA_LOGS:
            logging.info("After DOM extraction count=%s", len(media_urls))
        detail_links = collect_detail_page_links_from_dom(page, max_links=20)
        if VERBOSE_MEDIA_LOGS:
            logging.info("Detail links discovered (dom)=%s", len(detail_links))
            if TRACE_URLS and detail_links:
                for idx, link in enumerate(detail_links[:30], start=1):
                    logging.info("Detail link [%s]: %s", idx, link)
        if detail_links:
            detail_images = crawl_detail_pages_for_images(detail_links, page.url, max_pages=20)
            media_urls.extend(detail_images)
            if VERBOSE_MEDIA_LOGS:
                logging.info("Detail images added=%s total_now=%s", len(detail_images), len(media_urls))
            tab_images = crawl_detail_pages_with_tabs(page, detail_links, max_pages=12)
            media_urls.extend(tab_images)
            if VERBOSE_MEDIA_LOGS:
                logging.info("Detail tab images added=%s total_now=%s", len(tab_images), len(media_urls))
        title = page.title() or "No title"

    except Exception as exc:
        logging.error("Dynamic scrape error: %s", exc, exc_info=True)
        return {"title": "Error", "images": [], "videos": []}
    finally:
        if handle_response is not None:
            try:
                # Prevent response listeners from stacking when reusing the same page.
                page.remove_listener("response", handle_response)
            except Exception:
                pass

    media_urls = dedupe_keep_order(media_urls)
    if VERBOSE_MEDIA_LOGS:
        logging.info("Post-dedupe media count=%s", len(media_urls))
    media_urls = [u for u in media_urls if is_http_url(u) and not is_blocked_or_junk_url(u)]
    if VERBOSE_MEDIA_LOGS:
        logging.info("Post-http/junk-filter media count=%s", len(media_urls))

    expanded = []
    for u in media_urls:
        if has_any_ext(u, IMAGE_EXTS):
            expanded.extend(expand_image_candidates(u))
        else:
            expanded.append(u)
    media_urls = dedupe_keep_order(expanded)
    if VERBOSE_MEDIA_LOGS:
        logging.info("Post-expand media count=%s", len(media_urls))
    media_urls = [u for u in media_urls if is_valid_media(u) or u in response_image_urls or u in response_video_urls]
    if VERBOSE_MEDIA_LOGS:
        logging.info(
            "Post-valid-filter media count=%s (typed_images=%s typed_videos=%s)",
            len(media_urls),
            len(response_image_urls),
            len(response_video_urls),
        )

    media_urls = sorted(media_urls, key=score_url, reverse=True)

    images = [u for u in media_urls if has_any_ext(u, IMAGE_EXTS) or u in response_image_urls]
    videos = [u for u in media_urls if has_any_ext(u, VIDEO_EXTS) or ".m3u8" in u.lower() or u in response_video_urls]
    images, videos = filter_media_by_source_context(url, images, videos)
    images = filter_relevant_images(url, images)

    def extract_page_number(candidate):
        m = re.search(r"hr_(\d+)", candidate)
        return int(m.group(1)) if m else 0

    images = sorted(images, key=score_url, reverse=True)
    videos = sorted(videos, key=score_url, reverse=True)

    logging.info("Final images: %s", len(images))
    logging.info("Final videos: %s", len(videos))

    return {
        "title": title,
        "images": images,
        "videos": videos,
        "blocked": False,
    }


def dynamic_scrape(url):
    logging.info("Dynamic scrape started: %s", url)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=DEFAULT_UA,
                locale="en-US",
                viewport={"width": 1366, "height": 768},
                extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
            )
            page = context.new_page()
            result = _dynamic_scrape_on_page(page, url)
            context.close()
            browser.close()
            return result
    except Exception as exc:
        logging.error("Dynamic wrapper error: %s", exc, exc_info=True)
        return {"title": "Error", "images": [], "videos": []}


def scrape_youtube(url):
    ydl_opts = {
        "quiet": True,
        "format": "best",
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    return {
        "title": info.get("title", "YouTube"),
        "images": [],
        "videos": [info.get("url")],
        "blocked": False,
    }


def smart_scrape(url):
    logging.info("Starting scrape for: %s", url)
    site = detect_site(url)
    logging.info("Detected site: %s", site)

    try:
        if looks_like_direct_media_url(url):
            direct = scrape_direct_media_url(url)
            if direct:
                return direct

        if site == "youtube":
            return scrape_youtube(url)
        # Force browser-interaction path so thumbnail click/open logic always runs.
        return dynamic_scrape(url)
    except Exception as exc:
        logging.warning("Error in smart_scrape, falling back to dynamic: %s", exc)
        return dynamic_scrape(url)


def scrape_chapter(base_url, bot_client, chat_id, max_pages=50):
    all_images = []
    seen = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=DEFAULT_UA,
            locale="en-US",
            viewport={"width": 1366, "height": 768},
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )
        page = context.new_page()

        for i in range(1, max_pages + 1):
            if i == 1 or i % 5 == 0:
                bot_client.send_message(chat_id, f"Scraping page {i}...")

            page_url = f"{base_url}{i}/"
            logging.info("Scraping chapter page %s: %s", i, page_url)

            data = _dynamic_scrape_on_page(page, page_url)
            page_images = data.get("images", []) if data else []

            if not page_images:
                logging.info("Stopping chapter scrape: no images on page %s", i)
                break

            added = 0
            for img in page_images:
                if img not in seen:
                    seen.add(img)
                    all_images.append(img)
                    added += 1

            logging.info("Chapter page %s added %s images (total=%s)", i, added, len(all_images))
            if added == 0:
                logging.info("Stopping chapter scrape: no new images")
                break

        context.close()
        browser.close()

    return all_images


def scrape_with_pagination(base_url, max_pages=5):
    all_media = []

    for i in range(1, max_pages + 1):
        url = f"{base_url}?page={i}"
        logging.info("Scraping paginated URL %s: %s", i, url)

        data = dynamic_scrape(url)
        images = data.get("images", []) if data else []

        if not images:
            logging.info("Pagination stop: no images")
            break

        if len(images) < 3:
            logging.info("Pagination stop: likely end (few images)")
            break

        all_media.extend(images)

    return dedupe_keep_order(all_media)


@bot.message_handler(commands=["start"])
def start(msg):
    bot.reply_to(msg, "Send me any URL and I will scrape it.")


@bot.message_handler(func=lambda m: True)
def handle(msg):
    url = (msg.text or "").strip()
    logging.info("Received input: %s", url)

    if not url.startswith("http"):
        bot.reply_to(msg, "Send a valid URL starting with http/https.")
        return

    bot.reply_to(msg, "Scraping...")

    try:
        base_url = get_base_url(url)
        if base_url:
            logging.info("Chapter pattern detected for %s", url)
            images = scrape_chapter(base_url, bot, msg.chat.id)
            data = {
                "title": "Chapter Download",
                "images": images,
                "videos": [],
                "blocked": False,
            }
        else:
            data = smart_scrape(url)

        if not data:
            bot.send_message(msg.chat.id, "Failed to scrape data.")
            return

        title = data.get("title", "No title")
        images = data.get("images", [])
        videos = data.get("videos", [])
        blocked = data.get("blocked", False)

        if blocked and not images and not videos:
            bot.send_message(
                msg.chat.id,
                "This site is blocking automated access (HTTP 403 / protection page), so no media can be fetched right now.",
            )
            return

        summary = (
            f"Title: {title}\n"
            f"Images: {len(images)}\n"
            f"Videos: {len(videos)}"
        )
        bot.send_message(msg.chat.id, summary)

        image_limit = None if base_url else 10
        sent_images = 0
        if images:
            sent_images = send_images(bot, msg.chat.id, images, url, limit=image_limit)

        sent_videos = 0
        if videos:
            sent_videos = send_videos(bot, msg.chat.id, videos, url, limit=2)

        if sent_images == 0 and sent_videos == 0:
            bot.send_message(msg.chat.id, "Scraped media, but Telegram could not deliver files from the source URLs.")

    except Exception as exc:
        logging.error("Handle error: %s", exc, exc_info=True)
        bot.send_message(msg.chat.id, "Error occurred while scraping.")


if __name__ == "__main__":
    bot.infinity_polling(skip_pending=True, timeout=30, long_polling_timeout=30)
