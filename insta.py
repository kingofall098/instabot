import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import re
from playwright.sync_api import sync_playwright
import threading
import time
import random

# =========================
# BOT TOKEN
# =========================

TOKEN = "8756448611:AAHbnOlBbZP8639ZKHcFZd0vSQeK54EMSYQ"

bot = telebot.TeleBot(TOKEN, threaded=False)


# =========================
# INSTAGRAM SESSION
# =========================

IG_SESSIONID = "80454330558%3AtpURNMPKDVS2DH%3A16%3AAYjBDatw2qKZntVyio7s28j5Y7f0JchpOveCkxtx4w"
class Job:

    def __init__(self, username):

        self.username = username
        self.posts = []
        self.sent = 0
        self.running = True


user_jobs = {}
# =========================
# CACHE
# =========================

post_cache = {}
import datetime

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
    headless=True
)

page = browser.new_page()

# open instagram first
page.goto("https://www.instagram.com")

# add session cookie
browser.add_cookies([
    {
        "name": "sessionid",
        "value": IG_SESSIONID,
        "domain": ".instagram.com",
        "path": "/",
        "httpOnly": True,
        "secure": True,
        "sameSite": "None"
    }
])

# reload so cookie applies
page.goto("https://www.instagram.com/")

# =========================
# ADD INSTAGRAM SESSION
# =========================

browser.add_cookies([
    {
        "name": "sessionid",
        "value": IG_SESSIONID,
        "domain": ".instagram.com",
        "path": "/",
        "httpOnly": True,
        "secure": True,
        "sameSite": "None"
    }
])


# =========================
# FETCH PROFILE
# =========================
def scrape_background(job):

    username = job.username

    print("Scraping:", username)

    try:

        with sync_playwright() as p:

            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            url = f"https://www.instagram.com/{username}/"

            page.goto(url, wait_until="domcontentloaded")

            time.sleep(5)

            print("Current URL:", page.url)

            if "login" in page.url:
                print("Instagram redirected to login")
                return

            page.wait_for_selector("article", timeout=30000)

            while job.running:

                links = page.evaluate("""
                Array.from(document.querySelectorAll("article a"))
                .map(a => a.href)
                """)

                for link in links:

                    link = link.split("?")[0]

                    if link not in job.posts:
                        job.posts.append(link)

                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(3)

    except Exception as e:

        print("Scraper error:", e)        
import requests
import re
def fetch_media(post_url):

    try:

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9"
        }

        r = requests.get(post_url, headers=headers, timeout=15)

        print("Post request status:", r.status_code)

        html = r.text

        match = re.search(r'__additionalDataLoaded\([^,]+,(.*)\);</script>', html)

        if not match:
            print("JSON block not found")
            return None, None

        import json

        data = json.loads(match.group(1))

        media = data["items"][0]

        # VIDEO
        if media.get("video_versions"):
            url = media["video_versions"][0]["url"]
            return "video", url

        # PHOTO
        if media.get("image_versions2"):
            url = media["image_versions2"]["candidates"][0]["url"]
            return "photo", url

        return None, None

    except Exception as e:

        print("Media fetch error:", e)
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
# BUTTON HANDLER
# =========================
@bot.callback_query_handler(func=lambda call: call.data == "cancel")
def cancel(call):

    job = user_jobs.get(call.message.chat.id)

    if job:
        job.running = False

    bot.send_message(call.message.chat.id,"Scraping stopped.")
    
@bot.callback_query_handler(func=lambda call: call.data == "next")
def send_next(call):

    job = user_jobs.get(call.message.chat.id)

    if not job:
        bot.send_message(call.message.chat.id,"No active job")
        return

    start = job.sent
    end = start + 10

    posts = job.posts[start:end]

    if not posts:

        bot.send_message(call.message.chat.id,"Still collecting posts...")
        return

    for post_url in posts:
        media_type, media_url = fetch_media(post_url)
                # DEBUG LOGS
        print("Checking post:", post_url)
        print("Media type:", media_type)
        print("Media URL:", media_url)
        if media_url:

            try:

                if media_type == "video":
                    bot.send_video(call.message.chat.id, media_url)

                elif media_type == "photo":
                    bot.send_photo(call.message.chat.id, media_url)

            except Exception as e:

                print("Telegram error:", e)
                bot.send_message(call.message.chat.id, post_url)

        else:

            bot.send_message(call.message.chat.id, post_url)

        time.sleep(random.uniform(1.5,3))
    log(f"Sending media from: {post_url}")
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
