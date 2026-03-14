#DOWNOWLOAD INSTA MEDIA THROUGH LINK
import os
import re
import json
import uuid
import logging
import requests
from datetime import datetime
import pytz
from http.cookiejar import MozillaCookieJar

from telegram.ext import Application, CommandHandler, MessageHandler, filters
from telegram.constants import ChatAction

from instaloader import Instaloader, Post

import time
import random

time.sleep(random.uniform(1,2))
# ===============================
# CONFIG
# ===============================

TOKEN = "8628280617:AAEHHRQZ2dxsxoFWvmLs1PVO_wSCRn0rHPc"

COOKIE_FILE = "cookies.txt"

USERS_LOG_FILE = "users.log"
ADMIN_FILE = "admin.json"

DOWNLOAD_DIR = "downloads"

TASHKENT_TZ = pytz.timezone("Asia/Tashkent")

os.makedirs(DOWNLOAD_DIR, exist_ok=True)


# ===============================
# LOGGER
# ===============================

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# ===============================
# INSTAGRAM COOKIE SESSION
# ===============================

loader = Instaloader()


def load_cookie_session():

    if not os.path.exists(COOKIE_FILE):

        print("❌ Cookie file not found!")
        print("Put your exported cookies in:", COOKIE_FILE)
        exit()

    cookie_jar = MozillaCookieJar(COOKIE_FILE)

    cookie_jar.load(ignore_discard=True, ignore_expires=True)

    for cookie in cookie_jar:

        loader.context._session.cookies.set_cookie(cookie)

    print("✅ Instagram cookies loaded")


load_cookie_session()


# ===============================
# ADMIN SYSTEM
# ===============================

def get_admin():

    if os.path.exists(ADMIN_FILE):

        with open(ADMIN_FILE) as f:
            return json.load(f).get("admin_id")

    return None


def set_admin(user_id):

    if not os.path.exists(ADMIN_FILE):

        with open(ADMIN_FILE, "w") as f:
            json.dump({"admin_id": user_id}, f)


# ===============================
# USER LOGGING
# ===============================

def log_user(user):

    tashkent_time = datetime.now(TASHKENT_TZ)

    data = {
        "user_id": user.id,
        "username": user.username,
        "first_name": user.first_name,
        "timestamp": tashkent_time.strftime("%Y-%m-%d %H:%M:%S")
    }

    users = []

    if os.path.exists(USERS_LOG_FILE):

        with open(USERS_LOG_FILE) as f:
            users = json.load(f)

    for u in users:

        if u["user_id"] == data["user_id"]:
            u["timestamp"] = data["timestamp"]
            break
    else:
        users.append(data)

    with open(USERS_LOG_FILE, "w") as f:
        json.dump(users, f, indent=4)


# ===============================
# USER STATS COMMAND
# ===============================

async def list_users(update, context):

    user = update.effective_user

    if user.id != get_admin():

        await update.message.reply_text("❌ Admin only command")
        return

    if not os.path.exists(USERS_LOG_FILE):

        await update.message.reply_text("No users yet.")
        return

    with open(USERS_LOG_FILE) as f:
        users = json.load(f)

    total = len(users)

    today = datetime.now(TASHKENT_TZ).date()

    today_users = sum(
        1 for u in users
        if datetime.strptime(u["timestamp"], "%Y-%m-%d %H:%M:%S").date() == today
    )

    msg = f"📊 Total Users: {total}\n"
    msg += f"🌍 Active Today: {today_users}\n\n"

    for u in users:

        msg += (
            f"👤 {u['first_name']}\n"
            f"ID: {u['user_id']}\n"
            f"Username: @{u['username'] or 'N/A'}\n"
            f"Last Active: {u['timestamp']}\n\n"
        )

    await update.message.reply_text(msg)


# ===============================
# URL HELPERS
# ===============================

# def extract_shortcode(url):

#     m = re.search(r"instagram\.com/(?:p|reel|tv)/([^/?#&]+)", url)

#     return m.group(1) if m else None


# def valid_instagram_url(url):

#     return bool(
#         re.match(
#             r"https?://(www\.)?instagram\.com/(p|reel|tv)/",
#             url
#         )
        
#     )
def valid_instagram_url(url):

    if "instagram.com" not in url:
        return False

    if "/p/" in url or "/reel/" in url or "/tv/" in url:
        return True

    return False
def extract_shortcode(url):

    match = re.search(r"(?:p|reel|tv)/([^/?#&]+)", url)

    if match:
        return match.group(1)

    return None

# ===============================
# FETCH MEDIA URL
# ===============================

def fetch_instagram_media(url):

    shortcode = extract_shortcode(url)

    if not shortcode:
        return None

    try:

        post = Post.from_shortcode(loader.context, shortcode)

        media_list = []

        # Carousel post
        if post.typename == "GraphSidecar":

            for node in post.get_sidecar_nodes():

                if node.is_video:
                    media_list.append(("video", node.video_url))
                else:
                    media_list.append(("photo", node.display_url))

        # Single video
        elif post.is_video:

            media_list.append(("video", post.video_url))

        # Single image
        else:

            media_list.append(("photo", post.url))

        return media_list

    except Exception as e:

        logger.error(f"Instagram error: {e}")

        return None    
# ===============================
# START COMMAND
# ===============================

async def start(update, context):

    user = update.effective_user

    log_user(user)

    if get_admin() is None:

        set_admin(user.id)

        await update.message.reply_text("👑 You are now admin")

    await update.message.reply_text(
        "👋 Send a public Instagram post or reel link."
    )


# ===============================
# DOWNLOAD HANDLER
# ===============================

async def download(update, context):

    user = update.effective_user

    log_user(user)

    url = update.message.text.strip()

    if not valid_instagram_url(url):

        await update.message.reply_text("❌ Invalid Instagram URL")
        return

    await update.message.chat.send_action(ChatAction.TYPING)

    progress = await update.message.reply_text("⏳ Fetching media...")

    media_items = fetch_instagram_media(url)

    if not media_items:
        await progress.edit_text("❌ Failed to fetch media")
        return

    for media_type, media_url in media_items:

        ext = ".mp4" if media_type == "video" else ".jpg"

        file_path = os.path.join(DOWNLOAD_DIR, f"{uuid.uuid4()}{ext}")

        r = requests.get(
            media_url,
            stream=True,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://www.instagram.com/"
            }
        )

        with open(file_path, "wb") as f:
            for chunk in r.iter_content(1024):
                f.write(chunk)

        with open(file_path, "rb") as f:

                if ext == ".mp4":

                    await context.bot.send_video(
                        chat_id=update.effective_chat.id,
                        video=f,
                        caption="waism",
                        width=720,
                        height=1280,
                        supports_streaming=True
                    )

                else:

                    await context.bot.send_photo(
                        chat_id=update.effective_chat.id,
                        photo=f,
                        caption="wasim"
                    )

        os.remove(file_path)    
        try:
            await progress.delete()
        except:
            pass


# ===============================
# MAIN
# ===============================

def main():

    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("users", list_users))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download))

    print("Bot running...")

    application.run_polling()


if __name__ == "__main__":
    main()
