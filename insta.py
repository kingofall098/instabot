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
def smart_scrape(url):
    logging.info(f"Starting scrape for: {url}")

    if is_dynamic(url):
        logging.info("Using dynamic scraper")
        return dynamic_scrape(url)
    else:
        logging.info("Using static scraper")
        return static_scrape(url)
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
def dynamic_scrape(url):
    logging.info("Dynamic scraping started")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        logging.info("Opening page...")
        page.goto(url, timeout=60000)

        logging.info("Scrolling page...")
        for _ in range(3):
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(1500)

        title = page.title()
        logging.info(f"Page title: {title}")

        images = page.eval_on_selector_all(
            "img", "els => els.map(e => e.src)"
        )

        videos = page.eval_on_selector_all(
            "video", "els => els.map(e => e.src)"
        )

        logging.info(f"Collected {len(images)} images and {len(videos)} videos")

        browser.close()

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
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }

    res = requests.get(url, headers=headers, timeout=15)
    soup = BeautifulSoup(res.text, "html.parser")

    title = soup.title.string.strip() if soup.title else "No title"

    images = []
    for img in soup.find_all("img"):
        src = img.get("src")
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
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        page.goto(url, timeout=60000)
        page.wait_for_timeout(3000)

        # auto scroll (IMPORTANT UPGRADE)
        for _ in range(3):
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(1500)

        title = page.title()

        images = page.eval_on_selector_all(
            "img", "els => els.map(e => e.src)"
        )

        videos = page.eval_on_selector_all(
            "video", "els => els.map(e => e.src)"
        )

        browser.close()

        return {
            "title": title,
            "images": list(set(images)),
            "videos": list(set(videos))
        }

# -------------------------
# MAIN ENGINE
# -------------------------
def smart_scrape(url):
    if is_dynamic(url):
        return dynamic_scrape(url)
    else:
        return static_scrape(url)

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

    except Exception as e:
        logging.error(f"Error occurred: {str(e)}", exc_info=True)
        bot.send_message(msg.chat.id, "❌ Error occurred while scraping")

bot.infinity_polling()
