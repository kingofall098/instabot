import telebot
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from urllib.parse import urljoin

TOKEN = "8755937047:AAHBFaKCan-W8QLls2DDJ3-XpUdyw3tP16w"
bot = telebot.TeleBot(TOKEN)
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
def score_url(url):
    score = 0
    url = url.lower()

    if "large" in url or "original" in url:
        score += 3
    if "media" in url:
        score += 2
    if len(url) > 100:
        score += 1

    return score
def is_valid_media(url):
    url = url.lower()
    # ❌ remove thumbnails / UI junk
    if any(x in url for x in ["thumb", "small", "icon", "logo", "sprite"]):
        return False

    # ❌ remove svg/ico
    if url.endswith(".svg") or url.endswith(".ico"):
        return False
    # must be media type
    if not any(ext in url for ext in [".jpg", ".jpeg", ".png", ".webp", ".mp4", ".webm"]):
        return False

    # reject common junk
    bad_keywords = ["logo", "icon", "avatar", "thumb", "sprite", "ads", "banner"]

    if any(bad in url for bad in bad_keywords):
        return False

    # reject very small images
    if "s150x150" in url or "small" in url:
        return False

    return True
from urllib.parse import urlparse

def send_images(bot, chat_id, images, page_url):
    domain = urlparse(page_url).scheme + "://" + urlparse(page_url).netloc

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": domain   # 🔥 dynamic referer
    }

    sent = 0

    for img_url in images:
        if sent >= 5:
            break

        try:
            res = requests.get(img_url, headers=headers, timeout=10)

            if res.status_code == 200 and len(res.content) > 5000:
                bot.send_photo(chat_id, res.content)
                logging.info(f"Sent image {sent+1}")
                sent += 1
            else:
                logging.warning(f"Skipped bad image: {img_url}")

        except Exception as e:
            logging.warning(f"Send error: {e}")
def send_videos(bot, chat_id, videos):
    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    for vid_url in videos[:2]:
        try:
            res = requests.get(vid_url, headers=headers, timeout=15)

            if res.status_code == 200:
                bot.send_video(chat_id, res.content)
            else:
                logging.warning(f"Video failed: {vid_url}")

        except Exception as e:
            logging.warning(f"Video error: {e}")
# -------------------------
# MAIN ENGINE
# -------------------------

def smart_scrape(url):
    logging.info(f"Starting scrape for: {url}")

    try:
        if is_dynamic(url):
            logging.info("Using dynamic scraper (keyword match)")
            return dynamic_scrape(url)

        # try static first
        data = static_scrape(url)

        # 🔥 if blocked → fallback to dynamic
        if not data["images"] and not data["videos"]:
            logging.warning("Static failed → switching to dynamic")
            return dynamic_scrape(url)

        return data

    except Exception as e:
        logging.warning(f"Static error → switching to dynamic: {e}")
        return dynamic_scrape(url)
# -------------------------
# DETECTION
# -------------------------
def is_dynamic(url):
    keywords = ["instagram", "youtube", "twitter", "x.com"]
    return any(k in url.lower() for k in keywords)

# -------------------------
# STATIC SCRAPER
# -------------------------
def static_scrape(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.google.com/"
    }

    res = requests.get(url, headers=headers, timeout=15)
    soup = BeautifulSoup(res.text, "html.parser")

    title = soup.title.string.strip() if soup.title else "No title"
    if res.status_code == 403:
        logging.warning("403 detected (blocked)")
        return {"title": "Blocked", "images": [], "videos": []}
    images = []
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src")
        if src:
            images.append(urljoin(url, src))  # FIXED

    videos = []
    for v in soup.find_all("video"):
        src = v.get("src")
        if src:
            videos.append(urljoin(url, src))

    return {
        "title": title,
        "images": list(set(images)),  # remove duplicates
        "videos": list(set(videos))
    }

# -------------------------
# DYNAMIC SCRAPER
# -------------------------

