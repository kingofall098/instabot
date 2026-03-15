#USERNAM TO MEDIA INSTA BOT(OG)
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from playwright.sync_api import sync_playwright
import threading
import requests
import datetime
import time
import random
import re
import json
from io import BytesIO
from queue import Queue
import instaloader
# =========================
# BOT TOKEN
# =========================

TOKEN = "8665521420:AAHi0hfMNn3odVDCd9ajMCW_8FwrSz2OQLQ"
bot = telebot.TeleBot(TOKEN, threaded=True)
from queue import Queue

job_queue = Queue()
# =========================
# INSTAGRAM SESSION
# =========================

# IG_SESSIONID = "45575449095%3APTeNL8atjbF3Xs%3A9%3AAYhrp2AO-1Qn_PzdwHGe5QXpaBpzTh6oWBakuGsjlQ"

# =========================
# JOB SYSTEM

# =========================
# LOG FUNCTION
# =========================



def log(msg):
    t = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{t}] {msg}")
    
# SESSION FUNCTION
def load_session_from_cookie():

    with open("cookies.txt", "r") as f:

        for line in f:

            if "sessionid" not in line:
                continue

            parts = line.strip().split("\t")

            if len(parts) >= 7 and parts[-2] == "sessionid":

                session = parts[-1]

                log(f"Loaded session: {session[:20]}...")
                return session

    raise Exception("sessionid not found in cookies.txt")
import os
print("Files in project:", os.listdir())
IG_SESSIONID = load_session_from_cookie()
# =========================
# INSTALOADER
# =========================

L = instaloader.Instaloader(
    download_pictures=False,
    download_videos=False,
    download_video_thumbnails=False,
    save_metadata=False
)

L.context._session.cookies.set(
    "sessionid",
    IG_SESSIONID,
    domain=".instagram.com"
)
print("Instaloader session active")
# =========================
# START PLAYWRIGHT
# =========================

print("Starting browser...")

def get_profile_posts(username, limit=100):

    posts = []

    profile = instaloader.Profile.from_username(
        L.context,
        username
    )

    for post in profile.get_posts():

        posts.append(post)

        if len(posts) >= limit:
            break

    log(f"Collected {len(posts)} posts using Instaloader")

    return posts
def extract_media(post):

    items = []

    # carousel
    if post.typename == "GraphSidecar":

        for node in post.get_sidecar_nodes():

            if node.is_video:
                items.append(("video", node.video_url))
            else:
                items.append(("photo", node.display_url))

    # single video
    elif post.is_video:

        items.append(("video", post.video_url))

    # single image
    else:

        items.append(("photo", post.url))

    return items

def get_post_from_url(post_url):

    try:

        shortcode = post_url.split("/p/")[1].split("/")[0]

        post = instaloader.Post.from_shortcode(
            L.context,
            shortcode
        )

        return post

    except Exception as e:

        log(f"Instaloader error: {e}")
        return None
# =========================
# SCRAPER
# =========================

def scrape_background(job, context):
    username = job.username
    log(f"Scraping started for {username}")

    try:

        page = context.new_page()

        url = f"https://www.instagram.com/{username}/"

        delay = random.uniform(4,7)
        time.sleep(delay)

        page.goto(url, wait_until="domcontentloaded")

        time.sleep(5)

        log(f"Current URL: {page.url}")
        if "challenge" in page.url:
            log("Instagram triggered a security challenge. Session is blocked.")
            page.close()
            return

        if "accounts/login" in page.url:
            log("Session expired. Instagram requires login.")
            page.close()
            return
        # wait until page loads
        page.wait_for_load_state("networkidle")

        # small delay for JS rendering
        time.sleep(3)

        # scroll once to trigger posts loading
        page.evaluate("""
        window.scrollBy({
            top: 800,
            left: 0,
            behavior: 'smooth'
        });
        """)
        time.sleep(random.uniform(4,6))

        for _ in range(20):

            if not job.running:
                break
            log("Scanning page for posts...")
            links = page.evaluate("""
                Array.from(document.querySelectorAll('a'))
                    .map(a => a.href)
                    .filter(h => h.includes('/p/') || h.includes('/reel/'))
            """)

            new_posts = 0

            for link in links:
                link = link.split("?")[0]

                if link not in job.posts:
                    job.posts.append(link)
                    new_posts += 1

            log(f"Collected posts: {len(job.posts)} (+{new_posts})")

            page.evaluate("""
            window.scrollBy({
                top: 1200,
                left: 0,
                behavior: 'smooth'
            });
            """)

            time.sleep(3)

        page.close()

    except Exception as e:
        log(f"Scraper error: {e}")

    finally:
        try:
            page.close()
        except:
            pass

def playwright_worker():

    log("Starting browser in worker thread...")

    with sync_playwright() as play:

        browser = play.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage"
            ]
        )

        context = browser.new_context()

        context.add_cookies([{
            "name": "sessionid",
            "value": IG_SESSIONID,
            "domain": ".instagram.com",
            "path": "/",
            "httpOnly": True,
            "secure": True,
            "sameSite": "None"
        }])

        page = context.new_page()
        page.goto("https://www.instagram.com/")

        log("Instagram session activated")

        while True:

            job = job_queue.get()

            if job is None:
                break

            try:
                scrape_background(job, context)
            except Exception as e:
                log(f"Worker error: {e}")

            job_queue.task_done()
