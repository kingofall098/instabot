import telebot
import requests
import time
import random

# ==============================
# BOT TOKEN
# ==============================

TOKEN = "8780791852:AAHqVZYRVc7QEyzCNxzAqIdfDCZuoMPZtYY"

bot = telebot.TeleBot(TOKEN)

# ==============================
# BROWSER HEADERS
# ==============================

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "Referer": "https://www.instagram.com/",
}

# Create session (like real browser)
session = requests.Session()
session.headers.update(headers)


# ==============================
# INSTAGRAM MEDIA EXTRACTOR
# ==============================

def get_media(url):

    try:

        # random human delay
        delay = random.uniform(2, 5)
        print("Delay:", delay)
        time.sleep(delay)

        if "?" in url:
            url = url.split("?")[0]

        if not url.endswith("/"):
            url += "/"

        api = url + "?__a=1&__d=dis"

        r = session.get(api)

        if r.status_code != 200:
            return None

        data = r.json()

        media = data["graphql"]["shortcode_media"]

        items = []

        # PHOTO
        if media["__typename"] == "GraphImage":

            items.append({
                "type": "photo",
                "url": media["display_url"]
            })

        # VIDEO / REEL
        elif media["__typename"] == "GraphVideo":

            items.append({
                "type": "video",
                "url": media["video_url"]
            })

        # CAROUSEL
        elif media["__typename"] == "GraphSidecar":

            for edge in media["edge_sidecar_to_children"]["edges"]:

                node = edge["node"]

                if node["is_video"]:

                    items.append({
                        "type": "video",
                        "url": node["video_url"]
                    })

                else:

                    items.append({
                        "type": "photo",
                        "url": node["display_url"]
                    })

        return items

    except Exception as e:
        print("Downloader error:", e)
        return None


# ==============================
# BOT COMMANDS
# ==============================

@bot.message_handler(commands=['start'])
def start(message):

    bot.reply_to(
        message,
        "📥 Send an Instagram link (post / reel / video)\nI will download the media."
    )


# ==============================
# LINK HANDLER
# ==============================

@bot.message_handler(func=lambda m: m.text and "instagram.com" in m.text)
def download(message):

    bot.reply_to(message, "⏳ Fetching media...")

    media = get_media(message.text)

    if not media:

        bot.reply_to(message, "❌ Could not download media.")
        return

    for item in media:

        try:

            if item["type"] == "photo":

                bot.send_photo(
                    message.chat.id,
                    item["url"]
                )

            else:

                bot.send_video(
                    message.chat.id,
                    item["url"]
                )

        except Exception as e:

            print("Send error:", e)


# ==============================
# START BOT
# ==============================

print("Bot running...")

bot.remove_webhook()

while True:

    try:

        bot.infinity_polling(
            timeout=10,
            long_polling_timeout=5,
            skip_pending=True
        )

    except Exception as e:

        print("Polling error:", e)
        time.sleep(5)