def dynamic_scrape(url):
    logging.info("Deep scraping started (network mode)")

    media_urls = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            def handle_response(response):
                try:
                    url = response.url.lower()

                    # capture anything that LOOKS like media
                    if any(ext in url for ext in [
                        ".jpg", ".jpeg", ".png", ".webp", ".gif",
                        ".mp4", ".webm", ".m3u8"
                    ]):
                        media_urls.append(response.url)

                except Exception as e:
                    logging.warning(f"Response error: {e}")

            page.on("response", handle_response)

            page.goto(url, timeout=60000)
            page.wait_for_timeout(3000)

            for i in range(6):
                page.mouse.wheel(0, 6000)
                page.wait_for_timeout(2000)
            # 🔥 DOM IMAGE EXTRACTION
            dom_images = page.eval_on_selector_all(
                "img",
                "els => els.map(e => e.src || e.getAttribute('data-src') || e.getAttribute('data-original'))"
            )

            for img in dom_images:
                if img:
                    media_urls.append(img)


            # 🔥 EXTRACT FROM <a> TAGS (VERY IMPORTANT)
            links = page.eval_on_selector_all(
                "a",
                "els => els.map(e => e.href)"
            )

            for link in links:
                if link and any(ext in link.lower() for ext in [".jpg", ".jpeg", ".png", ".webp"]):
                    media_urls.append(link)
            title = page.title()

            browser.close()

    except Exception as e:
        logging.error(f"Dynamic scrape error: {e}", exc_info=True)
        return {"title": "Error", "images": [], "videos": []}

    # ALWAYS runs
    # keep order + remove duplicates
    # remove duplicates
    seen = set()
    media_urls = [u for u in media_urls if not (u in seen or seen.add(u))]

    # filter valid
    media_urls = [u for u in media_urls if is_valid_media(u)]

    # sort best first
    media_urls = sorted(media_urls, key=score_url, reverse=True)

    # filter
    images = [u for u in media_urls if any(ext in u for ext in [".jpg", ".png", ".webp"])]
    videos = [u for u in media_urls if any(ext in u for ext in [".mp4", ".webm", ".m3u8"])]

    # rank
    images = sorted(images, key=score_url, reverse=True)
    videos = sorted(videos, key=score_url, reverse=True)
    logging.info(f"Final Images: {len(images)}")
    logging.info(f"Final Videos: {len(videos)}")

    return {
        "title": title if title else "No title",
        "images": images,
        "videos": videos
    }
# -------------------------
# BOT
# -------------------------
@bot.message_handler(commands=['start'])
def start(msg):
    bot.reply_to(msg, "Send me any URL and I will scrape it 🔍")

@bot.message_handler(func=lambda m: True)
def handle(msg):
    url = msg.text.strip()
    logging.info(f"Received URL from user: {url}")

    if not url.startswith("http"):
        bot.reply_to(msg, "❌ Send a valid URL")
        return

    bot.reply_to(msg, "⏳ Scraping...")

    try:
        data = smart_scrape(url)

        if not data:
            bot.send_message(msg.chat.id, "❌ Failed to scrape data")
            return

        logging.info("Scraping completed successfully")

        response = f"📄 Title: {data['title']}\n"
        response += f"🖼 Images: {len(data['images'])}\n"
        response += f"🎥 Videos: {len(data['videos'])}\n"

        bot.send_message(msg.chat.id, response)

        logging.info(f"Images: {len(data['images'])}, Videos: {len(data['videos'])}")

        # 🔥 SEND MEDIA HERE
        if data['images']:
            send_images(bot, msg.chat.id, data['images'], url)

        if data['videos']:
            send_videos(bot, msg.chat.id, data['videos'])

        # 🔥 SEND IMAGES
        # send_images(bot, msg.chat.id, data['images'])
        
    except Exception as e:
        logging.error(f"Error occurred: {str(e)}", exc_info=True)
        bot.send_message(msg.chat.id, "❌ Error occurred while scraping")
    try:
        if site == "youtube":
            return scrape_youtube(url)

        if is_dynamic(url):
            return dynamic_scrape(url)

        data = static_scrape(url)

        if not data["images"] and not data["videos"]:
            logging.warning("Static failed → switching to dynamic")
            return dynamic_scrape(url)

        return data

    except Exception as e:
        logging.warning(f"Error → switching to dynamic: {e}")
        return dynamic_scrape(url)
# -------------------------
# DETECTION
# -------------------------
def is_dynamic(url):
    keywords = ["instagram", "youtube", "twitter", "x.com"]
    return any(k in url.lower() for k in keywords)

