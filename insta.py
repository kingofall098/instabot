import telebot
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from urllib.parse import urljoin
import logging

# =========================
# CONFIG
# =========================
TOKEN = "8755937047:AAHBFaKCan-W8QLls2DDJ3-XpUdyw3tP16w"
bot = telebot.TeleBot(TOKEN)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)

# =========================
# DETECTION
# =========================
def is_dynamic(url):
    keywords = ["instagram", "youtube", "twitter", "x.com"]
    return any(k in url.lower() for k in keywords)

# =========================
# STATIC SCRAPER
# =========================
def static_scrape(url):
    logging.info("Static scraping started")

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    res = requests.get(url, headers=headers, timeout=15)
    logging.info(f"Status Code: {res.status_code}")

    soup = BeautifulSoup(res.text, "html.parser")

    title = soup.title.string.strip() if soup.title else "No title"

    images = []
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src")
        if src:
            full_url = urljoin(url, src)
            if full_url.startswith("http"):
                images.append(full_url)

    videos = []
    for v in soup.find_all("video"):
        src = v.get("src")
        if src:
            videos.append(urljoin(url, src))

    logging.info(f"Found {len(images)} images and {len(videos)} videos")

    return {
        "title": title,
        "images": list(set(images)),
        "videos": list(set(videos))
    }

# =========================
# DYNAMIC SCRAPER
# =========================
def dynamic_scrape(url):
    logging.info("Deep scraping started (network mode)")

    media_urls = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # 🔥 Capture network responses
        def handle_response(response):
            try:
                content_type = response.headers.get("content-type", "")

                if "image" in content_type:
                    media_urls.append(response.url)

                if "video" in content_type:
                    media_urls.append(response.url)

                # Optional: capture JSON APIs
                if "application/json" in content_type:
                    data = response.text()
                    if "image" in data or "video" in data:
                        logging.info(f"API Data Found: {response.url}")

            except Exception as e:
                logging.warning(f"Response error: {e}")

        page.on("response", handle_response)

        logging.info("Opening page...")
        page.goto(url, timeout=60000)

        # Scroll to trigger loading
        for _ in range(5):
            page.mouse.wheel(0, 5000)
            page.wait_for_timeout(2000)

        title = page.title()

        browser.close()

        media_urls = list(set(media_urls))

        logging.info(f"Captured {len(media_urls)} media URLs")

        return {
            "title": title,
            "images": [u for u in media_urls if any(ext in u for ext in [".jpg", ".png", ".webp"])],
            "videos": [u for u in media_urls if any(ext in u for ext in [".mp4", ".webm"])]
        }
# =========================
# MAIN ENGINE
# =========================
def smart_scrape(url):
    logging.info(f"Starting scrape for: {url}")

    if is_dynamic(url):
        logging.info("Using dynamic scraper")
        return dynamic_scrape(url)
    else:
        logging.info("Using static scraper")
        return static_scrape(url)

# =========================
# BOT
# =========================
@bot.message_handler(commands=['start'])
def start(msg):
    bot.reply_to(msg, "Send me any URL and I will scrape it 🔍")

@bot.message_handler(func=lambda m: True)
def handle(msg):
    url = msg.text.strip()
    logging.info(f"Received URL: {url}")

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

        # Send first 3 images safely
        for img in data['images'][:3]:
            try:
                bot.send_photo(msg.chat.id, img)
            except:
                continue

    except Exception as e:
        logging.error(f"Error: {str(e)}", exc_info=True)
        bot.send_message(msg.chat.id, "❌ Error occurred while scraping")

bot.infinity_polling()
