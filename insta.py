# ==============================
# TELEGRAM INSTAGRAM DOWNLOADER
# USING INSTALOADER
# ==============================

import telebot
import instaloader
import os
import re
import uuid
import time

TOKEN = "8780791852:AAHqVZYRVc7QEyzCNxzAqIdfDCZuoMPZtYY"

bot = telebot.TeleBot(TOKEN)

# ==============================
# INSTALOADER SETUP
# ==============================

L = instaloader.Instaloader(
    download_videos=True,
    download_video_thumbnails=False,
    download_comments=False,
    save_metadata=False,
    compress_json=False
)

DOWNLOAD_FOLDER = "downloads"
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)


# ==============================
# HELPER FUNCTIONS
# ==============================

def extract_shortcode(url):
    pattern = r"(?:reel|p)/([A-Za-z0-9_-]+)"
    match = re.search(pattern, url)

    if match:
        return match.group(1)

    return None


def download_post(url):

    shortcode = extract_shortcode(url)

    if not shortcode:
        return None

    try:

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


# ==============================
# BOT COMMANDS
# ==============================

@bot.message_handler(commands=["start"])
def start(message):

    bot.reply_to(
        message,
        "Send an Instagram post or reel link and I will download the media."
    )


# ==============================
# LINK HANDLER
# ==============================

@bot.message_handler(func=lambda m: m.text and "instagram.com" in m.text)
def handle_link(message):

    url = message.text.strip()

    bot.reply_to(message, "Downloading media...")

    media = download_post(url)

    if not media:

        bot.reply_to(message, "Could not download media.")
        return

    for file in media:

        try:

            if file.endswith(".mp4"):

                with open(file, "rb") as f:
                    bot.send_video(message.chat.id, f)

            else:

                with open(file, "rb") as f:
                    bot.send_photo(message.chat.id, f)

        except Exception as e:
            print("Send error:", e)

    time.sleep(1)


# ==============================
# RUN BOT
# ==============================

print("Bot running...")

bot.remove_webhook()

while True:

    try:

        bot.infinity_polling(skip_pending=True)

    except Exception as e:

        print("Polling error:", e)

        time.sleep(5)
