import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import instaloader
import time

BOT_TOKEN = "8628280617:AAEHHRQZ2dxsxoFWvmLs1PVO_wSCRn0rHPc"

bot = telebot.TeleBot(BOT_TOKEN)

L = instaloader.Instaloader(
    download_pictures=False,
    download_videos=False,
    download_video_thumbnails=False,
    save_metadata=False
)

user_profiles = {}

@bot.message_handler(commands=['start'])
def start(message):

    bot.send_message(
        message.chat.id,
        "Send an Instagram username to download last 10 posts."
    )
@bot.message_handler(func=lambda message: True)
def receive_username(message):

    username = message.text.strip()

    user_profiles[message.from_user.id] = username

    markup = InlineKeyboardMarkup()

    button = InlineKeyboardButton(
        "⬇ Download Last 10 Posts",
        callback_data="download_posts"
    )

    markup.add(button)

    bot.send_message(
        message.chat.id,
        f"Username received: {username}\n\nPress the button to fetch media.",
        reply_markup=markup
    )
    
@bot.callback_query_handler(func=lambda call: call.data == "download_posts")
def download_posts(call):

    user_id = call.from_user.id
    username = user_profiles.get(user_id)

    if not username:
        bot.send_message(call.message.chat.id, "Please send a username first.")
        return

    try:
        profile = instaloader.Profile.from_username(L.context, username)

        if profile.is_private:
            bot.send_message(call.message.chat.id, "❌ This account is private.")
            return

        posts = profile.get_posts()

        count = 0

        for post in posts:

            if count >= 10:
                break

            try:

                if post.is_video:
                    bot.send_video(
                        call.message.chat.id,
                        post.video_url
                    )
                else:
                    bot.send_photo(
                        call.message.chat.id,
                        post.url
                    )

                count += 1

                time.sleep(2)

            except Exception as e:
                print("Send error:", e)
    except Exception as e:

        bot.send_message(
            call.message.chat.id,
            "⚠️ Failed to fetch media. Username may not exist."
        )

        print(e)
        
print("Bot running...")

bot.infinity_polling()
    # ===============================
# IMPORT LIBRARIES
# ===============================

import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import requests
import re
import json
import time
# ===============================
# BOT CONFIG
# ===============================

TOKEN = "8628280617:AAEHHRQZ2dxsxoFWvmLs1PVO_wSCRn0rHPc"

bot = telebot.TeleBot(TOKEN)

# cooldown system
user_last_request = {}
COOLDOWN = 8

# ===============================
# EXTRACT USERNAME
# ===============================

def extract_username(text):

    text = text.strip()

    match = re.search(r"instagram\.com/([A-Za-z0-9_.]+)", text)

    if match:
        return match.group(1)

    return text

# ===============================
# FETCH PROFILE DATA
# ===============================

def fetch_profile_data(username):

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
# ===============================
# START COMMAND
# ===============================

@bot.message_handler(commands=['start'])
def start(message):

    bot.send_message(
        message.chat.id,
        "📸 Instagram Media Bot\n\nSend an Instagram username."
    )

# ===============================
# PROFILE HANDLER
# ===============================

@bot.message_handler(func=lambda m: True)
def handle_username(message):

    username = extract_username(message.text)

    data = fetch_profile_data(username)

    if not data:
        bot.send_message(message.chat.id, "❌ Profile not found.")
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

    btn1 = InlineKeyboardButton(
        "Latest Posts",
        callback_data=f"posts|{username}|0"
    )

    markup.add(btn1)

    bot.send_photo(
        message.chat.id,
        profile_pic,
        caption=text,
        reply_markup=markup
    )
# ===============================
# BUTTON HANDLER
# ===============================

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):

    user_id = call.from_user.id
    now = time.time()

    # cooldown check
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

    data = fetch_profile_data(username)

    if not data:
        bot.send_message(call.message.chat.id, "Profile not found.")
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

    # create next button
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
# ===============================
# RUN BOT
# ===============================

bot.infinity_polling()# ===============================
# IMPORT LIBRARIES
# ===============================

import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import requests
import re
import json
import time
# ===============================
# BOT CONFIG
# ===============================

TOKEN = "8628280617:AAEHHRQZ2dxsxoFWvmLs1PVO_wSCRn0rHPc"

bot = telebot.TeleBot(TOKEN)

# cooldown system
user_last_request = {}
COOLDOWN = 8

# ===============================
# EXTRACT USERNAME
# ===============================

def extract_username(text):

    text = text.strip()

    match = re.search(r"instagram\.com/([A-Za-z0-9_.]+)", text)

    if match:
        return match.group(1)

    return text

# ===============================
# FETCH PROFILE DATA
# ===============================

def fetch_profile_data(username):

    url = f"https://www.instagram.com/{username}/"

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    r = requests.get(url, headers=headers)

    if r.status_code != 200:
        return None

    html = r.text

    match = re.search(r"window\._sharedData = (.*?);</script>", html)

    if not match:
        return None

    data = json.loads(match.group(1))

    return data

# ===============================
# START COMMAND
# ===============================

@bot.message_handler(commands=['start'])
def start(message):

    bot.send_message(
        message.chat.id,
        "📸 Instagram Media Bot\n\nSend an Instagram username."
    )

# ===============================
# PROFILE HANDLER
# ===============================

@bot.message_handler(func=lambda m: True)
def handle_username(message):

    username = extract_username(message.text)

    data = fetch_profile_data(username)

    if not data:
        bot.send_message(message.chat.id, "❌ Profile not found.")
        return

    user = data["entry_data"]["ProfilePage"][0]["graphql"]["user"]

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

    btn1 = InlineKeyboardButton(
        "Latest Posts",
        callback_data=f"posts|{username}|0"
    )

    markup.add(btn1)

    bot.send_photo(
        message.chat.id,
        profile_pic,
        caption=text,
        reply_markup=markup
    )
# ===============================
# BUTTON HANDLER
# ===============================

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):

    user_id = call.from_user.id
    now = time.time()

    # cooldown check
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

    data = fetch_profile_data(username)

    if not data:
        bot.send_message(call.message.chat.id, "Profile not found.")
        return

    user = data["entry_data"]["ProfilePage"][0]["graphql"]["user"]

    edges = user["edge_owner_to_timeline_media"]["edges"]

    posts = edges[start:start+10]

    for post in posts:

        node = post["node"]

        if node["is_video"]:
            bot.send_video(call.message.chat.id, node["video_url"])
        else:
            bot.send_photo(call.message.chat.id, node["display_url"])

    # create next button
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
# ===============================
# RUN BOT
# ===============================

bot.infinity_polling()
