# =============================
# IMPORT LIBRARIES
# =============================

import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import requests
import re
import time

# =============================
# BOT CONFIG
# =============================

TOKEN = "8756448611:AAHbnOlBbZP8639ZKHcFZd0vSQeK54EMSYQ"

bot = telebot.TeleBot(TOKEN)

# cooldown system
user_last_request = {}
COOLDOWN = 8

# =============================
# EXTRACT USERNAME
# =============================

def extract_username(text):

    text = text.strip()

    match = re.search(r"instagram\.com/([A-Za-z0-9_.]+)", text)

    if match:
        return match.group(1)

    return text

# =============================
# FETCH PROFILE DATA
# =============================

def fetch_profile(username):

    url = f"https://www.instagram.com/{username}/?__a=1&__d=dis"

    headers = {
        "User-Agent": "Mozilla/5.0",
        "x-ig-app-id": "936619743392459"
    }

    r = requests.get(url, headers=headers)

    if r.status_code != 200:
        return None

    try:
        return r.json()
    except:
        return None
    
# =============================
# START COMMAND
# =============================

@bot.message_handler(commands=['start'])
def start(message):

    bot.send_message(
        message.chat.id,
        "📸 Instagram Downloader Bot\n\nSend an Instagram username."
    )
    
# =============================
# PROFILE HANDLER
# =============================

@bot.message_handler(func=lambda m: True)
def profile_handler(message):

    username = extract_username(message.text)

    data = fetch_profile(username)

    if not data:
        bot.send_message(message.chat.id, "❌ Profile not found")
        return

    user = data["graphql"]["user"]

    followers = user["edge_followed_by"]["count"]
    following = user["edge_follow"]["count"]
    posts = user["edge_owner_to_timeline_media"]["count"]

    profile_pic = user["profile_pic_url_hd"]
    bio = user["biography"]

    text = f"""
📸 Instagram Profile

👤 Username: {username}

👥 Followers: {followers}
➡ Following: {following}
📦 Posts: {posts}

📄 Bio:
{bio}
"""

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

    data = fetch_profile(username)

    if not data:
        bot.send_message(call.message.chat.id, "Profile not found")
        return

    user = data["graphql"]["user"]

    edges = user["edge_owner_to_timeline_media"]["edges"]

    posts = edges[start:start+10]

    for post in posts:

        node = post["node"]

        if node["is_video"]:
            bot.send_video(call.message.chat.id, node["video_url"])
        else:
            bot.send_photo(call.message.chat.id, node["display_url"])

    next_start = start + 10

    markup = InlineKeyboardMarkup()

    next_btn = InlineKeyboardButton(
        "Next 10 Posts",
        callback_data=f"posts|{username}|{next_start}"
    )

    markup.add(next_btn)

    bot.send_message(
        call.message.chat.id,
        "Load more posts:",
        reply_markup=markup
    )
# =============================
# RUN BOT
# =============================

bot.infinity_polling()
