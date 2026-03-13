import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

from playwright.sync_api import sync_playwright

import time
import random
import re


# =========================
# BOT TOKEN
# =========================

TOKEN = "PUT_YOUR_TOKEN_HERE"

bot = telebot.TeleBot(TOKEN, threaded=False)


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
    user_data_dir="./ig_session",
    headless=True,

    args=[
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox"
    ],

    viewport={"width":1280,"height":800},

    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
)

page = browser.new_page()


# =========================
# HUMAN SCROLL
# =========================

def human_scroll():

    page.evaluate("""
    window.scrollBy({
        top: window.innerHeight,
        behavior: 'smooth'
    });
    """)

    time.sleep(random.uniform(2,4))


# =========================
# FETCH PROFILE POSTS
# =========================

def fetch_profile(username):

    try:

        delay = random.uniform(5,8)
        print("Delay:", delay)
        time.sleep(delay)

        url = f"https://www.instagram.com/{username}/"

        print("Opening:", url)

        page.goto(url, wait_until="domcontentloaded")

        time.sleep(random.uniform(4,6))

        print("Page title:", page.title())
        print("Current URL:", page.url)

        if "login" in page.url:
            print("Instagram login wall")
            return None

        page.wait_for_selector("article", timeout=30000)

        posts = set()

        last_count = 0
        no_change = 0

        while True:

            links = page.evaluate("""
            Array.from(document.querySelectorAll('a[href*="/p/"], a[href*="/reel/"]'))
            .map(a => a.href)
            """)

            for link in links:
                posts.add(link.split("?")[0])

            print("Posts collected:", len(posts))

            human_scroll()

            if len(posts) == last_count:
                no_change += 1
            else:
                no_change = 0

            last_count = len(posts)

            if no_change >= 4:
                break

        posts_list = []

        for link in posts:

            posts_list.append({
                "node": {
                    "display_url": link
                }
            })

        print("Total posts:", len(posts_list))

        return {"edges": posts_list}

    except Exception as e:

        print("FETCH ERROR:", e)
        return None


# =========================
# FETCH MEDIA FROM POST
# =========================

def fetch_media(post_url):

    try:

        page.goto(post_url)

        time.sleep(3)

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
# PAGINATION HANDLER
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

        post_url = node["display_url"]

        media_type, media_url = fetch_media(post_url)

        if media_type == "video":

            bot.send_video(call.message.chat.id, media_url)

        elif media_type == "photo":

            bot.send_photo(call.message.chat.id, media_url)

        else:

            bot.send_message(call.message.chat.id, post_url)

        time.sleep(random.uniform(2,4))

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
