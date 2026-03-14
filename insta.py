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

        video = re.search(r'property="og:video" content="([^"]+)"', html)
        image = re.search(r'property="og:image" content="([^"]+)"', html)

        if video:
            return "video", video.group(1)

        if image:
            return "photo", image.group(1)

        return None, None

    except Exception as e:
        print("Media error:", e)
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

    bot.send_message(
        message.chat.id,
        f"Fetching posts from {username}..."
    )

    stream_posts(username, message.chat.id)
# =========================
# BUTTON HANDLER
# =========================

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
