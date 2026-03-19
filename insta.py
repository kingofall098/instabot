import io
import logging
import os
import re
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

BUILD_TAG = "v2-rewrite-newtab-sequential-v2"
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif")
MAX_IMAGES = int(os.getenv("MAX_IMAGES", "50"))

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("Set TELEGRAM_BOT_TOKEN environment variable")

bot = telebot.TeleBot(TOKEN)


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


def is_junk_image_url(url: str) -> bool:
    lower = (url or "").lower()
    bad = ["logo", "icon", "sprite", "favicon", "/contents/categories/", "last_category"]
    return any(x in lower for x in bad)


def extract_megatube_album_id(page_url: str):
    m = re.search(r"/albums/(\d+)/", page_url.lower())
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


def filter_candidates_for_page(page_url: str, candidates):
    cleaned = [u for u in candidates if is_http_url(u) and looks_like_image_url(u) and not is_junk_image_url(u)]

    lower_page = page_url.lower()
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
                return dedupe_keep_order(album_only)

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
        candidates = [urljoin(tab.url, x) for x in dom_imgs if x]
        if is_http_url(final_url):
            candidates.insert(0, final_url)

        for u in dedupe_keep_order(candidates):
            if is_http_url(u) and looks_like_image_url(u) and not is_junk_image_url(u):
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
            response_urls = []

            def on_response(resp):
                try:
                    ct = (resp.headers.get("content-type") or "").lower()
                    if ct.startswith("image/") and is_http_url(resp.url):
                        response_urls.append(resp.url)
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
            raw_candidates.extend(response_urls)
            if not raw_candidates:
                raw_candidates.extend(fetch_candidates_via_requests(page.url))
            candidates = filter_candidates_for_page(page.url, raw_candidates)[:MAX_IMAGES]
            total_found = len(candidates)

            bot.send_message(chat_id, f"Found {total_found} page images. Opening each in a new tab and downloading one by one.")
            logging.info("Image candidates filtered=%s raw=%s url=%s", total_found, len(raw_candidates), page_url)
            if total_found == 0:
                bot.send_message(chat_id, "No downloadable images found on this page (it may be protected or dynamically blocked).")
                return 0, 0

            sent = 0
            for idx, candidate in enumerate(candidates, start=1):
                resolved = resolve_image_in_new_tab(context, page.url, candidate)
                if not resolved:
                    continue

                raw, ext = download_image_bytes(resolved, page.url)
                if not raw:
                    continue

                file_obj = io.BytesIO(raw)
                file_obj.name = f"image_{idx}{ext}"
                bot.send_document(chat_id, file_obj)
                sent += 1
                logging.info("Sent image %s/%s from %s", sent, total_found, resolved)

            bot.send_message(chat_id, f"Done. Sent {sent} images.")
            return sent, total_found
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
    bot.reply_to(msg, "Send a webpage URL. I will count pictures, open each in a new tab, and download/send one-by-one.")


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
