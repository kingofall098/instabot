import telebot
import requests
import time
import random
import yt_dlp
import os
import uuid
import re
from bs4 import BeautifulSoup

# =========================
# BOT TOKEN
# =========================

TOKEN = "8429656135:AAFZcHr-sKqcp5eBYsJWeP8YaSlvCeoyp2s"

bot = telebot.TeleBot(TOKEN)

# =========================
# SESSION
# =========================

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.instagram.com/"
}

session = requests.Session()
session.headers.update(headers)

# =========================
# DOWNLOAD FOLDER
# =========================

DOWNLOAD_FOLDER = "downloads"
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# =========================
# DEBUG LOGGER
# =========================

def debug(msg):
    print(f"[DEBUG] {msg}")

# =========================
# CLEAN URL
# =========================

def clean_instagram_url(url):
    return url.split("?")[0]

# =========================
# START COMMAND
# =========================

@bot.message_handler(commands=['start'])
def start(message):

    bot.reply_to(
        message,
        "Send an Instagram post or reel link and I will download the media."
    )

# =========================
# MEDIA DOWNLOADER
# =========================

def get_media(url):

    url = clean_instagram_url(url)

    filename = os.path.join(DOWNLOAD_FOLDER, str(uuid.uuid4()))

    debug("Trying yt-dlp extraction")

    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "ignoreerrors": True,
        "cookiefile": "cookies.txt"
    }

    media_urls = []

    try:

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:

            info = ydl.extract_info(url, download=False)

            if not info:
                debug("yt-dlp returned no info")
            else:

                # carousel posts
                if "entries" in info and info["entries"]:

                    for entry in info["entries"]:

                        media = (
                            entry.get("url")
                            or entry.get("thumbnail")
                            or entry.get("display_url")
                        )

                        if media:
                            media_urls.append(media)

                else:

                    media = (
                        info.get("url")
                        or info.get("thumbnail")
                        or info.get("display_url")
                    )

                    if media:
                        media_urls.append(media)

    except Exception as e:
        debug(f"yt-dlp error: {e}")

    debug(f"Extracted {len(media_urls)} media URLs")

    downloaded_files = []

    # =========================
    # DOWNLOAD MEDIA
    # =========================

    for media_url in media_urls:

        time.sleep(random.uniform(1.5,3))

        ext = ".mp4" if ".mp4" in media_url else ".jpg"

        path = filename + ext

        debug(f"Downloading: {media_url}")

        r = session.get(media_url, stream=True)

        if r.status_code != 200:
            debug(f"Download failed ({r.status_code})")
            continue

        with open(path, "wb") as f:

            for chunk in r.iter_content(1024):

                if chunk:
                    f.write(chunk)

        downloaded_files.append(path)

    # if successful return
    if downloaded_files:
        return downloaded_files

    # =========================
    # FALLBACK SCRAPER
    # =========================

    debug("Trying fallback extraction")

    try:

        r = session.get(url)

        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, "html.parser")

        video = soup.find("meta", property="og:video")
        image = soup.find("meta", property="og:image")

        if video:
            media_url = video["content"]
            ext = ".mp4"

        elif image:
            media_url = image["content"]
            ext = ".jpg"

        else:
            debug("No media found in fallback")
            return None

        path = filename + ext

        r = session.get(media_url, stream=True)

        with open(path, "wb") as f:
            for chunk in r.iter_content(1024):
                if chunk:
                    f.write(chunk)

        return [path]

    except Exception as e:
        debug(f"Fallback failed: {e}")
        return None

# =========================
# HANDLE INSTAGRAM LINKS
# =========================

@bot.message_handler(func=lambda m: m.text and "instagram.com" in m.text)
def download(message):

    debug("User sent Instagram link")

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
                        supports_streaming=True,
                        width=720,
                        height=1280
                    )

            else:

                with open(file, "rb") as f:

                    bot.send_photo(
                        message.chat.id,
                        f
                    )

        except Exception as e:
            debug(f"Send error: {e}")

# =========================
# RUN BOT
# =========================

print("Bot running...")

bot.remove_webhook()

bot.infinity_polling(skip_pending=True)
