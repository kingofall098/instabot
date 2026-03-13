# =====================================
# IMPORT LIBRARIES
# =====================================

import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import requests
import time
import random
import re


# =====================================
# BOT CONFIG
# =====================================

TOKEN = "8780791852:AAHqVZYRVc7QEyzCNxzAqIdfDCZuoMPZtYY"

bot = telebot.TeleBot(TOKEN)

post_cache = {}
user_last_request = {}

COOLDOWN = 10


# =====================================
# PROXY CONFIG (PHONE / LOCAL PROXY)
# =====================================

PHONE_PROXY = "http://192.0.0.4:8080"   # change if using phone proxy


def get_proxy():

    return {
        "http": PHONE_PROXY,
        "https": PHONE_PROXY
    }


# =====================================
# SESSION
# =====================================

session = requests.Session()

session.headers.update({
    "User-Agent": "Mozilla/5.0",
    "X-IG-App-ID": "936619743392459"
})


# =====================================
# USERNAME EXTRACTION
# =====================================

def extract_username(text):

    text = text.strip()

    match = re.search(r"instagram\.com/([A-Za-z0-9_.]+)", text)

    if match:
        return match.group(1)

    return text


# =====================================
# FETCH INSTAGRAM PROFILE
# =====================================

def fetch_profile(username):

    url = "https://i.instagram.com/api/v1/users/web_profile_info/"

    params = {"username": username.lower()}

    # ---------- TRY WITH PROXY ----------

    for attempt in range(5):

        try:

            delay = random.uniform(2,5)
            print("Delay:", delay)

            time.sleep(delay)

            r = session.get(
                url,
                params=params,
                proxies=get_proxy(),
                timeout=15
            )

            print("Status:", r.status_code)

            if r.status_code == 200:

                data = r.json()

                return data["data"]["user"]["edge_owner_to_timeline_media"]

        except Exception as e:

            print("Proxy attempt failed:", e)


    # ---------- FALLBACK WITHOUT PROXY ----------

    print("Trying direct connection...")

    for attempt in range(3):

        try:

            delay = random.uniform(2,5)

            time.sleep(delay)

            r = session.get(
                url,
                params=params,
                timeout=15
            )

            if r.status_code == 200:

                data = r.json()

                return data["data"]["user"]["edge_owner_to_timeline_media"]

        except Exception as e:

            print("Direct attempt failed:", e)

    return None


# =====================================
# START COMMAND
# =====================================

@bot.message_handler(commands=['start'])
def start(message):

    bot.send_message(
        message.chat.id,
        "📸 Instagram Downloader\n\nSend an Instagram username or profile link."
    )


# =====================================
# PROFILE HANDLER
# =====================================

@bot.message_handler(func=lambda m: True)
def profile_handler(message):

    username = extract_username(message.text)

    data = fetch_profile(username)

    if not data:

        bot.send_message(message.chat.id, "❌ Profile not found or request failed.")
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
        f"Found {len(edges)} posts.",
        reply_markup=markup
    )


# =====================================
# BUTTON HANDLER
# =====================================

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):

    user_id = call.from_user.id
    now = time.time()

    # cooldown protection
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

        bot.send_message(call.message.chat.id, "Cache expired. Send username again.")
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
# PAGINATION
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

bot.remove_webhook()

time.sleep(1)

bot.infinity_polling(
    timeout=30,
    long_polling_timeout=30
)
