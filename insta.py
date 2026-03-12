# =====================================
# IMPORT LIBRARIES
# =====================================

import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import requests
import re
import json
import time


# =====================================
# BOT CONFIG
# =====================================

TOKEN = "8628280617:AAEHHRQZ2dxsxoFWvmLs1PVO_wSCRn0rHPc"

bot = telebot.TeleBot(TOKEN)

session = requests.Session()

session.headers.update({
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "en-US,en;q=0.9"
})

post_cache = {}

user_last_request = {}
COOLDOWN = 10


# =====================================
# EXTRACT USERNAME
# =====================================

def extract_username(text):

    text = text.strip()

    match = re.search(r"instagram\.com/([A-Za-z0-9_.]+)", text)

    if match:
        return match.group(1)

    return text


# =====================================
# FETCH PROFILE HTML
# =====================================

def fetch_profile(username):

    url = f"https://www.instagram.com/{username}/"

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    r = session.get(url, headers=headers)

    if r.status_code != 200:
        print("Instagram error:", r.status_code)
        return None

    html = r.text

    # find embedded JSON
    match = re.search(r'<script type="application/json">(.*?)</script>', html)

    if not match:
        print("Embedded JSON not found")
        return None

    try:
        data = json.loads(match.group(1))
    except:
        return None

    # navigate to user media
    try:
        user = data["props"]["pageProps"]["graphql"]["user"]
        return user["edge_owner_to_timeline_media"]
    except:
        print("User media not found")
        return None
# =====================================
# START COMMAND
# =====================================

@bot.message_handler(commands=['start'])
def start(message):

    bot.send_message(
        message.chat.id,
        "📸 Instagram Downloader Bot\n\nSend an Instagram username."
    )


# =====================================
# PROFILE HANDLER
# =====================================

@bot.message_handler(func=lambda m: True)
def profile_handler(message):

    username = extract_username(message.text)

    data = fetch_profile(username)

    if not data:
        bot.send_message(message.chat.id, "❌ Profile not found")
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
        f"Found {len(edges)} posts.\n\nClick below to download.",
        reply_markup=markup
    )


# =====================================
# BUTTON HANDLER
# =====================================

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):

    user_id = call.from_user.id
    now = time.time()

    if user_id in user_last_request:

        elapsed = now - user_last_request[user_id]

        if elapsed < COOLDOWN:

            wait = int(COOLDOWN - elapsed)

            bot.answer_callback_query(
                call.id,
                f"Please wait {wait} seconds",
                show_alert=True
            )
            return

    user_last_request[user_id] = now

    action, username, start = call.data.split("|")

    start = int(start)

    edges = post_cache.get(username)

    if not edges:

        bot.send_message(call.message.chat.id, "Cache expired, send username again.")
        return

    posts = edges[start:start+10]

    for post in posts:

        node = post["node"]

        if node["is_video"]:

            bot.send_video(
                call.message.chat.id,
                node["video_url"]
            )

        else:

            bot.send_photo(
                call.message.chat.id,
                node["display_url"]
            )


# =====================================
# NEXT PAGE BUTTON
# =====================================

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

    else:

        bot.send_message(
            call.message.chat.id,
            "✅ No more posts."
        )


# =====================================
# RUN BOT
# =====================================

bot.infinity_polling()
