import telebot
import requests
import time
import random
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

TOKEN = "8755937047:AAHBFaKCan-W8QLls2DDJ3-XpUdyw3tP16w"

bot = telebot.TeleBot(TOKEN)

def load_session():
    text = open("cookies.txt").read()

    for line in text.splitlines():
        if "sessionid" in line and "\t" in line:
            return line.split("\t")[-1].strip()

    return text.strip()

SESSIONID = load_session()

print("Loaded session:", SESSIONID[:15], "...")

print("Loaded session:", SESSIONID[:10], "...")

# =========================
# JOB SYSTEM
# =========================

class Job:
    def __init__(self, posts):
        self.posts = posts
        self.sent = 0

user_jobs = {}

# =========================
# GET POSTS
# =========================
import requests

def get_user_posts(username):

    print("\n=== FETCHING PROFILE ===")
    print("Username:", username)

    url = "https://www.instagram.com/graphql/query/"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "X-IG-App-ID": "936619743392459",
        "Accept": "*/*",
        "Referer": f"https://www.instagram.com/{username}/"
    }

    params = {
        "doc_id": "8845758582119845",
        "variables": f'{{"username":"{username}","first":12}}'
    }

    r = requests.get(url, headers=headers, params=params)

    print("GraphQL status:", r.status_code)

    if r.status_code != 200:
        print("GraphQL request failed")
        return []

    data = r.json()

    print("Keys returned:", list(data.keys()))

    posts = []

    try:

        edges = data["data"]["user"]["edge_owner_to_timeline_media"]["edges"]

        print("Edges found:", len(edges))

        for edge in edges:

            shortcode = edge["node"]["shortcode"]

            post_url = f"https://www.instagram.com/p/{shortcode}/"

            posts.append(post_url)

    except Exception as e:

        print("Parsing error:", e)

    print("Collected posts:", len(posts))

    return posts
# =========================
# GET MEDIA
# =========================

def get_media(post_url):

    print("\nChecking post:", post_url)

    shortcode = post_url.split("/p/")[1].split("/")[0]

    url = f"https://i.instagram.com/api/v1/media/{shortcode}/info/"

    headers = {
        "User-Agent": "Mozilla/5.0",
        "x-ig-app-id": "936619743392459",
        "cookie": f"sessionid={SESSIONID}"
    }

    r = requests.get(url, headers=headers)

    print("Media API status:", r.status_code)

    media = []

    try:

        items = r.json()["items"]

        for item in items:

            if item.get("carousel_media"):

                print("Carousel detected")

                for c in item["carousel_media"]:

                    if c["media_type"] == 2:

                        media.append(("video", c["video_versions"][0]["url"]))

                    else:

                        media.append(("photo", c["image_versions2"]["candidates"][0]["url"]))

            else:

                if item["media_type"] == 2:

                    print("Video detected")

                    media.append(("video", item["video_versions"][0]["url"]))

                else:

                    print("Photo detected")

                    media.append(("photo", item["image_versions2"]["candidates"][0]["url"]))

    except Exception as e:

        print("Media parse error:", e)

    print("Media count:", len(media))

    return media


# =========================
# START COMMAND
# =========================

@bot.message_handler(commands=["start"])
def start(message):

    print("\nUser started bot:", message.chat.id)

    bot.send_message(message.chat.id, "Send Instagram username")


# =========================
# USERNAME HANDLER
# =========================

@bot.message_handler(func=lambda m: True)
def profile_handler(message):

    username = message.text.strip().lower()

    print("\n=== USER REQUEST ===")
    print("Chat ID:", message.chat.id)
    print("Requested username:", username)

    bot.send_message(message.chat.id, "Fetching posts...")

    posts = get_user_posts(username)

    if not posts:

        print("No posts found")

        bot.send_message(message.chat.id, "Profile private or no posts")

        return

    user_jobs[message.chat.id] = Job(posts)

    markup = InlineKeyboardMarkup()

    markup.add(
        InlineKeyboardButton("Download 10 Posts", callback_data="next")
    )

    bot.send_message(
        message.chat.id,
        f"Found {len(posts)} posts",
        reply_markup=markup
    )


# =========================
# SEND POSTS
# =========================

@bot.callback_query_handler(func=lambda call: call.data == "next")
def send_next(call):

    print("\n=== DOWNLOAD REQUEST ===")

    job = user_jobs.get(call.message.chat.id)

    if not job:

        print("No job found")

        bot.send_message(call.message.chat.id, "No active job")

        return

    start = job.sent
    end = start + 10

    posts = job.posts[start:end]

    print("Sending posts:", start, "to", end)

    if not posts:

        bot.send_message(call.message.chat.id, "No more posts")

        return

    for post in posts:

        medias = get_media(post)

        if not medias:

            bot.send_message(call.message.chat.id, post)
            continue

        for media_type, url in medias:

            print("Sending media:", media_type)

            try:

                if media_type == "video":

                    bot.send_video(call.message.chat.id, url)

                else:

                    bot.send_photo(call.message.chat.id, url)

                time.sleep(random.uniform(1,2))

            except Exception as e:

                print("Telegram error:", e)

                bot.send_message(call.message.chat.id, post)

    job.sent += len(posts)

    markup = InlineKeyboardMarkup()

    markup.add(
        InlineKeyboardButton("Next 10 Posts", callback_data="next")
    )

    bot.send_message(
        call.message.chat.id,
        f"Sent {job.sent} posts",
        reply_markup=markup
    )


# =========================
# RUN BOT
# =========================

print("Bot started")

bot.infinity_polling()
