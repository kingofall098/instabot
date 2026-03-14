import os
import re
import json
import uuid
import time
import random
import logging
import requests
from datetime import datetime
import pytz
from http.cookiejar import MozillaCookieJar

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from telegram.constants import ChatAction

from instaloader import Instaloader, Post


# ===============================
# CONFIG
# ===============================

TOKEN = "8695844889:AAG4-jb2S1Y9BAF5O92WxkWZOaeubM5P3o8"

COOKIE_FILE = "cookies.txt"

DOWNLOAD_DIR = "downloads"
USERS_FILE = "users.json"
ADMIN_FILE = "admin.json"

TASHKENT_TZ = pytz.timezone("Asia/Tashkent")

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# ===============================
# LOGGER
# ===============================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ===============================
# INSTAGRAM SESSION
# ===============================

loader = Instaloader()

def load_cookie_session():

    jar = MozillaCookieJar(COOKIE_FILE)

    jar.load(ignore_discard=True, ignore_expires=True)

    for cookie in jar:
        loader.context._session.cookies.set_cookie(cookie)

    print("Instagram cookies loaded")

load_cookie_session()

# ===============================
# MEMORY STATE
# ===============================

profile_state = {}  # pagination memory

# ===============================
# ADMIN SYSTEM
# ===============================

def get_admin():

    if os.path.exists(ADMIN_FILE):
        with open(ADMIN_FILE) as f:
            return json.load(f)["admin_id"]

    return None


def set_admin(user_id):

    if not os.path.exists(ADMIN_FILE):
        with open(ADMIN_FILE, "w") as f:
            json.dump({"admin_id": user_id}, f)

# ===============================
# USER LOGGING
# ===============================

def log_user(user):

    time_now = datetime.now(TASHKENT_TZ).strftime("%Y-%m-%d %H:%M:%S")

    data = {
        "id": user.id,
        "username": user.username,
        "name": user.first_name,
        "time": time_now
    }

    users = []

    if os.path.exists(USERS_FILE):

        with open(USERS_FILE) as f:
            users = json.load(f)

    if not any(u["id"] == user.id for u in users):
        users.append(data)

    with open(USERS_FILE, "w") as f:
        json.dump(users, f, indent=2)

# ===============================
# URL HELPERS
# ===============================

def is_instagram_link(text):

    return "instagram.com" in text


def extract_shortcode(url):

    m = re.search(r"(?:p|reel|tv)/([^/?#&]+)", url)

    return m.group(1) if m else None

# ===============================
# FETCH POST MEDIA
# ===============================

def fetch_post_media(url):

    shortcode = extract_shortcode(url)

    if not shortcode:
        return None

    try:

        post = Post.from_shortcode(loader.context, shortcode)

        media = []

        if post.typename == "GraphSidecar":

            for node in post.get_sidecar_nodes():

                if node.is_video:
                    media.append(("video", node.video_url))
                else:
                    media.append(("photo", node.display_url))

        elif post.is_video:
            media.append(("video", post.video_url))

        else:
            media.append(("photo", post.url))

        return media

    except Exception as e:

        logger.error(e)

        return None

# ===============================
# FETCH PROFILE POSTS
# ===============================

def fetch_profile_posts(username, start=0, limit=10):

    try:

        profile = loader.check_profile_id(username)

        posts = []

        for i, post in enumerate(profile.get_posts()):

            if i < start:
                continue

            if len(posts) >= limit:
                break

            if post.is_video:
                posts.append(("video", post.video_url))
            else:
                posts.append(("photo", post.url))

        return posts

    except Exception as e:

        logger.error(e)

        return None

# ===============================
# START
# ===============================

async def start(update, context):

    user = update.effective_user

    log_user(user)

    if get_admin() is None:

        set_admin(user.id)

        await update.message.reply_text("You are now admin.")

    await update.message.reply_text(
        "Send Instagram username or post link."
    )

# ===============================
# HANDLE USER MESSAGE
# ===============================

async def handle_message(update, context):

    user = update.effective_user

    log_user(user)

    text = update.message.text.strip()

    await update.message.chat.send_action(ChatAction.TYPING)

    # --------------------------------
    # INSTAGRAM LINK MODE
    # --------------------------------

    if is_instagram_link(text):

        media = fetch_post_media(text)

        if not media:
            await update.message.reply_text("Failed to fetch media")
            return

        for mtype, url in media:

            if mtype == "video":
                await context.bot.send_video(update.effective_chat.id, url)
            else:
                await context.bot.send_photo(update.effective_chat.id, url)

        return

    # --------------------------------
    # USERNAME MODE
    # --------------------------------

    username = text.replace("@","")

    await update.message.reply_text("Checking profile...")

    time.sleep(random.uniform(4,7))

    posts = fetch_profile_posts(username,0,10)

    if not posts:
        await update.message.reply_text("Profile not found or private.")
        return

    profile_state[user.id] = {
        "username": username,
        "offset": 10
    }

    for mtype, url in posts:

        if mtype == "video":
            await context.bot.send_video(update.effective_chat.id, url)
        else:
            await context.bot.send_photo(update.effective_chat.id, url)

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Next 10 ▶️", callback_data="next")]
    ])

    await update.message.reply_text("Load more?", reply_markup=keyboard)

# ===============================
# NEXT POSTS BUTTON
# ===============================

async def next_posts(update, context):

    query = update.callback_query

    await query.answer()

    user_id = query.from_user.id

    if user_id not in profile_state:

        await query.message.reply_text("Session expired.")
        return

    username = profile_state[user_id]["username"]

    offset = profile_state[user_id]["offset"]

    posts = fetch_profile_posts(username, offset, 10)

    if not posts:

        await query.message.reply_text("No more posts.")
        return

    profile_state[user_id]["offset"] += 10

    for mtype, url in posts:

        if mtype == "video":
            await context.bot.send_video(user_id, url)
        else:
            await context.bot.send_photo(user_id, url)

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Next 10 ▶️", callback_data="next")]
    ])

    await context.bot.send_message(user_id,"Load more?",reply_markup=keyboard)

# ===============================
# MAIN
# ===============================

def main():

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    app.add_handler(CallbackQueryHandler(next_posts, pattern="next"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot running...")

    app.run_polling()

if __name__ == "__main__":
    main()
