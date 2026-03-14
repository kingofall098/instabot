import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import re
from playwright.sync_api import sync_playwright

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

IG_SESSIONID = "43597613669%3Aa8ilkHnXtvOs70%3A16%3AAYhtiUZ55V_QMc7iC_I0G2l47xIBEFaR0R5JTKAB-g"
user_jobs = {}

class Job:
    def __init__(self):
        self.posts = []
        self.sent = 0
        self.running = True

# =========================
# CACHE
# =========================

post_cache = {}


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

import threading

def scrape_background(username, job):

    try:

        page.goto(f"https://www.instagram.com/{username}/", wait_until="domcontentloaded")

        page.wait_for_selector('a[href*="/p/"], a[href*="/reel/"]', timeout=30000)

        collected = set()
        last_count = 0
        no_new_scroll = 0

        while job.running:

            links = page.evaluate("""
                Array.from(document.querySelectorAll('a[href*="/p/"], a[href*="/reel/"]'))
                    .map(a => a.href)
            """)

            for link in links:

                link = link.split("?")[0]

                if link in collected:
                    continue

                collected.add(link)

                job.posts.append(link)

                print("Collected:", len(job.posts))

            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(3)

            if len(collected) == last_count:
                no_new_scroll += 1
            else:
                no_new_scroll = 0

            last_count = len(collected)

            if no_new_scroll >= 3:
                break

        print("Scraping finished")

    except Exception as e:
        print("Scraper error:", e)
# =========================
# FETCH PROFILE
# =========================

def stream_posts(username, chat_id):

    try:

        delay = random.uniform(5,8)
        print("Delay:", delay)
        time.sleep(delay)

        url = f"https://www.instagram.com/{username}/"
        print("Opening:", url)

        page.goto(url, wait_until="domcontentloaded")

        page.wait_for_selector('a[href*="/p/"], a[href*="/reel/"]', timeout=30000)

        sent_posts = set()
        no_new_scroll = 0
        last_count = 0

        while True:

            links = page.evaluate("""
                Array.from(document.querySelectorAll('a[href*="/p/"], a[href*="/reel/"]'))
                    .map(a => a.href)
            """)

            for link in links:

                link = link.split("?")[0]

                if link in sent_posts:
                    continue

                sent_posts.add(link)

                media_type, media_url = fetch_media(link)

                try:

                    if media_type == "video":
                        bot.send_video(chat_id, media_url)

                    elif media_type == "photo":
                        bot.send_photo(chat_id, media_url)

                    else:
                        bot.send_message(chat_id, link)

                except:
                    bot.send_message(chat_id, link)

                time.sleep(random.uniform(2,4))

            print("Posts sent:", len(sent_posts))

            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(3)

            if len(sent_posts) == last_count:
                no_new_scroll += 1
            else:
                no_new_scroll = 0

            last_count = len(sent_posts)

            if no_new_scroll >= 3:
                break

        bot.send_message(chat_id, f"Finished. {len(sent_posts)} posts sent.")

    except Exception as e:

        print("STREAM ERROR:", e)
        bot.send_message(chat_id, "Error scraping profile.")
def fetch_media(post_url):

    try:

        page.goto(post_url, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)

        html = page.content()

        video = re.search(r'"video_url":"([^"]+)"', html)
        image = re.search(r'"display_url":"([^"]+)"', html)

        if video:
            url = video.group(1).replace("\\u0026","&")
            return "video", url

        if image:
            url = image.group(1).replace("\\u0026","&")
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

    job = Job()
    user_jobs[message.chat.id] = job

    thread = threading.Thread(
        target=scrape_background,
        args=(username, job)
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
@bot.callback_query_handler(func=lambda call: call.data == "next")
def send_next(call):

    job = user_jobs.get(call.message.chat.id)

    if not job:
        bot.send_message(call.message.chat.id, "No active job.")
        return

    start = job.sent
    end = start + 10

    posts = job.posts[start:end]

    if not posts:
        bot.send_message(call.message.chat.id, "Still collecting posts...")
        return

    for post_url in posts:

        media_type, media_url = fetch_media(post_url)

        if not media_url:
            bot.send_message(chat_id, post_url)
            continue

        try:

            if media_type == "video":
                bot.send_video(chat_id, media_url)

            elif media_type == "photo":
                bot.send_photo(chat_id, media_url)

            else:
                bot.send_message(chat_id, post_url)

        except Exception as e:

            print("Send error:", e)
            bot.send_message(chat_id, post_url)

        time.sleep(random.uniform(2,3))

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
    
@bot.callback_query_handler(func=lambda call: call.data == "next")
def send_next(call):

    job = user_jobs.get(call.message.chat.id)

    if not job:
        bot.send_message(call.message.chat.id, "No active job.")
        return

    start = job.sent
    end = start + 10

    posts = job.posts[start:end]

    if not posts:
        bot.send_message(call.message.chat.id, "Still collecting posts...")
        return

    for post_url in posts:

        media_type, media_url = fetch_media(post_url)

        try:
            if media_type == "video":
                bot.send_video(call.message.chat.id, media_url)
            else:
                bot.send_photo(call.message.chat.id, media_url)
        except:
            bot.send_message(call.message.chat.id, post_url)

        time.sleep(2)

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
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):

    action, username, start = call.data.split("|")
    start = int(start)

    edges = post_cache.get(username)

    if not edges:
        bot.send_message(call.message.chat.id, "Cache expired. Send username again.")
        return

    end = start + 10
    posts = edges[start:end]

    print("Sending posts:", start, "to", end)

    for post in posts:

        post_url = post["node"]["display_url"]

        media_type, media_url = fetch_media(post_url)

        try:

            if media_type == "video":

                bot.send_video(call.message.chat.id, media_url)

            elif media_type == "photo":

                bot.send_photo(call.message.chat.id, media_url)

            else:

                bot.send_message(call.message.chat.id, post_url)

        except Exception as e:

            print("Telegram send error:", e)
            bot.send_message(call.message.chat.id, post_url)

        time.sleep(random.uniform(2,4))
# =========================
# RUN BOT
# =========================

print("Bot started")

bot.infinity_polling()
