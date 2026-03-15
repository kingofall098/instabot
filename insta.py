import telebot
import requests
import re
import time
import random

# =========================
# BOT TOKEN
# =========================

TOKEN = "8755937047:AAHBFaKCan-W8QLls2DDJ3-XpUdyw3tP16w"

bot = telebot.TeleBot(TOKEN)

# =========================
# INSTAGRAM SESSION
# =========================

SESSIONID = open("session.txt").read().strip()

# =========================
# GET INSTAGRAM POSTS
# =========================

def get_user_posts(username):

    url = f"https://i.instagram.com/api/v1/users/web_profile_info/?username={username}"

    headers = {
        "User-Agent": "Mozilla/5.0",
        "x-ig-app-id": "936619743392459",
        "cookie": f"sessionid={SESSIONID}"
    }

    r = requests.get(url, headers=headers)

    if r.status_code != 200:
        return []

    data = r.json()

    posts = []

    try:

        edges = data["data"]["user"]["edge_owner_to_timeline_media"]["edges"]

        for edge in edges:

            node = edge["node"]

            shortcode = node["shortcode"]

            post_url = f"https://www.instagram.com/p/{shortcode}/"

            posts.append(post_url)

    except:
        return []

    return posts


# =========================
# GET MEDIA FROM POST
# =========================

def get_media(post_url):

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    r = requests.get(post_url, headers=headers)

    html = r.text

    video = re.search(r'property="og:video" content="([^"]+)"', html)
    image = re.search(r'property="og:image" content="([^"]+)"', html)

    media = []

    if video:
        media.append(("video", video.group(1)))

    if image:
        media.append(("photo", image.group(1)))

    return media


# =========================
# START COMMAND
# =========================

@bot.message_handler(commands=["start"])
def start(m):

    bot.send_message(
        m.chat.id,
        "Send Instagram username"
    )


# =========================
# USERNAME HANDLER
# =========================

@bot.message_handler(func=lambda m: True)
def handle_user(m):

    username = m.text.strip().lower()

    bot.send_message(m.chat.id, "Fetching posts...")

    posts = get_user_posts(username)

    if not posts:
        bot.send_message(m.chat.id, "No posts found or profile private")
        return

    for post in posts[:10]:

        medias = get_media(post)

        if not medias:
            bot.send_message(m.chat.id, post)
            continue

        for media_type, url in medias:

            try:

                if media_type == "video":

                    bot.send_video(
                        m.chat.id,
                        url,
                        caption="Downloaded via bot"
                    )

                else:

                    bot.send_photo(
                        m.chat.id,
                        url,
                        caption="Downloaded via bot"
                    )

                time.sleep(random.uniform(1,2))

            except:

                bot.send_message(m.chat.id, post)


# =========================
# RUN BOT
# =========================

print("Bot running...")

bot.infinity_polling()
