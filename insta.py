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
        page.goto(url)

        page.wait_for_timeout(4000)

        print("Current URL:", page.url)

        if "accounts/login" in page.url:
            print("Instagram requires login session")
            return None
        print("Page title:", page.title())
        print("Current URL:", page.url)
        page.wait_for_selector("article", timeout=30000)

        # scroll page to load more posts
        for i in range(10):

            print("Scrolling page...", i+1)

            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

            time.sleep(2)

        # extract links from post grid
        links = page.evaluate("""
        Array.from(document.querySelectorAll("article a"))
            .map(a => a.href)
        """)

        posts = []
        seen = set()

        for link in links:

            if "/p/" in link or "/reel/" in link:

                link = link.split("?")[0]

                if link in seen:
                    continue

                seen.add(link)

                posts.append({
                    "node": {
                        "display_url": link
                    }
                })

        print("Total posts detected:", len(posts))

        if not posts:
            return None

        return {"edges": posts}

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
