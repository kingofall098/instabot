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

bot = telebot.TeleBot(TOKEN, threaded=False)


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

        page.goto(url, wait_until="domcontentloaded")

        page.wait_for_timeout(5000)

        print("Page title:", page.title())
        print("Current URL:", page.url)

        if "login" in page.url:
            print("Instagram redirected to login")
            return None

        # wait for posts
        page.wait_for_selector("article", timeout=30000)

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

bot.infinity_polling()
