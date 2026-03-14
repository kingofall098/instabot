#RUNING CODE FOR INSTA DOWNLOAD
import telebot
import requests
import time
import random
import json
from bs4 import BeautifulSoup

TOKEN = "8780791852:AAHqVZYRVc7QEyzCNxzAqIdfDCZuoMPZtYY"

bot = telebot.TeleBot(TOKEN)

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.instagram.com/"
}

session = requests.Session()
session.headers.update(headers)
import re
def clean_instagram_url(url):
    return url.split("?")[0]
def extract_shortcode(url):

    pattern = r"(?:reel|p)/([A-Za-z0-9_-]+)"

    match = re.search(pattern, url)

    if match:
        return match.group(1)

    return None
def debug(msg):
    print(f"[DEBUG] {msg}")

@bot.message_handler(commands=['start'])
def start(message):

    bot.reply_to(
        message,
        "Send an Instagram link and I will download the media."
    )

import yt_dlp
import requests
import os
import uuid
from bs4 import BeautifulSoup

def get_media(url):

    url = clean_instagram_url(url)

    debug(f"Downloading with yt-dlp: {url}")

    folder = "downloads"
    os.makedirs(folder, exist_ok=True)

    filename = os.path.join(folder, str(uuid.uuid4()))

    try:

        ydl_opts = {
            "quiet": True,
            "cookiefile": "cookies.txt",
            "ignoreerrors": True
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:

            info = ydl.extract_info(url, download=True)

            if info:

                if "entries" in info:
                    files = []
                    for e in info["entries"]:
                        files.append(ydl.prepare_filename(e))
                    return files
                else:
                    return [ydl.prepare_filename(info)]

    except Exception as e:
        debug(f"yt-dlp failed: {e}")

    # -------- fallback method --------

    debug("Trying fallback extraction")

    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})

    debug(f"Page status: {r.status_code}")

    soup = BeautifulSoup(r.text, "html.parser")

    video = soup.find("meta", property="og:video")
    image = soup.find("meta", property="og:image")

    files = []

    if video:

        debug("Found video in meta tags")

        media_url = video["content"]
        path = filename + ".mp4"

    elif image:

        debug("Found image in meta tags")

        media_url = image["content"]
        path = filename + ".jpg"

    else:

        debug("No media meta tags found")
        return None

    debug(f"Downloading media: {media_url}")

    data = requests.get(media_url).content

    with open(path, "wb") as f:
        f.write(data)

    debug("Media downloaded successfully")

    files.append(path)

    return files
@bot.message_handler(func=lambda m: m.text and "instagram.com" in m.text)
def download(message):

    debug("User sent Instagram link")

    bot.reply_to(message, "Downloading media...")

    media = get_media(message.text)

    if not media:
        bot.reply_to(message, "Could not download media.")
        return

    for file in media:

        if not os.path.exists(file):
            continue

        if file.endswith(".mp4"):
            bot.send_video(message.chat.id, open(file, "rb"))
        else:
            bot.send_photo(message.chat.id, open(file, "rb"))
print("Bot running...")

bot.remove_webhook()

while True:

    try:

        bot.infinity_polling(skip_pending=True)

    except Exception as e:

        print("Polling error:", e)
        time.sleep(5)