# -------------------------
# STATIC SCRAPER
# -------------------------
def static_scrape(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.google.com/"
    }

    res = requests.get(url, headers=headers, timeout=15)
    soup = BeautifulSoup(res.text, "html.parser")

    title = soup.title.string.strip() if soup.title else "No title"
    if res.status_code == 403:
        logging.warning("403 detected (blocked)")
        return {"title": "Blocked", "images": [], "videos": []}
    images = []
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src")
        if src:
            images.append(urljoin(url, src))  # FIXED

    videos = []
    for v in soup.find_all("video"):
        src = v.get("src")
        if src:
            videos.append(urljoin(url, src))

    return {
        "title": title,
        "images": list(set(images)),  # remove duplicates
        "videos": list(set(videos))
    }

# -------------------------
# DYNAMIC SCRAPER
# -------------------------

def dynamic_scrape(url):
    logging.info("Deep scraping started (network mode)")

    media_urls = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            def handle_response(response):
                try:
                    url = response.url.lower()

                    # 🔥 ONLY collect real media URLs
                    if any(ext in url for ext in [".jpg", ".jpeg", ".png", ".webp", ".mp4", ".webm"]):
                        if is_valid_media(url):
                            media_urls.append(response.url)

                except Exception as e:
                    logging.warning(f"Response error: {e}")

            page.on("response", handle_response)

            try:
                page.goto(url, timeout=30000)
                page.wait_for_timeout(3000)

                # 🔥 HANDLE POPUPS HERE
                handle_popups(page)
                page.wait_for_timeout(3000)
            except Exception:
                logging.warning(f"Timeout loading: {url}")
                return {"title": "Timeout", "images": [], "videos": []}
            
            analysis = analyze_page(page)
            strategy = decide_strategy(analysis)

            logging.info(f"Analysis: {analysis}")
            logging.info(f"Strategy chosen: {strategy}")
            page.wait_for_timeout(3000)

            analysis = analyze_page(page)
            strategy = decide_strategy(analysis)

            logging.info(f"Strategy: {strategy}")
            page.wait_for_timeout(5000)
        
            #scroll logic
            if strategy == "scroll":
                logging.info("Using scroll strategy")
                for i in range(6):
                    page.mouse.wheel(0, 6000)
                    page.wait_for_timeout(2000)

            elif strategy == "lazy_load":
                logging.info("Using lazy load strategy")
                page.wait_for_timeout(5000)

            elif strategy == "static":
                logging.info("Using static DOM strategy")

            else:
                logging.info("Unknown strategy → fallback scroll")
                for i in range(3):
                    page.mouse.wheel(0, 3000)
                    page.wait_for_timeout(1500)
            # 🔥 fallback: extract images directly from DOM
            # 🔥 STRONG DOM extraction (MAIN FIX)
            dom_images = page.eval_on_selector_all(
                "img.chapter-img, img",
                """els => els.map(e => 
                    e.src || 
                    e.getAttribute('data-src') || 
                    e.getAttribute('data-original') || 
                    e.getAttribute('data-lazy')
                )"""
            )

            for img in dom_images:
                if img and is_valid_media(img):
                    media_urls.append(img)
            logging.info(f"Collected raw URLs: {len(media_urls)}")
            logging.info(f"Sample: {media_urls[:5]}")
            extra_images = page.eval_on_selector_all(
                "img",
                """els => els.map(e => 
                    e.getAttribute('data-original') || 
                    e.getAttribute('data-lazy') || 
                    e.getAttribute('data-src')
                )"""
            )

            for img in extra_images:
                if img and is_valid_media(img):
                    media_urls.append(img)
            # 🔥 extract videos from DOM
            dom_videos = page.eval_on_selector_all(
                "video, source",
                "els => els.map(e => e.src)"
            )

            for v in dom_videos:
                if v:
                    media_urls.append(v)
            # 🔥 extract page HTML content
            # html = page.content()

            # import re

            # # find image URLs inside scripts
            # found = re.findall(r'https://[^"]+\.jpg', html)

            # for img in found:
            #     media_urls.append(img)
            # # 🔥 extract JSON-like image data
            # json_images = re.findall(r'https://[^"]+\.(?:jpg|png|webp)', html)

            # for img in json_images:
            #     media_urls.append(img)
            # logging.info(f"HTML extracted images: {len(found)}")
            # ✅ process images OUTSIDE try/except

            # for img in dom_images:
            #     if img:
            #         media_urls.append(img)
            # title = page.title()
            title = page.title()
            browser.close()
        logging.info(f"Collected raw URLs: {len(media_urls)}")
        logging.info(f"Sample: {media_urls[:5]}")
    except Exception as e:
        logging.error(f"Dynamic scrape error: {e}", exc_info=True)
        return {"title": "Error", "images": [], "videos": []}

    # ALWAYS runs
    # keep order + remove duplicates

    # remove duplicates but keep order
    # remove duplicates
    seen = set()
    media_urls = [u for u in media_urls if not (u in seen or seen.add(u))]

    # filter valid
    media_urls = [u for u in media_urls if is_valid_media(u)]

    # sort best first
    media_urls = sorted(media_urls, key=score_url, reverse=True)

    # filter
    # in dynamic_scrape(), final image split
    images = [
        u for u in media_urls
        if is_valid_media(u) and any(ext in u.lower() for ext in [".jpg", ".jpeg", ".png", ".webp"])
    ]

    videos = [u for u in media_urls if is_valid_media(u) and any(ext in u for ext in [".mp4", ".webm"])]

    # rank
    def extract_page_number(url):
        match = re.search(r'hr_(\d+)', url)
        return int(match.group(1)) if match else 0

    images = sorted(images, key=extract_page_number)
    videos = sorted(videos, key=score_url, reverse=True)
    logging.info(f"Final Images: {len(images)}")
    logging.info(f"Final Videos: {len(videos)}")

    return {
        "title": title if title else "No title",
        "images": images,
        "videos": videos
    }
    
