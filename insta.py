#FORWARD INSTA POST LINKS
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

IG_SESSIONID = "45575449095%3APTeNL8atjbF3Xs%3A9%3AAYhrp2AO-1Qn_PzdwHGe5QXpaBpzTh6oWBakuGsjlQ"

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

# Create context
context = browser.new_context()

# Add session cookie
context.add_cookies([{
    "name": "sessionid",
    "value": IG_SESSIONID,
    "domain": ".instagram.com",
    "path": "/",
    "httpOnly": True,
    "secure": True,
    "sameSite": "None"
}])

# Create page
page = context.new_page()

# Activate session
page.goto("https://www.instagram.com/")

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

        if "login" in page.url:
            log("Instagram redirected to login")
            return

        page.wait_for_selector('a[href^="/p/"], a[href^="/reel/"]', timeout=30000)

        for _ in range(15):

            if not job.running:
                break

            links = page.evaluate("""
                Array.from(document.querySelectorAll('a[href^="/p/"], a[href^="/reel/"]'))
                .map(a => a.href)
            """)

            for link in links:

                link = link.split("?")[0]

                if link not in job.posts:
                    job.posts.append(link)

            log(f"Collected posts: {len(job.posts)}")

            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

            time.sleep(3)

        page.close()

    except Exception as e:
        log(f"Scraper error: {e}")
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

    username = message.text.strip()

    job = Job(username)
    user_jobs[message.chat.id] = job

    thread = threading.Thread(
        target=scrape_background,
        args=(job,)
    )

    thread.start()

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
