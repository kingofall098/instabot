import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

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

def fetch_profile(username):

    try:

        delay = random.uniform(5,8)
        print("Delay:", delay)
        time.sleep(delay)

        url = f"https://www.instagram.com/{username}/"
        print("Opening:", url)

        page.goto(url, wait_until="domcontentloaded")

        page.wait_for_timeout(5000)

        print("Page title:", page.title())
        print("Current URL:", page.url)

        if "login" in page.url:
            print("Instagram redirected to login")
            return None

        # wait for posts
        page.wait_for_selector('a[href*="/p/"], a[href*="/reel/"]', timeout=30000)

        posts = set()

        last_count = 0
        no_new_scroll = 0

        while True:

            links = page.evaluate("""
                Array.from(document.querySelectorAll('a[href*="/p/"], a[href*="/reel/"]'))
                    .map(a => a.href)
            """)

            for link in links:
                posts.add(link.split("?")[0])

            print("Posts loaded:", len(posts))

            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(3)

            if len(posts) == last_count:
                no_new_scroll += 1
            else:
                no_new_scroll = 0

            last_count = len(posts)

            if no_new_scroll >= 3:
                break

        posts_list = []

        for link in posts:

            posts_list.append({
                "node": {
                    "display_url": link
                }
            })

        print("Total posts detected:", len(posts_list))

        if not posts_list:
            return None

        return {"edges": posts_list}

    except Exception as e:

        print("FETCH ERROR:", e)
        return None
def fetch_media(post_url):

    try:

        page.goto(post_url, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)

        html = page.content()

        video = re.search(r'property="og:video" content="([^"]+)"', html)
        image = re.search(r'property="og:image" content="([^"]+)"', html)

        if video:
            return "video", video.group(1)

        if image:
            return "photo", image.group(1)

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

    data = fetch_profile(username)

    if not data:

        bot.send_message(
            message.chat.id,
            "❌ Could not fetch profile posts"
        )

        return

    edges = data["edges"]

    post_cache[username] = edges

    markup = InlineKeyboardMarkup()

    btn = InlineKeyboardButton(
        "Download Posts",
        callback_data=f"posts|{username}|0"
    )

    markup.add(btn)

    bot.send_message(
        message.chat.id,
        f"Found {len(edges)} posts",
        reply_markup=markup
    )


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