import yt_dlp

def scrape_youtube(url):
    ydl_opts = {
        'quiet': True,
        'format': 'best'
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

        return {
            "title": info.get("title"),
            "images": [],
            "videos": [info.get("url")]
        }
def scrape_with_pagination(base_url, max_pages=5):
    all_media = []

    for i in range(1, max_pages + 1):
        url = f"{base_url}?page={i}"
        logging.info(f"Scraping page {i}: {url}")

        data = dynamic_scrape(url)

        if not data or not data.get('images'):
            logging.info("Stopping: no data")
            break

        if len(data['images']) < 3:
            logging.info("Stopping: end detected")
            break

        all_media.extend(data["images"])

    return list(set(all_media))
# -------------------------
# BOT
# -------------------------
@bot.message_handler(commands=['start'])
def start(msg):
    bot.reply_to(msg, "Send me any URL and I will scrape it 🔍")

@bot.message_handler(func=lambda m: True)
def handle(msg):
    url = msg.text.strip()
    logging.info(f"Received URL from user: {url}")

    if not url.startswith("http"):
        bot.reply_to(msg, "❌ Send a valid URL")
        return

    bot.reply_to(msg, "⏳ Scraping...")

    try:
        base_url = get_base_url(url)

        if base_url:
            logging.info("Chapter detected")

            images = scrape_chapter(base_url, bot, msg.chat.id)

            data = {
                "title": "Chapter Download",
                "images": images,
                "videos": []
            }
        else:
            data = smart_scrape(url)

        if not data:
            bot.send_message(msg.chat.id, "❌ Failed to scrape data")
            return

        logging.info("Scraping completed successfully")
        logging.info(f"Sending {len(data['images'])} images")
        response = f"📄 Title: {data['title']}\n"
        response += f"🖼 Images: {len(data['images'])}\n"
        response += f"🎥 Videos: {len(data['videos'])}\n"

        bot.send_message(msg.chat.id, response)
        # 🔥 LIMIT IMAGES
        MAX_IMAGES = 10
        data['images'] = data['images'][:MAX_IMAGES]

        logging.info(f"Images: {len(data['images'])}, Videos: {len(data['videos'])}")

        # 🔥 SEND MEDIA HERE
        if data['images']:
            send_images(bot, msg.chat.id, data['images'], url)

        if data['videos']:
            send_videos(bot, msg.chat.id, data['videos'], url)

        # 🔥 SEND IMAGES
        # send_images(bot, msg.chat.id, data['images'])
        
    except Exception as e:
        logging.error(f"Error occurred: {str(e)}", exc_info=True)
        bot.send_message(msg.chat.id, "❌ Error occurred while scraping")

bot.infinity_polling()
