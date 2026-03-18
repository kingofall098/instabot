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
def static_scrape(url):
    logging.info("Static scraping started")

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    res = requests.get(url, headers=headers, timeout=15)
    logging.info(f"Status Code: {res.status_code}")

    soup = BeautifulSoup(res.text, "html.parser")

    title = soup.title.string.strip() if soup.title else "No title"

    images = [img.get("src") for img in soup.find_all("img") if img.get("src")]
    videos = [v.get("src") for v in soup.find_all("video") if v.get("src")]

    logging.info(f"Found {len(images)} images and {len(videos)} videos")

    return {
        "title": title,
        "images": images,
        "videos": videos
    }
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

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        def handle_response(response):
            try:
                content_type = response.headers.get("content-type", "").lower()

                if "image" in content_type or "video" in content_type:
                    media_urls.append(response.url)

            except Exception as e:
                logging.warning(f"Response error: {e}")

        page.on("response", handle_response)

        logging.info("Opening page...")
        page.goto(url, timeout=60000)

        for i in range(5):
            logging.info(f"Scrolling {i+1}")
            page.mouse.wheel(0, 5000)
            page.wait_for_timeout(2000)

        title = page.title()

        browser.close()

    media_urls = list(set(media_urls))

    valid_ext = [".jpg", ".jpeg", ".png", ".webp", ".mp4", ".webm"]

    media_urls = [
        u for u in media_urls
        if any(ext in u.lower() for ext in valid_ext)
    ]

    logging.info(f"Captured {len(media_urls)} media URLs")
    logging.info(f"Sample: {media_urls[:5]}")

    return {
        "title": title,
        "images": [u for u in media_urls if any(ext in u for ext in [".jpg", ".png", ".webp"])],
        "videos": [u for u in media_urls if any(ext in u for ext in [".mp4", ".webm"])]
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

        logging.info("Scraping completed successfully")

        response = f"📄 Title: {data['title']}\n"
        response += f"🖼 Images: {len(data['images'])}\n"
        response += f"🎥 Videos: {len(data['videos'])}\n"

        bot.send_message(msg.chat.id, response)
        logging.info(f"Images: {len(data['images'])}, Videos: {len(data['videos'])}")
    except Exception as e:
        logging.error(f"Error occurred: {str(e)}", exc_info=True)
        bot.send_message(msg.chat.id, "❌ Error occurred while scraping")

bot.infinity_polling()
