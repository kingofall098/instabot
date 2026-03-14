import telebot
import instaloader
import os
import uuid
import re
import time
import random

TOKEN = "8429656135:AAFZcHr-sKqcp5eBYsJWeP8YaSlvCeoyp2s"

bot = telebot.TeleBot(TOKEN)

DOWNLOAD_FOLDER = "downloads"
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# Instaloader setup
L = instaloader.Instaloader(
    download_video_thumbnails=False,
    download_comments=False,
    save_metadata=False,
    compress_json=False
)

# ------------------------
# Extract shortcode
# ------------------------

def extract_shortcode(url):
    pattern = r"(?:reel|p)/([A-Za-z0-9_-]+)"
    match = re.search(pattern, url)
    if match:
        return match.group(1)
    return None


# ------------------------
# Download media
# ------------------------

def get_media(url):

    shortcode = extract_shortcode(url)

    if not shortcode:
        return None

    try:

        time.sleep(random.uniform(2,4))

        post = instaloader.Post.from_shortcode(L.context, shortcode)

        folder = os.path.join(DOWNLOAD_FOLDER, str(uuid.uuid4()))
        os.makedirs(folder, exist_ok=True)

        L.download_post(post, target=folder)

        media_files = []

        for root, dirs, files in os.walk(folder):

            for file in files:

                if file.endswith(".jpg") or file.endswith(".mp4"):

                    media_files.append(os.path.join(root, file))

        return media_files

    except Exception as e:
        print("Download error:", e)
        return None


# ------------------------
# Start command
# ------------------------

@bot.message_handler(commands=["start"])
def start(message):

    bot.reply_to(
        message,
        "Send an Instagram post or reel link."
    )


# ------------------------
# Handle link
# ------------------------

@bot.message_handler(func=lambda m: m.text and "instagram.com" in m.text)
def download(message):

    bot.reply_to(message, "Downloading media...")

    media = get_media(message.text)

    if not media:
        bot.reply_to(message, "Could not download media.")
        return

    for file in media:

        try:

            if file.endswith(".mp4"):

                with open(file, "rb") as f:
                    bot.send_video(
                        message.chat.id,
                        f,
                        supports_streaming=True
                    )

            else:

                with open(file, "rb") as f:
                    bot.send_photo(message.chat.id, f)

        except Exception as e:
            print("Send error:", e)


# ------------------------
# Run bot
# ------------------------

print("Bot running...")

bot.remove_webhook()

bot.infinity_polling(skip_pending=True)
