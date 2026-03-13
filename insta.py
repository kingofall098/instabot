import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import requests
import time
import random
import re

# =============================
# BOT TOKEN
# =============================

TOKEN = "8756448611:AAHbnOlBbZP8639ZKHcFZd0vSQeK54EMSYQ"

bot = telebot.TeleBot(TOKEN)

# =============================
# CACHE
# =============================

post_cache = {}

# =============================
# REQUEST SETTINGS
# =============================

HEADERS = {
    "User-Agent": "Instagram 219.0.0.12.117 Android",
    "x-ig-app-id": "936619743392459"
}

# optional proxy
PROXY = None
# example
# PROXY = {
#     "http": "http://user:pass@host:port",
#     "https": "http://user:pass@host:port"
# }

# =============================
# RANDOM DELAY
# =============================

def delay():

    d = random.uniform(3,6)

    print("Delay:", d)

    time.sleep(d)

# =============================
# EXTRACT USERNAME
# =============================

def extract_username(text):

    text = text.strip()

    match = re.search(r"instagram.com/([A-Za-z0-9_.]+)", text)

    if match:
        return match.group(1)

    return text

# =============================
# FETCH PROFILE
# =============================

def fetch_profile(username):

    delay()

    url = "https://i.instagram.com/api/v1/users/web_profile_info/"

    params = {
        "username": username
    }

    try:

        r = requests.get(
            url,
            headers=HEADERS,
            params=params,
            proxies=PROXY,
            timeout=15
        )

        print("Status:", r.status_code)

        if r.status_code != 200:
            return None

        return r.json()

    except Exception as e:

        print("Request error:", e)

        return None

# =============================
# PARSE POSTS
# =============================

def extract_posts(data):

    try:

        edges = data["data"]["user"]["edge_owner_to_timeline_media"]["edges"]

        posts = []

        for e in edges:

            node = e["node"]

            if node["is_video"]:

                posts.append({
                    "type": "video",
                    "url": node.get("video_url"),
                    "thumb": node.get("display_url")
                })

            else:

                posts.append({
                    "type": "photo",
                    "url": node.get("display_url")
                })

        return posts

    except:

        return []

# =============================
# START COMMAND
# =============================

@bot.message_handler(commands=["start"])
def start(message):

    bot.send_message(
        message.chat.id,
        "Instagram Media Bot\n\nSend Instagram username"
    )

# =============================
# USERNAME HANDLER
# =============================

@bot.message_handler(func=lambda m: True)
def profile_handler(message):

    username = extract_username(message.text)

    data = fetch_profile(username)

    if not data:

        bot.send_message(
            message.chat.id,
            "Could not fetch profile"
        )

        return

    user = data["data"]["user"]

    followers = user["edge_followed_by"]["count"]
    following = user["edge_follow"]["count"]
    posts = user["edge_owner_to_timeline_media"]["count"]
    profile_pic = user["profile_pic_url_hd"]

    text = f"""
Instagram Profile

Username: {username}

Followers: {followers}
Following: {following}
Posts: {posts}
"""

    extracted = extract_posts(data)

    if not extracted:

        bot.send_message(message.chat.id, "No posts found")

        return

    post_cache[username] = extracted

    markup = InlineKeyboardMarkup()

    btn = InlineKeyboardButton(
        "Download Posts",
        callback_data=f"posts|{username}|0"
    )

    markup.add(btn)

    bot.send_photo(
        message.chat.id,
        profile_pic,
        caption=text,
        reply_markup=markup
    )

# =============================
# BUTTON HANDLER
# =============================

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):

    action, username, start = call.data.split("|")

    start = int(start)

    if username not in post_cache:

        bot.send_message(
            call.message.chat.id,
            "Cache expired. Send username again."
        )

        return

    posts = post_cache[username]

    selected = posts[start:start+10]

    for post in selected:

        delay()

        try:

            if post["type"] == "video":

                bot.send_video(
                    call.message.chat.id,
                    post["url"]
                )

            else:

                bot.send_photo(
                    call.message.chat.id,
                    post["url"]
                )

        except:

            bot.send_message(
                call.message.chat.id,
                "Failed to send media"
            )

    next_start = start + 10

    if next_start < len(posts):

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

# =============================
# START BOT
# =============================

print("Bot started")

bot.infinity_polling()
