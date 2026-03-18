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
import re

def get_base_url(url):
    match = re.search(r"(.*?/p/)\d+", url)
    if match:
        return match.group(1)
    return None
def scrape_chapter(base_url, bot,chat_id):
    all_images = []
    seen = set()

    for i in range(1, 50):
        # 🔥 SEND PROGRESS
        bot.send_message(chat_id, f"📄 Scraping page {i}...")

        page_url = f"{base_url}{i}/"
        logging.info(f"Scraping page {i}: {page_url}")

        data = dynamic_scrape(page_url)

        if not data['images']:
            logging.info("No more images, stopping...")
            break

        for img in data['images']:
            if img not in seen:
                seen.add(img)
                all_images.append(img)

    return all_images
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
        if sent >= 10:
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
def send_videos(bot, chat_id, videos, page_url):
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": page_url
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

            title = page.title()

            browser.close()

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
    images = [u for u in media_urls if is_valid_media(u) and any(ext in u for ext in [".jpg", ".png", ".webp"])]
    videos = [u for u in media_urls if is_valid_media(u) and any(ext in u for ext in [".mp4", ".webm"])]

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

        response = f"📄 Title: {data['title']}\n"
        response += f"🖼 Images: {len(data['images'])}\n"
        response += f"🎥 Videos: {len(data['videos'])}\n"

        bot.send_message(msg.chat.id, response)
        # 🔥 LIMIT IMAGES
        MAX_IMAGES = 30
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