# =========================
# MEDIA FETCH
# =========================
# def fetch_media(post_url):

#     try:

#         headers = {
#             "User-Agent": "Mozilla/5.0",
#             "Accept-Language": "en-US,en;q=0.9"
#         }

#         r = requests.get(post_url, headers=headers, timeout=15)
#         html = r.text

#         items = []

#         # Extract JSON block
#         data_match = re.search(r'window\._sharedData = (.*?);</script>', html)

#         if not data_match:
#             return items

#         data = json.loads(data_match.group(1))

#         media = data["entry_data"]["PostPage"][0]["graphql"]["shortcode_media"]

#         # VIDEO
#         if media["is_video"]:
#             items.append(("video", media["video_url"]))

#         # SINGLE IMAGE
#         elif "display_url" in media:
#             items.append(("photo", media["display_url"]))

#         # CAROUSEL
#         if "edge_sidecar_to_children" in media:

#             edges = media["edge_sidecar_to_children"]["edges"]

#             for edge in edges:

#                 node = edge["node"]

#                 if node["is_video"]:
#                     items.append(("video", node["video_url"]))
#                 else:
#                     items.append(("photo", node["display_url"]))

#         return items

#     except Exception as e:

#         log(f"Media error: {e}")
#         return []
# =========================
# START COMMAND
# =========================

@bot.message_handler(commands=["start"])
def start(message):

    bot.send_message(
        message.chat.id,
        "Send Instagram username"
    )
class Job:
    def __init__(self, username):
        self.username = username
        self.posts = []
        self.sent = 0
        self.running = True
user_jobs ={}
job_queue = Queue()
# =========================
# USERNAME HANDLER
# =========================

@bot.message_handler(func=lambda m: True)
def profile_handler(message):

    username = message.text.strip().lower()

    job = Job(username)
    user_jobs[message.chat.id] = job

    # start scraper in background
    job_queue.put(job)

    markup = InlineKeyboardMarkup()

    markup.add(
        InlineKeyboardButton("Download 10 Posts", callback_data="next"),
        InlineKeyboardButton("Cancel", callback_data="cancel")
    )

    bot.send_message(
        message.chat.id,
        "Scraping started.\nPress download to receive posts.",
        reply_markup=markup
    )

# =========================
# CANCEL
# =========================

@bot.callback_query_handler(func=lambda call: call.data == "cancel")
def cancel(call):

    job = user_jobs.get(call.message.chat.id)

    if job:
        job.running = False

    bot.send_message(call.message.chat.id,"Scraping stopped.")

# =========================
# SEND POSTS
# =========================
@bot.callback_query_handler(func=lambda call: call.data == "next")
def send_next(call):

    job = user_jobs.get(call.message.chat.id)

    if not job:
        bot.send_message(call.message.chat.id, "No active job")
        return

    start = job.sent
    end = start + 10
    posts = job.posts[start:end]
    bot.send_message(call.message.chat.id, "Downloading media...")

    # if not posts:
    #     bot.send_message(call.message.chat.id, "Still collecting posts...")
    #     return

    from io import BytesIO
    from PIL import Image

    for post_url in posts:

        log(f"Processing: {post_url}")

        post = get_post_from_url(post_url)

        if not post:
            bot.send_message(call.message.chat.id, post_url)
            continue

        medias = extract_media(post)

        for media_type, media_url in medias:

            log(f"Checking post: {post}")
            log(f"Media type: {media_type}")
            log(f"Media URL: {media_url}")

            if not media_url:
                bot.send_message(call.message.chat.id, post)
                continue

            media_url = media_url.replace("&amp;", "&")
            media_url = media_url.replace(".heic", ".jpg")

            log(f"Final media URL: {media_url}")

            try:

                response = requests.get(media_url, timeout=30, stream=True)

                if response.status_code != 200:
                    raise Exception("Media download failed")

                file = BytesIO(response.content)

                if media_type == "video":

                    file.name = "video.mp4"

                    bot.send_video(
                        call.message.chat.id,
                        file,
                        width=720,
                        height=1280,
                        supports_streaming=True
                    )

                else:

                    img = Image.open(file).convert("RGB")

                    jpeg = BytesIO()
                    img.save(jpeg, format="JPEG")
                    jpeg.seek(0)

                    bot.send_photo(
                        call.message.chat.id,
                        jpeg,
                    )

            except Exception as e:

                log(f"Telegram error: {e}")
                bot.send_message(call.message.chat.id, post)

            time.sleep(random.uniform(1.5, 3))

    job.sent += len(posts)

    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("Next 10", callback_data="next"),
        InlineKeyboardButton("Cancel", callback_data="cancel")
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

# start playwright worker
threading.Thread(
    target=playwright_worker,
    daemon=True
).start()

bot.infinity_polling()
