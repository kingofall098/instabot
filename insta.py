import io
import logging
import os
import re
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

TOKEN = "8755937047:AAHBFaKCan-W8QLls2DDJ3-XpUdyw3tP16w"
if not TOKEN:
    raise RuntimeError("Set TELEGRAM_BOT_TOKEN environment variable")

bot = telebot.TeleBot(TOKEN)

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")
VIDEO_EXTS = (".mp4", ".webm")
MEDIA_EXTS = IMAGE_EXTS + VIDEO_EXTS
DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"


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


def score_url(url):
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
        "thumb",
        "sprite",
        "banner",
        "popup",
        "favicon",
        "emoji",
    ]
    if any(k in lower for k in bad_keywords):
        return True
    if "doubleclick" in lower or "googlesyndication" in lower:
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


def expand_image_candidates(url):
    if not url:
        return []

    candidates = [url]

    # Common size tokens in image CDNs: /236x/... or /960x540/... etc.
    sized_path = re.search(r"/\d{2,4}x\d{2,4}(?:_[a-z]+)?/", url, flags=re.IGNORECASE)
    if sized_path:
        candidates.append(re.sub(r"/\d{2,4}x\d{2,4}(?:_[a-z]+)?/", "/originals/", url, flags=re.IGNORECASE))
        candidates.append(re.sub(r"/\d{2,4}x\d{2,4}(?:_[a-z]+)?/", "/1200x/", url, flags=re.IGNORECASE))

    # Remove width/height quality params that often force thumbnails.
    stripped = re.sub(r"([?&])(w|h|width|height|quality|q|resize)=[^&]+", "", url, flags=re.IGNORECASE)
    stripped = re.sub(r"\?&", "?", stripped).rstrip("?&")
    if stripped and stripped != url:
        candidates.append(stripped)

    return dedupe_keep_order(candidates)


def send_images(bot_client, chat_id, images, page_url, limit=10, send_as_document=True, min_size_kb=0):
    parsed = urlparse(page_url)
    domain = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else page_url

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": domain,
    }

    sent = 0
    max_to_send = limit if limit is not None else len(images)

    for img_url in images:
        if sent >= max_to_send:
            break

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
        return {"title": "Blocked", "images": [], "videos": []}

    soup = BeautifulSoup(res.text, "html.parser")
    title = soup.title.string.strip() if soup.title and soup.title.string else "No title"

    images = []
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src")
        if src:
            abs_url = urljoin(url, src)
            if is_valid_media(abs_url):
                images.append(abs_url)

    videos = []
    for v in soup.find_all("video"):
        src = v.get("src")
        if src:
            abs_url = urljoin(url, src)
            if is_valid_media(abs_url):
                videos.append(abs_url)

    images = dedupe_keep_order(images)
    videos = dedupe_keep_order(videos)

    return {
        "title": title,
        "images": images,
        "videos": videos,
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

    return media_urls


def _dynamic_scrape_on_page(page, url):
    media_urls = []
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
                if (is_video_type or is_image_type) and is_http_url(candidate):
                    media_urls.append(candidate)
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

        handle_popups(page)
        page.wait_for_timeout(2000)

        analysis = analyze_page(page)
        strategy = decide_strategy(analysis)
        logging.info("Analysis: %s", analysis)
        logging.info("Strategy: %s", strategy)

        run_page_strategy(page, strategy)
        media_urls.extend(collect_dom_media(page))
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
    media_urls = [u for u in media_urls if is_valid_media(u)]

    expanded = []
    for u in media_urls:
        if has_any_ext(u, IMAGE_EXTS):
            expanded.extend(expand_image_candidates(u))
        else:
            expanded.append(u)
    media_urls = dedupe_keep_order(expanded)
    media_urls = [u for u in media_urls if is_valid_media(u)]

    media_urls = sorted(media_urls, key=score_url, reverse=True)

    images = [u for u in media_urls if has_any_ext(u, IMAGE_EXTS)]
    videos = [u for u in media_urls if has_any_ext(u, VIDEO_EXTS) or ".m3u8" in u.lower()]

    def extract_page_number(candidate):
        m = re.search(r"hr_(\d+)", candidate)
        return int(m.group(1)) if m else 0

    images = sorted(images, key=extract_page_number)
    videos = sorted(videos, key=score_url, reverse=True)

    logging.info("Final images: %s", len(images))
    logging.info("Final videos: %s", len(videos))

    return {
        "title": title,
        "images": images,
        "videos": videos,
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
    }


def smart_scrape(url):
    logging.info("Starting scrape for: %s", url)
    site = detect_site(url)
    logging.info("Detected site: %s", site)

    try:
        if site == "youtube":
            return scrape_youtube(url)

        if is_dynamic(url):
            return dynamic_scrape(url)

        data = static_scrape(url)
        if not data["images"] and not data["videos"]:
            logging.warning("Static scrape returned no media; falling back to dynamic")
            return dynamic_scrape(url)

        return data
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
            }
        else:
            data = smart_scrape(url)

        if not data:
            bot.send_message(msg.chat.id, "Failed to scrape data.")
            return

        title = data.get("title", "No title")
        images = data.get("images", [])
        videos = data.get("videos", [])

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
    bot.infinity_polling(skip_pending=True)


