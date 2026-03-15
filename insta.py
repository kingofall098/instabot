#2FORWARD INSTA POST LINKS 
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from playwright.sync_api import sync_playwright
import threading
import requests
import datetime
import time
import random
import re
import json
from io import BytesIO
# =========================
# BOT TOKEN
# =========================

TOKEN = "8755937047:AAHBFaKCan-W8QLls2DDJ3-XpUdyw3tP16w"
bot = telebot.TeleBot(TOKEN, threaded=False)

# =========================
# INSTAGRAM SESSION
# =========================

# IG_SESSIONID = "80454330558%3AgyVmoDRy4c8pBj%3A10%3AAYiQ7rgvA8jCZ_WEFR54X9TEPmj2mRs1s_cM8Mfghg"

# =========================
# JOB SYSTEM
# =========================

class Job:
    def __init__(self, username):
        self.username = username
        self.posts = []
        self.sent = 0
        self.running = True

user_jobs = {}

# =========================
# LOG FUNCTION
# =========================

def log(msg):
    t = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{t}] {msg}")
    
# SESSION FUNCTION
def load_session_from_cookie():

    with open("cookies.txt", "r") as f:
        for line in f:

            if line.startswith("#"):
                continue

            parts = line.strip().split("\t")

            if len(parts) >= 7 and parts[-2] == "sessionid":

                session = parts[-1]

                log(f"Loaded session: {session[:20]}...")
                return session

    raise Exception("sessionid not found in cookies.txt")

IG_SESSIONID = load_session_from_cookie()
# =========================
# START PLAYWRIGHT
# =========================

print("Starting browser...")

play = sync_playwright().start()

browser = play.chromium.launch(
    headless=True,
    args=[
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-dev-shm-usage"
    ]
)

context = browser.new_context()

# inject instagram session cookie
context.add_cookies([{
    "name": "sessionid",
    "value": IG_SESSIONID,
    "domain": ".instagram.com",
    "path": "/",
    "httpOnly": True,
    "secure": True,
    "sameSite": "None"
}])

# open page after cookie is set
page = context.new_page()

# visit instagram to activate session
page.goto("https://www.instagram.com/", wait_until="domcontentloaded")

log("Instagram session activated")

# =========================
# SCRAPER
# =========================

def scrape_background(job):

    username = job.username
    log(f"Scraping: {username}")

    try:

        page = context.new_page()

        url = f"https://www.instagram.com/{username}/"

        delay = random.uniform(4,7)
        time.sleep(delay)

        page.goto(url, wait_until="domcontentloaded")

        time.sleep(5)

        log(f"Current URL: {page.url}")
        if "challenge" in page.url:
            log("Instagram triggered a security challenge. Session is blocked.")
            page.close()
            return

        if "accounts/login" in page.url:
            log("Session expired. Instagram requires login.")
            page.close()
            return
        # wait until page loads
        page.wait_for_load_state("networkidle")

        # small delay for JS rendering
        time.sleep(3)

        # scroll once to trigger posts loading
        page.evaluate("""
        window.scrollBy({
            top: 800,
            left: 0,
            behavior: 'smooth'
        });
        """)
        time.sleep(random.uniform(4,6))

        for _ in range(40):

            if not job.running:
                break
            log("Scanning page for posts...")
            links = page.evaluate("""
                Array.from(document.querySelectorAll('a'))
                    .map(a => a.href)
                    .filter(h => h.includes('/p/') || h.includes('/reel/'))
            """)

            new_posts = 0

            for link in links:
                link = link.split("?")[0]

                if link not in job.posts:
                    job.posts.append(link)
                    new_posts += 1

            log(f"Collected posts: {len(job.posts)} (+{new_posts})")

            page.evaluate("""
            window.scrollBy({
                top: 1200,
                left: 0,
                behavior: 'smooth'
            });
            """)

            time.sleep(3)

        page.close()

    except Exception as e:
        log(f"Scraper error: {e}")

    finally:
        try:
            page.close()
        except:
            pass
# =========================
# MEDIA FETCH
# =========================
def fetch_media(post_url):

    try:

        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept-Language": "en-US,en;q=0.9"
        }

        r = requests.get(post_url, headers=headers, timeout=15)

        html = r.text

        video = re.search(r'property="og:video" content="([^"]+)"', html)
        image = re.search(r'property="og:image" content="([^"]+)"', html)

        items = []

        if video:
            items.append(("video", video.group(1)))

        if image:
            items.append(("photo", image.group(1)))

        return items

    except Exception as e:

        log(f"Media error: {e}")
        return []
# =========================
# START COMMAND
# =========================

@bot.message_handler(commands=["start"])
def start(message):

    bot.send_message(
        message.chat.id,
        "Send Instagram username"
    )

# =========================
# USERNAME HANDLER
# =========================

@bot.message_handler(func=lambda m: True)
def profile_handler(message):

    username = message.text.strip().lower()

    job = Job(username)
    user_jobs[message.chat.id] = job

    scrape_background(job)

    markup = InlineKeyboardMarkup()

    markup.add(
        InlineKeyboardButton("Download 10 Posts", callback_data="next"),
        InlineKeyboardButton("Cancel", callback_data="cancel")
    )

    bot.send_message(
        message.chat.id,
        "Scraping started.\nPress download to receive posts.",
        reply_markup=markup
    )

# =========================
# CANCEL
# =========================

@bot.callback_query_handler(func=lambda call: call.data == "cancel")
def cancel(call):

    job = user_jobs.get(call.message.chat.id)

    if job:
        job.running = False

    bot.send_message(call.message.chat.id,"Scraping stopped.")

# =========================
# SEND POSTS
# =========================
@bot.callback_query_handler(func=lambda call: call.data == "next")
def send_next(call):

    job = user_jobs.get(call.message.chat.id)

    if not job:
        bot.send_message(call.message.chat.id, "No active job")
        return

    start = job.sent
    end = start + 10
    posts = job.posts[start:end]

    if not posts:
        bot.send_message(call.message.chat.id, "Still collecting posts...")
        return

    from io import BytesIO
    from PIL import Image

    for post_url in posts:

        medias = fetch_media(post_url)

        if not medias:
            bot.send_message(call.message.chat.id, post_url)
            continue

        for media_type, media_url in medias:

            log(f"Checking post: {post_url}")
            log(f"Media type: {media_type}")
            log(f"Media URL: {media_url}")

            if not media_url:
                bot.send_message(call.message.chat.id, post_url)
                continue

            media_url = media_url.replace("&amp;", "&")
            media_url = media_url.replace(".heic", ".jpg")

            log(f"Final media URL: {media_url}")

            try:

                response = requests.get(media_url, timeout=30)

                if response.status_code != 200:
                    raise Exception("Media download failed")

                file = BytesIO(response.content)

                if media_type == "video":

                    file.name = "video.mp4"
                    bot.send_video(call.message.chat.id, file)

                else:

                    img = Image.open(file).convert("RGB")

                    jpeg = BytesIO()
                    img.save(jpeg, format="JPEG")
                    jpeg.seek(0)

                    bot.send_photo(call.message.chat.id, jpeg)

            except Exception as e:

                log(f"Telegram error: {e}")
                bot.send_message(call.message.chat.id, post_url)

            time.sleep(random.uniform(1.5, 3))

    job.sent += len(posts)

    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("Next 10", callback_data="next"),
        InlineKeyboardButton("Cancel", callback_data="cancel")
    )

    bot.send_message(
        call.message.chat.id,
        f"Sent {job.sent} posts",
        reply_markup=markup
    )
# =========================
# RUN BOT
# =========================

print("Bot started")

bot.infinity_polling()
