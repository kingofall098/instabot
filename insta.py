from telegram.ext import Updater, CommandHandler, MessageHandler, Filters
from telegram import ChatAction
import threading
import logging
import re
import os
from instaloader import Instaloader, Post
from dotenv import load_dotenv
import requests
import json
from datetime import datetime
import pytz
from telegram import ParseMode  # For safe formatting
TASHKENT_TZ = pytz.timezone("Asia/Tashkent")

# Load environment variables
load_dotenv()

# Logger setup
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Telegram Bot Token
TOKEN = "8756448611:AAHbnOlBbZP8639ZKHcFZd0vSQeK54EMSYQ"

# Instagram credentials
USERNAME = os.getenv("INSTAGRAM_USERNAME")
PASSWORD = os.getenv("INSTAGRAM_PASSWORD")

# File paths
USERS_LOG_FILE = "users.log"
ADMIN_FILE = "admin.json"

# Instaloader setup
loader = Instaloader()

# Session file path
SESSION_FILE = f"{os.getcwd()}/session-{USERNAME}"

session_lock = threading.Lock()

def load_or_create_session():
    with session_lock:
        if os.path.exists(SESSION_FILE):
            loader.load_session_from_file(USERNAME, filename=SESSION_FILE)
        else:
            loader.login(USERNAME, PASSWORD)
            loader.save_session_to_file(SESSION_FILE)

load_or_create_session()

# Admin-related functions
def get_admin():
    if os.path.exists(ADMIN_FILE):
        with open(ADMIN_FILE, "r") as file:
            return json.load(file).get("admin_id")
    return None

def set_admin(user_id):
    if not os.path.exists(ADMIN_FILE):  # Set admin only once
        with open(ADMIN_FILE, "w") as file:
            json.dump({"admin_id": user_id}, file)

# User logging function
def log_user_data(user):
    # Get the current time in the server's timezone and convert it to Tashkent time
    server_time = datetime.now()
    tashkent_time = server_time.astimezone(TASHKENT_TZ)

    user_data = {
        "user_id": user.id,
        "username": user.username,
        "first_name": user.first_name,
        "timestamp": tashkent_time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    try:
        # Read existing data
        if os.path.exists(USERS_LOG_FILE):
            with open(USERS_LOG_FILE, "r") as file:
                users = json.load(file)
        else:
            users = []

        # Update the timestamp if the user already exists
        for existing_user in users:
            if existing_user["user_id"] == user_data["user_id"]:
                existing_user["timestamp"] = user_data["timestamp"]
                break
        else:
            # Add new user if not found
            users.append(user_data)

        # Write updated data back to the file
        with open(USERS_LOG_FILE, "w") as file:
            json.dump(users, file, indent=4)

    except Exception as e:
        logger.error(f"Error logging user data: {e}")

# Command to list users and total counts
def list_users(update, context):
    user = update.effective_user
    admin_id = get_admin()

    if user.id != admin_id:
        update.message.reply_text("❌ You don't have permission to use this command.")
        return

    try:
        if os.path.exists(USERS_LOG_FILE):
            with open(USERS_LOG_FILE, "r") as file:
                users = json.load(file)

            if not users:
                update.message.reply_text("No users have used the bot yet.")
                return

            # Calculate total users and users who used the bot today
            total_users = len(users)
            today_users = sum(
                1 for u in users if datetime.strptime(u['timestamp'], "%Y-%m-%d %H:%M:%S").date() == datetime.now(TASHKENT_TZ).date()
            )

            # Preparing the response
            response = f"📊 Total users: {total_users}\n"
            response += f"🌍 Users who used today: {today_users}\n\n"
            response += "📋 List of users who used the bot:\n\n"
            for u in users:
                response += (
                    f"👤 User ID: {u['user_id']}\n"
                    f"   Username: @{u['username'] or 'N/A'}\n"
                    f"   First Name: {u['first_name']}\n"
                    f"   Last Active: {u['timestamp']}\n\n"
                )
            update.message.reply_text(response)
        else:
            update.message.reply_text("No user log file found. No users have used the bot yet.")
    except Exception as e:
        logger.error(f"Error reading user log file: {e}")
        update.message.reply_text("⚠️ An error occurred while retrieving user data.")


# Helper functions
def extract_shortcode(instagram_post):
    match = re.search(r"instagram\.com/(?:p|reel|tv)/([^/?#&]+)", instagram_post)
    return match.group(1) if match else None

def is_valid_instagram_url(url):
    return bool(re.match(r"https?://(www\.)?instagram\.com/(p|reel|tv)/", url))

def fetch_instagram_data(instagram_post):
    shortcode = extract_shortcode(instagram_post)
    if not shortcode:
        return None

    try:
        post = Post.from_shortcode(loader.context, shortcode)
        return post.video_url if post.is_video else post.url
    except Exception as e:
        logger.error(f"Error fetching Instagram data: {e}")
        return None

# Command: Start
def start(update, context):
    user = update.effective_user
    log_user_data(user)

    if get_admin() is None:
        set_admin(user.id)
        update.message.reply_text("👑 You have been set as the admin!")

    update.message.reply_text(
        "👋 Welcome to the Instagram Saver Bot!\n\n"
        "📩 Send me any **public** Instagram link (post, reel, or IGTV), and I'll fetch the media for you.\n"
        "⚠️ Make sure the post is **public** and not private.\n\n"
        "Happy downloading! 🎉"
    )

# Handle: Download with Threading
def download(update, context):
    thread = threading.Thread(target=process_download, args=(update, context))
    thread.start()

def process_download(update, context):
    user = update.effective_user
    log_user_data(user)

    instagram_post = update.effective_message.text.strip()
    if not is_valid_instagram_url(instagram_post):
        update.message.reply_text("❌ Invalid Instagram URL. Please send a valid post, Reel, or IGTV link.")
        return

    update.message.reply_chat_action(ChatAction.TYPING)
    progress_message = update.message.reply_text("⏳ Fetching your media...")

    media_url = fetch_instagram_data(instagram_post)
    if not media_url:
        progress_message.edit_text("❌ Failed to fetch media. Ensure the post is public and try again.")
        return

    file_name = f"temp_{update.message.chat_id}.mp4" if "video" in media_url else f"temp_{update.message.chat_id}.jpg"
    try:
        response = requests.get(media_url, stream=True)
        response.raise_for_status()
        with open(file_name, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024):
                f.write(chunk)

        with open(file_name, "rb") as file:
            if "video" in media_url:
                context.bot.send_video(chat_id=update.message.chat_id, video=file, caption="👾 Powered by @Instasave_downloader_bot")
            else:
                context.bot.send_photo(chat_id=update.message.chat_id, photo=file, caption="👾 Powered by @Instasave_downloader_bot")

        progress_message.delete()
    except Exception as e:
        logger.error(f"Error sending media: {e}")
        progress_message.edit_text("❌ Failed to send media. Please try again later.")
    finally:
        if os.path.exists(file_name):
            os.remove(file_name)

# Main function
def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("users", list_users))  # Add /users command
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, download))

    updater.start_polling()
    logger.info("Bot started and polling for updates...")
    updater.idle()

if __name__ == "__main__":
    main()
