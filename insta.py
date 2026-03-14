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

TOKEN = "8756448611:AAHbnOlBbZP8639ZKHcFZd0vSQeK54EMSYQ"
bot = telebot.TeleBot(TOKEN, threaded=False)

# =========================
# INSTAGRAM SESSION
# =========================

IG_SESSIONID = "80454330558%3AtpURNMPKDVS2DH%3A16%3AAYjBDatw2qKZntVyio7s28j5Y7f0JchpOveCkxtx4w"

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

browser = play.chromium.launch_persistent_context(
    user_data_dir="./ig_profile",
    headless=True,
    args=["--disable-blink-features=AutomationControlled"]
)

page = browser.new_page()

# open instagram first
page.goto("https://www.instagram.com")

# add session cookie
browser.add_cookies([{
    "name": "sessionid",
    "value": IG_SESSIONID,
    "domain": ".instagram.com",
    "path": "/",
    "httpOnly": True,
    "secure": True,
    "sameSite": "None"
}])

# reload so session activates
page.goto("https://www.instagram.com/")

# =========================
# SCRAPER
# =========================

def scrape_background(job):

    username = job.username
    log(f"Scraping: {username}")

    try:

        with sync_playwright() as p:

            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage"
                ]
            )

            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
                viewport={"width":1280,"height":800},
                locale="en-US"
            )

            # add instagram session cookie
            context.add_cookies([{
                "name": "sessionid",
                "value": IG_SESSIONID,
                "domain": ".instagram.com",
                "path": "/",
                "httpOnly": True,
                "secure": True,
                "sameSite": "None"
            }])

            page = context.new_page()

            url = f"https://www.instagram.com/{username}/"

            delay = random.uniform(4,7)
            print("Delay:", delay)
            time.sleep(delay)

            url = f"https://www.instagram.com/{username}/"
            page.goto(url, wait_until="domcontentloaded")

            time.sleep(5)

            log(f"Current URL: {page.url}")

            if "login" in page.url:
                log("Instagram redirected to login")
                return
            if "suspended" in page.url:
                log("instagram block the session")
                return
            
            try:
                page.wait_for_selector('a[href*="/p/"], a[href*="/reel/"]', timeout=30000)
            except:
                print("Posts not visible yet, trying scroll...")

            for _ in range(20):

                if not job.running:
                    break

                links = page.evaluate("""
                    Array.from(document.querySelectorAll('a[href*="/p/"], a[href*="/reel/"]'))
                    .map(a => a.href)
                """)

                for link in links:
                    link = link.split("?")[0]

                    if link not in job.posts:
                        job.posts.append(link)

                print("Collected posts:", len(job.posts))

                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(3)

            browser.close()

    except Exception as e:

        log(f"Scraper error: {e}")
# =========================
# MEDIA FETCH
# =========================

def fetch_media(post_url):

    try:

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept-Language": "en-US,en;q=0.9"
        }

        r = requests.get(post_url, headers=headers, timeout=15)

        html = r.text

        # video
        video = re.search(r'property="og:video" content="([^"]+)"', html)

        if video:
            return "video", video.group(1)

        # photo
        image = re.search(r'property="og:image" content="([^"]+)"', html)

        if image:
            return "photo", image.group(1)

        return None, None

    except Exception as e:

        log(f"Media error: {e}")
        return None, None
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

    for post_url in posts:

        media_type, media_url = fetch_media(post_url)

        log(f"Checking post: {post_url}")
        log(f"Media type: {media_type}")
        log(f"Media URL: {media_url}")

        if not media_url:
            bot.send_message(call.message.chat.id, post_url)
            continue

        try:

            media_url = media_url.replace("&amp;", "&")
            media_url = media_url.replace(".heic", ".jpg")

            log(f"Final media URL: {media_url}")

            # open media in playwright (keeps cookies/session)
            page = browser.new_page()

            response = page.goto(media_url)

            if not response:
                raise Exception("No response from media")

            content = response.body()

            file = BytesIO(content)

            if media_type == "video":
                file.name = "video.mp4"
                bot.send_video(call.message.chat.id, file)

            elif media_type == "photo":
                file.name = "photo.jpg"
                bot.send_photo(call.message.chat.id, file)

            page.close()

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
