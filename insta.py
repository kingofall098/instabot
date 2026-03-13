import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

from playwright.sync_api import sync_playwright

import time
import random
import re


# =========================
# BOT TOKEN
# =========================

TOKEN = "8756448611:AAHbnOlBbZP8639ZKHcFZd0vSQeK54EMSYQ"

bot = telebot.TeleBot(TOKEN)


# =========================
# CACHE
# =========================

post_cache = {}


# =========================
# PLAYWRIGHT BROWSER
# =========================

print("Starting browser...")

play = sync_playwright().start()

browser = play.chromium.launch_persistent_context(
    user_data_dir="./ig_profile",   # keeps login session
    headless=True
)

page = browser.new_page()


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

        page.goto(url)

        page.wait_for_timeout(6000)

        print("Page title:", page.title())
        print("Current URL:", page.url)

        # detect login page
        if "login" in page.url:
            print("Instagram login wall detected")
            return None

        # detect suspended
        if "suspended" in page.url:
            print("Instagram account/session suspended")
            return None

        # wait for posts to appear
        try:
            page.wait_for_selector('a[href*="/p/"], a[href*="/reel/"]', timeout=8000)
        except:
            print("Post selector not found")

        html = page.content()

        print("HTML length:", len(html))

        links = re.findall(r'href="/(p|reel)/([^/]+)/"', html)

        print("Links found:", len(links))

        if len(links) == 0:
            print("No post links detected")
            print("First 500 chars of HTML:")
            print(html[:500])
            return None

        posts = []

        for post_type, code in links:

            if post_type == "reel":
                media_url = f"https://www.instagram.com/reel/{code}/"
            else:
                media_url = f"https://www.instagram.com/p/{code}/"

            posts.append({
                "node": {
                    "is_video": False,
                    "display_url": media_url
                }
            })

        print("Posts collected:", len(posts))

        return {"edges": posts[:50]}

    except Exception as e:

        print("FETCH ERROR:", e)
        return None
        
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

        bot.send_message(
            call.message.chat.id,
            "Cache expired. Send username again."
        )

        return

    posts = edges[start:start+10]

    for post in posts:

        node = post["node"]

        bot.send_message(
            call.message.chat.id,
            node["display_url"]
        )

    next_start = start + 10

    if next_start < len(edges):

        markup = InlineKeyboardMarkup()

        btn = InlineKeyboardButton(
            "Next 10 Posts",
            callback_data=f"posts|{username}|{next_start}"
        )

        markup.add(btn)

        bot.send_message(
            call.message.chat.id,
            "Load more posts:",
            reply_markup=markup
        )


# =========================
# RUN BOT
# =========================

print("Bot started")

bot.infinity_polling(threaded=False)
